
from mock import call, patch, MagicMock
from test_utils import CharmTestCase, patch_open

dnsmock = MagicMock()
modules = {
    'dns': dnsmock,
    'dns.resolver': dnsmock,
}
module_patcher = patch.dict('sys.modules', modules)
module_patcher.start()
with patch('charmhelpers.fetch.apt_install'):
    import utils

_reg = utils.register_configs

utils.register_configs = MagicMock()

import hooks as ceph_hooks

utils.register_configs = _reg

TO_PATCH = [
    'add_source',
    'apt_update',
    'apt_install',
    'apt_purge',
    'config',
    'cmp_pkgrevno',
    'execd_preinstall',
    'enable_pocket',
    'get_host_ip',
    'get_iface_for_address',
    'get_netmask_for_address',
    'get_unit_hostname',
    'glob',
    'is_apache_24',
    'log',
    'lsb_release',
    'open_port',
    'os',
    'related_units',
    'relation_ids',
    'relation_set',
    'relation_get',
    'render_template',
    'resolve_address',
    'shutil',
    'subprocess',
    'sys',
    'unit_get',
]


class CephRadosGWTests(CharmTestCase):

    def setUp(self):
        super(CephRadosGWTests, self).setUp(ceph_hooks, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.test_config.set('source', 'distro')
        self.test_config.set('key', 'secretkey')
        self.test_config.set('use-syslog', False)

    def test_install_www_scripts(self):
        self.glob.glob.return_value = ['files/www/bob']
        ceph_hooks.install_www_scripts()
        self.shutil.copy.assert_called_with('files/www/bob', '/var/www/')

    def test_install_ceph_optimised_packages(self):
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'vivid'}
        fastcgi_source = (
            'http://gitbuilder.ceph.com/'
            'libapache-mod-fastcgi-deb-vivid-x86_64-basic/ref/master')
        apache_source = (
            'http://gitbuilder.ceph.com/'
            'apache2-deb-vivid-x86_64-basic/ref/master')
        calls = [
            call(fastcgi_source, key='6EAEAE2203C3951A'),
            call(apache_source, key='6EAEAE2203C3951A'),
        ]
        ceph_hooks.install_ceph_optimised_packages()
        self.add_source.assert_has_calls(calls)

    def test_install_packages(self):
        self.test_config.set('use-ceph-optimised-packages', '')
        ceph_hooks.install_packages()
        self.add_source.assert_called_with('distro', 'secretkey')
        self.apt_update.assert_called()
        self.apt_install.assert_called_with(['libapache2-mod-fastcgi',
                                             'apache2'], fatal=True)

    def test_install_optimised_packages_no_embedded(self):
        self.test_config.set('use-ceph-optimised-packages', True)
        self.test_config.set('use-embedded-webserver', False)
        _install_packages = self.patch('install_ceph_optimised_packages')
        ceph_hooks.install_packages()
        self.add_source.assert_called_with('distro', 'secretkey')
        self.apt_update.assert_called()
        _install_packages.assert_called()
        self.apt_install.assert_called_with(['libapache2-mod-fastcgi',
                                             'apache2'], fatal=True)

    def test_install_optimised_packages_embedded(self):
        self.test_config.set('use-ceph-optimised-packages', True)
        self.test_config.set('use-embedded-webserver', True)
        _install_packages = self.patch('install_ceph_optimised_packages')
        ceph_hooks.install_packages()
        self.add_source.assert_called_with('distro', 'secretkey')
        self.apt_update.assert_called()
        _install_packages.assert_called()
        self.apt_install.assert_called_with(['radosgw',
                                             'ntp',
                                             'haproxy'], fatal=True)
        self.apt_purge.assert_called_with(['libapache2-mod-fastcgi',
                                           'apache2'])

    def test_install(self):
        _install_packages = self.patch('install_packages')
        ceph_hooks.install()
        self.execd_preinstall.assert_called()
        _install_packages.assert_called()
        self.enable_pocket.assert_called_with('multiverse')
        self.os.makedirs.called_with('/var/lib/ceph/nss')

    def test_emit_cephconf(self):
        _get_keystone_conf = self.patch('get_keystone_conf')
        _get_auth = self.patch('get_auth')
        _get_mon_hosts = self.patch('get_mon_hosts')
        _get_auth.return_value = 'cephx'
        _get_keystone_conf.return_value = {'keystone_key': 'keystone_value'}
        _get_mon_hosts.return_value = ['10.0.0.1:6789', '10.0.0.2:6789']
        self.get_unit_hostname.return_value = 'bob'
        self.os.path.exists.return_value = False
        cephcontext = {
            'auth_supported': 'cephx',
            'mon_hosts': '10.0.0.1:6789 10.0.0.2:6789',
            'hostname': 'bob',
            'old_auth': False,
            'use_syslog': 'false',
            'keystone_key': 'keystone_value',
            'embedded_webserver': False,
        }
        self.cmp_pkgrevno.return_value = 1
        with patch_open() as (_open, _file):
            ceph_hooks.emit_cephconf()
            self.os.makedirs.assert_called_with('/etc/ceph')
            _open.assert_called_with('/etc/ceph/ceph.conf', 'w')
            self.render_template.assert_called_with('ceph.conf', cephcontext)

    def test_emit_apacheconf(self):
        self.is_apache_24.return_value = True
        self.unit_get.return_value = '10.0.0.1'
        apachecontext = {
            "hostname": '10.0.0.1',
        }
        vhost_file = '/etc/apache2/sites-available/rgw.conf'
        with patch_open() as (_open, _file):
            ceph_hooks.emit_apacheconf()
            _open.assert_called_with(vhost_file, 'w')
            self.render_template.assert_called_with('rgw', apachecontext)

    def test_apache_sites24(self):
        self.is_apache_24.return_value = True
        ceph_hooks.apache_sites()
        calls = [
            call(['a2dissite', '000-default']),
            call(['a2ensite', 'rgw']),
        ]
        self.subprocess.check_call.assert_has_calls(calls)

    def test_apache_sites22(self):
        self.is_apache_24.return_value = False
        ceph_hooks.apache_sites()
        calls = [
            call(['a2dissite', 'default']),
            call(['a2ensite', 'rgw']),
        ]
        self.subprocess.check_call.assert_has_calls(calls)

    def test_apache_modules(self):
        ceph_hooks.apache_modules()
        calls = [
            call(['a2enmod', 'fastcgi']),
            call(['a2enmod', 'rewrite']),
        ]
        self.subprocess.check_call.assert_has_calls(calls)

    def test_apache_reload(self):
        ceph_hooks.apache_reload()
        calls = [
            call(['service', 'apache2', 'reload']),
        ]
        self.subprocess.call.assert_has_calls(calls)

    def test_config_changed(self):
        _install_packages = self.patch('install_packages')
        _emit_cephconf = self.patch('emit_cephconf')
        _emit_apacheconf = self.patch('emit_apacheconf')
        _install_www_scripts = self.patch('install_www_scripts')
        _apache_sites = self.patch('apache_sites')
        _apache_modules = self.patch('apache_modules')
        _apache_reload = self.patch('apache_reload')
        ceph_hooks.config_changed()
        _install_packages.assert_called()
        _emit_cephconf.assert_called()
        _emit_apacheconf.assert_called()
        _install_www_scripts.assert_called()
        _apache_sites.assert_called()
        _apache_modules.assert_called()
        _apache_reload.assert_called()

    def test_get_mon_hosts(self):
        self.relation_ids.return_value = ['monrelid']
        self.related_units.return_value = ['monunit']
        self.relation_get.return_value = '10.0.0.1'
        self.get_host_ip.return_value = '10.0.0.1'
        self.assertEquals(ceph_hooks.get_mon_hosts(), ['10.0.0.1:6789'])

    def test_get_conf(self):
        self.relation_ids.return_value = ['monrelid']
        self.related_units.return_value = ['monunit']
        self.relation_get.return_value = 'bob'
        self.assertEquals(ceph_hooks.get_conf('key'), 'bob')

    def test_get_conf_nomatch(self):
        self.relation_ids.return_value = ['monrelid']
        self.related_units.return_value = ['monunit']
        self.relation_get.return_value = ''
        self.assertEquals(ceph_hooks.get_conf('key'), None)

    def test_get_auth(self):
        self.relation_ids.return_value = ['monrelid']
        self.related_units.return_value = ['monunit']
        self.relation_get.return_value = 'bob'
        self.assertEquals(ceph_hooks.get_auth(), 'bob')

    def test_get_keystone_conf(self):
        self.test_config.set('operator-roles', 'admin')
        self.test_config.set('cache-size', '42')
        self.test_config.set('revocation-check-interval', '21')
        self.relation_ids.return_value = ['idrelid']
        self.related_units.return_value = ['idunit']

        def _relation_get(key, unit, relid):
            ks_dict = {
                'auth_protocol': 'https',
                'auth_host': '10.0.0.2',
                'auth_port': '8090',
                'admin_token': 'sectocken',
            }
            return ks_dict[key]
        self.relation_get.side_effect = _relation_get
        self.assertEquals(ceph_hooks.get_keystone_conf(), {
            'auth_type': 'keystone',
            'auth_protocol': 'https',
            'admin_token': 'sectocken',
            'user_roles': 'admin',
            'auth_host': '10.0.0.2',
            'cache_size': '42',
            'auth_port': '8090',
            'revocation_check_interval': '21'})

    def test_get_keystone_conf_missinginfo(self):
        self.test_config.set('operator-roles', 'admin')
        self.test_config.set('cache-size', '42')
        self.test_config.set('revocation-check-interval', '21')
        self.relation_ids.return_value = ['idrelid']
        self.related_units.return_value = ['idunit']

        def _relation_get(key, unit, relid):
            ks_dict = {
                'auth_protocol': 'https',
                'auth_host': '10.0.0.2',
                'auth_port': '8090',
            }
            return ks_dict[key] if key in ks_dict else None
        self.relation_get.side_effect = _relation_get
        self.assertEquals(ceph_hooks.get_keystone_conf(), None)

    def test_mon_relation(self):
        _emit_cephconf = self.patch('emit_cephconf')
        _ceph = self.patch('ceph')
        _restart = self.patch('restart')
        self.relation_get.return_value = 'seckey'
        ceph_hooks.mon_relation()
        _restart.assert_called()
        _ceph.import_radosgw_key.assert_called_with('seckey')
        _emit_cephconf.assert_called()

    def test_mon_relation_nokey(self):
        _emit_cephconf = self.patch('emit_cephconf')
        _ceph = self.patch('ceph')
        _restart = self.patch('restart')
        self.relation_get.return_value = None
        ceph_hooks.mon_relation()
        self.assertFalse(_ceph.import_radosgw_key.called)
        self.assertFalse(_restart.called)
        _emit_cephconf.assert_called()

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

    def test_identity_joined_early_version(self):
        self.cmp_pkgrevno.return_value = -1
        ceph_hooks.identity_joined()
        self.sys.exit.assert_called_with(1)

    def test_identity_joined(self):
        self.cmp_pkgrevno.return_value = 1
        self.resolve_address.return_value = 'myserv'
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

    def test_identity_changed(self):
        _emit_cephconf = self.patch('emit_cephconf')
        _restart = self.patch('restart')
        ceph_hooks.identity_changed()
        _emit_cephconf.assert_called()
        _restart.assert_called()

    def test_canonical_url_ipv6(self):
        ipv6_addr = '2001:db8:85a3:8d3:1319:8a2e:370:7348'
        self.resolve_address.return_value = ipv6_addr
        self.assertEquals(ceph_hooks.canonical_url({}),
                          'http://[%s]' % ipv6_addr)

    @patch.object(ceph_hooks, 'CONFIGS')
    def test_cluster_changed(self, configs):
        _id_joined = self.patch('identity_joined')
        self.relation_ids.return_value = ['rid']
        ceph_hooks.cluster_changed()
        configs.write_all.assert_called()
        _id_joined.assert_called_with(relid='rid')

    def test_ha_relation_joined_no_vip(self):
        self.test_config.set('vip', '')
        ceph_hooks.ha_relation_joined()
        self.sys.exit.assert_called_with(1)

    def test_ha_relation_joined_vip(self):
        self.test_config.set('ha-bindiface', 'eth8')
        self.test_config.set('ha-mcastport', '5000')
        self.test_config.set('vip', '10.0.0.10')
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
            init_services={'res_cephrg_haproxy': 'haproxy'},
            corosync_bindiface='eth8',
            corosync_mcastport='5000',
            resource_params=resource_params,
            resources=resources,
            clones={'cl_cephrg_haproxy': 'res_cephrg_haproxy'})

    def test_ha_relation_changed(self):
        _id_joined = self.patch('identity_joined')
        self.relation_get.return_value = True
        self.relation_ids.return_value = ['rid']
        ceph_hooks.ha_relation_changed()
        _id_joined.assert_called_with(relid='rid')
