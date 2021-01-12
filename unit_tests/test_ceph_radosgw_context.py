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

from mock import patch

import ceph_radosgw_context as context
import charmhelpers
import charmhelpers.contrib.storage.linux.ceph as ceph

from test_utils import CharmTestCase

TO_PATCH = [
    'config',
    'log',
    'relation_get',
    'relation_ids',
    'related_units',
    'cmp_pkgrevno',
    'socket',
    'unit_public_ip',
    'determine_api_port',
    'cmp_pkgrevno',
    'leader_get',
    'utils',
]


class HAProxyContextTests(CharmTestCase):
    def setUp(self):
        super(HAProxyContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.cmp_pkgrevno.return_value = 1

    @patch('charmhelpers.contrib.openstack.context.get_relation_ip')
    @patch('charmhelpers.contrib.openstack.context.mkdir')
    @patch('charmhelpers.contrib.openstack.context.local_unit')
    @patch('charmhelpers.contrib.openstack.context.config')
    @patch('charmhelpers.contrib.hahelpers.cluster.config_get')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    def test_ctxt(self, _harelation_ids, _ctxtrelation_ids, _haconfig,
                  _ctxtconfig, _local_unit, _mkdir, _get_relation_ip):
        _get_relation_ip.return_value = '10.0.0.10'
        _ctxtconfig.side_effect = self.test_config.get
        _haconfig.side_effect = self.test_config.get
        _harelation_ids.return_value = []
        haproxy_context = context.HAProxyContext()
        self.utils.listen_port.return_value = 80
        self.determine_api_port.return_value = 70
        expect = {
            'cephradosgw_bind_port': 70,
            'service_ports': {'cephradosgw-server': [80, 70]}
        }
        self.assertEqual(expect, haproxy_context())


class IdentityServiceContextTest(CharmTestCase):

    def setUp(self):
        super(IdentityServiceContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.maxDiff = None
        self.cmp_pkgrevno.return_value = 1
        self.leader_get.return_value = 'False'

    @patch.object(charmhelpers.contrib.openstack.context,
                  'filter_installed_packages', return_value=['absent-pkg'])
    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt(self, _log, _rids, _runits, _rget, _ctxt_comp,
                      _format_ipv6_addr, _filter_installed_packages,
                      jewel_installed=False, cmp_pkgrevno_side_effects=None):
        self.cmp_pkgrevno.side_effect = (cmp_pkgrevno_side_effects
                                         if cmp_pkgrevno_side_effects
                                         else [-1, -1])
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('admin-roles', 'Dart')
        self.test_config.set('cache-size', '42')
        self.relation_ids.return_value = ['identity-service:5']
        self.related_units.return_value = ['keystone/0']
        _format_ipv6_addr.return_value = False
        _rids.return_value = 'rid1'
        _runits.return_value = 'runit'
        _ctxt_comp.return_value = True
        id_data = {
            'service_port': 9876,
            'service_host': '127.0.0.4',
            'service_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'service_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        expect = {
            'admin_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'admin_password': 'adminpass',
            'admin_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'admin_tenant_name': 'ten',
            'admin_user': 'admin',
            'api_version': '2.0',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'auth_protocol': 'http',
            'auth_type': 'keystone',
            'namespace_tenants': False,
            'cache_size': '42',
            'service_host': '127.0.0.4',
            'service_port': 9876,
            'service_protocol': 'http',
        }
        if cmp_pkgrevno_side_effects and cmp_pkgrevno_side_effects[1] >= 0:
            expect['user_roles'] = 'Babel'
            expect['admin_roles'] = 'Dart'
        else:
            expect['user_roles'] = 'Babel,Dart'
        if jewel_installed:
            expect['auth_keystone_v3_supported'] = True
        self.assertEqual(expect, ids_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context,
                  'filter_installed_packages', return_value=['absent-pkg'])
    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_with_namespace(self, _log, _rids, _runits, _rget,
                                     _ctxt_comp, _format_ipv6_addr,
                                     _filter_installed_packages,
                                     jewel_installed=False,
                                     cmp_pkgrevno_side_effects=None):
        self.cmp_pkgrevno.side_effect = (cmp_pkgrevno_side_effects
                                         if cmp_pkgrevno_side_effects
                                         else [-1, -1])
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('admin-roles', 'Dart')
        self.test_config.set('cache-size', '42')
        self.relation_ids.return_value = ['identity-service:5']
        self.related_units.return_value = ['keystone/0']
        _format_ipv6_addr.return_value = False
        _rids.return_value = 'rid1'
        _runits.return_value = 'runit'
        _ctxt_comp.return_value = True
        self.leader_get.return_value = 'True'
        id_data = {
            'service_port': 9876,
            'service_host': '127.0.0.4',
            'service_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'service_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        expect = {
            'admin_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'admin_password': 'adminpass',
            'admin_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'admin_tenant_name': 'ten',
            'admin_user': 'admin',
            'api_version': '2.0',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'auth_protocol': 'http',
            'auth_type': 'keystone',
            'namespace_tenants': True,
            'cache_size': '42',
            'service_host': '127.0.0.4',
            'service_port': 9876,
            'service_protocol': 'http',
        }
        if cmp_pkgrevno_side_effects and cmp_pkgrevno_side_effects[1] >= 0:
            expect['user_roles'] = 'Babel'
            expect['admin_roles'] = 'Dart'
        else:
            expect['user_roles'] = 'Babel,Dart'
        if jewel_installed:
            expect['auth_keystone_v3_supported'] = True
        self.assertEqual(expect, ids_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context,
                  'filter_installed_packages', return_value=['absent-pkg'])
    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_missing_admin_domain_id(
            self, _log, _rids, _runits, _rget, _ctxt_comp, _format_ipv6_addr,
            _filter_installed_packages, jewel_installed=False):
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('admin-roles', 'Dart')
        self.test_config.set('cache-size', '42')
        self.relation_ids.return_value = ['identity-service:5']
        self.related_units.return_value = ['keystone/0']
        _format_ipv6_addr.return_value = False
        _rids.return_value = ['rid1']
        _runits.return_value = ['runit']
        _ctxt_comp.return_value = True
        self.cmp_pkgrevno.return_value = -1
        if jewel_installed:
            self.cmp_pkgrevno.return_value = 0
        id_data = {
            'service_port': 9876,
            'service_host': '127.0.0.4',
            'service_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        expect = {
            'admin_password': 'adminpass',
            'admin_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'admin_tenant_name': 'ten',
            'admin_user': 'admin',
            'api_version': '2.0',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'auth_protocol': 'http',
            'auth_type': 'keystone',
            'namespace_tenants': False,
            'cache_size': '42',
            'service_host': '127.0.0.4',
            'service_port': 9876,
            'service_protocol': 'http',
            'user_roles': 'Babel,Dart',
        }
        if jewel_installed:
            expect['auth_keystone_v3_supported'] = True
        self.assertEqual(expect, ids_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context,
                  'filter_installed_packages', return_value=['absent-pkg'])
    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_v3(
            self, _log, _rids, _runits, _rget, _ctxt_comp, _format_ipv6_addr,
            _filter_installed_packages, jewel_installed=False):
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('admin-roles', 'Dart')
        self.test_config.set('cache-size', '42')
        self.relation_ids.return_value = ['identity-service:5']
        self.related_units.return_value = ['keystone/0']
        _format_ipv6_addr.return_value = False
        _rids.return_value = ['rid1']
        _runits.return_value = ['runit']
        _ctxt_comp.return_value = True
        self.cmp_pkgrevno.return_value = -1
        if jewel_installed:
            self.cmp_pkgrevno.return_value = 0
        id_data = {
            'service_port': 9876,
            'service_host': '127.0.0.4',
            'service_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'service_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'service_domain': 'service_domain',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
            'api_version': '3',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        expect = {
            'admin_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'admin_domain_name': 'service_domain',
            'admin_password': 'adminpass',
            'admin_tenant_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'admin_tenant_name': 'ten',
            'admin_user': 'admin',
            'api_version': '3',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'auth_protocol': 'http',
            'auth_type': 'keystone',
            'namespace_tenants': False,
            'cache_size': '42',
            'service_domain_id': '8e50f28a556911e8aaeed33789425d23',
            'service_host': '127.0.0.4',
            'service_port': 9876,
            'service_project_id': '2852107b8f8f473aaf0d769c7bbcf86b',
            'service_protocol': 'http',
            'user_roles': 'Babel,Dart',
        }
        if jewel_installed:
            expect['auth_keystone_v3_supported'] = True
        self.assertEqual(expect, ids_ctxt())

    def test_ids_ctxt_jewel(self):
        self.test_ids_ctxt(jewel_installed=True,
                           cmp_pkgrevno_side_effects=[0, -1])

    def test_ids_ctxt_luminous(self):
        self.test_ids_ctxt(jewel_installed=True,
                           cmp_pkgrevno_side_effects=[1, 0])

    @patch.object(charmhelpers.contrib.openstack.context,
                  'filter_installed_packages', return_value=['absent-pkg'])
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_no_rels(self, _log, _rids, _filter_installed_packages):
        _rids.return_value = []
        ids_ctxt = context.IdentityServiceContext()
        self.assertEqual(ids_ctxt(), None)


class MonContextTest(CharmTestCase):

    def setUp(self):
        super(MonContextTest, self).setUp(context, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.unit_public_ip.return_value = '10.255.255.255'
        self.cmp_pkgrevno.return_value = 1

    @patch.object(ceph, 'config', lambda *args:
                  '{"client.radosgw.gateway": {"rgw init timeout": 60}}')
    @patch.object(context, 'ensure_host_resolvable_v6')
    def test_ctxt(self, mock_ensure_rsv_v6):
        self.socket.gethostname.return_value = 'testhost'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return 'cephx'
            elif attr == 'rgw.testhost_key':
                return 'testkey'
            elif attr == 'fsid':
                return 'testfsid'

        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        self.determine_api_port.return_value = 70
        expect = {
            'auth_supported': 'cephx',
            'hostname': 'testhost',
            'mon_hosts': '10.5.4.1 10.5.4.2 10.5.4.3',
            'old_auth': False,
            'systemd_rgw': True,
            'unit_public_ip': '10.255.255.255',
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70,
            'client_radosgw_gateway': {'rgw init timeout': 60},
            'ipv6': False,
            'rgw_zone': 'default',
            'fsid': 'testfsid',
        }
        self.assertEqual(expect, mon_ctxt())
        self.assertFalse(mock_ensure_rsv_v6.called)

        self.test_config.set('prefer-ipv6', True)
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']
        expect['ipv6'] = True
        expect['port'] = "[::]:%s" % (70)
        self.assertEqual(expect, mon_ctxt())
        self.assertTrue(mock_ensure_rsv_v6.called)

    @patch.object(ceph, 'config', lambda *args:
                  '{"client.radosgw.gateway": {"rgw init timeout": 60}}')
    @patch.object(context, 'ensure_host_resolvable_v6')
    def test_list_of_addresses_from_ceph_proxy(self, mock_ensure_rsv_v6):
        self.socket.gethostname.return_value = 'testhost'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1 10.5.4.2 10.5.4.3']
        self.cmp_pkgrevno.return_value = 1

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return 'cephx'
            elif attr == 'rgw.testhost_key':
                return 'testkey'
            elif attr == 'fsid':
                return 'testfsid'

        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph-proxy/0']
        self.determine_api_port.return_value = 70
        expect = {
            'auth_supported': 'cephx',
            'hostname': 'testhost',
            'mon_hosts': '10.5.4.1 10.5.4.2 10.5.4.3',
            'old_auth': False,
            'systemd_rgw': True,
            'unit_public_ip': '10.255.255.255',
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70,
            'client_radosgw_gateway': {'rgw init timeout': 60},
            'ipv6': False,
            'rgw_zone': 'default',
            'fsid': 'testfsid',
        }
        self.assertEqual(expect, mon_ctxt())
        self.assertFalse(mock_ensure_rsv_v6.called)

        self.test_config.set('prefer-ipv6', True)
        addresses = ['10.5.4.1 10.5.4.2 10.5.4.3']
        expect['ipv6'] = True
        expect['port'] = "[::]:%s" % (70)
        self.assertEqual(expect, mon_ctxt())
        self.assertTrue(mock_ensure_rsv_v6.called)

    @patch.object(ceph, 'config', lambda *args:
                  '{"client.radosgw.gateway": {"rgw init timeout": 60}}')
    def test_ctxt_missing_data(self):
        self.socket.gethostname.return_value = 'testhost'
        mon_ctxt = context.MonContext()
        self.relation_get.return_value = None
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        self.assertEqual({}, mon_ctxt())

    @patch.object(ceph, 'config', lambda *args:
                  '{"client.radosgw.gateway": {"rgw init timeout": 60}}')
    def test_ctxt_inconsistent_auths(self):
        self.socket.gethostname.return_value = 'testhost'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']
        auths = ['cephx', 'cephy', 'cephz']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return auths.pop()
            elif attr == 'rgw.testhost_key':
                return 'testkey'
            elif attr == 'fsid':
                return 'testfsid'

        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        self.determine_api_port.return_value = 70
        expect = {
            'auth_supported': 'none',
            'hostname': 'testhost',
            'mon_hosts': '10.5.4.1 10.5.4.2 10.5.4.3',
            'old_auth': False,
            'systemd_rgw': True,
            'unit_public_ip': '10.255.255.255',
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70,
            'client_radosgw_gateway': {'rgw init timeout': 60},
            'ipv6': False,
            'rgw_zone': 'default',
            'fsid': 'testfsid',
        }
        self.assertEqual(expect, mon_ctxt())

    @patch.object(ceph, 'config', lambda *args:
                  '{"client.radosgw.gateway": {"rgw init timeout": 60}}')
    def test_ctxt_consistent_auths(self):
        self.socket.gethostname.return_value = 'testhost'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']
        auths = ['cephx', 'cephx', 'cephx']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return auths.pop()
            elif attr == 'rgw.testhost_key':
                return 'testkey'
            elif attr == 'fsid':
                return 'testfsid'

        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        self.determine_api_port.return_value = 70
        expect = {
            'auth_supported': 'cephx',
            'hostname': 'testhost',
            'mon_hosts': '10.5.4.1 10.5.4.2 10.5.4.3',
            'old_auth': False,
            'systemd_rgw': True,
            'unit_public_ip': '10.255.255.255',
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70,
            'client_radosgw_gateway': {'rgw init timeout': 60},
            'ipv6': False,
            'rgw_zone': 'default',
            'fsid': 'testfsid',
        }
        self.assertEqual(expect, mon_ctxt())


class ApacheContextTest(CharmTestCase):

    def setUp(self):
        super(ApacheContextTest, self).setUp(context, TO_PATCH)
        self.config.side_effect = self.test_config.get
