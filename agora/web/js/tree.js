// "Browse everything": the tree of everything you can buy (products AND services) as a big shop's mega menu.
// Desktop: all roots on the left (things | services), Miller columns to the right (children, grandchildren …,
// the last three levels), a breadcrumb with "Hunt for X". Phone: a drill-down list with breadcrumbs.
// A search box inside finds any of the ~35k categories instantly. Clicking a concrete leaf (or "Hunt for X") asks
// for a hunt with the label in the viewer's language and the category path (main.js shows it as a breadcrumb).
// A broad category (huntable === false: "Lifestyle Services", a whole department) never hunts its own label:
// "See all of X" opens its category page (catpage.js) with concrete subcategories to pick from.
import * as core from './core.js';
import * as C from './cats.js';
import { recordings, queryFor } from './stream.js';

const { esc, t } = C;
const PHONE = typeof matchMedia === 'function' ? matchMedia('(max-width: 760px)') : { matches: false, addEventListener() {} };
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const MAX_COLS = 3;

// popular categories, each with a real listing photo our hunts read (recorded hunts replay instantly)
const POPULAR = [
  { id: 'sp:co-2-2', img: '/web/assets/shelf/kamera-0.png', title: 'Sony A7 III', rec: 'sony-a7-iii-body' },
  { id: 'sp:el-4-8-5-2', img: '/web/assets/shelf/iphone-15-2.png', title: 'iPhone 15, 128 GB', rec: 'iphone-15-128gb-used' },
  { id: 'home-services.cleaning.home-cleaning', svg: 'home-services', title: 'Home cleaning, Helsinki', rec: 'home-cleaning-helsinki-60m2' },
  { id: 'sp:sg-4-4-3-2', img: '/web/assets/shelf/rennrad-0.png', title: 'City bike with basket', rec: 'city-bike-with-basket' },
  { id: 'sp:fr-22', img: '/web/assets/shelf/sohva-2.png', title: 'IKEA Söderhamn sofa', q: 'IKEA Söderhamn sofa' },
  { id: 'sp:sg-4-4-3-5-1', img: '/web/assets/shelf/bakfiets-2.png', title: 'Babboe cargo bike', q: 'electric cargo bike' },
  { id: 'trades.plumbing', svg: 'trades', title: 'A plumber near you', q: 'plumber' },
  { id: 'sp:vp-2-2-1', img: '/web/assets/shelf/fiat-500-0.png', title: 'Fiat 500, 2015', q: 'Fiat 500 used' },
];

let el = null, root = null;
const st = { path: [], q: '', hits: null, hi: 0, live: false, recs: new Set(), roots: null, pop: null };
const info = new Map();           // id -> item {id,label,count,n,kind,icon,leaf} in the current language
let renderId = 0, prevCols = [];

const remember = items => (items || []).forEach(it => info.set(it.id, it));
async function kids(id) {
  const r = await C.children(id);
  if (r) { remember(r.items); if (r.parent) info.set(r.parent.id, { ...info.get(r.parent.id), ...r.parent }); }
  return r ? r.items : [];
}
const label = id => (info.get(id) || {}).label || '';
const catOf = ids => ({ id: ids[ids.length - 1], ids: [...ids], path: ids.map(label) });
const canHunt = id => (info.get(id) || {}).huntable !== false;
// Owner, 14 Nov: "that white button with this long text looks way too goofy big". The button never repeats the
// category name (it is the title right above it): a short verb, the full name only for screen readers + tooltip.
const SEE_ALL = { en: 'See all', fi: 'Näytä kaikki', de: 'Alle ansehen', nl: 'Alles bekijken', sv: 'Visa alla' };
const seeAll = () => SEE_ALL[C.getLang()] || SEE_ALL.en;
// the action button for a node: hunt a concrete one, open the page of a broad one
const actHtml = (id, cls = 'ct-hunt') => {
  const hunt = canHunt(id);
  const full = hunt ? t('huntFor', label(id)) : t('seeAll', label(id));
  const attrs = hunt ? 'data-hunt-path="1"' : `data-page="${esc(id)}"`;
  return `<button type="button" class="${cls}${hunt ? '' : ' page'}" ${attrs} aria-label="${esc(full)}" title="${esc(full)}">${
    esc(hunt ? t('hunt') : seeAll())} <span aria-hidden="true">→</span></button>`;
};

