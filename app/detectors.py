"""Person-detector catalog: YOLO26 sizes x inference engines, fetched and converted only when selected.

Weights are downloaded from the official Ultralytics release (SHA-256 pinned) the first time a
size is chosen; ONNX/OpenVINO exports are generated once per detection size and cached in
data/models. Until the chosen detector is ready the camera keeps running on the default model.
"""
import hashlib
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from .config import DATA, MODEL, POSE_MODEL

os.environ.setdefault('YOLO_CONFIG_DIR', str(DATA / 'ultralytics'))
log = logging.getLogger(__name__)
MODELS = DATA / 'models'
MODELS.mkdir(exist_ok=True)
RELEASE = 'https://github.com/ultralytics/assets/releases/download/v8.4.0/'

CHECKSUMS = {
    'yolo26n': '9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef',
    'yolo26s': '646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b',
    'yolo26m': '401cea9ab23ad19246ff7744859816bc599f350e93c9dd30367b6f0a0745d0b7',
    'yolo26l': '9fe3c544f2b19bebad7ea41e76d7ad3d88b7c2f10d11d24430c5311f6b32db26',
    'yolo26n-pose': 'eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9',
    'yolo26s-pose': 'a083adb42303728ae14c4bd6bd56d80da46f82fb2564dbd6f31dcc92ea321646',
    'yolo26m-pose': '2fbf16367022256a226035695c5c389384c6706e8bb8ab8fcd0e7976f05443c4',
    'yolo26l-pose': 'ad33da8a29ea5772318c4c980844e47b56792d2b63815ad4e8e09c078c7d1abf',
}

# cost = relative inference time measured on CPU (n = 1); mb = download of the PyTorch weights.
SIZES = {
    'n': {'label': 'YOLO26n · nano', 'quality': 'Boa para pessoas próximas', 'cost': 1, 'mb': 6,
          'summary': 'O mais leve. Pode perder pessoas pequenas ou distantes.'},
    's': {'label': 'YOLO26s · pequeno', 'quality': 'Melhor com pessoas distantes', 'cost': 3, 'mb': 20,
          'summary': 'Bom equilíbrio para CPU potente ou GPU modesta.'},
    'm': {'label': 'YOLO26m · médio', 'quality': 'Alta precisão', 'cost': 6, 'mb': 44,
          'summary': 'Recomendado só com GPU NVIDIA.'},
    'l': {'label': 'YOLO26l · grande', 'quality': 'Máxima precisão', 'cost': 8, 'mb': 53,
          'summary': 'Só com GPU NVIDIA; em CPU fica lento demais para tempo real.'},
}
ENGINES = {
    'pytorch': {'label': 'PyTorch (original)', 'quality': 'Referência', 'speed': 'GPU NVIDIA: rápido · CPU: o mais lento',
                'summary': 'Use com GPU NVIDIA. Sem conversão.'},
    'onnx': {'label': 'ONNX Runtime', 'quality': 'Igual ao original', 'speed': 'CPU: 1,2 a 2× mais rápido que o PyTorch',
             'summary': 'Roda em qualquer CPU. Converte uma vez (cerca de 1 minuto).'},
    'openvino': {'label': 'OpenVINO', 'quality': 'Igual ao original', 'speed': 'CPU: ganho pequeno; nos modelos grandes pode ser mais lento que o PyTorch',
                 'summary': 'Mesma qualidade; mais útil em CPUs Intel antigas. Converte uma vez.'},
    'openvino-int8': {'label': 'OpenVINO INT8', 'quality': 'Levemente menor', 'speed': 'CPU: cerca de 2× mais rápido que o PyTorch',
                      'summary': 'Para CPU fraca ou VPS barata. Perde um pouco de precisão. Converte uma vez (alguns minutos).'},
}
DEFAULT_SIZE, DEFAULT_ENGINE = 'n', 'pytorch'

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_one_at_a_time = threading.Semaphore(1)


def _stem(size, pose):
    return f"yolo26{size}{'-pose' if pose else ''}"


def _fallback(pose):
    return Path(POSE_MODEL if pose else MODEL)


def _source(size, pose):
    """Path of the PyTorch weights for a size ('n' ships with the install)."""
    if size == 'n':
        return _fallback(pose)
    return MODELS / f'{_stem(size, pose)}.pt'


def _artifact(size, engine, pose, imgsz):
    stem = f'{_stem(size, pose)}-{imgsz}'
    if engine == 'pytorch':
        return _source(size, pose)
    if engine == 'onnx':
        return MODELS / f'{stem}.onnx'
    if engine == 'openvino':
        return MODELS / f'{stem}_openvino_model'
    return MODELS / f'{stem}-int8_openvino_model'


