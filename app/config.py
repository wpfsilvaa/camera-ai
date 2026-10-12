import json
import os
import secrets
import threading
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from .sources import local_device

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DATA = Path(os.environ.get('CAMERA_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
CLIPS = DATA / 'clips'
CLIPS.mkdir(exist_ok=True)
MODEL = os.environ.get('YOLO_MODEL', str(ROOT / 'yolo26n.pt'))
# Same person detection plus body keypoints; used when fall detection is on.
POSE_MODEL = os.environ.get('POSE_MODEL', str(ROOT / 'yolo26n-pose.pt'))
FACE_DETECTOR = os.environ.get('FACE_DETECTOR', str(ROOT / 'face_detection_yunet_2023mar.onnx'))
FACE_ENCODER = os.environ.get('FACE_ENCODER', str(ROOT / 'face_recognition_sface_2021dec.onnx'))
BODY_ENCODER = os.environ.get('REID_MODEL', str(ROOT / 'yolo26n-reid.onnx'))
PEOPLE = DATA / 'people'
PEOPLE.mkdir(exist_ok=True)
WA_URL = f"http://127.0.0.1:{int(os.environ.get('WA_PORT', '3001'))}"


class CameraSettings(BaseModel):
    camera_source: str = '0'
    camera_name: str = Field(default='Nova câmera', min_length=1, max_length=60)
    enabled: bool = False
    analysis_enabled: bool = True
    device: str = 'auto'
    # Person detector: YOLO26 size (n/s/m/l) and the engine that runs it; see app/detectors.py.
    detector_model: str = 'n'
    detector_engine: str = 'pytorch'
    detection_size: int = Field(default=640, ge=320, le=1280, multiple_of=32)
    detection_fps: int = Field(default=30, ge=1, le=30)
    # Analysis rate while nobody is around; goes back to detection_fps when someone appears.
    idle_detection_fps: int = Field(default=15, ge=1, le=30)
    # Watch mode: within the hours below, and while nobody is around, the camera is read at a low frame
    # rate and only motion wakes the analysis. People are still confirmed by the detector before any notice.
    sentinel_enabled: bool = False
    sentinel_always: bool = False   # Watch mode all day long, not only within the hours below.
    sentinel_start_hour: int = Field(default=22, ge=0, le=23)
    sentinel_end_hour: int = Field(default=6, ge=0, le=23)
    sentinel_fps: int = Field(default=5, ge=1, le=15)
    # Skip the YOLO model on an empty, motionless room (a full analysis still runs every couple of seconds).
    motion_gate: bool = True
    preview_width: int = Field(default=1280, ge=640, le=1920)
    recording_width: int = Field(default=1920, ge=640, le=1920)
    confidence: float = Field(default=0.5, ge=0.2, le=0.95)
    absence_seconds: float = Field(default=8, ge=2, le=120)
    min_presence_seconds: float = Field(default=1, ge=0.25, le=10)
    # Record the camera computer's microphone (MediaMTX "mic" path) with each clip.
    record_audio: bool = True
    segment_seconds: int = Field(default=60, ge=10, le=180)
    fps: int = Field(default=30, ge=5, le=30)
    # Normalized [x1, y1, x2, y2] areas (bed, sofa) where lying down is expected.
    fall_zones: list[list[float]] = Field(default_factory=list, max_length=10)
    # Restricted mode: video is recorded only while a watched person is inside one of these areas.
    restricted_enabled: bool = False
    restricted_zones: list[list[float]] = Field(default_factory=list, max_length=10)
    restricted_who: str = 'father'
    restricted_zone_names: list[str] = Field(default_factory=list, max_length=10)   # Name of each restricted area, by position ("Geladeira", "Armário").
    restricted_alert: bool = False
    # Restricted mode: send its alert and videos by WhatsApp too. Off = web-app notifications only.
    restricted_whatsapp: bool = True
    # Restricted mode: when the father is recognised going into the area, the kitchen screen plays a sound and shows this reminder.
    # Street mode: this camera watches the house; an unknown person on it raises the intruder alert while the mode is on.
    street_guard: bool = False
    restricted_pause_with_family: bool = True   # No alert or reminder while a registered person who is not monitored is in view (they are looking after the father).
    restricted_reminder: bool = False
    restricted_reminder_text: str = Field(default='Atenção com a glicose. Pense antes de pegar algo na geladeira.', max_length=160)

    @field_validator('camera_source')
    @classmethod
    def text_valid(cls, value):
        value = value.strip()
        if not value or len(value) > 2048:
            raise ValueError('Informe um nome e endereço válidos para a câmera.')
        local_device(value)  # Validates the optional ?WxH@fps of a USB camera.
        if '://' in value and not value.startswith(('rtsp://', 'rtsps://', 'http://', 'https://')):
            raise ValueError('Protocolo de câmera inválido.')
        return value

    @field_validator('camera_name')
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Informe o nome da câmera.')
        return value

    @field_validator('fall_zones', 'restricted_zones')
    @classmethod
    def zones_valid(cls, zones):
        for zone in zones:
            if len(zone) != 4 or not all(0 <= v <= 1 for v in zone) or zone[0] >= zone[2] or zone[1] >= zone[3]:
                raise ValueError('Área marcada inválida.')
        return [[round(v, 4) for v in zone] for zone in zones]

    @field_validator('restricted_zone_names')
    @classmethod
    def zone_names_valid(cls, names):
        return [''.join(ch for ch in str(name) if ch.isprintable()).strip()[:30] for name in names]

    @field_validator('restricted_who')
    @classmethod
    def who_valid(cls, value):
        if value not in ('father', 'father_or_unknown', 'anyone'):
            raise ValueError('Escolha quem ativa a área restrita.')
        return value

    @field_validator('detector_model')
    @classmethod
    def detector_model_valid(cls, value):
        if value not in ('n', 's', 'm', 'l'):
            raise ValueError('Escolha um modelo de detecção da lista.')
        return value

    @field_validator('detector_engine')
    @classmethod
    def detector_engine_valid(cls, value):
        if value not in ('pytorch', 'onnx', 'openvino', 'openvino-int8'):
            raise ValueError('Escolha um motor de detecção da lista.')
        return value

    @field_validator('device')
    @classmethod
    def device_valid(cls, value):
        if value not in ('auto', 'cuda', 'cpu'):
            raise ValueError('Escolha auto, cuda ou cpu.')
        return value


class ExtraCamera(CameraSettings):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r'^[a-f0-9]{32}$')


CAMERA_FIELDS = set(CameraSettings.model_fields)


class Settings(CameraSettings):
    schema_version: int = 2
    camera_source: str = os.environ.get('CAMERA_SOURCE', 'rtsp://192.168.1.103:8554/cam')
    camera_name: str = Field(default='Cozinha', min_length=1, max_length=60)
    recipient: str = ''
    additional_recipients: list[str] = Field(default_factory=list, max_length=9)
    recipient_since: dict[str,float] = Field(default_factory=dict)
    whatsapp_enabled: bool = False
    father_only: bool = True
    recognition_enabled: bool = True
    recognition_threshold: float = Field(default=0.85, ge=0.65, le=0.99)
    face_threshold: float = Field(default=0.50, ge=0.35, le=0.95)
    face_margin: float = Field(default=0.08, ge=0.02, le=0.30)
    body_reid_enabled: bool = True
    body_memory_minutes: int = Field(default=30, ge=1, le=240)
    body_threshold: float = Field(default=.85, ge=.70, le=.99)
    body_margin: float = Field(default=.08, ge=.02, le=.30)
    face_hold_seconds: float = Field(default=15, ge=0, le=60)
    send_probable_father: bool = False
    # Propose sharp, confidently recognized faces as new examples; a person approves each one.
    street_delay_seconds: int = Field(default=45, ge=0, le=300)   # A stranger must stay in view this long before the intruder alert.
    learning_suggestions_enabled: bool = True
    learning_threshold: float = Field(default=.65, ge=.5, le=.95)
    learning_auto_approve: bool = True   # Suggestions at or above learning_auto_threshold are approved without asking; the doubtful ones wait for a person.
    learning_auto_threshold: float = Field(default=.75, ge=.5, le=.99)
    retention_days: int = Field(default=7, ge=1, le=90)
    cameras: list[ExtraCamera] = Field(default_factory=list, max_length=15)
    fall_detection_enabled: bool = False
    fall_seconds: int = Field(default=45, ge=10, le=300)
    # WhatsApp text alerts; zero turns each check off.
    alerts_enabled: bool = False
    inactivity_hours: float = Field(default=4, ge=0, le=24)
    routine_alerts_enabled: bool = True
    quiet_start_hour: int = Field(default=22, ge=0, le=23)
    quiet_end_hour: int = Field(default=7, ge=0, le=23)
    camera_offline_minutes: int = Field(default=10, ge=0, le=240)
    daily_summary_hour: int = Field(default=21, ge=-1, le=23)
    # Kitchen notebook: low battery, unplugged for too long, no signal (zero turns a rule off).
    notebook_alerts_enabled: bool = False
    # The big "call the family" button on the notebook screen (and, separately, the help request).
    notebook_call_enabled: bool = False
    notebook_panic_enabled: bool = True
    # The kitchen screen greets recognised people by first name ("Bom dia, Waldemar").
    notebook_greeting_enabled: bool = True
    # Idle kitchen screen: family photos by day (buttons appear on touch), black at night.
    notebook_photo_frame_enabled: bool = True
    kiosk_slide_seconds: int = Field(default=15, ge=5, le=120)       # Seconds each photo stays on screen.
    kiosk_awake_seconds: int = Field(default=30, ge=10, le=300)      # Buttons stay this long after a touch.
    kiosk_night_start_hour: int = Field(default=22, ge=0, le=23)
    kiosk_night_end_hour: int = Field(default=6, ge=0, le=23)
    kiosk_night_mode: str = 'black'                                  # black screen, red tones, panel off, or no night look.
    kiosk_screen_off_day: bool = False                                # Panel off by day too (on again when someone shows up).
    kiosk_screen_off_after: int = Field(default=45, ge=10, le=600)    # Panel-off mode: seconds on after the last presence or touch.
    kiosk_sound_on: bool = True                                      # Master switch for the screen's sounds.
    # Volume (0-100) of each sound by day and by night: buttons, ringing, help call, message chime.
    kiosk_vol_button_day: int = Field(default=70, ge=0, le=100)
    kiosk_vol_button_night: int = Field(default=30, ge=0, le=100)
    kiosk_vol_call_day: int = Field(default=70, ge=0, le=100)
    kiosk_vol_call_night: int = Field(default=30, ge=0, le=100)
    kiosk_vol_help_day: int = Field(default=100, ge=0, le=100)
    kiosk_vol_help_night: int = Field(default=70, ge=0, le=100)
    kiosk_vol_message_day: int = Field(default=80, ge=0, le=100)
    kiosk_vol_message_night: int = Field(default=35, ge=0, le=100)
    kiosk_calendar_enabled: bool = True
    # Weather on the screen (Open-Meteo): off by default; the city's coordinates are all that is sent.
    kiosk_weather_enabled: bool = False
    kiosk_weather_city: str = Field(default='', max_length=120)
    kiosk_weather_lat: float = Field(default=0.0, ge=-90, le=90)
    kiosk_weather_lon: float = Field(default=0.0, ge=-180, le=180)
    kiosk_weather_rain: bool = True   # Falling-drops effect on the screen while it is raining.
    # Screen brightness (laptop backlight): dim at night, brighter while someone is around. Off by default.
    kiosk_dim_enabled: bool = False
    kiosk_bright_day: int = Field(default=60, ge=5, le=100)
    kiosk_bright_night: int = Field(default=3, ge=1, le=100)
    kiosk_bright_wake: int = Field(default=40, ge=1, le=100)
    kiosk_bright_hold: int = Field(default=45, ge=10, le=600)
    kiosk_frame_calendar: str = 'always'                             # On the photo frame: always visible, pulse (12 s a minute) or off.
    kiosk_birthdays_enabled: bool = True
    kiosk_read_messages: bool = True   # The kitchen screen reads a message aloud when the person it is for is recognised (and the daily briefing).
    kiosk_daily_briefing: bool = True   # First greeting of the day also gives the date, the weather and a few suggestions.
    kiosk_nightlight_enabled: bool = False                            # Night: a soft light on the screen while someone walks by.
    kiosk_nightlight_bright: int = Field(default=60, ge=5, le=100)
    kiosk_hints: list[str] = Field(default_factory=list, max_length=10)   # Extra messages cycled on the photo frame.

    @field_validator('kiosk_night_mode')
    @classmethod
    def kiosk_night_valid(cls, value):
        if value not in ('black', 'red', 'off', 'normal'):
            raise ValueError('Escolha como a tela fica à noite.')
        return value

    @field_validator('kiosk_frame_calendar')
    @classmethod
    def kiosk_frame_calendar_valid(cls, value):
        if value not in ('always', 'pulse', 'off'):
            raise ValueError('Escolha como o calendário aparece na moldura.')
        return value

    @field_validator('kiosk_hints')
    @classmethod
    def kiosk_hints_valid(cls, lines):
        cleaned = [' '.join(str(line).split())[:120] for line in lines]
        return [line for line in cleaned if line]
    notebook_battery_percent: int = Field(default=20, ge=5, le=60)
    notebook_unplugged_minutes: int = Field(default=15, ge=0, le=240)
    notebook_offline_minutes: int = Field(default=5, ge=0, le=240)
    min_free_gb: float = Field(default=2, ge=0.5, le=100)
    # Daily copy of history, settings and faces to another disk or a synced folder.
    backup_enabled: bool = False
    backup_dir: str = Field(default='', max_length=1024)
    backup_hour: int = Field(default=3, ge=0, le=23)
    backup_keep: int = Field(default=14, ge=1, le=90)

    @field_validator('cameras')
    @classmethod
    def unique_ids(cls, cameras):
        if len({c.id for c in cameras}) != len(cameras):
            raise ValueError('IDs de câmera duplicados.')
        return cameras

    @field_validator('backup_dir')
    @classmethod
    def backup_dir_valid(cls, value):
        value = value.strip()
        if value and not value.startswith('/'):
            raise ValueError('Informe o caminho completo da pasta de backup, começando com /.')
        return value

    @field_validator('recipient')
    @classmethod
    def recipient_valid(cls, value):
        value = ''.join(c for c in value if c not in ' +()-')
        if value and (not value.isascii() or not value.isdigit() or not 10 <= len(value) <= 15):
            raise ValueError('Use DDI + DDD + número, por exemplo 5511999999999.')
        return value

    @field_validator('additional_recipients')
    @classmethod
    def additional_valid(cls, values, info):
        result=[]
        for value in values:
            phone=cls.recipient_valid(value)
            if not phone:
                raise ValueError('Informe um número válido para cada familiar.')
            if phone not in result and phone!=info.data.get('recipient'):
                result.append(phone)
        return result

    def delivery_targets(self):
        # Family members always receive only father records. The primary number
        # retains its own existing all-presence/father-only preference.
        targets={phone:True for phone in self.additional_recipients}
        if self.recipient:
            targets={self.recipient:self.father_only, **{p:v for p,v in targets.items() if p!=self.recipient}}
        return targets

class Config:
    def __init__(self, path=DATA / 'settings.json'):
        self.path = path
        self.lock = threading.RLock()
        raw = json.loads(path.read_text()) if path.exists() else {}
        if raw and raw.get('schema_version', 1) < 2:
            # The old default was an 8 fps slideshow; upgrade the default without
            # changing the camera, recipient, password or delivery opt-ins.
            if raw.get('fps', 8) == 8:
                raw['fps'] = 30
            raw['fps'] = max(5, raw.get('fps', 30))
            raw['schema_version'] = 2
        self.value = Settings(**raw)

    def get(self):
        with self.lock:
            return self.value.model_copy(deep=True)

    def save(self, value):
        with self.lock:
            old_targets=self.value.delivery_targets()
            # The client cannot move a recipient's start date backwards and
            # silently share old recordings when a family contact is added.
            value.recipient_since={phone:self.value.recipient_since.get(phone,0) if phone in old_targets
                else time.time() if self.path.exists() and phone!=value.recipient else 0 for phone in value.delivery_targets()}
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(value.model_dump_json(indent=2))
            tmp.chmod(0o600)
            tmp.replace(self.path)
            self.value = value

    def for_camera(self, camera_id='main'):
        settings = self.get()
        if camera_id == 'main':
            return settings
        camera = next((c for c in settings.cameras if c.id == camera_id), None)
        if camera is None:
            raise KeyError('Câmera não encontrada.')
        return settings.model_copy(update=camera.model_dump(exclude={'id'}))

    def update_camera(self, camera_id, **changes):
        with self.lock:
            settings = self.get()
            current = self.for_camera(camera_id)
            validated = CameraSettings.model_validate({**current.model_dump(), **changes})
            values = validated.model_dump()
            if camera_id == 'main':
                settings = settings.model_copy(update=values)
            else:
                settings.cameras = [c.model_copy(update=values) if c.id == camera_id else c for c in settings.cameras]
            self.save(settings)

    def save_for_camera(self, value, camera_id='main'):
        with self.lock:
            self.for_camera(camera_id)  # Reject unknown cameras before changing globals.
            current = self.get()
            # A stale settings form must not remove cameras or reverse live controls.
            global_values = value.model_dump(exclude=CAMERA_FIELDS | {'cameras'})
            current = current.model_copy(update=global_values)
            self.save(current)
            self.update_camera(camera_id, **value.model_dump(include=CAMERA_FIELDS - {'enabled', 'analysis_enabled'}))


class CameraConfigView:
    """Scoped view for one worker; EOF can only stop its own camera."""
    def __init__(self, config, camera_id):
        self.config, self.camera_id = config, camera_id

    def get(self):
        return self.config.for_camera(self.camera_id)

    def save(self, value):
        self.config.update_camera(self.camera_id, enabled=value.enabled)


def gateway_token():
    path = DATA / 'gateway.token'
    try:
        with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


config = Config()
