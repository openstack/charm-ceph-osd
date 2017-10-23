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

from charmhelpers.core.hookenv import (
    config,
    action_get,
)

from charmhelpers.contrib.storage.linux.ceph import (
    CephBrokerRq,
    send_request_if_needed,
)

from ceph.utils import (
    osdize,
    tune_dev,
)

from ceph_hooks import (
    get_journal_devices,
)


def add_device(request, device_path, bucket=None):
    osdize(dev, config('osd-format'),
           get_journal_devices(), config('osd-reformat'),
           config('ignore-device-errors'),
           config('osd-encrypt'),
           config('bluestore'))
    # Make it fast!
    if config('autotune'):
        tune_dev(dev)
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
    for path in action_get('osd-devices').split(' '):
        path = path.strip()
        if os.path.isabs(path):
            devices.append(path)

    return devices


if __name__ == "__main__":
    request = CephBrokerRq()
    for dev in get_devices():
        request = add_device(request=request,
                             device_path=dev,
                             bucket=action_get("bucket"))
    send_request_if_needed(request, relation='mon')
