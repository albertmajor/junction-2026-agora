// The yellow "your price" tag (B4). Drag it along the line to set the price you would pay.
// Idea from our teammate rpaszekdev's "Your price" line (idea.md). See DESIGN.md section 3.4.
//
// While dragging, the line shows tag prices ("showing price at the till"): watches are on the tag
// price because that is what a shop changes. Release -> a watch sentence, a checkbox,
// POST /watches, then the guard clock.
//
// Desktop: the tag hangs under THE LINE at its x. Phone (the line is vertical): the tag is a dashed
// rule laid across the list at the y of your price, with the yellow chip on the rail. Rows above
// the rule are cheaper and stay lit; rows below dim (line.highlightBelow).
//
// Buy follows the pick: the "Watch at €X" button in the sheet sends {eur, from:'sheet', url}; the
// watch remembers that offer (S.watch.url, S.watch.cond) and "see it buy" passes it to the finale.
import { S, on, emit, eur, isSetAside, domainOf, condLetter } from './core.js';

const RM = matchMedia('(prefers-reduced-motion: reduce)');
const NARROW = matchMedia('(max-width: 640px)');
const DAY = 86400;
const COND_WORD = { n: 'new', u: 'used', r: 'refurbished', rent: 'rental', svc: 'service' };

let el, line, ui = {}, st = {
  v: null,            // the tag value in EUR (tag price); null = idle
  active: false,      // dragging / keyboard-adjusting
  shown: false,
  armedAt: 0, checkedAt: 0,
  buy: false,
  posted: null,       // {v, buy, url} of the last POST
  silent: false,      // finale: move the tag but never POST
  prevMode: null,
  pick: null,         // {url, from}: the offer the watch follows (sheet pick), else the leader
};
let clock = 0, keyTimer = 0, layoutRaf = 0, ownExtras = new Map(), kbd = false, busy = false;   // busy: the finale is playing

// ---------- helpers ----------
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function offersOnLine() {
  const out = [];
  for (const it of S.offers.values()) {
    const p = it && it.offer && it.offer.price_eur;
    if (typeof p === 'number' && isFinite(p) && p > 0 && !isSetAside(it)) out.push(it);
  }
  return out.sort((a, b) => a.offer.price_eur - b.offer.price_eur);
}

function leaderTag() {
  const v = S.verdict && S.verdict.verdict;
  const u = (line && line.winner) || S.leader || (v && (v.best_offer_url || v.best_true_cost_url));
  const it = u && S.offers.get(u);
  const p = it && it.offer && it.offer.price_eur;
  return typeof p === 'number' && isFinite(p) ? p : null;
}

function shopName(it) {
  const d = (it.offer && it.offer.source) || domainOf(it.url) || 'a shop';
  return String(d).replace(/^www\./, '').replace(/\.(com|net|org|eu)$/, '');
}

function thingName() {
  const raw = (S.need && (S.need.thing || S.need.raw)) || S.q || 'this';
  return String(raw).trim().split(/\s+/).map((w, i) => {
    if (/^iphone$/i.test(w)) return 'iPhone';
    if (/^(i{1,3}|iv|vi{0,3}|ix|x)$/i.test(w) || /\d/.test(w)) return w.toUpperCase();
    return i === 0 ? w[0].toUpperCase() + w.slice(1) : w;
  }).join(' ');
}

function snap(v) {
  const a = Math.abs(v);
  const step = a < 100 ? 1 : a < 1000 ? 5 : a < 10000 ? 10 : 50;
  return Math.max(step, Math.round(v / step) * step);
}

// The offer the watch follows: the sheet's pick, else the leader.
function pickUrl() { return (st.pick && st.pick.url) || S.leader || null; }
function pickInfo() {
  const url = pickUrl();
  const it = url && S.offers.get(url);
  const cond = it && it.offer ? condLetter(it.offer.condition) : '';
  return { url, it, cond };
}

// ---------- geometry ----------
function lineEl() { return document.getElementById('line'); }

// Is THE LINE drawn as a vertical list (phones)? Asks the line first, then its class.
function isVert() {
  if (!line) return false;
  if (typeof line.isVertical === 'function') { try { return !!line.isVertical(); } catch (e) { /* fall through */ } }
  const le = lineEl();
  return !!(le && le.classList.contains('ln-v'));
}
// The vertical list's box. line.listRect() when there is one, else the stage.
function listRect() {
  if (typeof line.listRect === 'function') { try { const r = line.listRect(); if (r && r.height > 0) return r; } catch (e) { /* fall through */ } }
  const le = lineEl();
  const stage = le && (le.querySelector('.ln-stage') || le);
  return stage ? stage.getBoundingClientRect() : null;
}
// y (px from the list's top) of a tag price, and back. line.yFor/eurForY, else xFor/eurFor (which
// answer in y while the line is vertical).
function vY(v) {
  const f = typeof line.yFor === 'function' ? line.yFor : line.xFor;
  const y = f.call(line, v);
  return typeof y === 'number' && isFinite(y) ? y : null;
}
function vEur(y) {
  const f = typeof line.eurForY === 'function' ? line.eurForY : line.eurFor;
  const v = f.call(line, y);
  return typeof v === 'number' && isFinite(v) ? v : null;
}

