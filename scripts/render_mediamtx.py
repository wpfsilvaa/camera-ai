#!/usr/bin/env python3
"""Gera o mediamtx.yml do totem (notebook da cozinha) a partir de parâmetros, sem IPs ou dispositivos fixos no código.

Exemplo:
  python3 scripts/render_mediamtx.py --server-ip 192.168.0.10 --webcam /dev/video0 --iface wlan0 --vaapi > mediamtx.yml
Sem --vaapi o vídeo é codificado em software (libx264): funciona em qualquer notebook, usando mais CPU.
"""
import argparse
import re
import sys

HEADER = """# Casa Presente: câmera, microfone e alto-falante da cozinha (gerado por scripts/render_mediamtx.py).
# Só este notebook e o servidor do painel ({servers}) podem publicar e ouvir o microfone; a rede local só vê a câmera.
authInternalUsers:
  - user: any
    ips: [{ips}]
    permissions:
      - action: publish
      - action: read
      - action: playback
      - action: api
  - user: any
    permissions:
      - action: read
        path: cam
      - action: read
        path: cam-lite

# WebRTC só oferece os endereços destas interfaces de rede.
webrtcIPsFromInterfacesList: [{ifaces}]

paths:
"""

CAM_VAAPI = """  cam:
    runOnInit: >
{env}      ffmpeg -nostdin -hide_banner -loglevel warning
      -hwaccel vaapi -hwaccel_device {render} -hwaccel_output_format vaapi
      -f v4l2 -input_format mjpeg -video_size {size} -framerate {fps}
      -i {webcam}
      -an -vf scale_vaapi=format=nv12 -c:v h264_vaapi -b:v 6M -maxrate 6M -g 60 -bf 0
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
    runOnInitRestart: yes
"""
CAM_SOFT = """  cam:
    runOnInit: >
      ffmpeg -nostdin -hide_banner -loglevel warning
      -f v4l2 -video_size {size} -framerate {fps}
      -i {webcam}
      -an -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -b:v 3M -maxrate 3M -g 60 -bf 0
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
    runOnInitRestart: yes
"""
LITE_VAAPI = """
  cam-lite:
    runOnDemand: >
{env}      ffmpeg -nostdin -hide_banner -loglevel warning
      -hwaccel vaapi -hwaccel_device {render} -hwaccel_output_format vaapi
      -rtsp_transport tcp -i rtsp://127.0.0.1:$RTSP_PORT/cam
      -an -vf fps=15,scale_vaapi=w=640:h=360:format=nv12
      -c:v h264_vaapi -profile:v constrained_baseline -b:v 450k -maxrate 450k -g 30 -bf 0
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
    runOnDemandRestart: yes
    runOnDemandCloseAfter: 10s
"""
LITE_SOFT = """
  cam-lite:
    runOnDemand: >
      ffmpeg -nostdin -hide_banner -loglevel warning
      -rtsp_transport tcp -i rtsp://127.0.0.1:$RTSP_PORT/cam
      -an -vf fps=15,scale=640:360
      -c:v libx264 -preset ultrafast -tune zerolatency -profile:v baseline -pix_fmt yuv420p -b:v 450k -maxrate 450k -g 30 -bf 0
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
    runOnDemandRestart: yes
    runOnDemandCloseAfter: 10s
"""
AUDIO = """
  # Microfone com eco cancelado; só captura enquanto alguém está ouvindo.
  mic:
    runOnDemand: >
      ffmpeg -hide_banner -loglevel warning
      -f pulse -fragment_size 1920 -i cozinha-microfone
      -ac 1 -c:a libopus -b:a 48k -application voip -frame_duration 20
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
    runOnDemandRestart: yes
    runOnDemandCloseAfter: 5s

  # Voz de quem chama, publicada pelo painel; toca no alto-falante com eco cancelado.
  talk:
    runOnAvailable: >
      ffmpeg -hide_banner -loglevel warning
      -fflags nobuffer -flags low_delay -rtsp_transport tcp
      -i rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH
      -vn -ac 1 -f pulse -buffer_duration 60 -device cozinha-falante Chamada
    runOnAvailableRestart: yes

  # Rosto de quem atendeu a chamada do botão: o painel publica (WHIP) e a tela do quiosque lê (WHEP).
  face: {}
"""
IP = re.compile(r'^[0-9a-fA-F:.]+$')
SAFE = re.compile(r'^[A-Za-z0-9_./:+-]+$')   # caminhos e nomes sem espaços nem caracteres que o YAML/ffmpeg interpretariam


def render(servers, webcam, ifaces=('wlan0',), vaapi=False, render_node='/dev/dri/renderD128', driver='', size='1280x720', fps=30):
    servers = list(servers)
    if not servers or not all(IP.match(ip) for ip in servers):
        raise ValueError('Informe o IP do computador do painel (ex.: 192.168.0.10).')
    for value in [webcam, render_node, *ifaces]:
        if not SAFE.match(value):
            raise ValueError(f'Valor inválido: {value!r}')
    if not re.match(r'^\d{3,4}x\d{3,4}$', size) or not 5 <= int(fps) <= 60:
        raise ValueError('Resolução ou quadros por segundo inválidos.')
    if driver and not SAFE.match(driver):
        raise ValueError(f'Driver inválido: {driver!r}')
    env = f'      env LIBVA_DRIVER_NAME={driver}\n' if driver else ''
    ips = ', '.join(['127.0.0.1', '"::1"', *servers])
    text = HEADER.format(servers=', '.join(servers), ips=ips, ifaces=', '.join([*ifaces, 'tailscale0']))
    fields = dict(env=env, render=render_node, webcam=webcam, size=size, fps=int(fps))
    text += (CAM_VAAPI if vaapi else CAM_SOFT).format(**fields) + (LITE_VAAPI if vaapi else LITE_SOFT).format(**fields) + AUDIO
    return text


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--server-ip', action='append', required=True, help='IP do computador do painel (repita para mais de um)')
    p.add_argument('--webcam', required=True, help='dispositivo da webcam, de preferência em /dev/v4l/by-id/')
    p.add_argument('--iface', action='append', help='interface de rede (padrão: wlan0)')
    p.add_argument('--vaapi', action='store_true', help='codificar na GPU Intel/AMD (VAAPI)')
    p.add_argument('--render-node', default='/dev/dri/renderD128')
    p.add_argument('--vaapi-driver', default='', help='ex.: i965 para Intel antiga; vazio = automático')
    p.add_argument('--size', default='1280x720')
    p.add_argument('--fps', type=int, default=30)
    a = p.parse_args(argv)
    try:
        sys.stdout.write(render(a.server_ip, a.webcam, a.iface or ['wlan0'], a.vaapi, a.render_node, a.vaapi_driver, a.size, a.fps))
    except ValueError as error:
        print(f'Erro: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
