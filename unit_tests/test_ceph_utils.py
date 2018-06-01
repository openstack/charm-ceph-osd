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

import unittest

from mock import patch

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    import utils


class CephUtilsTestCase(unittest.TestCase):
    def setUp(self):
        super(CephUtilsTestCase, self).setUp()

    @patch('os.path.exists')
    @patch.object(utils, 'storage_list')
    @patch.object(utils, 'config')
    def test_get_journal_devices(self, mock_config, mock_storage_list,
                                 mock_os_path_exists):
        '''Devices returned as expected'''
        config = {'osd-journal': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        mock_os_path_exists.return_value = True
        devices = utils.get_journal_devices()
        mock_storage_list.assert_called()
        mock_os_path_exists.assert_called()
        self.assertEqual(devices, set(['/dev/vda', '/dev/vdb']))

    @patch('os.path.exists')
    @patch.object(utils, 'get_blacklist')
    @patch.object(utils, 'storage_list')
    @patch.object(utils, 'config')
    def test_get_journal_devices_blacklist(self, mock_config,
                                           mock_storage_list,
                                           mock_get_blacklist,
                                           mock_os_path_exists):
        '''Devices returned as expected when blacklist in effect'''
        config = {'osd-journal': '/dev/vda /dev/vdb'}
        mock_config.side_effect = lambda key: config[key]
        mock_storage_list.return_value = []
        mock_get_blacklist.return_value = ['/dev/vda']
        mock_os_path_exists.return_value = True
        devices = utils.get_journal_devices()
        mock_storage_list.assert_called()
        mock_os_path_exists.assert_called()
        mock_get_blacklist.assert_called()
        self.assertEqual(devices, set(['/dev/vdb']))
