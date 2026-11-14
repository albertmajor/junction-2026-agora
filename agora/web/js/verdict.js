// verdict.js (B3): the one sentence above the line, the facts under it, and the pick card beside it.
// hunting… → provisional answer + "checking N more shops" → final answer + "✓ checked".
import { S, on, emit, eur, cutSrc, goHref, domainOf, isSetAside, isProductPhoto, allIn, pickUrl, cheapestByCondition, shippingUnknown, shipsUnconfirmed, shipNote, trustMark, isUnsure, unsureWhy } from './core.js';
import { flagHtml, originFor, countryName } from './flags.js';
import { pickMonkey } from './mascot.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let root, els = {}, finished = false, override = null;   // override: the finale's "Bought…" headline

const COND_WORD = { new: 'New', refurbished: 'Refurbished', used: 'Used', rental: 'Rental', service: '' };

function condWord(c) {
  const k = String(c || '').toLowerCase();
  for (const key of Object.keys(COND_WORD)) if (k.startsWith(key.slice(0, 4))) return COND_WORD[key];
  return k ? k[0].toUpperCase() + k.slice(1) : '';
}

// Half to even, like the engine (Python round), so "€62" here matches "€62" in the headline.
function roundEven(n) {
  const f = Math.floor(n), d = n - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(n);
}

// "€9.16" under €100, whole euros above; per-job prices are whole euros ('job2': keep cents like €62.50).
export function money(n, per) {
  if (n == null || !isFinite(n)) return '€–';
  if (per === 'job2') return eur(n, { dp: Math.abs(n % 1) > 0.004 ? 2 : 0 });
  if (per === 'job' || Math.abs(n) >= 100) return eur(roundEven(n), { dp: 0 });
  return eur(n, { dp: Math.abs(n) % 1 === 0 ? 0 : 2 });
}

function leaderUrl() {
  // the pick is the lowest all-in price you can surely buy; before anything is costed, the engine's leader
  const v = S.verdict && S.verdict.verdict;
  return pickUrl() || S.leader || (v && (v.best_offer_url || v.best_true_cost_url)) || null;
}

function costed(item) {
  return item && allIn(item) != null && !isSetAside(item);
}
const shopOf = it => (it.offer && it.offer.source) || domainOf(it.url);
const tagOf = it => { const p = it && it.offer && it.offer.price_eur; return typeof p === 'number' && isFinite(p) && p > 0 ? p : null; };
const extrasOf = it => { const a = allIn(it), t = tagOf(it); return a != null && t != null ? a - t : 0; };

// What was added on top of the tag, in plain words.
export function addedPhrase(it) {
  const rec = (it && it.tc && it.tc.true_cost && it.tc.true_cost.receipt) || [];
  const words = [];
  for (const [label, v] of rec.slice(1)) {
    if (!(v > 0.5)) continue;
    const l = String(label).toLowerCase();
    const w = /vat|dut|customs/.test(l) ? 'import VAT' : /ship|deliver|postage/.test(l) ? 'shipping' : /fee|call-out/.test(l) ? 'fees' : null;
    if (w && !words.includes(w)) words.push(w);
  }
  return words.length ? words.join(' and ') : 'extras';
}

// The lowest tag on the line, when it is not the pick and costs more once everything is added.
function cheapestTag(lead) {
  let cheapest = null;
  for (const it of S.offers.values()) {
    if (!costed(it) || tagOf(it) == null) continue;
    if (!cheapest || tagOf(it) < tagOf(cheapest)) cheapest = it;
  }
  if (!cheapest || !lead || cheapest.url === lead.url) return null;
  return extrasOf(cheapest) > 0.5 || shipsUnconfirmed(cheapest) ? cheapest : null;
}
export function cheapestTagUrl() {
  const url = leaderUrl(); const lead = url ? S.offers.get(url) : null;
  const c = costed(lead) ? cheapestTag(lead) : null;
  return c ? c.url : null;
}

