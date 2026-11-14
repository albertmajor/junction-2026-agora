// The landing page under the start search (UI round A, section 3): a browse grid of real listings,
// how it works, the sources we read, the agent door, and "Powered by Context.dev".
// main.js calls mountLanding($('landing')) and listens for the bus event 'ask' {q}.
import * as core from './core.js';
import { recordings, labelFor, queryFor } from './stream.js';
import { flagSrc } from './flags.js';

const brand = () => core.BRAND || document.documentElement.dataset.brand || 'Agora';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// the three recorded live hunts: the pick's photo (or a monogram plate) and what the hunt read
const RECORDED = {
  'sony-a7-iii-body': { img: '/web/assets/shelf/kamera-0.png', meta: '24 pages · 17 offers' },
  'iphone-15-128gb-used': { img: '/web/assets/shelf/iphone-15-0.png', meta: '11 pages · 6 offers' },
  'home-cleaning-helsinki-60m2': { svg: 'clean', meta: '13 pages · 10 offers', wide: true },
};
const REC_ORDER = Object.keys(RECORDED);

const SOURCES = [
  ['Second-hand', ['tori', 'blocket', 'finn', 'dba', 'kleinanzeigen', 'marktplaats', '2dehands', 'olx_pl', 'vinted',
    'gumtree', 'leboncoin', 'wallapop', 'subito', 'willhaben', 'ebay_de']],
  ['Refurbished', ['backmarket', 'rebuy']],
  ['Shops', ['amazon_de', 'verkkokauppa', 'power_fi', 'cdiscount', 'idealo', 'pricerunner']],
];

const TOOLS = [
  ['find_offers', 'query, country?, max_price_eur?, conditions?, limit?', 'offers ranked by all-in price, plus a one-line verdict'],
  ['get_offer', 'url', 'one offer we already read: price check, location, how it was read'],
  ['explain_price', 'url', 'its receipt: every line with its source'],
  ['watch_price', 'query, target_eur', 'notifies you when an offer hits the target. Never buys.'],
];

const CD_FACTS = [
  ['search', 'finds the shops and listings for a question'],
  ['product', 'reads a product page: price, stock, condition'],
  ['extract', 'structured JSON from listing pages'],
  ['scrape', 'markdown of marketplace search results'],
];

// ---------- small pieces ----------
const COUNTRY = { FI: 'Finland', SE: 'Sweden', DE: 'Germany', NL: 'the Netherlands', NO: 'Norway', DK: 'Denmark',
  BE: 'Belgium', FR: 'France', IT: 'Italy', ES: 'Spain', AT: 'Austria', PL: 'Poland', GB: 'the United Kingdom' };
function flag(cc) {
  if (!cc || !/^[A-Za-z]{2}$/.test(cc)) return '';
  const c = cc.toUpperCase(), name = COUNTRY[c] || c;
  const t = `Listed in ${name}, from the marketplace the listing is on.`;
  return `<span class="ld-flag" title="${esc(t)}" aria-label="${esc(t)}"><img src="${flagSrc(c)}" alt="" width="12" height="9" loading="lazy"><span class="ld-cc">${c}</span></span>`;
}
const cdMark = () => `<a class="cd-mark" href="https://context.dev" target="_blank" rel="noopener">Powered by <img src="https://www.google.com/s2/favicons?domain=context.dev&amp;sz=64" alt="" width="14" height="14" data-fb="sq"> <b>Context.dev</b></a>`;
const head = (n, kicker, h, id) => `<p class="ld-kicker"><span class="ld-n">${n}</span>${esc(kicker)}</p><h2 class="ld-h" id="${id}">${h}</h2>`;

