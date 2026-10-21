// "Saúde": every component with a colour and what to do about it. The overview only shows a small chip.
(() => {
  const NAMES = {ok: 'Funcionando', info: 'Desligado', warn: 'Atenção', error: 'Problema'};
  let timer = null;

  function paint(report) {
    const level = report.level === 'info' ? 'ok' : report.level;
    for (const dot of document.querySelectorAll('.health-dot')) dot.dataset.level = level;
    const chip = $('#health-chip');
    // Quiet when everything is fine: the chip only appears when something needs a look.
    chip.classList.toggle('hidden', level === 'ok');
    chip.dataset.level = level;
    $('#health-chip-text').textContent = level === 'ok' ? '' : `Sistema: ${report.summary} Toque para ver.`;
    if (activePage !== 'health') return;
    $('#health-summary').textContent = report.summary;
    $('#health-list').innerHTML = report.items.map(item => `<article class="health-item" data-level="${item.level}"><span class="health-dot" data-level="${item.level === 'info' ? 'off' : item.level}"></span><div><strong>${escapeHTML(item.title)}</strong> <span class="pill ${item.level === 'ok' ? 'green' : item.level === 'warn' ? 'amber' : item.level === 'error' ? 'red' : 'neutral'}">${NAMES[item.level]}</span><p class="small">${escapeHTML(item.detail)}</p>${item.hint ? `<p class="small muted">→ ${escapeHTML(item.hint)}</p>` : ''}</div></article>`).join('');
    const hours = Math.floor(report.uptime / 3600), minutes = Math.floor(report.uptime % 3600 / 60);
    $('#health-uptime').textContent = `Programa ligado há ${hours ? `${hours} h ` : ''}${minutes} min.`;
  }

  async function loadHealth() {
    try { paint(await api('/api/health/report')); } catch { /* the next round tries again */ }
  }
  window.loadHealth = loadHealth;
  document.addEventListener('DOMContentLoaded', () => setTimeout(loadHealth, 1200));
  clearInterval(timer);
  timer = setInterval(() => { if (!document.hidden) loadHealth(); }, 30000);
})();
