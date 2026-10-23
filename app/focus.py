"""How sharp the picture is right now, and an assisted focus sweep.

The sharpness is the variance of the Laplacian of the region that matters (the person, or the middle of the picture when nobody is
there) shrunk to a fixed size. It is only measured while someone looks at it (the settings page), so it costs nothing the rest of the time.
The sweep moves the camera's manual focus through its range, reads the sharpness at each position and keeps the best one.
"""
import statistics
import time

import cv2

SIZE = (256, 256)
COARSE = tuple(range(0, 251, 25))   # Focus positions of a first pass ...
FINE_SPAN = 25                      # ... and the neighbourhood of the best one, in steps of 5.
SETTLE_SECONDS = .9                 # The focus motor needs this long to settle.
WINDOW_SECONDS = .7                 # Then the sharpness is read over this long.
MIN_SAMPLES = 3
CLEAR_PEAK = 1.15                   # The best position must be this much sharper than the typical one to be trusted.


def region_sharpness(frame, boxes):
    """(sharpness, region name) of the largest person box, or of the middle of the picture; None when the region is empty."""
    height, width = frame.shape[:2]
    if boxes:
        x1, y1, x2, y2 = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        name = 'pessoa'
    else:
        x1, y1, x2, y2 = width * .25, height * .25, width * .75, height * .75
        name = 'centro'
    crop = frame[max(0, int(y1)):min(height, int(y2)), max(0, int(x1)):min(width, int(x2))]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(cv2.resize(crop, SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()), name


def choose(scores):
    """(best position, whether the peak is clear) from {position: sharpness}."""
    if not scores:
        return None, False
    best = max(scores, key=scores.get)
    typical = statistics.median(scores.values())
    return best, typical > 0 and scores[best] >= CLEAR_PEAK * typical


class Sweep:
    """Runs the two passes; `set_focus(position)` and `read(window)` (list of sharpness values read for `window` seconds) come from the camera."""

    def __init__(self, set_focus, read, sleep=time.sleep, progress=None):
        self.set_focus, self.read, self.sleep, self.progress = set_focus, read, sleep, progress or (lambda done, total: None)
        self.scores = {}

    def measure(self, position):
        if position in self.scores:
            return
        self.set_focus(position)
        self.sleep(SETTLE_SECONDS)
        values = self.read(WINDOW_SECONDS)
        if len(values) >= MIN_SAMPLES:
            self.scores[position] = statistics.median(values)

    def run(self):
        total = len(COARSE) + 2 * FINE_SPAN // 5 + 1
        for done, position in enumerate(COARSE, 1):
            self.measure(position)
            self.progress(done, total)
        coarse_best, _ = choose(self.scores)
        if coarse_best is None:
            return {'best': None, 'clear': False, 'scores': {}}
        for step, position in enumerate(range(max(0, coarse_best - FINE_SPAN), min(250, coarse_best + FINE_SPAN) + 1, 5), len(COARSE) + 1):
            self.measure(position)
            self.progress(min(step, total), total)
        best, clear = choose(self.scores)
        return {'best': best, 'clear': clear, 'scores': dict(sorted(self.scores.items())), 'best_score': self.scores.get(best)}
