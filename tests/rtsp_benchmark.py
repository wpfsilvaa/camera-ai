"""Temporary local camera benchmark; no delivery worker or persistent history."""
import json
import os
import tempfile
import time
from pathlib import Path
TEMP=tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR']=TEMP.name
from app.camera import CameraWorker
from app.config import Config,Settings
from app.db import Database
cfg=Config(Path(TEMP.name)/'settings.json')
cfg.save(Settings(enabled=True,fps=30))
worker=CameraWorker(Database(Path(TEMP.name)/'history.sqlite3'),cfg)
worker.start()
samples=[]
try:
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        state=worker.snapshot()
        if state['state']=='online': samples.append(state)
        time.sleep(.25)
finally: worker.stop()
assert samples,worker.snapshot()
import statistics
steady=samples[20:] or samples
report={k:steady[-1][k] for k in ('device','gpu','half','source_width','source_height','source_fps')}
report.update(processed_fps_median=statistics.median(s['fps'] for s in steady),inference_ms_median=statistics.median(s['inference_ms'] for s in steady),frame_age_ms_median=statistics.median(s['frame_age_ms'] for s in steady))
Path('test-results/rtsp-benchmark.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
TEMP.cleanup()
