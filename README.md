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
      charm: cs:xenial/ceph-radosgw
      num_units: 1
      bindings:
        public: public-space
        admin: admin-space
        internal: internal-space

NOTE: Spaces must be configured in the underlying provider prior to attempting to use them.

NOTE: Existing deployments using os-*-network configuration options will continue to function; these options are preferred over any network space binding provided if set.

Contact Information
===================

Author: James Page <james.page@ubuntu.com>
Report bugs at: http://bugs.launchpad.net/charms/+source/ceph-radosgw/+filebug
Location: http://jujucharms.com/charms/ceph-radosgw

Bootnotes
=========

The Ceph RADOS Gateway makes use of a multiverse package libapache2-mod-fastcgi.
As such it will try to automatically enable the multiverse pocket in
/etc/apt/sources.list.  Note that there is noting 'wrong' with multiverse
components - they typically have less liberal licensing policies or suchlike.
