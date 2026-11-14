// drawer.js (B3): "how we found this". Everything the main view hides, in one calm column.
import { S, on, emit, eur, domainOf, allIn, pickUrl, cheapestByCondition, isSetAside, isUnsure, shipsUnconfirmed, isJobItem } from './core.js';

let root, panel, body, isOpen = false, lastFocus = null, raf = 0;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const LANE = { new: 'New', refurbished: 'Refurbished', used: 'Used', rental: 'Rental', service: 'Services', sibling: 'Neighbouring models, for resale value', lookalike: 'Look-alike shops' };

// Group skip reasons: drop URLs and per-page numbers so the same cause lands in one bucket.
function reasonKey(r) {
  let s = String(r || 'skipped');
  s = s.replace(/https?:\/\/\S+/g, 'another page').replace(/\s*\(redirect or duplicate\)/, '');
  s = s.replace(/hunt budget \d+s reached/, 'out of time for this hunt');
  s = s.replace(/\b\d+(\.\d+)?\s?s\b/g, 'N s');
  return s[0].toUpperCase() + s.slice(1);
}

function linkUrl() {
  const u = new URL(location.origin + '/');
  if (S.q) u.searchParams.set('q', S.q);
  return u.toString();
}

// Every section starts folded to one line; what you open stays open for this session.
const OPEN_KEY = 'agora.drawer.open';
let openSecs = new Set();
try { openSecs = new Set(JSON.parse(sessionStorage.getItem(OPEN_KEY) || '[]')); } catch { openSecs = new Set(); }
function saveOpen() { try { sessionStorage.setItem(OPEN_KEY, JSON.stringify([...openSecs])); } catch { /* private mode */ } }
function sec(key, title, one, inner) {
  return `<details class="d-sec" data-k="${key}"${openSecs.has(key) ? ' open' : ''}>
    <summary><span class="d-k">${esc(title)}</span><span class="d-one">${one}</span></summary>
    <div class="d-in">${inner}</div></details>`;
}
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

// "Why this pick", ranked the way the page is: what you pay once, all in.
const money = (it, a = allIn(it)) => isJobItem(it) ? eur(a, { dp: Math.abs(a % 1) > 0.004 ? 2 : 0 }) : eur(Math.round(a), { dp: 0 });
function whyLines(v) {
  const pu = pickUrl(), pk = pu && S.offers.get(pu);
  if (!pk) return null;
  const shop = it => (it.offer && it.offer.source) || domainOf(it.url);
  const job = isJobItem(pk);
  const head = job
    ? `${money(pk)} for one job at ${shop(pk)}: the lowest price for the whole job, every fee in.`
    : `${money(pk)} all in at ${shop(pk)}${pk.offer.condition ? ', ' + pk.offer.condition : ''}: the lowest price you can surely buy once shipping, import VAT and fees are on the tag.`;
  const lines = [];
  if (!job) {
    const byC = cheapestByCondition();
    for (const c of ['new', 'refurbished', 'used']) {
      const e = byC[c]; if (!e) continue;
      const tag = e.it.offer.price_eur, a = allIn(e.it);
      lines.push(`${c}: ${money(e.it)} all in at ${shop(e.it)}${Math.abs(a - tag) > 0.5 ? ` (tag ${eur(Math.round(tag), { dp: 0 })})` : ''}${shipsUnconfirmed(e.it) ? ', plus shipping it does not confirm to Finland' : e.sure ? '' : ', not surely buyable'}`);
    }
    const cheaper = [...S.offers.values()].filter(it => it !== pk && !isSetAside(it) && isUnsure(it) && allIn(it) != null && allIn(it) < allIn(pk));
    if (cheaper.length) lines.push(`${cheaper.length} offer${cheaper.length === 1 ? ' is' : 's are'} cheaper all in but not the pick: abroad without confirmed shipping to Finland, out of stock or a "from" price.`);
  }
  // the engine's own notes, minus the per-month arithmetic the page no longer ranks by
  for (const l of (v && v.lines) || []) {
    if (/\/mo\b|to beat/.test(l)) continue;
    lines.push(l.replace(/\bREFURBISHED\b|\bNEW\b|\bUSED\b/g, w => w.toLowerCase()));
  }
  if (!job) lines.push('Resale value is an option on each receipt ("if you resell it"), never part of the ranking.');
  return { head, lines };
}

