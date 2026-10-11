// Family logbook: dated notes everyone can read, to remember what to tell the doctor.
const journalTags = {geral: 'Geral', saude: 'Saúde', humor: 'Humor', remedio: 'Remédio'};
let journalNotes = [], journalMore = false;

function renderJournal() {
  $('#journal-total').textContent = journalNotes.length ? `${journalNotes.length} anotação(ões)` : '';
  $('#journal-more').classList.toggle('hidden', !journalMore);
  let lastDay = '';
  $('#journal-list').innerHTML = journalNotes.length ? journalNotes.map(note => {
    const date = new Date(note.created * 1000), day = date.toLocaleDateString('pt-BR', {weekday: 'long', day: '2-digit', month: 'long'});
    const heading = day === lastDay ? '' : `<li class="journal-day">${escapeHTML(day)}</li>`;
    lastDay = day;
    return `${heading}<li><div><span class="journal-tag tag-${note.tag}">${journalTags[note.tag] || 'Geral'}</span><p>${escapeHTML(note.text)}</p><small>${escapeHTML(note.author)} · ${date.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'})}</small></div>${note.mine ? `<button class="text-button danger" data-remove-journal="${note.id}">Remover</button>` : ''}</li>`;
  }).join('') : '<li class="muted small">Nenhuma anotação ainda.</li>';
}

async function loadJournal(older = false) {
  const before = older && journalNotes.length ? `?before=${journalNotes[journalNotes.length - 1].created}` : '';
  const data = await api(`/api/journal${before}`);
  journalNotes = older ? journalNotes.concat(data.notes) : data.notes;
  journalMore = data.more;
  renderJournal();
}
window.loadJournal = loadJournal;

$('#journal-text')?.addEventListener('input', () => { $('#journal-count').textContent = `${$('#journal-text').value.length} de 500 letras`; });
$('#journal-send')?.addEventListener('click', event => {
  if (!$('#journal-text').value.trim()) { toast('Escreva a anotação antes.', true); return; }
  action(event.currentTarget, async () => {
    await api('/api/journal', {method: 'POST', body: JSON.stringify({text: $('#journal-text').value.trim(), tag: $('#journal-tag').value})});
    $('#journal-text').value = ''; $('#journal-count').textContent = '0 de 500 letras';
    toast('Anotação salva no diário.');
    await loadJournal();
  });
});
$('#journal-more')?.addEventListener('click', event => action(event.currentTarget, () => loadJournal(true)));
document.addEventListener('click', event => {
  const remove = event.target.closest('[data-remove-journal]');
  if (remove && confirm('Remover esta anotação?')) action(remove, async () => { await api(`/api/journal/${remove.dataset.removeJournal}`, {method: 'DELETE'}); await loadJournal(); });
});
