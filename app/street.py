"""Street mode: with the house empty, an unknown person on a guarded camera raises an intruder alert.

The mode is switched on and off from the app and survives restarts. A stranger must stay in view for the
entry delay (time to open the app and switch the mode off, and for face recognition to name a family member)
before the alert goes out; after an alert the same camera stays quiet for REPEAT seconds.
"""
import json
import threading
import time

from .config import DATA

STATE = DATA / 'street_mode.json'
GAP = 10       # Seconds without a stranger before the wait starts over.
REPEAT = 120   # Seconds between two alerts from the same camera.


class StreetMode:
    def __init__(self, path=STATE):
        self.path, self.lock = path, threading.Lock()
        self.pending, self.alerted = {}, {}
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        self.armed, self.since = bool(saved.get('armed')), saved.get('since')

    def state(self):
        return {'armed': self.armed, 'since': self.since}

    def set(self, armed, now=None):
        with self.lock:
            self.armed = bool(armed)
            self.since = (now or time.time()) if self.armed else None
            self.pending.clear()
            self.alerted.clear()
            self.path.write_text(json.dumps(self.state()))
        return self.state()

    def update(self, camera_id, stranger, now, delay):
        """Called every frame of a guarded camera; True when an intruder alert is due now."""
        if not self.armed:
            return False
        with self.lock:
            wait = self.pending.get(camera_id)
            if wait and now - wait['last'] > GAP:
                wait = self.pending.pop(camera_id)
                wait = None
            if not stranger:
                return False
            if wait is None:
                wait = self.pending[camera_id] = {'first': now, 'last': now}
            wait['last'] = now
            last = self.alerted.get(camera_id)
            if now - wait['first'] < delay or (last is not None and now - last < REPEAT):
                return False
            self.alerted[camera_id] = now
            self.pending.pop(camera_id, None)
            return True
