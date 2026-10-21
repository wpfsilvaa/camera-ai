// "O pai hoje": how many times he showed up and went to each restricted area (fridge, cupboard…), with the times, plus the last 7 days.
const fatherClock = seconds => new Date(seconds * 1000).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});

function renderFatherToday(data) {
  const {sightings, areas} = data.today, week = data.week;
  const chips = times => times.length ? times.map(t => `<span class="time-chip">${fatherClock(t)}</span>`).join('') : '<span class="muted small">Nenhuma ainda.</span>';
  $('#father-sightings').textContent = sightings.length;
  const watched = data.today.people || [];
  $('#father-today h2').textContent = watched.length > 1 ? 'Acompanhados hoje' : `${watched[0]?.name || 'O pai'} hoje`;
  $('#father-people').innerHTML = watched.length > 1 ? watched.map(p => `<span class="pill neutral">${escapeHTML(p.name)}: ${p.sightings}</span>`).join(' ') : '';
  $('#father-sightings-times').innerHTML = chips(sightings.map(s => s.started));
  // Every area with visits today, plus the ones named in the settings (so an area nobody used yet still shows 0).
  const configured = (typeof settings !== 'undefined' && settings?.restricted_enabled ? (settings.restricted_zone_names || []).filter(Boolean) : []);
  const names = [...new Set([...Object.keys(areas), ...configured])];
  $('#father-areas').innerHTML = names.map(name => `<div class="father-row"><div class="father-count"><strong>${(areas[name] || []).length}</strong><span>idas: ${escapeHTML(name)}</span></div><div class="time-chips area-chips">${chips(areas[name] || [])}</div></div>`).join('');
  const previous = week.slice(0, -1), average = key => Math.round(previous.reduce((sum, day) => sum + day[key], 0) / Math.max(1, previous.length));
  const totalToday = Object.values(areas).reduce((sum, times) => sum + times.length, 0);
  $('#father-today-note').textContent = `Nos 6 dias anteriores: média de ${average('sightings')} vez(es) na câmera${totalToday || average('visits') ? ` e ${average('visits')} ida(s) às áreas marcadas` : ''}.`;
  const others = data.today.others || {family: 0, unknown: 0};
  $('#father-others').textContent = others.family || others.unknown ? `Fora da contagem hoje: ${others.family} da família · ${others.unknown} sem identificação.` : '';
  $('#review-visits').classList.toggle('hidden', !data.pending || !isAdmin());
  $('#review-visits').textContent = `Revisar idas sem identificação (${data.pending || 0})`;
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

// Triage of the visits nobody could place: one tap says whether it was the father.
async function loadVisitReview() {
  const [items, calibration] = await Promise.all([api('/api/father/visits'), api('/api/father/calibration')]);
  const hint = calibration.suggested
    ? `Com ${calibration.father + calibration.other} respostas suas, o tempo mínimo que melhor separa é ${String(calibration.suggested.seconds).replace('.', ',')} s (hoje: ${String(calibration.current).replace('.', ',')} s): tira ${Math.round(calibration.suggested.others_removed * 100)}% das idas “Não foi” e mantém ${Math.round(calibration.suggested.father_kept * 100)}% das dele. <button type="button" class="text-button" data-apply-min="${calibration.suggested.seconds}">Aplicar</button>`
    : `Responda pelo menos 5 “Foi ele” e 5 “Não foi” para o sistema sugerir o tempo mínimo ideal (agora: ${calibration.father} e ${calibration.other}).`;
  $('#visits-calibration').innerHTML = hint;
  $('#visits-empty').classList.toggle('hidden', items.length > 0);
  $('#visits-list').innerHTML = items.map(item => `<article class="example-card" data-visit="${item.id}">${item.photo ? `<img class="example-photo" style="height:150px" src="${item.photo.startsWith('visit-') ? '/visit-media/' : '/media/'}${item.photo}.jpg" alt="Momento da ida" loading="lazy">` : '<div class="muted small">Sem foto deste momento.</div>'}<strong>${escapeHTML(item.area)}</strong><small>${day(item.started)} às ${time(item.started)}</small><div class="label-buttons"><button class="button primary compact" data-verdict="father">Foi ele</button><button class="button secondary compact" data-verdict="other">Não foi</button></div></article>`).join('');
}
document.addEventListener('click', event => {
  if (event.target.closest('#review-visits')) { $('#visits-dialog').showModal(); loadVisitReview().catch(error => toast(error.message, true)); return; }
  const apply = event.target.closest('[data-apply-min]');
  if (apply) {
    action(apply, async () => {
      await api(cameraPath('/api/settings'), {method: 'PUT', body: JSON.stringify({...settings, restricted_min_seconds: Number(apply.dataset.applyMin)})});
      settings.restricted_min_seconds = Number(apply.dataset.applyMin);
      toast('Tempo mínimo atualizado.');
      $('#visits-calibration').textContent = 'Aplicado. Confira nos próximos dias.';
    });
    return;
  }
  const button = event.target.closest('#visits-list [data-verdict]');
  if (!button) return;
  const card = button.closest('[data-visit]');
  action(button, async () => {
    await api(`/api/father/visits/${card.dataset.visit}`, {method: 'POST', body: JSON.stringify({father: button.dataset.verdict === 'father'})});
    card.remove();
    $('#visits-empty').classList.toggle('hidden', Boolean($('#visits-list').children.length));
    loadFatherToday();
  });
});
