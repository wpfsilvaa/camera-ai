import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['MONITOR_PHOTOS_DIR'] = str(Path(TEMP.name) / 'screen-photos')

from app import kiosk_widgets
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'notebook'))
import monitor


class KioskWidgetsTests(unittest.TestCase):
    def test_the_order_is_complete_deduplicated_and_ignores_unknown_names(self):
        self.assertEqual(kiosk_widgets.normalize('quote,calendar,xx,-clock,quote'), 'quote,calendar,-clock,-photo,-medication')
        self.assertEqual(kiosk_widgets.normalize(''), 'calendar,clock,quote,photo,medication'.replace('calendar', '-calendar').replace('clock', '-clock').replace('quote', '-quote').replace('photo', '-photo').replace('medication', '-medication'))
        self.assertEqual(Settings().kiosk_widgets, kiosk_widgets.DEFAULT_ORDER)

    def test_the_calendar_also_follows_its_own_switch(self):
        s = Settings(kiosk_widgets='clock,calendar,quote,-photo,-medication', kiosk_calendar_enabled=False)
        self.assertEqual(kiosk_widgets.effective(s)['order'], ['clock', 'quote'])
        self.assertEqual(kiosk_widgets.effective(Settings(kiosk_widgets='clock,calendar'))['order'], ['clock', 'calendar'])
        # A "-" in front of the calendar changes nothing: only its own switch turns it on or off.
        self.assertEqual(kiosk_widgets.effective(Settings(kiosk_widgets='clock,-calendar', kiosk_calendar_enabled=True))['order'], ['clock', 'calendar'])

    def test_standard_phrases_when_none_written_and_only_valid_medicine_lines(self):
        s = Settings(kiosk_quotes=['  Oi, tudo bem?  ', ''], kiosk_medications=['08:00 Losartana 50 mg', '25:00 Errado', 'sem hora', '9:05 Vitamina'])
        data = kiosk_widgets.effective(s)
        self.assertEqual(data['quotes'], ['Oi, tudo bem?'])
        self.assertEqual(data['meds'], ['08:00 Losartana 50 mg', '9:05 Vitamina'])
        self.assertGreaterEqual(len(kiosk_widgets.effective(Settings())['quotes']), 20)
        self.assertEqual(kiosk_widgets.effective(Settings())['meds'], [])

    def test_the_screen_keeps_only_known_tiles_and_short_printable_texts(self):
        cfg = monitor.parse_cfg(json.dumps({'widgets': {'order': ['clock', 'evil', 'clock', 'quote'], 'quotes': ['ok\x00', 7, 'x' * 400], 'meds': ['08:00 A'] * 30}}))
        self.assertEqual(cfg['widgets']['order'], ['clock', 'quote'])
        self.assertEqual(cfg['widgets']['quotes'][0], 'ok')
        self.assertEqual(len(cfg['widgets']['quotes'][1]), 160)
        self.assertEqual(len(cfg['widgets']['meds']), 20)
        self.assertNotIn('widgets', monitor.parse_cfg('{"widgets": "x"}'))


if __name__ == '__main__':
    unittest.main()
