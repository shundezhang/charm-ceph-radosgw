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

import sys

from mock import (
    call,
    patch,
    mock_open,
    MagicMock,
)

import utils

from test_utils import CharmTestCase

TO_PATCH = [
    'application_version_set',
    'get_upstream_version',
]


class CephRadosGWUtilTests(CharmTestCase):
    def setUp(self):
        super(CephRadosGWUtilTests, self).setUp(utils, TO_PATCH)
        self.get_upstream_version.return_value = '10.2.2'

    def test_assess_status(self):
        with patch.object(utils, 'assess_status_func') as asf:
            callee = MagicMock()
            asf.return_value = callee
            utils.assess_status('test-config')
            asf.assert_called_once_with('test-config')
            callee.assert_called_once_with()
            self.get_upstream_version.assert_called_with(
                utils.VERSION_PACKAGE
            )
            self.application_version_set.assert_called_with('10.2.2')

    @patch.object(utils, 'get_optional_interfaces')
    @patch.object(utils, 'check_optional_relations')
    @patch.object(utils, 'REQUIRED_INTERFACES')
    @patch.object(utils, 'services')
    @patch.object(utils, 'make_assess_status_func')
    def test_assess_status_func(self,
                                make_assess_status_func,
                                services,
                                REQUIRED_INTERFACES,
                                check_optional_relations,
                                get_optional_interfaces):
        services.return_value = 's1'
        REQUIRED_INTERFACES.copy.return_value = {'int': ['test 1']}
        get_optional_interfaces.return_value = {'opt': ['test 2']}
        utils.assess_status_func('test-config')
        # ports=None whilst port checks are disabled.
        make_assess_status_func.assert_called_once_with(
            'test-config',
            {'int': ['test 1'], 'opt': ['test 2']},
            charm_func=check_optional_relations,
            services='s1', ports=None)

    def test_pause_unit_helper(self):
        with patch.object(utils, '_pause_resume_helper') as prh:
            utils.pause_unit_helper('random-config')
            prh.assert_called_once_with(utils.pause_unit, 'random-config')
        with patch.object(utils, '_pause_resume_helper') as prh:
            utils.resume_unit_helper('random-config')
            prh.assert_called_once_with(utils.resume_unit, 'random-config')

    @patch.object(utils, 'services')
    def test_pause_resume_helper(self, services):
        f = MagicMock()
        services.return_value = 's1'
        with patch.object(utils, 'assess_status_func') as asf:
            asf.return_value = 'assessor'
            utils._pause_resume_helper(f, 'some-config')
            asf.assert_called_once_with('some-config')
            # ports=None whilst port checks are disabled.
            f.assert_called_once_with('assessor', services='s1', ports=None)

    @patch.dict('sys.modules', {'requests': MagicMock(),
                                'keystoneclient': MagicMock()})
    @patch.object(utils, 'is_ipv6', lambda addr: False)
    @patch.object(utils, 'get_ks_signing_cert')
    @patch.object(utils, 'get_ks_ca_cert')
    @patch.object(utils, 'relation_get')
    @patch.object(utils, 'mkdir')
    def test_setup_keystone_certs(self, mock_mkdir, mock_relation_get,
                                  mock_get_ks_ca_cert,
                                  mock_get_ks_signing_cert):
        auth_host = 'foo/bar'
        auth_port = 80
        admin_token = '666'
        auth_url = 'http://%s:%s/v2.0' % (auth_host, auth_port)
        mock_relation_get.return_value = {'auth_host': auth_host,
                                          'auth_port': auth_port,
                                          'admin_token': admin_token}
        utils.setup_keystone_certs()
        mock_get_ks_signing_cert.assert_has_calls([call(admin_token, auth_url,
                                                        '/var/lib/ceph/nss')])
        mock_get_ks_ca_cert.assert_has_calls([call(admin_token, auth_url,
                                                   '/var/lib/ceph/nss')])

    def test_get_ks_signing_cert(self):
        auth_host = 'foo/bar'
        auth_port = 80
        admin_token = '666'
        auth_url = 'http://%s:%s/v2.0' % (auth_host, auth_port)

        mock_ksclient = MagicMock
        m = mock_open()
        with patch.dict('sys.modules',
                        {'requests': MagicMock(),
                         'keystoneclient': mock_ksclient,
                         'keystoneclient.exceptions': MagicMock(),
                         'keystoneclient.exceptions.ConnectionRefused':
                         MagicMock(),
                         'keystoneclient.exceptions.Forbidden': MagicMock(),
                         'keystoneclient.v2_0': MagicMock(),
                         'keystoneclient.v2_0.client': MagicMock()}):
            # Reimport
            del sys.modules['utils']
            import utils
            with patch.object(utils, 'subprocess') as mock_subprocess:
                with patch.object(utils, 'open', m, create=True):
                    mock_certificates = MagicMock()
                    mock_ksclient.certificates = mock_certificates
                    mock_certificates.get_signing_certificate.return_value = \
                        'signing_cert_data'
                    utils.get_ks_signing_cert(admin_token, auth_url,
                                              '/foo/bar')
                    mock_certificates.get_signing_certificate.return_value = \
                        None
                    self.assertRaises(utils.KSCertSetupException,
                                      utils.get_ks_signing_cert, admin_token,
                                      auth_url, '/foo/bar')

                c = ['openssl', 'x509', '-in',
                     '/foo/bar/signing_certificate.pem',
                     '-pubkey']
                mock_subprocess.check_output.assert_called_with(c)

    def test_get_ks_ca_cert(self):
        auth_host = 'foo/bar'
        auth_port = 80
        admin_token = '666'
        auth_url = 'http://%s:%s/v2.0' % (auth_host, auth_port)

        mock_ksclient = MagicMock
        m = mock_open()
        with patch.dict('sys.modules',
                        {'requests': MagicMock(),
                         'keystoneclient': mock_ksclient,
                         'keystoneclient.exceptions': MagicMock(),
                         'keystoneclient.exceptions.ConnectionRefused':
                         MagicMock(),
                         'keystoneclient.exceptions.Forbidden': MagicMock(),
                         'keystoneclient.v2_0': MagicMock(),
                         'keystoneclient.v2_0.client': MagicMock()}):
            # Reimport
            del sys.modules['utils']
            import utils
            with patch.object(utils, 'subprocess') as mock_subprocess:
                with patch.object(utils, 'open', m, create=True):
                    mock_certificates = MagicMock()
                    mock_ksclient.certificates = mock_certificates
                    mock_certificates.get_ca_certificate.return_value = \
                        'ca_cert_data'
                    utils.get_ks_ca_cert(admin_token, auth_url, '/foo/bar')
                    mock_certificates.get_ca_certificate.return_value = None
                    self.assertRaises(utils.KSCertSetupException,
                                      utils.get_ks_ca_cert, admin_token,
                                      auth_url, '/foo/bar')

                c = ['openssl', 'x509', '-in', '/foo/bar/ca.pem',
                     '-pubkey']
                mock_subprocess.check_output.assert_called_with(c)
