import unittest

from pydantic import ValidationError

from app.config import CameraSettings
from app.presence import Presence
from app.restricted import MAX_PHOTOS, PhotoSchedule, RestrictedWatch, overlap

FRAME = (1000, 1000)
FRIDGE = [[.6, .2, .9, .9]]
AT_FRIDGE = (650, 300, 850, 900)
ACROSS_ROOM = (100, 300, 300, 950)
FATHER = {'person_id': 'father', 'name': 'Meu pai'}
SON = {'person_id': 'p1', 'name': 'Filho'}


class RestrictedTests(unittest.TestCase):
    def test_overlap_is_the_share_of_the_person_inside(self):
        self.assertAlmostEqual(overlap(AT_FRIDGE, FRIDGE[0], *FRAME), 1)
        self.assertEqual(overlap(ACROSS_ROOM, FRIDGE[0], *FRAME), 0)
        self.assertAlmostEqual(overlap((500, 300, 700, 900), FRIDGE[0], *FRAME), .5)

    def test_father_stays_identified_with_his_back_to_the_camera(self):
        watch = RestrictedWatch()
        # Recognized by the face across the room, then the label expires at the fridge.
        self.assertEqual(watch.update([ACROSS_ROOM], [7], {'7': FATHER}, FRAME, FRIDGE, 'father'), [])
        self.assertEqual(watch.update([AT_FRIDGE], [7], {}, FRAME, FRIDGE, 'father'), [7])

    def test_a_lost_track_must_be_recognized_again(self):
        watch = RestrictedWatch()
        watch.update([ACROSS_ROOM], [7], {'7': FATHER}, FRAME, FRIDGE, 'father')
        watch.update([], [], {}, FRAME, FRIDGE, 'father')
        self.assertEqual(watch.update([AT_FRIDGE], [7], {}, FRAME, FRIDGE, 'father'), [])

    def test_who_activates_the_area(self):
        boxes, ids, labels = [AT_FRIDGE, AT_FRIDGE, AT_FRIDGE], [1, 2, 3], {'1': FATHER, '2': SON}
        self.assertEqual(RestrictedWatch().update(boxes, ids, labels, FRAME, FRIDGE, 'father'), [1])
        self.assertEqual(RestrictedWatch().update(boxes, ids, labels, FRAME, FRIDGE, 'father_or_unknown'), [1, 3])
        self.assertEqual(RestrictedWatch().update(boxes, ids, labels, FRAME, FRIDGE, 'anyone'), [1, 2, 3])

    def test_no_area_means_no_recording(self):
        self.assertEqual(RestrictedWatch().update([AT_FRIDGE], [1], {'1': FATHER}, FRAME, [], 'anyone'), [])

    def test_visit_starts_once_and_ends_after_absence(self):
        watch, zone, actions = RestrictedWatch(), Presence(1, 8), []
        for step in range(100):  # 20 s at 5 detections per second.
            now = step / 5
            box = AT_FRIDGE if now < 5 else ACROSS_ROOM
            actions.append((zone.update(now, len(watch.update([box], [1], {'1': FATHER}, FRAME, FRIDGE, 'father'))), now))
        self.assertEqual([a for a in actions if a[0]], [('start', 1.0), ('end', 12.8)])

    def test_photos_start_with_the_record_and_follow_new_faces(self):
        photos, taken = PhotoSchedule(), []
        for step in range(400):  # 80 s at 5 detections per second.
            now = step / 5
            people = {'?'} if now < 10 else {'?', 'Meu pai'} if now < 11 else {'Meu pai'}
            if photos.due(1, now, people):
                taken.append(now)
        # Start; the father recognized; then one every 30 s while nobody new appears.
        self.assertEqual(taken, [0, 10, 40, 70])

    def test_photos_are_capped_and_restart_with_the_next_record(self):
        photos = PhotoSchedule()
        taken = sum(photos.due(1, step * 3, {f'Pessoa {step}'}) for step in range(20))
        self.assertEqual(taken, MAX_PHOTOS)
        self.assertFalse(photos.due(1, 100, set()))
        self.assertTrue(photos.due(2, 100, {'?'}))

    def test_settings_validation(self):
        self.assertEqual(CameraSettings(restricted_zones=[[.1, .2, .3, .4]]).restricted_zones, [[.1, .2, .3, .4]])
        with self.assertRaises(ValidationError):
            CameraSettings(restricted_zones=[[.5, .2, .3, .4]])
        with self.assertRaises(ValidationError):
            CameraSettings(restricted_who='vizinho')


