# Validação da volta de costas — 29/09/2026

O registro local 127 mostra rosto identificado, giro durante a saída e uma volta
de costas marcada como desconhecida. O código anterior só guardava o corpo quando
o rosto também era reconhecido no mesmo quadro: a vista durante o giro era perdida.

## Alterações

- Coleta de outros ângulos durante até 10 segundos de acompanhamento contínuo após
  reconhecimento facial. Perda do track, sobreposição, salto de posição ou rosto
  conflitante interrompem a coleta. A validade continua ligada ao rosto original.
- Até cinco embeddings consecutivos são combinados em uma média normalizada.
  Há até 12 referências faciais/corporais simultâneas e 12 vistas pela continuidade;
  só referências praticamente iguais são substituídas como repetidas.
- Após identificação corporal, pequenas oscilações podem manter a sugestão por até
  3 segundos. Ambiguidade e aparência diferente encerram essa manutenção. Acertos
  só pelo corpo não ensinam novas referências nem prolongam a memória.
- Diagnóstico corporal no histórico e limite corporal editável no painel.

## Evidência

`tests/body_replay.py --event 127` usa modelos reais e uma cópia temporária do banco.
Confere que a identidade da volta é a mesma que foi confirmada pelo rosto, que houve
saída de cena e que o retorno não oferece rosto utilizável. Não modifica o histórico
nem envia mensagens. A gravação já contém texto/caixas, o que limita o ensaio.

Na configuração atual de detecção (1280 e confiança 0,35), com as melhorias:

| Limite corporal | Primeira sugestão no vídeo | Observações do retorno com sugestão, incluindo manutenção |
| --- | --- | --- |
| 0,85 | 14,000 s | 2 de 16 |
| 0,75 | 10,667 s | 12 de 16 |

A primeira detecção do retorno ocorreu em 9,333 s. O limite 0,75 foi salvo para
esta instalação após esse ensaio; o padrão para instalações novas continua 0,85.
O modelo corporal permanece YOLO26n ReID, sem aumento do custo de inferência.

Cinco pessoas das imagens oficiais `zidane.jpg` e `bus.jpg` foram comparadas com
as referências coletadas: nenhuma recebeu a identidade, com semelhança máxima
aproximada de 0,22. São controles limitados, não uma medida da taxa geral de erros,
especialmente entre pessoas com roupas semelhantes. A identificação corporal é
uma sugestão de aparência; a regra de envio que exige evidência facial foi preservada.

Os testes unitários cobrem perda de track, conflitos de rosto, sobreposição, prazo
máximo de coleta, expiração, limite de referências, ambiguidade e ausência de
aprendizado recursivo pelo corpo. O teste do painel verifica o novo limite e o
diagnóstico, gravação manual e análise posterior. O pipeline com modelos reais
verificou saída, retorno com rosto coberto, novo ID e identificação no vídeo gravado.

Resultados locais: `test-results/body-unit.log`, `test-results/body-ui.log`,
`test-results/body-audit/replay-127.json`, `test-results/body-pipeline.json`.

O serviço principal estava parado e desabilitado para início automático durante
a validação final. Essa configuração foi preservada. Ao iniciar, a memória de roupa
começa vazia; é necessário reconhecer o rosto novamente e observar o giro dentro
do enquadramento para aprender a vista de costas.