// ---------- markup ----------
function shell() {
  return `<section class="ld-band" id="ld-browse" aria-labelledby="ld-browse-h">
    <div class="ld-in">
      <header class="ct-headrow">
        <div class="ld-head ld-rv">
          <p class="ld-kicker"><span class="ld-n">01</span><span class="ct-k"></span></p>
          <h2 class="ld-h" id="ld-browse-h"></h2>
          <p class="ld-sub ct-sub"></p>
        </div>
        <div class="ct-langs ld-rv" role="group"></div>
      </header>
      <div class="ct ld-rv">
        <div class="ct-top">
          <label class="ct-find"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>
            <span class="sr ct-find-l"></span>
            <input class="ct-q" type="search" autocomplete="off" spellcheck="false" maxlength="80" role="combobox"
              aria-autocomplete="list" aria-expanded="false" aria-controls="ct-results"></label>
          <nav class="ct-crumbs" aria-label="Category path"></nav>
        </div>
        <div class="ct-body">
          <div class="ct-roots" role="navigation"></div>
          <div class="ct-main" aria-live="polite"></div>
        </div>
      </div>
      <p class="ld-note" role="status" hidden>This demo server runs offline, so it replays the recorded live hunts (Sony A7 III, iPhone 15, home cleaning in Helsinki, a city bike). The other searches run live when a Context.dev key is set.</p>
    </div>
  </section>`;
}

function words() {
  const total = (st.roots && st.roots.total) || 0;
  root.querySelector('.ct-k').textContent = t('kicker');
  root.querySelector('#ld-browse-h').textContent = t('head');
  root.querySelector('.ct-sub').textContent = t('sub', total ? C.num(total) : 'Tens of thousands of');
  const q = root.querySelector('.ct-q');
  q.placeholder = t('find');
  root.querySelector('.ct-find-l').textContent = t('find');
  const lg = root.querySelector('.ct-langs');
  lg.setAttribute('aria-label', t('lang'));
  lg.innerHTML = C.LANGS.map(l => `<button type="button" data-lang="${l}" aria-pressed="${l === C.getLang()}" lang="${l}">${l.toUpperCase()}</button>`).join('');
}

function rowHtml(it, { level, sel, showIcon, parentKind, bare }) {
  const tag = bare ? '' : (showIcon || it.kind !== parentKind) ? C.kindTag(it.kind) : '';
  return `<li><button type="button" class="ct-row${sel ? ' sel' : ''}${it.leaf ? ' leaf' : ''}" data-id="${esc(it.id)}" data-level="${level}"
    ${it.leaf ? '' : `aria-expanded="${sel}"`} title="${esc(it.label)}${it.leaf ? '' : ` · ${C.num(it.count)} ${esc(t('cats'))}`}">
    ${showIcon ? C.icon(it.icon) : ''}<span class="ct-l">${esc(it.label)}</span>${tag}
    ${it.leaf ? `<span class="ct-go" aria-hidden="true">${it.huntable === false ? '›' : `${esc(t('hunt'))} →`}</span>` : bare ? '' : `<span class="ct-n">${C.num(it.count)}</span><span class="ct-chev" aria-hidden="true">›</span>`}
  </button></li>`;
}

function rootsHtml(items, bare = false) {
  const sel = st.path[0];
  const grp = (h, list) => `<div class="ct-grp"><p class="ct-gh">${esc(h)}</p><ul role="list">${
    list.map(it => rowHtml(it, { level: 0, sel: it.id === sel, showIcon: true, bare })).join('')}</ul></div>`;
  return grp(t('thingsH'), items.filter(i => i.kind !== 'service')) + grp(t('servicesH'), items.filter(i => i.kind === 'service'));
}

function crumbsHtml() {
  const ids = st.path;
  const parts = [`<button type="button" class="ct-cr" data-depth="0">${esc(t('all'))}</button>`];
  ids.forEach((id, k) => {
    const last = k === ids.length - 1;
    parts.push(last ? `<span class="ct-cr cur" aria-current="page">${esc(label(id))}</span>`
      : `<button type="button" class="ct-cr" data-depth="${k + 1}">${esc(label(id))}</button>`);
  });
  const sep = '<span class="ct-sep" aria-hidden="true">›</span>';
  const hunt = ids.length ? actHtml(ids[ids.length - 1], 'ct-hunt quiet') : '';
  return `<span class="ct-trail">${parts.join(sep)}</span>${hunt}`;
}

