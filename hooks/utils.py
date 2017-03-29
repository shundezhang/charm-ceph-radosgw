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
import re
import subprocess
import sys

from collections import OrderedDict
from copy import deepcopy

import ceph_radosgw_context

from charmhelpers.core.hookenv import (
    log,
    DEBUG,
    INFO,
    relation_get,
    relation_ids,
    application_version_set,
)
from charmhelpers.contrib.network.ip import (
    format_ipv6_addr,
    is_ipv6,
)
from charmhelpers.contrib.openstack import (
    context,
    templating,
)
from charmhelpers.contrib.openstack.utils import (
    make_assess_status_func,
    pause_unit,
    resume_unit,
)
from charmhelpers.contrib.hahelpers.cluster import get_hacluster_config
from charmhelpers.core.host import (
    cmp_pkgrevno,
    lsb_release,
    mkdir,
    CompareHostReleases,
)
from charmhelpers.fetch import (
    apt_cache,
    apt_install,
    apt_update,
    add_source,
    filter_installed_packages,
    get_upstream_version,
)

# NOTE: some packages are installed by the charm so may not be available
#       yet. Calls that depend on them should be aware of this (and use the
#       defer_if_unavailable() decorator).
try:
    import keystoneclient
    from keystoneclient.v2_0 import client
    try:
        # Kilo and newer
        from keystoneclient.exceptions import (
            ConnectionRefused,
            Forbidden,
        )
    except ImportError:
        # Juno and older
        from keystoneclient.exceptions import (
            ConnectionError as ConnectionRefused,
            Forbidden,
        )
except ImportError:
    keystoneclient = None

# This is installed as a dep of python-keystoneclient
try:
    import requests
except ImportError:
    requests = None

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

VERSION_PACKAGE = 'radosgw'

BASE_RESOURCE_MAP = OrderedDict([
    (HAPROXY_CONF, {
        'contexts': [context.HAProxyContext(singlenode_mode=True),
                     ceph_radosgw_context.HAProxyContext()],
        'services': ['haproxy'],
    }),
    (CEPH_CONF, {
        'contexts': [ceph_radosgw_context.MonContext()],
        'services': ['radosgw'],
    }),
])


class KSCertSetupException(BaseException):
    """Keystone SSL Certificate Setup Exception.

    This exception should be raised if any part of cert setup fails.
    """
    pass


def resource_map():
    """Dynamically generate a map of resources.

    These will be managed for a single hook execution.
    """
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


def services():
    """Returns a list of services associate with this charm."""
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


def get_optional_interfaces():
    """Return the optional interfaces that should be checked if the relavent
    relations have appeared.
    :returns: {general_interface: [specific_int1, specific_int2, ...], ...}
    """
    optional_interfaces = {}
    if relation_ids('ha'):
        optional_interfaces['ha'] = ['cluster']
    if (cmp_pkgrevno('radosgw', '0.55') >= 0 and
            relation_ids('identity-service')):
        optional_interfaces['identity'] = ['identity-service']
    return optional_interfaces


def check_optional_relations(configs):
    """Check that if we have a relation_id for high availability that we can
    get the hacluster config.  If we can't then we are blocked.  This function
    is called from assess_status/set_os_workload_status as the charm_func and
    needs to return either 'unknown', '' if there is no problem or the status,
    message if there is a problem.

    :param configs: an OSConfigRender() instance.
    :return 2-tuple: (string, string) = (status, message)
    """
    if relation_ids('ha'):
        try:
            get_hacluster_config()
        except:
            return ('blocked',
                    'hacluster missing configuration: '
                    'vip, vip_iface, vip_cidr')
    # return 'unknown' as the lowest priority to not clobber an existing
    # status.
    return 'unknown', ''


