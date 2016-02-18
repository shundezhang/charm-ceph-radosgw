from mock import patch

import ceph_radosgw_context as context

from test_utils import CharmTestCase
import charmhelpers

TO_PATCH = [
    'config',
    'log',
    'relation_get',
    'relation_ids',
    'related_units',
    'cmp_pkgrevno',
    'socket',
]


class HAProxyContextTests(CharmTestCase):
    def setUp(self):
        super(HAProxyContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get

    @patch('charmhelpers.contrib.openstack.context.unit_get')
    @patch('charmhelpers.contrib.openstack.context.local_unit')
    @patch('charmhelpers.contrib.openstack.context.get_host_ip')
    @patch('charmhelpers.contrib.openstack.context.config')
    @patch('charmhelpers.contrib.hahelpers.cluster.config_get')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    def test_ctxt(self, _harelation_ids, _ctxtrelation_ids, _haconfig,
                  _ctxtconfig, _get_host_ip, _local_unit, _unit_get):
        _get_host_ip.return_value = '10.0.0.10'
        _unit_get.return_value = '10.0.0.10'
        _ctxtconfig.side_effect = self.test_config.get
        _haconfig.side_effect = self.test_config.get
        _harelation_ids.return_value = []
        haproxy_context = context.HAProxyContext()
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

    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt(self, _log, _rids, _runits, _rget, _ctxt_comp,
                      _format_ipv6_addr):
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('cache-size', '42')
        self.test_config.set('revocation-check-interval', '7500000')
        self.test_relation.set({'admin_token': 'ubuntutesting'})
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
            'admin_token': 'ubuntutesting',
            'admin_user': 'admin',
            'api_version': '2.0',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'auth_protocol': 'http',
            'auth_type': 'keystone',
            'cache_size': '42',
            'revocation_check_interval': '7500000',
            'service_host': '127.0.0.4',
            'service_port': 9876,
            'service_protocol': 'http',
            'user_roles': 'Babel',
        }
        self.assertEqual(expect, ids_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_no_admin_token(self, _log, _rids, _runits, _rget,
                                     _ctxt_comp, _format_ipv6_addr):
        self.test_config.set('operator-roles', 'Babel')
        self.test_config.set('cache-size', '42')
        self.test_config.set('revocation-check-interval', '7500000')
        self.test_relation.set({})
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
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        self.assertEqual({}, ids_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_no_rels(self, _log, _rids):
        _rids.return_value = []
        ids_ctxt = context.IdentityServiceContext()
        self.assertEquals(ids_ctxt(), None)


class MonContextTest(CharmTestCase):

    def setUp(self):
        super(MonContextTest, self).setUp(context, TO_PATCH)
        self.config.side_effect = self.test_config.get

    def test_ctxt(self):
        self.socket.gethostname.return_value = '10.0.0.10'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return 'cephx'
        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        expect = {
            'auth_supported': 'cephx',
            'embedded_webserver': False,
            'disable_100_continue': True,
            'hostname': '10.0.0.10',
            'mon_hosts': '10.5.4.1:6789 10.5.4.2:6789 10.5.4.3:6789',
            'old_auth': False,
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70
        }
        self.assertEqual(expect, mon_ctxt())

    def test_ctxt_missing_data(self):
        self.socket.gethostname.return_value = '10.0.0.10'
        mon_ctxt = context.MonContext()
        self.relation_get.return_value = None
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        self.assertEqual({}, mon_ctxt())

    def test_ctxt_inconsistent_auths(self):
        self.socket.gethostname.return_value = '10.0.0.10'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']
        auths = ['cephx', 'cephy', 'cephz']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return auths.pop()
        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        expect = {
            'auth_supported': 'none',
            'embedded_webserver': False,
            'disable_100_continue': True,
            'hostname': '10.0.0.10',
            'mon_hosts': '10.5.4.1:6789 10.5.4.2:6789 10.5.4.3:6789',
            'old_auth': False,
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70
        }
        self.assertEqual(expect, mon_ctxt())

    def test_ctxt_consistent_auths(self):
        self.socket.gethostname.return_value = '10.0.0.10'
        mon_ctxt = context.MonContext()
        addresses = ['10.5.4.1', '10.5.4.2', '10.5.4.3']
        auths = ['cephx', 'cephx', 'cephx']

        def _relation_get(attr, unit, rid):
            if attr == 'ceph-public-address':
                return addresses.pop()
            elif attr == 'auth':
                return auths.pop()
        self.relation_get.side_effect = _relation_get
        self.relation_ids.return_value = ['mon:6']
        self.related_units.return_value = ['ceph/0', 'ceph/1', 'ceph/2']
        expect = {
            'auth_supported': 'cephx',
            'embedded_webserver': False,
            'disable_100_continue': True,
            'hostname': '10.0.0.10',
            'mon_hosts': '10.5.4.1:6789 10.5.4.2:6789 10.5.4.3:6789',
            'old_auth': False,
            'use_syslog': 'false',
            'loglevel': 1,
            'port': 70
        }
        self.assertEqual(expect, mon_ctxt())
