import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

from app.config import Config, Settings
from app.db import Database
from app.learning import LearningSuggestions
from app.recognition import Recognition, normalized


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'history.sqlite3')
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(learning_auto_approve=False))
        self.recognition = Recognition(self.db, path / 'people')
        self.learning = LearningSuggestions(self.db, self.recognition, self.config)
        self.now = time.time()
        # Two confirmed examples of the father and one of another person.
        self.teach('father', (1, 0, 0), 100)
        self.teach('father', (.95, .31, 0), 120)
        other = self.recognition.create_person('Vizinho')
        self.teach(other, (0, 0, 1), 100)
        self.other = other

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, ended=True):
        event = self.db.start_event(self.now - 60, 1)
        if ended:
            self.db.end_event(event, self.now - 30, 'absence')
        return event

    def track(self, event, suggested='father', faces=()):
        """A face-recognized, unreviewed track with its saved faces [(vector, quality)]."""
        track = self.db.execute("""INSERT INTO person_tracks(event_id,track_key,started,last_seen,suggested_id,similarity,recognition_kind)
            VALUES(?,?,?,?,?,.8,'face')""", (event, str(self.db.rows('SELECT COUNT(*) AS n FROM person_tracks')[0]['n']), self.now - 60, self.now - 30, suggested))
        ids = []
        for vector, quality in faces:
            sample = os.urandom(16).hex()
            self.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',
                            (sample, track, self.now - 40, normalized(vector).tobytes(), 'sface-test', quality))
            ids.append(sample)
        return track, ids

    def teach(self, person, vector, quality):
        track, (sample,) = self.track(self.event(), None, [(vector, quality)])
        self.recognition.confirm(track, person, sample)

    def test_proposes_the_sharpest_new_view_once_per_track(self):
        track, (blurry, sharp) = self.track(self.event(), faces=[((.97, .2, .1), 90), ((.9, .1, .42), 200)])
        self.assertEqual(self.learning.scan(self.now), 1)
        pending = self.learning.pending()
        self.assertEqual([(p['sample_id'], p['name']) for p in pending], [(sharp, 'Meu pai')])
        self.assertEqual(self.learning.scan(self.now), 0)

    def test_rejects_weak_duplicate_blurry_ambiguous_or_unfinished(self):
        self.track(self.event(), faces=[((0, 1, 0), 300)])                   # Not like the father.
        self.track(self.event(), faces=[((1, 0, .01), 300)])                  # Same image as an example.
        self.track(self.event(), faces=[((.9, .1, .42), 50)])                 # Blurrier than his examples.
        self.track(self.event(), suggested=self.other, faces=[((.9, .1, .42), 300)])  # Matches someone else.
        self.track(self.event(ended=False), faces=[((.9, .1, .42), 300)])    # Record still open.
        self.assertEqual(self.learning.scan(self.now), 0)

    def test_auto_approves_only_the_confident_suggestions(self):
        track, _ = self.track(self.event(), faces=[((.97, .2, .1), 90), ((.9, .1, .42), 200)])
        self.learning.scan(self.now)
        score = self.learning.pending()[0]['score']
        self.config.save(Settings(learning_auto_approve=True, learning_auto_threshold=min(.99, score + .05)))
        self.assertEqual(self.learning.auto_approve(self.config.get()), 0)   # Doubtful: it stays for a person.
        self.assertEqual(len(self.learning.pending()), 1)
        self.config.save(Settings(learning_auto_approve=True, learning_auto_threshold=max(.5, score - .05)))
        self.assertEqual(self.learning.auto_approve(self.config.get()), 1)
        self.assertEqual(self.learning.pending(), [])
        self.assertEqual(self.db.rows('SELECT person_id FROM person_tracks WHERE id=?', (track,))[0]['person_id'], 'father')

    def test_ignore_and_merge_tracks_of_a_finished_record(self):
        event = self.event()
        first, (kept,) = self.track(event, faces=[((.97, .2, .1), 90)])
        second, (moved,) = self.track(event, faces=[((.9, .1, .42), 80)])
        ghost, _ = self.track(event, suggested=None)
        self.recognition.ignore_track(ghost)
        self.recognition.merge_tracks(second, first)
        tracks = self.db.rows('SELECT id FROM person_tracks WHERE event_id=?', (event,))
        self.assertEqual([t['id'] for t in tracks], [first])
        self.assertEqual({r['id'] for r in self.db.rows('SELECT id FROM person_samples WHERE track_id=?', (first,))}, {kept, moved})
        with self.assertRaises(ValueError):
            self.recognition.merge_tracks(first, first)
        with self.assertRaises(ValueError):
            self.recognition.ignore_track(self.db.rows('SELECT id FROM person_tracks WHERE reviewed=1')[0]['id'])   # Taught: refused.

    def test_split_moves_the_chosen_faces_into_a_new_person(self):
        event = self.event()
        track, (a, b, c) = self.track(event, suggested=None, faces=[((.97, .2, .1), 90), ((.9, .1, .42), 80), ((.5, .5, .5), 70)])
        self.recognition.confirm(track, 'father', sample_ids=[a])
        new = self.recognition.split_track(track, [a, c])
        self.assertEqual({r['id'] for r in self.db.rows('SELECT id FROM person_samples WHERE track_id=?', (new,))}, {a, c})
        self.assertEqual([r['id'] for r in self.db.rows('SELECT id FROM person_samples WHERE track_id=?', (track,))], [b])
        self.assertIsNone(self.db.rows('SELECT person_id FROM person_samples WHERE id=?', (a,))[0]['person_id'])   # Taught under the old identity: out of the gallery.
        self.assertEqual(self.db.rows('SELECT reviewed FROM person_tracks WHERE id=?', (new,))[0]['reviewed'], 0)
        with self.assertRaises(ValueError):
            self.recognition.split_track(new, [a, c])   # Cannot take everything.
        with self.assertRaises(ValueError):
            self.recognition.split_track(track, [])

    def test_faceless_ghost_tracks_are_pruned_but_one_stays_when_nothing_else_is(self):
        event = self.event()
        real, _ = self.track(event, suggested=None, faces=[((.97, .2, .1), 90)])
        ghost_a, _ = self.track(event, suggested=None)
        ghost_b, _ = self.track(event, suggested=None)
        self.assertEqual(self.recognition.prune_ghosts(self.now - 3600, self.now), 2)
        self.assertEqual([t['id'] for t in self.db.rows('SELECT id FROM person_tracks WHERE event_id=?', (event,))], [real])
        only = self.event()
        first, _ = self.track(only, suggested=None)
        second, _ = self.track(only, suggested=None)
        self.recognition.prune_ghosts(self.now - 3600, self.now)
        self.assertEqual(len(self.db.rows('SELECT id FROM person_tracks WHERE event_id=?', (only,))), 1)

    def test_fragments_of_a_single_person_record_are_joined_automatically(self):
        event = self.event()
        a, _ = self.track(event, suggested=None, faces=[((.97, .2, .1), 90)])
        b, _ = self.track(event, suggested=None)
        self.db.execute('UPDATE person_tracks SET started=?,last_seen=? WHERE id=?', (self.now - 60, self.now - 50, a))
        self.db.execute('UPDATE person_tracks SET started=?,last_seen=? WHERE id=?', (self.now - 46, self.now - 31, b))
        self.assertEqual(self.recognition.merge_fragments(self.now - 3600), 1)
        self.assertEqual([t['id'] for t in self.db.rows('SELECT id FROM person_tracks WHERE event_id=?', (event,))], [a])

    def test_confirm_can_teach_several_faces_at_once(self):
        track, (a, b, c) = self.track(self.event(), faces=[((.97, .2, .1), 90), ((.9, .1, .42), 80), ((.5, .5, .5), 70)])
        self.recognition.confirm(track, 'father', sample_ids=[a, b])
        taught = {r['id'] for r in self.db.rows("SELECT id FROM person_samples WHERE track_id=? AND person_id='father'", (track,))}
        self.assertEqual(taught, {a, b})
        with self.assertRaises(ValueError):
            self.recognition.confirm(track, 'father', sample_ids=['0' * 32])

    def test_over_the_limit_the_most_redundant_example_goes_not_the_oldest(self):
        from app.recognition import EXAMPLE_LIMIT
        person = self.recognition.create_person('Teste')

        def teach(vector, quality):
            track, (sample,) = self.track(self.event(), None, [(vector, quality)])
            self.recognition.confirm(track, person, sample_ids=[sample])
            return sample
        unique = teach((0, 0, 1), 50)                       # The oldest, but a view nothing else has.
        weak_twin = teach((1, .001, 0), 40)                 # Two almost identical faces; this one is less sharp.
        strong_twin = teach((1, .002, 0), 90)
        for index in range(EXAMPLE_LIMIT - 3):              # Fill up with distinct views.
            angle = 0.2 + index * 0.05
            teach((np.cos(angle) * .8, np.sin(angle) * .8, .6 + (index % 7) * .1), 80)
        count = lambda: self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE person_id=?', (person,))[0]['n']
        self.assertEqual(count(), EXAMPLE_LIMIT)
        fresh = teach((.2, .9, .4), 85)
        taught = {r['id'] for r in self.db.rows('SELECT id FROM person_samples WHERE person_id=?', (person,))}
        self.assertEqual(len(taught), EXAMPLE_LIMIT)
        self.assertIn(fresh, taught)
        self.assertIn(unique, taught)                       # Oldest, yet kept: it is unique.
        self.assertIn(strong_twin, taught)
        self.assertNotIn(weak_twin, taught)                 # The redundant, less sharp one went.

    def test_matrix_gallery_gives_the_same_answer_as_the_loop(self):
        from app.recognition import Gallery, match_person
        rng = np.random.default_rng(3)
        items = [{'person_id': person, 'feature': normalized(rng.normal(size=16).astype(np.float32))} for person in 'abc' for _ in range(20)]
        for _ in range(30):
            probe = items[int(rng.integers(len(items)))]['feature'] + rng.normal(scale=.3, size=16).astype(np.float32)
            plain, fast = match_person(probe, items, .1, .0), match_person(probe, Gallery(items), .1, .0)
            self.assertEqual(plain[0], fast[0])
            self.assertAlmostEqual(plain[1], fast[1], places=5)

    def test_approve_teaches_and_reject_is_remembered(self):
        track, (sample,) = self.track(self.event(), faces=[((.9, .1, .42), 200)])
        self.learning.scan(self.now)
        self.learning.decide(sample, True)
        row = self.db.rows('SELECT s.person_id,t.reviewed,t.person_id AS confirmed FROM person_samples s JOIN person_tracks t ON t.id=s.track_id WHERE s.id=?', (sample,))[0]
        self.assertEqual((row['person_id'], row['reviewed'], row['confirmed']), ('father', 1, 'father'))
        self.assertEqual(self.learning.pending(), [])
        _, (second,) = self.track(self.event(), faces=[((.85, .2, -.49), 200)])  # Another new angle.
        self.learning.scan(self.now)
        self.learning.decide(second, False)
        self.assertIsNone(self.db.rows('SELECT person_id FROM person_samples WHERE id=?', (second,))[0]['person_id'])
        self.assertEqual(self.learning.scan(self.now), 0)
        with self.assertRaises(KeyError):
            self.learning.decide(second, True)

    def test_discarding_deletes_the_photo_and_keeps_everything_else(self):
        people = self.recognition.directory
        people.mkdir(exist_ok=True)
        track, (blurry, other) = self.track(self.event(), faces=[((.9, .1, .42), 200), ((.5, .5, .5), 20)])
        (people / f'{blurry}.jpg').write_bytes(b'jpg')
        self.learning.scan(self.now)
        self.assertEqual([p['sample_id'] for p in self.learning.pending()], [blurry])
        self.learning.discard(blurry)
        self.assertFalse((people / f'{blurry}.jpg').exists())
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE id=?', (blurry,))[0]['n'], 0)
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM learning_suggestions WHERE sample_id=?', (blurry,))[0]['n'], 0)
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE id=?', (other,))[0]['n'], 1)   # Other faces stay.
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE person_id=?', ('father',))[0]['n'], 2)   # Confirmed examples too.
        with self.assertRaises(KeyError):
            self.learning.discard(blurry)                                      # Already gone.
        with self.assertRaises(KeyError):
            self.learning.discard(other)                                       # Never suggested: not this action's job.

    def test_can_be_turned_off(self):
        settings = self.config.get(); settings.learning_suggestions_enabled = False; self.config.save(settings)
        self.track(self.event(), faces=[((.9, .1, .42), 200)])
        self.assertEqual(self.learning.scan(self.now), 0)


