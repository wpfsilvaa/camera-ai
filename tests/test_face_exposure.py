import unittest

import cv2
import numpy as np

from app.faces import exposure_of, normalize_exposure


def face_like(mean, spread=40, seed=1):
    rng = np.random.default_rng(seed)
    gray = np.clip(rng.normal(mean, spread, (112, 112)), 0, 255).astype(np.uint8)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class ExposureTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(exposure_of(face_like(120))[0], 'ok')
        self.assertEqual(exposure_of(face_like(215, 30))[0], 'blown')
        self.assertEqual(exposure_of(face_like(35, 15))[0], 'dark')
        self.assertEqual(exposure_of(np.full((112, 112, 3), 255, np.uint8))[0], 'lost')

    def test_normalization_moves_mean_towards_the_middle_and_keeps_shape(self):
        for mean in (215, 35):
            crop = face_like(mean, 30 if mean > 150 else 15)
            fixed = normalize_exposure(crop)
            self.assertEqual(fixed.shape, crop.shape)
            self.assertEqual(fixed.dtype, np.uint8)
            before = abs(float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean()) - 125)
            after = abs(float(cv2.cvtColor(fixed, cv2.COLOR_BGR2GRAY).mean()) - 125)
            self.assertLess(after, before / 2)

    def test_blown_face_survives_the_sharpness_gate_after_correction(self):
        crop = face_like(215, 30)
        lap = lambda image: cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        self.assertGreater(lap(normalize_exposure(crop)), lap(crop))   # Mais contraste local: deixa de parecer "borrado".


if __name__ == '__main__':
    unittest.main()
