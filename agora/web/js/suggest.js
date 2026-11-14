// Type-ahead under the main search box: categories from the tree as you type (any of its languages), plus the
// free text itself. Picking a category asks for a hunt with its label (in the viewer's language) and its path.
// main.js calls mountSuggest(form, input); the list is a combobox listbox under the box.
import * as core from './core.js';
import * as C from './cats.js';

const { esc, t } = C;

export function mountSuggest(form, input) {
  if (!form || !input || form.querySelector('.sg')) return;
  const box = document.createElement('div');
  box.className = 'sg';
  box.id = 'sg-list';
  box.setAttribute('role', 'listbox');
  box.setAttribute('aria-label', 'Suggestions');
  box.hidden = true;
  form.appendChild(box);
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', 'sg-list');
  input.setAttribute('aria-expanded', 'false');

  let items = [], hi = -1, timer = 0, seq = 0, typed = '';
  const close = () => { box.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); hi = -1; };
  const paint = () => {
    const q = typed.trim();
    if (!q || !items.length) { close(); return; }
    box.innerHTML = `<div class="sg-free" role="option" id="sg-o-free" aria-selected="false" data-i="-2">
        <svg viewBox="0 0 24 24" aria-hidden="true" class="ct-ic"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>
        <span>${esc(t('free', q))}</span></div>
      <p class="sg-h">${esc(t('catsH'))}</p>` +
      items.map((h, i) => `<div class="sg-o${i === hi ? ' hi' : ''}" role="option" id="sg-o-${i}" aria-selected="${i === hi}" data-i="${i}">
        ${C.icon(h.icon)}<span class="sg-t"><b>${esc(h.label)}</b>${C.kindTag(h.kind)}<span class="sg-p">${esc(h.path.slice(0, -1).join(' › '))}</span></span>
      </div>`).join('');
    box.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    if (hi >= 0) input.setAttribute('aria-activedescendant', `sg-o-${hi}`); else input.removeAttribute('aria-activedescendant');
  };
  const fetchNow = async () => {
    const q = typed.trim();
    const my = ++seq;
    if (q.length < 2) { items = []; close(); return; }
    const r = await C.search(q, 6);
    if (my !== seq || typed.trim() !== q) return;
    items = (r && r.items) || [];
    hi = -1;
    if (document.activeElement === input) paint();
  };
  const pick = i => {
    const h = items[i];
    if (!h) return;
    close();
    const q = h.label.replace(/­/g, '');
    input.value = q;
    core.emit('ask', { q, cat: { id: h.id, ids: h.path_ids, path: h.path } });
  };

  input.addEventListener('input', () => {
    typed = input.value;
    clearTimeout(timer);
    timer = setTimeout(fetchNow, 90);
  });
  input.addEventListener('focus', () => { if (typed && input.value === typed && items.length) paint(); });
  input.addEventListener('keydown', e => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); hi = Math.min(items.length - 1, hi + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); hi = Math.max(-1, hi - 1); paint(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Enter' && hi >= 0) { e.preventDefault(); e.stopPropagation(); pick(hi); }
  });
  // the free text goes through the form as before; any submit closes the list
  form.addEventListener('submit', () => { seq++; close(); }, true);
  box.addEventListener('mousedown', e => e.preventDefault());       // keep focus in the box while clicking
  box.addEventListener('click', e => {
    const o = e.target.closest('[data-i]');
    if (!o) return;
    const i = Number(o.dataset.i);
    if (i === -2) { close(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true })); }
    else pick(i);
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
  core.on('lang', () => { if (typed.trim()) fetchNow(); });
  core.on('reset', () => { seq++; close(); });
}
