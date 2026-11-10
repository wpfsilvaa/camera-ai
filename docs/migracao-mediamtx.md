# Migrar o processamento para o servidor (câmera só pelo MediaMTX)

Antes: o app roda no notebook e lê a webcam por USB (`usb:/dev/v4l/by-id/...`). Depois: o notebook só publica câmera, microfone e
alto-falante (MediaMTX) e exibe o totem; o computador servidor processa tudo lendo `rtsp://<notebook>:8554/cam`.

## Como fazer
No computador servidor, dentro da pasta do projeto:

```bash
./scripts/migrate-to-pc.sh --notebook usuario@IP-DO-NOTEBOOK --ssh-port 2222 --notebook-dir camera-ai-test --dry-run   # só mostra
./scripts/migrate-to-pc.sh --notebook usuario@IP-DO-NOTEBOOK --ssh-port 2222 --notebook-dir camera-ai-test             # executa (~5 min)
./scripts/migrate-to-pc.sh --notebook usuario@IP-DO-NOTEBOOK --ssh-port 2222 --notebook-dir camera-ai-test --rollback  # desfaz
```

O script lê a câmera, a GPU e a interface do notebook, gera o `mediamtx.yml` (720p a 15 quadros, igual ao que a análise usa hoje),
para o app do notebook, traz histórico, rostos, configurações e chaves do push, inicia o app no servidor e espera a câmera ficar online.
Os dados do notebook nunca são alterados. Use `--with-clips` para levar também as gravações (cerca de 500 MB).

## Depois
- **WhatsApp:** só pode haver uma sessão. Leia o QR no painel do servidor (Configurações → Avisos).
- **Acesso remoto:** rode `./scripts/setup-tailscale.sh` no servidor e passe o novo endereço aos celulares.
- **CPU:** a codificação por GPU do notebook custou cerca de 11% de um núcleo a 720p/15 (teste com a webcam HP).