function colHtml(parentId, items, level, fresh) {
  const p = info.get(parentId) || {};
  const sel = st.path[level + 1];
  return `<div class="ct-col${fresh ? ' fresh' : ''}" data-parent="${esc(parentId)}">
    <p class="ct-ch"><span class="ct-chl">${esc(p.label || '')}</span><span class="ct-n">${C.num(p.count)}</span></p>
    <ul role="list">${items.map(it => rowHtml(it, { level: level + 1, sel: it.id === sel, parentKind: p.kind })).join('')}</ul>
  </div>`;
}

function leafHtml(id) {
  const it = info.get(id) || {};
  const where = st.path.slice(0, -1).map(label).join(' › ');
  return `<div class="ct-col ct-leaf fresh">
    <div class="ct-leafcard">${C.icon(it.icon || st.path[0], 'ct-ic big')}
      <h3>${esc(it.label)}</h3>${C.kindTag(it.kind)}
      <p class="ct-where">${esc(where)}</p>
      ${actHtml(id, 'ct-hunt solid')}
    </div></div>`;
}

function overviewHtml(groups, sub) {
  const r = st.path[0];
  return `<div class="ct-over fresh">${groups.map((g, k) => `<section class="ct-og">
      <button type="button" class="ct-oh" data-open-path="${esc(JSON.stringify([r, g.id]))}">${esc(g.label)} <span class="ct-n">${C.num(g.count)}</span></button>
      <ul role="list">${(sub[k] || []).slice(0, 4).map(x => `<li><button type="button" class="ct-ol" data-open-path="${esc(JSON.stringify([r, g.id, x.id]))}">${esc(x.label)}</button></li>`).join('')}</ul>
    </section>`).join('')}</div>`;
}
function infoHtml(id) {
  const it = info.get(id) || {};
  return `<div class="ct-col ct-leaf ct-info fresh"><div class="ct-leafcard">${C.icon(it.icon || st.path[0], 'ct-ic big')}
    <h3>${esc(it.label || '')}</h3>${C.kindTag(it.kind)}
    <p class="ct-where">${C.num(it.count)} ${esc(t('cats'))}</p>
    ${actHtml(id, 'ct-hunt solid')}
  </div></div>`;
}

const CLEAN_SVG = id => `<span class="ct-draw">${C.icon(id, 'ct-ic huge')}</span>`;
function popHtml(compact) {
  const items = POPULAR.map((p, i) => {
    const n = (st.pop && st.pop.get(p.id)) || null;
    const rec = p.rec && st.recs.has(p.rec);
    const ok = rec || st.live;
    const plate = p.img ? `<img src="${esc(p.img)}" alt="" loading="lazy" decoding="async">` : CLEAN_SVG(p.svg);
    const cat = n ? n.label : '';
    return `<li style="--d:${i * 40}ms"><button type="button" class="ct-pop" data-pop="${i}" data-ok="${ok ? 1 : 0}" aria-label="${esc(`${t('hunt')}: ${p.title}`)}">
      <span class="ct-plate">${plate}${rec ? `<span class="ct-rec">${esc(t('replay'))}</span>` : (ok ? '' : `<span class="ct-rec off">${esc(t('liveOnly'))}</span>`)}</span>
      <span class="ct-pt">${esc(p.title)}</span>
      <span class="ct-pc">${n ? C.icon(n.icon, 'ct-ic sm') : ''}<span class="ct-pcl">${esc(cat)}</span>${n && n.kind === 'service' ? C.kindTag(n.kind) : ''}</span>
    </button></li>`;
  }).join('');
  return `<div class="ct-popular${compact ? ' strip' : ''}">
    <p class="ct-ph">${esc(t('popular'))}${compact ? '' : `<span> · ${esc(t('pick'))}</span>`}</p>
    <ul role="list">${items}</ul></div>`;
}

