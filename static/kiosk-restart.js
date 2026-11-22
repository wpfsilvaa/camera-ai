// Botão "Reiniciar a tela do totem": dois toques (o segundo confirma), para não reiniciar sem querer.
(() => {
  let armed = null;
  document.addEventListener('click', event => {
    const button = event.target.closest('#kiosk-restart');
    if (!button) return;
    if (!armed) {
      button.textContent = 'Toque de novo para confirmar';
      button.classList.add('danger');
      armed = setTimeout(() => { armed = null; button.textContent = button.dataset.label; button.classList.remove('danger'); }, 4000);
      return;
    }
    clearTimeout(armed); armed = null;
    button.classList.remove('danger'); button.textContent = button.dataset.label;
    action(button, async () => {
      await api('/api/kiosk/restart', {method: 'POST'});
      toast('Reiniciando a tela do totem. Ela volta em uns 10 segundos.');
    });
  });
})();
