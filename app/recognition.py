"""Confirmed face references and an asynchronous, bounded recognition worker."""
import json
import threading
import time
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from .body import BodyEncoder, BodyMemory, BodyAnchors
from .config import PEOPLE
from .faces import FaceEncoder, normalized


EXAMPLE_LIMIT = 100   # Taught faces kept per person.
MERGE_GAP = 10   # Seconds between two tracker numbers of one person for them to count as the same person.


class Gallery(list):
    """The reference faces, with the vectors also kept as one matrix per size so a face is compared with all of them at once."""

    def __init__(self, items=()):
        super().__init__(items)
        self.groups = {}
        by_size = {}
        for item in self:
            by_size.setdefault(item['feature'].shape, []).append(item)
        for shape, items in by_size.items():
            people = {}
            for index, item in enumerate(items):
                people.setdefault(item['person_id'], []).append(index)
            self.groups[shape] = (np.stack([item['feature'] for item in items]), {person: np.array(indexes) for person, indexes in people.items()})


def match_person(feature, gallery, threshold=.50, margin=.08):
    vector = normalized(feature)
    grouped = {}
    if isinstance(gallery, Gallery):
        matrix, people = gallery.groups.get(vector.shape, (None, {}))
        if matrix is not None:
            similarity = matrix @ vector
            for person, indexes in people.items():
                grouped[person] = similarity[indexes].tolist()
        gallery = ()
    for item in gallery:
        reference = item['feature']
        if reference.shape == vector.shape:
            grouped.setdefault(item['person_id'], []).append(float(vector @ reference))
    scores = sorted(((float(np.mean(sorted(values, reverse=True)[:2])), person)
                     for person, values in grouped.items()), reverse=True)
    if not scores:
        return None, None
    score, person = scores[0]
    second = scores[1][0] if len(scores) > 1 else -1
    if score < threshold or score-second < margin:
        return None, score
    return person, score


def recompute_identity(connection, event_id):
    tracks = connection.execute('''SELECT t.reviewed,t.person_id,p.is_father FROM person_tracks t
        LEFT JOIN people p ON p.id=t.person_id WHERE event_id=?''', (event_id,)).fetchall()
    if not tracks:
        return
    identity = 'father' if any(t['is_father'] and t['reviewed'] for t in tracks) else (
        'other' if all(t['reviewed'] and t['person_id'] for t in tracks) else 'unknown')
    connection.execute("UPDATE events SET identity=?,identity_source='tracks' WHERE id=?", (identity, event_id))


