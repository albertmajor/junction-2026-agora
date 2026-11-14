// Boot, start screen, header, need chips, ticker, URL state, keys, lab panel, stage script (B1).
import { S, bus, emit, on, eur, domainOf, resetStore, allIn, isJobItem, pickUrl, shipsUnconfirmed, BRAND } from './core.js';
import * as stream from './stream.js';
import { mountMascot, setDeciding } from './mascot.js';
if (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)) import('./devtools.js').then(m => m.init()).catch(e => console.warn('[agora] devtools', e)); // dev type panel: local only (?dev=1, Ctrl/Cmd+Shift+D)

const $ = id => document.getElementById(id);
const app = $('app'), bar = $('bar'), ask = $('ask'), qIn = $('q'), start = $('start'), h1 = start.querySelector('h1');
const chipsEl = $('chips'), ticker = $('ticker'), statusEl = $('status'), labEl = $('lab');
const params = new URLSearchParams(location.search);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- phase + header collapse ----------
function setPhase(p) {
  S.phase = p;
  if (app.dataset.phase === p) return;
  app.dataset.phase = p;
  placeBox();
}
function placeBox() {
  const home = app.dataset.phase === 'start';
  const want = home ? start : bar;
  if (ask.parentElement === want) return;
  const hadFocus = document.activeElement === qIn;
  if (home) h1.after(ask); else bar.querySelector('.logo').after(ask);
  if (hadFocus) qIn.focus({ preventScroll: true });
}

// ---------- modules (tolerate missing ones) ----------
let line = null;
const mods = {};
async function load(name) {
  try { return (mods[name] = await import(`./${name}.js`)); }
  catch (e) { console.warn(`[agora] module ${name}.js not loaded:`, e && e.message); return null; }
}
async function mountAll() {
  const lineMod = await load('line');
  if (lineMod) {
    try { lineMod.mountLine($('line')); line = lineMod.line || null; }
    catch (e) { console.warn('[agora] mountLine failed', e); }
  }
  const ll = await load('livelog');
  if (ll && ll.mountLivelog) { try { ll.mountLivelog($('reading'), line); } catch (e) { console.warn('[agora] mountLivelog failed', e); } }
  const sg = await load('suggest');
  if (sg && sg.mountSuggest) { try { sg.mountSuggest(ask, qIn); } catch (e) { console.warn('[agora] mountSuggest failed', e); } }
  load('imagefill').then(m => { try { m && m.mountImagefill && m.mountImagefill(); } catch (e) { console.warn('[agora] mountImagefill failed', e); } });
  const im = await load('intent');
  if (im && im.mountIntents) { try { im.mountIntents($('intents')); } catch (e) { console.warn('[agora] mountIntents failed', e); } }
  const cp = await load('catpage');
  if (cp && cp.mountCatpage) { try { cp.mountCatpage($('catpage')); } catch (e) { console.warn('[agora] mountCatpage failed', e); } }
  const lm = await load('landing');
  if (lm && lm.mountLanding) { try { lm.mountLanding($('landing')); } catch (e) { console.warn('[agora] mountLanding failed', e); } }
  const plan = [
    ['verdict', 'mountVerdict', 'verdict'], ['sheet', 'mountSheet', 'sheet'], ['drawer', 'mountDrawer', 'drawer'],
    ['agent', 'mountAgent', 'agent'], ['tag', 'mountTag', 'tag', true], ['finale', 'mountFinale', 'finale', true],
    ['ledger', 'mountLedger', 'ledger'], ['market', 'mountMarket', 'market'],
  ];
  await Promise.all(plan.map(async ([name, fn, id, withLine]) => {
    const m = await load(name);
    if (m && typeof m[fn] === 'function') {
      try { withLine ? m[fn]($(id), line) : m[fn]($(id)); }
      catch (e) { console.warn(`[agora] ${fn} failed`, e); }
    }
  }));
}

// ---------- start screen ----------
async function renderExamples() {
  const list = await stream.recordings();
  const order = ['sony-a7-iii-body', 'iphone-15-128gb-used', 'home-cleaning-helsinki-60m2'];
  const slugs = [...order.filter(s => list.includes(s)), ...list.filter(s => !order.includes(s))].slice(0, 3);
  const box = $('examples');
  box.innerHTML = '';
  slugs.forEach(slug => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'ex'; b.textContent = stream.labelFor(slug);
    b.dataset.q = stream.queryFor(slug);
    b.addEventListener('click', () => run(b.dataset.q));
    box.appendChild(b);
  });
}

