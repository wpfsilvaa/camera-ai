// Quadrinhos da tela do totem: ligar/desligar e reordenar (arrastando ou pelas setas), com a prévia acompanhando.
(() => {
  const IDS = ['calendar', 'clock', 'quote', 'photo', 'medication'];
  const $q = sel => document.querySelector(sel);
  const hidden = () => $q('#kiosk-widgets-panel [name="kiosk_widgets"]');
  const calendarBox = () => $q('[name="kiosk_calendar_enabled"]');
  const parse = value => {
    const seen = new Set(), items = [];
    for (const part of String(value || '').split(',')) {
      const id = part.trim().replace(/^-/, '');
      if (IDS.includes(id) && !seen.has(id)) { seen.add(id); items.push({id, on: !part.trim().startsWith('-')}); }
    }
    for (const id of IDS) if (!seen.has(id)) items.push({id, on: false});
    return items;
  };
  let items = null, dragging = null, lastValue = null, lastCalendar = null;

  const csv = () => items.map(item => (item.on || item.id === 'calendar' ? '' : '-') + item.id).join(',');   // The calendar is on or off by its own switch.
  function commit() {
    hidden().value = csv(); lastValue = hidden().value;
    document.getElementById('settings-form')?.dispatchEvent(new Event('input', {bubbles: true}));   // Marks the form as changed.
    paint();
  }
  function paint() {
    const list = $q('#wg-list');
    if (!list || !items) return;
    const box = calendarBox();
    list.innerHTML = '';
    for (const [index, item] of items.entries()) {
      const row = document.getElementById('wg-template').content.querySelector(`[data-id="${item.id}"]`).cloneNode(true);
      row.classList.toggle('off', !item.on);
      row.querySelector('[data-wg-on]').checked = item.on;
      row.querySelector('[data-wg-up]').disabled = index === 0;
      row.querySelector('[data-wg-down]').disabled = index === items.length - 1;
      list.append(row);
    }
    // Preview: the same order, only the tiles that are on.
    const board = $q('#tp-board');
    if (board) {
      const on = items.filter(item => item.on);
      for (const item of items) {
        const tile = board.querySelector(item.id === 'calendar' ? '[data-tp="calendar"]' : `[data-tw="${item.id}"]`);
        if (!tile) continue;
        const index = on.indexOf(item);
        tile.hidden = index < 0; tile.style.order = String(index < 0 ? 99 : index); tile.style.gridColumn = '';
      }
      board.dataset.count = String(on.length);
      if (on.length > 1 && on.length % 2) { const last = on[on.length - 1], tile = board.querySelector(last.id === 'calendar' ? '[data-tp="calendar"]' : `[data-tw="${last.id}"]`); if (tile) tile.style.gridColumn = '1 / -1'; }
      board.hidden = on.length === 0;
    }
    const total = items.filter(item => item.on).length;
    $q('#wg-count') && ($q('#wg-count').textContent = total > 4 ? 'Muitos quadrinhos: tudo fica pequeno na tela.' : '');
    meds();
  }
  function meds() {
    const area = $q('#kiosk-widgets-panel [name="kiosk_medications"]'), note = $q('#wg-meds-note');
    if (!area || !note) return;
    const lines = area.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (!lines.length) { note.textContent = 'O quadrinho mostra o próximo horário e fica destacado quando falta 30 minutos ou menos.'; return; }
    const ok = lines.filter(line => /^([01]?\d|2[0-3]):[0-5]\d\s+\S/.test(line)), bad = lines.length - ok.length;
    note.textContent = `Entendi ${ok.length} horário(s).${bad ? ` ${bad} linha(s) ignorada(s): use “08:00 Nome do remédio”.` : ''}`;
    note.style.color = bad ? 'var(--amber-ink)' : '';
  }
  function sync() {   // The form is filled by script (and the calendar switch lives elsewhere too): follow both without touching the form.
    const field = hidden(), box = calendarBox();
    if (!field) return;
    const calendarOn = box ? box.checked : true;
    if (items === null || field.value !== lastValue) { items = parse(field.value); lastValue = field.value; items.find(item => item.id === 'calendar').on = calendarOn; lastCalendar = calendarOn; paint(); return; }
    if (calendarOn !== lastCalendar) { items.find(item => item.id === 'calendar').on = calendarOn; lastCalendar = calendarOn; paint(); }
  }
  const move = (from, to) => { if (to < 0 || to >= items.length || from === to) return; const [item] = items.splice(from, 1); items.splice(to, 0, item); commit(); };
  const indexOf = element => items.findIndex(item => item.id === element.closest('.wg-row').dataset.id);

  document.addEventListener('click', event => {
    if (!items) return;
    const up = event.target.closest('[data-wg-up]'), down = event.target.closest('[data-wg-down]');
    if (up) move(indexOf(up), indexOf(up) - 1);
    else if (down) move(indexOf(down), indexOf(down) + 1);
    else if (event.target.closest('#wg-reset')) { items = parse('calendar,-clock,-quote,-photo,-medication'); commit(); }
  });
  document.addEventListener('change', event => {
    const box = event.target.closest?.('[data-wg-on]');
    if (!box || !items) return;
    const item = items[indexOf(box)];
    item.on = box.checked;
    if (item.id === 'calendar') { const real = calendarBox(); if (real) { real.checked = box.checked; lastCalendar = box.checked; } document.getElementById('settings-form')?.dispatchEvent(new Event('input', {bubbles: true})); paint(); }
    else commit();
  });
  document.addEventListener('input', event => { if (event.target.name === 'kiosk_medications') meds(); });
  document.addEventListener('dragstart', event => { const row = event.target.closest?.('.wg-row'); if (!row) return; dragging = row.dataset.id; row.classList.add('dragging'); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', dragging); });
  document.addEventListener('dragover', event => { if (dragging && event.target.closest?.('.wg-row')) event.preventDefault(); });
  document.addEventListener('drop', event => {
    const row = event.target.closest?.('.wg-row');
    if (!dragging || !row) return;
    event.preventDefault();
    const from = items.findIndex(item => item.id === dragging), to = items.findIndex(item => item.id === row.dataset.id);
    dragging = null; move(from, to);
  });
  document.addEventListener('dragend', () => { dragging = null; $q('#wg-list .dragging')?.classList.remove('dragging'); });
  setInterval(sync, 700);
  sync();
})();
