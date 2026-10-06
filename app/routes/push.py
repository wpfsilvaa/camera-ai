from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import ROOT
from ..services import call_service


class Subscription(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str] = Field(max_length=4)


class Endpoint(BaseModel):
    endpoint: str = Field(max_length=2048)


class Presence(Endpoint):
    enabled: bool
    audience: str = Field('all', pattern='^(all|father|unknown)$')
    quiet: bool = False


class Topics(Endpoint):
    enabled: list[str] = Field(max_length=10)


def build(push):
    """Installable app files and the per-device notification subscription."""
    router = APIRouter()

    @router.get('/sw.js')
    def service_worker():
        # Served from the root so it controls the whole dashboard.
        return FileResponse(ROOT / 'static/sw.js', media_type='text/javascript', headers={'Service-Worker-Allowed': '/'})

    @router.get('/manifest.webmanifest')
    def manifest():
        return FileResponse(ROOT / 'static/manifest.webmanifest', media_type='application/manifest+json')

    @router.get('/api/push/key')
    def public_key():
        return {'key': push.public_key}

    @router.post('/api/push/subscribe', status_code=201)
    def subscribe(body: Subscription, request: Request):
        user = request.state.user
        call_service(push.subscribe, user and user['id'], body.model_dump(), request.headers.get('user-agent', ''))
        return {'ok': True}

    @router.post('/api/push/unsubscribe')
    def unsubscribe(body: Endpoint):
        push.unsubscribe(body.endpoint)
        return {'ok': True}

    @router.post('/api/push/presence-status')
    def presence_status(body: Endpoint):
        return push.presence_settings(body.endpoint)

    @router.post('/api/push/presence')
    def presence(body: Presence):
        call_service(push.set_presence, body.endpoint, body.enabled, body.audience, body.quiet)
        return push.presence_settings(body.endpoint)

    @router.post('/api/push/topics-status')
    def topics_status(body: Endpoint):
        return push.topic_settings(body.endpoint)

    @router.post('/api/push/topics')
    def topics(body: Topics):
        call_service(push.set_topics, body.endpoint, body.enabled)
        return push.topic_settings(body.endpoint)

    @router.post('/api/push/test', status_code=201)
    def test(request: Request):
        user = request.state.user
        devices = push.devices(user and user['id'])
        if not devices:
            raise HTTPException(409, 'Ative as notificações neste aparelho primeiro.')
        push.notify({'id': 'push-test', 'kind': 'test', 'message': 'Se você viu esta notificação, o celular vai avisar sobre alertas.'})
        return {'devices': len(devices)}

    return router