// The cheapest costed offer whose all-in figure is below the pick's but that we cannot be sure of.
function cheaperUnsure(lead) {
  const a = allIn(lead);
  let best = null;
  for (const it of S.offers.values()) {
    if (!costed(it) || it.url === lead.url || !isUnsure(it)) continue;
    const v = allIn(it);
    if (v < a - 0.5 && (!best || v < allIn(best))) best = it;
  }
  return best;
}
// "is before shipping, and the shop doesn't say it ships to Finland" — the reason in a sentence
function whyWords(it) {
  const w = unsureWhy(it);
  if (/ships to FI\?/.test(w)) return 'is before shipping, and the shop doesn’t say it ships to Finland';
  if (/no shipping/.test(w)) return 'but the shop doesn’t ship to Finland';
  if (/out of stock/.test(w)) return 'but it is out of stock';
  if (/from/.test(w)) return 'is a “from” price, not this exact one';
  if (/reviews/.test(w)) return 'but its reviews show red flags';
  return 'but we can’t be sure of that price';
}

// "€795 + shipping" when the shop abroad does not confirm shipping to you
export function allInText(it, per) {
  const a = allIn(it);
  return money(a, per === 'job' ? 'job2' : 'job') + shipNote(it);
}

// The facts under the headline, as label/value rows (same sentences as before, split at their seams):
// "Added on top", the cheapest per other condition, and the lowest tag that costs more once it is all in.
// Each row: {k, v, url?} where v is plain text and url (optional) makes the shop a link to its receipt.
function factRows(lead) {
  const per = lead && lead.tc.true_cost.per;
  const rows = [];
  if (lead && per !== 'job') {
    const tag = money(tagOf(lead), 'job');
    const ex = extrasOf(lead);
    let why;
    if (ex > 0.5) why = `${tag} on the tag + ${money(ex, 'job')} ${addedPhrase(lead)}`;
    else if (ex < -0.5) why = `${tag} on the tag, ${money(-ex, 'job')} VAT back on export`;
    else why = S.mode === 'true' ? 'nothing on top of the tag' : `${money(allIn(lead), 'job')} all in`;
    if (shipsUnconfirmed(lead)) why += ', and shipping to Finland is not confirmed';
    else if (shippingUnknown(lead)) why += '; shipping not listed';
    rows.push({ k: 'Added on top', v: why[0].toUpperCase() + why.slice(1) + '.', key: 'add' });
    // the cheapest per condition, calmly: one row each, at most two
    const byC = cheapestByCondition();
    const mine = String(lead.offer.condition || '').toLowerCase().replace(/^refurb.*/, 'refurbished');
    ['new', 'refurbished', 'used'].filter(c => c !== mine && byC[c]).slice(0, 2).forEach(c => {
      const it = byC[c].it;
      // a cheaper one that cannot be the pick says why, right here
      const why = isUnsure(it) && allIn(it) < allIn(lead) - 0.5
        ? (shipsUnconfirmed(it) ? '; the shop doesn’t say it ships to Finland.' : `; ${whyWords(it).replace(/^(but |is )/, '')}.`) : '';
      rows.push({ k: `Cheapest ${c}`, pre: `${allInText(it)} at `, shop: shopOf(it), url: it.url, item: it, post: why, key: 'c-' + c, cheap: !!why });
    });
  }
  if (lead && per === 'job') {
    const first = String((lead.tc.true_cost.receipt || [[]])[0][0] || '');
    const m = /^(€[\d.,]+)\/h\b.*?x\s*([\d.]+)\s*h(?: for ([^()]+?))?\s*(\(|$)/.exec(first);
    const h = (S.verdict && S.verdict.verdict && S.verdict.verdict.headline) || '';
    const ded = /about (€[\d,.]+) after the household deduction/.exec(h);
    if (m) rows.push({ k: 'The job', v: `${m[1]} an hour × ${m[2]} h${m[3] ? ' for ' + m[3].trim() : ''}.`, key: 'job' });
    if (ded) rows.push({ k: 'After deduction', v: `About ${ded[1]} after the household deduction.`, key: 'ded' });
  }
  // why the pick is not the cheapest figure on the list: the cheapest offer below it that we cannot be sure of
  const shown = new Set(rows.filter(r => r.url).map(r => r.url));
  const below = lead && per !== 'job' ? cheaperUnsure(lead) : null;
  if (below && !shown.has(below.url)) {
    const org = originFor(below), cc = org && org.country_code;
    const where = cc && String(cc).toUpperCase() !== 'FI' ? ` (${String(cc).toUpperCase() === 'US' ? 'US' : countryName(cc)})` : '';
    rows.push({ k: 'Why not cheaper?', pre: `${money(allIn(below), 'job')} at `, shop: shopOf(below), url: below.url, item: below,
      post: `${where} ${whyWords(below)}.${extrasOf(below) > 0.5 ? ` Its ${money(tagOf(below), 'job')} tag becomes ${money(allIn(below), 'job')} with ${addedPhrase(below)}.` : ''}`, key: 'why', cheap: true });
    shown.add(below.url);
  }
  const cheapest = cheapestTag(lead);
  if (cheapest && !shown.has(cheapest.url)) {
    const ex = extrasOf(cheapest);
    const after = ex > 0.5 ? ` becomes ${money(allIn(cheapest), 'job')} with ${addedPhrase(cheapest)}` : ` is ${money(allIn(cheapest), 'job')} all in`;
    const ship = shipsUnconfirmed(cheapest) ? ', before shipping, and the shop doesn’t say it ships to Finland' : '';
    rows.push({ k: 'Lowest tag', pre: `${money(tagOf(cheapest), 'job')} at `, shop: shopOf(cheapest), url: cheapest.url, item: cheapest,
      post: `${after}${ship}.`, key: 'cheap', cheap: true });
  }
  const rc = S.recheck && lead && S.recheck.to === lead.url ? S.recheck : null;
  if (rc) {
    const from = S.offers.get(rc.from);
    const fromShop = from ? shopOf(from) : rc.domain;
    rows.push({ k: 'Re-checked', v: `After reviews: ${fromShop} has red flags, so this is the next best.`, key: 'rc' });
  }
  return rows;
}

function setFacts(rows) {
  const el = els.facts;
  const key = JSON.stringify(rows.map(r => [r.k, r.v, r.pre, r.shop, r.post, r.item ? flagHtml(r.item) : '']));
  if (el.dataset.k === key) return;
  el.dataset.k = key;
  el.innerHTML = rows.map(r => {
    const val = r.v != null ? esc(r.v)
      : `${esc(r.pre)}<button type="button" class="v-shop" data-url="${esc(r.url)}">${flagHtml(r.item)}<span>${esc(r.shop)}</span></button>${esc(r.post)}`;
    return `<div class="v-row${r.cheap ? ' is-cheap' : ''}" data-k="${esc(r.key)}"><dt>${esc(r.k)}</dt><dd>${val}</dd></div>`;
  }).join('');
  el.hidden = !rows.length;
}

// The pick card: photo, flag + shop, condition · city, the shop's trust mark, Open listing, Receipt.
function setPick(lead) {
  const el = els.pick;
  if (!lead) { el.hidden = true; el.dataset.k = ''; return; }
  const o = lead.offer || {};
  const org = originFor(lead);
  const tm0 = trustMark(lead);
  const tm = tm0 && tm0.state !== 'none' ? tm0 : null;   // "no reviews found" says nothing on the pick (the receipt keeps it)
  const city = (org && org.city) || '';
  const sub = [condWord(o.condition).toLowerCase(), city].filter(Boolean).join(' · ');
  const key = [lead.url, sub, tm && tm.text, flagHtml(lead, { size: 18 })].join('|');
  if (el.dataset.k === key && !el.hidden) return;
  el.dataset.k = key;
  const raw = o.image || '';
  const src = cutSrc(lead.url) || (isProductPhoto(raw) ? raw : '');
  const shop = shopOf(lead);
  el.innerHTML = `
    <button type="button" class="vp-pic${src ? '' : ' is-mono'}" data-act="receipt" aria-label="Receipt for ${esc(shop)}" data-mono="${esc((shop || '?')[0].toUpperCase())}">
      ${src ? `<img alt="" decoding="async" src="${esc(src)}" data-fallback="${esc(isProductPhoto(raw) ? raw : '')}">` : ''}
    </button>
    <div class="vp-body">
      <p class="vp-k">The pick</p>
      <p class="vp-shop">${flagHtml(lead, { size: 18, noFi: true })}<span>${esc(shop)}</span></p>
      ${sub ? `<p class="vp-sub">${esc(sub)}</p>` : ''}
      ${tm ? `<p class="vp-trust"><span class="tmark" data-state="${esc(tm.state)}" data-label="${esc(tm.label)}">${esc(tm.text)}</span></p>` : ''}
      <div class="vp-acts">
        <a class="btn primary sm" href="${esc(goHref(lead.url))}" target="_blank" rel="noopener">Open listing</a>
        <button type="button" class="btn sm" data-act="receipt">Receipt</button>
      </div>
    </div>`;
  const img = el.querySelector('.vp-pic img');
  if (img) img.addEventListener('error', () => {
    const fb = img.dataset.fallback;
    if (fb && img.getAttribute('src') !== fb) img.src = fb;
    else { img.remove(); el.querySelector('.vp-pic').classList.add('is-mono'); }
  });
  const mk = pickMonkey();                 // the monkey peeking over the card (kept across re-renders)
  if (mk) el.prepend(mk);
  el.dataset.url = lead.url;
  el.hidden = false;
}

// The headline: the euro figure in its own span, so it can count up from the cheapest tag (600 ms).
function bigParts(lead) {
  const t = lead.tc.true_cost;
  const dom = shopOf(lead);
  if (t.per === 'job') return { n: allIn(lead), fmt: 'job2', rest: ` for one job at ${dom}.` };
  const cw = condWord(lead.offer.condition);
  if (S.mode === 'true') {
    const tail = shipsUnconfirmed(lead) ? ' + shipping.' : shippingUnknown(lead) ? ' all in, if you pick it up.' : ' all in.';
    return { n: allIn(lead), fmt: 'job', rest: `${tail} ${cw ? cw + ', ' : ''}${dom}.` };
  }
  return { n: tagOf(lead), fmt: 'job', rest: ` ${cw ? cw.toLowerCase() + ' ' : ''}at ${dom}.` };
}
function lowestTag() {
  let lo = null;
  for (const it of S.offers.values()) { const t = costed(it) ? tagOf(it) : null; if (t != null && (lo == null || t < lo)) lo = t; }
  return lo;
}
let countRaf = 0;
function setBig(lead) {
  const p = bigParts(lead);
  const num = money(p.n, p.fmt);
  const text = num + p.rest;
  if (els.big.textContent === text && els.big.querySelector('.v-num')) return;
  const prevSig = els.big.dataset.n, sig = num + '|' + S.mode;
  els.big.innerHTML = `<span class="v-num">${esc(num)}</span>${esc(p.rest)}`;
  els.big.dataset.n = sig;
  els.big.classList.remove('lock'); void els.big.offsetWidth; els.big.classList.add('lock');
  // count up once per new figure, from the cheapest tag on the line to what you pay; reduced motion: none
  cancelAnimationFrame(countRaf);
  const from = lowestTag();
  const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || prevSig === sig || (S.mode !== 'true' && p.fmt !== 'job2') || from == null || p.n == null || Math.abs(p.n - from) < 1) return;
  const span = els.big.querySelector('.v-num');
  span.classList.add('counting');
  const t0 = performance.now(), D = 600;
  const step = now => {
    const k = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - k, 3);
    if (k >= 1 || !span.isConnected) { span.classList.remove('counting'); span.removeAttribute('data-n'); return; }
    span.dataset.n = money(from + (p.n - from) * e, p.fmt);
    countRaf = requestAnimationFrame(step);
  };
  span.dataset.n = money(from, p.fmt);
  countRaf = requestAnimationFrame(step);
}

