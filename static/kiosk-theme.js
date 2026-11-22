// Aparência da tela do totem: paletas, cores próprias, tamanho do texto e o que aparece, com pré-visualização ao vivo.
(() => {
  const NAMES = ['bg', 'ink', 'call', 'panic', 'accent'], SHOW = ['weather', 'present', 'vigia', 'battery', 'date', 'holidays'];
  const $q = sel => document.querySelector(sel);
  const field = name => $q(`#kiosk-theme-panel [name="${name}"]`);
  const preset = () => { const option = field('kiosk_palette')?.selectedOptions[0]; try { return JSON.parse(option?.dataset.colors || 'null'); } catch { return null; } };
  const luminance = hex => { const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4); return .2126 * r + .7152 * g + .0722 * b; };
  const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m); return (x + .05) / (y + .05); };

  function colors() {
    const chosen = preset();
    return chosen || Object.fromEntries(NAMES.map(n => [n, field(`kiosk_color_${n}`)?.value || '#000000']));
  }
  function paint() {
    const box = $q('#totem-preview');
    if (!box) return;
    const c = colors();
    box.style.setProperty('--bg', c.bg); box.style.setProperty('--ink', c.ink); box.style.setProperty('--call', c.call); box.style.setProperty('--panic', c.panic); box.style.setProperty('--accent', c.accent);
    box.dataset.size = field('kiosk_text_size')?.value || 'normal';
    for (const name of SHOW) box.querySelectorAll(`[data-tp="${name}"]`).forEach(el => { el.hidden = !field(`kiosk_show_${name}`)?.checked; });
    const calendar = $q('[name="kiosk_calendar_enabled"]');
    box.querySelector('[data-tp="calendar"]').hidden = calendar ? !calendar.checked : false;
    const warnings = [];
    if (contrast(c.ink, c.bg) < 4.5) warnings.push('o texto e o fundo têm pouco contraste');
    if (contrast('#ffffff', c.call) < 3) warnings.push('o botão “Chamar a família” está claro demais para o texto branco');
    if (contrast('#ffffff', c.panic) < 3) warnings.push('o botão “Preciso de ajuda” está claro demais para o texto branco');
    const note = $q('#theme-warning');
    note.textContent = warnings.length ? `Atenção: ${warnings.join('; ')}. Pode ficar difícil de ler.` : '';
    note.style.color = warnings.length ? 'var(--amber-ink)' : '';
  }
  document.addEventListener('change', event => {
    const target = event.target;
    if (!target.closest?.('#kiosk-theme-panel')) return;
    if (target.name === 'kiosk_palette') {   // A ready palette fills the pickers, so "Personalizada" starts from it.
      const chosen = preset();
      if (chosen) NAMES.forEach(n => { field(`kiosk_color_${n}`).value = chosen[n]; });
    }
    paint();
  });
  document.addEventListener('input', event => {
    const target = event.target;
    if (!target.closest?.('#kiosk-theme-panel')) return;
    if (target.name?.startsWith('kiosk_color_') && field('kiosk_palette').value !== 'personalizada') field('kiosk_palette').value = 'personalizada';
    paint();
  });
  document.addEventListener('change', event => { if (event.target.name === 'kiosk_calendar_enabled') paint(); });
  document.addEventListener('click', event => {
    if (!event.target.closest('#kiosk-theme-reset')) return;
    field('kiosk_palette').value = 'padrao';
    field('kiosk_palette').dispatchEvent(new Event('change', {bubbles: true}));
    field('kiosk_text_size').value = 'normal';
    SHOW.forEach(name => { field(`kiosk_show_${name}`).checked = true; });
    document.getElementById('settings-form')?.dispatchEvent(new Event('input', {bubbles: true}));
    paint();
  });
  setInterval(paint, 1500);   // The form is filled by script (no event).
  paint();
})();
