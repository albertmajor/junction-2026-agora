// agent.js (B3): the line, as an agent gets it through the MCP door (find_offers).
// Same order, same numbers. One engine, two doors.
import { S, on, emit, isSetAside, domainOf, allIn, netAfterResale, shippingUnknown, shipsUnconfirmed, pickUrl } from './core.js';

let root, pre, noteEl, isOn = false, lastFocus = null;

const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const r2 = n => (n == null || !isFinite(n)) ? null : Math.round(n * 100) / 100;

// Mirrors agora/mcp_server.py _brief().
function brief(it) {
  const o = it.offer || {}, tc = it.tc || {}, t = tc.true_cost;
  const b = {
    title: o.title ?? null, url: it.url, source: o.source || domainOf(it.url), condition: o.condition ?? null,
    price_eur: r2(o.price_eur), shipping_eur: r2(o.shipping_eur), in_stock: o.in_stock ?? null,
    trust: tc.trust ?? o.trust ?? null, flags: tc.flags || o.flags || [], thing_id: tc.thing_id ?? o.thing_id ?? null,
    all_in_eur: r2(allIn(it)),
    untrusted_text: ['title', 'seller'],
  };
  if (t && t.per === 'job') b.all_in_per = 'job';
  else if (t) {
    if (shipsUnconfirmed(it)) b.shipping_to_you = 'unconfirmed (not in all_in_eur)';
    else if (shippingUnknown(it)) b.shipping_to_you = 'not listed (not in all_in_eur)';
    const net = netAfterResale(it);
    if (net != null) b.net_if_resold_eur = { eur: r2(net), after_months: t.months || 12 };
  }
  if (o.seller && !(tc.injection && tc.injection.length)) b.seller = o.seller;
  if (tc.injection && tc.injection.length) b.injection = tc.injection;
  const band = (t && t.band) || tc.band;
  if (band) b.price_band = { label: band.label, p25: band.p25, p75: band.p75, median: band.median, what: band.what };
  if (tc.offer_id) b.offer_id = tc.offer_id;
  return b;
}

// Line order: what the line shows left to right, then the set-aside tray.
// Ranked by what you pay all in (tag + shipping + import VAT + fees) whenever that is known, whatever
// view the line happens to be on; tag price only before anything is costed.
function byAllIn() { return [...S.offers.values()].some(it => allIn(it) != null); }
function lineOrder() {
  const all = [...S.offers.values()];
  const tru = byAllIn();
  const key = it => {
    const v = tru ? allIn(it) : (it.offer && it.offer.price_eur);
    return v == null || !isFinite(v) ? Infinity : v;
  };
  const main = all.filter(it => !isSetAside(it)).sort((a, b) => key(a) - key(b));
  const aside = all.filter(it => isSetAside(it));
  return { main, aside };
}

export function buildPayload() {
  const { main, aside } = lineOrder();
  const v = S.verdict && S.verdict.verdict;
  const job = [...S.offers.values()].some(it => it.tc && it.tc.true_cost && it.tc.true_cost.per === 'job');
  const pu = pickUrl();
  const pk = pu && S.offers.get(pu);
  const out = {
    query: S.q || (S.need && S.need.raw) || '',
    ranked_by: byAllIn() ? (job ? 'all_in_eur (one job)' : 'all_in_eur (tag + shipping + import VAT + fees, paid once)') : 'price_eur',
  };
  if (pk) out.pick = { url: pu, all_in_eur: r2(allIn(pk)), condition: pk.offer.condition ?? null, source: pk.offer.source || domainOf(pu),
    why: 'lowest all-in price you can surely buy (not set aside, ships to you, in stock)' };
  out.n_offers = main.length + aside.length;
  out.offers = main.map(brief);
  if (aside.length) out.set_aside = aside.map(brief);
  if (v) out.verdict = { buy_or_wait: v.buy_or_wait, provisional: !!(S.verdict && S.verdict.provisional) };
  if (S.need) out.need = { thing: S.need.thing, kind: S.need.kind, conditions: S.need.conditions, where: S.need.where };
  if (S.need && S.need.hunt_id) out.hunt_id = S.need.hunt_id;
  if (S.budget) out.budget = { credits_used: S.budget.credits_used, requests: S.budget.requests, cache_hits: S.budget.cache_hits, pages: S.budget.pages };
  return out;
}

// JSON with quiet colour: keys, strings, numbers. The winner's url gets the highlighter.
// Like JSON.stringify(v, null, 2), but short arrays and objects stay on one line.
function oneLine(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(oneLine).join(', ') + ']';
  return '{' + Object.keys(v).map(k => JSON.stringify(k) + ': ' + oneLine(v[k])).join(', ') + '}';
}
function compact(v, ind = '') {
  const flat = oneLine(v);
  if (v === null || typeof v !== 'object' || (flat.length + ind.length <= 84 && !(Array.isArray(v) && v.some(x => x && typeof x === 'object')) && !(v && v.url))) return flat;
  const next = ind + '  ';
  if (Array.isArray(v)) return v.length ? '[\n' + v.map(x => next + compact(x, next)).join(',\n') + '\n' + ind + ']' : '[]';
  const ks = Object.keys(v);
  return ks.length ? '{\n' + ks.map(k => next + JSON.stringify(k) + ': ' + compact(v[k], next)).join(',\n') + '\n' + ind + '}' : '{}';
}

