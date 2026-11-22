import http.client
import os
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['MONITOR_PHOTOS_DIR'] = str(Path(TEMP.name) / 'screen-photos')

import httpx

from app.config import Config, Settings
from app.db import Database
from app.notebook import NotebookMonitor
from app import push

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'notebook'))
import monitor


class KioskProcessTests(unittest.TestCase):
    def browser(self, profile):
        return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', f'--user-data-dir={profile}'])

    def test_only_the_screens_own_browser_is_found_and_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            mine, other = Path(folder) / 'casa-kiosk', Path(folder) / 'outro-perfil'
            ours, theirs = self.browser(mine), self.browser(other)
            try:
                time.sleep(.3)
                self.assertEqual(monitor.kiosk_pids(mine), [ours.pid])
                self.assertNotIn(os.getpid(), monitor.kiosk_pids(mine))
                self.assertEqual(monitor.stop_kiosk(mine, wait=3), 1)
                self.assertIsNotNone(ours.wait(timeout=5))
                self.assertIsNone(theirs.poll(), 'outro navegador foi fechado junto')
            finally:
                for process in (ours, theirs):
                    process.kill()
                    process.wait()

    def test_a_browser_that_rewrote_its_title_is_found_and_a_longer_folder_name_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            mine = Path(folder) / 'casa-kiosk'
            # One single argument with spaces, as Chrome leaves it after changing its title.
            titled = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', f'--app=x --user-data-dir={mine} --no-first-run'])
            lookalike = self.browser(Path(folder) / 'casa-kiosk-outro')
            try:
                time.sleep(.3)
                self.assertEqual(monitor.kiosk_pids(mine), [titled.pid])
            finally:
                for process in (titled, lookalike):
                    process.kill()
                    process.wait()

    def test_start_uses_the_script_and_the_session_variables(self):
        with tempfile.TemporaryDirectory() as folder:
            marker, script = Path(folder) / 'ran', Path(folder) / 'start.sh'
            script.write_text(f'#!/usr/bin/env bash\necho "$WAYLAND_DISPLAY|$XDG_RUNTIME_DIR" > {marker}\n')
            runtime = Path(folder) / 'run'
            runtime.mkdir()
            (runtime / 'wayland-7').touch()
            (runtime / 'wayland-7.lock').touch()
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(runtime)}), patch('monitor.shutil.which', return_value=None):
                monitor.start_kiosk(script)
            for _ in range(30):
                if marker.exists():
                    break
                time.sleep(.1)
            self.assertEqual(marker.read_text().strip(), f'wayland-7|{runtime}')


class RestartRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        monitor.Handler.token = 't' * 40
        monitor.Handler.desk = monitor.Desk()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), monitor.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, token=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        connection.request('POST', '/restart-screen', headers={'Authorization': f'Bearer {token}'} if token else {})
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status

    def test_post_restarts_the_screen_only_with_the_token(self):
        done = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'start-kiosk.sh'
            script.touch()
            with patch.object(monitor, 'KIOSK_SCRIPT', script), patch.object(monitor, 'restart_kiosk', lambda: done.set()):
                self.assertNotEqual(self.post(), 200)
                self.assertNotEqual(self.post('x' * 40), 200)
                self.assertFalse(done.wait(.3), 'reiniciou sem autorização')
                self.assertEqual(self.post('t' * 40), 200)
                self.assertTrue(done.wait(2), 'o pedido autorizado não reiniciou a tela')
            with patch.object(monitor, 'KIOSK_SCRIPT', Path(folder) / 'ausente.sh'):
                self.assertEqual(self.post('t' * 40), 409)


class DashboardAskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(notebook_url='http://192.168.1.103:8765'))
        self.monitor = NotebookMonitor(Database(path / 'h.sqlite3'), self.config, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ask_goes_to_the_screen_agent_and_errors_are_clear(self):
        calls = []
        def fake(url, **kwargs):
            calls.append(url)
            return httpx.Response(200, json={'ok': True})
        self.monitor.token = lambda: 't' * 40
        with patch('app.notebook.httpx.post', fake):
            self.monitor.restart_screen()
        self.assertTrue(calls[0].endswith('/restart-screen'))
        with patch('app.notebook.httpx.post', return_value=httpx.Response(404, json={})):
            with self.assertRaisesRegex(RuntimeError, 'desatualizado'):
                self.monitor.restart_screen()
        self.monitor.token = lambda: ''
        with self.assertRaisesRegex(RuntimeError, 'não está configurada'):
            self.monitor.restart_screen()


class FridgeTopicTests(unittest.TestCase):
    def test_fridge_alert_has_a_title_and_a_mutable_topic(self):
        self.assertIn('fridge', push.TITLES)
        self.assertIn('fridge', push.TOPICS)
        self.assertIn('fridge', push.IMMEDIATE)


if __name__ == '__main__':
    unittest.main()
