import json
import logging
import threading
import time
from datetime import datetime

import httpx

from .alerts import CHECK_INTERVAL
from .config import WA_URL, gateway_token
from .db import TZ
from .recorder import cleanup, free_space, transcode

log = logging.getLogger(__name__)

HOURLY = 3600
LEARNING_INTERVAL = 300
# A face suggestion of the father that overlaps this clip; needs :threshold and aliases e (event), c (clip).
PROBABLE_FATHER = """EXISTS (SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.suggested_id
    WHERE t.event_id=e.id AND p.is_father=1 AND t.reviewed=0
    AND t.started<=c.ended AND t.last_seen>=c.started
    AND t.recognition_kind='face' AND t.similarity>=:threshold)"""
UNCONFIRMED = 'Sem confirmação de envio. Confira o WhatsApp antes de reenviar.'


def gateway_connected(client):
    try:
        return client.get(f'{WA_URL}/status').json().get('state') == 'connected'
    except (httpx.HTTPError, ValueError):
        return False


def caption_for(clip, event, settings, probable):
    when = datetime.fromtimestamp(clip['started'], TZ).strftime('%d/%m às %H:%M')
    who = ('Meu pai (confirmado no painel)' if event['identity'] == 'father'
           else 'Provável presença do pai (reconhecimento facial automático)' if probable
           else 'Presença detectada')
    return f'{who} · {event["camera_name"] or settings.camera_name}\n{when} · {round(clip["duration"])} s\nRegistro #{clip["event_id"]}'


def restricted_without_whatsapp(camera_settings):
    """True for a clip recorded by a camera in restricted mode whose WhatsApp sending was switched off."""
    try:
        saved = json.loads(camera_settings or '{}')
    except ValueError:
        return False
    return bool(saved.get('restricted_enabled')) and saved.get('restricted_whatsapp') is False


