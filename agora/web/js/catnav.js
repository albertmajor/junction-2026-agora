// The category navbar under the header (owner, 14 Nov: "lets move this section into a navbar instead. everything in
// a navbar and maybe it can be highlighted what category we are in when we are searching").
// Desktop: a row of the main roots (short label + icon, as many as fit, by priority; the rest behind "More").
// Hovering or clicking a root opens a mega menu (tree.js in 'root' mode: that root's subcategories on the left,
// the selected one's children + an overview on the right; the category search and the language toggle on top).
// "More" opens every root (things | services) with the popular tiles. Esc / outside click closes.
// Phone (<= 640 px): one "Categories" button that opens the same tree as a full-screen drill-down list.
// Active state: the hunt's category (main.js 'crumbs' {ids, path, guess}, the stream's 'huntcategory') or the open
// category page ('catpage:shown') highlights its root; a hunt also shows a breadcrumb chip whose crumbs open
// that category's page. tree.js and the popular tiles load on the first open (pointer intent prefetches).
import * as core from './core.js';
import * as C from './cats.js';

const { esc, t } = C;
const mm = q => (typeof matchMedia === 'function' ? matchMedia(q) : { matches: false, addEventListener() {} });
const PHONE = mm('(max-width: 640px)');
const HOVER = mm('(hover: hover) and (pointer: fine)');

// the navbar's own short names (the menu and the chip use the full ones). Other languages: the label up to its
// first comma or "&" when long.
const SHORT = {
  en: {
    electronics: 'Electronics', appliances: 'Appliances', fashion: 'Fashion', 'home-garden': 'Home & Garden',
    furniture: 'Furniture', diy: 'DIY & Tools', 'health-beauty': 'Health & Beauty', 'baby-kids': 'Baby & Kids',
    'toys-games': 'Toys & Games', 'sports-outdoors': 'Sports', hobbies: 'Hobbies & Music', media: 'Books & Film',
    'food-drink': 'Food & Drink', pets: 'Pets', office: 'Office', vehicles: 'Vehicles', business: 'Business',
    software: 'Software', property: 'Property', 'home-services': 'Cleaning & Moving', trades: 'Trades',
    'auto-services': 'Car Care', 'beauty-wellness': 'Hair & Beauty', 'health-services': 'Health Care',
    education: 'Courses', 'events-leisure': 'Events', travel: 'Travel', transport: 'Transport',
    professional: 'Legal & Tax', 'digital-services': 'Freelancers', 'finance-insurance': 'Finance',
    utilities: 'Energy & Internet', 'personal-services': 'Care & Family',
  },
};
const W = {
  en: { more: 'More', all: 'All categories', cats: 'Categories', close: 'Close', nav: 'Categories', now: 'You are in', guess: 'best guess', services: 'Services' },
  fi: { more: 'Lisää', all: 'Kaikki luokat', cats: 'Luokat', close: 'Sulje', nav: 'Luokat', now: 'Olet luokassa', guess: 'paras arvaus', services: 'Palvelut' },
  de: { more: 'Mehr', all: 'Alle Kategorien', cats: 'Kategorien', close: 'Schließen', nav: 'Kategorien', now: 'Du bist in', guess: 'beste Vermutung', services: 'Dienste' },
  nl: { more: 'Meer', all: 'Alle categorieën', cats: 'Categorieën', close: 'Sluiten', nav: 'Categorieën', now: 'Je bent in', guess: 'beste gok', services: 'Diensten' },
  sv: { more: 'Mer', all: 'Alla kategorier', cats: 'Kategorier', close: 'Stäng', nav: 'Kategorier', now: 'Du är i', guess: 'bästa gissning', services: 'Tjänster' },
};
const w = k => (W[C.getLang()] || W.en)[k] || W.en[k];
// which roots earn a place in the row first (things and services mixed, so both kinds stay visible)
const PRIORITY = ['electronics', 'fashion', 'home-garden', 'furniture', 'appliances', 'sports-outdoors', 'vehicles',
  'home-services', 'trades', 'baby-kids', 'health-beauty', 'diy', 'auto-services', 'beauty-wellness', 'toys-games',
  'hobbies', 'travel', 'health-services', 'events-leisure', 'pets', 'food-drink', 'media', 'education', 'transport',
  'office', 'professional', 'digital-services', 'software', 'property', 'utilities', 'finance-insurance',
  'personal-services', 'business'];
