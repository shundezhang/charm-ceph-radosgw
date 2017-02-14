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

import json
import os
import subprocess
import time


from socket import gethostname as get_unit_hostname

from utils import get_pkg_version

from charmhelpers.core.hookenv import (
    config,
)
from charmhelpers.contrib.storage.linux.ceph import (
    CephBrokerRq,
)

LEADER = 'leader'
PEON = 'peon'
QUORUM = [LEADER, PEON]


def is_quorum():
    asok = "/var/run/ceph/ceph-mon.{}.asok".format(get_unit_hostname())
    cmd = [
        "ceph",
        "--admin-daemon",
        asok,
        "mon_status"
    ]
    if os.path.exists(asok):
        try:
            result = json.loads(subprocess.check_output(cmd))
        except subprocess.CalledProcessError:
            return False
        except ValueError:
            # Non JSON response from mon_status
            return False
        if result['state'] in QUORUM:
            return True
        else:
            return False
    else:
        return False


def is_leader():
    asok = "/var/run/ceph/ceph-mon.{}.asok".format(get_unit_hostname())
    cmd = [
        "ceph",
        "--admin-daemon",
        asok,
        "mon_status"
    ]
    if os.path.exists(asok):
        try:
            result = json.loads(subprocess.check_output(cmd))
        except subprocess.CalledProcessError:
            return False
        except ValueError:
            # Non JSON response from mon_status
            return False
        if result['state'] == LEADER:
            return True
        else:
            return False
    else:
        return False


def wait_for_quorum():
    while not is_quorum():
        time.sleep(3)


def add_bootstrap_hint(peer):
    asok = "/var/run/ceph/ceph-mon.{}.asok".format(get_unit_hostname())
    cmd = [
        "ceph",
        "--admin-daemon",
        asok,
        "add_bootstrap_peer_hint",
        peer
    ]
    if os.path.exists(asok):
        # Ignore any errors for this call
        subprocess.call(cmd)


DISK_FORMATS = [
    'xfs',
    'ext4',
    'btrfs'
]


def is_osd_disk(dev):
    try:
        info = subprocess.check_output(['sgdisk', '-i', '1', dev])
        info = info.split("\n")  # IGNORE:E1103
        for line in info:
            if line.startswith(
                    'Partition GUID code: 4FBD7E29-9D25-41B8-AFD0-062C0CEFF05D'
            ):
                return True
    except subprocess.CalledProcessError:
        pass
    return False


def rescan_osd_devices():
    cmd = [
        'udevadm', 'trigger',
        '--subsystem-match=block', '--action=add'
    ]

    subprocess.call(cmd)


def zap_disk(dev):
    cmd = ['sgdisk', '--zap-all', dev]
    subprocess.check_call(cmd)


_bootstrap_keyring = "/var/lib/ceph/bootstrap-osd/ceph.keyring"


def is_bootstrapped():
    return os.path.exists(_bootstrap_keyring)


def wait_for_bootstrap():
    while (not is_bootstrapped()):
        time.sleep(3)


def import_osd_bootstrap_key(key):
    if not os.path.exists(_bootstrap_keyring):
        cmd = [
            'ceph-authtool',
            _bootstrap_keyring,
            '--create-keyring',
            '--name=client.bootstrap-osd',
            '--add-key={}'.format(key)
        ]
        subprocess.check_call(cmd)

# OSD caps taken from ceph-create-keys
_osd_bootstrap_caps = {
    'mon': [
        'allow command osd create ...',
        'allow command osd crush set ...',
        r'allow command auth add * osd allow\ * mon allow\ rwx',
        'allow command mon getmap'
    ]
}


def get_osd_bootstrap_key():
    return get_named_key('bootstrap-osd', _osd_bootstrap_caps)


_radosgw_keyring = "/etc/ceph/keyring.rados.gateway"


def import_radosgw_key(key):
    if not os.path.exists(_radosgw_keyring):
        cmd = [
            'ceph-authtool',
            _radosgw_keyring,
            '--create-keyring',
            '--name=client.radosgw.gateway',
            '--add-key={}'.format(key)
        ]
        subprocess.check_call(cmd)

