// Tendências: idas à geladeira por parte do dia e tempo na câmera, dia a dia, com a comparação da semana.
(() => {
  const $q = sel => document.querySelector(sel);
  const PERIODS = ['madrugada', 'manha', 'tarde', 'noite'], NAMES = {madrugada: 'Madrugada', manha: 'Manhã', tarde: 'Tarde', noite: 'Noite'};
  let days = 14;
  const clock = ts => ts ? new Date(ts * 1000).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'}) : '–';
  const hours = minutes => minutes >= 60 ? `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${String(minutes % 60).padStart(2, '0')} min` : ''}` : `${minutes} min`;
  const label = (day, count, today) => {
    const date = new Date(day + 'T12:00:00');
    return today ? 'hoje' : count > 14 ? String(date.getDate()) : date.toLocaleDateString('pt-BR', {weekday: 'short'}).replace('.', '');
  };
  const niceMax = value => { const steps = [2, 4, 5, 8, 10, 15, 20, 30, 40, 50, 80, 100, 150, 200]; return steps.find(step => step >= value) || Math.ceil(value / 50) * 50; };

  function bars(series, {value, stack, unit, ariaLabel, titleOf}) {
    const W = 640, H = 190, left = 30, bottom = 24, top = 8, count = series.length, step = (W - left) / count, width = Math.max(6, step * .6);
    const max = niceMax(Math.max(1, ...series.map(value))), scale = (H - bottom - top) / max;
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" role="img" aria-label="${escapeHTML(ariaLabel)}">`;
    for (const tick of [0, max / 2, max]) {
      const y = H - bottom - tick * scale;
      svg += `<line class="grid" x1="${left}" x2="${W}" y1="${y}" y2="${y}"/><text class="axis" x="${left - 5}" y="${y + 3}" text-anchor="end">${Number.isInteger(tick) ? tick : tick.toFixed(1)}</text>`;
    }
    series.forEach((row, index) => {
      const x = left + index * step + (step - width) / 2, today = index === count - 1;
      let y = H - bottom;
      const parts = stack ? PERIODS.map(name => [name, row.periods[name]]) : [['single', value(row)]];
      for (const [name, amount] of parts) {
        if (!amount) continue;
        const height = amount * scale;
        y -= height;
        svg += `<rect class="bar p-${name}${today ? ' today' : ''}" x="${x}" y="${y}" width="${width}" height="${Math.max(1, height - (stack ? 1 : 0))}" rx="2"><title>${escapeHTML(titleOf(row, name, amount))}</title></rect>`;
      }
      if (!value(row)) svg += `<rect class="empty" x="${x}" y="${H - bottom - 2}" width="${width}" height="2"/>`;
      if (count <= 14 || index % 2 === 0 || today) svg += `<text class="axis${today ? ' now' : ''}" x="${x + width / 2}" y="${H - 8}" text-anchor="middle">${label(row.day, count, today)}</text>`;
    });
    return svg + '</svg>';
  }

  function delta(now, before, {good = null, unit = ''} = {}) {
    const diff = now - before;
    if (!diff) return '<span class="delta">igual à semana anterior</span>';
    const worse = good === 'down' ? diff > 0 : good === 'up' ? diff < 0 : false;
    return `<span class="delta${worse ? ' worse' : ''}">${diff > 0 ? '+' : '−'}${unit === 'min' ? hours(Math.abs(diff)) : Math.abs(diff)} em relação à semana anterior</span>`;
  }

  function render(data) {
    const series = data.days, totalVisits = series.reduce((sum, row) => sum + row.visits, 0), totalMinutes = series.reduce((sum, row) => sum + row.minutes, 0);
    const c = data.compare;
    $q('#trend-compare').innerHTML = c ? `<div class="chip-stat"><b>${c.visits.now}</b> idas à geladeira nos últimos 7 dias ${delta(c.visits.now, c.visits.before, {good: 'down'})}</div>`
      + `<div class="chip-stat"><b>${c.madrugada.now}</b> de madrugada ${delta(c.madrugada.now, c.madrugada.before, {good: 'down'})}</div>`
      + `<div class="chip-stat"><b>${hours(c.minutes.now)}</b> na câmera ${delta(c.minutes.now, c.minutes.before, {unit: 'min'})}</div>`
      : `<div class="chip-stat"><b>${totalVisits}</b> idas à geladeira em ${series.length} dias</div><div class="chip-stat"><b>${hours(totalMinutes)}</b> na câmera</div>`;
    $q('#trend-visits').innerHTML = totalVisits ? bars(series, {value: row => row.visits, stack: true, ariaLabel: `Idas à geladeira por dia nos últimos ${series.length} dias: ${totalVisits} no total.`,
      titleOf: (row, name, amount) => `${new Date(row.day + 'T12:00:00').toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'})}: ${amount} (${NAMES[name].toLowerCase()}), ${row.visits} no dia`}) : '<p class="muted small trend-empty">Ainda sem idas registradas nestes dias.</p>';
    $q('#trend-legend').classList.toggle('hidden', !totalVisits);
    $q('#trend-minutes').innerHTML = totalMinutes ? bars(series, {value: row => Math.round(row.minutes / 6) / 10, stack: false, ariaLabel: `Tempo na câmera por dia nos últimos ${series.length} dias: ${hours(totalMinutes)} no total.`,
      titleOf: row => `${new Date(row.day + 'T12:00:00').toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'})}: ${hours(row.minutes)} na câmera`}) : '<p class="muted small trend-empty">Ainda sem presença registrada nestes dias.</p>';
    $q('#trend-rows').innerHTML = [...series].reverse().map(row => `<tr><td>${new Date(row.day + 'T12:00:00').toLocaleDateString('pt-BR', {weekday: 'short', day: '2-digit', month: '2-digit'})}</td><td><strong>${row.visits}</strong></td>${PERIODS.map(name => `<td>${row.periods[name]}</td>`).join('')}<td>${row.minutes ? hours(row.minutes) : '–'}</td><td>${clock(row.first)}</td><td>${clock(row.last)}</td></tr>`).join('');
    $q('#trend-note').textContent = 'Conta as idas do pai (confirmadas ou ainda sem identificação, sem as marcadas como outra pessoa) e o tempo em que ele aparece na câmera. Hoje ainda está em andamento.';
  }

  async function load() {
    if (!$q('#trends-panel')) return;
    try { render(await api(`/api/father/trends?days=${days}`)); } catch { /* the next visit tries again */ }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-trend-days]');
    if (!button) return;
    days = Number(button.dataset.trendDays);
    document.querySelectorAll('[data-trend-days]').forEach(b => b.classList.toggle('active', b === button));
    load();
  });
  window.loadTrends = load;
  document.addEventListener('DOMContentLoaded', load);
  setInterval(() => { if (typeof activePage !== 'undefined' && activePage === 'overview' && !document.hidden) load(); }, 300000);
  window.addEventListener('hashchange', () => setTimeout(load, 300));
})();
