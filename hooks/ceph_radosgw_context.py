from charmhelpers.contrib.openstack import context
from charmhelpers.contrib.hahelpers.cluster import (
    determine_api_port,
    determine_apache_port,
)


class HAProxyContext(context.HAProxyContext):

    def __call__(self):
        ctxt = super(HAProxyContext, self).__call__()

        # Apache ports
        a_cephradosgw_api = determine_apache_port(80,
                                                  singlenode_mode=True)

        port_mapping = {
            'cephradosgw-server': [
                80, a_cephradosgw_api]
        }

        ctxt['cephradosgw_bind_port'] = determine_api_port(
            80,
            singlenode_mode=True,
        )

        # for haproxy.conf
        ctxt['service_ports'] = port_mapping
        return ctxt
