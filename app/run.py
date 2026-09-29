import os

import uvicorn

from .config import gateway_token

if __name__ == '__main__':
    gateway_token()
    host = os.environ.get('HOST', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost', '::1') and not os.environ.get('DASHBOARD_PASSWORD'):
        raise SystemExit('Defina DASHBOARD_PASSWORD no .env antes de liberar acesso pela rede.')
    uvicorn.run('app.main:app', host=host, port=int(os.environ.get('PORT', '8000')), workers=1, timeout_graceful_shutdown=10)
