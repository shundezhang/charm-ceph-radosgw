#!/usr/bin/env python3
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
import socket

sys.path.append('lib')

import ceph_rgw as ceph
import ceph.utils as ceph_utils

from charmhelpers.core.hookenv import (
    relation_get,
    relation_ids,
    related_units,
    config,
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
    filter_missing_packages,
)
from charmhelpers.payload.execd import execd_preinstall
from charmhelpers.core.host import (
    cmp_pkgrevno,
    is_container,
    service_reload,
    service_restart,
    service_stop,
    service,
)
from charmhelpers.contrib.network.ip import (
    get_relation_ip,
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
    series_upgrade_prepare,
    series_upgrade_complete,
)
from charmhelpers.contrib.openstack.ha.utils import (
    generate_ha_relation_data,
)
from utils import (
    enable_pocket,
    register_configs,
    setup_ipv6,
    services,
    assess_status,
    setup_keystone_certs,
    disable_unused_apache_sites,
    pause_unit_helper,
    resume_unit_helper,
    restart_map,
    service_name,
    systemd_based_radosgw,
    request_per_unit_key,
)
from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.hardening.harden import harden

from charmhelpers.contrib.openstack.cert_utils import (
    get_certificate_request,
    process_certificates,
)

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
    'apache2'
]

APACHE_PACKAGES = [
    'libapache2-mod-fastcgi',
]


def upgrade_available():
    """Check for upgrade for ceph

    :returns: whether an upgrade is available
    :rtype: boolean
    """
    c = config()
    old_version = ceph_utils.resolve_ceph_version(c.previous('source') or
                                                  'distro')
    new_version = ceph_utils.resolve_ceph_version(c.get('source'))
    if (old_version in ceph_utils.UPGRADE_PATHS and
            new_version == ceph_utils.UPGRADE_PATHS[old_version]):
        return True
    return False


def install_packages():
    c = config()
    if c.changed('source') or c.changed('key'):
        add_source(c.get('source'), c.get('key'))
        apt_update(fatal=True)

    if is_container():
        PACKAGES.remove('ntp')

    # NOTE: just use full package list if we're in an upgrade
    #       config-changed execution
    pkgs = (
        PACKAGES if upgrade_available() else
        filter_installed_packages(PACKAGES)
    )
    if pkgs:
        status_set('maintenance', 'Installing radosgw packages')
        apt_install(pkgs, fatal=True)

    pkgs = filter_missing_packages(APACHE_PACKAGES)
    if pkgs:
        apt_purge(pkgs)

    disable_unused_apache_sites()


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


@hooks.hook('config-changed')
@harden()
def config_changed():
    @restart_on_change(restart_map())
    def _config_changed():
        # if we are paused, delay doing any config changed hooks.
        # It is forced on the resume.
        if is_unit_paused_set():
            log("Unit is pause or upgrading. Skipping config_changed", "WARN")
            return

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

        # Re-trigger hacluster relations to switch to ifaceless
        # vip configuration
        for r_id in relation_ids('ha'):
            ha_relation_joined(r_id)

        # Refire certificates relations for VIP changes
        for r_id in relation_ids('certificates'):
            certs_joined(r_id)

        CONFIGS.write_all()
        configure_https()

        update_nrpe_config()

        open_port(port=config('port'))
    _config_changed()


@hooks.hook('mon-relation-departed',
            'mon-relation-changed')
def mon_relation(rid=None, unit=None):
    @restart_on_change(restart_map())
    def _mon_relation():
        key_name = 'rgw.{}'.format(socket.gethostname())
        if request_per_unit_key():
            relation_set(relation_id=rid,
                         key_name=key_name)
        rq = ceph.get_create_rgw_pools_rq(
            prefix=config('pool-prefix'))
        if is_request_complete(rq, relation='mon'):
            log('Broker request complete', level=DEBUG)
            CONFIGS.write_all()
            # New style per unit keys
            key = relation_get(attribute='{}_key'.format(key_name),
                               rid=rid, unit=unit)
            if not key:
                # Fallback to old style global key
                key = relation_get(attribute='radosgw_key',
                                   rid=rid, unit=unit)
                key_name = None

            if key:
                new_keyring = ceph.import_radosgw_key(key,
                                                      name=key_name)
                # NOTE(jamespage):
                # Deal with switch from radosgw init script to
                # systemd named units for radosgw instances by
                # stopping and disabling the radosgw unit
                if systemd_based_radosgw():
                    service_stop('radosgw')
                    service('disable', 'radosgw')
                if not is_unit_paused_set() and new_keyring:
                    service('enable', service_name())
                    service_restart(service_name())
        else:
            send_request_if_needed(rq, relation='mon')
    _mon_relation()


