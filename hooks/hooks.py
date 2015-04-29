#!/usr/bin/python

#
# Copyright 2012 Canonical Ltd.
#
# Authors:
#  James Page <james.page@ubuntu.com>
#

import shutil
import subprocess
import sys
import glob
import os
import ceph
from charmhelpers.core.hookenv import (
    relation_get,
    relation_ids,
    related_units,
    config,
    unit_get,
    open_port,
    relation_set,
    log, ERROR,
    Hooks, UnregisteredHookError,
)
from charmhelpers.fetch import (
    apt_update,
    apt_install,
    apt_purge,
    add_source,
)
from charmhelpers.core.host import (
    lsb_release,
    restart_on_change
)
from utils import (
    render_template,
    get_host_ip,
    enable_pocket,
    is_apache_24,
    CEPHRG_HA_RES,
    register_configs,
)

from charmhelpers.payload.execd import execd_preinstall
from charmhelpers.core.host import cmp_pkgrevno
from socket import gethostname as get_unit_hostname

from charmhelpers.contrib.network.ip import (
    get_iface_for_address,
    get_netmask_for_address,
    is_ipv6,
)
from charmhelpers.contrib.openstack.ip import (
    resolve_address,
    PUBLIC, INTERNAL, ADMIN,
)

hooks = Hooks()
CONFIGS = register_configs()


def install_www_scripts():
    for x in glob.glob('files/www/*'):
        shutil.copy(x, '/var/www/')


NSS_DIR = '/var/lib/ceph/nss'


def install_ceph_optimised_packages():
    """Inktank provides patched/optimised packages for HTTP 100-continue
    support that does has not yet been ported to upstream. These can
    optionally be installed from ceph.com archives.
    """
    prolog = "http://gitbuilder.ceph.com/"
    epilog = "-x86_64-basic/ref/master"
    rel = lsb_release()['DISTRIB_CODENAME']
    fastcgi_source = "%slibapache-mod-fastcgi-deb-%s%s" % (prolog, rel, epilog)
    apache_source = "%sapache2-deb-%s%s" % (prolog, rel, epilog)

    for source in [fastcgi_source, apache_source]:
        add_source(source, key='6EAEAE2203C3951A')


PACKAGES = [
    'radosgw',
    'ntp',
    'haproxy',
]

APACHE_PACKAGES = [
    'libapache2-mod-fastcgi',
    'apache2',
]


def install_packages():
    add_source(config('source'), config('key'))
    if (config('use-ceph-optimised-packages') and
            not config('use-embedded-webserver')):
        install_ceph_optimised_packages()

    apt_update(fatal=True)
    apt_install(PACKAGES, fatal=True)
    if config('use-embedded-webserver'):
        apt_purge(APACHE_PACKAGES)
    else:
        apt_install(APACHE_PACKAGES, fatal=True)


@hooks.hook('install')
def install():
    execd_preinstall()
    enable_pocket('multiverse')
    install_packages()
    os.makedirs(NSS_DIR)


def emit_cephconf():
    # Ensure ceph directory actually exists
    if not os.path.exists('/etc/ceph'):
        os.makedirs('/etc/ceph')

    cephcontext = {
        'auth_supported': get_auth() or 'none',
        'mon_hosts': ' '.join(get_mon_hosts()),
        'hostname': get_unit_hostname(),
        'old_auth': cmp_pkgrevno('radosgw', "0.51") < 0,
        'use_syslog': str(config('use-syslog')).lower(),
        'embedded_webserver': config('use-embedded-webserver'),
    }

    # Check to ensure that correct version of ceph is
    # in use
    if cmp_pkgrevno('radosgw', '0.55') >= 0:
        # Add keystone configuration if found
        ks_conf = get_keystone_conf()
        if ks_conf:
            cephcontext.update(ks_conf)

    with open('/etc/ceph/ceph.conf', 'w') as cephconf:
        cephconf.write(render_template('ceph.conf', cephcontext))


def emit_apacheconf():
    apachecontext = {
        "hostname": unit_get('private-address')
    }
    site_conf = '/etc/apache2/sites-available/rgw'
    if is_apache_24():
        site_conf = '/etc/apache2/sites-available/rgw.conf'
    with open(site_conf, 'w') as apacheconf:
        apacheconf.write(render_template('rgw', apachecontext))


def apache_sites():
    if is_apache_24():
        subprocess.check_call(['a2dissite', '000-default'])
    else:
        subprocess.check_call(['a2dissite', 'default'])
    subprocess.check_call(['a2ensite', 'rgw'])


def apache_modules():
    subprocess.check_call(['a2enmod', 'fastcgi'])
    subprocess.check_call(['a2enmod', 'rewrite'])


def apache_reload():
    subprocess.call(['service', 'apache2', 'reload'])


def apache_ports():
    shutil.copy('files/ports.conf', '/etc/apache2/ports.conf')


@hooks.hook('upgrade-charm',
            'config-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw'],
                    '/etc/haproxy/haproxy.cfg': ['haproxy']})
