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
CONTACT = 'mailto:casa-presente@localhost'
TITLES = {'fall': 'Possível queda', 'routine': 'Fora da rotina', 'inactivity': 'Ninguém apareceu',
          'camera_offline': 'Câmera sem imagem', 'camera_online': 'Câmera voltou', 'summary': 'Resumo do dia',
          'backup': 'Backup falhou', 'test': 'Teste de notificação', 'presence': 'Presença detectada'}
URGENT = {'fall', 'routine', 'inactivity'}
# Delivered right away even with the phone asleep (high push priority), without the urgent alert style.
IMMEDIATE = URGENT | {'presence'}
# A person walking in and out restarts the record; one notification per camera in this window is enough.
PRESENCE_COOLDOWN = 60
# Presence photos live next to the alert photos (served, behind login, by /alert-media/) for a day.
PHOTOS = DATA / 'alerts'
PHOTO_DAYS = 1
PHOTOS.mkdir(exist_ok=True)


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

    def set_presence(self, endpoint, enabled):
        with self.db.connect() as db:
            changed = db.execute('UPDATE push_subscriptions SET presence=? WHERE endpoint=?', (int(enabled), endpoint)).rowcount
        if not changed:
            raise KeyError('Ative as notificações neste aparelho primeiro.')

    def presence_enabled(self, endpoint):
        rows = self.db.rows('SELECT presence FROM push_subscriptions WHERE endpoint=?', (endpoint,))
        return bool(rows and rows[0]['presence'])

    def presence(self, camera_id, camera_name, now=None):
        """Camera listener: someone appeared, so devices that opted in can open the live view."""
        now = now or time.time()
        with self.lock:
            if now - self.last_presence.get(camera_id, 0) < PRESENCE_COOLDOWN:
                return False
            self.last_presence[camera_id] = now
        self.notify({'id': f'presence-{camera_id}', 'kind': 'presence', 'camera_id': camera_id,
                     'photo': self.save_photo(camera_id, now),
                     'message': f'Alguém apareceu na câmera {camera_name} às {datetime.fromtimestamp(now, TZ):%H:%M}. Toque para ver ao vivo.'})
        return True

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

    def send_all(self, alert):
        camera = alert.get('camera_id')
        # Fall alerts keep their photo in data/alerts/<id>.jpg; presence passes its own.
        photo = alert.get('photo') or (f'/alert-media/{alert["id"]}.jpg' if alert.get('image') else None)
        payload = json.dumps({'title': TITLES.get(alert['kind'], 'Casa Presente'), 'body': alert['message'],
                              'tag': alert['id'], 'urgent': alert['kind'] in URGENT, 'image': photo,
                              # Alerts tied to a camera get "Ver ao vivo" and "Conversar" buttons.
                              'camera': camera,
                              'url': f'/?camera={quote(camera)}#overview' if camera else '/#overview'}, ensure_ascii=False)
        only = ' WHERE presence=1' if alert['kind'] == 'presence' else ''
        sent = 0
        for row in self.db.rows('SELECT endpoint,keys FROM push_subscriptions' + only):
            if self.send(row['endpoint'], json.loads(row['keys']), payload, urgent=alert['kind'] in IMMEDIATE):
                sent += 1
        return sent

    def send(self, endpoint, keys, payload, urgent=False):
        send = self.sender
        if send is None:
            from pywebpush import webpush
            send = webpush
        try:
            send(subscription_info={'endpoint': endpoint, 'keys': keys}, data=payload,
                 vapid_private_key=self.vapid, vapid_claims={'sub': CONTACT}, ttl=3600,
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
