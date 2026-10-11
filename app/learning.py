"""Face examples the system proposes on its own; they only teach after a person approves them.

A candidate is a face already saved from a finished record whose track the recognizer matched
by face. It must match the same profile again on its own (high similarity and a margin over
every other profile), be at least as sharp as the profile's typical example and add a view
the gallery does not already have. The best candidate of each track is proposed once.
"""
import statistics
import time

import numpy as np

from .faces import normalized
from .recognition import match_person

LOOKBACK_SECONDS = 3 * 86400
DUPLICATE_SIMILARITY = .97   # Nearly the same image as an existing example teaches nothing new.
MAX_PENDING_PER_PERSON = 12


def as_vector(blob):
    return normalized(np.frombuffer(blob, dtype=np.float32))


class LearningSuggestions:
    def __init__(self, db, recognition, config):
        self.db, self.recognition, self.config = db, recognition, config
        self.last_scan = 0

    def references(self, model):
        rows = self.db.rows('''SELECT person_id,feature,quality FROM person_samples WHERE person_id IS NOT NULL AND model=?
            UNION ALL SELECT person_id,feature,quality FROM face_enrollments WHERE model=?''', (model, model))
        return [{'person_id': r['person_id'], 'feature': as_vector(r['feature']), 'quality': r['quality']} for r in rows]

    def scan(self, now=None):
        """Propose new examples from recent records; returns how many were added."""
        now = now or time.time()
        self.last_scan = now
        settings = self.config.get()
        if not settings.learning_suggestions_enabled:
            return 0
        candidates = self.db.rows('''SELECT s.id,s.feature,s.quality,s.model,t.id AS track_id,t.suggested_id AS person_id
            FROM person_samples s JOIN person_tracks t ON t.id=s.track_id JOIN events e ON e.id=t.event_id
            WHERE s.person_id IS NULL AND s.model LIKE 'sface-%' AND s.created>=?
            AND t.reviewed=0 AND t.recognition_kind='face' AND t.suggested_id IS NOT NULL AND e.ended IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM learning_suggestions l JOIN person_samples o ON o.id=l.sample_id WHERE o.track_id=t.id)
            ORDER BY s.quality DESC''', (now - LOOKBACK_SECONDS,))
        galleries, best = {}, {}
        for row in candidates:
            if row['track_id'] in best:
                continue  # Rows come sharpest first: keep one per track.
            gallery = galleries.setdefault(row['model'], self.references(row['model']))
            score = self.qualifies(row, gallery, settings)
            if score is not None:
                best[row['track_id']] = (row, score)
        added = 0
        with self.db.connect() as db:
            for row, score in best.values():
                pending = db.execute("SELECT COUNT(*) FROM learning_suggestions WHERE person_id=? AND state='pending'", (row['person_id'],)).fetchone()[0]
                if pending >= MAX_PENDING_PER_PERSON:
                    continue
                added += db.execute('INSERT OR IGNORE INTO learning_suggestions(sample_id,person_id,score,created) VALUES(?,?,?,?)',
                                    (row['id'], row['person_id'], score, now)).rowcount
        return added

    @staticmethod
    def qualifies(row, gallery, settings):
        feature = as_vector(row['feature'])
        person, score = match_person(feature, gallery, settings.learning_threshold, settings.face_margin)
        if person != row['person_id']:
            return None
        own = [item for item in gallery if item['person_id'] == person]
        if max(float(feature @ item['feature']) for item in own) >= DUPLICATE_SIMILARITY:
            return None
        if row['quality'] < statistics.median(item['quality'] for item in own):
            return None
        return round(score, 3)

    def pending(self):
        return self.db.rows('''SELECT l.sample_id,l.person_id,l.score,l.created,p.name,s.quality,s.created AS seen,
            t.id AS track_id,t.event_id FROM learning_suggestions l JOIN people p ON p.id=l.person_id
            JOIN person_samples s ON s.id=l.sample_id JOIN person_tracks t ON t.id=s.track_id
            WHERE l.state='pending' ORDER BY p.is_father DESC,l.score DESC LIMIT 60''')

    def decide(self, sample_id, approve):
        rows = self.db.rows("""SELECT l.person_id,s.track_id FROM learning_suggestions l JOIN person_samples s ON s.id=l.sample_id
            WHERE l.sample_id=? AND l.state='pending'""", (sample_id,))
        if not rows:
            raise KeyError('Sugestão não encontrada ou já decidida.')
        if approve:
            # The same path as a manual confirmation in the history: teaches this face and names the person.
            self.recognition.confirm(rows[0]['track_id'], rows[0]['person_id'], sample_id)
        self.db.execute('UPDATE learning_suggestions SET state=? WHERE sample_id=?', ('approved' if approve else 'rejected', sample_id))

    def discard(self, sample_id):
        """A bad photo (blurred, cut off, someone else's back): delete it so nothing is ever learned from it.

        The unconfirmed sample and its file go away; the record, the other faces of the track and every
        confirmed example stay untouched.
        """
        rows = self.db.rows("""SELECT s.id FROM learning_suggestions l JOIN person_samples s ON s.id=l.sample_id
            WHERE l.sample_id=? AND l.state='pending' AND s.person_id IS NULL""", (sample_id,))
        if not rows:
            raise KeyError('Sugestão não encontrada ou já decidida.')
        self.db.execute('DELETE FROM person_samples WHERE id=? AND person_id IS NULL', (sample_id,))   # The suggestion goes with it (cascade).
        (self.recognition.directory / f'{sample_id}.jpg').unlink(missing_ok=True)
