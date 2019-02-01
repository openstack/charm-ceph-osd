from mock import call, patch
from test_utils import CharmTestCase
from ceph_hooks import check_for_upgrade


__author__ = 'Chris Holcombe <chris.holcombe@canonical.com>'


class UpgradeRollingTestCase(CharmTestCase):

    @patch('ceph_hooks.ceph.dirs_need_ownership_update')
    @patch('ceph_hooks.os.path.exists')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.emit_cephconf')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.ceph.roll_osd_cluster')
    def test_check_for_upgrade(self, roll_osd_cluster, hookenv,
                               emit_cephconf, version, exists,
                               dirs_need_ownership_update):
        dirs_need_ownership_update.return_value = False
        exists.return_value = True
        version.side_effect = ['firefly', 'hammer']

        self.test_config.set_previous('source', "cloud:trusty-juno")
        self.test_config.set('source', 'cloud:trusty-kilo')
        self.test_config.set('key', 'key')

        hookenv.config.side_effect = self.test_config
        check_for_upgrade()

        roll_osd_cluster.assert_called_with(new_version='hammer',
                                            upgrade_key='osd-upgrade')
        emit_cephconf.assert_has_calls([call(upgrading=True),
                                        call(upgrading=False)])
        exists.assert_called_with(
            "/var/lib/ceph/osd/ceph.client.osd-upgrade.keyring")

    @patch('ceph_hooks.ceph.dirs_need_ownership_update')
    @patch('ceph_hooks.os.path.exists')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.emit_cephconf')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.ceph.roll_osd_cluster')
    def test_resume_failed_upgrade(self, roll_osd_cluster,
                                   hookenv, emit_cephconf, version,
                                   exists,
                                   dirs_need_ownership_update):
        dirs_need_ownership_update.return_value = True
        exists.return_value = True
        version.side_effect = ['jewel', 'jewel']

        check_for_upgrade()

        roll_osd_cluster.assert_called_with(new_version='jewel',
                                            upgrade_key='osd-upgrade')
        emit_cephconf.assert_has_calls([call(upgrading=True),
                                        call(upgrading=False)])
        exists.assert_called_with(
            "/var/lib/ceph/osd/ceph.client.osd-upgrade.keyring")

    @patch('ceph_hooks.os.path.exists')
    @patch('ceph_hooks.ceph.resolve_ceph_version')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.ceph.roll_monitor_cluster')
    def test_check_for_upgrade_not_bootstrapped(self, roll_monitor_cluster,
                                                hookenv,
                                                version, exists):
        exists.return_value = False
        version.side_effect = ['firefly', 'hammer']

        self.test_config.set_previous('source', "cloud:trusty-juno")
        self.test_config.set('source', 'cloud:trusty-kilo')
        self.test_config.set('key', 'key')

        hookenv.config.side_effect = self.test_config
        check_for_upgrade()

        roll_monitor_cluster.assert_not_called()
        exists.assert_called_with(
            "/var/lib/ceph/osd/ceph.client.osd-upgrade.keyring")

    @patch('ceph_hooks.os.path.exists')
    @patch('ceph_hooks.ceph.dirs_need_ownership_update')
    @patch('ceph_hooks.add_source')
    @patch('ceph_hooks.ceph.is_bootstrapped')
    @patch('ceph_hooks.hookenv')
    @patch('ceph_hooks.ceph.roll_monitor_cluster')
    def test_check_for_upgrade_from_pike_to_queens(self, roll_monitor_cluster,
                                                   hookenv, is_bootstrapped,
                                                   add_source,
                                                   dirs_need_ownership_update,
                                                   exists):
        exists.return_value = True
        dirs_need_ownership_update.return_value = False
        is_bootstrapped.return_value = True
        hookenv.config.side_effect = self.test_config
        self.test_config.set('key', 'some-key')
        self.test_config.set_previous('source', 'cloud:xenial-pike')
        self.test_config.set('source', 'cloud:xenial-queens')
        check_for_upgrade()
        roll_monitor_cluster.assert_not_called()
        add_source.assert_called_with('cloud:xenial-queens', 'some-key')
