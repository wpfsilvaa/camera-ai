"""Real detector on a synthetic video: a person away from the fridge, at it, then away again.
Restricted mode must record only around the fridge visit and alert once. Nothing is sent."""
import os
import sys
import tempfile
import time
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ.setdefault('YOLO_CONFIG_DIR', str(Path(TEMP.name) / 'ultralytics'))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

FPS = 10
photo = cv2.imread(str(ROOT / 'tests/assets/messi5.jpg'))


def canvas(right):
    frame = np.full((720, 1280, 3), 90, np.uint8)
    h, w = photo.shape[:2]
    x = 1280 - w if right else 0
    frame[720 - h:, x:x + w] = photo
    return frame


video = Path(TEMP.name) / 'kitchen.mp4'
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (1280, 720))
for right, seconds in ((False, 5), (True, 6), (False, 12)):
    for _ in range(seconds * FPS):
        writer.write(canvas(right))
writer.release()

from app.cameras import CameraManager
from app.config import Config, Settings
from app.db import Database
from app.recognition import Recognition

device = os.environ.get('DEVICE', 'cpu')
db = Database(Path(TEMP.name) / 'history.sqlite3')
config = Config(Path(TEMP.name) / 'settings.json')
config.save(Settings(camera_source=str(video), enabled=True, recognition_enabled=False, detection_fps=5, fps=10,
                     device=device if device == 'cpu' else 'auto', restricted_enabled=True,
                     restricted_zones=[[.55, 0, 1, 1]], restricted_who='anyone', restricted_alert=True))
manager = CameraManager(db, config, Recognition(db))
reported = []
manager.restricted_handler = lambda *args: reported.append(args)
manager.start()
try:
    deadline = time.time() + 180
    while config.get().enabled and time.time() < deadline:
        time.sleep(.5)
finally:
    manager.stop()

events = db.rows('SELECT * FROM events')
clips = db.rows('SELECT * FROM clips ORDER BY started')
assert len(events) == 1, events  # Presence goes on for the whole video.
assert len(reported) == 1, [r[:2] for r in reported]
camera_id, name, jpeg, person = reported[0]
assert camera_id == 'main' and jpeg[:2] == b'\xff\xd8', reported[0][:2]
start = events[0]['started']
recorded = sum(c['duration'] for c in clips)
first = clips[0]['started'] - start
# At the fridge from 5 s to 11 s, plus 8 s absence: about 13 s of video out of 23 s.
assert clips and 3 <= first <= 7 and 9 <= recorded <= 16, (first, recorded, clips)
# Before the fridge, outside the area: a photo records who was in the kitchen.
photos = db.rows('SELECT * FROM event_photos')
assert len(photos) == 1 and photos[0]['created'] - start < 3, photos
from app.config import CLIPS
assert (CLIPS / f"{photos[0]['id']}.jpg").read_bytes()[:2] == b'\xff\xd8'
print(f'Modo restrito validado: 1 alerta, 1 foto fora da área, vídeo de {recorded:.1f} s a partir de {first:.1f} s '
      f'(registro de presença com {events[0]["last_seen"] - start:.0f} s). Detector real, vídeo sintético.')
