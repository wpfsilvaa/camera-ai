import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.db import TZ, Database
from app.fatherlog import FatherLog

NOON = datetime(2026, 10, 11, 12, 0, tzinfo=TZ).timestamp()


class FatherLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.log = FatherLog(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def presence(self, when, person):
        event = self.db.start_event(when, 1, camera_id='main', camera_name='Cozinha')
        self.db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen,person_id) VALUES(?,?,?,?,?)', (event, 'k', when, when, person))
        return event

    def test_counts_only_records_where_the_father_was_recognised(self):
        self.presence(NOON - 3600, 'father')
        self.presence(NOON - 1800, None)
        self.presence(NOON - 600, 'father')
        self.presence(NOON - 86400, 'father')   # Yesterday.
        self.assertEqual(self.log.count_today(NOON), 2)
        today = self.log.summary(NOON)['today']
        self.assertEqual([s['started'] for s in today['sightings']], [NOON - 3600, NOON - 600])

    def test_fridge_visits_and_the_week(self):
        for offset in (7200, 3600):
            self.log.record_visit('main', NOON - offset, 'Geladeira', 'Meu pai')
        self.log.record_visit('main', NOON - 60, 'Armário', 'Meu pai')
        self.log.record_visit('main', NOON - 86400 + 60, 'Geladeira')
        self.presence(NOON - 86400 + 60, 'father')
        summary = self.log.summary(NOON)
        self.assertEqual({name: len(times) for name, times in summary['today']['areas'].items()}, {'Geladeira': 2, 'Armário': 1})
        self.assertEqual(len(summary['week']), 7)
        today, yesterday = summary['week'][-1], summary['week'][-2]
        self.assertEqual((today['visits'], today['areas'], yesterday['visits'], yesterday['sightings']), (3, {'Geladeira': 2, 'Armário': 1}, 1, 1))

    def test_visit_in_a_record_confirmed_as_someone_else_is_not_counted(self):
        self.db.execute("INSERT INTO people(id,name,is_father,created) VALUES('ana','Ana',0,0)")
        event = self.presence(NOON - 600, 'ana')
        self.db.execute('UPDATE person_tracks SET reviewed=1 WHERE event_id=?', (event,))
        self.db.execute('UPDATE events SET ended=? WHERE id=?', (NOON - 500, event))
        self.log.record_visit('main', NOON - 550, 'Geladeira')
        self.log.record_visit('main', NOON - 60, 'Geladeira')   # Outside any reviewed record.
        self.assertEqual(self.log.summary(NOON)['today']['areas'], {'Geladeira': [NOON - 60]})
        self.db.execute("UPDATE person_tracks SET person_id='father' WHERE event_id=?", (event,))   # Reviewed again: it was him.
        self.assertEqual(len(self.log.summary(NOON)['today']['areas']['Geladeira']), 2)


if __name__ == '__main__':
    unittest.main()