const clean = s => String(s || '').replace(/­/g, '');
function short(it) {
  const m = (SHORT[C.getLang()] || {})[it.id];
  if (m) return m;
  let l = clean(it.label);
  if (l.length > 16) l = l.split(/,\s*/)[0];
  if (l.length > 16) l = l.split(/\s+(?:&|and|ja|und|en|och|og)\s+/)[0];
  return l;
}

let nav = null, row = null, list = null, more = null, catsBtn = null, chip = null, menu = null, treeHost = null;
let roots = [];                 // [{id,label,kind,icon}]
let tree = null, treeP = null;  // tree.js api (lazy)
const st = { open: false, mode: null, root: null, trigger: null, active: null, src: '', openedAt: 0, page: false };
let hoverT = 0, leaveT = 0, fitRaf = 0;

// ---------- the row ----------
function rowHtml() {
  const things = roots.filter(r => r.kind !== 'service'), services = roots.filter(r => r.kind === 'service');
  const li = r => `<li data-root="${esc(r.id)}" data-kind="${r.kind === 'service' ? 'service' : 'thing'}"><button type="button" class="cn-root" data-root="${esc(r.id)}"
    aria-expanded="false" aria-controls="catmenu" title="${esc(clean(r.label))}">${C.icon(r.icon || r.id, 'ct-ic cn-ic')}<span>${esc(short(r))}</span></button></li>`;
  return things.map(li).join('') + `<li class="cn-div" aria-hidden="true"><span>${esc(w('services'))}</span></li>` + services.map(li).join('');
}
function paintRow() {
  list.innerHTML = rowHtml();
  more.querySelector('span').textContent = w('more');
  catsBtn.querySelector('span').textContent = w('cats');
  nav.setAttribute('aria-label', w('nav'));
  menu.setAttribute('aria-label', w('all'));
  menu.querySelector('.cn-sheet-h b').textContent = w('cats');
  menu.querySelector('.cn-x').setAttribute('aria-label', w('close'));
  markActive();
  fit();
}

// as many roots as fit, by priority (the active root always), shown in tree order with a "Services" divider
function fit() {
  cancelAnimationFrame(fitRaf);
  fitRaf = requestAnimationFrame(() => {
    if (!list || PHONE.matches) return;
    const items = [...list.children];
    // the chip at its own width first (with every root shown it would be squeezed), then each root
    list.style.display = 'none';
    const chipW = chip.hidden ? 0 : chip.getBoundingClientRect().width + 16;
    list.style.display = '';
    items.forEach(li => { li.hidden = false; });
    const width = new Map(items.map(li => [li.dataset.root || 'div', li.getBoundingClientRect().width]));
    const gap = parseFloat(getComputedStyle(list).columnGap) || 0;
    const avail = row.clientWidth - more.getBoundingClientRect().width - chipW - 12;
    const act = st.active && st.active.ids && st.active.ids[0];
    const order = [act, ...PRIORITY].filter((id, i, a) => id && a.indexOf(id) === i && width.has(id));
    const show = new Set();
    let used = 0;
    for (const id of order) {
      const add = width.get(id) + gap;
      if (used + add > avail) break;
      show.add(id); used += add;
    }
    let kinds = new Set(roots.filter(r => show.has(r.id)).map(r => r.kind === 'service'));
    if (kinds.size === 2 && used + width.get('div') + gap > avail) {     // room for the divider: drop the last root
      const last = order.filter(id => show.has(id)).pop(); show.delete(last);
      kinds = new Set(roots.filter(r => show.has(r.id)).map(r => r.kind === 'service'));
    }
    items.forEach(li => { li.hidden = li.dataset.root ? !show.has(li.dataset.root) : kinds.size < 2; });
    more.dataset.all = show.size >= roots.length ? '1' : '';
  });
}