if __name__ == '__main__':
    unittest.main()


class IdentityHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.recognition = Recognition(Database(path / 'h.sqlite3'), path / 'people')

    def tearDown(self):
        self.tmp.cleanup()

    def named(self, key, now):
        self.recognition.live[key] = {'person_id': 'father', 'name': 'Meu pai', 'score': .8, 'seen': now, 'source': 'face'}

    def test_same_person_under_a_new_number_keeps_the_name_for_a_moment(self):
        self.named('5', 100)
        box = [100, 100, 200, 400]
        self.assertIn('5', self.recognition.labels([5], [box], 100.5, 15))
        labels = self.recognition.labels([9], [[110, 105, 210, 405]], 103, 15)   # Number 5 vanished; 9 appears in the same place.
        self.assertEqual((labels['9']['person_id'], labels['9']['source']), ('father', 'continuity'))

    def test_far_away_or_late_or_ambiguous_does_not_hand_off(self):
        self.named('5', 100)
        self.recognition.labels([5], [[100, 100, 200, 400]], 100.5, 15)
        self.assertEqual(self.recognition.labels([9], [[800, 100, 900, 400]], 103, 15), {})   # Somewhere else entirely.
        self.recognition.recent_lost = []
        self.named('6', 200)
        self.recognition.labels([6], [[100, 100, 200, 400]], 200.5, 15)
        self.assertEqual(self.recognition.labels([7], [[100, 100, 200, 400]], 215, 15), {})   # Too late.

    def test_body_identity_survives_ten_seconds_of_failed_comparisons(self):
        self.recognition.live['5'] = {'person_id': 'father', 'name': 'Meu pai', 'score': .8, 'seen': 100, 'source': 'body'}
        self.assertIn('5', self.recognition.labels([5], [[0, 0, 50, 100]], 108, 20))
        self.assertNotIn('5', self.recognition.labels([5], [[0, 0, 50, 100]], 112, 20))


