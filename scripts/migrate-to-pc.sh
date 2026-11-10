#!/usr/bin/env bash
# Move o processamento do notebook da cozinha para ESTE computador (o servidor): a webcam passa a ser publicada só pelo
# MediaMTX do notebook (rtsp://<notebook>:8554/cam) e o Casa Presente daqui lê esse fluxo.
#
# Rode NO COMPUTADOR que vai processar, dentro desta pasta:
#   ./scripts/migrate-to-pc.sh --notebook usuario@IP-DO-NOTEBOOK [--ssh-port 22] [--notebook-dir camera-ai] [--with-clips] [--dry-run]
#   ./scripts/migrate-to-pc.sh --notebook usuario@IP --rollback     # volta ao estado anterior
#
# Seguro por padrão: --dry-run só mostra o que faria. Os dados do notebook nunca são alterados nem apagados.
set -euo pipefail
cd "$(dirname "$0")/.."

NB=; PORT=22; NB_DIR=camera-ai; DRY=0; ROLLBACK=0; CLIPS=0; SIZE=1280x720; FPS=15
while (( $# )); do
  case "$1" in
    --notebook) NB=${2:-}; shift 2 ;;
    --ssh-port) PORT=${2:-}; shift 2 ;;
    --notebook-dir) NB_DIR=${2:-}; shift 2 ;;
    --with-clips) CLIPS=1; shift ;;
    --size) SIZE=${2:-}; shift 2 ;;
    --fps) FPS=${2:-}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --rollback) ROLLBACK=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$NB" ]] || { echo 'Informe --notebook usuario@IP.' >&2; exit 2; }
