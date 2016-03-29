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
    config,
)
from charmhelpers.contrib.openstack import (
    context,
    templating,
)
from charmhelpers.contrib.openstack.utils import (
    os_release,
    set_os_workload_status,
    make_assess_status_func,
    pause_unit,
    resume_unit,
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
    if not config('use-embedded-webserver'):
        if os.path.exists('/etc/apache2/conf-available'):
            BASE_RESOURCE_MAP.pop(APACHE_CONF)
        else:
            BASE_RESOURCE_MAP.pop(APACHE_24_CONF)
    else:
        BASE_RESOURCE_MAP.pop(APACHE_CONF)
        BASE_RESOURCE_MAP.pop(APACHE_24_CONF)
        BASE_RESOURCE_MAP.pop(APACHE_PORTS_CONF)

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


def services():
    ''' Returns a list of services associate with this charm '''
    _services = []
    for v in BASE_RESOURCE_MAP.values():
        _services.extend(v.get('services', []))
    return list(set(_services))


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


def assess_status(configs):
    """Assess status of current unit
    Decides what the state of the unit should be based on the current
    configuration.
    SIDE EFFECT: calls set_os_workload_status(...) which sets the workload
    status of the unit.
    Also calls status_set(...) directly if paused state isn't complete.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    assess_status_func(configs)()


def assess_status_func(configs):
    """Helper function to create the function that will assess_status() for
    the unit.
    Uses charmhelpers.contrib.openstack.utils.make_assess_status_func() to
    create the appropriate status function and then returns it.
    Used directly by assess_status() and also for pausing and resuming
    the unit.

    NOTE(ajkavanagh) ports are not checked due to race hazards with services
    that don't behave sychronously w.r.t their service scripts.  e.g.
    apache2.
    @param configs: a templating.OSConfigRenderer() object
    @return f() -> None : a function that assesses the unit's workload status
    """
    return make_assess_status_func(
        configs, REQUIRED_INTERFACES,
        charm_func=check_optional_relations,
        services=services(), ports=None)


def pause_unit_helper(configs):
    """Helper function to pause a unit, and then call assess_status(...) in
    effect, so that the status is correctly updated.
    Uses charmhelpers.contrib.openstack.utils.pause_unit() to do the work.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    _pause_resume_helper(pause_unit, configs)


def resume_unit_helper(configs):
    """Helper function to resume a unit, and then call assess_status(...) in
    effect, so that the status is correctly updated.
    Uses charmhelpers.contrib.openstack.utils.resume_unit() to do the work.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    _pause_resume_helper(resume_unit, configs)


def _pause_resume_helper(f, configs):
    """Helper function that uses the make_assess_status_func(...) from
    charmhelpers.contrib.openstack.utils to create an assess_status(...)
    function that can be used with the pause/resume of the unit
    @param f: the function to be used with the assess_status(...) function
    @returns None - this function is executed for its side-effect
    """
    # TODO(ajkavanagh) - ports= has been left off because of the race hazard
    # that exists due to service_start()
    f(assess_status_func(configs),
      services=services(),
      ports=None)