class SmartCleanupTests(unittest.TestCase):
    def setUp(self):
        from app import cleanup
        self.cleanup_module = cleanup
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'h.sqlite3')
        self.config = Config(path / 's.json')
        self.config.save(Settings(learning_auto_approve=False))
        self.recognition = Recognition(self.db, path / 'people')
        self.cleaner = cleanup.GalleryCleanup(self.db, self.recognition, self.config)
        from app import views
        self.views_module, self.original = views, views.view_of
        self.partial, self.side = set(), set()
        views.view_of = lambda path: (0.0, None) if path.name in self.partial else (0.95, 3.0) if path.name in self.side else (0.95, 0.2)
        self.rng = np.random.default_rng(7)
        self.people = {'father': self.rng.normal(size=16), 'ana': self.rng.normal(size=16)}
        self.ids = {'father': [], 'ana': []}

    def tearDown(self):
        self.views_module.view_of = self.original
        self.tmp.cleanup()

    def teach(self, person, vector=None, quality=100):
        vector = self.people[person] + self.rng.normal(scale=.25, size=16) if vector is None else vector
        event = self.db.start_event(100, 1)
        self.db.end_event(event, 110, 'absence')
        track = self.db.execute("INSERT INTO person_tracks(event_id,track_key,started,last_seen,person_id,reviewed) VALUES(?,?,?,?,?,1)", (event, str(len(self.ids[person])), 100, 110, person if person == 'father' else None))
        sample = os.urandom(16).hex()
        self.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality,person_id) VALUES(?,?,?,?,?,?,?)',
                        (sample, track, 100, normalized(vector).tobytes(), 'sface-test', quality, person if person != 'ana' else self.ana))
        self.ids[person].append(sample)
        return sample

    def gallery(self, count=30):
        self.ana = self.recognition.create_person('Ana')
        for _ in range(count):
            self.teach('father')
            self.teach('ana')

    def test_finds_swapped_blurry_and_partial_faces_and_checks_the_accuracy(self):
        self.gallery()
        swapped = self.teach('father', vector=self.people['ana'] + self.rng.normal(scale=.1, size=16))   # A face of Ana taught as the father.
        blurry = self.teach('father', quality=5)
        profile = self.teach('father')          # Covered face (no face found).
        self.partial.add(f'{profile}.jpg')
        result = self.cleaner.analyze()
        found = {item['sample_id']: item for item in result['items']}
        self.assertIn('swapped', found[swapped]['reasons'])
        self.assertEqual(found[swapped]['severity'], 'high')
        self.assertIn('blurry', found[blurry]['reasons'])
        self.assertIn('unclear', found[profile]['reasons'])
        self.assertNotIn(profile, [i['sample_id'] for i in result['items'] if i['severity'] == 'high'])
        clean = [s for s in self.ids['ana'] if s in found]
        self.assertLessEqual(len(clean), 3)   # Healthy faces are mostly left alone.
        validation = result['validation']
        self.assertTrue(validation['better_or_equal'])
        self.assertGreaterEqual(validation['after']['right'], validation['before']['right'])

    def test_clear_profiles_are_kept_for_someone_mostly_seen_from_the_side(self):
        self.gallery()
        for _ in range(20):                      # The father is mostly seen from the side.
            self.side.add(f'{self.teach("father")}.jpg')
        result = self.cleaner.analyze()
        self.assertFalse([i for i in result['items'] if 'profile' in i['reasons'] and i['name'] == 'Meu pai'])
        stranger_side = self.teach('ana')        # For Ana a profile is unusual, so it is noted (lightly).
        self.side.add(f'{stranger_side}.jpg')
        found = {i['sample_id']: i for i in self.cleaner.analyze()['items']}
        self.assertIn('profile', found[stranger_side]['reasons'])
        self.assertEqual(found[stranger_side]['severity'], 'low')

    def test_learning_never_teaches_unclear_faces_and_profiles_only_when_usual(self):
        self.gallery()
        learner = LearningSuggestions(self.db, self.recognition, self.config)
        row = lambda sample, person: {'id': sample, 'person_id': person}
        clear, covered, side = self.teach('father'), self.teach('father'), self.teach('father')
        self.partial.add(f'{covered}.jpg')
        self.side.add(f'{side}.jpg')
        self.assertTrue(learner.usable_view(row(clear, 'father')))
        self.assertFalse(learner.usable_view(row(covered, 'father')))
        self.assertFalse(learner.usable_view(row(side, 'father')))   # Few profiles in the gallery: not usual for him.
        for _ in range(15):
            self.side.add(f'{self.teach("father")}.jpg')
        self.db.execute('DELETE FROM sample_views')                  # Measure again with the new gallery.
        self.assertTrue(learner.usable_view(row(side, 'father')))

    def test_quarantine_hides_from_recognition_and_can_be_restored_and_purged(self):
        self.gallery()
        swapped = self.teach('father', vector=self.people['ana'])
        taught = lambda: self.db.rows('SELECT person_id FROM person_samples WHERE id=?', (swapped,))[0]['person_id']
        self.assertEqual(self.cleaner.apply([swapped]), 1)
        self.assertIsNone(taught())
        self.assertEqual([q['sample_id'] for q in self.cleaner.quarantined()], [swapped])
        self.recognition.cleanup(retention_days=0)   # The ordinary tidy-up must not delete it.
        self.assertEqual(len(self.db.rows('SELECT id FROM person_samples WHERE id=?', (swapped,))), 1)
        self.assertEqual(self.cleaner.restore([swapped]), 1)
        self.assertEqual(taught(), 'father')
        self.cleaner.apply([swapped])
        self.cleaner.purge(now=time.time() + 31 * 86400)
        self.assertEqual(self.db.rows('SELECT id FROM person_samples WHERE id=?', (swapped,)), [])

    def test_never_leaves_a_person_with_too_few_references(self):
        self.gallery(count=10)
        with self.assertRaises(ValueError):
            self.cleaner.apply(self.ids['father'][:5])
        with self.assertRaises(ValueError):
            self.cleaner.apply([])
