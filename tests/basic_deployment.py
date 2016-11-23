#!/usr/bin/env python
#
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

import amulet
import subprocess
import json
import time
from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)
from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)


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

        u.log.info('Waiting on extended status checks...')
        exclude_services = []

        # Wait for deployment ready msgs, except exclusions
        self._auto_wait_for_status(exclude_services=exclude_services)

        self.d.sentry.wait()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where ceph-radosgw is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'ceph-radosgw'}
        other_services = [
            {'name': 'ceph', 'units': 3},
            {'name': 'percona-cluster', 'constraints': {'mem': '3072M'}},
            {'name': 'keystone'},
            {'name': 'rabbitmq-server'},
            {'name': 'nova-compute'},
            {'name': 'glance'},
            {'name': 'cinder'}
        ]
        super(CephRadosGwBasicDeployment, self)._add_services(this_service,
                                                              other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'nova-compute:shared-db': 'percona-cluster:shared-db',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'nova-compute:image-service': 'glance:image-service',
            'nova-compute:ceph': 'ceph:client',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:amqp': 'rabbitmq-server:amqp',
            'glance:ceph': 'ceph:client',
            'cinder:shared-db': 'percona-cluster:shared-db',
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
        pxc_config = {
            'dataset-size': '25%',
            'max-connections': 1000,
            'root-password': 'ChangeMe123',
            'sst-password': 'ChangeMe123',
        }

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
        radosgw_config = {"use-embedded-webserver": True}

        configs = {'keystone': keystone_config,
                   'percona-cluster': pxc_config,
                   'cinder': cinder_config,
                   'ceph': ceph_config,
                   'ceph-radosgw': radosgw_config}
        super(CephRadosGwBasicDeployment, self)._configure_services(configs)

    def _run_action(self, unit_id, action, *args):
        command = ["juju", "action", "do", "--format=json", unit_id, action]
        command.extend(args)
        print("Running command: %s\n" % " ".join(command))
        output = subprocess.check_output(command)
        output_json = output.decode(encoding="UTF-8")
        data = json.loads(output_json)
        action_id = data[u'Action queued with id']
        return action_id

    def _wait_on_action(self, action_id):
        command = ["juju", "action", "fetch", "--format=json", action_id]
        while True:
            try:
                output = subprocess.check_output(command)
            except Exception as e:
                print(e)
                return False
            output_json = output.decode(encoding="UTF-8")
            data = json.loads(output_json)
            if data[u"status"] == "completed":
                return True
            elif data[u"status"] == "failed":
                return False
            time.sleep(2)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.nova_sentry = self.d.sentry['nova-compute'][0]
        self.glance_sentry = self.d.sentry['glance'][0]
        self.cinder_sentry = self.d.sentry['cinder'][0]
        self.ceph0_sentry = self.d.sentry['ceph'][0]
        self.ceph1_sentry = self.d.sentry['ceph'][1]
        self.ceph2_sentry = self.d.sentry['ceph'][2]
        self.ceph_radosgw_sentry = self.d.sentry['ceph-radosgw'][0]
        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

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

        # Authenticate radosgw user using swift api
        ks_obj_rel = self.keystone_sentry.relation(
            'identity-service',
            'ceph-radosgw:identity-service')
        self.swift = u.authenticate_swift_user(
            self.keystone,
            user=ks_obj_rel['service_username'],
            password=ks_obj_rel['service_password'],
            tenant=ks_obj_rel['service_tenant'])

    def test_100_ceph_processes(self):
        """Verify that the expected service processes are running
        on each ceph unit."""

        # Process name and quantity of processes to expect on each unit
        ceph_processes = {
            'ceph-mon': 1,
            'ceph-osd': 2
        }

        # Units with process names and PID quantities expected
        expected_processes = {
            self.ceph_radosgw_sentry: {'radosgw': 1},
            self.ceph0_sentry: ceph_processes,
            self.ceph1_sentry: ceph_processes,
            self.ceph2_sentry: ceph_processes
        }

        actual_pids = u.get_unit_process_ids(expected_processes)
        ret = u.validate_unit_process_ids(expected_processes, actual_pids)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_102_services(self):
        """Verify the expected services are running on the service units."""

        services = {
            self.rabbitmq_sentry: ['rabbitmq-server'],
            self.nova_sentry: ['nova-compute'],
            self.keystone_sentry: ['keystone'],
            self.glance_sentry: ['glance-registry',
                                 'glance-api'],
            self.cinder_sentry: ['cinder-api',
                                 'cinder-scheduler',
                                 'cinder-volume'],
        }

        if self._get_openstack_release() < self.xenial_mitaka:
            # For upstart systems only.  Ceph services under systemd
            # are checked by process name instead.
            ceph_services = [
                'ceph-mon-all',
                'ceph-mon id=`hostname`',
                'ceph-osd-all',
                'ceph-osd id={}'.format(u.get_ceph_osd_id_cmd(0)),
                'ceph-osd id={}'.format(u.get_ceph_osd_id_cmd(1))
            ]
            services[self.ceph0_sentry] = ceph_services
            services[self.ceph1_sentry] = ceph_services
            services[self.ceph2_sentry] = ceph_services
            services[self.ceph_radosgw_sentry] = ['radosgw-all']

        if self._get_openstack_release() >= self.trusty_liberty:
            services[self.keystone_sentry] = ['apache2']

        ret = u.validate_services_by_name(services)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_200_ceph_radosgw_ceph_relation(self):
        """Verify the ceph-radosgw to ceph relation data."""
        u.log.debug('Checking ceph-radosgw:mon to ceph:radosgw '
                    'relation data...')
        unit = self.ceph_radosgw_sentry
        relation = ['mon', 'ceph:radosgw']
        expected = {
            'private-address': u.valid_ip
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceph-radosgw to ceph', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_201_ceph_radosgw_relation(self):
        """Verify the ceph to ceph-radosgw relation data.

        At least one unit (the leader) must have all data provided by the ceph
        charm.
        """
        u.log.debug('Checking ceph0:radosgw radosgw:mon relation data...')
        s_entries = [
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]
        relation = ['radosgw', 'ceph-radosgw:mon']
        expected = {
            'private-address': u.valid_ip,
            'radosgw_key': u.not_null,
            'auth': 'none',
            'ceph-public-address': u.valid_ip,
            'fsid': u'6547bd3e-1397-11e2-82e5-53567c8d32dc'
        }

        ret = []
        for unit in s_entries:
            ret.append(u.validate_relation_data(unit, relation, expected))

        if any(ret):
            message = u.relation_error('ceph to ceph-radosgw', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_204_ceph_radosgw_keystone_relation(self):
        """Verify the ceph-radosgw to keystone relation data."""
        u.log.debug('Checking ceph-radosgw to keystone id service '
                    'relation data...')
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

    def test_205_keystone_ceph_radosgw_relation(self):
        """Verify the keystone to ceph-radosgw relation data."""
        u.log.debug('Checking keystone to ceph-radosgw id service '
                    'relation data...')
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

    def test_300_ceph_radosgw_config(self):
        """Verify the data in the ceph config file."""
        u.log.debug('Checking ceph config file data...')
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
                'rgw keystone url': 'http://{}:35357/'.format(keystone_ip),
                'rgw keystone admin token': 'ubuntutesting',
                'rgw keystone accepted roles': 'Member,Admin',
                'rgw keystone token cache size': '500',
                'rgw keystone revocation interval': '600',
                'rgw frontends': 'civetweb port=70',
            },
        }

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "ceph config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_302_cinder_rbd_config(self):
        """Verify the cinder config file data regarding ceph."""
        u.log.debug('Checking cinder (rbd) config file data...')
        unit = self.cinder_sentry
        conf = '/etc/cinder/cinder.conf'
        expected = {
            'DEFAULT': {
                'volume_driver': 'cinder.volume.drivers.rbd.RBDDriver'
            }
        }
        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "cinder (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_304_glance_rbd_config(self):
        """Verify the glance config file data regarding ceph."""
        u.log.debug('Checking glance (rbd) config file data...')
        unit = self.glance_sentry
        conf = '/etc/glance/glance-api.conf'
        config = {
            'default_store': 'rbd',
            'rbd_store_ceph_conf': '/etc/ceph/ceph.conf',
            'rbd_store_user': 'glance',
            'rbd_store_pool': 'glance',
            'rbd_store_chunk_size': '8'
        }

        if self._get_openstack_release() >= self.trusty_kilo:
            # Kilo or later
            config['stores'] = ('glance.store.filesystem.Store,'
                                'glance.store.http.Store,'
                                'glance.store.rbd.Store')
            section = 'glance_store'
        else:
            # Juno or earlier
            section = 'DEFAULT'

        expected = {section: config}
        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "glance (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_306_nova_rbd_config(self):
        """Verify the nova config file data regarding ceph."""
        u.log.debug('Checking nova (rbd) config file data...')
        unit = self.nova_sentry
        conf = '/etc/nova/nova.conf'
        expected = {
            'libvirt': {
                'rbd_user': 'nova-compute',
                'rbd_secret_uuid': u.not_null
            }
        }
        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "nova (rbd) config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_400_ceph_check_osd_pools(self):
        """Check osd pools on all ceph units, expect them to be
        identical, and expect specific pools to be present."""
        u.log.debug('Checking pools on ceph units...')

        expected_pools = self.get_ceph_expected_pools(radosgw=True)

        if self._get_openstack_release() >= self.trusty_mitaka:
            non_rgw_pools = self.get_ceph_expected_pools()
            _expected_pools = []
            for pool in expected_pools:
                if pool not in non_rgw_pools:
                    # prepend zone name
                    _expected_pools.append('default%s' % (pool))

            expected_pools = _expected_pools

        results = []
        sentries = [
            self.ceph_radosgw_sentry,
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]

        # Check for presence of expected pools on each unit
        u.log.debug('Expected pools: {}'.format(expected_pools))
        for sentry_unit in sentries:
            pools = u.get_ceph_pools(sentry_unit)
            results.append(pools)

            for expected_pool in expected_pools:
                if expected_pool not in pools:
                    msg = ('{} does not have pool: '
                           '{}'.format(sentry_unit.info['unit_name'],
                                       expected_pool))
                    amulet.raise_status(amulet.FAIL, msg=msg)
            u.log.debug('{} has (at least) the expected '
                        'pools.'.format(sentry_unit.info['unit_name']))

        # Check that all units returned the same pool name:id data
        ret = u.validate_list_of_identical_dicts(results)
        if ret:
            u.log.debug('Pool list results: {}'.format(results))
            msg = ('{}; Pool list results are not identical on all '
                   'ceph units.'.format(ret))
            amulet.raise_status(amulet.FAIL, msg=msg)
        else:
            u.log.debug('Pool list on all ceph units produced the '
                        'same results (OK).')

    def test_402_swift_api_connection(self):
        """Simple api call to confirm basic service functionality"""
        u.log.debug('Checking basic radosgw functionality via swift api...')
        headers, containers = self.swift.get_account()
        assert('content-type' in headers.keys())
        assert(containers == [])

    def test_498_radosgw_cmds_exit_zero(self):
        """Check basic functionality of radosgw cli commands against
        the ceph_radosgw unit."""
        sentry_units = [self.ceph_radosgw_sentry]
        commands = [
            'sudo radosgw-admin bucket list',
            'sudo radosgw-admin zone list',
            'sudo radosgw-admin metadata list',
            'sudo radosgw-admin gc list'
        ]

        ret = u.check_commands_on_units(commands, sentry_units)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_499_ceph_cmds_exit_zero(self):
        """Check basic functionality of ceph cli commands against
        all ceph units."""
        sentry_units = [
            self.ceph_radosgw_sentry,
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]
        commands = [
            'sudo ceph health',
            'sudo ceph mds stat',
            'sudo ceph pg stat',
            'sudo ceph osd stat',
            'sudo ceph mon stat',
        ]
        ret = u.check_commands_on_units(commands, sentry_units)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed. """
        u.log.debug('Checking pause and resume actions...')
        unit = self.ceph_radosgw_sentry
        unit_name = unit.info['unit_name']

        assert u.status_get(unit)[0] == "active"

        action_id = self._run_action(unit_name, "pause")
        assert self._wait_on_action(action_id), "Pause action failed."
        assert u.status_get(unit)[0] == "maintenance"

        action_id = self._run_action(unit_name, "resume")
        assert self._wait_on_action(action_id), "Resume action failed."
        assert u.status_get(unit)[0] == "active"
        u.log.debug('OK')
    # Note(beisner): need to add basic object store functional checks.

    # FYI: No restart check as ceph services do not restart
    # when charm config changes, unless monitor count increases.