// ---------- run / URL state ----------
// A broad category never hunts its own label (owner, 14 Nov: "Lifestyle Services" ran a hunt for those words and
// showed junk). A category with huntable === false, or typed words that are exactly the name of one ("home
// services", "electronics"), open its CATEGORY PAGE instead; typed words that only classify into a broad node
// ("massage in tampere") still hunt the person's own words. free = never redirect (the page's "search everything").
const within = (p, ms) => Promise.race([p, new Promise(r => setTimeout(() => r(null), ms))]);
async function browseInstead(q, cat) {
  let C = null;
  try { C = await import('./cats.js'); } catch { return null; }
  if (cat && cat.id) {
    if (cat.huntable === false) return { id: cat.id };
    if (cat.huntable === true) return null;
    const r = await within(C.nodes([cat.id]), 900);
    const n = r && r.items && r.items[0];
    return n && n.huntable === false ? { id: n.id } : null;
  }
  const r = await within(C.classify(q), 900);
  const m = r && r.match;
  if (!m) return null;
  if (m.browse) return { id: m.browse.id, typed: q };
  if (m.huntable === false && m.exact) return { id: m.id, typed: q };
  return null;
}
function openCategory(id, { push = true, typed = '' } = {}) {
  if (!id) return;
  stream.stop();
  resetStore('');
  qIn.value = typed || '';
  if (push) {
    const u = new URL(location.href);
    for (const k of ['q', 'cat', 'intent', 'share', 'by', 'browse', 'typed']) u.searchParams.delete(k);
    u.searchParams.set('c', id);
    if (typed) u.searchParams.set('typed', typed);
    u.hash = '';
    if (u.href !== location.href) history.pushState({ c: id }, '', u);
  }
  clearChips(); tickerOff(); setStatus(null); showCrumbs(null);
  setPhase('category');
  emit('reset', { q: '' });
  emit('catpage', { id, typed });
  scrollTo({ top: 0, behavior: 'auto' });
}
on('category', d => { if (d && d.id) openCategory(d.id, { typed: d.typed || '' }); });
on('category:home', () => {
  goHome();
  const b = document.getElementById('ld-browse');
  if (b) setTimeout(() => b.scrollIntoView({ block: 'start' }), 60);
});
on('catpage:shown', d => {        // an old id (merged away) shows its new home: keep the URL honest
  if (!d || !d.asked || d.asked === d.id) return;
  const u = new URL(location.href);
  if (u.searchParams.get('c') === d.asked) { u.searchParams.set('c', d.id); history.replaceState(history.state, '', u); }
});

// What the words most likely mean (owner, 14 Nov: "lunch" priced €4 lunch boxes, "not even services"): a typed
// hunt asks /api/intent first and hunts the likeliest meaning ("Lunch places near you", in Restaurants, with the
// lunch-menu sites), keeping the typed words in the box. intent.js shows which, and the other meanings as chips
// when the top one is not clearly it. plan = a meaning picked by a chip / the category page; intent = its id (URL).
async function run(q, { push = true, cat = null, free = false, intent = null, plan = null, interp = null } = {}) {
  q = String(q || '').trim().replace(/\s+/g, ' ');
  if (q.length < 2) { qIn.focus(); return; }
  const I = mods.intent || null;
  // the monkey thinks while the meaning (and the category) is worked out; the hunt or the category page ends it
  setDeciding(true);
  try { return await runDecided(q, I, { push, cat, free, intent, plan, interp }); } finally { setDeciding(false); }
}
async function runDecided(q, I, { push, cat, free, intent, plan, interp }) {
  if (I && !plan && !cat && !free) {
    interp = interp || await within(I.interpret(q), 900);
    const list = (interp && interp.intents) || [];
    plan = (intent && list.find(x => x.id === intent)) || list[0] || null;
  } else if (I && !plan && cat && cat.id && !free && cat.huntable !== false) {
    // a hunt from the tree: a category with a plan of its own ('School catering' -> catering companies, in
    // Finnish, on their own sites) hunts that plan; any other keeps its words, with next steps if nothing turns up
    interp = await within(I.interpret(q, { cat: cat.id }), 900);
    const top = interp && interp.intents && interp.intents[0];
    plan = top && top.source === 'curated' && top.node === cat.id ? top
      : (interp ? { id: '_typed', label: q, as_typed: true, hunt: null } : null);
    if (interp) interp = { ...interp, dominant: true };
  }
  const rw = !!(I && plan && I.rewrites(plan));
  if (!free && !rw && !(interp && interp.concept)) {
    const dest = await browseInstead(q, cat);
    if (dest) { openCategory(dest.id, { push, typed: dest.typed || '' }); return; }
  }
  const huntCat = rw ? (plan.hunt.cat ? { id: plan.hunt.cat, huntable: true } : null) : cat;
  qIn.value = q;
  if (push) {
    const u = new URL(location.href);
    u.searchParams.set('q', q);
    if (rw) { u.searchParams.set('intent', plan.id); u.searchParams.delete('cat'); }
    else { u.searchParams.delete('intent'); if (cat && cat.id) u.searchParams.set('cat', cat.id); else u.searchParams.delete('cat'); }
    for (const k of ['share', 'by', 'browse', 'c', 'typed']) u.searchParams.delete(k);
    if (u.href !== location.href) history.pushState({ q }, '', u);
  }
  showCrumbs(rw ? plan.hunt.q : q, huntCat);
  if (I) { if (interp && plan) I.show(q, interp, plan); else I.clear(); }
  setStatus('hunt', 'reading the question…');
  setDeciding(false);
  setPhase('hunting');
  await stream.startHunt(q, rw ? { send: plan.hunt.q, cat: plan.hunt.cat, intent: plan.hunt.intent || plan.id } : {});
}
function goHome({ push = true } = {}) {
  stream.stop();
  resetStore('');
  qIn.value = '';
  if (push) {
    const u = new URL(location.href);
    for (const k of ['q', 'cat', 'intent', 'c', 'typed']) u.searchParams.delete(k);
    if (u.href !== location.href) history.pushState({}, '', u);
  }
  clearChips(); tickerOff(); setStatus(null); showCrumbs(null);
  if (mods.intent) mods.intent.clear();
  setPhase('start');
  emit('reset', { q: '' });
  document.title = BRAND;
}
ask.addEventListener('submit', e => { e.preventDefault(); run(qIn.value); });
// a landing card (or 'what an agent sees') asks for a search: back to the top, then run it
on('ask', d => { if (!d || !d.q) return; scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); run(d.q, { cat: d.cat || null, free: !!d.free, plan: d.plan || null, interp: d.interp || null }); });
bar.querySelector('.logo').addEventListener('click', e => {
  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault(); goHome();
});
addEventListener('popstate', () => {
  const sp = new URLSearchParams(location.search), q = sp.get('q');
  if (sp.get('c')) openCategory(sp.get('c'), { push: false, typed: sp.get('typed') || '' });
  else if (q) run(q, { push: false, cat: sp.get('cat') ? { id: sp.get('cat') } : null, intent: sp.get('intent') }); else goHome({ push: false });
});

