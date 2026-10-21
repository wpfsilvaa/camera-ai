import asyncio
import json
import logging
import re
import shutil
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .alerts import Alerts, in_quiet_hours
from .auth import COOKIE, SAME_SITE, Auth
from .backup import Backups
from .cameras import CameraManager
from . import detectors, resources
from .sources import supports_light_video, usb_cameras
from .config import CLIPS, DATA, ROOT, WA_URL, CameraSettings, ExtraCamera, Settings, config
from .db import TZ, Database
from .pacing import Greeter, first_name, kiosk_night, screen_power_saving, vigia_state
from .jobs import Jobs
from .learning import LearningSuggestions
from .notebook import NotebookMonitor
from .avatars import MAX_BYTES as AVATAR_MAX, Avatars
from .fatherlog import FatherLog
from .journal import Journal
from .messages import MessagePlanner, PersonMessages
from .photos import Photos
from .weather import Weather, search as search_cities
from .reminders import Reminders
from .offline import OfflineAnalysis
from .proxy import allowed_origins, is_https
from .push import Push
from .recognition import Recognition
from .storage import Storage
from .street import StreetMode
from .cleanup import GalleryCleanup
from .viewers import Viewers
from .routes import cleanup as cleanup_routes, alerts as alert_routes, auth as auth_routes, backup as backup_routes, intercom as intercom_routes, people as people_routes, photos as photos_routes, push as push_routes, storage as storage_routes
from .services import call_service

db = Database()
recognition = Recognition(db)
cameras = CameraManager(db, config, recognition)
camera = cameras.get()  # Compatibility for the original single-camera API.
offline = OfflineAnalysis(db)
auth = Auth(db)
alerts = Alerts(db, config, cameras)
learning = LearningSuggestions(db, recognition, config)
gallery_cleanup = GalleryCleanup(db, recognition, config)
backups = Backups(db, config, alerts)
push = Push(db)
storage = Storage(db)
alerts.listeners.append(push.notify)
alerts.ringers.append(push.ring)
notebook = NotebookMonitor(alerts)
jobs = Jobs(db, config, recognition, alerts, auth, learning, backups, notebook)
cameras.fall_handler = alerts.fall
cameras.presence_handler = push.presence
cameras.restricted_handler = alerts.restricted
street = StreetMode()
viewers = Viewers()
cameras.viewer_count = viewers.count


def guard_house(camera_id, camera_name, stranger, now, make_jpeg):
    """A guarded camera reports whether an unknown person is in view; with Street mode on, a lasting stranger raises the alert."""
    if street.update(camera_id, stranger, now, config.get().street_delay_seconds):
        jpeg = make_jpeg()
        if jpeg:
            alerts.intruder(camera_id, camera_name, jpeg, now)


cameras.street_handler = guard_house


def latest_frame(camera_id):
    worker = cameras.get(camera_id)
    with worker.lock:
        return worker.jpeg


push.frame = latest_frame
notebook.frame = lambda: latest_frame('main')


log = logging.getLogger(__name__)
greeter = Greeter()
reminders = Reminders(db)
photos = Photos(db)
person_messages = PersonMessages(db)
journal = Journal(db)
father_log = FatherLog(db, DATA / 'visits')
cameras.visit_handler = father_log.record_visit
cameras.visit_time_handler = father_log.set_seconds
jobs.busy = lambda: any(c.get('people') for c in cameras.snapshots())
jobs.extra_cleanups.append(father_log.cleanup)
jobs.extra_cleanups.append(gallery_cleanup.purge)
push.sightings_today = father_log.count_today
avatars = Avatars()
weather = Weather(config)
greeted = {'id': None}   # Last greeting sent to the screen: its messages go out once.
message_planner = MessagePlanner(person_messages)
screen_state = {'until': 0}   # Until when the panel stays on after someone was in view (night, panel-off mode).
light_state = {'until': 0}    # Until when the night light stays on after someone was in view.
bright_state = {'until': 0}   # Until when the screen stays bright after someone was in view (night dimming).


