# Casa Presente

Monitoramento local com **YOLO26**, reconhecimento facial de várias pessoas por exemplos confirmados, gravação por presença, dashboard em português e envio pelo **Baileys**.

## Iniciar

As dependências já estão instaladas neste ambiente. Na pasta do projeto:

```bash
./start.sh
```

Abra **http://localhost:8000**. O script inicia a API Python e o serviço Node do WhatsApp; `Ctrl+C` encerra os dois. Execute apenas uma instância, com um único worker Python.

Para instalar em outro ambiente: Python 3.11 ou superior, Node 22 ou superior, FFmpeg com `libx264` e o modelo `yolo26n.pt` nesta pasta. Os modelos faciais YuNet e SFace e o modelo corporal YOLO26 ReID são baixados pelo script abaixo, com verificação SHA-256.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/download_models.py
npm ci
cp .env.example .env
./start.sh
```

Os modelos locais são usados diretamente; a aplicação não baixa pesos ao iniciar. Se o modelo facial estiver ausente, detecção e gravação continuam e o painel informa a falha no reconhecimento.

## Configurar e usar

1. Em **Configurações**, confira a câmera: `rtsp://192.168.1.103:8554/cam`. O computador precisa alcançar o notebook da cozinha pela rede local.
2. Clique em **Iniciar câmera** na visão geral. A transmissão MJPEG acompanha as detecções continuamente, com caixas e nomes. O painel mostra os quadros por segundo e o dispositivo de inferência.
3. Clique em **Conectar WhatsApp**. No celular, abra **Dispositivos conectados → Conectar dispositivo** e escaneie o QR code do painel.
4. Em **Configurações**, informe o número de destino com DDI e DDD, por exemplo `5511999999999`, e habilite **Enviar vídeos pelo WhatsApp**.
5. Em **Pessoas**, cadastre quem aparece na casa. O perfil **Meu pai** já existe e pode ser renomeado. Clique em **Cadastrar foto do rosto → Escolher foto**, arraste sobre a imagem para recortar uma pessoa e confirme em **Salvar rosto**. Use fotos nítidas e inclua o rosto inteiro com uma margem. Repita com alguns ângulos e condições de luz da câmera.
6. Abra um registro encerrado no **Histórico**. Cada pessoa rastreada tem suas próprias imagens. Selecione uma imagem nítida, escolha o nome e clique em **Confirmar e ensinar**. Só a imagem selecionada vira exemplo; repita para adicionar outros ângulos.
7. Com **Somente meu pai** habilitado, a confirmação da presença dele libera os vídeos do registro. A opção **Enviar também prováveis registros do pai**, inicialmente desativada, permite enviar estimativas por reconhecimento facial e pode enviar a pessoa errada; a legenda indica “provável”.

Se desabilitar **Somente meu pai**, todos os registros de pessoas poderão ser enviados automaticamente. Essa opção também libera os registros antigos ainda na fila e dentro do prazo de armazenamento.

## O que é contado

- Um registro é um **período contínuo com alguma pessoa na imagem**, não uma pessoa única, identidade ou visitante.
- Por padrão, exige 1 segundo de detecções consecutivas para iniciar a gravação e encerra após 8 segundos sem detectar ninguém. A gravação começa depois dessa confirmação inicial; não há pré-gravação.
- Quando uma pessoa sai e outra permanece, o mesmo registro continua. Entradas e saídas fora do campo da câmera não são contadas.
- Presenças longas são divididas em partes de 60 segundos, sem criar novas visitas. O envio de cada parte pode ocorrer assim que ela fica pronta, se o filtro de identidade permitir.
- A confirmação de identidade fica disponível **após encerrar o registro**. No modo “Somente meu pai”, as partes aguardam essa confirmação, a menos que o envio por identidade provável esteja habilitado.
- “Registros do pai” mostra os períodos iniciados hoje e confirmados manualmente. “A identificar” mostra os períodos iniciados hoje ainda sem identificação. Datas e gráficos usam `America/Sao_Paulo`.

## Reconhecimento facial e tracking

YOLO26 detecta pessoas, ByteTrack acompanha cada corpo e YuNet encontra o rosto.
O rosto é alinhado pelos olhos, nariz e boca; SFace produz um embedding (vetor)
comparado às referências que você confirmou. Todo o processamento fica local.