// Geometry: THE LINE's scale (desktop: x; phone: y down the list). A small ruler of our own only
// when there is no line at all. Every g.pos/g.eur works in px from the rail's own origin.
function geom() {
  const rail = ui.rail.getBoundingClientRect();
  if (isVert()) {
    const lr = listRect();
    if (lr && (typeof line.yFor === 'function' || typeof line.xFor === 'function')) {
      const off = lr.top - rail.top;            // the list's top, in rail px (negative: the list is above)
      const lo = off + 4, hi = off + Math.max(8, lr.height - 4);
      return {
        vert: true, own: false, width: rail.width, needle: 0, zoneH: 0, left: Math.max(0, lr.left - rail.left),
        listTop: off, listH: lr.height, lo, hi,
        // pos: where the tag is drawn (kept on the list); raw: the unclamped y, so a drag past either
        // end keeps going cheaper or dearer instead of snapping back to the end row's price
        pos: e => {
          // drawn at the seam between rows (never through one); the raw y drives the drag
          let y = typeof line.gapY === 'function' ? line.gapY(e) : null;
          if (y == null) y = vY(e);
          return y == null ? null : Math.min(hi, Math.max(lo, off + y));
        },
        raw: e => { const y = vY(e); return y == null ? null : off + y; },
        eur: y => vEur(y - off),
        get x() { return this.pos; },
      };
    }
  }
  const le = lineEl();
  const stageEl = le && (le.querySelector('.ln-stage') || le);
  const sr = stageEl ? stageEl.getBoundingClientRect() : rail;
  const usable = line && typeof line.xFor === 'function' && typeof line.eurFor === 'function'
    && !NARROW.matches && sr.width > 200 && isFinite(line.xFor(100));
  if (usable) {
    const off = sr.left - rail.left;
    // the axis, in page px: line.axisY() is measured like stage.offsetTop
    let axis = sr.top + sr.height - 84;
    if (typeof line.axisY === 'function') {
      const ay = line.axisY();
      if (ay != null && isFinite(ay)) axis = sr.top + (ay - stageEl.offsetTop);
    }
    const x = e => off + line.xFor(e);
    return {
      vert: false, own: false, width: rail.width, needle: Math.max(0, rail.top - axis), zoneH: Math.max(0, axis - sr.top - 8),
      left: Math.max(0, off), pos: x, x, eur: px => line.eurFor(px - off),
    };
  }
  const prices = offersOnLine().map(it => it.offer.price_eur);
  let lo = prices.length ? Math.min(...prices) : 0, hi = prices.length ? Math.max(...prices) : 1000;
  if (st.v != null) { lo = Math.min(lo, st.v); hi = Math.max(hi, st.v); }
  const pad = Math.max((hi - lo) * 0.08, hi * 0.02, 1);
  lo = Math.max(0, lo - pad); hi += pad;
  const L = 18, R = rail.width - 18, w = Math.max(1, R - L);
  const x = e => L + (e - lo) / (hi - lo) * w;
  return {
    vert: false, own: true, width: rail.width, needle: 0, zoneH: 0, left: 18, lo, hi,
    pos: x, x, eur: px => lo + (px - L) / w * (hi - lo),
  };
}

