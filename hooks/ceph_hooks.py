#!/usr/bin/env python3
#
# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import glob
import os
import shutil
import sys
import socket
import subprocess
import netifaces

sys.path.append('lib')
import ceph.utils as ceph
from charmhelpers.core import hookenv
from charmhelpers.core.hookenv import (
    log,
    DEBUG,
    ERROR,
    INFO,
    config,
    relation_ids,
    related_units,
    relation_get,
    relation_set,
    Hooks,
    UnregisteredHookError,
    service_name,
    status_get,
    status_set,
    storage_get,
    storage_list,
    application_version_set,
)
from charmhelpers.core.host import (
    umount,
    mkdir,
    cmp_pkgrevno,
    service_reload,
    service_restart,
    add_to_updatedb_prunepath,
    restart_on_change,
    write_file,
    is_container,
)
from charmhelpers.fetch import (
    add_source,
    apt_install,
    apt_update,
    filter_installed_packages,
    get_upstream_version,
)
from charmhelpers.core.sysctl import create as create_sysctl
from charmhelpers.contrib.openstack.context import (
    AppArmorContext,
)
from utils import (
    get_host_ip,
    get_networks,
    assert_charm_supports_ipv6,
    render_template,
    is_unit_paused_set,
    get_public_addr,
    get_cluster_addr,
    get_blacklist,
    get_journal_devices,
)
from charmhelpers.contrib.openstack.alternatives import install_alternative
from charmhelpers.contrib.network.ip import (
    get_ipv6_addr,
    format_ipv6_addr,
    get_relation_ip,
)
from charmhelpers.contrib.storage.linux.ceph import (
    CephConfContext)
from charmhelpers.contrib.storage.linux.utils import (
    is_device_mounted,
    is_block_device,
)
from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.hardening.harden import harden

from charmhelpers.core.unitdata import kv

import charmhelpers.contrib.openstack.vaultlocker as vaultlocker

hooks = Hooks()
STORAGE_MOUNT_PATH = '/var/lib/ceph'


def check_for_upgrade():
    if not os.path.exists(ceph._upgrade_keyring):
        log("Ceph upgrade keyring not detected, skipping upgrade checks.")
        return

    c = hookenv.config()
    old_version = ceph.resolve_ceph_version(c.previous('source') or
                                            'distro')
    log('old_version: {}'.format(old_version))
    new_version = ceph.resolve_ceph_version(hookenv.config('source') or
                                            'distro')
    log('new_version: {}'.format(new_version))

    # May be in a previous upgrade that was failed if the directories
    # still need an ownership update. Check this condition.
    resuming_upgrade = ceph.dirs_need_ownership_update('osd')

    if old_version == new_version and not resuming_upgrade:
        log("No new ceph version detected, skipping upgrade.", DEBUG)
        return

    if (ceph.UPGRADE_PATHS.get(old_version) == new_version) or\
       resuming_upgrade:
        if old_version == new_version:
            log('Attempting to resume possibly failed upgrade.',
                INFO)
        else:
            log("{} to {} is a valid upgrade path. Proceeding.".format(
                old_version, new_version))

        emit_cephconf(upgrading=True)
        ceph.roll_osd_cluster(new_version=new_version,
                              upgrade_key='osd-upgrade')
        emit_cephconf(upgrading=False)
    else:
        # Log a helpful error message
        log("Invalid upgrade path from {} to {}.  "
            "Valid paths are: {}".format(old_version,
                                         new_version,
                                         ceph.pretty_print_upgrade_paths()))


def tune_network_adapters():
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        if interface == "lo":
            # Skip the loopback
            continue
        log("Looking up {} for possible sysctl tuning.".format(interface))
        ceph.tune_nic(interface)


@restart_on_change({'/etc/apparmor.d/usr.bin.ceph-osd': ['apparmor']},
                   restart_functions={'apparmor': service_reload})
def copy_profile_into_place():
    """
    Copy the apparmor profiles included with the charm
    into the /etc/apparmor.d directory.
    """
    new_install = False
    apparmor_dir = os.path.join(os.sep,
                                'etc',
                                'apparmor.d')

    for x in glob.glob('files/apparmor/*'):
        if not os.path.exists(os.path.join(apparmor_dir,
                                           os.path.basename(x))):
            new_install = True
        shutil.copy(x, apparmor_dir)
    return new_install


