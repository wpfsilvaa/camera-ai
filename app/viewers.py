"""Who is watching the live camera right now (open video streams), so the kitchen screen can show a small marker."""
import threading
from contextlib import contextmanager


class Viewers:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}

    @contextmanager
    def watch(self, camera_id):
        """Held for as long as one viewer's video stream stays open."""
        with self.lock:
            self.counts[camera_id] = self.counts.get(camera_id, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.counts[camera_id] -= 1

    def count(self, camera_id):
        with self.lock:
            return self.counts.get(camera_id, 0)

    def total(self):
        with self.lock:
            return sum(self.counts.values())
