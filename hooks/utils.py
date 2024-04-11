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
import re
import os
import socket
import subprocess
import sys
import time

sys.path.append('lib')
import charms_ceph.utils as ceph

from charmhelpers.core.hookenv import (
    unit_get,
    cached,
    config,
    network_get_primary_address,
    log,
    DEBUG,
    WARNING,
    status_set,
    storage_get,
    storage_list,
    function_get,
)
from charmhelpers.core import unitdata
from charmhelpers.fetch import (
    apt_install,
    filter_installed_packages
)

from charmhelpers.core.host import (
    lsb_release,
    CompareHostReleases,
)

from charmhelpers.contrib.network.ip import (
    get_address_in_network,
    get_ipv6_addr
)

ALL = "all"  # string value representing all "OSD devices"
TEMPLATES_DIR = 'templates'

try:
    import jinja2
except ImportError:
    apt_install(filter_installed_packages(['python3-jinja2']),
                fatal=True)
    import jinja2

try:
    import dns.resolver
except ImportError:
    apt_install(filter_installed_packages(['python3-dnspython']),
                fatal=True)
    import dns.resolver


_bootstrap_keyring = "/var/lib/ceph/bootstrap-osd/ceph.keyring"
_upgrade_keyring = "/var/lib/ceph/osd/ceph.client.osd-upgrade.keyring"
_removal_keyring = "/var/lib/ceph/osd/ceph.client.osd-removal.keyring"
_client_crash_keyring = "/var/lib/ceph/osd/ceph.client.crash.keyring"


def is_osd_bootstrap_ready():
    """
    Is this machine ready to add OSDs.

    :returns: boolean: Is the OSD bootstrap key present
    """
    return os.path.exists(_bootstrap_keyring)


def _import_key(key, path, name, override=False):
    exists = os.path.exists(path)
    if not exists or override:
        create = ['--create-keyring'] if not exists else []
        cmd = [
            'sudo',
            '-u',
            ceph.ceph_user(),
            'ceph-authtool',
            path
        ] + create + [
            '--name={}'.format(name),
            '--add-key={}'.format(key)
        ]
        subprocess.check_call(cmd)


def import_osd_bootstrap_key(key):
    """
    Ensure that the osd-bootstrap keyring is setup.

    :param key: The cephx key to add to the bootstrap keyring
    :type key: str
    :raises: subprocess.CalledProcessError"""
    _import_key(key, _bootstrap_keyring, 'client.bootstrap-osd')


def import_osd_upgrade_key(key):
    """
    Ensure that the osd-upgrade keyring is setup.

    :param key: The cephx key to add to the upgrade keyring
    :type key: str
    :raises: subprocess.CalledProcessError"""
    _import_key(key, _upgrade_keyring, 'client.osd-upgrade')


def import_osd_removal_key(key):
    """
    Ensure that the osd-removal keyring is setup.

    :param key: The cephx key to add to the upgrade keyring
    :type key: str
    :raises: subprocess.CalledProcessError"""
    _import_key(key, _removal_keyring, 'client.osd-removal')


def import_client_crash_key(key):
    """
    Ensure that the client.crash keyring is set up.

    :param key: The cephx key to add to the client.crash keyring
    :type key: str
    :raises: subprocess.CalledProcessError"""
    _import_key(key, _client_crash_keyring, 'client.crash')


def import_pending_key(key, osd_id):
    """
    Import a pending key, used for key rotation.

    :param key: The pending cephx key that will replace the current one.
    :type key: str
    :param osd_id: The OSD id whose key will be replaced.
    :type osd_id: str
    :raises: subprocess.CalledProcessError"""
    _import_key(key, '/var/lib/ceph/osd/ceph-%s/keyring' % osd_id,
                'osd.%s' % osd_id, override=True)


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    """Render Jinja2 template.

    In addition to the template directory specified by the caller the shared
    'templates' directory in the ``charmhelpers.contrib.openstack`` module will
    be searched.

    :param template_name: Name of template file.
    :type template_name: str
    :param context: Template context.
    :type context: Dict[str,any]
    :param template_dir: Primary path to search for templates.
                         (default: contents of the ``TEMPLATES_DIR`` global)
    :type template_dir: Optional[str]
    :returns: The rendered template
    :rtype: str
    """
    templates = jinja2.Environment(
        loader=jinja2.ChoiceLoader((
            jinja2.FileSystemLoader(template_dir),
            jinja2.PackageLoader('charmhelpers.contrib.openstack',
                                 'templates'),
        )))
    template = templates.get_template(template_name)
    return template.render(context)


