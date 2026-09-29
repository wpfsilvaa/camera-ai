"""Replay a local recorded event in isolation; never change history or send messages.

Usage: PYTHONPATH=. .venv/bin/python tests/body_replay.py --event 127
Source recordings already contain annotations; this is a regression replay,
not an accuracy benchmark for unseen people or raw camera frames.
"""
import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--event',type=int,required=True)
parser.add_argument('--data',type=Path,default=Path('data'))
parser.add_argument('--return-after',type=float,default=9)
parser.add_argument('--body-threshold',type=float)
args=parser.parse_args()
source=args.data.resolve()
temporary=tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR']=temporary.name
os.environ['YOLO_CONFIG_DIR']=str(Path(temporary.name)/'ultralytics')
import cv2
from ultralytics import YOLO
from app.body import BodyEncoder
from app.config import Settings
from app.db import Database
from app.faces import FaceEncoder
from app.recognition import Recognition
from app.tracking import PersonTracker

with sqlite3.connect(f'file:{source}/history.sqlite3?mode=ro',uri=True) as src, sqlite3.connect(Path(temporary.name)/'history.sqlite3') as dest:
    src.backup(dest)
db=Database(Path(temporary.name)/'history.sqlite3')
settings=Settings.model_validate_json((source/'settings.json').read_text())
if args.body_threshold is not None:
    settings=Settings.model_validate({**settings.model_dump(),'body_threshold':args.body_threshold})
recognition=Recognition(db,Path(temporary.name)/'people')
recognition.encoder=FaceEncoder()
encoder=BodyEncoder()
model=YOLO('yolo26n.pt')
tracker=PersonTracker(settings.confidence)
records=[];absence=False;face_seen=False;known_faces=set()
event_start=db.rows('SELECT started FROM events WHERE id=?',(args.event,))[0]['started']
for clip in db.rows('SELECT * FROM clips WHERE event_id=? ORDER BY started',(args.event,)):
    cap=cv2.VideoCapture(str(source/'clips'/f"{clip['id']}.mp4"))
    fps=cap.get(cv2.CAP_PROP_FPS)
    for i in range(0,int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),max(1,round(fps/3))):
        cap.set(cv2.CAP_PROP_POS_FRAMES,i);ok,frame=cap.read()
        if not ok:break
        now=clip['started']+i/fps
        result=model.predict(frame,classes=[0],conf=.1,imgsz=settings.detection_size,verbose=False)[0]
        boxes,ids=tracker.update(result.boxes,frame,now)
        diagnostic={}
        faces=recognition.encoder.for_people(frame,boxes,ids,diagnostic)
        bodies=encoder.for_people(frame,boxes,ids)
        recognition.observe_faces(args.event,boxes,ids,faces,now,settings,bodies,diagnostic)
        labels=recognition.labels(ids,boxes,now,settings.face_hold_seconds)
        if not ids and face_seen:absence=True
        for key,label in labels.items():
            if label['source']=='face' and not label['held']:
                face_seen=True
                known_faces.add(label['person_id'])
        records.append({'seconds':round(now-event_start,3),'ids':ids,'faces':len(faces),
            'identity_consistent':all(label['person_id'] in known_faces for label in labels.values()),
            'body_diagnostics':[json.loads(r['diagnostic']).get('body') for key in ids for r in db.rows('SELECT diagnostic FROM person_tracks WHERE event_id=? AND track_key=?',(args.event,str(key)))],
            'labels':[{k:v for k,v in label.items() if k in ('source','score','held')} for label in labels.values()],
            'references':sum(len(v) for v in recognition.body_memory.references.values())})
    cap.release()
returned=[r for r in records if r['seconds']>=args.return_after and r['ids'] and not r['faces']]
recognized=[r for r in returned if any(v['source']=='body' for v in r['labels'])]
# Independent negative examples from the package's official sample photographs.
import ultralytics
negatives=[]
for filename in ('zidane.jpg','bus.jpg'):
    image=cv2.imread(str(Path(ultralytics.__file__).parent/'assets'/filename))
    detected=model.predict(image,classes=[0],conf=.5,imgsz=640,verbose=False)[0]
    for index,box in enumerate(detected.boxes.xyxy.cpu().tolist()):
        vectors=encoder.for_people(image,[box],[0])
        if not vectors:continue
        detail={}
        for j in range(3):
            person,score=recognition.body_memory.match(f'negative-{filename}-{index}',vectors['0'],now+1+j*.3,
                settings.body_threshold,settings.body_margin,detail)
        negatives.append({'image':filename,'box':index,'score':score,'matched':person is not None})
assert negatives and not any(r['matched'] for r in negatives),negatives
report={'event':args.event,'face_seen':face_seen,'absence_seen':absence,'return_observations':len(returned),
        'return_recognized':len(recognized),'first_return_match':recognized[0]['seconds'] if recognized else None,
        'body_threshold':settings.body_threshold,'detection_size':settings.detection_size,'confidence':settings.confidence,'negatives':negatives,'records':records}
out=Path('test-results/body-audit');out.mkdir(parents=True,exist_ok=True)
(out/f'replay-{args.event}.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))
assert len(known_faces)==1 and all(r['identity_consistent'] for r in returned), 'Replay expects the same single face-verified person to return.'
assert face_seen and absence and recognized, 'Return was not recognized after facial evidence and disappearance.'
