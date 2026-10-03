// Disk usage and the buttons that free space.
function bytesText(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1).replace('.', ',')} GB`;
  return bytes >= 1024 ** 2 ? `${Math.round(bytes / 1024 ** 2)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

let storagePreview = null;
async function loadStorage() {
  if (!isAdmin()) return;
  const data = await api(`/api/storage?older_than_days=${$('#clean-days').value}`);
  const used = data.disk_total_bytes - data.disk_free_bytes;
  $('#storage-usage').innerHTML = `<div class="storage-bar" role="img" aria-label="Disco ${Math.round(used / data.disk_total_bytes * 100)}% usado"><span class="storage-used"></span></div>
    <dl><div><dt>Livre no disco</dt><dd>${bytesText(data.disk_free_bytes)} de ${bytesText(data.disk_total_bytes)}</dd></div>
    <div><dt>Vídeos</dt><dd>${bytesText(data.videos_bytes)} · ${data.videos}</dd></div>
    <div><dt>Histórico (banco)</dt><dd>${bytesText(data.database_bytes)} · ${data.events} registros</dd></div>
    <div><dt>Fotos de rostos</dt><dd>${bytesText(data.faces_bytes)}</dd></div></dl>`;
  $('#storage-usage .storage-used').style.width = `${Math.min(100, used / data.disk_total_bytes * 100)}%`;
  storagePreview = data.preview;
  $('#clean-preview').textContent = `Nesta seleção: ${data.preview.videos} vídeo(s), ${bytesText(data.preview.videos_bytes)}; ${data.preview.events} registro(s) sem rosto ensinado.`;
  $('#clean-videos').disabled = !data.preview.videos;
  $('#clean-history').disabled = !data.preview.events && !data.preview.videos;
}

async function clean(what, button) {
  const days = Number($('#clean-days').value);
  const period = days ? `com mais de ${days} dia(s)` : 'de todos os períodos, inclusive de hoje';
  const question = what === 'videos'
    ? `Apagar ${storagePreview.videos} vídeo(s) ${period}? Libera cerca de ${bytesText(storagePreview.videos_bytes)}. Os registros continuam no histórico.`
    : `Apagar ${storagePreview.events} registro(s) ${period}, com vídeos e fotos não confirmadas? Rostos ensinados são mantidos. Não dá para desfazer.`;
  if (!confirm(question)) return;
  await action(button, async () => {
    const result = await api('/api/storage/clean', {method: 'POST', body: JSON.stringify({what, older_than_days: days}), signal: AbortSignal.timeout(300000)});
    toast(`Espaço liberado: ${bytesText(result.freed_bytes)} (${result.videos} vídeo(s)${result.events !== undefined ? `, ${result.events} registro(s)` : ''}).`);
    await Promise.all([loadStorage(), refresh()]);
  });
}

$('#clean-days').addEventListener('change', () => loadStorage().catch(error => toast(error.message, true)));
$('#clean-videos').addEventListener('click', event => clean('videos', event.currentTarget));
$('#clean-history').addEventListener('click', event => clean('history', event.currentTarget));
