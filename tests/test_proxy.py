import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import proxy


def request(host='127.0.0.1:8000', scheme='http', **headers):
    return SimpleNamespace(headers={'host': host, **{k.replace('_', '-'): v for k, v in headers.items()}},
                           url=SimpleNamespace(scheme=scheme))


class ProxyTests(unittest.TestCase):
    @patch.dict(os.environ, {'PUBLIC_URL': ''})
    def test_direct_requests_accept_only_their_own_origin(self):
        self.assertEqual(proxy.allowed_origins(request()), {'http://127.0.0.1:8000'})
        self.assertFalse(proxy.is_https(request()))

    def test_tailscale_serve_origin_is_accepted_when_listening_locally(self):
        via = request(x_forwarded_for='100.101.102.103', x_forwarded_host='casa.tail1234.ts.net', x_forwarded_proto='https')
        with patch.object(proxy, 'LOCAL_ONLY', True):
            self.assertIn('https://casa.tail1234.ts.net', proxy.allowed_origins(via))
            self.assertTrue(proxy.is_https(via))
        with patch.object(proxy, 'LOCAL_ONLY', False):
            # Exposed on the network, anyone could send these headers: they are ignored.
            self.assertNotIn('https://casa.tail1234.ts.net', proxy.allowed_origins(via))
            self.assertFalse(proxy.is_https(via))

    def test_public_url_from_environment(self):
        with patch.dict(os.environ, {'PUBLIC_URL': 'https://casa.tail1234.ts.net/, https://outra.ts.net'}):
            self.assertTrue({'https://casa.tail1234.ts.net', 'https://outra.ts.net'} <= proxy.allowed_origins(request()))


if __name__ == '__main__':
    unittest.main()
