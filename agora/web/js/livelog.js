// Live log: "what Context.dev is reading right now" (docs/UI_ROUND_A.md section 2, owner item A2).
// Replaces the old #reading pill row. Listens to the core.js bus itself; nothing else calls into it.
//
// Integrator hooks (UI_ROUND_A.md section 7) - exact changes outside this file:
//   main.js
//     - delete the reading-row block: `brands` fetch, `reads`, `bare`, `readPage`, `readOffer`, `RM`/`flying`/
//       `flyNext`, `lineTarget`, `flyToLine`, `readSkip`, `readDone`, `readReset`, `drawReads`, and the calls
//       readReset() (on 'reset'), readPage(...) (on 'source'), readOffer(d) (on 'offer'), readSkip(...) (on 'skip'),
//       readDone() (on 'done'); drop `readingEl` from the $() list.
//     - in mountAll(), right after mountLine:
//         const ll = await load('livelog');
//         if (ll && ll.mountLivelog) { try { ll.mountLivelog($('reading'), line); } catch (e) { console.warn('[agora] mountLivelog failed', e); } }
//     - the tick clock: this panel has its own clock (reset -> done). Keep clockStart/clockStop for phones only
//       (e.g. `if (matchMedia('(max-width: 640px)').matches) clockStart()`), or drop them.
//   stream.js handle(): set the recorded time before emit, for lane, source, skip, budget: `d._t = ev.t_ms;`
//     and for offer: `it._t = ev.t_ms;` (tolerated when absent).
//   index.html: `<section id="reading" class="livelog" aria-label="Live log" hidden></section>` (an <ol> also works:
//     it is swapped for a <section> with the same id) and `<link rel="stylesheet" href="/web/css/livelog.css">`.
//   base.css: the old `.rd*` / `.rd-fly` rules are dead and can go; `#app[data-log="on"]` hides the desktop ticker text.
import * as core from './core.js';

const { S, on } = core;
const RM = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : { matches: true };
const PHONE = typeof matchMedia === 'function' ? matchMedia('(max-width: 640px)') : { matches: false };
const MAX_ROWS = 6, MAX_THUMBS = 4, DRIP_MS = 70, FLY_MS = 450, MAX_FLY = 4;

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const bare = d => String(d || '').toLowerCase().replace(/^www\./, '');
const domainOf = u => { try { return core.domainOf ? core.domainOf(u) : new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const plural = (n, w, ws = w + 's') => `${n} ${n === 1 ? w : ws}`;

// ---------- brand marks: assets/brands.json -> google s2 favicon -> Fraunces monogram ----------
let brands = {};
const brandsReady = (typeof fetch === 'function' ? fetch('/web/assets/brands.json') : Promise.reject())
  .then(r => r.ok ? r.json() : {})
  .then(j => { for (const b of Object.values(j || {})) if (b && b.domain && b.logo) brands[bare(b.domain)] = b.logo; })
  .catch(() => {});
function brandLogo(d) {
  for (let h = bare(d); h && h.includes('.'); h = h.slice(h.indexOf('.') + 1)) if (brands[h]) return brands[h];
  return null;
}
const favicon = d => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(d)}&sz=64`;
function fillMark(plate, d) {
  const img = plate.querySelector('img');
  if (!img) return;
  const chain = [brandLogo(d), favicon(d)].filter(Boolean);
  let i = 0;
  img.onload = () => { if (img.naturalWidth > 1) plate.classList.add('has-img'); else img.onerror(); };
  img.onerror = () => { i++; if (i < chain.length) img.src = chain[i]; else { img.remove(); plate.classList.remove('has-img'); } };
  img.src = chain[0];
}
function markEl(row) {
  const plate = document.createElement('span');
  plate.className = 'll-mark';
  plate.setAttribute('aria-hidden', 'true');
  if (row.lane) {
    plate.classList.add('ll-mark-q');
    plate.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12"><circle cx="6.8" cy="6.8" r="4.3"/><path d="M10 10l3.6 3.6"/></svg>';
    return plate;
  }
  plate.dataset.l = (row.domain[0] || '?').toUpperCase();
  plate.innerHTML = '<img alt="" width="20" height="20" decoding="async" referrerpolicy="no-referrer">';
  brandsReady.then(() => fillMark(plate, row.domain));
  return plate;
}
function cdMark() {
  return `<a class="cd-mark" href="https://context.dev" target="_blank" rel="noopener">Powered by <img src="${favicon('context.dev')}" alt="" width="14" height="14" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'cd-sq'}))"> <b>Context.dev</b></a>`;
}

