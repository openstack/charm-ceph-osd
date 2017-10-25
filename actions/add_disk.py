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
import psutil
import sys

sys.path.append('lib')
sys.path.append('hooks')

import charmhelpers.contrib.storage.linux.ceph as ch_ceph
import charmhelpers.core.hookenv as hookenv

import ceph_hooks
import ceph.utils


def add_device(request, device_path, bucket=None):
    ceph.utils.osdize(dev, hookenv.config('osd-format'),
                      ceph_hooks.get_journal_devices(),
                      hookenv.config('osd-reformat'),
                      hookenv.config('ignore-device-errors'),
                      hookenv.config('osd-encrypt'),
                      hookenv.config('bluestore'))
    # Make it fast!
    if hookenv.config('autotune'):
        ceph.utils.tune_dev(dev)
    mounts = filter(lambda disk: device_path
                    in disk.device, psutil.disk_partitions())
    if mounts:
        osd = mounts[0]
        osd_id = osd.mountpoint.split('/')[-1].split('-')[-1]
        request.ops.append({
            'op': 'move-osd-to-bucket',
            'osd': "osd.{}".format(osd_id),
            'bucket': bucket})
    return request


def get_devices():
    devices = []
    for path in hookenv.action_get('osd-devices').split(' '):
        path = path.strip()
        if os.path.isabs(path):
            devices.append(path)

    return devices


if __name__ == "__main__":
    request = ch_ceph.CephBrokerRq()
    for dev in get_devices():
        request = add_device(request=request,
                             device_path=dev,
                             bucket=hookenv.action_get("bucket"))
    ch_ceph.send_request_if_needed(request, relation='mon')
