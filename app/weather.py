"""Weather forecast for the kitchen screen, from Open-Meteo (free, no account or key).

Only the chosen city's coordinates leave the house, and only when the feature is switched on. The server
fetches the forecast every 20 minutes and hands the result to the screen, which therefore needs no internet.
"""
import logging
import threading
import time

import httpx

log = logging.getLogger(__name__)
GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST = 'https://api.open-meteo.com/v1/forecast'
REFRESH_SECONDS = 20 * 60
STALE_SECONDS = 3 * 3600

# WMO weather codes -> (description in Portuguese, icon the screen draws)
CONDITIONS = {0: ('Céu limpo', 'sun'), 1: ('Predomínio de sol', 'sun'), 2: ('Parcialmente nublado', 'partly'), 3: ('Nublado', 'cloud'),
              45: ('Neblina', 'fog'), 48: ('Neblina', 'fog'),
              51: ('Garoa fraca', 'rain'), 53: ('Garoa', 'rain'), 55: ('Garoa forte', 'rain'), 56: ('Garoa gelada', 'rain'), 57: ('Garoa gelada', 'rain'),
              61: ('Chuva fraca', 'rain'), 63: ('Chuva', 'rain'), 65: ('Chuva forte', 'rain'), 66: ('Chuva gelada', 'rain'), 67: ('Chuva gelada', 'rain'),
              71: ('Neve fraca', 'snow'), 73: ('Neve', 'snow'), 75: ('Neve forte', 'snow'), 77: ('Grãos de neve', 'snow'),
              80: ('Pancadas de chuva', 'rain'), 81: ('Pancadas de chuva', 'rain'), 82: ('Pancadas fortes', 'rain'), 85: ('Pancadas de neve', 'snow'), 86: ('Pancadas de neve', 'snow'),
              95: ('Trovoadas', 'storm'), 96: ('Trovoadas com granizo', 'storm'), 99: ('Trovoadas com granizo', 'storm')}
WEEKDAYS = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')


def condition(code):
    return CONDITIONS.get(code, ('Tempo instável', 'cloud'))


def search(query, client=None):
    """Cities matching the text: [{'name', 'region', 'country', 'lat', 'lon'}]."""
    query = ' '.join(str(query).split())[:60]
    if len(query) < 2:
        return []
    owner = client or httpx.Client(timeout=8)
    try:
        data = owner.get(GEOCODE, params={'name': query, 'count': 6, 'language': 'pt', 'format': 'json'}).json()
    finally:
        if client is None:
            owner.close()
    return [{'name': r.get('name', ''), 'region': r.get('admin1', ''), 'country': r.get('country', ''), 'lat': r['latitude'], 'lon': r['longitude']}
            for r in data.get('results', []) if isinstance(r.get('latitude'), (int, float)) and isinstance(r.get('longitude'), (int, float))]


def fetch(lat, lon, now=None, client=None):
    """Current conditions plus today and the next two days, ready for the screen."""
    owner = client or httpx.Client(timeout=10)
    try:
        data = owner.get(FORECAST, params={
            'latitude': round(lat, 4), 'longitude': round(lon, 4), 'timezone': 'auto', 'forecast_days': 4,
            'current': 'temperature_2m,weather_code', 'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'}).json()
    finally:
        if client is None:
            owner.close()
    current, daily = data['current'], data['daily']
    days = []
    for i, date in enumerate(daily['time'][:4]):
        year, month, day = (int(p) for p in date.split('-'))
        from datetime import date as Date
        days.append({'d': 'Hoje' if i == 0 else WEEKDAYS[Date(year, month, day).weekday()], 'c': daily['weather_code'][i], 'icon': condition(daily['weather_code'][i])[1],
                     'hi': round(daily['temperature_2m_max'][i]), 'lo': round(daily['temperature_2m_min'][i]),
                     'rain': int(daily['precipitation_probability_max'][i] or 0)})
    description, icon = condition(current['weather_code'])
    return {'t': round(current['temperature_2m']), 'c': current['weather_code'], 'text': description, 'icon': icon, 'days': days, 'at': now or time.time()}


class Weather:
    """Keeps the latest forecast for the configured city, refreshed in the background."""

    def __init__(self, config):
        self.config = config
        self.data, self.key = None, None
        self.error = ''
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    @staticmethod
    def settings_key(settings):
        if not (settings.kiosk_weather_enabled and settings.kiosk_weather_city):
            return None
        return (round(settings.kiosk_weather_lat, 4), round(settings.kiosk_weather_lon, 4))

    def refresh(self):
        key = self.settings_key(self.config.get())
        if key is None:
            self.data, self.key, self.error = None, None, ''
            return
        try:
            self.data, self.key, self.error = fetch(*key), key, ''
        except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError) as exc:
            self.error = f'{type(exc).__name__}'
            log.warning('Não foi possível obter a previsão do tempo (%s)', self.error)

    def current(self, settings=None):
        """The forecast for the configured city, or None (off, not fetched yet, or too old)."""
        settings = settings or self.config.get()
        if self.settings_key(settings) != self.key or not self.data or time.time() - self.data['at'] > STALE_SECONDS:
            return None
        return self.data

    def poke(self):
        """Settings changed: refresh soon instead of waiting for the next round."""
        self.wake.set()

    def _run(self):
        last = 0
        while not self.stop_event.is_set():
            key = self.settings_key(self.config.get())
            if key != self.key or (key is not None and time.time() - last >= REFRESH_SECONDS):
                self.refresh()
                last = time.time()
            self.wake.wait(3)
            self.wake.clear()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='weather')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
