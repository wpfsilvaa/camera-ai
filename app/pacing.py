"""Ritmo do loop de vídeo: analisa menos quadros sem ninguém e grava no banco com menos frequência."""

# Seconds a person stays "active" after the last detection, so a brief miss does not slow analysis down.
ACTIVE_HOLD_SECONDS = 3.0
# An open event row only needs a fresh last_seen now and then; crash recovery tolerates a few seconds.
TOUCH_SECONDS = 5.0


class DetectionPacing:
    def __init__(self, hold=ACTIVE_HOLD_SECONDS):
        self.hold = hold
        self.last_active = None

    def reset(self):
        self.last_active = None

    def idle(self, now):
        return self.last_active is None or now - self.last_active >= self.hold

    def fps(self, settings, active, now):
        """Analysis rate: full while someone is around (or just left), idle rate otherwise."""
        if active:
            self.last_active = now
        if self.last_active is not None and now - self.last_active < self.hold:
            return settings.detection_fps
        return min(settings.idle_detection_fps, settings.detection_fps)


class TouchThrottle:
    def __init__(self, seconds=TOUCH_SECONDS):
        self.seconds = seconds
        self.reset()

    def reset(self):
        self.last = 0
        self.count = 0

    def due(self, now, count):
        """True when the event row should be written: interval elapsed, or a new peak of people."""
        if now - self.last >= self.seconds or count > self.count:
            self.last = now
            self.count = max(self.count, count)
            return True
        return False


# Even a still room is fully analysed this often, so a person who sits or lies motionless is not missed.
FORCE_SECONDS = 2.0
# Watch mode (night): the room is checked for motion at a low frame rate; a full analysis still runs this often.
SENTINEL_FORCE_SECONDS = 30.0
MOTION_SIZE = (160, 90)
PIXEL_DELTA = 20
CHANGED_SHARE = .002  # share of pixels that must change to count as motion


class MotionGate:
    """Cheap frame difference deciding whether the YOLO model needs to run on an idle room."""

    def __init__(self, force_seconds=FORCE_SECONDS, delta=PIXEL_DELTA, share=CHANGED_SHARE):
        self.force_seconds = force_seconds
        self.delta = delta
        self.share = share
        self.reset()

    def reset(self):
        self.previous = None
        self.last_full = None

    def skip(self, frame, now):
        """True when the frame shows no motion and a full analysis ran recently enough."""
        import cv2
        small = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        previous, self.previous = self.previous, small
        moved = previous is None or (cv2.absdiff(small, previous) > self.delta).mean() >= self.share
        stale = self.last_full is None or now - self.last_full >= self.force_seconds
        if moved or stale:
            self.last_full = now
            return False
        return True


def in_window(hour, start, end):
    """True when the hour falls in [start, end), wrapping past midnight (22 to 6); start == end means never."""
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end