// ---------- words ----------
const VIA = {
  contextdev_markdown_split: ['scrape', true], contextdev_json: ['extract', true], contextdev_product: ['product', true],
  search_highlight: ['search', true], jsonld: ['JSON-LD', false],
};
function methodOf(readVia) {
  if (!readVia) return null;
  if (VIA[readVia]) return VIA[readVia];
  return /^contextdev/i.test(readVia) ? ['read', true] : [String(readVia).replace(/_/g, ' '), false];
}
function shortReason(r) {
  r = String(r || '');
  if (/different model|other model|not the same model/i.test(r)) return 'different model';
  if (/accessor|case|cover|charger|strap/i.test(r) && !/not a shop/i.test(r)) return 'accessory';
  if (/rate limit|429/i.test(r)) return 'rate limit';
  if (/budget|out of time/i.test(r)) return 'out of time';
  if (/timed? ?out|timeout/i.test(r)) return 'too slow';
  if (/no (structured )?price|no offer|not a product/i.test(r)) return 'no price';
  if (/not a shop/i.test(r)) return 'not a shop';
  if (/same offer|duplicate|redirect/i.test(r)) return 'duplicate';
  if (/page gone|404|410/i.test(r)) return 'page gone';
  if (/does not match|not what you asked|mismatch/i.test(r)) return 'not a match';
  if (/already \d+ pages?/i.test(r)) return 'enough from this site';
  if (/could not read|failed/i.test(r)) return 'could not read';
  return r.split(/[;(:,.]/)[0].trim().split(/\s+/).slice(0, 3).join(' ').toLowerCase() || 'skipped';
}
const isCapSkip = r => /already \d+ pages?/i.test(String(r || ''));
function kindText(s) {
  const lane = s.lane ? String(s.lane) : '';
  const service = lane === 'service' || (S.need && S.need.kind === 'service');
  let k;
  if (service) k = s.list_page ? 'provider directory' : 'provider price list';
  else if (s.direct || (s.list_page && /used|second/i.test(lane))) k = 'marketplace search';
  else if (s.list_page) k = 'list page';
  else k = 'product page';
  return lane && !(service && lane === 'service') ? `${k} · ${lane}` : (service ? `${k} · service` : k);
}

// ---------- state ----------
let root = null, lineApi = null, app = null;
let rows = new Map();          // key -> row
let vis = [];                  // keys on screen in the live list, newest first
let skips = [];                // every skip: {domain, reason, short}
let pages = 0, replay = false, active = false, finished = false, stopped = false;
let t0 = 0, shownS = 0, endS = null, lastT = null, lastTWall = 0, clockTimer = 0, collapseTimer = 0;
let budget = null, flying = 0, flyNext = 0, logOpen = false;
let els = {};

function newRow(key, init) {
  const row = Object.assign({ key, lane: false, domain: '', what: '', via: null, state: 'reading', urls: new Set(),
    n: 0, thumbs: 0, more: 0, reason: '', pages: 0, laneName: '', dripAt: 0, el: null }, init);
  rows.set(key, row);
  return row;
}

// ---------- DOM ----------
function build(el) {
  if (el && /^(OL|UL)$/.test(el.tagName)) {
    const sec = document.createElement('section');
    sec.id = el.id || 'reading';
    sec.setAttribute('aria-label', 'Live log');
    sec.hidden = true;
    el.replaceWith(sec);
    el = sec;
  }
  el.classList.add('ll', 'livelog');
  el.innerHTML = `
    <div class="ll-panel">
      <div class="ll-head">
        <span class="ll-dot" aria-hidden="true"></span>
        <span class="ll-title"><span class="ll-t-long">Reading the web live</span><span class="ll-t-short">Reading live</span></span>
        <span class="ll-count"><b data-c="pages">0</b> <span data-w="pages">pages</span> · <b data-c="offers">0</b> <span data-w="offers">offers</span> · <b data-c="secs">0.0</b> s</span>
        <span class="ll-cd">${cdMark()}</span>
      </div>
      <ol class="ll-rows" aria-label="Pages being read"></ol>
    </div>
    <div class="ll-sum" hidden>
      <span class="ll-sum-text"></span>
      <button type="button" class="ll-toggle" aria-expanded="false">show log <span aria-hidden="true">▾</span></button>
      <span class="ll-cd">${cdMark()}</span>
    </div>
    <div class="ll-log" hidden></div>`;
  els = {
    panel: el.querySelector('.ll-panel'), head: el.querySelector('.ll-head'), title: el.querySelector('.ll-title'),
    list: el.querySelector('.ll-rows'), sum: el.querySelector('.ll-sum'), sumText: el.querySelector('.ll-sum-text'),
    toggle: el.querySelector('.ll-toggle'), log: el.querySelector('.ll-log'),
    c: { pages: el.querySelector('[data-c=pages]'), offers: el.querySelector('[data-c=offers]'), secs: el.querySelector('[data-c=secs]') },
    w: { pages: el.querySelector('[data-w=pages]'), offers: el.querySelector('[data-w=offers]') },
  };
  els.toggle.addEventListener('click', () => setLog(!logOpen));
  return el;
}

function rowEl(row, { full = false } = {}) {
  const li = document.createElement('li');
  li.className = 'll-row' + (row.lane ? ' ll-lane' : '');
  li.dataset.k = row.key;
  li.append(markEl(row));
  li.insertAdjacentHTML('beforeend',
    `<span class="ll-dom"></span><span class="ll-what"></span><span class="ll-via"><i aria-hidden="true"></i><span></span></span>` +
    `<span class="ll-yield"><span class="ll-bar" aria-hidden="true"></span><span class="ll-yt"></span><span class="ll-th" aria-hidden="true"></span><span class="ll-more"></span></span>`);
  if (!full) row.el = li;
  paint(row, li);
  return li;
}
function paint(row, li = row.el) {
  if (!li) return;
  li.dataset.s = row.state;
  li.querySelector('.ll-dom').textContent = row.lane ? 'web search' : row.domain;
  const what = li.querySelector('.ll-what');
  what.textContent = row.what; what.title = row.what;
  const via = li.querySelector('.ll-via');
  if (row.via) {
    via.hidden = false;
    via.dataset.cd = row.via[1] ? '1' : '0';
    via.lastChild.textContent = row.via[1] ? `Context.dev · ${row.via[0]}` : `free · ${row.via[0]}`;
    via.title = row.via[1] ? `Read through Context.dev (${row.via[0]})` : 'Read for free from the page\'s own structured data';
  } else via.hidden = true;
  const yt = li.querySelector('.ll-yt');
  if (row.state === 'reading') yt.textContent = row.lane ? 'searching' : 'reading';
  else if (row.state === 'done') yt.textContent = row.lane ? (row.n ? `${plural(row.n, 'page')} found` : 'searched') : `✓ ${plural(row.n, 'offer')}`;
  else if (row.state === 'skip') { yt.textContent = `skipped · ${row.reason}`; yt.title = row.reasonFull || ''; }
  else yt.textContent = 'no offer';
  li.querySelector('.ll-more').textContent = row.more > 0 ? `+${row.more}` : '';
}

// ---------- counters + clock ----------
function secsNow() {
  if (endS != null) return endS;
  if (!t0) return 0;
  // with recorded times (d._t) the clock follows the hunt's own timeline; otherwise wall time since reset
  const s = lastT != null ? (lastT + performance.now() - lastTWall) / 1000 : (performance.now() - t0) / 1000;
  return (shownS = Math.max(shownS, s));
}
function counts() {
  if (!els.c) return;
  const offers = S.offers ? S.offers.size : 0;
  els.c.pages.textContent = String(pages);
  els.w.pages.textContent = pages === 1 ? 'page' : 'pages';
  els.c.offers.textContent = String(offers);
  els.w.offers.textContent = offers === 1 ? 'offer' : 'offers';
  els.c.secs.textContent = secsNow().toFixed(1);
}
function clockStart() { clockStop(); t0 = performance.now(); endS = null; clockTimer = setInterval(counts, 100); counts(); }
function clockStop() { clearInterval(clockTimer); clockTimer = 0; }
function seeT(d) { if (d && typeof d._t === 'number' && isFinite(d._t) && (lastT == null || d._t >= lastT)) { lastT = d._t; lastTWall = performance.now(); } }

// ---------- visibility ----------
function show(on) {
  active = on;
  root.hidden = !on;
  if (app) { if (on) app.dataset.log = 'on'; else delete app.dataset.log; }
}

// ---------- the live list: newest on top, max 6, FLIP 200 ms ----------
function promote(row) {
  if (!active) return;
  const at = vis.indexOf(row.key);
  if (at === 0) return;
  const list = els.list;
  const before = new Map();
  for (const li of list.children) before.set(li, li.getBoundingClientRect().top);
  if (at > 0) vis.splice(at, 1);
  vis.unshift(row.key);
  if (!row.el) rowEl(row);
  list.prepend(row.el);
  while (vis.length > MAX_ROWS) {
    const gone = rows.get(vis.pop());
    if (gone && gone.el) { gone.el.remove(); gone.el = null; }
  }
  for (const [li, top] of before) {
    if (!li.isConnected || li === row.el) continue;
    const dy = top - li.getBoundingClientRect().top;
    if (dy && !RM.matches && li.animate) li.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 200, easing: 'cubic-bezier(.2,.7,.2,1)' });
  }
  if (row.el.animate) {
    row.el.animate(RM.matches ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }],
      { duration: 200, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'backwards' });
  }
}

