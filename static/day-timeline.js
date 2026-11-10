// Linha do tempo de hoje: cada registro de presença como uma marca no dia (0 h a 24 h), colorida pela identificação.
(() => {
  const panel = document.querySelector('#day-timeline');
  if (!panel) return;
  const kinds = {father: ['Meu pai', 'ok'], unknown: ['A identificar', 'warn'], other: ['Outra pessoa', 'off']};
  const clock = seconds => new Date(seconds * 1000).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
  function render(events) {
    const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
    const start = midnight.getTime() / 1000, day = 86400;
    const today = events.filter(e => e.started >= start).sort((a, b) => a.started - b.started);
    const nowPct = Math.min(100, (Date.now() / 1000 - start) / day * 100);
    const marks = today.map(e => {
      const left = Math.min(99.2, (e.started - start) / day * 100);
      const width = Math.max(.7, ((e.ended || Date.now() / 1000) - e.started) / day * 100);
      const [label, tone] = kinds[e.identity] || kinds.other;
      const name = e.person_name && e.identity !== 'unknown' ? e.person_name : label;
      return `<button type="button" class="tl-mark ${tone}" data-event="${e.id}" data-left="${left}" data-width="${width}" aria-label="${clock(e.started)}, ${name}" title="${clock(e.started)} · ${name}"></button>`;
    }).join('');
    const ticks = [0, 6, 12, 18, 24].map(h => `<span data-left="${h / 24 * 100}">${h}h</span>`).join('');
    const counts = Object.keys(kinds).map(k => [k, today.filter(e => (kinds[e.identity] ? e.identity : 'other') === k).length]).filter(([, n]) => n);
    panel.querySelector('.tl-track').innerHTML = `<div class="tl-now" data-left="${nowPct}"></div>${marks}`;
    panel.querySelector('.tl-ticks').innerHTML = ticks;
    panel.querySelector('#day-timeline-note').textContent = today.length ? `${today.length} registro(s) · último às ${clock(today[today.length - 1].started)}` : 'Nenhum registro hoje';
    // A política de segurança (CSP) bloqueia style="" no HTML; a posição é aplicada por script.
    panel.querySelectorAll('[data-left]').forEach(el => { el.style.left = `${el.dataset.left}%`; if (el.dataset.width) el.style.width = `${el.dataset.width}%`; });
    panel.querySelector('.tl-legend').innerHTML = counts.map(([k, n]) => `<span><i class="tl-key ${kinds[k][1]}"></i>${kinds[k][0]} (${n})</span>`).join('');
  }
  async function load() {
    try { render((await api('/api/events?limit=100')).events); } catch { /* o aviso de conexão já cobre */ }
  }
  window.loadDayTimeline = load;
  document.addEventListener('DOMContentLoaded', load);
  setInterval(() => { if (activePage === 'overview' && !document.hidden) load(); }, 30000);
})();
