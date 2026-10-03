// Live two-way conversation with the camera computer (see rtc.js).
(() => {
  let call = null;
  const button = $('#intercom-call'), mute = $('#intercom-mute'), note = $('#intercom-note'), speaker = $('#intercom-audio');

  function playOrAsk() {
    // Opened from a notification, the browser may block sound until the first tap on the page.
    speaker.play().catch(() => {
      if (!call) return;
      call.muted = true;
      render();
      document.addEventListener('pointerdown', () => speaker.play().then(() => { if (call) call.muted = false; render(); }).catch(() => {}), {once: true});
    });
  }

  function watch(pc) {
    pc.addEventListener('connectionstatechange', () => {
      if (call && pc.connectionState === 'failed') hangup('A conexão de áudio caiu. Confira a rede e chame de novo.');
    });
  }

  function render() {
    const active = Boolean(call);
    button.innerHTML = active ? 'Encerrar conversa <span>✕</span>' : 'Conversar ao vivo <span>🎙</span>';
    button.classList.toggle('danger-button', active);
    mute.classList.toggle('hidden', !call?.microphone);
    mute.textContent = call?.microphone && !call.microphone.enabled ? 'Ligar meu microfone' : 'Silenciar meu microfone';
    note.classList.toggle('hidden', !active);
    if (active) note.textContent = call.muted ? 'Toque em qualquer lugar da tela para ouvir o ambiente.' : call.microphone ? 'Em conversa: você ouve o ambiente e ele ouve você.' : 'Ouvindo o ambiente. Para falar, abra o painel pelo endereço https do Tailscale (…ts.net).';
  }

  async function start() {
    const cameraId = selectedCamera;
    call = {cameraId, peers: [], sessions: []};
    try {
      const listen = new RTCPeerConnection();
      call.peers.push(listen);
      watch(listen);
      listen.addTransceiver('audio', {direction: 'recvonly'});
      listen.addEventListener('track', event => { speaker.srcObject = event.streams[0] || new MediaStream([event.track]); playOrAsk(); });
      call.sessions.push(['listen', await rtcNegotiate('listen', listen, cameraId)]);

      // Browsers only release the microphone on HTTPS or localhost.
      if (window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
        call.microphone = stream.getAudioTracks()[0];
        const talk = new RTCPeerConnection();
        call.peers.push(talk);
        watch(talk);
        talk.addTransceiver(call.microphone, {direction: 'sendonly'});
        call.sessions.push(['talk', await rtcNegotiate('talk', talk, cameraId)]);
      }
      render();
    } catch (error) {
      await hangup();
      throw error.name === 'NotAllowedError' ? new Error('Permissão do microfone negada. Libere o microfone para este site no navegador.') : error;
    }
  }

  async function hangup(message) {
    if (!call) return;
    const ended = call;
    call = null;
    ended.microphone?.stop();
    ended.peers.forEach(pc => pc.close());
    speaker.srcObject = null;
    render();
    if (message) toast(message, true);
    await Promise.all(ended.sessions.map(([kind, session]) => rtcHangup(ended.cameraId, kind, session)));
  }

  button.addEventListener('click', event => action(event.currentTarget, () => call ? hangup() : start()));
  mute.addEventListener('click', () => {
    if (!call?.microphone) return;
    call.microphone.enabled = !call.microphone.enabled;
    render();
  });
  $('#camera-select').addEventListener('change', () => hangup());
  addEventListener('pagehide', () => hangup());
  render();
})();