// ---------- render ----------
function build() {
  el.innerHTML = `
    <div class="tg-rail">
      <div class="tg-track" aria-hidden="true"></div>
      <div class="tg-zone" aria-hidden="true"></div>
      <span class="tg-zlab" aria-hidden="true"></span>
      <div class="tg-needle" aria-hidden="true"></div>
      <div class="tg-vrule" aria-hidden="true"><span class="tg-vlab"></span></div>
      <div class="tg-ghosts" aria-hidden="true"></div>
      <button type="button" class="tg-tag" role="slider" aria-label="Your price" aria-orientation="horizontal"
              aria-valuemin="0" aria-valuemax="100000" aria-valuenow="0" aria-valuetext="not set: drag to set your price, we watch and can buy it for you">
        <span class="tg-hole" aria-hidden="true"></span>
        <span class="tg-val">your price</span>
        <span class="tg-hint" aria-hidden="true">drag to set your price · we watch, and can buy</span>
      </button>
      <span class="tg-park" aria-hidden="true"></span>
    </div>
    <div class="tg-row"><span class="tg-pill">showing tag prices</span><p class="tg-cap" aria-live="polite"></p></div>
    <div class="tg-watch" hidden>
      <p class="tg-sentence"></p>
      <div class="tg-step" role="group" aria-label="Change your price">
        <button type="button" data-d="-10" aria-label="Your price minus 10 euros">− €10</button>
        <button type="button" data-d="10" aria-label="Your price plus 10 euros">+ €10</button>
      </div>
      <div class="tg-ctl">
        <label class="tg-buy"><input type="checkbox"><span class="tg-box" aria-hidden="true"></span><span class="tg-buy-t"></span></label>
        <p class="tg-guard" hidden><span class="tg-dot" aria-hidden="true"></span><span class="tg-guard-t"></span>
          <a href="#finale" class="tg-see">see it buy →</a></p>
      </div>
    </div>`;
  el.insertAdjacentHTML('afterbegin', '<p class="tg-title">Your price</p>');
  ui = {
    rail: el.querySelector('.tg-rail'), track: el.querySelector('.tg-track'), zone: el.querySelector('.tg-zone'),
    needle: el.querySelector('.tg-needle'), ghosts: el.querySelector('.tg-ghosts'), tag: el.querySelector('.tg-tag'),
    vrule: el.querySelector('.tg-vrule'), vlab: el.querySelector('.tg-vlab'), park: el.querySelector('.tg-park'),
    val: el.querySelector('.tg-val'), cap: el.querySelector('.tg-cap'), watch: el.querySelector('.tg-watch'),
    sentence: el.querySelector('.tg-sentence'), box: el.querySelector('.tg-buy input'),
    buyT: el.querySelector('.tg-buy-t'), guard: el.querySelector('.tg-guard'), guardT: el.querySelector('.tg-guard-t'),
    see: el.querySelector('.tg-see'),
  };
}

function layout() {
  cancelAnimationFrame(layoutRaf);
  layoutRaf = requestAnimationFrame(place);
}

function place() {
  if (!st.shown) return;
  const g = geom();
  el.classList.toggle('is-own', g.own);
  el.classList.toggle('is-vert', g.vert);
  ui.tag.setAttribute('aria-orientation', g.vert ? 'vertical' : 'horizontal');
  const parked = isParked(g);
  el.classList.toggle('is-parked', parked);
  if (g.vert) {
    // the chip sits on the rail at the list's left edge; the dashed rule runs across the rows
    el.style.setProperty('--vl', g.left.toFixed(1) + 'px');
    const y = parked ? null : g.pos(st.v);
    if (y != null) el.style.setProperty('--ty', y.toFixed(1) + 'px');
    el.classList.toggle('is-off', !parked && y == null);
    ui.park.textContent = st.v == null ? 'drag up to set your price' : 'drag to put it back on the list';
    for (const [, ex] of ownExtras) ex.place(g);
    return;
  }
  ui.needle.style.height = g.needle + 'px';
  el.style.setProperty('--needle', g.needle + 'px');
  el.style.setProperty('--zoneh', (g.zoneH || 0) + 'px');
  // keep the whole tag body on screen, even for a price left of the scale
  const half = Math.max(30, (ui.tag.offsetWidth || 92) / 2);
  const x = parked ? dockX(g) : Math.min(g.width - half, Math.max(half, g.x(st.v)));
  el.style.setProperty('--tx', x.toFixed(1) + 'px');
  // hatched zone from the left end of the scale to the tag, only when nothing is left of it
  const zl = Math.max(0, Math.min(x, g.left));
  el.style.setProperty('--zl', zl.toFixed(1) + 'px');
  el.classList.toggle('is-left', x < g.width * 0.6);
  if (g.own) drawTrack(g);
  for (const [, ex] of ownExtras) ex.place(g);
}

// The tag is a TAG price. In the true-cost view it has no place on the axis: it waits at the dock
// (desktop: right end under the line; phone: under the list).
function lineMode() { return (line && line.mode) || S.mode; }
function isParked(g) { return st.v == null || (!g.own && lineMode() !== 'tag'); }
function dockX(g) { return Math.max(60, g.width - 70); }

