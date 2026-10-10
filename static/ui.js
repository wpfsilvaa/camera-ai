// Appearance toggle, grouped settings and the "unsaved changes" hint.
(() => {
  const $ = selector => document.querySelector(selector);

  // Theme -------------------------------------------------------------------
  const icons = {auto: '◐', light: '☀', dark: '☾'};
  const names = {auto: 'automática (segue o aparelho)', light: 'clara', dark: 'escura'};
  function paintTheme() {
    const mode = casaTheme.get(), button = $('#theme-toggle');
    button.firstElementChild.textContent = icons[mode];
    button.setAttribute('aria-label', `Aparência: ${names[mode]}. Toque para trocar.`);
    button.title = `Aparência ${names[mode]}`;
  }
  $('#theme-toggle').addEventListener('click', () => {
    const modes = casaTheme.modes, next = modes[(modes.indexOf(casaTheme.get()) + 1) % modes.length];
    casaTheme.set(next);
    paintTheme();
    toast(`Aparência ${names[next]}.`);
  });
  paintTheme();

  // Settings groups ---------------------------------------------------------
  const tabs = [...document.querySelectorAll('.settings-tab')];
  function showGroup(group) {
    for (const tab of tabs) {
      const on = tab.dataset.group === group;
      tab.setAttribute('aria-selected', on);
      tab.tabIndex = on ? 0 : -1;
    }
    document.querySelectorAll('#settings-form .settings-panel').forEach(panel => panel.classList.toggle('hidden', panel.dataset.group !== group));
    try { sessionStorage.setItem('casa-settings-group', group); } catch {}
    window.dispatchEvent(new Event('resize'));  // The fall-zone canvas measures itself when it becomes visible.
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => showGroup(tab.dataset.group));
    tab.addEventListener('keydown', event => {
      const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
      if (!step) return;
      const next = tabs[(index + step + tabs.length) % tabs.length];
      next.focus(); showGroup(next.dataset.group);
    });
  });
  let saved = 'camera';
  try { saved = sessionStorage.getItem('casa-settings-group') || saved; } catch {}
  showGroup(tabs.some(tab => tab.dataset.group === saved) ? saved : 'camera');

  // Unsaved changes -----------------------------------------------------------
  const actions = $('.settings-actions'), hint = actions.querySelector('.muted');
  const idle = hint.textContent;
  const mark = dirty => {
    actions.classList.toggle('dirty', dirty);
    hint.textContent = dirty ? '● Alterações ainda não salvas' : idle;
  };
  $('#settings-form').addEventListener('input', () => mark(true));
  window.settingsSaved = () => mark(false);
})();
