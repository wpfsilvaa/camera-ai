#!/usr/bin/env bash
# Instala o Casa Presente neste computador (o "servidor" do painel): ambiente Python, Node, modelos, serviço automático.
# Uso: ./scripts/install-server.sh [--no-service] [--dry-run]
# É seguro rodar de novo: só completa o que falta.
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE=1; DRY=0
for arg in "$@"; do
  case "$arg" in
    --no-service) SERVICE=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
  esac
done
run() { if (( DRY )); then echo "[simulação] $*"; else "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
fail() { echo "Erro: $*" >&2; exit 1; }

[[ "$(uname -s)" == Linux ]] || fail 'Só há suporte a Linux de 64 bits (x86-64).'
[[ "$(uname -m)" == x86_64 ]] || fail "Arquitetura $(uname -m) ainda não suportada (precisa de x86-64)."
command -v python3 >/dev/null || fail 'Instale o Python 3.11 ou mais novo (ex.: sudo apt install python3 python3-venv).'
python3 - <<'PY' || fail 'O Python precisa ser 3.11 ou mais novo.'
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
python3 -c 'import venv, ensurepip' 2>/dev/null || fail 'Falta o módulo venv (ex.: sudo apt install python3-venv).'
command -v node >/dev/null || fail 'Instale o Node.js 22 ou mais novo (https://nodejs.org).'
(( $(node -p 'process.versions.node.split(".")[0]') >= 22 )) || fail 'O Node.js precisa ser 22 ou mais novo.'
command -v ffmpeg >/dev/null || fail 'Instale o FFmpeg com libx264 (ex.: sudo apt install ffmpeg).'
encoders=$(ffmpeg -hide_banner -encoders 2>/dev/null || true)
grep -q libx264 <<<"$encoders" || fail 'Seu FFmpeg não tem libx264. Instale a versão completa do FFmpeg.'
free_gb=$(df -Pk . | awk 'NR==2 {printf "%d", $4/1024/1024}')
(( free_gb >= 10 )) || echo "Aviso: só há ${free_gb} GB livres aqui; recomenda-se 10 GB ou mais (modelos + gravações)." >&2

say 'Ambiente Python'
[[ -x .venv/bin/python ]] || run python3 -m venv .venv
run .venv/bin/python -m pip install --quiet --upgrade pip
run .venv/bin/python -m pip install --quiet -r requirements.txt

say 'Modelos de reconhecimento (verificados por SHA-256)'
run .venv/bin/python scripts/download_models.py

say 'Gateway do WhatsApp'
run npm ci --no-audit --no-fund

say 'Configuração'
if [[ ! -f .env ]]; then run cp .env.example .env; echo '.env criado.'; fi
if [[ ! -s data/notebook.token ]]; then
  run mkdir -p data
  if (( ! DRY )); then
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > data/notebook.token
  fi
  echo 'Token do totem criado em data/notebook.token (use no instalador do notebook da cozinha).'
fi

if (( SERVICE )); then
  say 'Serviço automático (inicia com o computador)'
  if command -v systemctl >/dev/null; then
    unit_dir="$HOME/.config/systemd/user"
    run mkdir -p "$unit_dir"
    # O serviço procura o programa em %h/camera-ai; ajusta se a pasta tiver outro nome ou lugar.
    if (( DRY )); then echo "[simulação] gerar $unit_dir/camera-ai.service para $PWD"; else
      sed "s#%h/camera-ai#$PWD#g" deploy/camera-ai.service > "$unit_dir/camera-ai.service"
    fi
    run systemctl --user daemon-reload
    run systemctl --user enable --now camera-ai.service
    command -v loginctl >/dev/null && run loginctl enable-linger "$USER" || true
  else
    echo 'systemd não encontrado: inicie com ./start.sh'
  fi
fi

port=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d "'\"" || true); port=${port:-8000}
say 'Pronto'
cat <<EOF
Abra no navegador DESTE computador:  http://127.0.0.1:${port}
O assistente de primeira configuração guia: quem é acompanhado, câmera, WhatsApp e senha do administrador.

Para ver no celular de qualquer lugar: ./scripts/setup-tailscale.sh
Para o totem da cozinha (outro notebook): scripts/install-totem.sh --server-ip <IP deste computador>
   e depois, no painel, Configurações → Totem → Procurar totens (o notebook mostra um código na tela).
EOF
