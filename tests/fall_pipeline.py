"""Real pose model on a synthetic video: standing, then lying for 40 s. No camera, nothing sent."""
import os
import sys
import tempfile
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ.setdefault('YOLO_CONFIG_DIR', str(Path(TEMP.name) / 'ultralytics'))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cv2
import numpy as np
from fall_replay import replay

FPS = 10


def canvas(image):
    frame = np.full((720, 720, 3), 90, np.uint8)
    h, w = image.shape[:2]
    frame[720 - h:, :w] = image
    return frame


photo = cv2.imread(str(ROOT / 'tests/assets/messi5.jpg'))
standing, lying = canvas(photo), canvas(cv2.rotate(photo, cv2.ROTATE_90_CLOCKWISE))
video = Path(TEMP.name) / 'fall.mp4'
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (720, 720))
for frame, seconds in ((standing, 5), (lying, 40)):
    for _ in range(seconds * FPS):
        writer.write(frame)
writer.release()

device = os.environ.get('DEVICE', 'cpu')
result = replay(video, seconds=30, device=device, analysis_fps=5)
assert len(result['alerts']) == 1, result
key, when = result['alerts'][0]
assert 34 <= when <= 37, f'alerta aos {when:.1f} s; esperado ~35 s (5 s em pé + 30 s deitado)'
# Hips of the lying person are in the lower-left part of the frame: a "sofa" there silences it.
silenced = replay(video, seconds=30, zones=[[0, .3, .8, 1]], device=device, analysis_fps=5)
assert silenced['alerts'] == [], silenced
print(f'Queda validada: alerta aos {when:.1f} s; área ignorada suprime o alerta. Pose real, vídeo sintético.')

# The same video through the real camera worker: model loading, tracker indices and the callback.
import time
from app.cameras import CameraManager
from app.config import Config, Settings
from app.db import Database
from app.recognition import Recognition

db = Database(Path(TEMP.name) / 'history.sqlite3')
config = Config(Path(TEMP.name) / 'settings.json')
config.save(Settings(camera_source=str(video), enabled=True, recognition_enabled=False, fall_detection_enabled=True,
                     fall_seconds=10, detection_fps=5, fps=10, device=device if device == 'cpu' else 'auto'))
manager = CameraManager(db, config, Recognition(db))
reported = []
manager.fall_handler = lambda *args: reported.append(args)
manager.start()
try:
    deadline = time.time() + 120
    while not reported and time.time() < deadline:
        time.sleep(.5)
finally:
    manager.stop()
assert reported, 'o CameraWorker não reportou a queda'
camera_id, name, jpeg, seconds = reported[0]
assert camera_id == 'main' and jpeg[:2] == b'\xff\xd8' and seconds >= 10, reported[0][:2]
print(f'CameraWorker: queda reportada com foto ({len(jpeg) // 1024} KB) após {seconds:.0f} s deitado.')
