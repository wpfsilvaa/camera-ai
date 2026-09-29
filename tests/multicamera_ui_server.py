"""Isolated real capture server; all WhatsApp delivery disabled."""
import sys
import cv2, numpy as np, uvicorn
from app.config import config,Settings,DATA
cv2.setNumThreads(2)
for name,width,color in [('first',640,(35,70,100)),('second',800,(110,50,30))]:
    frame=np.full((480,width,3),color,dtype=np.uint8)
    writer=cv2.VideoWriter(str(DATA/f'{name}.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(width,480))
    for index in range(1200):
        view=frame.copy();cv2.putText(view,str(index),(50,100),cv2.FONT_HERSHEY_SIMPLEX,2,(255,255,255),3);writer.write(view)
    writer.release()
config.save(Settings(camera_name='Cozinha',camera_source=str(DATA/'first.avi'),enabled=True,analysis_enabled=False,fps=10,device='cpu'))
uvicorn.run('app.main:app',host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
