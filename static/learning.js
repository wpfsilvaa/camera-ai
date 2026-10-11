// Faces the system proposes as new examples; nothing is learned without approval.
async function loadLearning() {
  const items = isAdmin() ? await api('/api/learning') : [];
  $('#learning-panel').classList.toggle('hidden', !items.length);
  $('#learning-count').textContent = `${items.length} para revisar`;
  $('#learning-list').innerHTML = items.map(item => `<article class="learning-card"><img src="/people-media/${item.sample_id}.jpg" alt="Rosto sugerido para ${escapeHTML(item.name)}" loading="lazy"><div><strong>Parece ser ${escapeHTML(item.name)}</strong><small>Semelhança ${Number(item.score).toFixed(2)} · nitidez ${Math.round(item.quality)}<br>${day(item.seen)} às ${time(item.seen)} · registro #${item.event_id}</small></div><div class="learning-actions"><button class="button primary compact" data-learning="${item.sample_id}" data-decision="approve">Aprovar</button><button class="button secondary compact" data-learning="${item.sample_id}" data-decision="reject">Não é</button><button class="text-button" data-learning="${item.sample_id}" data-decision="discard" title="Apaga esta foto: borrada, cortada ou ruim demais para aprender">Descartar foto</button></div></article>`).join('');
}

$('#learning-list').addEventListener('click', event => {
  const button = event.target.closest('[data-learning]');
  if (!button) return;
  const approve = button.dataset.decision === 'approve';
  action(button, async () => {
    await api(`/api/learning/${button.dataset.learning}/${button.dataset.decision}`, {method:'POST'});
    toast(approve ? 'Exemplo aprovado: o rosto entrou no aprendizado e o registro foi identificado.' : button.dataset.decision === 'discard' ? 'Foto descartada e apagada. Nada será aprendido com ela.' : 'Sugestão recusada. Ela não será mostrada de novo.');
    await Promise.all([loadLearning(), refresh()]);
    renderProfiles();
  });
});
