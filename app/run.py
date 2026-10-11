import logging
import os
import sqlite3

import uvicorn

from .config import DATA, gateway_token


def has_users():
    try:
        with sqlite3.connect(DATA / 'history.sqlite3') as db:
            return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    except sqlite3.Error:
        return False


if __name__ == '__main__':
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%d/%m %H:%M:%S')
    # The screen poll carries message texts in its URL: keep them out of the journal.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    gateway_token()
    host = os.environ.get('HOST', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost', '::1') and not os.environ.get('DASHBOARD_PASSWORD') and not has_users():
        raise SystemExit('Crie um usuário no painel (acessando por localhost) ou defina DASHBOARD_PASSWORD no .env antes de liberar acesso pela rede.')
    uvicorn.run('app.main:app', host=host, port=int(os.environ.get('PORT', '8000')), workers=1, timeout_graceful_shutdown=10)
