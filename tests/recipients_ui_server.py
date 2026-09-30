"""Isolated recipient settings/history fixture; no real WhatsApp connection."""
import sys,time
import cv2,numpy as np,uvicorn
from app import main
from app.config import Settings,CLIPS
main.config.save(Settings(enabled=False,whatsapp_enabled=False,recipient='5511999999999',additional_recipients=['5511888888888']))
now=time.time();event=main.db.start_event(now-60,1)
main.db.end_event(event,now-50,'absence')
main.db.execute("UPDATE events SET identity='father' WHERE id=?",(event,))
clip='a'*32
main.db.execute("INSERT INTO clips(id,event_id,started,ended,duration,state,delivery) VALUES(?,?,?,?,10,'ready','partial')",(clip,event,now-60,now-50))
for phone,state in [('5511999999999','sent'),('5511888888888','failed')]:
 main.db.execute('INSERT INTO clip_deliveries(clip_id,recipient,delivery) VALUES(?,?,?)',(clip,phone,state))
cv2.imwrite(str(CLIPS/f'{clip}.jpg'),np.zeros((120,160,3),dtype=np.uint8))
requests=[]
async def gateway(method,path,payload=None):
 if path=='/status':return {'state':'connected','qr':None,'error':None}
 requests.append({'path':path,'payload':payload});return {'ok':True}
main.gateway=gateway
@main.app.get('/test-requests')
def received_requests():return requests
uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
