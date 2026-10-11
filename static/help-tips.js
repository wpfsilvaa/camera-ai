// Settings hints: each switch's explanation gets a "?" button; on phones the text stays folded until it is tapped.
(() => {
  function decorate(root = document) {
    for (const row of root.querySelectorAll('.switch-row > span:not(.has-tip)')) {
      const hint = row.querySelector(':scope > small'), title = row.querySelector(':scope > strong');
      if (!hint || !title) continue;
      row.classList.add('has-tip');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'tip-button';
      button.textContent = '?';
      button.setAttribute('aria-expanded', 'false');
      button.setAttribute('aria-label', `Explicação: ${title.textContent}`);
      button.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        const open = hint.classList.toggle('tip-open');
        button.setAttribute('aria-expanded', String(open));
      });
      title.after(button);
    }
  }
  decorate();
})();
