#!/usr/bin/env python3
"""Agente do notebook da cozinha: informa bateria e energia ao painel Casa Presente.

Só leitura de /sys/class/power_supply, sem dependências. O painel consulta GET /status
com o token compartilhado; quem decide quando avisar é o painel (app/notebook.py).
"""
import hmac
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SUPPLIES = Path('/sys/class/power_supply')
PORT = int(os.environ.get('MONITOR_PORT', '8765'))
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


class Handler(BaseHTTPRequestHandler):
    token = ''

    def do_GET(self):
        sent = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if self.path != '/status' or not hmac.compare_digest(sent.encode(), self.token.encode()):
            self.send_error(404)
            return
        body = json.dumps(reading()).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    Handler.token = read(TOKEN_FILE) or ''
    if len(Handler.token) < 32:
        sys.exit(f'Token ausente ou curto em {TOKEN_FILE}.')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
