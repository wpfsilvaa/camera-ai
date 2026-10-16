"""Follow the monitored people through the day: how many times they showed up and how many times they went to each restricted area."""
import time
from datetime import datetime, timedelta

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


class FatherLog:
    def __init__(self, db):
        self.db = db

    def record_visit(self, camera_id, now, area='', person=None, kind='father'):
        """A visit to a restricted area (the fridge, a cupboard) started; `kind` is who the camera thought it was (father, family, unknown)."""
        self.db.execute('INSERT INTO restricted_visits(camera_id,started,person,area,kind) VALUES(?,?,?,?,?)', (camera_id, now, person, area or 'Área restrita', kind))

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
        """A photo of the record the visit belongs to: the one taken closest to the visit, or the video's cover."""
        if visit['event_id'] is None:
            return None
        photos = self.db.rows('SELECT id,created FROM event_photos WHERE event_id=?', (visit['event_id'],))
        if photos:
            return min(photos, key=lambda p: abs(p['created'] - visit['started']))['id']
        clip = self.db.rows("SELECT id FROM clips WHERE event_id=? AND state NOT IN ('expired','failed') ORDER BY started LIMIT 1", (visit['event_id'],))
        return clip[0]['id'] if clip else None

    def decide(self, visit_id, father):
        with self.db.connect() as db:
            if not db.execute('UPDATE restricted_visits SET verdict=? WHERE id=?', ('father' if father else 'other', visit_id)).rowcount:
                raise KeyError('Ida não encontrada.')

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
