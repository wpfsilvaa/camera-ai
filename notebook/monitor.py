#!/usr/bin/env python3
"""Agente do notebook da cozinha: bateria/energia e o botão de chamar a família.

Sem dependências. O painel consulta GET /status com o token compartilhado (bateria, energia e
estado da chamada) e decide quando avisar (app/notebook.py). A tela do quiosque (notebook/kiosk/)
é servida só para o próprio notebook (127.0.0.1) e fala com este agente em /state, /call e /cancel.
"""
import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SUPPLIES = Path('/sys/class/power_supply')
PORT = int(os.environ.get('MONITOR_PORT', '8765'))
PHOTOS = Path(os.environ.get('MONITOR_PHOTOS_DIR', Path.home() / '.cache/casa-monitor/photos'))
PHOTO_ID = re.compile(r'^[a-f0-9]{32}$')
MAX_PHOTO_BYTES = 4 * 1024 * 1024
AVATARS = Path(os.environ.get('MONITOR_AVATARS_DIR', Path.home() / '.cache/casa-monitor/avatars'))
MAX_AVATAR_BYTES = 300 * 1024
MAX_CALLTO = 4   # Buttons "call this person" on the screen.
KIOSK = Path(os.environ.get('MONITOR_KIOSK_DIR', Path(__file__).resolve().parent / 'kiosk'))
TTS_DIR = Path(os.environ.get('MONITOR_TTS_DIR', Path.home() / '.local/share/casa-tts'))
TOKEN_FILE = Path(os.environ.get('MONITOR_TOKEN_FILE', Path.home() / '.config/casa-monitor/token'))


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def reading():
    battery, mains = None, []
    for supply in sorted(SUPPLIES.glob('*')):
        kind = read(supply / 'type')
        if kind == 'Battery' and read(supply / 'scope') != 'Device' and battery is None:
            capacity = read(supply / 'capacity')
            battery = {'percent': int(capacity) if capacity and capacity.isdigit() else None,
                       'status': read(supply / 'status')}
        elif kind in ('Mains', 'USB'):
            mains.append(read(supply / 'online') == '1')
    if mains:
        plugged = any(mains)
    else:  # No adapter reported: infer from the battery state.
        plugged = battery is None or battery['status'] != 'Discharging'
    return {'host': socket.gethostname(), 'time': time.time(), 'plugged': plugged,
            'battery': battery['percent'] if battery else None,
            'status': battery['status'] if battery else None,
            'uptime': float(read(Path('/proc/uptime')).split()[0])}


# A call nobody answered stops ringing after this long ("panic" keeps ringing until someone answers or he cancels).
MISSED_AFTER = 300
RESULT_SECONDS = 10  # How long "call ended / missed" stays on the kiosk screen.
DEFAULT_CFG = {'slide': 15, 'awake': 30, 'sound': True, 'vol': {'button': 70, 'call': 70, 'help': 100, 'message': 80}, 'calendar': True, 'framecal': 'always', 'rain': True, 'speak': True, 'voice': 'faber', 'hints': [], 'black': True}
TEST_SOUNDS = ('press', 'ring', 'help', 'message', 'nudge', 'rain', 'voice')
VIGIA_STATES = ('off', 'resting', 'analysing', 'scheduled')
GREET_SECONDS = 10
BIRTHDAY_SECONDS = 25
DAILY_SECONDS = 25
LINK_SECONDS = 30  # The panel polls every few seconds; silence longer than this means calls would go nowhere.
KINDS = ('call', 'panic')
BACKLIGHT = Path(os.environ.get('MONITOR_BACKLIGHT_DIR', '/sys/class/backlight'))
STALE_BRIGHTNESS = 90   # Without news from the dashboard for this long, the screen goes back to how it was.


def parse_birthdays(text):
    """[{'n', 'd'}] from the dashboard's JSON, keeping only well-formed entries."""
    try:
        items = json.loads(text) if text else []
    except ValueError:
        return []
    found = []
    for item in items[:20] if isinstance(items, list) else []:
        name, day = (str(item.get('n', '')) if isinstance(item, dict) else ''), (str(item.get('d', '')) if isinstance(item, dict) else '')
        name = ''.join(ch for ch in name if ch.isprintable())[:30].strip()
        if name and len(day) == 5 and day[2] == '-' and day[:2].isdigit() and day[3:].isdigit():
            found.append({'n': name, 'd': day})
    return found


