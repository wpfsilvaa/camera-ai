import html
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['MONITOR_PHOTOS_DIR'] = str(Path(TEMP.name) / 'screen-photos')

from app import kiosk_texts
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'notebook'))
import monitor


class KioskTextsTests(unittest.TestCase):
    def test_empty_fields_use_the_standard_wording_and_written_ones_win(self):
        settings = Settings(kiosk_text_greet_morning='  Olá {nome}, hoje é {data} e são {hora}  ')
        texts = kiosk_texts.effective(settings)
        self.assertEqual(texts['greet_morning'], 'Olá {nome}, hoje é {data} e são {hora}')
        self.assertEqual(texts['greet_night'], kiosk_texts.DEFAULTS['greet_night'])
        self.assertIn('|', kiosk_texts.DEFAULTS['greet_night'])   # Standard greetings come in variations.
        self.assertEqual(set(texts), set(kiosk_texts.KEYS))
        with self.assertRaises(ValueError):
            Settings(kiosk_text_greet_morning='x' * 241)

    def test_every_text_has_a_settings_field_and_the_panel_shows_the_same_standard_wording(self):
        page = (ROOT / 'static/index.html').read_text()
        for key, _, _, default in kiosk_texts.TEXTS:
            self.assertIn(f'kiosk_text_{key}', Settings.model_fields, key)
            self.assertIn(f'name="kiosk_text_{key}"', page)
            self.assertIn(f'data-default="{html.escape(default, quote=True)}"', page, f'{key}: o texto padrão do painel mudou sem atualizar o HTML')

    def test_the_screen_accepts_only_short_printable_texts_under_plain_names(self):
        cfg = monitor.parse_cfg(json.dumps({'texts': {'greet_morning': 'Oi {nome}\x00', 'Bad Key': 'x', 'daily_day': '   ', 'tip_rain': 7, 'x' * 40: 'y', 'tip_hot': 'a' * 500}, 'tips': False}))
        self.assertEqual(cfg['texts']['greet_morning'], 'Oi {nome}')
        self.assertEqual(set(cfg['texts']), {'greet_morning', 'tip_hot'})
        self.assertEqual(len(cfg['texts']['tip_hot']), 240)
        self.assertIs(cfg['tips'], False)
        self.assertNotIn('texts', monitor.parse_cfg('{"texts": "oops"}'))


if __name__ == '__main__':
    unittest.main()
