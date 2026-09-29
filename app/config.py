import json
import os
import secrets
import threading
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DATA = Path(os.environ.get('CAMERA_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
CLIPS = DATA / 'clips'
CLIPS.mkdir(exist_ok=True)
MODEL = os.environ.get('YOLO_MODEL', str(ROOT / 'yolo26n.pt'))
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
    detection_size: int = Field(default=640, ge=320, le=1280, multiple_of=32)
    detection_fps: int = Field(default=30, ge=1, le=30)
    preview_width: int = Field(default=1280, ge=640, le=1920)
    recording_width: int = Field(default=1920, ge=640, le=1920)
    confidence: float = Field(default=0.5, ge=0.2, le=0.95)
    absence_seconds: float = Field(default=8, ge=2, le=120)
    min_presence_seconds: float = Field(default=1, ge=0.25, le=10)
    segment_seconds: int = Field(default=60, ge=10, le=180)
    fps: int = Field(default=30, ge=5, le=30)

    @field_validator('camera_source')
    @classmethod
    def text_valid(cls, value):
        value = value.strip()
        if not value or len(value) > 2048:
            raise ValueError('Informe um nome e endereço válidos para a câmera.')
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
    retention_days: int = Field(default=7, ge=1, le=90)
    cameras: list[ExtraCamera] = Field(default_factory=list, max_length=15)

    @field_validator('cameras')
    @classmethod
    def unique_ids(cls, cameras):
        if len({c.id for c in cameras}) != len(cameras):
            raise ValueError('IDs de câmera duplicados.')
        return cameras

    @field_validator('recipient')
    @classmethod
    def recipient_valid(cls, value):
        value = ''.join(c for c in value if c not in ' +()-')
        if value and (not value.isascii() or not value.isdigit() or not 10 <= len(value) <= 15):
            raise ValueError('Use DDI + DDD + número, por exemplo 5511999999999.')
        return value

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
