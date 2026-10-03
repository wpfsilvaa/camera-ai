"""Isolated server reading the real camera computer (MediaMTX with cam and cam-lite); WhatsApp disabled."""
import os
import sys

import uvicorn

from app.config import Settings, config

source = os.environ.get('LIVE_CAMERA', 'rtsp://192.168.1.103:8554/cam')
config.save(Settings(camera_name='Cozinha', camera_source=source, enabled=True, analysis_enabled=False, fps=10, device='cpu'))
uvicorn.run('app.main:app', host='127.0.0.1', port=int(sys.argv[1]), log_level='error')
