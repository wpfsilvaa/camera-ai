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
        worker.restricted, worker.camera_id, worker.last_reminder = RestrictedWatch(), 'main', 0.0
        worker.on_restricted, self.heard = None, []
        worker.on_reminder = lambda camera, text: self.heard.append((camera, text))
        return worker, np.zeros((1000, 1000, 3), np.uint8)

    def settings(self, **changes):
        return CameraSettings(restricted_enabled=True, restricted_zones=FRIDGE, restricted_who='anyone', restricted_reminder=True, **changes)

    def test_only_the_recognised_father_is_reminded(self):
        worker, frame = self.worker()
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [7], {'7': SON}, frame, 1000, self.settings())
        self.assertEqual(self.heard, [])
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1001, self.settings(restricted_reminder_text='Cuidado com o açúcar'))
        self.assertEqual(self.heard, [('main', 'Cuidado com o açúcar')])

    def test_one_reminder_a_minute_and_only_when_enabled(self):
        worker, frame = self.worker()
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1000, self.settings())
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1030, self.settings())
        self.assertEqual(len(self.heard), 1)
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 1061, self.settings())
        self.assertEqual(len(self.heard), 2)
        off = CameraSettings(restricted_enabled=True, restricted_zones=FRIDGE, restricted_who='anyone')
        worker.check_restricted(self.Zone(), [AT_FRIDGE], [8], {'8': FATHER}, frame, 2000, off)
        self.assertEqual(len(self.heard), 2)
