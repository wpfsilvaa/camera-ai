import json
import sqlite3
from bisect import bisect_right
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
                CREATE TABLE IF NOT EXISTS clip_deliveries (
                    clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    recipient TEXT NOT NULL, father_only INTEGER NOT NULL DEFAULT 1,
                    delivery TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, error TEXT, message_id TEXT, sent_at REAL,
                    PRIMARY KEY(clip_id,recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_clips_event ON clips(event_id);
                CREATE INDEX IF NOT EXISTS idx_events_started ON events(started);
                -- The job loops poll these states every few seconds.
                CREATE INDEX IF NOT EXISTS idx_clips_state ON clips(state);
                CREATE INDEX IF NOT EXISTS idx_deliveries_state ON clip_deliveries(delivery);
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
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    endpoint TEXT PRIMARY KEY, user_id TEXT, keys TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, last_ok REAL, presence INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS learning_suggestions (
                    sample_id TEXT PRIMARY KEY REFERENCES person_samples(id) ON DELETE CASCADE,
                    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    score REAL NOT NULL, created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, created REAL NOT NULL, message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created);
                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    alert_id TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE, recipient TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, error TEXT, sent_at REAL, PRIMARY KEY(alert_id,recipient)
                );
                CREATE TABLE IF NOT EXISTS face_enrollments (
                    id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    created REAL NOT NULL, feature BLOB NOT NULL, model TEXT NOT NULL, quality REAL NOT NULL
                );
            ''')
            # Import legacy delivery evidence only once, without backfilling newly
            # added recipients onto already sent or intentionally skipped clips.
            db.execute("""INSERT OR IGNORE INTO clip_deliveries
                (clip_id,recipient,delivery,attempts,retry_at,error,message_id,sent_at)
                SELECT c.id,c.recipient,c.delivery,c.attempts,c.retry_at,c.error,c.message_id,c.sent_at
                FROM clips c WHERE c.recipient IS NOT NULL AND c.recipient!=''
                AND c.delivery IN ('sent','sending','uncertain','failed','retry')
                AND NOT EXISTS(SELECT 1 FROM clip_deliveries d WHERE d.clip_id=c.id)""")
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
            if 'presence' not in {r['name'] for r in db.execute('PRAGMA table_info(push_subscriptions)')}:
                db.execute('ALTER TABLE push_subscriptions ADD COLUMN presence INTEGER NOT NULL DEFAULT 1')
            if 'image' not in {r['name'] for r in db.execute('PRAGMA table_info(alerts)')}:
                db.execute('ALTER TABLE alerts ADD COLUMN image INTEGER NOT NULL DEFAULT 0')
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

    def aggregate_delivery(self, clip_id):
        """Summarize per-recipient deliveries onto the clip row shown in the history."""
        rows = self.rows('SELECT * FROM clip_deliveries WHERE clip_id=?', (clip_id,))
        if not rows:
            return
        active = [r for r in rows if r['delivery'] != 'cancelled']
        state = aggregate_state({r['delivery'] for r in active})
        errors = [r['error'] for r in active if r['error']]
        waiting = [r['retry_at'] for r in active if r['delivery'] in ('pending', 'retry')]
        single = active[0] if len(active) == 1 else None
        self.execute('UPDATE clips SET delivery=?,attempts=?,retry_at=?,error=?,sent_at=?,message_id=?,recipient=? WHERE id=?', (
            state, sum(r['attempts'] for r in rows), min(waiting, default=0), errors[0] if errors else None,
            max((r['sent_at'] or 0 for r in active), default=0) if state == 'sent' else None,
            single and single['message_id'], single and single['recipient'], clip_id))

    def recover(self):
        # The gateway deduplicates alert ids, so an interrupted text can simply be retried.
        self.execute("UPDATE alert_deliveries SET state='pending' WHERE state='sending'")
        self.execute("UPDATE events SET analysis_state='interrupted',analysis_error='Análise interrompida pelo reinício.' WHERE analysis_state='running'")
        self.execute("UPDATE events SET ended=last_seen,reason='interrupted' WHERE ended IS NULL")
        self.execute("UPDATE clips SET state='processing' WHERE state='recording'")
        interrupted=self.rows("SELECT DISTINCT clip_id FROM clip_deliveries WHERE delivery='sending'")
        self.execute("UPDATE clip_deliveries SET delivery='uncertain',error='Envio interrompido; confira o WhatsApp antes de reenviar.' WHERE delivery='sending'")
        for row in interrupted:self.aggregate_delivery(row['clip_id'])
        # An interrupted upload may already have reached WhatsApp. Require manual retry.
        self.execute("UPDATE clips SET delivery='uncertain',error='Envio interrompido; confira o WhatsApp antes de reenviar.' WHERE delivery='sending'")

    def history(self, limit=30, offset=0, identity='all', camera_id=None):
        conditions, params = [], []
        if identity != 'all':
            conditions.append('identity=?'); params.append(identity)
        if camera_id:
            conditions.append('camera_id=?'); params.append(camera_id)
        where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.connect() as db:
            events = [dict(r) for r in db.execute(f'SELECT * FROM events {where} ORDER BY started DESC LIMIT ? OFFSET ?', (*params, limit, offset))]
            attach_details(db, events)
            total = db.execute(f'SELECT COUNT(*) FROM events {where}', params).fetchone()[0]
        return {'events': events, 'total': total}

    def event(self, event_id):
        """One event with its clips, deliveries and people, or None."""
        with self.connect() as db:
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE id=?', (event_id,))]
            attach_details(db, events)
        return events[0] if events else None

    def track_details(self, event_id):
        with self.connect() as db:
            return load_tracks(db, [event_id]).get(event_id, [])

    def stats(self, camera_id=None, now=None):
        """Last seven days up to `now` (default: the current time)."""
        scope = ' AND camera_id=?' if camera_id else ''
        clip_scope = ' AND event_id IN (SELECT id FROM events WHERE camera_id=?)' if camera_id else ''
        params = (camera_id,) if camera_id else ()
        today = (datetime.fromtimestamp(now, TZ) if now else datetime.now(TZ)).replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today - timedelta(days=i) for i in reversed(range(7))]
        starts = [day.timestamp() for day in dates]
        days = [{'date': day.date().isoformat(), 'total': 0, 'father': 0, 'unknown': 0} for day in dates]
        with self.connect() as db:
            # One pass over the week instead of one query per day.
            for started, identity in db.execute(f"SELECT started,identity FROM events WHERE kind='presence' AND started>=?{scope}", (starts[0], *params)):
                day = days[bisect_right(starts, started) - 1]
                day['total'] += 1
                if identity in ('father', 'unknown'):
                    day[identity] += 1
            one = lambda query, args=params: db.execute(query, args).fetchone()[0]
            return {
                'days': days, 'today': days[-1],
                'last_presence': one(f"SELECT MAX(last_seen) FROM events WHERE kind='presence'{scope}"),
                'pending': one(f"SELECT COUNT(*) FROM clips WHERE state='ready' AND delivery NOT IN ('sent','skipped'){clip_scope}"),
                'sent_today': one(f'SELECT COUNT(*) FROM clips WHERE sent_at>=?{clip_scope}', (starts[-1], *params)),
                'recorded_seconds_today': one(f'SELECT COALESCE(SUM(duration),0) FROM clips WHERE started>=?{clip_scope}', (starts[-1], *params)),
            }


def aggregate_state(states):
    """The most actionable state among a clip's active recipients."""
    if not states:
        return 'skipped'
    if states == {'sent'}:
        return 'sent'
    if 'sending' in states:
        return 'sending'
    if 'sent' in states:
        return 'partial'
    return next((state for state in ('pending', 'retry', 'uncertain') if state in states), 'failed')


def ids_param(ids):
    # A single JSON parameter avoids SQLite's bound-variable limit for long lists.
    return json.dumps(list(ids))


def attach_details(db, events):
    """Load clips, deliveries and people for many events in a few queries."""
    if not events:
        return
    clips = {}
    for row in db.execute('SELECT * FROM clips WHERE event_id IN (SELECT value FROM json_each(?)) ORDER BY started', (ids_param(e['id'] for e in events),)):
        clips.setdefault(row['event_id'], []).append({**dict(row), 'deliveries': []})
    by_id = {clip['id']: clip for items in clips.values() for clip in items}
    for row in db.execute('SELECT * FROM clip_deliveries WHERE clip_id IN (SELECT value FROM json_each(?)) ORDER BY recipient', (ids_param(by_id),)):
        by_id[row['clip_id']]['deliveries'].append(dict(row))
    # Manual recordings only list people after their offline analysis finished.
    analyzed = [e['id'] for e in events if e['kind'] != 'manual' or e['analysis_state'] == 'complete']
    tracks = load_tracks(db, analyzed)
    for event in events:
        event['clips'] = clips.get(event['id'], [])
        event['people'] = tracks.get(event['id'], [])
        event['probable_father'] = any(t['suggested_is_father'] and not t['reviewed'] for t in event['people'])


def load_tracks(db, event_ids):
    tracks = {}
    if not event_ids:
        return tracks
    rows = [dict(r) for r in db.execute('''SELECT t.*, p.name, p.is_father, s.name AS suggested_name,
        s.is_father AS suggested_is_father FROM person_tracks t
        LEFT JOIN people p ON p.id=t.person_id LEFT JOIN people s ON s.id=t.suggested_id
        WHERE event_id IN (SELECT value FROM json_each(?)) ORDER BY t.started,t.id''', (ids_param(event_ids),))]
    samples = {}
    for row in db.execute("""SELECT id,created,quality,person_id,track_id FROM person_samples
        WHERE track_id IN (SELECT value FROM json_each(?)) AND model LIKE 'sface-%' ORDER BY quality DESC,created DESC""",
            (ids_param(r['id'] for r in rows),)):
        sample = dict(row)
        samples.setdefault(sample.pop('track_id'), []).append(sample)
    for row in rows:
        row['diagnostic'] = json.loads(row['diagnostic'])
        row['samples'] = samples.get(row['id'], [])
        tracks.setdefault(row['event_id'], []).append(row)
    return tracks
