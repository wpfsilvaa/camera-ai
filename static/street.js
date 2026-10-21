// Street mode: one button in the top bar. Switch it on when the house is empty; an unknown person on a guarded camera then raises the intruder alert.
(() => {
  let state = null;
  function paint() {
    if (!state) return;
    const on = state.armed, button = $('#street-toggle');
    button.setAttribute('aria-pressed', String(on));
    button.classList.toggle('on', on);
    $('#street-label').textContent = on ? 'Modo rua ligado' : 'Modo rua';
    const where = state.guards.length ? `Câmeras vigiando: ${state.guards.join(', ')}.` : 'Nenhuma câmera marcada para vigiar a casa (Configurações → Câmera).';
    const warn = state.recognition ? '' : ' O reconhecimento facial está desligado: a família também seria tratada como desconhecida.';
    button.title = on
      ? `Ligado desde as ${time(state.since)}. Desconhecidos que ficarem ${state.delay} s na câmera disparam o alarme. ${where}${warn} Toque para desligar.`
      : `Toque ao sair de casa. Só pessoas desconhecidas disparam o alarme; a família reconhecida não. ${where}${warn}`;
    document.body.classList.toggle('street-on', on);
  }
  async function load() {
    try { state = await api('/api/street'); paint(); } catch { /* the next refresh tries again */ }
  }
  $('#street-toggle').addEventListener('click', event => action(event.currentTarget, async () => {
    if (!state) await load();
    state = {...state, ...await api('/api/street', {method: 'PUT', body: JSON.stringify({armed: !state.armed})})};
    paint();
    toast(state.armed ? `Modo rua ligado: vigiando ${state.guards.join(', ')}. Desconhecidos que ficarem ${state.delay} s disparam o alarme.` : 'Modo rua desligado.');
    load();
  }));
  document.addEventListener('DOMContentLoaded', load);
  setInterval(() => { if (!document.hidden) load(); }, 15000);
})();
