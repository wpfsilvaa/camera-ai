import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DATA

TZ = ZoneInfo('America/Sao_Paulo')


class Database:
    def __init__(self, path=DATA / 'history.sqlite3'):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, started REAL NOT NULL, ended REAL,
                    last_seen REAL NOT NULL, max_people INTEGER NOT NULL DEFAULT 1,
                    identity TEXT NOT NULL DEFAULT 'unknown', note TEXT NOT NULL DEFAULT '',
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id),
                    started REAL NOT NULL, ended REAL, duration REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'recording',
                    delivery TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, error TEXT, message_id TEXT,
                    recipient TEXT, sent_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_clips_event ON clips(event_id);
                CREATE INDEX IF NOT EXISTS idx_events_started ON events(started);
                CREATE TABLE IF NOT EXISTS people (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, is_father INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_father ON people(is_father) WHERE is_father=1;
                INSERT OR IGNORE INTO people(id,name,is_father,created) VALUES('father','Meu pai',1,0);
                CREATE TABLE IF NOT EXISTS person_tracks (
                    id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id),
                    track_key TEXT NOT NULL, started REAL NOT NULL, last_seen REAL NOT NULL,
                    person_id TEXT REFERENCES people(id) ON DELETE SET NULL,
                    suggested_id TEXT REFERENCES people(id) ON DELETE SET NULL,
                    similarity REAL, reviewed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(event_id,track_key)
                );
                CREATE TABLE IF NOT EXISTS person_samples (
                    id TEXT PRIMARY KEY, track_id INTEGER NOT NULL REFERENCES person_tracks(id),
                    created REAL NOT NULL, feature BLOB NOT NULL, model TEXT NOT NULL,
                    quality REAL NOT NULL, person_id TEXT REFERENCES people(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS sample_track ON person_samples(track_id);
                CREATE INDEX IF NOT EXISTS sample_person ON person_samples(person_id);
                CREATE TABLE IF NOT EXISTS recognition_meta (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO recognition_meta VALUES(1,0);
                CREATE TABLE IF NOT EXISTS face_enrollments (
                    id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    created REAL NOT NULL, feature BLOB NOT NULL, model TEXT NOT NULL, quality REAL NOT NULL
                );
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(events)')}
            if 'identity_source' not in columns:
                db.execute("ALTER TABLE events ADD COLUMN identity_source TEXT NOT NULL DEFAULT 'legacy'")
            for name,definition in [('kind',"TEXT NOT NULL DEFAULT 'presence'"),
                                    ('analysis_state',"TEXT NOT NULL DEFAULT 'none'"),
                                    ('analysis_progress','REAL NOT NULL DEFAULT 0'),
                                    ('analysis_error','TEXT'),
                                    ('camera_id',"TEXT NOT NULL DEFAULT 'main'"),
                                    ('camera_name',"TEXT NOT NULL DEFAULT ''"),
                                    ('camera_settings',"TEXT NOT NULL DEFAULT '{}'")]:
                if name not in columns:
                    db.execute(f'ALTER TABLE events ADD COLUMN {name} {definition}')
            db.execute('CREATE INDEX IF NOT EXISTS idx_events_camera_started ON events(camera_id,started)')
            clip_columns = {r['name'] for r in db.execute('PRAGMA table_info(clips)')}
            if 'analyzed' not in clip_columns:
                db.execute('ALTER TABLE clips ADD COLUMN analyzed INTEGER NOT NULL DEFAULT 0')
            track_columns = {r['name'] for r in db.execute('PRAGMA table_info(person_tracks)')}
            if 'diagnostic' not in track_columns:
                db.execute("ALTER TABLE person_tracks ADD COLUMN diagnostic TEXT NOT NULL DEFAULT '{}'")
            if 'recognition_kind' not in track_columns:
                db.execute("ALTER TABLE person_tracks ADD COLUMN recognition_kind TEXT NOT NULL DEFAULT 'body'")
                db.execute('ALTER TABLE person_tracks ADD COLUMN recognized_at REAL')
                db.execute('UPDATE person_tracks SET suggested_id=NULL,similarity=NULL WHERE reviewed=0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, query, params=()):
        with self.connect() as db:
            return db.execute(query, params).lastrowid

    def rows(self, query, params=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(query, params).fetchall()]

    def start_event(self, now, count, kind='presence', camera_id='main', camera_name='', camera_settings=None):
        return self.execute('INSERT INTO events(started,last_seen,max_people,kind,camera_id,camera_name,camera_settings) VALUES(?,?,?,?,?,?,?)',
                            (now, now, count, kind, camera_id, camera_name, json.dumps(camera_settings or {})))

    def touch_event(self, event_id, now, count):
        self.execute('UPDATE events SET last_seen=?, max_people=MAX(max_people,?) WHERE id=?', (now, count, event_id))

    def end_event(self, event_id, now, reason):
        self.execute('UPDATE events SET ended=?, reason=? WHERE id=?', (now, reason, event_id))

    def recover(self):
        self.execute("UPDATE events SET analysis_state='interrupted',analysis_error='Análise interrompida pelo reinício.' WHERE analysis_state='running'")
        self.execute("UPDATE events SET ended=last_seen,reason='interrupted' WHERE ended IS NULL")
        self.execute("UPDATE clips SET state='processing' WHERE state='recording'")
        # An interrupted upload may already have reached WhatsApp. Require manual retry.
        self.execute("UPDATE clips SET delivery='uncertain',error='Envio interrompido; confira o WhatsApp antes de reenviar.' WHERE delivery='sending'")

    def history(self, limit=30, offset=0, identity='all', camera_id=None):
        conditions, params = [], []
        if identity != 'all':
            conditions.append('identity=?'); params.append(identity)
        if camera_id:
            conditions.append('camera_id=?'); params.append(camera_id)
        where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        rows = self.rows(f'SELECT * FROM events {where} ORDER BY started DESC LIMIT ? OFFSET ?', (*params, limit, offset))
        for row in rows:
            row['clips'] = self.rows('SELECT * FROM clips WHERE event_id=? ORDER BY started', (row['id'],))
            row['people'] = self.track_details(row['id']) if row['kind']!='manual' or row['analysis_state']=='complete' else []
            row['probable_father'] = any(t['suggested_is_father'] and not t['reviewed'] for t in row['people'])
        total = self.rows(f'SELECT COUNT(*) AS n FROM events {where}', params)[0]['n']
        return {'events': rows, 'total': total}

    def track_details(self, event_id):
        rows = self.rows('''SELECT t.*, p.name, p.is_father, s.name AS suggested_name,
            s.is_father AS suggested_is_father FROM person_tracks t
            LEFT JOIN people p ON p.id=t.person_id LEFT JOIN people s ON s.id=t.suggested_id
            WHERE event_id=? ORDER BY t.started,t.id''', (event_id,))
        for row in rows:
            row['diagnostic'] = json.loads(row['diagnostic'])
            row['samples'] = self.rows("SELECT id,created,quality,person_id FROM person_samples WHERE track_id=? AND model LIKE 'sface-%' ORDER BY quality DESC,created DESC", (row['id'],))
        return rows

    def stats(self, camera_id=None):
        scope = " AND camera_id=?" if camera_id else ""
        clip_scope = " AND event_id IN (SELECT id FROM events WHERE camera_id=?)" if camera_id else ""
        params = (camera_id,) if camera_id else ()
        today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        days = []
        for i in reversed(range(7)):
            day = today - timedelta(days=i)
            end = day + timedelta(days=1)
            row = self.rows(f'''SELECT COUNT(*) AS total,
                COALESCE(SUM(identity='father'),0) AS father,
                COALESCE(SUM(identity='unknown'),0) AS unknown FROM events WHERE kind='presence' AND started>=? AND started<?{scope}''', (day.timestamp(), end.timestamp(), *params))[0]
            days.append({'date': day.date().isoformat(), **row})
        return {
            'days': days, 'today': days[-1],
            'last_presence': self.rows(f"SELECT MAX(last_seen) AS t FROM events WHERE kind='presence'{scope}", params)[0]['t'],
            'pending': self.rows(f"SELECT COUNT(*) AS n FROM clips WHERE state='ready' AND delivery!='sent'{clip_scope}", params)[0]['n'],
            'sent_today': self.rows(f"SELECT COUNT(*) AS n FROM clips WHERE sent_at>=?{clip_scope}", (today.timestamp(), *params))[0]['n'],
            'recorded_seconds_today': self.rows(f'SELECT COALESCE(SUM(duration),0) AS n FROM clips WHERE started>=?{clip_scope}', (today.timestamp(), *params))[0]['n'],
        }