class CephOsdAppArmorContext(AppArmorContext):
    """"Apparmor context for ceph-osd binary"""
    def __init__(self):
        super(CephOsdAppArmorContext, self).__init__()
        self.aa_profile = 'usr.bin.ceph-osd'

    def __call__(self):
        super(CephOsdAppArmorContext, self).__call__()
        if not self.ctxt:
            return self.ctxt
        self._ctxt.update({'aa_profile': self.aa_profile})
        return self.ctxt


def use_vaultlocker():
    """Determine whether vaultlocker should be used for OSD encryption

    :returns: whether vaultlocker should be used for key management
    :rtype: bool
    :raises: ValueError if vaultlocker is enable but ceph < 12.2.4"""
    if (config('osd-encrypt') and
            config('osd-encrypt-keymanager') == ceph.VAULT_KEY_MANAGER):
        if cmp_pkgrevno('ceph', '12.2.4') < 0:
            msg = ('vault usage only supported with ceph >= 12.2.4')
            status_set('blocked', msg)
            raise ValueError(msg)
        else:
            return True
    return False


def install_apparmor_profile():
    """
    Install ceph apparmor profiles and configure
    based on current setting of 'aa-profile-mode'
    configuration option.
    """
    log('Installing apparmor profile for ceph-osd')
    new_install = copy_profile_into_place()
    if new_install or config().changed('aa-profile-mode'):
        aa_context = CephOsdAppArmorContext()
        aa_context.setup_aa_profile()
        service_reload('apparmor')
        if ceph.systemd():
            for osd_id in ceph.get_local_osd_ids():
                service_restart('ceph-osd@{}'.format(osd_id))
        else:
            service_restart('ceph-osd-all')


def install_udev_rules():
    """
    Install and reload udev rules for ceph-volume LV
    permissions
    """
    if is_container():
        log('Skipping udev rule installation '
            'as unit is in a container', level=DEBUG)
        return
    for x in glob.glob('files/udev/*'):
        shutil.copy(x, '/lib/udev/rules.d')
    subprocess.check_call(['udevadm', 'control',
                           '--reload-rules'])


@hooks.hook('install.real')
@harden()
def install():
    add_source(config('source'), config('key'))
    apt_update(fatal=True)
    apt_install(packages=ceph.determine_packages(), fatal=True)
    if config('autotune'):
        tune_network_adapters()
    install_udev_rules()


def az_info():
    az_info = ""
    config_az = config("availability_zone")
    juju_az_info = os.environ.get('JUJU_AVAILABILITY_ZONE')
    if juju_az_info:
        # NOTE(jamespage): avoid conflicting key with root
        #                  of crush hierarchy
        if juju_az_info == 'default':
            juju_az_info = 'default-rack'
        az_info = "{} rack={}".format(az_info, juju_az_info)
    if config_az:
        # NOTE(jamespage): avoid conflicting key with root
        #                  of crush hierarchy
        if config_az == 'default':
            config_az = 'default-row'
        az_info = "{} row={}".format(az_info, config_az)
    if az_info != "":
        log("AZ Info: " + az_info)
        return az_info


def use_short_objects():
    '''
    Determine whether OSD's should be configured with
    limited object name lengths.

    @return: boolean indicating whether OSD's should be limited
    '''
    if cmp_pkgrevno('ceph', "10.2.0") >= 0:
        if config('osd-format') in ('ext4'):
            return True
        devices = config('osd-devices')
        if not devices:
            return False

        for device in devices.split():
            if device and not device.startswith('/dev'):
                # TODO: determine format of directory based
                #       OSD location
                return True
    return False