// ---------- thumbnails drip in, then fly to the line ----------
function thumbSrc(it) {
  try { if (core.cutSrc) return core.cutSrc(it); } catch { /* fall through */ }
  const u = it && it.offer && it.offer.image;
  return u && (!core.isProductPhoto || core.isProductPhoto(u)) ? u : null;
}
function addThumb(row, it) {
  if (row.thumbs >= MAX_THUMBS) { row.more++; paint(row); return; }
  row.thumbs++;
  (row.items || (row.items = [])).push(it);
  const now = performance.now();
  row.dripAt = Math.max(now, row.dripAt + DRIP_MS);
  const wait = row.dripAt - now;
  setTimeout(() => {
    const li = row.el;
    if (!li || !li.isConnected) return;
    const th = thumbNode(it);
    li.querySelector('.ll-th').append(th);
    if (th.animate) th.animate(RM.matches ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'none' }], { duration: 160, easing: 'cubic-bezier(.2,.7,.2,1)' });
    setTimeout(() => fly(th, row.domain), 180);
  }, wait);
}
function thumbNode(it) {
  const src = thumbSrc(it);
  let th;
  if (src) {
    th = document.createElement('img');
    th.alt = ''; th.loading = 'eager'; th.decoding = 'async'; th.referrerPolicy = 'no-referrer';
    th.onerror = () => { const x = document.createElement('i'); x.className = 'll-ti ll-ti-x'; th.replaceWith(x); };
    th.src = src;
  } else th = document.createElement('i');
  th.className = 'll-ti' + (src ? '' : ' ll-ti-x');
  if (it && it.setAside) th.classList.add('aside');
  th.dataset.u = (it && it.url) || '';
  return th;
}
function lineTarget(d) {
  const lineEl = document.getElementById('line');
  if (!lineEl || lineEl.offsetParent === null) return null;
  const toPt = t => {
    if (!t) return null;
    if (t instanceof Element) t = t.getBoundingClientRect();
    if (typeof t.width === 'number' && typeof t.left === 'number') return { x: t.left + t.width / 2, y: t.top + t.height / 2 };
    if (isFinite(t.x) && isFinite(t.y)) return { x: t.x, y: t.y };
    return null;
  };
  let pt = null;
  try { if (lineApi && typeof lineApi.readingDot === 'function') pt = toPt(lineApi.readingDot(d)); } catch { pt = null; }
  if (!pt) {
    const lr = lineEl.getBoundingClientRect();
    const st = lineEl.querySelector('.ln-stage') || lineEl;
    let ay = null;
    try { ay = lineApi && typeof lineApi.axisY === 'function' ? lineApi.axisY() : null; } catch { ay = null; }
    const y = (ay != null && isFinite(ay)) ? st.getBoundingClientRect().top + (ay - st.offsetTop) : lr.top + Math.min(lr.height / 2, 200);
    pt = { x: lr.right - 24, y };
  }
  return (pt.y < 0 || pt.y > innerHeight || pt.x < 0 || pt.x > innerWidth) ? null : pt;
}
function fly(src, d) {
  if (RM.matches || flying >= MAX_FLY || !src.isConnected || root.hidden || finished) return;
  const now = performance.now();
  const delay = Math.max(0, flyNext - now);
  flyNext = now + delay + 90;
  flying++;
  setTimeout(() => {
    const to = lineTarget(d);
    const a = src.isConnected ? src.getBoundingClientRect() : null;
    if (!to || !a || !a.width) { flying--; return; }
    const ghost = src.cloneNode(true);
    ghost.classList.add('ll-fly');
    ghost.setAttribute('aria-hidden', 'true');
    Object.assign(ghost.style, { left: a.left + 'px', top: a.top + 'px', width: a.width + 'px', height: a.height + 'px' });
    document.body.appendChild(ghost);
    const dx = to.x - (a.left + a.width / 2), dy = to.y - (a.top + a.height / 2);
    const anim = ghost.animate([
      { transform: 'translate(0,0) scale(1)', opacity: 1 },
      { transform: `translate(${dx * 0.55}px, ${dy * 0.35}px) scale(1.15)`, opacity: 1, offset: 0.55 },
      { transform: `translate(${dx}px, ${dy}px) scale(.6)`, opacity: 0 },
    ], { duration: FLY_MS, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'forwards' });
    const end = () => { ghost.remove(); flying--; };
    anim.finished.then(end, end);
  }, delay);
}

