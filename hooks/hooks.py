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
    log,
    Hooks, UnregisteredHookError,
)
from charmhelpers.fetch import (
    apt_update,
    apt_install,
    add_source,
)
from utils import (
    render_template,
    get_host_ip,
    enable_pocket
)

from charmhelpers.payload.execd import execd_preinstall
from socket import gethostname as get_unit_hostname

hooks = Hooks()


def install_www_scripts():
    for x in glob.glob('files/www/*'):
        shutil.copy(x, '/var/www/')


NSS_DIR = '/var/lib/ceph/nss'


@hooks.hook('install')
def install():
    execd_preinstall()
    enable_pocket('multiverse')
    add_source(config('source'), config('key'))
    apt_update(fatal=True)
    apt_install(['radosgw',
                 'libapache2-mod-fastcgi',
                 'apache2',
                 'ntp'], fatal=True)
    os.makedirs(NSS_DIR)


def emit_cephconf():
    # Ensure ceph directory actually exists
    if not os.path.exists('/etc/ceph'):
        os.makedirs('/etc/ceph')

    cephcontext = {
        'auth_supported': get_auth() or 'none',
        'mon_hosts': ' '.join(get_mon_hosts()),
        'hostname': get_unit_hostname(),
        'version': ceph.get_ceph_version('radosgw')
    }

    # Check to ensure that correct version of ceph is
    # in use
    if ceph.get_ceph_version('radosgw') >= "0.55":
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
    with open('/etc/apache2/sites-available/rgw.conf', 'w') as apacheconf:
        apacheconf.write(render_template('rgw', apachecontext))


def apache_sites():
    if os.path.exists('/etc/apache2/sites-available/000-default.conf'):
        subprocess.check_call(['a2dissite', '000-default'])
    else:
        subprocess.check_call(['a2dissite', 'default'])
    subprocess.check_call(['a2ensite', 'rgw'])


def apache_modules():
    subprocess.check_call(['a2enmod', 'fastcgi'])
    subprocess.check_call(['a2enmod', 'rewrite'])


def apache_reload():
    subprocess.call(['service', 'apache2', 'reload'])


@hooks.hook('upgrade-charm',
            'config-changed')
def config_changed():
    emit_cephconf()
    emit_apacheconf()
    install_www_scripts()
    apache_sites()
    apache_modules()
    apache_reload()


def get_mon_hosts():
    hosts = []
    for relid in relation_ids('mon'):
        for unit in related_units(relid):
            hosts.append(
                '{}:6789'.format(get_host_ip(
                    relation_get('private-address',
                                 unit, relid)))
            )

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
                'auth_protocol': 'http',
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


@hooks.hook('identity-service-relation-joined',
            'identity-service-relation-changed')
def identity_joined(relid=None):
    if ceph.get_ceph_version('radosgw') < "0.55":
        log('Integration with keystone requires ceph >= 0.55')
        sys.exit(1)

    hostname = unit_get('private-address')
    admin_url = 'http://{}:80/swift'.format(hostname)
    internal_url = public_url = '{}/v1'.format(admin_url)
    relation_set(service='swift',
                 region=config('region'),
                 public_url=public_url, internal_url=internal_url,
                 admin_url=admin_url,
                 requested_roles=config('operator-roles'),
                 rid=relid)


def identity_changed():
    emit_cephconf()
    restart()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
