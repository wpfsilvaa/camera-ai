"""Mede se o LFM2.5-VL-450M consegue confirmar "há uma pessoa?" em recortes dos alertas, sem enviar nada.

    .venv/bin/python scripts/lfm_check.py --lfm-dir /caminho/com/llama-bXXXX-e-model [--limit 40] [--dry-run]

Como funciona:
  - Positivos: o YOLO do projeto acha as pessoas nas fotos de alerta (data/alerts); cada recorte deve receber "sim".
  - Negativos: recortes de fundo (piso, cadeiras, sacos) sem nenhuma pessoa devem receber "não". Dá para somar casos
    conhecidos com --negative arquivo.jpg:x1,y1,x2,y2 (por exemplo, o saco de lixo que o detector marcou como "deitado").
  - Cada recorte é perguntado ao modelo com uma pergunta fechada (sim/não) e o resultado vai para o terminal e para
    <saida>/resultados.csv, com os recortes salvos para você conferir à mão.

Observação: as fotos de alerta já trazem a caixa e a etiqueta desenhadas pelo app; isso pode ajudar um pouco o modelo
e deve ser lembrado ao ler os números. O script não altera nada do app nem envia mensagens.
"""
import argparse
import csv
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROMPT = 'Há uma pessoa nesta imagem? Responda apenas sim ou não.'
MAX_SIDE = 512
MIN_SIDE = 64


def find_files(lfm_dir):
    lfm_dir = Path(lfm_dir)
    cli = next(iter(sorted(lfm_dir.glob('**/llama-mtmd-cli'))), None)
    model = next(iter(sorted(lfm_dir.glob('**/LFM2.5-VL-450M-*.gguf'))), None)
    mmproj = next(iter(sorted(lfm_dir.glob('**/mmproj-LFM2.5-VL-450m-*.gguf'))), None)
    missing = [n for n, p in (('llama-mtmd-cli', cli), ('modelo .gguf', model), ('mmproj .gguf', mmproj)) if not p]
    if missing:
        sys.exit(f'Não achei em {lfm_dir}: {", ".join(missing)}')
    return cli, model, mmproj


def ask(cli, model, mmproj, image, prompt, threads):
    """Devolve (resposta normalizada, segundos). A resposta fica no stdout; os logs do llama.cpp vão para o stderr."""
    started = time.time()
    run = subprocess.run(
        [str(cli), '-m', str(model), '--mmproj', str(mmproj), '--image', str(image), '-t', str(threads),
         '--temp', '0', '-n', '10', '-p', prompt],
        capture_output=True, text=True, timeout=300, cwd=str(cli.parent),
        env={'LD_LIBRARY_PATH': str(cli.parent), 'PATH': '/usr/bin:/bin'})
    seconds = time.time() - started
    text = run.stdout.strip().lower()
    word = text.replace('ã', 'a').split()[0].strip('.,!') if text else ''
    return {'sim': 'sim', 'nao': 'nao'}.get(word, f'?({text[:30]})'), seconds


def save_crop(frame, box, path):
    import cv2
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.shape[0] < MIN_SIDE or crop.shape[1] < MIN_SIDE:
        return False
    scale = MAX_SIDE / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), crop)
    return True


def overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def person_boxes(model, frame, confidence):
    result = model(frame, classes=[0], conf=confidence, verbose=False, device='cpu')[0]
    height, width = frame.shape[:2]
    boxes = []
    for x1, y1, x2, y2 in result.boxes.xyxy.cpu().numpy().tolist():
        pad_x, pad_y = (x2 - x1) * .08, (y2 - y1) * .08
        boxes.append((max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y)), min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y))))
    return boxes


def background_boxes(rng, boxes, width, height, count, side):
    found = []
    for _ in range(count * 30):
        if len(found) >= count:
            break
        x, y = rng.randint(0, max(0, width - side)), rng.randint(0, max(0, height - side))
        candidate = (x, y, x + side, y + side)
        if not any(overlaps(candidate, box) for box in boxes):
            found.append(candidate)
    return found


