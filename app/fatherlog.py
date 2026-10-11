"""Follow the father through the day: how many times he showed up and how many times he went to the fridge."""
import time
from datetime import datetime, timedelta

from .db import TZ

DAYS = 7
SLACK = 5   # Seconds around a record that still count as inside it.


class FatherLog:
    def __init__(self, db):
        self.db = db

    def record_visit(self, camera_id, now, area='', person=None):
        """A visit to a restricted area (the fridge, a cupboard) started."""
        self.db.execute('INSERT INTO restricted_visits(camera_id,started,person,area) VALUES(?,?,?,?)', (camera_id, now, person, area or 'Área restrita'))

    def midnight(self, now, days_back=0):
        day = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
        return day.timestamp()

    def sightings(self, since, until):
        """Presence records in which the father was recognised, oldest first."""
        return self.db.rows('''SELECT e.id,e.started,e.ended,e.camera_name FROM events e
            WHERE e.started>=? AND e.started<? AND EXISTS (SELECT 1 FROM person_tracks t WHERE t.event_id=e.id AND t.person_id='father')
            ORDER BY e.started''', (since, until))

    def visits(self, since, until):
        """Visits to restricted areas, minus those in a record the family reviewed and found were not the father."""
        return self.db.rows('''SELECT v.started,v.camera_id,v.area FROM restricted_visits v WHERE v.started>=? AND v.started<?
            AND NOT EXISTS (SELECT 1 FROM events e WHERE e.camera_id=v.camera_id AND v.started BETWEEN e.started-?3 AND COALESCE(e.ended,e.last_seen)+?3
                AND EXISTS (SELECT 1 FROM person_tracks t WHERE t.event_id=e.id AND t.reviewed=1 AND t.person_id IS NOT NULL AND t.person_id!='father')
                AND NOT EXISTS (SELECT 1 FROM person_tracks t WHERE t.event_id=e.id AND t.person_id='father'))
            ORDER BY v.started''', (since, until, SLACK))

    @staticmethod
    def by_area(visits):
        """{area name: [times]} in the order each area first appears."""
        found = {}
        for row in visits:
            found.setdefault(row['area'] or 'Área restrita', []).append(row['started'])
        return found

    def count_today(self, now=None):
        now = now or time.time()
        return len(self.sightings(self.midnight(now), now + 1))

    def summary(self, now=None):
        """Today's times plus a count per day for the last week (today included)."""
        now = now or time.time()
        start = self.midnight(now)
        today = {'sightings': [{'id': r['id'], 'started': r['started'], 'ended': r['ended'], 'camera': r['camera_name']} for r in self.sightings(start, now + 1)],
                 'areas': self.by_area(self.visits(start, now + 1))}
        week = []
        for back in range(DAYS - 1, -1, -1):
            first, last = self.midnight(now, back), self.midnight(now, back - 1) if back else now + 1
            visits = self.visits(first, last)
            week.append({'day': datetime.fromtimestamp(first, TZ).strftime('%Y-%m-%d'), 'sightings': len(self.sightings(first, last)), 'visits': len(visits),
                         'areas': {name: len(times) for name, times in self.by_area(visits).items()}})
        return {'today': today, 'week': week}
