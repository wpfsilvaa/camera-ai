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
  const input = button.dataset.testInput ? document.querySelector(`input[name="${button.dataset.testInput}"]`) : null;
  action(button, async () => {
    await api('/api/kiosk/test', {method: 'POST', body: JSON.stringify({sound: button.dataset.testSound, volume: Math.min(100, input ? Number(input.value) : Number(button.dataset.testVolume || 70))})});
    toast(button.dataset.testSound === 'message' ? 'Teste enviado: veja o cartão de exemplo na tela do notebook.' : button.dataset.testSound === 'brightness' ? 'Brilho aplicado por 6 segundos na tela do notebook.' : button.dataset.testSound === 'screenoff' ? 'A tela do notebook apaga por 5 segundos e liga de novo.' : button.dataset.testSound === 'rain' ? 'Chuva na tela do notebook por 15 segundos.' : 'Teste enviado para a tela do notebook.');
  });
});
setTimeout(syncVolumeLabels, 2500);
// "Testar o lembrete" (restricted mode): plays the reminder on the screen with the text as typed, at the message volume.
document.addEventListener('click', event => {
  const button = event.target.closest('#test-reminder');
  if (!button) return;
  const volume = Number(document.querySelector('input[name="kiosk_vol_message_day"]')?.value || 80);
  const text = document.querySelector('input[name="restricted_reminder_text"]')?.value.trim() || '';
  action(button, async () => {
    await api('/api/kiosk/test', {method: 'POST', body: JSON.stringify({sound: 'nudge', volume, text})});
    toast('Teste enviado: veja o lembrete na tela do notebook.');
  });
});
// "Ouvir esta voz": the notebook reads a sample with the voice picked in the list (no need to save first), at the message volume.
document.addEventListener('click', event => {
  const button = event.target.closest('#test-voice');
  if (!button) return;
  const volume = Number(document.querySelector('input[name="kiosk_vol_message_day"]')?.value || 80);
  const voice = document.querySelector('select[name="kiosk_voice"]')?.value || '';
  action(button, async () => {
    await api('/api/kiosk/test', {method: 'POST', body: JSON.stringify({sound: 'voice', volume, voice})});
    toast('Teste enviado: a tela do notebook vai ler um exemplo em alguns segundos.');
  });
});