def parse_quotes(text):
    """[{'t', 'a'}]: messages left for the person being greeted (text, sender's first name)."""
    try:
        items = json.loads(text) if text else []
    except ValueError:
        return []
    found = []
    for item in items[:5] if isinstance(items, list) else []:
        if isinstance(item, dict):
            body = ''.join(ch for ch in str(item.get('t', '')) if ch.isprintable())[:240].strip()
            if body:
                found.append({'s': bool(item.get('s')), 'i': str(item.get('i', ''))[:40], 't': body, 'a': ''.join(ch for ch in str(item.get('a', '')) if ch.isprintable())[:30].strip()})
    return found


WEATHER_ICONS = ('sun', 'partly', 'cloud', 'rain', 'storm', 'snow', 'fog')


def parse_weather(text):
    """The forecast from the dashboard's JSON with every field checked, or None."""
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return None
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
    if not isinstance(data, dict) or not number(data.get('t')) or not number(data.get('at')) or data.get('icon') not in WEATHER_ICONS:
        return None
    days = []
    for day in (data.get('days') or [])[:4]:
        if isinstance(day, dict) and all(number(day.get(k)) for k in ('hi', 'lo', 'rain')):
            days.append({'d': ''.join(ch for ch in str(day.get('d', '')) if ch.isprintable())[:5], 'icon': day['icon'] if day.get('icon') in WEATHER_ICONS else 'cloud',
                         'hi': round(day['hi']), 'lo': round(day['lo']), 'rain': min(max(round(day['rain']), 0), 100)})
    return {'t': round(data['t']), 'c': int(data['c']) if number(data.get('c')) else 3, 'icon': data['icon'], 'at': float(data['at']),
            'text': ''.join(ch for ch in str(data.get('text', '')) if ch.isprintable())[:40], 'days': days}


def parse_reminders(text):
    """[{'i', 'a', 't', 'e'}] from the dashboard's JSON: id, author, text, expiry (epoch seconds)."""
    try:
        items = json.loads(text) if text else []
    except ValueError:
        return []
    found = []
    for item in items[:10] if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('e'), (int, float)):
            continue
        body = ''.join(ch for ch in str(item.get('t', '')) if ch.isprintable())[:200].strip()
        if body:
            found.append({'i': str(item.get('i', ''))[:12], 'a': ''.join(ch for ch in str(item.get('a', '')) if ch.isprintable())[:30], 't': body, 'e': float(item['e'])})
    return found


def parse_cfg(text):
    """Screen settings from the dashboard's JSON, each value checked and clamped; defaults for anything odd."""
    cfg = dict(DEFAULT_CFG)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return cfg
    if not isinstance(data, dict):
        return cfg
    for key, low, high in (('slide', 5, 120), ('awake', 10, 300)):
        if isinstance(data.get(key), int) and not isinstance(data.get(key), bool):
            cfg[key] = min(max(data[key], low), high)
    if isinstance(data.get('vol'), dict):
        cfg['vol'] = {name: min(max(data['vol'][name], 0), 100) if isinstance(data['vol'].get(name), int) and not isinstance(data['vol'].get(name), bool) else DEFAULT_CFG['vol'][name]
                      for name in DEFAULT_CFG['vol']}
    if data.get('framecal') in ('always', 'pulse', 'off'):
        cfg['framecal'] = data['framecal']
    for key in ('calendar', 'black', 'sound', 'rain', 'light', 'speak'):
        if isinstance(data.get(key), bool):
            cfg[key] = data[key]
    if isinstance(data.get('hints'), list):
        cfg['hints'] = [''.join(ch for ch in str(h) if ch.isprintable())[:120].strip() for h in data['hints'][:10] if str(h).strip()]
    if data.get('voice') in Voice.MODELS:
        cfg['voice'] = data['voice']
    return cfg


def parse_callto(text):
    """[{'i', 'n'}] people the screen can call by name: user id (32 hex) and first name."""
    try:
        items = json.loads(text) if text else []
    except ValueError:
        return []
    found = []
    for item in items[:MAX_CALLTO] if isinstance(items, list) else []:
        if isinstance(item, dict) and PHOTO_ID.match(str(item.get('i', ''))):
            name = ''.join(ch for ch in str(item.get('n', '')) if ch.isprintable())[:30].strip()
            if name:
                found.append({'i': item['i'], 'n': name})
    return found


def avatar_revs():
    """{user id: revision} of the photos stored for the call buttons (the revision is what the dashboard sent)."""
    found = {}
    try:
        for path in AVATARS.glob('*.jpg'):
            if PHOTO_ID.match(path.stem):
                try:
                    found[path.stem] = (path.with_suffix('.rev')).read_text(encoding='utf-8').strip()[:20]
                except OSError:
                    found[path.stem] = ''
    except OSError:
        pass
    return found


