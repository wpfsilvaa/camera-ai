"""Calibrate fall detection with a recorded video, without sending anything.

    .venv/bin/python scripts/fall_replay.py data/clips/<id>.mp4 --seconds 45 --zone 0.55,0.40,1,1

Prints, for each person, how long they stayed lying outside the ignored areas and whether an
alert would have been sent. Record the father lying on the sofa or bed and check that no alert
appears; draw zones (x1,y1,x2,y2 from 0 to 1, left/top = 0) until it holds.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def replay(video, seconds=45, zones=(), device='cpu', analysis_fps=5, size=640, confidence=.5):
    import cv2
    from ultralytics import YOLO

    from app.config import POSE_MODEL
    from app.falls import FallDetector
    from app.tracking import PersonTracker

    model, tracker, detector = YOLO(POSE_MODEL), PersonTracker(confidence), FallDetector()
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps / analysis_fps))
    longest, alerts, frame_number = {}, [], 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_number += 1
        if frame_number % step:
            continue
        now = frame_number / fps
        result = model.predict(frame, classes=[0], conf=tracker.low_confidence, imgsz=size, device=device, verbose=False)[0]
        boxes, ids = tracker.update(result.boxes, frame, now)
        points = result.keypoints.data.cpu().numpy() if result.keypoints is not None else []
        keypoints = [points[i] if i < len(points) else None for i in tracker.last_indices]
        height, width = frame.shape[:2]
        lying, falls = detector.update(now, boxes, ids, keypoints, (width, height), list(zones), seconds)
        for key, value in lying.items():
            longest[key] = max(longest.get(key, 0), value)
        alerts += [(key, now) for key in falls]
    capture.release()
    return {'duration': frame_number / fps, 'longest_lying': longest, 'alerts': alerts}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('video')
    parser.add_argument('--seconds', type=int, default=45, help='tempo deitado para alertar')
    parser.add_argument('--zone', action='append', default=[], help='área ignorada x1,y1,x2,y2 (0 a 1)')
    parser.add_argument('--device', default='cpu', help='cpu ou 0 para a GPU')
    args = parser.parse_args()
    zones = [[float(v) for v in zone.split(',')] for zone in args.zone]
    result = replay(args.video, args.seconds, zones, args.device)
    print(f'Vídeo: {result["duration"]:.0f} s')
    for key, value in sorted(result['longest_lying'].items()):
        print(f'  Pessoa #{key}: deitada fora das áreas ignoradas por até {value:.0f} s')
    if not result['longest_lying']:
        print('  Ninguém ficou deitado fora das áreas ignoradas.')
    for key, when in result['alerts']:
        print(f'  ALERTA: pessoa #{key} aos {when:.0f} s do vídeo')
    if not result['alerts']:
        print(f'  Nenhum alerta seria enviado com {args.seconds} s.')


if __name__ == '__main__':
    main()