NB_HOST=${NB#*@}
STAMP=$(date +%Y%m%d-%H%M%S)
NB_PATH="\$HOME/$NB_DIR"   # caminho no notebook (expandido lá)

nb()  { ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=8 "$NB" "$@"; }
run() { if (( DRY )); then echo "[simulação] $*"; else "$@"; fi; }
nbrun() { if (( DRY )); then echo "[simulação no notebook] $*"; else nb "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
fail() { echo "Erro: $*" >&2; exit 1; }
cut_over_started=0
trap 'rc=$?; if (( rc && cut_over_started && ! ROLLBACK && ! DRY )); then echo; echo "A migração parou no meio. Para voltar ao estado anterior: ./scripts/migrate-to-pc.sh --notebook $NB --ssh-port $PORT --notebook-dir $NB_DIR --rollback" >&2; fi' EXIT

nb 'true' 2>/dev/null || fail "Não consegui entrar por SSH em $NB (porta $PORT). Teste: ssh -p $PORT $NB"

# ───────────────────────────── Reversão ─────────────────────────────
if (( ROLLBACK )); then
  say 'Reversão: o notebook volta a processar'
  prev=$(nb 'ls -1t ~/.config/mediamtx/mediamtx.yml.antes-migracao-* 2>/dev/null | head -n1' || true)
  [[ -n "$prev" ]] || echo 'Aviso: não há cópia anterior do mediamtx.yml; ele não será restaurado.' >&2
  run systemctl --user disable --now camera-ai.service || true
  [[ -z "$prev" ]] || nbrun "cp '$prev' ~/.config/mediamtx/mediamtx.yml && systemctl --user restart mediamtx.service"
  nbrun "systemctl --user enable --now camera-ai.service"
  last=$(ls -1dt data.antes-migracao-* 2>/dev/null | head -n1 || true)
  if [[ -n "$last" ]]; then
    echo "Dados deste computador anteriores à migração: $last (restaure à mão se quiser: os eventos feitos aqui depois da migração não existem no notebook)."
  fi
  say 'Feito. O notebook voltou a processar; este computador está parado.'
  exit 0
fi

# ───────────────────────────── Pré-checagem (só leitura) ─────────────────────────────
say 'Pré-checagem'
for tool in ssh rsync python3 ffprobe curl; do command -v "$tool" >/dev/null || fail "Instale o $tool neste computador."; done
[[ -x .venv/bin/python ]] || fail 'Este computador ainda não tem o Casa Presente instalado (rode ./scripts/install-server.sh).'
systemctl --user cat camera-ai.service >/dev/null 2>&1 || fail 'O serviço camera-ai não está instalado aqui (./scripts/install-server.sh).'
[[ "$(systemctl --user is-active camera-ai.service 2>/dev/null || true)" != active ]] || echo 'Aviso: o serviço já está ativo aqui; ele será reiniciado.' >&2
nb "test -d $NB_PATH/data && test -f $NB_PATH/data/settings.json" || fail "Não achei $NB_DIR/data no notebook (use --notebook-dir)."

PC_IP=$(ip route get "$NB_HOST" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
[[ -n "$PC_IP" ]] || fail 'Não consegui descobrir o IP deste computador na rede do notebook.'
echo "Este computador: $PC_IP | notebook: $NB_HOST"

pc_tok=$(sha256sum data/notebook.token 2>/dev/null | cut -c1-16 || true)
nb_tok=$(nb 'sha256sum ~/.config/casa-monitor/token 2>/dev/null | cut -c1-16' || true)
if [[ -n "$pc_tok" && "$pc_tok" == "$nb_tok" ]]; then echo 'Token do totem: igual nos dois lados.'
else echo 'Aviso: o token do totem difere. Depois da migração, pareie de novo em Configurações → Totem → Procurar totens.' >&2; fi

for p in 8554 8765; do
  timeout 3 bash -c "</dev/tcp/$NB_HOST/$p" 2>/dev/null && echo "Porta $p do notebook: aberta" || echo "Aviso: porta $p do notebook fechada agora." >&2
done

# Câmera, resolução e GPU: lidos da configuração atual do notebook (nada é presumido).
read -r WEBCAM <<<"$(nb "python3 - <<'PY'
import json,re,os
s=json.load(open(os.path.expanduser('~/$NB_DIR/data/settings.json')))['camera_source']
print(re.match(r'usb:([^?]+)',s).group(1) if s.startswith('usb:') else '')
PY")"
[[ -n "$WEBCAM" ]] || fail 'A câmera do notebook não está como USB local (usb:/dev/...): nada a migrar, ou já usa RTSP.'
echo "Webcam do notebook: $WEBCAM"
RENDER=$(nb "sed -n 's/.*-hwaccel_device \([^ ]*\) .*/\1/p' ~/.config/mediamtx/mediamtx.yml | head -n1" || true)
DRIVER=$(nb "sed -n 's/.*LIBVA_DRIVER_NAME=\([^ ]*\).*/\1/p' ~/.config/mediamtx/mediamtx.yml | head -n1" || true)
IFACE=$(nb "sed -n 's/^webrtcIPsFromInterfacesList: \[\([^,]*\),.*/\1/p' ~/.config/mediamtx/mediamtx.yml | head -n1" || true)
IFACE=${IFACE:-wlan0}
vaapi=()
if [[ -n "$RENDER" ]]; then vaapi=(--vaapi --render-node "$RENDER"); [[ -z "$DRIVER" ]] || vaapi+=(--vaapi-driver "$DRIVER"); echo "Codificação por GPU: $RENDER ${DRIVER:+(driver $DRIVER)}"
else echo 'Codificação por software (libx264): usa mais CPU do notebook.'; fi

need=$(nb "du -sk $NB_PATH/data --exclude=clips 2>/dev/null | cut -f1" || echo 0)
(( CLIPS )) && need=$(nb "du -sk $NB_PATH/data 2>/dev/null | cut -f1" || echo 0)
free=$(df -Pk . | awk 'NR==2 {print $4}')
(( free > need * 2 )) || fail "Pouco espaço livre aqui: precisa de ~$(( need * 2 / 1024 )) MB."
echo "Dados a copiar: ~$(( need / 1024 )) MB $( (( CLIPS )) && echo '(com gravações)' || echo '(sem gravações; use --with-clips para levá-las)')"

NEW_YML=$(mktemp)
python3 scripts/render_mediamtx.py --server-ip "$PC_IP" --webcam "$WEBCAM" --iface "$IFACE" "${vaapi[@]}" --size "$SIZE" --fps "$FPS" > "$NEW_YML"
echo "Novo mediamtx.yml gerado: webcam $SIZE a $FPS qps, aceitando o servidor $PC_IP."
if (( DRY )); then
  echo; echo 'Simulação: nada abaixo será executado de verdade.'
fi

# ───────────────────────────── Migração ─────────────────────────────
say '1/6 Parar o processamento no notebook (libera a webcam e fecha o banco com segurança)'
cut_over_started=1
nbrun "systemctl --user stop camera-ai.service"
nbrun "python3 -c \"import sqlite3,os;c=sqlite3.connect(os.path.expanduser('~/$NB_DIR/data/history.sqlite3'));c.execute('PRAGMA wal_checkpoint(TRUNCATE)');c.close()\""

say '2/6 Guardar os dados atuais deste computador'
if (( DRY )); then echo "[simulação] copiar data/{history.sqlite3,settings.json,people,vapid.json} para data.antes-migracao-$STAMP/"; else
  mkdir -p "data.antes-migracao-$STAMP"
  for item in history.sqlite3 history.sqlite3-wal history.sqlite3-shm settings.json people vapid.json; do [[ -e data/$item ]] && cp -a "data/$item" "data.antes-migracao-$STAMP/" || true; done
  ( umask 077; chmod 700 "data.antes-migracao-$STAMP" )
fi
run systemctl --user stop camera-ai.service

say '3/6 Trazer os dados do notebook (histórico, pessoas e rostos, configurações, chaves do push)'
items=(history.sqlite3 settings.json vapid.json people photos alerts avatars)
(( CLIPS )) && items+=(clips)
for item in "${items[@]}"; do
  if nb "test -e $NB_PATH/data/$item"; then
    run rsync -a -e "ssh -p $PORT" "$NB:$NB_DIR/data/$item" data/
  fi
done
run rm -f data/history.sqlite3-wal data/history.sqlite3-shm

say '4/6 Apontar este computador para a câmera do totem'
if (( DRY )); then echo "[simulação] settings.json: camera_source = rtsp://$NB_HOST:8554/cam; notebook_url vazio"; else
  python3 - "$NB_HOST" <<'PY'
import json, sys
path = 'data/settings.json'
s = json.load(open(path))
s['camera_source'] = f'rtsp://{sys.argv[1]}:8554/cam'
s['notebook_url'] = ''
json.dump(s, open(path, 'w'), ensure_ascii=False, indent=2)
PY
  chmod 600 data/settings.json
fi

say '5/6 MediaMTX do notebook passa a ser o único dono da webcam'
if (( DRY )); then echo "[simulação no notebook] guardar mediamtx.yml atual e instalar o novo; reiniciar o mediamtx"; else
  nb "cp ~/.config/mediamtx/mediamtx.yml ~/.config/mediamtx/mediamtx.yml.antes-migracao-$STAMP"
  scp -q -P "$PORT" "$NEW_YML" "$NB:.config/mediamtx/mediamtx.yml"
  nb 'systemctl --user restart mediamtx.service'
  echo -n 'Esperando o fluxo da câmera'
  ok=0
  for _ in $(seq 1 30); do
    if ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "rtsp://$NB_HOST:8554/cam" 2>/dev/null | grep -q h264; then ok=1; break; fi
    echo -n .; sleep 1
  done
  echo
  (( ok )) || fail "O fluxo rtsp://$NB_HOST:8554/cam não ficou disponível em 30 s (veja: ssh $NB 'journalctl --user -u mediamtx -n 30')."
  ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "rtsp://$NB_HOST:8554/cam" | sed 's/^/Fluxo: /'
fi
nbrun "systemctl --user disable camera-ai.service"

say '6/6 Iniciar o Casa Presente neste computador'
run systemctl --user enable --now camera-ai.service
if (( ! DRY )); then
  echo -n 'Esperando a câmera ficar online'
  port=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d "'\"" || true); port=${port:-8000}
  online=0
  for _ in $(seq 1 45); do
    if curl -fs "http://127.0.0.1:$port/api/health" 2>/dev/null | grep -q '"state":"online"'; then online=1; break; fi
    echo -n .; sleep 2
  done
  echo
  (( online )) || echo "Aviso: a câmera ainda não aparece online. Veja: journalctl --user -u camera-ai -n 40  (se precisar voltar: --rollback)" >&2
fi
rm -f "$NEW_YML"
cut_over_started=0

say 'Concluído'
cat <<EOF
- O processamento agora roda NESTE computador, lendo rtsp://$NB_HOST:8554/cam. O notebook só faz câmera, microfone, alto-falante e tela.
- WhatsApp: a sessão fica em data/whatsapp-auth de cada máquina e só pode existir em UMA. Leia o QR neste painel (Configurações → Avisos).
- Endereço remoto (Tailscale): o do notebook deixa de servir o painel; rode ./scripts/setup-tailscale.sh aqui e use o novo endereço no celular.
- Para desfazer: ./scripts/migrate-to-pc.sh --notebook $NB --ssh-port $PORT --notebook-dir $NB_DIR --rollback
EOF
