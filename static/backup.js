function sizeText(bytes) {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

async function loadBackup() {
  if (!isAdmin()) return;
  const backup = await api('/api/backup');
  const last = backup.last_ok ? `Último backup: ${day(backup.last_ok)} às ${time(backup.last_ok)} (${sizeText(backup.last_size)}). ${backup.count} cópia(s) na pasta.` : 'Nenhum backup feito ainda.';
  const failed = backup.last_error ? ` Última falha (${day(backup.last_error_at)} às ${time(backup.last_error_at)}): ${backup.last_error}` : '';
  $('#backup-status').textContent = last + failed;
  $('#backup-status').classList.toggle('backup-error', Boolean(backup.last_error));
}

$('#backup-now').addEventListener('click', event => action(event.currentTarget, async () => {
  try {
    const result = await api('/api/backup/run', {method:'POST', signal:AbortSignal.timeout(300000)});
    toast(`Backup criado: ${result.file}`);
  } finally {
    await loadBackup();
  }
}));
