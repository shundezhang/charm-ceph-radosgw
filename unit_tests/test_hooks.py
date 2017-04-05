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
    'get_iface_for_address',
    'get_netmask_for_address',
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
    'unit_get',
    'get_hacluster_config',
    'update_dns_ha_resource_params',
]


class CephRadosGWTests(CharmTestCase):

    def setUp(self):
        super(CephRadosGWTests, self).setUp(ceph_hooks, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.test_config.set('source', 'distro')
        self.test_config.set('key', 'secretkey')
        self.test_config.set('use-syslog', False)

    def test_install_packages(self):
        ceph_hooks.install_packages()
        self.add_source.assert_called_with('distro', 'secretkey')
        self.assertTrue(self.apt_update.called)
        self.apt_purge.assert_called_with(['libapache2-mod-fastcgi',
                                           'apache2'])

    def test_install(self):
        _install_packages = self.patch('install_packages')
        ceph_hooks.install()
        self.assertTrue(self.execd_preinstall.called)
        self.assertTrue(_install_packages.called)
        self.enable_pocket.assert_called_with('multiverse')
        self.os.makedirs.called_with('/var/lib/ceph/nss')

    @patch.object(ceph_hooks, 'update_nrpe_config')
    def test_config_changed(self, update_nrpe_config):
        _install_packages = self.patch('install_packages')
        ceph_hooks.config_changed()
        self.assertTrue(_install_packages.called)
        self.CONFIGS.write_all.assert_called_with()
        update_nrpe_config.assert_called_with()

    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: True)
    def test_mon_relation(self):
        _ceph = self.patch('ceph')
        _restart = self.patch('restart')
        self.relation_get.return_value = 'seckey'
        ceph_hooks.mon_relation()
        self.assertTrue(_restart.called)
        _ceph.import_radosgw_key.assert_called_with('seckey')
        self.CONFIGS.write_all.assert_called_with()

    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: True)
    def test_mon_relation_nokey(self):
        _ceph = self.patch('ceph')
        _restart = self.patch('restart')
        self.relation_get.return_value = None
        ceph_hooks.mon_relation()
        self.assertFalse(_ceph.import_radosgw_key.called)
        self.assertFalse(_restart.called)
        self.CONFIGS.write_all.assert_called_with()

    @patch.object(ceph_hooks, 'send_request_if_needed')
    @patch.object(ceph_hooks, 'is_request_complete',
                  lambda *args, **kwargs: False)
    def test_mon_relation_send_broker_request(self,
                                              mock_send_request_if_needed):
        _ceph = self.patch('ceph')
        _restart = self.patch('restart')
        self.relation_get.return_value = 'seckey'
        ceph_hooks.mon_relation()
        self.assertFalse(_restart.called)
        self.assertFalse(_ceph.import_radosgw_key.called)
        self.assertFalse(self.CONFIGS.called)
        self.assertTrue(mock_send_request_if_needed.called)

    def test_gateway_relation(self):
        self.unit_get.return_value = 'myserver'
        ceph_hooks.gateway_relation()
        self.relation_set.assert_called_with(hostname='myserver', port=80)

    def test_start(self):
        ceph_hooks.start()
        cmd = ['service', 'radosgw', 'start']
        self.subprocess.call.assert_called_with(cmd)

    def test_stop(self):
        ceph_hooks.stop()
        cmd = ['service', 'radosgw', 'stop']
        self.subprocess.call.assert_called_with(cmd)

    def test_restart(self):
        ceph_hooks.restart()
        cmd = ['service', 'radosgw', 'restart']
        self.subprocess.call.assert_called_with(cmd)

    @patch.object(ceph_hooks, 'setup_keystone_certs')
    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'ceph-radosgw')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_identity_joined_early_version(self, _config,
                                           mock_setup_keystone_certs):
        self.cmp_pkgrevno.return_value = -1
        ceph_hooks.identity_joined()
        self.assertTrue(mock_setup_keystone_certs.called)
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
        self.unit_get.return_value = 'myserv'
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
        _restart = self.patch('restart')
        ceph_hooks.identity_changed()
        self.CONFIGS.write_all.assert_called_with()
        self.assertTrue(_restart.called)
        self.assertTrue(mock_identity_joined.called)

    @patch('charmhelpers.contrib.openstack.ip.is_clustered')
    @patch('charmhelpers.contrib.openstack.ip.unit_get')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_canonical_url_ipv6(self, _config, _unit_get, _is_clustered):
        ipv6_addr = '2001:db8:85a3:8d3:1319:8a2e:370:7348'
        _config.side_effect = self.test_config.get
        _unit_get.return_value = ipv6_addr
        _is_clustered.return_value = False
        self.assertEquals(ceph_hooks.canonical_url({}, PUBLIC),
                          'http://[%s]' % ipv6_addr)

    @patch.object(ceph_hooks, 'get_address_in_network')
    def test_cluster_joined(self, mock_get_addr):
        addrs = {'10.0.0.0/24': '10.0.0.1',
                 '10.0.1.0/24': '10.0.1.1',
                 '10.0.2.0/24': '10.0.2.1'}

        def fake_get_address_in_network(network):
            return addrs.get(network)

        mock_get_addr.side_effect = fake_get_address_in_network

        self.test_config.set('os-public-network', '10.0.0.0/24')
        self.test_config.set('os-admin-network', '10.0.1.0/24')
        self.test_config.set('os-internal-network', '10.0.2.0/24')

        ceph_hooks.cluster_joined()
        self.relation_set.assert_has_calls(
            [call(relation_id=None,
                  **{'admin-address': '10.0.1.1',
                     'internal-address': '10.0.2.1',
                     'public-address': '10.0.0.1'})])

    def test_cluster_changed(self):
        _id_joined = self.patch('identity_joined')
        self.relation_ids.return_value = ['rid']
        ceph_hooks.cluster_changed()
        self.CONFIGS.write_all.assert_called_with()
        _id_joined.assert_called_with(relid='rid')

    def test_ha_relation_joined_vip(self):
        self.test_config.set('ha-bindiface', 'eth8')
        self.test_config.set('ha-mcastport', '5000')
        self.test_config.set('vip', '10.0.0.10')
        self.get_hacluster_config.return_value = {
            'vip': '10.0.0.10',
            'ha-bindiface': 'eth8',
            'ha-mcastport': '5000',
        }
        self.get_iface_for_address.return_value = 'eth7'
        self.get_netmask_for_address.return_value = '255.255.0.0'
        ceph_hooks.ha_relation_joined()
        eth_params = ('params ip="10.0.0.10" cidr_netmask="255.255.0.0" '
                      'nic="eth7"')
        resources = {'res_cephrg_haproxy': 'lsb:haproxy',
                     'res_cephrg_eth7_vip': 'ocf:heartbeat:IPaddr2'}
        resource_params = {'res_cephrg_haproxy': 'op monitor interval="5s"',
                           'res_cephrg_eth7_vip': eth_params}
        self.relation_set.assert_called_with(
            relation_id=None,
            init_services={'res_cephrg_haproxy': 'haproxy'},
            corosync_bindiface='eth8',
            corosync_mcastport='5000',
            resource_params=resource_params,
            resources=resources,
            clones={'cl_cephrg_haproxy': 'res_cephrg_haproxy'})

    def test_ha_joined_dns_ha(self):
        def _fake_update(resources, resource_params, relation_id=None):
            resources.update({'res_cephrg_public_hostname': 'ocf:maas:dns'})
            resource_params.update({'res_cephrg_public_hostname':
                                    'params fqdn="keystone.maas" '
                                    'ip_address="10.0.0.1"'})

        self.test_config.set('dns-ha', True)
        self.get_hacluster_config.return_value = {
            'vip': None,
            'ha-bindiface': 'em0',
            'ha-mcastport': '8080',
            'os-admin-hostname': None,
            'os-internal-hostname': None,
            'os-public-hostname': 'keystone.maas',
        }
        args = {
            'relation_id': None,
            'corosync_bindiface': 'em0',
            'corosync_mcastport': '8080',
            'init_services': {'res_cephrg_haproxy': 'haproxy'},
            'resources': {'res_cephrg_public_hostname': 'ocf:maas:dns',
                          'res_cephrg_haproxy': 'lsb:haproxy'},
            'resource_params': {
                'res_cephrg_public_hostname': 'params fqdn="keystone.maas" '
                                              'ip_address="10.0.0.1"',
                'res_cephrg_haproxy': 'op monitor interval="5s"'},
            'clones': {'cl_cephrg_haproxy': 'res_cephrg_haproxy'}
        }
        self.update_dns_ha_resource_params.side_effect = _fake_update

        ceph_hooks.ha_relation_joined()
        self.assertTrue(self.update_dns_ha_resource_params.called)
        self.relation_set.assert_called_with(**args)

    def test_ha_relation_changed(self):
        _id_joined = self.patch('identity_joined')
        self.relation_get.return_value = True
        self.relation_ids.return_value = ['rid']
        ceph_hooks.ha_relation_changed()
        _id_joined.assert_called_with(relid='rid')
