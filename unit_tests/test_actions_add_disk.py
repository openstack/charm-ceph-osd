# Copyright 2020 Canonical Ltd
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

from unittest import mock

from actions import add_disk

from test_utils import CharmTestCase


class AddDiskActionTests(CharmTestCase):
    def setUp(self):
        super(AddDiskActionTests, self).setUp(
            add_disk, ['hookenv', 'kv'])
        self.kv.return_value = self.kv

    @mock.patch.object(add_disk.ceph_hooks, 'get_journal_devices')
    @mock.patch.object(add_disk.charms_ceph.utils, 'osdize')
    def test_add_device(self, mock_osdize, mock_get_journal_devices):

        def fake_config(key):
            return {
                'ignore-device-errors': True,
                'osd-encrypt': True,
                'osd-encrypt-keymanager': True,
                'autotune': False,
            }.get(key)

        self.hookenv.config.side_effect = fake_config
        mock_get_journal_devices.return_value = ''
        self.hookenv.relation_ids.return_value = ['ceph:0']

        db = mock.MagicMock()
        self.kv.return_value = db
        db.get.side_effect = {'osd-devices': ['/dev/myosddev']}.get

        request = {'ops': []}
        add_disk.add_device(request, '/dev/myosddev')

        call = mock.call(relation_id='ceph:0',
                         relation_settings={'bootstrapped-osds': 1})
        self.hookenv.relation_set.assert_has_calls([call])
        mock_osdize.assert_has_calls([mock.call('/dev/myosddev',
                                                None, '', True, True,
                                                True, None, None)])

        piter = add_disk.PartitionIter(['/dev/cache'], 100, ['/dev/myosddev'])
        mock_create_bcache = mock.MagicMock(side_effect=lambda b: '/dev/cache')
        with mock.patch.object(add_disk.PartitionIter, 'create_bcache',
                               mock_create_bcache) as mock_call:
            add_disk.add_device(request, '/dev/myosddev', part_iter=piter)
            mock_call.assert_called()
            db.set.assert_called_with('osd-aliases',
                                      {'/dev/myosddev': '/dev/cache'})

        mock_create_bcache.side_effect = lambda b: None
        with mock.patch.object(add_disk.PartitionIter, 'create_bcache',
                               mock_create_bcache) as mock_call:
            with self.assertRaises(add_disk.DeviceError):
                add_disk.add_device(request, '/dev/myosddev', part_iter=piter)

    def test_get_devices(self):
        self.hookenv.action_get.return_value = '/dev/foo bar'
        rv = add_disk.get_devices('')
        self.assertEqual(rv, ['/dev/foo'])
        self.hookenv.action_get.return_value = None
        rv = add_disk.get_devices('')
        self.assertEqual(rv, [])

    @mock.patch.object(add_disk, 'device_size')
    @mock.patch.object(add_disk, 'function_fail')
    def test_validate_psize(self, function_fail, device_size):
        caches = {'cache1': 100, 'cache2': 200}
        device_size.side_effect = lambda c: caches[c]
        function_fail.return_value = None
        with self.assertRaises(SystemExit):
            add_disk.validate_partition_size(
                60, ['a', 'b', 'c'], list(caches.keys()))
        self.assertIsNone(add_disk.validate_partition_size(
            60, ['a', 'b'], list(caches.keys())))

    def test_cache_storage(self):
        self.hookenv.storage_list.return_value = [{'location': 'a', 'key': 1},
                                                  {'location': 'b'}]
        self.hookenv.storage_get.side_effect = lambda k, elem: elem.get(k)
        rv = add_disk.cache_storage()
        self.assertEqual(['a', 'b'], rv)

    def test_validate_osd_id(self):
        for elem in ('osd.1', '1', 0, 113):
            self.assertTrue(add_disk.validate_osd_id(elem))
        for elem in ('osd.-1', '-3', '???', -100, 3.4, {}):
            self.assertFalse(add_disk.validate_osd_id(elem))

    @mock.patch.object(add_disk.charms_ceph.utils, 'disable_osd')
    @mock.patch.object(add_disk.charms_ceph.utils, 'stop_osd')
    @mock.patch.object(add_disk.subprocess, 'check_output')
    @mock.patch.object(add_disk.subprocess, 'check_call')
    @mock.patch.object(add_disk, 'apt_install')
    @mock.patch.object(add_disk.shutil, 'copy')
    @mock.patch.object(add_disk.os.path, 'exists')
    def test_crimson_osd(self, os_path_exists, shcopy, apt_install,
                         check_call, check_output, stop_osd, disable_osd):
        os_path_exists.return_value = False
        check_output.return_value = b'{"1": [{"devices": ["/dev/vdc"]}]}'
        self.assertIsNone(add_disk.get_osd_from_device("/dev/vda"))

        add_disk.start_crimson_osd(None, '/dev/vdc')
        stop_osd.assert_called_with("1")
        check_call.assert_any_call(['systemctl', 'start', 'crimson-osd@1'])
        shcopy.assert_called()
        apt_install.assert_called()
