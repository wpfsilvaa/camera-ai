// Registro de presença: avançar/voltar entre os registros do histórico (botões nas laterais, setas do teclado e arrastar no celular).
(() => {
  const dialog = document.querySelector('#event-dialog'), nav = document.querySelector('#event-nav');
  const prev = document.querySelector('#event-prev'), next = document.querySelector('#event-next');
  const PAGE = 20;
  let busy = false;
  const position = () => navIds.indexOf(selectedEvent?.id);
  const hasNeighbor = dir => {
    const pos = position();
    if (pos < 0) return false;
    if (pos + dir >= 0 && pos + dir < navIds.length) return true;
    return dir > 0 ? offset + PAGE < total : offset > 0;
  };
  window.updateEventNav = () => {
    const pos = position();
    nav.classList.toggle('hidden', pos < 0);
    prev.disabled = !hasNeighbor(-1);
    next.disabled = !hasNeighbor(1);
    if (pos >= 0) dialog.querySelector('#event-number').dataset.pos = `${offset + pos + 1} de ${total}`;
  };
  async function step(dir) {
    if (busy || !dialog.open || !hasNeighbor(dir)) return;
    busy = true;
    try {
      let pos = position() + dir;
      if (pos < 0 || pos >= navIds.length) {
        offset += dir * PAGE;
        await loadHistory();
        navIds = historyEvents.map(e => e.id);
        pos = dir > 0 ? 0 : navIds.length - 1;
      }
      openEvent(await api(`/api/events/${navIds[pos]}`));
      dialog.scrollTop = 0;
    } catch (error) { toast(error.message, true); }
    finally { busy = false; }
  }
  prev.addEventListener('click', () => step(-1));
  next.addEventListener('click', () => step(1));

  document.addEventListener('keydown', event => {
    if (!dialog.open || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    if (event.target.closest('input, select, textarea, video, [contenteditable]')) return;
    event.preventDefault();
    step(event.key === 'ArrowRight' ? 1 : -1);
  });

  // Arrastar no celular: para a esquerda = próximo, para a direita = anterior.
  let start = null;
  dialog.addEventListener('touchstart', event => {
    if (event.touches.length !== 1 || event.target.closest('video, canvas, input, select, textarea, .sample-strip, .table-scroll')) { start = null; return; }
    start = {x: event.touches[0].clientX, y: event.touches[0].clientY, t: Date.now()};
  }, {passive: true});
  dialog.addEventListener('touchend', event => {
    if (!start) return;
    const touch = event.changedTouches[0], dx = touch.clientX - start.x, dy = touch.clientY - start.y;
    const quick = Date.now() - start.t < 800;
    start = null;
    if (quick && Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 2) step(dx < 0 ? 1 : -1);
  }, {passive: true});
  dialog.addEventListener('close', () => { navIds = []; });
})();
