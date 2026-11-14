// ASK FIRST WHEN UNSURE (owner + judges: "if it's unsure, it should ASK a question first — 'gta 6 ps5': just the
// game disc, or a PS5 with a GTA 6 deal? … and there should still be an option to just go ahead with whatever you
// first wrote"). A typed search asks /api/intent what it means; when the answer is not clearly one thing, main.js
// does not start the hunt: this card asks, in plain words, with 2–5 big options and "Search exactly “…”".
// The engine may send `clarify` {ask, question, options:[{id,label,hint,intent_id}], as_typed:{label}}; until it
// does (and whenever it is absent) the question is built here from the ranked meanings (ask = !dominant).
// The answer is remembered for the same words this session; intent.js shows "You picked: … · change".
// Module scope never touches the DOM (tests/web/clarify.test.mjs imports decide()).
import { picture } from './mascot.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const TYPED = '_typed';
export const MAX = 5;

const W = {
  en: { q: x => `“${x}” could mean a few things. What are you looking for?`, exact: x => `Search exactly “${x}”`, exactH: 'Just go with what I typed',
        keys: 'Press 1–{n} to pick · Esc searches as typed', picked: 'You picked:', change: 'change', typed: x => `Exactly “${x}”` },
  fi: { q: x => `”${x}” voi tarkoittaa montaa asiaa. Mitä etsit?`, exact: x => `Hae juuri ”${x}”`, exactH: 'Hae sillä mitä kirjoitin',
        keys: 'Valitse 1–{n} · Esc hakee sellaisenaan', picked: 'Valitsit:', change: 'vaihda', typed: x => `Juuri ”${x}”` },
  sv: { q: x => `”${x}” kan betyda flera saker. Vad letar du efter?`, exact: x => `Sök exakt ”${x}”`, exactH: 'Sök det jag skrev',
        keys: 'Tryck 1–{n} för att välja · Esc söker som skrivet', picked: 'Du valde:', change: 'ändra', typed: x => `Exakt ”${x}”` },
  de: { q: x => `„${x}“ kann mehreres heißen. Wonach suchst du?`, exact: x => `Genau „${x}“ suchen`, exactH: 'Einfach so suchen, wie ich es geschrieben habe',
        keys: '1–{n} zum Wählen · Esc sucht wie getippt', picked: 'Gewählt:', change: 'ändern', typed: x => `Genau „${x}“` },
  nl: { q: x => `“${x}” kan meerdere dingen betekenen. Wat zoek je?`, exact: x => `Zoek precies “${x}”`, exactH: 'Zoek gewoon wat ik typte',
        keys: 'Kies met 1–{n} · Esc zoekt zoals getypt', picked: 'Je koos:', change: 'wijzig', typed: x => `Precies “${x}”` },
};
let langOf = () => 'en';
export const w = (k, ...a) => { const L = W[langOf()] || W.en; const v = L[k] ?? W.en[k]; return typeof v === 'function' ? v(...a) : v; };

// ---------- the decision (pure) ----------
export const norm = q => String(q || '').trim().replace(/\s+/g, ' ').toLowerCase();
const str = x => (typeof x === 'string' && x.trim() ? x.trim() : '');

/** A meaning picked from the card that is not one of the ranked intents still needs a plan main.js can hunt. */
function planOf(o, intents) {
  const id = str(o.intent_id) || str(o.id);
  const it = id && intents.find(x => x && x.id === id);
  if (it) return it;
  const h = o.hunt && typeof o.hunt === 'object' ? o.hunt : (str(o.q) ? { q: str(o.q) } : null);
  if (!h || !str(h.q)) return null;
  return { id: id || 'opt:' + norm(h.q), label: str(o.label), kind: o.kind || 'product', why: str(o.hint),
           hunt: { q: str(h.q), cat: h.cat || null, intent: h.intent || id || null }, domains: [], look: [] };
}

/**
 * Should a typed search ask before it hunts?
 *   ctx {free, plan, cat, intent, example, recorded, remembered}
 * -> {ask:false} | {ask:false, pick:<intent id | '_typed'>} | {ask:true, question, options:[{id,label,hint,plan}], asTyped:{label}}
 * Never asks for: a hunt from the tree (cat), a meaning already chosen (plan / &intent=), "search everything"
 * (free), a start-screen example or a recorded search. A remembered answer for the same words is reused.
 */