# OSD caps taken from ceph-create-keys
_radosgw_caps = {
    'mon': ['allow r'],
    'osd': ['allow rwx']
}


def get_radosgw_key():
    return get_named_key('radosgw.gateway', _radosgw_caps)


_default_caps = {
    'mon': ['allow r'],
    'osd': ['allow rwx']
}


def get_named_key(name, caps=None):
    caps = caps or _default_caps
    cmd = [
        'ceph',
        '--name', 'mon.',
        '--keyring',
        '/var/lib/ceph/mon/ceph-{}/keyring'.format(
            get_unit_hostname()
        ),
        'auth', 'get-or-create', 'client.{}'.format(name),
    ]
    # Add capabilities
    for subsystem, subcaps in caps.iteritems():
        cmd.extend([
            subsystem,
            '; '.join(subcaps),
        ])
    output = subprocess.check_output(cmd).strip()  # IGNORE:E1103
    # get-or-create appears to have different output depending
    # on whether its 'get' or 'create'
    # 'create' just returns the key, 'get' is more verbose and
    # needs parsing
    key = None
    if len(output.splitlines()) == 1:
        key = output
    else:
        for element in output.splitlines():
            if 'key' in element:
                key = element.split(' = ')[1].strip()  # IGNORE:E1103
    return key


def get_create_rgw_pools_rq(prefix=None):
    """Pre-create RGW pools so that they have the correct settings.

    If a prefix is provided it will be prepended to each pool name.

    When RGW creates its own pools it will create them with non-optimal
    settings (LP: #1476749).

    NOTE: see http://docs.ceph.com/docs/master/radosgw/config-ref/#pools and
          http://docs.ceph.com/docs/master/radosgw/config/#create-pools for
          list of supported/required pools.
    """
    def _add_light_pool(rq, pool, pg_num, prefix=None):
        # Per the Ceph PG Calculator, all of the lightweight pools get 0.10%
        # of the data by default and only the .rgw.buckets.* get higher values
        weights = {
            '.rgw.buckets.index': 1.00,
            '.rgw.buckets.extra': 1.00
        }
        w = weights.get(pool, 0.10)
        if prefix:
            pool = "{prefix}{pool}".format(prefix=prefix, pool=pool)
        if pg_num > 0:
            rq.add_op_create_pool(name=pool, replica_count=replicas,
                                  pg_num=pg_num, group='objects')
        else:
            rq.add_op_create_pool(name=pool, replica_count=replicas,
                                  weight=w, group='objects')

    from apt import apt_pkg

    apt_pkg.init()
    rq = CephBrokerRq()
    replicas = config('ceph-osd-replication-count')

    # Jewel and above automatically always prefix pool names with zone when
    # creating them (see LP: 1573549).
    if prefix is None:
        vc = apt_pkg.version_compare(get_pkg_version('radosgw'), '10.0.0')
        if vc >= 0:
            prefix = 'default'
        else:
            prefix = ''

    # Buckets likely to contain the most data and therefore requiring the most
    # PGs
    heavy = ['.rgw.buckets']
    bucket_weight = config('rgw-buckets-pool-weight')
    for pool in heavy:
        pool = "{prefix}{pool}".format(prefix=prefix, pool=pool)
        rq.add_op_create_pool(name=pool, replica_count=replicas,
                              weight=bucket_weight, group='objects')

    # NOTE: we want these pools to have a smaller pg_num/pgp_num than the
    # others since they are not expected to contain as much data
    light = ['.rgw',
             '.rgw.root',
             '.rgw.control',
             '.rgw.gc',
             '.rgw.buckets.index',
             '.rgw.buckets.extra',
             '.log',
             '.intent-log',
             '.usage',
             '.users',
             '.users.email',
             '.users.swift',
             '.users.uid']
    pg_num = config('rgw-lightweight-pool-pg-num')
    for pool in light:
        _add_light_pool(rq, pool, pg_num, prefix)

    if prefix:
        light_unprefixed = ['.rgw.root']
        for pool in light_unprefixed:
            _add_light_pool(rq, pool, pg_num)

    if config('restrict-ceph-pools'):
        rq.add_op_request_access_to_group(name="objects",
                                          permission='rwx',
                                          key_name='radosgw.gateway')

    return rq