def vigia_for_kitchen():
    """What the kitchen screen shows besides the call buttons: watch-mode state, night tone and a greeting."""
    settings, now = config.for_camera('main'), time.time()
    hour = datetime.fromtimestamp(now, TZ).hour
    camera = next((c for c in cameras.snapshots() if c['id'] == 'main'), {})
    info_night = kiosk_night(settings, hour)
    # Night light: while someone is in view at night (and for a while after), the screen glows softly instead of showing the UI or staying black.
    night_light = False
    if info_night and settings.kiosk_nightlight_enabled and notebook.call.get('state') not in ('ringing', 'answered'):
        if camera.get('people'):
            light_state['until'] = now + settings.kiosk_screen_off_after
        night_light = now < light_state['until']
    info = {'vigia': vigia_state(settings.sentinel_enabled, settings.sentinel_start_hour, settings.sentinel_end_hour, hour, bool(camera.get('sentinel')), settings.sentinel_always),
            'night': int(kiosk_night(settings, hour)),
            'watch': viewers.total(),
            # Only the "red tones" choice recolours the screen; with the panel off (or black) it shows its normal colours when on.
            'red': int(kiosk_night(settings, hour) and settings.kiosk_night_mode == 'red'),
            'cfg': json.dumps({'slide': settings.kiosk_slide_seconds, 'awake': settings.kiosk_awake_seconds, 'sound': settings.kiosk_sound_on,
                               'vol': {name: getattr(settings, f'kiosk_vol_{name}_{"night" if info_night else "day"}') for name in ('button', 'call', 'help', 'message')},
                               'calendar': settings.kiosk_calendar_enabled, 'framecal': settings.kiosk_frame_calendar, 'rain': settings.kiosk_weather_rain, 'speak': settings.kiosk_read_messages, 'voice': settings.kiosk_voice, 'hints': settings.kiosk_hints, 'black': settings.kiosk_night_mode == 'black', 'light': bool(night_light)}, ensure_ascii=False)}
    if settings.kiosk_dim_enabled:
        # Day: the day level. Night: very dim, but brighter while someone is in view (kept for a while after they leave).
        if camera.get('people') or notebook.call.get('state') in ('ringing', 'answered'):
            bright_state['until'] = now + settings.kiosk_bright_hold
        around = now < bright_state['until']
        info['bright'] = settings.kiosk_bright_day if not info['night'] else (settings.kiosk_bright_wake if around else settings.kiosk_bright_night)
        info['bright_wake'] = settings.kiosk_bright_wake if info['night'] else settings.kiosk_bright_day
        info['bright_hold'] = settings.kiosk_bright_hold
    if night_light:   # The light sets its own brightness, whatever the dimming choice.
        info['bright'] = info['bright_wake'] = settings.kiosk_nightlight_bright
        info['bright_hold'] = settings.kiosk_screen_off_after
    if screen_power_saving(settings, bool(info['night'])):
        # Panel switched off (at night with that look, or by day with the daytime option): on while someone is in view, on a call, or for a while after.
        if camera.get('people') or notebook.call.get('state') in ('ringing', 'answered'):
            screen_state['until'] = now + settings.kiosk_screen_off_after
        info['screen'] = 'off' if now >= screen_state['until'] else 'on'
        info['screen_hold'] = settings.kiosk_screen_off_after
    if settings.notebook_call_enabled:
        contacts = call_contacts()
        if contacts:
            info['callto'] = json.dumps([{'i': i, 'n': n} for i, n, _ in contacts], ensure_ascii=False)
    forecast = weather.current(settings)
    if forecast:
        info['weather'] = json.dumps(forecast, ensure_ascii=False)
    notes = reminders.active(now)
    if notes:
        info['reminders'] = json.dumps([{'i': n['id'][:8], 'a': first_name(n['author']), 't': n['text'], 'e': round(n['expires'])} for n in notes[:10]], ensure_ascii=False)
    people = {r['id']: r for r in db.rows("SELECT id,name,birthday FROM people WHERE birthday IS NOT NULL")}
    if people:   # Names and month-day only: the screen marks them on its calendar.
        info['bdays'] = json.dumps([{'n': first_name(p['name']), 'd': p['birthday'][5:]} for p in people.values()][:20], ensure_ascii=False)
    night_black = night_light or (bool(info['night']) and settings.kiosk_night_mode == 'black')
    if not night_black:   # A dark screen cannot show a greeting or a message, so nothing is consumed then.
        greeting = greeter.update(camera.get('tracks') or [], now, {i: p['birthday'] for i, p in people.items()} if settings.kiosk_birthdays_enabled else None, datetime.fromtimestamp(now, TZ).date())
        if greeting:
            info.update(greet=greeting['name'], greet_id=greeting['id'])
            if not config.get().notebook_greeting_enabled:
                info['greet_quiet'] = 1
            if greeting.get('birthday') and config.get().notebook_greeting_enabled:
                info.update(greet_kind='birthday', age=greeting['age'])
            elif greeting.get('daily') and settings.kiosk_daily_briefing and config.get().notebook_greeting_enabled:
                info.update(greet_kind='daily')
            if greeting['id'] != greeted['id']:
                waiting = person_messages.for_person(greeting['person'], now)
                if waiting:
                    info['greet_msgs'] = json.dumps([{'i': r['id'], 't': r['text'], 'a': first_name(r['author']), 's': int(r['single'])} for r in waiting[:5]], ensure_ascii=False)
                    info['_deliver'] = [r['id'] for r in waiting[:5]]
                    greeted['pending'], greeted['person'] = greeting['id'], greeting['person']   # Counted as sent only once the screen accepted them.
                else:
                    greeted['id'] = greeting['id']
            if info.get('greet_quiet') and 'greet_msgs' not in info:
                info.pop('greet'), info.pop('greet_id'), info.pop('greet_quiet')   # Greeting off and nothing to say.
        if 'greet' not in info:
            # No greeting is due (they were greeted recently), but someone recognised may have unread messages.
            planned = message_planner.pick(camera.get('tracks') or [], now)
            if planned:
                person, track, waiting = planned
                info.update(greet=first_name(track.get('name') or ''), greet_id=int(now), greet_quiet=1,
                            greet_msgs=json.dumps([{'i': r['id'], 't': r['text'], 'a': first_name(r['author']), 's': int(r['single'])} for r in waiting[:5]], ensure_ascii=False))
                info['_deliver'] = [r['id'] for r in waiting[:5]]
                greeted['pending'], greeted['person'] = None, person
    return info


