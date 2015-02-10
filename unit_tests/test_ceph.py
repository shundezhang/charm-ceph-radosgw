from mock import call, patch, MagicMock
from test_utils import CharmTestCase, patch_open

import ceph

TO_PATCH = [
    'get_unit_hostname',
    'os',
    'subprocess',
    'time',
]

class CephRadosGWCephTests(CharmTestCase):

    def setUp(self):
        super(CephRadosGWCephTests, self).setUp(ceph, TO_PATCH)

    def test_is_quorum_leader(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = '{"state": "leader"}'
        self.assertEqual(ceph.is_quorum(), True)

    def test_is_quorum_notleader(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = '{"state": "notleader"}'
        self.assertEqual(ceph.is_quorum(), False)

    def test_is_quorum_valerror(self):
        self.get_unit_hostname.return_value = 'myhost'
        self.subprocess.check_output.return_value = "'state': 'bob'}"
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

#    def test_wait_for_quorum_yes(self):
#        _is_quorum = self.patch('is_quorum')
#        _is_quorum.return_value = False
#        self.time.return_value = None
#        ceph.wait_for_quorum()
#        self.time.sleep.assert_called_with(3)

#    def test_wait_for_quorum_no(self):
#        _is_quorum = self.patch('is_quorum')
#        _is_quorum.return_value = True
#        ceph.wait_for_quorum()
#        self.assertFalse(self.time.sleep.called)

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
        self.subprocess.check_output.return_value = 'Partition GUID code: 4FBD7E29-9D25-41B8-AFD0-062C0CEFF05D'
        self.assertEqual(ceph.is_osd_disk('/dev/fmd0'), True)
       
    def test_is_osd_disk_no(self):
        # XXX Insert real sgdisk output
        self.subprocess.check_output.return_value = 'Partition GUID code: 5FBD7E29-9D25-41B8-AFD0-062C0CEFF05D'
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
