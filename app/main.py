import asyncio
import re
import shutil
import time
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .alerts import Alerts
from .auth import COOKIE, Auth
from .backup import Backups
from .cameras import CameraManager
from .config import CLIPS, DATA, ROOT, WA_URL, CameraSettings, ExtraCamera, Settings, config
from .db import Database
from .jobs import Jobs
from .learning import LearningSuggestions
from .offline import OfflineAnalysis
from .proxy import allowed_origins
from .push import Push
from .recognition import Recognition
from .storage import Storage
from .routes import alerts as alert_routes, auth as auth_routes, backup as backup_routes, intercom as intercom_routes, people as people_routes, push as push_routes, storage as storage_routes
from .services import call_service

db = Database()
recognition = Recognition(db)
cameras = CameraManager(db, config, recognition)
camera = cameras.get()  # Compatibility for the original single-camera API.
offline = OfflineAnalysis(db)
auth = Auth(db)
alerts = Alerts(db, config, cameras)
learning = LearningSuggestions(db, recognition, config)
backups = Backups(db, config, alerts)
push = Push(db)
storage = Storage(db)
alerts.listeners.append(push.notify)
jobs = Jobs(db, config, recognition, alerts, auth, learning, backups)
cameras.fall_handler = alerts.fall
cameras.presence_handler = push.presence


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


PUBLIC = {
    '/login', '/api/auth/me', '/api/auth/login', '/api/health',
    '/static/login.css', '/static/login.js', '/static/favicon.svg', '/static/offline.html',
    # Installable app files carry no personal data and are fetched without cookies.
    '/sw.js', '/manifest.webmanifest', '/static/icon-192.png', '/static/icon-512.png', '/static/icon-maskable.png',
}
# Family accounts are read-only; these (their own password and devices) are the only changes they may make.
FAMILY_WRITES = {'/api/auth/logout', '/api/auth/password', '/api/push/subscribe', '/api/push/unsubscribe', '/api/push/test',
                 '/api/push/presence-status', '/api/push/presence',
                 '/api/intercom/listen', '/api/intercom/talk', '/api/intercom/hangup'}


