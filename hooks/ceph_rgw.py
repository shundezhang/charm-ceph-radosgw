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
CEPH_POOL_APP_NAME = 'rgw'


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
            '.rgw.buckets.index': 3.00,
            '.rgw.buckets.extra': 1.00
        }
        w = weights.get(pool, 0.10)
        if prefix:
            pool = "{prefix}{pool}".format(prefix=prefix, pool=pool)
        if pg_num > 0:
            rq.add_op_create_pool(name=pool, replica_count=replicas,
                                  pg_num=pg_num, group='objects',
                                  app_name=CEPH_POOL_APP_NAME)
        else:
            rq.add_op_create_pool(name=pool, replica_count=replicas,
                                  weight=w, group='objects',
                                  app_name=CEPH_POOL_APP_NAME)

    from apt import apt_pkg

    apt_pkg.init()
    rq = CephBrokerRq()
    replicas = config('ceph-osd-replication-count')

    prefix = prefix or 'default'

    # Buckets likely to contain the most data and therefore
    # requiring the most PGs
    heavy = [
        '.rgw.buckets.data'
    ]
    bucket_weight = config('rgw-buckets-pool-weight')
    for pool in heavy:
        pool = "{prefix}{pool}".format(prefix=prefix, pool=pool)
        rq.add_op_create_pool(name=pool, replica_count=replicas,
                              weight=bucket_weight, group='objects',
                              app_name=CEPH_POOL_APP_NAME)

    # NOTE: we want these pools to have a smaller pg_num/pgp_num than the
    # others since they are not expected to contain as much data
    light = [
        '.rgw.control',
        '.rgw.data.root',
        '.rgw.gc',
        '.rgw.log',
        '.rgw.intent-log',
        '.rgw.meta',
        '.rgw.usage',
        '.rgw.users.keys',
        '.rgw.users.email',
        '.rgw.users.swift',
        '.rgw.users.uid',
        '.rgw.buckets.extra',
        '.rgw.buckets.index',
    ]
    pg_num = config('rgw-lightweight-pool-pg-num')
    for pool in light:
        _add_light_pool(rq, pool, pg_num, prefix)

    _add_light_pool(rq, '.rgw.root', pg_num)

    if config('restrict-ceph-pools'):
        rq.add_op_request_access_to_group(name="objects",
                                          permission='rwx',
                                          key_name='radosgw.gateway')

    return rq
