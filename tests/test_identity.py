import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.db import Database
from app.recognition import Recognition, normalized


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name)
        self.db = Database(path / 'history.sqlite3')
        self.recognition = Recognition(self.db, path / 'people')
        for pid, name in (('father', 'Meu pai'), ('ana', 'Ana')):
            self.db.execute('INSERT OR IGNORE INTO people(id,name,created,is_father) VALUES(?,?,?,?)', (pid, name, 1, int(pid == 'father')))
        self.recognition.names = {'father': 'Meu pai', 'ana': 'Ana'}

    def tearDown(self):
        self.temporary.cleanup()

    def named(self, key, now, person='father', source='face'):
        self.recognition.live[key] = {'person_id': person, 'name': self.recognition.names[person], 'score': .8, 'seen': now, 'source': source}

    def feature(self, key, vector):
        self.recognition.body_memory.features[key] = ([normalized(vector)], 0)

    def log(self):
        return self.db.rows('SELECT reason,recovered_after,person_id FROM identity_log ORDER BY id')

    # Sticky name ------------------------------------------------------------

    def test_a_face_name_outlives_the_hold_while_the_same_track_goes_on(self):
        self.named('1', 100)
        box = [[10, 10, 90, 160]]
        self.assertIn('1', self.recognition.labels([1], box, 130, 15, sticky_seconds=180))
        self.assertEqual(self.log(), [])
        self.assertEqual(self.recognition.labels([1], box, 400, 15, sticky_seconds=180), {})   # Not for ever.
        self.assertEqual([r['reason'] for r in self.log()], ['expired'])

    def test_without_sticky_the_old_hold_applies(self):
        self.named('1', 100)
        self.assertEqual(self.recognition.labels([1], [[10, 10, 90, 160]], 130, 15), {})

    def test_body_and_inherited_names_are_sticky_for_a_shorter_time(self):
        box = [[10, 10, 90, 160]]
        self.named('1', 100, source='body')
        self.assertIn('1', self.recognition.labels([1], box, 200, 15, sticky_seconds=900))
        self.assertEqual(self.recognition.labels([1], box, 230, 15, sticky_seconds=900), {})   # 120 s cap for the body.
        self.named('2', 100, source='continuity')
        self.assertNotIn('2', self.recognition.labels([2], [[300, 10, 380, 160]], 170, 15, sticky_seconds=900))   # 60 s cap.

    def test_nobody_keeps_a_name_without_proof_when_crossing_another_person(self):
        self.named('1', 100)
        crossing = [[10, 10, 100, 160], [20, 10, 110, 160]]
        self.assertNotIn('1', self.recognition.labels([1, 2], crossing, 130, 15, sticky_seconds=180))
        self.assertEqual([r['reason'] for r in self.log()], ['overlap'])

    # Clothes anchors -------------------------------------------------------

    def test_anchor_summary_says_who_has_references_and_how_fresh_they_are(self):
        self.assertEqual(self.recognition.body_anchor_summary(now=1000), [])
        self.recognition.body_memory.learn('father', normalized((1, 0, 0)), 900)
        self.recognition.body_memory.learn('father', normalized((0, 1, 0)), 950)
        self.assertEqual(self.recognition.body_anchor_summary(now=1000), [{'person_id': 'father', 'name': 'Meu pai', 'count': 2, 'newest_seconds': 50}])

    def test_the_saved_clothes_memory_is_restored_with_the_configured_lifetime_not_the_default(self):
        import json, time
        from types import SimpleNamespace
        from app.config import Settings
        now = time.time()
        self.recognition.body_file.write_text(json.dumps({'father': [{'feature': [1.0, 0.0, 0.0], 'seen': now - 5 * 3600, 'collected': now - 5 * 3600, 'source': 'face'}]}))
        self.recognition.encoder = SimpleNamespace(version='sface-test')
        fresh = Recognition(self.db, Path(self.temporary.name) / 'people')
        fresh.encoder = SimpleNamespace(version='sface-test')
        fresh.names = {'father': 'Meu pai'}
        fresh.observe_faces(None, [], [], {}, now, Settings(body_memory_minutes=720))
        self.assertEqual(len(fresh.body_memory.references.get('father', [])), 1, 'uma referência de 5 h deveria valer com prazo de 12 h')

    # Giving the name back ---------------------------------------------------------

    def test_the_name_goes_to_the_track_that_looks_the_same_even_with_two_candidates(self):
        self.named('5', 100)
        self.feature('5', (1, 0, 0))
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.feature('9', (0, 1, 0)); self.feature('8', (1, .05, 0))   # 8 looks like who vanished, 9 does not.
        labels = self.recognition.labels([8, 9], [[130, 100, 230, 400], [30, 100, 130, 400]], 110, 15, reattach_seconds=20, body_threshold=.7)
        self.assertEqual(labels['8']['source'], 'continuity')
        self.assertNotIn('9', labels)
        self.assertEqual([(r['reason'], r['recovered_after']) for r in self.log()], [('track_lost', 9.5)])

    def test_two_candidates_equally_alike_are_left_alone(self):
        self.named('5', 100)
        self.feature('5', (1, 0, 0))
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.feature('8', (1, .02, 0)); self.feature('9', (1, .03, 0))
        labels = self.recognition.labels([8, 9], [[130, 100, 230, 400], [30, 100, 130, 400]], 110, 15, reattach_seconds=20, body_threshold=.7)
        self.assertEqual(labels, {})

    def test_a_longer_window_and_a_farther_place_work_only_with_matching_clothes(self):
        self.named('5', 100); self.feature('5', (1, 0, 0))
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.feature('9', (1, .03, 0))
        far = [[480, 100, 580, 400]]   # About 3.8 body sizes away, 14 s later.
        self.assertEqual(self.recognition.labels([9], far, 114.5, 15, reattach_seconds=20, body_threshold=.7)['9']['source'], 'continuity')
        # Without clothes information the old strict rule stays (close and soon).
        self.recognition.live.clear(); self.recognition.recent_lost = []
        self.named('5', 100)
        self.recognition.body_memory.features.clear()
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.assertEqual(self.recognition.labels([9], far, 114.5, 15, reattach_seconds=20, body_threshold=.7), {})

    def test_different_clothes_are_never_given_the_name(self):
        self.named('5', 100); self.feature('5', (1, 0, 0))
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.feature('9', (0, 1, 0))
        self.assertEqual(self.recognition.labels([9], [[110, 100, 210, 400]], 103, 15, reattach_seconds=20, body_threshold=.7), {})

    def test_an_unrecovered_loss_is_logged_when_the_window_ends_but_not_for_someone_who_just_left(self):
        self.named('5', 100); self.feature('5', (1, 0, 0))
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15, reattach_seconds=20, body_threshold=.7)
        self.recognition.labels([], [], 105, 15, reattach_seconds=20, body_threshold=.7)   # Left: nobody else showed up.
        self.recognition.labels([], [], 130, 15, reattach_seconds=20, body_threshold=.7)
        self.assertEqual(self.log(), [])
        self.recognition.live.clear(); self.recognition.recent_lost = []
        self.named('6', 200); self.feature('6', (1, 0, 0))
        self.recognition.labels([6], [[100, 100, 200, 400]], 200.5, 15, reattach_seconds=20, body_threshold=.7)
        self.feature('7', (0, 1, 0))   # Somebody unnamed (and different) stands right there...
        self.recognition.labels([7], [[110, 100, 210, 400]], 205, 15, reattach_seconds=20, body_threshold=.7)
        self.recognition.labels([7], [[110, 100, 210, 400]], 225, 15, reattach_seconds=20, body_threshold=.7)   # ...and the window ends.
        self.assertEqual([r['reason'] for r in self.log()], ['track_lost'])
        self.assertIsNone(self.log()[0]['recovered_after'])

    def test_a_name_that_comes_back_through_another_way_records_the_gap(self):
        self.named('1', 100)
        self.recognition.labels([1, 2], [[10, 10, 90, 160], [20, 10, 110, 160]], 130, 15, sticky_seconds=180)   # Lost by overlap.
        self.recognition.live['1']['seen'] = 140   # A face proved it again.
        self.recognition.labels([1], [[10, 10, 90, 160]], 140.5, 15, sticky_seconds=180)
        self.assertEqual([(r['reason'], r['recovered_after']) for r in self.log()], [('overlap', 10.5)])

    def test_summary_groups_losses_by_reason_and_counts_recoveries(self):
        from app.identity_log import IdentityLog
        log = IdentityLog(self.db)
        log.lost(1000, 'main', 'father', '1', 'expired'); log.named(1008, 'father')
        log.lost(2000, 'main', 'ana', '2', 'track_lost'); log.lost(2001, 'main', 'ana', '3', 'expired')   # Same person already open: not counted twice.
        summary = log.summary(days=1, now=3000)
        self.assertEqual((summary['total'], summary['recovered'], summary['median_gap']), (2, 1, 8.0))
        self.assertEqual({r['reason']: (r['count'], r['recovered']) for r in summary['by_reason']}, {'expired': (1, 1), 'track_lost': (1, 0)})
        log.cleanup(days=0, now=10 ** 9)
        self.assertEqual(log.summary(days=3, now=10 ** 9)['total'], 0)


if __name__ == '__main__':
    unittest.main()
