import os
import tempfile
import time
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

from app.config import CLIPS, PEOPLE
from app.db import Database
from app.recognition import Recognition, normalized
from app.storage import Storage

DAY = 86400


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'history.sqlite3')
        self.storage = Storage(self.db)
        self.now = time.time()
        self.old = self.record(self.now - 10 * DAY, 'a')
        self.recent = self.record(self.now - 1 * DAY, 'b')
        self.open = self.record(self.now - 20 * DAY, 'c', ended=False)          # Still in progress.
        self.taught = self.record(self.now - 30 * DAY, 'd', teach=True)         # Holds a confirmed face.
        self.sending = self.record(self.now - 15 * DAY, 'e', delivery='sending')

    def tearDown(self):
        for folder in (CLIPS, PEOPLE):
            for path in folder.iterdir():
                path.unlink()
        self.tmp.cleanup()

    def record(self, started, key, ended=True, teach=False, delivery='sent'):
        event = self.db.start_event(started, 1)
        if ended:
            self.db.end_event(event, started + 60, 'absence')
        clip = key * 32
        self.db.execute("INSERT INTO clips(id,event_id,started,state,delivery) VALUES(?,?,?,'ready',?)", (clip, event, started, delivery))
        (CLIPS / f'{clip}.mp4').write_bytes(b'v' * 1000)
        (CLIPS / f'{clip}.jpg').write_bytes(b'j' * 100)
        track = self.db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen) VALUES(?,?,?,?)', (event, '1', started, started + 60))
        sample = key * 31 + 'f'
        self.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',
                        (sample, track, started, normalized([1, 0, 0]).tobytes(), 'sface-test', 100))
        (PEOPLE / f'{sample}.jpg').write_bytes(b'f' * 50)
        if teach:
            Recognition(self.db, PEOPLE).confirm(track, 'father', sample)
        return event

    def states(self):
        return {r['event_id']: r['state'] for r in self.db.rows('SELECT event_id,state FROM clips')}

    def test_preview_counts_only_removable_items(self):
        preview = self.storage.preview(7, self.now)
        self.assertEqual(preview['videos'], 2)          # old + taught; not the open or sending ones.
        self.assertEqual(preview['videos_bytes'], 2200)
        self.assertEqual(preview['events'], 1)          # Only old: taught and sending stay.

    def test_delete_videos_keeps_every_record(self):
        result = self.storage.delete_videos(7, self.now)
        self.assertEqual((result['videos'], result['freed_bytes']), (2, 2200))
        states = self.states()
        self.assertEqual((states[self.old], states[self.taught]), ('expired', 'expired'))
        self.assertEqual((states[self.recent], states[self.open], states[self.sending]), ('ready', 'ready', 'ready'))
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM events')[0]['n'], 5)
        self.assertFalse((CLIPS / ('a' * 32 + '.mp4')).exists())

    def test_delete_history_preserves_open_sending_and_taught_records(self):
        result = self.storage.delete_history(7, self.now)
        remaining = {r['id'] for r in self.db.rows('SELECT id FROM events')}
        self.assertEqual(remaining, {self.recent, self.open, self.taught, self.sending})
        self.assertEqual(result['events'], 1)
        self.assertFalse((PEOPLE / ('a' * 31 + 'f.jpg')).exists())
        self.assertTrue((PEOPLE / ('d' * 31 + 'f.jpg')).exists())   # The taught face.
        self.assertEqual(self.db.rows("SELECT person_id FROM person_samples WHERE id=?", ('d' * 31 + 'f',))[0]['person_id'], 'father')
        self.assertGreaterEqual(result['freed_bytes'], 2250)

    def photo(self, event, key, created):
        photo = key * 32
        self.db.add_photo(photo, event, created)
        (CLIPS / f'{photo}.jpg').write_bytes(b'p' * 80)
        return CLIPS / f'{photo}.jpg'

    def test_restricted_mode_photos_leave_with_their_record(self):
        old, recent = self.photo(self.old, '1', self.now - 10 * DAY), self.photo(self.recent, '2', self.now - DAY)
        self.storage.delete_history(7, self.now)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertEqual([r['event_id'] for r in self.db.rows('SELECT event_id FROM event_photos')], [self.recent])

    def test_restricted_mode_photos_follow_the_video_retention(self):
        from app.recorder import cleanup
        old, kept = self.photo(self.old, '1', self.now - 10 * DAY), self.photo(self.open, '2', self.now - 20 * DAY)
        cleanup(self.db, 7)
        self.assertFalse(old.exists())
        self.assertTrue(kept.exists())   # The record is still open.
        self.assertEqual(len(self.db.rows('SELECT id FROM event_photos')), 1)
        self.assertEqual(len(self.db.event(self.old)['photos']), 0)

    def test_a_video_still_going_to_one_recipient_is_kept(self):
        self.db.execute("INSERT INTO clip_deliveries(clip_id,recipient,delivery) VALUES(?,?,'sending')", ('a' * 32, '5511999999999'))
        self.assertEqual(self.storage.delete_videos(7, self.now)['videos'], 1)  # Only the taught record's video.
        self.assertEqual(self.storage.delete_history(7, self.now)['events'], 0)
        self.assertTrue((CLIPS / ('a' * 32 + '.mp4')).exists())

    def test_all_including_today(self):
        self.assertEqual(self.storage.delete_videos(0, self.now)['videos'], 3)  # old, recent, taught.
        with self.assertRaises(ValueError):
            self.storage.preview(-1)


if __name__ == '__main__':
    unittest.main()