def photo_ids():
    """Photo ids on this screen, oldest upload first."""
    try:
        files = sorted(PHOTOS.glob('*.jpg'), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    return [p.stem for p in files if PHOTO_ID.match(p.stem)]


def photo_list():
    """[{'id', 'a'}]: photos with who sent them (the sidecar file written on upload)."""
    found = []
    for photo_id in photo_ids():
        try:
            author = (PHOTOS / f'{photo_id}.author').read_text(encoding='utf-8').strip()[:40]
        except OSError:
            author = ''
        found.append({'id': photo_id, 'a': ''.join(ch for ch in author if ch.isprintable())})
    return found


def build():
    """Changes whenever a kiosk file changes, so an open screen reloads itself after an update."""
    times = [int((KIOSK / name).stat().st_mtime) for name in ('index.html', 'kiosk.css', 'kiosk.js') if (KIOSK / name).is_file()]
    return str(max(times, default=0))


class Backlight:
    """Panel brightness without root: logind's SetBrightness on the graphical session (what brightnessctl does).

    Reads the level from /sys/class/backlight; setting it needs the session id, found with `loginctl`.
    """

    def __init__(self, root=BACKLIGHT, runner=None):
        devices = sorted(root.glob('*')) if root.is_dir() else []
        self.device = devices[0] if devices else None
        self.max = int(read(self.device / 'max_brightness') or 0) if self.device else 0
        self.runner = runner or self._logind
        self.session = None

    @property
    def available(self):
        return bool(self.device and self.max > 0)

    def percent(self):
        raw = read(self.device / 'brightness')
        return round(100 * int(raw) / self.max) if raw and raw.isdigit() else None

    def set_percent(self, percent):
        """Never fully off (some panels go black at 0): the minimum is one step."""
        self.runner(self.device.name, max(1, round(self.max * min(max(percent, 0), 100) / 100)))

    def _logind(self, name, raw):
        import subprocess
        if self.session is None:
            shown = subprocess.run(['loginctl', 'show-user', str(os.getuid()), '--property=Display', '--value'], capture_output=True, text=True, timeout=5)
            self.session = shown.stdout.strip() or None
        if self.session:
            subprocess.run(['busctl', 'call', 'org.freedesktop.login1', f'/org/freedesktop/login1/session/{self.session}', 'org.freedesktop.login1.Session',
                            'SetBrightness', 'ssu', 'backlight', name, str(raw)], capture_output=True, timeout=5)


class Dimmer:
    """Keeps the panel at the brightness the dashboard asks for, fading between levels.

    The dashboard sends the wanted level with every poll (dim at night, brighter when someone is around);
    a touch on the screen raises it at once for a while. Without news the screen returns to its original level.
    """

    def __init__(self, backlight, clock=time.time, sleep=time.sleep):
        self.backlight, self.clock, self.sleep = backlight, clock, sleep
        self.target = None      # percent from the dashboard, or None to leave the screen alone
        self.wake_level, self.hold, self.wake_until = None, 45, 0
        self.news_at = 0
        self.original = None    # brightness before the first change, restored when the dashboard stops asking
        self.current = None
        self.test = None        # (percent, until)
        self.lock = threading.Lock()

    def configure(self, target, wake_level=None, hold=45):
        with self.lock:
            self.target, self.wake_level, self.hold, self.news_at = target, wake_level, hold, self.clock()

    def wake(self):
        with self.lock:
            if self.wake_level is not None:
                self.wake_until = self.clock() + self.hold

    def try_level(self, percent, seconds=6):
        with self.lock:
            self.test = (percent, self.clock() + seconds)

    def desired(self):
        """Percent to show now, or None for "leave it as the user had it"."""
        with self.lock:
            now = self.clock()
            if self.test and now < self.test[1]:
                return self.test[0]
            if self.target is None or now - self.news_at > STALE_BRIGHTNESS:
                return None
            level = self.target
            if self.wake_level is not None and now < self.wake_until:
                level = max(level, self.wake_level)
            return level

    def step(self):
        if not self.backlight.available:
            return
        want = self.desired()
        if want is None:
            if self.original is not None:
                self.fade(self.original)
                self.original = None
            return
        if self.original is None:
            self.original = self.backlight.percent()
        if self.current is None:
            self.current = self.backlight.percent()
        if self.current is None or abs(self.current - want) >= 1:
            self.fade(want)

    def fade(self, to, steps=6):
        start = self.current if self.current is not None else self.backlight.percent()
        for i in range(1, steps + 1):
            self.backlight.set_percent(start + (to - start) * i / steps if start is not None else to)
            self.sleep(0.12)
        self.current = to

    def run(self, stop):
        while not stop.is_set():
            try:
                self.step()
            except Exception:
                pass
            stop.wait(0.4)


class DisplayPower:
    """Turns the panel off (DPMS) and on again: Hyprland first, X11 as a fallback.

    `commands` is injectable for tests; each entry takes (on: bool) and returns True when it worked.
    """

    def __init__(self, commands=None):
        self.commands = commands or [self._hyprland, self._x11]
        self.state = True        # What we last asked for.
        self.input_wake = None   # Hyprland instance where input-wakes-screen was already enabled.

    @staticmethod
    def _run(args, env=None):
        import subprocess
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=6, env=env)
        except (OSError, subprocess.SubprocessError):
            return None
        return result

    def _hyprland(self, on):
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
        instances = sorted((p for p in (runtime / 'hypr').glob('*') if (p / '.socket.sock').exists()), key=lambda p: p.stat().st_mtime) if (runtime / 'hypr').is_dir() else []
        if not instances:
            return False
        env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime), 'HYPRLAND_INSTANCE_SIGNATURE': instances[-1].name}
        if not on and self.input_wake != instances[-1].name:
            # With the panel off, a mouse move or key press should turn it on again (off by default in Hyprland).
            for arguments in (['eval', 'hl.config({ misc = { mouse_move_enables_dpms = true, key_press_enables_dpms = true } })'],
                              ['keyword', 'misc:mouse_move_enables_dpms', 'true']):
                result = self._run(['hyprctl', *arguments], env)
                if result and result.returncode == 0 and 'ok' in result.stdout.lower():
                    break
            self.input_wake = instances[-1].name
        word = 'on' if on else 'off'
        # Hyprland 0.55+ takes Lua (hl.dsp...); older versions take "dpms on|off".
        for arguments in (['dispatch', f'hl.dsp.dpms({{ action = "{word}" }})'], ['dispatch', 'dpms', word]):
            result = self._run(['hyprctl', *arguments], env)
            if result and result.returncode == 0 and 'ok' in result.stdout.lower():
                return True
        return False

    def _x11(self, on):
        display = os.environ.get('DISPLAY') or ':0'
        result = self._run(['xset', '-display', display, 'dpms', 'force', 'on' if on else 'off'])
        return bool(result and result.returncode == 0)

    def set(self, on):
        if on == self.state:
            return True
        for command in self.commands:
            if command(on):
                self.state = on
                return True
        return False


