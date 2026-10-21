"""Smart clean-up of the taught faces, run only when asked.

Every taught face is scored against the others: how alike it is to the rest of its own person, and whether it
looks more like somebody else (a wrong name) or is simply blurry. The worst ones go to a quarantine, not into the
bin, and before anything moves the gallery is tested on itself so the result can be compared with the original.
"""
import statistics
import time

import numpy as np

from .faces import normalized
from .views import ViewCache

QUARANTINE_DAYS = 30
MIN_REFERENCES = 20       # A person is never left with fewer references than this.
SWAPPED_MARGIN = .02      # More alike to someone else by this much: probably named wrong.
INTRUDER_ABSOLUTE = .45   # Alike to the rest of its person by less than this (and well below that person's usual).
INTRUDER_BELOW = .20
BLURRY_SHARE = .2         # Sharpness under this share of the person's median ...
BLURRY_FLOOR = 25         # ... or under this value.
MAX_LISTED = 120
PRESELECT_SHARE = .30     # At most this share of a person's gallery is pre-marked for removal in one pass (the worst first); the rest is only listed.
PROFILE_PERSON = .25      # A person with more than this share of clear profiles is mostly seen from the side: their profiles are kept.

SEVERITY = {'swapped': 'high', 'intruder': 'medium', 'unclear': 'medium', 'profile': 'low', 'blurry': 'low'}
REASON_TEXT = {'swapped': 'Parece mais com {other} do que com {own}', 'intruder': 'Pouco parecida com as outras fotos de {own}',
               'unclear': 'Rosto coberto ou não identificável (orelha, copo, mão…)', 'profile': 'De lado, incomum para {own}',
               'blurry': 'Imagem muito borrada'}


def person_scores(vectors, owners, alive):
    """(n x people) score of each face against each person's alive faces: the mean of the two closest, like the live matcher. Itself is left out."""
    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -2)
    similarity[:, ~alive] = -2
    people = sorted(set(owners))
    scores = np.full((len(vectors), len(people)), -1.0, dtype=np.float32)
    for column, person in enumerate(people):
        chosen = (owners == person) & alive
        if not chosen.any():
            continue
        sub = np.sort(similarity[:, chosen], axis=1)[:, -2:]
        sub = np.where(sub > -1.5, sub, np.nan)
        with np.errstate(all='ignore'):
            scores[:, column] = np.nan_to_num(np.nanmean(sub, axis=1), nan=-1.0)
    return scores, people


def accuracy(vectors, owners, alive, tested, threshold, margin):
    """Leave-one-out on the tested faces: how many are named right, how many named as the wrong person, how many left unknown."""
    scores, people = person_scores(vectors, owners, alive)
    index = {person: position for position, person in enumerate(people)}
    right = wrong = 0
    for i in np.flatnonzero(tested):
        order = np.argsort(scores[i])[::-1]
        best, second = scores[i][order[0]], scores[i][order[1]] if len(order) > 1 else -1
        if best < threshold or best - second < margin:
            continue
        if order[0] == index[owners[i]]:
            right += 1
        else:
            wrong += 1
    total = max(1, int(tested.sum()))
    return {'right': round(right / total, 4), 'wrong': round(wrong / total, 4), 'unknown': round(1 - (right + wrong) / total, 4)}


