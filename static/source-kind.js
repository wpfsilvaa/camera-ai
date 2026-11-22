// Tipo da fonte da câmera (USB, rede/RTSP ou vídeo local): mostra uma etiqueta e esconde o que não vale para esse tipo.
(() => {
  const KINDS = {
    usb: ['Câmera USB', 'green', 'Câmera ligada neste computador: foco, exposição e perfis de imagem ficam disponíveis abaixo.'],
    rtsp: ['Câmera de rede (RTSP)', 'neutral', 'Foco e imagem se ajustam no aplicativo da própria câmera. Se for a câmera USB do notebook, ela aparece abaixo.'],
    file: ['Vídeo local', 'amber', 'Arquivo de vídeo, útil para testes.'],
    empty: ['Tipo de fonte', 'neutral', 'Endereço RTSP, câmera USB deste computador (escolha na lista) ou vídeo local.'],
  };
  const kindOf = value => {
    const text = (value || '').trim().toLowerCase();
    if (!text) return 'empty';
    if (/^(rtsps?|https?|rtmp|udp):\/\//.test(text)) return 'rtsp';
    if (text.startsWith('usb:') || text.startsWith('/dev/video') || /^\d+$/.test(text)) return 'usb';
    return 'file';
  };
  let last = null;
  function paint() {
    const input = document.querySelector('input[name="camera_source"]');
    const chip = document.getElementById('source-kind');
    if (!input || !chip) return;
    const kind = kindOf(input.value);
    if (kind === last) return;
    last = kind;
    const [label, tone, hint] = KINDS[kind];
    chip.textContent = label;
    chip.className = `pill ${tone}`;
    document.getElementById('source-hint').textContent = hint;
    document.getElementById('settings-form')?.setAttribute('data-source', kind);
  }
  document.addEventListener('input', event => { if (event.target.matches?.('input[name="camera_source"]')) paint(); });
  setInterval(paint, 1000);   // The form is filled by script (no input event), so also check it now and then.
  paint();
})();
