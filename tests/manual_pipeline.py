"""Live preview with zero inference, manual recording, GPU release and deferred analysis."""
import json,os,tempfile,time
from pathlib import Path
TEMP=tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR']=TEMP.name
os.environ['DASHBOARD_PASSWORD']=''
os.environ['YOLO_CONFIG_DIR']=str(Path(TEMP.name)/'ultralytics')
import cv2,numpy as np,torch,ultralytics
from app.camera import CameraWorker
from app.config import CLIPS,Config,Settings,config
from app.db import Database
from app.recognition import Recognition
from app.recorder import transcode
from app.offline import OfflineAnalysis
cv2.setNumThreads(2)
photo=cv2.imread(str(Path(ultralytics.__file__).parent/'assets/zidane.jpg'))[:,744:]
frame=np.full((720,1280,3),35,dtype=np.uint8);frame[:,300:300+photo.shape[1]]=photo
video=Path(TEMP.name)/'input.avi'
writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(1280,720))
for _ in range(35*15):writer.write(frame)
writer.release()
config.save(Settings(camera_source=str(video),enabled=True,analysis_enabled=False,fps=15,min_presence_seconds=.25))
db=Database()
r=Recognition(db);r.rename_person('father','Referência manual');r.enroll('father',photo)
w=CameraWorker(db,config,r);offline=OfflineAnalysis(db)
def until(fn,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if fn():return
        time.sleep(.05)
    raise AssertionError(w.snapshot())
w.start()
try:
    until(lambda:w.snapshot()['state']=='online')
    assert w.snapshot()['device'] is None and w.snapshot()['analysis_active'] is False
    assert not (r.thread and r.thread.is_alive())
    seq=w.sequence;time.sleep(.4);assert w.sequence>seq
    assert db.history()['events']==[]
    w.request_recording(True);until(lambda:w.snapshot()['manual_recording'])
    event=w.snapshot()['manual_event_id'];time.sleep(2.3)
    w.request_recording(False);until(lambda:not w.snapshot()['manual_recording'])
    original=db.rows('SELECT * FROM events WHERE id=?',(event,))[0]
    assert original['kind']=='manual' and original['ended'] and original['max_people']==0
    assert not db.track_details(event)
    assert db.stats()['today']['total']==0
    for clip in db.rows('SELECT * FROM clips WHERE event_id=?',(event,)):transcode(db,clip)
    # Resume live inference, then pause while another manual recording continues.
    s=config.get();s.analysis_enabled=True;config.save(s)
    until(lambda:w.snapshot()['people']>0)
    used=torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
    w.request_recording(True);until(lambda:w.snapshot()['manual_recording'])
    continuing=w.snapshot()['manual_event_id']
    s=config.get();s.analysis_enabled=False;config.save(s)
    until(lambda:not w.snapshot()['analysis_active'])
    time.sleep(.3)
    remaining=torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
    assert not torch.cuda.is_available() or remaining<used,(used,remaining)
    assert w.snapshot()['manual_recording'] and w.snapshot()['manual_event_id']==continuing
    seq=w.sequence;time.sleep(.3);assert w.sequence>seq
    w.request_recording(False);until(lambda:not w.snapshot()['manual_recording'])
    # Analyse the first recording explicitly, then test cancellation and retry.
    offline.start(event)
    try:offline.start(event);raise AssertionError('Concurrent analysis was accepted')
    except ValueError:pass
    offline.cancel()
    assert db.rows('SELECT analysis_state FROM events WHERE id=?',(event,))[0]['analysis_state']=='cancelled'
    offline.start(event)
    until(lambda:db.rows('SELECT analysis_state FROM events WHERE id=?',(event,))[0]['analysis_state']!='running',40)
    state=db.rows('SELECT * FROM events WHERE id=?',(event,))[0]
    assert state['analysis_state']=='complete',state
    tracks=db.track_details(event)
    assert tracks and any(t['suggested_id']=='father' for t in tracks),tracks
    clip=db.rows('SELECT * FROM clips WHERE event_id=?',(event,))[0]
    assert clip['analyzed']==1
    assert (CLIPS/f"{clip['id']}.mp4").is_file()
    result=CLIPS/f"{clip['id']}.analyzed.mp4"
    cap=cv2.VideoCapture(str(result));cap.set(cv2.CAP_PROP_POS_MSEC,1500);ok,output=cap.read();cap.release();assert ok
    artifacts=Path('test-results');artifacts.mkdir(exist_ok=True)
    cv2.imwrite(str(artifacts/'manual-analyzed.jpg'),output)
    import shutil
    shutil.copy2(result,artifacts/'manual-analyzed.mp4')
    report={'preview_without_inference':True,'manual_recording_while_paused':True,'manual_survives_pause':True,
      'gpu_bytes_before_pause':used,'gpu_bytes_after_pause':remaining,'offline_result':state['analysis_state'],
      'identified_tracks':len(tracks),'cancellation_and_retry':True,'original_preserved':True}
    (artifacts/'manual-pipeline.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
finally:
    offline.cancel();w.stop()
TEMP.cleanup()