function drawTrack(g) {
  const items = offersOnLine();
  const v = st.v;
  ui.track.innerHTML = items.map(it => {
    const p = it.offer.price_eur;
    const lit = v == null || p <= v;
    return `<i class="tg-o${lit ? ' lit' : ''}${it.url === S.leader ? ' lead' : ''}" style="left:${g.x(p).toFixed(1)}px" title="${esc(shopName(it))} ${esc(eur(p))}"></i>`;
  }).join('');
}

// Your price is above what the pick already costs: nothing to wait for, it can be bought now.
function alreadyUnder(v = st.v) {
  if (v == null || st.silent || busy || st.done) return null;
  const { it, url } = pickInfo();
  const p = it && it.offer && it.offer.price_eur;
  return typeof p === 'number' && isFinite(p) && p < v - Math.max(5, v * 0.01) ? { url, it, p } : null;
}

function caption() {
  const v = st.v;
  if (v == null || st.done) { ui.cap.textContent = ''; ui.vlab.textContent = ''; return; }
  const items = offersOnLine();
  const under = items.filter(it => it.offer.price_eur < v);
  const next = items.find(it => it.offer.price_eur > v);
  const parts = [];
  if (under.length) parts.push(`${under.length} offer${under.length === 1 ? '' : 's'} under ${eur(v)}`);
  else parts.push(`nothing under ${eur(v)} yet`);
  if (next) parts.push(`${shopName(next)} would need to drop ${eur(Math.max(1, Math.round(next.offer.price_eur - v)))}`);
  else if (items.length) parts.push('every offer is under it');
  // the pick is already under your price: the next dearer offer does not matter
  ui.cap.textContent = alreadyUnder(v) ? '' : parts.join(' · ');
  // the phone's rule carries a short version at its right end
  ui.vlab.textContent = alreadyUnder(v) ? 'the pick is under it' : under.length ? `${under.length} cheaper ↑` : 'nothing cheaper yet';
  el.classList.toggle('is-empty', under.length === 0);
  // the empty-zone note exists only while the zone is empty (screen readers and page text included)
  const z = el.querySelector('.tg-zlab');
  if (z) z.textContent = under.length ? '' : "nothing here yet · I'll keep watching";
  ui.tag.setAttribute('aria-valuenow', String(Math.round(v)));
  ui.tag.setAttribute('aria-valuetext', `${eur(v)}: ${parts.join(', ')}`);
}

// Phone: a small yellow "your price" pill in the switch row, so nobody has to find the tag under the list.
function quickPill() {
  const row = document.querySelector('#line .ln-axislab');
  let b = document.getElementById('tg-quick');
  if (!row || !isVert() || !S.turned) { if (b) b.hidden = true; return; }
  if (!b) {
    b = document.createElement('button');
    b.type = 'button'; b.id = 'tg-quick'; b.className = 'tg-quick';
    b.addEventListener('click', () => {
      if (busy) return;
      if (st.v == null) { const lp = leaderTag(); if (lp != null) setTag(lp, { arm: true }); }
      reveal();
    });
  }
  // beside the switch, on the same row (the axis words wrap under both)
  const sw = row.querySelector('.ln-switch');
  if (sw ? b.previousElementSibling !== sw : b.parentNode !== row) { if (sw) sw.after(b); else row.appendChild(b); }
  b.hidden = false;
  b.textContent = st.v == null ? 'your price' : eur(st.v);
  b.setAttribute('aria-label', st.v == null ? 'Set your price at the pick’s price' : `Your price ${eur(st.v)}: show it`);
}

function paint() {
  ui.val.textContent = st.v == null ? 'your price' : eur(st.v);
  quickPill();
  const hint = el.querySelector('.tg-hint');
  if (hint) hint.textContent = st.v == null ? 'drag to set your price · we watch, and can buy' : 'your price is on the tag view · drag';
  el.classList.toggle('is-set', st.v != null);
  caption();
  layout();
  if (line && typeof line.highlightBelow === 'function') {
    try { line.highlightBelow(st.v); } catch (e) { /* the line may not be ready */ }
  }
}

function sentence() {
  const v = st.v;
  const phone = NARROW.matches;
  const { it, cond } = pickInfo();
  if (st.done) return;
  const already = alreadyUnder(v);
  el.classList.toggle('is-already', !!already);
  if (already) {
    ui.sentence.innerHTML = `The pick is already ${esc(eur(already.p))}, under your ${esc(eur(v))}. `
      + `<a href="#" class="tg-now">Buy it now →</a>`;
    ui.sentence.querySelector('.tg-now').addEventListener('click', e => { e.preventDefault(); emit('select', already.url); });
    ui.watch.hidden = false;
    return;
  }
  if (st.pick && st.pick.from === 'sheet' && it) {
    const c = COND_WORD[cond] || cond;
    ui.sentence.textContent = `Watching ${shopName(it)}${c ? ' · ' + c : ''}. I'll tell you when one lands under ${eur(v)}.`;
  } else {
    ui.sentence.textContent = `Watching ${thingName()}. I'll tell you when one lands under ${eur(v)}.`;
  }
  // a private seller has no returns window: the money waits in escrow until pickup
  const terms = cond === 'u' ? 'paid into escrow · released at pickup' : 'EU sellers · 14 days to return';
  ui.buyT.textContent = phone ? 'Buy it for me' : `Buy it for me at or under ${eur(v)} (${terms})`;
  ui.watch.hidden = false;
}