class Recognition:
    def __init__(self, db, directory=PEOPLE):
        self.db, self.directory = db, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.monitored = {'father'}
        self.encoder_lock = threading.Lock()
        self.condition = threading.Condition()
        self.encoder = None
        self.body_encoder = None
        self.body_error = None
        self.body_memory = BodyMemory()
        self.body_anchors = BodyAnchors()
        self.error = None
        self.gallery = []
        self.names = {}
        self.revision = -1
        self.last_sample = {}
        self.votes = {}
        self.live = {}
        self.visible = set()
        self.pending = None
        self.thread = None
        self.stopping = False
        self.generation = 0
        self.processing_ms = 0
        self.last_processed = None

    def ensure_encoder(self):
        with self.encoder_lock:
            if self.encoder is None:
                self.encoder = FaceEncoder()
        return self.encoder

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping = False
        self.thread = threading.Thread(target=self.run, name='face-recognition', daemon=True)
        self.thread.start()

    def stop(self):
        with self.condition:
            self.stopping = True
            self.pending = None
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=10)

    def reset_tracks(self):
        with self.lock:
            self.generation += 1
            self.last_sample.clear()
            self.votes.clear()
            self.live.clear()
            self.visible.clear()
            self.body_memory.clear()
            self.body_anchors.clear()
        with self.condition:
            self.pending = None

    def submit(self, event_id, frame, boxes, ids, now, settings):
        # One pending frame maximum: slow face inference never queues old video.
        with self.condition:
            self.pending = (self.generation, event_id, frame, boxes, ids, now, settings)
            self.condition.notify()

    def run(self):
        try:
            self.ensure_encoder()
        except Exception as exc:
            self.error = f'Reconhecimento facial indisponível ({type(exc).__name__}). Verifique os modelos locais.'
        while not self.stopping:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or self.pending is not None, timeout=1)
                if self.stopping:
                    break
                task, self.pending = self.pending, None
            if task is None:
                continue
            try:
                self.ensure_encoder()
                generation, event_id, frame, boxes, ids, now, settings = task
                begin = time.perf_counter()
                diagnostics = {}
                faces = self.encoder.for_people(frame, boxes, ids, diagnostics)
                bodies = {}
                if settings.body_reid_enabled and boxes:
                    try:
                        if self.body_encoder is None:
                            self.body_encoder = BodyEncoder()
                        bodies = self.body_encoder.for_people(frame, boxes, ids, diagnostics)
                        self.body_error = None
                    except Exception as exc:
                        self.body_error = f'Reconhecimento corporal indisponível ({type(exc).__name__}). Confira yolo26n-reid.onnx.'
                with self.lock:
                    if generation != self.generation:
                        continue
                    self.observe_faces(event_id, boxes, ids, faces, now, settings, bodies, diagnostics)
                self.processing_ms = round((time.perf_counter()-begin)*1000, 1)
                self.last_processed = now
                self.error = None
            except Exception as exc:
                self.error = f'Falha facial ({type(exc).__name__}); detecção e gravação continuam.'

    def profiles(self):
        rows = self.db.rows('''SELECT p.*,
            (SELECT COUNT(*) FROM person_samples s WHERE s.person_id=p.id AND s.model LIKE 'sface-%') +
            (SELECT COUNT(*) FROM face_enrollments f WHERE f.person_id=p.id) AS examples,
            (SELECT COUNT(DISTINCT t.event_id) FROM person_samples s JOIN person_tracks t ON t.id=s.track_id
                WHERE s.person_id=p.id AND s.model LIKE 'sface-%') AS learned_events,
            (SELECT COUNT(DISTINCT event_id) FROM person_tracks WHERE person_id=p.id AND reviewed=1) AS records
            FROM people p ORDER BY p.is_father DESC,p.created''')
        for row in rows:
            row['enrollments'] = self.db.rows('SELECT id,created FROM face_enrollments WHERE person_id=? ORDER BY created DESC', (row['id'],))
        return rows

    def status(self):
        return {'ready': self.encoder is not None and not self.error, 'error': self.error,
                'kind': 'face+body', 'model': 'YuNet + SFace + YOLO26 ReID',
                'body_error': self.body_error, 'body_reference_people': len(self.body_memory.references), 'profiles': self.profiles(),
                'minimum_examples': 1, 'processing_ms': self.processing_ms, 'last_processed': self.last_processed}

    def invalidate(self, connection):
        connection.execute('UPDATE recognition_meta SET revision=revision+1 WHERE id=1')
        connection.execute('UPDATE person_tracks SET suggested_id=NULL,similarity=NULL,recognized_at=NULL WHERE reviewed=0')
        self.live.clear()
        self.votes.clear()
        self.revision = -1
        self.body_memory.clear()
        self.body_anchors.clear()

    def create_person(self, name):
        with self.lock, self.db.connect() as db:
            if db.execute('SELECT COUNT(*) FROM people').fetchone()[0] >= 30:
                raise ValueError('Limite de 30 perfis atingido.')
            person_id = uuid.uuid4().hex
            db.execute('INSERT INTO people(id,name,created) VALUES(?,?,?)', (person_id, name, time.time()))
            self.invalidate(db)
        return person_id

    def set_birthday(self, person_id, birthday):
        """Birthday as YYYY-MM-DD, or None to clear it. Does not touch recognition, so no cache reset."""
        if birthday is not None:
            try:
                day = date.fromisoformat(birthday)
            except ValueError:
                raise ValueError('Data de aniversário inválida.')
            if not (1900 <= day.year <= date.today().year) or day > date.today():
                raise ValueError('Data de aniversário fora do intervalo aceito.')
            birthday = day.isoformat()
        with self.lock, self.db.connect() as db:
            if not db.execute('UPDATE people SET birthday=? WHERE id=?', (birthday, person_id)).rowcount:
                raise KeyError('Pessoa não encontrada.')

    def set_phone(self, person_id, phone):
        """WhatsApp number (country code + area code + number) or None. Persons with a number get a call button on the kitchen screen."""
        phone = ''.join(c for c in str(phone or '') if c not in ' +()-')
        if phone and (not phone.isascii() or not phone.isdigit() or not 10 <= len(phone) <= 15):
            raise ValueError('Use DDI + DDD + número, por exemplo 5511999999999.')
        with self.lock, self.db.connect() as db:
            if not db.execute('UPDATE people SET phone=? WHERE id=? AND is_father=0', (phone or None, person_id)).rowcount:
                raise KeyError('Pessoa não encontrada.')

    def set_monitored(self, person_id, monitored):
        """Follow this person like the father: presence notices, visits to restricted areas and the weekly report."""
        if person_id == 'father' and not monitored:
            raise ValueError('O perfil principal sempre é acompanhado.')
        with self.lock, self.db.connect() as db:
            if not db.execute('UPDATE people SET is_father=? WHERE id=?', (int(bool(monitored)), person_id)).rowcount:
                raise KeyError('Pessoa não encontrada.')
            if monitored:
                db.execute('UPDATE people SET phone=NULL WHERE id=?', (person_id,))   # The call button is for the family, not for who is watched.
            for event in db.execute('SELECT DISTINCT event_id FROM person_tracks WHERE person_id=?', (person_id,)).fetchall():
                recompute_identity(db, event[0])
            self.invalidate(db)

    def rename_person(self, person_id, name):
        with self.lock, self.db.connect() as db:
            if not db.execute('UPDATE people SET name=? WHERE id=?', (name, person_id)).rowcount:
                raise KeyError('Pessoa não encontrada.')
            self.invalidate(db)

    def forget(self, person_id, delete=False):
        with self.lock, self.db.connect() as db:
            person = db.execute('SELECT * FROM people WHERE id=?', (person_id,)).fetchone()
            if person is None:
                raise KeyError('Pessoa não encontrada.')
            if delete and person_id == 'father':
                raise ValueError('O perfil principal pode ser renomeado ou ter seus exemplos esquecidos.')
            photos = db.execute('SELECT id FROM face_enrollments WHERE person_id=?', (person_id,)).fetchall()
            db.execute('DELETE FROM face_enrollments WHERE person_id=?', (person_id,))
            db.execute('UPDATE person_samples SET person_id=NULL WHERE person_id=?', (person_id,))
            if delete:
                affected = db.execute('SELECT DISTINCT event_id FROM person_tracks WHERE person_id=?', (person_id,)).fetchall()
                db.execute('UPDATE person_tracks SET reviewed=0 WHERE person_id=?', (person_id,))
                db.execute('DELETE FROM people WHERE id=?', (person_id,))
                for event in affected:
                    recompute_identity(db, event[0])
            self.invalidate(db)
        for photo in photos:
            (self.directory / f'{photo[0]}.jpg').unlink(missing_ok=True)

    def enroll(self, person_id, image):
        if not self.db.rows('SELECT id FROM people WHERE id=?', (person_id,)):
            raise KeyError('Pessoa não encontrada.')
        faces = self.ensure_encoder().faces(image, max_width=1280, single=True)
        if len(faces) != 1:
            raise ValueError('Use uma foto com um único rosto visível, nítido e de frente. Não foi encontrado exatamente um rosto adequado.')
        face = faces[0]
        sample_id = uuid.uuid4().hex
        with self.lock, self.db.connect() as db:
            if db.execute('SELECT COUNT(*) FROM face_enrollments WHERE person_id=?', (person_id,)).fetchone()[0] >= 30:
                raise ValueError('Limite de 30 fotos por pessoa. Remova uma foto antes de adicionar outra.')
            target = self.directory / f'{sample_id}.jpg'
            if not cv2.imwrite(str(target), face['crop']):
                raise ValueError('Não foi possível salvar o rosto.')
            db.execute('INSERT INTO face_enrollments(id,person_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',
                       (sample_id,person_id,time.time(),face['feature'].tobytes(),self.encoder.version,face['quality']))
            self.invalidate(db)
        return sample_id

    def examples(self, person_id):
        with self.db.connect() as db:
            person = db.execute('SELECT id,name FROM people WHERE id=?', (person_id,)).fetchone()
            if person is None:
                raise KeyError('Pessoa não encontrada.')
            rows = db.execute("""SELECT s.id,s.created,s.quality,'history' AS source,t.event_id
                FROM person_samples s JOIN person_tracks t ON t.id=s.track_id
                WHERE s.person_id=? AND s.model LIKE 'sface-%'
                UNION ALL SELECT id,created,quality,'upload' AS source,NULL AS event_id
                FROM face_enrollments WHERE person_id=? ORDER BY created DESC,id""", (person_id,person_id)).fetchall()
            return {'person':dict(person), 'examples':[dict(r) for r in rows],
                    'limits':{'history':100,'upload':30}}

    def remove_example(self, person_id, source, sample_id):
        if source == 'upload':
            self.remove_enrollment(person_id, sample_id)
            return
        if source != 'history':
            raise ValueError('Origem de exemplo inválida.')
        with self.lock, self.db.connect() as db:
            # Keep the historical photo and confirmed identity; remove only its
            # membership of the face gallery. It may be explicitly taught again.
            changed = db.execute("""UPDATE person_samples SET person_id=NULL
                WHERE id=? AND person_id=? AND model LIKE 'sface-%'""", (sample_id,person_id)).rowcount
            if not changed:
                raise KeyError('Exemplo não encontrado para esta pessoa.')
            self.invalidate(db)

    def remove_enrollment(self, person_id, sample_id):
        with self.lock, self.db.connect() as db:
            if not db.execute('DELETE FROM face_enrollments WHERE id=? AND person_id=?', (sample_id,person_id)).rowcount:
                raise KeyError('Foto não encontrada.')
            self.invalidate(db)
        (self.directory / f'{sample_id}.jpg').unlink(missing_ok=True)

    def trim_examples(self, db, person_id, keep, limit=EXAMPLE_LIMIT):
        """Keep at most `limit` taught faces per person by dropping the most redundant ones, not the oldest.

        A face that is nearly the same as another one adds nothing; the rare views (profile, glasses, low light) stay.
        The faces just taught (`keep`) are never the ones dropped. A dropped face loses its name and is cleaned up with the other unconfirmed ones.
        """
        rows = db.execute("SELECT id,feature,quality,model,created FROM person_samples WHERE person_id=?", (person_id,)).fetchall()
        excess = len(rows) - limit
        if excess <= 0:
            return
        removable = [row for row in rows if row['id'] not in keep]
        dropped = []
        by_model = {}
        for row in rows:
            by_model.setdefault(row['model'], []).append(row)
        for _ in range(min(excess, len(removable))):
            worst, worst_key = None, None
            for group in by_model.values():
                alive = [row for row in group if row['id'] not in dropped]
                if len(alive) < 2:
                    continue
                vectors = np.stack([normalized(np.frombuffer(row['feature'], dtype=np.float32)) for row in alive])
                similarity = vectors @ vectors.T
                np.fill_diagonal(similarity, -1)
                nearest = similarity.max(axis=1)
                for row, closest in zip(alive, nearest):
                    if row['id'] in keep:
                        continue
                    key = (round(float(closest), 3), -row['quality'], row['created'])   # Most alike, then least sharp, then oldest.
                    if worst_key is None or key > worst_key:
                        worst, worst_key = row, key
            if worst is None:
                worst = min(removable, key=lambda row: row['created'])   # Nothing comparable: fall back to the oldest.
            dropped.append(worst['id'])
            removable = [row for row in removable if row['id'] != worst['id']]
        db.executemany('UPDATE person_samples SET person_id=NULL WHERE id=?', [(sample,) for sample in dropped])

    def confirm(self, track_id, person_id, sample_id=None, sample_ids=()):
        with self.lock, self.db.connect() as db:
            track = db.execute('''SELECT t.*,e.ended,e.kind,e.analysis_state FROM person_tracks t JOIN events e ON e.id=t.event_id
                WHERE t.id=?''', (track_id,)).fetchone()
            if track is None:
                raise KeyError('Pessoa do registro não encontrada.')
            if track['kind']=='manual' and track['analysis_state']!='complete':
                raise ValueError('Aguarde a conclusão da análise para confirmar rostos.')
            if track['ended'] is None:
                raise ValueError('Aguarde o fim do registro para identificar e ensinar.')
            if person_id and not db.execute('SELECT id FROM people WHERE id=?', (person_id,)).fetchone():
                raise KeyError('Perfil não encontrado.')
            chosen = list(dict.fromkeys([*sample_ids, *([sample_id] if sample_id else [])]))
            for chosen_id in chosen:
                sample = db.execute('SELECT model FROM person_samples WHERE id=? AND track_id=?', (chosen_id,track_id)).fetchone()
                if not sample:
                    raise ValueError('A imagem selecionada não pertence a essa pessoa do registro.')
                if not sample['model'].startswith('sface-'):
                    raise ValueError('Esta imagem antiga é do corpo. Cadastre uma foto do rosto na tela Pessoas.')
            db.execute('UPDATE person_samples SET person_id=NULL WHERE track_id=? AND (person_id!=? OR ? IS NULL)', (track_id,person_id,person_id))
            db.execute('UPDATE person_tracks SET person_id=?,reviewed=?,suggested_id=NULL,similarity=NULL WHERE id=?', (person_id,int(person_id is not None),track_id))
            if person_id and chosen:
                db.executemany('UPDATE person_samples SET person_id=? WHERE id=?', [(person_id,chosen_id) for chosen_id in chosen])
                self.trim_examples(db,person_id,set(chosen))
            recompute_identity(db,track['event_id'])
            self.invalidate(db)

    def _open_track(self, db, track_id):
        track = db.execute('''SELECT t.*,e.ended FROM person_tracks t JOIN events e ON e.id=t.event_id WHERE t.id=?''', (track_id,)).fetchone()
        if track is None:
            raise KeyError('Pessoa do registro não encontrada.')
        if track['ended'] is None:
            raise ValueError('Aguarde o fim do registro para alterar as pessoas.')
        return track

    def ignore_track(self, track_id):
        """The detection was not a person (or a duplicate): drop it and the unconfirmed photos it collected."""
        with self.lock, self.db.connect() as db:
            track = self._open_track(db, track_id)
            if track['reviewed']:
                raise ValueError('Esta pessoa já foi identificada. Use “Não sei / desfazer” antes de ignorar.')
            samples = [r['id'] for r in db.execute('SELECT id FROM person_samples WHERE track_id=?', (track_id,))]
            if db.execute('SELECT 1 FROM person_samples WHERE track_id=? AND person_id IS NOT NULL', (track_id,)).fetchone():
                raise ValueError('Há exemplos ensinados nesta pessoa. Use “Não sei / desfazer” antes de ignorar.')
            db.execute('DELETE FROM person_samples WHERE track_id=?', (track_id,))
            db.execute('DELETE FROM person_tracks WHERE id=?', (track_id,))
            recompute_identity(db, track['event_id'])
        for sample in samples:
            (self.directory / f'{sample}.jpg').unlink(missing_ok=True)

    def merge_tracks(self, source_id, target_id):
        """Two numbers of the same record were the same person: move everything of `source` into `target`."""
        if source_id == target_id:
            raise ValueError('Escolha outra pessoa para juntar.')
        with self.lock, self.db.connect() as db:
            source, target = self._open_track(db, source_id), self._open_track(db, target_id)
            if source['event_id'] != target['event_id']:
                raise ValueError('As duas pessoas precisam ser do mesmo registro.')
            if source['reviewed'] and target['reviewed'] and source['person_id'] != target['person_id']:
                raise ValueError('As duas já foram identificadas como pessoas diferentes.')
            db.execute('UPDATE person_samples SET track_id=? WHERE track_id=?', (target_id, source_id))
            db.execute('UPDATE person_tracks SET started=MIN(started,?),last_seen=MAX(last_seen,?) WHERE id=?', (source['started'], source['last_seen'], target_id))
            if source['reviewed'] and not target['reviewed']:
                db.execute('UPDATE person_tracks SET person_id=?,reviewed=1,suggested_id=NULL,similarity=NULL WHERE id=?', (source['person_id'], target_id))
            elif not target['reviewed'] and source['suggested_id'] and (not target['suggested_id'] or (source['similarity'] or 0) > (target['similarity'] or 0)):
                db.execute('UPDATE person_tracks SET suggested_id=?,similarity=?,recognition_kind=?,recognized_at=? WHERE id=?',
                           (source['suggested_id'], source['similarity'], source['recognition_kind'], source['recognized_at'], target_id))
            db.execute('DELETE FROM person_tracks WHERE id=?', (source_id,))
            recompute_identity(db, target['event_id'])

    def split_track(self, track_id, sample_ids):
        """The tracker gave one number to two people: move the chosen faces into a new, unidentified person of the same record."""
        chosen = list(dict.fromkeys(sample_ids))
        if not chosen:
            raise ValueError('Marque os rostos que pertencem à outra pessoa.')
        with self.lock, self.db.connect() as db:
            track = self._open_track(db, track_id)
            samples = db.execute('SELECT id,created,person_id FROM person_samples WHERE track_id=?', (track_id,)).fetchall()
            moving = [s for s in samples if s['id'] in chosen]
            if len(moving) != len(chosen):
                raise ValueError('Uma das imagens marcadas não pertence a essa pessoa do registro.')
            if len(moving) == len(samples):
                raise ValueError('Deixe ao menos um rosto na pessoa original.')
            number = db.execute('SELECT COUNT(*) FROM person_tracks WHERE event_id=?', (track['event_id'],)).fetchone()[0]
            key = f"{track['track_key']}-{number}"
            new_id = db.execute('''INSERT INTO person_tracks(event_id,track_key,started,last_seen,recognition_kind) VALUES(?,?,?,?,'face')''',
                                (track['event_id'], key, min(s['created'] for s in moving), max(s['created'] for s in moving))).lastrowid
            taught = any(s['person_id'] for s in moving)
            db.execute(f"UPDATE person_samples SET track_id=?,person_id=NULL WHERE id IN ({','.join('?' * len(chosen))})", (new_id, *chosen))
            recompute_identity(db, track['event_id'])
            if taught:
                self.invalidate(db)   # Faces taught under the old identity leave the gallery.
        return new_id

    def merge_fragments(self, since):
        """Records with one person at a time whose tracker handed out several numbers: join the ones that follow each other.

        Only unconfirmed numbers that start soon after the previous one ended (and do not suggest different people) are joined.
        Returns how many were joined.
        """
        joined = 0
        events = self.db.rows('''SELECT e.id FROM events e WHERE e.ended IS NOT NULL AND e.started>=? AND e.max_people<=1
            AND (SELECT COUNT(*) FROM person_tracks t WHERE t.event_id=e.id AND t.reviewed=0)>1''', (since,))
        for event in events:
            tracks = self.db.rows('SELECT id,started,last_seen,suggested_id FROM person_tracks WHERE event_id=? AND reviewed=0 ORDER BY started,id', (event['id'],))
            group = [tracks[0]]
            for track in tracks[1:]:
                gap = track['started'] - max(t['last_seen'] for t in group)
                suggested = {t['suggested_id'] for t in group if t['suggested_id']}
                if -1 <= gap <= MERGE_GAP and (not track['suggested_id'] or not suggested or {track['suggested_id']} == suggested):
                    group.append(track)
                else:
                    joined += self._join(group)
                    group = [track]
            joined += self._join(group)
        return joined

    def prune_ghosts(self, since, before):
        """Finished records: drop tracker numbers that never had a face, a suggestion or a confirmation (keeping one if nothing else is left)."""
        dropped = 0
        events = self.db.rows("SELECT id FROM events WHERE ended IS NOT NULL AND ended<? AND started>=? AND (kind!='manual' OR analysis_state='complete')", (before, since))
        for event in events:
            tracks = self.db.rows('''SELECT t.id,t.started,t.last_seen,t.reviewed,t.person_id,t.suggested_id,
                (SELECT COUNT(*) FROM person_samples s WHERE s.track_id=t.id) AS faces FROM person_tracks t WHERE t.event_id=?''', (event['id'],))
            ghosts = [t for t in tracks if not t['reviewed'] and not t['person_id'] and not t['suggested_id'] and not t['faces']]
            if len(ghosts) == len(tracks) and ghosts:
                ghosts.remove(max(ghosts, key=lambda t: t['last_seen'] - t['started']))   # Something must stay to confirm the presence.
            for ghost in ghosts:
                try:
                    self.ignore_track(ghost['id'])
                    dropped += 1
                except (KeyError, ValueError):
                    continue
        return dropped

    def _join(self, group):
        if len(group) < 2:
            return 0
        counts = {t['id']: self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE track_id=?', (t['id'],))[0]['n'] for t in group}
        keep = max(group, key=lambda t: (counts[t['id']], bool(t['suggested_id']), -t['started']))
        done = 0
        for track in group:
            if track['id'] != keep['id']:
                try:
                    self.merge_tracks(track['id'], keep['id'])
                    done += 1
                except (KeyError, ValueError):
                    continue
        return done

    def load_gallery(self):
        revision = self.db.rows('SELECT revision FROM recognition_meta WHERE id=1')[0]['revision']
        if revision != self.revision:
            rows = self.db.rows('''SELECT s.person_id,s.feature FROM person_samples s
                WHERE s.person_id IS NOT NULL AND s.model=? UNION ALL
                SELECT person_id,feature FROM face_enrollments WHERE model=?''', (self.encoder.version,self.encoder.version))
            self.gallery = Gallery({**r,'feature':normalized(np.frombuffer(r['feature'],dtype=np.float32))} for r in rows)
            self.names = {p['id']:p['name'] for p in self.db.rows('SELECT id,name FROM people')}
            self.monitored = {p['id'] for p in self.db.rows('SELECT id FROM people WHERE is_father=1')}
            self.revision = revision
            self.votes.clear()
            self.live.clear()
            self.body_memory.clear()
            self.body_anchors.clear()

    def observe_faces(self, event_id, boxes, ids, faces, now, settings, bodies=None, diagnostics=None):
        self.load_gallery()
        bodies = bodies or {}
        diagnostics = diagnostics or {}
        self.body_memory.prune(now, settings.body_memory_minutes*60)
        if not settings.body_reid_enabled:
            self.body_memory.clear()
            self.body_anchors.clear()
        visible = {str(key) for key in ids if key is not None}
        for key in (set(self.live) | set(self.votes) | set(self.body_memory.votes))-visible:
            self.live.pop(key,None)
            self.votes.pop(key,None)
            self.body_memory.votes.pop(key,None)
        self.visible = visible
        for key in visible:
            face = faces.get(key)
            if event_id is not None:
                self.db.execute('''INSERT INTO person_tracks(event_id,track_key,started,last_seen,recognition_kind)
                    VALUES(?,?,?,?,'face') ON CONFLICT(event_id,track_key) DO UPDATE SET last_seen=excluded.last_seen''', (event_id,key,now,now))
            if not face:
                if event_id is not None:
                    self.db.execute('UPDATE person_tracks SET diagnostic=? WHERE event_id=? AND track_key=?',
                        (json.dumps(diagnostics.get(key,{'reason':'no_face'})),event_id,key))
                continue
            self.body_memory.votes.pop(key, None)
            person,score = match_person(face['feature'],self.gallery,settings.face_threshold,settings.face_margin)
            previous,votes,last_vote = self.votes.get(key,(None,0,0))
            if now-last_vote > 1.5:
                votes = 0
            votes = votes+1 if person and person==previous else int(person is not None)
            self.votes[key]=(person,votes,now)
            if person and votes>=3:
                self.live[key]={'person_id':person,'name':self.names[person],'score':score,'seen':now,'source':'face'}
            else:
                self.live.pop(key,None)
            if event_id is None:
                continue
            track = self.db.rows('SELECT * FROM person_tracks WHERE event_id=? AND track_key=?',(event_id,key))[0]
            if now-self.last_sample.get(track['id'],0)>=2:
                self.last_sample[track['id']]=now
                self.save_best_sample(track['id'],face,now)
            detail=dict(diagnostics.get(key,{}))
            reason='matched' if person and votes>=3 else 'waiting_agreement' if person else 'no_references' if not self.gallery else 'below_threshold' if score is None or score<settings.face_threshold else 'ambiguous_match'
            detail.update(reason=reason,score=score,threshold=settings.face_threshold,agreement=min(votes,3),required=3)
            self.db.execute('UPDATE person_tracks SET diagnostic=? WHERE id=?',(json.dumps(detail),track['id']))
            if not track['reviewed']:
                self.db.execute("UPDATE person_tracks SET suggested_id=?,similarity=?,recognized_at=?,recognition_kind='face' WHERE id=?",
                    (person if votes>=3 else None,score,now if votes>=3 and person else None,track['id']))
        self.suppress_duplicates(event_id, visible)
        if settings.body_reid_enabled:
            self.body_memory.retain(visible & set(bodies))
            # Smooth both stored views and queries, without mixing lost tracks or
            # observations rejected by the face recognizer.
            for key in faces:
                previous=self.body_anchors.items.get(key)
                current=self.live.get(key)
                if not current or (previous and previous['person']!=current['person_id']):
                    self.body_memory.features.pop(key,None)
            bodies={key:self.body_memory.smooth(key,feature,now) for key,feature in bodies.items()}
            continued = self.body_anchors.observe(ids, boxes, faces, self.live, now)
            for key,(person,anchor_time) in continued.items():
                if key in bodies:
                    self.body_memory.learn(person,bodies[key],now,anchored_at=anchor_time)
            # Fresh face evidence seeds memory independently of continued views.
            for key,feature in bodies.items():
                item = self.live.get(key)
                if key in faces and item and item.get('source')=='face' and item['seen']==now:
                    self.body_memory.learn(item['person_id'],feature,now)
            for key in visible:
                if key in faces:
                    continue  # An available face always takes precedence over clothing.
                if key in continued and key in bodies:
                    # Do not score a track against the reference it just taught.
                    if event_id is not None:
                        detail=dict(diagnostics.get(key,{'reason':'no_face'}))
                        detail['body']={'reason':'learning_view'}
                        self.db.execute('UPDATE person_tracks SET diagnostic=? WHERE event_id=? AND track_key=?',
                            (json.dumps(detail),event_id,key))
                    continue
                if key not in bodies:
                    self.body_memory.votes.pop(key,None)
                    if self.live.get(key,{}).get('source')=='body':
                        self.live.pop(key,None)
                    continue
                body_detail={}
                person,score=self.body_memory.match(key,bodies[key],now,settings.body_threshold,settings.body_margin,body_detail)
                previous_body=self.live.get(key,{})
                same_body=(previous_body.get('source')=='body' and
                    previous_body.get('person_id')==body_detail['candidate'] and
                    (body_detail['gap'] is None or body_detail['gap']>=settings.body_margin) and
                    0<=now-previous_body['seen']<=3)
                # A still-visible, recently verified body track need not repeat
                # admission after one noisy observation. New tracks still need 3.
                if not person and same_body and score is not None and score>=settings.body_threshold:
                    person=body_detail['candidate']
                    body_detail.update(reason='continued_match',agreement=1,required=1)
                if event_id is not None:
                    detail=dict(diagnostics.get(key,{'reason':'no_face'}))
                    detail['body']={k:v for k,v in body_detail.items() if k!='candidate'}
                    self.db.execute('UPDATE person_tracks SET diagnostic=? WHERE event_id=? AND track_key=?',
                        (json.dumps(detail),event_id,key))
                if person and person in self.names:
                    self.live[key]={'person_id':person,'name':self.names[person],'score':score,'seen':now,'source':'body'}
                    if event_id is not None:
                        # Keep historical facial evidence if this track already had it.
                        self.db.execute("""UPDATE person_tracks SET suggested_id=?,similarity=?,recognized_at=?,recognition_kind='body'
                            WHERE event_id=? AND track_key=? AND reviewed=0
                            AND NOT (recognition_kind='face' AND suggested_id IS NOT NULL)""",
                            (person,score,now,event_id,key))
                elif self.live.get(key,{}).get('source')=='body':
                    if not (same_body and score is not None and score>=settings.body_threshold-.08):
                        self.live.pop(key,None)
            self.suppress_duplicates(event_id, visible)

    def save_best_sample(self, track_id, face, now):
        """Keep collecting after the first 12 frames; protect confirmed examples."""
        rows=self.db.rows('SELECT id,quality,person_id,feature FROM person_samples WHERE track_id=? AND model=? ORDER BY quality', (track_id,self.encoder.version))
        replace=None
        similar=[r for r in rows if np.frombuffer(r['feature'],dtype=np.float32).shape==face['feature'].shape
                 and float(np.frombuffer(r['feature'],dtype=np.float32) @ face['feature'])>.995]
        if similar:
            if any(r['person_id'] for r in similar):return
            best=max(similar,key=lambda r:r['quality'])
            if face['quality']<=best['quality']*1.2:return
            replace=best
        elif len(rows)>=12:
            replace=next((r for r in rows if not r['person_id']),None)
            if replace is None or face['quality']<=replace['quality']*1.2:return
        sample_id=uuid.uuid4().hex
        target=self.directory/f'{sample_id}.jpg'
        if not cv2.imwrite(str(target),face['crop']):return
        try:
            with self.db.connect() as db:
                if replace:
                    deleted=db.execute('DELETE FROM person_samples WHERE id=? AND person_id IS NULL',(replace['id'],)).rowcount
                    if not deleted:
                        target.unlink(missing_ok=True);return
                db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',
                    (sample_id,track_id,now,face['feature'].tobytes(),self.encoder.version,face['quality']))
        except Exception:
            target.unlink(missing_ok=True);raise
        if replace:(self.directory/f"{replace['id']}.jpg").unlink(missing_ok=True)

    def suppress_duplicates(self, event_id, visible):
        duplicates={p for p,n in Counter(v['person_id'] for k,v in self.live.items() if k in visible).items() if n>1}
        for key in list(self.live):
            if self.live[key]['person_id'] in duplicates:
                self.body_anchors.items.pop(key,None)
                self.live.pop(key,None);self.votes.pop(key,None);self.body_memory.votes.pop(key,None)
                if event_id is not None:
                    self.db.execute('UPDATE person_tracks SET suggested_id=NULL,similarity=NULL,recognized_at=NULL WHERE event_id=? AND track_key=? AND reviewed=0',(event_id,key))

    def labels(self, ids, boxes, now, hold_seconds):
        with self.lock:
            self.body_anchors.retain(ids,boxes)
            body_boxes={str(key):box for key,box in zip(ids,boxes) if key is not None}
            self.body_memory.retain({key for key in body_boxes if not self.body_anchors.overlaps(key,body_boxes)})
            visible={str(key) for key in ids if key is not None}
            # Drop identity immediately on a lost track; an ID returning must be verified again.
            for key in (set(self.live) | set(self.votes) | set(self.body_memory.votes))-visible:
                self.body_anchors.items.pop(key,None)
                self.live.pop(key,None);self.votes.pop(key,None);self.body_memory.votes.pop(key,None)
            output={}
            for key,item in self.live.items():
                age=now-item['seen']
                limit=min(hold_seconds,3) if item.get('source')=='body' else hold_seconds
                if key in visible and 0<=age<=limit:
                    output[key]={**item,'held':age>.8,'monitored':item['person_id'] in self.monitored}
            # FaceEncoder checks unique face ownership. Body rectangles can overlap
            # substantially even when both faces are clearly separated.
            return output

    def cleanup(self, retention_days):
        with self.lock:
            rows=self.db.rows('''SELECT s.id FROM person_samples s JOIN person_tracks t ON t.id=s.track_id
                JOIN events e ON e.id=t.event_id WHERE s.person_id IS NULL AND s.created<? AND e.ended IS NOT NULL AND e.analysis_state!='running' ''',(time.time()-retention_days*86400,))
            for row in rows:
                (self.directory/f"{row['id']}.jpg").unlink(missing_ok=True)
                self.db.execute('DELETE FROM person_samples WHERE id=?',(row['id'],))
