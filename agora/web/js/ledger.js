// ledger.js: ALL the listings a hunt found, with the better ones highlighted (UI round B, owner item 1).
//   1. The better ones: the pick + the best per condition + best trusted seller + closest + best value, each
//      with a short reason ("cheapest all-in", "best trusted seller", …).
//   2. One Filters menu, open only after a click: bananas (the teammate's trust), price value, condition,
//      country (flags), ships to you vs pickup only, price range. Order: best value first, or cheapest. List or grid.
//   3. Every other listing, best value first (or by what you pay, all in). Rendered 50 at a time as you scroll (an observer on a
//      sentinel, plus a "show 50 more" button), rows keyed by URL and reused, so hundreds stay smooth.
//   4. "Also in the EU (+ shipping est.)": the bulky hunt's extra marketplaces, folded.
//   5. Set aside: too cheap to trust, price unconfirmed, red-flag reviews. Dimmed, at the bottom, with reasons.
//   6. "Not this" on every row (judges, F5): one click takes a listing out (it joins "not counted" with
//      "you took it out", and can be put back); the pick, the verdict and the line re-pick in the browser.
//   The main list shows the top 12 first, then "show all N" (F8: hunts with 40+ listings stay one scroll).
//   A price in another currency shows its original next to the euros (F7).
// Click a row or card for its receipt (the sheet).
import { S, on, emit, eur, cutSrc, domainOf, isProductPhoto, allIn, isUnsure, unsureWhy, pickUrl as corePick, trustMark,
  isSetAside, isExtra, extraDomains, isPickupOnly, isRisky, riskWhy, reviewFor, netAfterResale, shipsUnconfirmed } from './core.js';
import { flagHtml, originFor, countryName, flagSrc } from './flags.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const n0 = n => Math.round(n || 0).toLocaleString('en-US');
const STEP = 50;                      // rows added per scroll step (the folded groups)
const COLLAPSE = 12;                  // the main list shows this many until "show all N"
const HUNT_THROTTLE_MS = 350;         // while offers stream in, redraw at most this often
const CONDS = ['new', 'refurbished', 'used'];

let root = null, els = {}, raf = 0, throttleT = 0, lastDraw = 0, io = null;
let limits = { main: STEP, eu: STEP, risky: 30 };
let filt = freshFilter();
let euOpen = false, riskOpen = true, mainAll = false;
const cache = new Map();              // url -> {sig, li}
const dismissed = new Map();          // url -> Item the shopper took out ("not this"); out of S.offers until put back

let mids = {};                        // middle price per condition, for the value icons (set each render)
let sortMode = 'best';               // one of SORTS (set from the URL / storage on mount) (the "Sort" menu); 'best' = the pick and the better ones first
let view = savedView();               // 'list' | 'grid'
let menuOpen = false;                 // the Filters panel opens only on a click

function freshFilter() { return { cond: new Set(), cc: new Set(), ship: 'all', min: null, max: null, bn: 0, vt: 0 }; }

const VIEW_KEY = 'pricemonkey.listings.view';
function savedView() { try { return globalThis.localStorage && localStorage.getItem(VIEW_KEY) === 'grid' ? 'grid' : 'list'; } catch { return 'list'; } }
function saveView(v) { try { if (globalThis.localStorage) localStorage.setItem(VIEW_KEY, v); } catch { /* private mode: the view lasts this visit */ } }

// ---------- sort (owner: "sort by things. definitely by price. also maybe when it was posted") ----------
// The order of the main list (and the folded EU group); the set-aside ones stay at the bottom whatever it is.
// Remembered in localStorage, shared in the URL (?sort=price), so a link opens in the same order.
export const SORTS = [
  ['best', 'Best match', 'best match first'],
  ['price', 'Price: low → high', 'cheapest first'],
  ['price-desc', 'Price: high → low', 'dearest first'],
  ['newest', 'Newest first', 'newest first'],
  ['near', 'Closest to you', 'closest to you first'],
  ['condition', 'Best condition', 'best condition first'],
  ['rating', 'Seller rating', 'best-rated sellers first'],
];
const SORT_KEY = 'pricemonkey.listings.sort';
const SORT_ALIAS = { value: 'best', cheapest: 'price', 'price-asc': 'price', dearest: 'price-desc', new: 'newest', date: 'newest',
  closest: 'near', cond: 'condition', trust: 'rating', reviews: 'rating' };
/** A sort name from the URL / storage, or null when it is not one we know. */
export function sortName(v) {
  const k = String(v || '').trim().toLowerCase();
  const n = SORT_ALIAS[k] || k;
  return SORTS.some(([id]) => id === n) ? n : null;
}
function savedSort() {
  try { const u = typeof location !== 'undefined' && new URLSearchParams(location.search).get('sort'); const n = sortName(u); if (n) return n; } catch { /* no URL: tests */ }
  try { return sortName(globalThis.localStorage && localStorage.getItem(SORT_KEY)) || 'best'; } catch { return 'best'; }
}
function saveSort(v) {
  try { if (globalThis.localStorage) localStorage.setItem(SORT_KEY, v); } catch { /* private mode: lasts this visit */ }
  try {   // the URL says it too (replace, not push: back still goes to the previous search)
    const u = new URL(location.href);
    if (v === 'best') u.searchParams.delete('sort'); else u.searchParams.set('sort', v);
    if (u.href !== location.href) history.replaceState(history.state, '', u);
  } catch { /* no history: fine */ }
}

