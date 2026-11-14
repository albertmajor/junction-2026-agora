// sheet.js (B3): the listing, opened big. A centered dialog on a dimmed page (a bottom sheet on phones):
// the photo on the left, on the right what it is, what you pay all in (the receipt), why, the seller, the details.
// ← / → step through the list in its current order. Every receipt line opens to its source.
import { S, on, emit, eur, cutSrc, goHref, domainOf, isSetAside, allIn, netAfterResale, shippingUnknown, shipsUnconfirmed, beatAllIn, pickUrl, reviewFor, trustMark, fmtCount,
  isRisky, riskWhy, isUnsure, unsureWhy } from './core.js';
import { flagHtml, originFor, basisWords, countryName } from './flags.js';

let root, panel, body, foot, navEl, lastFocus = null, openUrl = null, hideT = 0;
let line = null, ledger = null;
import('./line.js').then(m => { line = m.line || null; }).catch(() => {});
import('./ledger.js').then(m => { ledger = m; }).catch(() => {});

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const m2 = n => eur(n, { dp: 2 });

const COND = { new: 'new', refurbished: 'refurbished', used: 'used', rental: 'rental', service: 'service' };
function condWord(c) {
  const k = String(c || '').toLowerCase();
  for (const key of Object.keys(COND)) if (k.startsWith(key.slice(0, 4))) return COND[key];
  return k;
}

function lineLabel(label, i, tc) {
  const l = String(label);
  if (i === 0 && /^sticker$/i.test(l)) return tc.per === 'job' ? 'Price' : 'Price on the tag';
  const m = /^resale in (\d+) mo/i.exec(l);
  if (m) return +m[1] === 12 ? 'Back when you sell it in a year' : `Back when you sell it in ${m[1]} months`;
  return l[0].toUpperCase() + l.slice(1);
}

// Whole euros for the tag and the resale estimate (cents on an estimate are not believable).
function rowVal(label, val, i, isResale) {
  const whole = (i === 0 && val >= 100) || isResale;
  const f = n => whole ? eur(Math.round(n), { dp: 0 }) : m2(n);
  return (isResale ? '≈ ' : '') + (val < 0 ? '−' + f(-val) : f(val));
}

function when(ts) {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return 'read just now';
  if (s < 3600) return `read ${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `read ${Math.round(s / 3600)} h ago`;
  const d = new Date(ts * 1000);
  return 'read ' + d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function viaWord(v) {
  return ({ contextdev_product: 'product page', contextdev_json: 'page read', jsonld: 'page data (free read)', direct: 'page data (free read)', 'used comps': 'used listings', rule: 'tax rule' })[v] || (v ? String(v).replace(/_/g, ' ') : '');
}

// Depreciation sparkline: median used price by model year; this model gets the dot.
function spark(dep, model) {
  const pts = (dep && dep.points || []).filter(p => p.median_eur != null && p.year != null).sort((a, b) => a.year - b.year);
  if (pts.length < 2) return '';
  const W = 220, H = 50, P = 6, LB = 12;
  const xs = pts.map(p => p.year), ys = pts.map(p => p.median_eur);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = x => P + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - 2 * P);
  const Y = y => H - LB - 3 - (y1 === y0 ? 0.5 : (y - y0) / (y1 - y0)) * (H - LB - 3 - P);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.year).toFixed(1)},${Y(p.median_eur).toFixed(1)}`).join(' ');
  const cur = pts.find(p => model && p.model === model) || pts[Math.floor(pts.length / 2)];
  const labels = pts.map(p => `<text x="${X(p.year).toFixed(1)}" y="${H - 0.5}" text-anchor="${p === pts[0] ? 'start' : p === pts[pts.length - 1] ? 'end' : 'middle'}">${esc(p.year)}</text>`).join('');
  const rate = dep.rate != null ? `${Math.round(dep.rate * 100)}% a year` : '';
  const desc = pts.map(p => `${p.model} (${p.year}) ${eur(p.median_eur, { dp: 0 })} used`).join(', ');
  return `<figure class="spark">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc('Used prices by model year: ' + desc)}">
      <path d="${d}" />
      ${pts.map(p => `<circle class="${p === cur ? 'cur' : ''}" cx="${X(p.year).toFixed(1)}" cy="${Y(p.median_eur).toFixed(1)}" r="${p === cur ? 3.2 : 2}"/>`).join('')}
      ${labels}
    </svg>
    <figcaption>${esc(pts.map(p => `${p.model.replace(dep.family ? new RegExp('^' + dep.family + '\\s*', 'i') : /^$/, '') || p.model} ${eur(p.median_eur, { dp: 0 })}`).join(' · '))}${rate ? ` · loses about ${esc(rate)}` : ''}${dep.source === 'measured' ? ', measured' : ''}</figcaption>
  </figure>`;
}

