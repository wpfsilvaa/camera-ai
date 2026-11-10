"""Servidor isolado com 25 registros de presença, para testar avançar/voltar no histórico."""
import sys,time,uvicorn
from app.db import Database
db=Database()
now=time.time()
for i in range(25):
    e=db.start_event(now-3600-i*600,1,camera_name='Sala')
    db.end_event(e,now-3590-i*600,'absence')
uvicorn.run('app.main:app',host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