// icons: Lucide (lucide.dev, ISC licence), inline so they take the text colour
const svg = body => `<svg class="ic" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const IC = {
  banana: '<path d="M4 13c3.5-2 8-2 10 2a5.5 5.5 0 0 1 8 5"/><path d="M5.15 17.89c5.52-1.52 8.65-6.89 7-12C11.55 4 11.5 2 13 2c3.22 0 5 5.5 5 8 0 6.5-4.2 12-10.49 12C5.11 22 2 22 2 20c0-1.5 1.14-1.55 3.15-2.11Z"/>',
  value: '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m15 9-6 6"/><path d="M9 9h.01"/><path d="M15 15h.01"/>',
  filters: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
  list: '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
  sort: '<path d="m3 16 4 4 4-4"/><path d="M7 20V4"/><path d="m21 8-4-4-4 4"/><path d="M17 4v16"/>',
  grid: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
};

// ---------- words ----------
function condWord(c) {
  const k = String(c || '').toLowerCase();
  if (k.startsWith('refurb')) return 'refurbished';
  if (k.startsWith('used') || k === 'second-hand' || k === 'secondhand') return 'used';
  if (k.startsWith('new')) return 'new';
  if (k.startsWith('serv')) return '';
  return k;
}
const tagEur = it => { const p = it && it.offer && it.offer.price_eur; return typeof p === 'number' && isFinite(p) && p > 0 ? p : null; };
const isJob = it => { const t = it && it.tc && it.tc.true_cost; return !!(t && t.per === 'job'); };
/** The number a row is sorted and filtered by: all in once costed, else the tag. */
function val(it) { const a = allIn(it); return a != null ? a : tagEur(it); }
function money(v, it) {
  if (v == null) return '';
  return eur(v >= 100 ? Math.round(v) : v, { dp: v < 100 && Math.abs(v % 1) > 0.004 ? 2 : 0 }) + (isJob(it) ? ' a job' : '');
}
const shopOf = it => (it.offer && it.offer.source) || domainOf(it.url);

// ---------- the original currency (F7) ----------
// The engine sends the shop's own price and currency next to price_eur (agora/fx.py did the conversion).
// The rate shown is the one that conversion used (price_eur / price), never a rate we look up here.
function fmtCur(n, cur) {
  const dp = Math.abs(n % 1) > 0.004 ? 2 : 0;
  try { return new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n); }
  catch { return `${n.toLocaleString('en-US', { maximumFractionDigits: dp })} ${cur}`; }
}
/** {orig: "$699.95", eur: "€633.32", rate: "1 USD = €0.905", cur} when the shop priced it in another currency; else null. */
export function origPrice(it) {
  const o = (it && it.offer) || {};
  const cur = typeof o.currency === 'string' ? o.currency.trim().toUpperCase() : '';
  const p = o.price, pe = o.price_eur;
  if (!/^[A-Z]{3}$/.test(cur) || cur === 'EUR' || !(typeof p === 'number' && p > 0 && isFinite(p)) || !(typeof pe === 'number' && pe > 0 && isFinite(pe))) return null;
  const r = pe / p;
  const rate = r >= 0.1 ? `1 ${cur} = ${eur(r, { dp: r >= 10 ? 2 : 3 })}` : `€1 = ${(1 / r).toLocaleString('en-US', { maximumFractionDigits: 2 })} ${cur}`;
  return { orig: fmtCur(p, cur), eur: eur(pe, { dp: Math.abs(pe % 1) > 0.004 ? 2 : 0 }), rate, cur };
}
const fxTip = f => `${f.orig} on the page, ${f.eur} converted (${f.rate})`;

// ---------- "not this" (F5) ----------
export const isDismissed = url => dismissed.has(url);
export const dismissedItem = url => dismissed.get(url) || null;
/** Take a listing out: it leaves the ranking (the pick, the verdict and the line follow) and waits in
 *  "not counted" as "you took it out", until put back. Client side only; the engine is not told. */
export function notThis(url) {
  const it = S.offers.get(url);
  if (!it) return false;
  it.userOut = true;
  dismissed.set(url, it);
  S.offers.delete(url);
  if (S.leader === url) S.leader = null;
  if (S.turned) { const u = corePick(); if (u) S.leader = u; }
  emit('offer-removed', it);
  emit('rank', S.rank);           // the verdict, the line's pick and the sheet re-read the store
  return true;
}
export function putBack(url) {
  const it = dismissed.get(url);
  if (!it) return false;
  dismissed.delete(url);
  it.userOut = false;
  S.offers.set(url, it);
  if (S.turned) { const u = corePick(); if (u) S.leader = u; }
  emit('offer-restored', it);
  emit('rank', S.rank);
  return true;
}
const ccOf = it => { const o = originFor(it); return o && o.country_code ? String(o.country_code).toUpperCase() : ''; };
function meaningful(tm) { return !!tm && tm.state !== 'none' && !(tm.state === 'done' && tm.label === 'unknown' && !/★/.test(tm.text)); }

// ---------- price value ----------
// How far under the middle price of its condition, in the teammate's steps (bananas.py in
// rpaszekdev/agora-junction-2026): 10 / 20 / 30% under = one / two / three value icons. More than half under is too
// good to be true and gets none (the set-aside rules catch most of those anyway).
const VALUE_STEPS = [0.10, 0.20, 0.30];
const TOO_GOOD = 0.5;
const MIN_FOR_MIDDLE = 3;             // fewer prices than this say nothing about a middle
function median(nums) {
  const s = nums.filter(v => v != null && isFinite(v)).sort((a, b) => a - b);
  if (s.length < MIN_FOR_MIDDLE) return null;
  const h = s.length >> 1;
  return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}
/** {all, <condition>: middle EUR price}: of that condition when it has enough prices, else of every listing. */
export function middles(list) {
  const by = new Map();
  for (const it of list) {
    const c = condWord(it.offer && it.offer.condition) || 'other';
    if (!by.has(c)) by.set(c, []);
    by.get(c).push(val(it));
  }
  const all = median(list.map(val));
  const out = { all };
  for (const [c, vs] of by) out[c] = median(vs) ?? all;
  return out;
}
/** 0..3 value icons for a share under the middle price (negative: dearer; null: unknown). */
export function valueTier(u) { return u == null || !isFinite(u) || u > TOO_GOOD ? 0 : VALUE_STEPS.filter(s => u >= s).length; }
/** {under, tier, mid}: the share under the middle price of its condition, and its value icons. */
export function valueOf(it, m = mids) {
  const mid = m[condWord(it.offer && it.offer.condition) || 'other'] ?? m.all;
  const v = val(it);
  if (mid == null || v == null || !(mid > 0)) return { under: null, tier: 0, mid: null };
  const under = (mid - v) / mid;
  return { under, tier: valueTier(under), mid };
}
// ---------- the sort keys ----------
/** When the listing went up (ms since 1970), from the card's own date (offer.posted_at, ISO); null when not said. */
export function postedMs(it) {
  const p = it && it.offer && it.offer.posted_at;
  if (!p) return null;
  const t = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(p) ? p + 'T12:00:00' : p);   // a day only: its middle, local
  return isFinite(t) ? t : null;
}
/** "just now" · "3 h ago" · "yesterday" · "4 days ago" · "12 Nov" (older than three weeks) · "12 Nov 2025". */
export function postedAgo(it, now = Date.now()) {
  const t = postedMs(it);
  if (t == null) return '';
  const dayOnly = /^\d{4}-\d{2}-\d{2}$/.test(it.offer.posted_at);
  const d0 = new Date(now); d0.setHours(0, 0, 0, 0);
  const d1 = new Date(t); d1.setHours(0, 0, 0, 0);
  const days = Math.round((d0 - d1) / 864e5);
  if (days < 0 || (!dayOnly && t > now + 36e5)) return '';
  if (days === 0) {
    if (dayOnly) return 'today';
    const h = Math.floor((now - t) / 36e5);
    return h < 1 ? 'just now' : `${h} h ago`;
  }
  if (days === 1) return 'yesterday';
  if (days < 21) return `${days} days ago`;
  const dt = new Date(t);
  return dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(dt.getFullYear() !== new Date(now).getFullYear() ? { year: 'numeric' } : {}) });
}
// condition, best first: new, then like new / an excellent refurb, then the used grades the seller wrote
const GRADE_WORDS = [
  [/like new|as new|mint|wie neu|neuwertig|uudenveroinen|kuin uusi|jak nowy|nieużywan|zo goed als nieuw|nyskick|som ny|som nyt|comme neuf|come nuovo|como nuevo|excellent|erinomainen|stan idealny/i, 0.95],
  [/very good|sehr gut|erittäin hyvä|bardzo dobry|zeer goed|mycket bra|meget god|très bon|ottimo|muy bueno|premium/i, 0.8],
  [/good|gut|hyvä|dobry|goed|bra\b|\bgod\b|bon état|buono|bueno/i, 0.6],
  [/fair|acceptable|ok\b|tyydyttävä|kohtalainen|akzeptabel|dostateczny|redelijk|okej|correct/i, 0.4],
  [/for parts|defekt|defective|broken|rikki|uszkodzon|kapot|trasig|pour pièces/i, 0.05],
];
/** 0..1: new 1, refurbished ~0.85, used by its grade (grade_score from the engine, else the grade's words). */
export function conditionScore(it) {
  const o = (it && it.offer) || {};
  const c = condWord(o.condition);
  const gs = typeof o.grade_score === 'number' && isFinite(o.grade_score) ? Math.max(0, Math.min(1, o.grade_score)) : null;
  const words = `${o.grade || ''}`;
  const g = gs != null ? gs : (GRADE_WORDS.find(([re]) => re.test(words)) || [null, null])[1];
  if (c === 'new') return 1;
  if (c === 'refurbished') return 0.8 + 0.1 * (g ?? 0.5);
  if (c === 'used') return 0.2 + 0.55 * (g ?? 0.5);
  return 0.2;
}
/** 0 in your town · 1 in your country · 2 ships to you · 2.5 shipping not stated · 3 pickup only abroad. */
export function nearRank(it, home = homeCc(), where = (S.need && S.need.where ? String(S.need.where) : '')) {
  const o = originFor(it) || {};
  const cc = o.country_code ? String(o.country_code).toUpperCase().replace(/^UK$/, 'GB') : '';
  const w = String(where || '').toLowerCase().trim();
  if (cc === home && w && o.city && String(o.city).toLowerCase().includes(w)) return 0;
  if (cc === home) return 1;
  if (isPickupOnly(it)) return 3;
  return o.ships_to_fi === true ? 2 : 2.5;      // says it ships to you, then probably does (not stated)
}
/** Higher = a better-rated seller: solid reviews by their stars, then the judge's trust; red flags and an eaten
 *  banana last. */
export function ratingScore(it) {
  const b = bananasOf(it);
  if (b && b.eaten) return -1;
  return trustScore(it) + (b ? b.n * 0.01 : 0);
}

/** The list in this order. 'value': most value icons, then the biggest share under, then the cheapest.
 *  'best': the pick and the better ones first (`first`: their URLs, in order), then 'value'. 'price' /
 *  'price-desc': what you pay (all in, else the tag), unpriced last. 'newest': the card's own date, undated last.
 *  'near': your town, your country, ships to you, the rest. 'condition': new, like new, … 'rating': the seller's
 *  reviews / trust. Ties: the cheapest first. Keys are worked out once per row (2,000 rows sort in a few ms). */
export function sortBy(list, mode, m = mids, { first = [] } = {}) {
  const byPrice = (a, b) => (val(a) ?? Infinity) - (val(b) ?? Infinity);
  if (mode === 'value' || mode === 'best') return bestOrder(list, mode, m, first, byPrice);
  // the price sorts: the costed ones by what you pay all in, then the ones still costing by their tag, unpriced last
  const costed = new Map(list.map(it => [it, allIn(it) != null ? 0 : val(it) != null ? 1 : 2]));
  const byPay = (a, b) => (costed.get(a) - costed.get(b)) || byPrice(a, b);
  const keyed = (fn, dir = 1) => {
    const k = new Map(list.map(it => [it, fn(it)]));
    return list.slice().sort((a, b) => {
      const x = k.get(a), y = k.get(b);
      if (x == null || y == null) return x == null && y == null ? byPay(a, b) : x == null ? 1 : -1;
      return (x === y ? 0 : dir * (x < y ? -1 : 1)) || byPay(a, b);
    });
  };
  if (mode === 'price') return list.slice().sort(byPay);
  if (mode === 'price-desc') return list.slice().sort((a, b) => (costed.get(a) - costed.get(b)) || ((val(b) ?? -Infinity) - (val(a) ?? -Infinity)));
  if (mode === 'newest') return keyed(postedMs, -1);
  if (mode === 'near') return keyed(it => nearRank(it));
  if (mode === 'condition') return keyed(conditionScore, -1);
  if (mode === 'rating') return keyed(ratingScore, -1);
  return bestOrder(list, 'value', m, first, byPrice);
}
/** 'value': most value icons, then the biggest share under the middle, then the cheapest. 'best': the same, with
 *  the pick and the better ones (`first`, URLs in order) on top. */
function bestOrder(list, mode, m, first, byPrice) {
  if (mode === 'best') {
    const rest = bestOrder(list, 'value', m, [], byPrice);
    if (!first.length) return rest;
    const at = new Map(first.map((u, i) => [u, i]));
    const top = rest.filter(it => at.has(it.url)).sort((a, b) => at.get(a.url) - at.get(b.url));
    return top.concat(rest.filter(it => !at.has(it.url)));
  }
  const key = new Map(list.map(it => {
    const v = valueOf(it, m);
    return [it, [v.tier, v.under == null || v.under > TOO_GOOD ? -Infinity : v.under]];
  }));
  return list.slice().sort((a, b) => {
    const ka = key.get(a), kb = key.get(b);
    return (kb[0] - ka[0]) || (kb[1] === ka[1] ? 0 : kb[1] - ka[1]) || byPrice(a, b);
  });
}

// ---------- trust: the teammate's bananas ----------
/** agora/bananas.py puts {n, state, why} in every truecost: how much speaks for the listing and its seller.
 *  {n: 1..3, eaten: false, why} · {n: 0, eaten: true, why} (do not trust it) · null (nothing to say). */
export function bananasOf(it) {
  const b = it && it.tc && it.tc.bananas;
  if (!b || typeof b !== 'object') return null;
  const why = typeof b.why === 'string' ? b.why : '';
  if (b.state === 'eaten') return { n: 0, eaten: true, why };
  const n = Math.max(0, Math.min(3, Math.round(Number(b.n) || 0)));
  return n ? { n, eaten: false, why } : null;
}

// ---------- groups ----------
/** Every listing, split: main (by all in), eu (the bulky hunt's "also in the EU"), risky (set aside / red
 *  flags, at the bottom), costing (no true cost yet: at the end of main). Exported for tests. */
export function groups(offers = S.offers, { turned = S.turned } = {}) {
  const ex = extraDomains();
  const out = { main: [], eu: [], risky: [], costing: [] };
  for (const it of offers.values()) {
    if (tagEur(it) == null && allIn(it) == null) continue;
    if (it.tc && isRisky(it)) out.risky.push(it);
    else if (turned && !it.tc) out.costing.push(it);
    else if (isExtra(it, ex)) out.eu.push(it);
    else out.main.push(it);
  }
  // taken out by you: with the set-aside ones, so you can see (and undo) everything that is not counted
  if (offers === S.offers) for (const it of dismissed.values()) if (tagEur(it) != null || allIn(it) != null) out.risky.push(it);
  const by = (a, b) => (val(a) ?? Infinity) - (val(b) ?? Infinity);
  out.main.sort(by); out.eu.sort(by); out.costing.sort(by);
  out.risky.sort((a, b) => (tagEur(a) ?? Infinity) - (tagEur(b) ?? Infinity));
  return out;
}
/** Kept for older callers: the ranked rows (main, then costing), set-aside ones excluded. */
export function rows(offers, { turned = false } = {}) {
  const g = groups(offers, { turned });
  return g.main.concat(g.eu, g.costing).filter(it => !(it.tc && isSetAside(it)) && !it.userOut);
}

// ---------- the better ones ----------
function trustScore(it) {
  const r = reviewFor(it);
  if (r && r.label === 'solid') return 1 + (typeof r.rating === 'number' ? r.rating / 10 : 0);
  if (r && r.label === 'watch out') return 0;
  const t = it.tc && it.tc.trust;
  return typeof t === 'number' ? t : 0.5;
}
function homeCc() { return String((S.scope && S.scope.country) || 'FI').toUpperCase(); }
/** Up to five highlighted listings, each with its reasons: [{it, why:[...], key}]. Exported for tests. */
export function highlights(offers = S.offers) {
  const g = groups(offers);
  const pool = g.main.concat(g.eu).filter(it => allIn(it) != null);
  if (!pool.length) return [];
  const sure = pool.filter(it => !isUnsure(it));
  const home = sure.filter(it => !isExtra(it));
  const base = home.length ? home : (sure.length ? sure : pool);
  const out = new Map();
  const add = (it, why, key) => {
    if (!it) return;
    const h = out.get(it.url) || { it, why: [], key };
    if (!h.why.includes(why)) h.why.push(why);
    out.set(it.url, h);
  };
  const cheapest = list => list.reduce((a, b) => (allIn(b) < allIn(a) ? b : a), list[0]);
  const pu = corePick(offers);
  const pick = (pu && offers.get(pu) && pool.includes(offers.get(pu))) ? offers.get(pu) : cheapest(base);
  add(pick, 'cheapest all-in', 'pick');
  for (const c of CONDS) {
    const list = base.filter(it => condWord(it.offer.condition) === c);
    if (list.length) add(cheapest(list), `cheapest ${c}`, 'c-' + c);
  }
  // best trusted seller: the most trusted shop (solid reviews first), the cheaper one on a tie
  const ts = base.slice().sort((a, b) => trustScore(b) - trustScore(a) || allIn(a) - allIn(b))[0];
  if (ts && trustScore(ts) > trustScore(pick) + 0.04) {
    const r = reviewFor(ts);
    add(ts, 'best trusted seller' + (r && typeof r.rating === 'number' && r.count ? ` · ★ ${r.rating.toFixed(1)}` : ''), 'trust');
  }
  // closest to you: the asked-for town, else (when the pick is abroad) the cheapest one in your country
  const where = S.need && S.need.where ? String(S.need.where).toLowerCase() : '';
  const near = where ? base.filter(it => { const o = originFor(it); return o && o.city && String(o.city).toLowerCase().includes(where); }) : [];
  if (near.length) add(cheapest(near), `closest to you · ${originFor(cheapest(near)).city}`, 'near');
  else if (ccOf(pick) && ccOf(pick) !== homeCc()) {
    const dom = sure.filter(it => ccOf(it) === homeCc());
    if (dom.length) add(cheapest(dom), `closest to you · in ${countryName(homeCc())}`, 'near');
  }
  // best value: the least it costs you once you resell it in a year
  const nets = base.filter(it => netAfterResale(it) != null);
  if (nets.length > 2) {
    const bv = nets.reduce((a, b) => (netAfterResale(b) < netAfterResale(a) ? b : a));
    const pn = netAfterResale(pick);
    if (bv !== pick && (pn == null || netAfterResale(bv) < pn - 1)) add(bv, `best value: ≈${money(Math.max(0, netAfterResale(bv)))} if you resell it in a year`, 'value');
  }
  const list = [...out.values()];
  const head = list.shift();
  return [head].concat(list.sort((a, b) => allIn(a.it) - allIn(b.it))).slice(0, 5);
}

// ---------- filters ----------
function passes(it) {
  const f = filt;
  if (f.cond.size && !f.cond.has(condWord(it.offer.condition) || 'other')) return false;
  if (f.cc.size && !f.cc.has(ccOf(it) || '?')) return false;
  if (f.ship === 'ships' && isPickupOnly(it)) return false;
  if (f.ship === 'pickup' && !isPickupOnly(it)) return false;
  const v = val(it);
  if (f.min != null && (v == null || v < f.min)) return false;
  if (f.max != null && (v == null || v > f.max)) return false;
  if (f.bn && !((bananasOf(it) || { n: 0 }).n >= f.bn)) return false;
  if (f.vt && valueOf(it).tier < f.vt) return false;
  return true;
}
const filtering = () => filt.cond.size || filt.cc.size || filt.ship !== 'all' || filt.min != null || filt.max != null || filt.bn || filt.vt;
/** How many kinds of filter are on: the number on the Filters button. */
const activeKinds = () => [filt.cond.size, filt.cc.size, filt.ship !== 'all', filt.min != null || filt.max != null, filt.bn, filt.vt].filter(Boolean).length;
function facets(all) {
  const cond = new Map(), cc = new Map();
  const bn = [0, 0, 0, 0], vt = [0, 0, 0, 0];   // [-, at least one, at least two, three]
  let ships = 0, pickup = 0, lo = Infinity, hi = -Infinity;
  for (const it of all) {
    const b = bananasOf(it), t = valueOf(it).tier;
    for (let k = 1; b && k <= b.n; k++) bn[k]++;
    for (let k = 1; k <= t; k++) vt[k]++;
    const c = condWord(it.offer.condition) || 'other';
    cond.set(c, (cond.get(c) || 0) + 1);
    const k = ccOf(it) || '?';
    cc.set(k, (cc.get(k) || 0) + 1);
    if (isPickupOnly(it)) pickup++; else ships++;
    const v = val(it);
    if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  return { cond, cc, ships, pickup, bn, vt, lo: isFinite(lo) ? lo : null, hi: isFinite(hi) ? hi : null };
}

// ---------- rows (keyed, reused) ----------
function noteFor(it, kind, pick) {
  const notes = [];
  if (it.userOut) return '<i class="lg-why">you took it out</i>';
  if (kind === 'risky') return `<i class="lg-why">${esc(riskWhy(it))}</i>`;
  if (it.url === pick) notes.push('<b>the pick</b>');
  if (!it.tc && S.turned) notes.push('still costing');
  if (it.late && it.url !== pick) notes.push('late');
  if (isPickupOnly(it)) notes.push('<i>pickup only</i>');
  else if (kind === 'eu') notes.push('+ shipping est.');
  else if (it.tc && isUnsure(it)) { const w = unsureWhy(it); if (w) notes.push(`<i>${esc(shipsUnconfirmed(it) ? '+ shipping · ' + w : w)}</i>`); }
  if (S.recheck && S.recheck.to === it.url) notes.push('re-checked after reviews');
  return notes.join(' · ');
}
function rowSig(it, i, kind, pick) {
  const tm = trustMark(it);
  return [i, kind, val(it), tagEur(it), it.url === pick, !!it.tc, it.late, tm && tm.text, ccOf(it), isPickupOnly(it),
    it.tc && isUnsure(it), S.turned, S.recheck && S.recheck.to, valueHtml(it, kind), JSON.stringify(bananasOf(it)), !!it.userOut, postedAgo(it)].join('|');
}
// no photo (yet): a calm tile with the shop's own mark over its initial, so it reads as "from this shop", not broken
const shopIcon = d => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(d)}&sz=64`;
function placeholder(it) {
  const d = String(domainOf(it.url) || shopOf(it) || '').replace(/^www\./, '');
  const l = esc((shopOf(it) || d || '?').replace(/^www\./, '')[0].toUpperCase());
  return `<i class="ph" data-l="${l}">${d ? `<img class="ph-logo" alt="" loading="lazy" referrerpolicy="no-referrer" src="${esc(shopIcon(d))}">` : ''}</i>`;
}
// the value icons: the share under (or over) the middle price of its condition, with up to three % badges
function valueHtml(it, kind) {
  if (kind === 'risky') return '';
  const { under, tier, mid } = valueOf(it);
  if (under == null) return '';
  const pct = Math.round(Math.abs(under) * 100);
  const cond = condWord(it.offer && it.offer.condition);
  const of = `the middle price${cond ? ` of ${cond}` : ''} (${eur(Math.round(mid), { dp: 0 })})`;
  const tip = under > TOO_GOOD ? `${pct}% under ${of}: too good to be true` : pct === 0 ? `at ${of}` : `${pct}% ${under > 0 ? 'under' : 'over'} ${of}`;
  const label = pct === 0 ? '≈ middle' : `${under > 0 ? '−' : '+'}${pct}%`;
  return `<span class="lg-vi" data-t="${under > TOO_GOOD ? 'x' : tier}" title="${esc(tip)}">${svg(IC.value).repeat(tier)}<b>${label}</b></span>`;
}
// the teammate's bananas: how much speaks for the listing and its seller; an eaten black one = do not trust it
function bananaHtml(it) {
  const b = bananasOf(it);
  if (!b) return '';
  const tip = b.eaten ? `Do not trust it${b.why ? ': ' + b.why : ''}` : `${b.n} banana${b.n > 1 ? 's' : ''}${b.why ? ': ' + b.why : ''}`;
  return `<span class="lg-bn${b.eaten ? ' eaten' : ''}" title="${esc(tip)}">${svg(IC.banana).repeat(b.eaten ? 1 : b.n)}<span class="sr">${esc(tip)}</span></span>`;
}
// when it went up, quietly: "2 days ago" (the full date in the tooltip)
function ageHtml(it) {
  const a = postedAgo(it);
  if (!a) return '';
  const d = new Date(postedMs(it));
  return `<span class="lg-age" title="${esc('Posted ' + d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }))}">${esc(a)}</span>`;
}
function rowHtml(it, i, kind, pick) {
  const raw = it.offer.image || '';
  const src = cutSrc(it) || (isProductPhoto(raw) ? raw : '');
  const site = shopOf(it);
  const v = allIn(it);
  const tm = trustMark(it);
  const mark = meaningful(tm) ? `<span class="tmark" data-state="${esc(tm.state)}" data-label="${esc(tm.label)}">${esc(tm.text)}</span>` : '';
  const pic = src ? `<img alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" src="${esc(src)}" data-raw="${esc(isProductPhoto(raw) ? raw : '')}">`
                  : placeholder(it);
  const title = String(it.offer.title || '').trim();
  const cls = ['lg-r', it.url === pick ? 'pick' : '', it.tc && isUnsure(it) ? 'unsure' : '', kind === 'risky' ? 'risky' : '', it.userOut ? 'out' : ''].filter(Boolean).join(' ');
  const fx = origPrice(it);
  const fxS = fx ? `<small class="lg-fx" title="${esc(fxTip(fx))}">${esc(fx.orig)}</small>` : '';
  const name = title || site;
  // a sibling of the row (never inside it: a button in a button is not allowed), top right of the row
  const out = it.userOut
    ? `<button type="button" class="lg-out back" data-back="${esc(it.url)}" aria-label="${esc('Put back: ' + name)}">put back</button>`
    : kind === 'risky' ? ''
    : `<button type="button" class="lg-out" data-out="${esc(it.url)}" aria-label="${esc('Not this one, take it out: ' + name)}" title="Not what you want? Take it out and we re-pick"><span aria-hidden="true">×</span> not this</button>`;
  return `<button type="button" class="${cls}" data-url="${esc(it.url)}"${fx ? ` title="${esc(fxTip(fx))}"` : ''}>
    <span class="lg-n">${i + 1}</span><span class="lg-pic">${pic}</span>
    <span class="lg-main"><span class="lg-ti">${esc(title || site)}</span>
      <span class="lg-t"><span class="lg-s">${flagHtml(it, { noFi: true, unknown: true })}<span class="lg-d">${esc(site)}</span></span><span class="lg-cm">${esc(condWord(it.offer.condition))}</span>${fx ? `<span class="lg-fxm">${esc(fx.orig)} on the page</span>` : ''}${ageHtml(it)}${bananaHtml(it)}${mark}</span></span>
    <span class="lg-v">${valueHtml(it, kind)}</span>
    <span class="lg-c">${esc(condWord(it.offer.condition))}</span>
    <span class="lg-tag">${esc(eur(tagEur(it), { dp: 0 }))}${fxS}</span>
    <span class="lg-tc">${kind === 'risky' && v == null ? '<span class="lg-nc">not costed</span>' : esc(money(v, it))}</span>
    <span class="lg-x">${noteFor(it, kind, pick)}</span></button>${out}`;
}
function rowEl(it, i, kind, pick) {
  const sig = rowSig(it, i, kind, pick);
  let c = cache.get(it.url);
  if (c && c.sig === sig) return c.li;
  if (!c) {
    const li = document.createElement('li');
    c = { sig: '', li };
    cache.set(it.url, c);
  }
  c.sig = sig;
  c.li.innerHTML = rowHtml(it, i, kind, pick);
  return c.li;
}
/** Put exactly these rows in this list, in order, moving nodes only when out of place. */
function fill(ol, list, kind, pick) {
  let at = ol.firstChild;
  for (let i = 0; i < list.length; i++) {
    const li = rowEl(list[i], i, kind, pick);
    if (li === at) { at = at.nextSibling; continue; }
    ol.insertBefore(li, at);
  }
  while (at) { const nx = at.nextSibling; at.remove(); at = nx; }
}

