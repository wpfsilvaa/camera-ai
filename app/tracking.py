"""ByteTrack with separate admission/recovery thresholds and expiry in seconds; optionally BoT-SORT with appearance (clothes) to keep numbers apart.

The appearance is cheap on purpose: a person already followed reuses the vector the track holds; the neural network runs only for a new, confident
detection (somebody appearing, or coming back after a jump), at most `MAX_ENCODES` (one) per frame, and never for the low-confidence second pass.
"""
import logging
import time
from itertools import count
from types import SimpleNamespace

import numpy as np

log = logging.getLogger(__name__)
MAX_ENCODES = 1     # Neural-network runs per frame, at most (about 100 ms each on the kitchen notebook): new people are encoded one frame after the other.
REUSE_IOU = .6      # A detection this much on top of a followed track is that track: its vector is reused, nothing is computed.


class PersonTracker:
    low_confidence = .1

    def __init__(self, confidence=.5, lost_seconds=2., appearance=False):
        self.requested = appearance   # What was asked for (it may have fallen back).
        self.appearance, self.appearance_error = False, None
        self.encodes, self.encode_ms, self.frames, self.update_ms = 0, 0., 0, 0.
        self.stage = 0
        arguments = SimpleNamespace(track_high_thresh=confidence, track_low_thresh=self.low_confidence, new_track_thresh=confidence,
                                    track_buffer=2**31-1, match_thresh=.8, fuse_score=True)
        if appearance:
            try:
                self.tracker = self.build_appearance(arguments)
                self.appearance = True
            except Exception as error:   # No ReID model, no onnxruntime...: the plain tracker still works.
                self.appearance_error = f'Rastreamento com aparência indisponível ({type(error).__name__}).'
                log.warning(self.appearance_error, exc_info=True)
        if not self.appearance:
            self.tracker = self.build_plain(arguments)
        self.tracker.local_ids = count(1)
        self.lost_seconds = lost_seconds
        self.seen = {}
        self.last_time = None

    @staticmethod
    def build_plain(arguments):
        from ultralytics.trackers.byte_tracker import BYTETracker

        class LocalIDs(BYTETracker):
            def init_track(self, *args, **kwargs):
                tracks = super().init_track(*args, **kwargs)
                for track in tracks:
                    track.next_id = lambda: next(self.local_ids)
                return tracks

        return LocalIDs(arguments)

    def build_appearance(self, arguments):
        from ultralytics.trackers.bot_sort import BOTSORT
        from .body import shared_encoder
        encoder = shared_encoder()   # Raises when the model is missing: the caller falls back.
        owner = self

        class LocalBot(BOTSORT):
            def init_track(self, results, img=None):
                owner.stage += 1   # 1: confident detections, 2: the low-confidence pass.
                tracks = super().init_track(results, img)
                for track in tracks:
                    track.next_id = lambda: next(self.local_ids)
                return tracks

        # gmc off: the cameras are fixed. proximity .5: the clothes only decide among boxes that already overlap; appearance .8 means a cosine of at least .6.
        arguments = SimpleNamespace(**vars(arguments), gmc_method='none', proximity_thresh=.5, appearance_thresh=.8, with_reid=False, model='auto', device=None)
        tracker = LocalBot(arguments)   # Built with ReID off: nothing is downloaded or loaded by ultralytics.
        # Then ours goes in. A model name other than "auto" makes ultralytics hand over the frame (what our encoder needs) instead of the detector's features.
        arguments.with_reid, arguments.model = True, 'proprio'
        tracker.encoder = lambda img, boxes: owner.encode(encoder, tracker, img, boxes)
        return tracker

    def encode(self, encoder, tracker, img, boxes):
        """One vector per detection: reuse the track's own when the box sits on it, run the network only for the new ones (a few per frame)."""
        started = time.perf_counter()
        followed = tracker.tracked_stracks
        features, computed = [], 0
        for row in boxes:
            x, y, w, h = row[:4]
            box = np.array([x - w / 2, y - h / 2, x + w / 2, y + h / 2])
            feature = None
            for track in followed:
                if getattr(track, 'smooth_feat', None) is None:
                    continue
                tx1, ty1, tx2, ty2 = track.xyxy
                inter = max(0., min(box[2], tx2) - max(box[0], tx1)) * max(0., min(box[3], ty2) - max(box[1], ty1))
                union = w * h + (tx2 - tx1) * (ty2 - ty1) - inter
                if union > 0 and inter / union >= REUSE_IOU:
                    feature = track.smooth_feat
                    break
            if feature is None and self.stage == 1 and computed < MAX_ENCODES:
                feature = encoder.embed(img, box)
                computed += 1
            features.append(np.zeros(1, dtype=np.float32) if feature is None else feature)   # A zero vector is "no appearance": that pair falls back to the boxes.
        self.encodes += computed
        self.encode_ms += (time.perf_counter() - started) * 1000
        return features

    def update(self, boxes, frame, timestamp):
        started = time.perf_counter()
        self.stage = 0
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
        # Column 7 is the detection index, which links a track to its pose keypoints.
        self.last_indices = [int(row[7]) for row in tracks]
        ids = [int(row[4]) for row in tracks]
        for key in ids:
            self.seen[key] = timestamp
        self.frames += 1
        self.update_ms += (time.perf_counter() - started) * 1000
        return [row[:4].tolist() for row in tracks], ids

    def cost(self):
        """Mean milliseconds per frame spent in the tracker and how often the network ran (for the dashboard)."""
        return {'appearance': self.appearance, 'frames': self.frames, 'ms': round(self.update_ms / self.frames, 2) if self.frames else 0,
                'encodes_per_100': round(self.encodes * 100 / self.frames, 1) if self.frames else 0, 'error': self.appearance_error}