function pretty(obj, lead) {
  const json = compact(obj);
  return json.split('\n').map(line => {
    // Tokenise the line: strings (keys when followed by a colon), numbers, literals.
    let h = '', i = 0;
    const re = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)|\b(true|false|null)\b/g;
    let m;
    while ((m = re.exec(line))) {
      h += esc(line.slice(i, m.index));
      if (m[1]) h += m[2] ? `<span class="k">${esc(m[1])}</span>${m[2]}` : `<span class="s">${esc(m[1])}</span>`;
      else if (m[3]) h += `<span class="n">${m[3]}</span>`;
      else h += `<span class="b">${m[4]}</span>`;
      i = re.lastIndex;
    }
    h += esc(line.slice(i));
    if (lead && /"url"/.test(line) && line.includes(JSON.stringify(lead))) h = `<mark>${h}</mark>`;
    return h;
  }).join('\n');
}

function place() {
  const lineEl = document.getElementById('line');
  if (!lineEl) return;
  const parent = root.offsetParent || document.body;
  const pr = parent.getBoundingClientRect(), lr = lineEl.getBoundingClientRect();
  root.style.left = (lr.left - pr.left + parent.scrollLeft) + 'px';
  root.style.top = (lr.top - pr.top + parent.scrollTop) + 'px';
  root.style.width = lr.width + 'px';
  root.style.minHeight = Math.max(lr.height, 360) + 'px';
}

function render() {
  const data = buildPayload();
  const lead = pickUrl() || S.leader;
  const q = data.query || 'your search';
  noteEl.innerHTML = `This is what the MCP door returns to an agent for <code>find_offers(${esc(JSON.stringify(q))})</code>. Same order as the line, same numbers.`;
  pre.innerHTML = data.n_offers ? pretty(data, lead) : '<span class="b">// run a search first: the agent sees exactly what the line shows</span>';
}

function show() {
  if (isOn) return;
  isOn = true; lastFocus = document.activeElement;
  render(); place();
  root.hidden = false; root.setAttribute('aria-hidden', 'false');
  document.documentElement.classList.add('agent-on');
  requestAnimationFrame(() => root.classList.add('on'));
  root.querySelector('.a-pre').scrollTop = 0;
  setTimeout(() => root.querySelector('.back').focus({ preventScroll: true }), 30);
  // the finale may have scrolled the page: bring the JSON into view, just under the header
  const top = root.getBoundingClientRect().top;
  if (top < 0 || top > innerHeight * 0.6) scrollTo({ top: Math.max(0, scrollY + top - 140), behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}
function hide() {
  if (!isOn) return;
  isOn = false;
  root.classList.remove('on'); root.setAttribute('aria-hidden', 'true');
  document.documentElement.classList.remove('agent-on');
  setTimeout(() => { if (!isOn) root.hidden = true; }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320);
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}

export function mountAgent(el) {
  root = el;
  el.classList.add('agent');
  el.hidden = true;
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', 'What an agent sees');
  el.innerHTML = `
    <div class="a-top">
      <p class="a-note"></p>
      <div class="a-acts">
        <button type="button" class="ghost copyjson">Copy JSON</button>
        <button type="button" class="ghost back">Back to the line <kbd>A</kbd></button>
      </div>
    </div>
    <pre class="a-pre" tabindex="0"></pre>`;
  pre = el.querySelector('.a-pre');
  noteEl = el.querySelector('.a-note');

  el.addEventListener('click', e => {
    if (e.target.closest('.back')) { hide(); emit('agent', { on: false, from: 'agent' }); return; }
    const c = e.target.closest('.copyjson');
    if (c && navigator.clipboard) navigator.clipboard.writeText(JSON.stringify(buildPayload(), null, 2)).then(() => {
      c.textContent = 'Copied'; setTimeout(() => { c.textContent = 'Copy JSON'; }, 1400);
    }).catch(() => {});
  });
  document.addEventListener('keydown', e => { if (isOn && e.key === 'Escape') { hide(); emit('agent', { on: false, from: 'agent' }); } });
  addEventListener('resize', () => { if (isOn) place(); });

  on('agent', d => {
    if (d && d.from === 'agent') return;
    const want = d && typeof d.on === 'boolean' ? d.on : !isOn;
    want ? show() : hide();
  });
  on('reset', () => hide());
  for (const t of ['offer', 'truecost', 'verdict', 'turn']) on(t, () => { if (isOn) render(); });
}