notebook.vigia = vigia_for_kitchen


def remind_in_kitchen(camera_id, text):
    """The father went into a restricted area: a sound and a reminder on the kitchen screen (sent in the background, the camera loop must not wait)."""
    settings = config.get()
    night = kiosk_night(settings, datetime.now(TZ).hour)
    volume = getattr(settings, f'kiosk_vol_message_{"night" if night else "day"}')

    def send():
        try:
            notebook.send_test('nudge', volume, text)
        except Exception:
            log.warning('Não foi possível lembrar o pai na tela do notebook', exc_info=True)
    threading.Thread(target=send, daemon=True, name='kitchen-reminder').start()


cameras.reminder_handler = remind_in_kitchen


def screen_busy():
    """True while the kitchen screen should be refreshed quickly: someone is in view, a call is on, or a greeting just ran."""
    camera = next((c for c in cameras.snapshots() if c['id'] == 'main'), {})
    return bool(camera.get('people')) or notebook.call.get('state') in ('ringing', 'answered') or time.time() - greeter.last_any < 30


notebook.busy = screen_busy
notebook.photos = photos
notebook.callee_phone = lambda person_id: next((phone for i, _, phone in call_contacts() if i == person_id), None)
notebook.avatars = lambda: [(i, avatars.path(i) if avatars.has(i) else None, avatars.rev(i)) for i, _, _ in call_contacts()]


def messages_delivered(ids):
    person_messages.mark_shown(ids)
    if greeted.get('pending') is not None:
        greeted['id'] = greeted['pending']
    if greeted.get('person'):
        message_planner.delivered(greeted['person'], time.time())


notebook.delivered = messages_delivered
notebook.read = person_messages.mark_read
push.people = lambda camera_id: cameras.get(camera_id).snapshot()['tracks']


def quiet_now(now):
    settings = config.get()
    return in_quiet_hours(datetime.fromtimestamp(now, TZ).hour, settings.quiet_start_hour, settings.quiet_end_hour)


push.quiet = quiet_now


@asynccontextmanager
async def lifespan(app):
    db.recover()
    db.execute("UPDATE events SET camera_name=? WHERE camera_name='' AND camera_id='main'", (config.get().camera_name,))
    cameras.start()
    jobs.start()
    resources.monitor.start()
    weather.start()
    yield
    weather.stop()
    resources.monitor.stop()
    offline.cancel()
    cameras.stop()
    jobs.stop()


app = FastAPI(title='Casa Presente', lifespan=lifespan, docs_url=None, redoc_url=None)


