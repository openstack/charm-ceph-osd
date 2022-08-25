#!/usr/bin/env python3
#
# Copyright 2021 Canonical Ltd
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

import datetime
import errno
import json
from math import ceil
import os
import subprocess
import sys
import time

sys.path.append('lib')
sys.path.append('hooks')

import charmhelpers.core.hookenv as hookenv
from charmhelpers.core.hookenv import function_fail

import charms_ceph.utils
from charmhelpers.core.unitdata import kv
from utils import (get_bcache_names, bcache_remove, device_size,
                   get_parent_device, remove_lvm, wipefs_safely)


def normalize_osd_id(osd_id):
    """Make sure an OSD id has the form 'osd.<number>'.

    :param osd_id: The OSD id, either a string or the integer ID.
    :type osd_id: Option[int, str]

    :returns: A string with the form 'osd.<number>.
    :rtype: str
    """
    if not isinstance(osd_id, str) or not osd_id.startswith('osd.'):
        osd_id = 'osd.' + str(osd_id)
    return osd_id


def get_device_map():
    """Get a list of osd.id, device-path for every device that
       is being used by local OSD.

    :returns: A list of OSD ids and devices.
    :rtype: list[dict['id', 'path']]
    """
    ret = []
    vlist = subprocess.check_output(['ceph-volume', 'lvm', 'list',
                                     '--format=json'])
    for osd_id, data in json.loads(vlist.decode('utf8')).items():
        osd_id = normalize_osd_id(osd_id)
        for elem in data:
            for device in elem['devices']:
                ret.append({'id': osd_id, 'path': device})
    return ret


def map_device_to_id(dev_map, device):
    """Get the OSD id for a device or bcache name.

    :param dev_map: A map with the same form as that returned by
        the function 'get_device_map'.
    :type dev_map: list[dict['id', 'path']]

    :param device: The path to the device.
    :type device: str

    :returns: The OSD id in use by the device, if any.
    :rtype: Option[None, str]
    """
    for elem in dev_map:
        if device == elem['path']:
            return elem['id']


def map_id_to_device(dev_map, osd_id):
    """Get the device path for an OSD id.

    :param dev_map: A map with the same form as that returned by
        the function 'get_device_map'.
    :type dev_map: list[dict['id', 'path']]

    :param osd_id: The OSD id to check against.
    :type osd_id: str

    :returns: The device path being used by the OSD id, if any.
    :rtype: Option[None, str]
    """
    for elem in dev_map:
        if elem['id'] == osd_id:
            return elem['path']


def safe_to_destroy(osd_id):
    """Test whether an OSD id is safe to destroy per the Ceph cluster."""
    ret = subprocess.call(['ceph', '--id', 'osd-removal',
                           'osd', 'safe-to-destroy', osd_id])
    return ret == 0


def safe_to_stop(osd_id):
    """Test whether an OSD is safe to stop."""
    ret = subprocess.call(['ceph', '--id', 'osd-removal',
                           'osd', 'ok-to-stop', osd_id])
    return ret == 0


def reweight_osd(osd_id):
    """Set the weight of the OSD id to zero."""
    subprocess.check_call(['ceph', '--id', 'osd-removal',
                           'osd', 'crush', 'reweight', osd_id, '0'])


def destroy(osd_id, purge=False):
    """Destroy or purge an OSD id."""
    for _ in range(10):
        # We might get here before the OSD is marked as down. As such,
        # retry if the error code is EBUSY.
        try:
            subprocess.check_call(['ceph', '--id', 'osd-removal', 'osd',
                                   'purge' if purge else 'destroy',
                                   osd_id, '--yes-i-really-mean-it'])
            return
        except subprocess.CalledProcessError as e:
            if e.returncode != errno.EBUSY:
                raise
            time.sleep(0.1)


class RemoveException(Exception):
    """Exception type used to notify of errors for this action."""
    pass