// tiny drawings in the line style: 1.5 px ink, one yellow dot each
const SVG = {
  ask: `<svg viewBox="0 0 120 64" aria-hidden="true"><rect x="8" y="18" width="104" height="28" rx="9"/><path d="M20 32h44" class="soft"/><path d="M70 26v12"/><path d="M92 32h10M98 27l5 5-5 5"/><circle class="dot" cx="82" cy="11" r="4"/></svg>`,
  read: `<svg viewBox="0 0 120 64" aria-hidden="true"><rect x="10" y="12" width="30" height="40" rx="4"/><rect x="46" y="8" width="30" height="40" rx="4"/><rect x="82" y="12" width="30" height="40" rx="4"/><path d="M16 22h18M16 29h12M52 18h18M52 25h10M88 22h18M88 29h14" class="soft"/><path d="M8 60h104" class="soft"/><circle class="dot" cx="61" cy="40" r="4"/></svg>`,
  line: `<svg viewBox="0 0 120 64" aria-hidden="true"><path d="M6 44h108"/><path d="M18 44v5M48 44v5M78 44v5M108 44v5" class="soft"/><circle cx="34" cy="36" r="4" class="hollow"/><circle cx="64" cy="36" r="4" class="hollow"/><circle cx="96" cy="36" r="4" class="hollow"/><circle class="dot" cx="22" cy="36" r="4.5"/><path d="M13.5 35.5c.5-7 7.5-10.5 13-8.5 6 2 7 9 4 13-3 4.5-11 5-14.5 1.5" class="wob"/></svg>`,
};