class GalleryCleanup:
    def __init__(self, db, recognition, config):
        self.db, self.recognition, self.config = db, recognition, config

    def load(self):
        rows = self.db.rows('''SELECT s.id,s.person_id,s.feature,s.quality,s.model,'sample' AS source FROM person_samples s
            WHERE s.person_id IS NOT NULL AND s.model LIKE 'sface-%'
            UNION ALL SELECT f.id,f.person_id,f.feature,f.quality,f.model,'upload' FROM face_enrollments f WHERE f.model LIKE 'sface-%' ''')
        if not rows:
            return [], None, None
        models = [r['model'] for r in rows]
        current = max(set(models), key=models.count)
        rows = [r for r in rows if r['model'] == current]
        vectors = np.stack([normalized(np.frombuffer(r['feature'], dtype=np.float32)) for r in rows])
        return rows, vectors, np.array([r['person_id'] for r in rows])

    def analyze(self):
        """Score every taught face and propose the ones to quarantine, with the gallery's accuracy before and after."""
        rows, vectors, owners = self.load()
        if not rows or len(rows) < 3:
            return {'items': [], 'validation': None, 'total': len(rows)}
        settings = self.config.get()
        names = {p['id']: p['name'] for p in self.db.rows('SELECT id,name FROM people')}
        alive = np.ones(len(rows), dtype=bool)
        scores, people = person_scores(vectors, owners, alive)
        index = {person: position for position, person in enumerate(people)}
        own = np.array([scores[i][index[owners[i]]] for i in range(len(rows))])
        quality = np.array([r['quality'] for r in rows])
        typical_own = {person: statistics.median(own[owners == person]) for person in people}
        typical_quality = {person: statistics.median(quality[owners == person]) for person in people}
        views = ViewCache(self.db, self.recognition.directory)
        kinds = {row['id']: views.kind(row['id']) if row['source'] == 'sample' else 'front' for row in rows}
        profile_share = {person: sum(1 for i, row in enumerate(rows) if owners[i] == person and kinds[row['id']] == 'profile') / max(1, int((owners == person).sum())) for person in people}
        found = []
        for i, row in enumerate(rows):
            if row['source'] != 'sample':
                continue   # Photos uploaded on purpose are references, never proposed.
            person = owners[i]
            others = [(scores[i][column], other) for other, column in index.items() if other != person]
            best_other, other_id = max(others) if others else (-1, None)
            reasons = []
            if best_other > own[i] + SWAPPED_MARGIN:
                reasons.append('swapped')
            if own[i] < min(INTRUDER_ABSOLUTE, typical_own[person] - INTRUDER_BELOW):
                reasons.append('intruder')
            view = kinds[row['id']]
            if view == 'unclear':
                reasons.append('unclear')
            elif view == 'profile' and profile_share[person] <= PROFILE_PERSON:
                reasons.append('profile')   # Only when side views are unusual for this person.
            if quality[i] < max(BLURRY_FLOOR, BLURRY_SHARE * typical_quality[person]):
                reasons.append('blurry')
            if reasons:
                top = min(reasons, key=lambda r: ['swapped', 'intruder', 'unclear', 'profile', 'blurry'].index(r))
                found.append({'sample_id': row['id'], 'person_id': person, 'name': names.get(person, ''), 'reasons': reasons, 'severity': SEVERITY[top],
                              'text': ' · '.join(REASON_TEXT[r].format(own=names.get(person, ''), other=names.get(other_id, '')) for r in reasons),
                              'own': round(float(own[i]), 2), 'other': round(float(best_other), 2), 'quality': round(float(quality[i]))})
        found.sort(key=lambda item: (['high', 'medium', 'low'].index(item['severity']), item['own']))
        found = found[:MAX_LISTED]
        per_person = {person: int((owners == person).sum()) for person in people}
        taken, preselected = {}, []
        for item in found:   # Already ordered worst first.
            if item['severity'] == 'low':
                continue
            if taken.get(item['person_id'], 0) < int(PRESELECT_SHARE * per_person[item['person_id']]):
                taken[item['person_id']] = taken.get(item['person_id'], 0) + 1
                preselected.append(item['sample_id'])
        return {'items': found, 'total': len(rows), 'validation': self.validate(rows, vectors, owners, preselected, settings), 'preselected': preselected}

    def validate(self, rows, vectors, owners, removed, settings):
        """Accuracy of the gallery on the faces that stay: with the proposed ones still in it, and without them."""
        gone = set(removed)
        keep = np.array([row['id'] not in gone for row in rows])
        before = accuracy(vectors, owners, np.ones(len(rows), dtype=bool), keep, settings.face_threshold, settings.face_margin)
        after = accuracy(vectors, owners, keep, keep, settings.face_threshold, settings.face_margin)
        return {'removed': len(gone), 'before': before, 'after': after, 'better_or_equal': after['right'] >= before['right'] - .005 and after['wrong'] <= before['wrong'] + .002}

    def apply(self, sample_ids):
        """Move the chosen faces to the quarantine (out of recognition, kept for QUARANTINE_DAYS)."""
        chosen = list(dict.fromkeys(sample_ids))
        if not chosen:
            raise ValueError('Nenhuma foto marcada.')
        now = time.time()
        with self.recognition.lock, self.db.connect() as db:
            marks = ','.join('?' * len(chosen))
            rows = db.execute(f'SELECT id,person_id FROM person_samples WHERE person_id IS NOT NULL AND id IN ({marks})', chosen).fetchall()
            if len(rows) != len(chosen):
                raise ValueError('Uma das fotos marcadas não está mais no aprendizado.')
            for person in {r['person_id'] for r in rows}:
                left = db.execute('SELECT (SELECT COUNT(*) FROM person_samples WHERE person_id=?)+(SELECT COUNT(*) FROM face_enrollments WHERE person_id=?)', (person, person)).fetchone()[0]
                leaving = sum(1 for r in rows if r['person_id'] == person)
                if left - leaving < MIN_REFERENCES:
                    raise ValueError(f'Isso deixaria menos de {MIN_REFERENCES} fotos de referência para uma das pessoas. Desmarque algumas.')
            db.executemany('INSERT OR REPLACE INTO gallery_quarantine(sample_id,person_id,created) VALUES(?,?,?)', [(r['id'], r['person_id'], now) for r in rows])
            db.execute(f'UPDATE person_samples SET person_id=NULL WHERE id IN ({marks})', chosen)
            self.recognition.invalidate(db)
        return len(rows)

    def quarantined(self):
        return self.db.rows('''SELECT q.sample_id,q.person_id,q.created,p.name FROM gallery_quarantine q JOIN people p ON p.id=q.person_id
            JOIN person_samples s ON s.id=q.sample_id ORDER BY q.created DESC''')

    def restore(self, sample_ids):
        chosen = list(dict.fromkeys(sample_ids))
        restored = 0
        with self.recognition.lock, self.db.connect() as db:
            for sample in chosen:
                row = db.execute('SELECT q.person_id FROM gallery_quarantine q JOIN people p ON p.id=q.person_id WHERE q.sample_id=?', (sample,)).fetchone()
                if row and db.execute('UPDATE person_samples SET person_id=? WHERE id=?', (row['person_id'], sample)).rowcount:
                    db.execute('DELETE FROM gallery_quarantine WHERE sample_id=?', (sample,))
                    self.recognition.trim_examples(db, row['person_id'], {sample})
                    restored += 1
            if restored:
                self.recognition.invalidate(db)
        return restored

    def purge(self, now=None):
        """Quarantined faces older than QUARANTINE_DAYS are deleted for good."""
        cutoff = (now or time.time()) - QUARANTINE_DAYS * 86400
        for row in self.db.rows('SELECT sample_id FROM gallery_quarantine WHERE created<?', (cutoff,)):
            (self.recognition.directory / f"{row['sample_id']}.jpg").unlink(missing_ok=True)
            self.db.execute('DELETE FROM person_samples WHERE id=? AND person_id IS NULL', (row['sample_id'],))
            self.db.execute('DELETE FROM gallery_quarantine WHERE sample_id=?', (row['sample_id'],))
