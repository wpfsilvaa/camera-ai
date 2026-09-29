# C920 no notebook Linux com FFmpeg/MediaMTX

Execute os comandos no notebook que recebe o USB da C920. O endereço RTSP apenas
transporta vídeo e não permite ajustar os controles USB por este projeto.

## Localizar a câmera e consultar os controles

Em Debian/Ubuntu:

```bash
sudo apt install v4l-utils
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
v4l2-ctl -d /dev/video0 --list-ctrls-menus
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Troque `/dev/video0` pelo dispositivo **de captura** da C920. Prefira o caminho
estável de `/dev/v4l/by-id/...-video-index0` para scripts. A interface de metadados
não oferece as mesmas operações. Se faltar permissão, verifique o acesso do
usuário ao grupo `video` e entre novamente na sessão após ajustar o grupo.

## Desligar o autofoco

Copie `scripts/c920_focus.py` deste projeto para o notebook. O script reconhece os
nomes `focus_automatic_continuous` e `focus_auto` e valida a faixa e o passo antes
de escrever qualquer controle. Sem `--focus`, apenas consulta:

```bash
python3 c920_focus.py --device /dev/video0
python3 c920_focus.py --device /dev/video0 --focus 0
```

O segundo comando desliga o autofoco e define o foco em **0 como ponto inicial de
teste**, se esse valor existir na faixa do driver. Não é um foco universal:
coloque uma pessoa ou objeto com detalhes finos na distância em que seu pai
costuma aparecer, abra a imagem em tamanho original e ajuste em passos aceitos
pelo driver até encontrar a maior nitidez. Teste também o ponto mais próximo e o
mais distante do percurso. Não confunda foco com zoom digital.

Equivalente manual, se os nomes abaixo aparecerem na consulta:

```bash
v4l2-ctl -d /dev/video0 --set-ctrl=focus_automatic_continuous=0
v4l2-ctl -d /dev/video0 --set-ctrl=focus_absolute=0
v4l2-ctl -d /dev/video0 --get-ctrl=focus_automatic_continuous,focus_absolute
```

Em drivers antigos, substitua `focus_automatic_continuous` por `focus_auto`.
Desligue o modo automático **antes** de escrever o foco manual. Para voltar ao
automático, ajuste esse mesmo controle para `1`.

Adicione o comando com o valor escolhido ao script que inicia a transmissão,
antes do FFmpeg. Alguns drivers/programas restauram controles ao reconectar ou
abrir o dispositivo; confira a leitura e a imagem depois que a transmissão
iniciar. Se os controles forem restaurados, reaplique o script após a abertura.
O script não precisa rodar no servidor que recebe o RTSP.

## Ponto de partida para a imagem

| Ajuste | Sugestão inicial |
|---|---|
| Captura | 1920×1080 a 30 FPS, formato MJPEG, se listado pelo driver e sustentável no notebook/rede |
| Análise | 640 na GPU; 416 e 5 análises/s como opção econômica na CPU |
| Foco | Manual, ajustado na distância real de uso |
| Exposição | Comece com automática; se houver borrão durante movimento, teste manual em 1/120 s com luz suficiente, ou 1/60 s |
| Anti-flicker | 60 Hz para iluminação ligada à rede brasileira, se disponível; verifique se a lâmpada não produz faixas |
| Ganho | O menor que mantenha a imagem bem exposta; prefira aumentar a luz |
| Balanço de branco | Automático se a luz varia; fixo apenas depois de calibrar sob iluminação constante |
| Zoom | Sem zoom digital; enquadre fisicamente para aumentar o rosto na imagem |

Os nomes da exposição também mudam entre drivers. Consulte os menus e selecione
exposição manual antes do tempo absoluto. V4L2 usa unidades de **100 μs**:
`83` equivale aproximadamente a 1/120 s e `167` a 1/60 s, sujeitos à faixa e ao
passo anunciados. Não escreva esses valores em controles cujo significado não
foi conferido. Em modo automático, a prioridade de exposição igual a zero
impede que a câmera reduza FPS para compensar pouca luz, quando suportado.

MJPEG é o formato de captura USB proposto; mantenha a saída RTSP em H.264 conforme
o transmissor existente. Verifique no painel a resolução e a taxa que realmente
chegam. Não altere o comando de transmissão sem conferir os formatos da câmera.

Melhore o ângulo depois, buscando rosto visível de frente ou levemente de lado,
sem janela forte atrás. O diagnóstico “rosto pequeno” ou “pouca nitidez” do
histórico ajuda a verificar o efeito de cada ajuste.

## Referências

- [Logitech: controles da C920 e foco manual](https://support.logi.com/hc/en-gb/articles/360023188714-Customize-HD-Pro-Webcam-C920-Settings-with-Logitech-Gaming-Software).
- [Linux V4L2: foco, exposição e prioridade de FPS](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/ext-ctrls-camera.html).

Os valores sugeridos são pontos de partida; a câmera USB está em outro notebook
e não foi ajustada nem medida por este processo.
