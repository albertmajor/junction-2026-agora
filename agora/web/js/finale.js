// The night shift (B4): the recorded buy story, told on the line. It buys THE PICK:
// a used pick (the Sony hunt's tori.fi body) runs GET /demo/buy?variant=used&target=<your price>,
// a new one the recorded new-body story. We turn three story lines into typed captions, move the
// pick's object across your tag, drop a torn receipt and let you break the log on purpose.
import { S, on, emit, eur, cutSrc, condLetter, domainOf, allIn, isJobItem, pickUrl as corePick, BRAND } from './core.js';
import { setTag, checked, pulse, railExtra, clearGhosts, nightClock, restoreTag, state as tagState } from './tag.js';

const RM = matchMedia('(prefers-reduced-motion: reduce)');
const NEW_STORY_EUR = 1030;   // the new-body story is recorded at this price (agora/demo_buy.py TARGET)
const USED_PID = 'sony-a7iii-used-tori';   // the mock shop's stand-in for the recorded tori.fi listing

let el, line, ui = {}, run = null;

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = t => { const m = String(t || '').match(/€\s?([\d,]+(?:\.\d+)?)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
const allMoney = t => [...String(t || '').matchAll(/€\s?([\d,]+(?:\.\d+)?)/g)].map(m => parseFloat(m[1].replace(/,/g, '')));
const sleep = ms => new Promise(r => setTimeout(r, ms));

const WIDE = matchMedia('(min-width: 900px)');
const SIDE = matchMedia('(min-width: 900px)');
const wide = () => WIDE.matches && !(line && typeof line.isVertical === 'function' && line.isVertical());

function build() {
  document.querySelectorAll('#main > .fn-lines, #line > .fn-lines').forEach(n => n.remove());
  el.innerHTML = `
    <div class="fn-lines" aria-live="polite"></div>
    <div class="fn-out"></div>`;
  ui = { lines: el.querySelector('.fn-lines'), out: el.querySelector('.fn-out') };
  el.classList.remove('is-side'); el.style.removeProperty('--fy');
  const main = document.getElementById('main'); if (main) main.style.paddingBottom = '';
}

// Desktop: the typed lines sit ABOVE the line, in the band over the cutouts (DESIGN §2 Wow 2.4);
// the receipt drops in a right-hand column beside the tag, so line, tag, lines and receipt share one screen.
function stageDesktop() {
  const lineEl = document.getElementById('line');
  if (!wide() || !lineEl) return;
  // in the flow right above the line (never over the cutouts: their labels need that band)
  lineEl.before(ui.lines);
  ui.lines.classList.add('is-band');
  // one deliberate move at the start: the band, the line and your price on one screen
  requestAnimationFrame(() => {
    const top = ui.lines.getBoundingClientRect().top;
    const t = document.querySelector('#tag .tg-tag');
    const bottom = t ? t.getBoundingClientRect().bottom + 24 : top;
    const bar = document.getElementById('stagebar');
    const floor = innerHeight - (bar ? bar.offsetHeight + 16 : 0);
    let dy = 0;
    if (bottom > floor) dy = bottom - floor;
    if (top - dy < 16) dy = top - 16;
    if (Math.abs(dy) > 4) scrollBy({ top: dy, behavior: RM.matches ? 'auto' : 'smooth' });
  });
  if (SIDE.matches) {
    const tag = document.getElementById('tag');
    el.classList.add('is-side');
    // level with the switch row, so the receipt stands beside the tag, close to the line
    if (tag) el.style.setProperty('--fy', sideY(tag) + 'px');
  }
}
// the receipt's top: the switch row right under the line (the line may have shrunk since the start)
function sideY(tag = document.getElementById('tag')) {
  const row = document.querySelector('#line .ln-axislab');
  const par = el.offsetParent;
  if (row && par && row.offsetHeight) {
    const y = row.getBoundingClientRect().top - par.getBoundingClientRect().top;
    if (isFinite(y)) return Math.max(0, Math.round(y));
  }
  return Math.max(0, tag.offsetTop - 44);
}
// The side column must never sit on the tag: if your price hangs under its left edge, the receipt
// drops below the tag instead (measured once the receipt has its size).
function clearOfTag() {
  if (!el.classList.contains('is-side')) return;
  const tag = document.querySelector('#tag .tg-tag');
  const box = ui.out && ui.out.querySelector('.fn-receipt');
  if (!tag || !box) return;
  const t = tag.getBoundingClientRect(), r = box.getBoundingClientRect();
  if (t.right + 16 > r.left && t.bottom > r.top && t.top < r.bottom) {
    const tg = document.getElementById('tag');
    el.style.setProperty('--fy', (tg.offsetTop + tg.offsetHeight + 12) + 'px');
  }
}
// keep the receipt on screen without ever losing the line: scroll only as far as the axis allows
function showReceipt(art, target = art) {
  if (!wide()) {
    // phone: the receipt's foot at the bottom of the screen, but never past your price's rule
    const r = target.getBoundingClientRect();
    const t = document.querySelector('#tag .tg-tag');
    const tagTop = t && t.offsetParent ? t.getBoundingClientRect().top : r.top;
    // the receipt keeps your price in view; the red ledger row (verify) is the proof and wins
    const keep = target === art ? Math.max(0, tagTop - 24) : Infinity;
    // the tour's fixed bar covers the screen's foot: the receipt ends above it
    const bar = document.getElementById('stagebar');
    const barTop = bar && bar.getClientRects().length ? Math.min(innerHeight, bar.getBoundingClientRect().top) : innerHeight;
    let lift = 0;
    try { lift = new DOMMatrixReadOnly(getComputedStyle(art).transform).m42 || 0; } catch { lift = 0; }
    const dy = Math.min(r.bottom - lift - (barTop - 12), keep, r.top - lift - 72);
    if (Math.abs(dy) > 4) scrollBy({ top: dy, behavior: RM.matches ? 'auto' : 'smooth' });
    return;
  }
  if (el.classList.contains('is-side') && target === art) el.style.setProperty('--fy', sideY() + 'px');
  clearOfTag();
  const main = document.getElementById('main');
  if (main && el.classList.contains('is-side')) {
    const over = el.getBoundingClientRect().bottom - main.getBoundingClientRect().bottom;
    const had = parseFloat(main.style.paddingBottom) || 0;   // grow what is already there
    if (over > -24) main.style.paddingBottom = Math.ceil(had + over + 24) + 'px';
  }
  const r = target.getBoundingClientRect();
  // the receipt may still be sliding in: measure where it will land, not where it is
  let lift = 0;
  try { lift = new DOMMatrixReadOnly(getComputedStyle(art).transform).m42 || 0; } catch { lift = 0; }
  const lineEl = document.getElementById('line');
  // the line's real top: its highest object (with its price label), not the empty band above it
  let top = lineEl ? lineEl.getBoundingClientRect().top : 0;
  if (lineEl) {
    let hi = Infinity;
    lineEl.querySelectorAll('.ln-o:not(.ln-off):not(.ln-gone) .ln-face').forEach(o => {
      const b = o.getBoundingClientRect();
      if (b.height > 0 && b.width > 0) hi = Math.min(hi, b.top);
    });
    if (isFinite(hi)) top = Math.max(top, hi - 30);
  }
  const bar = document.getElementById('stagebar');
  const floor = innerHeight - (bar ? bar.offsetHeight + 28 : 16);
  const need = r.bottom - lift - floor;
  const room = Math.max(0, top - 8);
  const dy = Math.min(need, room);
  if (dy > 4) scrollBy({ top: dy, behavior: RM.matches ? 'auto' : 'smooth' });
}

// ---------- typed caption lines ----------
async function type(text, cls = '') {
  const p = document.createElement('p');
  p.className = 'fn-line ' + cls;
  p.setAttribute('aria-label', text);
  ui.lines.appendChild(p);
  const r = p.getBoundingClientRect();
  if (!wide() && r.bottom > innerHeight - 8) p.scrollIntoView({ behavior: RM.matches ? 'auto' : 'smooth', block: 'nearest' });
  const span = document.createElement('span');
  span.setAttribute('aria-hidden', 'true');
  p.appendChild(span);
  if (RM.matches) { span.textContent = text; return p; }
  p.classList.add('is-typing');
  for (let i = 1; i <= text.length; i++) {
    if (run && run.dead) break;
    span.textContent = text.slice(0, i);
    await sleep(text[i - 1] === ' ' ? 10 : 16);
  }
  p.classList.remove('is-typing');
  return p;
}

// ---------- the mock-shop object ----------
function placeShop(v, plan) {
  // used: the shop object is the pick itself (its seller, its photo), so it takes the pick's place on the line
  const opts = { img: plan.img, eur: v, label: plan.label, stands: plan.variant === 'used' ? plan.url : null };
  // the line places it on desktop and in the phone's list alike; our own rail is the fallback
  if (line && typeof line.placeExtra === 'function') {
    try {
      const h = line.placeExtra('mockshop', opts);
      if (h) return { moveTo: n => h.moveTo(n), remove: () => h.remove && h.remove(), dim: on => h.el && h.el.classList.toggle('is-dim', on) };
    } catch (e) { console.warn('[agora] placeExtra failed', e); }
  }
  const h = railExtra('mockshop', opts);
  return { moveTo: n => h.moveTo(n), remove: () => h.remove(), dim: on => h.el.classList.toggle('is-dim', on) };
}
let curShop = null;

// ---------- the receipt ----------
function receipt({ paid, target, asked, mandateId, rows, chainOk, watchId, order, plan, escrow }) {
  const under = target != null && paid != null ? target - paid : null;
  const short = String(mandateId || '').replace(/^\w+?_/, '').slice(0, 4) || '–';
  const used = plan.variant === 'used';
  const head = `Bought ${used ? 'used ' : ''}${eur(paid)} · ${eur(under)} under your price · mandate #${short}`;
  const sub = `${eur(under)} under your price · mandate #${short}`;
  ui.out.innerHTML = `
    <article class="fn-receipt" aria-label="${esc(head)}">
      <p class="fn-big"><span>${esc(plan.item)}</span> ${esc(eur(paid))}</p>
      <p class="fn-head">${esc(sub)}</p>
      <dl class="fn-rows">
        ${asked ? `<div><dt>${used ? 'Seller asked' : 'Shop asked'}</dt><dd>${esc(eur(asked))}</dd></div>` : ''}
        <div><dt>Your price</dt><dd>${esc(eur(target))}</dd></div>
        <div class="fn-sum"><dt>Paid</dt><dd>${esc(eur(paid))}</dd></div>
        ${used ? `<div><dt>Payment</dt><dd>${esc('private seller · escrow till pickup')}</dd></div>` : ''}
        <div><dt>Mandate</dt><dd title="${esc(order || '')}">#${esc(short)} · signed, cap checked</dd></div>
        <div><dt>Decision log</dt><dd class="fn-chain">${rows ? esc(rows) + ' rows · ' : ''}${chainOk ? 'chain ok' : 'chain broken'}</dd></div>
      </dl>
      <span class="fn-stamp" aria-hidden="true">bought</span>
      <div class="fn-verify">
        <button type="button" class="fn-vbtn">verify →</button>
        <span class="fn-vnote">edit one row behind ${BRAND}'s back, then check</span>
      </div>
      <div class="fn-ledger" hidden></div>
    </article>`;
  const art = ui.out.querySelector('.fn-receipt');
  requestAnimationFrame(() => art.classList.add('is-in'));
  // the headline follows the story: what was bought, and what we would still pick
  const big = used
    ? `Bought used at ${plan.seller} for ${eur(paid)} all in. ${eur(under)} under your price.`
    : `Bought for ${eur(paid)} all in. ${eur(under)} under your price.`;
  emit('verdict:override', { big, small: used ? usedNote(plan) : stillPick() });
  emit('finale:bought', { paid, target, under });
  setTimeout(() => showReceipt(art), 160);
  // phone: the line above may still settle while the receipt slides in; one quiet correction after
  if (!wide()) setTimeout(() => { if (art.isConnected) showReceipt(art); }, 900);
  ui.out.querySelector('.fn-vbtn').addEventListener('click', () => verify(watchId));
}

function usedNote(plan) {
  const where = plan.recorded ? 'A recorded night on a recorded listing' : 'A recorded night';
  return `${where}: our mock shop played the ${plan.seller} private seller. The money waits in escrow until you pick it up.`;
}

function stillPick() {
  const v = S.verdict && S.verdict.verdict;
  const u = (line && line.winner) || corePick() || (v && (v.best_offer_url || v.best_true_cost_url)) || S.leader;
  const it = u && S.offers.get(u);
  const a = it ? allIn(it) : null;
  if (!it || a == null) return 'The night shift: a recorded buy on our mock shop, inside your mandate.';
  const cond = String(it.offer.condition || '').toLowerCase();
  const shop = it.offer.source || '';
  const what = isJobItem(it) ? `${eur(a, { dp: Math.abs(a % 1) > 0.004 ? 2 : 0 })} for the job` : `${eur(Math.round(a), { dp: 0 })} all in`;
  return `A recorded night on our mock shop. For you we would still pick ${cond ? cond + ' ' : ''}at ${shop}: ${what}.`;
}

async function verify(watchId) {
  const btn = ui.out.querySelector('.fn-vbtn');
  const box = ui.out.querySelector('.fn-ledger');
  if (!watchId || !btn) return;
  btn.disabled = true; btn.textContent = 'checking…';
  let t = null, p = null;
  try {
    const r = await fetch('/demo/tamper', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ watch_id: watchId }) });
    t = r.ok ? await r.json() : null;
    const q = await fetch(`/watches/${encodeURIComponent(watchId)}/proof`);
    p = q.ok ? await q.json() : null;
  } catch (e) { console.warn('[agora] verify failed', e); }
  if (!p || !Array.isArray(p.chain)) { btn.disabled = false; btn.textContent = 'verify →'; return; }
  const bad = p.first_broken_index;
  const chain = p.chain;
  const at = bad == null ? chain.length - 1 : bad;
  const from = Math.max(0, at - 2), to = Math.min(chain.length, at + 2);
  // what changed: the first euro amount that differs between the signed row and the edited one
  const was = allMoney(t && t.was), now = allMoney(t && t.now);
  const k = was.findIndex((x, i) => now[i] !== x);
  const change = k >= 0 && now[k] != null ? `${eur(was[k])} → ${eur(now[k])}` : '';
  const row = (r, i) => {
    const broken = i === bad;
    const text = broken && t && t.now ? t.now : (r.reason || r.outcome || '');
    return `<li class="${broken ? 'is-bad' : (bad != null && i > bad ? 'is-after' : '')}">
      <span class="fn-i">#${i}</span>
      <span class="fn-r">${esc(String(text).slice(0, 90))}</span>
      <span class="fn-h">${esc(String(r.hash || '').slice(0, 8))}</span>
      ${broken ? `<span class="fn-why">row ${i} changed after signing · caught${change ? ` <s>${esc(change.split(' → ')[0])}</s> → ${esc(change.split(' → ')[1])}` : ''}</span>` : ''}
    </li>`;
  };
  box.innerHTML = `
    <p class="fn-ltitle">${bad == null ? `chain ok · ${chain.length} rows` : `re-hashed ${chain.length} rows · the chain breaks at row ${bad}`}</p>
    <ol>${chain.slice(from, to).map((r, k2) => row(r, from + k2)).join('')}</ol>`;
  const note = ui.out.querySelector('.fn-vnote');
  if (note) note.textContent = bad == null ? 'every row still matches its signature' : 'someone edited the paid amount after it was signed';
  box.hidden = false;
  ui.out.querySelector('.fn-chain').textContent = bad == null ? 'chain ok' : `broken at row ${bad}`;
  ui.out.querySelector('.fn-receipt').classList.toggle('is-tampered', bad != null);
  // the red row is the proof: bring it into view, never at the cost of the line
  const redRow = box.querySelector('.is-bad') || box;
  setTimeout(() => showReceipt(ui.out.querySelector('.fn-receipt'), redRow), 80);
  btn.textContent = bad == null ? 'chain ok' : 'caught';
  emit('proof', { watch_id: watchId, chain_ok: bad == null, first_broken_index: bad, tampered: true });
}

