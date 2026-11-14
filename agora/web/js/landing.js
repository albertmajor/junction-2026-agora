// The landing page under the start search: a "Powered by Context.dev" banner, the problem, how it works (one real example,
// start to finish), the all-in price (two receipts side by side), the sources we read, and the agent door.
// main.js calls mountLanding($('landing')) and listens for the bus event 'ask' {q}.
import * as core from './core.js';
import { queryFor } from './stream.js';

const brand = () => core.BRAND || document.documentElement.dataset.brand || 'PriceMonkey';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

const SOURCES = [
  ['Second-hand', 193, ['tori', 'blocket', 'finn', 'dba', 'kleinanzeigen', 'marktplaats', '2dehands', 'olx_pl', 'vinted',
    'gumtree', 'leboncoin', 'wallapop', 'subito', 'willhaben', 'ebay_de']],
  ['Refurbished', 0, ['backmarket', 'rebuy']],
  ['Shops', 0, ['amazon_de', 'verkkokauppa', 'power_fi', 'cdiscount', 'idealo', 'pricerunner']],
];

const TOOLS = [
  ['find_offers', 'query, country?, max_price_eur?, conditions?, limit?', 'offers ranked by all-in price, plus a one-line verdict'],
  ['get_offer', 'url', 'one offer we already read: price check, location, how it was read'],
  ['explain_price', 'url', 'its receipt: every line with its source'],
  ['watch_price', 'query, target_eur', 'notifies you when an offer hits the target. Never buys.'],
];

const CD_TOOLS = [
  ['search', 'finds the shops and listings for a question'],
  ['product', 'reads a product page: price, stock, condition'],
  ['extract', 'structured JSON from listing pages'],
  ['scrape', 'markdown of marketplace search results'],
];

// One worked example, used by every section below: a read of "sony a7 iii body" for a buyer in Finland.
const EX = {
  n: 17,
  rows: [
    { dom: 'allenscamera.net', from: 'United States', tag: 633.32, vat: 161.50, all: 794.82, eu: false, ships: 'not confirmed by the shop' },
    { dom: 'tori.fi', from: 'Finland', tag: 825, vat: 0, all: 825, eu: true, ships: 'domestic' },
    { dom: 'wexphotovideo.com', from: 'United Kingdom', tag: 978.95, vat: 0, all: 1023.82, eu: false, ships: 'not confirmed by the shop' },
  ],
};
const eur = (v, d = 2) => '€' + Number(v).toLocaleString('en-IE', { minimumFractionDigits: d, maximumFractionDigits: d });
const fav = (dom, sz = 16) => `<img src="https://www.google.com/s2/favicons?domain=${esc(dom)}&amp;sz=64" alt="" width="${sz}" height="${sz}" loading="lazy" data-fb="sq">`;

// ---------- small pieces ----------
const head = (n, kicker, h, id) => `<p class="ld-kicker"><span class="ld-n">${n}</span>${esc(kicker)}</p><h2 class="ld-h" id="${id}">${h}</h2>`;

// ---------- sections ----------
function stripHtml() {
  return `<aside class="ld-strip" id="ld-cd" aria-labelledby="ld-cd-h">
    <div class="ld-strip-in ld-rv">
      <div class="ld-strip-top">
        <h2 class="ld-strip-h" id="ld-cd-h">Powered by <a class="ld-strip-mark" href="https://context.dev" target="_blank" rel="noopener">${fav('context.dev', 28)}Context.dev</a></h2>
        <p class="ld-strip-count"><span class="ld-pulse" aria-hidden="true"></span><span><b>48</b> pages on <b>35</b> sites, read live in the recorded hunts</span></p>
      </div>
      <ul class="ld-strip-tools" role="list">
        ${CD_TOOLS.map(([k, v]) => `<li><b>${k}</b><span>${esc(v)}</span></li>`).join('')}
      </ul>
    </div>
  </aside>`;
}

