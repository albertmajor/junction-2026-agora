// SSE -> store -> bus (B1). One hunt at a time.
// Replays a recording when the query has one; goes live only when the lab live toggle is on.
import { S, emit, resetStore, isSetAside, slugify, pickUrl, allIn, domainOf } from './core.js';

export const cfg = {
  mode: 'auto',      // 'auto' (recording if any, else live when allowed) | 'replay' (nearest recording) | 'live'
  speed: 1,
  max_gap: 2,        // seconds: cut idle waits in replays
};

const LABELS = {
  'sony-a7-iii-body': 'Sony A7 III camera',
  'iphone-15-128gb-used': 'iPhone 15, used',
  'home-cleaning-helsinki-60m2': 'Home cleaning, Helsinki',
};
export function labelFor(slug) {
  if (LABELS[slug]) return LABELS[slug];
  const s = slug.replace(/-/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
export function queryFor(slug) { return slug.replace(/-/g, ' '); }

let recs = null;
export async function recordings() {
  if (recs) return recs;
  try {
    const r = await fetch('/recordings', { headers: { accept: 'application/json' } });
    recs = r.ok ? ((await r.json()).recordings || []) : [];
  } catch { recs = []; }
  return recs;
}

const words = s => new Set(String(s).toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length > 1));
/** Recordings ordered by word overlap with q (best first). */
export function nearest(q, list) {
  const qw = words(q);
  return list.map((slug, i) => {
    const sw = words(slug.replace(/-/g, ' '));
    let hit = 0; qw.forEach(w => { if (sw.has(w) || [...sw].some(x => x.startsWith(w) || w.startsWith(x))) hit++; });
    return { slug, score: hit / Math.max(1, new Set([...qw, ...sw]).size), i };
  }).sort((a, b) => b.score - a.score || a.i - b.i);
}

let es = null;
let gen = 0;
let turnTimer = 0, turnFirstAt = 0;
// A live hunt caps itself at about 20 s of reading. If the stream goes quiet for this long without its
// `done`, finish with what arrived instead of leaving the page on "checking N more shops" forever.
export const STALL_MS = 45000;
let stallTimer = 0;

export function stop() {
  gen++;
  if (es) { es.close(); es = null; }
  if (rs) { rs.close(); rs = null; }
  clearTimeout(turnTimer); turnTimer = 0;
  clearTimeout(stallTimer); stallTimer = 0;
}

const RATE_RE = /\b429\b|rate.?limit|too many requests/i;

// The stream ended (done, broken, stalled): an interrupted hunt still gets its Turn if costs arrived.
function finish(my, err) {
  if (my !== gen || S.done) return;
  S.done = true;
  clearTimeout(stallTimer); stallTimer = 0;
  if (es) { es.close(); es = null; }
  if (!S.turned && [...S.offers.values()].some(i => i.tc)) fireTurn();
  if (err) emit('error', err);
  emit('done', { ms: null, cut: true });
  openReviews(my);
}

// ---------- seller reviews: after the hunt, GET /reviews streams one `review` per shop ----------
let rs = null;
const REVIEW_HOSTS = 10;
/** Shops to check, most important first: the pick, then by what you pay all in. */
export function reviewHosts(offers = S.offers) {
  const host = it => String((it.offer && it.offer.source) || domainOf(it.url) || '').toLowerCase().replace(/^www\./, '');
  const out = [];
  const add = it => { const h = it && host(it); if (h && !out.includes(h) && out.length < REVIEW_HOSTS) out.push(h); };
  add(offers.get(pickUrl(offers)) || offers.get(S.leader));
  const all = [...offers.values()].filter(it => !isSetAside(it));
  const val = it => allIn(it) ?? (it.offer && it.offer.price_eur) ?? Infinity;
  all.sort((a, b) => val(a) - val(b)).forEach(add);
  return out;
}
function onReview(d) {
  for (const h of [d.domain].concat(d.hosts || [])) if (h) S.reviews.set(String(h).toLowerCase(), d);
  if (d.status !== 'checking') {
    const before = S.leader;
    repick();
    if (S.turned && before && S.leader && S.leader !== before) {
      S.recheck = { from: before, to: S.leader, domain: d.domain };
      emit('recheck', S.recheck);
    }
  }
  emit('review', d);
}
function openReviews(my) {
  if (my !== gen || rs || !S.offers.size) return;
  const hosts = reviewHosts();
  if (!hosts.length) return;
  const p = new URLSearchParams();
  if (S.hunt_id && !S.slug) p.set('hunt_id', S.hunt_id);
  p.set('domains', hosts.join(','));
  if (S.slug) p.set('paid', '0');               // a replay never spends credits: free reads and the cache
  if (S.unit === 'job') p.set('service', '1');
  hosts.forEach(h => S.reviewTargets.add(h));
  S.reviewsState = 'checking';
  emit('reviews', { state: 'checking', hosts });
  let src;
  try { src = new EventSource('/reviews?' + p.toString()); } catch { S.reviewsState = 'done'; emit('reviews', { state: 'done' }); return; }
  rs = src;
  const end = (extra = {}) => {
    if (rs === src) rs = null;
    src.close();
    if (my !== gen) return;
    S.reviewsState = 'done';
    emit('reviews', { state: 'done', ...extra });
  };
  src.onmessage = m => {
    if (my !== gen) { src.close(); return; }
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === 'review' && ev.data && ev.data.domain) onReview(ev.data);
    else if (ev.type === 'done') end(ev.data || {});
  };
  src.onerror = () => end({ error: true });
}
function armStall(my) {
  clearTimeout(stallTimer);
  if (!S.live || S.slug) { stallTimer = 0; return; }
  stallTimer = setTimeout(() => finish(my, { kind: 'net', message: S.offers.size
    ? 'The search went quiet. Showing what arrived so far.'
    : 'The search went quiet before any shop answered. Try again in a minute.' }), STALL_MS);
}

