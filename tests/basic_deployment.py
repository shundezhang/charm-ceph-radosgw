#!/usr/bin/python

import amulet
from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)
from charmhelpers.contrib.openstack.amulet.utils import (  # noqa
    OpenStackAmuletUtils,
    DEBUG,
    ERROR
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(ERROR)


class CephRadosGwBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic ceph-radosgw deployment."""

    def __init__(self, series=None, openstack=None, source=None, stable=False):
        """Deploy the entire test environment."""
        super(CephRadosGwBasicDeployment, self).__init__(series, openstack,
                                                         source, stable)
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where ceph-radosgw is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'ceph-radosgw'}
        other_services = [{'name': 'ceph', 'units': 3}, {'name': 'mysql'},
                          {'name': 'keystone'}, {'name': 'rabbitmq-server'},
                          {'name': 'nova-compute'}, {'name': 'glance'},
                          {'name': 'cinder'}]
        super(CephRadosGwBasicDeployment, self)._add_services(this_service,
                                                              other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'nova-compute:shared-db': 'mysql:shared-db',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'nova-compute:image-service': 'glance:image-service',
            'nova-compute:ceph': 'ceph:client',
            'keystone:shared-db': 'mysql:shared-db',
            'glance:shared-db': 'mysql:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:amqp': 'rabbitmq-server:amqp',
            'glance:ceph': 'ceph:client',
            'cinder:shared-db': 'mysql:shared-db',
            'cinder:identity-service': 'keystone:identity-service',
            'cinder:amqp': 'rabbitmq-server:amqp',
            'cinder:image-service': 'glance:image-service',
            'cinder:ceph': 'ceph:client',
            'ceph-radosgw:mon': 'ceph:radosgw',
            'ceph-radosgw:identity-service': 'keystone:identity-service'
        }
        super(CephRadosGwBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        keystone_config = {'admin-password': 'openstack',
                           'admin-token': 'ubuntutesting'}
        mysql_config = {'dataset-size': '50%'}
        cinder_config = {'block-device': 'None', 'glance-api-version': '2'}
        ceph_config = {
            'monitor-count': '3',
            'auth-supported': 'none',
            'fsid': '6547bd3e-1397-11e2-82e5-53567c8d32dc',
            'monitor-secret': 'AQCXrnZQwI7KGBAAiPofmKEXKxu5bUzoYLVkbQ==',
            'osd-reformat': 'yes',
            'ephemeral-unmount': '/mnt',
            'osd-devices': '/dev/vdb /srv/ceph'
        }

        configs = {'keystone': keystone_config,
                   'mysql': mysql_config,
                   'cinder': cinder_config,
                   'ceph': ceph_config}
        super(CephRadosGwBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.mysql_sentry = self.d.sentry.unit['mysql/0']
        self.keystone_sentry = self.d.sentry.unit['keystone/0']
        self.rabbitmq_sentry = self.d.sentry.unit['rabbitmq-server/0']
        self.nova_compute_sentry = self.d.sentry.unit['nova-compute/0']
        self.glance_sentry = self.d.sentry.unit['glance/0']
        self.cinder_sentry = self.d.sentry.unit['cinder/0']
        self.ceph0_sentry = self.d.sentry.unit['ceph/0']
        self.ceph1_sentry = self.d.sentry.unit['ceph/1']
        self.ceph2_sentry = self.d.sentry.unit['ceph/2']
        self.ceph_radosgw_sentry = self.d.sentry.unit['ceph-radosgw/0']

        # Authenticate admin with keystone
        self.keystone = u.authenticate_keystone_admin(self.keystone_sentry,
                                                      user='admin',
                                                      password='openstack',
                                                      tenant='admin')

        # Authenticate admin with glance endpoint
        self.glance = u.authenticate_glance_admin(self.keystone)

        # Create a demo tenant/role/user
        self.demo_tenant = 'demoTenant'
        self.demo_role = 'demoRole'
        self.demo_user = 'demoUser'
        if not u.tenant_exists(self.keystone, self.demo_tenant):
            tenant = self.keystone.tenants.create(tenant_name=self.demo_tenant,
                                                  description='demo tenant',
                                                  enabled=True)
            self.keystone.roles.create(name=self.demo_role)
            self.keystone.users.create(name=self.demo_user,
                                       password='password',
                                       tenant_id=tenant.id,
                                       email='demo@demo.com')

        # Authenticate demo user with keystone
        self.keystone_demo = u.authenticate_keystone_user(self.keystone,
                                                          self.demo_user,
                                                          'password',
                                                          self.demo_tenant)

        # Authenticate demo user with nova-api
        self.nova_demo = u.authenticate_nova_user(self.keystone,
                                                  self.demo_user,
                                                  'password',
                                                  self.demo_tenant)

    def _ceph_osd_id(self, index):
        """Produce a shell command that will return a ceph-osd id."""
        return "`initctl list | grep 'ceph-osd ' | awk 'NR=={} {{ print $2 }}' | grep -o '[0-9]*'`".format(index + 1)  # noqa

    def test_services(self):
        """Verify the expected services are running on the service units."""
        ceph_services = ['status ceph-mon-all',
                         'status ceph-mon id=`hostname`']
        commands = {
            self.mysql_sentry: ['status mysql'],
            self.rabbitmq_sentry: ['sudo service rabbitmq-server status'],
            self.nova_compute_sentry: ['status nova-compute'],
            self.keystone_sentry: ['status keystone'],
            self.glance_sentry: ['status glance-registry',
                                 'status glance-api'],
            self.cinder_sentry: ['status cinder-api',
                                 'status cinder-scheduler',
                                 'status cinder-volume'],
            self.ceph_radosgw_sentry: ['status radosgw-all']
        }
        ceph_osd0 = 'status ceph-osd id={}'.format(self._ceph_osd_id(0))
        ceph_osd1 = 'status ceph-osd id={}'.format(self._ceph_osd_id(1))
        ceph_services.extend([ceph_osd0, ceph_osd1, 'status ceph-osd-all'])
        commands[self.ceph0_sentry] = ceph_services
        commands[self.ceph1_sentry] = ceph_services
        commands[self.ceph2_sentry] = ceph_services

        ret = u.validate_services(commands)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_ceph_radosgw_ceph_relation(self):
        """Verify the ceph-radosgw to ceph relation data."""
        unit = self.ceph_radosgw_sentry
        relation = ['mon', 'ceph:radosgw']
        expected = {
            'private-address': u.valid_ip
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph-radosgw to ceph', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_ceph0_ceph_radosgw_relation(self):
        """Verify the ceph0 to ceph-radosgw relation data."""
        unit = self.ceph0_sentry
        relation = ['radosgw', 'ceph-radosgw:mon']
        expected = {
            'private-address': u.valid_ip,
            'radosgw_key': u.not_null,
            'auth': 'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph0 to ceph-radosgw', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_ceph1_ceph_radosgw_relation(self):
        """Verify the ceph1 to ceph-radosgw relation data."""
        unit = self.ceph1_sentry
        relation = ['radosgw', 'ceph-radosgw:mon']
        expected = {
            'private-address': u.valid_ip,
            'radosgw_key': u.not_null,
            'auth': 'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph1 to ceph-radosgw', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_ceph2_ceph_radosgw_relation(self):
        """Verify the ceph2 to ceph-radosgw relation data."""
        unit = self.ceph2_sentry
        relation = ['radosgw', 'ceph-radosgw:mon']
        expected = {
            'private-address': u.valid_ip,
            'radosgw_key': u.not_null,
            'auth': 'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph2 to ceph-radosgw', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_ceph_radosgw_keystone_relation(self):
        """Verify the ceph-radosgw to keystone relation data."""
        unit = self.ceph_radosgw_sentry
        relation = ['identity-service', 'keystone:identity-service']
        expected = {
            'service': 'swift',
            'region': 'RegionOne',
            'public_url': u.valid_url,
            'internal_url': u.valid_url,
            'private-address': u.valid_ip,
            'requested_roles': 'Member,Admin',
            'admin_url': u.valid_url
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph-radosgw to keystone', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_keystone_ceph_radosgw_relation(self):
        """Verify the keystone to ceph-radosgw relation data."""
        unit = self.keystone_sentry
        relation = ['identity-service', 'ceph-radosgw:identity-service']
        expected = {
            'service_protocol': 'http',
            'service_tenant': 'services',
            'admin_token': 'ubuntutesting',
            'service_password': u.not_null,
            'service_port': '5000',
            'auth_port': '35357',
            'auth_protocol': 'http',
            'private-address': u.valid_ip,
            'auth_host': u.valid_ip,
            'service_username': 'swift',
            'service_tenant_id': u.not_null,
            'service_host': u.valid_ip
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('keystone to ceph-radosgw', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_ceph_config(self):
        """Verify the data in the ceph config file."""
        unit = self.ceph_radosgw_sentry
        conf = '/etc/ceph/ceph.conf'
        keystone_sentry = self.keystone_sentry
        relation = keystone_sentry.relation('identity-service',
                                            'ceph-radosgw:identity-service')
        keystone_ip = relation['auth_host']
        expected = {
            'global': {
                'auth cluster required': 'none',
                'auth service required': 'none',
                'auth client required': 'none',
                'log to syslog': 'false',
                'err to syslog': 'false',
                'clog to syslog': 'false'
            },
            'client.radosgw.gateway': {
                'keyring': '/etc/ceph/keyring.rados.gateway',
                'rgw socket path': '/tmp/radosgw.sock',
                'log file': '/var/log/ceph/radosgw.log',
                'rgw print continue': 'false',
                'rgw keystone url': 'http://{}:35357/'.format(keystone_ip),
                'rgw keystone admin token': 'ubuntutesting',
                'rgw keystone accepted roles': 'Member,Admin',
                'rgw keystone token cache size': '500',
                'rgw keystone revocation interval': '600'
            },
        }

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "ceph config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_restart_on_config_change(self):
        """Verify the specified services are restarted on config change."""
        # NOTE(coreycb): Test not implemented but should it be? ceph-radosgw
        #                svcs aren't restarted by charm after config change
        #                Should they be restarted?
        if self._get_openstack_release() >= self.precise_essex:
            u.log.error("Test not implemented")
            return
