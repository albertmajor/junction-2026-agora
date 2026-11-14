// ledger.js: every offer of the hunt as one quiet ranked list under the line (desktop).
// The line shows the story; dots there are anonymous. This list names each one: shop, condition, tag,
// what you pay all in, and whether it came late. Click a row for its receipt (the sheet).
import { S, on, emit, eur, cutSrc, isSetAside, domainOf, isProductPhoto, allIn, shipNote, isUnsure, unsureWhy, pickUrl as corePick, trustMark } from './core.js';
import { flagHtml } from './flags.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const COND = { n: 'new', r: 'refurbished', u: 'used' };
const FOLD = 6;

let root, raf = 0, open = false, sureOnly = false, lastHtml = '';

function condWord(c) {
  const k = String(c || '').toLowerCase();
  for (const [p, w] of Object.entries(COND)) if (k.startsWith(w.slice(0, 4)) || k === p) return w;
  if (k.startsWith('serv')) return '';
  return k;
}
function perMonth(it) {      // kept name for the tests' sake: this is the all-in price now
  const v = allIn(it);
  return typeof v === 'number' && isFinite(v) ? v : null;
}
function isJob(it) { const t = it.tc && it.tc.true_cost; return !!(t && t.per === 'job'); }
// the trust mark only when it says something: solid, mixed, watch out, a star rating, or still checking.
// "no reviews found" says nothing here (the receipt still says it).
function meaningful(tm) { return !!tm && tm.state !== 'none' && !(tm.state === 'done' && tm.label === 'unknown' && !/★/.test(tm.text)); }
function tagEur(it) {
  const p = it.offer && it.offer.price_eur;
  return typeof p === 'number' && isFinite(p) && p > 0 ? p : null;
}

/** The rows, best first. Turned (all in): offers you can surely buy at that price, by what you pay all in;
 *  then the ones we cannot be sure of (abroad and shipping to Finland not confirmed, out of stock, a "from"
 *  price), by the same figure, so the pick is always row 1; then offers still being costed, by tag.
 *  Set-aside offers live in "not counted" under the line, not here. Exported for tests. */
export function rows(offers, { turned = false } = {}) {
  const all = [...offers.values()].filter(it => tagEur(it) != null && !(it.tc && isSetAside(it)));
  if (!turned) return all.sort((a, b) => tagEur(a) - tagEur(b));
  const costed = all.filter(it => perMonth(it) != null);
  const rest = all.filter(it => perMonth(it) == null);
  const by = (a, b) => perMonth(a) - perMonth(b);
  const sure = costed.filter(it => !isUnsure(it)).sort(by);
  const unsure = costed.filter(it => isUnsure(it)).sort(by);
  return sure.concat(unsure, rest.sort((a, b) => tagEur(a) - tagEur(b)));
}

function pickUrl() { return (S.turned && corePick()) || S.leader; }

