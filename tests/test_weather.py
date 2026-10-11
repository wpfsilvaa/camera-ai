import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name

from app import weather
from app.config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'notebook'))
import monitor

FORECAST = {'current': {'temperature_2m': 21.6, 'weather_code': 63},
            'daily': {'time': ['2026-10-10', '2026-10-11', '2026-10-12', '2026-10-13'], 'weather_code': [63, 95, 2, 0],
                      'temperature_2m_max': [24.2, 27.8, 29.1, 30.0], 'temperature_2m_min': [17.1, 18.9, 19.4, 20.2],
                      'precipitation_probability_max': [80, 95, None, 5]}}


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class WeatherTests(unittest.TestCase):
    def test_fetch_builds_what_the_screen_needs(self):
        seen = []

        def handler(request):
            seen.append(dict(request.url.params))
            return httpx.Response(200, json=FORECAST)

        data = weather.fetch(-22.90556, -47.06083, now=1000.0, client=client(handler))
        self.assertEqual((data['t'], data['text'], data['icon']), (22, 'Chuva', 'rain'))
        self.assertEqual([d['d'] for d in data['days']], ['Hoje', 'Dom', 'Seg', 'Ter'])      # 2026-10-10 is a Saturday.
        self.assertEqual((data['days'][0]['hi'], data['days'][0]['lo'], data['days'][0]['rain']), (24, 17, 80))
        self.assertEqual((data['days'][1]['icon'], data['days'][2]['rain']), ('storm', 0))   # A missing probability becomes 0.
        self.assertEqual(seen[0]['latitude'], '-22.9056')                                    # Coordinates are rounded: city-level only.

    def test_search_returns_cities_and_ignores_short_text(self):
        def handler(request):
            return httpx.Response(200, json={'results': [{'name': 'Campinas', 'admin1': 'São Paulo', 'country': 'Brasil', 'latitude': -22.9, 'longitude': -47.06}, {'name': 'Quebrada'}]})

        found = weather.search('Campinas', client=client(handler))
        self.assertEqual(found, [{'name': 'Campinas', 'region': 'São Paulo', 'country': 'Brasil', 'lat': -22.9, 'lon': -47.06}])
        self.assertEqual(weather.search('a'), [])

    def test_current_needs_the_feature_on_the_same_city_and_fresh_data(self):
        class Config:
            def __init__(self, settings):
                self.settings = settings

            def get(self):
                return self.settings

        on = Settings(kiosk_weather_enabled=True, kiosk_weather_city='Campinas', kiosk_weather_lat=-22.9, kiosk_weather_lon=-47.06)
        service = weather.Weather(Config(on))
        self.assertIsNone(service.current())                                   # Nothing fetched yet.
        service.data, service.key = {'t': 20, 'at': time.time()}, weather.Weather.settings_key(on)
        self.assertEqual(service.current()['t'], 20)
        service.config = Config(on.model_copy(update={'kiosk_weather_city': ''}))
        self.assertIsNone(service.current())                                   # City cleared.
        service.config = Config(on)
        service.data['at'] = time.time() - 4 * 3600
        self.assertIsNone(service.current())                                   # Too old: better nothing than a wrong forecast.
        self.assertIsNone(weather.Weather.settings_key(on.model_copy(update={'kiosk_weather_enabled': False})))

    def test_monitor_checks_every_field(self):
        good = {'t': 21.6, 'c': 63, 'text': 'Chuva', 'icon': 'rain', 'at': 1000, 'days': [{'d': 'Hoje', 'icon': 'rain', 'hi': 24, 'lo': 17, 'rain': 80}]}
        parsed = monitor.parse_weather(json.dumps(good))
        self.assertEqual((parsed['t'], parsed['icon'], parsed['days'][0]['rain']), (22, 'rain', 80))
        for bad in ('', 'not json', '[1]', json.dumps({**good, 'icon': 'tornado'}), json.dumps({**good, 't': 'hot'}), json.dumps({**good, 'at': None})):
            self.assertIsNone(monitor.parse_weather(bad))
        mixed = monitor.parse_weather(json.dumps({**good, 'days': [{'d': 'x', 'hi': 'a', 'lo': 1, 'rain': 1}, {'d': 'Dom', 'icon': 'x', 'hi': 1, 'lo': 0, 'rain': 500}]}))
        self.assertEqual([(d['d'], d['icon'], d['rain']) for d in mixed['days']], [('Dom', 'cloud', 100)])

    def test_the_forecast_reaches_the_screen_only_while_the_panel_keeps_talking(self):
        clock = [1000.0]
        desk = monitor.Desk(clock=lambda: clock[0])
        desk.configure(True, True, 'resting', False, weather=json.dumps({'t': 20, 'c': 0, 'text': 'Céu limpo', 'icon': 'sun', 'at': 1000, 'days': []}))
        self.assertEqual(desk.display()['weather']['t'], 20)
        clock[0] += 40
        self.assertIsNone(desk.display()['weather'])


if __name__ == '__main__':
    unittest.main()
