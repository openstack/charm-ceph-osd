import unittest

__author__ = 'Chris Holcombe <chris.holcombe@canonical.com>'

from mock import call, patch, MagicMock

from ceph_hooks import check_for_upgrade


def config_side_effect(*args):
    if args[0] == 'source':
        return 'cloud:trusty-kilo'
    elif args[0] == 'key':
        return 'key'
    elif args[0] == 'release-version':
        return 'cloud:trusty-kilo'


class UpgradeRollingTestCase(unittest.TestCase):

    @patch('ceph_hooks.ceph.dirs_need_ownership_update')
    @patch('ceph_hooks.ceph.is_bootstrapped')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.emit_cephconf')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.host')
    @patch('ceph_hooks.ceph.roll_osd_cluster')
    def test_check_for_upgrade(self, roll_osd_cluster, host, hookenv,
                               emit_cephconf, version, is_bootstrapped,
                               dirs_need_ownership_update):
        dirs_need_ownership_update.return_value = True
        is_bootstrapped.return_value = True
        version.side_effect = ['firefly', 'hammer']
        host.lsb_release.return_value = {
            'DISTRIB_CODENAME': 'trusty',
        }
        previous_mock = MagicMock().return_value
        previous_mock.previous.return_value = "cloud:trusty-juno"
        hookenv.config.side_effect = [previous_mock,
                                      config_side_effect('source')]
        check_for_upgrade()

        roll_osd_cluster.assert_called_with(new_version='hammer',
                                            upgrade_key='osd-upgrade')
        emit_cephconf.assert_has_calls([call(upgrading=True),
                                        call(upgrading=False)])

    @patch('ceph_hooks.ceph.dirs_need_ownership_update')
    @patch('ceph_hooks.ceph.is_bootstrapped')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.emit_cephconf')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.host.lsb_release')
    @patch('ceph_hooks.ceph.roll_osd_cluster')
    def test_resume_failed_upgrade(self, roll_osd_cluster, lsb_release,
                                   hookenv, emit_cephconf, version,
                                   is_bootstrapped,
                                   dirs_need_ownership_update):
        dirs_need_ownership_update.return_value = True
        is_bootstrapped.return_value = True
        version.side_effect = ['jewel', 'jewel']
        lsb_release.return_value = {'DISTRIB_CODENAME': 'trusty'}

        check_for_upgrade()

        roll_osd_cluster.assert_called_with(new_version='jewel',
                                            upgrade_key='osd-upgrade')
        emit_cephconf.assert_has_calls([call(upgrading=True),
                                        call(upgrading=False)])

    @patch('ceph_hooks.ceph.is_bootstrapped')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.host')
    @patch('ceph_hooks.ceph.roll_monitor_cluster')
    def test_check_for_upgrade_not_bootstrapped(self, roll_monitor_cluster,
                                                host, hookenv,
                                                version, is_bootstrapped):
        is_bootstrapped.return_value = False
        version.side_effect = ['firefly', 'hammer']
        host.lsb_release.return_value = {
            'DISTRIB_CODENAME': 'trusty',
        }
        previous_mock = MagicMock().return_value
        previous_mock.previous.return_value = "cloud:trusty-juno"
        hookenv.config.side_effect = [previous_mock,
                                      config_side_effect('source')]
        check_for_upgrade()

        roll_monitor_cluster.assert_not_called()
