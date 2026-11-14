// market.js: how big the market is, under the headline (UI round B, owner item 2 + 3).
// "≈19,405 listings on 4 marketplaces · we compared 318", a chip per marketplace (flag, logo, total vs read),
// the scope in plain words when the thing is bulky, and "Compare more" (the same hunt, deeper pages).
// Reads S.scope / S.market (stream.js stores the `scope` and `market` events); writes nothing to the store.
import { S, on, emit, fmtCount } from './core.js';
import * as stream from './stream.js';
import { flagSrc, countryName } from './flags.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const bare = d => String(d || '').toLowerCase().replace(/^www\./, '');
const n0 = n => Math.round(n || 0).toLocaleString('en-US');
const plural = (n, w, ws = w + 's') => `${n0(n)} ${n === 1 ? w : ws}`;

let root = null, done = false, waitTimer = 0, waitLeft = 0, note = '', noteKind = '', lastKey = '';

// brand logos (Context.dev brand data in assets/brands.json), then the favicon, then a letter
let brands = {};
const brandsReady = (typeof fetch === 'function' ? fetch('/web/assets/brands.json') : Promise.reject())
  .then(r => r.ok ? r.json() : {})
  .then(j => { for (const b of Object.values(j || {})) if (b && b.domain && b.logo) brands[bare(b.domain)] = b.logo; })
  .catch(() => {});