class ScreenSchedule:
    """When the panel should be off: at night, with nobody around, as the dashboard asks.

    The dashboard sends screen=off|on with every poll (off only at night with nobody in view or on a call);
    a touch, a click or a key turns it back on for `hold` seconds. Without news, or when the dashboard stops
    asking for it, the panel is switched on again so it can never stay dark by accident.
    """

    def __init__(self, power, clock=time.time):
        self.power, self.clock = power, clock
        self.wanted = None      # 'off', 'on' or None (leave it alone)
        self.hold, self.wake_until, self.news_at, self.test_until = 45, 0, 0, 0
        self.lock = threading.Lock()

    def configure(self, wanted, hold=45):
        with self.lock:
            self.wanted, self.hold, self.news_at = wanted, hold, self.clock()

    def wake(self):
        with self.lock:
            self.wake_until = self.clock() + self.hold

    def try_off(self, seconds=5):
        with self.lock:
            self.test_until = self.clock() + seconds

    def should_be_on(self):
        with self.lock:
            now = self.clock()
            if now < self.test_until:
                return False
            if self.wanted != 'off' or now - self.news_at > STALE_BRIGHTNESS:
                return True
            return now < self.wake_until

    def step(self):
        self.power.set(self.should_be_on())

    def run(self, stop):
        while not stop.is_set():
            try:
                self.step()
            except Exception:
                pass
            stop.wait(0.3)


