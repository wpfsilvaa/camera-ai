// Picture profiles of a USB camera: a live preview, try a profile right now, and choose how it is picked (always the same, by the hour, or by brightness).
(() => {
  const LABELS = {exposure_time_absolute: 'Exposição', gain: 'Ganho', sharpness: 'Nitidez', brightness: 'Brilho', contrast: 'Contraste', focus_absolute: 'Foco (0 = longe)'};
  const HELP = {fixed: 'O perfil escolhido abaixo fica sempre ligado.', schedule: 'Um perfil para cada faixa de horas (por exemplo, noite, manhã e tarde).', adaptive: 'A câmera troca de perfil sozinha conforme a imagem fica mais clara ou mais escura.'};
  const RUNGS = ['Cena muito clara', 'Cena média', 'Cena escura'];
  let state = null, rules = [], ladder = [], dirty = false;

  const profileOptions = selected => state.profiles.map(p => `<option value="${p.id}" ${p.id === selected ? 'selected' : ''}>${escapeHTML(p.label)}</option>`).join('');
  const hourOptions = selected => Array.from({length: 24}, (_, h) => `<option value="${h}" ${h === selected ? 'selected' : ''}>${String(h).padStart(2, '0')}h</option>`).join('');
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

  function renderRules() {
    $('#image-rules').innerHTML = rules.map((rule, i) => `<div class="image-rule" data-rule="${i}"><select data-field="start" aria-label="De">${hourOptions(rule.start)}</select><span>até</span><select data-field="end" aria-label="Até">${hourOptions(rule.end)}</select><select data-field="profile" aria-label="Perfil">${profileOptions(rule.profile)}</select><button type="button" class="text-button danger" data-remove-rule="${i}" aria-label="Remover horário">✕</button></div>`).join('') || '<p class="muted small">Nenhum horário ainda.</p>';
  }
  function renderLadder() {
    $('#image-ladder').innerHTML = ladder.map((name, i) => `<div class="image-rule"><span class="rung">${RUNGS[Math.min(i, RUNGS.length - 1)] || `Degrau ${i + 1}`}</span><select data-rung="${i}">${profileOptions(name)}</select></div>`).join('');
  }

  function paintMode() {
    const mode = $('#image-mode').value;
    $('#image-mode-help').textContent = HELP[mode];
    $('#image-schedule-box').classList.toggle('hidden', mode !== 'schedule');
    $('#image-ladder-box').classList.toggle('hidden', mode !== 'adaptive');
  }

  function paint() {
    $('#image-unsupported').classList.toggle('hidden', state.supported);
    $('#image-box').classList.toggle('hidden', !state.supported);
    if (!state.supported) return;
    const profile = $('#image-profile');
    if (!dirty) {   // Do not overwrite what is being edited with the saved values.
      profile.innerHTML = profileOptions(state.profile);
      $('#image-mode').value = state.mode;
      rules = state.schedule.map(r => ({...r}));
      ladder = [...state.ladder];
      renderRules(); renderLadder();
    } else if (!profile.options.length) profile.innerHTML = profileOptions(state.profile);
    $('#image-description').textContent = state.profiles.find(p => p.id === profile.value)?.description || '';
    const now = state.current || {};
    const active = state.profiles.find(p => p.id === state.active)?.label;
    $('#image-current').textContent = state.current ? `${active && state.mode !== 'fixed' ? `Perfil ativo agora: ${active}. ` : ''}Na câmera: exposição ${now.auto_exposure === 1 ? 'manual ' + (now.exposure_time_absolute ?? '?') : 'automática'} · ganho ${now.gain ?? '?'} · nitidez ${now.sharpness ?? '?'} · foco ${now.focus_automatic_continuous ? 'automático' : (now.focus_absolute ?? '?')}.` : '';
    $('#image-luma').textContent = state.luma != null ? `Brilho medido da imagem: ${state.luma} (faixa boa: 70 a 185).` : '';
    paintMode(); renderCustom();
  }

  async function load() {
    if (!isAdmin() || !$('#image-panel')) return;
    try { state = await api(cameraPath('/api/camera/image')); paint(); } catch { /* the next visit tries again */ }
  }
  window.loadImageControls = load;

  // The live picture is only fetched while this page is open and visible.
  function previewTick() {
    const image = $('#image-preview');
    if (!image) return;
    const wanted = activePage === 'settings' && !document.hidden && state?.supported;
    if (wanted && !image.getAttribute('src')) image.src = cameraPath(`/api/stream.mjpeg?t=${Date.now()}`);
    if (!wanted && image.getAttribute('src')) image.removeAttribute('src');
  }
  $('#image-preview')?.addEventListener('error', () => { $('#image-preview-note').classList.remove('hidden'); $('#image-preview').removeAttribute('src'); setTimeout(() => { $('#image-preview-note')?.classList.add('hidden'); }, 8000); });
  setInterval(() => { previewTick(); if (activePage === 'settings' && !document.hidden && state?.supported) load(); }, 4000);
  window.addEventListener('hashchange', () => setTimeout(previewTick, 100));

  const touch = () => { dirty = true; };
  $('#image-profile')?.addEventListener('change', () => { touch(); if (state) paint(); });
  $('#image-mode')?.addEventListener('change', () => { touch(); paintMode(); });
  $('#image-custom')?.addEventListener('input', touch);
  $('#image-rules')?.addEventListener('change', event => {
    const field = event.target.dataset.field, row = event.target.closest('[data-rule]');
    if (field && row) { rules[Number(row.dataset.rule)][field] = field === 'profile' ? event.target.value : Number(event.target.value); touch(); }
  });
  $('#image-rules')?.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-rule]');
    if (remove) { rules.splice(Number(remove.dataset.removeRule), 1); touch(); renderRules(); }
  });
  $('#image-add-rule')?.addEventListener('click', () => { if (rules.length < 8) { rules.push({start: 6, end: 18, profile: 'balanced'}); touch(); renderRules(); } });
  $('#image-ladder')?.addEventListener('change', event => { const rung = event.target.dataset.rung; if (rung !== undefined) { ladder[Number(rung)] = event.target.value; touch(); } });

  const send = (button, save) => action(button, async () => {
    const profile = $('#image-profile').value;
    state = await api(cameraPath('/api/camera/image'), {method: 'POST', body: JSON.stringify({profile, custom: profile === 'custom' ? customValues() : {}, save,
      ...(save ? {mode: $('#image-mode').value, schedule: rules, ladder} : {})})});
    if (save) dirty = false;
    paint();
    toast(save ? 'Salvo. As regras serão aplicadas toda vez que a câmera abrir.' : `Perfil aplicado na câmera (${state.applied} ajustes). As regras automáticas ficam pausadas por 2 minutos.`);
  });
  $('#image-test')?.addEventListener('click', event => send(event.currentTarget, false));
  $('#image-save')?.addEventListener('click', event => send(event.currentTarget, true));
})();
