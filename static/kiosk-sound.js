// Volumes of the kitchen screen's sounds (day and night) with "Testar" buttons that play on the screen right away.
function syncVolumeLabels() {
  document.querySelectorAll('output[data-for]').forEach(out => {
    const input = document.querySelector(`input[name="${out.dataset.for}"]`);
    if (input) out.textContent = `${input.value}%`;
  });
}
window.syncVolumeLabels = syncVolumeLabels;
document.addEventListener('input', event => { if (event.target.matches?.('input[type=range]')) syncVolumeLabels(); });
document.addEventListener('click', event => {
  const button = event.target.closest('[data-test-sound]');
  if (!button) return;
  const input = document.querySelector(`input[name="${button.dataset.testInput}"]`);
  action(button, async () => {
    await api('/api/kiosk/test', {method: 'POST', body: JSON.stringify({sound: button.dataset.testSound, volume: Number(input.value)})});
    toast(button.dataset.testSound === 'message' ? 'Teste enviado: veja o cartão de exemplo na tela do notebook.' : button.dataset.testSound === 'brightness' ? 'Brilho aplicado por 6 segundos na tela do notebook.' : 'Teste enviado para a tela do notebook.');
  });
});
setTimeout(syncVolumeLabels, 2500);
