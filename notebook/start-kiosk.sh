#!/usr/bin/env bash
# Abre a tela de chamada da família em tela cheia. Chame no início da sessão (ex.: exec-once do Hyprland).
for b in google-chrome-stable google-chrome chromium chromium-browser; do
  if command -v "$b" >/dev/null; then BROWSER=$b; break; fi
done
[[ -n "${BROWSER:-}" ]] || { echo 'Instale o Google Chrome ou o Chromium.' >&2; exit 1; }
exec "$BROWSER" --app=http://127.0.0.1:8765/ --start-fullscreen --user-data-dir="$HOME/.config/casa-kiosk" \
  --no-first-run --disable-features=Translate --autoplay-policy=no-user-gesture-required