// ---------- mode switch around a drag ----------
function enterTagMode() {
  if (st.active) return;
  st.active = true;
  el.classList.add('is-active');
  st.prevMode = S.mode;
  if (line && typeof line.setMode === 'function' && S.mode !== 'tag') {
    try { line.setMode('tag'); } catch (e) { /* ignore */ }
  }
  if (line && typeof line.lockSwitch === 'function') line.lockSwitch(true);
  setTimeout(layout, RM.matches ? 0 : 320);   // the scale animates for 300 ms
}

function leaveTagMode() {
  if (!st.active) return;
  st.active = false;
  el.classList.remove('is-active');
  if (line && typeof line.lockSwitch === 'function') line.lockSwitch(false);
  // once a price is set, the line stays on tag prices so the tag hangs under its real price;
  // the switch under the axis takes you back to the all-in view on purpose
  if (line && typeof line.setMode === 'function' && S.turned && !busy && st.v == null && !S.watch) {
    try { line.setMode('true'); } catch (e) { /* ignore */ }
  }
  setTimeout(layout, RM.matches ? 0 : 320);
}

// ---------- watch ----------
async function arm() {
  if (st.v == null || st.silent) return;
  const v = st.v, buy = st.buy;
  const { url, cond } = pickInfo();
  if (alreadyUnder(v)) { sentence(); ui.guard.hidden = true; el.classList.remove('is-armed'); return; }
  if (st.posted && st.posted.v === v && st.posted.buy === buy && st.posted.url === url) return;
  st.posted = { v, buy, url };
  sentence();
  const body = { query: (S.need && S.need.raw) || S.q || thingName(), max_eur: v, action: buy ? 'auto_buy' : 'notify' };
  if (st.pick && st.pick.from === 'sheet' && url) body.pinned_urls = [url];
  if (buy) body.mandate = { cap_eur: v, expires_at: Math.round(Date.now() / 1000) + 14 * DAY, days: 14, rule: 'eu sellers' };
  let id = null;
  try {
    const r = await fetch('/watches', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (r.ok) { const w = await r.json(); id = w && w.id; }
    else console.warn('[agora] POST /watches', r.status);
  } catch (e) { console.warn('[agora] POST /watches failed', e); }
  if (!st.posted || st.posted.v !== v || st.posted.buy !== buy || st.posted.url !== url) return;   // a newer arm won
  S.you = v; st.guardV = v;
  S.watch = { id, max_eur: v, action: buy ? 'buy' : 'notify', url, cond };
  st.armedAt = Date.now(); st.checkedAt = 0;
  ui.guard.hidden = false;
  el.classList.add('is-armed');
  tickClock();
  emit('watch', S.watch);
}

function tickClock() {
  clearInterval(clock);
  const draw = () => {
    const g = st.guardV != null ? st.guardV : (S.watch && S.watch.max_eur != null ? S.watch.max_eur : st.v);
    if (g == null || ui.guard.hidden) return;
    const since = Math.max(0, Math.round((Date.now() - (st.checkedAt || st.armedAt)) / 1000));
    const ago = since < 60 ? `${since} s ago` : `${Math.round(since / 60)} min ago`;
    // the recorded night tells its own hours: 23:40 → 02:14 → 06:58
    ui.guardT.textContent = st.clock ? `Agora is guarding ${eur(g)} · ${st.clock}`
      : `Agora is guarding ${eur(g)} · ${st.checkedAt ? 'checked' : 'set'} ${ago}`;
  };
  draw();
  clock = setInterval(draw, 1000);
}

// ---------- input ----------
// p: a pointer coordinate in rail px (x on desktop, y on a phone)
function valueAt(p, g = geom()) {
  const c = g.vert ? p : Math.min(g.width - 4, Math.max(4, p));
  const v = g.eur(c);
  return v != null && isFinite(v) ? snap(Math.max(0.5, v)) : st.v;
}
function railCoord(ev, g) {
  const r = ui.rail.getBoundingClientRect();
  return g.vert ? ev.clientY - r.top : ev.clientX - r.left;
}

function onDown(e, jump = false) {
  if (e.button != null && e.button !== 0) return;
  if (busy) return;
  e.preventDefault();
  hinted = true; el.classList.remove('is-hint');
  if (st.done) { st.done = false; el.classList.remove('is-done'); st.posted = null; }
  kbd = false; el.classList.remove('is-kbd');
  ui.tag.focus({ preventScroll: true });
  st.silent = false;
  const wasParked = el.classList.contains('is-parked');
  if (wasParked && st.v != null) el.classList.add('is-glide');
  enterTagMode();
  try { ui.tag.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
  // Relative drag: the tag never jumps under the finger. A tap on the empty rail (jump) moves it there.
  // While the line switches to tag view (300 ms) we wait, then anchor on where the tag landed.
  let anchor = null, last = e;
  const ready = () => {
    const g = geom();
    // first touch on a parked, unset tag: start at the price of the pick (the tag glides there)
    if (!jump && st.v == null) { const lp = leaderTag(); st.v = lp != null ? snap(lp) : valueAt(railCoord(last, g), g); paint(); }
    else if (jump || st.v == null) { st.v = valueAt(railCoord(last, g), g); paint(); }
    const at = (g.raw || g.pos)(st.v);
    anchor = { at: at == null ? railCoord(last, g) : at, p: railCoord(last, g) };
    el.classList.remove('is-glide');
  };
  const wait = (wasParked || jump) && !RM.matches ? 310 : 0;
  const t = setTimeout(ready, wait);
  const move = ev => {
    last = ev;
    if (!anchor) return;
    const g = geom();
    const d = railCoord(ev, g) - anchor.p;
    const v = valueAt(anchor.at + d, g);
    // a scale that clamps at its ends must never move the price against the finger
    if (v == null || v === st.v || (d < 0 && v > st.v) || (d > 0 && v < st.v)) return;
    st.v = v; paint();
  };
  const up = () => {
    clearTimeout(t);
    if (!anchor) ready();
    ui.tag.removeEventListener('pointermove', move);
    ui.tag.removeEventListener('pointerup', up);
    ui.tag.removeEventListener('pointercancel', up);
    setTimeout(() => { leaveTagMode(); arm(); }, RM.matches ? 0 : 420);
  };
  ui.tag.addEventListener('pointermove', move);
  ui.tag.addEventListener('pointerup', up);
  ui.tag.addEventListener('pointercancel', up);
}

function onRailDown(e) {
  // tapping the empty rail jumps the tag there, then drags as usual (desktop only: on a phone the
  // rows under the rule stay tappable)
  if (e.target.closest('.tg-tag') || el.classList.contains('is-vert')) return;
  onDown(e, true);
}

function onKey(e) {
  const k = e.key;
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Enter', 'Escape'].includes(k)) return;
  if (busy) return;
  e.preventDefault();
  kbd = true; el.classList.add('is-kbd');
  if (k === 'Enter' || k === 'Escape') { clearTimeout(keyTimer); leaveTagMode(); if (k === 'Enter') arm(); return; }
  st.silent = false;
  enterTagMode();
  const items = offersOnLine();
  if (st.v == null) { const lp = leaderTag(); st.v = lp != null ? snap(lp) : items.length ? snap(items[Math.floor(items.length / 2)].offer.price_eur) : 100; }
  const pct = e.shiftKey ? 0.10 : 0.01;
  // on a phone the list runs cheapest-first downwards: ↓ moves the rule down (dearer), ↑ up (cheaper)
  const vert = el.classList.contains('is-vert');
  const dir = (k === 'ArrowRight' || (vert ? k === 'ArrowDown' : k === 'ArrowUp')) ? 1 : -1;
  if (k === 'Home') st.v = items.length ? snap(items[0].offer.price_eur) : st.v;
  else if (k === 'End') st.v = items.length ? snap(items[items.length - 1].offer.price_eur) : st.v;
  else {
    let n = snap(st.v * (1 + dir * pct));
    if (n === st.v) n = Math.max(1, st.v + dir * (st.v < 100 ? 1 : 5));
    st.v = n;
  }
  paint();
  clearTimeout(keyTimer);
  keyTimer = setTimeout(() => { leaveTagMode(); arm(); }, 1400);
}

// Bring the tag (and on a phone, its sentence) into view.
function reveal() {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const g = geom();
    const rail = ui.rail.getBoundingClientRect();
    let top, bottom;
    if (g.vert) {
      const y = isParked(g) ? 0 : (g.pos(st.v) ?? 0);
      top = rail.top + y - 40;
      const w = ui.watch.hidden ? null : ui.watch.getBoundingClientRect();
      bottom = w ? Math.max(rail.top + y + 40, w.bottom + 16) : rail.top + y + 40;
    } else {
      const r = el.getBoundingClientRect();
      top = r.top - 24; bottom = r.bottom + 16;
    }
    const vh = innerHeight;
    let dy = 0;
    if (bottom - top <= vh - 80) {
      if (top < 64) dy = top - 64;
      else if (bottom > vh - 16) dy = bottom - (vh - 16);
    } else {
      dy = top - vh * 0.35;          // too tall: centre on the tag itself
    }
    if (Math.abs(dy) > 4) scrollBy({ top: dy, behavior: RM.matches ? 'auto' : 'smooth' });
  }));
}

