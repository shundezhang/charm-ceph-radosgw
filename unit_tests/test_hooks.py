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

from mock import (
    patch, call
)

from test_utils import (
    CharmTestCase,
)
from charmhelpers.contrib.openstack.ip import PUBLIC

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    with patch('charmhelpers.fetch.apt_install'):
        with patch('utils.register_configs'):
            import hooks as ceph_hooks

TO_PATCH = [
    'CONFIGS',
    'add_source',
    'apt_update',
    'apt_install',
    'apt_purge',
    'config',
    'cmp_pkgrevno',
    'execd_preinstall',
    'enable_pocket',
    'log',
    'open_port',
    'os',
    'relation_ids',
    'relation_set',
    'relation_get',
    'related_units',
    'status_set',
    'subprocess',
    'sys',
    'generate_ha_relation_data',
    'get_relation_ip',
    'disable_unused_apache_sites',
    'service_reload',
    'service_stop',
    'service_restart',
    'service',
    'setup_keystone_certs',
    'service_name',
    'socket',
    'restart_map',
    'systemd_based_radosgw',
    'request_per_unit_key',
    'get_certificate_request',
    'process_certificates',
]


class CephRadosGWTests(CharmTestCase):

    def setUp(self):
        super(CephRadosGWTests, self).setUp(ceph_hooks, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.test_config.set('source', 'distro')
        self.test_config.set('key', 'secretkey')
        self.test_config.set('use-syslog', False)
        self.cmp_pkgrevno.return_value = 0
        self.service_name.return_value = 'radosgw'
        self.request_per_unit_key.return_value = False
        self.systemd_based_radosgw.return_value = False

    def test_install_packages(self):
        ceph_hooks.install_packages()
        self.add_source.assert_called_with('distro', 'secretkey')
        self.assertTrue(self.apt_update.called)
        self.apt_purge.assert_called_with(['libapache2-mod-fastcgi'])

    def test_install(self):
        _install_packages = self.patch('install_packages')
        ceph_hooks.install()
        self.assertTrue(self.execd_preinstall.called)
        self.assertTrue(_install_packages.called)
        self.enable_pocket.assert_called_with('multiverse')
        self.os.makedirs.called_with('/var/lib/ceph/nss')

    @patch.object(ceph_hooks, 'certs_joined')
    @patch.object(ceph_hooks, 'update_nrpe_config')
    def test_config_changed(self, update_nrpe_config, mock_certs_joined):
        _install_packages = self.patch('install_packages')
        _relations = {
            'certificates': ['certificates:1']
        }
        self.relation_ids.side_effect = lambda name: _relations.get(name, [])
        ceph_hooks.config_changed()
        self.assertTrue(_install_packages.called)
        self.CONFIGS.write_all.assert_called_with()
        update_nrpe_config.assert_called_with()
        mock_certs_joined.assert_called_once_with('certificates:1')

    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: True)
    def test_mon_relation(self):
        _ceph = self.patch('ceph')
        _ceph.import_radosgw_key.return_value = True
        self.relation_get.return_value = 'seckey'
        self.socket.gethostname.return_value = 'testinghostname'
        ceph_hooks.mon_relation()
        self.relation_set.assert_not_called()
        self.service_restart.assert_called_once_with('radosgw')
        self.service.assert_called_once_with('enable', 'radosgw')
        _ceph.import_radosgw_key.assert_called_with('seckey',
                                                    name='rgw.testinghostname')
        self.CONFIGS.write_all.assert_called_with()

    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: True)
    def test_mon_relation_request_key(self):
        _ceph = self.patch('ceph')
        _ceph.import_radosgw_key.return_value = True
        self.relation_get.return_value = 'seckey'
        self.socket.gethostname.return_value = 'testinghostname'
        self.request_per_unit_key.return_value = True
        ceph_hooks.mon_relation()
        self.relation_set.assert_called_with(
            relation_id=None,
            key_name='rgw.testinghostname'
        )
        self.service_restart.assert_called_once_with('radosgw')
        self.service.assert_called_once_with('enable', 'radosgw')
        _ceph.import_radosgw_key.assert_called_with('seckey',
                                                    name='rgw.testinghostname')
        self.CONFIGS.write_all.assert_called_with()

    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: True)
    def test_mon_relation_nokey(self):
        _ceph = self.patch('ceph')
        _ceph.import_radosgw_key.return_value = False
        self.relation_get.return_value = None
        ceph_hooks.mon_relation()
        self.assertFalse(_ceph.import_radosgw_key.called)
        self.service_restart.assert_not_called()
        self.service.assert_not_called()
        self.CONFIGS.write_all.assert_called_with()

    @patch.object(ceph_hooks, 'send_request_if_needed')
    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: False)
    def test_mon_relation_send_broker_request(self,
                                              mock_send_request_if_needed):
        _ceph = self.patch('ceph')
        _ceph.import_radosgw_key.return_value = False
        self.relation_get.return_value = 'seckey'
        ceph_hooks.mon_relation()
        self.service_restart.assert_not_called()
        self.service.assert_not_called()
        self.assertFalse(_ceph.import_radosgw_key.called)
        self.assertFalse(self.CONFIGS.called)
        self.assertTrue(mock_send_request_if_needed.called)

    def test_gateway_relation(self):
        self.get_relation_ip.return_value = '10.0.0.1'
        ceph_hooks.gateway_relation()
        self.relation_set.assert_called_with(hostname='10.0.0.1', port=80)

    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'ceph-radosgw')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_identity_joined_early_version(self, _config):
        self.cmp_pkgrevno.return_value = -1
        ceph_hooks.identity_joined()
        self.sys.exit.assert_called_with(1)

    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'ceph-radosgw')
    @patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_identity_joined(self, _config, _resolve_address):
        self.related_units = ['unit/0']
        self.cmp_pkgrevno.return_value = 1
        _resolve_address.return_value = 'myserv'
        _config.side_effect = self.test_config.get
        self.test_config.set('region', 'region1')
        self.test_config.set('operator-roles', 'admin')
        ceph_hooks.identity_joined(relid='rid')
        self.relation_set.assert_called_with(
            service='swift',
            region='region1',
            public_url='http://myserv:80/swift/v1',
            internal_url='http://myserv:80/swift/v1',
            requested_roles='admin',
            relation_id='rid',
            admin_url='http://myserv:80/swift')

    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'ceph-radosgw')
    @patch('charmhelpers.contrib.openstack.ip.is_clustered')
    @patch('charmhelpers.contrib.openstack.ip.unit_get')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_identity_joined_public_name(self, _config, _unit_get,
                                         _is_clustered):
        self.related_units = ['unit/0']
        _config.side_effect = self.test_config.get
        self.test_config.set('os-public-hostname', 'files.example.com')
        _unit_get.return_value = 'myserv'
        _is_clustered.return_value = False
        ceph_hooks.identity_joined(relid='rid')
        self.relation_set.assert_called_with(
            service='swift',
            region='RegionOne',
            public_url='http://files.example.com:80/swift/v1',
            internal_url='http://myserv:80/swift/v1',
            requested_roles='Member,Admin',
            relation_id='rid',
            admin_url='http://myserv:80/swift')

    @patch.object(ceph_hooks, 'identity_joined')
    def test_identity_changed(self, mock_identity_joined):
        ceph_hooks.identity_changed()
        self.CONFIGS.write_all.assert_called_with()
        self.assertTrue(mock_identity_joined.called)

    @patch('charmhelpers.contrib.openstack.ip.is_clustered')
    @patch('charmhelpers.contrib.openstack.ip.unit_get')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_canonical_url_ipv6(self, _config, _unit_get, _is_clustered):
        ipv6_addr = '2001:db8:85a3:8d3:1319:8a2e:370:7348'
        _config.side_effect = self.test_config.get
        _unit_get.return_value = ipv6_addr
        _is_clustered.return_value = False
        self.assertEqual(ceph_hooks.canonical_url({}, PUBLIC),
                         'http://[%s]' % ipv6_addr)

    def test_cluster_joined(self):
        self.get_relation_ip.side_effect = ['10.0.0.1',
                                            '10.0.1.1',
                                            '10.0.2.1',
                                            '10.0.3.1']
        self.test_config.set('os-public-network', '10.0.0.0/24')
        self.test_config.set('os-admin-network', '10.0.1.0/24')
        self.test_config.set('os-internal-network', '10.0.2.0/24')

        ceph_hooks.cluster_joined()
        self.relation_set.assert_has_calls(
            [call(relation_id=None,
                  relation_settings={
                      'admin-address': '10.0.0.1',
                      'public-address': '10.0.2.1',
                      'internal-address': '10.0.1.1',
                      'private-address': '10.0.3.1'})])

    @patch.object(ceph_hooks, 'certs_changed')
    def test_cluster_changed(self, mock_certs_changed):
        _id_joined = self.patch('identity_joined')
        _relations = {
            'identity-service': ['rid'],
            'certificates': ['certificates:1'],
        }
        self.relation_ids.side_effect = lambda name: _relations.get(name)
        self.related_units.return_value = ['vault/0', 'vault/1']
        ceph_hooks.cluster_changed()
        self.CONFIGS.write_all.assert_called_with()
        _id_joined.assert_called_with(relid='rid')
        mock_certs_changed.assert_has_calls([
            call('certificates:1', 'vault/0'),
            call('certificates:1', 'vault/1')
        ])

    def test_ha_relation_joined(self):
        self.generate_ha_relation_data.return_value = {
            'test': 'data'
        }
        ceph_hooks.ha_relation_joined(relation_id='ha:1')
        self.relation_set.assert_called_with(
            relation_id='ha:1',
            test='data'
        )

    def test_ha_relation_changed(self):
        _id_joined = self.patch('identity_joined')
        self.relation_get.return_value = True
        self.relation_ids.return_value = ['rid']
        ceph_hooks.ha_relation_changed()
        _id_joined.assert_called_with(relid='rid')

    def test_certs_joined(self):
        self.get_certificate_request.return_value = {'foo': 'baa'}
        ceph_hooks.certs_joined('certificates:1')
        self.relation_set.assert_called_once_with(
            relation_id='certificates:1',
            relation_settings={'foo': 'baa'}
        )
        self.get_certificate_request.assert_called_once_with()

    @patch.object(ceph_hooks, 'configure_https')
    def test_certs_changed(self, mock_configure_https):
        ceph_hooks.certs_changed('certificates:1', 'vault/0')
        self.process_certificates.assert_called_once_with(
            'ceph-radosgw',
            'certificates:1',
            'vault/0'
        )
        mock_configure_https.assert_called_once_with()
