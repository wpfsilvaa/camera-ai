import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

import httpx

from app.alerts import STALE_SECONDS, Alerts, in_quiet_hours
from app.config import Config, Settings
from app.db import TZ, Database
from app.recorder import cleanup

PRIMARY, SISTER = '5511999999999', '5511888888888'
# 10:00 in São Paulo, outside the default quiet hours.
MORNING = datetime(2026, 9, 30, 10, tzinfo=TZ).timestamp()


class FakeCameras:
    def __init__(self):
        self.items = [{'id': 'main', 'name': 'Cozinha', 'enabled': True, 'analysis_enabled': True, 'state': 'online'}]

    def snapshots(self):
        return [dict(item) for item in self.items]


class AlertsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'history.sqlite3')
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(recipient=PRIMARY, additional_recipients=[SISTER], alerts_enabled=True,
                                  inactivity_hours=4, camera_offline_minutes=10, daily_summary_hour=21))
        self.cameras = FakeCameras()
        self.alerts = Alerts(self.db, self.config, self.cameras)
        self.sent, self.status = [], 200

    def tearDown(self):
        self.tmp.cleanup()

    def presence(self, when):
        event = self.db.start_event(when, 1)
        self.db.end_event(event, when + 60, 'absence')
        self.db.execute('UPDATE events SET last_seen=? WHERE id=?', (when + 60, event))

    def kinds(self):
        return [row['kind'] for row in self.db.rows('SELECT kind FROM alerts ORDER BY created,id')]

    def client(self):
        def handler(request):
            self.sent.append(json.loads(request.content))
            return httpx.Response(self.status, json={'message_id': 'x'})
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_fall_alert_tells_listeners_which_camera(self):
        heard = []
        self.alerts.listeners.append(heard.append)
        self.alerts.fall('sala', 'Sala', b'JPEG', 50, now=MORNING)
        self.assertEqual((heard[0]['kind'], heard[0]['camera_id'], heard[0]['image']), ('fall', 'sala', 1))

    def test_restricted_alert_names_the_person_with_the_photo(self):
        heard = []
        self.alerts.listeners.append(heard.append)
        self.alerts.restricted('main', 'Cozinha', b'JPEG', 'Meu pai', now=MORNING)
        self.assertEqual((heard[0]['kind'], heard[0]['camera_id'], heard[0]['image']), ('restricted', 'main', 1))
        self.assertIn('Meu pai entrou na área restrita da câmera Cozinha', heard[0]['message'])
        self.alerts.restricted('main', 'Cozinha', b'JPEG', None, now=MORNING + 60)
        self.assertTrue(heard[1]['message'].startswith('⚠️ Uma pessoa entrou'))

    def test_quiet_hours_wrap_midnight(self):
        self.assertTrue(in_quiet_hours(23, 22, 7))
        self.assertTrue(in_quiet_hours(3, 22, 7))
        self.assertFalse(in_quiet_hours(10, 22, 7))
        self.assertTrue(in_quiet_hours(14, 13, 15))
        self.assertFalse(in_quiet_hours(9, 8, 8))

    def test_inactivity_alerts_once_per_absence_and_respects_quiet_hours(self):
        self.presence(MORNING - 5 * 3600)
        self.alerts.check(MORNING)
        self.alerts.check(MORNING + 600)
        self.assertEqual(self.kinds(), ['inactivity'])
        self.assertEqual(len(self.db.rows('SELECT * FROM alert_deliveries')), 2)
        # A new absence period gets a new alert, but not during the night.
        self.presence(MORNING + 3600)
        night = datetime(2026, 9, 30, 23, tzinfo=TZ).timestamp()
        self.alerts.check(night)
        self.assertEqual(self.kinds().count('inactivity'), 1)

    def test_no_inactivity_alert_without_a_working_camera(self):
        self.presence(MORNING - 5 * 3600)
        self.cameras.items[0]['analysis_enabled'] = False
        self.alerts.check(MORNING)
        self.cameras.items[0].update(analysis_enabled=True, state='offline')
        self.alerts.check(MORNING)
        self.assertNotIn('inactivity', self.kinds())

    def test_camera_offline_and_recovery(self):
        self.cameras.items[0]['state'] = 'offline'
        self.alerts.check(MORNING)
        self.alerts.check(MORNING + 300)
        self.assertEqual(self.kinds(), [])
        self.alerts.check(MORNING + 601)
        self.alerts.check(MORNING + 900)
        self.assertEqual(self.kinds(), ['camera_offline'])
        self.cameras.items[0]['state'] = 'online'
        self.alerts.check(MORNING + 1200)
        self.assertEqual(self.kinds(), ['camera_offline', 'camera_online'])
        # A short drop below the limit does not report a recovery either.
        self.cameras.items[0]['state'] = 'offline'
        self.alerts.check(MORNING + 1300)
        self.cameras.items[0]['state'] = 'online'
        self.alerts.check(MORNING + 1400)
        self.assertEqual(self.kinds(), ['camera_offline', 'camera_online'])

    def test_paused_camera_is_not_reported(self):
        self.cameras.items[0].update(enabled=False, state='paused')
        self.alerts.check(MORNING)
        self.alerts.check(MORNING + 3600)
        self.assertEqual(self.kinds(), [])

    def test_daily_summary_once_after_the_hour(self):
        self.presence(MORNING)
        evening = datetime(2026, 9, 30, 21, 5, tzinfo=TZ).timestamp()
        self.alerts.check(evening - 3600)
        self.assertNotIn('summary', self.kinds())
        self.alerts.check(evening)
        self.alerts.check(evening + 60)
        summaries = self.db.rows("SELECT message FROM alerts WHERE kind='summary'")
        self.assertEqual(len(summaries), 1)
        self.assertIn('Registros de presença: 1', summaries[0]['message'])

    def test_disabled_alerts_do_nothing(self):
        settings = self.config.get(); settings.alerts_enabled = False; self.config.save(settings)
        self.presence(MORNING - 5 * 3600)
        self.cameras.items[0]['state'] = 'offline'
        self.alerts.check(MORNING); self.alerts.check(MORNING + 3600)
        self.assertEqual(self.kinds(), [])

    def test_delivery_sends_each_recipient_and_retries(self):
        self.alerts.send_test(MORNING)
        with self.client() as client:
            self.status = 503
            self.assertTrue(self.alerts.deliver_one(client, MORNING))
            row = self.db.rows('SELECT * FROM alert_deliveries WHERE state=?', ('retry',))[0]
            self.assertGreater(row['retry_at'], MORNING)
            self.status = 200
            while self.alerts.deliver_one(client, MORNING + 3600):
                pass
        states = {r['recipient']: r['state'] for r in self.db.rows('SELECT * FROM alert_deliveries')}
        self.assertEqual(states, {PRIMARY: 'sent', SISTER: 'sent'})
        self.assertEqual({s['recipient'] for s in self.sent}, {PRIMARY, SISTER})
        self.assertTrue(all(s['text'].startswith('🧪') for s in self.sent))

    def test_stale_and_removed_recipients_are_not_sent(self):
        self.alerts.send_test(MORNING)
        settings = self.config.get(); settings.additional_recipients = []; self.config.save(settings)
        with self.client() as client:
            while self.alerts.deliver_one(client, MORNING + STALE_SECONDS + 1):
                pass
        states = {r['recipient']: r['state'] for r in self.db.rows('SELECT * FROM alert_deliveries')}
        self.assertEqual(states, {PRIMARY: 'expired', SISTER: 'expired'})
        self.assertEqual(self.sent, [])
        self.alerts.send_test(MORNING + 10)
        with self.client() as client:
            while self.alerts.deliver_one(client, MORNING + 20):
                pass
        self.assertEqual([s['recipient'] for s in self.sent], [PRIMARY])

    def test_recent_lists_deliveries(self):
        self.alerts.send_test(MORNING)
        recent = self.alerts.recent()
        self.assertEqual(recent[0]['kind'], 'test')
        self.assertEqual(len(recent[0]['deliveries']), 2)

    def test_low_disk_removes_finished_clips_but_keeps_active_ones(self):
        folder = Path(self.tmp.name) / 'clips'; folder.mkdir()
        for index, key in enumerate('abc'):
            event = self.db.start_event(MORNING + index, 1)
            if key != 'c':  # The last visit is still in progress.
                self.db.end_event(event, MORNING + index + 5, 'absence')
            self.db.execute("INSERT INTO clips(id,event_id,started,state,delivery) VALUES(?,?,?,'ready','sent')", (key * 32, event, MORNING + index))
            (folder / f'{key * 32}.mp4').write_bytes(b'x')
        # The disk never recovers: cleanup must stop once nothing else can go.
        with patch('app.recorder.free_space', return_value=1):
            cleanup(self.db, 90, folder, min_free_gb=2)
        states = [r['state'] for r in self.db.rows('SELECT state FROM clips ORDER BY started')]
        self.assertEqual(states, ['expired', 'expired', 'ready'])
        self.assertEqual([f.name for f in folder.iterdir()], ['c' * 32 + '.mp4'])

if __name__ == '__main__':
    unittest.main()
