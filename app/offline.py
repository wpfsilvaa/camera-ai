"""Explicit, cancellable analysis of completed manual recordings in a child process."""
import json
import os
import subprocess
import sys
import threading

from .config import CLIPS, DATA, PEOPLE, ROOT


class OfflineAnalysis:
    def __init__(self, db):
        self.db=db
        self.lock=threading.Lock()
        self.process=None
        self.event_id=None

    def status(self):
        with self.lock:
            return {'event_id':self.event_id if self.process and self.process.poll() is None else None}

    def start(self, event_id):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise ValueError('Já existe uma análise em andamento. Aguarde ou cancele.')
            rows=self.db.rows('SELECT * FROM events WHERE id=?',(event_id,))
            if not rows:raise KeyError('Registro não encontrado.')
            event=rows[0]
            if event['kind']!='manual' or event['ended'] is None:
                raise ValueError('Escolha uma gravação manual encerrada.')
            if event['analysis_state']=='complete':raise ValueError('Este vídeo já foi analisado.')
            clips=self.db.rows('SELECT * FROM clips WHERE event_id=?',(event_id,))
            if not clips or any(c['state']!='ready' for c in clips):
                raise ValueError('Aguarde todos os vídeos ficarem prontos para reprodução.')
            if self.db.rows('SELECT id FROM person_tracks WHERE event_id=? AND reviewed=1',(event_id,)):
                raise ValueError('Este registro já tem identificações confirmadas. Elas serão preservadas.')
            self.db.execute("UPDATE events SET analysis_state='running',analysis_progress=0,analysis_error=NULL WHERE id=?",(event_id,))
            try:
                fd=os.open(DATA/'offline.log',os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
                with os.fdopen(fd,'ab',buffering=0) as output:
                    self.process=subprocess.Popen([sys.executable,'-m','app.offline',str(event_id)],cwd=ROOT,
                        stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
                self.event_id=event_id
                threading.Thread(target=self._watch,args=(self.process,event_id),daemon=True).start()
            except Exception:
                self.db.execute("UPDATE events SET analysis_state='failed',analysis_error='Não foi possível iniciar a análise.' WHERE id=?",(event_id,))
                raise
            return {'event_id':event_id,'state':'running'}

    def _watch(self, process, event_id):
        process.wait()
        with self.lock:
            if self.process is not process:
                return
            self.db.execute("UPDATE events SET analysis_state='failed',analysis_error='A análise foi interrompida. Tente novamente.' WHERE id=? AND analysis_state='running'",(event_id,))
            for clip in self.db.rows('SELECT id FROM clips WHERE event_id=?',(event_id,)):
                for suffix in ('analysis.avi','analysis.tmp.mp4'):
                    (CLIPS/f"{clip['id']}.{suffix}").unlink(missing_ok=True)

    def cancel(self):
        with self.lock:
            process=self.process
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                self.db.execute("UPDATE events SET analysis_state='cancelled',analysis_error='Análise cancelada; o vídeo original foi preservado.' WHERE id=? AND analysis_state='running'",(self.event_id,))
            return {'ok':True}


def analyze(event_id):
    import cv2
    import shutil
    import numpy as np
    import torch
    from ultralytics import YOLO
    from . import detectors
    from .config import config
    from .db import Database
    from .recognition import Recognition
    from .overlay import annotate
    from .tracking import PersonTracker
    db=Database()
    clips=db.rows('SELECT * FROM clips WHERE event_id=? ORDER BY started',(event_id,))
    settings=config.get()
    event=db.rows('SELECT camera_settings FROM events WHERE id=?',(event_id,))[0]
    settings=settings.model_copy(update=json.loads(event['camera_settings']))
    recognition=Recognition(db)
    tracker=PersonTracker(settings.confidence)
    cv2.setNumThreads(2);torch.set_num_threads(2)
    cuda=settings.device!='cpu' and torch.cuda.is_available()
    if settings.device=='cuda' and not cuda:raise RuntimeError('GPU CUDA indisponível.')
    weights,task,engine=detectors.ensure(settings.detector_model,settings.detector_engine,False,settings.detection_size)
    cuda=cuda and engine=='pytorch'
    model=YOLO(weights,task=task)
    if model.names.get(0)!='person':raise RuntimeError('O modelo precisa detectar pessoas na classe 0.')
    recognition.ensure_encoder()
    if settings.body_reid_enabled:
        from .body import BodyEncoder
        recognition.body_encoder=BodyEncoder()
    # A cancelled run may have provisional results; no reviewed records are removed.
    old=db.rows('SELECT s.id FROM person_samples s JOIN person_tracks t ON t.id=s.track_id WHERE t.event_id=?',(event_id,))
    with db.connect() as connection:
        connection.execute('DELETE FROM person_samples WHERE track_id IN (SELECT id FROM person_tracks WHERE event_id=?)',(event_id,))
        connection.execute('DELETE FROM person_tracks WHERE event_id=?',(event_id,))
    for sample in old:(PEOPLE/f"{sample['id']}.jpg").unlink(missing_ok=True)
    total=sum(c['duration'] for c in clips) or 1
    completed=0
    peak_people=0
    last_recognition=-float('inf')
    outputs=[]
    for clip in clips:
        if shutil.disk_usage(CLIPS).free < 512*1024*1024:
            raise RuntimeError('Menos de 512 MB livres para analisar. Libere espaço.')
        source=CLIPS/f"{clip['id']}.mp4"
        pending=CLIPS/f"{clip['id']}.analysis.tmp.mp4"
        temporary=CLIPS/f"{clip['id']}.analysis.avi"
        capture=cv2.VideoCapture(str(source))
        writer=None
        try:
            if not capture.isOpened():raise RuntimeError('Não foi possível abrir a gravação.')
            fps=capture.get(cv2.CAP_PROP_FPS)
            if not np.isfinite(fps) or fps<=0:raise RuntimeError('Taxa de quadros inválida.')
            frame_index=0
            while True:
                ok,frame=capture.read()
                if not ok:break
                now=clip['started']+frame_index/fps
                result=model.predict(frame,classes=[0],conf=tracker.low_confidence,imgsz=settings.detection_size,
                    device=0 if cuda else 'cpu',quantize=16 if cuda else 32,verbose=False)[0]
                boxes,ids=tracker.update(result.boxes,frame,now)
                peak_people=max(peak_people,len(boxes))
                if now-last_recognition>=.3:
                    diagnostics={}
                    faces=recognition.encoder.for_people(frame,boxes,ids,diagnostics)
                    bodies=recognition.body_encoder.for_people(frame,boxes,ids,diagnostics) if recognition.body_encoder else {}
                    recognition.observe_faces(event_id,boxes,ids,faces,now,settings,bodies,diagnostics)
                    last_recognition=now
                labels=recognition.labels(ids,boxes,now,settings.face_hold_seconds)
                annotated=annotate(frame,boxes,ids,labels)
                if writer is None:
                    h,w=frame.shape[:2]
                    writer=cv2.VideoWriter(str(temporary),cv2.VideoWriter_fourcc(*'MJPG'),fps,(w,h))
                    if not writer.isOpened():raise RuntimeError('Não foi possível gravar o vídeo identificado.')
                writer.write(annotated)
                frame_index+=1
                if frame_index%15==0:
                    progress=min(99,100*(completed+frame_index/fps)/total)
                    db.execute('UPDATE events SET analysis_progress=?,max_people=MAX(max_people,?) WHERE id=?',(progress,peak_people,event_id))
            if not frame_index:raise RuntimeError('Gravação vazia.')
        finally:
            capture.release()
            if writer:writer.release()
        # Convert in a child that is explicitly terminated if this process receives SIGTERM.
        convert=subprocess.Popen(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(temporary),
            '-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(pending)],
            stdin=subprocess.DEVNULL)
        try:
            if convert.wait(timeout=300)!=0:raise RuntimeError('Falha ao converter o vídeo identificado.')
        finally:
            if convert.poll() is None:
                convert.terminate()
                try:convert.wait(timeout=5)
                except subprocess.TimeoutExpired:convert.kill();convert.wait(timeout=5)
        temporary.unlink(missing_ok=True)
        outputs.append((clip['id'],pending))
        completed+=clip['duration']
    for clip_id,pending in outputs:
        pending.replace(CLIPS/f'{clip_id}.analyzed.mp4')
    with db.connect() as connection:
        connection.execute('UPDATE clips SET analyzed=1 WHERE event_id=?',(event_id,))
        connection.execute("UPDATE events SET analysis_state='complete',analysis_progress=100,analysis_error=NULL,max_people=MAX(max_people,?) WHERE id=?",(peak_people,event_id))


if __name__=='__main__':
    import signal
    from .db import Database
    event_id=int(sys.argv[1])
    def terminate(_signum,_frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,terminate)
    try:analyze(event_id)
    except Exception as error:
        Database().execute("UPDATE events SET analysis_state='failed',analysis_error=? WHERE id=?",(f'Falha na análise ({type(error).__name__}): {str(error)[:160]}',event_id))
        raise
