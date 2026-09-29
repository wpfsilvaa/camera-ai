# Capacidade sem GPU

Sim: selecione **CPU** em Configurações para cada câmera. YOLO, YuNet/SFace e
comparação corporal funcionam localmente em CPU. Baileys e o painel também.
Não é necessário treinar uma rede: o cadastro armazena embeddings dos rostos.

## Configuração inicial

Para começar com uma ou duas câmeras:

- CPU x86-64 com AVX2, **4 núcleos físicos / 8 threads**, desempenho de desktop
  próximo do i7-7700K usado no teste ou superior.
- **8 GB de RAM** para uma instalação dedicada; **16 GB** dão margem para
  navegador, mais câmeras e análise posterior.
- SSD, **20 GB livres para ambiente/modelos**, mais o espaço dos vídeos.
  Uma unidade de 256 GB é um ponto de partida; retenção e tempo gravado determinam
  a capacidade necessária. A aplicação interrompe gravações abaixo de 512 MB livres.
- Linux de 64 bits, Python 3.11+, Node 22+ e FFmpeg com libx264. A validação local
  foi feita com Python 3.14.7. Instale os requisitos Python e Node do projeto.
- Rede cabeada quando possível, com banda para a soma dos fluxos RTSP.

Estes são **requisitos práticos sugeridos**, não um mínimo certificado. Para
3–4 câmeras com folga eu dimensionaria **6–8 núcleos físicos e 16 GB de RAM**.
Mais pessoas visíveis, vídeo Full HD, análise de arquivos e outras aplicações
podem exigir mais. Para muitas câmeras ou análise a 25–30 FPS, dimensione com
benchmark dos fluxos reais e considere uma GPU.

No painel, comece com **CPU, detecção 416, 5 quadros analisados/s e vídeo a 15 FPS**.
A taxa de análise é um teto independente da taxa do vídeo; o processamento ainda
pode reduzir a fluidez do vídeo se não couber no tempo de cada quadro. Quadros
entre análises reutilizam as últimas caixas, por isso a marcação pode ficar
atrasada em movimentos rápidos. A captura RTSP mantém apenas o quadro recente.

Para a configuração mais econômica, desligue **Lembrar pelo corpo e pela roupa**.
O reconhecimento facial permanece disponível. Os rostos são recortados do quadro
original; reduzir a resolução YOLO não melhora a nitidez de uma câmera distante.
Detecção em 640 pode ajudar com pessoas pequenas, com custo maior.

## Medição local

Relatórios em `test-results/cpu-*.json`, reproduzíveis com:

```bash
PYTHONPATH=. .venv/bin/python tests/cpu_benchmark.py --cameras 1 --size 416
PYTHONPATH=. .venv/bin/python tests/cpu_benchmark.py --cameras 2 --size 416
PYTHONPATH=. .venv/bin/python tests/cpu_benchmark.py --cameras 4 --size 416
PYTHONPATH=. .venv/bin/python tests/cpu_benchmark.py --cameras 2 --size 416 --body
```

CPU: **Intel Core i7-7700K, 4 núcleos / 8 threads**. O processo esconde CUDA e força
`device=cpu`; usa YOLO26n/PyTorch FP32, duas threads por modelo e SFace real, com
uma pessoa cadastrada em cada quadro. Cada câmera recebe um vídeo local MJPEG de
1280×720 a 15 FPS. Detecção limitada a 5 FPS, entrada 416. Aquecimento excluído;
medição de aproximadamente 12 segundos. As gravações foram convertidas depois,
separadamente. O serviço normal e outras aplicações da máquina permaneceram ativos.

| Câmeras | Corpo/roupa | Análises/s por câmera | Vídeo FPS por câmera | Pico RAM Python |
|---|---|---|---|---|
| 1 | Desligado | 5.0 | 12.1 | 1030 MiB |
| 2 | Desligado | 4.5–4.9 | 9.8–10.5 | 1202 MiB |
| 4 | Desligado | 5.0 | 15.0 | 1526 MiB |
| 2 | Ligado | 4.9–5.0 | 15.0 | 1292 MiB |

As diferenças de latência entre execuções também refletem carga concorrente da
máquina; não use a tabela como prova de escalabilidade linear. O teste curto e
com uma pessoa não representa a variação de uma casa durante um dia inteiro.
RAM é o pico do processo Python; sistema, navegador, Node e FFmpeg são adicionais.
O benchmark não mede decodificação H.264/H.265 via RTSP, envio ao WhatsApp ou
conversão simultânea. Identificação correta nos vídeos de teste também não mede
a taxa de acerto em pessoas, distâncias e iluminação diferentes.

Na primeira execução com quatro câmeras, a conversão levou 133 s para 58 s
acumulados de vídeo. Na repetição, levou 2 s para 57 s, com todos os MP4 prontos.
A causa da variação não foi isolada; os dois relatórios foram preservados.

Observe no uso real **FPS de vídeo, FPS de análise, atraso e fila de conversão**.
Câmeras podem continuar sendo capturadas enquanto a fila de vídeos cresce; somente
ver o mosaico ao vivo não comprova que a máquina suporta gravação contínua.

## Espaço em disco

A 2 Mbit/s, uma hora de vídeo H.264 ocupa aproximadamente **0,9 GB**. Quatro
câmeras gravando 1 hora por dia durante 7 dias somam cerca de **25 GB**. Gravando
24 horas por dia, são cerca de **605 GB**. São exemplos de bitrate constante;
o sistema usa qualidade variável e grava automaticamente apenas durante presença.
Reserve margem para AVI temporário, miniaturas e cópias com identificação posterior.

## Possível otimização futura

A documentação do [YOLO26](https://docs.ultralytics.com/models/yolo26/) publica
38,9 ms para YOLO26n em CPU/ONNX a 640, em seu ambiente de benchmark. Esse número
não inclui este sistema completo e não deve ser convertido diretamente em número
de câmeras suportadas. Este projeto continua usando o modelo PyTorch `.pt`.

A integração [OpenVINO da Ultralytics](https://docs.ultralytics.com/integrations/openvino/)
permite otimização para CPUs Intel e relata ganhos em seus testes. Ela ainda não
foi habilitada aqui: exigiria exportar e validar o modelo, o tracking e a precisão
no hardware alvo. Os requisitos acima não dependem desse ganho futuro.
