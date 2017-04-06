#!/usr/bin/python
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

import os
import subprocess
import sys

import ceph

from charmhelpers.core.hookenv import (
    relation_get,
    relation_ids,
    related_units,
    config,
    unit_get,
    open_port,
    relation_set,
    log,
    DEBUG,
    Hooks, UnregisteredHookError,
    status_set,
)
from charmhelpers.fetch import (
    apt_update,
    apt_install,
    apt_purge,
    add_source,
    filter_installed_packages,
)
from charmhelpers.payload.execd import execd_preinstall
from charmhelpers.core.host import cmp_pkgrevno
from charmhelpers.contrib.network.ip import (
    get_address_in_network,
    get_ipv6_addr,
    get_iface_for_address,
    get_netmask_for_address,
    is_ipv6,
)
from charmhelpers.contrib.openstack.context import ADDRESS_TYPES
from charmhelpers.contrib.openstack.ip import (
    canonical_url,
    PUBLIC, INTERNAL, ADMIN,
)
from charmhelpers.contrib.storage.linux.ceph import (
    send_request_if_needed,
    is_request_complete,
)
from charmhelpers.contrib.openstack.utils import (
    is_unit_paused_set,
    pausable_restart_on_change as restart_on_change,
)
from charmhelpers.contrib.hahelpers.cluster import (
    get_hacluster_config,
)
from charmhelpers.contrib.openstack.ha.utils import (
    update_dns_ha_resource_params,
)
from utils import (
    enable_pocket,
    CEPHRG_HA_RES,
    register_configs,
    setup_ipv6,
    services,
    assess_status,
    setup_keystone_certs,
)
from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.hardening.harden import harden

hooks = Hooks()
CONFIGS = register_configs()
NSS_DIR = '/var/lib/ceph/nss'


PACKAGES = [
    'haproxy',
    'libnss3-tools',
    'ntp',
    'python-keystoneclient',
    'python-six',  # Ensures correct version is installed for precise
                   # since python-keystoneclient does not pull in icehouse
                   # version
    'radosgw',
]

APACHE_PACKAGES = [
    'libapache2-mod-fastcgi',
    'apache2',
]


def install_packages():
    add_source(config('source'), config('key'))
    apt_update(fatal=True)
    pkgs = filter_installed_packages(PACKAGES)
    if pkgs:
        status_set('maintenance', 'Installing radosgw packages')
        apt_install(PACKAGES, fatal=True)
    apt_purge(APACHE_PACKAGES)


@hooks.hook('install.real')
@harden()
def install():
    status_set('maintenance', 'Executing pre-install')
    execd_preinstall()
    enable_pocket('multiverse')
    install_packages()
    if not os.path.exists(NSS_DIR):
        os.makedirs(NSS_DIR)
    if not os.path.exists('/etc/ceph'):
        os.makedirs('/etc/ceph')


@hooks.hook('upgrade-charm',
            'config-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw'],
                    '/etc/haproxy/haproxy.cfg': ['haproxy']})
@harden()
def config_changed():
    install_packages()

    if config('prefer-ipv6'):
        status_set('maintenance', 'configuring ipv6')
        setup_ipv6()

    for r_id in relation_ids('identity-service'):
        identity_changed(relid=r_id)

    for r_id in relation_ids('cluster'):
        cluster_joined(rid=r_id)

    # NOTE(jamespage): Re-exec mon relation for any changes to
    #                  enable ceph pool permissions restrictions
    for r_id in relation_ids('mon'):
        for unit in related_units(r_id):
            mon_relation(r_id, unit)

    CONFIGS.write_all()

    update_nrpe_config()


@hooks.hook('mon-relation-departed',
            'mon-relation-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw']})
def mon_relation(rid=None, unit=None):
    rq = ceph.get_create_rgw_pools_rq(
        prefix=config('pool-prefix'))
    if is_request_complete(rq, relation='mon'):
        log('Broker request complete', level=DEBUG)
        CONFIGS.write_all()
        key = relation_get(attribute='radosgw_key',
                           rid=rid, unit=unit)
        if key:
            ceph.import_radosgw_key(key)
            if not is_unit_paused_set():
                restart()  # TODO figure out a better way todo this
    else:
        send_request_if_needed(rq, relation='mon')


@hooks.hook('gateway-relation-joined')
def gateway_relation():
    relation_set(hostname=unit_get('private-address'),
                 port=config('port'))


def start():
    subprocess.call(['service', 'radosgw', 'start'])
    open_port(port=config('port'))


def stop():
    subprocess.call(['service', 'radosgw', 'stop'])
    open_port(port=config('port'))


def restart():
    subprocess.call(['service', 'radosgw', 'restart'])
    open_port(port=config('port'))


