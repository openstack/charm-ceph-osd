#!/usr/bin/env python3
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

import json
import os
import psutil
import shutil
import subprocess
import sys

sys.path.append('lib')
sys.path.append('hooks')

import charmhelpers.contrib.storage.linux.ceph as ch_ceph
import charmhelpers.core.hookenv as hookenv
from charmhelpers.core.hookenv import function_fail
from charmhelpers.fetch import apt_install

from charmhelpers.core.unitdata import kv
from utils import (PartitionIter, device_size, DeviceError)

import ceph_hooks
import charms_ceph.utils


CRIMSON_PACKAGES = ['crimson-osd', 'libc-ares2', 'libcrypto++-dev',
                    'libyaml-cpp-dev']
CRIMSON_SYSTEMD_FILE = '/lib/systemd/system/crimson-osd@.service'


def get_osd_from_device(device):
    """Given a device, return the OSD ID that it maps to."""
    output = subprocess.check_output(['ceph-volume', 'lvm', 'list',
                                      '--format=json'])
    devmap = json.loads(output.decode('utf8'))
    for osd_id, data in devmap.items():
        for elem in data:
            if device in elem.get('devices', []):
                return osd_id


def start_crimson_osd(osd_id, device):
    """An OSD was started with the classic daemon, but Crimson was
    requested. As such, stop the current one and launch the correct daemon."""

    if osd_id is None:
        osd_id = get_osd_from_device(device)

    charms_ceph.utils.stop_osd(osd_id)
    charms_ceph.utils.disable_osd(osd_id)
    unit_name = (
        '/run/systemd/system/ceph-osd.target.wants/ceph-osd@{}.service'
        .format(osd_id))

    if os.path.exists(unit_name):
        os.remove(unit_name)

    if not os.path.exists(CRIMSON_SYSTEMD_FILE):
        apt_install(CRIMSON_PACKAGES, fatal=True)
        shutil.copy('files/systemd/crimson-osd@.service', CRIMSON_SYSTEMD_FILE)
        subprocess.check_call(['systemctl', 'daemon-reload'])

    subprocess.check_call(['systemctl', 'enable',
                           'crimson-osd@{}'.format(osd_id)])
    subprocess.check_call(['systemctl', 'start',
                           'crimson-osd@{}'.format(osd_id)])


def add_device(request, device_path, bucket=None, osd_id=None,
               part_iter=None, use_crimson=False, bluestore_skip=None):
    """Add a new device to be used by the OSD unit.

    :param request: A broker request to notify monitors of changes.
    :type request: CephBrokerRq

    :param device_path: The absolute path to the device to be added.
    :type device_path: str

    :param bucket: The bucket name in ceph to add the device into, or None.
    :type bucket: Option[str, None]

    :param osd_id: The OSD Id to use, or None.
    :type osd_id: Option[str, None]

    :param part_iter: The partition iterator that will create partitions on
                      demand, to service bcache creation, or None, if no
                      partitions need to be created.
    :type part_iter: Option[PartitionIter, None]

    :param use_crimson: Whether to use Crimson for the OSD (Experimental).
    :type use_crimson: bool

    :param bluestore_skip: Which Bluestore features to avoid.
    :type bluestore_skip: Option[str, None]
    """
    if part_iter is not None:
        effective_dev = part_iter.create_bcache(device_path)
        if not effective_dev:
            raise DeviceError(
                'Failed to create bcache for device {}'.format(device_path))
    else:
        effective_dev = device_path

    if osd_id is not None and osd_id.startswith('osd.'):
        osd_id = osd_id[4:]

    if bluestore_skip:
        bluestore_skip = bluestore_skip.split(',')

    charms_ceph.utils.osdize(effective_dev, hookenv.config('osd-format'),
                             ceph_hooks.get_journal_devices(),
                             hookenv.config('ignore-device-errors'),
                             hookenv.config('osd-encrypt'),
                             hookenv.config('osd-encrypt-keymanager'),
                             osd_id, bluestore_skip)

    if use_crimson:
        start_crimson_osd(osd_id, effective_dev)

    # Make it fast!
    if hookenv.config('autotune'):
        charms_ceph.utils.tune_dev(device_path)
    mounts = filter(lambda disk: device_path
                    in disk.device, psutil.disk_partitions())
    for osd in mounts:
        osd_id = osd.mountpoint.split('/')[-1].split('-')[-1]
        request.ops.append({
            'op': 'move-osd-to-bucket',
            'osd': "osd.{}".format(osd_id),
            'bucket': bucket})

    # Ensure mon's count of osds is accurate
    db = kv()
    bootstrapped_osds = len(db.get('osd-devices', []))
    for r_id in hookenv.relation_ids('mon'):
        hookenv.relation_set(
            relation_id=r_id,
            relation_settings={
                'bootstrapped-osds': bootstrapped_osds,
            }
        )

    if part_iter is not None:
        # Update the alias map so we can refer to an OSD via the original
        # device instead of the newly created cache name.
        aliases = db.get('osd-aliases', {})
        aliases[device_path] = effective_dev
        db.set('osd-aliases', aliases)
        db.flush()

    return request


