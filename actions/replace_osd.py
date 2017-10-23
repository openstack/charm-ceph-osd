#!/usr/bin/python
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

import os
import sys

sys.path.append('hooks/')
sys.path.append('lib/')

import charmhelpers.core.hookenv as hookenv

import ceph.utils

"""
Given a OSD number this script will attempt to turn that back into a mount
point and then replace the OSD with a new one.
"""


def get_disk_stats():
    try:
        # https://www.kernel.org/doc/Documentation/iostats.txt
        with open('/proc/diskstats', 'r') as diskstats:
            return diskstats.readlines()
    except IOError as err:
        hookenv.log('Could not open /proc/diskstats.  Error: {}'
                    .format(err.message))
        hookenv.action_fail(
            'replace-osd failed because /proc/diskstats could not '
            'be opened {}'.format(err.message))
        return None


def lookup_device_name(major_number, minor_number):
    """

    :param major_number: int.  The major device number
    :param minor_number: int. The minor device number
    :return: string.  The name of the device.  Example: /dev/sda.
    Returns None on error.
    """
    diskstats = get_disk_stats()
    for line in diskstats:
        parts = line.split()
        if not len(parts) > 3:
            # Skip bogus lines
            continue
        try:
            if int(parts[0]) is major_number and int(parts[1]) is \
                    minor_number:
                # Found our device.  Return its name
                return parts[2]
        except ValueError as value_err:
            hookenv.log('Could not convert {} or {} into an integer. Error: {}'
                        .format(parts[0], parts[1], value_err.message))
            continue
    return None


def get_device_number(osd_number):
    """
    This function will return a tuple of (major_number, minor_number)
    device number for the given osd.
    :param osd_number: int
    :rtype : (major_number,minor_number)
    """
    path = "/var/lib/ceph/osd/ceph-{}".format(osd_number)
    info = os.lstat(path)
    major_number = os.major(info.st_dev)
    minor_number = os.minor(info.st_dev)
    return major_number, minor_number


if __name__ == '__main__':
    dead_osd_number = hookenv.action_get("osd-number")
    replacement_device = hookenv.action_get("replacement-device")
    major, minor = get_device_number(dead_osd_number)
    device_name = lookup_device_name(major, minor)
    osd_format = hookenv.config('osd-format')
    osd_journal = hookenv.config('osd-journal')

    ceph.utils.replace_osd(dead_osd_number=dead_osd_number,
                           dead_osd_device="/dev/{}".format(device_name),
                           new_osd_device=replacement_device,
                           osd_format=osd_format,
                           osd_journal=osd_journal)
