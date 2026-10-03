import gc
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

from .config import DATA, MODEL, POSE_MODEL, CAMERA_FIELDS
os.environ.setdefault('YOLO_CONFIG_DIR', str(DATA / 'ultralytics'))
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp')

import cv2
import numpy as np

from .falls import FallDetector
from .overlay import annotate, draw_zones
from .presence import Presence
from .tracking import PersonTracker
from .recorder import Recorder
from .recognition import Recognition

log = logging.getLogger(__name__)
# Ultralytics initialization touches process-wide configuration; serialize warmup.
MODEL_LOAD_LOCK = threading.Lock()


def resize_width(frame, limit):
    height,width=frame.shape[:2]
    if width<=limit:
        return frame
    # Up to 2x (1080p -> 720p preview) bilinear looks the same and costs ~4x less than INTER_AREA,
    # which ran on every frame of the camera loop; larger reductions keep INTER_AREA against aliasing.
    interpolation=cv2.INTER_AREA if width>2*limit else cv2.INTER_LINEAR
    return cv2.resize(frame,(limit,round(height*limit/width)),interpolation=interpolation)


class LiveFrames:
    """Continuously drain RTSP and keep one latest frame instead of a backlog."""
    def __init__(self, capture):
        self.capture=capture
        self.condition=threading.Condition()
        self.stopping=threading.Event()
        self.frame=None
        self.timestamp=0
        self.sequence=0
        self.arrivals=deque(maxlen=90)
        self.consumed=0
        self.failed=False
        self.thread=threading.Thread(target=self.run,daemon=True,name='rtsp-reader')
        self.thread.start()

    def run(self):
        while not self.stopping.is_set():
            ok,frame=self.capture.read()
            with self.condition:
                if not ok:
                    self.failed=True
                    self.condition.notify_all()
                    return
                self.frame=frame
                self.timestamp=time.time()
                self.sequence+=1
                self.arrivals.append(time.monotonic())
                self.condition.notify_all()

    def read(self):
        with self.condition:
            self.condition.wait_for(lambda:self.failed or self.sequence!=self.consumed,timeout=6)
            if self.failed or self.sequence==self.consumed:
                return False,None,0
            self.consumed=self.sequence
            # OpenCV read allocates a new array; readers never mutate this frame.
            return True,self.frame,self.timestamp

    def measured_fps(self):
        with self.condition:
            return (len(self.arrivals)-1)/(self.arrivals[-1]-self.arrivals[0]) if len(self.arrivals)>1 else 0

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=7)


