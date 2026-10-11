// Camera selector: a button that opens a menu of thumbnails (a still of each camera, refreshed every minute while open).
// The hidden <select id="camera-select"> keeps the state the rest of the dashboard already reads.
(() => {
  const button = $('#camera-picker'), menu = $('#camera-menu'), cardsBox = $('#camera-cards'), select = $('#camera-select');
  const STATE = {online: 'Ao vivo', paused: 'Pausada', offline: 'Sem sinal', connecting: 'Conectando'};
  let refreshTimer = null;

  const isOpen = () => !menu.classList.contains('hidden');
  const cameras = () => (typeof knownCameras !== 'undefined' && knownCameras.length ? knownCameras : [{id: select.value || 'main', name: select.selectedOptions[0]?.textContent || 'Câmera', state: 'online'}]);

  function thumbnail(camera, fresh) {
    const img = cardsBox.querySelector(`[data-camera="${camera.id}"] img`), card = cardsBox.querySelector(`[data-camera="${camera.id}"]`);
    if (!img) return;
    const live = camera.state === 'online';
    card.classList.toggle('offline', !live);
    if (live && fresh) img.src = `/api/snapshot?camera_id=${encodeURIComponent(camera.id)}&t=${Date.now()}`;
    if (!live) img.removeAttribute('src');
  }

  function render(fresh = false) {
    const list = cameras(), current = select.value;
    $('#camera-picker-name').textContent = list.find(c => c.id === current)?.name || select.selectedOptions[0]?.textContent || 'Câmera';
    button.disabled = select.disabled;
    if (!isOpen()) return;
    const signature = list.map(c => `${c.id}|${c.name}`).join(',');
    if (menu.dataset.signature !== signature) {
      menu.dataset.signature = signature;
      cardsBox.innerHTML = list.map(c => `<button type="button" role="option" class="camera-card" data-camera="${escapeHTML(c.id)}"><span class="thumb"><img alt="" decoding="async"><span class="thumb-off"></span></span><strong>${escapeHTML(c.name)}</strong><small></small></button>`).join('');
      fresh = true;
    }
    for (const camera of list) {
      const card = cardsBox.querySelector(`[data-camera="${camera.id}"]`);
      card.setAttribute('aria-selected', String(camera.id === current));
      card.classList.toggle('selected', camera.id === current);
      card.querySelector('small').textContent = (STATE[camera.state] || '') + (camera.manual_recording ? ' · gravando' : '');
      card.querySelector('.thumb-off').textContent = STATE[camera.state] || '';
      thumbnail(camera, fresh);
    }
  }

  function open() {
    menu.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
    menu.dataset.signature = '';
    render(true);
    clearInterval(refreshTimer);
    refreshTimer = setInterval(() => { if (isOpen() && !document.hidden) render(true); }, 60000);   // A new still every minute.
    cardsBox.querySelector('.selected, .camera-card')?.focus();
  }

  function close(focus = false) {
    menu.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
    clearInterval(refreshTimer);
    if (focus) button.focus();
  }

  function choose(id) {
    close(true);
    if (id === select.value) return;
    select.value = id;
    select.dispatchEvent(new Event('change', {bubbles: true}));   // The dashboard (and the call code) already listen to this.
    render();
  }

  button.addEventListener('click', () => (isOpen() ? close() : open()));
  menu.addEventListener('click', event => { if (event.target.closest('.camera-actions button:not(:disabled)')) { close(); return; } const card = event.target.closest('[data-camera]'); if (card) choose(card.dataset.camera); });
  document.addEventListener('click', event => { if (isOpen() && !event.target.closest('.camera-picker')) close(); });
  document.addEventListener('keydown', event => {
    if (!isOpen()) return;
    if (event.key === 'Escape') { close(true); return; }
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      const cards = [...cardsBox.querySelectorAll('.camera-card')], at = cards.indexOf(document.activeElement);
      cards[(at + (event.key === 'ArrowRight' ? 1 : -1) + cards.length) % cards.length]?.focus();
      event.preventDefault();
    }
  });
  window.cameraPickerSync = () => render(false);
  render();
})();