PUBLIC = {
    '/login', '/api/auth/me', '/api/auth/login', '/api/health',
    '/static/login.css', '/static/login.js', '/static/theme.js', '/static/favicon.svg', '/static/offline.html',
    # Installable app files carry no personal data and are fetched without cookies.
    '/sw.js', '/manifest.webmanifest', '/static/icon-192.png', '/static/icon-512.png', '/static/icon-maskable.png',
}
# Family accounts are read-only; these (their own password and devices) are the only changes they may make.
FAMILY_WRITES = {'/api/street', '/api/auth/logout', '/api/auth/password', '/api/auth/profile', '/api/push/subscribe', '/api/push/unsubscribe', '/api/push/test',
                 '/api/push/presence-status', '/api/push/presence', '/api/push/topics-status', '/api/push/topics', '/api/notebook/call/answer', '/api/notebook/call/end',
                 '/api/intercom/listen', '/api/intercom/talk', '/api/intercom/video', '/api/intercom/face', '/api/intercom/hangup'}


@app.middleware('http')
async def protect(request: Request, call_next):
    login_required, request.state.user = await run_in_threadpool(auth.current, request.cookies.get(COOKIE))
    if login_required:
        path = request.url.path
        if request.state.user is None and path not in PUBLIC:
            if request.method == 'GET' and path == '/':
                # Keep a notification link (?camera=…&call=1) across the login.
                query = request.url.query
                return RedirectResponse(f'/login?next={quote("/?" + query)}' if query else '/login', status_code=303)
            return JSONResponse({'detail': 'Entre novamente para continuar.'}, status_code=401)
        user = request.state.user
        if user and user['role'] != 'admin':
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and path not in FAMILY_WRITES and not path.startswith(('/api/reminders', '/api/photos', '/api/messages', '/api/journal')) or path.startswith(('/api/users', '/api/backup', '/api/learning', '/api/cleanup', '/api/storage')):
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
def index(request: Request):
    response = FileResponse(ROOT / 'static/index.html')
    # Re-issue the session cookie with the current SameSite policy (older logins used Strict).
    token = request.cookies.get(COOKIE)
    valid, max_age = auth.cookie_lifetime(token)
    if valid:
        response.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite=SAME_SITE, secure=is_https(request), path='/')
    return response


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
    weather.poke()
    # Start fetching/converting the chosen detector now, even if the camera is stopped.
    detectors.prepare(settings.detector_model, settings.detector_engine, settings.fall_detection_enabled, settings.detection_size, retry=True)
    return config.for_camera(camera_id)


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    hours: int = Field(ge=1, le=24 * 14)


def reminder_view(row, user):
    return {'id': row['id'], 'author': row['author'], 'text': row['text'], 'created': row['created'], 'expires': row['expires'],
            'mine': bool(user) and (user['role'] == 'admin' or user['id'] == row['user_id'])}


@app.get('/api/reminders')
def list_reminders(request: Request):
    return {'reminders': [reminder_view(r, request.state.user) for r in reminders.active()]}


@app.post('/api/reminders')
def add_reminder(body: ReminderIn, request: Request):
    user = request.state.user
    call_service(reminders.add, user['name'] if user else 'Casa', user['id'] if user else None, body.text, body.hours)
    return {'reminders': [reminder_view(r, user) for r in reminders.active()]}


@app.delete('/api/reminders/{reminder_id}')
def delete_reminder(reminder_id: str, request: Request):
    user = request.state.user
    try:
        reminders.delete(reminder_id, user['id'] if user else None, bool(user) and user['role'] == 'admin' or not user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True}


def call_contacts():
    """People with a WhatsApp number get their own call button on the kitchen screen: [(id, first name, phone)], oldest first."""
    rows = db.rows('SELECT id,name,phone FROM people WHERE phone IS NOT NULL AND is_father=0 ORDER BY created LIMIT 4')
    return [(r['id'], first_name(r['name']), r['phone']) for r in rows]


@app.post('/api/people/{person_id}/photo')
async def upload_person_photo(person_id: str, request: Request):
    if not db.rows('SELECT 1 FROM people WHERE id=? AND is_father=0', (person_id,)):
        raise HTTPException(404, 'Pessoa não encontrada.')
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > AVATAR_MAX:
            raise HTTPException(413, 'A foto deve ter até 8 MB.')
    try:
        await run_in_threadpool(avatars.save, person_id, bytes(content))
    except Exception:
        raise HTTPException(422, 'Envie uma foto JPEG ou PNG válida.')
    return {'ok': True}