// ---------- public ----------
/** Move the tag to a price. opts.silent: never POST (the finale); opts.arm: arm right away. */
export function setTag(v, { silent = false, arm: doArm = false, buy = null } = {}) {
  show();
  if (st.done) { st.done = false; el.classList.remove('is-done'); st.posted = null; }
  st.silent = silent;
  if (buy != null) { st.buy = buy; ui.box.checked = buy; }
  el.classList.add('is-glide');
  setTimeout(() => el.classList.remove('is-glide'), 700);
  st.v = snap(v);
  if (silent) {                       // the finale: the line is already in tag view, nothing is posted
    st.guardV = st.v;
    paint(); sentence();
    ui.guard.hidden = false; el.classList.add('is-armed'); tickClock();
    return;
  }
  enterTagMode();
  paint();
  if (doArm) setTimeout(() => { leaveTagMode(); arm(); }, RM.matches ? 200 : 1300);
}

/** The finale's night clock ('23:40'); null goes back to "checked N s ago". */
export function nightClock(t) { st.clock = t || null; ui.guardT && tickClock(); }

/** The finale's watch checked the shops just now. */
export function checked() { st.checkedAt = Date.now(); ui.guard.hidden = false; tickClock(); }

/** One pulse: an offer crossed the tag. */
export function pulse() {
  el.classList.remove('is-pulse');
  void el.offsetWidth;
  el.classList.add('is-pulse');
  setTimeout(() => el.classList.remove('is-pulse'), 900);
}

