"""Short-lived body references anchored exclusively by a recognized face."""
from pathlib import Path

import cv2
import numpy as np

from .config import BODY_ENCODER
from .faces import normalized


class BodyEncoder:
    def __init__(self):
        import onnxruntime as ort
        if not Path(BODY_ENCODER).is_file():
            raise RuntimeError('Modelo corporal ausente: yolo26n-reid.onnx.')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(BODY_ENCODER, options, providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0].name

    def for_people(self, frame, boxes, ids, diagnostics=None):
        result = {}
        height, width = frame.shape[:2]
        for index, (box, key) in enumerate(zip(boxes, ids)):
            if key is None:
                continue
            detail = {}
            if diagnostics is not None:
                diagnostics.setdefault(str(key), {})['body'] = detail
            x1,y1,x2,y2 = box
            area = max(1,(x2-x1)*(y2-y1))
            # Do not memorize or match crops that contain much of another person.
            if any(j != index and max(0,min(x2,b[2])-max(x1,b[0])) *
                   max(0,min(y2,b[3])-max(y1,b[1])) / min(area,max(1,(b[2]-b[0])*(b[3]-b[1]))) > .3
                   for j,b in enumerate(boxes)):
                detail['reason'] = 'overlap'
                continue
            left,top,right,bottom = max(0,int(x1)),max(0,int(y1)),min(width,int(x2)),min(height,int(y2))
            if right-left < 60 or bottom-top < 120:
                detail['reason'] = 'small_body'
                continue
            detail['reason'] = 'usable_body'
            crop = frame[top:bottom,left:right].copy()
            # Ignore the head in both the stored reference and the returning crop.
            # This keeps comparison focused on clothes and body appearance.
            crop[:round(crop.shape[0]*.22)] = 114
            rgb = cv2.cvtColor(cv2.resize(crop,(448,448),interpolation=cv2.INTER_LINEAR),cv2.COLOR_BGR2RGB)
            tensor = np.ascontiguousarray(rgb.transpose(2,0,1)[None],dtype=np.float32)/255.
            result[str(key)] = normalized(self.session.run(None,{self.input:tensor})[0][0])
        return result


class BodyMemory:
    def __init__(self):
        self.references = {}
        self.votes = {}
        self.features = {}

    def clear(self):
        self.references.clear()
        self.votes.clear()
        self.features.clear()

    def prune(self, now, lifetime):
        for person in list(self.references):
            self.references[person] = [r for r in self.references[person] if 0 <= now-r['seen'] <= lifetime]
            if not self.references[person]:
                del self.references[person]
        self.votes = {k:v for k,v in self.votes.items() if 0 <= now-v[2] <= 1.5}

    def retain(self, visible):
        self.features = {k:v for k,v in self.features.items() if k in visible}

    def smooth(self, key, feature, now):
        previous, last = self.features.get(key, ([], now))
        if not 0 <= now-last <= 1.5:
            previous = []
        values = (previous+[normalized(feature)])[-5:]
        self.features[key] = (values, now)
        return normalized(np.mean(values, axis=0))

    def learn(self, person, feature, now, *, anchored_at=None):
        # Track-derived views keep the original facial anchor's expiry. Clothing
        # matches never call learn and cannot perpetuate their own identity.
        source = 'face' if anchored_at is None else 'track'
        anchor = now if anchored_at is None else anchored_at
        refs = self.references.setdefault(person, [])
        vector = normalized(feature)
        group = [r for r in refs if r.get('source', 'face') == source]
        if group and now-max(r.get('collected', r['seen']) for r in group) < .3:
            return
        similar = next((r for r in group if float(vector@r['feature']) > .995), None)
        if similar is not None:
            similar.update(feature=vector, seen=anchor, collected=now)
            return
        refs.append({'feature':vector, 'seen':anchor, 'collected':now, 'source':source})
        if len(group) >= 12:
            oldest = min(group, key=lambda r:r.get('collected', r['seen']))
            refs[:] = [r for r in refs if r is not oldest]

    def match(self, key, feature, now, threshold, margin, diagnostic=None):
        vector = normalized(feature)
        scores = sorted(((max(float(vector@r['feature']) for r in refs),person)
                         for person,refs in self.references.items()),reverse=True)
        person = None
        score = scores[0][0] if scores else None
        if scores and score >= threshold and (len(scores)==1 or score-scores[1][0]>=margin):
            person = scores[0][1]
        previous,count,last = self.votes.get(key,(None,0,0))
        count = count+1 if person and person==previous and 0<=now-last<=1.5 else int(person is not None)
        self.votes[key]=(person,count,now)
        if diagnostic is not None:
            diagnostic.update(reason='matched' if person and count>=3 else 'waiting_agreement' if person else
                'no_references' if not scores else 'below_threshold' if score<threshold else 'ambiguous_match',
                score=score, threshold=threshold, margin=margin, candidate=scores[0][1] if scores else None,
                gap=score-scores[1][0] if len(scores)>1 else None,
                agreement=min(count,3), required=3,
                references=sum(len(refs) for refs in self.references.values()))
        return (person if count>=3 else None),score


class BodyAnchors:
    """Short continuous tracks may add new views of a face-verified person."""
    def __init__(self):
        self.items = {}

    def clear(self):
        self.items.clear()

    def retain(self, ids, boxes):
        visible = {str(key):box for key,box in zip(ids,boxes) if key is not None}
        for key in list(self.items):
            box = visible.get(key)
            if box is None or self.overlaps(key, visible):
                self.items.pop(key, None)
        return visible

    @staticmethod
    def overlaps(key, boxes):
        a = boxes[key]
        area = max(1,(a[2]-a[0])*(a[3]-a[1]))
        for other,b in boxes.items():
            if other == key: continue
            intersection = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            if intersection/min(area,max(1,(b[2]-b[0])*(b[3]-b[1]))) > .3: return True
        return False

    def observe(self, ids, boxes, faces, live, now):
        visible = self.retain(ids, boxes)
        output = {}
        for key,box in visible.items():
            if self.overlaps(key, visible): continue
            item = live.get(key)
            if key in faces:
                self.items.pop(key, None)
                if item and item.get('source')=='face' and item['seen']==now:
                    self.items[key] = {'person':item['person_id'], 'face_at':now, 'last':now, 'box':box}
                continue
            anchor = self.items.get(key)
            if not anchor: continue
            a = anchor['box']; b = box
            intersection = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
            if not (0<=now-anchor['face_at']<=10 and 0<=now-anchor['last']<=1.5 and intersection/max(1,union)>=.25):
                self.items.pop(key, None)
                continue
            anchor.update(last=now, box=box)
            output[key] = (anchor['person'], anchor['face_at'])
        return output
