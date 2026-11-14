// sheet.js (B3): the receipt for one object on the line, where it ships from, and the details under it.
// Right sheet on desktop, bottom sheet on mobile. Every line opens to its source.
import { S, on, emit, eur, cutSrc, goHref, domainOf, isSetAside, allIn, netAfterResale, shippingUnknown, shipsUnconfirmed, beatAllIn, pickUrl, reviewFor, trustMark, fmtCount } from './core.js';
import { flagHtml, originFor, basisWords, countryName } from './flags.js';

let root, panel, body, lastFocus = null, openUrl = null;
let line = null;
import('./line.js').then(m => { line = m.line || null; }).catch(() => {});

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
    total += `<p class="conf">${esc(t.confidence ? t.confidence + ' confidence' : '')}</p>`;
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
  const bandHtml = band && band.label ? `<p class="band">${esc(eur(o.price_eur, { dp: 0 }))} is ${esc(band.label)} for ${esc(band.what || cond)}${band.p25 != null ? ` · usual ${eur(band.p25, { dp: 0 })}–${eur(band.p75, { dp: 0 })}` : ''}</p>` : '';

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
  else if (isLead) beatNote = `<p class="beat lead">This is the one we would buy: the lowest price all in.</p>`;
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

  const details = resaleOpt + reviewHtml(it) + folds.join('');
  const img = cutSrc(url);
  const mono = (dom || '?')[0].toUpperCase();
  body.innerHTML = `
    <div class="paper-wrap"><article class="paper">
      <figure class="stage${img || o.image ? '' : ' is-mono'}" data-mono="${esc(mono)}">
        ${img || o.image ? `<img alt="${esc(o.title || dom)}" src="${esc(img || o.image)}" data-fallback="${esc(o.image || '')}" decoding="async">` : ''}
      </figure>
      <h2 class="s-title" id="sheet-title">${esc(o.title || dom)}</h2>
      <p class="s-meta">${cc ? flagHtml(it, { size: 14, origin: org, noFi: true }) : ''}<span>${esc([cname, org && org.city, dom, cond].filter(Boolean).join(' · '))}${o.unit ? ` · priced per ${esc(o.unit)}` : ''}</span></p>
      ${bandHtml}
      <ol class="receipt">${rows}</ol>
      <div class="sum">${total}</div>
      ${originHtml}
      ${flagsHtml}
      ${beatNote}
      ${details ? `<section class="s-details" aria-label="Details"><h3 class="s-dh">Details</h3>${details}</section>` : ''}
      <div class="acts">
        <a class="btn primary" href="${esc(goHref(url))}" target="_blank" rel="noopener">Open listing</a>
        ${watchAt != null ? `<button type="button" class="btn watch" data-beat="${watchAt}">Watch at ${eur(watchAt, { dp: 0 })}</button>` : ''}
      </div>
      <p class="aff">We may earn a fee if you buy. It never changes the order.</p>
    </article></div>`;

  const im = body.querySelector('.stage img');
  if (im) im.addEventListener('error', () => {
    const fb = im.dataset.fallback;
    if (fb && im.getAttribute('src') !== fb) im.src = fb;
    else { im.remove(); body.querySelector('.stage').classList.add('is-mono'); }
  });
  return true;
}

function focusables() {
  return [...panel.querySelectorAll('a[href],button:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')].filter(e => e.offsetParent !== null || e === document.activeElement);
}

export function openSheet(url) {
  if (!root || !url) return;
  if (!render(url)) return;
  if (!openUrl) lastFocus = document.activeElement;
  openUrl = url;
  root.hidden = false;
  root.setAttribute('aria-hidden', 'false');
  document.documentElement.classList.add('sheet-open');
  requestAnimationFrame(() => { root.classList.add('open'); });
  body.scrollTop = 0;
  const it = S.offers.get(url);
  const lead = (pickUrl() || S.leader) === url;
  const bw = it && !isSetAside(it) ? beatAllIn(it) : null;
  try { line && line.ghostNotch && line.ghostNotch(lead || !bw || !(bw.gap > 0) ? null : bw.beat); } catch {}
  setTimeout(() => { const f = panel.querySelector('.close'); f && f.focus({ preventScroll: true }); }, 30);
}

export function closeSheet() {
  if (!root || !openUrl) return;
  openUrl = null;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
  document.documentElement.classList.remove('sheet-open');
  try { line && line.ghostNotch && line.ghostNotch(null); } catch {}
  const done = () => { if (!openUrl) root.hidden = true; };
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  setTimeout(done, reduce ? 0 : 320);
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}

export function mountSheet(el) {
  root = el;
  el.classList.add('sheet');
  el.hidden = true;
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `<div class="backdrop" data-close></div>
    <div class="panel" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
      <div class="grab" aria-hidden="true"></div>
      <div class="s-bar"><span class="s-bar-k">Receipt</span>
        <button type="button" class="close" data-close aria-label="Close receipt"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg></button></div>
      <div class="body"></div>
    </div>`;
  panel = el.querySelector('.panel');
  body = el.querySelector('.body');

  el.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) { closeSheet(); return; }
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
    if (e.key === 'Tab') {
      const f = focusables();
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  }, true);

  // Swipe down to close on mobile.
  let y0 = null;
  panel.addEventListener('touchstart', e => { if (body.scrollTop <= 0) y0 = e.touches[0].clientY; }, { passive: true });
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
  on('truecost', item => { if (openUrl && item && item.url === openUrl) { render(openUrl); } });
  // reviews land after the hunt: refresh the open receipt's seller section (keeps the scroll position)
  const rerender = () => { if (!openUrl) return; const y = body.scrollTop; render(openUrl); body.scrollTop = y; };
  on('review', d => { const it = openUrl && S.offers.get(openUrl); if (it && reviewFor(it) === d) rerender(); });
  on('reviews', () => { const it = openUrl && S.offers.get(openUrl); const tm = it && trustMark(it);
    if (it && (!tm || tm.state !== 'done')) rerender(); });
  on('agent', () => closeSheet());
}