def enable_pocket(pocket):
    apt_sources = "/etc/apt/sources.list"
    with open(apt_sources, "rt", encoding='UTF-8') as sources:
        lines = sources.readlines()
    with open(apt_sources, "wt", encoding='UTF-8') as sources:
        for line in lines:
            if pocket in line:
                sources.write(re.sub('^# deb', 'deb', line))
            else:
                sources.write(line)


@cached
def get_unit_hostname():
    return socket.gethostname()


@cached
def get_host_ip(hostname=None):
    if config('prefer-ipv6'):
        return get_ipv6_addr()[0]

    hostname = hostname or unit_get('private-address')
    try:
        # Test to see if already an IPv4 address
        socket.inet_aton(hostname)
        return hostname
    except socket.error:
        # This may throw an NXDOMAIN exception; in which case
        # things are badly broken so just let it kill the hook
        answers = dns.resolver.query(hostname, 'A')
        if answers:
            return answers[0].address


@cached
def get_public_addr():
    if config('ceph-public-network'):
        return get_network_addrs('ceph-public-network')[0]

    try:
        return network_get_primary_address('public')
    except NotImplementedError:
        log("network-get not supported", DEBUG)

    return get_host_ip()


@cached
def get_cluster_addr():
    if config('ceph-cluster-network'):
        return get_network_addrs('ceph-cluster-network')[0]

    try:
        return network_get_primary_address('cluster')
    except NotImplementedError:
        log("network-get not supported", DEBUG)

    return get_host_ip()


def get_networks(config_opt='ceph-public-network'):
    """Get all configured networks from provided config option.

    If public network(s) are provided, go through them and return those for
    which we have an address configured.
    """
    networks = config(config_opt)
    if networks:
        networks = networks.split()
        return [n for n in networks if get_address_in_network(n)]

    return []


def get_network_addrs(config_opt):
    """Get all configured public networks addresses.

    If public network(s) are provided, go through them and return the
    addresses we have configured on any of those networks.
    """
    addrs = []
    networks = config(config_opt)
    if networks:
        networks = networks.split()
        addrs = [get_address_in_network(n) for n in networks]
        addrs = [a for a in addrs if a]

    if not addrs:
        if networks:
            msg = ("Could not find an address on any of '%s' - resolve this "
                   "error to retry" % (networks))
            status_set('blocked', msg)
            raise Exception(msg)
        else:
            return [get_host_ip()]

    return addrs


def assert_charm_supports_ipv6():
    """Check whether we are able to support charms ipv6."""
    _release = lsb_release()['DISTRIB_CODENAME'].lower()
    if CompareHostReleases(_release) < "trusty":
        raise Exception("IPv6 is not supported in the charms for Ubuntu "
                        "versions less than Trusty 14.04")


def get_blacklist():
    """Get blacklist stored in the local kv() store"""
    db = unitdata.kv()
    return db.get('osd-blacklist', [])


def get_journal_devices():
    if config('osd-journal'):
        devices = [el.strip() for el in config('osd-journal').split(' ')]
    else:
        devices = []
    storage_ids = storage_list('osd-journals')
    devices.extend((storage_get('location', s) for s in storage_ids))

    # Filter out any devices in the action managed unit-local device blacklist
    _blacklist = get_blacklist()
    return set(device for device in devices
               if device not in _blacklist and os.path.exists(device))


