// Kitchen screen: which accounts get their own call button (with their photo), and each person's own photo.
const MAX_CALL_USERS = 4;
let callContacts = [], chosenCallUsers = [];

const avatarMarkup = user => user.avatar ? `<img src="/avatar-media/${user.id}.jpg?t=${Date.now()}" alt="">` : escapeHTML(user.name.slice(0, 1).toUpperCase());

function renderCallUsers() {
  const box = $('#call-users');
  if (!box) return;
  box.innerHTML = callContacts.length ? callContacts.map(user => `<label class="call-user"><input type="checkbox" value="${user.id}" ${chosenCallUsers.includes(user.id) ? 'checked' : ''}><span class="call-user-face">${avatarMarkup(user)}</span><span>${escapeHTML(user.name)}${user.avatar ? '' : ' <small class="muted">(sem foto)</small>'}</span></label>`).join('') : '<small class="muted">Nenhum usuário cadastrado.</small>';
}

window.fillCallUsers = ids => { chosenCallUsers = [...ids]; renderCallUsers(); };
window.readCallUsers = () => [...document.querySelectorAll('#call-users input:checked')].map(input => input.value).slice(0, MAX_CALL_USERS);

async function loadCallContacts() {
  callContacts = (await api('/api/call-contacts')).users;
  renderCallUsers();
  const mine = callContacts.find(user => user.me);
  $('#avatar-preview').innerHTML = mine ? avatarMarkup(mine) : '';
  $('#avatar-remove').classList.toggle('hidden', !mine?.avatar);
}
window.loadCallContacts = loadCallContacts;

document.addEventListener('change', event => {
  if (event.target.matches('#call-users input') && document.querySelectorAll('#call-users input:checked').length > MAX_CALL_USERS) {
    event.target.checked = false; toast(`No máximo ${MAX_CALL_USERS} pessoas.`, true);
  }
});
$('#avatar-file')?.addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  try {
    await api('/api/auth/avatar', {method: 'POST', body: file, headers: {'Content-Type': file.type || 'image/jpeg'}});
    toast('Foto atualizada. Ela chega à tela do notebook em instantes.');
    await loadCallContacts();
  } catch (error) { toast(error.message, true); }
});
$('#avatar-remove')?.addEventListener('click', event => action(event.currentTarget, async () => { await api('/api/auth/avatar', {method: 'DELETE'}); await loadCallContacts(); }));
$('#account-button')?.addEventListener('click', () => loadCallContacts().catch(() => {}));
document.addEventListener('DOMContentLoaded', () => loadCallContacts().catch(() => {}));
