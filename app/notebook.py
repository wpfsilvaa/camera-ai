"""Kitchen notebook: watch (low battery, unplugged too long, no signal) and the "call the family" button.

The notebook runs notebook/monitor.py; this side asks it for a reading every POLL_INTERVAL
seconds and raises alerts (WhatsApp and push) through Alerts. The notebook powers the camera
and the intercom, so losing it silently means losing the house view.
"""
import logging
import os
import threading
import time
from urllib.parse import quote, urlsplit

import httpx

from .alerts import clock, elapsed
from .config import DATA, config as default_config
from .sources import local_device

log = logging.getLogger(__name__)

POLL_INTERVAL = 5
TOKEN = DATA / 'notebook.token'
PORT = 8765
KINDS = ('notebook_battery', 'notebook_unplugged', 'notebook_power_back', 'notebook_offline', 'notebook_online')
# An unanswered call is announced again this often; a help request keeps going longer.
REMINDER_SECONDS = 120
REMINDERS = {'call': 1, 'panic': 5}


def notebook_url(camera_source):
    """The notebook is the machine that serves the camera, unless NOTEBOOK_URL says otherwise."""
    explicit = os.environ.get('NOTEBOOK_URL')
    if explicit:
        return explicit.rstrip('/')
    # A USB camera is plugged into this very computer.
    host = '127.0.0.1' if local_device(camera_source) else urlsplit(camera_source).hostname
    return f'http://{host}:{PORT}' if host else ''


def notebook_token():
    try:
        return TOKEN.read_text().strip()
    except OSError:
        return ''


