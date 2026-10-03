"""The father's usual day, learned from recent presence records.

For each of the last 28 days: the first appearance after 04:00 (waking up) and the longest
daytime gap between two presences. With at least a week of data, the late end of each
distribution (90th percentile) says what "normal" is, separately for weekdays and weekends
when both have enough days. No model: plain statistics that can be read and explained.
"""
import math
from datetime import datetime, timedelta

from .db import TZ

HISTORY_DAYS = 28
MIN_DAYS = 7            # Days with records before trusting the routine.
MIN_GROUP_DAYS = 4      # Days needed to learn weekdays and weekends separately.
DAY_STARTS = 4          # Presences before 04:00 are the previous night.
DAYTIME = (7, 22)       # Hours where long gaps are measured.
FIRST_MARGIN = 30 * 60  # Wait a little beyond the usual latest arrival.


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def clock_text(seconds_after_midnight):
    minutes = round(seconds_after_midnight / 60)
    return f'{minutes // 60 % 24:02d}:{minutes % 60:02d}'


class Routine:
    def __init__(self, db):
        self.db = db
        self.cache = (None, None)  # Recomputed every 10 minutes at most.

    def days(self, now):
        """Per local day: date, weekday flag, first appearance (s after midnight), longest daytime gap (s)."""
        today = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=HISTORY_DAYS)
        rows = self.db.rows("SELECT started,last_seen FROM events WHERE kind='presence' AND started>=? AND started<? ORDER BY started",
                            (start.timestamp(), today.timestamp()))
        grouped = {}
        for row in rows:
            local = datetime.fromtimestamp(row['started'], TZ)
            if local.hour >= DAY_STARTS:
                grouped.setdefault(local.date(), []).append(row)
        result = []
        for day, events in sorted(grouped.items()):
            midnight = datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()
            window = (midnight + DAYTIME[0] * 3600, midnight + DAYTIME[1] * 3600)
            gap, previous = 0, None
            for event in events:
                if window[0] <= event['started'] <= window[1] and previous is not None:
                    gap = max(gap, event['started'] - max(previous, window[0]))
                previous = max(previous or 0, event['last_seen'])
            result.append({'date': day, 'weekend': day.weekday() >= 5,
                           'first': events[0]['started'] - midnight, 'gap': gap})
        return result

    def summary(self, now):
        key = int(now // 600)
        if self.cache[0] != key:
            self.cache = (key, self.compute(now))
        return self.cache[1]

    def compute(self, now):
        days = self.days(now)
        groups = {'weekday': [d for d in days if not d['weekend']], 'weekend': [d for d in days if d['weekend']]}

        def describe(items):
            if len(items) < MIN_GROUP_DAYS:
                return None
            firsts = [d['first'] for d in items]
            return {'days': len(items), 'usual_first': clock_text(percentile(firsts, .5)),
                    'latest_first': clock_text(percentile(firsts, .9)), 'latest_first_seconds': percentile(firsts, .9)}

        hourly = [0] * 24
        for row in self.db.rows("SELECT started FROM events WHERE kind='presence' AND started>=?", (now - HISTORY_DAYS * 86400,)):
            hourly[datetime.fromtimestamp(row['started'], TZ).hour] += 1
        gaps = [d['gap'] for d in days if d['gap']]
        return {'learned': len(days) >= MIN_DAYS, 'days': len(days), 'needed_days': MIN_DAYS,
                'all': describe(days), 'weekday': describe(groups['weekday']), 'weekend': describe(groups['weekend']),
                'usual_gap_hours': round(percentile(gaps, .9) / 3600, 1) if gaps else None,
                'hourly': [round(n / max(1, len(days)), 2) for n in hourly]}

    def expected_first(self, now, summary=None):
        """Latest usual first appearance for today's kind of day, in seconds after midnight, or None."""
        summary = summary or self.summary(now)
        if not summary['learned']:
            return None
        weekend = datetime.fromtimestamp(now, TZ).weekday() >= 5
        group = summary['weekend' if weekend else 'weekday'] or summary['all']
        return group and group['latest_first_seconds'] + FIRST_MARGIN
