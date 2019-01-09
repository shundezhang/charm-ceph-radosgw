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

from utils import get_pkg_version

from charmhelpers.core.hookenv import (
    config,
)

from charmhelpers.core.host import (
    mkdir,
    symlink,
)
from charmhelpers.contrib.storage.linux.ceph import (
    CephBrokerRq,
)

CEPH_DIR = '/etc/ceph'
CEPH_RADOSGW_DIR = '/var/lib/ceph/radosgw'
_radosgw_keyring = "keyring.rados.gateway"


def import_radosgw_key(key, name=None):
    if name:
        keyring_path = os.path.join(CEPH_RADOSGW_DIR,
                                    'ceph-{}'.format(name),
                                    'keyring')
        link_path = os.path.join(CEPH_DIR,
                                 'ceph.client.{}.keyring'.format(name))
        owner = group = 'ceph'
    else:
        keyring_path = os.path.join(CEPH_DIR, _radosgw_keyring)
        link_path = None
        owner = group = 'root'

    if not os.path.exists(keyring_path):
        mkdir(path=os.path.dirname(keyring_path),
              owner=owner, group=group, perms=0o750)
        cmd = [
            'ceph-authtool',
            keyring_path,
            '--create-keyring',
            '--name=client.{}'.format(
                name or 'radosgw.gateway'
            ),
            '--add-key={}'.format(key)
        ]
        subprocess.check_call(cmd)
        cmd = [
            'chown',
            '{}:{}'.format(owner, group),
            keyring_path
        ]
        subprocess.check_call(cmd)
        # NOTE: add a link to the keyring in /var/lib/ceph
        # to /etc/ceph so we can use it for radosgw-admin
        # operations for multi-site configuration
        if link_path:
            symlink(keyring_path, link_path)
        return True

    return False


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
