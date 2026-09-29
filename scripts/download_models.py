"""Download official OpenCV face and Ultralytics body models with pinned SHA-256 verification."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = 'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/'
MODELS = {
    'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-reid.onnx': '8529c383197ae4c468eda535d1b165f8b4162cf17bf5fbcff49c7cb6455bc0bb',
    'face_detection_yunet/face_detection_yunet_2023mar.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    'face_recognition_sface/face_recognition_sface_2021dec.onnx': '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',
}
for remote, checksum in MODELS.items():
    target = ROOT / Path(remote).name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        print(f'{target.name}: verificado')
        continue
    temporary = target.with_suffix('.download')
    try:
        with urlopen(remote if remote.startswith('https://') else BASE + remote, timeout=90) as response:
            temporary.write_bytes(response.read())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum:
            raise RuntimeError(f'Checksum incorreto: {target.name}')
        temporary.replace(target)
        print(f'{target.name}: instalado')
    finally:
        temporary.unlink(missing_ok=True)
