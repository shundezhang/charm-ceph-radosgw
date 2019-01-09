Overview
========

Ceph is a distributed storage and network file system designed to provide
excellent performance, reliability and scalability.

This charm deploys the RADOS Gateway, a S3 and Swift compatible HTTP gateway
for online object storage on-top of a ceph cluster.

Usage
=====

In order to use this charm, it is assumed that you have already deployed a ceph
storage cluster using the 'ceph' charm with something like this::

    juju deploy -n 3 --config ceph.yaml ceph

To deploy the RADOS gateway simple do::

    juju deploy ceph-radosgw
    juju add-relation ceph-radosgw ceph

You can then directly access the RADOS gateway by exposing the service::

    juju expose ceph-radosgw

The gateway can be accessed over port 80 (as show in juju status exposed
ports).

Access
======

Note that you will need to login to one of the service units supporting the
ceph charm to generate some access credentials::

    juju ssh ceph/0 \
      'sudo radosgw-admin user create --uid="ubuntu" --display-name="Ubuntu Ceph"'

For security reasons the ceph-radosgw charm is not set up with appropriate
permissions to administer the ceph cluster.

Keystone Integration
====================

Ceph >= 0.55 integrates with Openstack Keystone for authentication of Swift requests.

This is enabled by relating the ceph-radosgw service with keystone::

    juju deploy keystone
    juju add-relation keystone ceph-radosgw

If you try to relate the radosgw to keystone with an earlier version of ceph the hook
will error out to let you know.

HA/Clustering
=============

There are two mutually exclusive high availability options: using virtual
IP(s) or DNS. In both cases, a relationship to hacluster is required which
provides the corosync back end HA functionality.

To use virtual IP(s) the clustered nodes must be on the same subnet such that
the VIP is a valid IP on the subnet for one of the node's interfaces and each
node has an interface in said subnet. The VIP becomes a highly-available API
endpoint.

At a minimum, the config option 'vip' must be set in order to use virtual IP
HA. If multiple networks are being used, a VIP should be provided for each
network, separated by spaces. Optionally, vip_iface or vip_cidr may be
specified.

To use DNS high availability there are several prerequisites. However, DNS HA
does not require the clustered nodes to be on the same subnet.
Currently the DNS HA feature is only available for MAAS 2.0 or greater
environments. MAAS 2.0 requires Juju 2.0 or greater. The clustered nodes must
have static or "reserved" IP addresses registered in MAAS. The DNS hostname(s)
must be pre-registered in MAAS before use with DNS HA.

At a minimum, the config option 'dns-ha' must be set to true and at least one
of 'os-public-hostname', 'os-internal-hostname' or 'os-internal-hostname' must
be set in order to use DNS HA. One or more of the above hostnames may be set.

The charm will throw an exception in the following circumstances:
If neither 'vip' nor 'dns-ha' is set and the charm is related to hacluster
If both 'vip' and 'dns-ha' are set as they are mutually exclusive
If 'dns-ha' is set and none of the os-{admin,internal,public}-hostname(s) are
set

Network Space support
=====================

This charm supports the use of Juju Network Spaces, allowing the charm to be bound to network space configurations managed directly by Juju.  This is only supported with Juju 2.0 and above.

API endpoints can be bound to distinct network spaces supporting the network separation of public, internal and admin endpoints.

To use this feature, use the --bind option when deploying the charm:

    juju deploy ceph-radosgw --bind "public=public-space internal=internal-space admin=admin-space"

alternatively these can also be provided as part of a juju native bundle configuration:

    ceph-radosgw:
      charm: cs:ceph-radosgw
      num_units: 1
      bindings:
        public: public-space
        admin: admin-space
        internal: internal-space

NOTE: Spaces must be configured in the underlying provider prior to attempting to use them.

NOTE: Existing deployments using os-\*-network configuration options will continue to function; these options are preferred over any network space binding provided if set.

Multi-Site replication
======================

Overview
--------

This charm supports configuration of native replication between Ceph RADOS
gateway deployments.

This is supported both within a single model and between different models
using cross-model relations.

By default either ceph-radosgw deployment will accept write operations.

Deployment
----------

NOTE: example bundles for the us-west and us-east models can be found
in the bundles subdirectory of the ceph-radosgw charm.

NOTE: switching from a standalone deployment to a multi-site replicated
deployment is not supported.

To deploy in this configuration ensure that the following configuration
options are set on the ceph-radosgw charm deployments - in this example
rgw-us-east and rgw-us-west are both instances of the ceph-radosgw charm:

    rgw-us-east:
      realm: replicated
      zonegroup: us
      zone: us-east
    rgw-us-west:
      realm: replicated
      zonegroup: us
      zone: us-west

When deploying with this configuration the ceph-radosgw applications will
deploy into a blocked state until the master/slave (cross-model) relation
is added.

Typically each ceph-radosgw deployment will be associated with a separate
ceph cluster at different physical locations - in this example the deployments
are in different models ('us-east' and 'us-west').

One ceph-radosgw application acts as the initial master for the deployment -
setup the master relation endpoint as the provider of the offer for the
cross-model relation:

    juju offer -m us-east rgw-us-east:master

The cross-model relation offer can then be consumed in the other model and
related to the slave ceph-radosgw application:

    juju consume -m us-west admin/us-east.rgw-us-east
    juju add-relation -m us-west rgw-us-west:slave rgw-us-east:master

Once the relation has been added the realm, zonegroup and zone configuration
will be created in the master deployment and then synced to the slave
deployment.

The current sync status can be validated from either model:

    juju ssh -m us-east ceph-mon/0
    sudo radosgw-admin sync status
              realm 142eb39c-67c4-42b3-9116-1f4ffca23964 (replicated)
          zonegroup 7b69f059-425b-44f5-8a21-ade63c2034bd (us)
               zone 4ee3bc39-b526-4ac9-a233-64ebeacc4574 (us-east)
      metadata sync no sync (zone is master)
          data sync source: db876cf0-62a8-4b95-88f4-d0f543136a07 (us-west)
                            syncing
                            full sync: 0/128 shards
                            incremental sync: 128/128 shards
                            data is caught up with source

Once the deployment is complete, the default zone and zonegroup can
optionally be tidied using the 'tidydefaults' action:

    juju run-action -m us-west --unit rgw-us-west/0 tidydefaults

This operation is not reversible.

Failover/Recovery
-----------------

In the event that the site hosting the zone which is the master for metadata
(in this example us-east) has an outage, the master metadata zone must be
failed over to the slave site; this operation is performed using the 'promote'
action:

    juju run-action -m us-west --wait rgw-us-west/0 promote

Once this action has completed, the slave site will be the master for metadata
updates and the deployment will accept new uploads of data.

Once the failed site has been recovered it will resync and resume as a slave
to the promoted master site (us-west in this example).

The master metadata zone can be failed back to its original location once resync
has completed using the 'promote' action:

    juju run-action -m us-east --wait rgw-us-east/0 promote

Read/write vs Read-only
-----------------------

By default all zones within a deployment will be read/write capable but only
the master zone can be used to create new containers.

Non-master zones can optionally be marked as read-only by using the 'readonly'
action:

    juju run-action -m us-east --wait rgw-us-east/0 readonly

a zone that is currently read-only can be switched to read/write mode by either
promoting it to be the current master or by using the 'readwrite' action:

    juju run-action -m us-east --wait rgw-us-east/0 readwrite