class ActionOSD:

    """Class used to encapsulate all the needed information to
    perform OSD removal."""

    def __init__(self, dev_map, dev=None, osd_id=None, aliases={}):
        """Construct an action-OSD.

        :param dev_map: A map with the same form as that returned by
            the function 'get_device_map'.
        :type dev_map: list[dict['id', 'path']]

        :param dev: The device being used by an OSD.
        :type dev: Option[None, str]

        :param osd_id: The OSD id.
        :type osd_id: Option[None, int, str]
        """
        if dev is not None:
            if osd_id is not None:
                raise RemoveException(
                    'osd-ids and osd-devices are mutually exclusive')
            elif dev in aliases:
                self.alias = dev
                self.device = aliases.get(dev)
            else:
                self.device, self.alias = dev, None

            self.osd_id = map_device_to_id(dev_map, self.device)
            self.bcache_backing, self.bcache_caching = \
                get_bcache_names(self.device)
            if self.osd_id is None:
                raise RemoveException('Device {} is not being used'
                                      .format(self.device))
        else:
            self.alias = None
            self.osd_id = normalize_osd_id(osd_id)
            self.device = map_id_to_device(dev_map, self.osd_id)
            if self.device is None:
                raise RemoveException('Invalid osd ID: {}'.format(self.osd_id))

            self.bcache_backing, self.bcache_caching = \
                get_bcache_names(self.device)

        self.report = {}   # maps device -> actions.

    @property
    def osd_device(self):
        return self.bcache_backing or self.device

    def remove(self, purge, timeout, force):
        """Remove the OSD from the cluster.

        :param purge: Whether to purge or just destroy the OSD.
        :type purge: bool

        :param timeout: The number of minutes to wait for until the OSD
            is safe to destroy.
        :type timeout: int

        :param force: Whether to proceed with OSD removal, even when
            it's not safe to do so.
        :type force: bool
        """
        # Set the CRUSH weight to 0.
        hookenv.log('Reweighting OSD', hookenv.DEBUG)
        reweight_osd(self.osd_id)

        # Ensure that the OSD is safe to stop and destroy.
        end = (datetime.datetime.now() +
               datetime.timedelta(seconds=timeout * 60))
        safe_stop, safe_destroy = False, False

        while True:
            if not safe_stop and safe_to_stop(self.osd_id):
                safe_stop = True
            if not safe_destroy and safe_to_destroy(self.osd_id):
                safe_destroy = True

            if safe_stop and safe_destroy:
                break

            curr = datetime.datetime.now()
            if curr >= end:
                if force:
                    hookenv.log(
                        'OSD not safe to destroy, but "force" was specified',
                        hookenv.DEBUG)
                    break

                raise RemoveException(
                    'timed out waiting for an OSD to be safe to destroy')
            time.sleep(min(1, (end - curr).total_seconds()))

        # Stop the OSD service.
        hookenv.log('Stopping the OSD service', hookenv.DEBUG)
        charms_ceph.utils.stop_osd(self.osd_id[4:])
        charms_ceph.utils.disable_osd(self.osd_id[4:])
        unit_filename = \
            '/run/systemd/system/ceph-osd.target.wants/ceph-osd@{}.service' \
            .format(self.osd_id[4:])
        if os.path.exists(unit_filename):
            os.remove(unit_filename)

        subprocess.check_call(['systemctl', 'daemon-reload'])

        # Remove the OSD from the cluster.
        hookenv.log('Destroying the OSD', hookenv.DEBUG)
        destroy(self.osd_id, purge)
        report = self.report.setdefault(self.osd_device,
                                        {'osd-ids': self.osd_id})

        if self.bcache_backing:
            # Remove anything related to bcache.
            size = int(ceil(device_size(self.bcache_caching)))
            caching = get_parent_device(self.bcache_caching)
            report.update({'cache-devices': caching, 'partition-size': size})
            bcache_remove(self.device, self.bcache_backing,
                          self.bcache_caching)
        else:
            remove_lvm(self.device)
            wipefs_safely(self.device)


def make_same_length(l1, l2):
    """Make sure 2 lists have the same length, padding out with None's."""
    ln = max(len(l1), len(l2))
    l1.extend([None] * (ln - len(l1)))
    l2.extend([None] * (ln - len(l2)))


def write_report(report, ftype):
    """Generate a report on how to re-established the removed disks
    to be part of the cluster again, then set the 'message' attribute to
    either a JSON object or a textual representation.

    :param report: The initial, raw report from the 'ActionOSD' objects.
    :type report: dict

    :param ftype: Either 'text' or 'json'; specifies the type of report
    :type ftype: Enum['text', 'json']
    """
    if ftype == 'text':
        msg = '{} disks have been removed\n'.format(len(report))
        msg += 'To replace them, run:\n'
        for device, action_args in report.items():
            args = json.dumps(action_args, separators=(' ', '='))
            args = args.replace('{', '').replace('}', '').replace('"', '')
            msg += 'juju run-action {} add-disk {} {}'.format(
                hookenv.local_unit(), 'osd-devices=' + device, args)
    else:
        msg = json.dumps(report)

    hookenv.action_set({'message': msg})


def get_list(key):
    """Retrieve the action arguments based on the key as a list."""
    ret = hookenv.action_get(key)
    return ret.split() if ret else []


def advertise_osd_count(count):
    """Let the Ceph-mon know of the updated OSD number."""
    for relid in hookenv.relation_ids('mon'):
        hookenv.relation_set(
            relation_id=relid,
            relation_settings={'bootstrapped-osds': count}
        )


def main():
    osd_ids = get_list('osd-ids')
    osd_devs = get_list('osd-devices')
    purge = hookenv.action_get('purge')
    force = hookenv.action_get('force')
    timeout = hookenv.action_get('timeout')

    if timeout <= 0:
        function_fail('timeout must be > 0')
        sys.exit(1)
    elif not osd_ids and not osd_devs:
        function_fail('One of osd-ids or osd-devices must be provided')
        sys.exit(1)

    make_same_length(osd_ids, osd_devs)
    errors = []
    report = {}
    dev_map = get_device_map()
    charm_devices = kv().get('osd-devices', [])
    aliases = kv().get('osd-aliases', {})

    for dev, osd_id in zip(osd_devs, osd_ids):
        try:
            action_osd = ActionOSD(dev_map, dev=dev, osd_id=osd_id,
                                   aliases=aliases)
            if action_osd.device not in charm_devices:
                errors.append('Device {} not being used by Ceph'
                              .format(action_osd.device))
                continue
            action_osd.remove(purge, timeout, force)
            charm_devices.remove(action_osd.device)
            if action_osd.alias:
                aliases.pop(action_osd.alias)
            report.update(action_osd.report)
        except RemoveException as e:
            errors.append(str(e))

    kv().set('osd-devices', charm_devices)
    kv().set('osd-aliases', aliases)
    kv().flush()
    advertise_osd_count(len(charm_devices))
    write_report(report, hookenv.action_get('format'))

    if errors:
        function_fail('Failed to remove devices: {}'.format(','.join(errors)))
        sys.exit(1)


if __name__ == '__main__':
    main()
