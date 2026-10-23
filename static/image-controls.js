// Picture profiles of a USB camera: try one right now, keep the one you like (reapplied every time the camera opens).
(() => {
  const LABELS = {exposure_time_absolute: 'Exposição', gain: 'Ganho', sharpness: 'Nitidez', brightness: 'Brilho', contrast: 'Contraste', focus_absolute: 'Foco (0 = longe)'};
  let state = null;

  const customValues = () => Object.fromEntries([...document.querySelectorAll('#image-custom input[type=range]')].map(input => [input.dataset.key, Number(input.value)]));

  function renderCustom() {
    const box = $('#image-custom');
    box.classList.toggle('hidden', $('#image-profile').value !== 'custom');
    if (box.dataset.ready) return;
    box.dataset.ready = '1';
    const start = {...(state.current || {}), ...(state.custom || {})};
    box.innerHTML = Object.entries(state.custom_keys).map(([key, [low, high]]) => `<label class="image-slider">${LABELS[key] || key}<span><input type="range" min="${low}" max="${high}" step="${key === 'focus_absolute' ? 5 : 1}" value="${start[key] ?? low}" data-key="${key}"><output>${start[key] ?? low}</output></span></label>`).join('');
  }
  document.addEventListener('input', event => {
    const slider = event.target.closest?.('#image-custom input[type=range]');
    if (slider) slider.nextElementSibling.textContent = slider.value;
  });

  function paint() {
    $('#image-unsupported').classList.toggle('hidden', state.supported);
    $('#image-box').classList.toggle('hidden', !state.supported);
    if (!state.supported) return;
    const select = $('#image-profile');
    if (!select.options.length) select.innerHTML = state.profiles.map(p => `<option value="${p.id}">${escapeHTML(p.label)}</option>`).join('');
    if (!select.dataset.touched) select.value = state.profile;
    $('#image-description').textContent = state.profiles.find(p => p.id === select.value)?.description || '';
    const names = {exposure_time_absolute: 'exposição', gain: 'ganho', sharpness: 'nitidez', focus_absolute: 'foco', auto_exposure: 'exposição'};
    const now = state.current || {};
    $('#image-current').textContent = state.current ? `Agora na câmera: exposição ${now.auto_exposure === 1 ? 'manual ' + (now.exposure_time_absolute ?? '?') : 'automática'} · ganho ${now.gain ?? '?'} · nitidez ${now.sharpness ?? '?'} · foco ${now.focus_automatic_continuous ? 'automático' : (now.focus_absolute ?? '?')}.` : '';
    renderCustom();
  }

  async function load() {
    if (!isAdmin() || !$('#image-panel')) return;
    try { state = await api(cameraPath('/api/camera/image')); paint(); } catch { /* the next visit tries again */ }
  }
  window.loadImageControls = load;

  $('#image-profile')?.addEventListener('change', event => { event.target.dataset.touched = '1'; if (state) paint(); });
  const send = (button, save) => action(button, async () => {
    const profile = $('#image-profile').value;
    state = await api(cameraPath('/api/camera/image'), {method: 'POST', body: JSON.stringify({profile, custom: profile === 'custom' ? customValues() : {}, save})});
    delete $('#image-profile').dataset.touched;
    paint();
    toast(save ? 'Perfil guardado e aplicado. Ele será reaplicado toda vez que a câmera abrir.' : `Perfil aplicado na câmera (${state.applied} ajustes). Olhe a imagem ao vivo.`);
  });
  $('#image-test')?.addEventListener('click', event => send(event.currentTarget, false));
  $('#image-save')?.addEventListener('click', event => send(event.currentTarget, true));
})();