def get_ceph_context(upgrading=False):
    """Returns the current context dictionary for generating ceph.conf

    :param upgrading: bool - determines if the context is invoked as
                      part of an upgrade proedure Setting this to true
                      causes settings useful during an upgrade to be
                      defined in the ceph.conf file
    """
    mon_hosts = get_mon_hosts()
    log('Monitor hosts are ' + repr(mon_hosts))

    networks = get_networks('ceph-public-network')
    public_network = ', '.join(networks)

    networks = get_networks('ceph-cluster-network')
    cluster_network = ', '.join(networks)

    cephcontext = {
        'auth_supported': get_auth(),
        'mon_hosts': ' '.join(mon_hosts),
        'fsid': get_fsid(),
        'old_auth': cmp_pkgrevno('ceph', "0.51") < 0,
        'crush_initial_weight': config('crush-initial-weight'),
        'osd_journal_size': config('osd-journal-size'),
        'osd_max_backfills': config('osd-max-backfills'),
        'osd_recovery_max_active': config('osd-recovery-max-active'),
        'use_syslog': str(config('use-syslog')).lower(),
        'ceph_public_network': public_network,
        'ceph_cluster_network': cluster_network,
        'loglevel': config('loglevel'),
        'dio': str(config('use-direct-io')).lower(),
        'short_object_len': use_short_objects(),
        'upgrade_in_progress': upgrading,
        'bluestore': config('bluestore'),
        'bluestore_experimental': cmp_pkgrevno('ceph', '12.1.0') < 0,
        'bluestore_block_wal_size': config('bluestore-block-wal-size'),
        'bluestore_block_db_size': config('bluestore-block-db-size'),
    }

    if config('prefer-ipv6'):
        dynamic_ipv6_address = get_ipv6_addr()[0]
        if not public_network:
            cephcontext['public_addr'] = dynamic_ipv6_address
        if not cluster_network:
            cephcontext['cluster_addr'] = dynamic_ipv6_address
    else:
        cephcontext['public_addr'] = get_public_addr()
        cephcontext['cluster_addr'] = get_cluster_addr()

    if config('customize-failure-domain'):
        az = az_info()
        if az:
            cephcontext['crush_location'] = "root=default {} host={}" \
                .format(az, socket.gethostname())
        else:
            log(
                "Your Juju environment doesn't"
                "have support for Availability Zones"
            )

    # NOTE(dosaboy): these sections must correspond to what is supported in the
    #                config template.
    sections = ['global', 'osd']
    cephcontext.update(CephConfContext(permitted_sections=sections)())
    return cephcontext


def emit_cephconf(upgrading=False):
    # Install ceph.conf as an alternative to support
    # co-existence with other charms that write this file
    charm_ceph_conf = "/var/lib/charm/{}/ceph.conf".format(service_name())
    mkdir(os.path.dirname(charm_ceph_conf), owner=ceph.ceph_user(),
          group=ceph.ceph_user())
    with open(charm_ceph_conf, 'w') as cephconf:
        context = get_ceph_context(upgrading)
        cephconf.write(render_template('ceph.conf', context))
    install_alternative('ceph.conf', '/etc/ceph/ceph.conf',
                        charm_ceph_conf, 90)


@hooks.hook('config-changed')
@harden()
def config_changed():
    # Determine whether vaultlocker is required and install
    if use_vaultlocker():
        installed = len(filter_installed_packages(['vaultlocker'])) == 0
        if not installed:
            add_source('ppa:openstack-charmers/vaultlocker')
            apt_update(fatal=True)
            apt_install('vaultlocker', fatal=True)

    # Check if an upgrade was requested
    check_for_upgrade()

    # Pre-flight checks
    if config('osd-format') not in ceph.DISK_FORMATS:
        log('Invalid OSD disk format configuration specified', level=ERROR)
        sys.exit(1)

    if config('prefer-ipv6'):
        assert_charm_supports_ipv6()

    sysctl_dict = config('sysctl')
    if sysctl_dict:
        create_sysctl(sysctl_dict, '/etc/sysctl.d/50-ceph-osd-charm.conf')

    e_mountpoint = config('ephemeral-unmount')
    if e_mountpoint and ceph.filesystem_mounted(e_mountpoint):
        umount(e_mountpoint)
    prepare_disks_and_activate()
    install_apparmor_profile()
    add_to_updatedb_prunepath(STORAGE_MOUNT_PATH)


