"""Kitchen notebook watch: low battery, mains unplugged for too long, or no signal at all.

The notebook runs notebook/monitor.py; this side asks it for a reading every POLL_INTERVAL
seconds and raises alerts (WhatsApp and push) through Alerts. The notebook powers the camera
and the intercom, so losing it silently means losing the house view.
"""
import logging
import os
import threading
import time
from urllib.parse import urlsplit

import httpx

from .alerts import clock, elapsed
from .config import DATA, config as default_config

log = logging.getLogger(__name__)

POLL_INTERVAL = 30
TOKEN = DATA / 'notebook.token'
PORT = 8765
KINDS = ('notebook_battery', 'notebook_unplugged', 'notebook_power_back', 'notebook_offline', 'notebook_online')


def notebook_url(camera_source):
    """The notebook is the machine that serves the camera, unless NOTEBOOK_URL says otherwise."""
    explicit = os.environ.get('NOTEBOOK_URL')
    if explicit:
        return explicit.rstrip('/')
    host = urlsplit(camera_source).hostname
    return f'http://{host}:{PORT}' if host else ''


def notebook_token():
    try:
        return TOKEN.read_text().strip()
    except OSError:
        return ''


class NotebookMonitor:
    def __init__(self, alerts, config=default_config, token=notebook_token):
        self.alerts, self.config, self.token = alerts, config, token
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
        if not settings.notebook_alerts_enabled:
            self.reset()
            return
        reading = None
        token = self.token()
        url = notebook_url(settings.camera_source)
        if url and token:
            try:
                response = client.get(f'{url}/status', headers={'Authorization': f'Bearer {token}'}, timeout=5)
                if response.status_code == 200:
                    reading = response.json()
            except (httpx.HTTPError, ValueError):
                pass
        self.check(settings, reading, now)

    def reset(self):
        with self.lock:
            self.reading = self.last_ok = self.silent_since = self.battery_since = None
            self.silent_alerted = self.unplugged_alerted = False

    def due(self, now=None):
        return (now or time.time()) - self.last_poll >= POLL_INTERVAL

    # Rules -------------------------------------------------------------------

    def check(self, settings, reading, now):
        with self.lock:
            if reading is None:
                self.check_silence(settings, now)
                return
            self.last_ok, self.reading = now, reading
            if self.silent_since is not None:
                if self.silent_alerted:
                    self.alerts.raise_alert(f'notebook-online-{int(self.silent_since)}', 'notebook_online',
                                            f'✅ O notebook da câmera voltou a responder após {elapsed(now - self.silent_since)} sem sinal.', now)
                self.silent_since, self.silent_alerted = None, False
            if reading.get('plugged', True):
                self.check_power_back(now)
            else:
                self.check_unplugged(settings, reading, now)

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

    # Status ------------------------------------------------------------------

    def status(self, now=None):
        now = now or time.time()
        settings = self.config.get()
        with self.lock:
            reading = self.reading
            state = ('disabled' if not settings.notebook_alerts_enabled else 'unknown' if self.last_ok is None and self.silent_since is None
                     else 'offline' if self.silent_since is not None else 'battery' if self.battery_since is not None else 'ok')
            return {'enabled': settings.notebook_alerts_enabled, 'state': state,
                    'battery': reading and reading.get('battery'), 'plugged': reading and reading.get('plugged'),
                    'status': reading and reading.get('status'), 'host': reading and reading.get('host'),
                    'last_ok': self.last_ok, 'silent_since': self.silent_since, 'battery_since': self.battery_since,
                    'now': now}
