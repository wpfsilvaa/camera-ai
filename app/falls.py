"""Possible falls: a person lying outside a bed/sofa zone for longer than the configured time.

Posture comes from YOLO pose keypoints (COCO order). The torso direction, from the middle of
the hips to the middle of the shoulders, is vertical when standing or sitting and close to
horizontal when lying. When the keypoints are not reliable, a wide silhouette is used instead.
"""
import math

SHOULDERS, HIPS = (5, 6), (11, 12)
MIN_KEYPOINT_CONFIDENCE = .4
LYING_ANGLE = 60          # Degrees from vertical.
WIDE_SILHOUETTE = 1.4     # Box width / height without usable keypoints.
GAP_SECONDS = 3           # Brief detection gaps or twitches do not restart the count.


def midpoint(keypoints, indexes):
    points = [keypoints[i] for i in indexes if len(keypoints) > i and keypoints[i][2] >= MIN_KEYPOINT_CONFIDENCE]
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def torso_angle(keypoints):
    """Torso angle from vertical in degrees, or None without visible shoulders and hips."""
    if keypoints is None:
        return None
    shoulders, hips = midpoint(keypoints, SHOULDERS), midpoint(keypoints, HIPS)
    if shoulders is None or hips is None:
        return None
    dx, dy = shoulders[0] - hips[0], shoulders[1] - hips[1]
    if math.hypot(dx, dy) < 8:  # Too small to judge a direction.
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def is_lying(box, keypoints):
    angle = torso_angle(keypoints)
    if angle is not None:
        return angle >= LYING_ANGLE
    x1, y1, x2, y2 = box
    return (x2 - x1) >= WIDE_SILHOUETTE * max(1, y2 - y1)


def body_point(box, keypoints):
    """Where the body rests: the hips when visible, otherwise the box center."""
    hips = midpoint(keypoints, HIPS) if keypoints is not None else None
    if hips:
        return hips
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


def in_zones(point, zones, width, height):
    x, y = point[0] / max(1, width), point[1] / max(1, height)
    return any(z[0] <= x <= z[2] and z[1] <= y <= z[3] for z in zones)


class FallDetector:
    """Tracks how long each person has been lying; reports each episode once."""

    def __init__(self):
        self.tracks = {}  # track id -> {'since', 'last', 'alerted'}

    def reset(self):
        self.tracks.clear()

    def update(self, now, boxes, ids, keypoints, frame_size, zones, seconds):
        """Return ({track id: seconds lying}, [track ids that just reached the limit])."""
        width, height = frame_size
        lying, falls = {}, []
        for box, key, points in zip(boxes, ids, keypoints):
            if not is_lying(box, points) or in_zones(body_point(box, points), zones, width, height):
                continue
            state = self.tracks.get(key)
            if state is None or now - state['last'] > GAP_SECONDS:
                state = self.tracks[key] = {'since': now, 'last': now, 'alerted': False}
            state['last'] = now
            lying[key] = now - state['since']
            if lying[key] >= seconds and not state['alerted']:
                state['alerted'] = True
                falls.append(key)
        for key in [k for k, s in self.tracks.items() if now - s['last'] > GAP_SECONDS]:
            del self.tracks[key]
        return lying, falls
