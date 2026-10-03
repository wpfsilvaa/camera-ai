"""Free disk space on request: delete old videos, or old records together with their videos.

Never touched: records still open or being analyzed, clips being recorded, converted or sent,
and faces you confirmed or approved (their records stay, only the videos go). SQLite is
compacted afterwards so deleted history actually returns space to the disk.
"""
import json
import shutil
import sqlite3
import threading
import time

from .config import CLIPS, DATA, PEOPLE
from .db import ids_param
from .recorder import CLIP_FILES, expire

# Finished, idle records older than :cutoff.
OLD_EVENTS = """SELECT id FROM events WHERE ended IS NOT NULL AND analysis_state!='running' AND started<:cutoff"""
# Their clips that are safe to remove (not recording, converting or sending to anyone).
OLD_CLIPS = f"""SELECT id FROM clips WHERE event_id IN ({OLD_EVENTS})
    AND state IN ('ready','failed') AND delivery!='sending'
    AND NOT EXISTS (SELECT 1 FROM clip_deliveries d WHERE d.clip_id=clips.id AND d.delivery='sending')"""
# Records holding a confirmed face example keep their row, so the example keeps its source.
TAUGHT = """SELECT DISTINCT t.event_id FROM person_tracks t JOIN person_samples s ON s.track_id=t.id WHERE s.person_id IS NOT NULL"""
# Old records that may go: no taught face and no clip still recording, converting or sending.
REMOVABLE_EVENTS = f"""{OLD_EVENTS} AND id NOT IN ({TAUGHT}) AND NOT EXISTS
    (SELECT 1 FROM clips c WHERE c.event_id=events.id AND (c.state NOT IN ('expired','ready','failed')
    OR c.delivery='sending' OR EXISTS (SELECT 1 FROM clip_deliveries d WHERE d.clip_id=c.id AND d.delivery='sending')))"""


def size(paths):
    return sum(p.stat().st_size for p in paths if p.is_file())


def clip_bytes(clip_ids):
    return sum(size(CLIPS / f'{clip_id}.{extension}' for extension in CLIP_FILES) for clip_id in clip_ids)


class Storage:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()

    def usage(self):
        disk = shutil.disk_usage(DATA)
        database = self.database_bytes()
        return {'videos_bytes': size(CLIPS.iterdir()), 'faces_bytes': size(PEOPLE.iterdir()), 'database_bytes': database,
                'disk_free_bytes': disk.free, 'disk_total_bytes': disk.total,
                'videos': self.db.rows("SELECT COUNT(*) AS n FROM clips WHERE state IN ('ready','failed')")[0]['n'],
                'events': self.db.rows('SELECT COUNT(*) AS n FROM events')[0]['n']}

    @staticmethod
    def cutoff(days, now=None):
        if days < 0:
            raise ValueError('Informe um número de dias válido.')
        return (now or time.time()) - days * 86400

    def preview(self, days, now=None):
        """What each cleanup would remove, for the confirmation question."""
        cutoff = {'cutoff': self.cutoff(days, now)}
        clips = [r['id'] for r in self.db.rows(OLD_CLIPS, cutoff)]
        events = self.db.rows(f'SELECT COUNT(*) AS n FROM ({REMOVABLE_EVENTS})', cutoff)[0]['n']
        return {'videos': len(clips), 'videos_bytes': clip_bytes(clips), 'events': events}

    def delete_videos(self, days, now=None):
        with self.lock:
            clips = [r['id'] for r in self.db.rows(OLD_CLIPS, {'cutoff': self.cutoff(days, now)})]
            freed = clip_bytes(clips)
            for clip_id in clips:
                expire(self.db, clip_id)
            return {'videos': len(clips), 'freed_bytes': freed}

    def delete_history(self, days, now=None):
        """Videos of all old records, then the records themselves except those with taught faces."""
        with self.lock:
            cutoff = {'cutoff': self.cutoff(days, now)}
            clips = [r['id'] for r in self.db.rows(OLD_CLIPS, cutoff)]
            freed = clip_bytes(clips)
            for clip_id in clips:
                expire(self.db, clip_id)
            database_before = self.database_bytes()
            with self.db.connect() as db:
                events = ids_param(r[0] for r in db.execute(REMOVABLE_EVENTS, cutoff))
                tracks = 'SELECT id FROM person_tracks WHERE event_id IN (SELECT value FROM json_each(:events))'
                samples = [r[0] for r in db.execute(f'SELECT id FROM person_samples WHERE track_id IN ({tracks})', {'events': events})]
                photos = [CLIPS / f'{r[0]}.jpg' for r in db.execute(
                    'SELECT id FROM event_photos WHERE event_id IN (SELECT value FROM json_each(:events))', {'events': events})]
                db.execute(f'DELETE FROM person_samples WHERE track_id IN ({tracks})', {'events': events})
                for table, column in (('person_tracks', 'event_id'), ('clips', 'event_id'), ('event_photos', 'event_id'), ('events', 'id')):
                    db.execute(f'DELETE FROM {table} WHERE {column} IN (SELECT value FROM json_each(:events))', {'events': events})
            photos += [PEOPLE / f'{sample_id}.jpg' for sample_id in samples]
            freed += size(photos)
            for photo in photos:
                photo.unlink(missing_ok=True)
            self.compact()
            freed += max(0, database_before - self.database_bytes())
            return {'videos': len(clips), 'events': len(json.loads(events)), 'freed_bytes': freed}

    def database_bytes(self):
        return size(DATA / f'history.sqlite3{suffix}' for suffix in ('', '-wal', '-shm'))

    def compact(self):
        """Return the space of deleted rows to the disk."""
        connection = sqlite3.connect(self.db.path, timeout=30)
        try:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            connection.execute('VACUUM')
        finally:
            connection.close()