function resultsHtml() {
  const hits = st.hits || [];
  const q = st.q.trim();
  const rows = hits.map((h, i) => {
    const trail = h.path.slice(0, -1).join(' › ');
    return `<li role="option" id="ct-opt-${i}" aria-selected="${i === st.hi}"><div class="ct-hit${i === st.hi ? ' hi' : ''}">
      <button type="button" class="ct-reveal" data-reveal="${i}">${C.icon(h.icon)}<span class="ct-hl"><b>${esc(h.label)}</b>${C.kindTag(h.kind)}<span class="ct-trailtxt">${esc(trail)}</span></span>
      ${h.leaf ? '' : `<span class="ct-n">${C.num(h.count)}</span>`}</button>
      ${h.huntable === false
        ? `<button type="button" class="ct-mini page" data-page="${esc(h.id)}" aria-label="${esc(t('seeAll', h.label))}">${esc(t('open'))} ›</button>`
        : `<button type="button" class="ct-mini" data-hunt-hit="${i}" aria-label="${esc(t('huntFor', h.label))}">${esc(t('hunt'))} →</button>`}
    </div></li>`;
  }).join('');
  const none = !hits.length ? `<p class="ct-none">${esc(t('none', q))}</p>` : '';
  return `<div class="ct-results">${none}<ul role="listbox" id="ct-results" aria-label="${esc(t('find'))}">${rows}</ul>
    <button type="button" class="ct-free" data-free="1">${esc(t('free', q))} <span aria-hidden="true">→</span></button></div>`;
}

// ---------- render ----------
async function render() {
  const my = ++renderId;
  const phone = PHONE.matches;
  if (!st.roots) { st.roots = await C.children(''); if (st.roots) remember(st.roots.items); words(); }
  const roots = (st.roots && st.roots.items) || [];
  // load every level on the path (cached per language)
  const levels = await Promise.all(st.path.map(id => kids(id)));
  if (my !== renderId) return;
  const ct = root.querySelector('.ct');
  ct.dataset.mode = phone ? 'list' : 'cols';
  const rootsEl = root.querySelector('.ct-roots'), main = root.querySelector('.ct-main');
  root.querySelector('.ct-crumbs').innerHTML = crumbsHtml();
  root.querySelector('.ct-crumbs').hidden = !st.path.length;
  const qIn = root.querySelector('.ct-q');
  qIn.setAttribute('aria-expanded', String(!!st.q.trim()));

  if (st.q.trim() && st.hits) {
    if (!phone) rootsEl.innerHTML = rootsHtml(roots, true);
    root.querySelector('.ct-crumbs').hidden = true;
    main.innerHTML = resultsHtml();
    qIn.setAttribute('aria-activedescendant', st.hits.length ? `ct-opt-${st.hi}` : '');
    return;
  }
  qIn.removeAttribute('aria-activedescendant');
  if (phone) {
    rootsEl.innerHTML = '';
    const last = st.path[st.path.length - 1];
    if (!last) { main.innerHTML = popHtml(true) + `<div class="ct-list">${rootsHtml(roots)}</div>`; return; }
    const items = levels[levels.length - 1] || [];
    const p = info.get(last) || {};
    const back = st.path.length > 1 ? label(st.path[st.path.length - 2]) : t('all');
    main.innerHTML = `<div class="ct-list">
      <button type="button" class="ct-back" data-depth="${st.path.length - 1}"><span aria-hidden="true">‹</span> ${esc(back)}</button>
      <h3 class="ct-lh">${C.icon(p.icon || st.path[0])}<span>${esc(p.label || '')}</span>${C.kindTag(p.kind)}</h3>
      ${p.leaf ? actHtml(last, 'ct-hunt solid') : `<p class="ct-lact">${actHtml(last, 'ct-hunt')}</p>`}
      ${p.leaf ? '' : `<ul role="list">${items.map(it => rowHtml(it, { level: st.path.length, sel: false, parentKind: p.kind })).join('')}</ul>`}
    </div>`;
    return;
  }
  rootsEl.innerHTML = rootsHtml(roots, true);
  if (!st.path.length) { main.innerHTML = popHtml(false); prevCols = []; return; }
  // columns: children of each node on the path (a leaf at the end gets a card instead), the last MAX_COLS shown
  const cols = [];
  st.path.forEach((id, k) => {
    const it = info.get(id) || {};
    if (it.leaf || (levels[k] && !levels[k].length)) cols.push({ leaf: id });
    else cols.push({ parent: id, items: levels[k], level: k });
  });
  const shown = cols.slice(-MAX_COLS);
  let extra = '';
  const lastId = st.path[st.path.length - 1];
  if (shown.length === 1 && !shown[0].leaf) {
    // one level open: the free space is a mega-menu overview (biggest groups with their first subcategories)
    const groups = shown[0].items.filter(i => !i.leaf).slice(0, 9);
    const sub = await Promise.all(groups.map(g => kids(g.id)));
    if (my !== renderId) return;
    extra = overviewHtml(groups, sub);
  } else if (shown.length === 2 && !shown[1].leaf) {
    extra = infoHtml(lastId);
  }
  main.innerHTML = `<div class="ct-cols" style="--cols:${MAX_COLS}">${shown.map(c => c.leaf
    ? leafHtml(c.leaf) : colHtml(c.parent, c.items, c.level, !prevCols.includes(c.parent))).join('')}${extra}</div>`;
  prevCols = shown.map(c => c.parent || c.leaf);
  // keep the selected row of every column in view (inside the column, never scrolling the page)
  main.querySelectorAll('.ct-col').forEach(col => {
    const s = col.querySelector('.ct-row.sel');
    const ul = col.querySelector('ul');
    if (s && ul) { const top = s.offsetTop - ul.offsetTop; if (top < ul.scrollTop || top > ul.scrollTop + ul.clientHeight - 40) ul.scrollTop = top - ul.clientHeight / 3; }
  });
  const rs = rootsEl.querySelector('.ct-row.sel');
  if (rs) { const top = rs.offsetTop; if (top > rootsEl.scrollTop + rootsEl.clientHeight - 30) rootsEl.scrollTop = top - rootsEl.clientHeight / 3; }
}

