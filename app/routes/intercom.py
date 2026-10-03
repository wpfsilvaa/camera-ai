import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import call_service

# MediaMTX on the camera computer: "mic" is its echo-cancelled microphone, "talk" plays on its speaker.
WEBRTC_PORT = 8889
PATHS = {'listen': ('mic', 'whep'), 'talk': ('talk', 'whip')}
SESSION = re.compile(r'^[0-9a-f-]{36}$')


class Offer(BaseModel):
    camera_id: str = Field('main', max_length=40)
    sdp: str = Field(max_length=20000)


class Hangup(BaseModel):
    camera_id: str = Field('main', max_length=40)
    kind: str = Field(pattern='^(listen|talk)$')
    session: str = Field(pattern=SESSION.pattern)


def http_client(timeout):
    return httpx.AsyncClient(timeout=timeout)


def camera_host(source):
    """The intercom lives on the same computer that serves the RTSP camera."""
    parts = urlsplit(source)
    if parts.scheme not in ('rtsp', 'rtsps') or not parts.hostname:
        raise ValueError('A conversa ao vivo só funciona com câmeras RTSP de um computador com o MediaMTX.')
    host = parts.hostname
    return f'[{host}]' if ':' in host else host


def build(config):
    """Two-way audio with the camera computer, proxied so only logged-in users can reach its speaker."""
    router = APIRouter()

    def base_url(camera_id):
        settings = call_service(config.for_camera, camera_id)
        return f'http://{call_service(camera_host, settings.camera_source)}:{WEBRTC_PORT}'

    async def negotiate(kind, body):
        path, protocol = PATHS[kind]
        url = f'{base_url(body.camera_id)}/{path}/{protocol}'
        try:
            async with http_client(8) as client:
                response = await client.post(url, content=body.sdp, headers={'Content-Type': 'application/sdp'})
        except httpx.HTTPError:
            raise HTTPException(502, 'O computador da câmera não respondeu. Confira se ele está ligado e com o MediaMTX ativo.')
        if response.status_code == 400 and kind == 'talk':
            raise HTTPException(409, 'Outra pessoa já está falando com este ambiente. Tente de novo em instantes.')
        if response.status_code == 404:
            raise HTTPException(502, 'O microfone deste ambiente não está configurado no MediaMTX.')
        if response.status_code != 201:
            raise HTTPException(502, f'O computador da câmera recusou a chamada (código {response.status_code}).')
        session = response.headers.get('location', '').rstrip('/').rsplit('/', 1)[-1]
        return {'sdp': response.text, 'session': session if SESSION.match(session) else None}

    @router.post('/api/intercom/listen', status_code=201)
    async def listen(body: Offer):
        return await negotiate('listen', body)

    @router.post('/api/intercom/talk', status_code=201)
    async def talk(body: Offer):
        return await negotiate('talk', body)

    @router.post('/api/intercom/hangup')
    async def hangup(body: Hangup):
        path, protocol = PATHS[body.kind]
        try:
            async with http_client(4) as client:
                await client.delete(f'{base_url(body.camera_id)}/{path}/{protocol}/{body.session}')
        except httpx.HTTPError:
            pass  # MediaMTX also closes the session when the browser stops sending media.
        return {'ok': True}

    return router
