// Calls from the kitchen notebook's button: banner on every page, answer with voice (and face), hang up.
(() => {
  const banner = $('#call-banner');
  let mine = null;  // Id of the call this browser answered.

  function paint() {
    const call = status?.notebook?.call;
    const live = call && ['ringing', 'answered'].includes(call.state);
    banner.classList.toggle('hidden', !live);
    if (!live) { mine = null; return; }
    const panic = call.kind === 'panic', ringing = call.state === 'ringing', answeredByMe = mine === call.id;
    banner.classList.toggle('panic', panic);
    $('#call-title').textContent = ringing ? (panic ? 'Pedido de ajuda do seu pai' : (call.to_name ? `Seu pai está chamando ${call.to_name}` : 'Seu pai está chamando')) : answeredByMe ? 'Em chamada com o notebook' : `${call.answered_by} atendeu`;
    $('#call-title').insertAdjacentHTML('afterbegin', ic(panic && ringing ? 'alert' : 'phone', 'lead'));
    $('#call-detail').textContent = ringing ? `Notebook da cozinha · desde as ${time(call.since)}` : answeredByMe ? 'Ele ouve você e vê o seu rosto, se a câmera estiver liberada.' : 'Outra pessoa da família já está falando com ele.';
    $('#call-answer').classList.toggle('hidden', !ringing);
    $('#call-end').classList.toggle('hidden', ringing ? false : !answeredByMe && !isAdmin());
    $('#call-end').textContent = ringing ? 'Dispensar' : 'Encerrar';
    // Reloaded the page mid-call: offer to bring the voice back.
    if (answeredByMe && !window.intercom.active()) { $('#call-detail').textContent = 'O áudio caiu. Toque em Atender para reconectar.'; $('#call-answer').classList.remove('hidden'); }
  }

  $('#call-answer').addEventListener('click', event => action(event.currentTarget, async () => {
    const call = status.notebook.call;
    if (mine !== call.id) await api('/api/notebook/call/answer', {method: 'POST'});
    mine = call.id;
    if (!window.intercom.active()) await window.intercom.start(true);
    await refresh();
  }));
  $('#call-end').addEventListener('click', event => action(event.currentTarget, async () => {
    if (window.intercom.active()) await window.intercom.hangup();
    await api('/api/notebook/call/end', {method: 'POST'});
    mine = null;
    await refresh();
  }));

  // Hook into the periodic status render.
  const original = window.renderHome;
  window.renderHome = function () { original.apply(this, arguments); paint(); };
})();