// ---------- highlight cards ----------
function cardHtml(h, i) {
  const it = h.it, o = it.offer || {};
  const raw = o.image || '';
  const src = cutSrc(it) || (isProductPhoto(raw) ? raw : '');
  const org = originFor(it);
  const sub = [condWord(o.condition), org && org.city, isPickupOnly(it) ? 'pickup only' : ''].filter(Boolean).join(' · ');
  const [lead, ...more] = h.why;
  const v = allIn(it);
  return `<li><button type="button" class="lg-hc${i === 0 ? ' is-pick' : ''}" data-url="${esc(it.url)}">
    <span class="hc-pic">${src ? `<img alt="" decoding="async" referrerpolicy="no-referrer" src="${esc(src)}">` : placeholder(it)}</span>
    <span class="hc-body">
      <span class="hc-why"><b>${esc(lead.charAt(0).toUpperCase() + lead.slice(1))}</b>${more.length ? `<span> · ${esc(more.join(' · '))}</span>` : ''}</span>
      <span class="hc-t">${esc(String(o.title || '').trim() || shopOf(it))}</span>
      <span class="hc-s">${flagHtml(it, { noFi: true })}<span>${esc(shopOf(it))}</span>${sub ? `<em>${esc(sub)}</em>` : ''}</span>
      <span class="hc-p">${esc(money(v, it))}<small>${isJob(it) ? '' : ' all in'}${shipsUnconfirmed(it) ? ' + shipping' : ''}</small></span>
    </span></button></li>`;
}

