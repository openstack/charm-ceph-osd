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

import unittest

from unittest.mock import patch

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    import utils


class CephUtilsTestCase(unittest.TestCase):
    def setUp(self):
        super(CephUtilsTestCase, self).setUp()

    @patch('os.path.exists')
    @patch.object(utils, 'storage_list')
    @patch.object(utils, 'config')
    def test_get_journal_devices(self, mock_config, mock_storage_list,
                                 mock_os_path_exists):
        '''Devices returned as expected'''
        config = {'osd-journal': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        mock_os_path_exists.return_value = True
        devices = utils.get_journal_devices()
        mock_storage_list.assert_called()
        mock_os_path_exists.assert_called()
        self.assertEqual(devices, set(['/dev/vda', '/dev/vdb']))

    @patch('os.path.exists')
    @patch.object(utils, 'get_blacklist')
    @patch.object(utils, 'storage_list')
    @patch.object(utils, 'config')
    def test_get_journal_devices_blacklist(self, mock_config,
                                           mock_storage_list,
                                           mock_get_blacklist,
                                           mock_os_path_exists):
        '''Devices returned as expected when blacklist in effect'''
        config = {'osd-journal': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        mock_get_blacklist.return_value = ['/dev/vda']
        mock_os_path_exists.return_value = True
        devices = utils.get_journal_devices()
        mock_storage_list.assert_called()
        mock_os_path_exists.assert_called()
        mock_get_blacklist.assert_called()
        self.assertEqual(devices, set(['/dev/vdb']))

    @patch('os.path.exists')
    @patch.object(utils, 'is_sata30orless')
    def test_should_enable_discard_yes(self, mock_is_sata30orless,
                                       mock_os_path_exists):
        devices = ['/dev/sda', '/dev/vda', '/dev/nvme0n1']
        mock_os_path_exists.return_value = True
        mock_is_sata30orless.return_value = False
        ret = utils.should_enable_discard(devices)
        mock_os_path_exists.assert_called()
        mock_is_sata30orless.assert_called()
        self.assertEqual(ret, True)

    @patch('os.path.exists')
    @patch.object(utils, 'is_sata30orless')
    def test_should_enable_discard_no(self, mock_is_sata30orless,
                                      mock_os_path_exists):
        devices = ['/dev/sda', '/dev/vda', '/dev/nvme0n1']
        mock_os_path_exists.return_value = True
        mock_is_sata30orless.return_value = True
        ret = utils.should_enable_discard(devices)
        mock_os_path_exists.assert_called()
        mock_is_sata30orless.assert_called()
        self.assertEqual(ret, False)

    @patch('subprocess.check_output')
    def test_is_sata30orless_sata31(self, mock_subprocess_check_output):
        extcmd_output = (b'supressed text\nSATA Version is:  '
                         b'SATA 3.1, 6.0 Gb/s (current: 6.0 Gb/s)\n'
                         b'supressed text\n\n')
        mock_subprocess_check_output.return_value = extcmd_output
        ret = utils.is_sata30orless('/dev/sda')
        mock_subprocess_check_output.assert_called()
        self.assertEqual(ret, False)

    @patch('subprocess.check_output')
    def test_is_sata30orless_sata30(self, mock_subprocess_check_output):
        extcmd_output = (b'supressed text\nSATA Version is:  '
                         b'SATA 3.0, 6.0 Gb/s (current: 6.0 Gb/s)\n'
                         b'supressed text\n\n')
        mock_subprocess_check_output.return_value = extcmd_output
        ret = utils.is_sata30orless('/dev/sda')
        mock_subprocess_check_output.assert_called()
        self.assertEqual(ret, True)

    @patch('subprocess.check_output')
    def test_is_sata30orless_sata26(self, mock_subprocess_check_output):
        extcmd_output = (b'supressed text\nSATA Version is:  '
                         b'SATA 2.6, 3.0 Gb/s (current: 3.0 Gb/s)\n'
                         b'supressed text\n\n')
        mock_subprocess_check_output.return_value = extcmd_output
        ret = utils.is_sata30orless('/dev/sda')
        mock_subprocess_check_output.assert_called()
        self.assertEqual(ret, True)

    @patch.object(utils, "function_get")
    def test_raise_on_missing_arguments(self, mock_function_get):
        mock_function_get.return_value = None
        err_msg = "Action argument \"osds\" is missing"
        with self.assertRaises(RuntimeError, msg=err_msg):
            utils.parse_osds_arguments()

    @patch.object(utils, "function_get")
    def test_parse_service_ids(self, mock_function_get):
        mock_function_get.return_value = "1,2,3"
        expected_ids = {"1", "2", "3"}

        parsed = utils.parse_osds_arguments()
        self.assertEqual(parsed, expected_ids)

    @patch.object(utils, "function_get")
    def test_parse_service_ids_with_all(self, mock_function_get):
        mock_function_get.return_value = "1,2,all"
        expected_id = {utils.ALL}

        parsed = utils.parse_osds_arguments()
        self.assertEqual(parsed, expected_id)

    @patch('subprocess.check_call')
    @patch('subprocess.check_output')
    def test_setup_bcache(self, check_output, check_call):
        check_output.return_value = b'''
          {
            "blockdevices": [
              {"name":"/dev/nvme0n1",
                 "children": [
                   {"name":"/dev/bcache0"}
                 ]
              }
            ]
          }
        '''
        self.assertEqual(utils.setup_bcache('', ''), '/dev/bcache0')

    @patch('subprocess.check_output')
    def test_get_partition_names(self, check_output):
        check_output.return_value = b'''
            {
              "blockdevices": [
                {"name":"/dev/sdd",
                 "children": [
                   {"name":"/dev/sdd1"}
                 ]
               }
             ]
           }
        '''
        partitions = utils.get_partition_names('')
        self.assertEqual(partitions, set(['/dev/sdd1']))
        # Check for a raw device with no partitions.
        check_output.return_value = b'''
          {"blockdevices": [{"name":"/dev/sdd"}]}
        '''
        self.assertEqual(set(), utils.get_partition_names(''))

    @patch.object(utils, 'get_partition_names')
    @patch('subprocess.check_call')
    def test_create_partition(self, check_call, get_partition_names):
        first_call = True

        def gpn(dev):
            nonlocal first_call
            if first_call:
                first_call = False
                return set()
            return set(['/dev/nvm0n1p1'])
        get_partition_names.side_effect = gpn
        partition_name = utils.create_partition('/dev/nvm0n1', 101, 0)
        self.assertEqual(partition_name, '/dev/nvm0n1p1')
        args = check_call.call_args[0][0]
        self.assertIn('/dev/nvm0n1', args)
        self.assertIn('101GB', args)

    @patch('subprocess.check_output')
    def test_device_size(self, check_output):
        check_output.return_value = b'''
            {
              "blockdevices": [{"size":800166076416}]
            }
            '''
        self.assertEqual(745, int(utils.device_size('')))

    @patch('subprocess.check_output')
    @patch.object(utils, 'remove_lvm')
    @patch.object(utils, 'wipe_disk')
    @patch('os.system')
    def test_bcache_remove(self, system, wipe_disk, remove_lvm, check_output):
        check_output.return_value = b'''
        sb.magic		ok
        sb.first_sector		8 [match]
        sb.csum			63F23B706BA0FE6A [match]
        sb.version		3 [cache device]
        dev.label		(empty)
        dev.uuid		ca4ce5e1-4cf3-4330-b1c9-2c735b14cd0b
        dev.sectors_per_block	1
        dev.sectors_per_bucket	1024
        dev.cache.first_sector	1024
        dev.cache.cache_sectors	1562822656
        dev.cache.total_sectors	1562823680
        dev.cache.ordered	yes
        dev.cache.discard	no
        dev.cache.pos		0
        dev.cache.replacement	0 [lru]
        cset.uuid		424242
        '''
        utils.bcache_remove('/dev/bcache0', 'backing', 'caching')
        system.assert_any_call(
            'echo 1 | sudo tee /sys/block/bcache0/bcache/detach')
        system.assert_any_call(
            'echo 1 | sudo tee /sys/block/bcache0/bcache/stop')
        system.assert_any_call(
            'echo 1 | sudo tee /sys/fs/bcache/424242/stop')
        wipe_disk.assert_any_call('backing', 1)
        wipe_disk.assert_any_call('caching', 1)

    @patch('os.listdir')
    @patch('os.path.exists')
    @patch('subprocess.check_output')
    def test_get_bcache_names(self, check_output, exists, listdir):
        exists.return_value = True
        check_output.return_value = b'''
sb.magic		ok
sb.first_sector		8 [match]
sb.csum			A71D96D4364343BF [match]
sb.version		1 [backing device]

dev.label		(empty)
dev.uuid		cca84a86-3f68-4ffb-8be1-4449c9fb29a8
dev.sectors_per_block	1
dev.sectors_per_bucket	1024
dev.data.first_sector	16
dev.data.cache_mode	1 [writeback]
dev.data.cache_state	1 [clean]

cset.uuid		57add9da-e5de-47c6-8f39-3e16aafb8d31
        '''
        listdir.return_value = ['backing', 'caching']
        values = utils.get_bcache_names('/dev/bcache0')
        self.assertEqual(2, len(values))
        self.assertEqual(values[0], '/dev/backing')
        check_output.return_value = b'''
sb.magic		ok
sb.first_sector		8 [match]
sb.csum			6802E76075FF7B77 [match]
sb.version		3 [cache device]

dev.label		(empty)
dev.uuid		fb6e9d06-12e2-46ca-b8fd-797ecec1a126
dev.sectors_per_block	1
dev.sectors_per_bucket	1024
dev.cache.first_sector	1024
dev.cache.cache_sectors	10238976
dev.cache.total_sectors	10240000
dev.cache.ordered	yes
dev.cache.discard	no
dev.cache.pos		0
dev.cache.replacement	0 [lru]

cset.uuid		57add9da-e5de-47c6-8f39-3e16aafb8d31
        '''
        values = utils.get_bcache_names('/dev/bcache0')
        self.assertEqual(values[0], '/dev/caching')

    @patch('subprocess.check_output')
    @patch('subprocess.check_call')
    def test_remove_lvm(self, check_call, check_output):
        check_output.return_value = b'''
--- Physical volume ---
  PV Name               /dev/bcache0
  VG Name               ceph-1
  VG Name               ceph-2
        '''
        utils.remove_lvm('/dev/bcache0')
        check_call.assert_any_call(
            ['sudo', 'vgremove', '-y', 'ceph-1', 'ceph-2'])
        check_call.assert_any_call(['sudo', 'pvremove', '-y', '/dev/bcache0'])

        check_call.reset_mock()

        def just_raise(*args):
            raise utils.DeviceError()

        check_output.side_effect = just_raise
        utils.remove_lvm('')
        check_call.assert_not_called()

    @patch.object(utils, 'wipe_disk')
    @patch.object(utils, 'bcache_remove')
    @patch.object(utils, 'create_partition')
    @patch.object(utils, 'setup_bcache')
    def test_partition_iter(self, setup_bcache, create_partition,
                            bcache_remove, wipe_disk):
        create_partition.side_effect = \
            lambda c, s, n: c + '|' + str(s) + '|' + str(n)
        setup_bcache.side_effect = lambda *args: args
        piter = utils.PartitionIter(['/dev/nvm0n1', '/dev/nvm0n2'],
                                    200, ['dev1', 'dev2', 'dev3'])
        piter.create_bcache('dev1')
        setup_bcache.assert_called_with('dev1', '/dev/nvm0n1|200|0')
        piter.cleanup('dev1')
        bcache_remove.assert_called()
        setup_bcache.mock_reset()
        piter.create_bcache('dev2')
        setup_bcache.assert_called_with('dev2', '/dev/nvm0n2|200|0')
        piter.create_bcache('dev3')
        setup_bcache.assert_called_with('dev3', '/dev/nvm0n1|200|1')

    @patch.object(utils, 'device_size')
    @patch.object(utils, 'create_partition')
    @patch.object(utils, 'setup_bcache')
    def test_partition_iter_no_size(self, setup_bcache, create_partition,
                                    device_size):
        device_size.return_value = 300
        piter = utils.PartitionIter(['/dev/nvm0n1'], 0,
                                    ['dev1', 'dev2', 'dev3'])
        create_partition.side_effect = lambda c, sz, g: sz

        # 300GB across 3 devices, i.e: 100 for each.
        self.assertEqual(100, next(piter))
        self.assertEqual(100, next(piter))

    @patch.object(utils.subprocess, 'check_output')
    def test_parent_device(self, check_output):
        check_output.return_value = b'''
{"blockdevices": [
  {"name": "loop1p1",
   "children": [
       {"name": "loop1"}]
  }]
}'''
        self.assertEqual(utils.get_parent_device('/dev/loop1p1'), '/dev/loop1')
