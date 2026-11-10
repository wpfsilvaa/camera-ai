#!/usr/bin/env bash
# Abre a tela de chamada da família em tela cheia. Chame no início da sessão (ex.: exec-once do Hyprland).
# Opcional: ~/.config/casa-monitor/kiosk.env com variáveis para o navegador (ex.: LIBVA_DRIVER_NAME=i965 em Intel antiga).
[[ -f "$HOME/.config/casa-monitor/kiosk.env" ]] && set -a && . "$HOME/.config/casa-monitor/kiosk.env" && set +a
for b in google-chrome-stable google-chrome chromium chromium-browser; do
  if command -v "$b" >/dev/null; then BROWSER=$b; break; fi
done
[[ -n "${BROWSER:-}" ]] || { echo 'Instale o Google Chrome ou o Chromium.' >&2; exit 1; }
# Em sessão Wayland usa Wayland (com DISPLAY também definido, "auto" escolheria o X11 e falhava por autorização).
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then OZONE=--ozone-platform=wayland; else OZONE=--ozone-platform-hint=auto; fi
# Sem IA local, sincronização nem rede em segundo plano: o totem só precisa da própria página (mede ~10% menos CPU).
exec "$BROWSER" "$OZONE" --app=http://127.0.0.1:8765/ --start-fullscreen --user-data-dir="$HOME/.config/casa-kiosk" \
  --no-first-run --no-default-browser-check --autoplay-policy=no-user-gesture-required \
  --disable-features=Translate,OptimizationHints,OptimizationGuideModelExecution,OptimizationGuideOnDeviceModel,OnDeviceModelService,SegmentationPlatform,HistoryEmbeddings,MediaRouter,DialMediaRouteProvider,GlobalMediaControls,SafeBrowsingEnhancedProtection,CertificateTransparencyComponentUpdater \
  --disable-extensions --disable-component-extensions-with-background-pages --disable-default-apps \
  --disable-background-networking --disable-component-update --disable-sync --disable-breakpad --disable-crash-reporter \
  --disable-domain-reliability --disable-client-side-phishing-detection --disable-print-preview --disable-speech-api \
  --no-pings --metrics-recording-only --renderer-process-limit=1
