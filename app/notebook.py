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

# The screen is asked often only while it matters (someone in front of the camera, a call going on) and rarely otherwise:
# a recognised face reaches it within about half a second, and an empty house costs one request every few seconds.
FAST_INTERVAL = 0.5
SLOW_INTERVAL = 3
PHOTO_SYNC_SECONDS = 5
TOKEN = DATA / 'notebook.token'
PORT = 8765
KINDS = ('notebook_battery', 'notebook_unplugged', 'notebook_power_back', 'notebook_offline', 'notebook_online')
# An unanswered call is announced again this often; a help request keeps going longer.
REMINDER_SECONDS = 120
REMINDERS = {'call': 1, 'panic': 5}   # WhatsApp reminders, every REMINDER_SECONDS.
# Phones are nudged much more often while a call rings, until someone answers or this long has passed.
RING_SECONDS = 20
RING_LIMIT = {'call': 180, 'panic': 600}


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
        self.ring_state = None  # The call currently being re-announced: {'id', 'kind', 'since', 'last'}.
        self.read = None  # Called with message ids the person confirmed on the screen.
        self.confirmed = []  # Acks already stored: tell the screen it can forget them.
        self.busy = None  # Callable: True while the screen needs quick updates.
        self.last_photo_sync = 0
        self.delivered = None  # Called with message ids once the screen accepted them.
        self.callee_phone = None  # Callable: person id -> WhatsApp number of someone with a call button.
        self.avatars = None  # Callable returning [(user id, picture path or None, revision)] for the screen's call buttons.
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

    def send_test(self, sound, volume, text='', voice=''):
        """Ask the kitchen screen to play one sound (or show a sample message) now."""
        url, token = notebook_url(self.config.get().camera_source), self.token()
        if not (url and token):
            raise RuntimeError('A tela do notebook não está configurada.')
        try:
            response = httpx.post(f'{url}/test', headers={'Authorization': f'Bearer {token}'}, json={'sound': sound, 'volume': volume, 'text': text, 'voice': voice}, timeout=5)
        except httpx.HTTPError:
            raise RuntimeError('A tela do notebook não respondeu. Confira se ele está ligado.')
        if response.status_code != 200:
            raise RuntimeError('A tela do notebook recusou o teste. Atualize o programa do notebook.')

    # Polling -----------------------------------------------------------------

    def poll(self, client, now=None):
        now = now or time.time()
        self.last_poll = now
        settings = self.config.get()
        if not (settings.notebook_alerts_enabled or settings.notebook_call_enabled):
            self.reset()
            return
        reading, deliver = None, []
        token = self.token()
        url = notebook_url(settings.camera_source)
        if url and token:
            try:
                params = {'call': int(settings.notebook_call_enabled), 'panic': int(settings.notebook_call_enabled and settings.notebook_panic_enabled)}
                if self.vigia:
                    try:
                        params.update(self.vigia())
                        deliver = params.pop('_deliver', [])
                    except Exception:
                        log.exception('Falha ao montar o estado da tela do notebook')
                    params['frame'] = int(settings.notebook_photo_frame_enabled)
                if self.confirmed:
                    params['acked'] = ','.join(self.confirmed)
                response = client.get(f'{url}/status', headers={'Authorization': f'Bearer {token}'}, timeout=5, params=params)
                if response.status_code == 200:
                    reading = response.json()
                    self.confirmed = []
                    acks = [a for a in reading.get('acks', []) if isinstance(a, str)]
                    if acks and self.read:
                        self.read(acks)
                        self.confirmed = acks
                    if deliver and self.delivered:
                        self.delivered(deliver)
                    if now - self.last_photo_sync >= PHOTO_SYNC_SECONDS:
                        self.last_photo_sync = now
                        self.sync_photos(client, url, {'Authorization': f'Bearer {token}'}, settings)
                        self.sync_avatars(client, url, {'Authorization': f'Bearer {token}'}, settings)
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

    def sync_avatars(self, client, url, headers, settings):
        """Keep the screen's copies of the call buttons' pictures in step with the accounts (small files, only what changed)."""
        if self.avatars is None or not settings.notebook_call_enabled:
            return
        try:
            wanted = {i: (path, rev) for i, path, rev in self.avatars() if path}
            stored = client.get(f'{url}/avatars', headers=headers, timeout=5).json().get('revs', {})
            for user_id in set(stored) - set(wanted):
                client.delete(f'{url}/avatars/{user_id}', headers=headers, timeout=5)
            for user_id, (path, rev) in wanted.items():
                if stored.get(user_id) != rev:
                    client.put(f'{url}/avatars/{user_id}', content=path.read_bytes(), timeout=10, headers={**headers, 'Content-Type': 'image/jpeg', 'X-Rev': rev})
        except (httpx.HTTPError, ValueError, OSError):
            log.warning('Não foi possível sincronizar as fotos dos botões de chamada', exc_info=True)

    def reset(self):
        with self.lock:
            self.reading = self.last_ok = self.silent_since = self.battery_since = None
            self.call = {'state': 'idle'}
            self.silent_alerted = self.unplugged_alerted = False

    def interval(self):
        try:
            return FAST_INTERVAL if self.busy and self.busy() else SLOW_INTERVAL
        except Exception:
            return SLOW_INTERVAL

    def due(self, now=None):
        return (now or time.time()) - self.last_poll >= self.interval()

    def run(self, stop_event):
        """Own thread: polls the screen at the adaptive rate (the delivery loop only ticks once a second)."""
        with httpx.Client(timeout=10, trust_env=False) as client:
            while not stop_event.is_set():
                try:
                    if self.due():
                        self.poll(client)
                except Exception:
                    log.exception('Falha na consulta à tela do notebook')
                stop_event.wait(0.1)

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
            self.finish_ring(call, now)
            return
        kind, since = call['kind'], call['since']
        to_name = call.get('to_name') or ''
        if not self.alerts.exists(f'{kind}-{call["id"]}'):
            jpeg = self.frame() if self.frame else None
            phone = self.callee_phone(call.get('to')) if call.get('to') and self.callee_phone else None
            self.alerts.notebook_call(call['id'], kind, jpeg, since, now, to_name=to_name, skip=phone)
            if phone:   # The person asked for by name also gets a WhatsApp message of their own.
                self.alerts.call_to_person(call['id'], since, phone, now)
        for number in range(1, min(int((now - since) // REMINDER_SECONDS), REMINDERS[kind]) + 1):
            self.alerts.notebook_call(call['id'], kind, None, since, now, reminder=number, to_name=to_name)
        # Push again every few seconds, like a phone that keeps ringing (the first alert above counts as the first ring).
        state = self.ring_state
        if state is None or state['id'] != call['id']:
            state = self.ring_state = {'id': call['id'], 'kind': kind, 'since': since, 'last': now}
        if now - since <= RING_LIMIT[kind] and now - state['last'] >= RING_SECONDS:
            state['last'] = now
            self.alerts.ring(call['id'], kind, since, now, to_name=to_name)

    def finish_ring(self, call, now):
        """The call stopped ringing: say how it ended, replacing the notification that kept nudging the phones."""
        state, self.ring_state = self.ring_state, None
        if state is None:
            return
        if call.get('id') == state['id'] and call.get('state') == 'answered':
            self.alerts.ring_notice(state['id'], state['kind'], f"✅ {call.get('answered_by') or 'Alguém'} atendeu a chamada do seu pai.", now)
        elif call.get('id') == state['id'] and call.get('state') in ('ended', 'missed'):
            self.alerts.ring_notice(state['id'], state['kind'], 'A chamada do notebook da cozinha terminou.', now)

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
