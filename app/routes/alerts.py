import re
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..alerts import IMAGES


def build(alerts, config):
    """Recent WhatsApp alerts and the test message."""
    router = APIRouter()

    @router.get('/api/alerts')
    def list_alerts():
        return alerts.recent(20)

    @router.post('/api/alerts/test', status_code=201)
    def test_alert():
        if not config.get().delivery_targets():
            raise HTTPException(409, 'Cadastre ao menos um número de WhatsApp nas configurações.')
        return {'id': alerts.send_test()}

    @router.get('/api/routine')
    def routine():
        return alerts.routine.summary(time.time())

    @router.get('/alert-media/{filename}')
    def alert_image(filename: str):
        if not re.fullmatch(r'[a-z0-9-]{8,80}\.jpg', filename) or not (IMAGES / filename).is_file():
            raise HTTPException(404)
        return FileResponse(IMAGES / filename, media_type='image/jpeg')

    return router


def build_notebook(notebook):
    """Live state of the kitchen notebook (battery, mains power, signal)."""
    router = APIRouter()

    @router.get('/api/notebook')
    def status():
        return notebook.status()

    return router
