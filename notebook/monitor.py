#!/usr/bin/env python3
"""Agente do notebook da cozinha: bateria/energia e o botão de chamar a família.

Sem dependências. O painel consulta GET /status com o token compartilhado (bateria, energia e
estado da chamada) e decide quando avisar (app/notebook.py). A tela do quiosque (notebook/kiosk/)
é servida só para o próprio notebook (127.0.0.1) e fala com este agente em /state, /call e /cancel.
"""
import hmac
import json
import os
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
LINK_SECONDS = 30  # The panel polls every few seconds; silence longer than this means calls would go nowhere.
KINDS = ('call', 'panic')


class Desk:
    """The call button's state: idle -> ringing -> answered -> ended (or missed)."""

    def __init__(self, clock=time.time):
        self.clock, self.lock = clock, threading.Lock()
        self.call = None
        self.last_poll = 0
        self.enabled = {'call': False, 'panic': False}

    def configure(self, call, panic):
        with self.lock:
            self.last_poll = self.clock()
            self.enabled = {'call': call, 'panic': panic}

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
            self.desk.configure(query.get('call') == ['1'], query.get('panic') == ['1'])
            return self.reply(200, {**reading(), 'call': self.desk.snapshot()})
        if not self.local():
            return self.send_error(404)
        if url.path == '/state':
            info = reading()
            return self.reply(200, {'call': self.desk.snapshot(), 'linked': self.desk.linked(), 'enabled': self.desk.enabled,
                                    'battery': info['battery'], 'plugged': info['plugged'], 'now': time.time()})
        entry = self.kiosk_files.get(url.path)
        if entry and (KIOSK / entry[0]).is_file():
            return self.reply(200, body=(KIOSK / entry[0]).read_bytes(), kind=entry[1])
        self.send_error(404)

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