- Cadastre fotos em **Pessoas** ou confirme rostos nítidos no **Histórico**. Uma referência já permite comparação; variedade de ângulos e luz melhora a cobertura. Fotos aceitas: até 8 MB e 16 megapixels, um rosto adequado por imagem.
- O limite inicial de semelhança é **0,50**, com margem **0,08** sobre o segundo perfil e três comparações concordantes. Sem confiança suficiente, a pessoa aparece como **Desconhecido**. Semelhança não é probabilidade de acerto; avalie os limites na sua câmera.
- As caixas mostram o nome depois da identificação facial. Quando o rosto vira, o tracking segura o nome por até 15 segundos por padrão (ajustável nas configurações); a memória corporal descrita abaixo pode continuar reconhecendo a aparência. O nome mantido aparece como “tracking”; não é uma nova confirmação facial. Perder a detecção do track ou encontrar um rosto conflitante limpa o nome. Trocas de track e oclusões podem causar erros.
- Várias pessoas podem ter nomes simultaneamente. Faces com associação ambígua ao corpo não são usadas; dois tracks sugerindo o mesmo perfil têm os nomes suspensos.
- Rostos menores que 40 pixels, com olhos muito próximos ou pouca nitidez são descartados. Uma câmera Full HD pode ajudar, mas distância, enquadramento e luz determinam os detalhes que chegam ao detector.
- **A galeria permanente de rostos só aprende com você.** Só fotos cadastradas e imagens confirmadas entram nessa galeria. São até 30 fotos enviadas e 100 exemplos confirmados por perfil; coleta até 12 rostos por track, espaçados em 2 segundos.
- As referências antigas do corpo não alimentam a comparação facial. O histórico fica preservado; cadastre fotos do rosto para começar esta versão.
- “Esquecer exemplos” remove as referências, preservando confirmações históricas. Excluir outro perfil remove também suas associações. O perfil reservado ao pai pode ser renomeado.
- Fotos cadastradas e exemplos confirmados ficam locais até remoção ou substituição pelo limite. Amostras sem confirmação seguem a retenção configurada. Imagens e embeddings ficam em `data/people/` e SQLite.

Os nomes são desenhados **antes da gravação**, portanto aparecem também no MP4 enviado.
O cadastro ou a correção posterior não altera o texto de vídeos já gravados.

