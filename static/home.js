// Overview: the "everything OK?" strip.
window.renderHome = function renderHome() {
  if (!status || !settings) return;
  const nb = status.notebook || {}, camera = status.camera, now = status.now;
  const ago = since => { const m = Math.max(0, Math.round((now - since) / 60)); return m < 1 ? 'menos de 1 min' : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`; };

  const low = nb.battery != null && nb.plugged === false && nb.battery <= settings.notebook_battery_percent;

  // Attention strip --------------------------------------------------------
  const problems = [];
  if (settings.enabled && camera.state === 'offline') problems.push(['red', 'Câmera sem imagem. Confira a energia e o Wi-Fi do computador da câmera.']);
  if (nb.state === 'offline') problems.push(['red', `Notebook sem sinal desde as ${time(nb.silent_since)}.`]);
  else if (nb.state === 'battery') problems.push([low ? 'red' : 'amber', `Notebook na bateria (${nb.battery ?? '?'}%) há ${ago(nb.battery_since)}. Reconecte o carregador.`]);
  if (settings.whatsapp_enabled && status.whatsapp.state !== 'connected') problems.push(['amber', 'WhatsApp desconectado: os vídeos não estão sendo enviados.']);
  if (status.storage_free_gb < settings.min_free_gb) problems.push(['amber', `Pouco espaço livre (${status.storage_free_gb} GB). Libere espaço em Configurações → Sistema.`]);
  const strip = $('#attention');
  strip.classList.remove('hidden');
  strip.classList.toggle('has-problems', problems.length > 0);
  strip.classList.toggle('is-red', problems.some(p => p[0] === 'red'));
  const parts = [camera.state === 'online' ? 'câmera ao vivo' : camera.state === 'paused' ? 'câmera pausada' : 'câmera conectando'];
  if (nb.state === 'ok') parts.push(`notebook na tomada${nb.battery != null ? ` (${nb.battery}%)` : ''}`);
  strip.replaceChildren(...(problems.length ? problems.map(([color, text]) => {
    const row = document.createElement('p');
    row.innerHTML = `<span class="dot ${color === 'red' ? 'error' : 'warn'}"></span>`;
    row.append(text);
    return row;
  }) : [Object.assign(document.createElement('p'), {textContent: `✓ Tudo funcionando · ${parts.join(' · ')}`})]));
}