// ---------- active category (a hunt's or a category page's) ----------
function markActive() {
  const act = st.active && st.active.ids && st.active.ids[0];
  list.querySelectorAll('.cn-root').forEach(b => {
    const on = b.dataset.root === act;
    b.classList.toggle('on', on);
    if (on) b.setAttribute('aria-current', st.page ? 'page' : 'true'); else b.removeAttribute('aria-current');
  });
  catsBtn.classList.toggle('on', !!act);
}
function paintChip() {
  const a = st.active;
  if (!a || !a.ids || !a.ids.length || st.page) { chip.hidden = true; chip.innerHTML = ''; return; }
  const sep = '<span class="cb-sep" aria-hidden="true">›</span>';
  const n = a.ids.length;
  // root › … › parent › this (the middle crumbs live in the tooltip and in the category pages)
  const keep = n > 3 ? [0, n - 2, n - 1] : a.ids.map((_, k) => k);
  const crumb = k => {
    const r = k === 0 && roots.find(x => x.id === a.ids[0]);
    const txt = r ? short(r) : clean(a.path[k]);
    return `<a href="/?c=${encodeURIComponent(a.ids[k])}" data-open-cat="${esc(a.ids[k])}" title="${esc(clean(a.path[k]))}"${k === n - 1 ? ' aria-current="location"' : ''}>${esc(txt)}</a>`;
  };
  const parts = [];
  keep.forEach((k, i) => { if (i && k - keep[i - 1] > 1) parts.push('<span class="cb-gap" aria-hidden="true">…</span>'); parts.push(crumb(k)); });
  chip.title = a.path.map(clean).join(' › ');
  chip.innerHTML = `${C.icon(a.ids[0], 'ct-ic cb-ic')}<span class="sr">${esc(w('now'))}: </span><span class="cb-trail">` + parts.join(sep)
    + `</span>` + (a.guess ? `<span class="cb-guess" title="The category tree's best guess for what you typed">${esc(w('guess'))}</span>` : '');
  chip.hidden = false;
}
function setActive(a, { src = '', page = false } = {}) {
  st.active = a && a.ids && a.ids.length ? a : null;
  st.src = st.active ? src : '';
  st.page = !!(st.active && page);
  markActive(); paintChip(); fit();
}
async function activeFromId(id, extra = {}, src = '', page = false) {
  const r = await C.nodes([id]);
  const n = r && r.items && r.items[0];
  if (!n) return;
  setActive({ ids: n.path_ids, path: n.path, ...extra }, { src, page });
}

// ---------- the menu ----------
function loadTree() {
  if (!treeP) treeP = import('./tree.js').then(m => {
    tree = m.mountTree(treeHost, {
      onPath: ({ path, mode }) => {
        st.root = mode === 'root' ? path[0] || null : null;
        list.querySelectorAll('.cn-root').forEach(b => b.setAttribute('aria-expanded', String(st.open && b.dataset.root === st.root)));
        more.setAttribute('aria-expanded', String(st.open && mode === 'all'));
      },
      onEdge: () => { const b = st.trigger || list.querySelector('.cn-root:not([hidden])'); if (b) b.focus(); },
    });
    return tree;
  });
  return treeP;
}
function placeMenu() {
  if (PHONE.matches) { menu.style.removeProperty('--menu-top'); return; }
  const b = nav.getBoundingClientRect();
  menu.style.setProperty('--menu-top', `${Math.round(b.bottom)}px`);
}
async function open(where, { trigger = null, focus = false } = {}) {
  clearTimeout(leaveT);
  const tr = await loadTree();
  st.trigger = trigger;
  // the active category's own root opens on the active category
  const act = st.active && st.active.ids;
  if (where.root && act && act[0] === where.root && !where.fresh) where = { path: act };
  if (where.phone) where = act ? { path: act } : { all: true };
  if (!st.open) { st.open = true; st.openedAt = performance.now(); menu.hidden = false; nav.classList.add('open'); document.documentElement.classList.toggle('cn-lock', PHONE.matches); }
  placeMenu();
  await tr.show(where);
  if (focus) (PHONE.matches ? tr.focusSearch : tr.focusIn)();
}
function close({ refocus = false } = {}) {
  clearTimeout(hoverT); clearTimeout(leaveT);
  if (!st.open) return;
  st.open = false; menu.hidden = true; nav.classList.remove('open');
  document.documentElement.classList.remove('cn-lock');
  list.querySelectorAll('.cn-root').forEach(b => b.setAttribute('aria-expanded', 'false'));
  more.setAttribute('aria-expanded', 'false'); catsBtn.setAttribute('aria-expanded', 'false');
  if (refocus && st.trigger) st.trigger.focus();
}

