// Light live video: WebRTC straight from the camera computer (≈450 kbps instead of the server's MJPEG),
// without the detection boxes. Default on phones; the choice is remembered per device.
(() => {
  const video = $('#live-video');
  const remembered = () => { try { return localStorage.getItem('casa-view'); } catch { return null; } };
  let mode = remembered() || (matchMedia('(max-width: 760px)').matches ? 'direct' : 'boxes');
  // The light video exists only for RTSP cameras (it comes from the camera computer's MediaMTX): not for a USB camera.
  const available = () => status?.camera?.light_video === true;
  let session = null;  // {cameraId, pc, id, playing}
  let failedFor = null;  // Camera whose light video failed: show the MJPEG there until the page reloads.

  async function start(cameraId) {
    const pc = new RTCPeerConnection();
    const current = session = {cameraId, pc, id: null, playing: false};
    pc.addTransceiver('video', {direction: 'recvonly'});
    pc.addEventListener('track', event => {
      video.srcObject = event.streams[0] || new MediaStream([event.track]);
      video.play().catch(() => {});
    });
    pc.addEventListener('connectionstatechange', () => {
      if (session === current && pc.connectionState === 'failed') fallback('A conexão do vídeo leve caiu.');
    });
    try {
      current.id = await rtcNegotiate('video', pc, cameraId);
      if (session !== current) rtcHangup(cameraId, 'video', current.id);  // Stopped while negotiating.
    } catch (error) {
      if (session === current) fallback(error.message);
    }
  }

  function stop() {
    if (!session) return;
    const ended = session;
    session = null;
    ended.pc.close();
    video.srcObject = null;
    rtcHangup(ended.cameraId, 'video', ended.id);
    render();
  }

  function fallback(reason) {
    stop();
    failedFor = selectedCamera;
    toast(`${reason} Mostrando o vídeo com detecções.`, true);
    updateStream();
  }

  function render() {
    const playing = Boolean(session?.playing);
    video.classList.toggle('hidden', !playing);
    if (playing) $('#camera-placeholder').classList.add('hidden');
    $$('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === mode)));
    document.querySelector('.view-mode')?.classList.toggle('hidden', !available());
  }

  video.addEventListener('playing', () => { if (session) { session.playing = true; render(); } });

  window.liveVideo = {
    direct: () => mode === 'direct' && available() && failedFor !== selectedCamera,
    playing: () => Boolean(session?.playing),
    // Called by updateStream(): keep the light video running only while it is wanted, for the selected camera.
    show(wanted) {
      render();   // Also shows or hides the selector once the camera's source is known.
      if (session && (!wanted || session.cameraId !== selectedCamera)) stop();
      if (wanted && !session) start(selectedCamera);
    },
  };

  $$('[data-view]').forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.view;
    failedFor = null;
    try { localStorage.setItem('casa-view', mode); } catch {}
    render();
    updateStream();
  }));
  addEventListener('pagehide', stop);
  render();
})();
