import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

from app.alerts import Alerts
from app.config import Config, Settings
from app.db import TZ, Database
from app.routine import Routine
from test_alerts import FakeCameras

# Wednesday.
TODAY = datetime(2026, 9, 30, tzinfo=TZ)


def at(day, hour, minute=0):
    return (day + timedelta(hours=hour, minutes=minute)).timestamp()


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'history.sqlite3')
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(recipient='5511999999999', alerts_enabled=True, inactivity_hours=2, daily_summary_hour=-1))
        self.routine = Routine(self.db)
        self.alerts = Alerts(self.db, self.config, FakeCameras(), self.routine)

    def tearDown(self):
        self.tmp.cleanup()

    def presence(self, start, minutes=5):
        event = self.db.start_event(start, 1)
        self.db.end_event(event, start + minutes * 60, 'absence')
        self.db.execute('UPDATE events SET last_seen=? WHERE id=?', (start + minutes * 60, event))

    def learn(self, days=14):
        """Wakes between 07:00 and 07:39, nobody until lunch at 12:00, night visit at 02:00 (ignored)."""
        for back in range(1, days + 1):
            day = TODAY - timedelta(days=back)
            self.presence(at(day, 2))
            self.presence(at(day, 7, back * 3 % 40))
            self.presence(at(day, 12))
            self.presence(at(day, 15, 5))
            self.presence(at(day, 19))

    def kinds(self):
        return [r['kind'] for r in self.db.rows('SELECT kind FROM alerts ORDER BY created')]

    def test_needs_a_week_of_data(self):
        self.learn(5)
        summary = self.routine.summary(at(TODAY, 9))
        self.assertFalse(summary['learned'])
        self.assertIsNone(self.routine.expected_first(at(TODAY, 9)))

    def test_learns_first_appearance_and_usual_gap(self):
        self.learn()
        summary = self.routine.summary(at(TODAY, 9))
        self.assertTrue(summary['learned'])
        self.assertEqual(summary['days'], 14)
        self.assertEqual(summary['weekday']['usual_first'][:2], '07')
        self.assertGreaterEqual(summary['weekday']['latest_first'], '07:30')
        self.assertAlmostEqual(summary['usual_gap_hours'], 4.9, delta=.1)  # Morning until lunch.
        self.assertGreater(summary['hourly'][7], 0)
        self.assertEqual(sum(summary['hourly']), round(sum(summary['hourly']), 2))

    def test_morning_alert_only_after_the_usual_time_and_without_presence(self):
        self.learn()
        self.alerts.check(at(TODAY, 7, 30))
        self.assertNotIn('routine', self.kinds())
        self.alerts.check(at(TODAY, 8, 30))
        self.alerts.check(at(TODAY, 8, 40))
        self.assertEqual(self.kinds().count('routine'), 1)
        message = self.db.rows("SELECT message FROM alerts WHERE kind='routine'")[0]['message']
        self.assertIn('Normalmente ele aparece até as 07:', message)

    def test_no_morning_alert_when_he_already_appeared(self):
        self.learn()
        self.presence(at(TODAY, 6, 50))
        self.alerts.check(at(TODAY, 9))
        self.assertNotIn('routine', self.kinds())

    def test_usual_gap_raises_the_inactivity_limit(self):
        self.learn()
        self.presence(at(TODAY, 7))
        # Configured 2 h, but he usually spends almost 5 h away before lunch: limit 5.4 h.
        self.alerts.check(at(TODAY, 11, 30))
        self.assertNotIn('inactivity', self.kinds())
        self.alerts.check(at(TODAY, 12, 45))
        self.assertIn('inactivity', self.kinds())


if __name__ == '__main__':
    unittest.main()
