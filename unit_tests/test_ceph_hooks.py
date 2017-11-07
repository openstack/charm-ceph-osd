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

import copy
import unittest

from mock import patch, MagicMock, call

import charmhelpers.contrib.storage.linux.ceph as ceph

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    import ceph_hooks

CHARM_CONFIG = {'config-flags': '',
                'loglevel': 1,
                'use-syslog': True,
                'osd-journal-size': 1024,
                'use-direct-io': True,
                'osd-format': 'ext4',
                'prefer-ipv6': False,
                'customize-failure-domain': False,
                'bluestore': False,
                'crush-initial-weight': '0'}


class CephHooksTestCase(unittest.TestCase):
    def setUp(self):
        super(CephHooksTestCase, self).setUp()

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno', lambda *args: 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context(self, mock_config, mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': False,
                    'bluestore_experimental': False}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno',
                  lambda pkg, ver: -1 if ver == '12.1.0' else 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context_filestore_old(self, mock_config, mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': False,
                    'bluestore_experimental': True}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno', lambda *args: 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context_bluestore(self, mock_config, mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        config['bluestore'] = True
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': True,
                    'bluestore_experimental': False}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno',
                  lambda pkg, ver: -1 if ver == '12.1.0' else 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context_bluestore_old(self, mock_config, mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        config['bluestore'] = True
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': True,
                    'bluestore_experimental': True}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno', lambda *args: 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context_w_config_flags(self, mock_config, mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        config['config-flags'] = '{"osd": {"osd max write size": 1024}}'
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'osd': {'osd max write size': 1024},
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': False,
                    'bluestore_experimental': False}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'get_fsid', lambda *args: '1234')
    @patch.object(ceph_hooks, 'get_auth', lambda *args: False)
    @patch.object(ceph_hooks, 'get_public_addr', lambda *args: "10.0.0.1")
    @patch.object(ceph_hooks, 'get_cluster_addr', lambda *args: "10.1.0.1")
    @patch.object(ceph_hooks, 'cmp_pkgrevno', lambda *args: 1)
    @patch.object(ceph_hooks, 'get_mon_hosts', lambda *args: ['10.0.0.1',
                                                              '10.0.0.2'])
    @patch.object(ceph_hooks, 'get_networks', lambda *args: "")
    @patch.object(ceph, 'config')
    @patch.object(ceph_hooks, 'config')
    def test_get_ceph_context_w_config_flags_invalid(self, mock_config,
                                                     mock_config2):
        config = copy.deepcopy(CHARM_CONFIG)
        config['config-flags'] = ('{"osd": {"osd max write size": 1024},'
                                  '"foo": "bar"}')
        mock_config.side_effect = lambda key: config[key]
        mock_config2.side_effect = lambda key: config[key]
        ctxt = ceph_hooks.get_ceph_context()
        expected = {'auth_supported': False,
                    'ceph_cluster_network': '',
                    'ceph_public_network': '',
                    'cluster_addr': '10.1.0.1',
                    'dio': 'true',
                    'fsid': '1234',
                    'loglevel': 1,
                    'mon_hosts': '10.0.0.1 10.0.0.2',
                    'old_auth': False,
                    'osd': {'osd max write size': 1024},
                    'crush_initial_weight': '0',
                    'osd_journal_size': 1024,
                    'public_addr': '10.0.0.1',
                    'short_object_len': True,
                    'upgrade_in_progress': False,
                    'use_syslog': 'true',
                    'bluestore': False,
                    'bluestore_experimental': False}
        self.assertEqual(ctxt, expected)

    @patch.object(ceph_hooks, 'ceph')
    @patch.object(ceph_hooks, 'service_restart')
    @patch.object(ceph_hooks, 'service_reload')
    @patch.object(ceph_hooks, 'copy_profile_into_place')
    @patch.object(ceph_hooks, 'CephOsdAppArmorContext')
    @patch.object(ceph_hooks, 'config')
    def test_install_apparmor_profile(self, mock_config,
                                      mock_apparmor_context,
                                      mock_copy_profile_into_place,
                                      mock_service_reload,
                                      mock_service_restart,
                                      mock_ceph):
        '''Apparmor profile reloaded when config changes (upstart)'''
        m_config = MagicMock()
        m_config.changed.return_value = True
        mock_config.return_value = m_config
        m_aa_context = MagicMock()
        mock_apparmor_context.return_value = m_aa_context
        mock_ceph.systemd.return_value = False

        ceph_hooks.install_apparmor_profile()

        m_aa_context.setup_aa_profile.assert_called()
        mock_copy_profile_into_place.assert_called()
        m_config.changed.assert_called_with('aa-profile-mode')
        mock_service_restart.assert_called_with('ceph-osd-all')
        mock_service_reload.assert_called_with('apparmor')

    @patch.object(ceph_hooks, 'ceph')
    @patch.object(ceph_hooks, 'service_restart')
    @patch.object(ceph_hooks, 'service_reload')
    @patch.object(ceph_hooks, 'copy_profile_into_place')
    @patch.object(ceph_hooks, 'CephOsdAppArmorContext')
    @patch.object(ceph_hooks, 'config')
    def test_install_apparmor_profile_systemd(self, mock_config,
                                              mock_apparmor_context,
                                              mock_copy_profile_into_place,
                                              mock_service_reload,
                                              mock_service_restart,
                                              mock_ceph):
        '''Apparmor profile reloaded when config changes (systemd)'''
        m_config = MagicMock()
        m_config.changed.return_value = True
        mock_config.return_value = m_config
        m_aa_context = MagicMock()
        mock_apparmor_context.return_value = m_aa_context
        mock_ceph.systemd.return_value = True
        mock_ceph.get_local_osd_ids.return_value = [0, 1, 2]

        ceph_hooks.install_apparmor_profile()

        m_aa_context.setup_aa_profile.assert_called()
        mock_copy_profile_into_place.assert_called()
        m_config.changed.assert_called_with('aa-profile-mode')
        mock_service_reload.assert_called_with('apparmor')
        mock_service_restart.assert_has_calls([
            call('ceph-osd@0'),
            call('ceph-osd@1'),
            call('ceph-osd@2'),
        ])

    @patch.object(ceph_hooks, 'storage_list')
    @patch.object(ceph_hooks, 'config')
    def test_get_devices(self, mock_config, mock_storage_list):
        '''Devices returned as expected'''
        config = {'osd-devices': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        devices = ceph_hooks.get_devices()
        self.assertEqual(devices, ['/dev/vda', '/dev/vdb'])

    @patch('os.path.exists')
    @patch.object(ceph_hooks, 'storage_list')
    @patch.object(ceph_hooks, 'config')
    def test_get_journal_devices(self, mock_config, mock_storage_list,
                                 mock_os_path_exists):
        '''Devices returned as expected'''
        config = {'osd-journal': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        mock_os_path_exists.return_value = True
        devices = ceph_hooks.get_journal_devices()
        mock_storage_list.assert_called()
        mock_os_path_exists.assert_called()
        self.assertEqual(devices, set(['/dev/vda', '/dev/vdb']))
