// Street mode: switch on when the house is empty; an unknown person on a guarded camera then raises the intruder alert.
(() => {
  let state = null;
  function paint() {
    if (!state) return;
    const on = state.armed;
    $('#street-pill').textContent = on ? 'Ligado' : 'Desligado';
    $('#street-pill').className = `pill ${on ? 'red' : 'neutral'}`;
    $('#street-toggle').textContent = on ? 'Desligar Modo rua' : 'Ligar Modo rua';
    $('#street-toggle').className = `button ${on ? 'secondary' : 'primary'}`;
    const where = state.guards.length ? `Câmeras vigiando: ${state.guards.join(', ')}.` : 'Nenhuma câmera marcada para vigiar a casa (Configurações → Câmera).';
    const warn = state.recognition ? '' : ' O reconhecimento facial está desligado: a família também seria tratada como desconhecida.';
    $('#street-text').textContent = on
      ? `Ligado desde as ${time(state.since)}. Desconhecidos que ficarem ${state.delay} s na câmera disparam o alarme. ${where}${warn}`
      : `Ligue ao sair de casa. Só pessoas desconhecidas disparam o alarme; a família reconhecida não. ${where}${warn}`;
    document.body.classList.toggle('street-on', on);
  }
  async function load() {
    try { state = await api('/api/street'); paint(); } catch { /* the next refresh tries again */ }
  }
  $('#street-toggle').addEventListener('click', event => action(event.currentTarget, async () => {
    state = {...state, ...await api('/api/street', {method: 'PUT', body: JSON.stringify({armed: !state.armed})})};
    paint();
    toast(state.armed ? 'Modo rua ligado. Você tem alguns segundos para sair.' : 'Modo rua desligado.');
    load();
  }));
  document.addEventListener('DOMContentLoaded', load);
  setInterval(() => { if (!document.hidden) load(); }, 15000);
})();