_ready_paths: set[Path] = set()


def _ready(path):
    if path in _ready_paths:
        return True
    if path.is_file() or (path.is_dir() and any(path.glob('*.xml'))):
        _ready_paths.add(path)
        return True
    return False


def _key(size, engine, pose, imgsz):
    return f'{size}/{engine}/{"pose" if pose else "det"}/{imgsz if engine != "pytorch" else 0}'


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _download(size, pose, job):
    target = _source(size, pose)
    if target.is_file():
        return target
    stem = _stem(size, pose)
    job['message'] = f'Baixando {stem}.pt'
    temporary = target.with_suffix('.download')
    try:
        with urlopen(f'{RELEASE}{stem}.pt', timeout=90) as response, temporary.open('wb') as out:
            shutil.copyfileobj(response, out, 1 << 20)
        if _sha256(temporary) != CHECKSUMS[stem]:
            raise RuntimeError(f'Checksum incorreto: {stem}.pt')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _export(size, engine, pose, imgsz, job):
    source = _download(size, pose, job)
    final = _artifact(size, engine, pose, imgsz)
    if _ready(final) or engine == 'pytorch':
        return
    job['message'] = 'Convertendo o modelo (feito uma vez)'
    work = MODELS / f'.work-{final.name}'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        staged = work / f'{_stem(size, pose)}-{imgsz}.pt'
        shutil.copy2(source, staged)
        from ultralytics import YOLO
        model = YOLO(str(staged), task='pose' if pose else 'detect')
        options = {'format': 'onnx' if engine == 'onnx' else 'openvino', 'imgsz': imgsz, 'verbose': False}
        if engine == 'openvino-int8':
            options.update(int8=True, data='coco8-pose.yaml' if pose else 'coco8.yaml')
        exported = Path(model.export(**options))
        if not exported.exists():
            raise RuntimeError('A conversão não gerou o modelo.')
        if final.exists():
            shutil.rmtree(final, ignore_errors=True) if final.is_dir() else final.unlink()
        shutil.move(str(exported), str(final))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run(size, engine, pose, imgsz, key):
    job = _jobs[key]
    with _one_at_a_time:
        try:
            _export(size, engine, pose, imgsz, job)
            job.update(state='ready', message='')
        except Exception as exc:
            log.exception('Falha ao preparar o detector %s', key)
            job.update(state='error', message=f'{type(exc).__name__}: {exc}'[:300])


def prepare(size, engine, pose, imgsz, retry=False):
    """Start fetching/converting in the background. Returns the artifact path when it is already usable."""
    path = _artifact(size, engine, pose, imgsz)
    if _ready(path):
        return path
    key = _key(size, engine, pose, imgsz)
    with _lock:
        job = _jobs.get(key)
        if job and (job['state'] == 'preparing' or (job['state'] == 'error' and not retry)):
            return None
        _jobs[key] = {'state': 'preparing', 'message': 'Na fila', 'started': time.time()}
        threading.Thread(target=_run, args=(size, engine, pose, imgsz, key), daemon=True, name=f'detector-{key}').start()
    return None


def resolve(size, engine, pose, imgsz):
    """(weights, task, engine, ready) to load now; the default PyTorch model while the chosen one is prepared."""
    task = 'pose' if pose else 'detect'
    path = prepare(size, engine, pose, imgsz)
    if path is not None:
        return str(path), task, engine, True
    return str(_fallback(pose)), task, 'pytorch', False


def ensure(size, engine, pose, imgsz):
    """Blocking variant for background jobs (offline analysis): prepare and wait, else use the default."""
    path = prepare(size, engine, pose, imgsz)
    key = _key(size, engine, pose, imgsz)
    while path is None and _jobs.get(key, {}).get('state') == 'preparing':
        time.sleep(1)
        path = _artifact(size, engine, pose, imgsz)
        path = path if _ready(path) else None
    if path is None:
        return str(_fallback(pose)), 'pose' if pose else 'detect', 'pytorch'
    return str(path), 'pose' if pose else 'detect', engine


def state(size, engine, pose, imgsz):
    path = _artifact(size, engine, pose, imgsz)
    if _ready(path):
        return {'state': 'ready', 'message': ''}
    job = _jobs.get(_key(size, engine, pose, imgsz))
    if job:
        return {'state': job['state'], 'message': job['message']}
    return {'state': 'missing', 'message': ''}


def label(size, engine):
    return f"{SIZES[size]['label'].split(' · ')[0]} · {ENGINES[engine]['label']}"


def catalog():
    return {
        'sizes': [{'id': key, 'installed': _source(key, False).is_file(), **value} for key, value in SIZES.items()],
        'engines': [{'id': key, **value} for key, value in ENGINES.items()],
    }