// ---------- events ----------
function laneRow(name) { return rows.get('lane:' + name) || null; }
function pageRow(d) {
  d = bare(d);
  if (!d) return null;
  let row = rows.get(d);
  if (!row) { row = newRow(d, { domain: d }); promote(row); }
  return row;
}
function onReset(d) {
  clearTimeout(collapseTimer); clockStop();
  rows = new Map(); vis = []; skips = []; pages = 0; budget = null; finished = false; stopped = false;
  t0 = 0; shownS = 0; endS = null; lastT = null; logOpen = false;
  replay = !!(d && d.replay);
  els.list.innerHTML = ''; els.log.innerHTML = ''; els.log.hidden = true;
  els.sum.hidden = true; els.panel.hidden = false;
  els.toggle.setAttribute('aria-expanded', 'false');
  root.dataset.state = 'live';
  root.dataset.replay = replay ? '1' : '0';
  els.title.querySelector('.ll-t-long').textContent = replay ? 'Replaying a recorded live hunt' : 'Reading the web live';
  els.title.querySelector('.ll-t-short').textContent = replay ? 'Recorded hunt' : 'Reading live';
  const on = !!(d && d.q && !d.empty);
  show(on);
  if (on) clockStart();
  counts();
}
function onLane(l) {
  seeT(l);
  if (!active) return;
  const q = (l && l.queries || [])[0];
  if (!q || finished) return;
  const name = String(l.lane || 'search');
  const key = 'lane:' + name;
  let row = rows.get(key);
  if (!row) row = newRow(key, { lane: true, laneName: name, via: ['search', true] });
  row.what = `“${q}” · ${name}`;
  row.state = row.n ? 'done' : 'reading';
  if (row.el) paint(row); else promote(row);
}
function onSource(s) {
  seeT(s);
  if (!s) return;
  pages++;
  const row = pageRow(s.domain || domainOf(s.url));
  if (row) {
    row.pages++;
    if (!row.what || !row.n) row.what = kindText(s);
    if (!row.via && s.direct) row.via = s.paid === false ? ['JSON-LD', false] : ['scrape', true];
    if (row.state === 'skip' || row.state === 'empty') row.state = finished ? (row.n ? 'done' : 'empty') : 'reading';
    paint(row);
  }
  const lr = s.lane && laneRow(s.lane);
  if (lr) { lr.n++; lr.state = 'done'; paint(lr); }
  counts();
}
function onOffer(it) {
  seeT(it);
  if (!it || !it.url) return;
  const o = it.offer || {};
  let d = bare(domainOf(it.url));
  if (!rows.has(d) && o.source && rows.has(bare(o.source))) d = bare(o.source);
  if (!d) d = bare(o.source);
  const row = pageRow(d);
  if (!row) return;
  const m = methodOf(o.read_via);
  if (m) row.via = m;
  if (!row.what) row.what = o.condition ? `product page · ${o.condition}` : 'product page';
  if (!row.urls.has(it.url)) {
    row.urls.add(it.url);
    row.n = row.urls.size;
    row.state = 'done';
    if (!row.el && !finished) promote(row);
    paint(row);
    addThumb(row, it);
  } else paint(row);
  counts();
  if (finished) summary();
}
function onRemoved(it) {
  for (const row of rows.values()) {
    if (row.urls.delete(it && it.url)) { row.n = row.urls.size; if (!row.n) row.state = finished ? 'empty' : 'reading'; paint(row); }
  }
  const th = it && [...root.querySelectorAll('.ll-ti')].find(x => x.dataset.u === it.url);
  if (th) th.classList.add('aside');
  counts();
  if (finished) summary();
}
function onSkip(sk) {
  seeT(sk);
  if (!sk) return;
  const d = bare(sk.domain || domainOf(sk.url));
  const short = shortReason(sk.reason);
  skips.push({ domain: d, reason: String(sk.reason || ''), short, url: sk.url || '' });
  if (!d || sk.rejected) { counts(); return; }
  let row = rows.get(d);
  if (row && row.n) return;                // the site already gave offers: the skip lives in the full log only
  if (!row && isCapSkip(sk.reason)) return;  // "already 2 pages from X": not a read, log only
  if (!row) row = pageRow(d);
  row.state = 'skip'; row.reason = short; row.reasonFull = String(sk.reason || '');
  if (!row.what) row.what = sk.lane ? `page · ${sk.lane}` : 'page';
  paint(row);
}
function onTruecost(it) {
  if (!it || !it.url || !root) return;
  const th = [...root.querySelectorAll('.ll-ti')].find(x => x.dataset.u === it.url);
  if (th) th.classList.toggle('aside', !!it.setAside);
}
function onBudget(b) { seeT(b); budget = b || null; if (finished) summary(); }

