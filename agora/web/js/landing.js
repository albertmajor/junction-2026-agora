// The landing page under the start search. It sells PriceMonkey in the order a doubter needs:
// Context.dev banner → the problem → watch it happen → be as specific as you like → the all-in price (proof)
// → anywhere it's sold → honest by design → for agents → go on, ask.
// Every number is real: the recorded "sony a7 iii body" hunt for a buyer in Finland (tests/fixtures/
// live_sony-a7-iii-body.jsonl), the four recorded hunts, and marketplaces.py (193 second-hand sources).
// main.js calls mountLanding($('landing')) and listens for the bus event 'ask' {q}.
import * as core from './core.js';
import { queryFor } from './stream.js';

const brand = () => core.BRAND || document.documentElement.dataset.brand || 'PriceMonkey';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// What real testers told us, word for word: { quote, who }. It ships empty and the strip stays hidden until it isn't.
// Never put an invented or paraphrased quote here.
export const REAL_QUOTES = [];

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

// The four recorded hunts (Sony A7 III, iPhone 15, home cleaning in Helsinki, a city bike): `source` events and
// their distinct domains. Recount from tests/fixtures/live_*.jsonl if a recording changes.
const READ = { pages: 80, sites: 64, hunts: 4 };

// The worked example: a read of "sony a7 iii body" for a buyer in Finland (recorded live).
const EX = {
  n: 17, skipped: 23, firstPickS: 3.4, doneS: 20,
  rows: [
    { dom: 'allenscamera.net', from: 'United States', orig: '$699.95', tag: 633.32, vat: 161.50, all: 794.82, eu: false, ships: 'not confirmed by the shop' },
    { dom: 'tori.fi', from: 'Finland', orig: '', tag: 825, vat: 0, all: 825, eu: true, ships: 'domestic' },
    { dom: 'wexphotovideo.com', from: 'United Kingdom', orig: '£818', tag: 978.95, vat: 0, all: 1023.82, eu: false, ships: 'not confirmed by the shop' },
  ],
};
const eur = (v, d = 2) => '€' + Number(v).toLocaleString('en-IE', { minimumFractionDigits: d, maximumFractionDigits: d });
const fav = (dom, sz = 16) => `<img src="https://www.google.com/s2/favicons?domain=${esc(dom)}&amp;sz=64" alt="" width="${sz}" height="${sz}" loading="lazy" data-fb="sq">`;

// ---------- small pieces ----------
const head = (n, kicker, h, id) => `<p class="ld-kicker">${n ? `<span class="ld-n">${n}</span>` : ''}${esc(kicker)}</p><h2 class="ld-h" id="${id}">${h}</h2>`;
const band = (id, tone, inner, extra = '') => `<section class="ld-band t-${tone}${extra ? ' ' + extra : ''}" id="${id}" aria-labelledby="${id}-h">${inner}</section>`;