class PassingByTests(unittest.TestCase):
    """Walking past the fridge is not a visit: the person must stay a few seconds, standing still, with a hand there if asked."""

    def watch(self, boxes_by_time, **options):
        watch, results = RestrictedWatch(), []
        for now, box in boxes_by_time:
            results.append(watch.update([box], [7], {'7': FATHER}, FRAME, FRIDGE, 'father', now, **options))
        return results

    def test_must_stay_the_minimum_time(self):
        results = self.watch([(0, AT_FRIDGE), (1, AT_FRIDGE), (2.5, AT_FRIDGE), (3.2, AT_FRIDGE)], min_seconds=3)
        self.assertEqual(results, [[], [], [], [7]])

    def test_crossing_the_room_never_counts(self):
        x = 600
        walking = []
        for step in range(8):
            walking.append((step * .5, (x + step * 60, AT_FRIDGE[1], x + step * 60 + 200, AT_FRIDGE[3])))
        # Only the first positions touch the area, and the person keeps moving along it.
        results = self.watch(walking, min_seconds=2, still=True)
        self.assertTrue(all(result == [] for result in results))

    def test_leaving_resets_the_clock(self):
        results = self.watch([(0, AT_FRIDGE), (2, AT_FRIDGE), (4, ACROSS_ROOM), (6, AT_FRIDGE), (7, AT_FRIDGE)], min_seconds=3)
        self.assertEqual(results[-1], [])

    def test_without_the_new_options_nothing_changes(self):
        self.assertEqual(self.watch([(0, AT_FRIDGE)]), [[7]])

    def test_hands_decide_when_the_pose_is_known(self):
        import numpy as np
        watch = RestrictedWatch()
        hands_away = np.zeros((17, 3), np.float32)           # No hand sure enough.
        hands_in = hands_away.copy()
        hands_in[9] = (750, 500, .9)                           # A wrist inside the fridge area.
        shown = lambda points: watch.update([AT_FRIDGE], [7], {'7': FATHER}, FRAME, FRIDGE, 'father', 0, 0, False, [points])
        self.assertEqual(shown(hands_away), [])
        self.assertEqual(shown(hands_in), [7])
        self.assertEqual(watch.update([AT_FRIDGE], [7], {'7': FATHER}, FRAME, FRIDGE, 'father', 0, 0, False, [None]), [7])   # No pose: the body rule.


class FloorStripTests(unittest.TestCase):
    STRIP = [[.55, .8, .95, 1.0]]   # The floor right in front of the fridge.

    def test_feet_must_be_on_the_strip(self):
        in_front = (650, 300, 850, 950)        # Feet at y=950: on the strip.
        far_behind = (650, 100, 850, 600)      # Overlaps the fridge in the picture, but the feet are far up the room.
        update = lambda box: RestrictedWatch().update([box], [7], {'7': FATHER}, FRAME, FRIDGE, 'father', floor=self.STRIP)
        self.assertEqual(update(in_front), [7])
        self.assertEqual(update(far_behind), [])
        self.assertEqual(RestrictedWatch().update([far_behind], [7], {'7': FATHER}, FRAME, FRIDGE, 'father'), [7])   # Without strips: as before.


class VisitMeasureTests(unittest.TestCase):
    def test_new_visit_gets_a_snapshot_and_its_length_is_updated(self):
        import numpy as np
        from app.camera import CameraWorker
        worker = CameraWorker.__new__(CameraWorker)
        worker.restricted, worker.camera_id, worker.area_seen = RestrictedWatch(), 'main', {}
        made, lengths = [], []
        worker.on_visit = lambda camera, now, area, person, kind, snapshot: (made.append(snapshot() if snapshot else None), 42)[1]
        worker.on_visit_time = lambda visit, seconds: lengths.append((visit, round(seconds)))
        settings = CameraSettings(restricted_enabled=True, restricted_zones=FRIDGE, restricted_who='anyone')
        for now in (1000, 1001, 1003, 1006):
            worker.restricted.update([AT_FRIDGE], [7], {'7': FATHER}, FRAME, FRIDGE, 'anyone')
            worker.log_visits(now, settings, 'Meu pai', 'father', lambda: b'jpeg')
        self.assertEqual(made, [b'jpeg'])   # One visit, one picture.
        self.assertEqual(lengths, [(42, 3), (42, 6)])


