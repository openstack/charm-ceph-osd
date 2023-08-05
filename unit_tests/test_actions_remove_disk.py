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

from unittest import mock

from actions import remove_disk

from test_utils import CharmTestCase


class RemoveDiskActionTests(CharmTestCase):

    @mock.patch.object(remove_disk.subprocess, 'check_output')
    def test_get_device_map(self, check_output):
        check_output.return_value = b'''
{
    "1": [{"devices": ["/dev/sdx1"]}],
    "2": [{"devices": ["/dev/sdc2", "/dev/sdc3"]}]
}
        '''
        rv = remove_disk.get_device_map()
        self.assertEqual(rv[0]['path'], '/dev/sdx1')
        self.assertEqual(rv[1]['id'], rv[2]['id'])

    def test_normalize_osd_id(self):
        self.assertEqual('osd.1', remove_disk.normalize_osd_id(1))
        self.assertEqual('osd.2', remove_disk.normalize_osd_id('osd.2'))
        self.assertEqual('osd.3', remove_disk.normalize_osd_id('3'))

    def test_map_device_id(self):
        dev_map = [
            {'id': 'osd.1', 'path': '/dev/sdc1'},
            {'id': 'osd.2', 'path': '/dev/sdd2'},
            {'id': 'osd.2', 'path': '/dev/sdx3'}
        ]
        self.assertEqual(
            'osd.1',
            remove_disk.map_device_to_id(dev_map, '/dev/sdc1'))
        self.assertIsNone(
            remove_disk.map_device_to_id(dev_map, '/dev/sdx4'))

        self.assertEqual(
            '/dev/sdd2',
            remove_disk.map_id_to_device(dev_map, 'osd.2'))
        self.assertIsNone(
            remove_disk.map_id_to_device(dev_map, 'osd.3'))

    @mock.patch.object(remove_disk, 'get_bcache_names')
    def test_action_osd_constructor(self, bcache_names):
        bcache_names.return_value = ('bcache0', '/dev/bcache0')
        dev_map = [
            {'path': '/dev/sdx1', 'id': 'osd.1'}
        ]
        with self.assertRaises(remove_disk.RemoveException):
            remove_disk.ActionOSD(dev_map, dev='/dev/sdx1', osd_id='osd.1')
        obj = remove_disk.ActionOSD(dev_map, dev='/dev/sdx1')
        self.assertEqual(obj.osd_id, 'osd.1')
        obj = remove_disk.ActionOSD(dev_map, osd_id='1')
        self.assertEqual(obj.device, '/dev/sdx1')

    @mock.patch.object(remove_disk.charms_ceph.utils, 'disable_osd')
    @mock.patch.object(remove_disk, 'device_size')
    @mock.patch.object(remove_disk.charms_ceph.utils, 'stop_osd')
    @mock.patch.object(remove_disk, 'bcache_remove')
    @mock.patch.object(remove_disk.subprocess, 'call')
    @mock.patch.object(remove_disk.subprocess, 'check_call')
    @mock.patch.object(remove_disk, 'get_bcache_names')
    def test_action_osd_remove(self, get_bcache_names, check_call,
                               call, bcache_remove, stop_osd, device_size,
                               disable_osd):
        call.return_value = 0
        get_bcache_names.return_value = ('/dev/backing', '/dev/caching')
        device_size.side_effect = lambda x: 1 if x == '/dev/caching' else 0
        dev_map = [
            {'path': '/dev/bcache0', 'id': 'osd.1'}
        ]
        prefix_args = ['ceph', '--id', 'osd-removal']
        obj = remove_disk.ActionOSD(dev_map, osd_id='1')

        obj.remove(True, 1, True)

        # Subprocess Call checks
        call.assert_any_call(
            prefix_args + ['osd', 'safe-to-destroy', 'osd.1'], timeout=300
        )
        check_call.assert_any_call(
            prefix_args + ['osd', 'purge', 'osd.1', '--yes-i-really-mean-it'],
            timeout=600
        )
        check_call.assert_any_call(
            prefix_args + ['osd', 'crush', 'reweight', 'osd.1', '0'],
            timeout=300
        )

        bcache_remove.assert_called_with(
            '/dev/bcache0', '/dev/backing', '/dev/caching')
        report = obj.report
        self.assertIn('/dev/backing', report)
        report = report['/dev/backing']
        self.assertIn('osd-ids', report)
        self.assertIn('osd.1', report['osd-ids'])
        self.assertIn('cache-devices', report)
        self.assertIn('partition-size', report)
        self.assertEqual('/dev/caching', report['cache-devices'])
        self.assertEqual(1, report['partition-size'])

        # Test the timeout check.
        with self.assertRaises(remove_disk.RemoveException):
            call.return_value = 1
            obj.remove(False, 0, False)

    @mock.patch.object(remove_disk.hookenv, 'local_unit')
    @mock.patch.object(remove_disk.hookenv, 'action_set')
    def test_write_report(self, action_set, local_unit):
        output = {}
        local_unit.return_value = 'ceph-osd/0'
        action_set.side_effect = lambda x: output.update(x)
        report = {'dev@': {'osd-ids': 'osd.1', 'cache-devices': 'cache@',
                           'partition-size': 5}}
        remove_disk.write_report(report, 'text')
        self.assertIn('message', output)
        msg = output['message']
        self.assertIn('juju run ceph-osd/0 add-disk', msg)
        self.assertIn('osd-devices=dev@', msg)
        self.assertIn('osd-ids=osd.1', msg)
        self.assertIn('cache-devices=cache@', msg)
        self.assertIn('partition-size=5', msg)

    def test_make_same_length(self):
        l1, l2 = [1], []
        remove_disk.make_same_length(l1, l2)
        self.assertEqual(len(l1), len(l2))
        self.assertIsNone(l2[0])
        prev_len = len(l1)
        remove_disk.make_same_length(l1, l2)
        self.assertEqual(len(l1), prev_len)