// ---------- filter bar ----------
function seg(name, opts, cur) {
  return `<span class="lg-f" role="group" aria-label="${esc(name)}">${opts.map(([v, label]) =>
    `<button type="button" data-ship="${esc(v)}" aria-pressed="${cur === v}">${label}</button>`).join('')}</span>`;
}
function filterHtml(fc) {
  const cond = [...fc.cond.entries()].sort((a, b) => CONDS.indexOf(a[0]) - CONDS.indexOf(b[0]));
  const ccs = [...fc.cc.entries()].sort((a, b) => b[1] - a[1]);
  const chip = (k, v, label, on) => `<button type="button" class="lg-chip" data-${k}="${esc(v)}" aria-pressed="${on}">${label}</button>`;
  const condRow = cond.length > 1 ? `<span class="lg-fg" role="group" aria-label="Condition">${cond.map(([c, n]) =>
    chip('cond', c, `${esc(c)} <span>${n0(n)}</span>`, filt.cond.has(c))).join('')}</span>` : '';
  const ccRow = ccs.length > 1 ? `<span class="lg-fg" role="group" aria-label="Where the seller is">${ccs.map(([c, n]) =>
    chip('cc', c, c === '?' ? `not stated <span>${n0(n)}</span>`
      : `<img alt="" width="14" height="10" src="${esc(flagSrc(c))}"><span class="sr">${esc(countryName(c))}</span><span>${n0(n)}</span>`, filt.cc.has(c))
      .replace('class="lg-chip"', `class="lg-chip cc" title="${esc(c === '?' ? 'Origin not stated' : countryName(c))}"`)).join('')}</span>` : '';
  const shipRow = fc.pickup && fc.ships ? seg('Delivery', [['all', 'all'], ['ships', `ships to you <span>${n0(fc.ships)}</span>`], ['pickup', `pickup only <span>${n0(fc.pickup)}</span>`]], filt.ship) : '';
  const price = fc.lo != null && fc.hi != null && fc.hi - fc.lo >= 5 ? `<span class="lg-price" role="group" aria-label="Price, all in">
      <label><span class="sr">from</span><input type="number" inputmode="numeric" min="0" step="1" data-p="min" placeholder="${esc(eur(Math.floor(fc.lo), { dp: 0 }))}" value="${filt.min ?? ''}"></label>
      <span aria-hidden="true">–</span>
      <label><span class="sr">to</span><input type="number" inputmode="numeric" min="0" step="1" data-p="max" placeholder="${esc(eur(Math.ceil(fc.hi), { dp: 0 }))}" value="${filt.max ?? ''}"></label>
    </span>` : '';
  const step = (k, counts, icon, cur) => `<span class="lg-f" role="group">${[0, 1, 2, 3].map(n =>
    `<button type="button" data-${k}="${n}" aria-pressed="${cur === n}">${n ? `${svg(icon).repeat(n)}${n < 3 ? '+' : ''} <span>${n0(counts[n])}</span>` : 'any'}</button>`).join('')}</span>`;
  const row = (label, html, tip = '') => html ? `<div class="lg-fr"><span class="lg-fl"${tip ? ` title="${esc(tip)}"` : ''}>${label}</span>${html}</div>` : '';
  return row('Price value', mids.all != null ? step('vt', fc.vt, IC.value, filt.vt) : '', '10 / 20 / 30% under the middle price of its condition')
    + row('Bananas', fc.bn[1] || filt.bn ? step('bn', fc.bn, IC.banana, filt.bn) : '', 'how much speaks for the listing and its seller')
    + row('Condition', condRow) + row('Seller in', ccRow) + row('Delivery', shipRow) + row('Price, all in', price);
}

