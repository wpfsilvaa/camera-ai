"""Actual RTX/YOLO, face enrollment, two identities and annotated Full HD recording."""
import json
import os
import tempfile
import time
from pathlib import Path

TEMP=tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR']=TEMP.name
os.environ['DASHBOARD_PASSWORD']=''
os.environ['YOLO_CONFIG_DIR']=str(Path(TEMP.name)/'ultralytics')

import cv2
import numpy as np
import torch
import ultralytics

from app.camera import CameraWorker
from app.config import CLIPS,Config,Settings
from app.db import Database
from app.faces import FaceEncoder
from app.recognition import Recognition,match_person
from app.recorder import transcode

artifacts=Path('test-results');artifacts.mkdir(exist_ok=True)
image=cv2.imread(str(Path(ultralytics.__file__).parent/'assets/zidane.jpg'))
image=cv2.resize(image,(1920,1080))
encoder=FaceEncoder()
faces=sorted(encoder.faces(image,1280),key=lambda f:f['box'][0])
assert len(faces)==2,'Duas faces no fixture são necessárias.'
db=Database(Path(TEMP.name)/'history.sqlite3')
recognition=Recognition(db)
recognition.encoder=encoder
recognition.rename_person('father','Referência A')
other=recognition.create_person('Referência B')
for person,face in zip(['father',other],faces):
    x1,y1,x2,y2=map(int,face['box'])
    photo=image[max(0,y1-40):min(image.shape[0],y2+40),max(0,x1-40):min(image.shape[1],x2+40)]
    recognition.enroll(person,photo)
# A third, unenrolled face must not get one of the two known names.
recognition.load_gallery()
unknown=encoder.faces(cv2.imread('tests/assets/lena.jpg'))[0]
assert match_person(unknown['feature'],recognition.gallery)[0] is None

video=Path(TEMP.name)/'input.avi'
writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),30,(1920,1080))
assert writer.isOpened()
for i in range(12*30):
    # A slow pan and lighting variation exercise detection and tracking on changing frames.
    dx=int(8*np.sin(i/25))
    changed=cv2.warpAffine(image,np.float32([[1,0,dx],[0,1,0]]),(1920,1080),borderMode=cv2.BORDER_REFLECT)
    changed=cv2.convertScaleAbs(changed,alpha=.94+.04*np.sin(i/40),beta=2)
    writer.write(changed)
for _ in range(3*30):writer.write(np.zeros_like(image))
writer.release()

cfg=Config(Path(TEMP.name)/'settings.json')
cfg.save(Settings(camera_source=str(video),enabled=True,fps=30,segment_seconds=10,min_presence_seconds=.25,absence_seconds=2))
worker=CameraWorker(db,cfg,recognition)
worker.start()
measurements=[];observed=set();saved=False
try:
    deadline=time.monotonic()+55
    while cfg.get().enabled and time.monotonic()<deadline:
        state=worker.snapshot()
        if state['state']=='online' and state['fps']>0:
            measurements.append(state)
            names={t['name'] for t in state['tracks'] if t['name']}
            observed.update(names)
            if len(names)==2 and not saved:
                with worker.lock: jpeg=worker.jpeg
                if jpeg:
                    (artifacts/'face-live.jpg').write_bytes(jpeg);saved=True
        time.sleep(.1)
    assert not cfg.get().enabled,worker.snapshot()
finally:
    worker.stop()
assert observed=={'Referência A','Referência B'},(observed,recognition.error,db.track_details(1))
events=db.history()['events']
assert len(events)==1 and events[0]['reason']=='absence',events
assert len(events[0]['clips'])==2
assert len(events[0]['people'])>=2
assert all(t['recognition_kind']=='face' for t in events[0]['people'])
for clip in events[0]['clips']:transcode(db,clip)
ready=db.rows('SELECT * FROM clips ORDER BY started')
assert all(c['state']=='ready' for c in ready),ready
first=CLIPS/f"{ready[0]['id']}.mp4"
cap=cv2.VideoCapture(str(first));cap.set(cv2.CAP_PROP_POS_MSEC,5000);ok,frame=cap.read()
assert ok and frame.shape[:2]==(1080,1920)
assert abs(cap.get(cv2.CAP_PROP_FPS)-30)<.1
cv2.imwrite(str(artifacts/'face-recorded.jpg'),frame)
cap.release()
# Keep an actual annotated result for review; all identity references remain temporary.
import shutil
shutil.copy2(first,artifacts/'face-recorded.mp4')
steady=measurements[30:] or measurements
report={
 'gpu':steady[-1]['gpu'],'device':steady[-1]['device'],'fp16':steady[-1]['half'],
 'input':'1920x1080 @ 30 fps; pan and lighting variation; two real faces',
 'processed_fps_median':float(np.median([s['fps'] for s in steady])),
 'inference_ms_median':float(np.median([s['inference_ms'] for s in steady])),
 'processing_latency_ms_p95':float(np.percentile([s['frame_age_ms'] for s in steady],95)),
 'recognized_names':sorted(observed),'unknown_face_rejected':True,
 'clips':len(ready),'recorded_seconds':sum(c['duration'] for c in ready),
 'face_processing_ms':recognition.processing_ms,
}
(artifacts/'full-pipeline.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
assert report['device']=='cuda:0' and report['fp16'],'Este teste de desempenho exige a GPU.'
assert report['processed_fps_median']>=24,report
TEMP.cleanup()