// ---------- category breadcrumb (from the tree of everything you can buy) ----------
// A hunt started from a category shows its path; a typed one shows the tree's best guess when it is sure.
let crumbSeq = 0;
async function showCrumbs(q, cat) {
  const el = $('crumbs');
  if (!el) return;
  const my = ++crumbSeq;
  el.hidden = true; el.innerHTML = '';
  if (!q) return;
  let C = null;
  try { C = await import('./cats.js'); } catch { return; }
  let ids = cat && cat.ids, path = cat && cat.path, guess = false;
  if (cat && cat.id && !(ids && path && ids.length === path.length)) {
    const r = await C.nodes([cat.id]);
    const n = r && r.items && r.items[0];
    if (n) { ids = n.path_ids; path = n.path; }
  }
  if (!ids) {
    const r = await C.api('/api/categories/classify', { q });
    const m = r && r.match;
    if (!m || m.confidence < 0.6) return;
    ids = m.path_ids; path = m.path; guess = true;
  }
  if (my !== crumbSeq || !ids || !ids.length) return;
  const sep = '<span class="cb-sep" aria-hidden="true">›</span>';
  el.dataset.guess = guess ? '1' : '';
  el.innerHTML = `${C.icon(ids[0], 'ct-ic cb-ic')}<span class="sr">Category: </span>` + ids.map((id, k) =>
    `<a href="/?browse=${encodeURIComponent(id)}#ld-browse" data-browse="${esc(id)}"${k === ids.length - 1 ? ' aria-current="page"' : ''}>${esc(String(path[k] || '').replace(/\u00ad/g, ''))}</a>`).join(sep)
    + (guess ? `<span class="cb-guess" title="The category tree's best guess for what you typed">best guess</span>` : '');
  el.hidden = false;
}
$('crumbs') && $('crumbs').addEventListener('click', e => {
  const a = e.target.closest('[data-browse]');
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  goHome();
  emit('browse', { id: a.dataset.browse });
});

// ---------- status line ----------
// monkey: the mascot shrugs beside a "found nothing" message (the only place he appears in the results)
function setStatus(kind, text, extra = '', { monkey = false } = {}) {
  statusEl.classList.toggle('err', kind === 'err');
  statusEl.classList.toggle('none', !!(kind && monkey));
  statusEl.dataset.kind = kind || '';
  if (!kind) { statusEl.innerHTML = ''; return; }
  statusEl.innerHTML = monkey
    ? `<img class="st-monkey" src="/web/assets/brand/mascot.svg" width="44" height="80" alt=""><span class="st-text"><span class="dot" aria-hidden="true"></span>${esc(text)}${extra}</span>`
    : `<span class="dot" aria-hidden="true"></span>${esc(text)}${extra}`;
}

