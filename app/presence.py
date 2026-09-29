from dataclasses import dataclass


@dataclass
class Presence:
    """A visit is one continuous occupancy period, not a unique person."""
    minimum: float = 1
    absence: float = 8
    active: bool = False
    candidate: float | None = None
    last_seen: float | None = None

    def update(self, now, people):
        if people:
            self.last_seen = now
            if self.candidate is None:
                self.candidate = now
            if not self.active and now - self.candidate >= self.minimum:
                self.active = True
                return 'start'
        elif not self.active:
            self.candidate = None
        elif self.last_seen is not None and now - self.last_seen >= self.absence:
            self.active = False
            self.candidate = None
            return 'end'
        return None
