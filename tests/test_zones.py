import unittest

import numpy as np

from app import zones
from app.config import CameraSettings
from app.falls import in_zones
from app.overlay import draw_zones
from app.restricted import RestrictedWatch, overlap

RECT = [.2, .2, .6, .8]
# A fridge seen at an angle: the top edge is narrower than the bottom one.
SLANT = [.40, .20, .60, .20, .70, .90, .30, .90]
FRAME = (1000, 1000)


class ZoneGeometryTests(unittest.TestCase):
    def test_rectangle_and_polygon_forms_are_told_apart(self):
        self.assertTrue(zones.is_rect(RECT))
        self.assertFalse(zones.is_rect(SLANT))
        self.assertEqual(zones.corners(RECT), [(.2, .2), (.6, .2), (.6, .8), (.2, .8)])
        self.assertEqual(len(zones.corners(SLANT)), 4)

    def test_point_inside_follows_the_slanted_edges(self):
        self.assertTrue(zones.contains(SLANT, .5, .5))
        self.assertTrue(zones.contains(SLANT, .35, .85))    # Wide at the bottom...
        self.assertFalse(zones.contains(SLANT, .35, .25))   # ...but not up at the narrow top.
        self.assertFalse(zones.contains(SLANT, .9, .5))
        self.assertTrue(zones.contains(RECT, .6, .8))       # Rectangle edges count, as before.

    def test_concave_polygon(self):
        arrow = [.1, .1, .9, .1, .9, .9, .5, .5, .1, .9]   # A notch cut into the bottom.
        self.assertTrue(zones.contains(arrow, .2, .5))
        self.assertFalse(zones.contains(arrow, .5, .8))

    def test_share_of_a_box_inside(self):
        self.assertAlmostEqual(overlap((200, 200, 600, 800), RECT, *FRAME), 1.0)
        self.assertAlmostEqual(overlap((600, 200, 1000, 800), RECT, *FRAME), 0.0)
        self.assertEqual(overlap((0, 0, 100, 100), SLANT, *FRAME), 0)
        self.assertGreater(overlap((350, 300, 650, 800), SLANT, *FRAME), .8)
        left_half = overlap((200, 200, 600, 800), SLANT, *FRAME)   # Only the right part of this box reaches the slanted area.
        self.assertTrue(.2 < left_half < .8)

    def test_hand_margin_around_a_polygon(self):
        self.assertTrue(zones.near(SLANT, .5, .5, .02))
        self.assertTrue(zones.near(SLANT, .39, .5, .03))
        self.assertFalse(zones.near(SLANT, .2, .5, .03))
        self.assertTrue(zones.near(RECT, .61, .5, .02))

    def test_validation(self):
        self.assertTrue(zones.valid(RECT) and zones.valid(SLANT))
        self.assertFalse(zones.valid([.5, .5, .5, .9]))                      # No width.
        self.assertFalse(zones.valid([.1, .1, .2, .2, .3, .3]))              # Collinear: no area.
        self.assertFalse(zones.valid([.1, .1, .2, .2, .3, .3, .4]))          # Odd length.
        self.assertFalse(zones.valid([.1, .1, .5, .1, 1.2, .9]))             # Outside the picture.
        self.assertFalse(zones.valid(list(np.linspace(.1, .9, 26))))         # Too many corners.

    def test_settings_accept_polygons_and_keep_rectangles(self):
        saved = CameraSettings(restricted_zones=[RECT, SLANT], restricted_floor=[SLANT], fall_zones=[SLANT])
        self.assertEqual(saved.restricted_zones, [RECT, SLANT])
        with self.assertRaises(ValueError):
            CameraSettings(restricted_zones=[[.1, .1, .2, .2, .3, .3]])


class PolygonUseTests(unittest.TestCase):
    def test_restricted_watch_uses_a_slanted_area_and_floor(self):
        watch = RestrictedWatch()
        inside, outside = (350, 300, 650, 880), (700, 300, 950, 880)
        self.assertEqual(watch.update([inside, outside], [1, 2], {}, FRAME, [SLANT], 'anyone'), [1])
        self.assertTrue(RestrictedWatch.feet_on(inside, [SLANT], *FRAME))      # Feet at (.5, .88).
        self.assertFalse(RestrictedWatch.feet_on(outside, [SLANT], *FRAME))

    def test_fall_zone_polygon(self):
        self.assertTrue(in_zones((500, 500), [SLANT], 1000, 1000))
        self.assertFalse(in_zones((900, 500), [SLANT], 1000, 1000))

    def test_preview_draws_polygons_and_rectangles(self):
        frame = np.zeros((100, 100, 3), np.uint8)
        shaded = draw_zones(frame, [SLANT], (0, 0, 200))
        self.assertGreater(shaded[50, 50, 2], 0)    # Inside.
        self.assertEqual(int(shaded[50, 5, 2]), 0)  # Outside.
        self.assertGreater(draw_zones(frame, [RECT])[50, 40].sum(), 0)


if __name__ == '__main__':
    unittest.main()
