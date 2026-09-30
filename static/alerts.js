const alertKinds = {inactivity:['Ausência','amber'], camera_offline:['Câmera sem imagem','red'], camera_online:['Câmera voltou','green'], summary:['Resumo do dia','neutral'], test:['Teste','neutral']};
const alertStates = {pending:'na fila', retry:'nova tentativa', sending:'enviando', sent:'enviado', failed:'falhou', uncertain:'conferir', expired:'expirado', cancelled:'cancelado'};

function alertDelivery(alert) {
  if (!alert.deliveries.length) return 'sem destinatário';
  const counts = {};
  for (const item of alert.deliveries) counts[item.state] = (counts[item.state] || 0) + 1;
  return Object.entries(counts).map(([state, n]) => `${n} ${alertStates[state] || state}`).join(' · ');
}

function renderAlerts(alerts) {
  $('#alerts-state').textContent = settings?.alerts_enabled ? 'Ativos' : 'Desativados nas configurações';
  $('#alerts-list').innerHTML = alerts.map(alert => {
    const [label, color] = alertKinds[alert.kind] || [alert.kind, 'neutral'];
    return `<li class="alert-row"><span class="pill ${color}">${label}</span><p>${escapeHTML(alert.message)}</p><small>${day(alert.created)} às ${time(alert.created)} · ${alertDelivery(alert)}</small></li>`;
  }).join('') || '<li class="muted small">Nenhum alerta até agora.</li>';
}

$('#test-alert').addEventListener('click', event => action(event.currentTarget, async () => {
  await api('/api/alerts/test', {method:'POST'});
  toast('Alerta de teste na fila. Ele chega em alguns segundos se o WhatsApp estiver conectado.');
  await refresh();
}));
