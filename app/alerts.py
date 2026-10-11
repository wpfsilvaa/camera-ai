"""WhatsApp text alerts: nobody seen for hours, a camera without image, the daily summary."""
import logging
import os
import time
from datetime import datetime

import httpx

from .config import DATA, WA_URL
from .db import TZ
from .routine import DAY_STARTS, FIRST_MARGIN as ROUTINE_MARGIN, Routine, clock_text

log = logging.getLogger(__name__)

CHECK_INTERVAL = 30
# An alert that could not go out within this time no longer describes the present.
STALE_SECONDS = 6 * 3600
RETENTION_DAYS = 90
IMAGES = DATA / 'alerts'
IMAGES.mkdir(exist_ok=True)


def clock(timestamp):
    return datetime.fromtimestamp(timestamp, TZ).strftime('%H:%M')


def elapsed(seconds):
    hours, minutes = divmod(int(seconds // 60), 60)
    return f'{hours} h {minutes:02d} min' if hours else f'{minutes} min'


def watching(snapshots):
    # Without a working, analyzing camera, silence says nothing about the house.
    return any(c['enabled'] and c['analysis_enabled'] and c['state'] == 'online' for c in snapshots)


def in_quiet_hours(hour, start, end):
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end


class Alerts:
    def __init__(self, db, config, cameras, routine=None):
        self.db, self.config, self.cameras = db, config, cameras
        self.routine = routine or Routine(db)
        self.offline_since = {}  # camera id -> first moment seen without image
        self.last_check = 0
        self.listeners = []  # Called with each new alert (e.g. push notifications).
        self.ringers = []    # Called again while a call from the kitchen screen is still unanswered (push only).

    # Detection ---------------------------------------------------------------

    def check(self, now=None):
        now = now or time.time()
        self.last_check = now
        settings = self.config.get()
        if not settings.alerts_enabled:
            self.offline_since.clear()
            return
        snapshots = self.cameras.snapshots()
        self.check_cameras(settings, snapshots, now)
        if watching(snapshots):
            self.check_routine(settings, now)
            self.check_inactivity(settings, now)
        self.check_summary(settings, now)

    def check_cameras(self, settings, snapshots, now):
        limit = settings.camera_offline_minutes * 60
        for camera in snapshots:
            key = camera['id']
            if not camera['enabled']:
                self.offline_since.pop(key, None)  # Paused on purpose: nothing to report.
            elif camera['state'] == 'online':
                since = self.offline_since.pop(key, None)
                if since is not None and self.exists(f'offline-{key}-{int(since)}'):
                    self.raise_alert(f'online-{key}-{int(since)}', 'camera_online',
                                     f'✅ A câmera {camera["name"]} voltou a transmitir após {elapsed(now - since)} sem imagem.', now)
            else:
                since = self.offline_since.setdefault(key, now)
                if limit and now - since >= limit:
                    self.raise_alert(f'offline-{key}-{int(since)}', 'camera_offline',
                                     f'⚠️ A câmera {camera["name"]} está sem imagem desde as {clock(since)}. '
                                     'Confira a energia, o Wi-Fi e o computador da câmera.', now)

    def check_routine(self, settings, now):
        """Morning check: he usually shows up by a certain time and has not yet today."""
        if not settings.routine_alerts_enabled:
            return
        local = datetime.fromtimestamp(now, TZ)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        expected = self.routine.expected_first(now)
        if expected is None or now - midnight < expected or self.seen_today(midnight):
            return
        usual = clock_text(expected - ROUTINE_MARGIN)
        self.raise_alert(f'routine-{local.date().isoformat()}', 'routine',
                         f'🔔 Hoje ainda ninguém apareceu nas câmeras. Normalmente ele aparece até as {usual}. '
                         'Vale ligar para confirmar que está tudo bem.', now)

    def seen_today(self, midnight):
        return bool(self.db.rows("SELECT 1 FROM events WHERE kind='presence' AND last_seen>=? LIMIT 1",
                                 (midnight + DAY_STARTS * 3600,)))

    def inactivity_limit(self, settings, now):
        """The configured hours, raised to his usual longest daytime gap once the routine is known."""
        summary = self.routine.summary(now)
        usual = summary['usual_gap_hours'] if summary['learned'] else None
        return max(settings.inactivity_hours, min(12, usual + .5)) if usual else settings.inactivity_hours

    def check_inactivity(self, settings, now):
        if not settings.inactivity_hours:
            return
        local = datetime.fromtimestamp(now, TZ)
        if in_quiet_hours(local.hour, settings.quiet_start_hour, settings.quiet_end_hour):
            return
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        # Before today's first appearance, the routine check speaks with a better reference.
        if settings.routine_alerts_enabled and self.routine.summary(now)['learned'] and not self.seen_today(midnight):
            return
        last = self.db.rows("SELECT MAX(last_seen) AS t FROM events WHERE kind='presence'")[0]['t']
        limit = self.inactivity_limit(settings, now)
        if last and now - last >= limit * 3600:
            self.raise_alert(f'inactive-{int(last)}', 'inactivity',
                             f'🔔 Ninguém apareceu nas câmeras desde as {clock(last)} (há {elapsed(now - last)}). '
                             'Vale ligar para confirmar que está tudo bem.', now)

    def check_summary(self, settings, now):
        local = datetime.fromtimestamp(now, TZ)
        if settings.daily_summary_hour < 0 or local.hour < settings.daily_summary_hour:
            return
        alert_id = f'summary-{local.date().isoformat()}'
        if self.exists(alert_id):
            return
        stats = self.db.stats(now=now)
        today = stats['today']
        last = f'às {clock(stats["last_presence"])}' if stats['last_presence'] else 'sem registros'
        lines = [f'📋 Resumo de hoje ({local.strftime("%d/%m")})',
                 f'• Registros de presença: {today["total"]}',
                 f'• Confirmados como seu pai: {today["father"]}',
                 f'• A identificar: {today["unknown"]}',
                 f'• Última presença: {last}',
                 f'• Tempo gravado: {elapsed(stats["recorded_seconds_today"])}']
        problems = self.db.rows("SELECT COUNT(*) AS n FROM alerts WHERE kind IN ('camera_offline','inactivity','routine','fall','notebook_battery','notebook_unplugged','notebook_offline','panic','intruder') AND created>=?",
                                (local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp(),))[0]['n']
        if problems:
            lines.append(f'• Alertas enviados hoje: {problems}')
        self.raise_alert(alert_id, 'summary', '\n'.join(lines), now)

    def fall(self, camera_id, camera_name, jpeg, seconds, now=None):
        """A person has been lying outside the ignored areas: alert right away, with the photo."""
        now = now or time.time()
        alert_id = f'fall-{camera_id}-{int(now)}'
        (IMAGES / f'{alert_id}.jpg').write_bytes(jpeg)
        return self.raise_alert(alert_id, 'fall',
                                f'🚨 Possível queda na câmera {camera_name}: uma pessoa está deitada fora da cama/sofá '
                                f'há {round(seconds)} s ({clock(now)}). Ligue ou peça para alguém verificar agora.',
                                now, image=True, camera_id=camera_id)

    def intruder(self, camera_id, camera_name, jpeg, now=None):
        """Street mode is on and an unknown person is in a guarded camera: alert right away, with the photo."""
        now = now or time.time()
        alert_id = f'intruder-{camera_id}-{int(now)}'
        (IMAGES / f'{alert_id}.jpg').write_bytes(jpeg)
        return self.raise_alert(alert_id, 'intruder',
                                f'🚨 Alguém entrou em casa? Uma pessoa desconhecida apareceu na câmera {camera_name} às {clock(now)} '
                                f'com o Modo rua ligado. Confira a foto e ligue para quem estiver por perto.',
                                now, image=True, camera_id=camera_id)

    def restricted(self, camera_id, camera_name, jpeg, name, now=None, whatsapp=True):
        """Someone watched entered a restricted area (the fridge, in restricted mode): alert with the photo."""
        now = now or time.time()
        alert_id = f'restricted-{camera_id}-{int(now)}'
        (IMAGES / f'{alert_id}.jpg').write_bytes(jpeg)
        return self.raise_alert(alert_id, 'restricted',
                                f'⚠️ {name or "Uma pessoa"} entrou na área restrita da câmera {camera_name} ({clock(now)}). '
                                f'O vídeo fica no histórico.', now, image=True, camera_id=camera_id, whatsapp=whatsapp)

    def notebook_call(self, call_id, kind, jpeg, since, now=None, reminder=0, to_name='', skip=None):
        """The kitchen notebook's button was pressed (kind "call" or "panic"): alert at once, then remind while nobody answers."""
        now = now or time.time()
        alert_id = f'{kind}-{call_id}' + (f'-r{reminder}' if reminder else '')
        if reminder and self.exists(alert_id):
            return alert_id
        image = bool(jpeg)
        if jpeg:
            (IMAGES / f'{alert_id}.jpg').write_bytes(jpeg)
        if kind == 'panic':
            text = f'🚨 PEDIDO DE AJUDA: seu pai apertou o botão de ajuda no notebook da cozinha às {clock(since)}.'
        else:
            text = (f'📞 Seu pai está chamando {to_name} pelo notebook da cozinha ({clock(since)}).' if to_name
                    else f'📞 Seu pai está chamando a família pelo notebook da cozinha ({clock(since)}).')
        if reminder:
            text = f'⏰ Ainda sem resposta há {elapsed(now - since)}. ' + text
        link = os.environ.get('PUBLIC_URL', '').rstrip('/')
        text += ' Abra o painel e toque em Atender.' if kind == 'call' else ' Ligue para ele agora ou abra o painel e toque em Atender.'
        if link:
            text += f'\n{link}'
        return self.raise_alert(alert_id, kind, text, now, image=image, skip=skip)

    def call_to_person(self, call_id, since, phone, now=None):
        """The father asked for this person by name: they get their own WhatsApp message (no push; the family got the general alert)."""
        now = now or time.time()
        link = os.environ.get('PUBLIC_URL', '').rstrip('/')
        text = f'📞 Seu pai está chamando você pelo notebook da cozinha ({clock(since)}). Ligue para ele agora.' + (f'\n{link}' if link else '')
        return self.raise_alert(f'call-{call_id}-to', 'call', text, now, recipients=[phone], notify=False)

    def ring(self, call_id, kind, since, now, to_name=''):
        """A call nobody answered yet: nudge the phones again (push only; WhatsApp keeps its own, slower reminders)."""
        waited = elapsed(now - since)
        text = (f'🚨 PEDIDO DE AJUDA sem resposta há {waited}. Ligue para ele agora ou toque em Atender.' if kind == 'panic'
                else f'📞 Seu pai continua chamando {to_name} há {waited}. Toque em Atender.' if to_name else f'📞 Seu pai continua chamando há {waited}. Toque em Atender.')
        self._ring({'id': f'{kind}-{call_id}', 'kind': kind, 'created': now, 'message': text, 'image': 0, 'ring': True})

    def ring_notice(self, call_id, kind, text, now=None):
        """Replaces the ringing notification (same tag) with a calm one once the call is over."""
        self._ring({'id': f'{kind}-{call_id}', 'kind': kind, 'created': now or time.time(), 'message': text, 'image': 0, 'notice': True,
                    'title': 'Chamada atendida' if text.startswith('✅') else 'Chamada encerrada'})

    def _ring(self, alert):
        for listener in self.ringers:
            try:
                listener(alert)
            except Exception:
                log.exception('Falha ao repetir o aviso da chamada')

    def send_test(self, now=None):
        now = now or time.time()
        return self.raise_alert(f'test-{int(now * 1000)}', 'test',
                                '🧪 Teste de alerta do Casa Presente. Se recebeu esta mensagem, os alertas estão funcionando.', now)

    # Storage -----------------------------------------------------------------

    def exists(self, alert_id):
        return bool(self.db.rows('SELECT 1 FROM alerts WHERE id=?', (alert_id,)))

    def raise_alert(self, alert_id, kind, message, now, image=False, camera_id=None, whatsapp=True, recipients=None, skip=None, notify=True):
        """Record an alert once per id and queue it for every WhatsApp recipient (or only notify the web app)."""
        if recipients is None:
            recipients = [phone for phone in self.config.get().delivery_targets() if phone != skip] if whatsapp else []
        with self.db.connect() as db:
            created = db.execute('INSERT OR IGNORE INTO alerts(id,kind,created,message,image) VALUES(?,?,?,?,?)',
                                 (alert_id, kind, now, message, int(image))).rowcount
            if created:
                db.executemany('INSERT INTO alert_deliveries(alert_id,recipient) VALUES(?,?)',
                               [(alert_id, phone) for phone in recipients])
        if created:
            log.info('Alerta %s registrado para %d destinatário(s)', alert_id, len(recipients))
            alert = {'id': alert_id, 'kind': kind, 'created': now, 'message': message, 'image': int(image), 'camera_id': camera_id}
            for listener in (self.listeners if notify else []):
                try:
                    listener(alert)
                except Exception:
                    log.exception('Falha ao avisar %s sobre o alerta', listener)
        return alert_id

    def recent(self, limit=10):
        alerts = self.db.rows('SELECT * FROM alerts ORDER BY created DESC LIMIT ?', (limit,))
        deliveries = self.db.rows('''SELECT * FROM alert_deliveries WHERE alert_id IN
            (SELECT id FROM alerts ORDER BY created DESC LIMIT ?) ORDER BY recipient''', (limit,))
        for alert in alerts:
            alert['deliveries'] = [d for d in deliveries if d['alert_id'] == alert['id']]
        return alerts

    def cleanup(self, now=None):
        cutoff = (now or time.time()) - RETENTION_DAYS * 86400
        for row in self.db.rows('SELECT id FROM alerts WHERE created<? AND image=1', (cutoff,)):
            (IMAGES / f'{row["id"]}.jpg').unlink(missing_ok=True)
        self.db.execute('DELETE FROM alerts WHERE created<?', (cutoff,))

    # Delivery ----------------------------------------------------------------

    def mark(self, row, state, error=None, retry_at=0, sent_at=None):
        self.db.execute('UPDATE alert_deliveries SET state=?,error=?,retry_at=?,sent_at=? WHERE alert_id=? AND recipient=?',
                        (state, error, retry_at, sent_at, row['alert_id'], row['recipient']))

    def deliver_one(self, client, now=None):
        now = now or time.time()
        rows = self.db.rows('''SELECT d.*,a.message,a.created,a.image FROM alert_deliveries d JOIN alerts a ON a.id=d.alert_id
            WHERE d.state IN ('pending','retry') AND d.retry_at<=? ORDER BY a.created LIMIT 1''', (now,))
        if not rows:
            return False
        row = rows[0]
        if now - row['created'] > STALE_SECONDS:
            self.mark(row, 'expired', 'Não foi possível enviar a tempo; o alerta ficou desatualizado.')
            return True
        if row['recipient'] not in self.config.get().delivery_targets():
            self.mark(row, 'cancelled')
            return True
        self.db.execute('UPDATE alert_deliveries SET state=?,attempts=attempts+1 WHERE alert_id=? AND recipient=?',
                        ('sending', row['alert_id'], row['recipient']))
        try:
            response = client.post(f'{WA_URL}/text', json={'alert_id': row['alert_id'], 'recipient': row['recipient'],
                                                              'text': row['message'], 'image': bool(row['image'])})
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code == 200:
            self.mark(row, 'sent', sent_at=now)
        elif response is not None and response.status_code == 422:
            self.mark(row, 'failed', 'Número não encontrado no WhatsApp.')
        elif response is not None and response.status_code == 409:
            self.mark(row, 'uncertain', 'Envio sem confirmação. Confira o WhatsApp.')
        else:
            delay = min(600, 30 * 2 ** min(row['attempts'], 4))
            self.mark(row, 'retry', 'WhatsApp indisponível. Nova tentativa automática.', now + delay)
        return True
