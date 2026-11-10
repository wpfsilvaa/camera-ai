"""Marked areas on the camera picture, as fractions of its width and height.

A zone is a rectangle `[x1, y1, x2, y2]` or a polygon `[x1, y1, x2, y2, x3, y3, ...]` (3 to 12 corners, so an area can follow the
camera's angle). Rectangles keep their original, cheaper tests; every polygon goes through the general ones.
"""
MAX_POINTS = 12
MIN_AREA = 1e-4   # Share of the picture; smaller than this is a line or a mistake.
SAMPLES = 9       # A box is tested on a SAMPLES x SAMPLES grid to find how much of it lies inside a polygon.


def is_rect(zone):
    return len(zone) == 4


def corners(zone):
    """The corners as (x, y) pairs; a rectangle gives its four."""
    if is_rect(zone):
        x1, y1, x2, y2 = zone
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return list(zip(zone[0::2], zone[1::2]))


def area(zone):
    points = corners(zone)
    return abs(sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]))) / 2


def valid(zone):
    """True for a well-formed zone inside the picture that is not degenerate."""
    if not isinstance(zone, (list, tuple)) or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in zone):
        return False
    if is_rect(zone):
        return zone[0] < zone[2] and zone[1] < zone[3]
    return len(zone) % 2 == 0 and 6 <= len(zone) <= MAX_POINTS * 2 and area(zone) >= MIN_AREA


def contains(zone, x, y):
    """Whether the point lies in the zone (a rectangle's edges count; a polygon's are not guaranteed to)."""
    if is_rect(zone):
        return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]
    inside = False
    points = corners(zone)
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def distance(zone, x, y):
    """How far the point is from the zone's outline (0 on it)."""
    points = corners(zone)
    best = float('inf')
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0 if not length else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length))
        best = min(best, ((x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2) ** .5)
    return best


def near(zone, x, y, margin):
    """Inside the zone or within `margin` of it."""
    if is_rect(zone):
        return zone[0] - margin <= x <= zone[2] + margin and zone[1] - margin <= y <= zone[3] + margin
    return contains(zone, x, y) or distance(zone, x, y) <= margin


def share_inside(zone, box, width, height):
    """Fraction of the pixel box that lies inside the zone."""
    x1, y1, x2, y2 = box
    if is_rect(zone):
        zx1, zy1, zx2, zy2 = zone[0] * width, zone[1] * height, zone[2] * width, zone[3] * height
        inside = max(0, min(x2, zx2) - max(x1, zx1)) * max(0, min(y2, zy2) - max(y1, zy1))
        return inside / max(1, (x2 - x1) * (y2 - y1))
    hits = sum(contains(zone, (x1 + (x2 - x1) * (i + .5) / SAMPLES) / width, (y1 + (y2 - y1) * (j + .5) / SAMPLES) / height)
               for i in range(SAMPLES) for j in range(SAMPLES))
    return hits / SAMPLES ** 2
