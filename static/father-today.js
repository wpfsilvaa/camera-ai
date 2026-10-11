// "O pai hoje": how many times he showed up and went to each restricted area (fridge, cupboard…), with the times, plus the last 7 days.
const fatherClock = seconds => new Date(seconds * 1000).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});

function renderFatherToday(data) {
  const {sightings, areas} = data.today, week = data.week;
  const chips = times => times.length ? times.map(t => `<span class="time-chip">${fatherClock(t)}</span>`).join('') : '<span class="muted small">Nenhuma ainda.</span>';
  $('#father-sightings').textContent = sightings.length;
  $('#father-sightings-times').innerHTML = chips(sightings.map(s => s.started));
  // Every area with visits today, plus the ones named in the settings (so an area nobody used yet still shows 0).
  const configured = (typeof settings !== 'undefined' && settings?.restricted_enabled ? (settings.restricted_zone_names || []).filter(Boolean) : []);
  const names = [...new Set([...Object.keys(areas), ...configured])];
  $('#father-areas').innerHTML = names.map(name => `<div class="father-row"><div class="father-count"><strong>${(areas[name] || []).length}</strong><span>idas: ${escapeHTML(name)}</span></div><div class="time-chips area-chips">${chips(areas[name] || [])}</div></div>`).join('');
  const previous = week.slice(0, -1), average = key => Math.round(previous.reduce((sum, day) => sum + day[key], 0) / Math.max(1, previous.length));
  const totalToday = Object.values(areas).reduce((sum, times) => sum + times.length, 0);
  $('#father-today-note').textContent = `Nos 6 dias anteriores: média de ${average('sightings')} vez(es) na câmera${totalToday || average('visits') ? ` e ${average('visits')} ida(s) às áreas marcadas` : ''}.`;
  const top = Math.max(1, ...week.map(day => Math.max(day.sightings, day.visits)));
  $('#father-week').innerHTML = week.map(day => {
    const label = new Date(day.day + 'T12:00:00').toLocaleDateString('pt-BR', {weekday: 'short'}).replace('.', '');
    const detail = Object.entries(day.areas).map(([name, count]) => `${name}: ${count}`).join(', ');
    return `<div class="week-day" title="${day.sightings} na câmera${detail ? `; ${detail}` : ''}"><div class="week-bar"><i style="height:${Math.round(day.sightings / top * 100)}%"></i><b style="height:${Math.round(day.visits / top * 100)}%"></b></div><span>${label}</span></div>`;
  }).join('') + '<div class="week-legend"><i></i> na câmera <b></b> áreas marcadas</div>';
}

async function loadFatherToday() {
  try { renderFatherToday(await api('/api/father/today')); } catch { /* the next refresh tries again */ }
}
window.loadFatherToday = loadFatherToday;
document.addEventListener('DOMContentLoaded', loadFatherToday);
setInterval(() => { if (activePage === 'overview' && !document.hidden) loadFatherToday(); }, 30000);