/** A small object on our own rail (fallback when the line has no placeExtra). On a phone it stands
 * at the right end of the rows, at the y of its price, and climbs past the rule as it gets cheaper. */
export function railExtra(id, { img, eur: v, label }) {
  const node = document.createElement('figure');
  node.className = 'tg-extra';
  node.innerHTML = `${img ? `<img alt="" src="${esc(img)}">` : ''}<figcaption>${esc(label || '')}</figcaption>`;
  ui.rail.appendChild(node);
  let cur = v;
  const ex = {
    place(g) {
      const p = g.pos(cur);
      if (p == null) return;
      node.style.setProperty(g.vert ? '--ey' : '--ex', p.toFixed(1) + 'px');
    },
    moveTo(n) { ghost(cur); cur = n; layout(); },
    remove() { node.remove(); ownExtras.delete(id); },
    el: node,
  };
  ownExtras.set(id, ex);
  layout();
  return ex;
}

/** A faint ghost dot at a tag price (where something used to be). */
export function ghost(v) {
  const g = geom();
  const p = g.pos(v);
  if (p == null) return;
  const d = document.createElement('i');
  d.className = 'tg-ghost';
  if (g.vert) d.style.top = p.toFixed(1) + 'px';
  else d.style.left = p.toFixed(1) + 'px';
  ui.ghosts.appendChild(d);
}

export function clearGhosts() { if (ui.ghosts) ui.ghosts.innerHTML = ''; }

/** Position of a tag price inside #tag's rail (x on desktop, y on a phone). */
export function railX(v) { return geom().pos(v); }

export function state() { return { ...st }; }

function show() {
  if (st.shown) return;
  st.shown = true;
  el.hidden = false;
  el.classList.add('is-shown');
  layout();
  watchForHint();
}

// "Drag me", said once: the first time the parked tag is really on screen, it lifts and glides a
// little the way it wants to go, then settles. Once per page, never while dragging or in the finale.
let hinted = false, hintIO = null;
function watchForHint() {
  if (hinted || hintIO || !window.IntersectionObserver || RM.matches) return;
  hintIO = new IntersectionObserver(es => {
    if (!es.some(e => e.isIntersecting && e.intersectionRatio > 0.9)) return;
    setTimeout(() => {
      if (hinted || st.v != null || st.active || busy || !el.classList.contains('is-parked')) return;
      hinted = true;
      hintIO && hintIO.disconnect(); hintIO = null;
      el.classList.add('is-hint');
      setTimeout(() => el.classList.remove('is-hint'), 2200);
    }, 700);
  }, { threshold: [0, 0.9, 1] });
  hintIO.observe(ui.tag);
}