function evidenceHtml(ev, label) {
  if (ev && ev.via === 'rule' && String(ev.quote || '').trim().toLowerCase() === String(label || '').trim().toLowerCase())
    return `<p class="ev-none">A rule we apply (an estimate), not a quote from the page.</p>`;
  if (!ev) return `<p class="ev-none">No page quote for this line. It is our estimate; the basis is below.</p>`;
  const urls = ev.urls && ev.urls.length ? ev.urls : (ev.url ? [ev.url] : []);
  const doms = [...new Set(urls.map(domainOf).filter(Boolean))];
  const meta = [viaWord(ev.via), doms.length > 1 ? `${doms.length} shops: ${doms.join(', ')}` : doms[0], when(ev.fetched_at)].filter(Boolean).join(' · ');
  return `<blockquote>${esc(ev.quote || '')}</blockquote><p class="ev-meta">${esc(meta)}</p>`;
}

// the shop's reviews: label, one plain sentence, red flags, sources with links, and why stars are not taken at face value
function reviewHtml(it) {
  const tm = trustMark(it);
  if (!tm) return '';
  const r = reviewFor(it) || {};
  const mark = `<span class="tmark" data-state="${esc(tm.state)}" data-label="${esc(tm.label)}">${esc(tm.text)}</span>`;
  if (tm.state === 'checking') return `<section class="rev" aria-live="polite"><h3 class="rev-h">Seller reviews ${mark}</h3></section>`;
  const httpUrl = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '';
  const src = (r.sources || []).filter(x => x && x.name).map(x => {
    const u = httpUrl(x.url);
    const name = u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(x.name)}</a>` : esc(x.name);
    const bits = [x.rating != null ? `${Number(x.rating).toFixed(1)}★` : '', x.count ? `${fmtCount(x.count)} reviews` : '', x.mood || '', x.via && x.via !== 'page' ? x.via : ''].filter(Boolean);
    return `<li>${name}${bits.length ? ' <span>' + esc(bits.join(' · ')) + '</span>' : ''}</li>`;
  }).join('');
  const red = (r.red_flags || []).length ? `<ul class="rev-red">${r.red_flags.map(f => `<li><span class="dot" aria-hidden="true"></span>${esc(f)}</li>`).join('')}</ul>` : '';
  const when = r.cached && r.checked_at ? ` Checked ${esc(new Date(r.checked_at * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }))}.` : '';
  const bias = r.bias_note ? `<details class="fold"><summary>Why we do not take the stars at face value</summary><p class="basis">${esc(r.bias_note)}${r.baseline ? ` A normal shop scores about ${esc(Number(r.baseline).toFixed(1))}★ on ${esc((r.sources && r.sources[0] && r.sources[0].name) || 'that site')}.` : ''}${r.adjusted_score != null ? ` Adjusted score: ${Math.round(r.adjusted_score * 100)} / 100.` : ''}${when}</p></details>` : '';
  return `<section class="rev" data-label="${esc(tm.label)}">
      <h3 class="rev-h">Seller reviews ${mark}</h3>
      ${r.summary ? `<p class="rev-sum">${esc(r.summary)}</p>` : ''}
      ${red}
      ${src ? `<ul class="rev-src">${src}</ul>` : ''}
      ${bias}
    </section>`;
}

function flagTone(f) {
  if (/too good|disagrees|scam|copied|stock photo|looks like|days old|inflated|does not ship|grey import|out of stock|not costed|red flags/i.test(f)) return 'warn';
  return 'info';
}
function flagText(f) {
  return String(f).replace(/^outside the EU \((\w+)\): /, 'outside the EU, priced in $1: ');
}

function render(url) {
  const it = S.offers.get(url);
  if (!it) return false;
  const o = it.offer || {};
  const tc = it.tc || {};
  const t = tc.true_cost || null;
  const dom = o.source || domainOf(url);
  const org = originFor(it);
  const cc = org && org.country_code ? String(org.country_code).toUpperCase() : '';
  const cname = cc ? (org.country_name || countryName(cc)) : '';
  const cond = condWord(o.condition);
  const evs = tc.evidence || [];
  const evAt = i => evs.find(e => e.line_index === i);
  const per = t ? t.per : (S.unit === 'job' ? 'job' : 'month');
  const aside = isSetAside(it);

  // the receipt adds up to what you pay, once: tag + shipping + import VAT + fees. Resale is an option below.
  const isResaleL = (label, val, i) => /^resale/i.test(String(label)) || (i > 0 && val < 0 && /resale|sell/i.test(String(label)));
  const rowHtml = (label, val, i, isResale) => {
    const id = `rc-${i}`;
    return `<li class="rline${isResale ? ' resale' : ''}">
        <button type="button" class="rbtn" aria-expanded="false" aria-controls="${id}">
          <span class="rl">${esc(lineLabel(label, i, t))}</span><span class="rv">${rowVal(label, val, i, isResale)}</span><span class="chev" aria-hidden="true"></span>
        </button>
        ${isResale ? spark(S.depreciation, S.depreciation && S.depreciation.model) : ''}
        <div class="ev" id="${id}" hidden>${evidenceHtml(evAt(i), label)}</div>
      </li>`;
  };
  let rows = '', resaleRow = '';
  if (t && Array.isArray(t.receipt)) {
    rows = t.receipt.map(([label, val], i) => {
      if (isResaleL(label, val, i)) { resaleRow += rowHtml(label, val, i, true); return ''; }
      return rowHtml(label, val, i, false);
    }).join('');
    const noShip = [].concat(tc.flags || []).some(f => /does not ship/i.test(String(f)));
    if (per !== 'job' && noShip) rows += `<li class="rline"><div class="rbtn static"><span class="rl">Shipping to Finland</span><span class="rv muted">not offered</span></div></li>`;
    else if (per !== 'job' && shipsUnconfirmed(it)) rows += `<li class="rline"><div class="rbtn static"><span class="rl">Shipping to Finland</span><span class="rv muted">not confirmed</span></div></li>`;
    else if (per !== 'job' && shippingUnknown(it)) rows += `<li class="rline"><div class="rbtn static"><span class="rl">Shipping</span><span class="rv muted">not listed</span></div></li>`;
  } else {
    rows = `<li class="rline"><div class="rbtn static"><span class="rl">Price on the tag</span><span class="rv">${o.price_eur != null ? m2(o.price_eur) : '€–'}</span></div></li>`;
  }

  let total = '';
  const all = allIn(it);
  if (t && all != null) {
    if (per === 'job') total = `<p class="total">You pay<br><b>${m2(all)} for one job</b></p>`;
    else total = `<p class="total">You pay, all in<br><b>${all >= 100 ? eur(Math.round(all), { dp: 0 }) : m2(all)}${shipsUnconfirmed(it) ? ' + shipping' : ''}</b></p>`;
    const conf = t.confidence ? t.confidence + ' confidence' + (per !== 'job' && shippingUnknown(it) ? ', if picked up or shipped free' : '') : '';
    total += `<p class="conf">${esc(conf)}</p>`;
  } else {
    total = `<p class="total muted">Not costed</p><p class="conf">${aside ? 'Set aside: the price does not add up, so we did not rank it.' : 'Waiting for shipping and import costs on this one.'}</p>`;
  }
  // the old "true cost" survives as an option: what it costs you net if you sell it on after a while
  const net = netAfterResale(it);
  let resaleOpt = '';
  if (net != null && per !== 'job') {
    const mo = t.months || 12;
    const span = mo === 12 ? 'a year' : `${mo} months`;
    const pm = t.per_month_eur;
    resaleOpt = `<details class="fold resale-opt"><summary>If you resell it after ${span}: about ${eur(Math.round(net), { dp: 0 })} net</summary>
      <ol class="receipt">${resaleRow}</ol>
      <p class="basis">You pay ${eur(Math.round(all), { dp: 0 })} now and get about ${eur(Math.round(t.resale_eur), { dp: 0 })} back when you sell it${pm != null && isFinite(pm) ? `, about ${eur(pm, { dp: 2 })} a month while you own it` : ''}. An estimate from used prices today.</p></details>`;
  }

  const flags = (tc.flags || o.flags || []).filter(Boolean);
  const flagsHtml = flags.length ? `<ul class="flags">${flags.map(f => `<li data-tone="${flagTone(f)}"><span class="dot" aria-hidden="true"></span>${esc(flagText(f))}</li>`).join('')}</ul>` : '';

  const band = (t && t.band) || tc.band;
  const bandHtml = band && band.label ? `<span class="band">${esc(eur(o.price_eur, { dp: 0 }))} is ${esc(band.label)} for ${esc(band.what || cond)}${band.p25 != null ? ` · usual ${eur(band.p25, { dp: 0 })}–${eur(band.p75, { dp: 0 })}` : ''}</span>` : '';

  const folds = [];
  if (tc.haggle) {
    const h = tc.haggle;
    folds.push(`<details class="fold"><summary>Haggle: offer ${eur(h.suggested_offer_eur, { dp: 0 })}, fair ${eur(h.fair_low_eur, { dp: 0 })}–${eur(h.fair_high_eur, { dp: 0 })}</summary>
      <blockquote class="msg">${esc(h.message)}</blockquote>
      <button type="button" class="ghost copy" data-copy="${esc(h.message)}">Copy message</button></details>`);
  }
  if (tc.coupons && tc.coupons.length) {
    folds.push(`<details class="fold"><summary>${tc.coupons.length === 1 ? '1 code' : tc.coupons.length + ' codes'} seen on the page, not checked</summary>
      <ul class="coupons">${tc.coupons.map(c => `<li><code>${esc(c.code)}</code> ${c.percent ? esc(c.percent + '% off') : c.amount ? esc(c.amount + ' ' + (c.currency || '')) : ''}<span>${esc((c.text || '').slice(0, 140))}</span></li>`).join('')}</ul></details>`);
  }
  if (t && t.basis) folds.push(`<details class="fold"><summary>How this was worked out</summary><p class="basis">${esc(t.basis)}</p></details>`);

  // ranked all in: the tag at which this one would cost you less than the pick
  const bw = aside ? null : beatAllIn(it);
  const beat = bw ? bw.beat : null;
  const isLead = (pickUrl() || S.leader) === url;
  let beatNote = '';
  if (beat != null && !isLead && bw.gap > 0) beatNote = `<p class="beat">It would win at ${eur(beat, { dp: 0 })} on the tag, ${eur(bw.gap, { dp: 0 })} less than today.</p>`;
  else if (beat != null && !isLead && bw.gap === 0) beatNote = `<p class="beat">Cheaper all in, but we cannot say you can surely buy it at this price.</p>`;
  else if (isLead) beatNote = `<p class="beat lead">This is the one we would buy: the lowest all-in price we can be sure of${per === 'job' ? '' : ' (it ships to Finland, or you can pick it up)'}.</p>`;
  else if (beat == null && t && !aside) beatNote = `<p class="beat">It cannot win at any price today.</p>`;
  // the pick is watched at its own tag price; any other offer at the price where it would win
  const watchAt = isLead && o.price_eur != null && isFinite(o.price_eur) ? Math.round(o.price_eur) : (beat != null && isFinite(beat) && bw.gap > 0 ? Math.round(beat) : null);

  // where it ships from, and whether it ships to you: from the engine's origin (or our marked guess)
  const isJob = per === 'job';
  const fromVal = cc
    ? `<span class="s-from">${flagHtml(it, { size: 18, origin: org })}<span>${esc(cname)}${org.city ? ' — ' + esc(org.city) : ''}</span></span>
       ${basisWords(org) ? `<span class="s-basis">${esc(basisWords(org))}</span>` : ''}`
    : '<span class="muted">not stated</span>';
  const fi = org ? org.ships_to_fi : null;
  const originHtml = `<dl class="s-origin">
      <div><dt>${isJob ? 'Based in' : 'Ships from'}</dt><dd>${fromVal}</dd></div>
      ${isJob ? '' : `<div><dt>Ships to Finland</dt><dd class="${fi === false ? 'no' : fi === true ? 'yes' : 'muted'}">${esc((org && org.ships_text) || 'not stated')}</dd></div>`}
    </dl>`;

  // why: what makes it stand out (the list's own reasons), whether it can win, what holds it back
  const hl = highlightWhy(url);
  const risky = !!(it.tc && isRisky(it));
  const unsure = !risky && isUnsure(it) ? unsureWhy(it) : '';
  const holdBack = risky ? `<p class="m-hold" data-tone="warn"><b>${aside ? 'Set aside' : 'Risky'}:</b> ${esc(riskWhy(it))}.${aside ? ' It is not ranked.' : ''}</p>`
    : unsure ? `<p class="m-hold"><b>Not the pick:</b> ${esc(/[.?!]$/.test(unsure) ? unsure : unsure + '.')}</p>` : '';
  const whyBody = (hl.length ? `<ul class="m-chips">${hl.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '') + holdBack + beatNote + flagsHtml;
  const whyHtml = whyBody ? `<section class="m-sec m-why" aria-labelledby="m-why-h"><h3 class="m-h" id="m-why-h">Why</h3>${whyBody}</section>` : '';

  const details = resaleOpt + reviewHtml(it) + folds.join('');
  const pics = gallery(it);
  const img = pics[0] || '';
  const mono = (dom || '?')[0].toUpperCase();
  const thumbs = pics.length > 1 ? `<div class="m-thumbs" role="group" aria-label="Photos">${pics.map((p, i) =>
    `<button type="button" class="m-thumb" data-src="${esc(p)}" aria-label="Photo ${i + 1} of ${pics.length}" aria-pressed="${i === 0}"><img alt="" src="${esc(p)}" loading="lazy" decoding="async" referrerpolicy="no-referrer"></button>`).join('')}</div>` : '';
  const condHtml = cond ? `<span class="m-cond" data-c="${esc(cond)}">${esc(cond)}</span>` : '';
  const tm = trustMark(it);
  const trustHtml = tm ? `<span class="tmark" data-state="${esc(tm.state)}" data-label="${esc(tm.label)}">${esc(tm.text)}</span>` : '';
  body.innerHTML = `
    <div class="m-grid">
      <div class="m-media">
        <figure class="stage${img ? '' : ' is-mono'}" data-mono="${esc(mono)}" data-url="${esc(url)}">
          ${img ? `<img alt="${esc(o.title || dom)}" src="${esc(img)}" data-fallback="${esc(o.image || '')}" decoding="async">` : ''}
        </figure>
        ${thumbs}
      </div>
      <div class="m-info">
        <h2 class="s-title" id="sheet-title">${esc(o.title || dom)}</h2>
        <p class="s-meta">${flagHtml(it, { size: 14, origin: org, noFi: true, unknown: true })}<span>${esc([cname, org && org.city, dom].filter(Boolean).join(' · '))}</span>${trustHtml ? `<span class="m-dot" aria-hidden="true">·</span>${trustHtml}` : ''}</p>
        <p class="m-sub">${condHtml}${o.unit ? `<span>priced per ${esc(o.unit)}</span>` : ''}${bandHtml}</p>
        <section class="m-price" aria-label="What you pay">
          <div class="sum">${total}</div>
          <ol class="receipt">${rows}</ol>
        </section>
        ${whyHtml}
        ${originHtml}
        ${details ? `<section class="m-sec s-details" aria-labelledby="m-det-h"><h3 class="m-h s-dh" id="m-det-h">Details</h3>${details}</section>` : ''}
        <p class="aff">We may earn a fee if you buy. It never changes the order.</p>
      </div>
    </div>`;
  foot.innerHTML = `
      <a class="btn primary" href="${esc(goHref(url))}" target="_blank" rel="noopener">Open listing <span aria-hidden="true">↗</span></a>
      ${watchAt != null ? `<button type="button" class="btn watch" data-beat="${watchAt}">Watch at ${eur(watchAt, { dp: 0 })}</button>` : ''}
      <button type="button" class="btn ghost-btn share" data-share>Share</button>`;
  panel.dataset.url = url;
  navState();

  const im = body.querySelector('.stage img');
  if (im) im.addEventListener('error', () => {
    const fb = im.dataset.fallback;
    if (fb && im.getAttribute('src') !== fb) im.src = fb;
    else { im.remove(); body.querySelector('.stage').classList.add('is-mono'); }
  });
  for (const t of body.querySelectorAll('.m-thumb img')) t.addEventListener('error', () => t.closest('.m-thumb').remove(), { once: true });
  return true;
}

