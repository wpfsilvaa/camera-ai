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

    def test_every_monitored_person_counts(self):
        self.db.execute("INSERT INTO people(id,name,is_father,created) VALUES('mae','Minha mãe',1,1)")
        self.presence(NOON - 3600, 'father')
        self.presence(NOON - 1800, 'mae')
        self.presence(NOON - 900, 'mae')
        self.assertEqual(self.log.count_today(NOON), 3)
        self.assertEqual({p['name']: p['sightings'] for p in self.log.summary(NOON)['today']['people']}, {'Meu pai': 1, 'Minha mãe': 2})

    def test_visits_are_split_by_who_they_were(self):
        self.db.execute("INSERT INTO people(id,name,is_father,created) VALUES('ana','Ana',0,0)")
        self.log.record_visit('main', NOON - 300, 'Geladeira', 'Meu pai', 'father')
        self.log.record_visit('main', NOON - 240, 'Geladeira', 'Ana', 'family')
        self.log.record_visit('main', NOON - 180, 'Geladeira', None, 'unknown')
        self.log.record_visit('main', NOON - 120, 'Geladeira', None, 'unknown')
        today = self.log.summary(NOON)['today']
        self.assertEqual(today['areas'], {'Geladeira': [NOON - 300]})          # Only the father counts.
        self.assertEqual(today['others'], {'family': 1, 'unknown': 2})
        self.assertEqual(self.log.summary(NOON)['week'][-1]['unknown'], 2)

    def test_triage_verdict_moves_a_visit_between_the_counts(self):
        self.log.record_visit('main', NOON - 180, 'Geladeira', None, 'unknown')
        self.log.record_visit('main', NOON - 120, 'Geladeira', None, 'unknown')
        first, second = [v['id'] for v in self.log.pending(NOON)][::-1]
        self.assertEqual(len(self.log.pending(NOON)), 2)
        self.log.decide(first, True)     # It was him.
        self.log.decide(second, False)   # It was someone else.
        summary = self.log.summary(NOON)
        self.assertEqual(summary['today']['areas'], {'Geladeira': [NOON - 180]})
        self.assertEqual((summary['today']['others'], summary['pending'], self.log.pending(NOON)), ({'family': 1, 'unknown': 0}, 0, []))
        with self.assertRaises(KeyError):
            self.log.decide(9999, True)

    def test_review_in_the_history_beats_what_the_camera_guessed(self):
        event = self.presence(NOON - 600, 'father')
        self.db.execute('UPDATE events SET ended=? WHERE id=?', (NOON - 500, event))
        self.log.record_visit('main', NOON - 550, 'Geladeira', None, 'unknown')   # The camera could not tell.
        self.assertEqual(self.log.summary(NOON)['today']['areas'], {'Geladeira': [NOON - 550]})


    def test_snapshot_is_kept_and_served_for_the_triage(self):
        folder = Path(self.tmp.name) / 'visits'
        log = FatherLog(self.db, folder)
        visit = log.record_visit('main', NOON - 100, 'Geladeira', None, 'unknown', lambda: b'jpg')
        log.set_seconds(visit, 7.26)
        self.assertEqual((folder / f'{visit}.jpg').read_bytes(), b'jpg')
        pending = log.pending(NOON)
        self.assertEqual((pending[0]['photo'], self.db.rows('SELECT seconds FROM restricted_visits')[0]['seconds']), (f'visit-{visit}', 7.3))
        log.cleanup(days=1, now=NOON + 3 * 86400)
        self.assertIsNone(log.photo_path(visit))

    def test_calibration_suggests_the_stay_that_separates_the_answers(self):
        for seconds, father in [(4, 0), (5, 0), (5, 0), (6, 0), (6, 0), (12, 1), (14, 1), (15, 1), (18, 1), (20, 1)]:
            visit = self.log.record_visit('main', NOON - 100, 'Geladeira', None, 'unknown')
            self.log.set_seconds(visit, seconds)
            self.log.decide(visit, bool(father))
        result = self.log.calibration(3, NOON)
        self.assertEqual((result['father'], result['other']), (5, 5))
        self.assertTrue(6 < result['suggested']['seconds'] <= 12)
        self.assertEqual((result['suggested']['others_removed'], result['suggested']['father_kept']), (1.0, 1.0))

    def test_calibration_waits_for_enough_answers(self):
        self.assertIsNone(self.log.calibration(3, NOON)['suggested'])


if __name__ == '__main__':
    unittest.main()