@hooks.hook('gateway-relation-joined')
def gateway_relation():
    relation_set(hostname=get_relation_ip('gateway-relation'),
                 port=config('port'))


@hooks.hook('identity-service-relation-joined')
def identity_joined(relid=None):
    if cmp_pkgrevno('radosgw', '0.55') < 0:
        log('Integration with keystone requires ceph >= 0.55')
        sys.exit(1)

    port = config('port')
    admin_url = '%s:%i/swift' % (canonical_url(CONFIGS, ADMIN), port)
    internal_url = '%s:%s/swift/v1' % \
        (canonical_url(CONFIGS, INTERNAL), port)
    public_url = '%s:%s/swift/v1' % \
        (canonical_url(CONFIGS, PUBLIC), port)
    relation_set(service='swift',
                 region=config('region'),
                 public_url=public_url, internal_url=internal_url,
                 admin_url=admin_url,
                 requested_roles=config('operator-roles'),
                 relation_id=relid)


@hooks.hook('identity-service-relation-changed')
def identity_changed(relid=None):
    @restart_on_change(restart_map())
    def _identity_changed():
        identity_joined(relid)
        CONFIGS.write_all()
        configure_https()
    _identity_changed()


@hooks.hook('cluster-relation-joined')
def cluster_joined(rid=None):
    @restart_on_change(restart_map())
    def _cluster_joined():
        settings = {}

        for addr_type in ADDRESS_TYPES:
            address = get_relation_ip(
                addr_type,
                cidr_network=config('os-{}-network'.format(addr_type)))
            if address:
                settings['{}-address'.format(addr_type)] = address

        settings['private-address'] = get_relation_ip('cluster')

        relation_set(relation_id=rid, relation_settings=settings)
    _cluster_joined()


@hooks.hook('cluster-relation-changed')
def cluster_changed():
    @restart_on_change(restart_map())
    def _cluster_changed():
        CONFIGS.write_all()
        for r_id in relation_ids('identity-service'):
            identity_joined(relid=r_id)
        for r_id in relation_ids('certificates'):
            for unit in related_units(r_id):
                certs_changed(r_id, unit)
    _cluster_changed()


@hooks.hook('ha-relation-joined')
def ha_relation_joined(relation_id=None):
    settings = generate_ha_relation_data('cephrg')
    relation_set(relation_id=relation_id, **settings)


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


def configure_https():
    '''Enables SSL API Apache config if appropriate and kicks
    identity-service and image-service with any required
    updates
    '''
    CONFIGS.write_all()
    if 'https' in CONFIGS.complete_contexts():
        cmd = ['a2ensite', 'openstack_https_frontend']
        subprocess.check_call(cmd)
    else:
        cmd = ['a2dissite', 'openstack_https_frontend']
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            # The site is not yet enabled or
            # https is not configured
            pass

    # TODO: improve this by checking if local CN certs are available
    # first then checking reload status (see LP #1433114).
    if not is_unit_paused_set():
        service_reload('apache2', restart_on_failure=True)

    setup_keystone_certs(CONFIGS)


@hooks.hook('update-status')
@harden()
def update_status():
    log('Updating status.')


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    log("Running prepare series upgrade hook", "INFO")
    series_upgrade_prepare(
        pause_unit_helper, CONFIGS)


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    log("Running complete series upgrade hook", "INFO")
    series_upgrade_complete(
        resume_unit_helper, CONFIGS)


@hooks.hook('certificates-relation-joined')
def certs_joined(relation_id=None):
    relation_set(
        relation_id=relation_id,
        relation_settings=get_certificate_request())


@hooks.hook('certificates-relation-changed')
def certs_changed(relation_id=None, unit=None):
    @restart_on_change(restart_map(), stopstart=True)
    def _certs_changed():
        process_certificates('ceph-radosgw', relation_id, unit)
        configure_https()
    _certs_changed()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status(CONFIGS)
