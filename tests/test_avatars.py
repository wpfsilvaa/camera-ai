import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.avatars import SIDE, Avatars


def picture(width, height):
    ok, data = cv2.imencode('.jpg', np.full((height, width, 3), (30, 140, 200), np.uint8))
    return data.tobytes()


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.avatars = Avatars(Path(self.tmp.name))
        self.user = 'c' * 32

    def tearDown(self):
        self.tmp.cleanup()

    def test_any_picture_becomes_a_small_square(self):
        self.avatars.save(self.user, picture(800, 300))
        image = cv2.imread(str(self.avatars.path(self.user)))
        self.assertEqual(image.shape[:2], (SIDE, SIDE))
        self.assertTrue(self.avatars.has(self.user))
        self.assertTrue(self.avatars.rev(self.user))
        self.avatars.delete(self.user)
        self.assertFalse(self.avatars.has(self.user))

    def test_rejects_invalid_files_and_ids(self):
        with self.assertRaises(Exception):
            self.avatars.save(self.user, b'not a picture')
        with self.assertRaises(KeyError):
            self.avatars.path('../etc/passwd')
        self.assertFalse(self.avatars.has('../x'))


if __name__ == '__main__':
    unittest.main()
