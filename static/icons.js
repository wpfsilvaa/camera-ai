// Icons come from the SVG sprite at the top of index.html, so they look the same on every phone (emoji do not).
window.ic = (name, cls = '') => `<svg class="ic${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#ic-${name}"/></svg>`;
