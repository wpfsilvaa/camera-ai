"""ByteTrack with separate admission/recovery thresholds and expiry in seconds."""
from itertools import count
from types import SimpleNamespace


class PersonTracker:
    low_confidence = .1

    def __init__(self, confidence=.5, lost_seconds=2.):
        from ultralytics.trackers.byte_tracker import BYTETracker

        class LocalIDs(BYTETracker):
            def init_track(self, *args, **kwargs):
                tracks = super().init_track(*args, **kwargs)
                for track in tracks:
                    track.next_id = lambda: next(self.local_ids)
                return tracks

        self.tracker = LocalIDs(SimpleNamespace(track_high_thresh=confidence,
            track_low_thresh=self.low_confidence, new_track_thresh=confidence,
            track_buffer=2**31-1, match_thresh=.8, fuse_score=True))
        self.tracker.local_ids = count(1)
        self.lost_seconds = lost_seconds
        self.seen = {}
        self.last_time = None

    def update(self, boxes, frame, timestamp):
        if self.last_time is not None and timestamp < self.last_time:
            self.tracker.reset()
            self.seen.clear()
        self.last_time = timestamp
        expired = {key for key, seen in self.seen.items() if timestamp-seen>self.lost_seconds}
        for pool in ('tracked_stracks', 'lost_stracks'):
            tracks = getattr(self.tracker, pool)
            for track in tracks:
                if track.track_id in expired:
                    track.mark_removed()
            setattr(self.tracker, pool, [t for t in tracks if t.track_id not in expired])
        for key in expired:
            self.seen.pop(key, None)
        # Low scores can continue a matched track, but cannot create a new one.
        tracks = self.tracker.update(boxes.cpu().numpy(), img=frame)
        active = self.tracker.tracked_stracks + self.tracker.lost_stracks
        for track in active:
            self.seen.setdefault(track.track_id, timestamp)
        ids = [int(row[4]) for row in tracks]
        for key in ids:
            self.seen[key] = timestamp
        return [row[:4].tolist() for row in tracks], ids