function finish(d, { cut = false } = {}) {
  if (!active || finished) return;
  finished = true; stopped = cut;
  clockStop();
  const ms = d && typeof d.ms === 'number' && isFinite(d.ms) ? d.ms : (lastT != null ? lastT : null);
  endS = ms != null ? ms / 1000 : secsNow();
  for (const row of rows.values()) {
    if (row.state === 'reading') row.state = row.lane ? 'done' : (row.n ? 'done' : 'empty');
    paint(row);
  }
  counts();
  summary();
  clearTimeout(collapseTimer);
  collapseTimer = setTimeout(collapse, RM.matches ? 300 : 900);
}
function collapse() {
  if (!active || root.dataset.state === 'done') return;
  const h0 = root.offsetHeight;
  root.dataset.state = 'done';
  els.panel.hidden = true;
  els.sum.hidden = false;
  const h1 = root.offsetHeight;
  if (!root.animate) return;
  if (!RM.matches && h0 > h1) {
    root.animate([{ height: h0 + 'px', overflow: 'hidden' }, { height: h1 + 'px', overflow: 'hidden' }], { duration: 320, easing: 'cubic-bezier(.2,.7,.2,1)' });
  }
  els.sum.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'backwards' });
}
function viaCounts() {
  let ctx = 0, free = 0;
  for (const it of (S.offers ? S.offers.values() : [])) {
    const m = methodOf(it.offer && it.offer.read_via);
    if (!m) continue;
    if (m[1]) ctx++; else free++;
  }
  if (!ctx && !free && budget) {
    free = Array.isArray(budget.free_reads) ? budget.free_reads.length : (+budget.free_reads || 0);
    ctx = +budget.requests || 0;
  }
  return { ctx, free };
}
function summary() {
  const sites = [...rows.values()].filter(r => !r.lane && r.pages).length;
  const offers = S.offers ? S.offers.size : 0;
  const { ctx, free } = viaCounts();
  const secs = endS != null ? endS.toFixed(1) : secsNow().toFixed(1);
  const lead = stopped ? 'Stopped after reading' : '✓ Read';
  const via = (ctx || free) ? `<span class="ll-s-long">: <b class="ll-cd-n">${ctx} via Context.dev</b>, ${free} free from JSON-LD</span>` : '';
  els.sumText.innerHTML =
    (replay ? '<span class="ll-s-rec">Recorded live hunt · </span>' : '') +
    `<span class="ll-ok">${lead}</span> <b>${plural(pages, 'page')}</b><span class="ll-s-long"> on ${plural(sites, 'site')}</span> in <b>${secs} s</b> · <b>${plural(offers, 'offer')}</b>${via}`;
  root.dataset.cut = stopped ? '1' : '0';
  if (logOpen) drawLog();
}

