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

  const chip = $('#listen-chip');
  function render() {
    const active = Boolean(call), talking = Boolean(call?.microphone);
    button.innerHTML = talking ? 'Encerrar conversa <span>✕</span>' : active ? 'Conversar <span>🎙</span>' : 'Conversar ao vivo <span>🎙</span>';
    button.classList.toggle('danger-button', talking);
    mute.classList.toggle('hidden', !talking);
    mute.textContent = talking && !call.microphone.enabled ? 'Ligar meu microfone' : 'Silenciar meu microfone';
    note.classList.toggle('hidden', !active);
    if (active) note.textContent = call.muted ? 'Toque em qualquer lugar da tela para ouvir o ambiente.' : talking ? 'Em conversa: você ouve o ambiente e ele ouve você.' : 'Ouvindo o ambiente. Toque em Conversar para falar, ou na imagem para parar de ouvir.';
    if (chip) {
      const label = talking ? 'Em conversa' : active ? 'Ouvindo · toque na imagem para silenciar' : 'Sem som · toque na imagem para ouvir';
      chip.textContent = talking ? '🎙' : active ? '🔊' : '🔇';
      chip.title = label; chip.setAttribute('aria-label', label);
      chip.classList.toggle('live', active);
    }
  }

  // Listening only: the camera computer's microphone, nothing leaves this device.
  async function listen() {
    if (call) return;
    const cameraId = selectedCamera;
    call = {cameraId, peers: [], sessions: []};
    try {
      const pc = new RTCPeerConnection();
      call.peers.push(pc);
      watch(pc);
      pc.addTransceiver('audio', {direction: 'recvonly'});
      pc.addEventListener('track', event => { speaker.srcObject = event.streams[0] || new MediaStream([event.track]); playOrAsk(); });
      call.sessions.push(['listen', await rtcNegotiate('listen', pc, cameraId)]);
      render();
    } catch (error) {
      await hangup();
      throw error;
    }
  }

  // Starts the conversation: adds the microphone (and face) to an existing or new listening session.
  async function start(withFace = false) {
    await listen();
    if (!call || call.microphone) return;
    const cameraId = call.cameraId;
    try {
      // Browsers only release the microphone (and camera) on HTTPS or localhost.
      if (window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
        const audio = {echoCancellation: true, noiseSuppression: true, autoGainControl: true};
        let stream;
        if (withFace) {
          // Whoever answers the notebook's call shows their face on its screen, when they have a camera.
          stream = await navigator.mediaDevices.getUserMedia({audio, video: {width: {ideal: 640}, height: {ideal: 480}, facingMode: 'user'}}).catch(() => null);
        }
        stream = stream || await navigator.mediaDevices.getUserMedia({audio});
        call.microphone = stream.getAudioTracks()[0];
        const talk = new RTCPeerConnection();
        call.peers.push(talk);
        watch(talk);
        talk.addTransceiver(call.microphone, {direction: 'sendonly'});
        call.sessions.push(['talk', await rtcNegotiate('talk', talk, cameraId)]);
        const picture = stream.getVideoTracks()[0];
        if (picture) {
          call.picture = picture;
          const face = new RTCPeerConnection();
          call.peers.push(face);
          face.addTransceiver(picture, {direction: 'sendonly'});
          call.sessions.push(['face', await rtcNegotiate('face', face, cameraId)]);
        }
      } else {
        throw new Error('Para falar é preciso abrir o painel por HTTPS (ou localhost). Ouvir já funciona.');
      }
      render();
    } catch (error) {
      await stopTalking();
      throw error.name === 'NotAllowedError' ? new Error('Permissão do microfone negada. Libere o microfone para este site no navegador.') : error;
    }
  }

  // Ends the conversation but keeps listening to the room.
  async function stopTalking() {
    if (!call) return;
    const ended = call;
    ended.microphone?.stop();
    ended.picture?.stop();
    ended.microphone = ended.picture = undefined;
    const keep = ended.peers[0], gone = ended.sessions.filter(([kind]) => kind !== 'listen');
    ended.peers.slice(1).forEach(pc => pc.close());
    ended.peers = [keep];
    ended.sessions = ended.sessions.filter(([kind]) => kind === 'listen');
    render();
    await Promise.all(gone.map(([kind, session]) => rtcHangup(ended.cameraId, kind, session)));
  }

  async function hangup(message) {
    if (!call) return;
    const ended = call;
    call = null;
    ended.microphone?.stop();
    ended.picture?.stop();
    ended.peers.forEach(pc => pc.close());
    speaker.srcObject = null;
    render();
    if (message) toast(message, true);
    await Promise.all(ended.sessions.map(([kind, session]) => rtcHangup(ended.cameraId, kind, session)));
  }

  button.addEventListener('click', event => action(event.currentTarget, () => call?.microphone ? stopTalking() : start()));
  // Tapping the picture listens to the room; tapping again stops. A conversation is never ended by accident.
  const picture = document.querySelector('.camera-view');
  picture?.addEventListener('click', () => {
    if (!(streamActive || window.liveVideo?.playing()) || call?.microphone) return;
    (call ? hangup() : listen()).catch(error => toast(error.message, true));
  });
  mute.addEventListener('click', () => {
    if (!call?.microphone) return;
    call.microphone.enabled = !call.microphone.enabled;
    render();
  });
  $('#camera-select').addEventListener('change', () => hangup());
  addEventListener('pagehide', () => hangup());
  render();
  window.intercom = {start, listen, hangup, active: () => Boolean(call)};
})();
