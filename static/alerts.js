const alertKinds = {fall:['Possível queda','red'], restricted:['Área restrita','amber'], routine:['Fora da rotina','amber'], backup:['Backup falhou','red'], inactivity:['Ausência','amber'], camera_offline:['Câmera sem imagem','red'], camera_online:['Câmera voltou','green'], summary:['Resumo do dia','neutral'], notebook_battery:['Bateria do notebook','red'], notebook_unplugged:['Notebook sem energia','amber'], notebook_power_back:['Energia voltou','green'], notebook_offline:['Notebook sem sinal','red'], notebook_online:['Notebook voltou','green'], test:['Teste','neutral']};
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
    return `<li class="alert-row"><span class="pill ${color}">${label}</span><p>${escapeHTML(alert.message)}</p>${alert.image?`<a class="alert-photo" href="/alert-media/${alert.id}.jpg" target="_blank" rel="noopener"><img src="/alert-media/${alert.id}.jpg" alt="Foto do alerta" loading="lazy"></a>`:''}<small>${day(alert.created)} às ${time(alert.created)} · ${alertDelivery(alert)}</small></li>`;
  }).join('') || '<li class="muted small">Nenhum alerta até agora.</li>';
}

$('#test-alert').addEventListener('click', event => action(event.currentTarget, async () => {
  await api('/api/alerts/test', {method:'POST'});
  toast('Alerta de teste na fila. Ele chega em alguns segundos se o WhatsApp estiver conectado.');
  await refresh();
}));

let routineLoaded = 0;
async function loadRoutine() {
  // The routine changes slowly; the server recomputes it every 10 minutes.
  if (Date.now() - routineLoaded < 600000) return;
  routineLoaded = Date.now();
  const routine = await api('/api/routine');
  $('#routine-days').textContent = `${routine.days} dia(s) de registros`;
  const group = routine.weekday || routine.all;
  $('#routine-text').textContent = !routine.learned
    ? `Aprendendo: faltam ${Math.max(0, routine.needed_days - routine.days)} dia(s) com registros para conhecer o horário de costume.`
    : `Costuma aparecer por volta das ${group.usual_first}, até as ${group.latest_first} nos dias úteis${routine.weekend ? `; no fim de semana, até as ${routine.weekend.latest_first}` : ''}.${routine.usual_gap_hours ? ` Fica até ${String(routine.usual_gap_hours).replace('.', ',')} h sem aparecer durante o dia.` : ''}`;
  const max = Math.max(...routine.hourly, .01), width = 480, height = 90, bar = width / 24;
  $('#routine-chart').innerHTML = `<svg viewBox="0 0 ${width} ${height + 16}">${routine.hourly.map((value, hour) => {
    if (!value) return `<rect class="routine-hit" x="${hour * bar}" y="0" width="${bar}" height="${height}"><title>${String(hour).padStart(2, '0')}h: nenhum registro</title></rect>`;
    const h = Math.max(4, value / max * height);
    return `<g><rect class="routine-hit" x="${hour * bar}" y="0" width="${bar}" height="${height}"><title>${String(hour).padStart(2, '0')}h: ${String(value).replace('.', ',')} registro(s) por dia</title></rect><path class="routine-bar" d="M${hour * bar + 1} ${height} v${-(h - 4)} q0 -4 4 -4 h${bar - 10} q4 0 4 4 v${h - 4} z"/></g>`;
  }).join('')}${[0, 6, 12, 18].map(hour => `<text x="${hour * bar + 2}" y="${height + 13}">${hour}h</text>`).join('')}</svg>`;
  const peak = routine.hourly.indexOf(Math.max(...routine.hourly));
  $('#routine-caption').textContent = routine.days ? `Média de registros por hora nos últimos 28 dias. Mais movimento às ${peak}h.` : 'O gráfico aparece com os primeiros registros.';
}