function reset() {
  clearInterval(clock); clearTimeout(keyTimer);
  st = { v: null, active: false, shown: false, armedAt: 0, checkedAt: 0, buy: false, posted: null, silent: false, prevMode: null, guardV: null, pick: null, done: false };
  for (const [, ex] of ownExtras) ex.remove();
  ownExtras = new Map();
  if (!ui.tag) return;
  el.className = '';
  ui.watch.hidden = true; ui.guard.hidden = true; ui.box.checked = false;
  clearGhosts();
  paint();
}

export function mountTag(root, lineApi) {
  el = root; line = lineApi || null;
  el.setAttribute('aria-label', 'Your price');
  build();
  reset();
  ui.tag.addEventListener('pointerdown', onDown);
  ui.rail.addEventListener('pointerdown', onRailDown);
  ui.tag.addEventListener('keydown', onKey);
  ui.box.addEventListener('change', () => { st.buy = ui.box.checked; st.silent = false; arm(); });
  el.querySelector('.tg-step').addEventListener('click', e => {
    const b = e.target.closest('button[data-d]');
    if (!b || busy || st.v == null) return;
    st.posted = null;
    setTag(Math.max(1, st.v + Number(b.dataset.d)), { arm: true });
  });
  ui.see.addEventListener('click', e => {
    e.preventDefault();
    const w = S.watch || {};
    emit('finale:start', { from: 'tag', url: w.url || pickUrl(), eur: w.max_eur != null ? w.max_eur : st.v });
  });

  on('reset', () => { busy = false; reset(); });
  // bought: the watch is over. One line says so; the checkbox, the guard and "see it buy" go.
  const done = d => {
    const paid = d && (d.paid ?? d.paid_eur);
    if (paid == null || !isFinite(paid)) return;
    const target = d.target != null ? d.target : (st.guardV != null ? st.guardV : st.v);
    st.done = true;
    clearInterval(clock);
    el.classList.add('is-done');
    el.classList.remove('is-armed', 'is-already');
    const under = target != null ? Math.max(0, target - paid) : null;
    ui.sentence.textContent = `Done. Bought for ${eur(paid)} all in${under ? `, ${eur(under)} under your price` : ''}.`;
    ui.cap.textContent = ''; ui.vlab.textContent = '';
    ui.guard.hidden = true;
    ui.watch.hidden = false;
  };
  // only once the story has been told (finale.js emits finale:bought with the receipt), never on
  // the stream's own early "done", which lands while the night's lines are still typing
  on('finale:bought', done);
  on('finale:start', () => { busy = true; el.classList.add('is-busy'); });
  const free = () => { busy = false; el.classList.remove('is-busy'); };
  on('finale:end', free); on('finale:error', free); on('finale:stop', free);
  on('turn', () => { show(); paint(); });
  on('line:turned', () => quickPill());
  on('done', () => { if (S.offers.size) { show(); paint(); } });
  on('offer', () => { if (st.shown) paint(); });
  on('truecost', () => { if (st.shown) layout(); });
  on('line:layout', () => { if (st.shown) layout(); });
  on('mode', () => { if (st.shown) setTimeout(layout, RM.matches ? 0 : 680); });
  on('tag', d => {
    if (!d || d.eur == null || !isFinite(d.eur)) return;
    const fromStage = d.from === 'stage';
    // buy follows the pick: an explicit url (the sheet, the stage) is the offer the watch follows
    if (d.url) st.pick = { url: d.url, from: d.from || 'sheet' };
    else if (d.from === 'sheet') st.pick = { url: S.leader, from: 'sheet' };
    if (d.from === 'sheet') {
      // the sheet just closed: the price must visibly land, wherever the page is
      if (busy) return;                 // the recorded night owns the tag while it plays
      st.posted = null;
      setTag(d.eur, { arm: true });
      sentence();                       // the copy line shows now; the guard follows after POST
      reveal();
      setTimeout(pulse, RM.matches ? 0 : 450);
      return;
    }
    setTag(d.eur, { arm: true, buy: fromStage ? true : null });
  });

  const le = lineEl();
  if (window.ResizeObserver && le) new ResizeObserver(layout).observe(le);
  addEventListener('resize', layout);
  NARROW.addEventListener && NARROW.addEventListener('change', layout);
}
