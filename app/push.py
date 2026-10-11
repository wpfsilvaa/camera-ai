"""Web Push notifications to the installed dashboard (PWA), independent of WhatsApp.

Keys (VAPID) are created once and stay in data/. Each signed-in device subscribes on its own;
browsers deliver through their push service (Google, Mozilla, Apple) with end-to-end
encrypted payloads. A subscription the push service reports as gone is removed.
"""
import base64
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

from .config import DATA
from .db import TZ

log = logging.getLogger(__name__)

KEYS = DATA / 'vapid.json'
# Apple rejects VAPID contacts on made-up hosts such as @localhost (403 BadJwtToken).
CONTACT = 'mailto:casa-presente@example.com'
TITLES = {'fall': 'Possível queda', 'routine': 'Fora da rotina', 'inactivity': 'Ninguém apareceu',
          'camera_offline': 'Câmera sem imagem', 'camera_online': 'Câmera voltou', 'summary': 'Resumo do dia',
          'backup': 'Backup falhou', 'test': 'Teste de notificação', 'presence': 'Presença detectada',
          'restricted': 'Área restrita', 'notebook_battery': 'Bateria do notebook baixa',
          'notebook_unplugged': 'Notebook sem energia', 'notebook_power_back': 'Energia do notebook voltou',
          'notebook_offline': 'Notebook sem sinal', 'call': 'Chamada do notebook', 'panic': 'Pedido de ajuda', 'notebook_online': 'Notebook voltou'}
URGENT = {'fall', 'routine', 'inactivity', 'call', 'panic'}
# Delivered right away even with the phone asleep (high push priority), without the urgent alert style.
IMMEDIATE = URGENT | {'presence', 'restricted', 'notebook_battery', 'notebook_unplugged', 'notebook_offline'}
# A person walking in and out restarts the record; one notification per camera in this window is enough.
PRESENCE_COOLDOWN = 60
# Presence photos live next to the alert photos (served, behind login, by /alert-media/) for a day.
PHOTOS = DATA / 'alerts'
PHOTO_DAYS = 1
PHOTOS.mkdir(exist_ok=True)
# Per device: who triggers a presence notice. "father" and "unknown" wait for face recognition.
AUDIENCES = ('all', 'father', 'unknown')
IDENTIFY_SECONDS = 15
# What a device can switch off, in the order shown. Each topic covers some alert kinds; the test is always sent.
TOPICS = {'emergency': ('Quedas, ausência e chamadas do notebook', {'fall', 'routine', 'inactivity', 'call', 'panic'}),
          'restricted': ('Área restrita', {'restricted'}),
          'camera': ('Câmera sem imagem ou de volta', {'camera_offline', 'camera_online'}),
          'notebook': ('Notebook da câmera (bateria, energia, sinal)', {'notebook_battery', 'notebook_unplugged', 'notebook_power_back', 'notebook_offline', 'notebook_online'}),
          'summary': ('Resumo do dia', {'summary'}),
          'backup': ('Falha no backup', {'backup'})}
FATHER = 'father'  # Fixed id of the father's profile.


def clock(timestamp):
    return f'{datetime.fromtimestamp(timestamp, TZ):%H:%M}'


def load_keys():
    """(private key PEM, public key for the browser) — generated on first use."""
    try:
        keys = json.loads(KEYS.read_text())
    except (OSError, ValueError):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        private = ec.generate_private_key(ec.SECP256R1())
        point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        keys = {'private': private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()).decode(),
                'public': base64.urlsafe_b64encode(point).rstrip(b'=').decode()}
        KEYS.write_text(json.dumps(keys))
        KEYS.chmod(0o600)
    return keys['private'], keys['public']


