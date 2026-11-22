"""Follow the monitored people through the day: how many times they showed up and how many times they went to each restricted area."""
import time
from datetime import datetime, timedelta
from pathlib import Path

from .db import TZ

DAYS = 7
SLACK = 5   # Seconds around a record that still count as inside it.

# Who a visit counts for. The history review and an explicit verdict beat what the camera guessed at the time.
VISITS = f'''SELECT v.id,v.started,v.camera_id,v.area,v.verdict,
    CASE
        WHEN v.verdict IS NOT NULL THEN CASE v.verdict WHEN 'father' THEN 'father' ELSE 'family' END
        WHEN e.id IS NOT NULL AND EXISTS (SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.person_id WHERE t.event_id=e.id AND p.is_father=1) THEN 'father'
        WHEN e.id IS NOT NULL AND EXISTS (SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.person_id WHERE t.event_id=e.id AND t.reviewed=1 AND p.is_father=0) THEN 'family'
        WHEN v.kind IN ('father','family') THEN v.kind
        ELSE 'unknown'
    END AS kind,e.id AS event_id
    FROM restricted_visits v LEFT JOIN events e ON e.id=(SELECT e2.id FROM events e2 WHERE e2.camera_id=v.camera_id
        AND v.started BETWEEN e2.started-{SLACK} AND COALESCE(e2.ended,e2.last_seen)+{SLACK} ORDER BY e2.started DESC LIMIT 1)'''


PERIODS = (('madrugada', 0, 6), ('manha', 6, 12), ('tarde', 12, 18), ('noite', 18, 24))   # Hours: from (included) to (excluded).


def period_of(hour):
    return next(name for name, start, end in PERIODS if start <= hour < end)