class Jobs:
    def __init__(self, db, config, recognition=None, alerts=None, auth=None, learning=None, backups=None, notebook=None):
        self.db, self.config = db, config
        self.recognition, self.alerts, self.auth, self.learning, self.backups = recognition, alerts, auth, learning, backups
        self.extra_cleanups = []   # Other parts of the application that tidy their own files hourly.
        self.notebook = notebook
        self.stop_event = threading.Event()
        self.threads = []
        self.headers = {'Authorization': f'Bearer {gateway_token()}'}

    def start(self):
        targets = [self.process_loop, self.delivery_loop]
        if self.notebook:
            targets.append(lambda: self.notebook.run(self.stop_event))   # The screen has its own, faster loop.
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=5)

    # Recordings --------------------------------------------------------------

    def process_loop(self):
        last_cleanup = 0
        while not self.stop_event.is_set():
            try:
                pending = self.db.rows("SELECT * FROM clips WHERE state='processing' ORDER BY started LIMIT 1")
                if pending:
                    transcode(self.db, pending[0])
                if self.learning and time.time() - self.learning.last_scan >= LEARNING_INTERVAL:
                    if self.recognition:
                        self.recognition.merge_fragments(time.time() - 3 * 86400)
                        self.recognition.prune_ghosts(time.time() - 30 * 86400, time.time() - 600)
                    self.learning.scan()
                if self.backups and self.backups.due():
                    try:
                        self.backups.run()
                    except ValueError:
                        pass  # Recorded in the backup status and sent as an alert.
                since = time.time() - last_cleanup
                if since > HOURLY or (since > 60 and free_space() < self.config.get().min_free_gb):
                    self.housekeeping()
                    last_cleanup = time.time()
            except Exception:
                log.exception('Falha ao processar gravação')
            self.stop_event.wait(.5)

    def housekeeping(self):
        settings = self.config.get()
        cleanup(self.db, settings.retention_days, min_free_gb=settings.min_free_gb)
        if self.recognition:
            self.recognition.cleanup(settings.retention_days)
        if self.alerts:
            self.alerts.cleanup()
        for extra in self.extra_cleanups:
            extra()
        if self.auth:
            self.auth.prune_sessions()

    # WhatsApp videos ---------------------------------------------------------

    def prepare_deliveries(self, settings):
        """Create one delivery row per recipient for new clips and drop removed recipients."""
        targets = settings.delivery_targets()
        if not targets:
            return
        with self.db.connect() as db:
            clips = db.execute("""SELECT clips.id,clips.started,e.camera_settings FROM clips JOIN events e ON e.id=clips.event_id
                WHERE clips.state='ready' AND clips.delivery IN ('pending','retry')
                AND NOT EXISTS(SELECT 1 FROM clip_deliveries d WHERE d.clip_id=clips.id)
                ORDER BY clips.started LIMIT 100""").fetchall()
            for clip in clips:
                eligible = {phone: policy for phone, policy in targets.items() if clip['started'] >= settings.recipient_since.get(phone, 0)}
                if restricted_without_whatsapp(clip['camera_settings']):
                    eligible = {}   # Restricted mode set to web-app notifications only: the video stays in the history.
                if not eligible:
                    db.execute("UPDATE clips SET delivery='skipped',error=NULL WHERE id=?", (clip['id'],))
                db.executemany('INSERT OR IGNORE INTO clip_deliveries(clip_id,recipient,father_only) VALUES(?,?,?)',
                               [(clip['id'], phone, int(father_only)) for phone, father_only in eligible.items()])
            pending = db.execute("""SELECT DISTINCT d.clip_id,d.recipient,c.started FROM clip_deliveries d JOIN clips c ON c.id=d.clip_id
                WHERE d.delivery IN ('pending','retry','failed','uncertain')""").fetchall()
            changed = set()
            for row in pending:
                if row['recipient'] not in targets or row['started'] < settings.recipient_since.get(row['recipient'], 0):
                    db.execute("UPDATE clip_deliveries SET delivery='cancelled',error=NULL WHERE clip_id=? AND recipient=?", (row['clip_id'], row['recipient']))
                    changed.add(row['clip_id'])
                else:
                    db.execute('UPDATE clip_deliveries SET father_only=? WHERE clip_id=? AND recipient=?',
                               (int(targets[row['recipient']]), row['clip_id'], row['recipient']))
        for clip_id in changed:
            self.db.aggregate_delivery(clip_id)

    def next_delivery(self, settings):
        rows = self.db.rows(f"""SELECT c.*,d.recipient AS target,d.attempts AS target_attempts
            FROM clip_deliveries d JOIN clips c ON c.id=d.clip_id JOIN events e ON e.id=c.event_id
            WHERE c.state='ready' AND c.delivery!='skipped' AND d.delivery IN ('pending','retry') AND d.retry_at<=:now
            AND (e.kind!='manual' OR (e.analysis_state!='running' AND e.identity!='unknown'))
            AND (d.father_only=0 OR e.identity='father' OR (:probable=1 AND {PROBABLE_FATHER}))
            ORDER BY c.started,d.recipient LIMIT 1""",
            {'now': time.time(), 'probable': int(self.sends_probable(settings)), 'threshold': settings.face_threshold})
        return rows[0] if rows else None

    @staticmethod
    def sends_probable(settings):
        return settings.send_probable_father and settings.recognition_enabled

    def is_probable_father(self, clip, settings):
        return self.sends_probable(settings) and bool(self.db.rows(
            f'SELECT 1 FROM clips c JOIN events e ON e.id=c.event_id WHERE c.id=:clip AND {PROBABLE_FATHER}',
            {'clip': clip['id'], 'threshold': settings.face_threshold}))

    def mark(self, clip_id, phone, delivery, error=None, **extra):
        columns = ''.join(f',{name}=?' for name in extra)
        self.db.execute(f'UPDATE clip_deliveries SET delivery=?,error=?{columns} WHERE clip_id=? AND recipient=?',
                        (delivery, error, *extra.values(), clip_id, phone))

    def deliver_one(self, client):
        settings = self.config.get()
        if not settings.whatsapp_enabled or not settings.delivery_targets():
            return
        self.prepare_deliveries(settings)
        clip = self.next_delivery(settings)
        if clip is None or not gateway_connected(client):
            return
        phone = clip['target']
        # Settings or the identity may have changed while waiting for the gateway.
        latest = self.config.get()
        targets = latest.delivery_targets()
        event = self.db.rows('SELECT identity,kind,analysis_state,camera_name FROM events WHERE id=?', (clip['event_id'],))[0]
        if event['kind'] == 'manual' and (event['analysis_state'] == 'running' or event['identity'] == 'unknown'):
            return
        probable = self.is_probable_father(clip, latest)
        if (not latest.whatsapp_enabled or phone not in targets or clip['started'] < latest.recipient_since.get(phone, 0)
                or (targets[phone] and event['identity'] != 'father' and not probable)):
            return
        with self.db.connect() as db:
            claimed = db.execute("""UPDATE clip_deliveries SET delivery='sending',attempts=attempts+1,error=NULL
                WHERE clip_id=? AND recipient=? AND delivery IN ('pending','retry')""", (clip['id'], phone)).rowcount
        if not claimed:
            return
        self.db.aggregate_delivery(clip['id'])
        try:
            self.send(client, clip, phone, caption_for(clip, event, latest, probable))
        finally:
            self.db.aggregate_delivery(clip['id'])

    def send(self, client, clip, phone, caption):
        try:
            response = client.post(f'{WA_URL}/send', json={'clip_id': clip['id'], 'recipient': phone, 'caption': caption})
            if response.status_code == 409:
                self.mark(clip['id'], phone, 'uncertain', 'Envio sem confirmação. Confira o WhatsApp antes de reenviar.')
                return
            response.raise_for_status()
            self.mark(clip['id'], phone, 'sent', sent_at=time.time(), message_id=response.json()['message_id'])
        except (httpx.TimeoutException, httpx.NetworkError, ValueError, KeyError):
            self.mark(clip['id'], phone, 'uncertain', UNCONFIRMED)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 503:
                delay = min(300, 15 * 2 ** min(clip['target_attempts'], 4))
                self.mark(clip['id'], phone, 'retry', 'WhatsApp indisponível. Nova tentativa automática.', retry_at=time.time() + delay)
            else:
                self.mark(clip['id'], phone, 'failed', 'Falha de envio. Verifique o número e o WhatsApp.')

    # Loop --------------------------------------------------------------------

    def delivery_loop(self):
        with httpx.Client(timeout=90, headers=self.headers, trust_env=False) as client:
            while not self.stop_event.is_set():
                for step in (self.deliver_one, self.alert_step):
                    try:
                        step(client)
                    except Exception:
                        log.exception('Falha na fila do WhatsApp')
                self.stop_event.wait(1)

    def alert_step(self, client):
        if not self.alerts:
            return
        if time.time() - self.alerts.last_check >= CHECK_INTERVAL:
            self.alerts.check()
        self.alerts.deliver_one(client)
