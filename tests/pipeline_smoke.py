"""Real YOLO → presence → segmentation → H.264, using a synthetic local video."""
import os
import tempfile
import time
from pathlib import Path

temporary = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = temporary.name
os.environ['YOLO_CONFIG_DIR'] = str(Path(temporary.name) / 'ultralytics')

import cv2
import numpy as np
import ultralytics

from app.camera import CameraWorker
from app.config import CLIPS, Config, Settings
from app.db import Database
from app.recorder import transcode

sample = Path(ultralytics.__file__).parent / 'assets/bus.jpg'
assert sample.is_file(), 'Exemplo bus.jpg ausente no pacote Ultralytics.'
image = cv2.resize(cv2.imread(str(sample)), (480, 640))
video = Path(temporary.name) / 'input.avi'
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 8, (480, 640))
assert writer.isOpened()
for _ in range(12 * 8):
    writer.write(image)
for _ in range(3 * 8):
    writer.write(np.zeros_like(image))
writer.release()

config = Config(Path(temporary.name) / 'settings.json')
config.save(Settings(camera_source=str(video), enabled=True, min_presence_seconds=.25, absence_seconds=2, segment_seconds=10))
db = Database(Path(temporary.name) / 'history.sqlite3')
worker = CameraWorker(db, config)
worker.start()
try:
    deadline = time.monotonic() + 45
    while config.get().enabled and time.monotonic() < deadline:
        time.sleep(.2)
    assert not config.get().enabled, worker.snapshot()
finally:
    worker.stop()

events = db.history()['events']
assert len(events) == 1, f'Esperado um registro: {events}'
event = events[0]
assert event['reason'] == 'absence', event
assert event['max_people'] >= 1
assert len(event['clips']) == 2, event
assert len(event['people']) >= 2, 'O rastreamento deve separar as pessoas da imagem de exemplo.'
assert all(t['person_id'] is None and t['suggested_id'] is None for t in event['people']), 'Sem exemplos confirmados, todos devem permanecer desconhecidos.'
for clip in event['clips']:
    transcode(db, clip)
ready = db.rows('SELECT * FROM clips')
assert all(clip['state'] == 'ready' for clip in ready), ready
assert 12 <= sum(clip['duration'] for clip in ready) <= 16, ready
assert len(list(CLIPS.glob('*.mp4'))) == 2
print('Fluxo completo OK: YOLO real, um período de presença, duas partes H.264 e encerramento por ausência. Nenhuma mensagem enviada.')
temporary.cleanup()
