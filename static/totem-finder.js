// Totens na rede: procura notebooks com o monitor do Casa Presente, pareia por código e escolhe qual usar.
(() => {
  const list = $('#totem-list'), button = $('#totem-scan'), current = $('#totem-current');
  if (!list || !button) return;
  const esc = text => String(text).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  function describe(url) {
    current.textContent = url ? `Totem em uso: ${url.replace(/^https?:\/\//, '')}` : 'Totem em uso: o notebook da câmera (padrão).';
  }
  function row(totem, active) {
    const where = `${esc(totem.name || 'Totem')} · ${esc(totem.ip)}`;
    if (totem.mine) return `<div class="totem-row"><div><strong>${where}</strong><small>Pareado com este computador${active ? ' · em uso' : ''}</small></div>${active ? '<span class="pill green">Em uso</span>' : `<button type="button" class="button secondary compact" data-use="${esc(totem.ip)}">Usar este</button>`}</div>`;
    if (totem.paired) return `<div class="totem-row"><div><strong>${where}</strong><small>Já pareado com outro computador</small></div><span class="pill neutral">Ocupado</span></div>`;
    return `<div class="totem-row"><div><strong>${where}</strong><small>Novo: digite o código da tela dele</small></div><div class="totem-pair"><input inputmode="numeric" maxlength="7" placeholder="000 000" aria-label="Código do totem ${esc(totem.ip)}" data-code="${esc(totem.ip)}" data-raw><button type="button" class="button primary compact" data-pair="${esc(totem.ip)}">Conectar</button></div></div>`;
  }
  async function scan() {
    list.innerHTML = '<p class="small muted">Procurando na rede… (alguns segundos)</p>';
    const data = await api('/api/notebook/discover', {method: 'POST', signal: AbortSignal.timeout(40000)});
    describe(data.current);
    const activeIp = data.current ? new URL(data.current).hostname : '';
    list.innerHTML = data.totems.length ? data.totems.map(t => row(t, t.ip === activeIp)).join('') : '<p class="small muted">Nenhum totem encontrado. Confira se o notebook está ligado, na mesma rede, e se o serviço casa-monitor está rodando.</p>';
  }
  button.addEventListener('click', () => action(button, scan).catch(() => {}));
  list.addEventListener('click', event => {
    const pair = event.target.closest('[data-pair]'), use = event.target.closest('[data-use]');
    if (pair) {
      const ip = pair.dataset.pair, code = list.querySelector(`[data-code="${CSS.escape(ip)}"]`).value;
      action(pair, async () => {
        await api('/api/notebook/pair', {method: 'POST', body: JSON.stringify({ip, code})});
        toast('Totem conectado.'); await scan();
      });
    }
    if (use) action(use, async () => { await api('/api/notebook/use', {method: 'POST', body: JSON.stringify({ip: use.dataset.use})}); toast('Este painel agora usa esse totem.'); await scan(); });
  });
  document.addEventListener('DOMContentLoaded', () => setTimeout(() => { if (typeof settings !== 'undefined' && settings) describe(settings.notebook_url); }, 1500));
})();
