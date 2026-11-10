#!/usr/bin/env bash
# Instala o totem no notebook da cozinha (câmera, microfone, alto-falante e tela de chamada).
# Rode NO NOTEBOOK, de dentro de uma cópia desta pasta:
#   ./scripts/install-totem.sh --server-ip 192.168.0.10
# O totem mostra um código de 6 dígitos na tela; no painel, Configurações → Totem → Procurar totens, digite o código.
# (Opcional: --token "$(ssh servidor cat camera-ai/data/notebook.token)" pareia na hora, sem código.)
# Opções: --webcam /dev/v4l/by-id/...  --iface wlan0  --mic NOME  --no-vaapi  --dry-run
set -euo pipefail
cd "$(dirname "$0")/.."
SERVER=; TOKEN=; WEBCAM=; IFACE=; MIC=; VAAPI=auto; DRY=0
while (( $# )); do
  case "$1" in
    --server-ip) SERVER=${2:-}; shift 2 ;;
    --token) TOKEN=${2:-}; shift 2 ;;
    --webcam) WEBCAM=${2:-}; shift 2 ;;
    --iface) IFACE=${2:-}; shift 2 ;;
    --mic) MIC=${2:-}; shift 2 ;;
    --no-vaapi) VAAPI=0; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
run() { if (( DRY )); then echo "[simulação] $*"; else "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
fail() { echo "Erro: $*" >&2; exit 1; }
need() { if (( DRY )); then echo "[simulação] faltaria: $*" >&2; else fail "$*"; fi; }

[[ "$(uname -s)" == Linux ]] || fail 'Só há suporte a Linux.'
[[ -n "$SERVER" ]] || fail 'Informe --server-ip (o IP do computador do painel).'
[[ -z "$TOKEN" ]] || (( ${#TOKEN} >= 32 )) || fail '--token deve ter 32 ou mais caracteres (conteúdo de data/notebook.token do servidor).'
for tool in ffmpeg python3; do command -v "$tool" >/dev/null || fail "Instale o $tool."; done
command -v mediamtx >/dev/null || [[ -x /usr/local/bin/mediamtx ]] || need 'Instale o MediaMTX (https://github.com/bluenviron/mediamtx/releases) em /usr/local/bin/mediamtx.'
BROWSER=
for b in google-chrome-stable google-chrome chromium chromium-browser; do command -v "$b" >/dev/null && { BROWSER=$b; break; }; done
[[ -n "$BROWSER" ]] || need 'Instale o Google Chrome ou o Chromium (a tela do totem abre nele).'

# Detecção automática (qualquer item pode ser forçado pelas opções).
[[ -n "$IFACE" ]] || IFACE=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
[[ -n "$IFACE" ]] || IFACE=wlan0
if [[ -z "$WEBCAM" ]]; then
  WEBCAM=$(ls /dev/v4l/by-id/*video-index0 2>/dev/null | head -n1 || true)
  [[ -n "$WEBCAM" ]] || WEBCAM=/dev/video0
fi
[[ -e "$WEBCAM" ]] || echo "Aviso: $WEBCAM não existe agora (webcam desligada?). Continuando." >&2
vaapi_flags=()
vainfo_out=
if [[ "$VAAPI" == auto ]] && [[ -e /dev/dri/renderD128 ]] && command -v vainfo >/dev/null; then
  vainfo_out=$(vainfo --display drm --device /dev/dri/renderD128 2>/dev/null || true)
fi
if grep -q 'H264.*EncSlice' <<<"$vainfo_out"; then
  vaapi_flags=(--vaapi)
  echo 'GPU com codificação H.264 detectada: usando VAAPI.'
else
  echo 'Sem codificação por GPU: usando software (libx264), um pouco mais de CPU.'
fi
NB_IP=$(ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{sub(/\/.*/,"",$4); print $4; exit}' || true)
echo "Servidor: $SERVER | webcam: $WEBCAM | rede: $IFACE | navegador: $BROWSER"

say 'Arquivos do totem'
conf="$HOME/.config"
run mkdir -p "$conf/casa-monitor" "$conf/mediamtx" "$conf/systemd/user" "$conf/pipewire/pipewire.conf.d"
run cp notebook/monitor.py "$conf/casa-monitor/monitor.py"
run rm -rf "$conf/casa-monitor/kiosk"
run cp -r notebook/kiosk "$conf/casa-monitor/kiosk"
run cp notebook/start-kiosk.sh "$conf/casa-monitor/start-kiosk.sh"
run chmod +x "$conf/casa-monitor/start-kiosk.sh"
if [[ -z "$TOKEN" ]]; then
  echo 'Sem --token: o totem começa sem pareamento e mostra um código na tela.'
elif (( DRY )); then echo "[simulação] gravar token em $conf/casa-monitor/token"; else
  ( umask 077; printf '%s' "$TOKEN" > "$conf/casa-monitor/token" )
fi

say 'MediaMTX'
if (( DRY )); then
  python3 scripts/render_mediamtx.py --server-ip "$SERVER" --webcam "$WEBCAM" --iface "$IFACE" "${vaapi_flags[@]}" | head -n 8
else
  python3 scripts/render_mediamtx.py --server-ip "$SERVER" --webcam "$WEBCAM" --iface "$IFACE" "${vaapi_flags[@]}" > "$conf/mediamtx/mediamtx.yml"
fi

say 'Eco da chamada (PipeWire)'
if [[ -n "$MIC" ]]; then
  sed "s#target.object = \"[^\"]*\"#target.object = \"$MIC\"#" notebook/60-echo-cancel.conf > /tmp/60-echo-cancel.$$ 
else
  sed 's# target.object = "[^"]*"##' notebook/60-echo-cancel.conf > /tmp/60-echo-cancel.$$   # sem alvo: usa o microfone padrão
fi
run cp /tmp/60-echo-cancel.$$ "$conf/pipewire/pipewire.conf.d/60-echo-cancel.conf"; rm -f /tmp/60-echo-cancel.$$

say 'Serviços'
run cp notebook/mediamtx.service notebook/casa-monitor.service "$conf/systemd/user/"
run systemctl --user daemon-reload
run systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
run systemctl --user enable --now mediamtx.service casa-monitor.service
command -v loginctl >/dev/null && run loginctl enable-linger "$USER" || true

cat <<EOF

Pronto. Falta só:
 1. Abrir a tela do totem ao iniciar a sessão gráfica: adicione  $conf/casa-monitor/start-kiosk.sh
    ao autostart do seu ambiente (no Hyprland: exec-once; no GNOME/KDE: "Aplicativos de início").
 2. No painel: Configurações → Totem → Procurar totens; digite o código que aparece na tela do notebook
    (se usou --token, ele já está pareado). Depois ative Configurações → Avisos → Notebook da câmera.
 3. No painel (Configurações → Câmera), endereço da câmera: rtsp://${NB_IP:-IP-DO-NOTEBOOK}:8554/cam
EOF
