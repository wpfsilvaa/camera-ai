import logging
import threading
import time
from datetime import datetime

import httpx

from .config import WA_URL, gateway_token
from .db import TZ
from .recorder import cleanup, transcode

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, db, config, recognition=None):
        self.db, self.config = db, config
        self.recognition = recognition
        self.stop_event = threading.Event()
        self.threads = []
        self.headers = {'Authorization': f'Bearer {gateway_token()}'}

    def start(self):
        for target in (self.process_loop, self.delivery_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=5)

    def process_loop(self):
        last_cleanup = 0
        while not self.stop_event.is_set():
            try:
                pending = self.db.rows("SELECT * FROM clips WHERE state='processing' ORDER BY started LIMIT 1")
                if pending:
                    transcode(self.db, pending[0])
                if time.time() - last_cleanup > 3600:
                    cleanup(self.db, self.config.get().retention_days)
                    if self.recognition:
                        self.recognition.cleanup(self.config.get().retention_days)
                    last_cleanup = time.time()
            except Exception:
                log.exception('Falha ao processar gravação')
            self.stop_event.wait(.5)

    def deliver_one(self, client):
        settings = self.config.get()
        if not settings.whatsapp_enabled or not settings.recipient:
            return
        rows = self.db.rows('''SELECT clips.*, events.identity FROM clips JOIN events ON events.id=clips.event_id
            WHERE clips.state='ready' AND clips.delivery IN ('pending','retry') AND clips.retry_at<=?
            AND (events.kind!='manual' OR (events.analysis_state!='running' AND events.identity!='unknown'))
            AND (?=0 OR events.identity='father' OR (?=1 AND EXISTS (
                SELECT 1 FROM person_tracks t JOIN people p ON p.id=t.suggested_id
                WHERE t.event_id=events.id AND p.is_father=1 AND t.reviewed=0
                AND t.started<=clips.ended AND t.last_seen>=clips.started
                AND t.recognition_kind='face' AND t.similarity>=?))) ORDER BY clips.started LIMIT 1''',
            (time.time(), int(settings.father_only), int(settings.send_probable_father and settings.recognition_enabled), settings.face_threshold))
        if not rows:
            return
        row = rows[0]
        try:
            status = client.get(f'{WA_URL}/status').json()
            if status.get('state') != 'connected':
                return
        except (httpx.HTTPError, ValueError):
            return
        # Check the identity filter again immediately before sending.
        latest = self.config.get()
        event = self.db.rows('SELECT identity,kind,analysis_state,camera_name FROM events WHERE id=?', (row['event_id'],))[0]
        identity = event['identity']
        if event['kind']=='manual' and (event['analysis_state']=='running' or identity=='unknown'):
            return
        probable = latest.recognition_enabled and latest.send_probable_father and bool(self.db.rows('''SELECT t.id FROM person_tracks t
            JOIN people p ON p.id=t.suggested_id WHERE t.event_id=? AND p.is_father=1 AND t.reviewed=0
            AND t.started<=? AND t.last_seen>=? AND t.recognition_kind='face' AND t.similarity>=?''',
            (row['event_id'], row['ended'], row['started'], latest.face_threshold)))
        if not latest.whatsapp_enabled or not latest.recipient or (latest.father_only and identity != 'father' and not probable):
            return
        self.db.execute("UPDATE clips SET delivery='sending',attempts=attempts+1,recipient=? WHERE id=?", (latest.recipient, row['id']))
        when = datetime.fromtimestamp(row['started'], TZ).strftime('%d/%m às %H:%M')
        who = 'Meu pai (confirmado no painel)' if identity == 'father' else 'Provável presença do pai (reconhecimento facial automático)' if probable else 'Presença detectada'
        caption = f'{who} · {event['camera_name'] or latest.camera_name}\n{when} · {round(row["duration"])} s\nRegistro #{row["event_id"]}'
        try:
            response = client.post(f'{WA_URL}/send', json={'clip_id': row['id'], 'recipient': latest.recipient, 'caption': caption})
            if response.status_code == 409:
                self.db.execute("UPDATE clips SET delivery='uncertain',error='Envio anterior sem confirmação. Confira o WhatsApp antes de reenviar.' WHERE id=?", (row['id'],))
                return
            response.raise_for_status()
            result = response.json()
            self.db.execute("UPDATE clips SET delivery='sent',sent_at=?,message_id=?,error=NULL WHERE id=?", (time.time(), result['message_id'], row['id']))
        except (httpx.TimeoutException, httpx.NetworkError, ValueError, KeyError):
            self.db.execute("UPDATE clips SET delivery='uncertain',error='Sem confirmação de envio. Confira o WhatsApp antes de reenviar.' WHERE id=?", (row['id'],))
        except httpx.HTTPStatusError as exc:
            # 503 is returned only before an upload starts; safe to retry.
            if exc.response.status_code == 503:
                delay = min(300, 15 * 2 ** min(row['attempts'], 4))
                self.db.execute("UPDATE clips SET delivery='retry',retry_at=?,error='WhatsApp indisponível. Nova tentativa automática.' WHERE id=?", (time.time() + delay, row['id']))
            else:
                self.db.execute("UPDATE clips SET delivery='failed',error='Falha de envio. Verifique o WhatsApp e tente novamente.' WHERE id=?", (row['id'],))

    def delivery_loop(self):
        with httpx.Client(timeout=90, headers=self.headers, trust_env=False) as client:
            while not self.stop_event.is_set():
                try:
                    self.deliver_one(client)
                except Exception:
                    log.exception('Falha na fila do WhatsApp')
                self.stop_event.wait(3)
