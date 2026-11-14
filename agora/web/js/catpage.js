// A CATEGORY PAGE (owner, 14 Nov: clicking "Lifestyle Services" hunted for the literal words and showed junk).
// A broad category (huntable === false in /api/categories*) never starts a hunt: it opens this page instead.
// Title in plain words + one line about what is inside, its subcategories as large cards (picture, name,
// "e.g." two or three concrete things, a count), "Popular:" chips that hunt concrete things, the concrete
// things directly in it A–Z, breadcrumbs and a search box scoped to the category. Only concrete nodes hunt.
// main.js shows it in phase 'category' (URL ?c=<id>) and emits 'catpage' {id, typed?}.
import * as core from './core.js';
import * as C from './cats.js';
import * as intent from './intent.js';

const { esc, t } = C;
let el = null;
const st = { id: null, data: null, typed: '', q: '', hits: null, hi: -1, seq: 0, next: null };

const catOf = (id, ids, path) => ({ id, ids, path });
const crumbIds = d => (d.path || []).map(p => p.id);
const crumbLabels = d => (d.path || []).map(p => p.label);

function header(d) {
  const sep = '<span class="cp-sep" aria-hidden="true">›</span>';
  const trail = [`<a href="/#ld-browse" data-home="1">${esc(t('home'))}</a>`]
    .concat((d.path || []).map((p, k, a) => k === a.length - 1
      ? `<span aria-current="page">${esc(p.label)}</span>`
      : `<a href="/?c=${encodeURIComponent(p.id)}" data-cat="${esc(p.id)}">${esc(p.label)}</a>`)).join(sep);
  const inside = (d.groups || []).concat(d.items || []).map(x => x.label);
  const about = d.about || (inside.length ? t('inside', inside.slice(0, 4).join(', '), Math.max(0, inside.length - 4)) : '');
  const hunt = d.huntable
    // a short verb, not the title again (owner, 14 Nov: long name buttons looked "goofy big")
    ? `<button type="button" class="cp-hunt" data-hunt-self="1" aria-label="${esc(t('huntAny', d.label))}" title="${esc(t('huntAny', d.label))}">${
      esc(t('hunt'))} <span aria-hidden="true">→</span></button>` : '';
  return `<nav class="cp-crumbs" aria-label="Category path">${trail}</nav>
    <header class="cp-head">
      <span class="cp-badge">${C.icon(d.icon, 'ct-ic cp-hic')}</span>
      <div class="cp-ht">
        <h1 class="cp-title">${esc(d.label)}${C.kindTag(d.kind)}</h1>
        ${about ? `<p class="cp-about">${esc(about)}</p>` : ''}
      </div>
      ${hunt}
    </header>`;
}

function typedNote(d) {
  if (!st.typed) return '';
  const choices = (d.popular || []).slice(0, 6);
  return `<div class="cp-typed" role="note"><p>${esc(t('shelf', st.typed))}</p>
    <div class="cp-chips">${choices.map((p, i) => `<button type="button" class="cp-chip strong" data-pop="${i}">${esc(p.q)}</button>`).join('')}
    <button type="button" class="cp-chip ghost" data-free="1">${esc(t('everything', st.typed))} →</button></div></div>`;
}

function popular(d) {
  const pop = d.popular || [];
  if (!pop.length || st.typed) return '';
  return `<div class="cp-pop"><span class="cp-pop-h">${esc(t('popularIn'))}:</span>
    <div class="cp-chips">${pop.map((p, i) => `<button type="button" class="cp-chip" data-pop="${i}">${esc(p.q)}</button>`).join('')}</div></div>`;
}

function search(d) {
  return `<div class="cp-find" role="search">
    <label class="cp-field"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>
      <span class="sr">${esc(t('findIn', d.label))}</span>
      <input class="cp-q" type="search" autocomplete="off" spellcheck="false" maxlength="80" placeholder="${esc(t('findIn', d.label))}"
        role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="cp-hits" value="${esc(st.q)}"></label>
    <div class="cp-hits" id="cp-hits" role="listbox" hidden></div>
  </div>`;
}

