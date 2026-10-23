"""When to switch the camera's picture profile: by the clock, or by how bright the scene is.

The brightness rule is a ladder of profiles ordered from the brightest scene to the darkest. The picture is measured
(mean grey level, 0-255); too dark for a while moves one step towards more exposure, too bright one step back. Each profile
changes the picture by a limited amount and the band between the two limits is wide, so the camera does not flip back and forth.
"""
from .pacing import in_window

LOW, HIGH = 70, 185        # Mean grey level band that counts as "right".
CONFIRM_SECONDS = 90       # Out of the band for this long before a step.
HOLD_SECONDS = 300         # After a step, no other step for this long (the picture needs to settle).
DEFAULT_LADDER = ('bright_day', 'balanced', 'low_light')


def scheduled_profile(rules, hour, fallback):
    """Profile of the first rule whose window [start, end) holds `hour` (wrapping past midnight); `fallback` when none does."""
    for rule in rules:
        if in_window(hour, rule['start'], rule['end']):
            return rule['profile']
    return fallback


class Ladder:
    def __init__(self, profiles=DEFAULT_LADDER, start=None):
        self.profiles = list(profiles) or list(DEFAULT_LADDER)
        self.index = self.profiles.index(start) if start in self.profiles else len(self.profiles) // 2
        self.out_since = None
        self.changed = None

    @property
    def profile(self):
        return self.profiles[self.index]

    def update(self, level, now):
        """Feed the measured brightness; returns the profile to use now (it only changes after CONFIRM_SECONDS out of the band)."""
        if level is None:
            return self.profile
        direction = 1 if level < LOW else -1 if level > HIGH else 0
        if not direction:
            self.out_since = None
            return self.profile
        if self.out_since is None:
            self.out_since = now
        settled = self.changed is None or now - self.changed >= HOLD_SECONDS
        target = self.index + direction
        if now - self.out_since >= CONFIRM_SECONDS and settled and 0 <= target < len(self.profiles):
            self.index, self.changed, self.out_since = target, now, None
        return self.profile
