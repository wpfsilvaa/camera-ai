import unittest
from unittest import mock

from app import image_controls as ic

SAMPLE = """User Controls

                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128 flags=has-min-max
                           gain 0x00980913 (int)    : min=0 max=255 step=1 default=0 value=255 flags=has-min-max
Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=1 (Manual Mode)
         exposure_time_absolute 0x009a0902 (int)    : min=3 max=2047 step=1 default=250 value=331 flags=has-min-max
"""


class ImageControlsTests(unittest.TestCase):
    def test_every_profile_only_uses_known_controls_inside_their_range(self):
        for key, profile in ic.PROFILES.items():
            self.assertEqual(ic.clean(profile['controls']), profile['controls'], key)

    def test_values_are_clamped_and_unknown_controls_dropped(self):
        self.assertEqual(ic.clean({'gain': 999, 'exposure_time_absolute': -4, 'rm -rf': 1, 'sharpness': True, 'focus_absolute': 12.7}),
                         {'gain': 255, 'exposure_time_absolute': 3, 'focus_absolute': 12})

    def test_modes_are_set_before_the_values_that_need_them(self):
        calls = ic.commands('/dev/video2', ic.PROFILES['balanced']['controls'])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][3].startswith('--set-ctrl=auto_exposure=1'))
        self.assertIn('exposure_time_absolute=200', calls[1][3])
        self.assertNotIn('auto_exposure', calls[1][3])

    def test_device_comes_from_the_source_and_rtsp_has_none(self):
        self.assertEqual(ic.device_of('usb:/dev/v4l/by-id/cam-video-index0?1920x1080@15'), '/dev/v4l/by-id/cam-video-index0')
        self.assertEqual(ic.device_of('0'), '/dev/video0')
        self.assertIsNone(ic.device_of('rtsp://192.168.1.2/cam'))

    def test_apply_runs_v4l2_ctl_and_reads_values_back(self):
        with mock.patch.object(ic, 'available', return_value=True), mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0, stdout=SAMPLE, stderr='')
            self.assertEqual(ic.apply('usb:/dev/video2', {'gain': 200, 'auto_exposure': 1}), 2)
            self.assertEqual(run.call_args_list[0].args[0][:3], ['v4l2-ctl', '-d', '/dev/video2'])
            self.assertEqual(ic.read('usb:/dev/video2'), {'brightness': 128, 'gain': 255, 'auto_exposure': 1, 'exposure_time_absolute': 331})
        with mock.patch.object(ic, 'available', return_value=True), mock.patch('subprocess.run') as run:
            self.assertEqual(ic.apply('rtsp://x/y', {'gain': 1}), 0)   # Not a local camera: nothing runs.
            run.assert_not_called()

    def test_custom_profile_starts_from_manual_mode(self):
        controls = ic.controls_for('custom', {'gain': 120, 'exposure_time_absolute': 150})
        self.assertEqual((controls['auto_exposure'], controls['gain'], controls['exposure_time_absolute']), (1, 120, 150))
        self.assertEqual(ic.controls_for('keep'), {})


    def test_fine_tuning_overrides_a_profile_and_only_the_changes_are_kept(self):
        base = ic.PROFILES['balanced']['controls']
        tuned = ic.fine_tuning('balanced', {**base, 'gain': 170, 'sharpness': 110})
        self.assertEqual(tuned, {'gain': 170})                      # Sharpness equals the profile's own: nothing to store.
        self.assertEqual(ic.controls_for('balanced', presets={'balanced': tuned})['gain'], 170)
        self.assertEqual(ic.controls_for('balanced', presets={'balanced': tuned})['exposure_time_absolute'], 200)
        self.assertEqual(ic.controls_for('motion', presets={'balanced': tuned})['gain'], 200)   # Other profiles are untouched.
        self.assertEqual(ic.fine_tuning('balanced', base), {})                                  # Back to the default.
        self.assertEqual(ic.controls_for('keep', presets={'keep': {'gain': 1}}), {})

    def test_settings_keep_only_valid_fine_tuning(self):
        from app.config import CameraSettings
        settings = CameraSettings(image_presets={'balanced': {'gain': 999, 'bogus': 1}, 'keep': {'gain': 5}, 'nope': {'gain': 5}, 'motion': {}})
        self.assertEqual(settings.image_presets, {'balanced': {'gain': 255}})


class FocusTests(unittest.TestCase):
    def curve(self, peak):
        """Sharpness by focus position: a hill around `peak`."""
        return lambda position: 100 + 400 * max(0, 1 - abs(position - peak) / 70)

    def run_sweep(self, peak, noisy=False):
        from app.focus import Sweep
        state = {'position': 0}
        sharp = self.curve(peak)
        read = (lambda window: [100.0, 101.0, 99.0]) if noisy else (lambda window: [sharp(state['position'])] * 4)
        sweep = Sweep(lambda position: state.update(position=position), read, sleep=lambda seconds: None)
        return sweep.run()

    def test_finds_the_sharpest_position(self):
        result = self.run_sweep(peak=130)
        self.assertEqual(result['best'], 130)
        self.assertTrue(result['clear'])
        self.assertGreater(len(result['scores']), 12)       # Coarse pass plus the fine one around the best.

    def test_a_flat_curve_has_no_clear_peak(self):
        result = self.run_sweep(peak=0, noisy=True)
        self.assertFalse(result['clear'])

    def test_not_enough_readings_leaves_no_score(self):
        from app.focus import Sweep
        sweep = Sweep(lambda position: None, lambda window: [5.0], sleep=lambda seconds: None)
        self.assertEqual(sweep.run()['best'], None)

    def test_sharpness_is_higher_for_a_detailed_region_than_a_blurred_one(self):
        import cv2
        import numpy as np
        from app.focus import region_sharpness
        rng = np.random.default_rng(1)
        detailed = (rng.random((360, 640, 3)) * 255).astype(np.uint8)
        blurred = cv2.GaussianBlur(detailed, (0, 0), 6)
        sharp, region = region_sharpness(detailed, [])
        self.assertEqual(region, 'centro')
        self.assertGreater(sharp, 10 * region_sharpness(blurred, [])[0])
        self.assertEqual(region_sharpness(detailed, [[100, 50, 300, 300]])[1], 'pessoa')


if __name__ == '__main__':
    unittest.main()
