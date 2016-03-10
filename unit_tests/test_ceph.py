import ceph
from mock import patch, call

from test_utils import CharmTestCase

TO_PATCH = [
    'get_unit_hostname',
    'os',
    'subprocess',
    'time',
]


def config_side_effect(*args):
    if args[0] == 'ceph-osd-replication-count':
        return 3
    elif args[0] == 'rgw-lightweight-pool-pg-num':
        return 10


class CephRadosGWCephTests(CharmTestCase):
    def setUp(self):
        super(CephRadosGWCephTests, self).setUp(ceph, TO_PATCH)

    def test_is_quorum_leader(self):
        self.os.path.exists.return_value = True
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = '{"state": "leader"}'
        self.assertEqual(ceph.is_quorum(), True)

    def test_is_quorum_notleader(self):
        self.os.path.exists.return_value = True
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = '{"state": "notleader"}'
        self.assertEqual(ceph.is_quorum(), False)

    def test_is_quorum_valerror(self):
        self.os.path.exists.return_value = True
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = "'state': 'bob'}"
        self.assertEqual(ceph.is_quorum(), False)

    def test_is_quorum_no_asok(self):
        self.os.path.exists.return_value = False
        self.assertEqual(ceph.is_quorum(), False)

    def test_is_leader(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.os.path.exists.return_value = True
        self.subprocess.check_output.return_value = '{"state": "leader"}'
        self.assertEqual(ceph.is_leader(), True)

    def test_is_leader_notleader(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.os.path.exists.return_value = True
        self.subprocess.check_output.return_value = '{"state": "notleader"}'
        self.assertEqual(ceph.is_leader(), False)

    def test_is_leader_valerror(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.os.path.exists.return_value = True
        self.subprocess.check_output.return_value = "'state': 'bob'}"
        self.assertEqual(ceph.is_leader(), False)

    def test_is_leader_noasok(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.os.path.exists.return_value = False
        self.assertEqual(ceph.is_leader(), False)

    def test_wait_for_quorum_yes(self):
        results = [True, False]

        def quorum():
            return results.pop()

        _is_quorum = self.patch('is_quorum')
        _is_quorum.side_effect = quorum
        ceph.wait_for_quorum()
        self.time.sleep.assert_called_with(3)

    def test_wait_for_quorum_no(self):
        _is_quorum = self.patch('is_quorum')
        _is_quorum.return_value = True
        ceph.wait_for_quorum()
        self.assertFalse(self.time.sleep.called)

    def test_wait_for_bootstrap(self):
        results = [True, False]

        def bootstrapped():
            return results.pop()

        _is_bootstrapped = self.patch('is_bootstrapped')
        _is_bootstrapped.side_effect = bootstrapped
        ceph.wait_for_bootstrap()
        self.time.sleep.assert_called_with(3)

    def test_add_bootstrap_hint(self):
        self.get_unit_hostname.return_value = 'myhost'
        cmd = [
            "ceph",
            "--admin-daemon",
            '/var/run/ceph/ceph-mon.myhost.asok',
            "add_bootstrap_peer_hint",
            'mypeer'
        ]
        self.os.path.exists.return_value = True
        ceph.add_bootstrap_hint('mypeer')
        self.subprocess.call.assert_called_with(cmd)

    def test_add_bootstrap_hint_noasok(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.os.path.exists.return_value = False
        ceph.add_bootstrap_hint('mypeer')
        self.assertFalse(self.subprocess.call.called)

    def test_is_osd_disk(self):
        # XXX Insert real sgdisk output
        self.subprocess.check_output.return_value = \
            'Partition GUID code: 4FBD7E29-9D25-41B8-AFD0-062C0CEFF05D'
        self.assertEqual(ceph.is_osd_disk('/dev/fmd0'), True)

    def test_is_osd_disk_no(self):
        # XXX Insert real sgdisk output
        self.subprocess.check_output.return_value = \
            'Partition GUID code: 5FBD7E29-9D25-41B8-AFD0-062C0CEFF05D'
        self.assertEqual(ceph.is_osd_disk('/dev/fmd0'), False)

    def test_rescan_osd_devices(self):
        cmd = [
            'udevadm', 'trigger',
            '--subsystem-match=block', '--action=add'
        ]
        ceph.rescan_osd_devices()
        self.subprocess.call.assert_called_with(cmd)

    def test_zap_disk(self):
        cmd = [
            'sgdisk', '--zap-all', '/dev/fmd0',
        ]
        ceph.zap_disk('/dev/fmd0')
        self.subprocess.check_call.assert_called_with(cmd)

    def test_import_osd_bootstrap_key(self):
        self.os.path.exists.return_value = False
        cmd = [
            'ceph-authtool',
            '/var/lib/ceph/bootstrap-osd/ceph.keyring',
            '--create-keyring',
            '--name=client.bootstrap-osd',
            '--add-key=mykey',
        ]
        ceph.import_osd_bootstrap_key('mykey')
        self.subprocess.check_call.assert_called_with(cmd)

    def test_is_bootstrapped(self):
        self.os.path.exists.return_value = True
        self.assertEqual(ceph.is_bootstrapped(), True)
        self.os.path.exists.return_value = False
        self.assertEqual(ceph.is_bootstrapped(), False)

    def test_import_radosgw_key(self):
        self.os.path.exists.return_value = False
        ceph.import_radosgw_key('mykey')
        cmd = [
            'ceph-authtool',
            '/etc/ceph/keyring.rados.gateway',
            '--create-keyring',
            '--name=client.radosgw.gateway',
            '--add-key=mykey'
        ]
        self.subprocess.check_call.assert_called_with(cmd)

    def test_get_named_key_create(self):
        self.get_unit_hostname.return_value = "myhost"
        self.subprocess.check_output.return_value = """

[client.dummy]
    key = AQAPiu1RCMb4CxAAmP7rrufwZPRqy8bpQa2OeQ==
"""
        self.assertEqual(ceph.get_named_key('dummy'),
                         'AQAPiu1RCMb4CxAAmP7rrufwZPRqy8bpQa2OeQ==')
        cmd = [
            'ceph',
            '--name', 'mon.',
            '--keyring',
            '/var/lib/ceph/mon/ceph-myhost/keyring',
            'auth', 'get-or-create', 'client.dummy',
            'mon', 'allow r', 'osd', 'allow rwx'
        ]
        self.subprocess.check_output.assert_called_with(cmd)

    def test_get_named_key_get(self):
        self.get_unit_hostname.return_value = "myhost"
        key = "AQAPiu1RCMb4CxAAmP7rrufwZPRqy8bpQa2OeQ=="
        self.subprocess.check_output.return_value = key
        self.assertEqual(ceph.get_named_key('dummy'), key)
        cmd = [
            'ceph',
            '--name', 'mon.',
            '--keyring',
            '/var/lib/ceph/mon/ceph-myhost/keyring',
            'auth', 'get-or-create', 'client.dummy',
            'mon', 'allow r', 'osd', 'allow rwx'
        ]
        self.subprocess.check_output.assert_called_with(cmd)

    @patch('ceph.CephBrokerRq')
    @patch('ceph.config')
    def test_create_rgw_pools_rq_with_prefix(self, config, broker):
        config.side_effect = config_side_effect
        ceph.get_create_rgw_pools_rq(prefix='us-east')
        broker.assert_has_calls([
            call().add_op_create_pool(
                replica_count=3, name='.rgw.buckets'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.root'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.control'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.gc'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.buckets'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.buckets.index'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.rgw.buckets.extra'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.log'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='us-east.intent-log.usage'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3,
                name='us-east.users.users.email.users.swift.users.uid')]
        )

    @patch('ceph.CephBrokerRq')
    @patch('ceph.config')
    def test_create_rgw_pools_rq_without_prefix(self, config, broker):
        config.side_effect = config_side_effect
        ceph.get_create_rgw_pools_rq(prefix=None)
        broker.assert_has_calls([
            call().add_op_create_pool(
                replica_count=3, name='.rgw.buckets'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.root'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.control'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.gc'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.buckets'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.buckets.index'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.rgw.buckets.extra'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.log'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3, name='.intent-log.usage'),
            call().add_op_create_pool(
                pg_num=10, replica_count=3,
                name='.users.users.email.users.swift.users.uid')]
        )