class Desk:
    """The call button's state: idle -> ringing -> answered -> ended (or missed)."""

    def __init__(self, clock=time.time):
        self.clock, self.lock = clock, threading.Lock()
        self.call = None
        self.last_poll = 0
        self.enabled = {'call': False, 'panic': False}
        self.vigia = None   # (state, night, received_at) from the dashboard's last poll.
        self.greet = None   # {'name', 'id', 'until', 'birthday', 'age'}: shown once per id.
        self.bdays = []     # [{'n': first name, 'd': 'MM-DD'}] for the calendar.
        self.tests = []  # [{'id', 'sound', 'volume', 'text', 'at'}]: sounds/messages the dashboard asked the screen to play now.
        self.version = 0     # Bumped on every change worth showing; /state?v=N waits for it (long-poll).
        self.changed = threading.Condition()
        self._signature = ''
        self.weather = None   # {'t', 'c', 'text', 'icon', 'days', 'at'} forecast sent by the dashboard.
        self.red = False   # Night look in red tones (only when chosen in the settings).
        self.acks = []   # Message ids confirmed with "Li" on this screen, until the dashboard stores them.
        self.cfg = dict(DEFAULT_CFG)   # Screen settings from the dashboard.
        self.frame = False   # Photo frame switched on in the dashboard's settings.
        self.reminders = []  # [{'i', 'a', 't', 'e'}]: notes cycled on the screen until their expiry.
        self.callto = []     # [{'i', 'n'}]: people with their own call button.

    def configure(self, call, panic, vigia=None, night=False, greet='', greet_id='', kind='', age='', bdays='', reminders='', frame=False, cfg='', msgs='', quiet=False, acked='', red=False, weather='', callto=''):
        with self.lock:
            now = self.last_poll = self.clock()
            self.enabled = {'call': call, 'panic': panic}
            self.vigia = (vigia, night, now) if vigia in VIGIA_STATES else None
            self.red = bool(red)
            self.callto = parse_callto(callto)
            self.weather = parse_weather(weather)
            name = ''.join(ch for ch in greet if ch.isprintable())[:30].strip()
            if name and (not self.greet or self.greet['id'] != greet_id):
                birthday, daily = kind == 'birthday', kind == 'daily'
                self.greet = {'name': name, 'id': greet_id, 'until': now + (BIRTHDAY_SECONDS if birthday else DAILY_SECONDS if daily else GREET_SECONDS),
                              'birthday': birthday, 'daily': daily, 'age': int(age) if age.isdigit() and 0 < int(age) < 130 else 0,
                              'msgs': parse_quotes(msgs), 'quiet': bool(quiet)}
            self.bdays = parse_birthdays(bdays)
            done = {i for i in acked.split(',') if i}
            self.acks = [a for a in self.acks if a not in done]   # The dashboard stored these already.
            self.reminders = parse_reminders(reminders)
            self.frame = bool(frame)
            self.cfg = parse_cfg(cfg)

    def queue_test(self, spec):
        """A sound (or a sample message) to play on the screen right now, so volumes can be tuned from the dashboard."""
        sound = str(spec.get('sound', ''))
        volume = spec.get('volume')
        if sound not in TEST_SOUNDS or not isinstance(volume, int) or isinstance(volume, bool):
            raise ValueError('Teste inválido.')
        text = ''.join(ch for ch in str(spec.get('text', '')) if ch.isprintable())[:200].strip()
        voice = spec.get('voice') if spec.get('voice') in Voice.MODELS else ''
        with self.lock:
            now = self.clock()
            self.tests = [t for t in self.tests if now - t['at'] < 30][-4:] + [{'id': uuid.uuid4().hex, 'sound': sound, 'volume': min(max(volume, 0), 100), 'text': text, 'voice': voice, 'at': now}]
            test_id = self.tests[-1]['id']
        self.bump()
        return test_id

    def ack(self, message_id):
        if re.fullmatch(r'[a-f0-9]{32}', message_id or ''):
            with self.lock:
                if message_id not in self.acks:
                    self.acks = (self.acks + [message_id])[-50:]

    def display(self):
        """Watch-mode state, night tone and greeting for the kitchen screen; stale data is dropped."""
        with self.lock:
            now, vigia = self.clock(), self.vigia
            avatars = avatar_revs()
            fresh = vigia is not None and now - vigia[2] < LINK_SECONDS
            greet = self.greet if self.greet and now < self.greet['until'] else None
            return {'vigia': vigia[0] if fresh else None, 'night': bool(vigia[1]) if fresh else False, 'red': self.red if fresh else False, 'weather': self.weather if fresh else None,
                    'greet': {k: greet[k] for k in ('name', 'id', 'birthday', 'daily', 'age', 'msgs', 'quiet')} if greet else None,
                    'bdays': self.bdays if fresh else [],
                    'callto': [{**p, 'p': avatars.get(p['i'])} for p in self.callto] if fresh else [],
                    'reminders': [r for r in self.reminders if r['e'] > now] if fresh else [],
                    'tests': [{k: t[k] for k in ('id', 'sound', 'volume', 'text', 'voice')} for t in self.tests if now - t['at'] < 15],
                    'cfg': self.cfg if fresh else dict(DEFAULT_CFG), 'frame': self.frame if fresh else False, 'photos': photo_list() if fresh and self.frame else []}

    def bump(self):
        with self.changed:
            self.version += 1
            self.changed.notify_all()

    def touch(self):
        """Bump the version when what the screen would show differs from the last time."""
        signature = json.dumps(self.display(), sort_keys=True, default=str) + json.dumps(self.snapshot(), sort_keys=True, default=str)
        if signature != self._signature:
            self._signature = signature
            self.bump()

    def wait_change(self, since, seconds):
        with self.changed:
            self.changed.wait_for(lambda: self.version != since, timeout=seconds)
            return self.version

    def linked(self):
        return self.clock() - self.last_poll < LINK_SECONDS

    def snapshot(self):
        with self.lock:
            return self._tick()

    def _tick(self):
        call, now = self.call, self.clock()
        if call and call['state'] == 'ringing' and call['kind'] == 'call' and now - call['since'] >= MISSED_AFTER:
            call.update(state='missed', ended_at=now)
        if call and call['state'] in ('ended', 'missed') and now - call['ended_at'] >= RESULT_SECONDS:
            self.call = call = None
        return dict(call) if call else {'state': 'idle'}

    def press(self, kind, to=''):
        with self.lock:
            if kind not in KINDS or not self.enabled[kind] or not self.linked():
                raise ValueError('Chamada indisponível agora.')
            target = next((p for p in self.callto if p['i'] == to), None) if to and kind == 'call' else None
            if to and not target:
                raise ValueError('Esta pessoa não está mais na lista de chamadas.')
            if self._tick()['state'] in ('ringing', 'answered'):
                return dict(self.call)
            self.call = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'state': 'ringing', 'since': self.clock(),
                         'answered_by': None, 'answered_at': None, 'ended_at': None}
            if target:
                self.call.update(to=target['i'], to_name=target['n'])
            return dict(self.call)

    def answer(self, name):
        with self.lock:
            if self._tick()['state'] != 'ringing':
                raise ValueError('Esta chamada já foi atendida ou terminou.')
            self.call.update(state='answered', answered_by=name[:60] or 'Alguém da família', answered_at=self.clock())
            return dict(self.call)

    def end(self):
        with self.lock:
            if self._tick()['state'] in ('ringing', 'answered'):
                self.call.update(state='ended', ended_at=self.clock())
            return self._tick()


