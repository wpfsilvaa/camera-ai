// Como a casa chama a pessoa acompanhada ("pai", "mãe", "avó"...). Os textos do painel são escritos para "pai";
// aqui eles são adaptados (gênero e palavra) quando a instalação usa outra relação. Texto digitado pelos
// usuários (recados, diário, campos) nunca é alterado.
(() => {
  const REL = {pai: 'm', 'mãe': 'f', 'avô': 'm', 'avó': 'f', sogro: 'm', sogra: 'f', tio: 'm', tia: 'f', 'irmão': 'm', 'irmã': 'f', marido: 'm', esposa: 'f'};
  const KEY = 'casa-elder';
  const cap = word => word.charAt(0).toUpperCase() + word.slice(1);
  const norm = value => (value in REL ? value : 'pai');
  let relation = 'pai';
  try { relation = norm(localStorage.getItem(KEY)); } catch {}

  const terms = (rel = relation) => {
    rel = norm(rel); const f = REL[rel] === 'f';
    const my = f ? 'minha' : 'meu', your = f ? 'sua' : 'seu';
    return {rel, Rel: cap(rel), my, your, the: f ? 'a' : 'o', of_the: f ? 'da' : 'do', he: f ? 'ela' : 'ele', label: `${cap(my)} ${rel}`, your_rel: `${your} ${rel}`, feminine: f};
  };
  window.elderTerms = terms;

  const SPECIAL = [['Foi ele', 'Foi ela'], ['Ele ouve você', 'Ela ouve você'], ['e ele ouve você', 'e ela ouve você'], ['das dele', 'das dela'], ['fala com ele', 'fala com ela'],
    ['se ele não aparecer', 'se ela não aparecer'], ['Se ele chegar', 'Se ela chegar'], ['enquanto ele estiver', 'enquanto ela estiver'], ['como ele estava', 'como ela estava']];
  const ART = {do: 'da', Do: 'Da', ao: 'à', Ao: 'À', no: 'na', No: 'Na', pelo: 'pela', Pelo: 'Pela', o: 'a', O: 'A', um: 'uma'};
  const POSS = {meu: 'minha', seu: 'sua', teu: 'tua', Meu: 'Minha', Seu: 'Sua'};
  function convert(text) {
    if (relation === 'pai') return text;
    const t = terms(), f = t.feminine;
    if (!/pai/i.test(text) && !(f && /\b(ele|dele)\b/.test(text))) return text;
    let s = text;
    if (f) {
      s = s.replace(/\b(do|Do|ao|Ao|no|No|pelo|Pelo|o|O)( (?:meu|seu|teu))? pai\b/g, (_, a, p) => `${ART[a]}${p ? ' ' + POSS[p.trim()] : ''} ${t.rel}`);
      s = s.replace(/\b(Meu|Seu|meu|seu|teu) pai\b/g, (_, p) => `${POSS[p]} ${t.rel}`);
      for (const [from, to] of SPECIAL) s = s.split(from).join(to);
    }
    return s.replace(/\bPai\b/g, t.Rel).replace(/\bpai\b/g, t.rel);
  }
  window.elderConvert = convert;

  const SKIP = '[data-raw], textarea, input, select, script, style, #messages-list, #journal-list, #journal-tag, #people-profiles, .profile-card, .person-track, #recipients-list';
  const originals = new WeakMap();   // texto original de cada nó, para poder trocar de relação sem recarregar
  function walk(root) {
    if (root.nodeType === 3) return fixText(root);
    if (root.nodeType !== 1 || root.closest?.(SKIP)) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) fixText(n);
    for (const el of root.querySelectorAll('[placeholder],[aria-label],[title]')) {
      if (el.closest(SKIP) && el.tagName !== 'TEXTAREA' && el.tagName !== 'INPUT') continue;
      for (const attr of ['placeholder', 'aria-label', 'title']) {
        const v = el.getAttribute(attr); if (!v) continue;
        const key = `data-orig-${attr}`, base = el.getAttribute(key) ?? v;
        if (!el.hasAttribute(key)) el.setAttribute(key, v);
        const out = convert(base); if (out !== v) el.setAttribute(attr, out);
      }
    }
  }
  function fixText(node) {
    if (node.parentElement?.closest(SKIP)) return;
    const base = originals.has(node) && originals.get(node).out === node.nodeValue ? originals.get(node).base : node.nodeValue;
    const out = convert(base);
    if (out !== node.nodeValue) { originals.set(node, {base, out}); node.nodeValue = out; }
    else if (out !== base) originals.set(node, {base, out});
  }
  let busy = false;
  const observer = new MutationObserver(records => {
    if (busy || relation === 'pai') return;
    busy = true;
    for (const r of records) {
      if (r.type === 'characterData') fixText(r.target);
      else r.addedNodes.forEach(walk);
    }
    busy = false;
  });
  function apply() { busy = true; walk(document.body); busy = false; document.title = convert(document.title); }
  window.setElderRelation = value => {
    value = norm(value);
    if (value === relation) return;
    relation = value;
    try { localStorage.setItem(KEY, value); } catch {}
    apply(); document.dispatchEvent(new CustomEvent('elderchange', {detail: value}));
  };
  document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, {childList: true, subtree: true, characterData: true});
    apply();
  });
})();
