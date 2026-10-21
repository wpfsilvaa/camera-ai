// Smart clean-up of the taught faces: analysed only on request, moved to a quarantine instead of being deleted.
(() => {
  const percent = value => `${(value * 100).toFixed(1).replace('.', ',')}%`;
  const label = {high: ['Grave', 'red'], medium: ['Provável', 'amber'], low: ['Leve', 'neutral']};
  let items = [];

  async function refreshNote() {
    if (!isAdmin()) return;
    $('#cleanup-panel').classList.remove('hidden');
    try {
      const held = await api('/api/cleanup/quarantine');
      $('#cleanup-quarantine-note').textContent = held.length ? `${held.length} foto(s) na quarentena.` : '';
      $('#cleanup-open-quarantine').classList.toggle('hidden', !held.length);
    } catch { /* the next visit tries again */ }
  }

  function renderItems(result) {
    items = result.items;
    const v = result.validation;
    $('#cleanup-summary').innerHTML = !items.length ? `Analisei ${result.total} fotos e não achei nenhuma que valha remover. 🎉`
      : `Analisei ${result.total} fotos e achei ${items.length} suspeitas. ${v ? `<strong>Teste:</strong> com as ${v.removed} marcadas fora, o acerto interno vai de ${percent(v.before.right)} para ${percent(v.after.right)} e os erros de nome de ${percent(v.before.wrong)} para ${percent(v.after.wrong)}. ${v.better_or_equal ? 'Sem perda de precisão.' : '<strong>Atenção: a precisão cairia; revise antes de mover.</strong>'}` : ''}`;
    $('#cleanup-list').innerHTML = items.map(item => {
      const [text, color] = label[item.severity];
      return `<label class="example-card cleanup-card"><img class="example-photo" style="height:150px" src="/people-media/${item.sample_id}.jpg" alt="Foto de ${escapeHTML(item.name)}" loading="lazy"><span><input type="checkbox" data-cleanup="${item.sample_id}" ${result.preselected.includes(item.sample_id) ? 'checked' : ''}> <span class="pill ${color}">${text}</span></span><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.text)}<br>Semelhança com as dela(e) ${item.own.toFixed(2)} · com outra pessoa ${item.other.toFixed(2)} · nitidez ${item.quality}</small></label>`;
    }).join('');
    $('#cleanup-apply').disabled = !items.length;
  }

  const checked = () => [...document.querySelectorAll('#cleanup-list [data-cleanup]:checked')].map(input => input.dataset.cleanup);

  $('#cleanup-run').addEventListener('click', event => action(event.currentTarget, async () => {
    $('#cleanup-summary').textContent = 'Analisando as fotos… isso leva alguns segundos.';
    $('#cleanup-list').innerHTML = '';
    $('#cleanup-dialog').showModal();
    renderItems(await api('/api/cleanup/analyze', {signal: AbortSignal.timeout(120000)}));
  }));
  $('#cleanup-select-high').addEventListener('click', () => {
    document.querySelectorAll('#cleanup-list [data-cleanup]').forEach(input => { input.checked = items.find(i => i.sample_id === input.dataset.cleanup)?.severity === 'high'; });
  });
  $('#cleanup-apply').addEventListener('click', event => action(event.currentTarget, async () => {
    const chosen = checked();
    if (!chosen.length) throw new Error('Marque ao menos uma foto.');
    const {moved} = await api('/api/cleanup/apply', {method: 'POST', body: JSON.stringify({sample_ids: chosen})});
    $('#cleanup-dialog').close();
    toast(`${moved} foto(s) movida(s) para a quarentena. Dá para restaurar por 30 dias.`);
    await Promise.all([refresh(), refreshNote()]);
    renderProfiles();
  }));

  async function openQuarantine() {
    const held = await api('/api/cleanup/quarantine');
    $('#quarantine-empty').classList.toggle('hidden', held.length > 0);
    $('#quarantine-list').innerHTML = held.map(item => `<article class="example-card" data-held="${item.sample_id}"><img class="example-photo" style="height:150px" src="/people-media/${item.sample_id}.jpg" alt="Foto em quarentena" loading="lazy"><strong>${escapeHTML(item.name)}</strong><small>Desde ${day(item.created)}</small><button class="button secondary compact" data-restore="${item.sample_id}">Restaurar</button></article>`).join('');
    if (!$('#quarantine-dialog').open) $('#quarantine-dialog').showModal();
  }
  $('#cleanup-open-quarantine').addEventListener('click', event => action(event.currentTarget, openQuarantine));
  $('#quarantine-list').addEventListener('click', event => {
    const button = event.target.closest('[data-restore]');
    if (!button) return;
    action(button, async () => {
      await api('/api/cleanup/restore', {method: 'POST', body: JSON.stringify({sample_ids: [button.dataset.restore]})});
      toast('Foto restaurada no reconhecimento.');
      await Promise.all([openQuarantine(), refreshNote(), refresh()]);
      renderProfiles();
    });
  });
  document.addEventListener('DOMContentLoaded', () => setTimeout(refreshNote, 1500));
})();
