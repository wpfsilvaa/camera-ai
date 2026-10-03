"""Isolated fixture for login-ui-smoke.mjs; starts without users and without WhatsApp."""
import sys
import time
import uuid
from datetime import datetime, timedelta

import cv2
import uvicorn

from app import main
from app.config import PEOPLE
from app.db import TZ
from app.faces import normalized


async def gateway(method, path, payload=None):
    return {'state': 'connected', 'qr': 'data:image/png;base64,AAAA', 'error': None}

main.gateway = gateway
# Two weeks of presences so the learned routine and its chart have data.
for back in range(1, 15):
    day = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=back)
    for hour, minute in ((7, back * 3 % 40), (12, 0), (15, 30), (19, 10)):
        start = (day + timedelta(hours=hour, minutes=minute)).timestamp()
        event = main.db.start_event(start, 1)
        main.db.end_event(event, start + 300, 'absence')
        main.db.execute('UPDATE events SET last_seen=? WHERE id=?', (start + 300, event))


def face_track(vector, quality, suggested=None):
    event = main.db.start_event(time.time() - 120, 1)
    main.db.end_event(event, time.time() - 60, 'absence')
    track = main.db.execute('''INSERT INTO person_tracks(event_id,track_key,started,last_seen,suggested_id,similarity,recognition_kind)
        VALUES(?,'1',?,?,?,.8,'face')''', (event, time.time() - 120, time.time() - 60, suggested))
    sample = uuid.uuid4().hex
    cv2.imwrite(str(PEOPLE / f'{sample}.jpg'), cv2.resize(cv2.imread('tests/assets/lena.jpg'), (112, 112)))
    main.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',
                    (sample, track, time.time() - 90, normalized(vector).tobytes(), 'sface-test', quality))
    return track, sample


# A confirmed example of the father and a sharper, new view waiting for approval.
track, sample = face_track((1, 0, 0), 100)
main.recognition.confirm(track, 'father', sample)
face_track((.9, .1, .42), 200, 'father')
main.learning.scan()
uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[1]), log_level='error')
