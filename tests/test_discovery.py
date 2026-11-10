import importlib.util
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import discovery

spec = importlib.util.spec_from_file_location('casa_monitor', Path(__file__).resolve().parents[1] / 'notebook' / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class Hosts(unittest.TestCase):
    def test_only_private_lan_addresses(self):
        for ok in ('192.168.0.20', '10.1.2.3', '172.16.5.5', '127.0.0.1'):
            self.assertTrue(discovery.is_allowed_host(ok), ok)
        for bad in ('8.8.8.8', '169.254.1.1', '0.0.0.0', '224.0.0.1', 'example.com', '::1', '192.168.0.1:80', ''):
            self.assertFalse(discovery.is_allowed_host(bad), bad)

    def test_pair_rejects_bad_input_without_network(self):
        with self.assertRaises(ValueError):
            discovery.pair('8.8.8.8', '123456', 'x' * 40)
        with self.assertRaises(ValueError):
            discovery.pair('192.168.0.9', '12', 'x' * 40)


class PairingCode(unittest.TestCase):
    def test_wrong_codes_lock_then_rotate(self):
        p = monitor.Pairing()
        code = p.current(100)
        for _ in range(monitor.Pairing.MAX_FAILS):
            self.assertFalse(p.check('000000' if code != '000000' else '111111', 100))
        self.assertFalse(p.check(code, 105))   # bloqueado: nem o código certo vale por 30 s
        self.assertTrue(p.check(p.current(200), 200))

    def test_code_expires(self):
        p = monitor.Pairing()
        first = p.current(0)
        self.assertEqual(p.current(10), first)
        p.current(monitor.Pairing.TTL + 1)   # gera outro (pode coincidir por acaso, mas o relógio reinicia)
        self.assertGreater(p.born, 0)


class TotemOverHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (monitor.TOKEN_FILE, monitor.Handler.token, monitor.Handler.pairing, discovery.PORT)
        monitor.TOKEN_FILE = Path(self.tmp.name) / 'cfg' / 'token'
        monitor.Handler.token = ''
        monitor.Handler.pairing = monitor.Pairing()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), monitor.Handler)
        discovery.PORT = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        monitor.TOKEN_FILE, monitor.Handler.token, monitor.Handler.pairing, discovery.PORT = self.old
        self.tmp.cleanup()

    def test_discover_pair_and_recognize(self):
        found = discovery.probe('127.0.0.1')
        self.assertFalse(found['paired'])
        self.assertFalse(found['mine'])
        token = discovery.new_token()
        with self.assertRaisesRegex(ValueError, 'incorreto'):
            discovery.pair('127.0.0.1', '000000' if monitor.Handler.pairing.current() != '000000' else '111111', token)
        discovery.pair('127.0.0.1', monitor.Handler.pairing.current(), token)
        self.assertEqual(monitor.TOKEN_FILE.read_text(), token)
        self.assertEqual(oct(monitor.TOKEN_FILE.stat().st_mode & 0o777), '0o600')
        again = discovery.probe('127.0.0.1', token)
        self.assertTrue(again['paired'] and again['mine'])
        self.assertFalse(discovery.probe('127.0.0.1', discovery.new_token())['mine'])   # pareado com outro computador
        with self.assertRaisesRegex(ValueError, 'já está pareado'):
            discovery.pair('127.0.0.1', '123456', discovery.new_token())

    def test_scan_finds_it(self):
        import ipaddress
        result = discovery.scan('', networks=[ipaddress.ip_network('127.0.0.0/30')], timeout=.5)
        self.assertEqual([r['ip'] for r in result], ['127.0.0.1'])

    def test_unpaired_totem_authorizes_nothing(self):
        import httpx
        base = f'http://127.0.0.1:{discovery.PORT}'
        self.assertNotEqual(httpx.get(f'{base}/status', headers={'Authorization': 'Bearer x'}).status_code, 200)
        self.assertNotEqual(httpx.get(f'{base}/status').status_code, 200)
        state = httpx.get(f'{base}/state').json()
        self.assertEqual(len(state['pairing']['code']), 6)


class RemoteImageControls(TotemOverHttp):
    def test_panel_adjusts_the_totem_camera(self):
        import os
        import stat
        from unittest import mock
        from app import image_controls as ic
        token = discovery.new_token()
        discovery.pair('127.0.0.1', monitor.Handler.pairing.current(), token)
        log = Path(self.tmp.name) / 'calls.txt'
        fake = Path(self.tmp.name) / 'v4l2-ctl'
        fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n[ "$3" = "--list-ctrls" ] && echo "     gain 0x00980913 (int)    : min=0 max=255 step=1 default=0 value=77"\nexit 0\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        env = {'PATH': f'{self.tmp.name}:{os.environ["PATH"]}', 'MONITOR_CAMERA_DEVICE': '/dev/video-teste'}
        remote = ic.Remote(f'http://127.0.0.1:{discovery.PORT}', token)
        with mock.patch.dict(os.environ, env):
            self.assertEqual(ic.apply(remote, {'auto_exposure': 3, 'backlight_compensation': 1, 'gain': 10}), 3)
            self.assertEqual(ic.read(remote), {'gain': 77})
            self.assertEqual(ic.apply(ic.Remote(remote.url, 'x' * 40), {'gain': 1}), 0)   # token errado: o totem recusa
        calls = log.read_text()
        self.assertIn('-d /dev/video-teste --set-ctrl=auto_exposure=3', calls)
        self.assertIn('backlight_compensation=1,gain=10', calls)
        self.assertNotIn('gain=1\n', calls)


if __name__ == '__main__':
    unittest.main()