// ---------- the run ----------
// ---------- what tonight buys ----------
function pickUrl() {
  const v = S.verdict && S.verdict.verdict;
  return (line && line.winner) || corePick() || (v && (v.best_offer_url || v.best_true_cost_url)) || S.leader || null;
}

/** The pick and your price: finale:start {url, eur, cond}, else S.watch {url, max_eur, cond}, else the verdict pick. */
async function plan(d = {}) {
  const w = S.watch || {};
  const url = d.url || w.url || pickUrl();
  const it = url ? S.offers.get(url) : null;
  const o = (it && it.offer) || {};
  const fromEvent = d.url || d.eur != null;
  let v = Number(fromEvent ? d.eur : (w.url ? w.max_eur : null));
  if (!isFinite(v) || v <= 0) v = Number(o.price_eur);
  const cond = d.cond || (w.url || fromEvent ? w.cond : null) || condLetter(o.condition);
  const q = (S.q || '').toLowerCase();
  const sony = !q || /sony|a7/.test(q);
  // used, or unknown condition: the Sony hunt's pick is the used tori.fi body
  if (sony && cond !== 'n' && cond !== 'r') {
    const seller = domainOf(url) || 'tori.fi';
    const listed = Number(o.price_eur);
    let target = isFinite(v) && v > 0 ? Math.round(v * 100) / 100 : 825;
    let note = null;
    // a used listing has one price: we never pays more than the pick was listed at
    if (isFinite(listed) && listed > 0 && target > listed) {
      note = `the pick was listed at ${eur(listed)} on ${seller} · ${BRAND} holds your price there`;
      target = listed;
    }
    return { variant: 'used', target, seller, img: cutSrc(url), url, label: `${seller} · used`,
             item: `${o.title || 'Sony A7 III body'} · used · ${seller}`, recorded: false, note };
  }
  if (sony) {
    // the new-body story is recorded at one price: tell it at that price, from the pick's own photo
    return { variant: 'new', target: NEW_STORY_EUR, seller: 'agora mock shop', img: cutSrc(url), url,
             label: 'mock shop · new', item: 'Sony A7 III body, new · agora mock shop', recorded: false,
             note: isFinite(v) && Math.abs(v - NEW_STORY_EUR) > 1 ? `a recorded night: a new Sony A7 III, your price ${eur(NEW_STORY_EUR)}` : null };
  }
  // not a Sony hunt: the recorded night still tells the Sony's used listing, and says so
  let img = null;
  try {
    const r = await fetch('/mockshop/products/' + USED_PID);
    if (r.ok) { const p = await r.json(); img = p.image ? cutSrc(p.image) : null; }
  } catch (e) { /* a missing photo is fine: the object shows its caption */ }
  return { variant: 'used', target: 825, seller: 'tori.fi', img, url: null, label: 'tori.fi · used',
           item: 'Sony A7 III body · used · tori.fi', recorded: true,
           note: 'a recorded night: a used Sony A7 III on tori.fi, your price €825' };
}