// ---------- render ----------
function scaffold() {
  root.innerHTML = `
    <div class="lg-top"><h2 class="lg-h"></h2><span class="lg-cnt" role="status"></span></div>
    <ol class="lg-hl" aria-label="The better ones"></ol>
    <div class="lg-tb">
      <button type="button" class="lg-fbtn" aria-expanded="false" aria-controls="lg-fp">${svg(IC.filters)}Filters<span class="lg-fn"></span><i aria-hidden="true">▾</i></button>
      <label class="lg-sortw">${svg(IC.sort)}<span class="lg-sortl">Sort</span><select class="lg-sort" aria-label="Sort the listings">${SORTS.map(([id, label]) => `<option value="${id}">${esc(label)}</option>`).join('')}</select><i aria-hidden="true">▾</i></label>
      <button type="button" class="lg-clear" hidden>clear filters</button>
      <span class="lg-f lg-view" role="group" aria-label="View"><button type="button" data-view="list" aria-pressed="true" title="List">${svg(IC.list)}<span class="sr">list</span></button><button type="button" data-view="grid" aria-pressed="false" title="Grid">${svg(IC.grid)}<span class="sr">grid</span></button></span>
    </div>
    <div class="lg-fb" id="lg-fp" role="group" aria-label="Filter the listings" hidden></div>
    <p class="lg-jump" hidden></p>
    <div class="lg-r lg-head" aria-hidden="true"><span></span><span></span><span>listing</span><span class="lg-v">value</span><span>condition</span><span class="lg-tag">tag</span><span class="lg-tc">all in</span><span></span></div>
    <ol class="lg-l" data-g="main"></ol>
    <div class="lg-more-w" data-g="main"><button type="button" class="lg-more" data-g="main"></button></div>
    <section class="lg-g lg-eu" hidden>
      <button type="button" class="lg-gh" aria-expanded="false" data-tg="eu"><span class="lg-gt"></span><span class="lg-gs"></span><i aria-hidden="true">▾</i></button>
      <div class="lg-gb" hidden><p class="lg-gn"></p><ol class="lg-l" data-g="eu"></ol>
        <div class="lg-more-w" data-g="eu"><button type="button" class="lg-more" data-g="eu"></button></div></div>
    </section>
    <section class="lg-g lg-risk" hidden>
      <button type="button" class="lg-gh" aria-expanded="true" data-tg="risky"><span class="lg-gt"></span><span class="lg-gs"></span><i aria-hidden="true">▾</i></button>
      <div class="lg-gb"><p class="lg-gn"></p><ol class="lg-l" data-g="risky"></ol>
        <div class="lg-more-w" data-g="risky"><button type="button" class="lg-more" data-g="risky"></button></div></div>
    </section>`;
  els = {
    h: root.querySelector('.lg-h'), cnt: root.querySelector('.lg-cnt'), hl: root.querySelector('.lg-hl'), fb: root.querySelector('.lg-fb'),
    fbtn: root.querySelector('.lg-fbtn'), fn: root.querySelector('.lg-fn'), clear: root.querySelector('.lg-tb .lg-clear'),
    sort: root.querySelector('select.lg-sort'),
    head: root.querySelector('.lg-head'),
    list: { main: root.querySelector('ol[data-g=main]'), eu: root.querySelector('ol[data-g=eu]'), risky: root.querySelector('ol[data-g=risky]') },
    more: { main: root.querySelector('.lg-more[data-g=main]'), eu: root.querySelector('.lg-more[data-g=eu]'), risky: root.querySelector('.lg-more[data-g=risky]') },
    eu: root.querySelector('.lg-eu'), risk: root.querySelector('.lg-risk'), jump: root.querySelector('.lg-jump'),
  };
  if (typeof IntersectionObserver === 'function') {
    io = new IntersectionObserver(ents => {
      for (const e of ents) {
        if (!e.isIntersecting) continue;
        const g = e.target.dataset.g;
        if (g === 'main' || e.target.hidden || !els.more[g] || els.more[g].hidden) continue;   // main waits for "show all"
        limits[g] += STEP; queue(true);
      }
    }, { rootMargin: '600px 0px' });
    root.querySelectorAll('.lg-more-w').forEach(w => io.observe(w));
  }
}

