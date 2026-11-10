// Assistente de primeira configuração: relação, câmera, aviso e administrador. Aparece só em instalação nova.
(() => {
  const dialog = $('#setup-dialog'), banner = $('#setup-banner');
  if (!dialog || !banner) return;
  const titles = ['Quem a casa acompanha', 'Conectar a câmera', 'Quem recebe os avisos', 'Senha do administrador'];
  const TOTAL = titles.length;
  let step = 1, loginAlreadyRequired = false;
  const err = message => { const box = $('#setup-error'); box.textContent = message || ''; box.classList.toggle('hidden', !message); };
  const put = changes => api('/api/settings', {method: 'PUT', body: JSON.stringify({...settings, ...changes})}).then(next => { settings = next; return next; });

  function show(n) {
    step = n; err('');
    $$('.setup-step').forEach(el => el.classList.toggle('hidden', Number(el.dataset.step) !== n));
    $('#setup-step-label').textContent = `PASSO ${n} DE ${TOTAL}`;
    $('#setup-title').textContent = titles[n - 1];
    $('#setup-back').classList.toggle('hidden', n === 1);
    $('#setup-skip').classList.toggle('hidden', n !== 3);
    $('#setup-next').textContent = n === TOTAL ? (loginAlreadyRequired ? 'Concluir' : 'Criar administrador e concluir') : 'Continuar';
  }
  async function next() {
    err('');
    try {
      if (step === 1) await put({elder_relation: $('#setup-relation').value});
      if (step === 2) {
        const source = $('#setup-camera-source').value.trim();
        if (!source) throw new Error('Informe o endereço da câmera (ou pule este passo editando depois em Configurações).');
        await put({camera_source: source, camera_name: $('#setup-camera-name').value.trim() || 'Cozinha', enabled: true});
      }
      if (step === 3) { const phone = $('#setup-recipient').value.trim(); if (phone) await put({recipient: phone}); }
      if (step === TOTAL) return await finish();
      show(step + 1);
    } catch (error) { err(error.message); }
  }
  async function finish() {
    const name = $('#setup-admin-name').value.trim(), username = $('#setup-admin-user').value.trim(), password = $('#setup-admin-pass').value;
    if (!loginAlreadyRequired) {
      if (!username || password.length < 8) throw new Error('Informe um usuário e uma senha de pelo menos 8 caracteres.');
      await put({setup_done: true});
      await api('/api/users', {method: 'POST', body: JSON.stringify({name: name || username, username, password, role: 'admin'})});
      location.href = '/login';
      return;
    }
    await put({setup_done: true});
    dialog.close(); banner.classList.add('hidden'); toast('Tudo pronto.');
  }
  async function testCamera() {
    const result = $('#setup-camera-result'), source = $('#setup-camera-source').value.trim();
    if (!source) { result.textContent = 'Informe o endereço primeiro.'; return; }
    result.textContent = 'Conectando…';
    try {
      await put({camera_source: source, camera_name: $('#setup-camera-name').value.trim() || 'Cozinha', enabled: true});
      for (let i = 0; i < 15; i++) {
        await new Promise(r => setTimeout(r, 1000));
        const camera = (await api('/api/status')).camera;
        if (camera.state === 'online') { result.textContent = '✓ Câmera conectada.'; return; }
        if (camera.state === 'offline' && camera.error && i > 3) { result.textContent = `Não conectou: ${camera.error}`; return; }
      }
      result.textContent = 'Ainda sem imagem. Confira o endereço, o usuário e a senha da câmera.';
    } catch (error) { result.textContent = error.message; }
  }
  async function refreshBanner() {
    try {
      const me = await api('/api/auth/me');
      loginAlreadyRequired = Boolean(me.enabled);
      const needed = settings && settings.setup_done === false && (!me.enabled || me.user?.role === 'admin');
      banner.classList.toggle('hidden', !needed);
    } catch { /* sem conexão: o aviso de conexão já cobre */ }
  }
  $('#setup-start').addEventListener('click', () => { $('#setup-relation').value = settings.elder_relation || 'pai'; show(1); dialog.showModal(); });
  $('#setup-close').addEventListener('click', () => dialog.close());
  $('#setup-back').addEventListener('click', () => show(Math.max(1, step - 1)));
  $('#setup-skip').addEventListener('click', () => show(step + 1));
  $('#setup-next').addEventListener('click', event => action(event.currentTarget, next));
  $('#setup-camera-test').addEventListener('click', event => action(event.currentTarget, testCamera));
  window.refreshSetupBanner = refreshBanner;
  document.addEventListener('DOMContentLoaded', () => setTimeout(refreshBanner, 1500));
})();