export async function runFinale(d = {}) {
  if (!el) return;
  if (run) { run.dead = true; run.es && run.es.close(); run.shop && run.shop.remove(); }
  const me = run = { dead: false, es: null, shop: null, asked: null, paid: null, order: null, mandate: null, said: new Set(), escrow: null };
  build();
  const P = me.plan = await plan(d || {});
  if (me.dead || run !== me) return;
  const TARGET = P.target;
  // what the viewer had before the night took over: their price and their view come back afterwards
  let before = { v: null, mode: S.mode };
  try { before = { v: tagState().v, mode: S.mode }; } catch (e) { /* tag not mounted */ }
  me.before = before;
  clearGhosts();
  el.classList.add('is-on');
  document.documentElement.classList.add('night');
  me.night = 0;
  nightClock('23:40');
  // the page never jumps: on a wide screen everything fits beside the line; a phone keeps its place

  if (line && typeof line.setMode === 'function') { try { line.setMode('tag'); } catch (e) { /* ignore */ } }
  setTag(TARGET, { silent: true, buy: true });
  stageDesktop();
  if (line && typeof line.highlightBelow === 'function') { try { line.highlightBelow(TARGET); } catch (e) { /* ignore */ } }

  const queue = [];
  let typing = Promise.resolve();
  const HOURS = ['02:14', '04:31', '06:58'];
  const say = (key, text, cls) => {
    if (me.said.has(key)) return;
    me.said.add(key);
    const hour = cls === 'is-note' ? null : HOURS[Math.min(HOURS.length - 1, me.night++)];
    typing = typing.then(() => { if (me.dead) return null; if (hour) nightClock(hour); return type(text, cls); });
    queue.push(typing);
  };
  if (P.note) say('note', P.note, 'is-note');

  const src = P.variant === 'used'
    ? `/demo/buy?variant=used&target=${encodeURIComponent(P.target)}&pause=1.2`
    : '/demo/buy?pause=1.2';
  const open = () => {
  const es = me.es = new EventSource(src);
  es.onmessage = async ev => {
    if (me.dead) return;
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    const d = m.data || {};
    emit(m.type === 'story' || m.type === 'proof' ? m.type : 'finale:' + m.type, d);
    if (m.type === 'story') onStory(me, d, say);
    else if (m.type === 'proof') { me.proof = d; }
    else if (m.type === 'done') {
      es.close();
      await typing;
      if (me.dead) return;
      const p = me.proof || {};
      const rec = p.receipt || {};
      if (d.status !== 'bought' && !rec.paid_eur) {
        // another viewer's night reset the shop under us: tell it again, once
        if (d.status === 'stopped' && !me.retried) {
          me.retried = true; me.said = new Set(); me.night = 0; me.proof = null;
          await type('the shop was busy · trying again', 'is-note');
          if (!me.dead) open();
          return;
        }
        await type(`no buy this time: ${d.status || 'no deal'}`, 'is-note');
        end();
        return;
      }
      await sleep(RM.matches ? 0 : 500);
      end(true);
      receipt({
        paid: rec.paid_eur ?? d.paid_eur ?? me.paid, target: TARGET, asked: me.asked,
        mandateId: rec.closed_mandate_id || me.mandate, rows: p.rows, chainOk: p.chain_ok !== false,
        watchId: d.watch_id || p.watch_id, order: rec.order_id || me.order, plan: P, escrow: me.escrow,
      });
    } else if (m.type === 'error') {
      es.close();
      end();
      type('the buy story stopped: ' + (d.message || 'error'), 'is-note');
      return;
    }
  };
  es.onerror = () => {
    if (me.dead) return;
    es.close();
    emit('finale:stop', {});
    end();
    if (!me.proof) type('lost the story stream', 'is-note');
  };
  };
  // night is over: the page's own light comes back, the line steps back out
  const end = (bought = false) => {
    emit('finale:end', {});
    document.documentElement.classList.remove('night');
    if (line && typeof line.focus === 'function') { try { line.focus(null); } catch (e) { /* ignore */ } }
    // no buy, or a recorded story told over someone else's hunt: hand back their price, view and offers
    if (!bought || P.recorded) {
      if (!bought && me.shop) { try { me.shop.remove(); } catch (e) { /* ignore */ } me.shop = null; }
      try { restoreTag(me.before.v); } catch (e) { /* ignore */ }
      if (line && typeof line.highlightBelow === 'function') { try { line.highlightBelow(me.before.v); } catch (e) { /* ignore */ } }
      if (me.before.mode && line && typeof line.setMode === 'function') { try { line.setMode(me.before.mode, { calm: true }); } catch (e) { /* ignore */ } }
    }
  };
  open();
}

