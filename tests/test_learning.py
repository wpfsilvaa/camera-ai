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
