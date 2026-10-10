let account = {enabled:false, user:null}, users = [];
const roleLabel = {admin:'Administrador', family:'Família'};
const isAdmin = () => !account.enabled || account.user?.role === 'admin';

async function loadAccount() {
  account = await api('/api/auth/me');
  document.body.classList.toggle('readonly', !isAdmin());
  const user = account.user;
  $('#account-button').classList.toggle('hidden', !user);
  if (!user) return;
  $('#account-name').textContent = user.name;
  $('#account-initial').textContent = user.name.slice(0,1).toUpperCase();
  if ($('#profile-form')) { $('#profile-form').elements.name.value = user.name; $('#profile-form').elements.username.value = user.username; }
  $('#account-summary').textContent = `${user.name} · usuário ${user.username} · ${roleLabel[user.role]}${user.role === 'family' ? ' (somente visualizar)' : ''}`;
}

async function loadUsers() {
  users = await api('/api/users');
  $('#users-first').classList.toggle('hidden', users.length > 0);
  const form = $('#user-form');
  form.role.value = users.length ? form.role.value : 'admin';
  form.role.disabled = !users.length;
  $('#users-list').innerHTML = users.map(user => `<li class="user-row"><span class="account-initial">${escapeHTML(user.name.slice(0,1).toUpperCase())}</span><div class="user-info"><strong>${escapeHTML(user.name)}${user.id === account.user?.id ? ' <span class="pill neutral">você</span>' : ''}</strong><small>${escapeHTML(user.username)} · ${user.last_login ? `último acesso ${day(user.last_login)} às ${time(user.last_login)}` : 'nunca entrou'}</small></div><select data-user-role="${user.id}" aria-label="Perfil de ${escapeHTML(user.name)}">${Object.entries(roleLabel).map(([value,label]) => `<option value="${value}" ${user.role===value?'selected':''}>${label}</option>`).join('')}</select><div class="user-actions"><button class="text-button" data-user-password="${user.id}">Redefinir senha</button>${user.id !== account.user?.id ? `<button class="text-button danger" data-user-delete="${user.id}">Excluir</button>` : ''}</div></li>`).join('') || '<li class="muted small">Nenhum usuário cadastrado.</li>';
}

$('#user-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  action(form.querySelector('[type=submit]'), async () => {
    const body = {name:form.name.value, username:form.username.value, password:form.password.value, role:form.role.disabled ? 'admin' : form.role.value};
    const created = await api('/api/users', {method:'POST', body:JSON.stringify(body)});
    form.reset();
    if (created.login_required) { toast('Administrador criado. Entre com o novo usuário.'); setTimeout(() => location.replace('/login'), 1200); return; }
    toast(`Usuário ${body.username} criado.`); await loadUsers();
  });
});

$('#users-list').addEventListener('change', event => {
  const select = event.target.closest('[data-user-role]');
  if (!select) return;
  api(`/api/users/${select.dataset.userRole}`, {method:'PATCH', body:JSON.stringify({role:select.value})})
    .then(() => toast('Perfil atualizado. A pessoa precisará entrar novamente.'))
    .catch(error => toast(error.message, true))
    .finally(() => loadUsers().then(loadAccount).catch(() => {}));
});

$('#users-list').addEventListener('click', event => {
  const reset = event.target.closest('[data-user-password]'), remove = event.target.closest('[data-user-delete]');
  const user = users.find(item => item.id === (reset || remove)?.dataset[reset ? 'userPassword' : 'userDelete']);
  if (!user) return;
  if (reset) {
    const password = prompt(`Nova senha para ${user.name} (mínimo de 8 caracteres):`);
    if (!password) return;
    action(reset, async () => { await api(`/api/users/${user.id}`, {method:'PATCH', body:JSON.stringify({password})}); toast('Senha redefinida. Os outros aparelhos dessa conta foram desconectados.'); });
  } else if (confirm(`Excluir o acesso de ${user.name}? A pessoa será desconectada imediatamente.`)) {
    action(remove, async () => { await api(`/api/users/${user.id}`, {method:'DELETE'}); toast('Usuário excluído.'); await loadUsers(); });
  }
});

$('#account-button').addEventListener('click', () => $('#account-dialog').showModal());
$('#password-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  action(form.querySelector('[type=submit]'), async () => {
    await api('/api/auth/password', {method:'POST', body:JSON.stringify({current:form.current.value, new:form.new.value})});
    form.reset(); $('#account-dialog').close(); toast('Senha alterada.');
  });
});
$('#logout-button').addEventListener('click', async () => {
  await api('/api/auth/logout', {method:'POST'}).catch(() => {});
  location.replace('/login');
});

$('#profile-form')?.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  action(form.querySelector('button[type=submit]'), async () => {
    await api('/api/auth/profile', {method: 'PATCH', body: JSON.stringify({name: form.elements.name.value.trim(), username: form.elements.username.value.trim().toLowerCase()})});
    toast('Perfil atualizado. Seu novo nome já aparece nas fotos e lembretes.');
    await loadAccount();
  });
});
