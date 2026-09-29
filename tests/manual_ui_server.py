"""Isolated real capture/API/analysis server; never connects to WhatsApp."""
import sys
from pathlib import Path
import cv2,numpy as np,ultralytics,uvicorn
from app.config import config,Settings,DATA
from app.db import Database
from app.recognition import Recognition
cv2.setNumThreads(2)
photo=cv2.imread(str(Path(ultralytics.__file__).parent/'assets/zidane.jpg'))[:,744:]
frame=np.full((720,1280,3),35,dtype=np.uint8);frame[:,300:300+photo.shape[1]]=photo
video=DATA/'input.avi'
w=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(1280,720))
for _ in range(90*10):w.write(frame)
w.release()
config.save(Settings(camera_source=str(video),enabled=True,analysis_enabled=False,fps=10))
r=Recognition(Database());r.rename_person('father','Referência de teste');r.enroll('father',photo)
uvicorn.run('app.main:app',host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
