#!/usr/bin/env bash
# Abre a tela de chamada da família em tela cheia. Chame no início da sessão (ex.: exec-once do Hyprland).
exec google-chrome-stable --app=http://127.0.0.1:8765/ --start-fullscreen --user-data-dir="$HOME/.config/casa-kiosk" \
  --no-first-run --disable-features=Translate --autoplay-policy=no-user-gesture-required
