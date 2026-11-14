// The mascot's moods, from the owner's animations (assets/animations; web-sized copies in /web/assets/mascot,
// cropped so every mood stands on the same feet with its right edge in the same place):
//   eat        the start screen, beside the box, chewing his banana
//   idle       standing still (a provisional answer, a done hunt)
//   searching  peeking over the live log while the hunt reads pages
//   thinking   while costing / judging (first answer in, final not yet) and while the intent chips decide
//   found-it   once, when the final verdict lands (peeking over the pick card), then a still frame
// One monkey at a time. Animated WebP with a GIF fallback; prefers-reduced-motion gets a still frame (a
// <source media> does that, no JS); a hidden tab gets the still too, so nothing animates unseen.
// Module scope never touches the DOM: node tests import livelog.js and verdict.js, which import this.
import { S, on } from './core.js';

const BASE = '/web/assets/mascot/';
export const MOODS = ['idle', 'eat', 'searching', 'thinking', 'found-it'];
export const ONCE_MS = 2000;                 // found-it's length (37 frames at 50-60 ms)
const STILL = { 'found-it': 'monkey-found-it-still.png', eat: 'monkey-eat-still.png' };

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** The files for a mood: {still, webp, gif}; still=true points all three at the still frame. */
export function srcs(mood, { still = false } = {}) {
  if (!MOODS.includes(mood)) mood = 'idle';
  const s = BASE + (STILL[mood] || 'monkey-idle-still.png');
  if (still) return { still: s, webp: s, gif: s };
  return { still: s, webp: `${BASE}monkey-${mood}.webp`, gif: `${BASE}monkey-${mood}.gif` };
}

/** <picture> markup for a mood (decorative: aria-hidden, empty alt). */
export function picture(mood, { cls = '', w = 0, h = 0, lazy = false } = {}) {
  const f = srcs(mood);
  const size = w && h ? ` width="${w}" height="${h}"` : '';
  return `<picture class="mk${cls ? ' ' + esc(cls) : ''}" data-mood="${esc(mood)}" aria-hidden="true">`
    + `<source media="(prefers-reduced-motion: reduce)" srcset="${f.still}">`
    + `<source type="image/webp" srcset="${f.webp}">`
    + `<img src="${f.gif}" alt=""${size} decoding="async"${lazy ? ' loading="lazy"' : ''}></picture>`;
}

/** Swap a <picture class="mk"> to another mood (no-op when nothing changes, so a loop never restarts). */
export function setMood(pic, mood, { still = false, webp = null } = {}) {
  if (!pic) return;
  const f = srcs(mood, { still });
  if (webp && !still) f.webp = webp;
  const key = `${mood}|${still ? 1 : 0}|${f.webp}`;
  if (pic.dataset.k === key) return;
  pic.dataset.k = key;
  pic.dataset.mood = mood;
  pic.dataset.still = still ? '1' : '';
  const [rm, wp] = pic.querySelectorAll('source');
  const img = pic.querySelector('img');
  if (rm) rm.srcset = f.still;
  if (wp) wp.srcset = f.webp;
  if (img) img.src = f.gif;
}

// ---------- what each spot shows, from the store (pure: tested in node) ----------
const isFinal = v => !!(v && v.provisional === false);
/** Over the live log: thinking once a first answer is being costed, else searching. */
export function peekMood(s, deciding = false) {
  return deciding || (s && s.verdict && !isFinal(s.verdict)) ? 'thinking' : 'searching';
}
/** Over the pick card: found-it on the final verdict (played once), thinking before it, a still after. */
export function pickMood(s, { played = false, done = false } = {}) {
  if (s && isFinal(s.verdict)) return played ? ['found-it', true] : ['found-it', false];
  if (done) return ['idle', true];
  return ['thinking', false];
}

// ---------- the browser side ----------
let mounted = false, deciding = false, played = false, done = false, playing = false, onceTimer = 0, blobUrl = '';
let pickEl = null;
const RM = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

// found-it plays once: a once-only animation shares its timeline per URL, so each play gets a fresh blob URL
// of the same bytes (fetched once)
let foundBlob = null;
function foundBytes() {
  if (!foundBlob && typeof fetch === 'function') {
    foundBlob = fetch(srcs('found-it').webp).then(r => (r.ok ? r.blob() : null)).catch(() => null);
  }
  return foundBlob || Promise.resolve(null);
}
// light preloading: a mood's file, once, at low priority, only when it will be needed soon
const warmed = new Set();
function warm(mood) {
  if (warmed.has(mood) || RM() || typeof fetch !== 'function') return;
  warmed.add(mood);
  if (mood === 'found-it') { foundBytes(); return; }
  try { fetch(srcs(mood).webp, { priority: 'low' }).catch(() => {}); } catch {}
}

/** The monkey that peeks over the pick card (verdict.js re-attaches it after each re-render of the card). */
export function pickMonkey() {
  if (typeof document === 'undefined') return null;
  if (!pickEl) {
    pickEl = document.createElement('span');
    pickEl.className = 'vp-mk';
    pickEl.setAttribute('aria-hidden', 'true');
    pickEl.innerHTML = picture('thinking', { w: 64, h: 112 });
    refresh();
  }
  return pickEl;
}

