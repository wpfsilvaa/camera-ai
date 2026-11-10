# Confirmar queda com IA local (experimental)

Desligado por padrão. Quando o detector marca uma possível queda, um modelo de visão pequeno
(**LFM2.5-VL-450M**, via llama.cpp, só CPU) olha o recorte da pessoa marcada e responde "sim" ou "não" para
"há uma pessoa nesta imagem?". Tudo roda neste computador; nada vai para a nuvem.

**Regra de segurança:** o aviso só é cancelado quando o modelo responde **"não" com clareza** para todas as caixas
marcadas (por exemplo, um saco de lixo azul que o detector achou que estava deitado). Resposta "sim", dúvida, erro,
tempo esgotado ou modelo ausente: o aviso sai exatamente como sem o filtro. Um aviso cancelado conta mais um período
de "alertar após ficar deitado" antes de poder disparar de novo para a mesma pessoa marcada.

## Como ligar

1. Baixe o `llama-mtmd-cli` (release do llama.cpp, build `ubuntu-x64`) e, do repositório `LiquidAI/LFM2.5-VL-450M-GGUF`,
   os arquivos `LFM2.5-VL-450M-Q4_K_M.gguf` (229 MB) e `mmproj-LFM2.5-VL-450m-Q8_0.gguf` (103 MB), todos numa pasta.
2. No `.env`: `LFM_DIR=/caminho/da/pasta` (opcional: `LFM_THREADS=2`, padrão 2).
3. Reinicie o serviço e ligue **Confirmar queda com IA local** em Configurações → Possível queda.

## Custo e medidas (2026-11)

- Notebook i5-4200U (4 threads, sem GPU): cerca de 4 s por recorte.
- PC com 8 threads: cerca de 1,6 s por recorte. A consulta roda em segundo plano e não trava a detecção.
- Teste em 58 recortes de fotos reais de alerta: 27/27 pessoas reconhecidas, 31/31 fundos sem pessoa, e o saco de
  lixo do falso positivo conhecido foi corretamente "não". Amostra pequena; falta testar negativos difíceis (roupa
  no chão, cobertor). Reproduza com `scripts/lfm_check.py`.