function logoFor(d) {
  for (let h = bare(d); h && h.includes('.'); h = h.slice(h.indexOf('.') + 1)) if (brands[h]) return brands[h];
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(bare(d))}&sz=64`;
}

/** The scope reason, as the engine wrote it, made into a sentence ("Bulky item: searched near you in Finland
 *  first; shipping a bike from abroad costs ≈€60–120. …"). Small things say nothing: shipping is normal. */
export function scopeText(sc = S.scope) {
  if (!sc || !sc.reason || !sc.bulky) return '';
  let t = String(sc.reason).trim();
  t = t.charAt(0).toUpperCase() + t.slice(1);
  if (!/[.!?]$/.test(t)) t += '.';
  return t;
}

/** "≈19,405 listings on 4 marketplaces" / "at least 2,000 listings on 2 marketplaces"; '' when no site said. */
export function sizeText(m = S.market) {
  const src = (m && m.sources) || [];
  const tot = m && m.total;
  if (!src.length || !(tot > 0)) return '';
  const lead = m.at_least ? `at least ${n0(tot)}` : `≈${n0(tot)}`;
  return `${lead} listings on ${plural(src.length, 'marketplace')}`;
}

function chip(s) {
  const d = bare(s.domain);
  const cc = s.country ? String(s.country).toUpperCase() : '';
  const tot = s.total > 0 ? s.total : null;
  const read = s.read || 0;
  const pct = tot ? Math.max(2, Math.min(100, (read / tot) * 100)) : 100;
  const where = cc ? countryName(cc) : '';
  const title = `${d}${where ? ' (' + where + ')' : ''}: ${tot ? (s.at_least ? 'at least ' : '') + n0(tot) + ' listings for this search' : 'size not stated'}, ` +
    `we read ${plural(read, 'listing')} on ${plural(s.pages || 1, 'page')}${s.extra ? '. Also in the EU: shown apart, with shipping estimated' : ''}.`;
  return `<li class="mk-chip${s.extra ? ' is-extra' : ''}" title="${esc(title)}">
    <span class="mk-logo" data-l="${esc((d[0] || '?').toUpperCase())}"><img alt="" width="16" height="16" decoding="async" referrerpolicy="no-referrer" src="${esc(logoFor(d))}"></span>
    ${cc ? `<img class="mk-flag" alt="" width="14" height="10" src="${esc(flagSrc(cc))}">` : ''}
    <span class="mk-d">${esc(d)}</span>
    <span class="mk-n"><b>${tot ? (s.at_least ? '≥' : '') + fmtCount(tot) : '?'}</b> · read ${n0(read)}</span>
    <span class="mk-bar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></span>
    ${s.extra ? '<span class="mk-eu">also in the EU</span>' : ''}
  </li>`;
}

function render() {
  if (!root) return;
  const hunting = S.phase !== 'start' && !!S.q && S.phase !== 'finale';
  const m = S.market;
  const sc = scopeText();
  const size = sizeText(m);
  const offers = S.offers ? S.offers.size : 0;
  if (!hunting || (!sc && !size && !done)) { root.hidden = true; root.innerHTML = ''; lastKey = ''; return; }
  const compared = m && m.read ? m.read : offers;
  const others = m && m.read ? Math.max(0, offers - m.read) : 0;
  const sizeLine = size
    ? `${esc(size)} · <b>we compared ${n0(compared)}</b>${others ? `<span class="mk-plus"> + ${plural(others, 'offer')} from shops</span>` : ''}`
    : done ? `<b>We compared ${plural(offers, 'listing')}</b>${S.sources && S.sources.length ? ` from ${plural(new Set(S.sources.map(s => bare(s.domain))).size, 'site')}` : ''}`
      : '';
  const deeper = S.depth > 1 ? `<span class="mk-deep">${done ? 'deeper hunt' : 'reading deeper pages…'}</span>` : '';
  const canMore = done && !waitTimer;
  const btn = done || waitTimer
    ? `<button type="button" class="mk-more btn sm" ${canMore ? '' : 'disabled'} aria-describedby="mk-note">${waitTimer ? 'waiting for Context.dev…' : 'Compare more'}</button>` : '';
  const chips = m && m.sources && m.sources.length
    ? `<ul class="mk-chips" aria-label="Marketplaces: listings they have for this search, and how many we read">${m.sources.slice().sort((a, b) => (a.extra ? 1 : 0) - (b.extra ? 1 : 0) || (b.read || 0) - (a.read || 0)).map(chip).join('')}</ul>` : '';
  const key = [sizeLine, sc, deeper, btn, chips, note, noteKind].join('|');
  root.hidden = false;
  if (key === lastKey) return;
  lastKey = key;
  root.innerHTML = `
    ${sizeLine || btn ? `<div class="mk-line"><p class="mk-size">${sizeLine}${deeper}</p>${btn}</div>` : ''}
    ${sc ? `<p class="mk-scope"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 1.8c-2.5 0-4.4 1.9-4.4 4.3 0 3.2 4.4 8 4.4 8s4.4-4.8 4.4-8c0-2.4-1.9-4.3-4.4-4.3z"/><circle cx="8" cy="6.1" r="1.5"/></svg><span>${esc(sc)}</span></p>` : ''}
    ${chips}
    <p class="mk-note" id="mk-note" role="status" data-kind="${esc(noteKind)}"${note ? '' : ' hidden'}>${esc(note)}</p>`;
  root.querySelectorAll('.mk-logo img').forEach(img => img.addEventListener('error', () => { img.remove(); }, { once: true }));
}
let raf = 0;
function queue() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; render(); }); }

function setNote(text, kind = '') { note = text || ''; noteKind = kind; render(); }
function stopWait() { clearInterval(waitTimer); waitTimer = 0; waitLeft = 0; }

/** Context.dev reads 10 pages a minute for the whole account: wait for room, say so, then hunt deeper. */
async function more() {
  if (waitTimer) return;
  if (S.slug || !stream.isLive()) {
    setNote(S.slug ? 'This is a recorded hunt: comparing more needs a live search, which reads new pages through Context.dev.'
                   : 'Comparing more needs a live search (Context.dev), and this server is offline.', 'info');
    return;
  }
  const b = await stream.bucket();
  const wait = stream.waitFor(b);
  if (wait > 0) {
    waitLeft = wait;
    const tick = () => {
      if (waitLeft <= 0) { stopWait(); setNote('', ''); go(); return; }
      setNote(`Context.dev allows ${stream.READS_PER_MIN} pages a minute — reading more in ${waitLeft} s`, 'wait');
      waitLeft--;
    };
    waitTimer = setInterval(tick, 1000);
    tick();
    return;
  }
  go();
}
function go() {
  setNote('', '');
  const q = S.q;
  stream.compareMore().then(r => {
    if (r && r.error) setNote('Could not start a deeper hunt for this search.', 'info');
    else emit('market:more', { q, depth: S.depth });
  });
}

export function mountMarket(el) {
  if (!el) return;
  root = el;
  root.classList.add('market');
  root.addEventListener('click', e => { if (e.target.closest('.mk-more')) more(); });
  on('reset', d => {
    done = false; lastKey = '';
    if (!(d && d.depth > 1)) { stopWait(); note = ''; noteKind = ''; }
    else { note = ''; noteKind = ''; }
    render();
  });
  for (const t of ['scope', 'market', 'need', 'turn', 'verdict', 'finale:start']) on(t, queue);
  on('done', () => {
    done = true;
    // pages that waited on the read limit were not read: say so where the button to read more is
    const limited = (S.skips || []).filter(k => /rate limit|budget|out of time/i.test(String(k.reason || ''))).length;
    if (limited && !S.slug && !note) { note = `${plural(limited, 'page')} waited on Context.dev's limit of ${stream.READS_PER_MIN} pages a minute. Compare more reads them.`; noteKind = 'info'; }
    queue();
  });
  on('error', e => { if (e && (e.kind === 'net' || e.kind === '429')) { done = true; queue(); } });
  brandsReady.then(() => { lastKey = ''; queue(); });
  render();
}

export const _test = { scopeText, sizeText };