def should_enable_discard(devices):
    """
    Tries to autodetect if we can enable discard on devices and if that
    discard can be asynchronous. We want to enable both options if there's
    any SSDs unless any of them are using SATA <= 3.0, in which case
    discard is supported but is a blocking operation.
    """
    discard_enable = True
    for device in devices:
        # whitelist some devices that do not need checking
        if (device.startswith("/dev/nvme") or
                device.startswith("/dev/vd")):
            continue
        try:
            sata_3_or_less = is_sata30orless(device)
        except subprocess.CalledProcessError:
            sata_3_or_less = True
        if (device.startswith("/dev/") and
                os.path.exists(device) and
                sata_3_or_less):
            discard_enable = False
            log("SSD Discard autodetection: {} is forcing discard off"
                "(sata <= 3.0)".format(device), level=WARNING)
    return discard_enable


def is_sata30orless(device):
    result = subprocess.check_output(["/usr/sbin/smartctl", "-i", device])
    print(result)
    for line in str(result).split("\\n"):
        if re.match(r"SATA Version is: *SATA (1\.|2\.|3\.0)", str(line)):
            return True
    return False


def parse_osds_arguments():
    """Parse OSD IDs from action `osds` argument.

    Fetch action arguments and parse them from comma separated list to
    the set of OSD IDs.

    :return: Set of OSD IDs
    :rtype: set(str)
    """
    raw_arg = function_get("osds")

    if raw_arg is None:
        raise RuntimeError("Action argument \"osds\" is missing")

    # convert OSD IDs from user's input into the set
    args = {osd_id.strip() for osd_id in str(raw_arg).split(',')}

    if ALL in args and len(args) != 1:
        args = {ALL}
        log("keyword \"all\" was found in \"osds\" argument. Dropping other "
            "explicitly defined OSD IDs", WARNING)

    return args


class DeviceError(Exception):

    """Exception type used to signal errors raised by calling
    external commands that manipulate devices.
    """
    pass


def _check_output(args, **kwargs):
    try:
        return subprocess.check_output(args, **kwargs).decode('UTF-8')
    except subprocess.CalledProcessError as e:
        raise DeviceError(str(e))


def _check_call(args, **kwargs):
    try:
        return subprocess.check_call(args, **kwargs)
    except subprocess.CalledProcessError as e:
        raise DeviceError(str(e))


def setup_bcache(backing, cache):
    """Create a bcache device out of the backing storage and caching device.

    :param backing: The path to the backing device.
    :type backing: str

    :param cache: The path to the caching device.
    :type cache: str

    :returns: The full path of the newly created bcache device.
    :rtype: str
    """
    _check_call(['sudo', 'make-bcache', '-B', backing,
                 '-C', cache, '--writeback'])

    def bcache_name(dev):
        rv = _check_output(['lsblk', '-p', '-b', cache, '-J', '-o', 'NAME'])
        for x in json.loads(rv)['blockdevices'][0].get('children', []):
            if x['name'] != dev:
                return x['name']

    for _ in range(100):
        rv = bcache_name(cache)
        if rv is not None:
            return rv

        # Tell the kernel to refresh the partitions.
        time.sleep(0.3)
        _check_call(['sudo', 'partprobe'])


def get_partition_names(dev):
    """Given a raw device, return a set of the partitions it contains.

    :param dev: The path to the device.
    :type dev: str

    :returns: A set with the partitions of the passed device.
    :rtype: set[str]
    """
    rv = _check_output(['lsblk', '-b', dev, '-J', '-p', '-o', 'NAME'])
    rv = json.loads(rv)['blockdevices'][0].get('children', {})
    return set(x['name'] for x in rv)