// ---------- 0. Context.dev ----------
function bannerHtml() {
  const pts = [
    ['Reads what the page knows', 'Shops hide the real product data (price, stock, condition) in structured data behind the page. Context.dev reads that, not just the words you see.'],
    ['Gets past the walls', 'Every shop builds its pages its own way, and plenty block fast readers. Context.dev deals with page structures and rate blocks, so one stubborn shop never stalls the hunt.'],
    ['Search, product, extract, scrape', 'It finds the shops for your question, reads product pages, pulls JSON from listings and turns marketplace searches into rows we can rank.'],
  ];
  return `<aside class="ld-band t-ink ld-cd" id="ld-cd" aria-labelledby="ld-cd-h">
    <div class="ld-in">
      <div class="ld-cd-top ld-rv">
        <div>
          <p class="ld-kicker">Powered by <a class="ld-cd-mark" href="https://context.dev" target="_blank" rel="noopener">${fav('context.dev', 22)}Context.dev</a></p>
          <h2 class="ld-h ld-h-xl" id="ld-cd-h">Reading the internet’s shops is hard. <span>Context.dev makes it our job, not yours.</span></h2>
        </div>
        <div class="ld-cd-count"><p><b>${READ.pages}</b><span>pages read</span></p><p><b>${READ.sites}</b><span>sites</span></p><p class="ld-cd-live"><span class="ld-pulse" aria-hidden="true"></span>read live in our ${READ.hunts} recorded hunts</p></div>
      </div>
      <ul class="ld-cd-pts" role="list">
        ${pts.map(([t, b], i) => `<li class="ld-rv" style="--d:${i * 70}ms"><h3>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ul>
      <p class="ld-cd-link ld-rv"><a href="https://context.dev" target="_blank" rel="noopener">context.dev →</a></p>
    </div>
  </aside>`;
}

// ---------- 1. the problem ----------
function whyHtml() {
  const [us, fi] = EX.rows;
  const night = [
    ['21:04', `tori.fi: a used Sony A7 III for <b>${eur(fi.tag, 0)}</b>, here in Finland. Is that a good price? No idea.`],
    ['21:11', `A shop in the US has one for <b>${esc(us.orig)}</b>. Cheaper! In dollars.`],
    ['21:14', `A currency-converter tab. <b>${eur(us.tag, 0)}</b>. Still cheaper.`],
    ['21:26', `Checkout. Import VAT: about <b>+${eur(us.vat, 0)}</b>. Shipping: “calculated at the next step”.`],
    ['21:33', 'Does it even ship to Finland? The shop never says.'],
    ['21:47', 'A comparison site. The first three results are sponsored.'],
    ['22:20', 'Fourteen tabs later you buy the first one you saw, and hope.'],
  ];
  return band('ld-why', 'cream', `<div class="ld-in ld-split">
      <header class="ld-head ld-rv">
        ${head('01', 'The problem', 'Buying online shouldn’t be a research project.', 'ld-why-h')}
        <p class="ld-sub">The camera you want is on a marketplace in Finland, in a shop in the US and at a refurbisher in South Africa. Our one recorded hunt for it met prices in euros, dollars, pounds and rand. Every shop has its own shipping and its own fine print, and none of them mentions the others.</p>
        <p class="ld-pull">Fourteen tabs. <em>One camera.</em></p>
      </header>
      <figure class="ld-night ld-rv" style="--d:80ms" aria-label="A Tuesday night of comparing prices">
        <div class="ld-tabs" aria-hidden="true">${Array.from({ length: 14 }, (_, i) => `<i${i === 13 ? ' class="on"' : ''}></i>`).join('')}</div>
        <figcaption>Tuesday night</figcaption>
        <ol role="list">${night.map(([t, s]) => `<li><time>${t}</time><span>${s}</span></li>`).join('')}</ol>
        <p class="ld-night-end">${esc(brand())} does the evening for you, <b>in under a minute.</b></p>
      </figure>
    </div>`);
}

// ---------- 2. watch it happen (three small mock-ups, drawn from the worked example) ----------
function mockAsk() {
  return `<div class="ld-mock m-ask" aria-hidden="true">
    <div class="mk-box"><span>Sony A7 III body</span><i></i><b>→</b></div>
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
    [mockAsk(), 'Ask in plain words.', 'A camera, a used iPhone, someone to clean your flat. No categories to pick, no filters to find.'],
    [mockRead(), 'Prices snow in.', 'Context.dev reads the shops while you watch, and each offer drops onto the line the moment it’s priced. Nobody waits for the slowest shop.'],
    [mockLine(), 'The pick lands, all in.', 'Every offer sits on one euro line at tag + shipping + import VAT + fees. The cheapest one you can surely buy gets the circle, often before the last shop has answered.'],
  ];
  return band('ld-how', 'paper', `<div class="ld-in">
      <div class="ld-headrow">
        <header class="ld-head ld-rv">
          ${head('02', 'Watch it happen', 'Ask once. Watch every shop answer.', 'ld-how-h')}
          <p class="ld-sub">Offers stream in as each page is read, so you watch the market take shape instead of waiting for a list.</p>
        </header>
        <p class="ld-stat ld-rv" style="--d:60ms"><b>${EX.firstPickS} s</b><span>to the first pick in our recorded Sony A7 III hunt. All ${EX.n} offers in ${EX.doneS} s.</span></p>
      </div>
      <ol class="ld-steps" role="list">
        ${steps.map(([m, t, b], i) => `<li class="ld-step ld-rv" style="--d:${i * 80}ms">${m}<h3><span class="ld-n">${i + 1}</span>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <p class="ld-after ld-rv">Not ready yet? Drag your price onto the line and we’ll watch it for you.</p>
    </div>`);
}

// ---------- 3. be as specific as you like ----------
// marks: the words in the query that carry a constraint, with a tag saying what we heard. tone: ok | flag | plain
const SPECIFIC = [
  { q: 'PS5 Pro, no GTA bundle, delivered to Helsinki',
    marks: [['no GTA bundle', 'flag'], ['delivered to Helsinki', 'ok']],
    tags: [['exact model: PS5 Pro', 'plain'], ['not the GTA bundle', 'flag'], ['delivery: Helsinki', 'ok']] },
  { q: 'Sony A7 III body only, used is fine, under €900',
    marks: [['body only', 'plain'], ['used is fine', 'ok'], ['under €900', 'ok']],
    tags: [['body, no lens', 'plain'], ['condition: used OK', 'ok'], ['budget: €900', 'ok']] },
  { q: 'someone to clean a 2-room flat in Kallio on Friday',
    marks: [['2-room flat', 'plain'], ['in Kallio', 'ok']],
    tags: [['a service, not a product', 'plain'], ['size: 2 rooms', 'plain'], ['place: Kallio', 'ok']] },
  { q: 'city bike with a basket, pickup near me',
    marks: [['with a basket', 'flag'], ['pickup near me', 'ok']],
    tags: [['must have: basket', 'flag'], ['local pickup', 'ok']] },
];
function markQuery({ q, marks }) {
  let html = esc(q);
  for (const [w, tone] of marks) html = html.replace(esc(w), `<mark class="k-${tone}">${esc(w)}</mark>`);
  return html;
}
function specificHtml() {
  return band('ld-spec', 'sun', `<div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('03', 'Be as specific as you like', 'Say it like you’d say it to a friend.', 'ld-spec-h')}
        <p class="ld-sub">Budgets, places, conditions and must-haves come straight out of your sentence. No filter panel, no boxes to tick. Try one:</p>
      </header>
      <ul class="ld-qs" role="list">
        ${SPECIFIC.map((s, i) => `<li class="ld-rv" style="--d:${(i % 2) * 70 + Math.floor(i / 2) * 50}ms">
          <button type="button" class="ld-q" data-q="${esc(s.q)}" aria-label="Search: ${esc(s.q)}">
            <span class="ld-q-text">“${markQuery(s)}”</span>
            <span class="ld-q-tags">${s.tags.map(([t, tone]) => `<span class="ld-tag k-${tone}">${esc(t)}</span>`).join('')}</span>
            <span class="ld-q-go">Run this search <span aria-hidden="true">→</span></span>
          </button>
        </li>`).join('')}
      </ul>
      <div class="ld-ask ld-rv">
        <p class="ld-ask-k">If it could mean a few things, we ask:</p>
        <p class="ld-pull ld-pull-c">“That could be a few things. Which one?”</p>
        <p class="ld-ask-s">and keep hunting the likeliest one while you decide.</p>
      </div>
    </div>`);
}

// ---------- 4. the all-in price ----------
function receipt(r, i) {
  const line = (k, v, cls = '') => `<div class="rc-l ${cls}"><span>${k}</span><span>${v}</span></div>`;
  return `<figure class="ld-rc ld-rv${r.eu ? ' pick' : ''}" style="--d:${i * 80}ms">
    <figcaption>${fav(r.dom)}<b>${esc(r.dom)}</b><span>ships from ${esc(r.from)} · used</span></figcaption>
    ${line('Tag', r.orig ? `<span class="rc-o">${esc(r.orig)} →</span> ${eur(r.tag)}` : eur(r.tag))}
    ${line('Shipping', 'not quoted, counted as €0', 'q')}
    ${line(r.eu ? 'Import VAT' : 'Import VAT, estimated', r.eu ? 'none, inside the EU' : '+ ' + eur(r.vat), r.eu ? 'q' : 'add')}
    ${line('All in', eur(r.all), 'sum')}
    <p class="rc-n">Ships to Finland: ${esc(r.ships)}.${r.eu ? ' <b>Our pick.</b>' : ''}</p>
  </figure>`;
}
function priceHtml() {
  const [us, fi] = EX.rows;
  return band('ld-price', 'paper', `<div class="ld-in ld-split ld-flip">
      <div class="ld-rcs">${[us, fi].map(receipt).join('')}</div>
      <header class="ld-head ld-rv">
        ${head('04', 'The all-in price', 'The sticker is not the price.', 'ld-price-h')}
        <p class="ld-pull">${eur(us.tag, 0)} on the tag. <em>${eur(us.all, 0)} at your door.</em></p>
        <p class="ld-sub">Shipping, import VAT and fees turn up at checkout, after you’ve already decided. We add them before you look, say where each number came from, and mark anything a shop won’t confirm.</p>
        <p class="ld-gap"><b>${eur(fi.tag - us.tag, 0)}</b> cheaper on the sticker. Only <b>${eur(fi.all - us.all, 0)}</b> at your door, before a shipping fee nobody quoted, from a shop that never said it ships to Finland. We picked the one in Finland.</p>
        <p class="ld-fx">Converted to euros at the day’s ECB reference rate. The shop’s own price stays with every offer: ${esc(us.orig)} here.</p>
        <p class="ld-own">And what it costs to own: buy at ${eur(fi.all, 0)}, resell in 12 months for about €715. That’s €9.16 a month.</p>
      </header>
    </div>`);
}

// ---------- 5. sources ----------
function sourcesHtml() {
  const lanes = [
    ['The open web', 'A fresh web search for every question, in English and in the local language. Guides, news and forums are dropped. Any shop that sells it stays, whether we’ve heard of it or not.'],
    ['Marketplaces, searched directly', 'The big European marketplaces are read through their own search pages, around twenty listings per read. 193 second-hand sources are known by name.'],
    ['The long tail', 'Small providers on their own sites: found through “best of” articles and look-alikes, priced from their pricing pages, and remembered for next time.'],
  ];
  return band('ld-sources', 'cream', `<div class="ld-in">
      <div class="ld-headrow">
        <header class="ld-head ld-rv">
          ${head('05', 'Sources', 'Anywhere it’s sold.', 'ld-sources-h')}
          <p class="ld-sub">If a shop sells it, we can find it. Every question starts with a live search of the web, so an offer can come from a shop we’d never heard of a minute earlier. Three ways in:</p>
        </header>
        <p class="ld-pull ld-rv" style="--d:60ms">There’s no list.</p>
      </div>
      <ol class="ld-lanes" role="list">
        ${lanes.map(([t, b], i) => `<li class="ld-rv" style="--d:${i * 80}ms"><span class="ld-n">${'abc'[i]}</span><h3>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <p class="ld-wall-h ld-rv"><b>A few places we’ve read</b><span>examples, not the list</span></p>
      <div class="ld-wall"></div>
      <p class="ld-foot ld-rv">Brand marks from the Context.dev brand API · free JSON-LD first, Context.dev where it matters.</p>
    </div>`);
}

