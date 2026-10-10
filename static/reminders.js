// Reminders for the kitchen screen: anyone signed in can leave one with an expiry; the screen cycles through them.
const reminderLeft = expires => {
  const minutes = Math.max(1, Math.round((expires * 1000 - Date.now()) / 60000));
  return minutes >= 2880 ? `${Math.round(minutes / 1440)} dias` : minutes >= 120 ? `${Math.round(minutes / 60)} h` : minutes >= 60 ? '1 h' : `${minutes} min`;
};

async function loadReminders() {
  const list = $('#reminders-list');
  if (!list) return;
  const data = await api('/api/reminders');
  $('#reminders-count').textContent = data.reminders.length ? `${data.reminders.length} ativo(s)` : '';
  list.innerHTML = data.reminders.length ? data.reminders.map(item => `<li><div><strong>${escapeHTML(item.text)}</strong><small>${escapeHTML(item.author)} · some em ${reminderLeft(item.expires)}</small></div>${item.mine ? `<button type="button" class="text-button" data-remove-reminder="${item.id}">Remover</button>` : ''}</li>`).join('') : '<li class="muted small">Nenhum lembrete ativo.</li>';
}

$('#reminder-form')?.addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter || event.currentTarget.querySelector('button'), async () => {
    await api('/api/reminders', {method: 'POST', body: JSON.stringify({text: $('#reminder-text').value.trim(), hours: Number($('#reminder-hours').value)})});
    $('#reminder-text').value = '';
    toast('Lembrete deixado. Ele aparece na tela do notebook em instantes.');
    await loadReminders();
  });
});
document.addEventListener('click', event => {
  const remove = event.target.closest('[data-remove-reminder]');
  if (remove) action(remove, async () => { await api(`/api/reminders/${remove.dataset.removeReminder}`, {method: 'DELETE'}); await loadReminders(); });
});
setTimeout(() => loadReminders().catch(() => {}), 1500);
setInterval(() => { if (activePage === 'overview' && !document.hidden) loadReminders().catch(() => {}); }, 15000);
