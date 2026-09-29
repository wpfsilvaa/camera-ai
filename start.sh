#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
# The systemd service runs this same script; allow its own MainPID through.
if command -v systemctl >/dev/null; then
  service_pid=$(systemctl --user show camera-ai.service --property=MainPID --value 2>/dev/null || true)
  if [[ "$service_pid" =~ ^[0-9]+$ ]] && (( service_pid > 0 && service_pid != $$ )); then
    echo 'Casa Presente já está rodando pelo serviço automático.'
    echo 'Reiniciar: systemctl --user restart camera-ai.service'
    echo 'Executar manualmente: systemctl --user stop camera-ai.service; ./start.sh'
    exit 0
  fi
fi
if command -v flock >/dev/null; then
  mkdir -p data
  exec 9>data/start.lock
  if ! flock -n 9; then
    echo 'Casa Presente já possui uma instância iniciada nesta pasta.' >&2
    exit 1
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Crie a .venv e instale requirements.txt antes de iniciar.' >&2
  exit 1
fi
if [[ ! -d node_modules/@whiskeysockets/baileys ]]; then
  echo 'Execute npm ci antes de iniciar.' >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null; then
  echo 'Instale o FFmpeg antes de iniciar.' >&2
  exit 1
fi
children=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${children[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${children[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
node whatsapp/server.mjs &
children+=("$!")
.venv/bin/python -m app.run &
children+=("$!")
wait -n "${children[@]}"
