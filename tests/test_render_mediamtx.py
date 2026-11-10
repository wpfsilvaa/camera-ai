import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('render_mediamtx', Path(__file__).resolve().parents[1] / 'scripts' / 'render_mediamtx.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RenderMediaMtx(unittest.TestCase):
    def test_software(self):
        text = mod.render(['192.168.0.10'], '/dev/video0')
        self.assertIn('ips: [127.0.0.1, "::1", 192.168.0.10]', text)
        self.assertIn('libx264', text)
        self.assertNotIn('vaapi', text)
        self.assertNotIn('192.168.1.1', text)
        self.assertNotIn('C922', text)
        self.assertIn('-i /dev/video0', text)

    def test_vaapi_with_driver(self):
        text = mod.render(['10.0.0.2', '10.0.0.3'], '/dev/v4l/by-id/usb-X-video-index0', ['wlp2s0'], True, '/dev/dri/renderD129', 'i965')
        self.assertIn('LIBVA_DRIVER_NAME=i965', text)
        self.assertIn('/dev/dri/renderD129', text)
        self.assertIn('webrtcIPsFromInterfacesList: [wlp2s0, tailscale0]', text)
        self.assertEqual(text.count('h264_vaapi'), 2)

    def test_rejects_bad_values(self):
        for bad in ({'servers': []}, {'servers': ['a; rm -rf /']}, {'servers': ['1.2.3.4'], 'webcam': '/dev/video0 -f x'}):
            with self.assertRaises(ValueError):
                mod.render(bad['servers'], bad.get('webcam', '/dev/video0'))
        with self.assertRaises(ValueError):
            mod.render(['1.2.3.4'], '/dev/video0', size='huge')

    def test_valid_yaml_structure(self):
        import yaml  # só se disponível
        data = yaml.safe_load(mod.render(['192.168.0.10'], '/dev/video0'))
        self.assertEqual(set(data['paths']), {'cam', 'cam-lite', 'mic', 'talk', 'face'})


if __name__ == '__main__':
    unittest.main()
