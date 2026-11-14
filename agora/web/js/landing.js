// The landing page under the start search. It sells PriceMonkey in the order a doubter needs:
// Context.dev banner → the problem → watch it happen → be as specific as you like → the all-in price (proof)
// → anywhere it's sold → honest by design → for agents → go on, ask.
// Every number is real: the recorded "sony a7 iii body" hunt for a buyer in Finland (tests/fixtures/
// live_sony-a7-iii-body.jsonl), the four recorded hunts, and marketplaces.py (124 second-hand sources:
// len(agora.marketplaces.SECOND_HAND); recount if that registry grows).
// main.js calls mountLanding($('landing')) and listens for the bus event 'ask' {q}.
import * as core from './core.js';
import { queryFor, liveReady, isLive, recordings } from './stream.js';

const brand = () => core.BRAND || document.documentElement.dataset.brand || 'PriceMonkey';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// What real testers told us, word for word: { quote, who }. It ships empty and the strip stays hidden until it isn't.
// Never put an invented or paraphrased quote here.
export const REAL_QUOTES = [];

const SOURCES = [
  ['Second-hand', 124, ['tori', 'blocket', 'finn', 'dba', 'kleinanzeigen', 'marktplaats', '2dehands', 'olx_pl', 'vinted',
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
// their distinct domains (80 pages, 64 sites). Recount from tests/fixtures/live_*.jsonl if a recording changes.
// Shown per question: 80 / 4 and 64 / 4.
const READ = { pages: 80, sites: 64, hunts: 4 };
const perQ = k => Math.round(READ[k] / READ.hunts);

// The worked example: a read of "sony a7 iii body" for a buyer in Finland (recorded live).
const EX = {
  n: 17, skipped: 23, firstPickS: 3.4, doneS: 20,
  rows: [
    { dom: 'allenscamera.net', from: 'United States', orig: '$699.95', tag: 633.32, vat: 161.50, all: 794.82, eu: false, ships: 'not confirmed by the shop' },
    { dom: 'tori.fi', from: 'Finland', orig: '', tag: 825, vat: 0, all: 825, eu: true, ships: 'domestic' },
    { dom: 'wexphotovideo.com', from: 'United Kingdom', orig: '£818', tag: 978.95, vat: 0, all: 1023.82, eu: false, ships: 'not confirmed by the shop' },
  ],
  // the other offers' all-in prices (tag, plus import VAT outside the EU), for the faint dots on the price line;
  // 12 of the 16 costed offers sit right of the drawn range. mpb.com's €239 was flagged, not costed.
  faint: [1029, 1063.49],
  dearer: 12, dearestAll: 1817,
  odd: { dom: 'mpb.com', tag: 239, median: 949, under: 75 },
  // the 23 pages set aside, by reason (from the recording's `skip` events)
  set: { model: 1, dead: 1, noPrice: 2, slow: 4, capped: 15 },
};
const eur = (v, d = 2) => '€' + Number(v).toLocaleString('en-IE', { minimumFractionDigits: d, maximumFractionDigits: d });
const fav = (dom, sz = 16) => `<img src="https://www.google.com/s2/favicons?domain=${esc(dom)}&amp;sz=64" alt="" width="${sz}" height="${sz}" loading="lazy" data-fb="sq">`;

// ---------- small pieces ----------
const head = (n, kicker, h, id, cls = '') => `<p class="ld-kicker">${n ? `<span class="ld-n">${n}</span>` : ''}${esc(kicker)}</p><h2 class="ld-h${cls ? ' ' + cls : ''}" id="${id}">${h}</h2>`;
const band = (id, tone, inner, extra = '') => `<section class="ld-band t-${tone}${extra ? ' ' + extra : ''}" id="${id}" aria-labelledby="${id}-h">${inner}</section>`;

// ---------- 0. Context.dev ----------
function bannerHtml() {
  const pts = [
    ['Sees the real price', 'Shops keep the real product data (price, stock, condition) in structured data behind the page. Context.dev reads that, not just the words you see.'],
    ['Never blocked, never stalled', 'Every shop builds its pages its own way, and plenty block fast readers. Context.dev handles both, so one stubborn shop never holds up your answer.'],
    ['Finds shops you didn’t know', 'One reader for every kind of page: search finds the shops for your question, product and extract read their pages, scrape turns marketplace searches into rows we can rank.'],
  ];
  return `<aside class="ld-band t-quiet ld-cd" id="ld-cd" aria-labelledby="ld-cd-h">
    <div class="ld-in">
      <div class="ld-cd-top ld-rv">
        <div>
          <p class="ld-kicker">Powered by <a class="ld-cd-mark" href="https://context.dev" target="_blank" rel="noopener">${fav('context.dev', 22)}Context.dev</a></p>
          <h2 class="ld-h ld-cd-h" id="ld-cd-h">PriceMonkey runs on Context.dev. <span>It reads every shop’s pages for you, live, while you watch.</span></h2>
        </div>
        <div class="ld-cd-count"><p><b>~${perQ('pages')}</b><span>pages read per question</span></p><p><b>${perQ('sites')}</b><span>sites on average</span></p><p class="ld-cd-live"><span class="ld-pulse" aria-hidden="true"></span>live, while you watch · across our first ${READ.hunts} hunts</p></div>
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
    ['22:20', `Fourteen tabs later you buy the <b>${eur(fi.all, 0)}</b> one you saw first, and still don’t know if it was a good price.`],
  ];
  return band('ld-why', 'cream', `<div class="ld-in ld-split">
      <header class="ld-head ld-rv">
        ${head('01', 'The problem', 'Buying online shouldn’t be a research project.', 'ld-why-h')}
        <p class="ld-value">One question. Every kind of shop: marketplaces, refurbishers, stores abroad. One price that includes shipping and import VAT. <b>A pick in seconds.</b></p>
        <p class="ld-sub">The camera you want is on a marketplace in Finland, in a shop in the US and at a refurbisher in South Africa. One search for it turned up euros, dollars, pounds and rand, and none of the shops mentions the others.</p>
        <p class="ld-pull">Fourteen tabs. <em>One camera.</em></p>
      </header>
      <figure class="ld-night ld-rv" style="--d:80ms" aria-label="A Tuesday night of comparing prices">
        <div class="ld-tabs" aria-hidden="true">${Array.from({ length: 14 }, (_, i) => `<i${i === 13 ? ' class="on"' : ''}></i>`).join('')}</div>
        <figcaption>Tuesday night</figcaption>
        <ol role="list">${night.map(([t, s]) => `<li><time>${t}</time><span>${s}</span></li>`).join('')}</ol>
        <p class="ld-night-end">${esc(brand())} would have told you at 21:04 and 20 seconds: <b>${eur(fi.all, 0)} is the best price that actually reaches you.</b></p>
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
    <div class="mk-row mk-more"><span class="ld-pulse"></span><span>${EX.n} offers read · ${EX.n - EX.rows.length} more</span></div>
  </div>`;
}
function mockLine() {
  // a zoomed window of the price line (one euro scale); the dearer offers run off to the right
  const lo = 610, hi = 1075, x = v => ((v - lo) / (hi - lo) * 100).toFixed(1);
  const [us, fi, gb] = EX.rows;
  return `<div class="ld-mock m-line" aria-hidden="true">
    <p class="mk-key"><span class="pk"></span>reaches you <span class="uq"></span>ships to Finland? unconfirmed</p>
    <div class="mk-axis">
      ${EX.faint.map(v => `<i class="mk-dot mk-faint" style="left:${x(v)}%"></i>`).join('')}
      <i class="mk-hop" style="left:${x(us.tag)}%; width:${(x(us.all) - x(us.tag)).toFixed(1)}%"><em>+${eur(us.vat, 0)} VAT</em></i>
      <i class="mk-dot mk-tag" style="left:${x(us.tag)}%"><em class="dn">${eur(us.tag, 0)} tag</em></i>
      <i class="mk-dot mk-unsure" style="left:${x(us.all)}%"><em class="dn">${eur(us.all, 0)}?</em></i>
      <i class="mk-dot pick" style="left:${x(fi.all)}%"><em class="up">${eur(fi.all, 0)}</em></i>
      <i class="mk-dot" style="left:${x(gb.all)}%"><em class="dn end">${eur(gb.all, 0)}</em></i>
      <i class="mk-dearer">+${EX.dearer} more →</i>
    </div>
  </div>`;
}
function howHtml() {
  const steps = [
    [mockAsk(), 'Ask in plain words.', 'A camera, a used iPhone, someone to clean your flat. No categories to pick, no filters to find.'],
    [mockRead(), 'Prices snow in.', 'Context.dev reads the shops while you watch, and each offer drops onto the line the moment it’s priced. Nobody waits for the slowest shop.'],
    [mockLine(), 'The pick lands, all in.', 'Every offer sits on the price line: one euro scale, tag + shipping + import VAT + fees. The cheapest one that surely reaches you gets the circle, often before the last shop has answered.'],
  ];
  return band('ld-how', 'paper', `<div class="ld-in">
      <div class="ld-headrow">
        <header class="ld-head ld-rv">
          ${head('02', 'Watch it happen', 'Ask once. Watch the shops answer.', 'ld-how-h')}
          <p class="ld-sub">Offers stream in as each page is read, and the cheapest real option is circled before the slowest shop answers.</p>
        </header>
        <p class="ld-stat ld-rv" style="--d:60ms"><b>${EX.firstPickS} s</b><span>to the first pick in our recorded Sony A7 III hunt. All ${EX.n} offers in ${EX.doneS} s.</span></p>
      </div>
      <ol class="ld-steps" role="list">
        ${steps.map(([m, t, b], i) => `<li class="ld-step ld-rv" style="--d:${i * 80}ms">${m}<h3><span class="ld-n">${i + 1}</span>${esc(t)}</h3><p>${esc(b)}</p></li>`).join('')}
      </ol>
      <div class="ld-after ld-rv">
        <p>Not ready yet? Drag your price onto the line and we’ll watch it for you.</p>
        <p>Buying used? We show what it costs to own: ${eur(EX.rows[1].all, 0)} now, about €715 back in a year, about €9 a month.</p>
      </div>
    </div>`);
}

// ---------- 3. be as specific as you like ----------
// Each card pairs a phrase in the sentence (the mark) with what we heard (the tag), same order, same tone:
// plain = what it is, ok = a constraint we act on. Only constraints the engine really uses (judges, F2): no
// exclusions until need.py learns "no X" (must_not). rec: the recorded search a card replays offline (null: live only).
const NB = ' ';
const SPECIFIC = [
  { q: `PS5 Pro, under${NB}€800, delivered to Helsinki`, rec: null,
    pairs: [['PS5 Pro', 'exact model: PS5 Pro', 'plain'], [`under${NB}€800`, 'budget: €800', 'ok'], ['delivered to Helsinki', 'delivery: Helsinki', 'ok']] },
  { q: `Sony A7 III body only, used, under${NB}€900`, rec: 'sony-a7-iii-body',
    pairs: [['body only', 'body, no lens', 'plain'], ['used', 'condition: used', 'ok'], [`under${NB}€900`, 'budget: €900', 'ok']] },
  { q: 'someone to clean a 2-room flat in Kallio', rec: 'home-cleaning-helsinki-60m2',
    pairs: [['someone to clean', 'a service, not a product', 'plain'], ['2-room flat', 'size: 2 rooms', 'plain'], ['in Kallio', 'place: Kallio', 'ok']] },
  { q: 'city bike with a basket, pickup near me', rec: 'city-bike-with-basket',
    pairs: [['city bike', 'what: city bike', 'plain'], ['with a basket', 'must have: basket', 'ok'], ['pickup near me', 'local pickup', 'ok']] },
];
function markQuery({ q, pairs }) {
  // replace left to right so a short phrase ("used") never matches inside an earlier mark
  let html = '', rest = q;
  for (const [w, , tone] of pairs) {
    const i = rest.indexOf(w);
    if (i < 0) continue;
    html += esc(rest.slice(0, i)) + `<mark class="k-${tone}">${esc(w)}</mark>`;
    rest = rest.slice(i + w.length);
  }
  return html + esc(rest);
}
// what a card (or a closing chip) sends: live, the words as written; offline, its recorded search
async function offlineRecs() {
  try { await liveReady; } catch { /* treated as offline */ }
  if (isLive()) return null;
  try { return await recordings(); } catch { return []; }
}
async function cardQuery(q, rec) {
  const recs = await offlineRecs();
  return recs && rec && recs.includes(rec) ? queryFor(rec) : q;
}
function specificHtml() {
  return band('ld-spec', 'sun', `<div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('03', 'Be as specific as you like', 'Say it like you’d say it to a friend.', 'ld-spec-h')}
        <p class="ld-sub">Budget, place, condition and must-haves come straight out of your sentence. No filter panel, no boxes to tick. Try one:</p>
      </header>
      <ul class="ld-qs" role="list">
        ${SPECIFIC.map((s, i) => `<li class="ld-rv" style="--d:${(i % 2) * 70 + Math.floor(i / 2) * 50}ms">
          <button type="button" class="ld-q" data-q="${esc(s.q)}"${s.rec ? ` data-rec="${esc(s.rec)}"` : ''} aria-label="Search: ${esc(s.q)}">
            <span class="ld-q-text">“${markQuery(s)}”</span>
            <span class="ld-q-tags">${s.pairs.map(([, t, tone]) => `<span class="ld-tag k-${tone}">${esc(t)}</span>`).join('')}</span>
            <span class="ld-q-go"><span class="ld-q-run">Run this search <span aria-hidden="true">→</span></span><span class="ld-q-off" hidden>live only</span></span>
          </button>
        </li>`).join('')}
      </ul>
      <p class="ld-legend ld-rv"><span class="ld-tag k-plain">blue</span> what it is <span class="ld-tag k-ok">green</span> what we act on</p>
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
    ${line(r.eu ? 'All in' : 'All in, at least', eur(r.all) + (r.eu ? '' : '+'), 'sum')}
    <p class="rc-n">Ships to Finland: ${esc(r.ships)}.${r.eu ? ' <b>Our pick.</b>' : ''}</p>
  </figure>`;
}
function priceHtml() {
  const [us, fi] = EX.rows;
  // the section opens with the claim itself; the receipts follow it straight away on phones (CSS order)
  return band('ld-price', 'green', `<div class="ld-in ld-split ld-flip">
      <div class="ld-rcs">${[us, fi].map(receipt).join('')}</div>
      <header class="ld-head ld-rv">
        ${head('04', 'The sticker is not the price.', `<s>${eur(us.tag, 0)} on the tag.</s> <em>${eur(us.all, 0)}+ at your door.</em>`, 'ld-price-h', 'ld-h-pull')}
        <p class="ld-sub">Shipping, import VAT and fees turn up at checkout, after you’ve already decided. We add them before you look, say where each number came from, and mark anything a shop won’t confirm.</p>
        <p class="ld-gap"><b>${eur(fi.tag - us.tag, 0)}</b> cheaper on the sticker. At most <b>${eur(fi.all - us.all, 0)}</b> cheaper at your door, and only if it ships to Finland at all, which the shop never said. The pick is the cheapest offer that surely reaches you: ${esc(fi.dom)}, ${eur(fi.all, 0)}, no surprises.</p>
        <p class="ld-fx">Converted to euros at the day’s ECB reference rate (or our last saved rate if that can’t be reached). The shop’s own price stays with every offer: ${esc(us.orig)} here.</p>
      </header>
    </div>`);
}

// ---------- 5. sources ----------
function sourcesHtml() {
  const lanes = [
    ['The open web', 'A fresh web search for every question, in English and in the local language. Guides, news and forums are dropped. Any shop that sells it stays, whether we’ve heard of it or not.'],
    ['Marketplaces, searched directly', `The big European marketplaces are read through their own search pages, around twenty listings per read. ${SOURCES[0][1]} second-hand sources are known by name.`],
    ['The long tail', 'Small providers on their own sites: found through “best of” articles and look-alikes, priced from their pricing pages, and remembered for next time.'],
  ];
  return band('ld-sources', 'peach', `<div class="ld-in">
      <header class="ld-head ld-rv">
        ${head('05', 'Anywhere it’s sold', 'There’s no list.', 'ld-sources-h', 'ld-h-big')}
        <p class="ld-sub">If a shop sells it, we can find it. Every question starts with a live search of the web, so an offer can come from a shop we’d never heard of a minute earlier. Three ways in:</p>
      </header>
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
    ['Ranked by what you pay.', 'The all-in price sets the order, and the pick is the cheapest one that surely reaches you. Not who pays us. No paid placements.'],
    ['We may earn a fee, never a better spot.', 'If a shop ever pays us for a click, it still sits exactly where its all-in price puts it.'],
    ['We show what we left out, and why.', 'Offers we didn’t count stay in view with the reason: a different model, a dead link, a shop too slow to answer.'],
  ];
  return band('ld-honest', 'sky', `<div class="ld-in ld-narrow">
      <header class="ld-head ld-rv">
        ${head('06', 'Honest by design', 'Built to be on your side of the counter.', 'ld-honest-h')}
      </header>
      <p class="ld-big ld-rv"><b>${eur(EX.odd.tag, 0)}</b><span>One shop said ${eur(EX.odd.tag, 0)} for the Sony. That’s ${EX.odd.under}% under what it sells for used (${eur(EX.odd.median, 0)}), so we flagged it instead of picking it.</span></p>
      <p class="ld-set ld-rv"><b>${EX.skipped}</b> pages set aside in the same hunt, each with its reason: ${EX.set.model} different camera (an A7R III), ${EX.set.dead} dead link, ${EX.set.noPrice} with no price, ${EX.set.slow} too slow, and ${EX.set.capped} more pages from shops we’d already read twice.</p>
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
  const [us, fi] = EX.rows;
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
    `      ${k('origin')}: { ${k('country_code')}: ${v('"US"')}, ${k('ships_to_fi')}: ${v('null')} },`,
    `      ${k('flags')}: [`,
    `        ${v('"outside the EU (USD): import VAT added, shipping to Finland unconfirmed"')}`,
    `      ]`,
    `    },`,
    `    { ${k('source')}: ${v('"' + fi.dom + '"')}, ${k('all_in_eur')}: ${v(fi.all.toFixed(1))},`,
    `      ${k('origin')}: { ${k('country_code')}: ${v('"FI"')}, ${k('ships_to_fi')}: ${v('true')} } },`,
    `    ${c('… 1 more')}`,
    `  ]`,
    `}`,
  ].join('\n');
}
function agentsHtml() {
  // the curl line is this server, as you see it (no port on 80/443: location.origin already drops it)
  const origin = (typeof location !== 'undefined' && /^https?:/.test(location.protocol || '')) ? location.origin : '';
  const block = (kind, label, note = '') => {
    if (kind === 'http' && !origin) return '';
    const c = codeLine(kind, origin);
    return `<figure class="ld-code ld-rv"><figcaption>${esc(label)}</figcaption>
      <pre><code>${c.html}</code></pre>${note ? `<p class="ld-code-n">${esc(note)}</p>` : ''}
      <button type="button" class="ld-copy" data-copy="${esc(c.text)}" aria-label="Copy: ${esc(label)}">copy</button></figure>`;
  };
  // an aside, not step 7 of the pitch: no number, a calmer technical voice
  return band('ld-agents', 'paper', `<div class="ld-in">
      <header class="ld-head ld-rv">
        ${head(null, 'For agents', 'Your agent gets the same line.', 'ld-agents-h')}
        <p class="ld-sub">Same offers, same order, same all-in prices, over MCP or plain JSON. One call instead of a scraper per shop.</p>
      </header>
      <div class="ld-agent">
        <div class="ld-codes">
          ${block('mcp', 'MCP, for Claude Code', 'Run it in the repo folder.')}
          ${block('http', 'Plain JSON over HTTP')}
          <p class="ld-badges ld-rv"><span>read-only</span><span>it never buys</span></p>
          <div class="ld-tools ld-rv" role="table" aria-label="MCP tools">
            <div class="ld-tr ld-th" role="row"><span role="columnheader">tool</span><span role="columnheader">takes</span><span role="columnheader">gives back</span></div>
            ${TOOLS.map(([n, a, r]) => `<div class="ld-tr" role="row"><code role="cell">${n}</code><span role="cell" class="ld-args">${esc(a)}</span><span role="cell">${esc(r)}</span></div>`).join('')}
          </div>
          <p class="ld-links ld-rv"><a href="#agent" class="ld-agent-demo">what an agent sees →</a><a href="/api">API index →</a></p>
        </div>
        <figure class="ld-code ld-json ld-rv"><figcaption>What comes back · trimmed</figcaption><pre><code>${sampleJson()}</code></pre></figure>
      </div>
    </div>`);
}

// ---------- 8. close ----------
// three quick starts, each with a recorded search behind it so they work offline too
const CLOSE_CHIPS = [
  ['Sony A7 III body', 'Sony A7 III body, used, under\u00a0€900', 'sony-a7-iii-body'],
  ['Flat cleaning in Helsinki', 'flat cleaning in Helsinki, 60 m²', 'home-cleaning-helsinki-60m2'],
  ['City bike with a basket', 'city bike with a basket, pickup near me', 'city-bike-with-basket'],
];
function closeHtml() {
  return band('ld-close', 'sun', `<div class="ld-in ld-close-in ld-rv">
      <img class="ld-banana" src="/web/assets/mascot/banana.png" alt="" width="54" height="34" loading="lazy">
      <h2 class="ld-close-h" id="ld-close-h">What do you want to <em>buy</em>?</h2>
      <p class="ld-close-s">Name it. We’ll find who sells it, what it really costs delivered, and which one to buy.</p>
      <form class="ld-close-ask" role="search" aria-label="Start a search">
        <label class="ld-sr" for="ld-close-q">What do you want to buy?</label>
        <input id="ld-close-q" name="q" type="text" autocomplete="off" spellcheck="false" placeholder="A used camera, a PS5 Pro, a flat cleaner…">
        <button type="submit" class="ld-cta">Ask the monkey <span aria-hidden="true">→</span></button>
      </form>
      <p class="ld-close-chips">${CLOSE_CHIPS.map(([t, q, rec]) => `<button type="button" class="ld-chip" data-q="${esc(q)}" data-rec="${esc(rec)}">${esc(t)}</button>`).join('')}</p>
      <p class="ld-close-s2">Go on, ask the monkey. Every price all in, the first one in seconds. <a href="#q" class="ld-totop">Start a search ↑</a></p>
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
  const form = el.querySelector('.ld-close-ask');
  if (form) form.addEventListener('submit', e => {
    e.preventDefault();
    const v = form.elements.q.value.trim();
    if (v) { form.elements.q.value = ''; ask(v); } else form.elements.q.focus();
  });
  // offline: a card with a recording replays it (say so), one without is marked "live only"
  offlineRecs().then(recs => {
    if (!recs) return;
    el.querySelectorAll('.ld-q, .ld-chip').forEach(b => {
      const rec = b.dataset.rec;
      if (rec && recs.includes(rec)) b.title = `Offline: replays the recorded search “${queryFor(rec)}”`;
      else if (b.classList.contains('ld-q')) {
        b.classList.add('ld-live-only');
        const run = b.querySelector('.ld-q-run'), off = b.querySelector('.ld-q-off');
        if (run) run.hidden = true;
        if (off) off.hidden = false;
      }
    });
  });

  el.addEventListener('click', e => {
    const cp = e.target.closest('.ld-copy');
    if (cp) {
      const done = ok => { cp.textContent = ok ? 'copied' : 'select to copy'; cp.classList.toggle('ok', ok); setTimeout(() => { cp.textContent = 'copy'; cp.classList.remove('ok'); }, 1600); };
      try { navigator.clipboard.writeText(cp.dataset.copy).then(() => done(true), () => done(false)); } catch { done(false); }
      return;
    }
    const q = e.target.closest('.ld-q, .ld-chip');
    if (q) { cardQuery(q.dataset.q, q.dataset.rec).then(ask); return; }
    if (e.target.closest('.ld-totop')) { e.preventDefault(); toBox(); return; }
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