function whyHtml() {
  const rows = [
    ['A dozen tabs: a marketplace here, a refurbisher there, a shop in another country.', 'One search box.'],
    ['New, refurbished and used each live on different sites.', 'Every way to buy it, on one line.'],
    ['Prices in dollars, pounds and kronor.', 'Everything in euros.'],
    ['Shipping and import VAT show up at checkout.', 'Counted before you look, and marked when a shop will not say.'],
    ['No idea whether a seller even ships to you.', 'Where it ships from, and whether it reaches you.'],
    ['Sponsored results first.', 'No paid placements. The cheapest all-in price comes first.'],
  ];
  return `<section class="ld-band" id="ld-why" aria-labelledby="ld-why-h">
    <div class="ld-in ld-why">
      <header class="ld-head ld-rv">
        ${head('01', 'The problem', 'Buying online is a research project.', 'ld-why-h')}
        <p class="ld-sub">The same camera is on a marketplace in Finland, at a refurbisher in Germany and in a shop in the United States. Each has its own currency, its own shipping and its own fine print, and none of them will tell you about the others.</p>
        <p class="ld-sub">Comparing them properly takes an evening. So most of us check two sites, pick one and hope.</p>
        <p class="ld-gap">${esc(brand())} does the evening for you,<br><b>while you watch.</b></p>
      </header>
      <div class="ld-vs ld-rv" role="table" aria-label="Buying on your own, and with ${esc(brand())}">
        <div class="ld-vs-r ld-vs-h" role="row"><span role="columnheader">On your own</span><span role="columnheader">With ${esc(brand())}</span></div>
        ${rows.map(([x, y]) => `<div class="ld-vs-r" role="row"><span role="cell">${esc(x)}</span><span role="cell">${esc(y)}</span></div>`).join('')}
      </div>
    </div>
  </section>`;
}

