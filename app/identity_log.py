"""A record of every time a named person turns "unknown" on the camera, why, and whether the name came back."""
import time

REASONS = {
    'track_lost': 'O rastreador perdeu a pessoa (cobriu-se, cruzou com outra ou saiu do quadro) e ela voltou com outro número',
    'expired': 'Ficou tempo demais sem rosto nem corpo reconhecido',
    'contradicted': 'O rosto visto não parecia com a pessoa que estava com o nome',
    'overlap': 'Cruzou com outra pessoa e o nome foi retirado por segurança',
}
RECOVER_WITHIN = 120   # Seconds: a name that comes back this soon counts as recovered.


class IdentityLog:
    def __init__(self, db):
        self.db = db
        self.open = {}   # person id -> (row id, when): lost and not seen again yet.

    def lost(self, now, camera_id, person_id, key, reason, source='', age=None, detail=''):
        """The same loss is written once: a person already open (lost, not back yet) is not logged again."""
        if person_id in self.open and now - self.open[person_id][1] < RECOVER_WITHIN:
            return None
        row = self.db.execute('INSERT INTO identity_log(at,camera_id,person_id,track_key,reason,source,age,detail) VALUES(?,?,?,?,?,?,?,?)',
                              (now, camera_id or '', person_id, str(key), reason, source or '', None if age is None else round(age, 1), detail[:120]))
        self.open[person_id] = (row, now)
        return row

    def named(self, now, person_id):
        """The person is named again: the open loss (if recent) gets how long it took."""
        entry = self.open.pop(person_id, None)
        if entry and now - entry[1] <= RECOVER_WITHIN:
            self.db.execute('UPDATE identity_log SET recovered_after=? WHERE id=?', (round(now - entry[1], 1), entry[0]))

    def summary(self, days=3, now=None):
        since = (now or time.time()) - days * 86400
        rows = self.db.rows('SELECT reason,recovered_after,person_id FROM identity_log WHERE at>=?', (since,))
        by_reason = {}
        for row in rows:
            item = by_reason.setdefault(row['reason'], {'reason': row['reason'], 'label': REASONS.get(row['reason'], row['reason']), 'count': 0, 'recovered': 0})
            item['count'] += 1
            item['recovered'] += row['recovered_after'] is not None
        gaps = sorted(r['recovered_after'] for r in rows if r['recovered_after'] is not None)
        names = {p['id']: p['name'] for p in self.db.rows('SELECT id,name FROM people')}
        per_person = {}
        for row in rows:
            per_person[row['person_id']] = per_person.get(row['person_id'], 0) + 1
        return {'days': days, 'total': len(rows), 'recovered': len(gaps), 'median_gap': gaps[len(gaps) // 2] if gaps else None,
                'by_reason': sorted(by_reason.values(), key=lambda r: -r['count']),
                'by_person': [{'name': names.get(pid, pid), 'count': n} for pid, n in sorted(per_person.items(), key=lambda kv: -kv[1])]}

    def cleanup(self, days=14, now=None):
        self.db.execute('DELETE FROM identity_log WHERE at<?', ((now or time.time()) - days * 86400,))