@hooks.hook('identity-service-relation-joined')
def identity_joined(relid=None):
    if cmp_pkgrevno('radosgw', '0.55') < 0:
        log('Integration with keystone requires ceph >= 0.55')
        sys.exit(1)

    port = config('port')
    admin_url = '%s:%i/swift' % (canonical_url(None, ADMIN), port)
    internal_url = '%s:%s/swift/v1' % \
        (canonical_url(None, INTERNAL), port)
    public_url = '%s:%s/swift/v1' % \
        (canonical_url(None, PUBLIC), port)
    relation_set(service='swift',
                 region=config('region'),
                 public_url=public_url, internal_url=internal_url,
                 admin_url=admin_url,
                 requested_roles=config('operator-roles'),
                 relation_id=relid)

    if relid:
        for unit in related_units(relid):
            setup_keystone_certs(unit=unit, rid=relid)
    else:
        setup_keystone_certs()


@hooks.hook('identity-service-relation-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw']})
def identity_changed(relid=None):
    identity_joined(relid)
    CONFIGS.write_all()
    if not is_unit_paused_set():
        restart()


@hooks.hook('cluster-relation-joined')
@restart_on_change({'/etc/haproxy/haproxy.cfg': ['haproxy']})
def cluster_joined(rid=None):
    settings = {}

    for addr_type in ADDRESS_TYPES:
        address = get_address_in_network(
            config('os-{}-network'.format(addr_type))
        )
        if address:
            settings['{}-address'.format(addr_type)] = address

    if config('prefer-ipv6'):
        private_addr = get_ipv6_addr(exc_list=[config('vip')])[0]
        settings['private-address'] = private_addr

    relation_set(relation_id=rid, **settings)


@hooks.hook('cluster-relation-changed')
@restart_on_change({'/etc/haproxy/haproxy.cfg': ['haproxy']})
def cluster_changed():
    CONFIGS.write_all()
    for r_id in relation_ids('identity-service'):
        identity_joined(relid=r_id)


@hooks.hook('ha-relation-joined')
def ha_relation_joined(relation_id=None):
    cluster_config = get_hacluster_config()
    # Obtain resources
    resources = {
        'res_cephrg_haproxy': 'lsb:haproxy'
    }
    resource_params = {
        'res_cephrg_haproxy': 'op monitor interval="5s"'
    }

    if config('dns-ha'):
        update_dns_ha_resource_params(relation_id=relation_id,
                                      resources=resources,
                                      resource_params=resource_params)
    else:
        vip_group = []
        for vip in cluster_config['vip'].split():
            if is_ipv6(vip):
                res_rgw_vip = 'ocf:heartbeat:IPv6addr'
                vip_params = 'ipv6addr'
            else:
                res_rgw_vip = 'ocf:heartbeat:IPaddr2'
                vip_params = 'ip'

            iface = get_iface_for_address(vip)
            netmask = get_netmask_for_address(vip)

            if iface is not None:
                vip_key = 'res_cephrg_{}_vip'.format(iface)
                resources[vip_key] = res_rgw_vip
                resource_params[vip_key] = (
                    'params {ip}="{vip}" cidr_netmask="{netmask}"'
                    ' nic="{iface}"'.format(ip=vip_params,
                                            vip=vip,
                                            iface=iface,
                                            netmask=netmask)
                )
                vip_group.append(vip_key)

        if len(vip_group) >= 1:
            relation_set(groups={CEPHRG_HA_RES: ' '.join(vip_group)})

    init_services = {
        'res_cephrg_haproxy': 'haproxy'
    }
    clones = {
        'cl_cephrg_haproxy': 'res_cephrg_haproxy'
    }

    relation_set(relation_id=relation_id,
                 init_services=init_services,
                 corosync_bindiface=cluster_config['ha-bindiface'],
                 corosync_mcastport=cluster_config['ha-mcastport'],
                 resources=resources,
                 resource_params=resource_params,
                 clones=clones)


@hooks.hook('ha-relation-changed')
def ha_relation_changed():
    clustered = relation_get('clustered')
    if clustered:
        log('Cluster configured, notifying other services and'
            'updating keystone endpoint configuration')
        # Tell all related services to start using
        # the VIP instead
        for r_id in relation_ids('identity-service'):
            identity_joined(relid=r_id)


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    apt_install('python-dbus')
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)
    nrpe.copy_nrpe_checks()
    nrpe.add_init_service_checks(nrpe_setup, services(), current_unit)
    nrpe.add_haproxy_checks(nrpe_setup, current_unit)
    nrpe_setup.write()


@hooks.hook('update-status')
@harden()
def update_status():
    log('Updating status.')


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status(CONFIGS)
