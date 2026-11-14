// imagefill.js: the right photo for every listing, found for free after the offers render.
//   1. BACKFILL: offers with no photo (or a placeholder, or one that failed to load) ask the server
//      (POST /api/images, plain fetch of the listing page: JSON-LD / og:image, no paid reads) for it.
//   2. VERIFY: offers people can see (the pick, the top cards, the first rows, photos on screen in the line)
//      send the photo they show; when the listing page shows another photo, the page's one replaces it
//      (a search page's row can carry its neighbour's photo). Two listings of one site with the same photo
//      are checked first.
//   3. The new photo goes into the store (item.offer.image) and into every place that shows the offer
//      (line, list rows, top cards, the pick, the receipt sheet) with a short fade; bus event 'image'.
//   4. After the hunt, ones still missing are asked once more (fresh), later.
// Lazy and polite: what is on screen first, the rest as you scroll; <= 2 requests of <= 50 listings in flight.
import { S, on, emit, isProductPhoto, goHref } from './core.js';

const BATCH = 50, IN_FLIGHT = 2, EAGER_ROWS = 40, RETRY_MS = 7000;
const st = new Map();          // url -> 'queued' | 'pending' | 'done' | 'none' | 'retried'
const failed = new Set();      // photo URLs that did not load in the browser
const prio = new Map();        // url -> lower = sooner
let inflight = 0, scanT = 0, scrollT = 0, retryT = 0, finished = false, gen = 0;

const reduce = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const sel = u => (window.CSS && CSS.escape ? CSS.escape(u) : String(u).replace(/["\\]/g, '\\$&'));

function photoOf(it) { return it && it.offer && it.offer.image; }
function missing(it) { const im = photoOf(it); return !im || !isProductPhoto(im) || failed.has(im); }

/** A size-free id of a photo (enough to spot two listings sharing one): uuid, olx file id, else the path. */
function photoKey(u) {
  if (!u) return '';
  const m = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.exec(u) || /\/v1\/files\/([^/;]+)/.exec(u);
  if (m) return (m[1] || m[0]).toLowerCase();
  try { return new URL(u).pathname.split(';')[0].toLowerCase(); } catch { return u; }
}
function host(u) { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } }

// ---------- what is on screen ----------
function onScreen(el) {
  if (!el || !el.isConnected) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.bottom > -100 && r.top < innerHeight + 300 && r.right > 0 && r.left < innerWidth;
}
/** Listing URLs people see now, most important first. */
function visibleUrls() {
  const out = [];
  const add = u => { if (u && S.offers.has(u) && !out.includes(u)) out.push(u); };
  const pick = document.querySelector('.v-pick[data-url]');
  if (pick && !pick.hidden) add(pick.dataset.url);
  const fig = document.querySelector('.v-fig img[data-url]');
  if (fig && fig.dataset.url) add(fig.dataset.url);
  for (const b of document.querySelectorAll('.lg-hc[data-url]')) add(b.dataset.url);
  for (const b of document.querySelectorAll('.lg-r[data-url]')) if (onScreen(b)) add(b.dataset.url);
  for (const f of document.querySelectorAll('.ln-o[data-key]')) if (!f.classList.contains('pip') && onScreen(f)) add(f.dataset.key);
  return out;
}
function firstRows(n) {
  const out = [];
  for (const b of document.querySelectorAll('.lg-r[data-url]')) { if (out.length >= n) break; out.push(b.dataset.url); }
  return out;
}

// ---------- queue ----------
function want(url, p, force = false) {
  const s = st.get(url);
  if (s === 'pending' || (!force && (s === 'done' || s === 'none' || s === 'retried'))) return;
  st.set(url, 'queued');
  prio.set(url, Math.min(p, prio.has(url) ? prio.get(url) : Infinity));
}
function scan() {
  scanT = 0;
  if (!S.offers.size) return;
  const vis = visibleUrls();
  // two listings of one site showing one photo: one of them has its neighbour's
  const seen = new Map(), dup = new Set();
  for (const it of S.offers.values()) {
    const im = photoOf(it); if (!im || missing(it)) continue;
    const k = host(it.url) + '|' + photoKey(im);
    if (seen.has(k)) { dup.add(it.url); dup.add(seen.get(k)); } else seen.set(k, it.url);
  }
  vis.forEach((u, i) => want(u, i));                         // on screen: fill or verify
  for (const u of dup) want(u, 100);
  if (finished) firstRows(EAGER_ROWS).forEach((u, i) => { if (missing(S.offers.get(u))) want(u, 200 + i); });
  pump();
}
function soon(ms = 500) { if (!scanT) scanT = setTimeout(scan, ms); }

async function pump() {
  while (inflight < IN_FLIGHT) {
    const urls = [...st.entries()].filter(([, s]) => s === 'queued').map(([u]) => u)
      .sort((a, b) => (prio.get(a) ?? 1e9) - (prio.get(b) ?? 1e9)).slice(0, BATCH);
    if (!urls.length) return;
    const fresh = urls.some(u => prio.get(u) === -1);
    urls.forEach(u => st.set(u, 'pending'));
    inflight++;
    const g = gen;
    request(urls, fresh).then(res => { if (g === gen) apply(urls, res); })
      .catch(() => { if (g === gen) urls.forEach(u => st.set(u, 'none')); })
      .finally(() => { inflight--; if (g === gen) pump(); });
  }
}
async function request(urls, fresh) {
  const have = {};
  for (const u of urls) { const it = S.offers.get(u); if (it && !missing(it)) have[u] = photoOf(it); }
  const r = await fetch('/api/images', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, have, fresh }) });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function apply(urls, res) {
  for (const u of urls) {
    const d = res && res[u];
    const it = S.offers.get(u);
    if (!it || !d) { st.set(u, 'none'); continue; }
    const img = d.image;
    if (img && !failed.has(img) && (d.match === 'filled' || d.match === 'replaced' || missing(it))) {
      setPhoto(it, img, d);
      st.set(u, 'done');
    } else st.set(u, img || d.match === 'same' ? 'done' : (prio.get(u) === -1 ? 'retried' : 'none'));
  }
}