function focusRow(id) {
  const b = root.querySelector(`.ct-row[data-id="${CSS.escape(id)}"]`);
  if (b) b.focus({ preventScroll: true });
}

// ---------- actions ----------
function hunt(ids) {
  if (!ids || !ids.length) return;
  const id = ids[ids.length - 1];
  if (!canHunt(id)) { C.openCategory(id); return; }
  C.huntCategory(label(id), catOf(ids));
}
async function open(level, id, { focusChild = false } = {}) {
  st.path = [...st.path.slice(0, level), id];
  await render();
  if (focusChild) { const col = root.querySelector(`.ct-col[data-parent="${CSS.escape(id)}"] .ct-row`); if (col) col.focus({ preventScroll: true }); }
  else if (!PHONE.matches) focusRow(id);
}
export async function reveal(id) {
  if (!el) return;
  const r = await C.nodes([id]);
  const n = r && r.items && r.items[0];
  if (!n) return;
  // load each level so every label on the path is known
  for (let k = 0; k < n.path_ids.length; k++) info.set(n.path_ids[k], { ...(info.get(n.path_ids[k]) || {}), id: n.path_ids[k], label: n.path[k] });
  info.set(n.id, { ...info.get(n.id), ...n });
  st.path = [...n.path_ids];
  st.q = ''; st.hits = null;
  root.querySelector('.ct-q').value = '';
  await render();
}

let qTimer = 0, qSeq = 0;
function onQuery(v) {
  st.q = v;
  clearTimeout(qTimer);
  if (!v.trim()) { st.hits = null; render(); return; }
  qTimer = setTimeout(async () => {
    const seq = ++qSeq;
    const r = await C.search(v.trim(), 12);
    if (seq !== qSeq) return;
    st.hits = (r && r.items) || [];
    st.hi = 0;
    render();
  }, 80);
}

