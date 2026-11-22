"""Manual: what the tracker with appearance (BoT-SORT + clothes) costs against the plain one, with the real ReID network.

Usage: PYTHONPATH=. .venv/bin/python tests/tracker_benchmark.py
No detector runs: boxes are synthetic over a real photo, so only the tracker and the ReID network are timed.
"""
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ultralytics.engine.results import Boxes

from app.tracking import PersonTracker

frame = cv2.resize(cv2.imread(str(ROOT / 'tests/assets/messi5.jpg')), (1280, 720))


def run(appearance, scenario, frames=150):
    tracker = PersonTracker(.5, 4., appearance=appearance)
    if appearance and not tracker.appearance:
        return None
    times = []
    for n in range(frames):
        rows = scenario(n)
        boxes = Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), frame.shape[:2])
        started = time.perf_counter()
        tracker.update(boxes, frame, n / 5)
        times.append((time.perf_counter() - started) * 1000)
    cost = tracker.cost()
    return statistics.mean(times[10:]), max(times), cost['encodes_per_100']


def still(n):   # Two people standing: after the first frame nothing is new.
    return [[100, 100, 300, 600, .9, 0], [700, 100, 900, 600, .9, 0]]


def coming_and_going(n):   # Somebody walks in and out every 25 frames (5 s).
    rows = [[100, 100, 300, 600, .9, 0]]
    if (n // 25) % 2:
        rows.append([700 + (n % 25) * 4, 100, 900 + (n % 25) * 4, 600, .9, 0])
    return rows


def worst_case(n):   # Four people jumping to a new place each frame: nothing can be reused.
    return [[(n * 97 + i * 300) % 1000, 100, (n * 97 + i * 300) % 1000 + 200, 600, .9, 0] for i in range(4)]


print(f'{"cenário":<22}{"comum (ms/quadro)":>20}{"aparência (média / pico)":>28}{"rede a cada 100 quadros":>26}')
for name, scenario in (('duas pessoas paradas', still), ('entra e sai alguém', coming_and_going), ('pior caso (4 pulando)', worst_case)):
    plain = run(False, scenario)
    appearance = run(True, scenario)
    if appearance is None:
        print(f'{name:<22}{plain[0]:>20.2f}{"modelo ReID ausente":>28}')
    else:
        print(f'{name:<22}{plain[0]:>20.2f}{appearance[0]:>17.2f} / {appearance[1]:>6.1f}{appearance[2]:>26.1f}')