// ---------- need chips ----------
function clearChips() { chipsEl.innerHTML = ''; chipsEl.hidden = true; }
function chipList(need) {
  const out = [];
  if (!need) return out;
  // the query is already in the box: only say what we understood when it differs from what was typed
  const thing = titleCase(need.thing || need.raw || S.q);
  const norm = x => String(x || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  // (not when the row of meanings already says what we hunt: 'Searching for Lunch places near you')
  const said = $('intents') && !$('intents').hidden;
  if (!said && norm(thing) && !norm(S.q).includes(norm(thing))) out.push({ kind: 'thing', text: thing });
  // a condition chip only when the user typed that condition (an implied one is not a filter to remove)
  const conds = (need.conditions || []).filter(c => c !== 'service' && typedCond(c));
  conds.forEach(c => out.push({ kind: 'cond', text: c, cond: c }));
  if (need.budget) out.push({ kind: 'budget', text: `under ${eur(need.budget)}` });
  if (need.where) out.push({ kind: 'where', text: `in ${need.where}`, word: need.where });
  (need.must_have || []).forEach(m => out.push({ kind: 'must', text: m, word: m }));
  return out;
}
const COND_ALIAS = { refurbished: ['refurbished', 'refurb', 'renewed'], used: ['used', 'second hand', 'pre-owned', 'käytetty'],
                     new: ['new'], rental: ['rental', 'rent', 'hire'] };
function typedCond(c) {
  const q = ' ' + String(S.q || '').toLowerCase() + ' ';
  return (COND_ALIAS[c] || [c]).some(a => q.includes(' ' + a + ' '));
}
function titleCase(s) {
  s = String(s || '');
  s = s.replace(/\bi(phone|pad|mac)\b/gi, (m, r) => 'i' + r.charAt(0).toUpperCase() + r.slice(1).toLowerCase());
  return /^i[A-Z]/.test(s) ? s : s.charAt(0).toUpperCase() + s.slice(1);
}
function renderChips(need) {
  chipsEl.innerHTML = '';
  chipList(need).forEach(c => {
    const el = document.createElement('span');
    el.className = 'chip ' + c.kind;
    if (c.kind === 'thing') { el.innerHTML = `understood as <b>${esc(c.text)}</b>`; chipsEl.appendChild(el); return; }
    el.textContent = c.text;
    if (c.kind !== 'thing' && !c.fixed) {
      const x = document.createElement('button');
      x.type = 'button'; x.setAttribute('aria-label', `search again without “${c.text}”`); x.textContent = '×';
      x.addEventListener('click', () => { el.classList.add('gone'); setTimeout(() => run(without(c)), 160); });
      el.appendChild(x);
    }
    chipsEl.appendChild(el);
  });
  chipsEl.hidden = !chipsEl.children.length;
}
function without(c) {
  const q = S.q;
  const strip = w => {
    const re = new RegExp(`(^|\\s)${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=\\s|$)`, 'i');
    return re.test(q) ? q.replace(re, ' ').replace(/\s+/g, ' ').trim() : null;
  };
  if (c.kind === 'cond') {
    const alias = COND_ALIAS[c.cond] || [c.cond];
    for (const a of alias) { const r = strip(a); if (r != null) return r; }
    // the condition was implied: keep the others explicitly
    const rest = (S.need.conditions || []).filter(x => x !== c.cond);
    return `${q} ${rest.join(' ')}`.trim();
  }
  if (c.kind === 'budget') return q.replace(/\b(under|below|max|<)\s*€?\s*\d[\d.,]*\s*(€|eur|euros?)?/i, '').replace(/\s+/g, ' ').trim();
  if (c.word) { const r = strip(c.word); if (r != null) return r; }
  return q;
}

// ---------- ticker ----------
let tickPending = null, tickTimer = 0, tickLast = 0;
function tickerOff() { ticker.hidden = true; clearTimeout(tickTimer); tickPending = null; }
function tick(html) {
  tickPending = html;
  if (tickTimer) return;
  const wait = Math.max(0, 250 - (performance.now() - tickLast));
  tickTimer = setTimeout(flushTick, wait);
}
function flushTick() {
  tickTimer = 0;
  if (tickPending == null) return;
  tickLast = performance.now();
  const holder = ticker.querySelector('.tick-text');
  const old = holder.querySelector(':scope > span:not(.out)');
  const nu = document.createElement('span');
  nu.innerHTML = tickPending; tickPending = null;
  nu.classList.add('out');
  holder.appendChild(nu);
  requestAnimationFrame(() => {
    nu.classList.remove('out');
    if (old) { old.classList.add('out'); setTimeout(() => old.remove(), 260); }
  });
  ticker.hidden = false;
}
// a live hunt reads for about 20 s (the engine's budget): a quiet clock shows how far along it is
const LIVE_BUDGET_S = 20;
const PHONE = matchMedia('(max-width: 640px)');
const RM = matchMedia('(prefers-reduced-motion: reduce)');
let clockT0 = 0, clockTimer = 0;
function clockEl() {
  let c = ticker.querySelector('.tick-clock');
  if (!c) {
    c = document.createElement('span');
    c.className = 'tick-clock';
    c.setAttribute('aria-hidden', 'true');
    c.innerHTML = '<i class="tc-bar"><i></i></i><span class="tc-s"></span>';
    ticker.appendChild(c);
  }
  return c;
}
function clockStart() {
  clockStop(true);
  clockT0 = performance.now();
  const c = clockEl(); c.hidden = false; c.classList.remove('end');
  const paint = () => {
    const s = (performance.now() - clockT0) / 1000;
    c.querySelector('.tc-bar > i').style.width = Math.min(100, s / (LIVE_BUDGET_S + 2) * 100).toFixed(1) + '%';
    c.querySelector('.tc-s').textContent = s < LIVE_BUDGET_S + 2 ? `${Math.floor(s)} s` : 'finishing…';
  };
  paint();
  clockTimer = setInterval(paint, 250);
}
function clockStop(hide) {
  clearInterval(clockTimer); clockTimer = 0;
  const c = ticker.querySelector('.tick-clock');
  if (!c) return;
  if (hide) { c.hidden = true; return; }
  c.classList.add('end');
  c.querySelector('.tc-bar > i').style.width = '100%';
  setTimeout(() => { if (!clockTimer) c.hidden = true; }, 1200);
}
function counts() {
  const shops = new Set(S.sources.map(s => s.domain || domainOf(s.url)));
  return `${shops.size} shop${shops.size === 1 ? '' : 's'} · ${S.offers.size} offer${S.offers.size === 1 ? '' : 's'}`;
}
let lastDomain = '';
$('how-top').addEventListener('click', e => { e.preventDefault(); emit('drawer', { open: true }); });

// ---------- agent door ----------
let agentOn = false;
on('agent', d => { agentOn = !!(d && d.on); });
const toAgent = e => { e.preventDefault(); emit('agent', { on: !agentOn }); };
$('agent-top').addEventListener('click', toAgent);

// ---------- store -> chrome ----------
on('reset', d => {
  lastDomain = '';
  clearChips();
  if (d && d.q && !d.empty && !d.replay && PHONE.matches) clockStart(); else clockStop(true);
  if (!d || !d.q) return;
  qIn.value = d.q;
  document.title = `${d.q} · ${BRAND}`;
  if (!d.empty) {
    setPhase('hunting');
    if (!d.keepError) setStatus('hunt', d.replay ? 'hunting… (recorded hunt)' : 'hunting… live');
    ticker.querySelector('.tick-text').innerHTML = '';
    tick(d.replay ? `replaying a recorded hunt · ${esc(d.slug)}` : 'reading the question');
  }
});
on('need', need => {
  setPhase(S.phase === 'start' ? 'hunting' : S.phase);
  renderChips(need);
  // the verdict area says "hunting…" from here on; this line only covers for a missing verdict module
  if (!statusEl.classList.contains('err')) setStatus(mods.verdict ? null : 'hunt', 'hunting…');
  tick(`looking for <b>${esc(need && need.thing)}</b>`);
});
on('lane', l => tick(`searching ${esc(l.lane)} · ${esc((l.queries || [])[0] || '')}`));
on('source', s => { lastDomain = s.domain || domainOf(s.url); tick(`reading <b>${esc(lastDomain)}</b> · ${counts()}`); });
on('offer', it => { const d = domainOf(it.url) || it.offer.source; tick(`<b>${esc(it.offer.source || d)}</b> ${eur(it.offer.price_eur)} · ${counts()}`); });
on('skip', sk => { if (lastDomain) tick(`reading <b>${esc(lastDomain)}</b> · ${counts()}<span class="tk-sk"> · ${S.skips.length} skipped</span>`); });
on('verdict', v => {
  if (!statusEl.classList.contains('err')) setStatus(null);
  if (v && v.provisional && v.pending_reads) tick(`first answer · checking ${v.pending_reads} more shop${v.pending_reads === 1 ? '' : 's'} · ${counts()}`);
});
on('turn', () => setPhase(S.phase === 'start' ? 'turned' : (S.phase === 'hunting' ? 'turned' : S.phase)));
on('watch', () => { if (S.phase !== 'finale') setPhase('watch'); });
on('finale:start', () => setPhase('finale'));
on('done', d => {
  const secs = d && d.ms != null ? ` · ${(d.ms / 1000).toFixed(1)} s` : '';
  const n = S.offers.size;
  tick(`${d && d.cut ? 'stopped ·' : '✓'} ${n} offer${n === 1 ? '' : 's'} from ${S.sources.length} page${S.sources.length === 1 ? '' : 's'}${secs}`);
  clockStop(false);
  if (statusEl.classList.contains('err')) return;
  setStatus(null);
  const note = endStatus();
  if (note) setStatus(note[0], note[1], '', { monkey: n === 0 });
});
// what the end of a hunt says when it found little: honest, and what to do about it
function endStatus() {
  const n = S.offers.size, pages = S.sources.length;
  const timedOut = S.skips.filter(k => /budget|out of time|timed? ?out|rate limit/i.test(String(k.reason || ''))).length;
  if (n === 0) {
    if (!pages) return ['err', 'No shop pages turned up for that. Try fewer words, or the name a shop would use.'];
    if (timedOut) return ['err', `No offer in time: ${timedOut} of ${pages} pages waited on the read limit (Context.dev allows 10 a minute). Try again in a minute: what we read is kept.`];
    return ['err', `None of the ${pages} pages we read had a price we could check. Try fewer words, or the name a shop would use.`];
  }
  if (n <= 2 && S.live && !S.slug && timedOut) {
    return ['note', `Only ${n} offer${n === 1 ? '' : 's'} in time: ${timedOut} page${timedOut === 1 ? '' : 's'} waited on the 10-a-minute read limit. Searching again in a minute reads more.`];
  }
  return null;
}
on('error', e => {
  if (e.kind === 'net' || e.kind === '429') {
    clockStop(false);
    tick(`stopped · ${counts()}`);
  }
  if (e.kind === '404') {
    setPhase('start');
    // the examples are right there: put the closest recording first instead of repeating them
    const box = $('examples');
    (e.suggestions || []).slice().reverse().forEach(slug => {
      const b = box.querySelector(`.ex[data-q="${CSS.escape(stream.queryFor(slug))}"]`);
      if (b) box.prepend(b);
    });
    setStatus('err', e.message, '', { monkey: true });
    box.after(statusEl);
  } else {
    setStatus('err', e.message);
  }
});
// on the start screen the status sits under the examples; otherwise above the verdict
on('reset', d => { if (d && d.q && !d.empty) $('verdict').before(statusEl); });

// ---------- keys ----------
const typing = t => t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'Escape' && document.activeElement === qIn) { qIn.blur(); return; }
  if (typing(e.target)) return;
  if (e.key === '/') { e.preventDefault(); qIn.focus(); qIn.select(); }
  else if (e.key === 'a' || e.key === 'A') { if (S.phase !== 'start' || S.offers.size) emit('agent', { on: !agentOn }); }
  else if (e.key === 'l' || e.key === 'L') toggleLab();
});

