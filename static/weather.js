// Forecast on the kitchen screen: pick the city here, the server fetches it and the screen shows it.
const weatherForm = () => document.querySelector('#settings-form');

function weatherPreview(info) {
  const box = $('#weather-preview');
  if (!box) return;
  if (!info.enabled) { box.textContent = 'Desligada.'; return; }
  if (!info.city) { box.textContent = 'Escolha uma cidade para ver a previsão.'; return; }
  box.textContent = info.data
    ? `Agora em ${info.city}: ${info.data.t}°, ${info.data.text.toLowerCase()}. Hoje: máx ${info.data.days[0].hi}°, mín ${info.data.days[0].lo}°, chuva ${info.data.days[0].rain}%.`
    : info.error ? `Não foi possível obter a previsão (${info.error}). Confira a internet do servidor.` : 'Buscando a previsão… (salve as configurações se acabou de mudar a cidade)';
}

async function loadWeatherPreview() {
  if (!$('#weather-preview') || !isAdmin()) return;
  weatherPreview(await api('/api/weather'));
}

$('#weather-find')?.addEventListener('click', event => {
  const query = $('#weather-q').value.trim();
  if (query.length < 2) { toast('Digite pelo menos 2 letras da cidade.', true); return; }
  action(event.currentTarget, async () => {
    const data = await api(`/api/weather/search?q=${encodeURIComponent(query)}`);
    $('#weather-results').innerHTML = data.cities.length
      ? data.cities.map((c, i) => `<button type="button" class="weather-city" data-city="${i}">${escapeHTML(c.name)}${c.region ? `, ${escapeHTML(c.region)}` : ''} <small>${escapeHTML(c.country)}</small></button>`).join('')
      : '<p class="muted small">Nenhuma cidade encontrada.</p>';
    $('#weather-results').cities = data.cities;
  });
});
$('#weather-q')?.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); $('#weather-find').click(); } });
document.addEventListener('click', event => {
  const pick = event.target.closest('.weather-city');
  if (!pick) return;
  const city = $('#weather-results').cities[Number(pick.dataset.city)], form = weatherForm();
  const label = [city.name, city.region].filter(Boolean).join(', ');
  const set = (name, value) => { const field = form.elements.namedItem(name); field.value = value; field.dispatchEvent(new Event('input', {bubbles: true})); };
  set('kiosk_weather_city', label); set('kiosk_weather_lat', city.lat); set('kiosk_weather_lon', city.lon);
  form.elements.namedItem('kiosk_weather_enabled').checked = true;
  $('#weather-results').innerHTML = `<p class="small">Escolhida: <strong>${escapeHTML(label)}</strong>. Clique em <strong>Salvar configurações</strong> para ativar.</p>`;
});
setTimeout(() => loadWeatherPreview().catch(() => {}), 2500);
setInterval(() => { if (activePage === 'settings' && !document.hidden) loadWeatherPreview().catch(() => {}); }, 30000);
document.addEventListener('click', event => { if (event.target.closest('#save-settings')) setTimeout(() => loadWeatherPreview().catch(() => {}), 4000); });