// ---------- swap the photo in everywhere ----------
function fadeIn(img) {
  if (reduce()) return img;
  img.style.opacity = '0';
  img.style.transition = 'opacity .35s ease';
  const show = () => { img.style.opacity = '1'; };
  img.addEventListener('load', show, { once: true });
  img.addEventListener('error', show, { once: true });
  return img;
}
function newImg(src) {
  const img = document.createElement('img');
  img.alt = ''; img.decoding = 'async'; img.referrerPolicy = 'no-referrer'; img.draggable = false;
  img.dataset.filled = '1';
  img.src = src;
  return fadeIn(img);
}
function swapInto(box, src, raw = false) {
  if (!box) return;
  const old = box.querySelector('img:not(.ln-logo)');
  if (old) { fadeIn(old); old.src = src; if (raw) old.dataset.raw = src; if (old.dataset.fallback != null) old.dataset.fallback = src; return; }
  box.textContent = '';
  const img = newImg(src);
  if (raw) img.dataset.raw = src;
  box.appendChild(img);
}
function setPhoto(it, src, d = {}) {
  it.offer = Object.assign({}, it.offer, { image: src, image_source: d.source || null });
  const u = it.url, q = sel(u);
  // list rows + top cards (ledger.js reads it.offer.image the next time it draws the row)
  for (const b of document.querySelectorAll(`.lg-r[data-url="${q}"] .lg-pic`)) swapInto(b, src, true);
  for (const b of document.querySelectorAll(`.lg-hc[data-url="${q}"] .hc-pic`)) swapInto(b, src);
  // the line: a monogram plate becomes the photo on a plate
  for (const f of document.querySelectorAll(`.ln-o[data-key="${q}"]`)) {
    const pic = f.querySelector('.ln-pic');
    if (!pic) continue;
    f.classList.remove('mono', 'logo'); f.classList.add('raw');
    pic.style.background = '';
    if (!pic.querySelector('img:not(.ln-logo)')) pic.textContent = '';
    swapInto(pic, src);
  }
  // the verdict: hero figure + the pick card
  const fig = document.querySelector('.v-fig');
  const fimg = fig && fig.querySelector('img');
  if (fimg && fimg.dataset.url === u) { fimg.dataset.fallback = src; fadeIn(fimg); fimg.src = src; fig.classList.remove('is-mono'); fig.hidden = false; }
  const pick = document.querySelector(`.v-pick[data-url="${q}"] .vp-pic`);
  if (pick) { pick.classList.remove('is-mono'); swapInto(pick, src); }
  // the receipt sheet, when it is open on this offer
  const go = goHref(u);
  for (const a of document.querySelectorAll(`a.btn.primary[href="${sel(go)}"]`)) {
    const stage = a.closest('.paper') && a.closest('.paper').querySelector('.stage');
    if (stage) { stage.classList.remove('is-mono'); swapInto(stage, src); }
  }
  emit('image', { url: u, image: src, source: d.source || null, match: d.match || null });
}

// ---------- photos that fail to load ----------
function urlForImg(img) {
  const a = img.closest('[data-url]');
  if (a && a.dataset.url) return a.dataset.url;
  const f = img.closest('.ln-o[data-key]');
  if (f) return f.dataset.key;
  if (img.dataset.url) return img.dataset.url;
  const paper = img.closest('.paper');
  const btn = paper && paper.querySelector('a.btn.primary[href^="/go/"]');
  if (btn) for (const it of S.offers.values()) if (goHref(it.url) === btn.getAttribute('href')) return it.url;
  return null;
}
function onImgError(e) {
  const img = e.target;
  if (!img || img.tagName !== 'IMG' || img.closest('.flag') || img.classList.contains('ln-logo')) return;
  const src = img.currentSrc || img.src || '';
  if (!/^https?:/.test(src) || src.startsWith(location.origin + '/web/')) return;
  const u = urlForImg(img);
  const it = u && S.offers.get(u);
  if (!it) return;
  failed.add(src);
  if (photoOf(it) && (src === photoOf(it) || src.endsWith(encodeURIComponent(photoOf(it))))) failed.add(photoOf(it));
  if (st.get(u) === 'retried') return;
  want(u, 50, true);
  soon(300);
}

// ---------- wiring ----------
export function mountImagefill() {
  document.addEventListener('error', onImgError, true);
  on('reset', () => {
    gen++; st.clear(); prio.clear(); failed.clear(); finished = false; inflight = 0;
    clearTimeout(scanT); scanT = 0; clearTimeout(retryT);
  });
  on('offer', () => soon(800));
  for (const t of ['verdict', 'turn', 'rank', 'select']) on(t, () => soon(400));
  on('done', () => {
    finished = true;
    soon(150);
    clearTimeout(retryT);
    retryT = setTimeout(() => {           // one more try, later, for the ones still without a photo
      for (const [u, s] of st) {
        const it = S.offers.get(u);
        if (s === 'none' && it && missing(it)) { st.set(u, 'queued'); prio.set(u, -1); }
      }
      pump();
    }, RETRY_MS);
  });
  const onScroll = () => { if (!scrollT) scrollT = setTimeout(() => { scrollT = 0; scan(); }, 350); };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll, { passive: true });
  document.addEventListener('scroll', onScroll, { passive: true, capture: true });
}

export const _test = { st, failed, scan, setPhoto, photoKey };
