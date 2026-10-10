// Family photos for the kitchen screen: anyone signed in uploads; each person removes their own.
const PHOTO_LONG_SIDE = 1920;

async function shrinkPhoto(file) {
  // The server also resizes; shrinking here keeps phone uploads (often 5-10 MB) small on a slow connection.
  try {
    const bitmap = await createImageBitmap(file, {imageOrientation: 'from-image'});
    const scale = Math.min(1, PHOTO_LONG_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return await new Promise(resolve => canvas.toBlob(blob => resolve(blob || file), 'image/jpeg', 0.88));
  } catch { return file; }
}

async function loadPhotos() {
  const grid = $('#photos-grid');
  if (!grid) return;
  const data = await api('/api/photos');
  $('#photos-count').textContent = data.photos.length ? `${data.photos.length} foto(s)` : '';
  grid.innerHTML = data.photos.length ? data.photos.map(photo => `<figure><img src="/photos-media/${photo.id}.thumb.jpg" alt="Foto enviada por ${escapeHTML(photo.author)}" loading="lazy"><figcaption>${escapeHTML(photo.author)}${photo.mine ? ` · <button type="button" class="text-button" data-remove-photo="${photo.id}">Remover</button>` : ''}</figcaption></figure>`).join('') : '<p class="muted small">Nenhuma foto ainda.</p>';
}

$('#photo-input')?.addEventListener('change', async event => {
  const files = [...event.target.files], status = $('#photo-status');
  event.target.value = '';
  let done = 0;
  for (const file of files) {
    status.textContent = `Enviando ${done + 1} de ${files.length}…`;
    try {
      const body = await shrinkPhoto(file);
      await api('/api/photos', {method: 'POST', body, headers: {'Content-Type': 'application/octet-stream'}, signal: AbortSignal.timeout(60000)});
      done++;
    } catch (error) { toast(`${file.name}: ${error.message}`, true); }
  }
  status.textContent = done ? `${done} foto(s) enviada(s). Elas aparecem na tela do notebook em instantes.` : '';
  if (done) toast('Fotos enviadas.');
  await loadPhotos().catch(() => {});
});
document.addEventListener('click', event => {
  const remove = event.target.closest('[data-remove-photo]');
  if (remove && confirm('Remover esta foto da tela do notebook?')) action(remove, async () => { await api(`/api/photos/${remove.dataset.removePhoto}`, {method: 'DELETE'}); await loadPhotos(); });
});
setTimeout(() => loadPhotos().catch(() => {}), 1800);
setInterval(() => { if (activePage === 'overview' && !document.hidden) loadPhotos().catch(() => {}); }, 30000);
