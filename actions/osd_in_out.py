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

# osd_out/osd_in actions file.

import os
import sys
from subprocess import check_call

sys.path.append('lib')
sys.path.append('hooks')

from charmhelpers.core.hookenv import (
    action_fail,
)

from ceph.utils import get_local_osd_ids
from ceph_hooks import assess_status


def osd_out(args):
    """Pause the ceph-osd units on the local machine only.

    Optionally uses the 'osd-number' from juju action param to only osd_out a
    specific osd.

    @raises CalledProcessError if the ceph commands fails.
    @raises OSError if it can't get the local osd ids.
    """
    for local_id in get_local_osd_ids():
        cmd = [
            'ceph',
            '--id', 'osd-upgrade',
            'osd', 'out', str(local_id)]
        check_call(cmd)
    assess_status()


def osd_in(args):
    """Resume the ceph-osd units on this local machine only

    @raises subprocess.CalledProcessError should the osd units fails to osd_in.
    @raises OSError if the unit can't get the local osd ids
    """
    for local_id in get_local_osd_ids():
        cmd = [
            'ceph',
            '--id', 'osd-upgrade',
            'osd', 'in', str(local_id)]
        check_call(cmd)
    assess_status()

# A dictionary of all the defined actions to callables (which take
# parsed arguments).
ACTIONS = {"osd-out": osd_out, "osd-in": osd_in}


def main(args):
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        s = "Action {} undefined".format(action_name)
        action_fail(s)
        return s
    else:
        try:
            action(args)
        except Exception as e:
            action_fail("Action {} failed: {}".format(action_name, str(e)))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