function onStory(me, d, say) {
  const P = me.plan, TARGET = P.target, used = P.variant === 'used';
  const kind = String(d.title || '');
  const text = String(d.text || '');
  if (!text) {                                   // a beat header: "1 ARM", "2 LIE DETECTOR …"
    if (/^\d/.test(String(d.step)) && d.step > 1) checked();
    return;
  }
  if (kind === 'shop') {                         // "our mock shop lists it at €1,099 (target …)"
    me.asked = money(text);
    if (me.asked && !me.shop) me.shop = placeShop(me.asked, P), curShop = me.asked;
    // close-up on your price: the shop's glide across the tag is the climax, so make it long
    if (me.asked && line && typeof line.focus === 'function') {
      const lo = Math.min(TARGET, me.asked), hi = Math.max(TARGET, me.asked);
      const pad = Math.max(30, (hi - lo) * 0.6);
      try { line.focus(lo - pad * 1.4, hi + pad); } catch (e) { /* ignore */ }
    }
  } else if (kind === 'decision' && /sold out/i.test(text)) {
    checked();
    if (me.shop) { me.shop.dim(true); setTimeout(() => me.shop && me.shop.dim(false), 1600); }
    say('lie', used ? 'listing says sold · still listed, data says in stock · lie caught'
                    : 'shop says sold out · page shows in stock · lie caught');
  } else if (kind === 'haggle' && /declined/i.test(text)) {
    checked();
    const offered = money(text) ?? me.asked;
    const cite = used ? (text.match(/competitor (€[\d,.]+) at (\S+?)\)/) || null) : null;
    say('declined', `${eur(offered)} offered · declined, above your ${eur(TARGET)}`
      + (cite ? ` · it was ${cite[1]} on ${cite[2]}` : ''));
  } else if (kind === 'counter') {
    const n = money(text);
    if (n != null) {
      say('counter', `${used ? 'seller' : 'shop'} counters ${eur(n)} · accepted inside your mandate`);
      const was = curShop;
      if (me.shop) { me.shop.moveTo(n); curShop = n; }
      if (was != null && was > TARGET && n <= TARGET) {
        setTimeout(() => {
          pulse();
          if (line && typeof line.pulse === 'function') { try { line.pulse(); } catch (e) { /* ignore */ } }
        }, RM.matches ? 0 : 520);
      }
    }
  } else if (kind === 'order') {
    const nums = allMoney(text);
    me.paid = nums[0] ?? me.paid;
    me.order = (text.match(/^(\S+):/) || [])[1] || null;
    me.mandate = (text.match(/closed mandate (\S+)/) || [])[1] || null;
  } else if (kind === 'escrow') {
    me.escrow = 'held in escrow · released at pickup';
    say('escrow', 'private seller · paid into escrow · released at pickup', 'is-note');
  }
}

export function mountFinale(root, lineApi) {
  el = root; line = lineApi || null;
  el.setAttribute('aria-label', 'Buy it for me: the recorded night');
  build();
  on('finale:start', d => runFinale(d));
  on('reset', () => {
    if (run) { run.dead = true; run.es && run.es.close(); run.shop && run.shop.remove(); run = null; }
    el.classList.remove('is-on');
    document.documentElement.classList.remove('night');
    nightClock(null);
    build();
  });
  // the stage tour (and anyone else) can press verify without hunting for the button
  on('finale:verify', () => { const b = ui.out && ui.out.querySelector('.fn-vbtn'); if (b && !b.disabled) b.click(); });
}
