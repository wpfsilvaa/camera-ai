"""Isolated fixture for login-ui-smoke.mjs; starts without users and without WhatsApp."""
import sys

import uvicorn

from app import main


async def gateway(method, path, payload=None):
    return {'state': 'connected', 'qr': 'data:image/png;base64,AAAA', 'error': None}

main.gateway = gateway
uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[1]), log_level='error')