class Push:
    def __init__(self, db, sender=None):
        self.db = db
        private, self.public_key = load_keys()
        from py_vapid import Vapid
        self.vapid = Vapid.from_pem(private.encode())
        self.sender = sender  # Injected in tests; pywebpush otherwise.
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='push')
        self.lock = threading.Lock()
        self.last_presence = {}
        self.frame = None  # Set by the application: camera_id -> latest JPEG (with boxes and names) or None.
        self.people = None  # camera_id -> visible tracks [{'id', 'person_id', 'name'}], for the presence filter.
        self.quiet = None  # now -> True during the configured quiet hours.
        # Seams for tests: where the identity watch runs and how it waits.
        self.spawn = lambda fn: threading.Thread(target=fn, name='push-presence', daemon=True).start()
        self.sleep, self.clock = time.sleep, time.time

    def subscribe(self, user_id, subscription, agent=''):
        endpoint = subscription.get('endpoint', '')
        keys = subscription.get('keys') or {}
        if not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):
            raise ValueError('Inscrição de notificação inválida.')
        self.db.execute('''INSERT INTO push_subscriptions(endpoint,user_id,keys,agent,created) VALUES(?,?,?,?,?)
            ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,keys=excluded.keys,agent=excluded.agent''',
                        (endpoint, user_id, json.dumps(keys), agent[:200], time.time()))

    def unsubscribe(self, endpoint):
        self.db.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (endpoint,))

    def set_presence(self, endpoint, enabled, audience='all', quiet=False):
        if audience not in AUDIENCES:
            raise ValueError('Escolha quem deve gerar o aviso de presença.')
        with self.db.connect() as db:
            changed = db.execute('UPDATE push_subscriptions SET presence=?,presence_filter=?,presence_quiet=? WHERE endpoint=?',
                                 (int(enabled), audience, int(quiet), endpoint)).rowcount
        if not changed:
            raise KeyError('Ative as notificações neste aparelho primeiro.')

    def presence_settings(self, endpoint):
        rows = self.db.rows('SELECT presence,presence_filter,presence_quiet FROM push_subscriptions WHERE endpoint=?', (endpoint,))
        if not rows:
            return {'enabled': False, 'audience': 'all', 'quiet': False}
        return {'enabled': bool(rows[0]['presence']), 'audience': rows[0]['presence_filter'], 'quiet': bool(rows[0]['presence_quiet'])}

    def topic_settings(self, endpoint):
        rows = self.db.rows('SELECT muted FROM push_subscriptions WHERE endpoint=?', (endpoint,))
        muted = set(json.loads(rows[0]['muted'])) if rows else set()
        return {'topics': [{'id': key, 'label': label, 'enabled': key not in muted} for key, (label, _) in TOPICS.items()]}

    def set_topics(self, endpoint, enabled):
        unknown = set(enabled) - set(TOPICS)
        if unknown:
            raise ValueError('Tipo de notificação desconhecido.')
        muted = [key for key in TOPICS if key not in enabled]
        with self.db.connect() as db:
            changed = db.execute('UPDATE push_subscriptions SET muted=? WHERE endpoint=?', (json.dumps(muted), endpoint)).rowcount
        if not changed:
            raise KeyError('Ative as notificações neste aparelho primeiro.')

    def presence_devices(self, audience, now):
        """Devices that want this kind of presence notice now (quiet hours honored per device)."""
        rows = self.db.rows('SELECT endpoint,keys,presence_quiet FROM push_subscriptions WHERE presence=1 AND presence_filter=?', (audience,))
        quiet = bool(self.quiet and self.quiet(now))
        return [row for row in rows if not (quiet and row['presence_quiet'])]

    def presence(self, camera_id, camera_name, now=None):
        """Camera listener: someone appeared, so devices that opted in can open the live view.

        "all" devices hear right away. Recognition needs a few seconds, so devices that only want
        the father, or only people not recognized, hear after watching the camera for a while.
        """
        now = now or time.time()
        with self.lock:
            if now - self.last_presence.get(camera_id, 0) < PRESENCE_COOLDOWN:
                return False
            self.last_presence[camera_id] = now
        if self.presence_devices('all', now):
            self.notify(self.presence_alert(camera_id, now, 'all',
                                            f'Alguém apareceu na câmera {camera_name} às {clock(now)}. Toque para ver ao vivo.'))
        if self.people and (self.presence_devices('father', now) or self.presence_devices('unknown', now)):
            self.spawn(lambda: self.watch_identity(camera_id, camera_name, now))
        return True

    def presence_alert(self, camera_id, now, audience, message):
        return {'id': f'presence-{camera_id}', 'kind': 'presence', 'camera_id': camera_id, 'created': now,
                'audience': audience, 'photo': self.save_photo(camera_id, now), 'message': message}

    def watch_identity(self, camera_id, camera_name, started):
        """Follow the camera's tracks for IDENTIFY_SECONDS and tell "father" and "unknown" devices."""
        seen, recognized, father_told = set(), set(), False
        deadline = started + IDENTIFY_SECONDS
        while True:
            now = self.clock()
            try:
                tracks = self.people(camera_id) or []
            except KeyError:  # Camera removed meanwhile.
                tracks = []
            for track in tracks:
                seen.add(track['id'])
                if track.get('person_id'):
                    recognized.add(track['id'])
                if track.get('person_id') == FATHER and not father_told:
                    father_told = True
                    self.notify(self.presence_alert(camera_id, now, 'father',
                                                    f'{track.get("name") or "Seu pai"} apareceu na câmera {camera_name} às {clock(now)}.'))
            if now >= deadline:
                break
            self.sleep(1)
        if seen - recognized:
            self.notify(self.presence_alert(camera_id, now, 'unknown',
                                            f'Pessoa não reconhecida na câmera {camera_name} às {clock(started)}. Toque para ver ao vivo.'))

    def save_photo(self, camera_id, now):
        """Keep the current camera image for the notification; returns its URL or None."""
        jpeg = self.frame(camera_id) if self.frame else None
        if not jpeg:
            return None
        for old in PHOTOS.glob('presence-*.jpg'):
            if old.stat().st_mtime < now - PHOTO_DAYS * 86400:
                old.unlink(missing_ok=True)
        name = f'presence-{camera_id}-{int(now)}.jpg'
        (PHOTOS / name).write_bytes(jpeg)
        return f'/alert-media/{name}'

    def devices(self, user_id):
        return self.db.rows('SELECT endpoint,agent,created,last_ok FROM push_subscriptions WHERE user_id IS ? ORDER BY created', (user_id,))

    def notify(self, alert):
        """Alert listener: send in the background so the camera loop never waits on the network."""
        self.pool.submit(self.send_all, alert)

    def ring(self, alert):
        """Same as notify, for the repeated nudges of a call that is still ringing."""
        self.pool.submit(self.send_all, alert)

    def send_all(self, alert):
        camera = alert.get('camera_id')
        # Fall alerts keep their photo in data/alerts/<id>.jpg; presence passes its own.
        photo = alert.get('photo') or (f'/alert-media/{alert["id"]}.jpg' if alert.get('image') else None)
        calm = bool(alert.get('notice'))   # "answered" / "ended": replaces the ringing notification without ringing
        payload = json.dumps({'title': alert.get('title') or TITLES.get(alert['kind'], 'Casa Presente'), 'body': alert['message'],
                              'tag': alert['id'], 'urgent': alert['kind'] in URGENT and not calm, 'ring': bool(alert.get('ring')), 'image': photo,
                              # Alerts tied to a camera get "Ver ao vivo" and "Conversar" buttons.
                              'camera': camera,
                              'url': f'/?camera={quote(camera)}#overview' if camera else '/?answer=1#overview' if alert['kind'] in ('call', 'panic') else '/#overview'}, ensure_ascii=False)
        if alert['kind'] == 'presence':
            rows = self.presence_devices(alert.get('audience', 'all'), alert.get('created') or time.time())
        else:
            kind = alert['kind']
            rows = [row for row in self.db.rows('SELECT endpoint,keys,muted FROM push_subscriptions')
                    if not any(kind in kinds and key in json.loads(row['muted']) for key, (_, kinds) in TOPICS.items())]
        sent = 0
        for row in rows:
            if self.send(row['endpoint'], json.loads(row['keys']), payload, urgent=alert['kind'] in IMMEDIATE, ttl=90 if alert.get('ring') or calm else 3600):
                sent += 1
        return sent

    def send(self, endpoint, keys, payload, urgent=False, ttl=3600):
        send = self.sender
        if send is None:
            from pywebpush import webpush
            send = webpush
        try:
            send(subscription_info={'endpoint': endpoint, 'keys': keys}, data=payload,
                 vapid_private_key=self.vapid, vapid_claims={'sub': CONTACT}, ttl=ttl,
                 headers={'Urgency': 'high' if urgent else 'normal'}, timeout=10)
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status in (404, 410):
                self.unsubscribe(endpoint)  # The browser dropped this subscription.
            else:
                log.warning('Notificação não entregue (%s): %s', status or type(exc).__name__, endpoint[:60])
            return False
        self.db.execute('UPDATE push_subscriptions SET last_ok=? WHERE endpoint=?', (time.time(), endpoint))
        return True