function playFound(pic) {
  played = true;
  clearTimeout(onceTimer);
  if (RM() || hidden()) { setMood(pic, 'found-it', { still: true }); return; }
  playing = true;
  foundBytes().then(b => {
    if (!playing) return;                    // the tab went away meanwhile (or a new hunt began)
    if (blobUrl) { try { URL.revokeObjectURL(blobUrl); } catch {} blobUrl = ''; }
    if (b && typeof URL !== 'undefined' && URL.createObjectURL) blobUrl = URL.createObjectURL(b);
    setMood(pic, 'found-it', { webp: blobUrl || `${srcs('found-it').webp}?r=${Date.now()}` });
    // then settle on the last frame (the same pose, as a still), so nothing replays later
    onceTimer = setTimeout(() => { playing = false; setMood(pic, 'found-it', { still: true }); }, ONCE_MS + 150);
  });
}

function refresh() {
  if (typeof document === 'undefined') return;
  const still = hidden();
  const start = document.querySelector('#start .start-monkey');
  if (start) setMood(start, deciding ? 'thinking' : 'eat', { still });
  const peek = document.querySelector('#reading .ll-peek');
  if (peek) setMood(peek, peekMood(S, deciding), { still });
  const pic = pickEl && pickEl.querySelector('.mk');
  if (pic && !playing) {
    const [mood, st] = pickMood(S, { played, done });
    if (mood === 'found-it' && !st) playFound(pic);
    else setMood(pic, mood, { still: st || still });
  }
}

/** main.js: the intent chips are working out what was meant (the start monkey thinks meanwhile). */
export function setDeciding(v) {
  deciding = !!v;
  if (deciding) warm('thinking');
  refresh();
}

export function mountMascot() {
  if (mounted || typeof document === 'undefined') return;
  mounted = true;
  on('reset', d => {
    played = false; done = false; playing = false; clearTimeout(onceTimer); onceTimer = 0;
    if (d && d.q && !d.empty) { warm('thinking'); warm('found-it'); }
    refresh();
  });
  for (const t of ['need', 'verdict', 'turn']) on(t, refresh);
  on('done', () => { done = true; refresh(); });
  on('error', e => { if (e && (e.kind === 'net' || e.kind === '429')) done = true; refresh(); });
  document.addEventListener('visibilitychange', () => {
    if (hidden()) {
      clearTimeout(onceTimer); onceTimer = 0; playing = false;
      document.querySelectorAll('picture.mk').forEach(p => setMood(p, p.dataset.mood || 'idle', { still: true }));
    } else refresh();
  });
  // the hunt is about to start: fetch the live-log monkey while the question is typed (wide screens show it)
  const ask = document.getElementById('ask');
  if (ask && typeof matchMedia === 'function') {
    ask.addEventListener('focusin', () => { if (matchMedia('(min-width: 641px)').matches) warm('searching'); });
  }
  refresh();
}

/** Where the start-screen monkey stands, relative to the search box (#ask): his left edge `dx` px right of the
 *  box's right edge, his feet `dy` px below the box's bottom; `w` = width in px; `flip` mirrors him; `rot` tilts.
 *  The owner sets these with the monkey devtool (?monkeydev=1 or Ctrl+Shift+M on localhost) and exports JSON. */
export const MONKEY_PLACE = { dx: 22, dy: 0, w: 75, flip: false, rot: 0 };
const LOCAL = () => typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
export function monkeyPlace() {
  if (LOCAL()) {
    try { const o = JSON.parse(localStorage.getItem('pm.monkeyPlace') || 'null'); if (o) return { ...MONKEY_PLACE, ...o }; } catch {}
  }
  return MONKEY_PLACE;
}

export function placeStartMonkey(cfg = monkeyPlace()) {
  if (typeof document === 'undefined') return;
  const m = document.querySelector('#start .start-monkey');
  const start = document.getElementById('start');
  const ask = document.getElementById('ask');
  if (!m || !start || !ask || !m.offsetParent) return;
  const s = start.getBoundingClientRect(), a = ask.getBoundingClientRect();
  const img = m.querySelector('img');
  m.style.width = `${cfg.w}px`; if (img) { img.style.width = `${cfg.w}px`; img.style.height = 'auto'; }
  const h = (img && img.getBoundingClientRect().height) || cfg.w * 131 / 75;
  m.style.left = `${Math.round(a.right - s.left + cfg.dx)}px`;
  m.style.top = `${Math.round(a.bottom - s.top - h + cfg.dy)}px`;
  if (img) img.style.transform = `${cfg.flip ? 'scaleX(-1) ' : ''}rotate(${cfg.rot || 0}deg)`;
}
if (typeof window !== 'undefined') {
  const go = () => requestAnimationFrame(() => placeStartMonkey());
  window.addEventListener('resize', go);
  window.addEventListener('load', go);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(go);
  setTimeout(go, 50); setTimeout(go, 600);
  if (LOCAL()) {
    const open = () => import('./monkeydev.js').then(m => m.openMonkeyDev()).catch(e => console.warn('monkeydev', e));
    if (/[?&]monkeydev=1\b/.test(location.search)) setTimeout(open, 300);
    window.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'm') { e.preventDefault(); open(); } });
  }
}
