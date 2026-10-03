import os
import sqlite3
import sys
import tarfile
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from app.backup import Backups
from app.config import DATA, PEOPLE, Config, Settings
from app.db import TZ, Database
from restore_backup import restore


class FakeAlerts:
    def __init__(self):
        self.raised = []

    def raise_alert(self, alert_id, kind, message, now):
        self.raised.append((alert_id, kind))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.TemporaryDirectory()
        self.db = Database(DATA / 'history.sqlite3')
        self.config = Config(Path(self.target.name).with_suffix('.settings.json'))
        self.config.save(Settings(backup_enabled=True, backup_dir=self.target.name, backup_hour=3, backup_keep=2))
        self.alerts = FakeAlerts()
        self.backups = Backups(self.db, self.config, self.alerts)
        (PEOPLE / ('a' * 32 + '.jpg')).write_bytes(b'face')
        self.db.start_event(time.time(), 1)

    def tearDown(self):
        self.target.cleanup()
        self.config.path.unlink(missing_ok=True)
        (DATA / 'backup.json').unlink(missing_ok=True)

    def test_archive_contains_a_consistent_copy_and_no_whatsapp_session(self):
        (DATA / 'whatsapp-auth').mkdir(exist_ok=True)
        path = self.backups.run()
        with tarfile.open(path) as archive:
            names = archive.getnames()
            self.assertIn('history.sqlite3', names)
            self.assertIn('settings.json', names)
            self.assertIn('people/' + 'a' * 32 + '.jpg', names)
            self.assertFalse(any('whatsapp' in n or 'gateway' in n for n in names))
            with tempfile.TemporaryDirectory() as folder:
                archive.extract('history.sqlite3', folder, filter='data')
                with sqlite3.connect(Path(folder) / 'history.sqlite3') as copy:
                    self.assertEqual(copy.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
        self.assertEqual(self.backups.status()['last_file'], path.name)
        self.assertEqual(list(Path(self.target.name).glob('*.part')), [])

    def test_keeps_only_the_newest_copies(self):
        for index in range(4):
            self.backups.run(time.time() + index)
        self.assertEqual(len(self.backups.files()), 2)

    def test_missing_drive_is_reported_once_per_day(self):
        settings = self.config.get(); settings.backup_dir = '/nao/existe'; self.config.save(settings)
        with self.assertRaisesRegex(ValueError, 'HD externo'):
            self.backups.run()
        self.assertEqual([kind for _, kind in self.alerts.raised], ['backup'])
        self.assertIn('HD externo', self.backups.status()['last_error'])

    def test_schedule(self):
        day = datetime(2026, 9, 30, tzinfo=TZ)
        self.assertFalse(self.backups.due(day.replace(hour=2).timestamp()))
        self.assertTrue(self.backups.due(day.replace(hour=4).timestamp()))
        self.backups.run(day.replace(hour=4).timestamp())
        self.assertFalse(self.backups.due(day.replace(hour=9).timestamp()))
        self.assertTrue(self.backups.due(day.replace(day=1, month=10, hour=4).timestamp()))

    def test_restore_moves_current_files_aside(self):
        path = self.backups.run()
        with tempfile.TemporaryDirectory() as data:
            (Path(data) / 'settings.json').write_text('{"old": true}')
            aside = restore(path, Path(data))
            self.assertEqual((aside / 'settings.json').read_text(), '{"old": true}')
            self.assertTrue((Path(data) / 'history.sqlite3').is_file())
            self.assertTrue((Path(data) / 'people' / ('a' * 32 + '.jpg')).is_file())


if __name__ == '__main__':
    unittest.main()
