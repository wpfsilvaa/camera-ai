"""Isolated fixture server used only by people-ui-smoke.mjs."""
import sys
import time

import cv2
import numpy as np
import uvicorn

from app.config import PEOPLE
from app.db import Database

db = Database()
event = db.start_event(time.time()-20,2)
db.end_event(event,time.time()-5,'absence')
for index in (1,2):
    track = db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen) VALUES(?,?,?,?)',(event,str(index),time.time()-20,time.time()-5))
    sample=f'{index:032x}'
    image=np.zeros((180,80,3),dtype=np.uint8)
    image[:]=(90*index,140,80)
    cv2.imwrite(str(PEOPLE/f'{sample}.jpg'),image)
    db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)',(sample,track,time.time()-10,np.array([1,0],dtype=np.float32).tobytes(),'sface-ui-test',100))
# Publish changing frames without opening the user's camera or WhatsApp.
import threading
from app.main import camera

def preview():
    image=cv2.resize(cv2.imread('tests/assets/lena.jpg'),(960,540))
    while not camera.stop_event.is_set():
        frame=image.copy()
        cv2.putText(frame,str(time.time_ns()),(20,50),cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,0),2)
        _,jpeg=cv2.imencode('.jpg',frame)
        with camera.lock:
            camera.jpeg=jpeg.tobytes()
            camera.sequence+=1
        camera.update(state='online',last_frame=time.time(),source_width=960,source_height=540,source_fps=30,fps=30)
        camera.stop_event.wait(1/30)

def start_preview():
    camera.thread=threading.Thread(target=preview,daemon=True)
    camera.thread.start()
camera.start=start_preview
uvicorn.run('app.main:app' ,host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