// ---------- events ----------
function onClick(e) {
  const crumb = e.target.closest('[data-open-cat]');
  if (crumb) {
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault(); close(); C.openCategory(crumb.dataset.openCat); return;
  }
  const b = e.target.closest('.cn-root');
  if (b) {
    const same = st.open && st.root === b.dataset.root;
    if (same && performance.now() - st.openedAt > 450) { close(); return; }   // a hover-open is not toggled shut
    open({ root: b.dataset.root }, { trigger: b, focus: e.detail === 0 }); return;
  }
  if (e.target.closest('.cn-more')) {
    if (st.open && !st.root && performance.now() - st.openedAt > 450) { close(); return; }
    open({ all: true }, { trigger: more, focus: e.detail === 0 }); return;
  }
  if (e.target.closest('.cn-cats')) { catsBtn.setAttribute('aria-expanded', 'true'); open({ phone: true }, { trigger: catsBtn, focus: true }); return; }
  if (e.target.closest('.cn-x')) { close({ refocus: true }); }
}
function onKey(e) {
  if (e.key === 'Escape' && st.open) {
    if (e.defaultPrevented) return;            // the tree's search box clears itself first
    e.preventDefault(); close({ refocus: true }); return;
  }
  const b = e.target.closest('.cn-root, .cn-more');
  if (!b || !row.contains(b)) return;
  const all = [...row.querySelectorAll('.cn-root, .cn-more')].filter(x => !x.closest('[hidden]'));
  const i = all.indexOf(b);
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault();
    const n = all[(i + (e.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length];
    n.focus();
    if (st.open) open(n.classList.contains('cn-more') ? { all: true } : { root: n.dataset.root }, { trigger: n });
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    open(b.classList.contains('cn-more') ? { all: true } : { root: b.dataset.root }, { trigger: b, focus: true });
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault(); all[e.key === 'Home' ? 0 : all.length - 1].focus();
  }
}
function onEnter(e) {
  if (!HOVER.matches || PHONE.matches) return;
  clearTimeout(leaveT);
  const b = e.target.closest && e.target.closest('.cn-root, .cn-more');
  if (!b || !row.contains(b)) return;
  loadTree();                                   // intent: fetch the tree while the pointer settles
  clearTimeout(hoverT);
  const where = b.classList.contains('cn-more') ? { all: true } : { root: b.dataset.root };
  const same = st.open && (where.all ? !st.root : st.root === where.root);
  if (same) return;
  hoverT = setTimeout(() => open(where, { trigger: b }), st.open ? 90 : 160);
}
function onLeave() {
  if (!HOVER.matches || PHONE.matches) return;
  clearTimeout(hoverT);
  if (!st.open) return;
  // the menu stays while focus is in it (a keyboard user who moved the mouse away)
  leaveT = setTimeout(() => { if (!menu.contains(document.activeElement) || document.activeElement === document.body) close(); }, 320);
}

export function mountCatnav(host) {
  if (!host || nav) return;
  nav = host;
  nav.innerHTML = `<div class="cn-row">
      <button type="button" class="cn-cats" aria-expanded="false" aria-controls="catmenu"><svg class="cn-burger" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg><span></span></button>
      <ul class="cn-list" role="list"></ul>
      <button type="button" class="cn-more" aria-expanded="false" aria-controls="catmenu"><span></span><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg></button>
      <div id="crumbs" class="cn-chip" aria-label="Category" hidden></div>
    </div>
    <div id="catmenu" class="cn-menu" role="region" hidden>
      <div class="cn-sheet-h"><b></b><button type="button" class="cn-x"><span aria-hidden="true">×</span></button></div>
      <div class="cn-tree"></div>
    </div>`;
  row = nav.querySelector('.cn-row'); list = nav.querySelector('.cn-list'); more = nav.querySelector('.cn-more');
  catsBtn = nav.querySelector('.cn-cats'); chip = nav.querySelector('#crumbs'); menu = nav.querySelector('#catmenu');
  treeHost = nav.querySelector('.cn-tree');
  const old = document.querySelectorAll('#crumbs');          // index.html's old breadcrumb row, if still there
  old.forEach(x => { if (x !== chip) x.remove(); });

  nav.addEventListener('click', onClick);
  nav.addEventListener('keydown', onKey);
  nav.addEventListener('pointerover', onEnter);
  nav.addEventListener('pointerleave', onLeave);
  nav.addEventListener('pointerenter', () => clearTimeout(leaveT));
  nav.addEventListener('focusin', () => clearTimeout(leaveT));
  nav.addEventListener('focusout', e => {
    if (PHONE.matches || !st.open) return;
    if (e.relatedTarget && !nav.contains(e.relatedTarget)) close();
  });
  document.addEventListener('pointerdown', e => { if (st.open && !nav.contains(e.target)) close(); });
  addEventListener('resize', () => { fit(); if (st.open) placeMenu(); });
  addEventListener('scroll', () => { if (st.open && !PHONE.matches) placeMenu(); }, { passive: true });
  PHONE.addEventListener && PHONE.addEventListener('change', () => { close(); fit(); });
  if ('ResizeObserver' in window) {
    // the sticky header's height, for scroll-padding (anchors and scrollIntoView land under it, not behind it)
    const top = nav.closest('#top') || nav;
    new ResizeObserver(() => document.documentElement.style.setProperty('--top-h', `${Math.round(top.getBoundingClientRect().height)}px`)).observe(top);
    new ResizeObserver(() => fit()).observe(row);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);

  // the hunt's category: main.js's breadcrumb (the tree path it started from, or a sure guess), then the
  // stream's own category event (what the server actually hunts in) wins over a guess
  core.on('crumbs', d => {
    if (!d) { setActive(null); return; }
    if (d.guess && st.src === 'hunt') return;
    setActive({ ids: d.ids, path: d.path, guess: !!d.guess }, { src: d.guess ? 'guess' : 'cat' });
  });
  core.on('huntcategory', d => {
    if (!d || !d.id) return;
    const sure = d.source === 'tree' || (d.confidence ?? 1) >= 0.6;
    if (!sure) return;
    if (st.active && st.src === 'cat' && st.active.ids[st.active.ids.length - 1] === d.id) return;
    activeFromId(d.id, { guess: d.source !== 'tree' && (d.confidence ?? 1) < 0.9 }, 'hunt');
  });
  core.on('catpage:shown', d => { if (d && d.id) activeFromId(d.id, {}, 'page', true); });
  core.on('ask', () => close());
  core.on('category', () => close());
  core.on('catnav:open', d => open(d && d.id ? { id: d.id } : { all: true }, { trigger: PHONE.matches ? catsBtn : more }));
  core.on('lang', async () => {
    const r = await C.children('');
    roots = (r && r.items) || roots;
    paintRow();
    if (st.active) activeFromId(st.active.ids[st.active.ids.length - 1], { guess: st.active.guess }, st.src, st.page);
  });
  C.children('').then(r => { roots = (r && r.items) || []; paintRow(); });
}