function setStatus(kind, text) {
  els.status.dataset.kind = kind;
  els.status.textContent = text;
}

function setImg(lead) {
  const img = els.img;
  if (!lead) { els.fig.hidden = true; return; }
  const src = cutSrc(lead.url);
  if (img.dataset.url === lead.url) return;
  img.dataset.url = lead.url;
  const raw = (lead.offer && lead.offer.image) || '';
  img.dataset.fallback = isProductPhoto(raw) ? raw : '';
  els.fig.dataset.mono = (lead.offer.source || domainOf(lead.url) || '?')[0].toUpperCase();
  els.fig.classList.remove('is-mono');
  if (!src && !img.dataset.fallback) { els.fig.classList.add('is-mono'); els.fig.hidden = false; return; }
  img.src = src || img.dataset.fallback;
  els.fig.hidden = false;
}

function render() {
  if (!root) return;
  const v = S.verdict;
  const url = leaderUrl();
  const lead = url ? S.offers.get(url) : null;
  const ready = (S.turned || v) && costed(lead);

  if (S.phase === 'start' && !S.need) { root.dataset.state = 'idle'; return; }
  if (override) {
    root.dataset.state = 'final';
    cancelAnimationFrame(countRaf);
    if (els.big.textContent !== override.big) {
      els.big.textContent = override.big; els.big.dataset.n = '';
      els.big.classList.remove('lock'); void els.big.offsetWidth; els.big.classList.add('lock');
    }
    els.small.textContent = override.small || '';
    setFacts([]); setPick(null);
    setStatus('ok', '');
    return;
  }

  if (ready) {
    root.dataset.state = v && v.provisional === false ? 'final' : 'provisional';
    setBig(lead);
    els.small.textContent = '';
    setFacts(factRows(lead));
    setPick(lead);
    setImg(lead);
  } else {
    root.dataset.state = 'hunting';
    const r = S.rank && S.rank.reason;
    cancelAnimationFrame(countRaf);
    // while we read: the leader so far, in the headline's place and size, plainly a tag price (all in comes
    // once shipping and import VAT are costed), so the result lands where this sentence stands
    const ld = !finished && S.leader ? S.offers.get(S.leader) : null;
    const lt = ld ? tagOf(ld) : null;
    if (lt != null) {
      const cw = condWord(ld.offer.condition);
      const txt = `${money(lt, 'job')} on the tag so far. ${cw ? cw + ', ' : ''}${shopOf(ld)}.`;
      if (els.big.textContent !== txt) {
        els.big.innerHTML = `<span class="v-num is-tag">${esc(money(lt, 'job'))}</span> on the tag so far. ${esc(cw ? cw + ', ' : '')}${esc(shopOf(ld))}.`;
        els.big.dataset.n = '';
      }
      els.small.textContent = 'Shipping, import VAT and fees get added next: the answer is what you pay, all in.';
    } else {
      els.big.textContent = ''; els.big.dataset.n = '';
      els.small.textContent = finished ? endNote()
        : r ? captionFromRank(r) : (S.need ? `Looking for ${S.need.thing || S.need.raw || S.q} in every shop we can read.` : '');
    }
    setFacts([]); setPick(null);
    els.fig.hidden = true;
  }

  const st = statusFor(v, finished, S.offers.size);
  setStatus(st[0], st[1]);
}