def create_partition(cache, size, n_iter):
    """Create a partition of a specific size in a device. If needed,
       make sure the device has a GPT ready.

    :param cache: The path to the caching device from which to create
        the partition.
    :type cache: str

    :param size: The size (in GB) of the partition to create.
    :type size: int

    :param n_iter: The iteration number. If zero, this function will
        also create the GPT on the caching device.
    :type n_iter: int

    :returns: The full path of the newly created partition.
    :rtype: str
    """
    if not n_iter:
        # In our first iteration, make sure the device has a GPT.
        _check_call(['sudo', 'parted', '-s', cache, 'mklabel', 'gpt'])
    prev_partitions = get_partition_names(cache)
    cmd = ['sudo', 'parted', '-s', cache, 'mkpart', 'primary',
           str(n_iter * size) + 'GB', str((n_iter + 1) * size) + 'GB']

    _check_call(cmd)
    for _ in range(100):
        ret = get_partition_names(cache) - prev_partitions
        if ret:
            return next(iter(ret))

        time.sleep(0.3)
        _check_call(['sudo', 'partprobe'])

    raise DeviceError('Failed to create partition')


def device_size(dev):
    """Compute the size of a device, in GB.

    :param dev: The full path to the device.
    :type dev: str

    :returns: The size in GB of the specified device.
    :rtype: int
    """
    ret = _check_output(['lsblk', '-b', '-d', dev, '-J', '-o', 'SIZE'])
    ret = int(json.loads(ret)['blockdevices'][0]['size'])
    return ret / (1024 * 1024 * 1024)   # Return size in GB.


def remove_lvm(device):
    """Remove any physical and logical volumes associated to a device."""
    vgs = []
    try:
        rv = _check_output(['sudo', 'pvdisplay', device])
    except DeviceError:
        # Assume no physical volumes.
        return

    for line in rv.splitlines():
        line = line.strip()
        if line.startswith('VG Name'):
            vgs.append(line.split()[2])
    if vgs:
        _check_call(['sudo', 'vgremove', '-y'] + vgs)
    _check_call(['sudo', 'pvremove', '-y', device])


def bcache_remove(bcache, backing, caching):
    """Remove a bcache kernel device, given its caching.

    :param bache: The path of the bcache device.
    :type bcache: str

    :param backing: The backing device for bcache
    :type backing: str

    :param caching: The caching device for bcache
    :type caching: str
    """
    rv = _check_output(['sudo', 'bcache-super-show', backing])
    uuid = None
    # Fetch the UUID for the caching device.
    for line in rv.split('\n'):
        idx = line.find('cset.uuid')
        if idx >= 0:
            uuid = line[idx + 9:].strip()
            break
    else:
        return
    bcache_name = bcache[bcache.rfind('/') + 1:]

    def write_one(path):
        os.system('echo 1 | sudo tee {}'.format(path))

    # The command ceph-volume typically creates PV's and VG's for the
    # OSD device. Remove them now before deleting the bcache.
    remove_lvm(bcache)

    # NOTE: We *must* do the following steps in this order. For
    # kernels 4.x and prior, not doing so will cause the bcache device
    # to be undeletable.
    # In addition, we have to use 'sudo tee' as done above, since it
    # can cause permission issues in some implementations.
    write_one('/sys/block/{}/bcache/detach'.format(bcache_name))
    write_one('/sys/block/{}/bcache/stop'.format(bcache_name))
    write_one('/sys/fs/bcache/{}/stop'.format(uuid))

    # We wipe the bcache signatures here because the bcache tools will not
    # create the devices otherwise. There is a 'force' option, but it's not
    # always available, so we do the portable thing here.
    wipefs_safely(backing)
    wipefs_safely(caching)


def wipe_disk(dev, timeout=None):
    """Destroy all data in a specific device, including partition tables."""
    _check_call(['sudo', 'wipefs', '-a', dev], timeout=timeout)


def wipefs_safely(dev):
    for _ in range(10):
        try:
            wipe_disk(dev, 1)
            return
        except DeviceError:
            time.sleep(0.3)
        except subprocess.TimeoutExpired:
            # If this command times out, then it's likely because
            # the disk is dead, so give up.
            return
    raise DeviceError('Failed to wipe bcache device: {}'.format(dev))