def setup_ipv6():
    ubuntu_rel = lsb_release()['DISTRIB_CODENAME'].lower()
    if CompareHostReleases(ubuntu_rel) < "trusty":
        raise Exception("IPv6 is not supported in the charms for Ubuntu "
                        "versions less than Trusty 14.04")

    from apt import apt_pkg
    apt_pkg.init()

    # Need haproxy >= 1.5.3 for ipv6 so for Trusty if we are <= Kilo we need to
    # use trusty-backports otherwise we can use the UCA.
    vc = apt_pkg.version_compare(get_pkg_version('haproxy'), '1.5.3')
    if ubuntu_rel == 'trusty' and vc == -1:
        add_source('deb http://archive.ubuntu.com/ubuntu trusty-backports '
                   'main')
        apt_update(fatal=True)
        apt_install('haproxy/trusty-backports', fatal=True)


def assess_status(configs):
    """Assess status of current unit.

    Decides what the state of the unit should be based on the current
    configuration.
    SIDE EFFECT: calls set_os_workload_status(...) which sets the workload
    status of the unit.
    Also calls status_set(...) directly if paused state isn't complete.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    assess_status_func(configs)()
    application_version_set(get_upstream_version(VERSION_PACKAGE))


def assess_status_func(configs):
    """Helper function to create the function that will assess_status() for
    the unit.
    Uses charmhelpers.contrib.openstack.utils.make_assess_status_func() to
    create the appropriate status function and then returns it.
    Used directly by assess_status() and also for pausing and resuming
    the unit.

    NOTE: REQUIRED_INTERFACES is augmented with the optional interfaces
    depending on the current config before being passed to the
    make_assess_status_func() function.

    NOTE(ajkavanagh) ports are not checked due to race hazards with services
    that don't behave sychronously w.r.t their service scripts.  e.g.
    apache2.
    @param configs: a templating.OSConfigRenderer() object
    @return f() -> None : a function that assesses the unit's workload status
    """
    required_interfaces = REQUIRED_INTERFACES.copy()
    required_interfaces.update(get_optional_interfaces())
    return make_assess_status_func(
        configs, required_interfaces,
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


def get_pkg_version(name):
    from apt import apt_pkg
    pkg = apt_cache()[name]
    version = apt_pkg.upstream_version(pkg.current_ver.ver_str)
    return version


def defer_if_unavailable(modules):
    """If a function depends on a package/module that is installed by the charm
    but may not yet have been installed, it can be deferred using this
    decorator.

    :param modules: list of modules that must be importable.
    """
    def _inner1_defer_if_unavailable(f):
        def _inner2_defer_if_unavailable(*args, **kwargs):
            for m in modules:
                if m not in sys.modules:
                    log("Module '{}' does not appear to be available "
                        "yet - deferring call to '{}' until it "
                        "is.".format(m, f.__name__), level=INFO)
                    return

            return f(*args, **kwargs)

        return _inner2_defer_if_unavailable

    return _inner1_defer_if_unavailable


@defer_if_unavailable(['keystoneclient'])
def get_ks_cert(ksclient, auth_endpoint, cert_type):
    """Get certificate from keystone.

    :param admin_token: Keystone admin token
    :param auth_endpoint: Keystone auth endpoint url
    :param certs_path: Path to local certs store
    :returns: certificate
    """
    try:
        try:
            # Kilo and newer
            if cert_type == 'ca':
                cert = ksclient.certificates.get_ca_certificate()
            elif cert_type == 'signing':
                cert = ksclient.certificates.get_signing_certificate()
            else:
                raise KSCertSetupException("Invalid cert type "
                                           "'{}'".format(cert_type))
        except AttributeError:
            # Juno and older
            cert = requests.request('GET', "{}/certificates/{}".
                                    format(auth_endpoint, cert_type)).text
    except (ConnectionRefused, requests.exceptions.ConnectionError, Forbidden):
        raise KSCertSetupException("Error connecting to keystone")

    return cert


@defer_if_unavailable(['keystoneclient'])
def get_ks_ca_cert(admin_token, auth_endpoint, certs_path):
    """"Get and store keystone CA certificate.

    :param admin_token: Keystone admin token
    :param auth_endpoint: Keystone auth endpoint url
    :param certs_path: Path to local certs store
    :returns: None
    """
    ksclient = client.Client(token=admin_token, endpoint=auth_endpoint)
    ca_cert = get_ks_cert(ksclient, auth_endpoint, 'ca')
    if ca_cert:
        try:
            # Cert should not contain unicode chars.
            str(ca_cert)
        except UnicodeEncodeError:
            raise KSCertSetupException("Did not get a valid ca cert from "
                                       "keystone - cert setup incomplete")

        log("Updating ca cert from keystone", level=DEBUG)
        ca = os.path.join(certs_path, 'ca.pem')
        with open(ca, 'w') as fd:
            fd.write(ca_cert)

        out = subprocess.check_output(['openssl', 'x509', '-in', ca,
                                       '-pubkey'])
        p = subprocess.Popen(['certutil', '-d', certs_path, '-A', '-n', 'ca',
                              '-t', 'TCu,Cu,Tuw'], stdin=subprocess.PIPE)
        p.communicate(out)
    else:
        raise KSCertSetupException("No ca cert available from keystone")


@defer_if_unavailable(['keystoneclient'])
def get_ks_signing_cert(admin_token, auth_endpoint, certs_path):
    """"Get and store keystone signing certificate.

    :param admin_token: Keystone admin token
    :param auth_endpoint: Keystone auth endpoint url
    :param certs_path: Path to local certs store
    :returns: None
    """
    ksclient = client.Client(token=admin_token, endpoint=auth_endpoint)
    signing_cert = get_ks_cert(ksclient, auth_endpoint, 'signing')
    if signing_cert:
        try:
            # Cert should not contain unicode chars.
            str(signing_cert)
        except UnicodeEncodeError:
            raise KSCertSetupException("Invalid signing cert from keystone")

        log("Updating signing cert from keystone", level=DEBUG)
        signing_cert_path = os.path.join(certs_path, 'signing_certificate.pem')
        with open(signing_cert_path, 'w') as fd:
            fd.write(signing_cert)

        out = subprocess.check_output(['openssl', 'x509', '-in',
                                       signing_cert_path, '-pubkey'])
        p = subprocess.Popen(['certutil', '-A', '-d', certs_path, '-n',
                              'signing_cert', '-t', 'P,P,P'],
                             stdin=subprocess.PIPE)
        p.communicate(out)
    else:
        raise KSCertSetupException("No signing cert available from keystone")


@defer_if_unavailable(['keystoneclient'])
def setup_keystone_certs(unit=None, rid=None):
    """
    Get CA and signing certs from Keystone used to decrypt revoked token list.

    :param unit: context unit id
    :param rid: context relation id
    :returns: None
    """
    certs_path = '/var/lib/ceph/nss'
    if not os.path.exists(certs_path):
        mkdir(certs_path)

    rdata = relation_get(unit=unit, rid=rid)
    required = ['admin_token', 'auth_host', 'auth_port']
    settings = {key: rdata.get(key) for key in required}
    if not all(settings.values()):
        log("Missing relation settings ({}) - deferring cert setup".format(
            ', '.join([k for k in settings if not settings[k]])),
            level=DEBUG)
        return

    auth_protocol = rdata.get('auth_protocol', 'http')
    if is_ipv6(settings.get('auth_host')):
        settings['auth_host'] = format_ipv6_addr(settings.get('auth_host'))

    auth_endpoint = "{}://{}:{}/v2.0".format(auth_protocol,
                                             settings['auth_host'],
                                             settings['auth_port'])

    try:
        get_ks_ca_cert(settings['admin_token'], auth_endpoint, certs_path)
        get_ks_signing_cert(settings['admin_token'], auth_endpoint, certs_path)
    except KSCertSetupException as e:
        log("Keystone certs setup incomplete - {}".format(e), level=INFO)
