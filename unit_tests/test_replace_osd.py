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

import errno
import posix

from mock import call, Mock, patch

import test_utils
import ceph.utils as ceph
import replace_osd

TO_PATCH = [
    'ctypes',
    'status_set',
]

proc_data = [
    '   8       0 sda 2291336 263100 108136080 1186276 28844343 28798167 '
    '2145908072 49433216 0 7550032 50630100\n',
    '   8       1 sda1 1379 1636 8314 692 75 17 1656 0 0 496 692\n',
    '   8       2 sda2 1 0 2 0 0 0 0 0 0 0 0\n',
]


def umount_busy(*args):
    # MNT_FORCE
    if args[1] == 1:
        return -1
    # MNT_DETACH
    if args[1] == 2:
        return 0


class ReplaceOsdTestCase(test_utils.CharmTestCase):
    def setUp(self):
        super(ReplaceOsdTestCase, self).setUp(ceph, TO_PATCH)

    def test_umount_ebusy(self):
        self.ctypes.util.find_library.return_value = 'libc.so.6'
        umount_mock = Mock()
        self.ctypes.CDLL.return_value = umount_mock
        umount_mock.umount.side_effect = umount_busy
        self.ctypes.get_errno.return_value = errno.EBUSY

        ret = ceph.umount('/some/osd/mount')
        umount_mock.assert_has_calls([
            call.umount('/some/osd/mount', 1),
            call.umount('/some/osd/mount', 2),
        ])
        assert ret == 0

    def test_umount(self):
        self.ctypes.util.find_library.return_value = 'libc.so.6'
        umount_mock = Mock()
        self.ctypes.CDLL.return_value = umount_mock
        umount_mock.umount.return_value = 0

        ret = ceph.umount('/some/osd/mount')
        umount_mock.assert_has_calls([
            call.umount('/some/osd/mount', 1),
        ])
        assert ret == 0

    @patch.object(ceph, 'mounts')
    @patch.object(ceph.subprocess, 'check_output')
    @patch.object(ceph, 'umount')
    @patch.object(ceph, 'osdize')
    @patch.object(ceph, 'shutil')
    @patch.object(ceph, 'systemd')
    @patch.object(ceph, 'ceph_user')
    def test_replace_osd(self, ceph_user, systemd, shutil, osdize, umount,
                         check_output, mounts):
        ceph_user.return_value = "ceph"
        mounts.return_value = [['/var/lib/ceph/osd/ceph-a', '/dev/sda']]
        check_output.return_value = True
        self.status_set.return_value = None
        systemd.return_value = False
        umount.return_value = 0
        osdize.return_value = None
        shutil.rmtree.return_value = None
        ceph.replace_osd(dead_osd_number=0,
                         dead_osd_device='/dev/sda',
                         new_osd_device='/dev/sdb',
                         osd_format=True,
                         osd_journal=None,
                         reformat_osd=False,
                         ignore_errors=False)
        check_output.assert_has_calls(
            [
                call(['ceph', '--id', 'osd-upgrade',
                      'osd', 'out', 'osd.0']),
                call(['stop', 'ceph-osd', 'id=0']),
                call(['ceph', '--id',
                      'osd-upgrade', 'osd', 'crush', 'remove', 'osd.0']),
                call(['ceph', '--id',
                      'osd-upgrade', 'auth', 'del', 'osd.0']),
                call(['ceph', '--id',
                      'osd-upgrade', 'osd', 'rm', 'osd.0'])
            ]
        )

    @patch('replace_osd.get_disk_stats')
    def test_lookup_device_name(self, disk_stats):
        disk_stats.return_value = proc_data
        dev_name = replace_osd.lookup_device_name(major_number=8,
                                                  minor_number=0)
        assert dev_name == 'sda', "dev_name: {}".format(dev_name)

    @patch('replace_osd.os.lstat')
    def test_get_device_number(self, lstat):
        lstat.return_value = posix.stat_result([
            16877, 16, 51729L, 3, 0, 0, 217, 0, 1458086872, 1458086872
        ])
        major, minor = replace_osd.get_device_number(1)
        assert major == 202
        assert minor == 17
