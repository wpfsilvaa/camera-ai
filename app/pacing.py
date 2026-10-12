"""Ritmo do loop de vídeo: analisa menos quadros sem ninguém e grava no banco com menos frequência."""

# Seconds a person stays "active" after the last detection, so a brief miss does not slow analysis down.
ACTIVE_HOLD_SECONDS = 3.0
# An open event row only needs a fresh last_seen now and then; crash recovery tolerates a few seconds.
TOUCH_SECONDS = 5.0


class DetectionPacing:
    def __init__(self, hold=ACTIVE_HOLD_SECONDS):
        self.hold = hold
        self.last_active = None

    def reset(self):
        self.last_active = None

    def idle(self, now):
        return self.last_active is None or now - self.last_active >= self.hold

    def fps(self, settings, active, now):
        """Analysis rate: full while someone is around (or just left), idle rate otherwise."""
        if active:
            self.last_active = now
        if self.last_active is not None and now - self.last_active < self.hold:
            return settings.detection_fps
        return min(settings.idle_detection_fps, settings.detection_fps)


class TouchThrottle:
    def __init__(self, seconds=TOUCH_SECONDS):
        self.seconds = seconds
        self.reset()

    def reset(self):
        self.last = 0
        self.count = 0

    def due(self, now, count):
        """True when the event row should be written: interval elapsed, or a new peak of people."""
        if now - self.last >= self.seconds or count > self.count:
            self.last = now
            self.count = max(self.count, count)
            return True
        return False


# Even a still room is fully analysed this often, so a person who sits or lies motionless is not missed.
FORCE_SECONDS = 2.0
# Watch mode (night): the room is checked for motion at a low frame rate; a full analysis still runs this often.
SENTINEL_FORCE_SECONDS = 30.0
MOTION_SIZE = (160, 90)
PIXEL_DELTA = 20
CHANGED_SHARE = .002  # share of pixels that must change to count as motion


class MotionGate:
    """Cheap frame difference deciding whether the YOLO model needs to run on an idle room."""

    def __init__(self, force_seconds=FORCE_SECONDS, delta=PIXEL_DELTA, share=CHANGED_SHARE):
        self.force_seconds = force_seconds
        self.delta = delta
        self.share = share
        self.reset()

    def reset(self):
        self.previous = None
        self.last_full = None

    def skip(self, frame, now):
        """True when the frame shows no motion and a full analysis ran recently enough."""
        import cv2
        small = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        previous, self.previous = self.previous, small
        moved = previous is None or (cv2.absdiff(small, previous) > self.delta).mean() >= self.share
        stale = self.last_full is None or now - self.last_full >= self.force_seconds
        if moved or stale:
            self.last_full = now
            return False
        return True


def in_window(hour, start, end):
    """True when the hour falls in [start, end), wrapping past midnight (22 to 6); start == end means never."""
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end


def vigia_state(enabled, start, end, hour, resting, always=False):
    """Watch-mode state shown on the dashboard and the kitchen screen.

    off: switched off; resting: reading at the low rate; analysing: inside its hours but someone/something
    moved so the detector is running; scheduled: switched on, waiting for its hours.
    """
    if not enabled:
        return 'off'
    if resting:
        return 'resting'
    return 'analysing' if always or in_window(hour, start, end) else 'scheduled'


def kiosk_night(settings, hour):
    """Whether the kitchen screen is in its night look: inside the totem's night hours and not set to "normal"."""
    return settings.kiosk_night_mode != 'normal' and in_window(hour, settings.kiosk_night_start_hour, settings.kiosk_night_end_hour)


GREET_SECONDS = 10      # How long the kitchen screen greets someone.
BIRTHDAY_SECONDS = 25   # ... and on their birthday.
DAILY_SECONDS = 25      # ... and the first time of the day (date, weather and suggestions).
GREET_COOLDOWN = 1800   # The same person is greeted again only after this long.


def first_name(name):
    """What the screen says: the first name, without "Meu"/"Minha" from profiles like "Meu pai"."""
    words = [w for w in str(name).split() if w]
    if len(words) > 1 and words[0].lower() in ('meu', 'minha'):
        words = words[1:]
    return (words[0] if words else '')[:30]


def birthday_today(birthday, today):
    """Age turning today (0 when the year is unknown) if `birthday` (YYYY-MM-DD) falls on `today`, else None."""
    try:
        year, month, day = (int(part) for part in str(birthday).split('-'))
    except ValueError:
        return None
    if (month, day) == (today.month, today.day) or (month, day) == (2, 29) and (today.month, today.day) == (3, 1) and not _leap(today.year):
        return max(today.year - year, 0)
    return None


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class Greeter:
    """Picks who the kitchen screen should greet: a recognised person not greeted recently."""

    def __init__(self, seconds=GREET_SECONDS, cooldown=GREET_COOLDOWN):
        self.seconds, self.cooldown = seconds, cooldown
        self.last = {}
        self.last_any = 0   # When anybody was last greeted (keeps the screen refreshing fast around a greeting).
        self.current = None
        self.day = {}   # person -> the date they were last greeted on (the first greeting of a day carries the briefing).

    def update(self, tracks, now, birthdays=None, today=None):
        """tracks: [{'person_id', 'name'}] visible now; birthdays: {person_id: 'YYYY-MM-DD'}.

        Returns {'name', 'id'} (plus 'birthday' and 'age' on their birthday) while a greeting is due.
        """
        for track in tracks:
            person, name = track.get('person_id'), first_name(track.get('name') or '')
            if person and name and now - self.last.get(person, -self.cooldown) >= self.cooldown:
                self.last[person] = now
                self.last_any = now
                age = birthday_today((birthdays or {}).get(person), today) if today and birthdays else None
                self.current = {'name': name, 'id': int(now), 'person': person, 'until': now + (BIRTHDAY_SECONDS if age is not None else self.seconds)}
                if age is not None:
                    self.current.update(birthday=True, age=age)
                elif today and self.day.get(person) != today:
                    self.current.update(daily=True, until=now + DAILY_SECONDS)
                if today:
                    self.day[person] = today
                break
        if self.current and now < self.current['until']:
            return {k: v for k, v in self.current.items() if k != 'until'}
        return None


def screen_power_saving(settings, night):
    """Whether the panel is switched off while nobody is around in this period: by night with the "panel off" look,
    by day when the daytime option is on."""
    return settings.kiosk_night_mode == 'off' if night else settings.kiosk_screen_off_day