@app.delete('/api/people/{person_id}/photo')
def delete_person_photo(person_id: str):
    avatars.delete(person_id)
    return {'ok': True}


@app.get('/avatar-media/{person_id}.jpg')
def avatar_media(person_id: str):
    if not avatars.has(person_id):
        raise HTTPException(404)
    return FileResponse(avatars.path(person_id), media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=300'})


class StreetSwitch(BaseModel):
    armed: bool


@app.get('/api/street')
def street_state():
    settings = config.get()
    guards = [settings.camera_name] if settings.street_guard else []
    guards += [c.camera_name for c in settings.cameras if c.street_guard]
    return {**street.state(), 'guards': guards, 'delay': settings.street_delay_seconds, 'recognition': settings.recognition_enabled}


@app.put('/api/street')
def street_switch(body: StreetSwitch):
    if body.armed and not street_state()['guards']:
        raise HTTPException(409, 'Marque ao menos uma câmera para vigiar a casa (Configurações → Câmera → Vigiar a casa no Modo rua).')
    return street.set(body.armed)


class VisitVerdict(BaseModel):
    father: bool


@app.get('/api/father/visits')
def father_visits():
    return father_log.pending()


@app.post('/api/father/visits/{visit_id}')
def father_visit_verdict(visit_id: int, body: VisitVerdict):
    call_service(father_log.decide, visit_id, body.father)
    return {'ok': True}


@app.get('/api/father/calibration')
def father_calibration():
    return father_log.calibration(config.get().restricted_min_seconds)


@app.get('/visit-media/{filename}')
def visit_media(filename: str):
    match = re.fullmatch(r'visit-(\d{1,12})\.jpg', filename)
    path = father_log.photo_path(match[1]) if match else None
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type='image/jpeg')


@app.get('/api/father/today')
def father_today():
    return father_log.summary()


class JournalIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    tag: str = Field(default='geral', pattern='^(geral|saude|humor|remedio)$')


def journal_view(row, user):
    return {'id': row['id'], 'author': row['author'], 'text': row['text'], 'tag': row['tag'], 'created': row['created'],
            'mine': not user or user['role'] == 'admin' or user['id'] == row['user_id']}


@app.get('/api/journal')
def list_journal(request: Request, before: float | None = None):
    rows = journal.list(before)
    return {'notes': [journal_view(r, request.state.user) for r in rows], 'more': len(rows) >= 50}


@app.post('/api/journal')
def add_journal(body: JournalIn, request: Request):
    user = request.state.user
    call_service(journal.add, user['name'] if user else 'Casa', user['id'] if user else None, body.text, body.tag)
    return {'notes': [journal_view(r, user) for r in journal.list()]}


@app.delete('/api/journal/{note_id}')
def delete_journal(note_id: str, request: Request):
    user = request.state.user
    try:
        journal.delete(note_id, user['id'] if user else None, not user or user['role'] == 'admin')
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True}


class MessageIn(BaseModel):
    to_person: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=240)
    hours: int = Field(ge=1, le=24 * 90)
    mode: str = Field(default='read', pattern='^(read|always|single)$')   # until read, every time, or view-once


def message_view(row, user):
    """A message as its author sees it; nobody else gets to list it (it is shown only to the recipient, on the screen)."""
    return {'id': row['id'], 'to_person': row['to_person'], 'to_name': row['to_name'], 'author': row['author'], 'text': row['text'], 'created': row['created'],
            'expires': row['expires'], 'once': bool(row['once']), 'single': bool(row['single']), 'shown': row['shown'], 'last_shown': row['last_shown'], 'read_at': row['read_at'],
            'mine': True}


@app.get('/api/messages')
def list_messages(request: Request):
    user = request.state.user
    return {'messages': [message_view(r, user) for r in person_messages.active(only_user=user['id'] if user else None)]}


@app.post('/api/messages')
def add_message(body: MessageIn, request: Request):
    user = request.state.user
    call_service(person_messages.add, user['name'] if user else 'Casa', user['id'] if user else None, body.to_person, body.text, body.hours, body.mode != 'always', None, body.mode == 'single')
    return {'messages': [message_view(r, user) for r in person_messages.active(only_user=user['id'] if user else None)]}