// ---------- sections ----------
function browseHtml() {
  return `<section class="ld-band" id="ld-browse" aria-labelledby="ld-browse-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('01', 'Browse', 'Or start from something real.', 'ld-browse-h')}
        <p class="ld-sub">Real listings our hunts have read, at the price on their tag. Pick one and we hunt it across Europe, all in.</p>
      </header>
      <p class="ld-note" role="status" hidden>This demo server runs offline, so it replays the three recorded live hunts (Sony A7 III, iPhone 15, home cleaning in Helsinki). The other searches run live when a Context.dev key is set.</p>
      <ul class="ld-grid" role="list"></ul>
    </div>
  </section>`;
}
function howHtml() {
  const steps = [
    ['ask', 'You ask once.', 'Anything you can buy: a camera, a used iPhone, someone to clean your flat.'],
    ['read', 'We read the shops, live.', 'Context.dev reads marketplace searches and shop pages while you watch: price, shipping, condition, and where it ships from.'],
    ['line', 'You see what you’d pay, all in.', 'Every offer lands on one euro line at tag + shipping + import VAT + fees. The cheapest you can surely buy gets the circle.'],
  ];
  return `<section class="ld-band alt" id="ld-how" aria-labelledby="ld-how-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">${head('03', 'How it works', 'One question. Every shop. One line.', 'ld-how-h')}</header>
      <ol class="ld-steps" role="list">
        ${steps.map(([k, t, b], i) => `<li class="ld-step ld-rv" style="--d:${i * 80}ms">${SVG[k]}<h3><span class="ld-n">${i + 1}</span>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <p class="ld-after ld-rv">Not ready? Drag your price onto the line and we’ll watch it for you.</p>
    </div>
  </section>`;
}
function sourcesHtml() {
  return `<section class="ld-band" id="ld-sources" aria-labelledby="ld-sources-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('04', 'Sources', 'Where we look.', 'ld-sources-h')}
        <p class="ld-sub">Second-hand marketplaces, refurbishers and big shops across Europe, plus any shop the search turns up.</p>
      </header>
      <div class="ld-wall"></div>
      <p class="ld-foot ld-rv">Brand marks fetched by the Context.dev brand API · 193 second-hand sources in our registry · free JSON-LD first, Context.dev where it matters.</p>
    </div>
  </section>`;
}
function codeLine(kind, origin) {
  if (kind === 'mcp') {
    // runs as written from the repo folder (uv reads the project's lockfile); no machine-specific path
    const name = brand().toLowerCase().replace(/[^a-z0-9-]+/g, '-');
    return { text: `claude mcp add ${name} -- uv run python -m agora.mcp_server`,
      html: `<span class="tk-p">$</span> <span class="tk-k">claude</span> mcp add ${esc(name)} <span class="tk-s">--</span> uv run python <span class="tk-k">-m</span> agora.mcp_server` };
  }
  const url = `${origin}/api/offers?q=sony+a7+iii+body&limit=3`;
  return { text: `curl "${url}"`,
    html: `<span class="tk-p">$</span> <span class="tk-k">curl</span> <span class="tk-s">"</span>${esc(origin)}/api/offers?<span class="tk-k">q</span>=sony+a7+iii+body&amp;<span class="tk-k">limit</span>=3<span class="tk-s">"</span>` };
}
function agentsHtml() {
  // the curl line is this server, as you see it (no port on 80/443: location.origin already drops it)
  const origin = (typeof location !== 'undefined' && /^https?:/.test(location.protocol || '')) ? location.origin : '';
  const block = (kind, label) => {
    if (kind === 'http' && !origin) return '';
    const c = codeLine(kind, origin);
    return `<figure class="ld-code ld-rv"><figcaption>${esc(label)}</figcaption>
      <pre><code>${c.html}</code></pre>
      <button type="button" class="ld-copy" data-copy="${esc(c.text)}" aria-label="Copy: ${esc(label)}">copy</button></figure>`;
  };
  return `<section class="ld-band alt" id="ld-agents" aria-labelledby="ld-agents-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('05', 'For agents', 'Same line, for your agent.', 'ld-agents-h')}
        <p class="ld-sub">Agents get the same offers in the same order, ranked by all-in price, over MCP or plain JSON. Read-only: ${esc(brand())} never buys for an agent.</p>
      </header>
      <div class="ld-codes">
        ${block('mcp', 'MCP, for Claude Code · run it in the repo folder')}
        ${block('http', 'Plain JSON over HTTP')}
      </div>
      <div class="ld-tools ld-rv" role="table" aria-label="MCP tools">
        <div class="ld-tr ld-th" role="row"><span role="columnheader">tool</span><span role="columnheader">takes</span><span role="columnheader">gives back</span></div>
        ${TOOLS.map(([n, a, r]) => `<div class="ld-tr" role="row"><code role="cell">${n}</code><span role="cell" class="ld-args">${esc(a)}</span><span role="cell">${esc(r)}</span></div>`).join('')}
      </div>
      <p class="ld-links ld-rv"><a href="#agent" class="ld-agent-demo">what an agent sees →</a><a href="/api">API index →</a></p>
    </div>
  </section>`;
}
function cdHtml() {
  return `<section class="ld-band ink" id="ld-cd" aria-labelledby="ld-cd-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        <p class="ld-kicker"><span class="ld-n">02</span><span class="ld-pulse" aria-hidden="true"></span>The engine</p>
        <h2 class="ld-h" id="ld-cd-h">Powered by <span class="ld-cd-name"><img src="https://www.google.com/s2/favicons?domain=context.dev&amp;sz=64" alt="" width="28" height="28" data-fb="sq">Context.dev</span>.</h2>
        <p class="ld-sub">Every page ${esc(brand())} reads goes through Context.dev: web search to find the shops, product extraction, structured JSON from listing pages, markdown scrapes of marketplace search results, and the brand logos you see in the live log. We spend it carefully: free JSON-LD first, paid reads where they matter.</p>
      </header>
      <p class="ld-count ld-rv" aria-live="polite"><b>48</b> pages on <b>35</b> sites, read live in the three recorded hunts above: Context.dev where it pays, free JSON-LD where a shop already publishes it.</p>
      <ul class="ld-facts" role="list">
        ${CD_FACTS.map(([k, v], i) => `<li class="ld-rv" style="--d:${i * 60}ms"><b>${k}</b><span>${esc(v)}</span></li>`).join('')}
      </ul>
      <p class="ld-links ld-rv"><a href="https://context.dev" target="_blank" rel="noopener">context.dev →</a></p>
    </div>
  </section>`;
}

// ---------- browse cards ----------
// a cleaning job has no product photo: a drawn spray bottle and bucket, in the same muted cut-out look
const CLEAN_SVG = `<svg class="ld-draw" viewBox="0 0 220 120" aria-hidden="true">
  <ellipse cx="110" cy="110" rx="78" ry="5" class="sh"/>
  <path d="M58 44h22l6 10v52a4 4 0 0 1-4 4H56a4 4 0 0 1-4-4V58z" class="b1"/>
  <path d="M56 70h28v24H56z" class="lb"/><path d="M61 78h18M61 84h12" class="ln"/>
  <path d="M60 30h18v14H60z" class="b2"/><path d="M60 30h-14l-4 6h18z" class="b3"/>
  <path d="M74 44c4 6 6 10 4 16" class="ln"/>
  <circle cx="36" cy="32" r="1.6" class="mist"/><circle cx="30" cy="27" r="1.2" class="mist"/><circle cx="29" cy="36" r="1.1" class="mist"/>
  <path d="M112 62h64l-7 44a5 5 0 0 1-5 4h-40a5 5 0 0 1-5-4z" class="b2"/>
  <path d="M112 62c0-26 64-26 64 0" class="hd"/>
  <path d="M108 62h72" class="rim"/>
  <path d="M150 52c6-12 18-12 22-4" class="sp"/><path d="M146 54c2-8 10-10 14-6" class="sp2"/>
</svg>`;
function cardHtml(c, i) {
  const plate = c.svg === 'clean' ? CLEAN_SVG
    : c.img ? `<img src="${esc(c.img)}" alt="" loading="lazy" decoding="async">`
    : `<span class="ld-mono" aria-hidden="true">${esc(c.mono || '')}</span>`;
  const label = c.label ? `<span class="ld-label${c.recorded ? ' rec' : ''}">${esc(c.label)}</span>` : '';
  return `<li class="ld-item ld-rv${c.wide ? ' wide' : ''}${i === 0 ? ' first' : ''}" style="--d:${(i % 6) * 40}ms">
    <button type="button" class="ld-card" data-q="${esc(c.q)}" data-ok="${c.ok ? 1 : 0}" aria-label="${esc(`Hunt for ${c.title}`)}">
      <span class="ld-plate">${plate}${label}</span>
      <span class="ld-title">${esc(c.title)}</span>
      <span class="ld-meta">${c.cc ? flag(c.cc) : ''}<span>${esc(c.meta)}</span></span>
    </button></li>`;
}
async function getJson(url) {
  try { const r = await fetch(url, { headers: { accept: 'application/json' } }); return r.ok ? await r.json() : null; }
  catch { return null; }
}
async function cards() {
  const [recs, shelf, status] = await Promise.all([
    recordings().catch(() => []), getJson('/web/assets/shelf.json'), getJson('/status'),
  ]);
  const live = !!(status && status.live);
  const have = new Set(recs || []);
  const out = [];
  const used = new Set();
  for (const slug of [...REC_ORDER.filter(s => have.has(s)), ...[...have].filter(s => !REC_ORDER.includes(s))]) {
    const r = RECORDED[slug] || { mono: labelFor(slug).slice(0, 5).toLowerCase(), meta: 'recorded live hunt' };
    if (r.img) used.add(r.img);
    out.push({ title: labelFor(slug), q: queryFor(slug), img: r.img, mono: r.mono, svg: r.svg, wide: r.wide, meta: r.meta, recorded: true, ok: true, label: 'instant replay' });
  }
  const items = (Array.isArray(shelf) ? shelf : []).filter(s => s && s.title && s.query && !used.has(s.img))
    .sort((a, b) => (a.price_eur || 0) - (b.price_eur || 0));
  for (const s of items) {
    const rec = s.recording && have.has(s.recording);
    out.push({
      title: s.title, q: rec ? queryFor(s.recording) : s.query, img: s.img, cc: s.country,
      // the price as listed is a tag, and says so (the main number everywhere else is all in)
      meta: [s.price_eur ? 'tag ' + core.eur(s.price_eur, { dp: 0 }) : '', s.site, s.condition].filter(Boolean).join(' · '),
      recorded: rec, ok: rec || live, label: rec ? 'instant replay' : '',
    });
  }
  return out;
}

function brandsWall(el, brands) {
  el.innerHTML = SOURCES.map(([label, keys], g) => {
    const cells = keys.map(k => brands && brands[k]).filter(Boolean).map(b => {
      const mono = esc((b.name || b.domain || '?').charAt(0));
      return `<li title="${esc(b.domain)}"><span class="ld-logo" data-mono="${mono}">${b.logo
        ? `<img src="${esc(b.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<i>${mono}</i>`}</span><span class="ld-bn">${esc(b.name)}</span></li>`;
    }).join('');
    return `<div class="ld-group ld-rv" style="--d:${g * 60}ms"><p class="ld-gl">${esc(label)}</p><ul role="list">${cells}</ul></div>`;
  }).join('');
}

// ---------- behaviour ----------
function ask(q) {
  q = String(q || '').trim();
  if (!q) return;
  core.emit('ask', { q });
  // until main.js listens for 'ask' (a run flips the phase synchronously), submit the box ourselves
  const app = document.getElementById('app');
  if (app && app.dataset.phase === 'start') {
    const qIn = document.getElementById('q'), form = document.getElementById('ask');
    if (qIn && form) {
      qIn.value = q;
      scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' });
      if (typeof form.requestSubmit === 'function') form.requestSubmit(); else form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  }
}

function fallbacks(root) {
  root.querySelectorAll('img').forEach(img => {
    if (img.dataset.fbOn) return;
    img.dataset.fbOn = '1';
    img.addEventListener('error', () => {
      if (img.dataset.fb === 'sq') { const i = document.createElement('i'); i.className = 'cd-sq'; img.replaceWith(i); return; }
      const fl = img.closest('.ld-flag');
      if (fl) { fl.classList.add('txt'); img.remove(); return; }
      const lg = img.closest('.ld-logo');
      if (lg) { const i = document.createElement('i'); i.textContent = lg.dataset.mono || ''; img.replaceWith(i); return; }
      const pl = img.closest('.ld-plate');
      if (pl) { img.remove(); pl.classList.add('empty'); }
    }, { once: true });
    if (img.complete && img.naturalWidth === 0 && img.src) img.dispatchEvent(new Event('error'));
  });
}

let io = null, sweepOn = false;
// anything at or above the fold's bottom edge is shown: a jump (End key, anchor, fast fling) never leaves blank bands
function sweep() {
  for (const e of document.querySelectorAll('.ld-rv:not(.in)')) {
    if (e.getBoundingClientRect().top < innerHeight) { e.classList.add('in'); if (io) io.unobserve(e); }
  }
}
function reveal(root) {
  const els = [...root.querySelectorAll('.ld-rv:not(.in)')];
  if (!('IntersectionObserver' in window)) { els.forEach(e => e.classList.add('in')); return; }
  if (!io) io = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }, { rootMargin: '0px', threshold: 0.01 });
  els.forEach(e => io.observe(e));
  if (!sweepOn) {
    sweepOn = true;
    let raf = 0;
    addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; sweep(); }); }, { passive: true });
  }
}

export function mountLanding(el) {
  if (!el || el.dataset.mounted) return;
  el.dataset.mounted = '1';
  el.classList.add('ld-js');
  const cue = el.querySelector('.scroll-cue');
  el.insertAdjacentHTML('beforeend', browseHtml() + cdHtml() + howHtml() + sourcesHtml() + agentsHtml());
  if (cue) el.prepend(cue);

  const grid = el.querySelector('.ld-grid');
  cards().then(list => {
    grid.innerHTML = list.map(cardHtml).join('');
    fallbacks(grid); reveal(grid);
  });
  getJson('/web/assets/brands.json').then(b => {
    const wall = el.querySelector('.ld-wall');
    brandsWall(wall, b || {}); fallbacks(wall); reveal(wall);
  });
  fallbacks(el); reveal(el);

  el.addEventListener('click', e => {
    const card = e.target.closest('.ld-card');
    if (card) {
      if (card.dataset.ok === '1') { ask(card.dataset.q); return; }
      const note = el.querySelector('.ld-note');
      if (note) {
        note.hidden = false; note.classList.remove('flash'); void note.offsetWidth; note.classList.add('flash');
        note.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'nearest' });
      }
      return;
    }
    const cp = e.target.closest('.ld-copy');
    if (cp) {
      const done = ok => { cp.textContent = ok ? 'copied' : 'select to copy'; cp.classList.toggle('ok', ok); setTimeout(() => { cp.textContent = 'copy'; cp.classList.remove('ok'); }, 1600); };
      try { navigator.clipboard.writeText(cp.dataset.copy).then(() => done(true), () => done(false)); } catch { done(false); }
      return;
    }
    const demo = e.target.closest('.ld-agent-demo');
    if (demo) {
      e.preventDefault();
      // run the Sony example, then open what an agent sees once the hunt is in
      core.bus.addEventListener('done', () => core.emit('agent', { on: true }), { once: true });
      ask(queryFor('sony-a7-iii-body'));
    }
    const cueA = e.target.closest('.scroll-cue');
    if (cueA) {
      e.preventDefault();
      const t = el.querySelector('#ld-browse');
      if (t) t.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
    }
  });
}