def config_changed():
    install_packages()
    emit_cephconf()
    CONFIGS.write_all()
    if not config('use-embedded-webserver'):
        emit_apacheconf()
        install_www_scripts()
        apache_sites()
        apache_modules()
        apache_ports()
        apache_reload()
    for r_id in relation_ids('identity-service'):
        identity_joined(relid=r_id)


def get_mon_hosts():
    hosts = []
    for relid in relation_ids('mon'):
        for unit in related_units(relid):
            host_ip = get_host_ip(relation_get('ceph-public-address',
                                               unit, relid))
            hosts.append('{}:6789'.format(host_ip))

    hosts.sort()
    return hosts


def get_auth():
    return get_conf('auth')


def get_conf(name):
    for relid in relation_ids('mon'):
        for unit in related_units(relid):
            conf = relation_get(name,
                                unit, relid)
            if conf:
                return conf
    return None


def get_keystone_conf():
    for relid in relation_ids('identity-service'):
        for unit in related_units(relid):
            ks_auth = {
                'auth_type': 'keystone',
                'auth_protocol':
                relation_get('auth_protocol', unit, relid) or "http",
                'auth_host': relation_get('auth_host', unit, relid),
                'auth_port': relation_get('auth_port', unit, relid),
                'admin_token': relation_get('admin_token', unit, relid),
                'user_roles': config('operator-roles'),
                'cache_size': config('cache-size'),
                'revocation_check_interval':
                config('revocation-check-interval')
            }
            if None not in ks_auth.itervalues():
                return ks_auth
    return None


@hooks.hook('mon-relation-departed',
            'mon-relation-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw']})
def mon_relation():
    emit_cephconf()
    key = relation_get('radosgw_key')
    if key:
        ceph.import_radosgw_key(key)
        restart()  # TODO figure out a better way todo this


@hooks.hook('gateway-relation-joined')
def gateway_relation():
    relation_set(hostname=unit_get('private-address'),
                 port=80)


def start():
    subprocess.call(['service', 'radosgw', 'start'])
    open_port(port=80)


def stop():
    subprocess.call(['service', 'radosgw', 'stop'])
    open_port(port=80)


def restart():
    subprocess.call(['service', 'radosgw', 'restart'])
    open_port(port=80)


# XXX Define local canonical_url until charm has been updated to use the
#     standard context architecture.
def canonical_url(configs, endpoint_type=PUBLIC):
    scheme = 'http'
    address = resolve_address(endpoint_type)
    if is_ipv6(address):
        address = "[{}]".format(address)
    return '%s://%s' % (scheme, address)


@hooks.hook('identity-service-relation-joined')
def identity_joined(relid=None):
    if cmp_pkgrevno('radosgw', '0.55') < 0:
        log('Integration with keystone requires ceph >= 0.55')
        sys.exit(1)

    port = 80
    admin_url = '%s:%i/swift' % (canonical_url(ADMIN), port)
    internal_url = '%s:%s/swift/v1' % \
        (canonical_url(INTERNAL), port)
    public_url = '%s:%s/swift/v1' % \
        (canonical_url(PUBLIC), port)
    relation_set(service='swift',
                 region=config('region'),
                 public_url=public_url, internal_url=internal_url,
                 admin_url=admin_url,
                 requested_roles=config('operator-roles'),
                 relation_id=relid)


@hooks.hook('identity-service-relation-changed')
@restart_on_change({'/etc/ceph/ceph.conf': ['radosgw']})
def identity_changed():
    emit_cephconf()
    restart()


@hooks.hook('cluster-relation-changed',
            'cluster-relation-joined')
@restart_on_change({'/etc/haproxy/haproxy.cfg': ['haproxy']})
def cluster_changed():
    CONFIGS.write_all()
    for r_id in relation_ids('identity-service'):
        identity_joined(relid=r_id)


@hooks.hook('ha-relation-joined')
def ha_relation_joined():
    # Obtain the config values necessary for the cluster config. These
    # include multicast port and interface to bind to.
    corosync_bindiface = config('ha-bindiface')
    corosync_mcastport = config('ha-mcastport')
    vip = config('vip')
    if not vip:
        log('Unable to configure hacluster as vip not provided',
            level=ERROR)
        sys.exit(1)
    # Obtain resources
    # SWIFT_HA_RES = 'grp_swift_vips'
    resources = {
        'res_cephrg_haproxy': 'lsb:haproxy'
    }
    resource_params = {
        'res_cephrg_haproxy': 'op monitor interval="5s"'
    }

    vip_group = []
    for vip in vip.split():
        iface = get_iface_for_address(vip)
        if iface is not None:
            vip_key = 'res_cephrg_{}_vip'.format(iface)
            resources[vip_key] = 'ocf:heartbeat:IPaddr2'
            resource_params[vip_key] = (
                'params ip="{vip}" cidr_netmask="{netmask}"'
                ' nic="{iface}"'.format(vip=vip,
                                        iface=iface,
                                        netmask=get_netmask_for_address(vip))
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

    relation_set(init_services=init_services,
                 corosync_bindiface=corosync_bindiface,
                 corosync_mcastport=corosync_mcastport,
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


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