export function decide(q, interp, ctx = {}) {
  const no = { ask: false };
  q = String(q || '').trim().replace(/\s+/g, ' ');
  if (!q || ctx.free || ctx.plan || ctx.cat || ctx.intent || ctx.example || ctx.recorded) return no;
  const intents = (interp && Array.isArray(interp.intents) ? interp.intents : []).filter(x => x && x.id && str(x.label));
  if (ctx.remembered) {
    if (ctx.remembered === TYPED || intents.some(x => x.id === ctx.remembered)) return { ask: false, pick: ctx.remembered };
  }
  if (!interp) return no;
  const cl = interp.clarify && typeof interp.clarify === 'object' ? interp.clarify : null;
  let options, question = '', asTyped = '';
  if (cl) {
    if (cl.ask !== true) return no;
    options = (Array.isArray(cl.options) ? cl.options : []).filter(o => o && str(o.label))
      .map(o => ({ id: str(o.id) || str(o.intent_id), label: str(o.label), hint: str(o.hint), plan: planOf(o, intents) }))
      .filter(o => o.plan);
    question = str(cl.question);
    asTyped = cl.as_typed && str(cl.as_typed.label);
  } else {
    if (interp.dominant || intents.length < 2) return no;
    options = intents.map(x => ({ id: x.id, label: str(x.label), hint: str(x.why), plan: x }));
  }
  const seen = new Set();
  options = options.filter(o => { const k = o.plan.id; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, MAX);
  if (options.length < 2) return no;
  return { ask: true, question: question || w('q', q), options, asTyped: { label: asTyped || w('exact', q) } };
}

// ---------- remembered answers (this session) ----------
const KEY = 'agora.clarify:';
function store() { try { return typeof sessionStorage !== 'undefined' ? sessionStorage : null; } catch { return null; } }
export function recall(q, s = store()) { try { return (s && s.getItem(KEY + norm(q))) || ''; } catch { return ''; } }
export function remember(q, id, s = store()) { try { if (s && id) s.setItem(KEY + norm(q), id); } catch {} }

// ---------- the card ----------
let el = null, cur = null;
const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

function html(q, d) {
  const n = d.options.length;
  return `<div class="cl-card" role="group" aria-labelledby="cl-q" aria-describedby="cl-keys">`
    + picture('thinking', { cls: 'cl-monkey', w: 52, h: 91 })
    + `<div class="cl-body"><p class="cl-q" id="cl-q">${esc(d.question)}</p>`
    + `<ul class="cl-opts" role="list">${d.options.map((o, i) => `<li><button type="button" class="cl-opt" data-cl="${i}">`
      + `<span class="cl-n" aria-hidden="true">${i + 1}</span><span class="cl-t"><span class="cl-l">${esc(o.label)}</span>`
      + (o.hint ? `<span class="cl-h">${esc(o.hint)}</span>` : '') + `</span></button></li>`).join('')}</ul>`
    + `<button type="button" class="cl-exact" data-cl="typed"><span>${esc(d.asTyped.label)}</span> <span class="cl-ea" aria-hidden="true">→</span></button>`
    + `<p class="cl-keys" id="cl-keys">${esc(w('keys').replace('{n}', n))}</p></div></div>`;
}

/** Show the question for q. onPick({id, plan} | {id:'_typed'}) runs the hunt. */
export function ask(q, d, onPick, { focus = true } = {}) {
  if (!el) return false;
  cur = { q, d, onPick };
  el.innerHTML = html(q, d);
  el.hidden = false;
  el.classList.toggle('cl-still', reduced());
  if (focus) {
    const b = el.querySelector('.cl-opt');
    if (b) b.focus({ preventScroll: true });
  }
  return true;
}
export function close() { cur = null; if (el) { el.hidden = true; el.innerHTML = ''; } }
export const isOpen = () => !!cur;
/** The question last asked for these words (for "change"), or null. */
export const lastFor = q => (last && norm(last.q) === norm(q) ? last : null);
let last = null;

function choose(i) {
  if (!cur) return;
  const { q, d, onPick } = cur;
  const pick = i === 'typed' ? { id: TYPED } : (d.options[i] ? { id: d.options[i].plan.id, plan: d.options[i].plan } : null);
  if (!pick) return;
  remember(q, pick.id);
  last = { q, d };
  close();
  onPick(pick);
}

function onKey(e) {
  if (!cur || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  const inCard = el.contains(t);
  if (!inCard && t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  if (/^[1-9]$/.test(e.key)) {
    const i = Number(e.key) - 1;
    if (i < cur.d.options.length) { e.preventDefault(); choose(i); }
  } else if (e.key === 'Escape') { e.preventDefault(); choose('typed'); }
  else if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
    const bs = [...el.querySelectorAll('.cl-opt, .cl-exact')];
    if (!bs.length) return;
    e.preventDefault();
    const at = bs.indexOf(document.activeElement);
    const k = e.key === 'Home' ? 0 : e.key === 'End' ? bs.length - 1
      : (at < 0 ? 0 : (at + (e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : -1) + bs.length) % bs.length);
    bs[k].focus();
  }
}

export function mountClarify(host, { lang } = {}) {
  if (!host || el) return;
  el = host;
  if (typeof lang === 'function') langOf = lang;
  el.addEventListener('click', e => {
    const b = e.target.closest('[data-cl]');
    if (b) choose(b.dataset.cl === 'typed' ? 'typed' : Number(b.dataset.cl));
  });
  document.addEventListener('keydown', onKey);
}

export const _test = { W };
