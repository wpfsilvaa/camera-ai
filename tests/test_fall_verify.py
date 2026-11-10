import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.camera import CameraWorker
from app.fall_verify import FallVerifier, crop_person, parse_answer
from app.falls import FallDetector

from test_falls import FRAME, LYING


def fake_install(answer):
    """A folder that looks like llama.cpp + the model, where the "CLI" is a script printing a fixed answer."""
    folder = Path(tempfile.mkdtemp())
    cli = folder / 'llama-mtmd-cli'
    cli.write_text(f'#!/bin/sh\necho "{answer}"\n')
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    (folder / 'LFM2.5-VL-450M-Q4_K_M.gguf').write_bytes(b'x')
    (folder / 'mmproj-LFM2.5-VL-450m-Q8_0.gguf').write_bytes(b'x')
    return folder


class ParseTests(unittest.TestCase):
    def test_only_a_clear_answer_counts(self):
        self.assertIs(parse_answer('Sim'), True)
        self.assertIs(parse_answer('Não.'), False)
        self.assertIs(parse_answer('nao'), False)
        for doubt in ('', 'Talvez', 'Há um homem', None):
            self.assertIsNone(parse_answer(doubt))


class CropTests(unittest.TestCase):
    def test_crop_and_tiny_box(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        self.assertTrue(crop_person(frame, (100, 100, 400, 500)).startswith(b'\xff\xd8'))
        self.assertIsNone(crop_person(frame, (100, 100, 130, 130)))


class VerifierTests(unittest.TestCase):
    def test_missing_install_means_unavailable_and_unsure(self):
        for directory in ('', '/nao/existe'):
            verifier = FallVerifier(directory)
            self.assertFalse(verifier.available())
            self.assertIsNone(verifier.has_person(b'jpeg'))

    def test_runs_the_cli_and_reads_the_answer(self):
        self.assertIs(FallVerifier(str(fake_install('Não'))).has_person(b'jpeg'), False)
        self.assertIs(FallVerifier(str(fake_install('Sim'))).has_person(b'jpeg'), True)
        self.assertIsNone(FallVerifier(str(fake_install('Talvez'))).has_person(b'jpeg'))


class WorkerTests(unittest.TestCase):
    def worker(self, answers):
        sent = []
        verifier = SimpleNamespace(has_person=lambda crop: next(answers))
        return SimpleNamespace(fall_verifier=verifier, fall_rearm=[], camera_id='sala',
                               report_fall=lambda *args: sent.append(args)), sent

    def verify(self, answers, crops):
        worker, sent = self.worker(iter(answers))
        CameraWorker.verify_fall(worker, [1] * len(crops), crops, 'Sala', b'jpeg', 50)
        return worker, sent

    def test_only_a_clear_no_drops_the_alert(self):
        worker, sent = self.verify([False], [b'a'])
        self.assertEqual(sent, [])
        self.assertEqual(worker.fall_rearm, [[1]])

    def test_yes_unsure_or_missing_crop_still_alerts(self):
        for answers, crops in (([True], [b'a']), ([None], [b'a']), ([False, True], [b'a', b'b']), ([], [None])):
            _, sent = self.verify(answers, crops)
            self.assertEqual(len(sent), 1, (answers, crops))


class RearmTests(unittest.TestCase):
    def test_a_dismissed_track_counts_a_new_period_before_alerting_again(self):
        detector, events = FallDetector(), []
        box = [(40, 380, 260, 440)]
        for step in range(0, 400):          # 80 s at 5 fps, limit 30 s
            now = step / 5
            if step == 160:                 # the model dismissed the first alert (at ~30 s)
                detector.rearm([1], now)
            _, falls = detector.update(now, box, [1], [LYING], FRAME, [], 30)
            events += [now for _ in falls]
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[1] - 32, 30, delta=1)


if __name__ == '__main__':
    unittest.main()
