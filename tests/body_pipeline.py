"""Real YOLO + SFace + ReID: leave, return with face hidden and a new track."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
TEMP=tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR']=TEMP.name
os.environ['DASHBOARD_PASSWORD']=''
os.environ['YOLO_CONFIG_DIR']=str(Path(TEMP.name)/'ultralytics')
import cv2
import numpy as np
import ultralytics
from app.camera import CameraWorker
from app.config import CLIPS,Config,Settings
from app.db import Database
from app.faces import FaceEncoder
from app.body import BodyEncoder
from app.recognition import Recognition
from app.recorder import transcode
cv2.setNumThreads(2)
out=Path('test-results');out.mkdir(exist_ok=True)
# Crop one person from an official sample; place against a fixed background.
photo=cv2.imread(str(Path(ultralytics.__file__).parent/'assets/zidane.jpg'))[:,744:]
encoder=FaceEncoder()
faces=encoder.faces(photo,1280)
assert len(faces)==1
x1,y1,x2,y2=map(int,faces[0]['box'])
masked=photo.copy()
masked[max(0,y1-15):y2+15,max(0,x1-15):x2+15]=114
assert not encoder.faces(masked,1280),'Return image must contain no usable face.'
def scene(person,offset):
    frame=np.full((720,1280,3),35,dtype=np.uint8)
    frame[:,offset:offset+person.shape[1]]=person
    return frame
video=Path(TEMP.name)/'reentry.avi'
writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),30,(1280,720))
assert writer.isOpened()
for i in range(5*30): writer.write(scene(photo,150+int(3*np.sin(i/15))))
for _ in range(4*30): writer.write(np.full((720,1280,3),35,dtype=np.uint8))
for i in range(6*30): writer.write(scene(masked,620+int(3*np.sin(i/15))))
for _ in range(3*30): writer.write(np.full((720,1280,3),35,dtype=np.uint8))
writer.release()
db=Database(Path(TEMP.name)/'history.sqlite3')
recognition=Recognition(db)
recognition.encoder=encoder
recognition.rename_person('father','Referência de teste')
recognition.enroll('father',photo)
cfg=Config(Path(TEMP.name)/'settings.json')
cfg.save(Settings(camera_source=str(video),enabled=True,fps=30,min_presence_seconds=.25,absence_seconds=2))
worker=CameraWorker(db,cfg,recognition)
worker.start()
seen={'face':set(),'body':set()};samples=[]
try:
    deadline=time.monotonic()+55
    while cfg.get().enabled and time.monotonic()<deadline:
        state=worker.snapshot()
        if state['state']=='online':
            samples.append(state)
            for track in state['tracks']:
                if track.get('name') and track.get('source') in seen:
                    seen[track['source']].add(track['id'])
                    if track['source']=='body':
                        with worker.lock: jpeg=worker.jpeg
                        if jpeg:(out/'body-return-live.jpg').write_bytes(jpeg)
        time.sleep(.1)
    assert not cfg.get().enabled,worker.snapshot()
finally:worker.stop()
assert seen['face'] and seen['body'],(seen,recognition.error,recognition.body_error,db.rows('SELECT * FROM person_tracks'))
assert seen['face'].isdisjoint(seen['body']),seen
records=sorted(db.history()['events'],key=lambda e:e['id'])
assert len(records)==2,records
returned=records[-1]
assert any(t['suggested_id']=='father' and t['recognition_kind']=='body' for t in returned['people']),returned
assert all(not t['samples'] for t in returned['people']),'No returning face can have supplied the name.'
for event in records:
    for clip in event['clips']:transcode(db,clip)
clip=db.rows('SELECT * FROM clips WHERE event_id=?',(returned['id'],))[0]
assert clip['state']=='ready',clip
path=CLIPS/f"{clip['id']}.mp4"
shutil.copy2(path,out/'body-return.mp4')
cap=cv2.VideoCapture(str(path));cap.set(cv2.CAP_PROP_POS_MSEC,3000);ok,frame=cap.read();cap.release()
assert ok
cv2.imwrite(str(out/'body-return-recorded.jpg'),frame)
steady=samples[30:]
report={'face_track_ids':sorted(seen['face']),'body_return_track_ids':sorted(seen['body']),
        'return_face_samples':0,'events':len(records),'recorded_source':'body',
        'median_fps':float(np.median([s['fps'] for s in steady])),
        'face_and_body_error':[recognition.error,recognition.body_error],
        'fixture':'Official photo; simulated movement, departure and return with covered face'}
(out/'body-pipeline.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
assert report['median_fps']>=24
TEMP.cleanup()
