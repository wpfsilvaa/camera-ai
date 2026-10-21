"""Restricted areas (the fridge, a cupboard): in restricted mode video is recorded only while a
watched person is inside one, and an optional alert is raised when such a visit starts.

A person counts as inside when enough of their box covers the area, so an area drawn over the
fridge (ideally with the floor right in front of it) catches someone standing at its door.
"""
FATHER = 'father'  # Fixed id of the father's profile.
OVERLAP = .3       # Share of the person's box inside the area.
GRACE = 2.0        # Seconds a person may leave the area (box jitter) before the stay starts over.
STILL_RADIUS = .35 # How far (in body heights) the center may drift while the person still counts as standing there.
WRISTS = (9, 10)   # COCO keypoints of the hands.
HAND_CONFIDENCE = .3
HAND_MARGIN = .02  # Normalised slack around the area for a hand to count.


def overlap(box, zone, width, height):
    """Fraction of the box that lies inside the normalized zone."""
    x1, y1, x2, y2 = box
    zx1, zy1, zx2, zy2 = zone[0] * width, zone[1] * height, zone[2] * width, zone[3] * height
    inside = max(0, min(x2, zx2) - max(x1, zx1)) * max(0, min(y2, zy2) - max(y1, zy1))
    return inside / max(1, (x2 - x1) * (y2 - y1))


class RestrictedWatch:
    """Remembers who each track was recognized as while it stays visible.

    At the fridge the father usually turns his back to the camera; the face seen on the way
    there keeps identifying the same track after recognition labels expire.
    """

    def __init__(self):
        self.identities = {}  # track id -> person id
        self.watched = set()  # Track ids recognised as a monitored person.
        self.stay = {}        # track id -> {'since', 'last', 'anchor'}: how long the person has stood in an area.
        self.areas = set()    # Indexes of the areas that have a watched person inside (after the last update).

    def reset(self):
        self.identities.clear()
        self.watched.clear()
        self.stay.clear()

    def hands_in(self, points, zone, width, height):
        """True when a wrist the pose model is sure about lies in the area."""
        for index in WRISTS:
            x, y, confidence = points[index]
            if confidence >= HAND_CONFIDENCE and zone[0] - HAND_MARGIN <= x / width <= zone[2] + HAND_MARGIN and zone[1] - HAND_MARGIN <= y / height <= zone[3] + HAND_MARGIN:
                return True
        return False

    def stayed(self, key, box, now, min_seconds, still):
        """Whether the person has been in an area long enough (and, if asked, standing still) to count as using it."""
        x1, y1, x2, y2 = box
        center, height = ((x1 + x2) / 2, (y1 + y2) / 2), max(1.0, y2 - y1)
        state = self.stay.get(key)
        if state is None or now - state['last'] > GRACE:
            state = self.stay[key] = {'since': now, 'last': now, 'anchor': center}
        state['last'] = now
        if still and ((center[0] - state['anchor'][0]) ** 2 + (center[1] - state['anchor'][1]) ** 2) ** .5 > STILL_RADIUS * height:
            state['since'], state['anchor'] = now, center   # Walking through: the count starts over.
        return now - state['since'] >= min_seconds

    def update(self, boxes, ids, labels, frame_size, zones, who, now=None, min_seconds=0, still=False, keypoints=None):
        """Return the track ids of watched people inside a restricted area.

        With `now` and `min_seconds` (and/or `still`) someone just walking past is not counted; with `keypoints`
        (pose model) the hands must be in the area instead of a share of the body.
        """
        visible = {key for key in ids if key is not None}
        for key in self.identities.keys() - visible:
            del self.identities[key]
            self.watched.discard(key)
        for key in visible:
            label = labels.get(str(key), {})
            if label.get('person_id'):
                self.identities[key] = label['person_id']
                if label.get('monitored') or label['person_id'] == FATHER:
                    self.watched.add(key)
        width, height = frame_size
        inside, self.areas = [], set()
        timed = now is not None and (min_seconds > 0 or still)
        touched = set()
        for position, (box, key) in enumerate(zip(boxes, ids)):
            points = keypoints[position] if keypoints is not None and position < len(keypoints) else None
            if points is not None:
                hit = [index for index, zone in enumerate(zones) if self.hands_in(points, zone, width, height)]
            else:
                hit = [index for index, zone in enumerate(zones) if overlap(box, zone, width, height) >= OVERLAP]
            if not hit:
                continue
            touched.add(key)
            if timed and not self.stayed(key, box, now, min_seconds, still):
                continue
            person = self.identities.get(key)
            if who == 'anyone' or key in self.watched or (who == 'father_or_unknown' and person is None):
                inside.append(key)
                self.areas.update(hit)
        for key in list(self.stay):
            if key not in touched and (now is None or now - self.stay[key]['last'] > GRACE):
                del self.stay[key]
        return inside


PHOTO_GAP = 3       # Seconds between two photos at least.
PHOTO_EVERY = 30    # Seconds between photos while nobody new shows up.
MAX_PHOTOS = 8      # Per record.


class PhotoSchedule:
    """When a record without video (restricted mode) keeps a photo of who was there.

    One when the record starts, one whenever someone new appears or is recognized, and one
    every PHOTO_EVERY seconds otherwise, up to MAX_PHOTOS per record.
    """

    def __init__(self):
        self.event_id = None
        self.count, self.last, self.seen = 0, None, set()

    def due(self, event_id, now, people):
        """`people` names who is visible: a name when recognized, otherwise the track id."""
        if event_id != self.event_id:
            self.event_id, self.count, self.last, self.seen = event_id, 0, None, set()
        if not people or self.count >= MAX_PHOTOS:
            return False
        if self.last is not None and (now - self.last < PHOTO_GAP or (people <= self.seen and now - self.last < PHOTO_EVERY)):
            return False
        self.seen |= people
        self.count += 1
        self.last = now
        return True
