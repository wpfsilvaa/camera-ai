import asyncio
import base64
import hmac
import os
import re
import shutil
import time
import io
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from PIL import Image
import cv2
import numpy as np
from pydantic import BaseModel, Field

from .cameras import CameraManager
from .config import CLIPS, DATA, PEOPLE, ROOT, WA_URL, CameraSettings, ExtraCamera, Settings, config, gateway_token
from .db import Database
from .jobs import Jobs
from .offline import OfflineAnalysis
from .recognition import Recognition

db = Database()
recognition = Recognition(db)
cameras = CameraManager(db, config, recognition)
camera = cameras.get()  # Compatibility for the original single-camera API.
jobs = Jobs(db, config, recognition)
offline = OfflineAnalysis(db)


@asynccontextmanager
async def lifespan(app):
    db.recover()
    db.execute("UPDATE events SET camera_name=? WHERE camera_name='' AND camera_id='main'", (config.get().camera_name,))
    cameras.start()
    jobs.start()
    yield
    offline.cancel()
    cameras.stop()
    jobs.stop()


app = FastAPI(title='Casa Presente', lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware('http')
async def protect(request: Request, call_next):
    password = os.environ.get('DASHBOARD_PASSWORD', '')
    if password:
        try:
            scheme, encoded = request.headers.get('authorization', '').split(' ', 1)
            user, supplied = base64.b64decode(encoded, validate=True).decode().split(':', 1)
            valid = scheme.lower() == 'basic' and hmac.compare_digest(user, 'admin') and hmac.compare_digest(supplied.encode(), password.encode())
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            return Response(status_code=401, headers={'WWW-Authenticate': 'Basic realm="Casa Presente"'})
    # Prevent other sites from changing local settings through the browser.
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('x-casa-request') != '1':
            return JSONResponse({'detail': 'Requisição não autorizada.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return JSONResponse({'detail': 'Origem inválida.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/api/settings')
def get_settings(camera_id: str = 'main'):
    return recognition_action(config.for_camera, camera_id)


@app.put('/api/settings')
def save_settings(settings: Settings, camera_id: str = 'main'):
    if settings.whatsapp_enabled and not settings.recipient:
        raise HTTPException(422, 'Informe o número que receberá os vídeos.')
    old = recognition_action(config.for_camera, camera_id)
    if any(getattr(old,k) != getattr(settings,k) for k in ('recognition_enabled','face_threshold','face_margin','body_reid_enabled','body_memory_minutes','body_threshold','body_margin')):
        with recognition.lock, db.connect() as connection:
            recognition.invalidate(connection)
    recognition_action(config.save_for_camera, settings, camera_id)
    return config.for_camera(camera_id)


@app.get('/api/cameras')
def list_cameras():
    return {'cameras': cameras.snapshots()}


@app.post('/api/cameras', status_code=201)
def add_camera(body: CameraSettings):
    with config.lock:
        settings = config.get()
        if len(settings.cameras) >= 15:
            raise HTTPException(409, 'Limite de 16 câmeras cadastradas. A capacidade simultânea depende do computador.')
        new = ExtraCamera(**body.model_dump())
        settings.cameras.append(new)
        config.save(settings)
    cameras.sync()
    return {'id': new.id}


@app.delete('/api/cameras/{camera_id}')
def delete_camera(camera_id: str):
    recognition_action(cameras.remove, camera_id)
    return {'ok': True}


@app.post('/api/monitor/{action}')
def monitor(action: Literal['start', 'stop'], camera_id: str = 'main'):
    recognition_action(lambda: config.update_camera(camera_id, enabled=action == 'start'))
    return {'enabled': action == 'start'}


@app.post('/api/analysis/{action}')
def analysis_control(action: Literal['pause', 'resume'], camera_id: str = 'main'):
    recognition_action(config.for_camera, camera_id)
    if action == 'pause':
        job = offline.status()['event_id']
        if job is None or db.rows('SELECT id FROM events WHERE id=? AND camera_id=?', (job, camera_id)):
            offline.cancel()
    recognition_action(lambda: config.update_camera(camera_id, analysis_enabled=action == 'resume'))
    return {'analysis_enabled': action == 'resume'}


@app.post('/api/analysis-all/{action}')
def all_analysis_control(action: Literal['pause', 'resume']):
    if action == 'pause':
        offline.cancel()
    with config.lock:
        settings = config.get()
        settings.analysis_enabled = action == 'resume'
        for item in settings.cameras:
            item.analysis_enabled = action == 'resume'
        config.save(settings)
    return {'analysis_enabled': action == 'resume'}


@app.post('/api/recording/{action}')
def recording_control(action: Literal['start', 'stop'], camera_id: str = 'main'):
    worker = recognition_action(cameras.get, camera_id)
    return recognition_action(worker.request_recording,action=='start')


@app.post('/api/events/{event_id}/analyze')
def analyze_event(event_id: int):
    return recognition_action(offline.start,event_id)


@app.post('/api/offline/cancel')
def cancel_analysis():
    return offline.cancel()


async def gateway(method, path, payload=None):
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.request(method, WA_URL + path, headers=jobs.headers, json=payload)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        if path == '/status':
            return {'state': 'unavailable', 'qr': None, 'error': 'Serviço WhatsApp indisponível. Inicie com ./start.sh.'}
        raise HTTPException(503, 'Serviço WhatsApp indisponível.')


@app.get('/api/status')
async def status(camera_id: str = 'main'):
    worker = recognition_action(cameras.get, camera_id)
    storage = shutil.disk_usage(DATA)
    return {'camera': worker.snapshot(), 'cameras': cameras.snapshots(), 'whatsapp': await gateway('GET', '/status'),
            'recognition': worker.recognition.status(), 'offline': offline.status(),
            'stats': db.stats(), 'camera_stats': db.stats(camera_id), 'storage_free_gb': round(storage.free / 1024**3, 1), 'now': time.time()}


@app.get('/api/events')
def events(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), identity: Literal['all', 'father', 'other', 'unknown'] = 'all', camera_id: str | None = None):
    return db.history(limit, offset, identity, camera_id)


@app.get('/api/event-cameras')
def event_cameras():
    return db.rows('''SELECT e.camera_id AS id,e.camera_name AS name FROM events e
        JOIN (SELECT camera_id,MAX(id) AS last_id FROM events GROUP BY camera_id) last ON e.id=last.last_id''')


@app.get('/api/events/{event_id}')
def event_details(event_id: int):
    rows = db.rows('SELECT * FROM events WHERE id=?', (event_id,))
    if not rows:
        raise HTTPException(404, 'Registro não encontrado.')
    row = rows[0]
    row['clips'] = db.rows('SELECT * FROM clips WHERE event_id=? ORDER BY started', (event_id,))
    row['people'] = db.track_details(event_id) if row['kind']!='manual' or row['analysis_state']=='complete' else []
    row['probable_father'] = any(t['suggested_is_father'] and not t['reviewed'] for t in row['people'])
    return row


class Label(BaseModel):
    identity: Literal['father', 'other', 'unknown']
    note: str = Field(default='', max_length=500)


@app.patch('/api/events/{event_id}')
def label_event(event_id: int, label: Label):
    rows = db.rows('SELECT * FROM events WHERE id=?', (event_id,))
    if not rows:
        raise HTTPException(404, 'Registro não encontrado.')
    if rows[0]['analysis_state']=='running':
        raise HTTPException(409, 'Aguarde ou cancele a análise antes de confirmar.')
    if rows[0]['ended'] is None:
        raise HTTPException(409, 'Aguarde o fim deste registro para confirmar quem apareceu.')
    if db.rows('SELECT id FROM person_tracks WHERE event_id=? LIMIT 1', (event_id,)):
        raise HTTPException(409, 'Identifique cada pessoa nas imagens deste registro para ensinar corretamente.')
    db.execute('UPDATE events SET identity=?,note=? WHERE id=?', (label.identity, label.note, event_id))
    return {'ok': True}


class PersonName(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class PersonConfirmation(BaseModel):
    person_id: str | None = None
    sample_id: str | None = None


def recognition_action(fn, *args):
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.get('/api/people')
def people():
    return recognition.status()


@app.post('/api/people')
def create_person(body: PersonName):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'Informe um nome.')
    return {'id': recognition_action(recognition.create_person, name)}


@app.patch('/api/people/{person_id}')
def rename_person(person_id: str, body: PersonName):
    if not body.name.strip():
        raise HTTPException(422, 'Informe um nome.')
    recognition_action(recognition.rename_person, person_id, body.name.strip())
    return {'ok': True}


@app.delete('/api/people/{person_id}')
def delete_person(person_id: str):
    recognition_action(recognition.forget, person_id, True)
    return {'ok': True}


@app.post('/api/people/{person_id}/forget')
def forget_person(person_id: str):
    recognition_action(recognition.forget, person_id)
    return {'ok': True}


@app.get('/api/people/{person_id}/examples')
def person_examples(person_id: str):
    return recognition_action(recognition.examples, person_id)


@app.delete('/api/people/{person_id}/examples/{source}/{sample_id}')
def remove_person_example(person_id: str, source: Literal['history', 'upload'], sample_id: str):
    recognition_action(recognition.remove_example, person_id, source, sample_id)
    return {'ok': True}


@app.post('/api/people/{person_id}/faces')
async def enroll_face(person_id: str, request: Request):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(413, 'A foto deve ter até 8 MB.')
    try:
        with Image.open(io.BytesIO(content)) as photo:
            if photo.width * photo.height > 16_000_000:
                raise ValueError('Imagem muito grande.')
            photo.verify()
        image = cv2.imdecode(np.frombuffer(content,dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Imagem inválida.')
    except Exception:
        raise HTTPException(422, 'Envie uma foto JPEG ou PNG válida, com até 16 megapixels.')
    sample_id = await run_in_threadpool(recognition_action, recognition.enroll, person_id, image)
    return {'id': sample_id}


@app.delete('/api/people/{person_id}/faces/{sample_id}')
def delete_face(person_id: str, sample_id: str):
    recognition_action(recognition.remove_enrollment, person_id, sample_id)
    return {'ok': True}


@app.patch('/api/person-tracks/{track_id}')
def confirm_person(track_id: int, body: PersonConfirmation):
    recognition_action(recognition.confirm, track_id, body.person_id, body.sample_id)
    return {'ok': True}


@app.get('/people-media/{filename}')
def person_media(filename: str):
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', filename) or not (PEOPLE / filename).is_file():
        raise HTTPException(404)
    return FileResponse(PEOPLE / filename, media_type='image/jpeg')


@app.post('/api/whatsapp/connect')
async def connect_whatsapp():
    return await gateway('POST', '/connect')


@app.post('/api/clips/{clip_id}/retry')
async def retry(clip_id: str):
    rows = db.rows('SELECT * FROM clips WHERE id=?', (clip_id,))
    if not rows:
        raise HTTPException(404, 'Vídeo não encontrado.')
    row = rows[0]
    if row['state'] != 'ready' or row['delivery'] not in ('failed', 'uncertain', 'retry'):
        raise HTTPException(409, 'Este vídeo não está disponível para reenvio.')
    await gateway('POST', '/retry', {'clip_id': clip_id})
    db.execute("UPDATE clips SET delivery='pending',error=NULL,retry_at=0 WHERE id=?", (clip_id,))
    return {'ok': True}


@app.get('/media/{filename}')
def media(filename: str):
    if not re.fullmatch(r'[a-f0-9]{32}\.(mp4|jpg|analyzed\.mp4)', filename):
        raise HTTPException(404)
    path = CLIPS / filename
    if not path.is_file():
        raise HTTPException(404, 'Arquivo indisponível ou removido pela retenção.')
    return FileResponse(path, media_type='video/mp4' if filename.endswith('.mp4') else 'image/jpeg')


@app.get('/api/snapshot')
def snapshot(camera_id: str = 'main'):
    worker = recognition_action(cameras.get, camera_id)
    with worker.lock:
        jpeg = worker.jpeg
    if jpeg is None or worker.snapshot()['state'] != 'online':
        return Response(status_code=204)
    return Response(jpeg, media_type='image/jpeg')


@app.get('/api/stream.mjpeg')
async def stream(request: Request, camera_id: str = 'main'):
    worker = recognition_action(cameras.get, camera_id)
    async def frames():
        previous = -1
        while not await request.is_disconnected() and not worker.stop_event.is_set():
            with worker.lock:
                sequence, jpeg = worker.sequence, worker.jpeg
            if jpeg is not None and sequence != previous and worker.snapshot()['state'] == 'online':
                previous = sequence
                yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n'
            # Each viewer reads the latest frame; a slow client cannot queue old images.
            await asyncio.sleep(.005)
    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                             headers={'X-Accel-Buffering': 'no'})


app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
