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

"""
List unmounted devices.

This script will get all block devices known by udev and check if they
are mounted so that we can give unmounted devices to the administrator.
"""

import sys

sys.path.append('hooks/')
sys.path.append('lib/')

import charmhelpers.core.hookenv as hookenv

import ceph.utils

if __name__ == '__main__':
    hookenv.action_set({
        'disks': ceph.utils.unmounted_disks()})
