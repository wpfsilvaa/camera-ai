// Resource monitor on the "Saúde" page: tiles, a 3-line chart and the busiest processes.
const resNumber = (value, digits = 0) => value === null || value === undefined ? '–' : Number(value).toFixed(digits).replace('.', ',');
const resBytes = bytes => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1).replace('.', ',')} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
let resTimer = null;

function resTile(label, value, caption, level = '') {
  return `<div class="res-tile ${level}"><span>${label}</span><strong>${value}</strong><small>${caption}</small></div>`;
}

function renderResourceTiles(data) {
  const now = data.now;
  if (!now) { $('#resources-tiles').textContent = 'Coletando as primeiras medições…'; return; }
  const memPct = 100 * now.mem_used / now.mem_total;
  const tiles = [
    resTile('CPU', `${resNumber(now.cpu)}%`, `${data.cores} núcleos · carga ${resNumber(now.load, 2)}`, now.cpu > 90 ? 'hot' : now.cpu > 70 ? 'warn' : ''),
    resTile('Memória', `${resNumber(memPct)}%`, `${resBytes(now.mem_used)} de ${resBytes(now.mem_total)}`, memPct > 92 ? 'hot' : memPct > 80 ? 'warn' : ''),
    resTile('Temperatura', now.temp === null ? '–' : `${resNumber(now.temp)} °C`, 'sensor mais quente', now.temp >= 85 ? 'hot' : now.temp >= 75 ? 'warn' : ''),
    resTile('Disco livre', resBytes(data.disk_free), `de ${resBytes(data.disk_total)}`, data.disk_free < 2 * 1024 ** 3 ? 'hot' : ''),
  ];
  if (now.swap_total) tiles.push(resTile('Swap', resBytes(now.swap_used), `de ${resBytes(now.swap_total)}`));
  if (now.battery) tiles.push(resTile('Bateria', `${now.battery.percent}%`, now.battery.status === 'Discharging' ? 'descarregando' : now.battery.status === 'Charging' ? 'carregando' : 'na tomada', now.battery.status === 'Discharging' && now.battery.percent < 30 ? 'hot' : ''));
  if (now.gpu) tiles.push(resTile('GPU', `${resNumber(now.gpu.util)}%`, `${resBytes(now.gpu.mem_used)} de ${resBytes(now.gpu.mem_total)} · ${resNumber(now.gpu.temp)} °C${now.gpu.power ? ` · ${resNumber(now.gpu.power)} W` : ''}`, now.gpu.util > 95 ? 'warn' : ''));
  $('#resources-tiles').innerHTML = tiles.join('');
}

function renderResourceChart(data) {
  const points = data.history, box = $('#resources-chart');
  if (points.length < 2) { box.textContent = 'O gráfico aparece depois de alguns segundos de medições.'; return; }
  const first = points[0].t, span = Math.max(points[points.length - 1].t - first, 1);
  const line = (key, cls) => {
    const coords = points.filter(p => p[key] !== null && p[key] !== undefined).map(p => `${((p.t - first) / span * 100).toFixed(2)},${(100 - Math.min(Math.max(p[key], 0), 100)).toFixed(2)}`);
    return coords.length > 1 ? `<polyline class="${cls}" points="${coords.join(' ')}"/>` : '';
  };
  box.innerHTML = `<svg viewBox="0 0 100 100" preserveAspectRatio="none"><g class="grid">${[0, 25, 50, 75, 100].map(y => `<line x1="0" x2="100" y1="${y}" y2="${y}" stroke="currentColor" vector-effect="non-scaling-stroke"/>`).join('')}</g>${line('mem', 'l-mem')}${line('temp', 'l-temp')}${line('cpu', 'l-cpu')}</svg>`;
  box.querySelectorAll('.grid line').forEach(l => { l.style.stroke = 'var(--border)'; l.style.strokeDasharray = '3 4'; });
}

function renderResourceTop(data) {
  const top = data.now?.top || [];
  $('#resources-top').innerHTML = top.length ? top.map(p => `<li><span>${p.name}</span><span>${resNumber(p.cpu)}% de um núcleo · ${resBytes(p.rss)}</span></li>`).join('') : '<li><span>Nenhum processo relevante agora.</span></li>';
  const camera = typeof status !== 'undefined' && status?.camera;
  $('#resources-camera').textContent = camera && camera.detector ? `${camera.sentinel ? 'Modo vigia ativo · ' : ''}Detecção: ${camera.detector} · inferência ${resNumber(camera.inference_ms, 1)} ms · ${resNumber(camera.detection_fps, 1)} análises/s · vídeo ${resNumber(camera.fps, 1)} qps` : '';
}

async function loadResources() {
  if (!isAdmin() || !$('#resources-panel')) return;
  const data = await api(`/api/resources?minutes=${$('#resources-minutes').value}`);
  renderResourceTiles(data); renderResourceChart(data); renderResourceTop(data);
}

function resourcesVisible() {
  const panel = $('#resources-panel');
  if (!panel) return false;
  panel.classList.toggle('hidden', !isAdmin());   // Server numbers are for administrators.
  return activePage === 'health' && !panel.classList.contains('hidden') && !document.hidden;
}

$('#resources-minutes')?.addEventListener('change', () => loadResources().catch(() => {}));
clearInterval(resTimer);
resTimer = setInterval(() => { if (resourcesVisible()) loadResources().catch(() => {}); }, 5000);
setTimeout(() => { if (resourcesVisible()) loadResources().catch(() => {}); }, 2500);
window.addEventListener('hashchange', () => setTimeout(() => { if (resourcesVisible()) loadResources().catch(() => {}); }, 300));