// ---------- the full log (after done): offers first, then searches, then reads with no offer, then skips by reason ----------
function setLog(open) {
  logOpen = !!open;
  els.toggle.setAttribute('aria-expanded', String(logOpen));
  els.toggle.firstChild.textContent = logOpen ? 'hide log ' : 'show log ';
  els.toggle.lastElementChild.textContent = logOpen ? '▴' : '▾';
  if (logOpen) drawLog();
  els.log.hidden = !logOpen;
  if (logOpen && els.log.animate) els.log.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 });
}
function drawLog() {
  const all = [...rows.values()];
  const group = (title, list, mk) => {
    if (!list.length) return null;
    const g = document.createElement('section');
    g.className = 'll-group';
    g.innerHTML = `<h3>${esc(title)} <span>${list.length}</span></h3>`;
    const ol = document.createElement('ol');
    ol.className = 'll-rows';
    for (const x of list) ol.append(mk(x));
    g.append(ol);
    return g;
  };
  const full = row => {
    const li = rowEl(row, { full: true });
    const box = li.querySelector('.ll-th');
    for (const it of (row.items || [])) box.append(thumbNode(it));
    return li;
  };
  const parts = [
    group('Gave offers', all.filter(r => !r.lane && r.n), full),
    group('Searches', all.filter(r => r.lane), full),
    group('Read, no offer', all.filter(r => !r.lane && !r.n && r.state !== 'skip'), full),
  ];
  const by = new Map();
  for (const s of skips) { if (!by.has(s.short)) by.set(s.short, []); by.get(s.short).push(s); }
  for (const [reason, list] of [...by.entries()].sort((a, b) => b[1].length - a[1].length)) {
    parts.push(group(`Skipped · ${reason}`, list, s => {
      const row = { key: 'skip', lane: false, domain: s.domain || '?', what: s.reason, via: null, state: 'skip', reason, reasonFull: s.reason, n: 0, more: 0 };
      return rowEl(row, { full: true });
    }));
  }
  els.log.replaceChildren(...parts.filter(Boolean));
}