@app.delete('/api/messages/{message_id}')
def delete_message(message_id: str, request: Request):
    user = request.state.user
    try:
        person_messages.delete(message_id, user['id'] if user else None, not user)   # Only the author (no login: single-user setup).
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True}


class KioskTest(BaseModel):
    sound: str = Field(pattern='^(press|ring|help|message|nudge|brightness|screenoff|rain|voice)$')
    voice: str = Field(default='', pattern='^(faber|cadu|jeff|edresson|)$')
    volume: int = Field(ge=0, le=100)
    text: str = Field(default='', max_length=160)   # The reminder shown by the "nudge" test.


@app.post('/api/kiosk/test')
def kiosk_test(body: KioskTest, request: Request):
    """Play a sound (or a sample message) on the kitchen screen at the given volume, to tune the settings."""
    user = request.state.user
    text = 'Esta é uma mensagem de teste.' if body.sound == 'message' else body.text.strip() or 'Este é um lembrete de teste.' if body.sound == 'nudge' else 'Bom dia! Hoje o dia vai ser nublado, com máxima de vinte e oito graus. Leve o guarda-chuva se for sair.' if body.sound == 'voice' else ''
    call_service(notebook.send_test, body.sound, body.volume, text, body.voice)
    return {'ok': True, 'from': first_name(user['name']) if user else ''}


@app.get('/api/weather/search')
def weather_search(q: str = Query('', max_length=60)):
    """Cities matching the text, to pick the one whose forecast the screen shows."""
    try:
        return {'cities': search_cities(q)}
    except Exception:
        raise HTTPException(503, 'Não foi possível buscar cidades agora. Confira a internet do servidor.')


@app.get('/api/weather')
def weather_now():
    """What the screen is showing: the cached forecast, so the settings can preview it."""
    settings = config.get()
    return {'enabled': settings.kiosk_weather_enabled, 'city': settings.kiosk_weather_city, 'data': weather.current(settings), 'error': weather.error}


@app.get('/api/resources')
def resource_usage(minutes: int = Query(30, ge=5, le=60)):
    return resources.monitor.snapshot(minutes)


@app.get('/api/cameras/usb')
def usb_camera_list():
    return {'cameras': usb_cameras()}


@app.get('/api/detectors')
def detector_catalog():
    return detectors.catalog()


@app.get('/api/detectors/state')
def detector_state(model: str = Query('n', pattern='^[nsml]$'), engine: str = Query('pytorch', pattern='^(pytorch|onnx|openvino|openvino-int8)$'),
                   size: int = Query(640, ge=320, le=1280, multiple_of=32), pose: bool = False):
    return detectors.state(model, engine, pose, size)


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
    return {'camera': {**worker.snapshot(), 'light_video': supports_light_video(worker.config.get().camera_source)}, 'cameras': cameras.snapshots(), 'whatsapp': whatsapp,
            'recognition': worker.recognition.status(), 'offline': offline.status(),
            'stats': db.stats(), 'camera_stats': db.stats(camera_id), 'alerts': alerts.recent(5), 'notebook': notebook.status(), 'storage_free_gb': round(storage.free / 1024**3, 1), 'now': time.time()}


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
    person_id: str | None = Field(default=None, max_length=64)


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
    if label.person_id and not db.rows('SELECT 1 FROM people WHERE id=? AND (is_father=1)=(?=\'father\')', (label.person_id, label.identity)):
        raise HTTPException(422, 'Pessoa inválida para esta identificação.')
    db.execute('UPDATE events SET identity=?,note=?,person_id=? WHERE id=?', (label.identity, label.note, label.person_id, event_id))
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
        with viewers.watch(camera_id):
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


def author_renamed(user_id, name):
    """Photos and reminders keep the author's name as text: follow the account when it is renamed."""
    for table in ('photos', 'reminders'):
        db.execute(f'UPDATE {table} SET author=? WHERE user_id=?', (name[:60], user_id))


app.include_router(auth_routes.build(auth, on_profile=author_renamed))
app.include_router(people_routes.build(recognition, learning, on_forget=avatars.delete))
app.include_router(cleanup_routes.build(gallery_cleanup))
app.include_router(alert_routes.build(alerts, config))
app.include_router(backup_routes.build(backups))
app.include_router(intercom_routes.build(config))
app.include_router(push_routes.build(push))
app.include_router(alert_routes.build_notebook(notebook))
app.include_router(storage_routes.build(storage))
app.include_router(photos_routes.build(photos))
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
