// Tela do notebook da cozinha: botões grandes para chamar a família e o rosto de quem atendeu.
(() => {
  const $ = id => document.getElementById(id);
  const screen = $('screen');
  let last = {call: {state: 'idle'}}, confirming = false, face = null, faceTimer = null;

  const post = path => fetch(path, {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: '{}'});

  async function press(kind) {
    const response = await fetch('/call', {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: JSON.stringify({kind})});
    if (!response.ok) { $('note').textContent = 'Não foi possível chamar agora. Tente de novo.'; $('note').classList.remove('hidden'); }
    confirming = false;
    await poll();
  }

  $('btn-call').onclick = () => press('call');
  $('btn-panic').onclick = () => { confirming = true; render(); };
  $('confirm-yes').onclick = () => press('panic');
  $('confirm-no').onclick = () => { confirming = false; render(); };
  $('btn-cancel').onclick = async () => { await post('/cancel'); poll(); };
  $('btn-end').onclick = async () => { await post('/cancel'); poll(); };

  function clock() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    $('date').textContent = now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'});
  }

  function render() {
    const {call, linked, enabled, battery, plugged} = last;
    $('battery').classList.toggle('hidden', battery == null);
    $('battery').textContent = battery == null ? '' : `${plugged ? '⚡' : '🔋'} ${battery}%`;
    let view = 'idle';
    if (call.state === 'ringing') view = 'ringing';
    else if (call.state === 'answered') view = 'answered';
    else if (call.state === 'ended' || call.state === 'missed') view = 'over';
    else if (confirming) view = 'confirm';
    screen.dataset.view = view;

    $('btn-call').classList.toggle('hidden', !enabled.call);
    $('btn-panic').classList.toggle('hidden', !enabled.panic);
    $('btn-call').disabled = $('btn-panic').disabled = !linked;
    const note = !linked ? 'Chamada indisponível no momento. Se precisar, use o telefone.' : !enabled.call && !enabled.panic ? 'Chamada pela tela desativada.' : '';
    $('note').textContent = note;
    $('note').classList.toggle('hidden', !note);
    $('ringing-title').textContent = call.kind === 'panic' ? 'Pedindo ajuda…' : 'Chamando a família…';
    if (view === 'answered') {
      $('answered-title').textContent = `${call.answered_by} atendeu`;
      $('avatar').textContent = (call.answered_by || '?').trim().slice(0, 1).toUpperCase();
      watchFace(true);
    } else watchFace(false);
    if (view === 'over') {
      $('over-title').textContent = call.state === 'missed' ? 'Ninguém atendeu' : 'Chamada encerrada';
      $('over-text').textContent = call.state === 'missed' ? 'Tente de novo daqui a pouco ou use o telefone.' : '';
    }
  }

  // The family member's camera arrives through MediaMTX ("face"); until it does, the initial letter shows.
  function watchFace(on) {
    if (!on) {
      clearTimeout(faceTimer); faceTimer = null;
      if (face) { face.close(); face = null; }
      $('face').srcObject = null; $('face').classList.add('hidden'); $('avatar').classList.remove('hidden');
      return;
    }
    if (face || faceTimer) return;
    faceTimer = setTimeout(async () => {
      faceTimer = null;
      const pc = new RTCPeerConnection();
      face = pc;
      pc.addTransceiver('video', {direction: 'recvonly'});
      pc.ontrack = event => {
        $('face').srcObject = event.streams[0] || new MediaStream([event.track]);
        $('face').classList.remove('hidden'); $('avatar').classList.add('hidden');
      };
      pc.onconnectionstatechange = () => {
        if (['failed', 'closed', 'disconnected'].includes(pc.connectionState) && face === pc) { watchFace(false); if (screen.dataset.view === 'answered') watchFace(true); }
      };
      try {
        await pc.setLocalDescription(await pc.createOffer());
        await new Promise(resolve => { pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && resolve(); setTimeout(resolve, 1000); });
        const response = await fetch('http://127.0.0.1:8889/face/whep', {method: 'POST', headers: {'Content-Type': 'application/sdp'}, body: pc.localDescription.sdp});
        if (response.status !== 201) throw new Error('sem vídeo ainda');
        await pc.setRemoteDescription({type: 'answer', sdp: await response.text()});
      } catch {
        // Nobody publishing yet (or no camera on their side): try again shortly.
        if (face === pc) { watchFace(false); if (screen.dataset.view === 'answered') faceTimer = setTimeout(() => { faceTimer = null; watchFace(true); }, 2500); }
      }
    }, 0);
  }

  async function poll() {
    try { last = await (await fetch('/state', {cache: 'no-store'})).json(); }
    catch { last = {call: {state: 'idle'}, linked: false, enabled: {call: false, panic: false}}; }
    render();
  }

  clock(); setInterval(clock, 10000);
  poll(); setInterval(poll, 1000);
})();
