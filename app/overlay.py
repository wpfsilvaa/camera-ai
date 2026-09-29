"""The same labels are burned into live frames and saved video frames."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=256)
def label_image(text, size, color):
    candidates = ['/usr/share/fonts/TTF/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    font_path = next((p for p in candidates if Path(p).exists()),None)
    font = ImageFont.truetype(font_path,size) if font_path else ImageFont.load_default(size=size)
    bbox=font.getbbox(text)
    image=Image.new('RGB',(max(20,bbox[2]-bbox[0]+18),size+16),color)
    ImageDraw.Draw(image).text((9,6-bbox[1]),text,font=font,fill=(255,255,255))
    return cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)


def annotate(frame, boxes, ids, labels):
    output=frame.copy()
    height,width=output.shape[:2]
    size=max(15,min(26,round(width/70)))
    for box,key in zip(boxes,ids):
        x1,y1,x2,y2=map(int,box)
        x1,y1,x2,y2=max(0,x1),max(0,y1),min(width-1,x2),min(height-1,y2)
        item=labels.get(str(key),{})
        name=item.get('name')
        text=f'{name} · #{key}' if name else f'Desconhecido · #{key if key is not None else "?"}'
        if name and item.get('source')=='body':
            text+=' · corpo/roupa'
        if name and item.get('held'):
            text+=' · tracking'
        rgb=(164,112,36) if item.get('source')=='body' else (38,126,84) if name else (113,103,56)
        cv2.rectangle(output,(x1,y1),(x2,y2),rgb[::-1],2)
        label=label_image(text,size,rgb)
        lh,lw=label.shape[:2]
        lx=min(x1,max(0,width-lw));ly=max(0,y1-lh)
        crop=label[:min(lh,height-ly),:min(lw,width-lx)]
        output[ly:ly+crop.shape[0],lx:lx+crop.shape[1]]=crop
    return output
