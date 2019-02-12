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

import sys

from mock import patch, call, MagicMock

# python-apt is not installed as part of test-requirements but is imported by
# some charmhelpers modules so create a fake import.
mock_apt = MagicMock()
mock_apt.apt_pkg = MagicMock()
sys.modules['apt'] = mock_apt
sys.modules['apt_pkg'] = mock_apt.apt_pkg

import ceph_rgw as ceph  # noqa
import utils  # noqa

from test_utils import CharmTestCase  # noqa

TO_PATCH = [
    'config',
    'os',
    'subprocess',
    'mkdir',
]


class CephRadosGWCephTests(CharmTestCase):
    def setUp(self):
        super(CephRadosGWCephTests, self).setUp(ceph, TO_PATCH)
        self.config.side_effect = self.test_config.get

    def test_import_radosgw_key(self):
        self.os.path.exists.return_value = False
        self.os.path.join.return_value = '/etc/ceph/keyring.rados.gateway'
        ceph.import_radosgw_key('mykey')
        cmd = [
            'ceph-authtool',
            '/etc/ceph/keyring.rados.gateway',
            '--create-keyring',
            '--name=client.radosgw.gateway',
            '--add-key=mykey'
        ]
        self.subprocess.check_call.assert_has_calls([
            call(cmd),
            call(['chown', 'root:root',
                  '/etc/ceph/keyring.rados.gateway'])
        ])

    @patch('charmhelpers.contrib.storage.linux.ceph.CephBrokerRq'
           '.add_op_create_pool')
    def test_create_rgw_pools_rq_with_prefix(self, mock_broker):
        self.test_config.set('rgw-lightweight-pool-pg-num', 10)
        self.test_config.set('ceph-osd-replication-count', 3)
        self.test_config.set('rgw-buckets-pool-weight', 19)
        ceph.get_create_rgw_pools_rq(prefix='us-east')
        mock_broker.assert_has_calls([
            call(replica_count=3, weight=19, name='us-east.rgw.buckets',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw.root',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw.control',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw.gc',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw.buckets.index',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.rgw.buckets.extra',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.log',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.intent-log',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.usage',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.users',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.users.email',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.users.swift',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='us-east.users.uid',
                 group='objects'),
            call(pg_num=10, replica_count=3, name='.rgw.root',
                 group='objects')]
        )

    @patch.object(mock_apt.apt_pkg, 'version_compare', lambda *args: -1)
    @patch('charmhelpers.contrib.storage.linux.ceph.CephBrokerRq'
           '.add_op_create_pool')
    def test_create_rgw_pools_rq_no_prefix_pre_jewel(self, mock_broker):
        self.test_config.set('rgw-lightweight-pool-pg-num', -1)
        self.test_config.set('ceph-osd-replication-count', 3)
        self.test_config.set('rgw-buckets-pool-weight', 19)
        ceph.get_create_rgw_pools_rq(prefix=None)
        mock_broker.assert_has_calls([
            call(weight=19, replica_count=3, name='.rgw.buckets',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.rgw',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.rgw.root',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.rgw.control',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.rgw.gc',
                 group='objects'),
            call(weight=1.00, replica_count=3, name='.rgw.buckets.index',
                 group='objects'),
            call(weight=1.00, replica_count=3, name='.rgw.buckets.extra',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.log',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.intent-log',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.usage',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.users',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.users.email',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.users.swift',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.users.uid',
                 group='objects')]
        )

    @patch.object(mock_apt.apt_pkg, 'version_compare', lambda *args: 0)
    @patch('charmhelpers.contrib.storage.linux.ceph.CephBrokerRq'
           '.add_op_request_access_to_group')
    @patch('charmhelpers.contrib.storage.linux.ceph.CephBrokerRq'
           '.add_op_create_pool')
    def test_create_rgw_pools_rq_no_prefix_post_jewel(self, mock_broker,
                                                      mock_request_access):
        self.test_config.set('rgw-lightweight-pool-pg-num', -1)
        self.test_config.set('ceph-osd-replication-count', 3)
        self.test_config.set('rgw-buckets-pool-weight', 19)
        self.test_config.set('restrict-ceph-pools', True)
        ceph.get_create_rgw_pools_rq(prefix=None)
        mock_broker.assert_has_calls([
            call(weight=19, replica_count=3, name='default.rgw.buckets',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.rgw',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.rgw.root',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.rgw.control',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.rgw.gc',
                 group='objects'),
            call(weight=1.00, replica_count=3,
                 name='default.rgw.buckets.index',
                 group='objects'),
            call(weight=1.00, replica_count=3,
                 name='default.rgw.buckets.extra',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.log',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.intent-log',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.usage',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.users',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.users.email',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.users.swift',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='default.users.uid',
                 group='objects'),
            call(weight=0.10, replica_count=3, name='.rgw.root',
                 group='objects')]
        )
        mock_request_access.assert_called_with(key_name='radosgw.gateway',
                                               name='objects',
                                               permission='rwx')

    @patch.object(mock_apt.apt_pkg, 'version_compare', lambda *args: -1)
    @patch.object(utils, 'lsb_release',
                  lambda: {'DISTRIB_CODENAME': 'trusty'})
    @patch.object(utils, 'add_source')
    @patch.object(utils, 'apt_update')
    @patch.object(utils, 'apt_install')
    def test_setup_ipv6_install_backports(self, mock_add_source,
                                          mock_apt_update,
                                          mock_apt_install):
        utils.setup_ipv6()
        self.assertTrue(mock_apt_update.called)
        self.assertTrue(mock_apt_install.called)

    @patch.object(mock_apt.apt_pkg, 'version_compare', lambda *args: 0)
    @patch.object(utils, 'lsb_release',
                  lambda: {'DISTRIB_CODENAME': 'trusty'})
    @patch.object(utils, 'add_source')
    @patch.object(utils, 'apt_update')
    @patch.object(utils, 'apt_install')
    def test_setup_ipv6_not_install_backports(self, mock_add_source,
                                              mock_apt_update,
                                              mock_apt_install):
        utils.setup_ipv6()
        self.assertFalse(mock_apt_update.called)
        self.assertFalse(mock_apt_install.called)
