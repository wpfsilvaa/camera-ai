"""Repeatable CPU-only workload: synthetic local 720p feeds, real YOLO + SFace.
Run each case in a fresh process; this never loads production settings or sends messages.
"""
import argparse,json,os,resource,statistics,tempfile,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--cameras',type=int,default=1);parser.add_argument('--size',type=int,default=416);parser.add_argument('--body',action='store_true');parser.add_argument('--seconds',type=int,default=12)
args=parser.parse_args()
TEMP=tempfile.TemporaryDirectory();os.environ['CAMERA_DATA_DIR']=TEMP.name;os.environ['DASHBOARD_PASSWORD']='';os.environ['CUDA_VISIBLE_DEVICES']='';os.environ['YOLO_CONFIG_DIR']=str(Path(TEMP.name)/'ultralytics')
import cv2,numpy as np,torch,ultralytics
from app.config import config,Settings,ExtraCamera,DATA
from app.db import Database
from app.recognition import Recognition
from app.cameras import CameraManager
from app.recorder import transcode
cv2.setNumThreads(2);torch.set_num_threads(2)
assert not torch.cuda.is_available()
photo=cv2.imread(str(Path(ultralytics.__file__).parent/'assets/zidane.jpg'))[:,744:]
frame=np.full((720,1280,3),35,dtype=np.uint8);frame[:,300:300+photo.shape[1]]=photo
video=DATA/'input.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),15,(1280,720))
for index in range(75*15):
    image=frame.copy();cv2.putText(image,str(index),(30,40),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),1);writer.write(image)
writer.release()
values=dict(camera_source=str(video),enabled=True,device='cpu',fps=15,detection_fps=5,detection_size=args.size,min_presence_seconds=.25,segment_seconds=60)
config.save(Settings(**values,body_reid_enabled=args.body,cameras=[ExtraCamera(**values,camera_name=f'Camera {i+2}') for i in range(args.cameras-1)]))
db=Database();recognition=Recognition(db);recognition.enroll('father',photo)
manager=CameraManager(db,config,recognition);manager.start();samples=[]
try:
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        states=manager.snapshots()
        if len(states)==args.cameras and all(s['state']=='online' and s['people']>0 and manager.get(s['id']).recognition.last_processed for s in states):break
        time.sleep(.1)
    else:raise AssertionError(states)
    time.sleep(2)
    start=time.perf_counter();cpu_start=time.process_time();sequences={k:w.sequence for k,w in manager.workers.items()}
    while time.perf_counter()-start<args.seconds:
        samples.append(manager.snapshots());time.sleep(.2)
    elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu_start
    measured_fps={k:(w.sequence-sequences[k])/elapsed for k,w in manager.workers.items()}
    assert all(s['state']=='online' and s['device']=='cpu' for s in samples[-1]),samples[-1]
    recognition_status={k:w.recognition.status() for k,w in manager.workers.items()}
    manager.stop()
    clips=db.rows("SELECT * FROM clips WHERE state='processing'")
    conversion_start=time.perf_counter()
    for clip in clips:transcode(db,clip)
    conversion_seconds=time.perf_counter()-conversion_start
    assert all(c['state']=='ready' for c in db.rows('SELECT state FROM clips')),db.rows('SELECT state,error FROM clips')
    tracks=db.rows('SELECT e.camera_id,t.track_key,t.suggested_id FROM person_tracks t JOIN events e ON e.id=t.event_id')
    assert len({t['camera_id'] for t in tracks if t['suggested_id']=='father'})==args.cameras,tracks
    recorded=db.rows('SELECT SUM(duration) AS seconds FROM clips')[0]['seconds'] or 0
    report={'cpu':next(line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
      'gpu_visible':False,'cameras':args.cameras,'source':'local MJPEG 1280x720 / 15 fps; one static enrolled face per feed',
      'yolo':'yolo26n.pt / PyTorch FP32','threads_per_model':2,'detection_size':args.size,'target_detection_fps':5,'body_reid':args.body,
      'measurement_seconds':round(elapsed,2),'cpu_core_equivalents':round(cpu/elapsed,2),'cpu_percent_of_8_logical':round(100*cpu/elapsed/(os.cpu_count() or 1),1),
      'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024),
      'per_camera':[{'id':k,'preview_fps':round(measured_fps[k],1),'detection_fps_median':statistics.median(next(s for s in batch if s['id']==k)['detection_fps'] for batch in samples),
        'inference_ms_median':statistics.median(next(s for s in batch if s['id']==k)['inference_ms'] for batch in samples),
        'recognition_ms_last':recognition_status[k]['processing_ms']} for k in measured_fps],
      'identified_cameras':len({t['camera_id'] for t in tracks if t['suggested_id']=='father'}),
      'transcode_seconds_separate':round(conversion_seconds,2),'recorded_seconds_total':round(recorded,2),
      'limitations':'Warmup excluded; no RTSP/H264 decode, browser, WhatsApp, concurrent ffmpeg or offline analysis; one visible person. Not a hardware guarantee.'}
    output=Path('test-results')/f'cpu-{args.cameras}cam-{args.size}-body{int(args.body)}.json';output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
finally:manager.stop();TEMP.cleanup()
