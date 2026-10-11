"""Restricted areas (the fridge, a cupboard): in restricted mode video is recorded only while a
watched person is inside one, and an optional alert is raised when such a visit starts.

A person counts as inside when enough of their box covers the area, so an area drawn over the
fridge (ideally with the floor right in front of it) catches someone standing at its door.
"""
FATHER = 'father'  # Fixed id of the father's profile.
OVERLAP = .3       # Share of the person's box inside the area.


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
        self.areas = set()    # Indexes of the areas that have a watched person inside (after the last update).

    def reset(self):
        self.identities.clear()

    def update(self, boxes, ids, labels, frame_size, zones, who):
        """Return the track ids of watched people inside a restricted area."""
        visible = {key for key in ids if key is not None}
        for key in self.identities.keys() - visible:
            del self.identities[key]
        for key in visible:
            person = labels.get(str(key), {}).get('person_id')
            if person:
                self.identities[key] = person
        width, height = frame_size
        inside, self.areas = [], set()
        for box, key in zip(boxes, ids):
            hit = [index for index, zone in enumerate(zones) if overlap(box, zone, width, height) >= OVERLAP]
            if not hit:
                continue
            person = self.identities.get(key)
            if who == 'anyone' or person == FATHER or (who == 'father_or_unknown' and person is None):
                inside.append(key)
                self.areas.update(hit)
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
