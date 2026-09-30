const form = document.getElementById('login-form');
const error = document.getElementById('login-error');
const submit = document.getElementById('login-submit');
const toggle = document.getElementById('toggle-password');

toggle.addEventListener('click', () => {
  const visible = form.password.type === 'password';
  form.password.type = visible ? 'text' : 'password';
  toggle.textContent = visible ? 'Ocultar' : 'Mostrar';
  toggle.setAttribute('aria-pressed', String(visible));
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.hidden = true;
  if (!form.username.value.trim() || !form.password.value) {
    error.textContent = 'Informe usuário e senha.'; error.hidden = false; return;
  }
  submit.disabled = true; submit.textContent = 'Entrando…';
  try {
    const response = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json','X-Casa-Request':'1'},
      body:JSON.stringify({username:form.username.value, password:form.password.value, remember:form.remember.checked})});
    if (response.ok) { location.replace('/'); return; }
    const body = await response.json().catch(() => ({}));
    error.textContent = body.detail || 'Não foi possível entrar.';
  } catch {
    error.textContent = 'Sem conexão com o servidor.';
  }
  error.hidden = false; form.password.value = ''; form.password.focus();
  submit.disabled = false; submit.textContent = 'Entrar';
});