Documentação: [YuNet e SFace no OpenCV](https://docs.opencv.org/4.13.0/d0/dd4/tutorial_dnn_face.html),
[YOLO](https://docs.ultralytics.com/modes/predict/) e [ByteTrack](https://docs.ultralytics.com/modes/track/).

## Revisar e remover exemplos individuais

Em **Pessoas**, clique em **Revisar exemplos** no perfil desejado. A galeria reúne
as fotos cadastradas e as imagens ensinadas no Histórico. Clique numa imagem para
ampliar; filtre pela origem ou escolha **Menor nitidez primeiro** para encontrar
possíveis fotos ruins. O índice de nitidez serve para ordenar, não mede a precisão
do reconhecimento.

Use **Remover do aprendizado** para retirar apenas aquela referência. A base facial
e a memória corporal são invalidadas imediatamente. Exemplos do Histórico continuam
no registro, com o vídeo e a identidade confirmada preservados; podem ser ensinados
novamente por uma confirmação explícita. Fotos enviadas pelo cadastro são excluídas.

Os limites são exibidos separadamente: **100 exemplos do Histórico** e **30 fotos
cadastradas** por pessoa. Remover um exemplo libera espaço no respectivo limite.

## Reconhecer novamente pelo corpo e pela roupa

Com **Lembrar pelo corpo e pela roupa** ativado (padrão), três comparações faciais
concordantes autorizam guardar a aparência corporal daquela pessoa. O modelo local
`yolo26n-reid.onnx` gera um embedding do corpo, com a região superior mascarada para
reduzir a influência do rosto. YOLO usa o dispositivo escolhido em cada câmera; a
comparação corporal roda na CPU em uma tarefa separada da captura.

Quando a pessoa sai e volta, mesmo com outro número de rastreamento e sem rosto
visível, três comparações corporais concordantes podem recuperar seu nome. O vídeo
ao vivo e o MP4 mostram **“Nome · #número · corpo/roupa”** em uma caixa âmbar. O
Histórico marca a sugestão como **“Provável Nome (corpo/roupa)”**.

- A memória dura **30 minutos**, ajustáveis de 1 a 240 em **Configurações**. O prazo
  conta desde a referência obtida com rosto reconhecido; acertos só pela roupa não
  ensinam novas referências nem prolongam sua validade.
- As referências sobrevivem à saída do campo de visão e ao fim de um registro.
  Ficam apenas na memória do processo, até expirar, reiniciar/reconectar a câmera,
  alterar as configurações de reconhecimento ou modificar os cadastros.
- São guardadas até 24 referências por pessoa: 12 associadas ao rosto no mesmo
  quadro e 12 de outros ângulos durante a continuidade do track. Após reconhecer
  o rosto, a coleta desses ângulos dura no máximo 10 segundos sem nova confirmação
  facial. Perda de track, sobreposição de pessoas, salto de posição ou rosto
  conflitante interrompem essa coleta. Os ângulos adicionais expiram contando
  desde o rosto que os autorizou; não estendem a validade da memória.
- A comparação usa a média normalizada de até cinco observações recentes de cada
  track, tanto nas referências quanto na volta. Perder o track ou ficar mais de
  1,5 segundo sem comparação descarta essa média. Corpos muito pequenos ou
  bastante sobrepostos não são comparados.
- Após três comparações concordantes, oscilações pequenas podem manter o nome
  pelo tracking por até 3 segundos. Uma aparência diferente ou ambígua limpa essa
  continuidade. Um novo track continua exigindo três comparações para entrar.
  A caixa mostra “corpo/roupa · tracking” quando mantém uma sugestão anterior.
- A revisão do histórico mostra também o diagnóstico corporal: memória ausente,
  semelhança insuficiente, candidatos ambíguos, coleta de ângulo ou reconhecimento.
- O limite corporal padrão é 0,85, ajustável no painel entre 0,70 e 0,99.
  Reduzir o limite aceita mais variações de ângulo e iluminação, mas pode confundir
  pessoas com aparência parecida. Exige margem de 0,08 entre identidades e três
  observações concordantes. Um rosto visível tem prioridade. Roupas parecidas,
  mudanças de roupa, ângulo e luz podem causar desconhecidos ou erros; isso é uma
  estimativa de aparência, não confirmação de identidade.
- O envio automático de prováveis registros do pai mantém o filtro facial
  existente. Um novo registro identificado apenas pelo corpo aguarda confirmação
  manual para ser enviado no modo **Somente meu pai**.

O modelo é publicado pelo [Ultralytics para ReID](https://docs.ultralytics.com/modes/track/#enabling-re-identification-reid).
`tests/body_pipeline.py` verifica com modelos reais: rosto conhecido, saída completa,
novo registro, retorno com o rosto coberto, novo número de track e nome corporal
no MP4. Usa uma foto de teste com movimento simulado; não estima acurácia na casa.

## Jogar mantendo o vídeo no segundo monitor

Na visão geral, **Pausar análise** desliga YOLO, tracking e reconhecimento facial e
corporal, mantendo a câmera e a transmissão ao vivo. O modelo YOLO é descarregado;
o contexto CUDA pode manter uma pequena reserva de memória. Captura, exibição e
gravação continuam usando CPU. **Retomar análise** carrega novamente os modelos.
A pausa é mantida após reiniciar o serviço. **Tela cheia** amplia o vídeo e os
controles no monitor escolhido. **Pausar câmera** encerra também a transmissão.

### Gravar manualmente e identificar depois

1. Clique em **Gravar manualmente**, mesmo com a análise pausada.
2. Clique em **Parar gravação manual**. O vídeo fica no **Histórico**, marcado como
   gravação manual, e precisa terminar a conversão para MP4.
3. Abra o registro e clique em **Analisar vídeo**. O processamento usa YOLO e as
   referências faciais atuais; pode consumir GPU mesmo com a análise ao vivo pausada.
4. Acompanhe o progresso ou use **Cancelar análise**. Ao concluir, o painel mostra
   a cópia com caixas/nomes e as pessoas detectadas para revisão e confirmação.

A gravação manual continua durante pausa/retomada da análise, termina ao parar a
câmera ou perder o sinal e é dividida em partes conforme a duração configurada.
Enquanto ela está ativa, a gravação automática por presença fica suspensa para
não gerar arquivos duplicados. Registros manuais não contam como visitas detectadas.

O original é preservado; a cópia identificada tem sufixo `.analyzed.mp4`. Ambas
seguem a retenção configurada. A fila de WhatsApp aguarda revisão manual desses
registros e continua enviando o arquivo original conforme os filtros de envio.
Confirmar somente um vídeo sem rostos detectados não cria exemplos faciais.

Há uma análise posterior por vez, iniciada apenas por pedido no painel. Cancelar
libera o processo e permite tentar novamente. **Pausar análise** também cancela
uma análise posterior da mesma câmera em andamento; se a análise ao vivo já estiver pausada, use
**Cancelar análise do vídeo**. Ao reiniciar o serviço, uma análise interrompida
não recomeça automaticamente. Os resultados incompletos não podem ser ensinados.

Validação: `tests/manual_pipeline.py` exercita pausa/retomada, vídeo contínuo,
gravação, liberação dos pesos na GPU, cancelamento/repetição e análise facial real.
`tests/manual-ui-smoke.mjs` cobre os botões, tela cheia e reprodução do resultado.
Os testes usam dados temporários e não enviam mensagens.

## Vídeo e RTX 2060

Em **Configurações**, “Auto” seleciona CUDA se disponível. A inferência YOLO usa FP16
na GPU, com entrada de detecção de 640 pixels. Os rostos são recortados da resolução
original e processados separadamente, sem formar fila de frames antigos.

A gravação preserva até 1920 pixels de largura e a prévia usa até 1280. O limite
padrão é 30 quadros por segundo. Isso depende da câmera e da máquina: o painel mostra
a taxa processada, que pode ser menor. A latência exibida mede a partir da leitura
local do frame, sem incluir o atraso que já vem da câmera ou da rede.

O teste controlado `tests/full_pipeline.py` usa uma foto com duas pessoas, movimento
e iluminação simulados em 1920×1080/30 qps. Na RTX 2060 deste computador, mediu
mediana de 29,7 qps e 9,7 ms de inferência, com nomes no vídeo e rejeição de uma face
não cadastrada. Isso verifica integração e desempenho; não mede precisão em
filmagens reais da casa. O relatório fica em `test-results/full-pipeline.json`.

A câmera RTSP configurada foi medida em **1920×1080 a 15 qps**; o processamento
ficou em cerca de **14,3 qps**. Para obter 30 qps de movimento real, a origem RTSP
precisa transmitir nessa taxa.

## Gravação e envio

- MP4/H.264, sem áudio, até 1920 pixels de largura. Padrão: 30 quadros por segundo. Se a inferência ficar lenta, o último quadro é repetido para preservar a duração; isso não recupera movimento perdido.
- A leitura do vídeo ao vivo roda separadamente da inferência, descartando frames antigos para evitar acúmulo de atraso.
- SQLite armazena os registros, segmentos e estados de envio. Após uma interrupção, fecha registros abertos, tenta converter vídeos temporários e sinaliza envios sem confirmação.
- Quando o WhatsApp está desconectado, os vídeos aguardam. A reconexão de uma sessão pareada é automática.
- Há um comprovante local de cada envio confirmado para reduzir duplicações. Um timeout durante upload vira **Conferir envio**: verifique o WhatsApp antes de usar **Tentar envio novamente**. Não é possível garantir envio exatamente uma vez quando a conexão cai entre o upload e a confirmação.
- “Enviado” significa que o Baileys retornou um identificador de mensagem; não significa que o destinatário leu ou recebeu o vídeo no aparelho.
- Vídeos e miniaturas expiram após **7 dias**, inclusive os não enviados. O prazo é configurável, a limpeza roda a cada hora e preserva registros ainda ativos. O histórico permanece.
- A gravação para com um erro visível se houver menos de 512 MB livres. Erros de gravação ou conexão não são tratados como ausência confirmada.

O [Baileys](https://github.com/WhiskeySockets/Baileys) é uma integração não oficial do WhatsApp. A versão está fixada no `package-lock.json`; mudanças do WhatsApp podem exigir atualização. Sessão e chaves ficam locais em `data/whatsapp-auth/`.

## Acesso e arquivos

Neste computador, o `.env` já está configurado para a rede local com senha. Em uma instalação nova, o painel escuta apenas em `127.0.0.1:8000`. Para acessar de outro dispositivo na sua rede, defina `HOST=0.0.0.0` no `.env` depois de criar um usuário. Para acesso pela internet, use VPN ou um proxy com HTTPS; a aplicação não configura isso automaticamente.

### Usuários e login

O painel usa uma tela de login com usuário e senha, e cada pessoa tem sua própria conta.

- **Administrador** altera tudo: câmeras, WhatsApp, pessoas, registros e usuários.
- **Família** vê o ao vivo, o histórico e os vídeos, sem alterar nada. Não vê o endereço da câmera, os números do WhatsApp nem o QR code de pareamento.
- Sem nenhum usuário, o painel fica aberto no próprio computador. Abra **Usuários** e crie o primeiro administrador; a partir daí o login é obrigatório.
- Se o `.env` tiver `DASHBOARD_PASSWORD` (configuração antiga), a primeira execução cria o usuário `admin` com essa senha. Troque a senha em **Minha conta** (botão com seu nome, no topo) e remova a variável do `.env`.
- Senhas usam scrypt; a sessão é um cookie `HttpOnly` e `SameSite=Strict`, válido por 12 horas ou 30 dias com “Manter conectado”. Cinco senhas erradas bloqueiam novas tentativas daquele endereço por 15 minutos.
- Redefinir a senha ou mudar o perfil de alguém desconecta os outros aparelhos dessa conta.

O gateway Baileys só escuta em `127.0.0.1:3001`, com token interno. QR code, gravações e APIs ficam sob a mesma proteção do painel. Não exponha essa porta externamente.

```text
app/main.py           Aplicação, proteção das rotas, câmeras, histórico e mídia
app/routes/           Rotas de login/usuários, pessoas e alertas
app/alerts.py         Alertas de ausência, câmera sem imagem e resumo diário
app/jobs.py           Conversão de vídeos, limpeza e filas do WhatsApp
app/                  Detecção, reconhecimento, gravação e banco de dados
static/               Dashboard sem dependências externas de frontend
whatsapp/             Integração Baileys e comprovantes de envio
tests/                Testes de presença, armazenamento, API e navegador
data/settings.json    Configurações salvas no painel
data/history.sqlite3  Histórico e fila persistente
data/clips/           Gravações e miniaturas
data/people/          Imagens individuais usadas na revisão e no aprendizado
data/whatsapp-auth/   Credenciais da sessão do WhatsApp
```

`data/`, `.env`, gravações e modelos estão no `.gitignore`. Não compartilhe a pasta de sessão do WhatsApp. O serviço deve permanecer aberto, o computador ligado e a câmera transmitindo.

**O sistema acompanha presença. Não detecta emergências, quedas ou problemas de saúde, nem confirma que seu pai está bem.**

## Alertas no WhatsApp

Em **Configurações → 05 · Alertas no WhatsApp**, ative **Enviar alertas**. As mensagens de texto vão para o número principal e para os familiares cadastrados.

- **Ninguém apareceu:** avisa quando nenhuma pessoa é vista pelas câmeras há X horas (padrão 4; 0 desativa). Só conta com alguma câmera ligada e analisando. Não envia durante o silêncio noturno (padrão 22:00–07:00). Há um aviso por período de ausência.
- **Câmera sem imagem:** avisa quando uma câmera ligada fica sem imagem por X minutos (padrão 10; 0 desativa) e avisa de novo quando ela volta. Câmeras pausadas por você não geram aviso.
- **Resumo do dia:** no horário escolhido (padrão 21:00), envia os registros do dia, confirmados como pai, a identificar, última presença e tempo gravado.
- **Enviar alerta de teste** confirma que números e WhatsApp estão funcionando. Os últimos alertas aparecem na visão geral, com o estado de envio.

Alertas que não puderem ser enviados em até 6 horas expiram, para não chegar uma informação desatualizada. O gateway não repete a mesma mensagem para o mesmo número, mesmo após reinícios. Um alerta ajuda a perceber uma rotina diferente, mas não é um sistema de emergência.

### Espaço em disco e monitoramento

- Com menos espaço livre que o mínimo configurado (padrão 2 GB), os vídeos mais antigos de registros encerrados são apagados antes do prazo, para as gravações não pararem. O histórico permanece.
- `GET /api/health` responde sem login, sem dados pessoais: `ok`, estado do WhatsApp, espaço livre e estado de cada câmera. Retorna 503 quando uma câmera ligada está sem imagem ou o disco está abaixo do mínimo. Útil para um monitor externo como Uptime Kuma.
- Logs com data e hora aparecem no terminal ou em `journalctl --user -u camera-ai.service`. Ajuste com `LOG_LEVEL=DEBUG` no `.env`.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -v
npm test
PYTHONPATH=. .venv/bin/python tests/full_pipeline.py
PYTHONPATH=. .venv/bin/python tests/body_pipeline.py
node tests/people-ui-smoke.mjs
node tests/login-ui-smoke.mjs
node tests/multi-recipient-gateway.mjs
```

Os testes Python usam uma pasta temporária e um WhatsApp simulado; não enviam mensagens reais. Verificam duração e segmentação de vídeos, recuperação de interrupções, retenção, filtro do pai, timeout de envio, validação da API e proteção das rotas.

O teste `full_pipeline.py` exige CUDA e valida YOLO, reconhecimento de duas faces, desconhecido, segmentação, MP4 Full HD e desempenho. Usa dados temporários e salva um vídeo demonstrativo em `test-results/face-recorded.mp4`.

Testes opcionais com o sistema em execução:

```bash
npm install --no-save --package-lock=false playwright
node tests/ui-smoke.mjs
node tests/live-smoke.mjs
node tests/people-ui-smoke.mjs
```

O teste de interface usa Chrome em `/opt/google/chrome/chrome` (ajustável por `CHROME_PATH`) e salva capturas em `test-results/`. O teste ao vivo **inicia e mantém o monitoramento da câmera configurada**. Não há envio automático sem destinatário, sessão conectada e habilitação no painel.

O teste `people-ui-smoke.mjs` usa um servidor temporário separado para validar cadastro por foto real, confirmação de duas pessoas no mesmo registro, aprendizado, esquecimento, exclusão e transmissão MJPEG no navegador em tela móvel. Não altera o seu histórico. Os testes de reconhecimento também verificam rejeição de ambiguidades, correção de exemplos, compatibilidade do modelo e envio opcional de estimativas.

## Diagnóstico rápido

- **Sem sinal:** confira se o RTSP está ativo e se os computadores estão na mesma rede. A captura tenta reconectar a cada 5 segundos.
- **Sem registros:** verifique a imagem, iluminação, sensibilidade e se a pessoa permanece visível por tempo suficiente.
- **Aguardando identificação:** revise um registro já encerrado e confirme quem apareceu.
- **WhatsApp indisponível:** inicie pelo `./start.sh`; ele sobe os dois serviços juntos.
- **Falha de conversão:** confira FFmpeg (`ffmpeg -encoders`) e espaço em disco. A gravação original `.avi` é preservada até expirar.
- **Computador reiniciou:** rode `./start.sh` novamente. Configurações e sessão são preservadas. Se o serviço systemd estiver habilitado, ele inicia automaticamente; veja a seção de serviço.

## Múltiplas câmeras

1. Clique em **Adicionar câmera +**, informe nome e RTSP/webcam e cadastre.
2. Ela começa pausada. Selecione-a no menu **Câmera selecionada**, ajuste suas
   configurações e clique em **Iniciar câmera** na visão geral.
3. Cada câmera tem captura, rastreamento, gravação manual e pausa de análise
   independentes. A perda de sinal de uma câmera não encerra as demais.
4. O mosaico mostra prévias atualizadas a cada 3 segundos. A câmera selecionada
   tem vídeo contínuo e pode ir para tela cheia.
5. No histórico, use o filtro de câmera; ele inclui câmeras removidas.

Os totais do painel somam todas as câmeras. **Uma pessoa vista em duas câmeras
pode gerar dois registros**: não há deduplicação de visitas entre ambientes.
Nome e ID da câmera ficam em cada evento. Renomear/remover uma câmera preserva
os vídeos e seus nomes de origem; as legendas do WhatsApp usam a origem do registro.
A câmera principal existente é preservada e pode ser editada ou pausada. As
adicionais podem ser removidas, encerrando primeiro suas gravações.

O cadastro de rostos, os ajustes de reconhecimento, o prazo de retenção e o
WhatsApp são compartilhados. IDs de rastreamento e memória temporária de roupas
são separados por câmera para evitar misturar pessoas de ambientes distintos.
As confirmações e exclusões de exemplos atualizam a galeria compartilhada.

**Pausar todas as análises** interrompe YOLO/reconhecimento em todas as câmeras
mais a análise posterior em andamento. Vídeos ao vivo e gravações manuais
continuam. **Retomar todas** reativa a análise das câmeras que estiverem ligadas.
A análise posterior continua limitada a um vídeo de cada vez. Ela usa os ajustes
locais de processamento salvos no início da gravação, mesmo se sua câmera for
removida, com a galeria facial atual.

Há um limite de cadastro de 16 câmeras (principal + 15 adicionais). Esse limite
não é uma garantia de desempenho simultâneo: cada câmera ativa mantém seu próprio
modelo YOLO e seu reconhecimento. Veja [capacidade sem GPU](docs/cpu-capacity.md).

### Compatibilidade e API

O arquivo antigo de configurações continua válido; seus campos de câmera são a
câmera `main`. Câmeras adicionais ficam na lista `cameras`. O banco migra o
histórico antigo para `main`. As rotas antigas continuam usando a principal quando
`camera_id` não é informado.

- `GET/POST /api/cameras`, `DELETE /api/cameras/{id}`.
- `GET/PUT /api/settings?camera_id={id}`: ajustes locais da câmera + globais.
- `POST /api/monitor/{start|stop}?camera_id={id}`.
- `POST /api/analysis/{pause|resume}?camera_id={id}`.
- `POST /api/analysis-all/{pause|resume}`.
- `POST /api/recording/{start|stop}?camera_id={id}`.
- `GET /api/status?camera_id={id}`: câmera selecionada, lista de estados,
  totais globais em `stats` e totais da selecionada em `camera_stats`.
- `GET /api/events?camera_id={id}`: omitir o parâmetro retorna todas as origens.
- `GET /api/snapshot?camera_id={id}` e `/api/stream.mjpeg?camera_id={id}`.

Salvar o formulário não altera os estados de captura/análise nem substitui a
lista de câmeras: use os controles explícitos. As rotas mantêm autenticação e
proteção de escrita existentes.

### Testes de múltiplas câmeras

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/multicamera-ui-smoke.mjs
PYTHONPATH=. .venv/bin/python tests/cpu_benchmark.py --cameras 2 --size 416
```

O teste de navegador usa dois vídeos locais, confere prévias distintas, controles,
gravações independentes e remoção durante gravação com histórico preservado.
O benchmark desabilita CUDA no próprio processo, usa diretório temporário e
YOLO/SFace reais; não acessa as câmeras da casa nem envia mensagens.


## Diagnóstico e escolha dos melhores rostos

Novos rastros guardam a última avaliação facial: rosto não encontrado, pequeno,
pouco nítido, associação ambígua, falta de exemplos, semelhança insuficiente ou
aguardando concordância. Abra o registro no histórico para ver o motivo, o tamanho
do rosto, a nitidez e o resultado de comparação quando disponíveis. Registros
antigos informam que não têm diagnóstico, sem inventar motivos retroativos.

O sistema mantém até 12 imagens de revisão por rastro e continua procurando
imagens melhores durante toda a presença. Rostos com embeddings quase iguais são
tratados como redundantes; uma imagem pelo menos 20% mais nítida pode substituir
uma versão não confirmada. Ao atingir o limite, uma imagem melhor substitui a
menos nítida que não foi confirmada. Exemplos confirmados ficam protegidos.
A revisão mostra primeiro os rostos mais nítidos. Nitidez é uma medida auxiliar;
confira visualmente antes de ensinar uma imagem ao sistema.

Esse comportamento vale para captura ao vivo e análise posterior. A comparação
continua exigindo os limites configurados e três observações concordantes. Essas
mudanças melhoram a seleção de evidências e o diagnóstico; o ganho de acerto ainda
precisa ser medido em gravações reais com a câmera ajustada.

Para a C920 no notebook: [guia Linux de foco e exposição](docs/c920-linux.md).

## Serviço com reinício automático

O arquivo `deploy/camera-ai.service` instala o serviço do usuário para o projeto
em `~/camera-ai` (ajuste os caminhos se mover a pasta):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/camera-ai.service ~/.config/systemd/user/camera-ai.service
systemctl --user daemon-reload
systemctl --user enable --now camera-ai.service
```

Encerre uma instância manual de `./start.sh` antes de iniciar o serviço, para não
usar a mesma porta e sessão WhatsApp em dois processos. Para iniciar antes do
login e manter após sair da sessão, o usuário precisa de linger habilitado:
`loginctl enable-linger "$USER"`. A política da máquina pode exigir administrador.

```bash
systemctl --user status camera-ai.service
systemctl --user restart camera-ai.service
systemctl --user stop camera-ai.service
systemctl --user start camera-ai.service
journalctl --user -u camera-ai.service -n 80
```

Nesta instalação, o serviço do usuário está habilitado e o linger já estava ativo, permitindo iniciar antes do login. Use `systemctl --user show camera-ai.service -p MainPID` para consultar o processo atual.

Uma parada explícita pelo `systemctl` é respeitada. Para impedir o início
seguinte, use `systemctl --user disable --now camera-ai.service`. Para voltar ao
modo manual, desabilite o serviço e execute `./start.sh`. O serviço reinicia em
caso de saída do processo; perda da câmera é tratada pela reconexão interna.

### FPS variável e continuidade

A câmera pode reduzir de 30 para 24/25 FPS com pouca luz. A gravação usa o tempo
recebido de cada quadro e repete quadros quando necessário para preservar a duração;
isso não recupera detalhes perdidos por movimento ou pouca iluminação. O painel
mostra separadamente a taxa recebida, a declarada pela câmera e a taxa da análise.

O ByteTrack recebe detecções a partir de 10% para tentar manter pessoas já
acompanhadas. Iniciar um novo track continua exigindo a confiança configurada
(50% por padrão). Tracks ausentes expiram em 2 segundos de tempo decorrido,
independentemente da taxa de análise. Recuperar o número do track não recupera
sozinho um nome apagado: rosto ou memória corporal precisam verificá-lo novamente.
A associação de movimento ainda depende dos quadros disponíveis e pode falhar
com oclusão, cruzamento de pessoas ou mudança brusca de posição.

A seleção automática de fotos mais nítidas melhora os exemplos candidatos para
revisão. Ela preserva os exemplos já confirmados pelo usuário e não resolve,
sozinha, perdas de tracking quando a pessoa vira de costas.

### Reproduzir um problema corporal de um vídeo local

`PYTHONPATH=. .venv/bin/python tests/body_replay.py --event ID --return-after SEGUNDOS`
reprocessa um registro em uma cópia temporária do banco, sem modificar o histórico
nem enviar mensagens. O relatório fica em `test-results/body-audit/`. O teste exige
rosto reconhecido, saída de cena e identificação corporal na volta; também compara
pessoas das imagens oficiais de exemplo como controles negativos. Gravações antigas
já contêm caixas e texto, por isso esse teste não substitui uma avaliação com vídeo
original nem mede a taxa geral de acerto.

### Diagnóstico de envio pelo WhatsApp

O gateway consulta o número com `onWhatsApp` antes de enviar e usa o JID retornado
pelo WhatsApp. Isso evita o envio ao endereço errado quando a conta brasileira é
registrada sem o nono dígito, mesmo que o número informado contenha esse dígito.
Não remova dígitos manualmente: a resolução é feita pelo serviço.

O identificador retornado por `sendMessage` indica submissão, não comprova entrega
no celular. O gateway registra separadamente as confirmações `server`, `delivered`
e `read` em `data/whatsapp-delivery.json`. A rota local autenticada `POST /delivery`
recebe `clip_id` e permite consultar essa confirmação. Mensagens de mídia ficam
armazenadas nesse arquivo privado para responder a pedidos de retransmissão do
Baileys (`getMessage`). Não compartilhe esse arquivo nem a pasta de autenticação.

Na revisão de 29/09/2026, os registros antigos foram retirados da fila por solicitação
do usuário, com estado `skipped`. Continuam no histórico, com indicação “Não enviar ·
registro antigo”, e não entram no contador de pendências. Apenas vídeos novos seguem
as configurações de envio. O início automático do serviço permanece desabilitado.

## Enviar os vídeos do pai para familiares

Em **Configurações → WhatsApp**, mantenha o seu telefone em **Seu número (principal)**
e preencha **Outros familiares · somente meu pai**, com um número por linha incluindo
DDI e DDD. São permitidos até nove familiares além do número principal. Salve as
configurações e mantenha o envio pelo WhatsApp ativado.

- O número principal mantém sua opção de receber todas as presenças ou somente o pai.
- Familiares recebem somente registros confirmados do pai. Se **Enviar também
  prováveis registros do pai** estiver habilitado, também recebem os que atendem
  ao filtro facial. Reconhecimento apenas pela roupa não autoriza esse envio.
- Um familiar novo recebe somente vídeos iniciados após seu cadastro. Adicionar
  números não compartilha o histórico antigo nem repete vídeos já enviados.
- O histórico mostra o estado de cada destinatário. **Tentar para este número**
  repete somente a tentativa que falhou; destinatários com envio concluído são preservados.
- Remover um número cancela suas entregas ainda pendentes. Um envio já em andamento
  pode terminar. Remover e cadastrar novamente não libera vídeos antigos para ele.
- O gateway identifica cada envio pelo vídeo e pelo endereço confirmado pelo
  WhatsApp. Duas formas de escrever o mesmo número não geram mensagens duplicadas.

O banco guarda esse controle em `clip_deliveries`. Registros antigos de envio
individual são migrados sem repetir mensagens. Para consultar `/delivery` ou
acionar `/retry` no gateway com vários destinatários, informe `clip_id` e `recipient`.

Validação: `tests/test_deliveries.py`, `tests/recipients-ui-smoke.mjs` e
`tests/multi-recipient-gateway.mjs`. Os testes usam números fictícios e um socket
simulado; não enviam mensagens reais a familiares.