function onClick(e) {
  const lg = e.target.closest('[data-lang]');
  if (lg) { C.setLang(lg.dataset.lang); return; }
  const row = e.target.closest('.ct-row');
  if (row) {
    const id = row.dataset.id, level = Number(row.dataset.level);
    const it = info.get(id) || {};
    if (it.leaf) { hunt([...st.path.slice(0, level), id]); return; }
    open(level, id);
    return;
  }
  const cr = e.target.closest('[data-depth]');
  if (cr) { st.path = st.path.slice(0, Number(cr.dataset.depth)); render().then(() => { if (st.path.length) focusRow(st.path[st.path.length - 1]); }); return; }
  if (e.target.closest('[data-hunt-path]')) { hunt(st.path); return; }
  const op = e.target.closest('[data-open-path]');
  if (op) {
    const ids = JSON.parse(op.dataset.openPath);
    const last = info.get(ids[ids.length - 1]) || {};
    if (last.leaf) { hunt(ids); return; }
    st.path = ids; render().then(() => focusRow(ids[ids.length - 1]));
    return;
  }
  const pg = e.target.closest('[data-page]');
  if (pg) { C.openCategory(pg.dataset.page); return; }
  const rv = e.target.closest('[data-reveal]');
  if (rv) { const h = st.hits[Number(rv.dataset.reveal)]; if (h) reveal(h.id); return; }
  const hh = e.target.closest('[data-hunt-hit]');
  if (hh) { const h = st.hits[Number(hh.dataset.huntHit)]; if (h) C.huntCategory(h.label, { id: h.id, ids: h.path_ids, path: h.path }); return; }
  if (e.target.closest('[data-free]')) { core.emit('ask', { q: st.q.trim() }); return; }
  const pop = e.target.closest('.ct-pop');
  if (pop) {
    const p = POPULAR[Number(pop.dataset.pop)];
    const n = st.pop && st.pop.get(p.id);
    if (pop.dataset.ok !== '1') {
      const note = root.querySelector('.ld-note');
      note.hidden = false; note.classList.remove('flash'); void note.offsetWidth; note.classList.add('flash');
      note.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'nearest' });
      return;
    }
    core.emit('ask', { q: p.rec ? queryFor(p.rec) : p.q, cat: n ? { id: n.id, ids: n.path_ids, path: n.path } : null });
  }
}

function onKey(e) {
  if (e.target.classList.contains('ct-q')) {
    const hits = st.hits || [];
    if (e.key === 'ArrowDown' && hits.length) { e.preventDefault(); st.hi = (st.hi + 1) % hits.length; render(); }
    else if (e.key === 'ArrowUp' && hits.length) { e.preventDefault(); st.hi = (st.hi - 1 + hits.length) % hits.length; render(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (hits[st.hi]) reveal(hits[st.hi].id); else if (st.q.trim()) core.emit('ask', { q: st.q.trim() }); }
    else if (e.key === 'Escape' && st.q) { e.preventDefault(); e.target.value = ''; onQuery(''); }
    return;
  }
  const row = e.target.closest('.ct-row');
  if (!row) return;
  const list = [...row.closest('ul, .ct-roots').querySelectorAll('.ct-row')];
  const i = list.indexOf(row);
  const level = Number(row.dataset.level);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const n = list[(i + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length];
    if (n) n.focus({ preventScroll: false });
  } else if (e.key === 'ArrowRight' && !row.classList.contains('leaf')) {
    e.preventDefault(); open(level, row.dataset.id, { focusChild: true });
  } else if (e.key === 'ArrowLeft' && level > 0) {
    e.preventDefault(); focusRow(st.path[level - 1]);
  }
}

async function loadPopular() {
  const [r, recs, status] = await Promise.all([
    C.nodes(POPULAR.map(p => p.id)), recordings().catch(() => []),
    fetch('/status', { headers: { accept: 'application/json' } }).then(x => (x.ok ? x.json() : null)).catch(() => null),
  ]);
  st.pop = new Map(((r && r.items) || []).map(n => [n.id, n]));
  st.recs = new Set(recs || []);
  st.live = !!(status && status.live);
}

export function mountTree(host) {
  if (!host || el) return;
  host.insertAdjacentHTML('afterbegin', shell());
  el = host; root = host.querySelector('#ld-browse');
  words();
  root.addEventListener('click', onClick);
  root.addEventListener('keydown', onKey);
  root.querySelector('.ct-q').addEventListener('input', e => onQuery(e.target.value));
  PHONE.addEventListener && PHONE.addEventListener('change', () => render());
  core.on('lang', async () => {
    words();
    st.roots = null;
    await loadPopular();
    if (st.q.trim()) onQuery(st.q); else render();
  });
  core.on('browse', d => {
    if (!d || !d.id) return;
    reveal(d.id).then(() => root.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' }));
  });
  loadPopular().then(render);
  render();
  const want = new URLSearchParams(location.search).get('browse');
  if (want) reveal(want).then(() => root.scrollIntoView({ block: 'start' }));
}