function fireTurn() {
  clearTimeout(turnTimer); turnTimer = 0;
  if (S.turned) return;
  S.turned = true;
  S.mode = 'true';
  repick();
  if (S.phase === 'hunting' || S.phase === 'start') S.phase = 'turned';
  emit('turn', {});
}

// The truecosts of a hunt land in one burst. Wait for the burst to settle so the line
// animates every object once (cap 600 ms); the final verdict fires it at once.
function armTurn() {
  if (S.turned) return;
  const now = performance.now();
  if (!turnFirstAt) turnFirstAt = now;
  clearTimeout(turnTimer);
  const wait = Math.max(0, Math.min(140, 600 - (now - turnFirstAt)));
  turnTimer = setTimeout(fireTurn, wait);
}

function itemFor(url) { return url ? S.offers.get(url) : null; }
// Once the costs are in, the leader IS the pick: the lowest all-in price you can surely buy.
function repick() {
  if (!S.turned) return;
  const u = pickUrl();
  if (u) S.leader = u;
}

function handle(ev, my) {
  if (my !== gen) return;
  const d = ev.data || {};
  switch (ev.type) {
    case 'need':
      S.need = d.need || null;
      S.hunt_id = d.hunt_id || null;
      S.unit = S.need && S.need.kind === 'service' ? 'job' : 'month';
      S.phase = 'hunting';
      emit('need', S.need);
      break;
    case 'lane': d._t = ev.t_ms; S.lanes.push(d); emit('lane', d); break;
    case 'source': d._t = ev.t_ms; S.sources.push(d); emit('source', d); break;
    case 'skip': {
      d._t = ev.t_ms;
      S.skips.push(d); emit('skip', d);
      // a page that was shown as an offer and then failed the final check leaves the line
      const it = d.rejected ? itemFor(d.url) : null;
      if (it) {
        S.offers.delete(d.url);
        if (S.leader === d.url) S.leader = null;
        repick();
        emit('offer-removed', it);
      }
      break;
    }
    case 'budget': d._t = ev.t_ms; S.budget = d; emit('budget', d); break;
    // where we looked and why (bulky things: near you first), then how big the market is (before resolve)
    case 'scope': S.scope = d; emit('scope', d); break;
    case 'market': S.market = d; if (!S.scope && d.scope) S.scope = d.scope; emit('market', d); break;
    case 'depreciation': S.depreciation = d; emit('depreciation', d); break;
    case 'thing': S.things = (S.things || []).concat(d); emit('thing', d); break;
    case 'offer': {
      const o = d.offer; if (!o || !o.url) break;
      // a shop's JSON-LD can give its photo as a path ("/image/…"): resolve it against the listing, not our origin
      if (o.image && typeof o.image === 'string' && !/^(https?:|data:)/i.test(o.image)) {
        try { o.image = new URL(o.image, o.url).href; } catch { o.image = null; }
      }
      let it = itemFor(o.url);
      if (it) { it.offer = Object.assign({}, it.offer, o); }
      else {
        it = { url: o.url, offer: o, tc: null, setAside: false, full: false, ghostX: null,
               arrived: performance.now(), late: S.turned };
        S.offers.set(o.url, it);
      }
      it._t = ev.t_ms;
      emit('offer', it);
      break;
    }
    case 'truecost': {
      const it = itemFor(d.url); if (!it) break;
      it.tc = d;
      it.setAside = isSetAside(it);
      if (d.true_cost && d.true_cost.per === 'job') S.unit = 'job';
      repick();
      emit('truecost', it);
      armTurn();
      break;
    }
    case 'rank': {
      S.rank = d;
      const top = d.top && d.top[0];
      if (top && top.url) S.leader = top.url;
      repick();
      emit('rank', d);
      break;
    }
    case 'verdict': {
      S.verdict = d;
      const v = d.verdict || {};
      const best = v.best_true_cost_url || v.best_offer_url;
      if (best && !S.leader) S.leader = best;
      repick();
      if (d.provisional === false) fireTurn();
      emit('verdict', d);
      break;
    }
    case 'late': {
      S.late.push(d);
      const it = itemFor(d.url); if (it) it.late = true;
      emit('late', d);
      break;
    }
    case 'error': {
      const msg = String(d.message || 'error');
      // a page that failed to read is not a failed hunt: list it with the skips. A 429 (Context.dev
      // allows 10 reads a minute) only costs that page; the hunt goes on with what it has.
      const limited = RATE_RE.test(msg);
      if (limited) S.rateLimited = (S.rateLimited || 0) + 1;
      const sk = { url: d.url || '', reason: limited ? 'not read: Context.dev rate limit (10 a minute)' : `could not read (${d.where || 'page'})`,
                   error: msg, where: d.where || '' };
      S.skips.push(sk); emit('skip', sk);
      break;
    }
    case 'done': {
      S.done = true;
      clearTimeout(stallTimer); stallTimer = 0;
      if (!S.turned && [...S.offers.values()].some(i => i.tc)) fireTurn();
      if (es) { es.close(); es = null; }
      if (!S.offers.size && S.rateLimited) {
        emit('error', { kind: '429', message: 'Context.dev allows 10 reads a minute and this search hit the limit. Try again in a minute: pages already read are kept.' });
      }
      emit('done', { ms: d.ms != null ? d.ms : ev.t_ms });
      openReviews(my);
      break;
    }
    default:
      emit(ev.type, d);
  }
}