function render() {
  if (!body) return;
  const v = S.verdict && S.verdict.verdict;
  const parts = [];

  const why = whyLines(v);
  if (why) parts.push(sec('why', 'Why this pick', esc(why.head), `<p class="d-head">${esc(why.head)}</p>
      <ul class="d-lines">${why.lines.map(l => `<li>${esc(l)}</li>`).join('')}</ul>`));

  if (S.lanes.length) {
    const names = S.lanes.map(l => (LANE[l.lane] || l.lane).split(',')[0].toLowerCase());
    parts.push(sec('lanes', 'Where we looked', esc(names.join(' · ')),
      `<ul class="d-lanes">${S.lanes.map(l => `
      <li><span class="ln">${esc(LANE[l.lane] || l.lane)}${l.via ? ` <i>via ${esc(l.via)}</i>` : ''}</span>
      <span class="lq">${(l.queries || []).map(q => `<q>${esc(q)}</q>`).join(' ')}</span></li>`).join('')}</ul>`));
  }

  const read = new Map();
  for (const it of S.offers.values()) {
    const d = (it.offer && it.offer.source) || domainOf(it.url);
    read.set(d, (read.get(d) || 0) + 1);
  }
  const groups = new Map();
  for (const sk of S.skips) {
    const k = reasonKey(sk.reason);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(domainOf(sk.url) || sk.url);
  }
  if (read.size || groups.size || S.sources.length) {
    const g = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
    parts.push(sec('pages', 'Pages', `${S.sources.length} found · ${S.offers.size} offers · ${S.skips.length} skipped`,
      `${read.size ? `<div class="d-group"><p class="gk">Read <span>${read.size}</span></p><p class="gv">${[...read.entries()].map(([d, n]) => esc(d) + (n > 1 ? ` <i>×${n}</i>` : '')).join(' · ')}</p></div>` : ''}
      ${g.map(([k, ds]) => `<div class="d-group"><p class="gk">${esc(k)} <span>${ds.length}</span></p><p class="gv">${[...new Set(ds)].map(esc).join(' · ')}</p></div>`).join('')}`));
  }

  if (S.budget) {
    const b = S.budget;
    const free = b.saved_by_free_reads ?? (b.free_reads || []).length;
    const credits = +(b.credits_used || 0).toFixed(1);
    const bits = [plural(credits, 'credit'), plural(free, 'free read'), plural(b.cache_hits || 0, 'cache hit')];
    if (b.credit_eur != null) bits.push(`about ${eur(b.credit_eur, { dp: 2 })}`);
    const one = b.credit_eur != null ? `about ${eur(b.credit_eur, { dp: 2 })}` : plural(credits, 'credit');
    parts.push(sec('cost', 'What it cost us', esc(one), `<p class="d-budget">${bits.join(' · ')}</p>`));
  }

  if (!parts.length) parts.push(`<p class="d-empty">Run a search and this fills in as we read the shops.</p>`);
  parts.push(`<p class="d-rule">Ranked by what you pay, all in: the tag plus shipping, import VAT and fees. No paid placements. We may earn a fee, never a better spot.</p>`);
  const a = document.activeElement;
  const focusK = a && a.tagName === 'SUMMARY' && body.contains(a) ? a.parentElement.dataset.k : null;
  body.innerHTML = parts.join('');
  if (focusK) { const f = body.querySelector(`.d-sec[data-k="${focusK}"] > summary`); f && f.focus({ preventScroll: true }); }
}

function schedule() { if (!isOpen || raf) return; raf = requestAnimationFrame(() => { raf = 0; render(); }); }

function open() {
  if (isOpen) return;
  isOpen = true; lastFocus = document.activeElement;
  render();
  root.hidden = false; root.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => root.classList.add('open'));
  setTimeout(() => panel.querySelector('.close').focus({ preventScroll: true }), 30);
}
function close() {
  if (!isOpen) return;
  isOpen = false;
  root.classList.remove('open'); root.setAttribute('aria-hidden', 'true');
  setTimeout(() => { if (!isOpen) root.hidden = true; }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320);
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}

export function mountDrawer(el) {
  root = el;
  el.classList.add('drawer');
  el.hidden = true;
  el.innerHTML = `<div class="backdrop" data-close></div>
    <div class="panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <div class="grab" aria-hidden="true"></div>
      <header class="d-top">
        <h2 id="drawer-title">How we found this</h2>
        <button type="button" class="icon copylink" aria-label="Copy link to this search" title="Copy link"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.6 2.6 0 013.7 3.7L10.7 8.2M9 11.5l-1.2 1.2a2.6 2.6 0 01-3.7-3.7L5.3 7.8"/></svg><span class="copied" aria-live="polite"></span></button>
        <button type="button" class="icon close" data-close aria-label="Close"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg></button>
      </header>
      <div class="body"></div>
    </div>`;
  panel = el.querySelector('.panel');
  body = el.querySelector('.body');

  // remember which sections are open (toggle does not bubble: listen in the capture phase)
  body.addEventListener('toggle', e => {
    const d = e.target;
    if (!d.classList || !d.classList.contains('d-sec')) return;
    if (d.open) openSecs.add(d.dataset.k); else openSecs.delete(d.dataset.k);
    saveOpen();
  }, true);

  el.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) { close(); emit('drawer', { open: false, from: 'drawer' }); return; }
    const c = e.target.closest('.copylink');
    if (c) {
      const msg = c.querySelector('.copied');
      const ok = () => { msg.textContent = 'Link copied'; c.classList.add('done'); setTimeout(() => { msg.textContent = ''; c.classList.remove('done'); }, 1600); };
      if (navigator.clipboard) navigator.clipboard.writeText(linkUrl()).then(ok).catch(() => { msg.textContent = linkUrl(); });
      else msg.textContent = linkUrl();
    }
  });
  document.addEventListener('keydown', e => {
    if (!isOpen) return;
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key === 'Tab') {
      const f = [...panel.querySelectorAll('button,a[href],summary')];
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (!panel.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    }
  }, true);

  on('drawer', d => {
    if (d && d.from === 'drawer') return;
    const want = d && typeof d.open === 'boolean' ? d.open : !isOpen;
    want ? open() : close();
  });
  on('reset', () => { if (isOpen) render(); });
  for (const t of ['lane', 'source', 'skip', 'budget', 'offer', 'verdict', 'done']) on(t, schedule);
}