// ---------- lab panel ----------
function toggleLab(force) {
  const open = force != null ? force : labEl.hidden;
  if (open) renderLab();
  labEl.hidden = !open;
  const u = new URL(location.href);
  if (open) u.searchParams.set('lab', '1'); else u.searchParams.delete('lab');
  history.replaceState(history.state, '', u);
}
function renderLab() {
  const seg = (name, opts, cur) => `<span class="seg" data-k="${name}">${opts.map(o =>
    `<button type="button" data-v="${o}" aria-pressed="${String(o) === String(cur)}">${o}</button>`).join('')}</span>`;
  labEl.innerHTML = `
    <h2>Lab <button type="button" data-x aria-label="close lab">×</button></h2>
    <div class="row">mode ${seg('mode', ['auto', 'replay', 'live'], stream.cfg.mode)}</div>
    <div class="row">speed ${seg('speed', [1, 2, 4], stream.cfg.speed)}</div>
    <div class="row"><label for="lab-gap">max gap (s)</label><input id="lab-gap" type="number" min="0" max="60" step="0.5" value="${stream.cfg.max_gap}"></div>
    <div class="row"><label for="lab-live">live search (Context.dev)</label><input id="lab-live" type="checkbox" ${stream.isLive() ? 'checked' : ''}></div>
    <div class="row"><span>phase · mode</span><span>${esc(S.phase)} · ${esc(S.mode)}</span></div>
    <div class="row"><button type="button" class="act" data-stage>▶ stage</button><a href="/lab">old lab viewer</a></div>
    <p class="note">live costs credits · 10 reads a minute</p>`;
  labEl.querySelector('[data-x]').onclick = () => toggleLab(false);
  labEl.querySelectorAll('.seg').forEach(s => s.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    const k = s.dataset.k; const v = b.dataset.v;
    stream.cfg[k] = k === 'speed' ? Number(v) : v;
    if (k === 'mode' && v === 'live' && !stream.isLive()) { stream.setLive(true); }
    renderLab();
  }));
  labEl.querySelector('#lab-gap').onchange = e => { const n = Number(e.target.value); if (isFinite(n) && n >= 0) stream.cfg.max_gap = n; };
  labEl.querySelector('#lab-live').onchange = e => {
    stream.setLive(e.target.checked);
    if (!e.target.checked && stream.cfg.mode === 'live') stream.cfg.mode = 'auto';
    renderLab();
  };
  labEl.querySelector('[data-stage]').onclick = () => stage();
}
on('turn', () => { if (!labEl.hidden) renderLab(); });