// ---------- photos ----------
/** The offer's photos: the main one first, then any extra ones the listing gave (deduped, at most 8). */
export function gallery(it) {
  const o = (it && it.offer) || {};
  const main = cutSrc(it) || o.image || '';
  const pick = x => typeof x === 'string' ? x : (x && (x.url || x.src)) || '';
  const extra = [].concat(o.images || [], o.gallery || [], o.photos || []).map(pick)
    .filter(u => /^(https?:)?\/\//i.test(u) || u.startsWith('/'));
  return [...new Set([main, ...extra].filter(Boolean))].slice(0, 8);
}

// ---------- the list order (← / →) ----------
/** The listing urls in the order the list shows them: main, also in the EU, still costing, set aside. */
export function listOrder() {
  try {
    if (ledger && ledger.groups) {
      const g = ledger.groups();
      return [].concat(g.main, g.eu, g.costing, g.risky).map(it => it.url);
    }
  } catch {}
  return [...S.offers.values()].filter(it => allIn(it) != null || (it.offer && it.offer.price_eur != null))
    .sort((a, b) => (allIn(a) ?? Infinity) - (allIn(b) ?? Infinity)).map(it => it.url);
}
function neighbours(url) {
  const ord = listOrder();
  const i = ord.indexOf(url);
  return { i, n: ord.length, prev: i > 0 ? ord[i - 1] : null, next: i >= 0 && i < ord.length - 1 ? ord[i + 1] : null };
}
/** The list's own reasons for this one ("cheapest all-in", "cheapest new", …), or []. */
function highlightWhy(url) {
  try { const h = ledger && ledger.highlights ? ledger.highlights().find(x => x.it.url === url) : null; return h ? h.why : []; }
  catch { return []; }
}
function navState() {
  if (!navEl || !openUrl) return;
  const nb = neighbours(openUrl);
  const [pv, nx] = navEl.querySelectorAll('.m-step');
  pv.disabled = !nb.prev; nx.disabled = !nb.next;
  pv.dataset.url = nb.prev || ''; nx.dataset.url = nb.next || '';
  navEl.querySelector('.m-count').textContent = nb.i >= 0 && nb.n > 1 ? `${nb.i + 1} of ${nb.n}` : '';
}
function step(dir) {
  if (!openUrl) return;
  const nb = neighbours(openUrl);
  const to = dir < 0 ? nb.prev : nb.next;
  if (to) emit('select', to);   // the line moves its notch too; openSheet re-renders in place
}

function focusables() {
  return [...panel.querySelectorAll('a[href],button:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')].filter(e => e.offsetParent !== null || e === document.activeElement);
}
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

export function openSheet(url) {
  if (!root || !url) return;
  const was = openUrl;
  openUrl = url;
  if (!render(url)) { openUrl = was; return; }
  clearTimeout(hideT);
  if (!was) {
    lastFocus = document.activeElement;
    const sbw = innerWidth - document.documentElement.clientWidth;
    document.documentElement.style.setProperty('--sbw', Math.max(0, sbw) + 'px');
    root.hidden = false;
    root.setAttribute('aria-hidden', 'false');
    document.documentElement.classList.add('sheet-open');
    void root.offsetWidth;   // start the scale/fade from the closed state
    requestAnimationFrame(() => { root.classList.add('open'); });
    setTimeout(() => { const f = panel.querySelector('.close'); f && f.focus({ preventScroll: true }); }, 30);
  } else if (was !== url) {
    // stepped: keep the focus on whatever stepped (or the dialog), show the new one from the top
    if (!panel.contains(document.activeElement)) panel.focus({ preventScroll: true });
    if (!reduced()) { panel.classList.remove('stepped'); void panel.offsetWidth; panel.classList.add('stepped'); }
  }
  if (was !== url) body.scrollTop = 0;
  const it = S.offers.get(url);
  const lead = (pickUrl() || S.leader) === url;
  const bw = it && !isSetAside(it) ? beatAllIn(it) : null;
  try { line && line.ghostNotch && line.ghostNotch(lead || !bw || !(bw.gap > 0) ? null : bw.beat); } catch {}
}

function returnFocus(url) {
  let t = lastFocus && document.contains(lastFocus) ? lastFocus : null;
  if (!t && url) {
    const q = CSS.escape(url);
    t = document.querySelector(`.lg-r[data-url="${q}"], .lg-hc[data-url="${q}"], .ln-o[data-key="${q}"] button, .ln-o[data-key="${q}"]`);
  }
  if (t && t.focus) t.focus({ preventScroll: true });
}

export function closeSheet() {
  if (!root || !openUrl) return;
  const url = openUrl;
  openUrl = null;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
  try { line && line.ghostNotch && line.ghostNotch(null); } catch {}
  const done = () => {
    if (openUrl) return;
    root.hidden = true;
    document.documentElement.classList.remove('sheet-open');
    document.documentElement.style.removeProperty('--sbw');
  };
  clearTimeout(hideT);
  hideT = setTimeout(done, reduced() ? 0 : 220);
  returnFocus(url);
}

async function share(btn) {
  const it = openUrl && S.offers.get(openUrl);
  if (!it) return;
  const o = it.offer || {};
  const a = allIn(it);
  const text = `${o.title || domainOf(it.url)}${a != null ? ` · ${eur(Math.round(a), { dp: 0 })} all in` : ''}`;
  const link = it.url;
  const say = w => { const t = btn.textContent; btn.textContent = w; setTimeout(() => { btn.textContent = t; }, 1400); };
  try {
    if (navigator.share && matchMedia('(pointer: coarse)').matches) { await navigator.share({ title: o.title || '', text, url: link }); return; }
    await navigator.clipboard.writeText(`${text}\n${link}`);
    say('Link copied');
  } catch (e) { if (!e || e.name !== 'AbortError') say('Could not copy'); }
}

export function mountSheet(el) {
  root = el;
  el.classList.add('sheet');
  el.hidden = true;
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `<div class="backdrop" data-close></div>
    <div class="m-wrap" data-close>
      <div class="panel paper" role="dialog" aria-modal="true" aria-labelledby="sheet-title" tabindex="-1">
        <div class="grab" aria-hidden="true"></div>
        <div class="s-bar">
          <div class="m-nav" role="group" aria-label="Step through the list">
            <button type="button" class="m-step" data-dir="-1" aria-label="Previous listing" title="Previous (←)"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5L5.5 8l4.5 4.5"/></svg></button>
            <span class="m-count" aria-live="polite"></span>
            <button type="button" class="m-step" data-dir="1" aria-label="Next listing" title="Next (→)"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5"/></svg></button>
          </div>
          <button type="button" class="close" data-close aria-label="Close listing"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg></button>
        </div>
        <div class="body"></div>
        <div class="acts m-foot"></div>
      </div>
    </div>`;
  panel = el.querySelector('.panel');
  body = el.querySelector('.body');
  foot = el.querySelector('.m-foot');
  navEl = el.querySelector('.m-nav');

  el.addEventListener('click', e => {
    // the empty space around the card closes it; clicks inside the card never do (only its close button)
    const c0 = e.target.closest('[data-close]');
    if (c0 && (c0.classList.contains('close') || e.target === c0)) { closeSheet(); return; }
    const st = e.target.closest('.m-step');
    if (st) { step(Number(st.dataset.dir)); return; }
    const th = e.target.closest('.m-thumb');
    if (th) {
      const im = body.querySelector('.stage img');
      if (im) { im.src = th.dataset.src; im.dataset.fallback = th.dataset.src; }
      for (const b of body.querySelectorAll('.m-thumb')) b.setAttribute('aria-pressed', String(b === th));
      return;
    }
    const b = e.target.closest('.rbtn');
    if (b && b.tagName === 'BUTTON') {
      const ev = document.getElementById(b.getAttribute('aria-controls'));
      const open = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', String(open));
      if (ev) ev.hidden = !open;
      return;
    }
    const w = e.target.closest('.watch');
    if (w) {
      if (w.classList.contains('is-set')) return;
      const v = Number(w.dataset.beat), u = openUrl;
      // say it on the button first, then hand the price to the tag on the line
      w.classList.add('is-set');
      w.setAttribute('aria-live', 'polite');
      w.textContent = `Watching at ${eur(v, { dp: 0 })} ✓`;
      setTimeout(() => {
        if (openUrl === u) closeSheet();
        emit('tag', { eur: v, from: 'sheet', url: u });
      }, 600);
      return;
    }
    const sh = e.target.closest('[data-share]');
    if (sh) { share(sh); return; }
    const c = e.target.closest('.copy');
    if (c) {
      navigator.clipboard && navigator.clipboard.writeText(c.dataset.copy).then(() => {
        const t = c.textContent; c.textContent = 'Copied'; setTimeout(() => { c.textContent = t; }, 1400);
      }).catch(() => {});
    }
  });

  document.addEventListener('keydown', e => {
    if (!openUrl) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSheet(); return; }
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !typing && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      e.preventDefault(); e.stopPropagation(); step(e.key === 'ArrowLeft' ? -1 : 1); return;
    }
    if (e.key === '/' && !typing) { e.stopPropagation(); return; }   // the search box sits under the dimmed page
    if (e.key === 'Tab') {
      const f = focusables();
      if (!f.length) { e.preventDefault(); panel.focus(); return; }
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement) || document.activeElement === panel)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  }, true);
  // focus never wanders behind the dialog (a click on the dimmed page, a screen reader's virtual cursor)
  document.addEventListener('focusin', e => {
    if (openUrl && !panel.contains(e.target) && !e.target.closest('.flag-tip')) panel.focus({ preventScroll: true });
  });

  // Phones: swipe the sheet down to close it.
  let y0 = null;
  panel.addEventListener('touchstart', e => { if (body.scrollTop <= 0 && matchMedia('(max-width: 640px)').matches) y0 = e.touches[0].clientY; }, { passive: true });
  panel.addEventListener('touchmove', e => {
    if (y0 == null) return;
    const dy = e.touches[0].clientY - y0;
    if (dy > 0) panel.style.transform = `translateY(${dy}px)`;
  }, { passive: true });
  panel.addEventListener('touchend', e => {
    if (y0 == null) return;
    const dy = (e.changedTouches[0].clientY - y0);
    panel.style.transform = ''; y0 = null;
    if (dy > 110) closeSheet();
  });

  on('select', d => openSheet(typeof d === 'string' ? d : d && d.url));
  on('reset', () => closeSheet());
  // the list changes under an open dialog: re-render in place (keeps the scroll position and open receipt lines)
  const rerender = () => {
    if (!openUrl) return;
    const y = body.scrollTop;
    const openRows = [...body.querySelectorAll('.rbtn[aria-expanded="true"]')].map(b => b.getAttribute('aria-controls'));
    const openFolds = [...body.querySelectorAll('details[open] > summary')].map(s => s.textContent);
    if (!render(openUrl)) return;
    for (const id of openRows) { const b = body.querySelector(`.rbtn[aria-controls="${id}"]`); const ev = document.getElementById(id); if (b && ev) { b.setAttribute('aria-expanded', 'true'); ev.hidden = false; } }
    for (const s of body.querySelectorAll('details > summary')) if (openFolds.includes(s.textContent)) s.parentElement.open = true;
    body.scrollTop = y;
  };
  on('truecost', item => { if (openUrl && item && item.url === openUrl) rerender(); });
  on('review', d => { const it = openUrl && S.offers.get(openUrl); if (it && reviewFor(it) === d) rerender(); });
  on('reviews', () => { const it = openUrl && S.offers.get(openUrl); const tm = it && trustMark(it);
    if (it && (!tm || tm.state !== 'done')) rerender(); });
  // a photo arrives later (imagefill swaps the big one in place): keep the first thumbnail in step
  on('image', d => {
    if (!openUrl || !d || d.url !== openUrl) return;
    const th = body.querySelector('.m-thumb');
    if (th) { th.dataset.src = d.image; const i = th.querySelector('img'); if (i) i.src = d.image; }
    const stg = body.querySelector('.stage');
    if (stg && !stg.querySelector('img')) rerender();
  });
  for (const t of ['offer', 'offer-removed', 'rank', 'verdict']) on(t, () => { if (openUrl) navState(); });
  on('agent', () => closeSheet());
}
