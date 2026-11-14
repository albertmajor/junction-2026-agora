// WHAT YOU MOST LIKELY MEAN (owner, 14 Nov: typed "lunch" and got €4 lunch boxes from tori.fi, "not even services").
// GET /api/intent turns a vague request into 2–5 concrete meanings, each with a search plan. main.js hunts the
// likeliest one; this row says which, in plain words ("Lunch places near you · lounaat.info, …"), and when the
// top meaning is not clearly it, offers the others as calm chips ("We think you mean: …"). A tap re-runs the hunt
// with that meaning. A hunt that finds nothing gets next steps here (other meanings, providers near you, the
// broader category), never a dead end. The category page uses nextSteps() for an empty category.
import * as core from './core.js';
import * as C from './cats.js';

const { esc } = C;
const W = {
  en: { which: 'That could be a few things. Which one?', pick: x => `We see a few products called “${x}”. Which one?`, keep: 'Meanwhile we keep hunting the likeliest one.',
        mean: 'We think you mean:', now: 'Searching for', none: x => `Nothing found for “${x}” yet. Try:`, other: 'Something else? Search the words as typed',
        near: 'Search providers near you', can: 'We can search these for you:', open: 'Browse',
        picked: 'You picked:', change: 'change', changeL: 'Change what you are looking for', typed: x => `Exactly “${x}”` },
  fi: { which: 'Tämä voi tarkoittaa montaa asiaa. Mitä haet?', pick: x => `Nimellä ”${x}” löytyy useita tuotteita. Mikä niistä?`, keep: 'Haemme sillä välin todennäköisintä.',
        mean: 'Tarkoititko:', now: 'Haetaan', none: x => `”${x}” ei tuottanut vielä tuloksia. Kokeile:`, other: 'Jotain muuta? Hae sanoilla sellaisenaan',
        near: 'Hae palveluntarjoajia läheltäsi', can: 'Voimme hakea nämä puolestasi:', open: 'Selaa',
        picked: 'Valitsit:', change: 'vaihda', changeL: 'Vaihda mitä etsit', typed: x => `Juuri ”${x}”` },
  sv: { which: 'Det kan betyda flera saker. Vilken?', pick: x => `Vi ser flera produkter som heter ”${x}”. Vilken menar du?`, keep: 'Under tiden letar vi vidare efter den troligaste.',
        mean: 'Vi tror du menar:', now: 'Söker', none: x => `Inget hittades för ”${x}” än. Prova:`, other: 'Något annat? Sök orden som de är',
        near: 'Sök leverantörer nära dig', can: 'Vi kan söka de här åt dig:', open: 'Bläddra',
        picked: 'Du valde:', change: 'ändra', changeL: 'Ändra vad du letar efter', typed: x => `Exakt ”${x}”` },
  de: { which: 'Das kann mehreres sein. Welches?', pick: x => `Es gibt mehrere Produkte namens „${x}“. Welches meinst du?`, keep: 'Wir suchen derweil weiter nach dem wahrscheinlichsten.',
        mean: 'Meinst du:', now: 'Wir suchen', none: x => `Noch nichts für „${x}“ gefunden. Versuch:`, other: 'Etwas anderes? Die Wörter so suchen',
        near: 'Anbieter in deiner Nähe suchen', can: 'Das können wir für dich suchen:', open: 'Ansehen',
        picked: 'Gewählt:', change: 'ändern', changeL: 'Ändern, wonach du suchst', typed: x => `Genau „${x}“` },
  nl: { which: 'Dat kan van alles zijn. Welke bedoel je?', pick: x => `We zien een paar producten die “${x}” heten. Welke bedoel je?`, keep: 'Ondertussen zoeken we door naar de meest waarschijnlijke.',
        mean: 'We denken dat je bedoelt:', now: 'We zoeken', none: x => `Nog niets gevonden voor “${x}”. Probeer:`, other: 'Iets anders? Zoek de woorden zoals getypt',
        near: 'Zoek aanbieders bij jou in de buurt', can: 'Dit kunnen we voor je zoeken:', open: 'Bekijk',
        picked: 'Je koos:', change: 'wijzig', changeL: 'Wijzig wat je zoekt', typed: x => `Precies “${x}”` },
};
const w = (k, ...a) => { const L = W[C.getLang()] || W.en; const v = L[k] ?? W.en[k]; return typeof v === 'function' ? v(...a) : v; };