// ---------- 6. honest by design ----------
function quotesHtml() {
  const qs = (Array.isArray(REAL_QUOTES) ? REAL_QUOTES : []).filter(x => x && x.quote);
  if (!qs.length) return '';
  return `<ul class="ld-quotes" role="list" aria-label="What testers told us">${qs.map((x, i) =>
    `<li class="ld-rv" style="--d:${i * 70}ms"><blockquote>“${esc(x.quote)}”</blockquote>${x.who ? `<p>${esc(x.who)}</p>` : ''}</li>`).join('')}</ul>`;
}
function honestHtml() {
  const pts = [
    ['Ranked by what you pay.', 'The all-in price sets the order. Not who pays us, not who shouts loudest. No paid placements.'],
    ['We may earn a fee, never a better spot.', 'If a shop ever pays us for a click, it still sits exactly where its all-in price puts it.'],
    ['We show what we left out, and why.', 'Offers we didn’t count stay in view with the reason: a different model, a dead link, a shop too slow to answer.'],
  ];
  return band('ld-honest', 'sky', `<div class="ld-in ld-narrow">
      <header class="ld-head ld-rv">
        ${head('06', 'Honest by design', 'Built to be on your side of the till.', 'ld-honest-h')}
      </header>
      <p class="ld-big ld-rv"><b>${EX.skipped}</b><span>pages set aside in the Sony hunt, each with its reason. One was an A7R III: close, but a different camera.</span></p>
      <ol class="ld-promises" role="list">
        ${pts.map(([t, b], i) => `<li class="ld-rv" style="--d:${i * 70}ms"><h3>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      ${quotesHtml()}
    </div>`);
}

// ---------- 7. for agents ----------
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
  return band('ld-agents', 'paper', `<div class="ld-in">
      <div class="ld-headrow">
        <header class="ld-head ld-rv">
          ${head('07', 'For agents', 'Your agent gets the same line.', 'ld-agents-h')}
          <p class="ld-sub">Same offers, same order, same all-in prices, over MCP or plain JSON. One call instead of a scraper per shop.</p>
        </header>
        <p class="ld-pull ld-rv" style="--d:60ms">Read-only. <em>It never buys.</em></p>
      </div>
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
    </div>`);
}

// ---------- 8. close ----------
function closeHtml() {
  return band('ld-close', 'sun', `<div class="ld-in ld-close-in ld-rv">
      <img class="ld-banana" src="/web/assets/mascot/banana.png" alt="" width="54" height="34" loading="lazy">
      <h2 class="ld-close-h" id="ld-close-h">What do you want to <em>buy</em>?</h2>
      <p class="ld-close-s">Go on, ask the monkey. Every shop answers, all in, in under a minute.</p>
      <button type="button" class="ld-cta">Start a search <span aria-hidden="true">↑</span></button>
    </div>`);
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

// the closing button: back to the box, cursor in it (focus without a second jump)
function toBox() {
  const qIn = document.getElementById('q');
  scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' });
  if (qIn) { try { qIn.focus({ preventScroll: true }); } catch { qIn.focus(); } }
}

function fallbacks(root) {
  root.querySelectorAll('img').forEach(img => {
    if (img.dataset.fbOn) return;
    img.dataset.fbOn = '1';
    img.addEventListener('error', () => {
      if (img.dataset.fb === 'sq') { const i = document.createElement('i'); i.className = 'cd-sq'; img.replaceWith(i); return; }
      const lg = img.closest('.ld-logo');
      if (lg) { const i = document.createElement('i'); i.textContent = lg.dataset.mono || ''; img.replaceWith(i); return; }
      img.remove();
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
  el.insertAdjacentHTML('beforeend', bannerHtml() + whyHtml() + howHtml() + specificHtml() + priceHtml()
    + sourcesHtml() + honestHtml() + agentsHtml() + closeHtml());
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
    const q = e.target.closest('.ld-q');
    if (q) { ask(q.dataset.q); return; }
    if (e.target.closest('.ld-cta')) { toBox(); return; }
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
      const t = el.querySelector('#ld-cd');
      if (t) t.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
    }
  });
}
