// Textos da tela do totem: exemplo ao vivo de como cada frase fica e botão para voltar aos textos padrão.
(() => {
  const fill = (template, vars) => template.replace(/\[([^\[\]]*)\]/g, (_, piece) => [...piece.matchAll(/\{(\w+)\}/g)].some(m => !vars[m[1]]) ? '' : piece)
    .replace(/\{(\w+)\}/g, (_, key) => vars[key] ?? '').replace(/\s+([.,;:!?])/g, '$1').replace(/\s+/g, ' ').trim();
  function sample() {
    const now = new Date(), hour = now.getHours();
    return {nome: 'Flavio', saudacao: hour >= 5 && hour < 12 ? 'Bom dia' : hour >= 12 && hour < 18 ? 'Boa tarde' : 'Boa noite',
      data: now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'}), dia: now.toLocaleDateString('pt-BR', {weekday: 'long'}),
      hora: now.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'}), temperatura: '27°', tempo: 'parcialmente nublado', max: '31°', min: '19°', chuva: '70%',
      sugestao: 'leve o guarda-chuva se for sair', sugestoes: 'leve o guarda-chuva se for sair e beba bastante água'};
  }
  function paint() {
    const vars = sample();
    if (document.querySelector('input[name="kiosk_tips_enabled"]') && !document.querySelector('input[name="kiosk_tips_enabled"]').checked) vars.sugestao = vars.sugestoes = '';
    document.querySelectorAll('#kiosk-texts-panel [data-text-field]').forEach(input => {
      const preview = input.parentElement.querySelector('.text-preview');
      if (preview) preview.textContent = `Exemplo: ${fill(input.value.trim() || input.dataset.default, vars) || '(vazio)'}`;
    });
  }
  document.addEventListener('input', event => { if (event.target.closest?.('#kiosk-texts-panel')) paint(); });
  document.addEventListener('change', event => { if (event.target.closest?.('#kiosk-texts-panel')) paint(); });
  document.addEventListener('click', event => {
    if (!event.target.closest('#kiosk-texts-reset')) return;
    document.querySelectorAll('#kiosk-texts-panel [data-text-field]').forEach(input => { input.value = ''; });
    document.getElementById('settings-form')?.dispatchEvent(new Event('input', {bubbles: true}));   // Marks the form as changed.
    paint();
  });
  setInterval(paint, 1500);   // The form is filled by script (no input event) and the clock changes the example.
  paint();
})();
