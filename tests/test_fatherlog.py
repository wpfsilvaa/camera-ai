import tempfile
import unittest
from datetime import datetime, timedelta
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


class VisitReviewTeachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.log = FatherLog(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def people(self):
        self.db.execute("INSERT INTO people(id,name,created,is_father) VALUES('pai','Pai',1,1)")
        self.db.execute("INSERT INTO people(id,name,created,is_father) VALUES('lorena','Lorena',2,0)")

    def event_with_track(self, when, keys=1):
        event = self.db.start_event(when - 5, 1, camera_id='main', camera_name='Cozinha')
        self.db.end_event(event, when + 30, 'absence')
        for i in range(keys):
            self.db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen) VALUES(?,?,?,?)', (event, f'k{i}', when - 5, when + 10))
        return event

    def test_review_with_a_person_sets_the_verdict_from_that_person(self):
        self.people()
        father_visit = self.log.record_visit('main', NOON, 'Geladeira', None, 'unknown')
        other_visit = self.log.record_visit('main', NOON + 600, 'Geladeira', None, 'unknown')
        self.log.decide(father_visit, False, 'pai')
        self.log.decide(other_visit, True, 'lorena')   # The person decides, not the flag.
        rows = {r['id']: r for r in self.db.rows('SELECT id,verdict,person_id FROM restricted_visits')}
        self.assertEqual((rows[father_visit]['verdict'], rows[father_visit]['person_id']), ('father', 'pai'))
        self.assertEqual((rows[other_visit]['verdict'], rows[other_visit]['person_id']), ('other', 'lorena'))
        with self.assertRaises(KeyError):
            self.log.decide(father_visit, False, 'ninguem')

    def test_teachable_needs_exactly_one_unconfirmed_person_and_picks_the_sharpest_faces(self):
        self.people()
        visit = self.log.record_visit('main', NOON, 'Geladeira', None, 'unknown')
        event = self.event_with_track(NOON)
        track = self.db.rows('SELECT id FROM person_tracks WHERE event_id=?', (event,))[0]['id']
        for sample, quality, model in (('a', .2, 'sface-v1'), ('b', .9, 'sface-v1'), ('c', .5, 'sface-v1'), ('d', .99, 'body-v1'), ('e', .7, 'sface-v1')):
            self.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)', (sample, track, NOON, b'x', model, quality))
        self.assertEqual(self.log.teachable(visit), (track, ['b', 'e', 'c']))
        self.db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen) VALUES(?,?,?,?)', (event, 'other', NOON - 5, NOON + 10))
        self.assertIsNone(self.log.teachable(visit))   # Two people at that moment: not guessing.


class TrendsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.log = FatherLog(self.db)
        self.db.execute("INSERT OR IGNORE INTO people(id,name,created,is_father) VALUES('father','Pai',1,1)")

    def tearDown(self):
        self.tmp.cleanup()

    def day(self, back, hour, minute=0):
        return (datetime(2026, 10, 11, hour, minute, tzinfo=TZ) - timedelta(days=back)).timestamp()

    def presence(self, start, minutes):
        event = self.db.start_event(start, 1, camera_id='main', camera_name='Cozinha')
        self.db.end_event(event, start + minutes * 60, 'absence')
        self.db.execute("INSERT INTO person_tracks(event_id,track_key,started,last_seen,person_id) VALUES(?,?,?,?,?)", (event, 'k', start, start, 'father'))

    def test_visits_are_split_by_part_of_the_day_and_presence_in_minutes(self):
        for hour in (2, 3, 9, 14, 19, 23):
            self.log.record_visit('main', self.day(0, hour), 'Geladeira', None, 'father')
        self.log.record_visit('main', self.day(0, 15), 'Geladeira', None, 'family')   # Someone else: not counted.
        self.presence(self.day(0, 8), 30)
        self.presence(self.day(0, 18), 90)
        today = self.log.trends(7, now=self.day(0, 23, 30))['days'][-1]
        self.assertEqual(today['visits'], 6)
        self.assertEqual(today['periods'], {'madrugada': 2, 'manha': 1, 'tarde': 1, 'noite': 2})
        self.assertEqual(today['minutes'], 120)
        self.assertEqual((today['first'], today['last']), (self.day(0, 8), self.day(0, 19, 30)))

    def test_a_record_that_crosses_midnight_is_split_between_the_two_days(self):
        self.presence(self.day(1, 23, 30), 60)   # 23:30 to 00:30.
        series = self.log.trends(7, now=self.day(0, 12))['days']
        self.assertEqual((series[-2]['minutes'], series[-1]['minutes']), (30, 30))

    def test_the_week_is_compared_with_the_one_before_only_when_there_are_14_days(self):
        for back in range(14):
            for _ in range(2 if back < 7 else 1):
                self.log.record_visit('main', self.day(back, 2), 'Geladeira', None, 'father')
        data = self.log.trends(14, now=self.day(0, 23))
        self.assertEqual(data['compare']['visits'], {'now': 14, 'before': 7})
        self.assertEqual(data['compare']['madrugada'], {'now': 14, 'before': 7})
        self.assertEqual(len(data['days']), 14)
        self.assertIsNone(self.log.trends(7, now=self.day(0, 23))['compare'])
        self.assertEqual(len(self.log.trends(30, now=self.day(0, 23))['days']), 30)

