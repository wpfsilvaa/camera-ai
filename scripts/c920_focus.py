#!/usr/bin/env python3
"""Run on the Linux notebook physically connected to the camera. No network control."""
import argparse,re,shutil,subprocess,sys

def main():
    parser=argparse.ArgumentParser(description='Consultar ou ajustar foco manual da C920 com v4l2-ctl.')
    parser.add_argument('--device',required=True,help='Dispositivo de captura, de preferência /dev/v4l/by-id/...-video-index0')
    parser.add_argument('--focus',type=int,help='Foco manual; deve respeitar a faixa e o passo do driver.')
    args=parser.parse_args()
    if not shutil.which('v4l2-ctl'):parser.error('Instale v4l-utils no notebook da câmera.')
    def run(*options):
        return subprocess.run(['v4l2-ctl','--device',args.device,*options],check=True,text=True,capture_output=True).stdout
    listing=run('--list-ctrls-menus')
    controls={}
    for line in listing.splitlines():
        found=re.match(r'\s*(\w+)\s+0x[0-9a-f]+\s+\(([^)]+)\)\s*:\s*(.*)',line)
        if found:controls[found[1]]=found[3]
    auto=next((name for name in ('focus_automatic_continuous','focus_auto') if name in controls),None)
    absolute='focus_absolute'
    if auto is None or absolute not in controls:parser.error('Driver não expôs os controles esperados de foco. Consulte v4l2-ctl --list-ctrls-menus.')
    if args.focus is None:
        print(f'{auto}: {controls[auto]}\n{absolute}: {controls[absolute]}')
        print('Consulta concluída. Para aplicar: repita com --focus VALOR e confira a imagem ao vivo.')
        return
    limits={key:int(value) for key,value in re.findall(r'(min|max|step)=(-?\d+)',controls[absolute])}
    if not all(k in limits for k in ('min','max','step')):parser.error('Não foi possível ler a faixa de foco do driver.')
    if not limits['min']<=args.focus<=limits['max'] or (args.focus-limits['min'])%max(1,limits['step']):
        parser.error(f'Foco fora da faixa/passo: {limits}')
    run(f'--set-ctrl={auto}=0')
    run(f'--set-ctrl={absolute}={args.focus}')
    print(run(f'--get-ctrl={auto},{absolute}').strip())
    print('Autofoco desligado. Confira a nitidez na distância de uso; reaplique após reconectar/reiniciar, se necessário.')

if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.strip() or str(exc),file=sys.stderr);sys.exit(1)
