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

from app import kiosk_theme
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'notebook'))
import monitor


class KioskThemeTests(unittest.TestCase):
    def test_a_palette_wins_over_the_custom_fields_until_personalizada_is_chosen(self):
        custom = {'kiosk_color_bg': '#112233', 'kiosk_color_ink': '#ffeedd', 'kiosk_color_call': '#223344', 'kiosk_color_panic': '#334455', 'kiosk_color_accent': '#445566'}
        ready = kiosk_theme.effective(Settings(kiosk_palette='verde', **custom))
        self.assertEqual(ready['colors'], kiosk_theme.PALETTES['verde'][1])
        mine = kiosk_theme.effective(Settings(kiosk_palette='personalizada', kiosk_text_size='grande', kiosk_show_weather=False, **custom))
        self.assertEqual(mine['colors'], {'bg': '#112233', 'ink': '#ffeedd', 'call': '#223344', 'panic': '#334455', 'accent': '#445566'})
        self.assertEqual((mine['size'], mine['show']['weather'], mine['show']['date']), ('grande', False, True))

    def test_only_valid_colours_and_choices_are_accepted(self):
        for bad in ('red', '#12345', '#gggggg', 'url(x)'):
            with self.assertRaises(ValueError):
                Settings(kiosk_color_bg=bad)
        with self.assertRaises(ValueError):
            Settings(kiosk_palette='neon')
        with self.assertRaises(ValueError):
            Settings(kiosk_text_size='gigante')

    def test_the_panel_lists_exactly_the_palettes_and_colours_of_the_server(self):
        page = (ROOT / 'static/index.html').read_text()
        found = dict(re.findall(r'<option value="(\w+)" data-colors="([^"]*)"', page))
        self.assertEqual(set(found), set(kiosk_theme.PALETTES))
        for key, (_, colors) in kiosk_theme.PALETTES.items():
            self.assertEqual(json.loads(html.unescape(found[key])), colors, key)
        for name in kiosk_theme.SHOW:
            self.assertIn(f'name="kiosk_show_{name}"', page)

    def test_the_screen_keeps_only_safe_theme_values(self):
        ok = {'colors': {'bg': '#0d1519', 'ink': '#f0f6f8', 'call': '#0f6b82', 'panic': '#d6453a', 'accent': '#e6b45e'}, 'size': 'grande', 'show': {'weather': False, 'date': True, 'evil': False}}
        cfg = monitor.parse_cfg(json.dumps({'theme': ok}))
        self.assertEqual(cfg['theme']['colors'], ok['colors'])
        self.assertEqual((cfg['theme']['size'], cfg['theme']['show']), ('grande', {'weather': False, 'date': True}))
        injected = {**ok, 'colors': {**ok['colors'], 'bg': 'red;} body{display:none'}, 'size': 'enorme'}
        cfg = monitor.parse_cfg(json.dumps({'theme': injected}))
        self.assertNotIn('colors', cfg['theme'])   # A broken set is dropped whole: nothing reaches the style sheet.
        self.assertNotIn('size', cfg['theme'])
        self.assertNotIn('theme', monitor.parse_cfg('{"theme": "x"}'))


if __name__ == '__main__':
    unittest.main()