function open(q, slug, { keepError = false, depth = 1 } = {}) {
  stop();
  const my = gen;
  resetStore(q);
  S.depth = depth;
  S.slug = slug || null;
  S.live = live;
  S.phase = 'hunting';
  S.done = false; S.things = []; S.hunt_id = null; S.rateLimited = 0;
  turnFirstAt = 0;
  emit('reset', { q, slug: S.slug, replay: !!slug, keepError, depth });
  const p = new URLSearchParams({ q });
  if (depth > 1 && !slug) p.set('depth', String(depth));
  if (slug) { p.set('replay', slug); p.set('speed', String(cfg.speed)); p.set('max_gap', String(cfg.max_gap)); }
  let src;
  try { src = new EventSource('/hunt?' + p.toString()); }
  catch (e) { emit('error', { kind: 'net', message: 'Could not open the stream.' }); return; }
  es = src;
  armStall(my);
  src.onmessage = m => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (my === gen && !S.done) armStall(my);
    handle(ev, my);
  };
  src.onerror = () => {
    if (my !== gen) return;
    src.close(); if (es === src) es = null;
    if (S.done) return;
    // finish what we have: an interrupted hunt still gets its Turn if costs arrived
    finish(my, { kind: 'net', message: S.offers.size ? 'The stream stopped. Showing what arrived so far.'
                                                     : 'The stream stopped before any shop answered. Try again.' });
  };
}