class Voice:
    """Local text to speech with Piper (a Portuguese neural voice), installed in its own folder; wavs are cached."""
    MODELS = {'faber': 'pt_BR-faber-medium', 'cadu': 'pt_BR-cadu-medium', 'jeff': 'pt_BR-jeff-medium', 'edresson': 'pt_BR-edresson-low'}
    DEFAULT = 'faber'
    MAX_CHARS = 700
    KEEP = 60

    def __init__(self, folder=None):
        self.folder = Path(folder or TTS_DIR)
        self.lock = threading.Lock()

    @property
    def python(self):
        return self.folder / 'venv/bin/python'

    def model(self, voice):
        return self.folder / 'voices' / f'{self.MODELS.get(voice) or self.MODELS[self.DEFAULT]}.onnx'

    def available(self, voice=None):
        return self.python.is_file() and self.model(voice).is_file()

    def wav(self, text, voice=None):
        """WAV bytes for the text in that voice (faber, cadu, jeff, edresson), or None when it is not installed or failed."""
        text = ' '.join(''.join(ch for ch in str(text) if ch.isprintable()).split())[:self.MAX_CHARS]
        voice = voice if voice in self.MODELS else self.DEFAULT
        if not text or not self.available(voice):
            return None
        cache = self.folder / 'cache'
        cache.mkdir(exist_ok=True)
        target = cache / (hashlib.sha1(f'{voice}|{text}'.encode()).hexdigest() + '.wav')
        with self.lock:
            if not target.is_file():
                temporary = target.with_suffix('.tmp')
                try:
                    subprocess.run([str(self.python), '-m', 'piper', '-m', str(self.model(voice)), '-f', str(temporary), '--', text],
                                   check=True, capture_output=True, timeout=40)
                    temporary.replace(target)
                except (subprocess.SubprocessError, OSError):
                    temporary.unlink(missing_ok=True)
                    return None
                for old in sorted(cache.glob('*.wav'), key=lambda p: p.stat().st_mtime)[:-self.KEEP]:
                    old.unlink(missing_ok=True)
        return target.read_bytes()


