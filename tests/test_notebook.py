import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

import httpx

from app.alerts import Alerts
from app.config import Config, Settings
from app.db import TZ, Database
from app.notebook import NotebookMonitor, notebook_url

MORNING = datetime(2026, 9, 30, 10, tzinfo=TZ).timestamp()
MINUTE = 60


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'history.sqlite3')
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(recipient='5511999999999', notebook_alerts_enabled=True, notebook_battery_percent=20,
                                  notebook_unplugged_minutes=15, notebook_offline_minutes=5))
        self.alerts = Alerts(self.db, self.config, None)
        self.monitor = NotebookMonitor(self.alerts, self.config, token=lambda: 'x' * 32)
        self.heard = []
        self.alerts.listeners.append(self.heard.append)
        self.reading = None

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        def handler(request):
            assert request.headers['Authorization'] == 'Bearer ' + 'x' * 32
            if self.reading is None:
                raise httpx.ConnectError('down')
            return httpx.Response(200, json=self.reading)
        return httpx.Client(transport=httpx.MockTransport(handler))

    def poll(self, minutes, **reading):
        self.reading = {'plugged': True, 'battery': 90, 'status': 'Full', 'host': 'nb', **reading} if reading is not False else None
        self.monitor.poll(self.client(), MORNING + minutes * MINUTE)

    def kinds(self):
        return [a['kind'] for a in self.heard]

    def test_unplugged_alert_waits_for_the_limit_and_comes_once(self):
        self.poll(0, plugged=False, battery=80)
        self.poll(14, plugged=False, battery=75)
        self.assertEqual(self.kinds(), [])
        self.poll(15, plugged=False, battery=74)
        self.poll(20, plugged=False, battery=70)
        self.assertEqual(self.kinds(), ['notebook_unplugged'])
        self.assertIn('74%', self.heard[0]['message'])

    def test_power_back_before_the_limit_is_silent(self):
        self.poll(0, plugged=False)
        self.poll(10, plugged=True)
        self.poll(30, plugged=True)
        self.assertEqual(self.kinds(), [])
        self.poll(31, plugged=False)  # A new outage starts counting again.
        self.poll(40, plugged=False)
        self.assertEqual(self.kinds(), [])

    def test_power_back_after_alert_is_announced(self):
        self.poll(0, plugged=False)
        self.poll(16, plugged=False)
        self.poll(20, plugged=True)
        self.assertEqual(self.kinds(), ['notebook_unplugged', 'notebook_power_back'])

    def test_low_battery_only_while_unplugged(self):
        self.poll(0, plugged=True, battery=10)
        self.assertEqual(self.kinds(), [])
        self.poll(1, plugged=False, battery=20)
        self.assertEqual(self.kinds(), ['notebook_battery'])

    def test_new_outage_alerts_again(self):
        for start in (0, 100):
            self.poll(start, plugged=False, battery=15)
            self.poll(start + 5, plugged=True)
        self.assertEqual(self.kinds().count('notebook_battery'), 2)

    def test_silence_alert_and_recovery(self):
        self.poll(0)
        self.reading = None
        for minute in (1, 5, 6, 9):
            self.monitor.poll(self.client(), MORNING + minute * MINUTE)
        self.assertEqual(self.kinds(), ['notebook_offline'])
        self.poll(12)
        self.assertEqual(self.kinds(), ['notebook_offline', 'notebook_online'])
        self.assertEqual(self.monitor.status(MORNING)['state'], 'ok')

    def test_short_silence_is_not_reported(self):
        self.reading = None
        self.monitor.poll(self.client(), MORNING)
        self.monitor.poll(self.client(), MORNING + 3 * MINUTE)
        self.poll(4)
        self.assertEqual(self.kinds(), [])

    def test_zero_turns_each_rule_off(self):
        self.config.save(self.config.get().model_copy(update={'notebook_unplugged_minutes': 0, 'notebook_offline_minutes': 0}))
        self.poll(0, plugged=False, battery=80)
        self.poll(600, plugged=False, battery=80)
        self.reading = None
        self.monitor.poll(self.client(), MORNING + 700 * MINUTE)
        self.assertEqual(self.kinds(), [])

    def test_disabled_does_nothing(self):
        self.config.save(self.config.get().model_copy(update={'notebook_alerts_enabled': False}))
        self.poll(0, plugged=False, battery=1)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.monitor.status()['state'], 'disabled')

    def test_status_reports_battery_mode(self):
        self.poll(0, plugged=False, battery=64)
        status = self.monitor.status(MORNING)
        self.assertEqual((status['state'], status['battery'], status['plugged']), ('battery', 64, False))

    def test_url_comes_from_the_camera_host(self):
        self.assertEqual(notebook_url('rtsp://192.168.1.103:8554/cam'), 'http://192.168.1.103:8765')
        self.assertEqual(notebook_url('0'), 'http://127.0.0.1:8765')  # A local camera: the monitor runs on this computer.


if __name__ == '__main__':
    unittest.main()