// Tests: drive the store without an EventSource (begin a hunt, then feed it events).
export const _test = {
  begin(q = 'test', { live: lv = true } = {}) { stop(); resetStore(q); S.live = lv; S.slug = null; S.phase = 'hunting';
    S.done = false; S.things = []; S.rateLimited = 0; turnFirstAt = 0; return gen; },
  feed(ev) { handle(ev, gen); },
  review(d) { onReview(d); },
  finish(err) { finish(gen, err); },
  stall() { finish(gen, { kind: 'net', message: 'stalled' }); },
};

let live = false;
// Live search is on by default whenever the server has a Context.dev key and is not offline.
export const liveReady = fetch('/status', { headers: { accept: 'application/json' } })
  .then(r => r.ok ? r.json() : {}).then(j => { if (j && j.live) { live = true; S.live = true; } })
  .catch(() => {});
export function setLive(on) { live = !!on; S.live = live; }
export function isLive() { return live; }

// ---------- "Compare more": the same hunt again, asking for deeper pages ----------
export const READS_PER_MIN = 10;     // Context.dev's account-wide limit
export const MORE_TOKENS = 6;        // reads a deeper hunt wants ready before it starts
/** The shared Context.dev bucket, from GET /status: {tokens, per_min} or null when the server does not say. */
export async function bucket() {
  try {
    const r = await fetch('/status', { headers: { accept: 'application/json' } });
    const j = r.ok ? await r.json() : null;
    return j && j.bucket && typeof j.bucket.tokens === 'number' ? j.bucket : null;
  } catch { return null; }
}
/** Seconds until the bucket holds `want` reads again (0 = go now). */
export function waitFor(b, want = MORE_TOKENS) {
  if (!b) return 0;
  const per = (b.per_min || READS_PER_MIN) / 60;
  return b.tokens >= want ? 0 : Math.ceil((want - b.tokens) / per);
}
/** Re-run the current hunt one level deeper. Recorded hunts cannot read more: {error:'replay'}. */
export async function compareMore() {
  const q = S.q;
  if (!q) return { error: 'none' };
  await liveReady;
  if (!live) return { error: 'offline' };
  const depth = Math.min(3, (S.depth || 1) + 1);
  open(q, null, { depth });
  return { live: true, depth };
}

/** Start a hunt for q. Resolves to {slug, live} or {error}. */
export async function startHunt(q) {
  q = String(q || '').trim().replace(/\s+/g, ' ');
  if (q.length < 2) return { error: 'short' };
  await liveReady;
  const list = await recordings();
  const slug = slugify(q);
  const has = list.includes(slug);
  if (cfg.mode === 'live' && live) { open(q, null); return { live: true }; }
  if (cfg.mode === 'replay') {
    const best = has ? slug : (nearest(q, list)[0] || {}).slug;
    if (best) { open(q, best); return { slug: best }; }
  }
  if (has) { open(q, slug); return { slug }; }
  if (live) { open(q, null); return { live: true }; }
  stop();
  resetStore(q);
  S.phase = 'start';
  emit('reset', { q, slug: null, replay: false, empty: true });
  const order = nearest(q, list).map(r => r.slug);
  emit('error', { kind: '404', message: 'Offline we have three recorded searches. Try one of these.',
                  suggestions: order });
  return { error: '404', suggestions: order };
}