class CameraWorker:
    def __init__(self, db, config, recognition=None, camera_id='main'):
        self.db,self.config=db,config
        self.camera_id=camera_id
        self.recognition=recognition or Recognition(db)
        self.stop_event=threading.Event()
        self.lock=threading.Lock()
        self.thread=None
        self.manual_requested=False
        self.falls=FallDetector()
        # Called with (camera_id, camera_name, jpeg bytes, seconds lying) when a fall is suspected.
        self.on_fall=None
        self.on_presence=None  # Called with (camera_id, camera_name, time) when a presence record starts.
        self.jpeg=None
        self.sequence=0
        self.status={'state':'paused','people':0,'last_frame':None,'event_id':None,'error':None,
                     'inference_ms':None,'detection_fps':0,'fps':0,'frame_age_ms':None,'device':None,'gpu':None,'half':False,
                     'analysis_active':False,'manual_recording':False,'manual_requested':False,'manual_event_id':None,
                     'source_width':None,'source_height':None,'source_fps':None,'input_fps':None,'tracks':[]}

    def update(self, **values):
        with self.lock:
            self.status.update(values)

    def snapshot(self):
        with self.lock:
            result=self.status.copy()
        if result['state']=='online' and result['last_frame'] and time.time()-result['last_frame']>5:
            result.update(state='offline',error='Câmera sem imagens recentes.',people=0,tracks=[])
        return result

    def request_recording(self, enabled):
        with self.lock:
            if enabled and (self.status['state']!='online' or not self.status['last_frame'] or time.time()-self.status['last_frame']>5):
                raise ValueError('Inicie a câmera e aguarde a imagem para gravar.')
            self.manual_requested=enabled
            self.status['manual_requested']=enabled
        return {'requested':enabled}

    def check_falls(self, result, tracker, boxes, ids, frame, now, settings):
        """Update lying durations from pose keypoints and report new suspected falls."""
        if not settings.fall_detection_enabled or result.keypoints is None:
            self.falls.reset()
            return {}
        points=result.keypoints.data.cpu().numpy()
        keypoints=[points[i] if i<len(points) else None for i in tracker.last_indices]
        height,width=frame.shape[:2]
        lying,falls=self.falls.update(now,boxes,ids,keypoints,(width,height),settings.fall_zones,settings.fall_seconds)
        if falls and self.on_fall:
            snapshot=annotate(frame,boxes,ids,{},lying)
            encoded,jpeg=cv2.imencode('.jpg',resize_width(snapshot,1280),[cv2.IMWRITE_JPEG_QUALITY,85])
            if encoded:
                try:
                    self.on_fall(self.camera_id,settings.camera_name,jpeg.tobytes(),max(lying[k] for k in falls))
                except Exception:
                    log.exception('Falha ao registrar possível queda')
        return lying

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name=f'camera-{self.camera_id}')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=20)
        self.recognition.stop()

    def run(self):
        model=None
        tracker=None
        model_options=None
        result=None
        def release_model():
            nonlocal model,model_options,result,tracker
            self.recognition.stop()
            self.recognition.reset_tracks()
            result=None;model=None;model_options=None;tracker=None
            gc.collect()
            import sys
            torch=sys.modules.get('torch')
            if torch is not None and torch.cuda.is_initialized():torch.cuda.empty_cache()
            self.update(device=None,gpu=None,half=False,analysis_active=False)
        cv2.setNumThreads(2)
        while not self.stop_event.is_set():
            settings=self.config.get()
            if not settings.enabled or not settings.analysis_enabled:
                if model is not None or (self.recognition.thread and self.recognition.thread.is_alive()):
                    release_model()
            if not settings.enabled:
                self.update(state='paused',people=0,event_id=None,error=None,fps=0,tracks=[])
                self.stop_event.wait(.3)
                continue
            cap=live=None
            recorder=Recorder(self.db)
            manual_recorder=Recorder(self.db)
            manual_event=None
            analysis_active=None
            event_id=None
            latest_time=time.time()
            reason='stopped'
            tracker=None
            presence=Presence(settings.min_presence_seconds,settings.absence_seconds)
            self.recognition.reset_tracks()
            last_recognition=last_db_touch=0
            rates=deque(maxlen=90)
            try:
                self.update(state='connecting',error=None,people=0)
                source=settings.camera_source
                is_file=not source.isdigit() and '://' not in source
                cap=cv2.VideoCapture(int(source)) if source.isdigit() else cv2.VideoCapture(source,cv2.CAP_FFMPEG,
                    [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,5000])
                if not cap.isOpened():
                    raise RuntimeError('Não foi possível abrir a câmera. Confira endereço, rede e transmissão.')
                cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
                source_fps=cap.get(cv2.CAP_PROP_FPS)
                if not np.isfinite(source_fps) or source_fps<1 or source_fps>120:
                    source_fps=30
                self.update(source_width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),source_height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),source_fps=round(source_fps,1))
                next_frame=next_detection=0
                detected_boxes=[];detected_ids=[];last_inference_ms=None;detected_lying={}
                detections=deque(maxlen=90)
                file_start=time.time()
                file_frames=0
                if not is_file:
                    live=LiveFrames(cap)
                while not self.stop_event.is_set():
                    current=self.config.get()
                    restart=('camera_source','fps','confidence','min_presence_seconds','absence_seconds','segment_seconds','recognition_enabled','device','detection_size','detection_fps','recording_width','camera_name')
                    if not current.enabled or any(getattr(current,k)!=getattr(settings,k) for k in restart):
                        reason='settings_changed'
                        break
                    if live:
                        ok,original,now=live.read()
                    else:
                        ok,original=cap.read()
                        due=file_start+file_frames/source_fps
                        file_frames+=1
                        self.stop_event.wait(max(0,due-time.time()))
                        now=time.time()
                    if not ok:
                        if is_file:
                            reason='file_ended'
                            current.enabled=False
                            self.config.save(current)
                            break
                        raise RuntimeError('A câmera parou de enviar imagens. Tentando reconectar.')
                    if now<next_frame:
                        continue
                    # Tolerance avoids accidentally reducing a 30 fps source to 15 fps.
                    next_frame=now+1/settings.fps-.003
                    if analysis_active != current.analysis_enabled:
                        if event_id is not None:
                            recorder.finish(latest_time)
                            self.db.end_event(event_id,latest_time,'analysis_paused')
                            event_id=None
                        presence=Presence(settings.min_presence_seconds,settings.absence_seconds)
                        self.recognition.stop()
                        self.recognition.reset_tracks()
                        if not current.analysis_enabled:
                            release_model()
                        tracker=None
                        detected_boxes=[];detected_ids=[];last_inference_ms=None;detected_lying={}
                        detections.clear();next_detection=0
                        self.falls.reset()
                        analysis_active=current.analysis_enabled
                        self.update(analysis_active=analysis_active)
                    with self.lock:
                        manual_wanted=self.manual_requested
                    if manual_wanted and manual_event is None:
                        if event_id is not None:
                            recorder.finish(latest_time)
                            self.db.end_event(event_id,latest_time,'manual_started')
                            event_id=None
                        presence=Presence(settings.min_presence_seconds,settings.absence_seconds)
                        manual_event=self.db.start_event(now,0,'manual',self.camera_id,settings.camera_name,
                            settings.model_dump(include=CAMERA_FIELDS-{'camera_source'}))
                    elif not manual_wanted and manual_event is not None:
                        manual_recorder.finish(latest_time)
                        self.db.end_event(manual_event,latest_time,'manual_stopped')
                        manual_event=None
                        presence=Presence(settings.min_presence_seconds,settings.absence_seconds)
                    boxes=[];ids=[];labels={};count=0;inference_ms=None;action=None
                    lying={}
                    if analysis_active and now>=next_detection:
                        setup_started=time.time()
                        import torch
                        cuda=settings.device!='cpu' and torch.cuda.is_available()
                        if settings.device=='cuda' and not cuda:
                            raise RuntimeError('CUDA solicitado, mas a GPU não está acessível. Verifique o driver ou selecione Auto.')
                        device=0 if cuda else 'cpu'
                        half=cuda
                        torch.set_num_threads(2)
                        if cuda:
                            torch.backends.cudnn.benchmark=True
                        weights=POSE_MODEL if current.fall_detection_enabled else MODEL
                        options=(device,half,settings.detection_size,weights)
                        if model is None or model_options!=options:
                            load_started=setup_started
                            if not Path(weights).is_file():
                                raise RuntimeError('Modelo YOLO não encontrado. Verifique YOLO_MODEL/POSE_MODEL ou execute scripts/download_models.py.')
                            with MODEL_LOAD_LOCK:
                                from ultralytics import YOLO
                                model=YOLO(weights)
                                self.falls.reset()
                                if model.names.get(0)!='person':
                                    raise RuntimeError('O modelo precisa detectar a classe person (0).')
                                # Warm up at the actual inference shape before opening the video.
                                model.predict(np.zeros((settings.detection_size,settings.detection_size,3),dtype=np.uint8),
                                              device=device,quantize=16 if half else 32,imgsz=settings.detection_size,verbose=False)
                            model_options=options
                            tracker=None
                            if is_file:
                                # Loading a model must not consume the beginning of a
                                # file as if playback had already advanced during warmup.
                                loading=time.time()-load_started
                                file_start+=loading
                                now+=loading
                                next_frame=now+1/settings.fps-.003
                            else:
                                # RTSP reader kept draining: use its latest frame next.
                                continue
                        self.update(device='cuda:0' if cuda else 'cpu',gpu=torch.cuda.get_device_name(0) if cuda else None,half=bool(model.predictor.model.fp16))
                        if settings.recognition_enabled:
                            self.recognition.start()
                        begin=time.perf_counter()
                        if tracker is None:
                            tracker=PersonTracker(settings.confidence)
                        result=model.predict(original,classes=[0],conf=tracker.low_confidence,imgsz=settings.detection_size,
                            device=device,quantize=16 if half else 32,max_det=20,verbose=False)[0]
                        boxes,ids=tracker.update(result.boxes,original,now)
                        detected_lying=self.check_falls(result,tracker,boxes,ids,original,now,current)
                        count=len(boxes)
                        inference_ms=round((time.perf_counter()-begin)*1000,1)
                        result=None
                        detected_boxes,detected_ids=boxes,ids
                        last_inference_ms=inference_ms
                        next_detection=now+1/current.detection_fps-.003
                        detections.append(time.perf_counter())
                        if manual_event is None:
                            action=presence.update(now,count)
                            if action=='start':
                                event_id=self.db.start_event(now,count,camera_id=self.camera_id,camera_name=settings.camera_name,
                                    camera_settings=settings.model_dump(include=CAMERA_FIELDS-{'camera_source'}))
                                if self.on_presence:
                                    try:
                                        self.on_presence(self.camera_id,settings.camera_name,now)
                                    except Exception:
                                        log.exception('Falha ao avisar sobre a presença')
                            if event_id is not None and count and now-last_db_touch>=.5:
                                self.db.touch_event(event_id,now,count)
                                last_db_touch=now
                        if current.recognition_enabled and now-last_recognition>=.30:
                            last_recognition=now
                            self.recognition.submit(event_id,original,boxes,ids,now,current)
                        labels=self.recognition.labels(ids,boxes,now,current.face_hold_seconds) if current.recognition_enabled else {}
                    if analysis_active:
                        lying=detected_lying
                        boxes,ids=detected_boxes,detected_ids
                        count=len(boxes)
                        inference_ms=last_inference_ms
                        labels=self.recognition.labels(ids,boxes,now,current.face_hold_seconds) if current.recognition_enabled else {}
                    latest_time=now
                    annotated=annotate(original,boxes,ids,labels,lying) if analysis_active else original
                    if event_id is not None:
                        recorded=resize_width(annotated,settings.recording_width)
                        if recorder.writer is None:
                            recorder.start(event_id,recorded,now,settings.fps)
                        else:
                            recorder.write(recorded,now)
                        if action=='end':
                            recorder.finish(now)
                            self.db.end_event(event_id,now,'absence')
                            event_id=None
                        elif now-recorder.start_time>=settings.segment_seconds:
                            recorder.finish(now)
                    if manual_event is not None:
                        recorded=resize_width(original,settings.recording_width)
                        if manual_recorder.writer is None:
                            manual_recorder.start(manual_event,recorded,now,settings.fps)
                        else:
                            manual_recorder.write(recorded,now)
                        if now-manual_recorder.start_time>=settings.segment_seconds:
                            manual_recorder.finish(now)
                        if now-last_db_touch>=.5:
                            self.db.touch_event(manual_event,now,count)
                            last_db_touch=now
                    preview=resize_width(annotated,current.preview_width)
                    if analysis_active and current.fall_detection_enabled:
                        preview=draw_zones(preview,current.fall_zones)
                    encoded,jpeg=cv2.imencode('.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,78])
                    if encoded:
                        with self.lock:
                            self.jpeg=jpeg.tobytes()
                            self.sequence+=1
                    rates.append(time.perf_counter())
                    fps=(len(rates)-1)/(rates[-1]-rates[0]) if len(rates)>1 else 0
                    tracks=[{'id':key,'name':labels.get(str(key),{}).get('name'),'person_id':labels.get(str(key),{}).get('person_id'),'lying_seconds':round(lying[key]) if key in lying else None,
                             'held':labels.get(str(key),{}).get('held',False),
                             'source':labels.get(str(key),{}).get('source')} for key in ids]
                    self.update(state='online',error=None,people=count,last_frame=now,event_id=event_id,
                        input_fps=round(live.measured_fps(),1) if live else source_fps,
                        manual_event_id=manual_event,manual_recording=manual_event is not None,
                        inference_ms=inference_ms,detection_fps=round((len(detections)-1)/(detections[-1]-detections[0]),1) if len(detections)>1 else 0,fps=round(fps,1),frame_age_ms=round((time.time()-now)*1000,1),tracks=tracks)
            except Exception as exc:
                reason='camera_error'
                message=str(exc) if isinstance(exc,RuntimeError) else f'Falha na captura/detecção ({type(exc).__name__}). Confira os requisitos e a câmera.'
                self.update(state='offline',error=message,people=0,event_id=None,tracks=[])
                log.exception('Camera worker: %s',message)
            finally:
                if live is not None:
                    live.close()
                if cap is not None:
                    cap.release()
                manual_recorder.finish(latest_time)
                if manual_event is not None:
                    self.db.end_event(manual_event,latest_time,reason)
                with self.lock:
                    self.manual_requested=False
                self.update(manual_recording=False,manual_requested=False,manual_event_id=None)
                recorder.finish(latest_time)
                if event_id is not None:
                    self.db.end_event(event_id,latest_time,reason)
                with self.lock:
                    self.jpeg=None
                self.recognition.reset_tracks()
                self.update(event_id=None,people=0,tracks=[])
            if reason=='camera_error':
                self.stop_event.wait(5)

        release_model()
