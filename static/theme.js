// Appearance: automatic (follows the device), light or dark. Loaded in <head> so the page never flashes.
(() => {
  const KEY = 'casa-theme', MODES = ['auto', 'light', 'dark'];
  const query = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
  const stored = () => { try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'auto'; } catch { return 'auto'; } };
  function apply(mode) {
    const dark = mode === 'dark' || (mode === 'auto' && query && query.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    const bar = document.querySelector('meta[name=theme-color]');
    if (bar) bar.content = dark ? '#0f1713' : '#163d32';
  }
  window.casaTheme = {
    modes: MODES,
    get: stored,
    set(mode) {
      try { localStorage.setItem(KEY, mode); } catch {}
      apply(mode);
      document.dispatchEvent(new CustomEvent('themechange', {detail: mode}));
    },
  };
  apply(stored());
  if (query) query.addEventListener('change', () => stored() === 'auto' && apply('auto'));
  document.addEventListener('DOMContentLoaded', () => apply(stored()));
})();
