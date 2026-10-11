// Volumes of the kitchen screen's sounds (day and night) with "Testar" buttons that play on the screen right away.
function syncVolumeLabels() {
  document.querySelectorAll('#sound-panel input[type=range]').forEach(input => {
    const out = document.querySelector(`#sound-panel output[data-for="${input.name}"]`);
    if (out) out.textContent = `${input.value}%`;
  });
}
window.syncVolumeLabels = syncVolumeLabels;
document.addEventListener('input', event => { if (event.target.matches?.('#sound-panel input[type=range]')) syncVolumeLabels(); });
document.addEventListener('click', event => {
  const button = event.target.closest('[data-test-sound]');
  if (!button) return;
  const input = document.querySelector(`#sound-panel input[name="${button.dataset.testInput}"]`);
  action(button, async () => {
    await api('/api/kiosk/test', {method: 'POST', body: JSON.stringify({sound: button.dataset.testSound, volume: Number(input.value)})});
    toast(button.dataset.testSound === 'message' ? 'Teste enviado: veja o cartão de exemplo na tela do notebook.' : 'Teste enviado para a tela do notebook.');
  });
});
setTimeout(syncVolumeLabels, 2500);
