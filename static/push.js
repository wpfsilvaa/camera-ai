// Per-device notifications and "install as app". Push needs HTTPS (or localhost).
(() => {
  let installPrompt = null;
  const canPush = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const keyBytes = key => Uint8Array.from(atob(key.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
  const show = (id, visible) => $(id).classList.toggle('hidden', !visible);

  async function registration() {
    return navigator.serviceWorker.register('/sw.js', {scope: '/'});
  }

  async function currentSubscription() {
    return canPush() && window.isSecureContext ? (await registration()).pushManager.getSubscription() : null;
  }

  async function render() {
    let text, on = false;
    if (!window.isSecureContext) text = 'Notificações exigem conexão segura. Abra o painel pelo endereço https do Tailscale (…ts.net) neste aparelho.';
    else if (!canPush()) text = 'Este navegador não recebe notificações. No iPhone, instale o app pela opção Compartilhar → Adicionar à Tela de Início e abra por ele.';
    else if (Notification.permission === 'denied') text = 'Notificações bloqueadas para este site. Libere nas configurações do navegador.';
    else {
      on = Boolean(await currentSubscription());
      text = on ? 'Notificações ativas: alertas de queda, rotina, ausência e câmera aparecem neste aparelho.' : 'Notificações desligadas neste aparelho. Ative para receber os alertas aqui também, mesmo se o WhatsApp falhar.';
    }
    $('#push-status').textContent = text;
    show('#push-enable', window.isSecureContext && canPush() && Notification.permission !== 'denied' && !on);
    show('#push-test', on);
    show('#push-disable', on);
    show('#presence-row', on);
    if (on) $('#presence-push').checked = (await api('/api/push/presence-status', {method: 'POST', body: JSON.stringify({endpoint: (await currentSubscription()).endpoint})})).enabled;
    show('#install-app', Boolean(installPrompt));
  }

  $('#push-enable').addEventListener('click', event => action(event.currentTarget, async () => {
    if (await Notification.requestPermission() !== 'granted') { await render(); throw new Error('Permissão de notificação não concedida.'); }
    const {key} = await api('/api/push/key');
    const subscription = await (await registration()).pushManager.subscribe({userVisibleOnly: true, applicationServerKey: keyBytes(key)});
    await api('/api/push/subscribe', {method: 'POST', body: JSON.stringify(subscription.toJSON())});
    toast('Notificações ativadas neste aparelho.');
    await render();
  }));
  $('#presence-push').addEventListener('change', event => {
    const input = event.currentTarget;
    action(input, async () => {
      const subscription = await currentSubscription();
      try {
        await api('/api/push/presence', {method: 'POST', body: JSON.stringify({endpoint: subscription.endpoint, enabled: input.checked})});
      } catch (error) { input.checked = !input.checked; throw error; }
      toast(input.checked ? 'Você será avisado neste aparelho quando alguém aparecer.' : 'Avisos de presença desligados neste aparelho.');
    });
  });
  $('#push-test').addEventListener('click', event => action(event.currentTarget, async () => {
    await api('/api/push/test', {method: 'POST'});
    toast('Notificação de teste enviada. Ela chega em alguns segundos.');
  }));
  $('#push-disable').addEventListener('click', event => action(event.currentTarget, async () => {
    const subscription = await currentSubscription();
    if (subscription) {
      await api('/api/push/unsubscribe', {method: 'POST', body: JSON.stringify({endpoint: subscription.endpoint})});
      await subscription.unsubscribe();
    }
    toast('Notificações desativadas neste aparelho.');
    await render();
  }));
  $('#install-app').addEventListener('click', async () => {
    installPrompt?.prompt();
    installPrompt = null;
    await render();
  });

  window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); installPrompt = event; render(); });
  $('#account-button').addEventListener('click', () => render().catch(() => {}));
  // Keep the offline page and notification handling available even before opening the dialog.
  if ('serviceWorker' in navigator && window.isSecureContext) registration().catch(() => {});
})();