function card(g, i, root) {
  const pic = C.pictureFor(g.label, root);
  const eg = (g.examples || []).slice(0, 3);
  return `<li style="--d:${Math.min(i, 12) * 28}ms"><a class="cp-card" href="/?c=${encodeURIComponent(g.id)}" data-cat="${esc(g.id)}">
    <span class="cp-pic" data-pic="${esc(pic)}">${C.icon(pic, 'ct-ic cp-cic')}</span>
    <span class="cp-cb">
      <span class="cp-cn">${esc(g.label)}${C.kindTag(g.kind === d0().kind ? '' : g.kind)}</span>
      ${eg.length ? `<span class="cp-eg">${esc(t('eg'))} ${esc(eg.join(', '))}</span>` : ''}
      <span class="cp-cc">${C.num(g.count)} ${esc(t('subcats'))}</span>
    </span>
    <span class="cp-arrow" aria-hidden="true">→</span>
  </a></li>`;
}
const d0 = () => st.data || {};

function items(d) {
  const list = d.items || [];
  if (!list.length) return '';
  const head = d.groups && d.groups.length ? t('alsoHere') : t('popularIn');
  return `<section class="cp-sec" aria-labelledby="cp-items-h"><h2 class="cp-h2" id="cp-items-h">${esc(head)} <span class="cp-n">${C.num(list.length)}</span></h2>
    <ul class="cp-items" role="list">${list.map((x, i) => `<li><button type="button" class="cp-item${x.huntable ? '' : ' browse'}" data-item="${i}">
      <span>${esc(x.label)}</span>${C.kindTag(x.kind === d.kind ? '' : x.kind)}<span class="cp-go" aria-hidden="true">${x.huntable ? esc(t('hunt')) + ' →' : '›'}</span></button></li>`).join('')}</ul></section>`;
}

function official(d) {
  const list = d.official || [];
  if (!list.length) return '';
  return `<details class="cp-off"><summary>${esc(t('officialH'))} <span class="cp-n">${C.num(list.length)}</span></summary>
    <ul role="list">${list.map(x => `<li><a href="/?c=${encodeURIComponent(x.id)}" data-cat="${esc(x.id)}">${esc(x.label)}</a> <span class="cp-n">${C.num(x.count)}</span></li>`).join('')}</ul></details>`;
}

function render() {
  const d = st.data;
  if (!d) { el.innerHTML = `<div class="cp"><p class="cp-loading">${esc(t('loading'))}</p></div>`; return; }
  const groups = d.groups || [];
  const root = (d.path && d.path[0] && d.path[0].id) || d.icon;
  el.innerHTML = `<div class="cp">
    ${header(d)}
    ${typedNote(d)}
    <div class="cp-bar">${search(d)}${popular(d)}</div>
    ${groups.length ? `<ul class="cp-cards" role="list">${groups.map((g, i) => card(g, i, root)).join('')}</ul>` : ''}
    ${items(d)}
    ${!groups.length && !(d.items || []).length ? `<div class="it-slot"><p class="cp-loading">${esc(t('loading'))}</p></div>` : ''}
    ${official(d)}
    <p class="cp-note">${esc(t('browseNote'))}</p>
  </div>`;
}

// A category with nothing inside it (owner, 14 Nov: "School catering" said "Nothing here yet."): what we can
// search for it instead: its providers near you, the broader and sibling services, never a dead end.
async function fillNext(d) {
  const slot = el.querySelector('.it-slot');
  if (!slot) return;
  const my = st.seq;
  let blk = null;
  try { blk = await intent.nextSteps(d.id, d.label); } catch { blk = null; }
  if (my !== st.seq || st.id !== d.id) return;
  const now = el.querySelector('.it-slot');
  if (!now) return;
  st.next = blk;
  now.innerHTML = blk ? blk.html : `<p class="cp-empty">${esc(t('none2'))}</p>`;
}

function hitsHtml() {
  const hits = st.hits || [];
  const q = st.q.trim();
  return hits.map((h, i) => `<div class="cp-hit${i === st.hi ? ' hi' : ''}" role="option" id="cp-h-${i}" aria-selected="${i === st.hi}" data-hit="${i}">
      ${C.icon(C.pictureFor(h.label, h.icon))}<span class="cp-hl"><b>${esc(h.label)}</b>${C.kindTag(h.kind)}<span class="cp-ht2">${esc(h.path.slice(1, -1).join(' › '))}</span></span>
      <span class="cp-go">${h.huntable ? esc(t('hunt')) + ' →' : esc(t('open')) + ' ›'}</span></div>`).join('')
    + `<div class="cp-hit free" role="option" id="cp-h-free" data-free="1">${esc(t('everything', q))} →</div>`;
}
function paintHits() {
  const box = el.querySelector('.cp-hits'), qIn = el.querySelector('.cp-q');
  if (!box || !qIn) return;
  const open = !!st.q.trim() && st.hits !== null;
  box.hidden = !open;
  qIn.setAttribute('aria-expanded', String(open));
  if (open) box.innerHTML = hitsHtml();
  if (open && st.hi >= 0) qIn.setAttribute('aria-activedescendant', `cp-h-${st.hi}`); else qIn.removeAttribute('aria-activedescendant');
}
let qTimer = 0;
function onQuery(v) {
  st.q = v;
  clearTimeout(qTimer);
  if (v.trim().length < 2) { st.hits = null; paintHits(); return; }
  qTimer = setTimeout(async () => {
    const my = ++st.seq;
    const r = await C.searchIn(v.trim(), st.id, 10);
    if (my !== st.seq) return;
    st.hits = (r && r.items) || [];
    st.hi = -1;
    paintHits();
  }, 90);
}

