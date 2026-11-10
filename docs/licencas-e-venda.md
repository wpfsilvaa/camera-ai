# Licenças e venda — o que precisa ser decidido

Este documento resume os pontos jurídicos e de dependência que bloqueiam a venda. Não é aconselhamento jurídico: leve-o a um advogado.

## 1. Ultralytics / YOLO (AGPL-3.0) — bloqueador
O detector (`ultralytics`) e os pesos `yolo26*.pt/.onnx` são AGPL-3.0. Vender ou entregar o software (ou oferecê-lo por rede) obriga a
oferecer o código-fonte completo, sob AGPL, a quem o receber. Saídas:
1. **Licença Enterprise da Ultralytics** (paga): permite manter o produto fechado. Peça orçamento.
2. **Trocar o detector** por um de licença permissiva (por exemplo YOLOX, RT-DETR/D-FINE ou MediaPipe) e refazer o ReID. Exige reavaliar precisão e desempenho (`docs/cpu-capacity.md`).
3. **Publicar tudo como AGPL** e vender serviço/instalação/suporte em vez de licença.

## 2. WhatsApp (Baileys, não oficial) — bloqueador
Automatizar uma conta pessoal pelo protocolo não oficial viola os termos do WhatsApp e pode banir o número do cliente. Para vender:
use a WhatsApp Business Cloud API (oficial, paga por conversa) ou ofereça push e Telegram como canal padrão, deixando o Baileys
apenas como opção avisada.

## 3. Clima (Open-Meteo)
A API gratuita é só para uso não comercial. Em instalações vendidas, contrate o plano comercial e defina `OPEN_METEO_API_KEY` no `.env`
(o código passa a usar os endereços `customer-*`), ou desative o clima do totem.

## 4. LGPD e biometria — bloqueador (fase 2)
Rostos são dados pessoais sensíveis. É preciso consentimento registrado, termo e política de privacidade, RIPD, criptografia em repouso
e fluxo de apagamento. Está no plano, fase 2.

## 5. Outros
- Contato do responsável pelo push: defina `PUSH_CONTACT` no `.env` (padrão é um e-mail de exemplo).
- Defina a licença do produto no arquivo `LICENSE` depois de decidir o item 1.