// three small mock-ups, drawn from the worked example
function mockAsk() {
  return `<div class="ld-mock m-ask" aria-hidden="true">
    <div class="mk-box"><span>Sony A7 III camera</span><i></i><b>→</b></div>
    <div class="mk-pills"><span>iPhone 15, used</span><span>Home cleaning, Helsinki</span><span>City bike with basket</span></div>
  </div>`;
}
function mockRead() {
  return `<div class="ld-mock m-read" aria-hidden="true">
    ${EX.rows.map(r => `<div class="mk-row">${fav(r.dom)}<b>${esc(r.dom)}</b><span>${esc(r.from)}</span></div>`).join('')}
    <div class="mk-row mk-more"><span class="ld-pulse"></span><span>${EX.n} offers read, ${EX.n - EX.rows.length} more below these</span></div>
  </div>`;
}
function mockLine() {
  const lo = 600, hi = 1050, x = v => ((v - lo) / (hi - lo) * 100).toFixed(1);
  const [us, fi, gb] = EX.rows;
  return `<div class="ld-mock m-line" aria-hidden="true">
    <div class="mk-axis">
      <i class="mk-hop" style="left:${x(us.tag)}%; width:${(x(us.all) - x(us.tag)).toFixed(1)}%"><em>+ ${eur(us.vat, 0)} import VAT</em></i>
      <i class="mk-dot mk-tag" style="left:${x(us.tag)}%"><em class="dn">${eur(us.tag, 0)} tag</em></i>
      <i class="mk-dot" style="left:${x(us.all)}%"><em class="dn">${eur(us.all, 0)}</em></i>
      <i class="mk-dot pick" style="left:${x(fi.all)}%"><em class="up">${eur(fi.all, 0)}</em></i>
      <i class="mk-dot" style="left:${x(gb.all)}%"><em class="dn end">${eur(gb.all, 0)}</em></i>
    </div>
  </div>`;
}
function howHtml() {
  const steps = [
    [mockAsk(), 'You ask once.', 'Say what you want in plain words: a camera, a used iPhone, someone to clean your flat. No categories to pick, no filters to set.'],
    [mockRead(), 'We do the legwork, live.', 'Context.dev reads marketplace searches and shop pages for you: price, condition, shipping and where it ships from. The evening of tabs happens while you watch.'],
    [mockLine(), 'You see what you’d really pay.', 'Every offer lands on one euro line at tag + shipping + import VAT + fees. The cheapest you can surely buy gets the circle.'],
  ];
  return `<section class="ld-band alt" id="ld-how" aria-labelledby="ld-how-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('02', 'How it works', 'One question. Every shop. One line.', 'ld-how-h')}
        <p class="ld-sub">One real example, start to finish: a used Sony A7 III body for a buyer in Finland.</p>
      </header>
      <ol class="ld-steps" role="list">
        ${steps.map(([m, t, b], i) => `<li class="ld-step ld-rv" style="--d:${i * 80}ms">${m}<h3><span class="ld-n">${i + 1}</span>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <p class="ld-after ld-rv">Not ready? Drag your price onto the line and we’ll watch it for you.</p>
    </div>
  </section>`;
}
function receipt(r, i) {
  const line = (k, v, cls = '') => `<div class="rc-l ${cls}"><span>${k}</span><span>${v}</span></div>`;
  return `<figure class="ld-rc ld-rv" style="--d:${i * 80}ms">
    <figcaption>${fav(r.dom)}<b>${esc(r.dom)}</b><span>ships from ${esc(r.from)} · used</span></figcaption>
    ${line('Tag', eur(r.tag))}
    ${line('Shipping', 'unknown, not included', 'q')}
    ${line(r.eu ? 'Import VAT' : 'Import VAT, estimated', r.eu ? 'none, inside the EU' : '+ ' + eur(r.vat), r.eu ? 'q' : 'add')}
    ${line('All in', eur(r.all), 'sum')}
    <p class="rc-n">Ships to Finland: ${esc(r.ships)}.</p>
  </figure>`;
}
function priceHtml() {
  const [us, fi] = EX.rows;
  return `<section class="ld-band" id="ld-price" aria-labelledby="ld-price-h">
    <div class="ld-in ld-price">
      <header class="ld-head ld-rv">
        ${head('03', 'The all-in price', 'The sticker is not the price.', 'ld-price-h')}
        <p class="ld-sub">The cheapest listing is often not the cheapest purchase. Shipping, import VAT and fees turn up at checkout, after you have already decided. We add them before you look, say where each number came from, and mark anything a shop would not confirm.</p>
        <p class="ld-gap"><b>${eur(fi.tag - us.tag, 0)}</b> apart on the sticker.<br><b>${eur(fi.all - us.all, 0)}</b> apart at your door.</p>
        <p class="ld-own">And what it costs to own: buy at ${eur(fi.all, 0)}, resell in 12 months for about €715. That is €9.16 a month.</p>
      </header>
      <div class="ld-rcs">${[us, fi].map(receipt).join('')}</div>
    </div>
  </section>`;
}
function sourcesHtml() {
  const lanes = [
    ['The open web', 'A fresh web search for every question, in English and in the local language. Guides, news and forums are dropped. Any shop that sells it stays, whether we have heard of it or not.'],
    ['Marketplaces, searched directly', 'The big European marketplaces are read through their own search pages, around twenty listings per read. 193 second-hand sources are known by name.'],
    ['The long tail', 'Small providers that live on their own sites: found through “best of” articles and look-alikes, priced from their pricing pages, and remembered for the next search.'],
  ];
  return `<section class="ld-band alt" id="ld-sources" aria-labelledby="ld-sources-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('04', 'Sources', 'Anywhere it’s sold.', 'ld-sources-h')}
        <p class="ld-sub">There is no fixed list of shops. Every question starts with a live search of the web, so an offer can come from any shop that sells it. Three ways in:</p>
      </header>
      <ol class="ld-lanes" role="list">
        ${lanes.map(([t, b], i) => `<li class="ld-rv" style="--d:${i * 80}ms"><span class="ld-n">${'abc'[i]}</span><h3>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <p class="ld-wall-h ld-rv"><b>A few of the places we read</b><span>examples, not the full list</span></p>
      <div class="ld-wall"></div>
      <p class="ld-foot ld-rv">Brand marks fetched by the Context.dev brand API · free JSON-LD first, Context.dev where it matters.</p>
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
// what the curl line gives back, trimmed to the fields an agent ranks on
function sampleJson() {
  const [us] = EX.rows;
  const k = s => `<span class="tk-k">"${s}"</span>`, v = s => `<span class="tk-v">${s}</span>`, c = s => `<span class="tk-p">${s}</span>`;
  return [
    `{`,
    `  ${k('query')}: ${v('"sony a7 iii body"')},`,
    `  ${k('n_offers')}: ${v(EX.n)},`,
    `  ${k('ranked_by')}: ${v('"all_in_eur ascending"')},`,
    `  ${k('offers')}: [`,
    `    {`,
    `      ${k('title')}: ${v('"Used Sony a7 III Body"')},`,
    `      ${k('condition')}: ${v('"used"')},`,
    `      ${k('price_eur')}: ${v(us.tag)},`,
    `      ${k('all_in_eur')}: ${v(us.all)},`,
    `      ${k('source')}: ${v('"' + us.dom + '"')},`,
    `      ${k('origin')}: { ${k('country_code')}: ${v('"US"')}, ${k('eu')}: ${v('false')} },`,
    `      ${k('flags')}: [${v('"outside the EU (USD): import VAT added"')}]`,
    `    },`,
    `    ${c('… 2 more')}`,
    `  ]`,
    `}`,
  ].join('\n');
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
  return `<section class="ld-band" id="ld-agents" aria-labelledby="ld-agents-h">
    <div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('05', 'For agents', 'Same line, for your agent.', 'ld-agents-h')}
        <p class="ld-sub">Agents get the same offers in the same order, ranked by all-in price, over MCP or plain JSON. Read-only: ${esc(brand())} never buys for an agent.</p>
      </header>
      <div class="ld-agent">
        <div class="ld-codes">
          ${block('mcp', 'MCP, for Claude Code · run it in the repo folder')}
          ${block('http', 'Plain JSON over HTTP')}
          <p class="ld-links ld-rv"><a href="#agent" class="ld-agent-demo">what an agent sees →</a><a href="/api">API index →</a></p>
        </div>
        <figure class="ld-code ld-json ld-rv"><figcaption>What comes back · trimmed</figcaption><pre><code>${sampleJson()}</code></pre></figure>
      </div>
      <div class="ld-tools ld-rv" role="table" aria-label="MCP tools">
        <div class="ld-tr ld-th" role="row"><span role="columnheader">tool</span><span role="columnheader">takes</span><span role="columnheader">gives back</span></div>
        ${TOOLS.map(([n, a, r]) => `<div class="ld-tr" role="row"><code role="cell">${n}</code><span role="cell" class="ld-args">${esc(a)}</span><span role="cell">${esc(r)}</span></div>`).join('')}
      </div>
    </div>
  </section>`;
}

async function getJson(url) {
  try { const r = await fetch(url, { headers: { accept: 'application/json' } }); return r.ok ? await r.json() : null; }
  catch { return null; }
}

function brandsWall(el, brands) {
  el.innerHTML = SOURCES.map(([label, total, keys], g) => {
    const list = keys.map(k => brands && brands[k]).filter(Boolean);
    const cells = list.map(b => {
      const mono = esc((b.name || b.domain || '?').charAt(0));
      return `<li title="${esc(b.domain)}"><span class="ld-logo" data-mono="${mono}">${b.logo
        ? `<img src="${esc(b.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<i>${mono}</i>`}</span><span class="ld-bn">${esc(b.name)}</span></li>`;
    }).join('');
    const more = total > list.length ? `<li class="ld-more"><span class="ld-logo"><i>+${total - list.length}</i></span><span class="ld-bn">more</span></li>` : `<li class="ld-more"><span class="ld-logo"><i>+</i></span><span class="ld-bn">any other</span></li>`;
    return `<div class="ld-group ld-rv" style="--d:${g * 60}ms"><p class="ld-gl">${esc(label)}</p><ul role="list">${cells}${more}</ul></div>`;
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
  el.insertAdjacentHTML('beforeend', stripHtml() + whyHtml() + howHtml() + priceHtml() + sourcesHtml() + agentsHtml());
  if (cue) el.prepend(cue);
  getJson('/web/assets/brands.json').then(b => {
    const wall = el.querySelector('.ld-wall');
    brandsWall(wall, b || {}); fallbacks(wall); reveal(wall);
  });
  fallbacks(el); reveal(el);

  el.addEventListener('click', e => {
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
      const t = el.querySelector('#ld-why');
      if (t) t.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
    }
  });
}
