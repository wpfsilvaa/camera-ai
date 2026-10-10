# Estudo de UI/UX — Casa Presente

Quem usa: familiares (muitas vezes pelo celular, com pressa e preocupação) e um administrador. A tela precisa responder em 2 segundos: **"está tudo bem?"**

## Problemas encontrados → o que mudou

| # | Problema | Efeito | Solução aplicada |
|---|----------|--------|------------------|
| 1 | Nenhum resumo de saúde: era preciso ler 4 cartões, a câmera e os alertas para saber se algo falhava | Problema passa despercebido | Faixa **"Tudo funcionando"** no topo da Visão geral; vira âmbar/vermelha e lista cada problema (câmera, notebook, WhatsApp, disco) |
| 2 | Fontes de 8 a 10 px em legendas, selos e botões | Ilegível no celular | Escala mínima 11 px (legendas) e 12 px (texto pequeno); cinza de apoio com mais contraste |
| 3 | Configurações: 9 painéis numerados em uma página longa | Rolagem enorme | 3 abas — **Câmera · Avisos · Sistema** (setas do teclado funcionam) |
| 4 | Salvar só no fim da página, sem indicar mudança pendente | Perde alterações | Barra de salvar fixa com "● Alterações ainda não salvas" |
| 5 | Menu no topo do celular | Longe do polegar | Barra de navegação **inferior** no celular, respeitando a área segura do iPhone |
| 6 | Alvos de toque pequenos (29–34 px) | Erros de toque | Em telas de toque: 44 px mínimo e interruptores maiores |
| 7 | Só tema claro | Cansa à noite | **Aparência automática / clara / escura** (botão no topo; lembra a escolha; sem "piscar") |
| 8 | Troca de página seca | Sensação de travado | Transição de 0,2 s (desligada com "reduzir movimento") |
| 9 | Família não podia escolher os avisos do próprio aparelho (403) | Opção inútil | Liberado para contas de família |

## Dark mode
As cores fixas do CSS viraram variáveis (`--surface`, `--muted`, `--green-ink` …) em `static/style.css`; o tema escuro redefine só as variáveis. Telas novas devem usar as variáveis.

## Próximos passos sugeridos (não feitos)
- Linha do tempo do dia no lugar dos 4 cartões numéricos.
- Histórico em cartões no celular (a tabela exige rolagem lateral).
- Gráfico de bateria do notebook nas últimas 24 h.