@hooks.hook('storage.real')
def prepare_disks_and_activate():
    # NOTE: vault/vaultlocker preflight check
    vault_kv = vaultlocker.VaultKVContext(vaultlocker.VAULTLOCKER_BACKEND)
    context = vault_kv()
    if use_vaultlocker() and not vault_kv.complete:
        log('Deferring OSD preparation as vault not ready',
            level=DEBUG)
        return
    elif use_vaultlocker() and vault_kv.complete:
        log('Vault ready, writing vaultlocker configuration',
            level=DEBUG)
        vaultlocker.write_vaultlocker_conf(context)

    osd_journal = get_journal_devices()
    if not osd_journal.isdisjoint(set(get_devices())):
        raise ValueError('`osd-journal` and `osd-devices` options must not'
                         'overlap.')
    log("got journal devs: {}".format(osd_journal), level=DEBUG)

    # pre-flight check of eligible device pristinity
    devices = get_devices()

    # if a device has been previously touched we need to consider it as
    # non-pristine. If it needs to be re-processed it has to be zapped
    # via the respective action which also clears the unitdata entry.
    db = kv()
    touched_devices = db.get('osd-devices', [])
    devices = [dev for dev in devices if dev not in touched_devices]
    log('Skipping osd devices previously processed by this unit: {}'
        .format(touched_devices))
    # filter osd-devices that are file system paths
    devices = [dev for dev in devices if dev.startswith('/dev')]
    # filter osd-devices that does not exist on this unit
    devices = [dev for dev in devices if os.path.exists(dev)]
    # filter osd-devices that are already mounted
    devices = [dev for dev in devices if not is_device_mounted(dev)]
    # filter osd-devices that are active bluestore devices
    devices = [dev for dev in devices
               if not ceph.is_active_bluestore_device(dev)]

    log('Checking for pristine devices: "{}"'.format(devices), level=DEBUG)
    if not all(ceph.is_pristine_disk(dev) for dev in devices):
        status_set('blocked',
                   'Non-pristine devices detected, consult '
                   '`list-disks`, `zap-disk` and `blacklist-*` actions.')
        return

    if ceph.is_bootstrapped():
        log('ceph bootstrapped, rescanning disks')
        emit_cephconf()
        for dev in get_devices():
            ceph.osdize(dev, config('osd-format'),
                        osd_journal,
                        config('ignore-device-errors'),
                        config('osd-encrypt'),
                        config('bluestore'),
                        config('osd-encrypt-keymanager'))
            # Make it fast!
            if config('autotune'):
                ceph.tune_dev(dev)
        ceph.start_osds(get_devices())


def get_mon_hosts():
    hosts = []
    for relid in relation_ids('mon'):
        for unit in related_units(relid):
            addr = \
                relation_get('ceph-public-address',
                             unit,
                             relid) or get_host_ip(
                    relation_get(
                        'private-address',
                        unit,
                        relid))

            if addr:
                hosts.append('{}:6789'.format(format_ipv6_addr(addr) or addr))

    return sorted(hosts)


def get_fsid():
    return get_conf('fsid')


def get_auth():
    return get_conf('auth')


def get_conf(name):
    for relid in relation_ids('mon'):
        for unit in related_units(relid):
            conf = relation_get(name,
                                unit, relid)
            if conf:
                return conf
    return None


def get_devices():
    devices = []
    if config('osd-devices'):
        for path in config('osd-devices').split(' '):
            path = path.strip()
            # Ensure that only block devices
            # are considered for evaluation as block devices.
            # This avoids issues with relative directories
            # being passed via configuration, and ensures that
            # the path to a block device provided by the user
            # is used, rather than its target which may change
            # between reboots in the case of bcache devices.
            if is_block_device(path):
                devices.append(path)
            # Make sure its a device which is specified using an
            # absolute path so that the current working directory
            # or any relative path under this directory is not used
            elif os.path.isabs(path):
                devices.append(os.path.realpath(path))

    # List storage instances for the 'osd-devices'
    # store declared for this charm too, and add
    # their block device paths to the list.
    storage_ids = storage_list('osd-devices')
    devices.extend((storage_get('location', s) for s in storage_ids))

    # Filter out any devices in the action managed unit-local device blacklist
    _blacklist = get_blacklist()
    return [device for device in devices if device not in _blacklist]


@hooks.hook('mon-relation-changed',
            'mon-relation-departed')