function render() {
  raf = 0;
  if (!root) return;
  const all = rows(S.offers, { turned: S.turned });
  const show = (S.turned || S.done) && all.length > 0 && S.phase !== 'finale' && S.phase !== 'start';
  root.hidden = !show;
  if (!show) { root.innerHTML = ''; lastHtml = ''; return; }
  const pick = pickUrl();
  // "sure only": costed offers you can surely buy at that price (the pick's pool)
  const canFilter = S.turned && all.some(it => it.tc && isUnsure(it));
  const list = canFilter && sureOnly ? all.filter(it => !(it.tc && isUnsure(it))) : all;
  const fold = !open && list.length > FOLD + 2;
  const vis = fold ? list.slice(0, FOLD) : list;
  const by = S.turned ? 'by what you pay, all in' : 'by the price on the tag';
  const n = all.length;
  const filt = canFilter ? `<span class="lg-f" role="group" aria-label="Which offers">
      <button type="button" data-f="all" aria-pressed="${!sureOnly}">all</button><button type="button" data-f="sure" aria-pressed="${sureOnly}">sure only</button></span>` : '';
  const html = `
    <div class="lg-top"><h2 class="lg-h">${n === 1 ? 'The one offer' : `All ${n} offers`}, <span>${by}</span></h2>${filt}</div>
    <div class="lg-r lg-head" aria-hidden="true"><span></span><span></span><span>shop</span><span>title</span><span>condition</span><span class="lg-tag">tag</span><span class="lg-tc">${S.turned ? 'all in' : ''}</span><span></span></div>
    <ol class="lg-l">${vis.map((it, i) => {
      const un = S.turned && it.tc && perMonth(it) != null && isUnsure(it);
      const prevUn = i > 0 && S.turned && vis[i - 1].tc && perMonth(vis[i - 1]) != null && isUnsure(vis[i - 1]);
      const sep = un && !prevUn && i > 0
        ? `<li class="lg-sep" aria-hidden="false"><b>Cheaper maybe, but not sure</b><span>the shop doesn’t confirm shipping to Finland, or the price isn’t final, so none of these can be the pick</span></li>` : '';
      const raw = it.offer.image || '';
      const src = cutSrc(it) || (isProductPhoto(raw) ? raw : '');
      const site = it.offer.source || domainOf(it.url);
      const pm = perMonth(it);
      const notes = [];
      if (it.url === pick) notes.push('<b>the pick</b>');
      if (it.late && it.url !== pick) notes.push('late');
      if (S.turned && pm == null) notes.push('still costing');
      const why = un ? unsureWhy(it) : '';
      const sn = pm != null && !isJob(it) ? shipNote(it).replace(/^\s*[·+]?\s*/, '') : '';
      if (why) notes.push(`<i>${esc(sn === 'shipping' ? '+ shipping · ' : '')}${esc(why)}</i>`);
      else if (sn) notes.push(`<i>${esc(sn === 'shipping' ? '+ shipping' : sn)}</i>`);
      if (S.recheck && S.recheck.to === it.url) notes.push('re-checked after reviews');
      const tm = trustMark(it);
      const mark = meaningful(tm) ? `<span class="tmark" data-state="${esc(tm.state)}" data-label="${esc(tm.label)}">${esc(tm.text)}</span>` : '';
      const pic = src ? `<img alt="" loading="lazy" decoding="async" src="${esc(src)}" data-raw="${esc(isProductPhoto(raw) ? raw : '')}">`
                      : `<i>${esc((site || '?').replace(/^www\./, '')[0].toUpperCase())}</i>`;
      const tc = pm == null ? '' : eur(pm >= 100 ? Math.round(pm) : pm, { dp: pm < 100 && Math.abs(pm % 1) > 0.004 ? 2 : 0 }) + (isJob(it) ? ' a job' : '');
      return `${sep}<li><button type="button" class="lg-r${it.url === pick ? ' pick' : ''}${it.tc && isUnsure(it) ? ' unsure' : ''}" data-url="${esc(it.url)}">
        <span class="lg-n">${i + 1}</span><span class="lg-pic">${pic}</span>
        <span class="lg-t"><span class="lg-s">${flagHtml(it, { noFi: true, unknown: true })}<span class="lg-d">${esc(site)}</span></span>${mark}</span>
        <span class="lg-ti">${esc(it.offer.title || '')}</span>
        <span class="lg-c">${esc(condWord(it.offer.condition))}</span>
        <span class="lg-tag">${esc(eur(tagEur(it), { dp: 0 }))}</span>
        <span class="lg-tc">${esc(tc)}</span>
        <span class="lg-x">${notes.join(' · ')}</span></button></li>`;
    }).join('')}</ol>
    ${fold ? `<button type="button" class="lg-more">show all ${list.length}</button>` : ''}`;
  // the same rows again (a review for another shop, a late event): leave the DOM alone, so photos and
  // flags do not blink
  if (html === lastHtml && root.childElementCount) return;
  lastHtml = html;
  root.innerHTML = html;
  root.querySelectorAll('.lg-pic img').forEach(img => img.addEventListener('error', () => {
    const raw = img.dataset.raw;
    if (raw && img.src !== raw) { img.dataset.raw = ''; img.src = raw; }
    else img.replaceWith(Object.assign(document.createElement('i'), { textContent: '·' }));
  }, { once: false }));
}
function queue() { if (!raf) raf = requestAnimationFrame(render); }

export function mountLedger(el) {
  if (!el) return;
  root = el;
  root.classList.add('ledger');
  root.hidden = true;
  root.addEventListener('click', e => {
    if (e.target.closest('.lg-more')) { open = true; render(); return; }
    const f = e.target.closest('.lg-f button');
    if (f) { sureOnly = f.dataset.f === 'sure'; render(); const b = root.querySelector(`.lg-f button[data-f="${f.dataset.f}"]`); b && b.focus(); return; }
    const b = e.target.closest('.lg-r');
    if (b && b.dataset.url) emit('select', b.dataset.url);
  });
  on('reset', () => { open = false; sureOnly = false; queue(); });
  for (const t of ['offer', 'offer-removed', 'truecost', 'verdict', 'rank', 'turn', 'done', 'late', 'finale:start', 'watch',
                   'review', 'reviews', 'recheck']) on(t, queue);
  queue();
}