// ---------- mount ----------
export function mountLivelog(el, line) {
  if (!el) return null;
  lineApi = line || null;
  app = document.getElementById('app');
  root = build(el);
  root.hidden = true;
  on('reset', onReset);
  on('need', () => { if (active) counts(); });
  on('lane', onLane);
  on('source', d => { if (active) onSource(d); });
  on('offer', d => { if (active) onOffer(d); });
  on('offer-removed', d => { if (active) onRemoved(d); });
  on('skip', d => { if (active) onSkip(d); });
  on('truecost', onTruecost);
  on('budget', onBudget);
  on('done', d => finish(d, { cut: !!(d && d.cut) }));
  on('error', e => {
    if (!e) return;
    if (e.kind === '404') { clockStop(); show(false); return; }
    if (e.kind === 'net' || e.kind === '429') finish(null, { cut: true });
  });
  PHONE.addEventListener && PHONE.addEventListener('change', () => counts());
  return root;
}

/** Test hook: a plain snapshot of what the panel shows. */
export const _test = {
  state() {
    return {
      visible: !!(root && !root.hidden), replay, finished, stopped, state: root && root.dataset.state,
      pages, offers: S.offers ? S.offers.size : 0, secs: +secsNow().toFixed(1),
      onScreen: vis.slice(),
      rows: [...rows.values()].map(r => ({ key: r.key, lane: r.lane, domain: r.domain, what: r.what,
        via: r.via ? (r.via[1] ? 'Context.dev · ' : 'free · ') + r.via[0] : null, state: r.state, n: r.n, reason: r.reason })),
      skips: skips.map(s => s.short),
      summary: els.sumText ? els.sumText.textContent : '',
      log: app ? app.dataset.log || null : null,
    };
  },
  shortReason, methodOf, kindText,
};
