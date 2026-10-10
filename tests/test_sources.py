import unittest

from app.sources import local_device


class SourceTests(unittest.TestCase):
    def test_rtsp_files_and_hosts_are_not_local(self):
        for source in ('rtsp://192.168.1.103:8554/cam', 'http://x/y.mjpg', 'video.mp4', '/home/a/b.mp4'):
            self.assertIsNone(local_device(source))

    def test_device_forms_and_default_mode(self):
        self.assertEqual(local_device('0'), (0, (1920, 1080, 30)))
        self.assertEqual(local_device('usb:/dev/video2'), ('/dev/video2', (1920, 1080, 30)))
        self.assertEqual(local_device('/dev/v4l/by-id/usb-cam-video-index0'), ('/dev/v4l/by-id/usb-cam-video-index0', (1920, 1080, 30)))

    def test_requested_mode(self):
        self.assertEqual(local_device('usb:/dev/video0?1280x720@15'), ('/dev/video0', (1280, 720, 15)))
        self.assertEqual(local_device('usb:0?640x480'), (0, (640, 480, 30)))

    def test_bad_mode_is_rejected(self):
        for source in ('usb:/dev/video0?big', 'usb:/dev/video0?9999x9999@30', 'usb:/dev/video0?1280x720@0'):
            with self.assertRaises(ValueError):
                local_device(source)


if __name__ == '__main__':
    unittest.main()