class FatherLog:
    def __init__(self, db, photos=None):
        self.db = db
        self.photos = Path(photos) if photos else None   # Folder of the pictures taken when a visit started.
        if self.photos:
            self.photos.mkdir(parents=True, exist_ok=True)

    def record_visit(self, camera_id, now, area='', person=None, kind='father', make_jpeg=None):
        """A visit to a restricted area (the fridge, a cupboard) started; `kind` is who the camera thought it was (father, family, unknown).

        `make_jpeg` builds a picture of the moment; returns the visit's id.
        """
        visit = self.db.execute('INSERT INTO restricted_visits(camera_id,started,person,area,kind) VALUES(?,?,?,?,?)', (camera_id, now, person, area or 'Área restrita', kind))
        if make_jpeg and self.photos:
            jpeg = make_jpeg()
            if jpeg:
                (self.photos / f'{visit}.jpg').write_bytes(jpeg)
        return visit

    def set_seconds(self, visit_id, seconds):
        self.db.execute('UPDATE restricted_visits SET seconds=? WHERE id=?', (round(seconds, 1), visit_id))

    def photo_path(self, visit_id):
        path = self.photos / f'{int(visit_id)}.jpg' if self.photos else None
        return path if path and path.is_file() else None

    def cleanup(self, days=21, now=None):
        """Pictures of old visits go away; the visits stay in the report."""
        if not self.photos:
            return
        cutoff = (now or time.time()) - days * 86400
        for row in self.db.rows('SELECT id FROM restricted_visits WHERE started<?', (cutoff,)):
            (self.photos / f"{row['id']}.jpg").unlink(missing_ok=True)

    def calibration(self, current_min=3.0, now=None):
        """From the answers given in the triage: the minimum stay that best separates the father's visits from the others'."""
        rows = self.db.rows("SELECT verdict,seconds FROM restricted_visits WHERE verdict IS NOT NULL AND seconds IS NOT NULL AND started>?", ((now or time.time()) - 30 * 86400,))
        father = sorted(r['seconds'] for r in rows if r['verdict'] == 'father')
        other = sorted(r['seconds'] for r in rows if r['verdict'] == 'other')
        result = {'father': len(father), 'other': len(other), 'current': current_min, 'suggested': None}
        if len(father) < 5 or len(other) < 5:
            return result
        best = None
        for step in range(int(current_min * 2), 41):   # From the current value to 20 s, in half-seconds.
            limit = step / 2
            score = sum(1 for s in other if s < limit) / len(other) + sum(1 for s in father if s >= limit) / len(father)
            if best is None or score > best[0] + 1e-9:
                best = (score, limit, sum(1 for s in other if s < limit) / len(other), sum(1 for s in father if s >= limit) / len(father))
        result['suggested'] = {'seconds': best[1], 'others_removed': round(best[2], 2), 'father_kept': round(best[3], 2)}
        return result

    def midnight(self, now, days_back=0):
        day = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
        return day.timestamp()

    def sightings(self, since, until):
        """Presence records in which a monitored person was recognised, oldest first."""
        return self.db.rows('''SELECT e.id,e.started,e.ended,e.camera_name FROM events e
            WHERE e.started>=? AND e.started<? AND EXISTS (SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.person_id WHERE t.event_id=e.id AND p.is_father=1)
            ORDER BY e.started''', (since, until))

    def all_visits(self, since, until):
        return self.db.rows(f'SELECT * FROM ({VISITS}) WHERE started>=? AND started<? ORDER BY started', (since, until))

    def visits(self, since, until):
        """Visits that count for the monitored people."""
        return [row for row in self.all_visits(since, until) if row['kind'] == 'father']

    def per_person(self, since, until):
        """How many records each monitored person was confirmed in."""
        return self.db.rows('''SELECT p.id,p.name,COUNT(DISTINCT e.id) AS sightings FROM people p
            LEFT JOIN person_tracks t ON t.person_id=p.id LEFT JOIN events e ON e.id=t.event_id AND e.started>=? AND e.started<?
            WHERE p.is_father=1 GROUP BY p.id ORDER BY p.created''', (since, until))

    @staticmethod
    def by_area(visits):
        """{area name: [times]} in the order each area first appears."""
        found = {}
        for row in visits:
            found.setdefault(row['area'] or 'Área restrita', []).append(row['started'])
        return found

    @staticmethod
    def others(visits):
        return {'family': sum(1 for v in visits if v['kind'] == 'family'), 'unknown': sum(1 for v in visits if v['kind'] == 'unknown')}

    def count_today(self, now=None):
        now = now or time.time()
        return len(self.sightings(self.midnight(now), now + 1))

    def pending(self, now=None, limit=40):
        """Visits nobody could place yet (neither the camera nor the history review), newest first, with a picture when there is one."""
        now = now or time.time()
        rows = [v for v in self.all_visits(self.midnight(now, DAYS - 1), now + 1) if v['kind'] == 'unknown'][::-1][:limit]
        for row in rows:
            row['photo'] = self.picture(row)
        return rows

    def picture(self, visit):
        """The picture taken when the visit started; for older ones, a photo of the record: the one closest to the visit, or the video's cover."""
        if self.photo_path(visit['id']):
            return f"visit-{visit['id']}"
        if visit['event_id'] is None:
            return None
        photos = self.db.rows('SELECT id,created FROM event_photos WHERE event_id=?', (visit['event_id'],))
        if photos:
            return min(photos, key=lambda p: abs(p['created'] - visit['started']))['id']
        clip = self.db.rows("SELECT id FROM clips WHERE event_id=? AND state NOT IN ('expired','failed') ORDER BY started LIMIT 1", (visit['event_id'],))
        return clip[0]['id'] if clip else None

    def decide(self, visit_id, father, person_id=None):
        """Record who a visit was. With `person_id` (a registered person) the verdict follows whether that person is monitored."""
        if person_id:
            person = self.db.rows('SELECT id,is_father FROM people WHERE id=?', (person_id,))
            if not person:
                raise KeyError('Pessoa não encontrada.')
            father = bool(person[0]['is_father'])
        with self.db.connect() as db:
            if not db.execute('UPDATE restricted_visits SET verdict=?,person_id=? WHERE id=?', ('father' if father else 'other', person_id or None, visit_id)).rowcount:
                raise KeyError('Ida não encontrada.')

    def teachable(self, visit_id, limit=3):
        """(track id, best face sample ids) of the one unconfirmed person in the visit's record at that moment, or None when it cannot be told."""
        rows = self.db.rows(VISITS + ' WHERE v.id=?', (visit_id,))
        if not rows or rows[0]['event_id'] is None:
            return None
        visit = rows[0]
        tracks = [t for t in self.db.rows('SELECT id,reviewed FROM person_tracks WHERE event_id=? AND started<=? AND last_seen>=?',
                                           (visit['event_id'], visit['started'] + SLACK, visit['started'] - SLACK)) if not t['reviewed']]
        if len(tracks) != 1:
            return None
        samples = self.db.rows("SELECT id FROM person_samples WHERE track_id=? AND model LIKE 'sface-%' ORDER BY quality DESC LIMIT ?", (tracks[0]['id'], limit))
        return tracks[0]['id'], [r['id'] for r in samples]

    def trends(self, days=14, now=None):
        """Per day for the last `days` (today included): visits to the restricted areas by part of the day, minutes in front of the camera, first and last time.

        `compare` puts the last 7 days against the 7 before (when `days` allows) for the visits, the small-hours visits and the minutes.
        """
        now = now or time.time()
        series = []
        for back in range(days - 1, -1, -1):
            first, last = self.midnight(now, back), (self.midnight(now, back - 1) if back else now + 1)
            periods = {name: 0 for name, _, _ in PERIODS}
            mine = self.visits(first, last)
            for visit in mine:
                periods[period_of(datetime.fromtimestamp(visit['started'], TZ).hour)] += 1
            records = self.db.rows('''SELECT e.started,COALESCE(e.ended,e.last_seen) AS ended FROM events e
                WHERE e.started<? AND COALESCE(e.ended,e.last_seen)>=? AND EXISTS (SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.person_id WHERE t.event_id=e.id AND p.is_father=1)
                ORDER BY e.started''', (last, first))
            seconds = sum(max(0, min(r['ended'], last) - max(r['started'], first)) for r in records)
            series.append({'day': datetime.fromtimestamp(first, TZ).strftime('%Y-%m-%d'), 'visits': len(mine), 'periods': periods, 'minutes': round(seconds / 60),
                           'first': max(records[0]['started'], first) if records else None, 'last': min(max(r['ended'] for r in records), last) if records else None})
        compare = None
        if len(series) >= 14:
            def total(rows, key):
                return sum(row[key] if key != 'madrugada' else row['periods']['madrugada'] for row in rows)
            now_week, before = series[-7:], series[-14:-7]
            compare = {key: {'now': total(now_week, key), 'before': total(before, key)} for key in ('visits', 'madrugada', 'minutes')}
        return {'days': series, 'compare': compare}

    def summary(self, now=None):
        """Today's times plus a count per day for the last week (today included); only visits placed on a monitored person are counted."""
        now = now or time.time()
        start = self.midnight(now)
        today_all = self.all_visits(start, now + 1)
        today_father = [v for v in today_all if v['kind'] == 'father']
        today = {'sightings': [{'id': r['id'], 'started': r['started'], 'ended': r['ended'], 'camera': r['camera_name']} for r in self.sightings(start, now + 1)],
                 'areas': self.by_area(today_father), 'people': self.per_person(start, now + 1), 'others': self.others(today_all)}
        week = []
        for back in range(DAYS - 1, -1, -1):
            first, last = self.midnight(now, back), self.midnight(now, back - 1) if back else now + 1
            visits = self.all_visits(first, last)
            mine = [v for v in visits if v['kind'] == 'father']
            week.append({'day': datetime.fromtimestamp(first, TZ).strftime('%Y-%m-%d'), 'sightings': len(self.sightings(first, last)), 'visits': len(mine),
                         'areas': {name: len(times) for name, times in self.by_area(mine).items()}, **self.others(visits)})
        pending = sum(1 for day in week for _ in range(day['unknown']))
        return {'today': today, 'week': week, 'pending': pending}
