#!/usr/bin/env python
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

import amulet
import time
from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)
from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)


class CephOsdBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic ceph-osd deployment."""

    def __init__(self, series=None, openstack=None, source=None,
                 stable=True):
        """Deploy the entire test environment."""
        super(CephOsdBasicDeployment, self).__init__(series, openstack,
                                                     source, stable)
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        exclude_services = []

        # Wait for deployment ready msgs, except exclusions
        self._auto_wait_for_status(exclude_services=exclude_services)

        self.d.sentry.wait()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where ceph-osd is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'ceph-osd', 'units': 3}
        other_services = [
            {'name': 'ceph-mon', 'units': 3},
            {'name': 'percona-cluster'},
            {'name': 'keystone'},
            {'name': 'rabbitmq-server'},
            {'name': 'nova-compute'},
            {'name': 'glance'},
            {'name': 'cinder'},
            {'name': 'cinder-ceph'},
        ]
        super(CephOsdBasicDeployment, self)._add_services(this_service,
                                                          other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'nova-compute:shared-db': 'percona-cluster:shared-db',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'nova-compute:image-service': 'glance:image-service',
            'nova-compute:ceph': 'ceph-mon:client',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:amqp': 'rabbitmq-server:amqp',
            'glance:ceph': 'ceph-mon:client',
            'cinder:shared-db': 'percona-cluster:shared-db',
            'cinder:identity-service': 'keystone:identity-service',
            'cinder:amqp': 'rabbitmq-server:amqp',
            'cinder:image-service': 'glance:image-service',
            'cinder-ceph:storage-backend': 'cinder:storage-backend',
            'cinder-ceph:ceph': 'ceph-mon:client',
            'ceph-osd:mon': 'ceph-mon:osd',
        }
        super(CephOsdBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        keystone_config = {'admin-password': 'openstack',
                           'admin-token': 'ubuntutesting'}
        pxc_config = {
            'max-connections': 1000,
        }

        cinder_config = {'block-device': 'None', 'glance-api-version': '2'}
        ceph_config = {
            'monitor-count': '3',
            'auth-supported': 'none',
            'fsid': '6547bd3e-1397-11e2-82e5-53567c8d32dc',
            'monitor-secret': 'AQCXrnZQwI7KGBAAiPofmKEXKxu5bUzoYLVkbQ==',
        }

        # Include a non-existent device as osd-devices is a whitelist,
        # and this will catch cases where proposals attempt to change that.
        ceph_osd_config = {
            'osd-reformat': 'yes',
            'ephemeral-unmount': '/mnt',
            'osd-devices': '/dev/vdb /srv/ceph /dev/test-non-existent'
        }

        configs = {'keystone': keystone_config,
                   'percona-cluster': pxc_config,
                   'cinder': cinder_config,
                   'ceph-mon': ceph_config,
                   'ceph-osd': ceph_osd_config}
        super(CephOsdBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.nova_sentry = self.d.sentry['nova-compute'][0]
        self.glance_sentry = self.d.sentry['glance'][0]
        self.cinder_sentry = self.d.sentry['cinder'][0]
        self.ceph0_sentry = self.d.sentry['ceph-mon'][0]
        self.ceph1_sentry = self.d.sentry['ceph-mon'][1]
        self.ceph2_sentry = self.d.sentry['ceph-mon'][2]
        self.ceph_osd_sentry = self.d.sentry['ceph-osd'][0]
        self.ceph_osd1_sentry = self.d.sentry['ceph-osd'][1]
        self.ceph_osd2_sentry = self.d.sentry['ceph-osd'][2]
        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate admin with keystone
        self.keystone = u.authenticate_keystone_admin(self.keystone_sentry,
                                                      user='admin',
                                                      password='openstack',
                                                      tenant='admin')

        # Authenticate admin with cinder endpoint
        self.cinder = u.authenticate_cinder_admin(self.keystone_sentry,
                                                  username='admin',
                                                  password='openstack',
                                                  tenant='admin')
        # Authenticate admin with glance endpoint
        self.glance = u.authenticate_glance_admin(self.keystone)

        # Authenticate admin with nova endpoint
        self.nova = u.authenticate_nova_user(self.keystone,
                                             user='admin',
                                             password='openstack',
                                             tenant='admin')

        # Create a demo tenant/role/user
        self.demo_tenant = 'demoTenant'
        self.demo_role = 'demoRole'
        self.demo_user = 'demoUser'
        if not u.tenant_exists(self.keystone, self.demo_tenant):
            tenant = self.keystone.tenants.create(tenant_name=self.demo_tenant,
                                                  description='demo tenant',
                                                  enabled=True)
            self.keystone.roles.create(name=self.demo_role)
            self.keystone.users.create(name=self.demo_user,
                                       password='password',
                                       tenant_id=tenant.id,
                                       email='demo@demo.com')

        # Authenticate demo user with keystone
        self.keystone_demo = u.authenticate_keystone_user(self.keystone,
                                                          self.demo_user,
                                                          'password',
                                                          self.demo_tenant)

        # Authenticate demo user with nova-api
        self.nova_demo = u.authenticate_nova_user(self.keystone,
                                                  self.demo_user,
                                                  'password',
                                                  self.demo_tenant)

    def test_100_ceph_processes(self):
        """Verify that the expected service processes are running
        on each ceph unit."""

        # Process name and quantity of processes to expect on each unit
        ceph_processes = {
            'ceph-mon': 1,
        }

        # Units with process names and PID quantities expected
        expected_processes = {
            self.ceph0_sentry: ceph_processes,
            self.ceph1_sentry: ceph_processes,
            self.ceph2_sentry: ceph_processes,
            self.ceph_osd_sentry: {'ceph-osd': [2, 3]}
        }

        actual_pids = u.get_unit_process_ids(expected_processes)
        ret = u.validate_unit_process_ids(expected_processes, actual_pids)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_102_services(self):
        """Verify the expected services are running on the service units."""

        services = {
            self.glance_sentry: ['glance-registry',
                                 'glance-api'],
            self.cinder_sentry: ['cinder-scheduler',
                                 'cinder-volume'],
        }

        if self._get_openstack_release() < self.xenial_ocata:
            services[self.cinder_sentry].append('cinder-api')
        else:
            services[self.cinder_sentry].append('apache2')

        if self._get_openstack_release() < self.xenial_mitaka:
            # For upstart systems only.  Ceph services under systemd
            # are checked by process name instead.
            ceph_services = [
                'ceph-mon-all',
                'ceph-mon id=`hostname`',
            ]
            services[self.ceph0_sentry] = ceph_services
            services[self.ceph1_sentry] = ceph_services
            services[self.ceph2_sentry] = ceph_services
            services[self.ceph_osd_sentry] = [
                'ceph-osd-all',
                'ceph-osd id={}'.format(u.get_ceph_osd_id_cmd(0)),
                'ceph-osd id={}'.format(u.get_ceph_osd_id_cmd(1))
            ]

        if self._get_openstack_release() >= self.trusty_liberty:
            services[self.keystone_sentry] = ['apache2']

        ret = u.validate_services_by_name(services)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_200_ceph_osd_ceph_relation(self):
        """Verify the ceph-osd to ceph relation data."""
        u.log.debug('Checking ceph-osd:ceph-mon relation data...')
        unit = self.ceph_osd_sentry
        relation = ['mon', 'ceph-mon:osd']
        expected = {
            'private-address': u.valid_ip
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph-osd to ceph-mon', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_201_ceph0_to_ceph_osd_relation(self):
        """Verify the ceph0 to ceph-osd relation data."""
        u.log.debug('Checking ceph0:ceph-osd mon relation data...')
        unit = self.ceph0_sentry
        relation = ['osd', 'ceph-osd:mon']
        expected = {
            'osd_bootstrap_key': u.not_null,
            'private-address': u.valid_ip,
            'auth': u'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph0 to ceph-osd', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_202_ceph1_to_ceph_osd_relation(self):
        """Verify the ceph1 to ceph-osd relation data."""
        u.log.debug('Checking ceph1:ceph-osd mon relation data...')
        unit = self.ceph1_sentry
        relation = ['osd', 'ceph-osd:mon']
        expected = {
            'osd_bootstrap_key': u.not_null,
            'private-address': u.valid_ip,
            'auth': u'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph1 to ceph-osd', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_203_ceph2_to_ceph_osd_relation(self):
        """Verify the ceph2 to ceph-osd relation data."""
        u.log.debug('Checking ceph2:ceph-osd mon relation data...')
        unit = self.ceph2_sentry
        relation = ['osd', 'ceph-osd:mon']
        expected = {
            'osd_bootstrap_key': u.not_null,
            'private-address': u.valid_ip,
            'auth': u'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph2 to ceph-osd', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_300_ceph_osd_config(self):
        """Verify the data in the ceph config file."""
        u.log.debug('Checking ceph config file data...')
        unit = self.ceph_osd_sentry
        conf = '/etc/ceph/ceph.conf'
        expected = {
            'global': {
                'auth cluster required': 'none',
                'auth service required': 'none',
                'auth client required': 'none',
                'fsid': '6547bd3e-1397-11e2-82e5-53567c8d32dc',
                'log to syslog': 'false',
                'err to syslog': 'false',
                'clog to syslog': 'false'
            },
            'mon': {
                'keyring': '/var/lib/ceph/mon/$cluster-$id/keyring'
            },
            'mds': {
                'keyring': '/var/lib/ceph/mds/$cluster-$id/keyring'
            },
            'osd': {
                'keyring': '/var/lib/ceph/osd/$cluster-$id/keyring',
                'osd journal size': '1024',
                'filestore xattr use omap': 'true'
            },
        }

        for section, pairs in expected.items():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "ceph config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_302_cinder_rbd_config(self):
        """Verify the cinder config file data regarding ceph."""
        u.log.debug('Checking cinder (rbd) config file data...')
        unit = self.cinder_sentry
        conf = '/etc/cinder/cinder.conf'
        section_key = 'cinder-ceph'
        expected = {
            section_key: {
                'volume_driver': 'cinder.volume.drivers.rbd.RBDDriver'
            }
        }
        for section, pairs in expected.items():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "cinder (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_304_glance_rbd_config(self):
        """Verify the glance config file data regarding ceph."""
        u.log.debug('Checking glance (rbd) config file data...')
        unit = self.glance_sentry
        conf = '/etc/glance/glance-api.conf'
        config = {
            'default_store': 'rbd',
            'rbd_store_ceph_conf': '/etc/ceph/ceph.conf',
            'rbd_store_user': 'glance',
            'rbd_store_pool': 'glance',
            'rbd_store_chunk_size': '8'
        }

        if self._get_openstack_release() >= self.trusty_kilo:
            # Kilo or later
            config['stores'] = ('glance.store.filesystem.Store,'
                                'glance.store.http.Store,'
                                'glance.store.rbd.Store')
            section = 'glance_store'
        else:
            # Juno or earlier
            section = 'DEFAULT'

        expected = {section: config}
        for section, pairs in expected.items():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "glance (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_306_nova_rbd_config(self):
        """Verify the nova config file data regarding ceph."""
        u.log.debug('Checking nova (rbd) config file data...')
        unit = self.nova_sentry
        conf = '/etc/nova/nova.conf'
        expected = {
            'libvirt': {
                'rbd_user': 'nova-compute',
                'rbd_secret_uuid': u.not_null
            }
        }
        for section, pairs in expected.items():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "nova (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_400_ceph_check_osd_pools(self):
        """Check osd pools on all ceph units, expect them to be
        identical, and expect specific pools to be present."""
        u.log.debug('Checking pools on ceph units...')

        expected_pools = self.get_ceph_expected_pools()
        results = []
        sentries = [
            self.ceph_osd_sentry,
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]

        # Check for presence of expected pools on each unit
        u.log.debug('Expected pools: {}'.format(expected_pools))
        for sentry_unit in sentries:
            pools = u.get_ceph_pools(sentry_unit)
            results.append(pools)

            for expected_pool in expected_pools:
                if expected_pool not in pools:
                    msg = ('{} does not have pool: '
                           '{}'.format(sentry_unit.info['unit_name'],
                                       expected_pool))
                    amulet.raise_status(amulet.FAIL, msg=msg)
            u.log.debug('{} has (at least) the expected '
                        'pools.'.format(sentry_unit.info['unit_name']))

        # Check that all units returned the same pool name:id data
        ret = u.validate_list_of_identical_dicts(results)
        if ret:
            u.log.debug('Pool list results: {}'.format(results))
            msg = ('{}; Pool list results are not identical on all '
                   'ceph units.'.format(ret))
            amulet.raise_status(amulet.FAIL, msg=msg)
        else:
            u.log.debug('Pool list on all ceph units produced the '
                        'same results (OK).')

    def test_410_ceph_cinder_vol_create(self):
        """Create and confirm a ceph-backed cinder volume, and inspect
        ceph cinder pool object count as the volume is created
        and deleted."""
        sentry_unit = self.ceph0_sentry
        obj_count_samples = []
        pool_size_samples = []
        pools = u.get_ceph_pools(self.ceph0_sentry)
        cinder_pool = pools['cinder-ceph']

        # Check ceph cinder pool object count, disk space usage and pool name
        u.log.debug('Checking ceph cinder pool original samples...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               cinder_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        expected = 'cinder-ceph'
        if pool_name != expected:
            msg = ('Ceph pool {} unexpected name (actual, expected): '
                   '{}. {}'.format(cinder_pool, pool_name, expected))
            amulet.raise_status(amulet.FAIL, msg=msg)

        # Create ceph-backed cinder volume
        cinder_vol = u.create_cinder_volume(self.cinder)

        # Re-check ceph cinder pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph cinder pool samples after volume create...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               cinder_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Delete ceph-backed cinder volume
        u.delete_resource(self.cinder.volumes, cinder_vol, msg="cinder volume")

        # Final check, ceph cinder pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph cinder pool after volume delete...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               cinder_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Validate ceph cinder pool object count samples over time
        ret = u.validate_ceph_pool_samples(obj_count_samples,
                                           "cinder pool object count")
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        # Validate ceph cinder pool disk space usage samples over time
        ret = u.validate_ceph_pool_samples(pool_size_samples,
                                           "cinder pool disk usage")
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_412_ceph_glance_image_create_delete(self):
        """Create and confirm a ceph-backed glance image, and inspect
        ceph glance pool object count as the image is created
        and deleted."""
        sentry_unit = self.ceph0_sentry
        obj_count_samples = []
        pool_size_samples = []
        pools = u.get_ceph_pools(self.ceph0_sentry)
        glance_pool = pools['glance']

        # Check ceph glance pool object count, disk space usage and pool name
        u.log.debug('Checking ceph glance pool original samples...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               glance_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        expected = 'glance'
        if pool_name != expected:
            msg = ('Ceph glance pool {} unexpected name (actual, '
                   'expected): {}. {}'.format(glance_pool,
                                              pool_name, expected))
            amulet.raise_status(amulet.FAIL, msg=msg)

        # Create ceph-backed glance image
        glance_img = u.create_cirros_image(self.glance, 'cirros-image-1')

        # Re-check ceph glance pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph glance pool samples after image create...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               glance_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Delete ceph-backed glance image
        u.delete_resource(self.glance.images,
                          glance_img, msg="glance image")

        # Final check, ceph glance pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph glance pool samples after image delete...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(sentry_unit,
                                                               glance_pool)
        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Validate ceph glance pool object count samples over time
        ret = u.validate_ceph_pool_samples(obj_count_samples,
                                           "glance pool object count")
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        # Validate ceph glance pool disk space usage samples over time
        ret = u.validate_ceph_pool_samples(pool_size_samples,
                                           "glance pool disk usage")
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_499_ceph_cmds_exit_zero(self):
        """Check basic functionality of ceph cli commands against
        all ceph units."""
        sentry_units = [
            self.ceph_osd_sentry,
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]
        commands = [
            'sudo ceph health',
            'sudo ceph mds stat',
            'sudo ceph pg stat',
            'sudo ceph osd stat',
            'sudo ceph mon stat',
        ]
        ret = u.check_commands_on_units(commands, sentry_units)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    # FYI: No restart check as ceph services do not restart
    # when charm config changes, unless monitor count increases.

    def test_900_ceph_encryption(self):
        """Verify that the new disk is added with encryption by checking for
           Ceph's encryption keys directory"""

        if self._get_openstack_release() >= self.trusty_mitaka:
            u.log.warn("Skipping encryption test for Mitaka")
            return
        sentry = self.ceph_osd_sentry
        set_default = {
            'osd-encrypt': 'False',
            'osd-devices': '/dev/vdb /srv/ceph',
        }
        set_alternate = {
            'osd-encrypt': 'True',
            'osd-devices': '/dev/vdb /srv/ceph /srv/ceph_encrypted',
        }
        juju_service = 'ceph-osd'
        u.log.debug('Making config change on {}...'.format(juju_service))
        mtime = u.get_sentry_time(sentry)
        self.d.configure(juju_service, set_alternate)
        unit_name = sentry.info['unit_name']

        sleep_time = 30
        retry_count = 30
        file_mtime = None
        time.sleep(sleep_time)

        filename = '/etc/ceph/dmcrypt-keys'
        tries = 0
        retry_sleep_time = 10
        while tries <= retry_count and not file_mtime:
            try:
                stat = sentry.directory_stat(filename)
                file_mtime = stat['mtime']
                self.log.debug('Attempt {} to get {} mtime on {} '
                               'OK'.format(tries, filename, unit_name))
            except IOError as e:
                self.d.configure(juju_service, set_default)
                self.log.debug('Attempt {} to get {} mtime on {} '
                               'failed\n{}'.format(tries, filename,
                                                   unit_name, e))
                time.sleep(retry_sleep_time)
                tries += 1

        self.d.configure(juju_service, set_default)

        if not file_mtime:
            self.log.warn('Could not determine mtime, assuming '
                          'folder does not exist')
            amulet.raise_status('folder does not exist')

        if file_mtime >= mtime:
            self.log.debug('Folder mtime is newer than provided mtime '
                           '(%s >= %s) on %s (OK)' % (file_mtime,
                                                      mtime, unit_name))
        else:
            self.log.warn('Folder mtime is older than provided mtime'
                          '(%s < on %s) on %s' % (file_mtime,
                                                  mtime, unit_name))
            amulet.raise_status('Folder mtime is older than provided mtime')

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed. """
        u.log.debug('Checking pause and resume actions...')
        sentry_unit = self.ceph_osd_sentry

        assert u.status_get(sentry_unit)[0] == "active"

        action_id = u.run_action(sentry_unit, "pause")
        assert u.wait_on_action(action_id), "Pause action failed."
        assert u.status_get(sentry_unit)[0] == "maintenance"

        action_id = u.run_action(sentry_unit, "resume")
        assert u.wait_on_action(action_id), "Resume action failed."
        assert u.status_get(sentry_unit)[0] == "active"
        u.log.debug('OK')

    def test_911_blacklist(self):
        """The blacklist actions execute and behave as expected. """
        u.log.debug('Checking blacklist-add-disk and'
                    'blacklist-remove-disk actions...')
        sentry_unit = self.ceph_osd_sentry

        assert u.status_get(sentry_unit)[0] == "active"

        # Attempt to add device with non-absolute path should fail
        action_id = u.run_action(sentry_unit,
                                 "blacklist-add-disk",
                                 params={"osd-devices": "vda"})
        assert not u.wait_on_action(action_id), "completed"
        assert u.status_get(sentry_unit)[0] == "active"

        # Attempt to add device with non-existent path should fail
        action_id = u.run_action(sentry_unit,
                                 "blacklist-add-disk",
                                 params={"osd-devices": "/non-existent"})
        assert not u.wait_on_action(action_id), "completed"
        assert u.status_get(sentry_unit)[0] == "active"

        # Attempt to add device with existent path should succeed
        action_id = u.run_action(sentry_unit,
                                 "blacklist-add-disk",
                                 params={"osd-devices": "/dev/vda"})
        assert u.wait_on_action(action_id), "completed"
        assert u.status_get(sentry_unit)[0] == "active"

        # Attempt to remove listed device should always succeed
        action_id = u.run_action(sentry_unit,
                                 "blacklist-remove-disk",
                                 params={"osd-devices": "/dev/vda"})
        assert u.wait_on_action(action_id), "completed"
        assert u.status_get(sentry_unit)[0] == "active"
        u.log.debug('OK')

    def test_912_list_disks(self):
        """The list-disks action execute. """
        u.log.debug('Checking list-disks action...')
        sentry_unit = self.ceph_osd_sentry

        assert u.status_get(sentry_unit)[0] == "active"

        action_id = u.run_action(sentry_unit, "list-disks")
        assert u.wait_on_action(action_id), "completed"
        assert u.status_get(sentry_unit)[0] == "active"
        u.log.debug('OK')