// ---------- stage script (?stage=1): a captioned 30-second tour, one sentence per beat ----------
// Every wait has a timeout, so no beat sticks if an event never arrives. 'skip ›' jumps a beat, Esc ends it.
const BEATS = 7;
let staging = null;            // {bar, cap, hint, n, skip: fn|null, over: bool}
class StageOver extends Error {}
function stageBar() {
  const el = document.createElement('div');
  el.id = 'stagebar';
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<span class="sb-n" aria-hidden="true"></span>
    <p class="sb-text"><span class="sb-cap"></span><span class="sb-hint"></span></p>
    <button type="button" class="sb-skip" aria-label="Next step of the tour">skip <span aria-hidden="true">›</span></button>
    <button type="button" class="sb-x" aria-label="End the tour (Esc)">×</button>`;
  el.querySelector('.sb-skip').addEventListener('click', () => {
    if (!staging) return;
    staging.jump = staging.n;           // every wait left in this beat resolves at once
    staging.skip && staging.skip();
  });
  el.querySelector('.sb-x').addEventListener('click', () => endStage());
  document.body.appendChild(el);
  document.documentElement.classList.add('staging');
  requestAnimationFrame(() => el.classList.add('on'));
  return el;
}
function caption(n, text, hint = '') {
  const st = staging; if (!st) return;
  st.n = n;
  const bar = st.bar, txt = bar.querySelector('.sb-text');
  const put = () => {
    bar.querySelector('.sb-n').textContent = `${n}/${BEATS}`;
    bar.querySelector('.sb-cap').textContent = text;
    const h = bar.querySelector('.sb-hint'); h.textContent = hint; h.hidden = !hint;
    txt.classList.remove('swap');
  };
  if (RM.matches || !bar.querySelector('.sb-cap').textContent) { put(); return; }
  txt.classList.add('swap');
  setTimeout(put, 170);
}
// swap only the small line under the caption (beat 3 names the cheapest tag, then where it landed)
function hint(text) {
  const st = staging; if (!st) return;
  const h = st.bar.querySelector('.sb-hint');
  if (!text || h.textContent === text) return;
  const put = () => { h.textContent = text; h.hidden = false; h.classList.remove('swap'); };
  if (RM.matches || h.hidden) { put(); return; }
  h.classList.add('swap');
  setTimeout(put, 170);
}
// beat 3: "€633 at allenscamera.net is the lowest tag" before the Turn, "…is €795 once import VAT is on it" after.
// Empty when the lowest tag also wins (then there is nothing to point at).
function cheapHint(after) {
  const vm = mods.verdict;
  let url = null;
  try { url = vm && vm.cheapestTagUrl ? vm.cheapestTagUrl() : null; } catch { url = null; }
  const it = url && S.offers.get(url);
  if (it && it.offer) {
    const shop = it.offer.source || domainOf(url);
    const tag = eur(it.offer.price_eur, { dp: 0 });
    const a = allIn(it);
    if (!after || a == null) return `${tag} at ${shop} is the lowest tag. Watch where it lands.`;
    const what = vm && vm.addedPhrase ? vm.addedPhrase(it) : 'import VAT';
    const ship = shipsUnconfirmed(it) ? ', and shipping is still unknown' : '';
    return `${tag} at ${shop} is ${eur(Math.round(a), { dp: 0 })} once ${what} is on it${ship}.`;
  }
  // before the true costs: the engine's headline already names it
  const h = (S.verdict && S.verdict.verdict && S.verdict.verdict.headline) || '';
  const m = /cheapest sticker \((€[\d,.]+) at ([^)\s]+)\)/.exec(h);
  return m && !after ? `${m[1]} at ${m[2]} is the lowest tag. Watch where it lands.` : '';
}
// resolves on the event, the timeout or 'skip ›'; throws when the tour was ended
function beat(type, ms) {
  const st = staging;
  if (!st) return Promise.reject(new StageOver());
  return new Promise((res, rej) => {
    let fn = null, t = 0;
    const fin = (v, err) => {
      clearTimeout(t); if (fn) bus.removeEventListener(type, fn);
      if (st.skip === skip) st.skip = null;
      if (st.over || staging !== st) rej(new StageOver()); else if (err) rej(err); else res(v);
    };
    const skip = () => fin(null);
    if (st.jump === st.n) { setTimeout(skip, 0); return; }
    st.skip = skip; st.end = () => fin(null, new StageOver());
    if (type) { fn = e => fin(e.detail || {}); bus.addEventListener(type, fn); }
    t = setTimeout(() => fin(null), ms);
  });
}
const hold = ms => beat(null, ms);
function endStage() {
  const st = staging; if (!st) return;
  st.over = true; staging = null;
  st.bar.classList.remove('on');
  document.documentElement.classList.remove('staging');
  setTimeout(() => st.bar.remove(), RM.matches ? 0 : 260);
  if (st.end) st.end();
}
// "Bought for €1,028 all in, while you slept." (what the night paid; else the pick's all-in price)
function closing(url, paid) {
  if (typeof paid === 'number' && isFinite(paid)) return `Bought for ${eur(Math.round(paid), { dp: 0 })} all in, while you slept.`;
  const it = url && S.offers.get(url);
  const a = it ? allIn(it) : null;
  if (a == null) return 'Bought while you slept.';
  const job = isJobItem(it);
  return `${eur(job ? a : Math.round(a), { dp: job && Math.abs(a % 1) > 0.004 ? 2 : 0 })} ${job ? 'for the job' : 'all in'}. Bought while you slept.`;
}
function pick() {
  const pu = pickUrl();
  const url = pu && S.offers.has(pu) ? pu : S.leader;
  const it = url && S.offers.get(url);
  const p = it && it.offer && it.offer.price_eur;
  return { url, eur: (typeof p === 'number' && isFinite(p)) ? Math.round(p) : 1030 };
}
async function typeInto(q) {
  if (S.phase !== 'start') goHome();
  qIn.value = '';
  for (let i = 1; i <= q.length; i++) {
    qIn.value = q.slice(0, i);
    await hold(RM.matches ? 0 : 55 + (q[i - 1] === ' ' ? 60 : 0));
  }
}
async function stage() {
  if (staging) return;
  staging = { bar: stageBar(), n: 0, skip: null, over: false };
  const t0 = performance.now();
  try {
    if (agentOn) emit('agent', { on: false });
    const Q = 'sony a7 iii body';
    caption(1, 'One search box.');
    await hold(700);
    await typeInto(Q);
    await hold(450);
    const turned = { v: false }; const offTurn = on2('turn', () => { turned.v = true; });
    run(Q);
    caption(2, 'Every shop, one euro line.');
    await hold(1200);
    await beat('verdict', 5000);           // the first answer: the cheapest tag usually leads
    if (!turned.v) await hold(1200);
    caption(3, 'Cheapest tag is not cheapest.', cheapHint(false));
    if (!turned.v) await beat('turn', 16000);
    offTurn();
    try { line && line.setMode && line.setMode('true'); } catch {}
    await hold(1100);                    // the slide lands, then the hint says where the cheap tag went
    hint(cheapHint(true));
    await hold(2300);
    caption(4, 'What you actually pay, all in.', 'shipping, import VAT and fees on top of the tag · hold any cutout to see them');
    if (!S.done) await beat('done', 2500);
    await hold(600);
    // show the gesture once: tag + shipping & import VAT = all in
    let close = null;
    // on the lowest tag when it jumped (its tag + import VAT, = what you pay), else on the pick
    let cu = null;
    try { cu = mods.verdict && mods.verdict.cheapestTagUrl ? mods.verdict.cheapestTagUrl() : null; } catch { cu = null; }
    try { close = line && line.split ? (cu && line.split(cu)) || line.split() : null; } catch { close = null; }
    await hold(close ? 3000 : 2600).finally(() => { try { close && close(); } catch {} });
    const { url, eur: price } = pick();
    caption(5, 'Set your price.', 'a tag price: the line shows tags while you set it');
    await hold(500);
    emit('tag', { eur: price, from: 'stage', url });
    await hold(3200);
    caption(6, `${BRAND} watches overnight.`);
    const bought = beat('finale:bought', 34000);
    emit('finale:start', { from: 'stage', url, eur: price });
    const got = await bought;
    await hold(1400);                    // the receipt lands, the headline locks in, then the proof beat
    caption(7, 'Proof, not promises.', 'someone edits one row of the log; the chain catches it');
    await hold(900);
    const proof = beat('proof', 6000);
    emit('finale:verify', {});
    await proof;
    await hold(3400);                    // time to read the red row
    try { line && line.setMode && line.setMode('true', { calm: true }); } catch {}
    emit('agent', { on: true });
    await hold(2600);
    emit('agent', { on: false });        // the tour ends on the line, true view, ring on the pick
    await hold(900);
    // the last word: hold on the ringed pick, one quiet sentence, then hand the page back
    try { line && line.setMode && line.setMode('true', { calm: true }); } catch {}
    const ring = line && line.rect ? line.rect(line.winner || url) : null;
    if (ring && (ring.top < 72 || ring.bottom > innerHeight - 120)) {
      scrollBy({ top: ring.top + ring.height / 2 - innerHeight * 0.4, behavior: RM.matches ? 'auto' : 'smooth' });
    }
    if (staging) staging.jump = null;    // a skip on beat 7 must not swallow the last word
    caption(BEATS, closing(url, got && got.paid));
    await hold(4200);
    console.info(`[agora] stage tour ${(performance.now() - t0) / 1000 | 0} s`);
  } catch (e) {
    if (!(e instanceof StageOver)) console.warn('[agora] stage', e);
  } finally { endStage(); }
}
// a listener that can be removed (core.on cannot)
function on2(type, fn) { const h = e => fn(e.detail); bus.addEventListener(type, h); return () => bus.removeEventListener(type, h); }
addEventListener('keydown', e => { if (staging && e.key === 'Escape') { e.preventDefault(); endStage(); } }, true);

// ---------- boot ----------
async function boot() {
  // the product name: one edit point (data-brand on <html>, read into BRAND by core.js); the static
  // <title> and .brand text in index.html are only the no-JS fallback
  if (!params.get('q')) document.title = BRAND;
  // "PriceMonkey" -> price<b>monkey</b>: the second word wears the monkey's brown
  const bm = /^(.+?)([A-Z][a-z]+)$/.exec(BRAND);
  document.querySelectorAll('.brand').forEach(b => { b.innerHTML = bm ? `${esc(bm[1])}<b>${esc(bm[2])}</b>` : esc(BRAND); });
  app.dataset.phase = 'start';
  placeBox();
  const narrowPh = matchMedia('(max-width: 480px)');
  const ph = () => { qIn.placeholder = narrowPh.matches ? 'a camera, a cleaner, anything…' : 'a camera, a used iPhone, someone to clean my flat…'; };
  ph(); narrowPh.addEventListener && narrowPh.addEventListener('change', ph);
  if (params.has('lab')) { const l = $('lab-link'); if (l) l.hidden = false; }
  renderExamples();
  mountMascot();
  await mountAll();
  emit('ready', {});
  if (params.get('lab') === '1') toggleLab(true);
  const q = params.get('q');
  if (params.get('stage') === '1') stage();
  else if (params.get('c')) openCategory(params.get('c'), { push: false, typed: params.get('typed') || '' });
  else if (q) run(q, { push: false, cat: params.get('cat') ? { id: params.get('cat') } : null, intent: params.get('intent') });
  else if (matchMedia('(min-width: 641px)').matches) qIn.focus({ preventScroll: true });
}
boot();

// for the console and for the other modules' debugging
window.agora = { S, emit, on, run, stage, stream };