// ---------- remembered city: "near you in Helsinki" once the viewer has named one ----------
function near() { try { return localStorage.getItem('agora.near') || ''; } catch { return ''; } }
function rememberNear(p) { if (!p) return; try { localStorage.setItem('agora.near', p); } catch {} }

/** The meanings of q (cached per q/cat/lang): {intents, dominant, next, place, concept, ...} or null. */
export function interpret(q, { cat = null } = {}) {
  q = String(q || '').trim();
  if (q.length < 2 && !cat) return Promise.resolve(null);
  return C.api('/api/intent', { q, cat: cat || '', near: near() }).then(r => {
    if (r && r.remember) rememberNear(r.remember);
    return r && Array.isArray(r.intents) ? r : null;
  });
}

export const meanH = () => w('mean').replace(/:$/, '');

/** Should main.js hunt this meaning instead of the typed words? (it is not what a plain hunt does anyway) */
export const rewrites = it => !!(it && it.hunt && !it.as_typed);

// ---------- the row under the search box ----------
let el = null;
const st = { q: '', interp: null, chosen: null, empty: false, clarify: null, picked: false };

// ---------- "which one?" (judges, F3: "We see multiple products with this name.") ----------
// The engine may send `clarify` {question?, name?, options:[{label, q, image?}]} while the hunt keeps streaming
// its top guess. It is optional: until one arrives nothing here changes. A tap re-asks with the option's q.
const okImg = u => typeof u === 'string' && /^(https?:\/\/|data:image\/|\/)/i.test(u) ? u : '';
function readClarify(d) {
  const opts = (d && Array.isArray(d.options) ? d.options : [])
    .filter(o => o && typeof o.label === 'string' && o.label.trim() && typeof o.q === 'string' && o.q.trim().length > 1)
    .slice(0, 6).map(o => ({ label: o.label.trim(), q: o.q.trim(), image: okImg(o.image) }));
  if (opts.length < 2) return null;
  const name = [d.name, d.term, d.thing].find(x => typeof x === 'string' && x.trim()) || st.q;
  const question = typeof d.question === 'string' && d.question.trim() ? d.question.trim() : w('pick', name);
  return { question, options: opts };
}
function clarifyHtml(c) {
  return `<div class="it-clarify" role="group" aria-labelledby="it-q"><p class="it-q" id="it-q">${esc(c.question)}</p><div class="it-row it-ask">`
    + c.options.map((o, i) => `<button type="button" class="it-chip it-pic${o.image ? '' : ' no-img'}" data-clarify="${i}" title="${esc(o.q)}">`
      + (o.image ? `<img src="${esc(o.image)}" alt="" width="40" height="40" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : '')
      + `<span>${esc(o.label)}</span></button>`).join('')
    + `</div><p class="it-keep">${esc(w('keep'))}</p></div>`;
}

function where(it) {
  const d = (it.domains || []).filter(x => x.includes('.')).slice(0, 3);
  const list = d.length ? d : (it.look || []).slice(0, 2);
  return list.length ? ` <span class="it-where">· ${esc(list.join(', '))}</span>` : '';
}
function chip(it, pressed) {
  const kind = C.kindTag(it.kind);
  return `<button type="button" class="it-chip" data-intent="${esc(it.id)}" aria-pressed="${pressed}" title="${esc(it.why || '')}">${esc(it.label)}${kind}</button>`;
}
function render() {
  if (!el) return;
  const I = st.interp, it = st.chosen, ask = st.clarify;
  if (ask && (!I || !it)) { el.innerHTML = clarifyHtml(ask); el.hidden = false; return; }
  if (!I || !it || (!I.intents.length && !(I.next || []).length && !st.picked)) { el.hidden = true; el.innerHTML = ''; return; }
  const picked = st.picked;
  const showNow = rewrites(it) && !picked;
  const showChips = !ask && !picked && !I.dominant && I.intents.length > 1;
  if (!showNow && !showChips && !st.empty && !ask && !picked) { el.hidden = true; el.innerHTML = ''; return; }
  const others = I.intents.filter(x => x.id !== it.id && !(it.id === '_typed' && x.hunt && x.hunt.q === st.q));
  let html = '';
  if (ask) html += clarifyHtml(ask);
  if (picked) {
    // the answer to the clarify question (clarify.js): what we hunt, and a way back to the question
    const label = it.id === '_typed' ? w('typed', st.q) : it.label;
    html += `<p class="it-now it-picked"><span class="it-pk"><span class="it-k">${esc(w('picked'))}</span> <b>${esc(label)}</b>`
      + `${it.id === '_typed' ? '' : where(it)}</span> <span class="it-dot" aria-hidden="true">·</span> `
      + `<button type="button" class="it-change" data-change="1" aria-label="${esc(w('changeL'))}">${esc(w('change'))}</button></p>`;
  }
  if (showNow || showChips) {
    html += `<p class="it-now"><span class="it-k">${esc(w('now'))}</span> <b>${esc(it.label)}</b>${where(it)}</p>`;
  }
  if (showChips && !st.empty) {
    html += `<div class="it-row" role="group" aria-label="${esc(w('mean'))}"><span class="it-h">${esc(w('which'))}</span>`
      + I.intents.map(x => chip(x, x.id === it.id)).join('') + '</div>';
  }
  if (st.empty) {
    const steps = stepsFor(I, it);
    html += `<div class="it-row it-next" role="group"><span class="it-h">${esc(w('none', rewrites(it) ? it.label : st.q))}</span>`
      + others.map(x => chip(x, false)).join('')
      + steps.map((n, i) => n.open
        ? `<button type="button" class="it-chip ghost" data-open="${esc(n.open)}">${esc(w('open'))}: ${esc(n.label)} ›</button>`
        : `<button type="button" class="it-chip ghost" data-step="${i}">${esc(n.label)} →</button>`).join('')
      + '</div>';
  }
  el.innerHTML = html;
  el.hidden = false;
}

// next steps belong to the likeliest meaning (its providers near you, its broader category): offered only while
// that one is chosen; another meaning's empty hunt offers the other meanings instead
function stepsFor(I, it) {
  if (!I || !it || (it.id !== '_typed' && (!I.intents.length || I.intents[0].id !== it.id))) return [];
  const shown = new Set(I.intents.map(x => x.node).filter(Boolean));
  return (I.next || []).filter(n => !(n.hunt && n.hunt.intent === it.id && n.kind !== 'providers')
    && !(n.kind === 'sibling' && n.hunt && shown.has(n.hunt.cat)));
}

/** main.js: the hunt is starting with this interpretation (or none). */
export function show(q, interp, chosen, { picked = false } = {}) {
  st.q = q; st.interp = interp; st.chosen = chosen; st.empty = false; st.clarify = null; st.picked = !!picked;
  render();
}
export function clear() { st.interp = null; st.chosen = null; st.empty = false; st.clarify = null; st.picked = false; render(); }

function onClick(e) {
  if (e.target.closest('[data-change]')) { core.emit('clarify:change', { q: st.q, interp: st.interp }); return; }
  const c = e.target.closest('[data-clarify]');
  if (c) {
    const o = st.clarify && st.clarify.options[Number(c.dataset.clarify)];
    if (o) core.emit('ask', { q: o.q, free: false });
    return;
  }
  const I = st.interp;
  if (!I) return;
  const b = e.target.closest('[data-intent]');
  if (b) {
    const it = I.intents.find(x => x.id === b.dataset.intent);
    if (it && (it !== st.chosen || st.empty)) core.emit('ask', { q: st.q, plan: it, interp: I });
    return;
  }
  const o = e.target.closest('[data-open]');
  if (o) { C.openCategory(o.dataset.open); return; }
  const s = e.target.closest('[data-step]');
  if (s) {
    const n = stepsFor(I, st.chosen)[Number(s.dataset.step)];
    if (n && n.hunt) core.emit('ask', { q: st.q, plan: { id: n.hunt.intent || '', label: n.label, kind: 'service', hunt: n.hunt, domains: [], look: [] }, interp: I });
  }
}

export function mountIntents(host) {
  if (!host || el) return;
  el = host;
  el.addEventListener('click', onClick);
  core.on('done', () => {
    if (!st.chosen || core.S.offers.size) return;
    st.empty = true;
    render();
  });
  core.on('catpage', clear);
  core.on('clarify', d => {
    try { st.clarify = readClarify(d); } catch { st.clarify = null; }
    if (st.clarify) render();
  });
  // a broken picture leaves a clean text chip
  el.addEventListener('error', e => {
    const im = e.target;
    if (im && im.tagName === 'IMG' && im.closest('.it-pic')) { im.closest('.it-pic').classList.add('no-img'); im.remove(); }
  }, true);
}

// ---------- category page: an empty category is never a dead end ----------
/** HTML for the 'what we can search for you' block of a category page (id = node, label = its name). */
export async function nextSteps(id, label) {
  const I = await interpret(label, { cat: id });
  if (!I || (!I.intents.length && !(I.next || []).length)) return null;
  const list = I.intents.slice(0, 5);
  const steps = (I.next || []).filter(n => n.kind !== 'sibling' || !list.some(x => x.hunt && n.hunt && x.hunt.cat === n.hunt.cat));
  const html = `<section class="it-cp" aria-labelledby="it-cp-h"><h2 class="cp-h2" id="it-cp-h">${esc(w('can'))}</h2>
    <ul class="it-cards" role="list">${list.map((x, i) => `<li><button type="button" class="it-card" data-cp-intent="${i}">
      <span class="it-cn">${esc(x.label)}${C.kindTag(x.kind)}</span>
      ${x.why ? `<span class="it-cw">${esc(x.why)}</span>` : ''}
      ${(x.domains || []).filter(d => d.includes('.')).length ? `<span class="it-cd">${esc(x.domains.filter(d => d.includes('.')).slice(0, 4).join(' · '))}</span>` : ''}
      <span class="cp-arrow" aria-hidden="true">→</span></button></li>`).join('')}</ul>
    <div class="cp-chips it-cp-next">${steps.map((n, i) => n.open
      ? `<button type="button" class="cp-chip ghost" data-cp-open="${esc(n.open)}">${esc(w('open'))}: ${esc(n.label)} ›</button>`
      : `<button type="button" class="cp-chip${n.kind === 'providers' ? ' strong' : ''}" data-cp-step="${i}">${esc(n.label)} →</button>`).join('')}</div></section>`;
  return {
    html,
    click(e) {
      const a = e.target.closest('[data-cp-intent]');
      if (a) { const x = list[Number(a.dataset.cpIntent)]; if (x) core.emit('ask', { q: label, plan: x, interp: { ...I, dominant: false } }); return true; }
      const o = e.target.closest('[data-cp-open]');
      if (o) { C.openCategory(o.dataset.cpOpen); return true; }
      const s = e.target.closest('[data-cp-step]');
      if (s) {
        const n = steps[Number(s.dataset.cpStep)];
        if (n && n.hunt) core.emit('ask', { q: label, plan: { id: n.hunt.intent || '', label: n.label, kind: 'service', hunt: n.hunt, domains: [], look: [] }, interp: { ...I, dominant: false } });
        return true;
      }
      return false;
    },
  };
}