def parse_negative(text):
    try:
        path, coords = text.rsplit(':', 1)
        x1, y1, x2, y2 = map(int, coords.split(','))
    except ValueError:
        sys.exit(f'--negative inválido: {text} (use arquivo.jpg:x1,y1,x2,y2)')
    return Path(path), (x1, y1, x2, y2)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lfm-dir', help='pasta com o llama-mtmd-cli, o modelo .gguf e o mmproj .gguf')
    parser.add_argument('--alerts', default=str(ROOT / 'data' / 'alerts'), help='pasta das fotos de alerta')
    parser.add_argument('--kinds', default='restricted,presence,fall', help='tipos de alerta a usar (prefixo do arquivo)')
    parser.add_argument('--limit', type=int, default=30, help='quantas fotos sortear (padrão 30)')
    parser.add_argument('--negatives-per-photo', type=int, default=1)
    parser.add_argument('--negative', action='append', default=[], help='negativo conhecido: arquivo.jpg:x1,y1,x2,y2')
    parser.add_argument('--out', default=str(ROOT / 'data' / 'lfm_check'), help='onde salvar recortes e resultados.csv')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--confidence', type=float, default=.5)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--prompt', default=PROMPT)
    parser.add_argument('--dry-run', action='store_true', help='só gera os recortes, sem chamar o modelo')
    args = parser.parse_args()

    import cv2
    from ultralytics import YOLO
    from app.config import MODEL

    if not args.dry_run:
        if not args.lfm_dir:
            sys.exit('Informe --lfm-dir (ou use --dry-run).')
        cli, model_path, mmproj = find_files(args.lfm_dir)

    rng = random.Random(args.seed)
    kinds = tuple(k.strip() for k in args.kinds.split(',') if k.strip())
    photos = sorted(p for p in Path(args.alerts).glob('*.jpg') if p.name.startswith(kinds))
    rng.shuffle(photos)
    photos = photos[:args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    detector = YOLO(MODEL)

    items = []  # (rótulo esperado, origem, caminho do recorte)
    for photo in photos:
        frame = cv2.imread(str(photo))
        if frame is None:
            continue
        boxes = person_boxes(detector, frame, args.confidence)
        for n, box in enumerate(boxes):
            path = out / f'pos-{photo.stem}-{n}.jpg'
            if save_crop(frame, box, path):
                items.append(('sim', photo.name, path))
        side = 200
        for n, box in enumerate(background_boxes(rng, boxes, frame.shape[1], frame.shape[0], args.negatives_per_photo, side)):
            path = out / f'neg-{photo.stem}-{n}.jpg'
            if save_crop(frame, box, path):
                items.append(('nao', photo.name, path))
    for n, text in enumerate(args.negative):
        path_in, box = parse_negative(text)
        frame = cv2.imread(str(path_in))
        if frame is None:
            sys.exit(f'Não consegui abrir {path_in}')
        path = out / f'neg-conhecido-{n}.jpg'
        if save_crop(frame, box, path):
            items.append(('nao', path_in.name, path))

    positives = sum(1 for e, _, _ in items if e == 'sim')
    print(f'{len(photos)} fotos -> {positives} recortes com pessoa, {len(items) - positives} recortes sem pessoa. Em {out}')
    if args.dry_run:
        return

    rows, times = [], []
    for expected, origin, path in items:
        answer, seconds = ask(cli, model_path, mmproj, path, args.prompt, args.threads)
        times.append(seconds)
        rows.append((expected, answer, f'{seconds:.1f}', origin, path.name))
        mark = 'ok ' if answer == expected else 'ERRO'
        print(f'{mark} esperado={expected} resposta={answer} {seconds:4.1f}s {path.name}', flush=True)
    with open(out / 'resultados.csv', 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['esperado', 'resposta', 'segundos', 'foto', 'recorte'])
        writer.writerows(rows)

    def rate(expected):
        group = [r for r in rows if r[0] == expected]
        hits = sum(1 for r in group if r[1] == expected)
        return hits, len(group)
    yes_hits, yes_total = rate('sim')
    no_hits, no_total = rate('nao')
    print('\n--- Resumo ---')
    print(f'Pessoas reconhecidas como pessoa (sim): {yes_hits}/{yes_total}   <- erro aqui engole alerta de queda real')
    print(f'Fundo reconhecido como sem pessoa (não): {no_hits}/{no_total}   <- erro aqui deixa passar falso positivo')
    if times:
        print(f'Tempo por recorte: média {sum(times) / len(times):.1f} s, máximo {max(times):.1f} s (já inclui carregar o modelo)')


if __name__ == '__main__':
    main()