class MonitoredTests(unittest.TestCase):
    def test_any_monitored_person_counts_as_watched(self):
        boxes, ids = [AT_FRIDGE, AT_FRIDGE], [1, 2]
        labels = {'1': {'person_id': 'mae', 'name': 'Minha mãe', 'monitored': True}, '2': SON}
        self.assertEqual(RestrictedWatch().update(boxes, ids, labels, FRAME, FRIDGE, 'father'), [1])


if __name__ == '__main__':
    unittest.main()


class ReminderTests(unittest.TestCase):
    """The father going into the restricted area makes the kitchen screen remind him (at most once a minute)."""

    class Zone:
        def __init__(self):
            self.state = 'start'

        def update(self, now, count):
            return self.state if count else None

    def worker(self):
        import numpy as np
        from app.camera import CameraWorker
        worker = CameraWorker.__new__(CameraWorker)
        worker.restricted, worker.camera_id, worker.last_reminder, worker.area_seen = RestrictedWatch(), 'main', 0.0, {}
        worker.on_visit = None
        worker.on_restricted, self.heard = None, []
        worker.on_reminder = lambda camera, text: self.heard.append((camera, text))
        return worker, np.zeros((1000, 1000, 3), np.uint8)

    def settings(self, **changes):
        return CameraSettings(restricted_enabled=True, restricted_zones=FRIDGE, restricted_who='anyone', restricted_reminder=True, restricted_min_seconds=0, restricted_still=False, **changes)

    def test_only_the_recognised_father_is_reminded(self):
        worker, frame = self.worker()
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [7], {'7': SON}, frame, 1000, self.settings())
        self.assertEqual(self.heard, [])
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1001, self.settings(restricted_reminder_text='Cuidado com o açúcar'))
        self.assertEqual(self.heard, [('main', 'Cuidado com o açúcar')])

    def test_family_in_view_silences_the_reminder_and_the_alert(self):
        worker, frame = self.worker()
        worker.on_restricted = lambda *args: self.heard.append(('alert',))
        both = {'8': FATHER, '9': SON}
        worker.check_restricted(self.Zone(), [AT_FRIDGE, ACROSS_ROOM], [8, 9], both, frame, 1000, self.settings(restricted_alert=True))
        self.assertEqual(self.heard, [])
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1100, self.settings(restricted_alert=True))   # Family left.
        self.assertEqual(len(self.heard), 2)
        worker.check_restricted(self.Zone(), [AT_FRIDGE, ACROSS_ROOM], [8, 9], both, frame, 1300, self.settings(restricted_alert=True, restricted_pause_with_family=False))
        self.assertEqual(len(self.heard), 4)

    def test_one_reminder_a_minute_and_only_when_enabled(self):
        worker, frame = self.worker()
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1000, self.settings())
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1030, self.settings())
        self.assertEqual(len(self.heard), 1)
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1061, self.settings())
        self.assertEqual(len(self.heard), 2)
        off = CameraSettings(restricted_enabled=True, restricted_zones=FRIDGE, restricted_who='anyone', restricted_min_seconds=0, restricted_still=False)
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 2000, off)
        self.assertEqual(len(self.heard), 2)


class AreaVisitTests(unittest.TestCase):
    """Each named area counts its own visits (fridge and cupboard), a new one after it was empty for a few seconds."""

    def test_visits_are_logged_per_named_area(self):
        import numpy as np
        from app.camera import CameraWorker, AREA_GAP
        zones = [[.6, .2, .9, .9], [.0, .2, .3, .9]]
        settings = CameraSettings(restricted_enabled=True, restricted_zones=zones, restricted_zone_names=['Geladeira', ''], restricted_who='anyone')
        worker = CameraWorker.__new__(CameraWorker)
        worker.restricted, worker.camera_id, worker.area_seen, seen = RestrictedWatch(), 'main', {}, []
        worker.on_visit = lambda camera, now, area, person, kind='', snapshot=None: seen.append((now, area, person))
        fridge, cupboard = AT_FRIDGE, (50, 300, 250, 900)
        for now, box in ((1000, fridge), (1002, fridge), (1004, cupboard), (1006, cupboard), (1030, fridge)):
            worker.restricted.update([box], [7], {'7': FATHER}, FRAME, zones, 'anyone')
            worker.log_visits(now, settings, 'Meu pai')
        self.assertEqual([(a, p) for _, a, p in seen], [('Geladeira', 'Meu pai'), ('Área 2', 'Meu pai'), ('Geladeira', 'Meu pai')])
        self.assertEqual([n for n, _, _ in seen], [1000, 1004, 1030])
