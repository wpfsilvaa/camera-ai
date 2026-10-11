"""Fill a data folder with made-up sample data, to explore or photograph the dashboard without real people.

    CAMERA_DATA_DIR=/tmp/casa-demo .venv/bin/python scripts/demo_seed.py
    CAMERA_DATA_DIR=/tmp/casa-demo DASHBOARD_PASSWORD= PORT=8010 .venv/bin/python -m app.run

Creates two weeks of presence records (with fake clip rows, no video files), a few profiles with birthdays,
two reminders, a message and the sample photos from tests/assets. Nothing here touches your real data.
"""
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if 'CAMERA_DATA_DIR' not in os.environ:
    sys.exit('Defina CAMERA_DATA_DIR para uma pasta de demonstração (não use a pasta de dados real).')
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import CLIPS, Settings, config  # noqa: E402
from app.db import TZ, Database  # noqa: E402
from app.messages import PersonMessages  # noqa: E402
from app.photos import Photos  # noqa: E402
from app.reminders import Reminders  # noqa: E402

random.seed(7)
SAMPLE = cv2.imread(str(ROOT / 'tests/assets/lena.jpg'))


def thumbnail(seed):
    """A soft, abstract 16:9 preview (a blurred crop of the sample photo) standing in for a video frame."""
    height, width = SAMPLE.shape[:2]
    top, left = (seed * 37) % (height // 2), (seed * 53) % (width // 2)
    crop = SAMPLE[top:top + height // 2, left:left + width // 2]
    return cv2.GaussianBlur(cv2.resize(crop, (320, 180)), (0, 0), 6)


db = Database()
now = time.time()
today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)

# Profiles: the built-in "Meu pai" plus two relatives with birthdays.
db.execute("UPDATE people SET birthday=? WHERE id='father'", ('1952-03-14',))
for person_id, name, birthday in (('ana', 'Ana', '1988-10-14'), ('beto', 'Beto', '1990-12-02')):
    db.execute('INSERT OR IGNORE INTO people(id,name,is_father,created,birthday) VALUES(?,?,0,?,?)', (person_id, name, now, birthday))

# Two weeks of presence: a morning, noon and evening visit most days.
for back in range(13, -1, -1):
    day = today - timedelta(days=back)
    for hour, minute, length in ((8, 10, 25), (12, 25, 35), (16, 40, 12), (19, 35, 40)):
        if random.random() < 0.2:
            continue
        start = (day + timedelta(hours=hour, minutes=minute + random.randint(-8, 8))).timestamp()
        if start > now:
            continue
        end = start + length * 60
        event = db.start_event(start, 1)
        db.end_event(event, min(end, now), 'absence')
        identity = 'father' if random.random() < 0.8 else 'unknown'
        db.execute('UPDATE events SET identity=?, identity_source=? WHERE id=?', (identity, 'manual' if identity == 'father' else 'legacy', event))
        db.execute("INSERT INTO clips(id,event_id,started,ended,duration,state,delivery,sent_at) VALUES(?,?,?,?,?,'ready','sent',?)",
                   (f'{event:032x}', event, start, min(end, now), length * 60 * 0.6, start + 90))
        cv2.imwrite(str(CLIPS / f'{event:032x}.jpg'), thumbnail(event))

config.save(Settings(camera_name='Cozinha', camera_source='rtsp://192.168.1.50:8554/cam', enabled=False, whatsapp_enabled=False,
                     notebook_call_enabled=False, notebook_alerts_enabled=False, sentinel_enabled=True, recipient='', recognition_enabled=True,
                     kiosk_hints=['Hoje tem almoço em família', 'Beba água!']))

reminders = Reminders(db)
reminders.add('Ana', None, 'Tomar o remédio das 14h', 6)
reminders.add('Beto', None, 'Comprar pão na volta', 24)
PersonMessages(db).add('Ana', None, 'father', 'Te amo, pai! Lembre de descansar um pouquinho depois do almoço.', 72, True)

photos = Photos(db)
for image in sorted((ROOT / 'tests/assets').glob('*.jpg')):
    photos.add('Ana', None, image.read_bytes())
print('Dados de demonstração criados em', os.environ['CAMERA_DATA_DIR'])
