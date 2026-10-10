#!/usr/bin/env python3
"""Agente do notebook da cozinha: bateria/energia e o botão de chamar a família.

Sem dependências. O painel consulta GET /status com o token compartilhado (bateria, energia e
estado da chamada) e decide quando avisar (app/notebook.py). A tela do quiosque (notebook/kiosk/)
é servida só para o próprio notebook (127.0.0.1) e fala com este agente em /state, /call e /cancel.
"""
import hmac
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SUPPLIES = Path('/sys/class/power_supply')
PORT = int(os.environ.get('MONITOR_PORT', '8765'))
PHOTOS = Path(os.environ.get('MONITOR_PHOTOS_DIR', Path.home() / '.cache/casa-monitor/photos'))
PHOTO_ID = re.compile(r'^[a-f0-9]{32}$')
MAX_PHOTO_BYTES = 4 * 1024 * 1024
KIOSK = Path(os.environ.get('MONITOR_KIOSK_DIR', Path(__file__).resolve().parent / 'kiosk'))
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
VIGIA_STATES = ('off', 'resting', 'analysing', 'scheduled')
GREET_SECONDS = 10
BIRTHDAY_SECONDS = 25
LINK_SECONDS = 30  # The panel polls every few seconds; silence longer than this means calls would go nowhere.
KINDS = ('call', 'panic')


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


def photo_ids():
    """Photo ids on this screen, oldest upload first."""
    try:
        files = sorted(PHOTOS.glob('*.jpg'), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    return [p.stem for p in files if PHOTO_ID.match(p.stem)]


def build():
    """Changes whenever a kiosk file changes, so an open screen reloads itself after an update."""
    times = [int((KIOSK / name).stat().st_mtime) for name in ('index.html', 'kiosk.css', 'kiosk.js') if (KIOSK / name).is_file()]
    return str(max(times, default=0))


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
        self.frame = False   # Photo frame switched on in the dashboard's settings.
        self.reminders = []  # [{'i', 'a', 't', 'e'}]: notes cycled on the screen until their expiry.

    def configure(self, call, panic, vigia=None, night=False, greet='', greet_id='', kind='', age='', bdays='', reminders='', frame=False):
        with self.lock:
            now = self.last_poll = self.clock()
            self.enabled = {'call': call, 'panic': panic}
            self.vigia = (vigia, night, now) if vigia in VIGIA_STATES else None
            name = ''.join(ch for ch in greet if ch.isprintable())[:30].strip()
            if name and (not self.greet or self.greet['id'] != greet_id):
                birthday = kind == 'birthday'
                self.greet = {'name': name, 'id': greet_id, 'until': now + (BIRTHDAY_SECONDS if birthday else GREET_SECONDS),
                              'birthday': birthday, 'age': int(age) if age.isdigit() and 0 < int(age) < 130 else 0}
            self.bdays = parse_birthdays(bdays)
            self.reminders = parse_reminders(reminders)
            self.frame = bool(frame)

    def display(self):
        """Watch-mode state, night tone and greeting for the kitchen screen; stale data is dropped."""
        with self.lock:
            now, vigia = self.clock(), self.vigia
            fresh = vigia is not None and now - vigia[2] < LINK_SECONDS
            greet = self.greet if self.greet and now < self.greet['until'] else None
            return {'vigia': vigia[0] if fresh else None, 'night': bool(vigia[1]) if fresh else False,
                    'greet': {k: greet[k] for k in ('name', 'id', 'birthday', 'age')} if greet else None,
                    'bdays': self.bdays if fresh else [],
                    'reminders': [r for r in self.reminders if r['e'] > now] if fresh else [],
                    'frame': self.frame if fresh else False, 'photos': photo_ids() if fresh and self.frame else []}

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

    def press(self, kind):
        with self.lock:
            if kind not in KINDS or not self.enabled[kind] or not self.linked():
                raise ValueError('Chamada indisponível agora.')
            if self._tick()['state'] in ('ringing', 'answered'):
                return dict(self.call)
            self.call = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'state': 'ringing', 'since': self.clock(),
                         'answered_by': None, 'answered_at': None, 'ended_at': None}
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


class Handler(BaseHTTPRequestHandler):
    token = ''
    desk = Desk()
    kiosk_files = {'/': ('index.html', 'text/html; charset=utf-8'), '/kiosk.css': ('kiosk.css', 'text/css'),
                   '/kiosk.js': ('kiosk.js', 'text/javascript'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}

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
                                (query.get('greet_kind') or [''])[0], (query.get('age') or [''])[0], (query.get('bdays') or [''])[0], (query.get('reminders') or [''])[0], query.get('frame') == ['1'])
            return self.reply(200, {**reading(), 'call': self.desk.snapshot()})
        if url.path == '/photos' and self.authorized():
            return self.reply(200, {'ids': photo_ids()})
        if not self.local():
            return self.send_error(404)
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
            info = reading()
            return self.reply(200, {'call': self.desk.snapshot(), 'linked': self.desk.linked(), 'enabled': self.desk.enabled,
                                    'battery': info['battery'], 'plugged': info['plugged'], 'now': time.time(), **self.desk.display(),
                                    'build': build()})
        entry = self.kiosk_files.get(url.path)
        if entry and (KIOSK / entry[0]).is_file():
            return self.reply(200, body=(KIOSK / entry[0]).read_bytes(), kind=entry[1])
        self.send_error(404)

    def do_PUT(self):
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
        self.reply(200, {'ok': True})

    def do_DELETE(self):
        photo = re.fullmatch(r'/photos/([a-f0-9]{32})', urlsplit(self.path).path)
        if not (photo and self.authorized()):
            return self.send_error(404)
        (PHOTOS / f'{photo[1]}.jpg').unlink(missing_ok=True)
        self.reply(200, {'ok': True})

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path in ('/call/answer', '/call/end') and self.authorized():
            try:
                call = self.desk.answer(str(self.body().get('name', ''))) if url.path == '/call/answer' else self.desk.end()
            except ValueError as error:
                return self.reply(409, {'error': str(error)})
            return self.reply(200, call)
        # A custom header keeps other web pages in the kiosk browser from pressing the button.
        if not self.local() or self.headers.get('X-Kiosk') != '1':
            return self.send_error(404)
        try:
            if url.path == '/call':
                return self.reply(201, self.desk.press(str(self.body().get('kind'))))
            if url.path == '/cancel':
                return self.reply(200, self.desk.end())
        except ValueError as error:
            return self.reply(409, {'error': str(error)})
        self.send_error(404)

    def log_message(self, *_):
        pass


def main():
    Handler.token = read(TOKEN_FILE) or ''
    if len(Handler.token) < 32:
        sys.exit(f'Token ausente ou curto em {TOKEN_FILE}.')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