/** The toolbar's state: Filters open or not and how many are on, the order, list or grid. */
function toolbar() {
  els.fbtn.setAttribute('aria-expanded', String(menuOpen));
  const k = activeKinds();
  els.fn.textContent = k ? ` · ${k}` : '';
  els.fb.hidden = !menuOpen || !els.fb.innerHTML.trim();
  els.clear.hidden = !filtering();
  // "Newest first" only when listings carry the date they went up
  const nw = els.sort.querySelector('option[value=newest]');
  if (nw.hidden === hasDates) { nw.hidden = !hasDates; nw.disabled = !hasDates; }
  const eff = effSort();
  if (els.sort.value !== eff) els.sort.value = eff;
  els.sort.parentElement.classList.toggle('on', eff !== 'best');
  root.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  root.classList.toggle('is-grid', view === 'grid');
}

let hasDates = false;                 // any listing with offer.posted_at: "Newest first" is offered
/** The order in use: the chosen one, but 'best' while "Newest first" has no dates to go by. */
const effSort = () => (sortMode === 'newest' && !hasDates ? 'best' : sortMode);

let hlKey = '', fbKey = '';
function render() {
  raf = 0; lastDraw = performance.now();
  if (!root) return;
  const g = groups();
  const n = g.main.length + g.eu.length + g.risky.length + g.costing.length;
  const show = (S.turned || S.done) && n > 0 && S.phase !== 'finale' && S.phase !== 'start';
  root.hidden = !show;
  if (!show) return;
  const pick = (S.turned && corePick()) || S.leader;

  // the better ones
  const hls = S.turned ? highlights() : [];
  const hk = hls.map(h => [h.it.url, h.why.join(','), val(h.it), ccOf(h.it)].join('~')).join('|');
  if (hk !== hlKey) { hlKey = hk; els.hl.innerHTML = hls.map(cardHtml).join(''); els.hl.hidden = !hls.length; }

  // filters (built from every listing, so the counts say what each filter would show); value against the comparable ones
  mids = middles(g.main.concat(g.costing, g.eu));
  const all = g.main.concat(g.costing, g.eu, g.risky);
  hasDates = all.some(it => it.offer && it.offer.posted_at);
  const fc = facets(all);
  const fk = JSON.stringify([[...fc.cond], [...fc.cc], fc.ships, fc.pickup, fc.bn, fc.vt, mids.all != null, Math.floor(fc.lo || 0), Math.ceil(fc.hi || 0),
    filt.ship, [...filt.cond], [...filt.cc], filt.min, filt.max, filt.bn, filt.vt]);
  if (fk !== fbKey && !(document.activeElement && document.activeElement.closest && document.activeElement.closest('.lg-price'))) {
    fbKey = fk; els.fb.innerHTML = filterHtml(fc);
  }
  toolbar();

  const mode = effSort();
  const first = mode === 'best' ? [pick].concat(hls.map(h => h.it.url)).filter(Boolean) : [];
  const main = sortBy(g.main.concat(g.costing).filter(passes), mode, mids, { first }), eu = sortBy(g.eu.filter(passes), mode, mids), risky = g.risky.filter(passes);
  const shown = main.length + eu.length + risky.length;
  const order = mode === 'price' ? (S.turned ? 'cheapest first, all in' : 'cheapest first, by the tag')
    : (SORTS.find(([id]) => id === mode) || SORTS[0])[2];
  els.h.innerHTML = `${n === 1 ? 'The one listing' : `All ${n0(n)} listings`}, <span>${order}</span>`;
  els.cnt.innerHTML = filtering() ? `showing ${n0(shown)} of ${n0(n)}` : (g.risky.length ? `${n0(n - g.risky.length)} compared · ${n0(g.risky.length)} not counted` : '');

  const part = (key, list, kind) => {
    // the main list: the top 12, then every one at once ("show all N"); the folded groups grow 50 at a time
    const lim = key === 'main' ? (mainAll ? list.length : Math.min(list.length, COLLAPSE)) : Math.min(list.length, limits[key]);
    fill(els.list[key], list.slice(0, lim), kind, pick);
    const left = list.length - lim;
    const b = els.more[key];
    const fold = key === 'main' && mainAll && list.length > COLLAPSE + 3;
    b.hidden = left <= 0 && !fold;
    b.parentElement.hidden = b.hidden;
    b.dataset.fold = fold && left <= 0 ? '1' : '';
    if (key === 'main' && left > 0) b.textContent = `show all ${n0(list.length)}`;
    else if (fold && left <= 0) b.textContent = `show the top ${COLLAPSE} only`;
    else if (left > 0) b.textContent = `show ${Math.min(STEP, left)} more · ${n0(left)} left`;
  };
  part('main', main, 'main');
  els.head.hidden = !main.length;

  const euOn = g.eu.length > 0;
  els.eu.hidden = !euOn;
  if (euOn) {
    const lo = eu.length ? Math.min(...eu.map(val).filter(v => v != null)) : null;
    const pickupN = eu.filter(isPickupOnly).length;
    els.eu.querySelector('.lg-gt').textContent = 'Also in the EU (+ shipping est.)';
    els.eu.querySelector('.lg-gs').textContent = `${n0(eu.length)} listing${eu.length === 1 ? '' : 's'}${lo != null && isFinite(lo) ? ` · from ${eur(Math.round(lo), { dp: 0 })} all in` : ''}${pickupN ? ` · ${n0(pickupN)} pickup only` : ''}`;
    const tg = els.eu.querySelector('.lg-gh'); tg.setAttribute('aria-expanded', String(euOpen));
    els.eu.querySelector('.lg-gb').hidden = !euOpen;
    const sc = S.scope;
    els.eu.querySelector('.lg-gn').textContent = sc && sc.bulky
      ? `Bulky, so we pick near you. These are on the big EU marketplaces; shipping is an estimate (ask the seller), and pickup-only ones abroad are never the pick.`
      : 'Read from the big EU marketplaces; shipping is estimated.';
    if (euOpen) part('eu', eu, 'eu'); else fill(els.list.eu, [], 'eu', pick);
  }

  const rOn = g.risky.length > 0;
  els.risk.hidden = !rOn;
  if (rOn) {
    const why = new Map();
    for (const it of g.risky) { const w = it.userOut ? 'taken out by you' : riskWhy(it).split(':')[0]; why.set(w, (why.get(w) || 0) + 1); }
    const mine = g.risky.filter(it => it.userOut).length;
    els.risk.querySelector('.lg-gt').textContent = `Not counted (${n0(g.risky.length)})`;
    els.risk.querySelector('.lg-gs').textContent = [...why.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([w, k]) => `${w} ${n0(k)}`).join(' · ');
    els.risk.querySelector('.lg-gh').setAttribute('aria-expanded', String(riskOpen));
    els.risk.querySelector('.lg-gb').hidden = !riskOpen;
    els.risk.querySelector('.lg-gn').textContent = (g.risky.length > mine ? 'We would not buy these at that price: too cheap to trust, a price we could not confirm, or a seller with red flags. Shown so you can see everything we found.' : '')
      + (mine ? `${g.risky.length > mine ? ' ' : ''}${mine === 1 ? 'One you took out' : `${n0(mine)} you took out`}: “put back” returns it to the ranking.` : '');
    if (riskOpen) part('risky', risky, 'risky'); else fill(els.list.risky, [], 'risky', pick);
  }
  // the folded groups sit under a long list: say they exist, and jump there
  const jumps = [];
  if (euOn) jumps.push(`<button type="button" data-jump="eu">Also in the EU (+ shipping est.): ${n0(eu.length)} ↓</button>`);
  if (rOn) jumps.push(`<button type="button" data-jump="risky">Not counted: ${n0(risky.length)} ↓</button>`);
  const jk = jumps.join('');
  if (els.jump.dataset.k !== jk) { els.jump.dataset.k = jk; els.jump.innerHTML = jk; }
  els.jump.hidden = !jumps.length || !mainAll || main.length < COLLAPSE;
  // rows that left for good (removed offers, a reset) free their nodes
  if (cache.size > S.offers.size + 64) for (const u of cache.keys()) if (!S.offers.has(u)) cache.delete(u);
}

