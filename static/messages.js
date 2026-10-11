// Messages for a person: written here, shown on the kitchen screen when that person is recognised.
let messagePeopleLoaded = false;

const messageLeft = expires => {
  const minutes = Math.max(1, Math.round((expires * 1000 - Date.now()) / 60000));
  return minutes >= 2880 ? `${Math.round(minutes / 1440)} dias` : minutes >= 120 ? `${Math.round(minutes / 60)} h` : minutes >= 60 ? '1 h' : `${minutes} min`;
};
const firstWord = name => String(name || '').split(/\s+/).filter(Boolean).filter((w, i, all) => !(i === 0 && all.length > 1 && /^(meu|minha)$/i.test(w)))[0] || '';

function renderMessagePreview() {
  const text = $('#msg-text').value.trim(), user = typeof account !== 'undefined' && account?.user;
  $('#msg-preview-text').textContent = text || 'Sua mensagem aparece assim na tela.';
  $('#msg-preview-by').textContent = user ? firstWord(user.name) : '';
  $('#msg-count').textContent = `${$('#msg-text').value.length} de 240 letras`;
}

async function loadMessages() {
  if (!messagePeopleLoaded) {
    const people = await api('/api/people');
    $('#msg-to').innerHTML = people.profiles.map(p => `<option value="${p.id}">${escapeHTML(p.name)}</option>`).join('');
    messagePeopleLoaded = true;
  }
  const data = await api('/api/messages');
  $('#msg-total').textContent = data.messages.length ? `${data.messages.length} recado(s)` : '';
  $('#messages-list').innerHTML = data.messages.length ? data.messages.map(m => {
    const readAt = m.read_at ? new Date(m.read_at * 1000).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
    const state = m.read_at ? (m.single ? `✓ visualizada em ${readAt} (já sumiu da tela)` : `✓ lido em ${readAt}`) : m.shown ? `mostrado ${m.shown}× na tela, ainda sem confirmação` : 'aguardando a pessoa aparecer';
    return `<li><div><strong>Para ${escapeHTML(m.to_name || '—')}</strong><p>${escapeHTML(m.text)}</p><small>de ${escapeHTML(m.author)} · ${m.single ? 'visualização única' : m.once ? 'até confirmar' : 'toda vez'} · ${state} · vale por mais ${messageLeft(m.expires)}</small></div>${m.mine ? `<button type="button" class="text-button" data-remove-message="${m.id}">Remover</button>` : ''}</li>`;
  }).join('') : '<li class="muted small">Nenhum recado ativo.</li>';
  renderMessagePreview();
}
window.loadMessages = loadMessages;

$('#msg-text')?.addEventListener('input', renderMessagePreview);
$('#msg-send')?.addEventListener('click', event => {
  if (!$('#msg-text').value.trim()) { toast('Escreva o recado antes de deixar.', true); return; }
  action(event.currentTarget, async () => {
    await api('/api/messages', {method: 'POST', body: JSON.stringify({to_person: $('#msg-to').value, text: $('#msg-text').value.trim(), hours: Number($('#msg-hours').value), mode: $('#msg-mode').value})});
    $('#msg-text').value = '';
    toast('Recado deixado. Ele aparece quando a pessoa for reconhecida na tela do notebook.');
    await loadMessages();
  });
});
document.addEventListener('click', event => {
  const remove = event.target.closest('[data-remove-message]');
  if (remove) action(remove, async () => { await api(`/api/messages/${remove.dataset.removeMessage}`, {method: 'DELETE'}); await loadMessages(); });
});
setInterval(() => { if (activePage === 'messages' && !document.hidden) loadMessages().catch(() => {}); }, 20000);
