#
# Copyright 2016 Canonical Ltd.
#
# Authors:
#  James Page <james.page@ubuntu.com>
#  Paul Collins <paul.collins@canonical.com>
#  Edward Hope-Morley <edward.hope-morley@canonical.com>
#

import os
import re
import jinja2

from copy import deepcopy
from collections import OrderedDict

import ceph_radosgw_context

from charmhelpers.core.hookenv import (
    relation_ids,
    status_get,
)
from charmhelpers.contrib.openstack import (
    context,
    templating,
)
from charmhelpers.contrib.openstack.utils import (
    os_release,
    set_os_workload_status,
)
from charmhelpers.contrib.hahelpers.cluster import get_hacluster_config
from charmhelpers.core.host import (
    cmp_pkgrevno,
    lsb_release,
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
    add_source,
    filter_installed_packages,
)

# The interface is said to be satisfied if anyone of the interfaces in the
# list has a complete context.
REQUIRED_INTERFACES = {
    'mon': ['ceph-radosgw'],
}
CEPHRG_HA_RES = 'grp_cephrg_vips'
TEMPLATES_DIR = 'templates'
TEMPLATES = 'templates/'
HAPROXY_CONF = '/etc/haproxy/haproxy.cfg'
CEPH_CONF = '/etc/ceph/ceph.conf'
APACHE_CONF = '/etc/apache2/sites-available/rgw'
APACHE_24_CONF = '/etc/apache2/sites-available/rgw.conf'
APACHE_PORTS_CONF = '/etc/apache2/ports.conf'

BASE_RESOURCE_MAP = OrderedDict([
    (HAPROXY_CONF, {
        'contexts': [context.HAProxyContext(singlenode_mode=True),
                     ceph_radosgw_context.HAProxyContext()],
        'services': ['haproxy'],
    }),
    (APACHE_CONF, {
        'contexts': [ceph_radosgw_context.ApacheContext()],
        'services': ['apache2'],
    }),
    (APACHE_24_CONF, {
        'contexts': [ceph_radosgw_context.ApacheContext()],
        'services': ['apache2'],
    }),
    (APACHE_PORTS_CONF, {
        'contexts': [ceph_radosgw_context.ApacheContext()],
        'services': ['apache2'],
    }),
    (CEPH_CONF, {
        'contexts': [ceph_radosgw_context.MonContext()],
        'services': ['radosgw'],
    }),
])


def resource_map():
    '''
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    '''
    if os.path.exists('/etc/apache2/conf-available'):
        BASE_RESOURCE_MAP.pop(APACHE_CONF)
    else:
        BASE_RESOURCE_MAP.pop(APACHE_24_CONF)

    resource_map = deepcopy(BASE_RESOURCE_MAP)
    return resource_map


# Hardcoded to icehouse to enable use of charmhelper templating/context tools
# Ideally these function would support non-OpenStack services
def register_configs(release='icehouse'):
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)
    CONFIGS = resource_map()
    pkg = 'radosgw'
    if not filter_installed_packages([pkg]) and cmp_pkgrevno(pkg, '0.55') >= 0:
        # Add keystone configuration if found
        CONFIGS[CEPH_CONF]['contexts'].append(
            ceph_radosgw_context.IdentityServiceContext()
        )
    for cfg, rscs in CONFIGS.iteritems():
        configs.register(cfg, rscs['contexts'])
    return configs


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir)
    )
    template = templates.get_template(template_name)
    return template.render(context)


def enable_pocket(pocket):
    apt_sources = "/etc/apt/sources.list"
    with open(apt_sources, "r") as sources:
        lines = sources.readlines()
    with open(apt_sources, "w") as sources:
        for line in lines:
            if pocket in line:
                sources.write(re.sub('^# deb', 'deb', line))
            else:
                sources.write(line)


def check_optional_relations(configs):
    required_interfaces = {}
    if relation_ids('ha'):
        required_interfaces['ha'] = ['cluster']
        try:
            get_hacluster_config()
        except:
            return ('blocked',
                    'hacluster missing configuration: '
                    'vip, vip_iface, vip_cidr')
    if cmp_pkgrevno('radosgw', '0.55') >= 0 and \
            relation_ids('identity-service'):
        required_interfaces['identity'] = ['identity-service']
    if required_interfaces:
        set_os_workload_status(configs, required_interfaces)
        return status_get()
    else:
        return 'unknown', 'No optional relations'


def setup_ipv6():
    ubuntu_rel = lsb_release()['DISTRIB_CODENAME'].lower()
    if ubuntu_rel < "trusty":
        raise Exception("IPv6 is not supported in the charms for Ubuntu "
                        "versions less than Trusty 14.04")

    # Need haproxy >= 1.5.3 for ipv6 so for Trusty if we are <= Kilo we need to
    # use trusty-backports otherwise we can use the UCA.
    if ubuntu_rel == 'trusty' and os_release('ceph-common') < 'liberty':
        add_source('deb http://archive.ubuntu.com/ubuntu trusty-backports '
                   'main')
        apt_update(fatal=True)
        apt_install('haproxy/trusty-backports', fatal=True)