/** Redraw soon. While a hunt streams, at most every HUNT_THROTTLE_MS; otherwise on the next frame. */
function queue(now = false) {
  if (raf) return;
  const wait = now || S.done || !S.q ? 0 : Math.max(0, HUNT_THROTTLE_MS - (performance.now() - lastDraw));
  if (wait <= 0) { raf = requestAnimationFrame(render); return; }
  if (throttleT) return;
  throttleT = setTimeout(() => { throttleT = 0; if (!raf) raf = requestAnimationFrame(render); }, wait);
}

let priceT = 0;
export function mountLedger(el) {
  if (!el) return;
  root = el;
  root.classList.add('ledger');
  sortMode = savedSort();
  root.hidden = true;
  scaffold();
  root.addEventListener('click', e => {
    const ob = e.target.closest('[data-out], [data-back]');
    if (ob) { notOrBack(ob); return; }
    const more = e.target.closest('.lg-more');
    if (more) {
      if (more.dataset.g === 'main') {
        const fold = more.dataset.fold === '1';
        mainAll = !fold; render();
        if (fold) root.scrollIntoView({ behavior: 'auto', block: 'start' });
        return;
      }
      limits[more.dataset.g] += STEP; render(); return;
    }
    const tg = e.target.closest('.lg-gh');
    if (tg) { if (tg.dataset.tg === 'eu') euOpen = !euOpen; else riskOpen = !riskOpen; render(); return; }
    const chip = e.target.closest('.lg-chip');
    if (chip) {
      const [k, v] = chip.dataset.cond != null ? ['cond', chip.dataset.cond] : ['cc', chip.dataset.cc];
      filt[k].has(v) ? filt[k].delete(v) : filt[k].add(v);
      limits.eu = STEP; render(); refocus(`.lg-chip[data-${k}="${CSS.escape(v)}"]`); return;
    }
    if (e.target.closest('.lg-fbtn')) {
      menuOpen = !menuOpen; render();
      if (menuOpen) { const f = els.fb.querySelector('button, input'); if (f) f.focus({ preventScroll: true }); }
      return;
    }
    const vw = e.target.closest('[data-view]');
    if (vw) { view = vw.dataset.view === 'grid' ? 'grid' : 'list'; saveView(view); render(); return; }
    const st = e.target.closest('[data-bn], [data-vt]');
    if (st) {
      const k = st.dataset.bn != null ? 'bn' : 'vt';
      filt[k] = Math.max(0, Math.min(3, Number(st.dataset[k]) || 0));
      limits.eu = STEP; render(); refocus(`[data-${k}="${filt[k]}"]`); return;
    }
    const sh = e.target.closest('[data-ship]');
    if (sh) { filt.ship = sh.dataset.ship; render(); refocus(`[data-ship="${sh.dataset.ship}"]`); return; }
    if (e.target.closest('.lg-clear')) { filt = freshFilter(); render(); return; }
    const j = e.target.closest('[data-jump]');
    if (j) {
      if (j.dataset.jump === 'eu') euOpen = true; else riskOpen = true;
      render();
      const sec = j.dataset.jump === 'eu' ? els.eu : els.risk;
      sec.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
      sec.querySelector('.lg-gh').focus({ preventScroll: true });
      return;
    }
    const b = e.target.closest('.lg-r, .lg-hc');
    if (b && b.dataset.url) emit('select', b.dataset.url);
  });
  root.addEventListener('change', e => {
    if (!e.target.matches || !e.target.matches('select.lg-sort')) return;
    sortMode = sortName(e.target.value) || 'best';
    saveSort(sortMode);
    limits.eu = STEP; render();
  });
  root.addEventListener('input', e => {
    const p = e.target.closest('input[data-p]');
    if (!p) return;
    clearTimeout(priceT);
    priceT = setTimeout(() => {
      const v = p.value === '' ? null : Number(p.value);
      filt[p.dataset.p] = v != null && isFinite(v) ? v : null;
      render();
    }, 220);
  });
  root.addEventListener('keydown', e => {
    if (e.key === 'Escape' && menuOpen) { menuOpen = false; render(); els.fbtn.focus(); }
  });
  // Google's "no icon" answer is a tiny generic globe: keep the shop's initial instead
  root.addEventListener('load', e => {
    const img = e.target;
    if (img && img.classList && img.classList.contains('ph-logo') && img.naturalWidth < 32) img.remove();
  }, true);
  root.addEventListener('error', e => {
    const img = e.target;
    if (!img || img.tagName !== 'IMG' || img.closest('.flag')) return;
    if (img.classList.contains('ph-logo')) { img.remove(); return; }   // no shop mark: the initial stays
    const raw = img.dataset.raw;
    if (raw && img.src !== raw) { img.dataset.raw = ''; img.src = raw; return; }
    const ph = Object.assign(document.createElement('i'), { className: 'ph' });
    ph.dataset.l = '·';
    img.replaceWith(ph);
  }, true);
  on('reset', () => {
    limits = { main: STEP, eu: STEP, risky: 30 }; filt = freshFilter(); euOpen = false; riskOpen = true; menuOpen = false; mainAll = false;
    cache.clear(); dismissed.clear(); hlKey = ''; fbKey = '';
    for (const ol of Object.values(els.list)) ol.textContent = '';
    queue(true);
  });
  for (const t of ['offer', 'offer-removed', 'offer-restored', 'truecost', 'verdict', 'rank', 'late', 'watch', 'review', 'reviews', 'recheck', 'market', 'scope']) on(t, () => queue());
  // a listing you took out that streams in again (a later read of the same page) stays out
  on('offer', it => {
    if (!it || !dismissed.has(it.url) || S.offers.get(it.url) !== it) return;
    const old = dismissed.get(it.url);
    old.offer = Object.assign({}, old.offer, it.offer);
    S.offers.delete(it.url);
    if (S.leader === it.url) S.leader = null;
    emit('offer-removed', old);
  });
  for (const t of ['turn', 'done', 'finale:start']) on(t, () => queue(true));
  // the phone's line shows the cheapest few; "all N listings" brings you here
  on('ledger:show', () => { if (!root.hidden) root.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); });
  queue(true);
}
/** "not this" / "put back": keep the keyboard where it was (the next row's button, or the moved row's). */
function notOrBack(b) {
  const url = b.dataset.out || b.dataset.back;
  const li = b.closest('li');
  const next = li && (li.nextElementSibling || li.previousElementSibling);
  const nextUrl = next && next.querySelector('.lg-r') ? next.querySelector('.lg-r').dataset.url : null;
  const ok = b.dataset.out ? notThis(url) : putBack(url);
  if (!ok) return;
  render();
  const sel = b.dataset.out
    ? (nextUrl ? `[data-out="${CSS.escape(nextUrl)}"], .lg-r[data-url="${CSS.escape(nextUrl)}"]` : `[data-back="${CSS.escape(url)}"]`)
    : `.lg-r[data-url="${CSS.escape(url)}"]`;
  refocus(sel);
}
function refocus(sel) { const b = root.querySelector(sel); if (b) b.focus({ preventScroll: true }); }

export const _test = { groups, highlights, rows, passes, notThis, putBack, origPrice, effSort, setSort(v) { sortMode = sortName(v) || 'best'; }, setFilter(f) { filt = Object.assign(freshFilter(), f); }, setMids(m) { mids = m || {}; } };
