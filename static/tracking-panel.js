// Rastreamento e nomes: custo medido do rastreador e o resumo das vezes em que um nome se perdeu.
(() => {
  const $q = sel => document.querySelector(sel);
  const fmt = seconds => seconds == null ? '–' : seconds >= 60 ? `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s` : `${Math.round(seconds)} s`;
  async function loadLosses() {
    const box = $q('#losses-body');
    if (!box) return;
    try {
      const data = await api('/api/recognition/losses?days=3');
      const changes = (data.clothes_changes || []).length
        ? `<p class="muted">Trocas de roupa percebidas (a roupa nova foi aprendida na hora): ${data.clothes_changes.map(c => `${escapeHTML(c.name)} às ${new Date(c.at * 1000).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'})}`).join(', ')}.</p>` : '';
      if (!data.total) { box.innerHTML = 'Nenhuma perda de nome registrada nos últimos 3 dias. Quando acontecer, ela aparece aqui com o motivo.' + changes; return; }
      box.innerHTML = `<p><strong>${data.total}</strong> vez(es) um nome se perdeu; em <strong>${data.recovered}</strong> ele voltou (mediana ${fmt(data.median_gap)}).</p>`
        + `<ul class="loss-list">${data.by_reason.map(r => `<li><b>${r.count}×</b> ${escapeHTML(r.label)} <span class="muted">(voltou em ${r.recovered})</span></li>`).join('')}</ul>`
        + (data.by_person.length ? `<p class="muted">Por pessoa: ${data.by_person.map(p => `${escapeHTML(p.name)} (${p.count})`).join(', ')}.</p>` : '') + changes;
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
  async function anchors() {
    const line = $q('#anchors-line');
    if (!line) return;
    try {
      const list = (await api('/api/people')).body_anchors || [];
      line.innerHTML = list.length
        ? `<strong>Âncoras de roupa de hoje:</strong> ${list.map(a => `${escapeHTML(a.name)} (${a.count} referência(s), a mais recente há ${fmt(a.newest_seconds)})`).join('; ')}. Quando o rosto aparece, por exemplo ao olhar para a tela do totem, as referências se renovam e a roupa passa a reconhecer a pessoa mesmo de costas.`
        : '<strong>Âncoras de roupa de hoje:</strong> nenhuma ainda. Assim que um rosto for reconhecido (por exemplo, quando ele olhar para a tela do totem), a roupa de hoje vira referência para reconhecer de costas.';
    } catch { line.textContent = ''; }
  }
  document.addEventListener('click', event => { if (event.target.closest('#losses-refresh')) loadLosses(); });
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'settings' && !document.hidden) anchors(); }, 10000);
  setTimeout(anchors, 1500);
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'settings' && !document.hidden) { cost(); } }, 2000);
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'settings' && !document.hidden && $q('#tracking-panel') && !$q('#tracking-panel').classList.contains('hidden')) loadLosses(); }, 30000);
  window.addEventListener('hashchange', () => setTimeout(loadLosses, 300));
  setTimeout(loadLosses, 1200);
})();