// the hunt ended without an answer we can stand behind
function endNote() {
  const n = S.offers.size;
  if (!n) return '';                                   // #status says why
  return `Found ${n} offer${n === 1 ? '' : 's'}, none we could cost honestly. They are under "not counted".`;
}

/** The small line over the answer. Once the hunt is over (done, cut, stalled) it never says "checking". */
export function statusFor(v, done, nOffers) {
  if (v && v.provisional === false) return ['ok', ''];
  if (done) {
    if (v && v.provisional) return ['ok', 'checked every shop we had time for'];
    return [nOffers ? 'ok' : 'wait', ''];
  }
  if (v && v.provisional) {
    const n = v.pending_reads | 0;
    return ['wait', n > 0 ? `checking ${n} more shop${n === 1 ? '' : 's'}` : 'checking the last shops'];
  }
  // "hunting…" itself is shown by main.js in #status; this line takes over from the first answer.
  return ['wait', ''];
}

// "used at tori.fi €8/mo takes the lead" → "Used at tori.fi took the lead"
function captionFromRank(reason) {
  const m = /^(\w+) at (\S+)\s.*?(takes the lead|overtook.*)$/i.exec(reason);
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1)} at ${m[2]} took the lead.`;
  return reason[0].toUpperCase() + reason.slice(1);
}

export function mountVerdict(el) {
  root = el;
  el.classList.add('verdict');
  el.dataset.state = 'idle';
  el.innerHTML = `
    <figure class="v-fig" hidden><img alt="" decoding="async"></figure>
    <div class="v-text">
      <p class="v-status" data-kind="wait"></p>
      <h2 class="v-big"></h2>
      <p class="v-small"></p>
      <dl class="v-facts" hidden></dl>
    </div>
    <aside class="v-pick" aria-label="The pick" hidden></aside>`;
  els = {
    fig: el.querySelector('.v-fig'), img: el.querySelector('.v-fig img'),
    status: el.querySelector('.v-status'), big: el.querySelector('.v-big'), small: el.querySelector('.v-small'),
    facts: el.querySelector('.v-facts'), pick: el.querySelector('.v-pick'),
  };
  els.img.addEventListener('error', () => {
    const fb = els.img.dataset.fallback;
    if (fb && els.img.src !== fb && !els.img.src.endsWith(fb)) els.img.src = fb;
    else els.fig.classList.add('is-mono');
  });
  els.fig.addEventListener('click', () => { const u = els.img.dataset.url; if (u) emit('select', u); });
  els.facts.addEventListener('click', e => { const b = e.target.closest('.v-shop'); if (b && b.dataset.url) emit('select', b.dataset.url); });
  els.pick.addEventListener('click', e => { const b = e.target.closest('[data-act="receipt"]'); if (b && els.pick.dataset.url) emit('select', els.pick.dataset.url); });

  on('verdict:override', d => { override = d && d.big ? d : null; render(); });
  on('reset', () => {
    finished = false; override = null; cancelAnimationFrame(countRaf);
    els.big.textContent = ''; els.big.dataset.n = ''; els.small.textContent = '';
    setFacts([]); setPick(null);
    els.img.dataset.url = ''; els.fig.hidden = true; setStatus('wait', ''); el.dataset.state = 'idle';
  });
  for (const t of ['need', 'verdict', 'turn', 'mode', 'recheck']) on(t, render);
  // offers and costs stream in by the hundred: one render per frame is enough
  let vraf = 0;
  const soon = () => { if (!vraf) vraf = requestAnimationFrame(() => { vraf = 0; render(); }); };
  for (const t of ['rank', 'truecost', 'review', 'reviews', 'offer']) on(t, soon);
  on('done', () => { finished = true; render(); });
  on('error', e => { if (e && (e.kind === 'net' || e.kind === '429')) finished = true; render(); });
  render();
}