class Handler(BaseHTTPRequestHandler):
    token = ''
    desk = Desk()
    voice = Voice()
    dimmer = Dimmer(Backlight())
    screen = ScreenSchedule(DisplayPower())
    kiosk_files = {'/': ('index.html', 'text/html; charset=utf-8'), '/kiosk.css': ('kiosk.css', 'text/css'),
                   '/kiosk.js': ('kiosk.js', 'text/javascript'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}

    def dim_from(self, query):
        """Brightness wanted by the dashboard: bright=<0-100> (absent: leave the screen alone), bright_wake, bright_hold."""
        def number(name, low, high):
            value = (query.get(name) or [''])[0]
            return min(max(int(value), low), high) if value.isdigit() else None
        target = number('bright', 0, 100)
        self.dimmer.configure(target, number('bright_wake', 0, 100), number('bright_hold', 5, 3600) or 45)
        self.screen.configure((query.get('screen') or [''])[0] if (query.get('screen') or [''])[0] in ('on', 'off') else None, number('screen_hold', 5, 3600) or 45)

    def local(self):
        return self.client_address[0] in ('127.0.0.1', '::1')

    def authorized(self):
        sent = self.headers.get('Authorization', '').removeprefix('Bearer ')
        return hmac.compare_digest(sent.encode(), self.token.encode())

    def reply(self, status, payload=None, body=None, kind='application/json'):
        data = body if body is not None else json.dumps(payload if payload is not None else {}).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        except ValueError:
            return {}

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/status' and self.authorized():
            query = parse_qs(url.query)
            self.desk.configure(query.get('call') == ['1'], query.get('panic') == ['1'], (query.get('vigia') or [None])[0],
                                query.get('night') == ['1'], (query.get('greet') or [''])[0], (query.get('greet_id') or [''])[0],
                                (query.get('greet_kind') or [''])[0], (query.get('age') or [''])[0], (query.get('bdays') or [''])[0], (query.get('reminders') or [''])[0], query.get('frame') == ['1'], (query.get('cfg') or [''])[0], (query.get('greet_msgs') or [''])[0], query.get('greet_quiet') == ['1'], (query.get('acked') or [''])[0], query.get('red') == ['1'], (query.get('weather') or [''])[0], (query.get('callto') or [''])[0])
            self.dim_from(query)
            self.desk.touch()   # Anything new for the screen goes out immediately to the waiting /state request.
            return self.reply(200, {**reading(), 'call': self.desk.snapshot(), 'acks': list(self.desk.acks)})
        if url.path == '/avatars' and self.authorized():
            return self.reply(200, {'revs': avatar_revs()})
        if url.path == '/photos' and self.authorized():
            return self.reply(200, {'ids': photo_ids(), 'authors': {p['id']: p['a'] for p in photo_list()}})
        if not self.local():
            return self.send_error(404)
        avatar = re.fullmatch(r'/avatar/([a-f0-9]{32})\.jpg', url.path)
        if avatar and (AVATARS / f'{avatar[1]}.jpg').is_file():
            data = (AVATARS / f'{avatar[1]}.jpg').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'max-age=3600')
            self.end_headers()
            return self.wfile.write(data)
        photo = re.fullmatch(r'/photo/([a-f0-9]{32})\.jpg', url.path)
        if photo:
            path = PHOTOS / f'{photo[1]}.jpg'
            if not path.is_file():
                return self.send_error(404)
            self.send_response(200)
            data = path.read_bytes()
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'max-age=86400')
            self.end_headers()
            return self.wfile.write(data)
        if url.path == '/state':
            query = parse_qs(url.query)
            since = query.get('v', [''])[0]
            if since.lstrip('-').isdigit() and int(since) >= 0:
                # Long-poll: answers as soon as something changes, or after a few seconds so timers still advance.
                self.desk.wait_change(int(since), min(float((query.get('wait') or ['3'])[0] or 3), 5))
            info = reading()
            return self.reply(200, {'call': self.desk.snapshot(), 'linked': self.desk.linked(), 'enabled': self.desk.enabled,
                                    'battery': info['battery'], 'plugged': info['plugged'], 'now': time.time(), **self.desk.display(),
                                    'build': build(), 'v': self.desk.version})
        entry = self.kiosk_files.get(url.path)
        if entry and (KIOSK / entry[0]).is_file():
            return self.reply(200, body=(KIOSK / entry[0]).read_bytes(), kind=entry[1])
        self.send_error(404)

    def do_PUT(self):
        renamed = re.fullmatch(r'/photos/([a-f0-9]{32})/author', urlsplit(self.path).path)
        if renamed and self.authorized():
            size = min(int(self.headers.get('Content-Length') or 0), 200)
            if (PHOTOS / f'{renamed[1]}.jpg').is_file():
                (PHOTOS / f'{renamed[1]}.author').write_text(self.rfile.read(size).decode('utf-8', 'replace')[:40], encoding='utf-8')
            return self.reply(200, {'ok': True})
        avatar = re.fullmatch(r'/avatars/([a-f0-9]{32})', urlsplit(self.path).path)
        if avatar and self.authorized():
            size = int(self.headers.get('Content-Length') or 0)
            if not 0 < size <= MAX_AVATAR_BYTES:
                return self.send_error(413)
            data = self.rfile.read(size)
            if not data.startswith(b'\xff\xd8'):
                return self.send_error(415)
            AVATARS.mkdir(parents=True, exist_ok=True)
            temporary = AVATARS / f'{avatar[1]}.part'
            temporary.write_bytes(data)
            temporary.replace(AVATARS / f'{avatar[1]}.jpg')
            (AVATARS / f'{avatar[1]}.rev').write_text(self.headers.get('X-Rev', '')[:20], encoding='utf-8')
            return self.reply(200, {'ok': True})
        photo = re.fullmatch(r'/photos/([a-f0-9]{32})', urlsplit(self.path).path)
        if not (photo and self.authorized()):
            return self.send_error(404)
        size = int(self.headers.get('Content-Length') or 0)
        if not 0 < size <= MAX_PHOTO_BYTES:
            return self.send_error(413)
        data = self.rfile.read(size)
        if not data.startswith(b'\xff\xd8'):
            return self.send_error(415)
        PHOTOS.mkdir(parents=True, exist_ok=True)
        temporary = PHOTOS / f'{photo[1]}.part'
        temporary.write_bytes(data)
        temporary.replace(PHOTOS / f'{photo[1]}.jpg')
        author = unquote(self.headers.get('X-Photo-Author', ''))[:40]
        (PHOTOS / f'{photo[1]}.author').write_text(author, encoding='utf-8')
        self.reply(200, {'ok': True})

    def do_DELETE(self):
        avatar = re.fullmatch(r'/avatars/([a-f0-9]{32})', urlsplit(self.path).path)
        if avatar and self.authorized():
            (AVATARS / f'{avatar[1]}.jpg').unlink(missing_ok=True)
            (AVATARS / f'{avatar[1]}.rev').unlink(missing_ok=True)
            return self.reply(200, {'ok': True})
        photo = re.fullmatch(r'/photos/([a-f0-9]{32})', urlsplit(self.path).path)
        if not (photo and self.authorized()):
            return self.send_error(404)
        (PHOTOS / f'{photo[1]}.jpg').unlink(missing_ok=True)
        (PHOTOS / f'{photo[1]}.author').unlink(missing_ok=True)
        self.reply(200, {'ok': True})

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path == '/test' and self.authorized():
            spec = self.body()
            if spec.get('sound') == 'screenoff':   # Hardware: turn the panel off for a few seconds, then back on.
                self.screen.try_off(5)
                return self.reply(200, {'ok': True})
            if spec.get('sound') == 'brightness':   # Hardware: handled here, not by the page.
                if not isinstance(spec.get('volume'), int):
                    return self.reply(422, {'error': 'Teste inválido.'})
                self.dimmer.try_level(min(max(spec['volume'], 1), 100))
                return self.reply(200, {'ok': True, 'available': self.dimmer.backlight.available})
            try:
                return self.reply(200, {'id': self.desk.queue_test(spec)})
            except ValueError as error:
                return self.reply(422, {'error': str(error)})
        if url.path in ('/call/answer', '/call/end') and self.authorized():
            try:
                call = self.desk.answer(str(self.body().get('name', ''))) if url.path == '/call/answer' else self.desk.end()
            except ValueError as error:
                return self.reply(409, {'error': str(error)})
            self.desk.bump()
            return self.reply(200, call)
        # A custom header keeps other web pages in the kiosk browser from pressing the button.
        if not self.local() or self.headers.get('X-Kiosk') != '1':
            return self.send_error(404)
        try:
            if url.path == '/call':
                body = self.body()
                call = self.desk.press(str(body.get('kind')), str(body.get('to') or ''))
                self.desk.bump()
                return self.reply(201, call)
            if url.path == '/cancel':
                call = self.desk.end()
                self.desk.bump()
                return self.reply(200, call)
            if url.path == '/wake':
                self.dimmer.wake()
                self.screen.wake()
                return self.reply(200, {'ok': True})
            if url.path == '/tts':
                body = self.body()
                audio = self.voice.wav(str(body.get('text', '')), str(body.get('voice', '')))
                return self.reply(200, body=audio, kind='audio/wav') if audio else self.send_error(404)
            if url.path == '/ack':
                self.desk.ack(str(self.body().get('id', '')))
                self.desk.bump()
                return self.reply(200, {'ok': True})
        except ValueError as error:
            return self.reply(409, {'error': str(error)})
        self.send_error(404)

    def log_message(self, *_):
        pass


def main():
    Handler.token = read(TOKEN_FILE) or ''
    if len(Handler.token) < 32:
        sys.exit(f'Token ausente ou curto em {TOKEN_FILE}.')
    stop = threading.Event()
    threading.Thread(target=Handler.dimmer.run, args=(stop,), daemon=True).start()
    threading.Thread(target=Handler.screen.run, args=(stop,), daemon=True).start()
    Handler.screen.power.set(True)   # Whatever happened before, start with the panel on.
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
