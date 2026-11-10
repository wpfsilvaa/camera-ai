import unittest

from app.image_auto import CONFIRM_SECONDS, HOLD_SECONDS, Ladder, scheduled_profile

RULES = [{'start': 22, 'end': 6, 'profile': 'low_light'}, {'start': 6, 'end': 11, 'profile': 'balanced'}, {'start': 11, 'end': 18, 'profile': 'bright_day'}]


class ScheduleTests(unittest.TestCase):
    def test_picks_the_rule_of_the_hour_wrapping_past_midnight(self):
        by_hour = {h: scheduled_profile(RULES, h, 'auto') for h in (0, 5, 6, 10, 11, 17, 18, 21, 22, 23)}
        self.assertEqual((by_hour[0], by_hour[5], by_hour[23], by_hour[22]), ('low_light',) * 4)
        self.assertEqual((by_hour[6], by_hour[10]), ('balanced', 'balanced'))
        self.assertEqual((by_hour[11], by_hour[17]), ('bright_day', 'bright_day'))
        self.assertEqual((by_hour[18], by_hour[21]), ('auto', 'auto'))   # No rule: the fallback.


class LadderTests(unittest.TestCase):
    def test_steps_only_after_staying_out_of_the_band(self):
        ladder = Ladder(('bright_day', 'balanced', 'low_light'), start='balanced')
        self.assertEqual(ladder.update(40, 0), 'balanced')                       # Dark, but not for long enough yet.
        self.assertEqual(ladder.update(45, CONFIRM_SECONDS - 1), 'balanced')
        self.assertEqual(ladder.update(45, CONFIRM_SECONDS), 'low_light')       # One step towards more exposure.
        self.assertEqual(ladder.update(30, CONFIRM_SECONDS + 200), 'low_light')  # Nothing darker left.

    def test_a_brief_swing_is_ignored_and_a_step_needs_the_picture_to_settle(self):
        ladder = Ladder(('bright_day', 'balanced', 'low_light'), start='balanced')
        ladder.update(40, 0)
        ladder.update(120, 50)                                                   # Back in the band: the clock resets.
        self.assertEqual(ladder.update(40, 60 + CONFIRM_SECONDS - 1), 'balanced')
        ladder.update(200, 1000); self.assertEqual(ladder.update(200, 1000 + CONFIRM_SECONDS), 'bright_day')
        self.assertEqual(ladder.update(40, 1000 + CONFIRM_SECONDS + 1), 'bright_day')
        # Too dark again right after a step: wait the hold time as well as the confirmation.
        self.assertEqual(ladder.update(40, 1000 + CONFIRM_SECONDS + CONFIRM_SECONDS + 1), 'bright_day')
        self.assertEqual(ladder.update(40, 1000 + CONFIRM_SECONDS + HOLD_SECONDS), 'balanced')


if __name__ == '__main__':
    unittest.main()


class BlownHighlightsTests(unittest.TestCase):
    def test_blown_highlights_step_down_fast_even_with_a_good_mean(self):
        from app.image_auto import CLIP_CONFIRM_SECONDS, CLIP_LIMIT
        ladder = Ladder(('bright_day', 'balanced', 'low_light'), start='balanced')
        self.assertEqual(ladder.update(120, 0, CLIP_LIMIT + .01), 'balanced')
        self.assertEqual(ladder.update(120, CLIP_CONFIRM_SECONDS - 1, CLIP_LIMIT + .01), 'balanced')
        self.assertEqual(ladder.update(120, CLIP_CONFIRM_SECONDS, CLIP_LIMIT + .01), 'bright_day')   # Bem antes dos 90 s normais.

    def test_blown_does_not_also_ask_for_more_exposure(self):
        ladder = Ladder(('bright_day', 'balanced', 'low_light'), start='balanced')
        ladder.update(50, 0, .2)   # Média escura, mas há estouro: nunca sobe para "pouca luz".
        self.assertEqual(ladder.update(50, 500, .2), 'bright_day')

    def test_small_clipping_is_ignored(self):
        ladder = Ladder(('bright_day', 'balanced', 'low_light'), start='balanced')
        ladder.update(120, 0, .02)
        self.assertEqual(ladder.update(120, 1000, .02), 'balanced')