class PartitionIter:

    """Class used to create partitions iteratively.

    Objects of this type are used to create partitions out of
    the specified cache devices, either with a specific size,
    or with a size proportional to what is needed."""

    def __init__(self, caches, psize, devices):
        """Construct a partition iterator.

        :param caches: The list of cache devices to use.
        :type caches: iterable

        :param psize: The size of the partitions (in GB), or None
        :type psize: Option[int, None]

        :param devices: The backing devices. Only used to get their length.
        :type devices: iterable
        """
        self.caches = [[cache, 0] for cache in caches]
        self.idx = 0
        if not psize:
            factor = min(1.0, len(caches) / len(devices))
            self.psize = [factor * device_size(cache) for cache in caches]
        else:
            self.psize = psize
        self.created = {}

    def __iter__(self):
        return self

    def __next__(self):
        """Return a newly created partition.

        The object keeps track of the currently used caching device,
        so upon creating a new partition, it will move to the next one,
        distributing the load among them in a round-robin fashion.
        """
        cache, n_iter = self.caches[self.idx]
        size = self.psize
        if not isinstance(size, (int, float)):
            size = self.psize[self.idx]

        self.caches[self.idx][1] += 1
        self.idx = (self.idx + 1) % len(self.caches)
        log('Creating partition in device {} of size {}'.format(cache, size))
        return create_partition(cache, size, n_iter)

    def create_bcache(self, backing):
        """Create a bcache device, using the internal caching device,
        and an external backing one.

        :param backing: The path to the backing device.
        :type backing: str

        :returns: The name for the newly created bcache device.
        :rtype: str
        """
        cache = next(self)
        ret = setup_bcache(backing, cache)
        if ret is not None:
            self.created[backing] = (ret, cache)
            log('Bcache device created: {}'.format(cache))
        return ret

    def cleanup(self, device):
        """Destroy any created partitions and bcache names for a device."""
        args = self.created.get(device)
        if not args:
            return

        bcache, caching = args
        try:
            bcache_remove(bcache, device, caching)
        except DeviceError:
            log('Failed to cleanup bcache device: {}'.format(bcache))


def _device_suffix(dev):
    ix = dev.rfind('/')
    if ix >= 0:
        dev = dev[ix + 1:]
    return dev


def get_bcache_names(dev):
    """Return the backing and caching devices for a bcache device,
    in that specific order.

    :param dev: The path to the bcache device, i.e: /dev/bcache0
    :type dev: str

    :returns: A tuple with the backing and caching devices.
    :rtype: list[Option[None, str], Option[None, str]]
    """
    if dev is None:
        return None, None

    dev_name = _device_suffix(dev)
    bcache_path = '/sys/block/{}/slaves'.format(dev_name)
    if (not os.path.exists('/sys/block/{}/bcache'.format(dev_name)) or
            not os.path.exists(bcache_path)):
        return None, None

    cache = os.listdir(bcache_path)
    if len(cache) < 2:
        return None, None

    backing = '/dev/' + cache[0]
    caching = '/dev/' + cache[1]
    out = _check_output(['sudo', 'bcache-super-show', backing])
    if 'backing device' not in out:
        return caching, backing
    return backing, caching


def get_parent_device(dev):
    """Return the device's parent, assuming if it's a block device."""
    try:
        rv = subprocess.check_output(['lsblk', '-as', dev, '-J'])
        rv = json.loads(rv.decode('UTF-8'))
    except subprocess.CalledProcessError:
        return dev

    children = rv.get('blockdevices', [])
    if not children:
        return dev

    children = children[0].get('children', [])
    for child in children:
        if 'children' not in child:
            return '/dev/' + child['name']

    return dev


def find_filestore_osds():
    # Path to Ceph OSD
    osd_path = '/var/lib/ceph/osd'

    # Search through OSD directories in path starting with 'ceph-'
    dirs = [d for d in os.listdir(osd_path)
            if d.startswith('ceph-')
            and os.path.isdir(os.path.join(osd_path, d))]

    found = []
    for dir in dirs:
        # Construct the full path
        type_file_path = os.path.join(osd_path, dir, 'type')
        # Open and read the type file
        with open(type_file_path, 'r') as f:
            content = f.read()
        # Check if the content includes 'filestore'
        if 'filestore' in content:
            found.append(dir)

    return found