@app.middleware('http')
async def protect(request: Request, call_next):
    login_required, request.state.user = await run_in_threadpool(auth.current, request.cookies.get(COOKIE))
    if login_required:
        path = request.url.path
        if request.state.user is None and path not in PUBLIC:
            if request.method == 'GET' and path == '/':
                return RedirectResponse('/login', status_code=303)
            return JSONResponse({'detail': 'Entre novamente para continuar.'}, status_code=401)
        user = request.state.user
        if user and user['role'] != 'admin':
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and path not in FAMILY_WRITES or path.startswith(('/api/users', '/api/backup', '/api/learning', '/api/storage')):
                return JSONResponse({'detail': 'Seu acesso é somente para visualização. Peça a um administrador.'}, status_code=403)
    # Prevent other sites from changing local settings through the browser.
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('x-casa-request') != '1':
            return JSONResponse({'detail': 'Requisição não autorizada.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin not in allowed_origins(request):
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
def get_settings(request: Request, camera_id: str = 'main'):
    settings = call_service(config.for_camera, camera_id)
    user = request.state.user
    if user and user['role'] != 'admin':
        # Camera addresses may carry passwords; phone numbers stay with administrators.
        return settings.model_dump() | {'camera_source': '', 'recipient': '', 'additional_recipients': [], 'cameras': []}
    return settings


@app.put('/api/settings')
def save_settings(settings: Settings, camera_id: str = 'main'):
    if settings.whatsapp_enabled and not settings.delivery_targets():
        raise HTTPException(422, 'Informe o número que receberá os vídeos.')
    old = call_service(config.for_camera, camera_id)
    if any(getattr(old,k) != getattr(settings,k) for k in ('recognition_enabled','face_threshold','face_margin','body_reid_enabled','body_memory_minutes','body_threshold','body_margin')):
        with recognition.lock, db.connect() as connection:
            recognition.invalidate(connection)
    call_service(config.save_for_camera, settings, camera_id)
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
    call_service(cameras.remove, camera_id)
    return {'ok': True}


@app.post('/api/monitor/{action}')
def monitor(action: Literal['start', 'stop'], camera_id: str = 'main'):
    call_service(lambda: config.update_camera(camera_id, enabled=action == 'start'))
    return {'enabled': action == 'start'}


@app.post('/api/analysis/{action}')
def analysis_control(action: Literal['pause', 'resume'], camera_id: str = 'main'):
    call_service(config.for_camera, camera_id)
    if action == 'pause':
        job = offline.status()['event_id']
        if job is None or db.rows('SELECT id FROM events WHERE id=? AND camera_id=?', (job, camera_id)):
            offline.cancel()
    call_service(lambda: config.update_camera(camera_id, analysis_enabled=action == 'resume'))
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
    worker = call_service(cameras.get, camera_id)
    return call_service(worker.request_recording,action=='start')


@app.post('/api/events/{event_id}/analyze')
def analyze_event(event_id: int):
    return call_service(offline.start,event_id)


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
async def status(request: Request, camera_id: str = 'main'):
    worker = call_service(cameras.get, camera_id)
    storage = shutil.disk_usage(DATA)
    whatsapp = await gateway('GET', '/status')
    if request.state.user and request.state.user['role'] != 'admin':
        whatsapp = {**whatsapp, 'qr': None}  # Scanning the QR code would link another phone.
    return {'camera': worker.snapshot(), 'cameras': cameras.snapshots(), 'whatsapp': whatsapp,
            'recognition': worker.recognition.status(), 'offline': offline.status(),
            'stats': db.stats(), 'camera_stats': db.stats(camera_id), 'alerts': alerts.recent(5), 'storage_free_gb': round(storage.free / 1024**3, 1), 'now': time.time()}


@app.get('/api/health')
async def health():
    """Minimal component status for uptime monitors; carries no personal data."""
    snapshots = cameras.snapshots()
    whatsapp = (await gateway('GET', '/status'))['state']
    free_gb = round(shutil.disk_usage(DATA).free / 1024**3, 1)
    active = [c for c in snapshots if c['enabled']]
    ok = all(c['state'] == 'online' for c in active) and free_gb >= config.get().min_free_gb
    return JSONResponse({'ok': ok, 'whatsapp': whatsapp, 'disk_free_gb': free_gb,
                         'cameras': [{'id': c['id'], 'state': c['state'] if c['enabled'] else 'paused'} for c in snapshots]},
                        status_code=200 if ok else 503)


@app.get('/api/events')
def events(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), identity: Literal['all', 'father', 'other', 'unknown'] = 'all', camera_id: str | None = None):
    return db.history(limit, offset, identity, camera_id)


@app.get('/api/event-cameras')
def event_cameras():
    return db.rows('''SELECT e.camera_id AS id,e.camera_name AS name FROM events e
        JOIN (SELECT camera_id,MAX(id) AS last_id FROM events GROUP BY camera_id) last ON e.id=last.last_id''')


@app.get('/api/events/{event_id}')
def event_details(event_id: int):
    event = db.event(event_id)
    if event is None:
        raise HTTPException(404, 'Registro não encontrado.')
    return event


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


@app.post('/api/whatsapp/connect')
async def connect_whatsapp():
    return await gateway('POST', '/connect')


RETRYABLE = ('failed', 'uncertain', 'retry')


@app.post('/api/clips/{clip_id}/retry')
async def retry(clip_id: str, recipient: str | None = None):
    rows = db.rows('SELECT * FROM clips WHERE id=?', (clip_id,))
    if not rows:
        raise HTTPException(404, 'Vídeo não encontrado.')
    clip = rows[0]
    if clip['state'] != 'ready':
        raise HTTPException(409, 'Este vídeo não está disponível para reenvio.')
    deliveries = db.rows('SELECT * FROM clip_deliveries WHERE clip_id=?', (clip_id,))
    if not deliveries:
        # Clips queued before per-recipient deliveries existed.
        if clip['delivery'] not in RETRYABLE:
            raise HTTPException(409, 'Este vídeo não está disponível para reenvio.')
        await gateway('POST', '/retry', {'clip_id': clip_id})
        db.execute("UPDATE clips SET delivery='pending',error=NULL,retry_at=0 WHERE id=?", (clip_id,))
        return {'ok': True}
    retryable = [d for d in deliveries if d['delivery'] in RETRYABLE and recipient in (None, d['recipient'])]
    if not retryable:
        raise HTTPException(409, 'Nenhum envio com falha para este destinatário.')
    for target in retryable:
        await gateway('POST', '/retry', {'clip_id': clip_id, 'recipient': target['recipient']})
        db.execute("""UPDATE clip_deliveries SET delivery='pending',error=NULL,retry_at=0
            WHERE clip_id=? AND recipient=? AND delivery IN ('failed','uncertain','retry')""", (clip_id, target['recipient']))
    db.aggregate_delivery(clip_id)
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
    worker = call_service(cameras.get, camera_id)
    with worker.lock:
        jpeg = worker.jpeg
    if jpeg is None or worker.snapshot()['state'] != 'online':
        return Response(status_code=204)
    return Response(jpeg, media_type='image/jpeg')


@app.get('/api/stream.mjpeg')
async def stream(request: Request, camera_id: str = 'main'):
    worker = call_service(cameras.get, camera_id)
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


app.include_router(auth_routes.build(auth))
app.include_router(people_routes.build(recognition, learning))
app.include_router(alert_routes.build(alerts, config))
app.include_router(backup_routes.build(backups))
app.include_router(intercom_routes.build(config))
app.include_router(push_routes.build(push))
app.include_router(storage_routes.build(storage))
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
