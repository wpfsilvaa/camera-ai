#!/usr/bin/env bash
# Opens the dashboard to the family's phones through Tailscale, with HTTPS and without
# opening any router port. Run once on the house computer: ./scripts/setup-tailscale.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d "\"' " || true); PORT=${PORT:-8000}

if ! command -v tailscale >/dev/null; then
  echo 'Tailscale não está instalado. No Arch Linux:'
  echo '  sudo pacman -S tailscale && sudo systemctl enable --now tailscaled'
  echo 'Outras distribuições: curl -fsSL https://tailscale.com/install.sh | sh'
  exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
  echo 'Entrando na sua conta Tailscale (abra o link que aparecer)…'
  sudo tailscale up
fi

# HTTPS on the tailnet name; certificates come from Tailscale (enable HTTPS in the admin console if asked).
sudo tailscale serve --bg --https=443 "http://127.0.0.1:${PORT}"
NAME=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
URL="https://${NAME}"

# Let the dashboard accept requests from that address.
touch .env
if grep -q '^PUBLIC_URL=' .env; then sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=${URL}|" .env; else echo "PUBLIC_URL=${URL}" >> .env; fi

read -r -p 'Aceitar acesso ao painel somente pelo Tailscale (recomendado)? [S/n] ' answer
if [[ ! "$answer" =~ ^[nN] ]]; then
  if grep -q '^HOST=' .env; then sed -i 's|^HOST=.*|HOST=127.0.0.1|' .env; else echo 'HOST=127.0.0.1' >> .env; fi
  echo 'O painel passa a escutar só neste computador; a rede local também deve usar o endereço do Tailscale.'
fi

cat <<INFO

Pronto. Endereço do painel: ${URL}

Nos celulares da família:
  1. Instale o app Tailscale (Play Store / App Store) e entre com a mesma conta,
     ou aceite o convite enviado pelo painel de administração do Tailscale.
  2. Abra ${URL} e entre com o próprio usuário e senha do Casa Presente.
  3. Menu do navegador → "Instalar app" / "Adicionar à tela de início".
  4. Em "Minha conta", toque em "Ativar notificações".

Reinicie o serviço para aplicar: systemctl --user restart camera-ai.service
INFO
