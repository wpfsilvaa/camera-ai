import os
import sys
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['MONITOR_PHOTOS_DIR'] = str(Path(TEMP.name) / 'screen-photos')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'notebook'))
import monitor


class PresentNamesTests(unittest.TestCase):
    def test_names_are_cleaned_deduplicated_and_limited(self):
        self.assertEqual(monitor.parse_present('Flavio;Lorena;Flavio'), ['Flavio', 'Lorena'])
        self.assertEqual(monitor.parse_present(' ; \x00;A;B;C;D;E'), ['A', 'B', 'C', 'D'])
        self.assertEqual(monitor.parse_present('x' * 80), ['x' * 30])
        self.assertEqual(monitor.parse_present(None), [])

    def test_the_screen_gets_the_names_only_while_the_link_is_fresh(self):
        desk = monitor.Desk()
        desk.configure(False, False, 'resting')
        desk.present = monitor.parse_present('Flavio')
        self.assertEqual(desk.display()['present'], ['Flavio'])
        desk.vigia = None   # The dashboard stopped talking: nothing stale is shown.
        self.assertEqual(desk.display()['present'], [])


if __name__ == '__main__':
    unittest.main()