function hunt(label, id) {
  const d = st.data;
  core.emit('ask', { q: label, cat: id ? { id } : (d ? catOf(d.id, crumbIds(d), crumbLabels(d)) : null) });
}

function onClick(e) {
  const d = st.data;
  if (!d) return;
  if (st.next && e.target.closest('.it-cp') && st.next.click(e)) return;
  const a = e.target.closest('[data-cat]');
  if (a) { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); C.openCategory(a.dataset.cat); return; }
  if (e.target.closest('[data-home]')) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); core.emit('category:home', {}); return; }
  if (e.target.closest('[data-hunt-self]')) { core.emit('ask', { q: d.label, cat: catOf(d.id, crumbIds(d), crumbLabels(d)) }); return; }
  const pop = e.target.closest('[data-pop]');
  if (pop) { const p = d.popular[Number(pop.dataset.pop)]; if (p) hunt(p.q, p.id); return; }
  const it = e.target.closest('[data-item]');
  if (it) {
    const x = d.items[Number(it.dataset.item)];
    if (!x) return;
    if (x.huntable === false) C.openCategory(x.id);
    else core.emit('ask', { q: x.label, cat: catOf(x.id, crumbIds(d).concat(x.id), crumbLabels(d).concat(x.label)) });
    return;
  }
  const h = e.target.closest('[data-hit]');
  if (h) { const x = (st.hits || [])[Number(h.dataset.hit)]; if (x) C.go(x); return; }
  if (e.target.closest('[data-free]')) { const q = (st.q.trim() || st.typed); if (q) core.emit('ask', { q, free: true }); }
}

function onKey(e) {
  if (!e.target.classList.contains('cp-q')) return;
  const hits = st.hits || [];
  if (e.key === 'ArrowDown' && hits.length) { e.preventDefault(); st.hi = Math.min(hits.length - 1, st.hi + 1); paintHits(); }
  else if (e.key === 'ArrowUp' && hits.length) { e.preventDefault(); st.hi = Math.max(-1, st.hi - 1); paintHits(); }
  else if (e.key === 'Enter') {
    e.preventDefault();
    if (st.hi >= 0 && hits[st.hi]) C.go(hits[st.hi]);
    else if (st.q.trim()) core.emit('ask', { q: st.q.trim(), free: true });
  } else if (e.key === 'Escape' && st.q) { e.preventDefault(); e.target.value = ''; onQuery(''); }
}

export async function show(id, { typed = '' } = {}) {
  if (!el) return;
  const fresh = id !== st.id;
  st.id = id; st.typed = typed || ''; st.q = ''; st.hits = null; st.hi = -1;
  if (fresh) st.data = null;
  render();
  const my = ++st.seq;
  const d = await C.page(id);
  if (my !== st.seq || st.id !== id) return;
  if (!d) { st.data = { id, label: id, path: [], groups: [], items: [], popular: [] }; render(); return; }
  st.data = d;
  st.id = d.id;
  st.next = null;
  render();
  if (!(d.groups || []).length && !(d.items || []).length) fillNext(d);
  document.title = `${d.label} · ${core.BRAND}`;
  core.emit('catpage:shown', { id: d.id, asked: id, label: d.label });
}

export function mountCatpage(host) {
  if (!host || el) return;
  el = host;
  el.addEventListener('click', onClick);
  el.addEventListener('keydown', onKey);
  el.addEventListener('input', e => { if (e.target.classList.contains('cp-q')) onQuery(e.target.value); });
  el.addEventListener('focusout', e => {
    if (e.target.classList.contains('cp-q')) setTimeout(() => { if (!el.contains(document.activeElement)) { st.hits = null; paintHits(); } }, 150);
  });
  core.on('catpage', d => { if (d && d.id) show(d.id, { typed: d.typed }); });
  core.on('lang', () => { if (st.id && document.getElementById('app').dataset.phase === 'category') show(st.id, { typed: st.typed }); });
}
