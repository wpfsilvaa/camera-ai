// Rastreamento e nomes: custo medido do rastreador e o resumo das vezes em que um nome se perdeu.
(() => {
  const $q = sel => document.querySelector(sel);
  const fmt = seconds => seconds == null ? '–' : seconds >= 60 ? `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s` : `${Math.round(seconds)} s`;
  async function loadLosses() {
    const box = $q('#losses-body');
    if (!box) return;
    try {
      const data = await api('/api/recognition/losses?days=3');
      if (!data.total) { box.innerHTML = 'Nenhuma perda de nome registrada nos últimos 3 dias. Quando acontecer, ela aparece aqui com o motivo.'; return; }
      box.innerHTML = `<p><strong>${data.total}</strong> vez(es) um nome se perdeu; em <strong>${data.recovered}</strong> ele voltou (mediana ${fmt(data.median_gap)}).</p>`
        + `<ul class="loss-list">${data.by_reason.map(r => `<li><b>${r.count}×</b> ${escapeHTML(r.label)} <span class="muted">(voltou em ${r.recovered})</span></li>`).join('')}</ul>`
        + (data.by_person.length ? `<p class="muted">Por pessoa: ${data.by_person.map(p => `${escapeHTML(p.name)} (${p.count})`).join(', ')}.</p>` : '');
    } catch { box.textContent = 'Não foi possível carregar agora.'; }
  }
  function cost() {
    const note = $q('#tracker-cost');
    if (!note) return;
    const t = (typeof status !== 'undefined' && status && status.camera && status.camera.tracker) || null;
    if (!t) { note.textContent = ''; return; }
    note.textContent = t.error ? t.error : t.appearance
      ? `Custo medido com a aparência ligada: ${t.ms} ms por quadro no rastreador; a rede rodou ${t.encodes_per_100} vez(es) a cada 100 quadros.`
      : `Rastreador comum: ${t.ms} ms por quadro. Ligue a aparência para comparar.`;
    note.style.color = t.error ? 'var(--amber-ink)' : '';
  }
  document.addEventListener('click', event => { if (event.target.closest('#losses-refresh')) loadLosses(); });
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'settings' && !document.hidden) { cost(); } }, 2000);
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'settings' && !document.hidden && $q('#tracking-panel') && !$q('#tracking-panel').classList.contains('hidden')) loadLosses(); }, 30000);
  window.addEventListener('hashchange', () => setTimeout(loadLosses, 300));
  setTimeout(loadLosses, 1200);
})();