def mon_relation():
    bootstrap_key = relation_get('osd_bootstrap_key')
    upgrade_key = relation_get('osd_upgrade_key')
    if get_fsid() and get_auth() and bootstrap_key:
        log('mon has provided conf- scanning disks')
        emit_cephconf()
        ceph.import_osd_bootstrap_key(bootstrap_key)
        ceph.import_osd_upgrade_key(upgrade_key)
        prepare_disks_and_activate()
    else:
        log('mon cluster has not yet provided conf')


@hooks.hook('upgrade-charm.real')
@harden()
def upgrade_charm():
    if get_fsid() and get_auth():
        emit_cephconf()
    apt_install(packages=filter_installed_packages(ceph.determine_packages()),
                fatal=True)
    install_udev_rules()
    remap_resolved_targets()


def remap_resolved_targets():
    '''Remap any previous fully resolved target devices to provided names'''
    # NOTE(jamespage): Deal with any prior provided dev to
    # target device resolution which occurred in prior
    # releases of the charm - the user provided value
    # should be used in preference to the target path
    # to the block device as in some instances this
    # is not consistent between reboots (bcache).
    db = kv()
    touched_devices = db.get('osd-devices', [])
    osd_devices = get_devices()
    for dev in osd_devices:
        real_path = os.path.realpath(dev)
        if real_path != dev and real_path in touched_devices:
            log('Device {} already processed by charm using '
                'actual device path {}, updating block device '
                'usage with provided device path '
                'and skipping'.format(dev,
                                      real_path))
            touched_devices.remove(real_path)
            touched_devices.append(dev)
    db.set('osd-devices', touched_devices)
    db.flush()


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    apt_install('python3-dbus')
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)
    nrpe_setup.add_check(
        shortname='ceph-osd',
        description='process check {%s}' % current_unit,
        check_cmd=('/bin/cat /var/lib/ceph/osd/ceph-*/whoami |'
                   'xargs -I@ status ceph-osd id=@ && exit 0 || exit 2')
    )
    nrpe_setup.write()


@hooks.hook('secrets-storage-relation-joined')
def secrets_storage_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 secret_backend='charm-vaultlocker',
                 isolated=True,
                 access_address=get_relation_ip('secrets-storage'),
                 hostname=socket.gethostname())


@hooks.hook('secrets-storage-relation-changed')
def secrets_storage_changed():
    vault_ca = relation_get('vault_ca')
    if vault_ca:
        vault_ca = base64.decodestring(json.loads(vault_ca).encode())
        write_file('/usr/local/share/ca-certificates/vault-ca.crt',
                   vault_ca, perms=0o644)
        subprocess.check_call(['update-ca-certificates', '--fresh'])
    prepare_disks_and_activate()


VERSION_PACKAGE = 'ceph-common'


def assess_status():
    """Assess status of current unit"""
    # check to see if the unit is paused.
    application_version_set(get_upstream_version(VERSION_PACKAGE))
    if is_unit_paused_set():
        status_set('maintenance',
                   "Paused. Use 'resume' action to resume normal service.")
        return
    # Check for mon relation
    if len(relation_ids('mon')) < 1:
        status_set('blocked', 'Missing relation: monitor')
        return

    # Check for monitors with presented addresses
    # Check for bootstrap key presentation
    monitors = get_mon_hosts()
    if len(monitors) < 1 or not get_conf('osd_bootstrap_key'):
        status_set('waiting', 'Incomplete relation: monitor')
        return

    # Check for vault
    if use_vaultlocker():
        if not relation_ids('secrets-storage'):
            status_set('blocked', 'Missing relation: vault')
            return
        if not vaultlocker.vault_relation_complete():
            status_set('waiting', 'Incomplete relation: vault')
            return

    # Check for OSD device creation parity i.e. at least some devices
    # must have been presented and used for this charm to be operational
    (prev_status, prev_message) = status_get()
    running_osds = ceph.get_running_osds()
    if not prev_message.startswith('Non-pristine'):
        if not running_osds:
            status_set('blocked',
                       'No block devices detected using current configuration')
        else:
            status_set('active',
                       'Unit is ready ({} OSD)'.format(len(running_osds)))


@hooks.hook('update-status')
@harden()
def update_status():
    log('Updating status.')


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status()