class NotebookMonitor:
    def __init__(self, alerts, config=default_config, token=notebook_token):
        self.alerts, self.config, self.token = alerts, config, token
        self.frame = None  # Callable returning the camera's current JPEG (attached to call alerts).
        self.photos = None  # Photos object whose files are copied to the screen's frame.
        self.vigia = None  # Callable returning extra query parameters for the kitchen screen (watch mode, night, greeting).
        self.call = {'state': 'idle'}
        self.lock = threading.Lock()
        self.last_poll = 0
        self.last_ok = None  # Last moment a reading arrived.
        self.reading = None
        self.silent_since = None  # First failed poll of the current outage.
        self.battery_since = None  # Moment the mains power went away.
        self.silent_alerted = False
        self.unplugged_alerted = False

    # Polling -----------------------------------------------------------------

    def poll(self, client, now=None):
        now = now or time.time()
        self.last_poll = now
        settings = self.config.get()
        if not (settings.notebook_alerts_enabled or settings.notebook_call_enabled):
            self.reset()
            return
        reading = None
        token = self.token()
        url = notebook_url(settings.camera_source)
        if url and token:
            try:
                params = {'call': int(settings.notebook_call_enabled), 'panic': int(settings.notebook_call_enabled and settings.notebook_panic_enabled)}
                if self.vigia:
                    try:
                        params.update(self.vigia())
                    except Exception:
                        log.exception('Falha ao montar o estado da tela do notebook')
                    params['frame'] = int(settings.notebook_photo_frame_enabled)
                response = client.get(f'{url}/status', headers={'Authorization': f'Bearer {token}'}, timeout=5, params=params)
                if response.status_code == 200:
                    reading = response.json()
                    self.sync_photos(client, url, {'Authorization': f'Bearer {token}'}, settings)
            except (httpx.HTTPError, ValueError):
                pass
        self.check(settings, reading, now)

    def sync_photos(self, client, url, headers, settings):
        """Make the screen's folder of photos match the family album (a couple of uploads per poll)."""
        if self.photos is None:
            return
        try:
            rows = self.photos.list() if settings.notebook_photo_frame_enabled else []
            wanted, authors = [r['id'] for r in rows], {r['id']: r['author'] for r in rows}
            listing = client.get(f'{url}/photos', headers=headers, timeout=5).json()
            have, shown = set(listing.get('ids', [])), listing.get('authors', {})
            for photo_id in have & set(wanted):
                if authors.get(photo_id, '') != shown.get(photo_id, ''):   # The sender renamed their account.
                    client.put(f'{url}/photos/{photo_id}/author', content=authors.get(photo_id, '').encode('utf-8'), headers=headers, timeout=5)
            for photo_id in have - set(wanted):
                client.delete(f'{url}/photos/{photo_id}', headers=headers, timeout=5)
            for photo_id in [i for i in wanted if i not in have][:2]:
                client.put(f'{url}/photos/{photo_id}', content=self.photos.path(photo_id).read_bytes(), timeout=20,
                           headers={**headers, 'Content-Type': 'image/jpeg', 'X-Photo-Author': quote(authors.get(photo_id, ''))})
        except (httpx.HTTPError, ValueError, OSError):
            log.warning('Não foi possível sincronizar as fotos com a tela do notebook', exc_info=True)

    def reset(self):
        with self.lock:
            self.reading = self.last_ok = self.silent_since = self.battery_since = None
            self.call = {'state': 'idle'}
            self.silent_alerted = self.unplugged_alerted = False

    def due(self, now=None):
        return (now or time.time()) - self.last_poll >= POLL_INTERVAL

    # Rules -------------------------------------------------------------------

    def check(self, settings, reading, now):
        with self.lock:
            if reading is None:
                self.call = {'state': 'idle'}
                if settings.notebook_alerts_enabled:
                    self.check_silence(settings, now)
                elif self.silent_since is None:
                    self.silent_since = now
                return
            self.last_ok, self.reading = now, reading
            self.call = reading.get('call') or {'state': 'idle'}
            if settings.notebook_call_enabled:
                self.check_call(settings, now)
            if self.silent_since is not None:
                if self.silent_alerted:
                    self.alerts.raise_alert(f'notebook-online-{int(self.silent_since)}', 'notebook_online',
                                            f'✅ O notebook da câmera voltou a responder após {elapsed(now - self.silent_since)} sem sinal.', now)
                self.silent_since, self.silent_alerted = None, False
            if not settings.notebook_alerts_enabled:
                return
            if reading.get('plugged', True):
                self.check_power_back(now)
            else:
                self.check_unplugged(settings, reading, now)

    def check_call(self, settings, now):
        call = self.call
        if call.get('state') != 'ringing':
            return
        kind, since = call['kind'], call['since']
        if not self.alerts.exists(f'{kind}-{call["id"]}'):
            jpeg = self.frame() if self.frame else None
            self.alerts.notebook_call(call['id'], kind, jpeg, since, now)
        for number in range(1, min(int((now - since) // REMINDER_SECONDS), REMINDERS[kind]) + 1):
            self.alerts.notebook_call(call['id'], kind, None, since, now, reminder=number)

    def check_silence(self, settings, now):
        if self.silent_since is None:
            self.silent_since = now
        limit = settings.notebook_offline_minutes * 60
        if limit and not self.silent_alerted and now - self.silent_since >= limit:
            self.silent_alerted = True
            self.alerts.raise_alert(f'notebook-offline-{int(self.silent_since)}', 'notebook_offline',
                                    f'⚠️ O notebook da câmera está sem sinal desde as {clock(self.silent_since)}. '
                                    'Ele pode ter desligado por falta de bateria ou perdido o Wi-Fi. Confira a energia.', now)

    def check_power_back(self, now):
        if self.battery_since is not None and self.unplugged_alerted:
            self.alerts.raise_alert(f'notebook-power-{int(self.battery_since)}', 'notebook_power_back',
                                    f'🔌 A energia do notebook da câmera voltou após {elapsed(now - self.battery_since)}.', now)
        self.battery_since, self.unplugged_alerted = None, False

    def check_unplugged(self, settings, reading, now):
        if self.battery_since is None:
            self.battery_since = now
        episode = int(self.battery_since)
        percent = reading.get('battery')
        if percent is not None and percent <= settings.notebook_battery_percent:
            # One per outage: the first low reading is the one worth waking someone for.
            self.unplugged_alerted = True
            self.alerts.raise_alert(f'notebook-battery-{episode}', 'notebook_battery',
                                    f'🪫 A bateria do notebook da câmera está em {percent}% e ele está sem energia na tomada. '
                                    'Ligue o carregador antes que a câmera pare.', now)
        limit = settings.notebook_unplugged_minutes * 60
        if limit and now - self.battery_since >= limit:
            self.unplugged_alerted = True
            suffix = f' Bateria em {percent}%.' if percent is not None else ''
            self.alerts.raise_alert(f'notebook-unplugged-{episode}', 'notebook_unplugged',
                                    f'🔌 O notebook da câmera está sem energia na tomada desde as {clock(self.battery_since)} '
                                    f'({elapsed(now - self.battery_since)}).{suffix} Reconecte o carregador.', now)

    # Answering ---------------------------------------------------------------

    def command(self, path, payload=None):
        """Tell the notebook agent (answer or end the call); returns its call state."""
        url, token = notebook_url(self.config.get().camera_source), self.token()
        if not (url and token):
            raise RuntimeError('O notebook não está configurado.')
        try:
            response = httpx.post(f'{url}/call/{path}', json=payload or {}, headers={'Authorization': f'Bearer {token}'}, timeout=5)
        except httpx.HTTPError:
            raise RuntimeError('O notebook não respondeu. Ele pode estar desligado ou sem Wi-Fi.')
        if response.status_code == 409:
            raise ValueError(response.json().get('error', 'Esta chamada já foi atendida ou terminou.'))
        if response.status_code != 200:
            raise RuntimeError('O notebook recusou o comando.')
        with self.lock:
            self.call = response.json()
        return self.call

    def answer(self, name):
        return self.command('answer', {'name': name})

    def end(self):
        return self.command('end')

    # Status ------------------------------------------------------------------

    def status(self, now=None):
        now = now or time.time()
        settings = self.config.get()
        with self.lock:
            reading = self.reading
            state = ('disabled' if not (settings.notebook_alerts_enabled or settings.notebook_call_enabled) else 'unknown' if self.last_ok is None and self.silent_since is None
                     else 'offline' if self.silent_since is not None else 'battery' if self.battery_since is not None else 'ok')
            return {'enabled': settings.notebook_alerts_enabled, 'call_enabled': settings.notebook_call_enabled, 'call': self.call, 'state': state,
                    'battery': reading and reading.get('battery'), 'plugged': reading and reading.get('plugged'),
                    'status': reading and reading.get('status'), 'host': reading and reading.get('host'),
                    'last_ok': self.last_ok, 'silent_since': self.silent_since, 'battery_since': self.battery_since,
                    'now': now}