def get_devices(key):
    """Get a list of the devices passed for this action, for a key."""
    devices = []
    for path in (hookenv.action_get(key) or '').split():
        path = path.strip()
        if os.path.isabs(path):
            devices.append(path)

    return devices


def cache_storage():
    """Return a list of Juju storage for caches."""
    cache_ids = hookenv.storage_list('cache-devices')
    return [hookenv.storage_get('location', cid) for cid in cache_ids]


def validate_osd_id(osd_id):
    """Test that an OSD id is actually valid."""
    if isinstance(osd_id, str):
        if osd_id.startswith('osd.'):
            osd_id = osd_id[4:]
        try:
            return int(osd_id) >= 0
        except ValueError:
            return False
    elif isinstance(osd_id, int):
        return osd_id >= 0
    return False


def validate_partition_size(psize, devices, caches):
    """Test that the cache devices have enough room."""
    sizes = [device_size(cache) for cache in caches]
    n_caches = len(caches)
    for idx in range(len(devices)):
        cache_idx = idx % n_caches
        prev = sizes[cache_idx] - psize
        if prev < 0:
            function_fail('''Cache device {} does not have enough
                room to provide {} {}GB partitions'''.format(
                caches[cache_idx], (idx + 1) // n_caches, psize))
            sys.exit(1)
        sizes[cache_idx] = prev


if __name__ == "__main__":
    crimson = hookenv.action_get('use-crimson')
    if crimson and not hookenv.action_get('i-really-mean-it'):
        function_fail('Need to pass i-really-mean-it for Crimson OSDs')
        sys.exit(1)

    request = ch_ceph.CephBrokerRq()
    devices = get_devices('osd-devices')
    caches = get_devices('cache-devices') or cache_storage()
    if caches:
        psize = hookenv.action_get('partition-size')
        if psize:
            validate_partition_size(psize, devices, caches)

        part_iter = PartitionIter(caches, psize, devices)
    else:
        part_iter = None

    osd_ids = hookenv.action_get('osd-ids')
    if osd_ids:
        # Validate number and format for OSD ids.
        osd_ids = osd_ids.split()
        if len(osd_ids) != len(devices):
            function_fail('The number of osd-ids and osd-devices must match')
            sys.exit(1)
        for osd_id in osd_ids:
            if not validate_osd_id(osd_id):
                function_fail('Invalid OSD ID passed: {}'.format(osd_id))
                sys.exit(1)
    else:
        osd_ids = [None] * len(devices)

    bluestore_skip = hookenv.action_get('bluestore-skip')

    errors = []
    for dev, osd_id in zip(devices, osd_ids):
        try:
            request = add_device(request=request,
                                 device_path=dev,
                                 bucket=hookenv.action_get("bucket"),
                                 osd_id=osd_id, part_iter=part_iter,
                                 use_crimson=crimson)
        except Exception:
            errors.append(dev)

    ch_ceph.send_request_if_needed(request, relation='mon')
    if errors:
        if part_iter is not None:
            for error in errors:
                part_iter.cleanup(error)

        function_fail('Failed to add devices: {}'.format(','.join(errors)))
        sys.exit(1)
