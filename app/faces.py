"""YuNet detection, five-point alignment and SFace embeddings, entirely local."""
import hashlib
import threading
from pathlib import Path

import cv2
import numpy as np

from .config import FACE_DETECTOR, FACE_ENCODER


def normalized(feature):
    vector = np.asarray(feature, dtype=np.float32).reshape(-1)
    length = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or length < 1e-8:
        raise ValueError('Embedding facial inválido.')
    return vector / length


class FaceEncoder:
    def __init__(self):
        for path in (FACE_DETECTOR, FACE_ENCODER):
            if not Path(path).is_file():
                raise RuntimeError(f'Modelo facial ausente: {Path(path).name}. Execute scripts/download_models.py.')
        digest = hashlib.sha256(Path(FACE_ENCODER).read_bytes()).hexdigest()[:16]
        self.version = f'sface-v1-{digest}'
        self.detector = cv2.FaceDetectorYN.create(FACE_DETECTOR, '', (320,320), .85, .3, 100)
        self.recognizer = cv2.FaceRecognizerSF.create(FACE_ENCODER, '')
        self.lock = threading.Lock()

    def faces(self, image, max_width=640, single=False, diagnostic=None):
        diagnostic = diagnostic if diagnostic is not None else {}
        diagnostic.update(reason='no_face')
        height,width = image.shape[:2]
        scale = min(1., max_width/width)
        small = cv2.resize(image, (round(width*scale),round(height*scale))) if scale < 1 else image
        with self.lock:
            self.detector.setInputSize((small.shape[1],small.shape[0]))
            _, found = self.detector.detect(small)
            if single and (found is None or len(found) != 1):
                if found is not None and len(found)>1: diagnostic.update(reason='multiple_faces')
                return []
            output = []
            for face in found if found is not None else []:
                face = face.copy()
                face[:14] /= scale
                x,y,w,h = face[:4]
                diagnostic.update(face_pixels=round(float(min(w,h)),1))
                if min(w,h) < 40 or np.linalg.norm(face[4:6]-face[6:8]) < 12:
                    diagnostic.update(reason='small_face')
                    continue
                aligned = self.recognizer.alignCrop(image, face)
                quality = float(cv2.Laplacian(cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var())
                diagnostic.update(sharpness=round(quality,1))
                if quality < 35:
                    diagnostic.update(reason='blurred_face')
                    continue
                diagnostic.update(reason='usable_face')
                feature = normalized(self.recognizer.feature(aligned))
                output.append({'feature':feature,'crop':aligned,'quality':quality,'box':[float(x),float(y),float(x+w),float(y+h)]})
        return output

    def for_people(self, frame, boxes, ids, diagnostics=None):
        diagnostics = diagnostics if diagnostics is not None else {}
        result = {}
        height,width = frame.shape[:2]
        for box,key in zip(boxes,ids):
            if key is None:
                continue
            detail=diagnostics.setdefault(str(key),{'reason':'no_face'})
            x1,y1,x2,y2 = box
            left,top = max(0,int(x1)),max(0,int(y1))
            right,bottom = min(width,int(x2)),min(height,int(y1+(y2-y1)*.65))
            if right-left < 40 or bottom-top < 40:
                detail.update(reason='small_person')
                continue
            faces = self.faces(frame[top:bottom,left:right],max_width=480, single=True, diagnostic=detail)
            # Multiple faces inside a body box mean association is ambiguous.
            if len(faces) != 1:
                continue
            face = faces[0]
            face['box'] = [v+(left if i%2==0 else top) for i,v in enumerate(face['box'])]
            cx=(face['box'][0]+face['box'][2])/2
            cy=(face['box'][1]+face['box'][3])/2
            owners = [k for b,k in zip(boxes,ids) if k is not None and b[0]<=cx<=b[2] and b[1]<=cy<=b[1]+(b[3]-b[1])*.65]
            if owners == [key]:
                result[str(key)] = face
            else:
                detail.update(reason='ambiguous_owner')
        return result
