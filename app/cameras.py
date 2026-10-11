"""Independent capture, tracking and appearance memory for each camera."""
import threading

from .camera import CameraWorker
from .config import CameraConfigView
from .recognition import Recognition


class CameraManager:
    def __init__(self, db, config, recognition):
        self.db, self.config = db, config
        self.lock = threading.RLock()
        self.running = False
        self.fall_handler = None  # Set by the application; receives suspected falls from every camera.
        self.presence_handler = None  # Receives each new presence record from every camera.
        self.restricted_handler = None  # Receives each visit to a restricted area (restricted mode).
        self.reminder_handler = None  # Receives (camera id, reminder text) when the father goes into a restricted area.
        self.workers = {}
        self.add_worker('main', recognition)

    def add_worker(self, camera_id, recognition):
        worker = CameraWorker(self.db, CameraConfigView(self.config, camera_id), recognition, camera_id)
        worker.on_fall = lambda *args: self.fall_handler and self.fall_handler(*args)
        worker.on_presence = lambda *args: self.presence_handler and self.presence_handler(*args)
        worker.on_restricted = lambda *args: self.restricted_handler and self.restricted_handler(*args)
        worker.on_reminder = lambda *args: self.reminder_handler and self.reminder_handler(*args)
        self.workers[camera_id] = worker
        return worker

    def get(self, camera_id='main'):
        with self.lock:
            if camera_id not in self.workers:
                raise KeyError('Câmera não encontrada.')
            return self.workers[camera_id]

    def sync(self):
        with self.lock:
            ids = {'main'} | {c.id for c in self.config.get().cameras}
            for camera_id in ids - self.workers.keys():
                worker = self.add_worker(camera_id, Recognition(self.db))
                if self.running:
                    worker.start()

    def remove(self, camera_id):
        with self.lock:
            if camera_id == 'main':
                raise ValueError('A câmera principal pode ser editada ou pausada; mantenha ao menos ela cadastrada.')
            worker = self.get(camera_id)
            worker.stop_event.set()
        # RTSP read timeouts must not block status/preview of the other cameras.
        worker.stop()
        if worker.thread and worker.thread.is_alive():
            raise ValueError('A câmera ainda está encerrando. Aguarde alguns segundos e tente remover novamente.')
        with self.lock:
            with self.config.lock:
                settings = self.config.get()
                settings.cameras = [c for c in settings.cameras if c.id != camera_id]
                self.config.save(settings)
            del self.workers[camera_id]

    def start(self):
        with self.lock:
            self.sync()
            self.running = True
            for worker in self.workers.values():
                worker.start()

    def stop(self):
        with self.lock:
            self.running = False
            # Signal everyone first, so slow RTSP shutdowns run concurrently.
            for worker in self.workers.values():
                worker.stop_event.set()
            for worker in self.workers.values():
                worker.stop()

    def snapshots(self):
        with self.lock:
            return [{'id': camera_id, 'name': worker.config.get().camera_name,
                     'enabled': worker.config.get().enabled,
                     'analysis_enabled': worker.config.get().analysis_enabled,
                     **worker.snapshot()} for camera_id, worker in self.workers.items()]
