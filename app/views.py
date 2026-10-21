"""How usable a saved face is for recognition: is it a clear face, a profile, or something else (an ear, a cup, a hand)?

The saved crop is run through the face detector again. A profile is not the same as a bad photo: someone who is
mostly seen from the side has good profile examples, so they are measured and cached, and each caller decides.
"""
import cv2
import numpy as np

from .config import FACE_DETECTOR

UNCLEAR_SCORE = .75   # The detector is less sure than this: not a clear face.
PROFILE_YAW = 1.5     # Nose this far (in eye distances) from the middle of the eyes: seen from the side.
_detector = None


def view_of(path):
    """(score, yaw) of the best face in the saved crop; (0.0, None) when none is found; None when the file is missing."""
    global _detector
    image = cv2.imread(str(path))
    if image is None:
        return None
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(FACE_DETECTOR, '', (224, 224), .4, .3, 5)
    padded = cv2.copyMakeBorder(cv2.resize(image, (224, 224)), 56, 56, 56, 56, cv2.BORDER_REPLICATE)
    _detector.setInputSize((padded.shape[1], padded.shape[0]))
    _, found = _detector.detect(padded)
    if found is None or len(found) == 0:
        return 0.0, None
    face = found[int(np.argmax(found[:, -1]))]
    eyes = np.linalg.norm(face[4:6] - face[6:8]) + 1e-6
    return float(face[-1]), float(abs(face[8] - (face[4] + face[6]) / 2) / eyes)


def kind_of(view):
    """'unclear' (no clear face), 'profile' (a clear face seen from the side) or 'front'. A missing file counts as 'front'."""
    if view is None:
        return 'front'
    score, yaw = view
    if yaw is None or score < UNCLEAR_SCORE:
        return 'unclear'
    return 'profile' if yaw > PROFILE_YAW else 'front'


class ViewCache:
    """The measurements are kept in the database: the detector runs once per saved face."""

    def __init__(self, db, directory, measure=None):
        self.db, self.directory, self.measure = db, directory, measure

    def get(self, sample_id):
        row = self.db.rows('SELECT score,yaw FROM sample_views WHERE sample_id=?', (sample_id,))
        if row:
            return (row[0]['score'], row[0]['yaw']) if row[0]['score'] is not None else None
        view = (self.measure or view_of)(self.directory / f'{sample_id}.jpg')
        if view is not None:
            self.db.execute('INSERT OR REPLACE INTO sample_views(sample_id,score,yaw) VALUES(?,?,?)', (sample_id, view[0], view[1]))
        return view

    def kind(self, sample_id):
        return kind_of(self.get(sample_id))

    def profile_share(self, person_id):
        """Share of a person's taught faces that are clear profiles (0 to 1)."""
        ids = [r['id'] for r in self.db.rows("SELECT id FROM person_samples WHERE person_id=? AND model LIKE 'sface-%'", (person_id,))]
        if not ids:
            return 0.0
        return sum(1 for sample in ids if self.kind(sample) == 'profile') / len(ids)
