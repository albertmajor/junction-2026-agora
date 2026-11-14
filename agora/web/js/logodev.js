// Dev logo panel: tune the header logo (monkey mark + "price|monkey" wordmark) live on the real page, export a JSON
// the owner hands over, and scripts/apply_logo.py writes it into the --logo-* tokens in base.css :root.
// Local only: main.js imports this module on localhost / 127.0.0.1 / [::1]; it opens with ?logodev=1 or
// Ctrl/Cmd+Shift+L. Production users never load it. The font family is not touched (that is the type panel's job,
// devtools.js); weight, size, tracking, case and italics move within the applied wordmark font. See docs/DEVTOOLS.md.
//
// The preview sets the --logo-* tokens inline on :root. Every logo rule in base.css reads only those tokens, so what
// the panel shows is exactly what apply_logo.py writes. A shows the tokens in the code, B your settings.

// ---------- the settings <-> the --logo-* tokens ----------
// numeric fields: [key, css var, unit, min, max, step, label]
export const NUM = [
  ['markWidth', '--logo-mark-w', 'px', 12, 96, 0.5, 'image size'],
  ['gap', '--logo-gap', 'px', -8, 40, 0.25, 'gap'],
  ['tilt', '--logo-tilt', 'deg', -30, 30, 0.5, 'tilt'],
  ['hoverTilt', null, 'deg', -30, 30, 0.5, 'hover tilt'],
  ['size', '--logo-size', 'px', 10, 72, 0.01, 'size'],
  ['weight', '--logo-weight', '', 100, 900, 1, 'weight'],
  ['hoverWeight', '--logo-hover-weight', '', 100, 900, 1, 'hover weight'],
  ['tracking', '--logo-tracking', 'em', -0.15, 0.3, 0.001, 'letter-spacing'],
  ['center', '--logo-center', 'em', 0, 0.8, 0.0025, 'optical middle'],
  ['nudge', null, '', -24, 24, 0.05, 'nudge'],
  ['footerWidth', '--logo-foot-w', 'px', 8, 48, 0.5, 'footer size'],
  ['footerNudge', '--logo-foot-nudge', 'px', -8, 8, 0.25, 'footer nudge'],
];
export const CASES = ['lowercase', 'none', 'uppercase', 'capitalize'];
// the wordmark's optical middle above the baseline, measured on Fraunces italic at opsz 48 (see base.css :root)
export const CENTERS = { x: 0.2325, cap: 0.35 };
export const NUDGE_RANGE = { px: [-12, 12, 0.25], em: [-0.5, 0.5, 0.005] };
const COLOR_VARS = { light: { price: '--logo-price-light', monkey: '--logo-monkey-light' }, dark: { price: '--logo-price-dark', monkey: '--logo-monkey-dark' } };
export const VARS = ['--logo-mark-w', '--logo-gap', '--logo-size', '--logo-weight', '--logo-hover-weight', '--logo-tracking',
  '--logo-case', '--logo-price-style', '--logo-monkey-style', '--logo-center', '--logo-nudge', '--logo-tilt', '--logo-hover-tilt',
  '--logo-price-light', '--logo-monkey-light', '--logo-price-dark', '--logo-monkey-dark', '--logo-foot-w', '--logo-foot-nudge'];
const RX_COLOR = /^(#[0-9a-fA-F]{3,4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|var\(--[a-z0-9-]+\))$/;
const DEFAULT_HOVER_TILT = -7;

// numbers as CSS writes them: at most 4 decimals, no trailing zeros, never "-0" (scripts/apply_logo.py: fmt())
export function fmt(n) {
  const r = Math.floor(n * 1e4 + 0.5) / 1e4;
  return r === 0 ? '0' : String(r);
}
const num = v => { const m = /^\s*(-?[\d.]+)\s*([a-z%]*)\s*$/i.exec(String(v == null ? '' : v)); return m ? { n: +m[1], u: m[2].toLowerCase() } : null; };
const clampN = (v, lo, hi, dflt) => { if (v == null || typeof v === 'boolean' || v === '') return dflt; const n = Number(v); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt; };

// the :root tokens of a stylesheet: { light: {--x: value}, dark: {--x: value} } (dark = :root[data-theme="dark"])
export function parseTokens(cssText) {
  const css = String(cssText).replace(/\/\*[\s\S]*?\*\//g, '');
  const vars = block => Object.fromEntries([...(block || '').matchAll(/(--[\w-]+)\s*:\s*([^;]*);/g)].map(m => [m[1], m[2].trim()]));
  const light = vars((/:root\s*\{([^}]*)\}/.exec(css) || [])[1]);
  const dark = { ...light, ...vars((/:root\[data-theme="dark"\]\s*\{([^}]*)\}/.exec(css) || [])[1]) };
  return { light, dark };
}

// settings from token values (get(name) -> the declared value)
export function fromVars(get) {
  const s = {};
  for (const [key, v, unit, , , , ] of NUM) {
    if (!v) continue;
    const p = num(get(v));
    s[key] = p ? p.n : NaN;
    if (!p || (unit && p.u && p.u !== unit)) throw new Error(`${v}: "${get(v)}" is not a ${unit || 'number'}`);
  }
  const nd = num(get('--logo-nudge')) || { n: 0, u: 'px' };
  s.nudge = nd.n; s.nudgeUnit = nd.u === 'em' ? 'em' : 'px';
  const ht = num(get('--logo-hover-tilt')) || { n: DEFAULT_HOVER_TILT };
  s.wiggle = ht.n !== 0; s.hoverTilt = ht.n !== 0 ? ht.n : DEFAULT_HOVER_TILT;
  s.case = CASES.includes(String(get('--logo-case')).trim()) ? String(get('--logo-case')).trim() : 'lowercase';
  s.priceItalic = String(get('--logo-price-style')).trim() !== 'normal';
  s.monkeyItalic = String(get('--logo-monkey-style')).trim() !== 'normal';
  s.colors = {};
  for (const mode of ['light', 'dark']) {
    s.colors[mode] = {};
    for (const part of ['price', 'monkey']) s.colors[mode][part] = String(get(COLOR_VARS[mode][part]) || '').trim();
  }
  return s;
}
export function baselineFrom(cssText) {
  const t = parseTokens(cssText).light;
  return fromVars(n => t[n]);
}

export function toVars(s) {
  const out = {};
  for (const [key, v, unit] of NUM) if (v) out[v] = fmt(s[key]) + unit;
  out['--logo-nudge'] = fmt(s.nudge) + s.nudgeUnit;
  out['--logo-hover-tilt'] = (s.wiggle ? fmt(s.hoverTilt) : '0') + 'deg';
  out['--logo-case'] = s.case;
  out['--logo-price-style'] = s.priceItalic ? 'italic' : 'normal';
  out['--logo-monkey-style'] = s.monkeyItalic ? 'italic' : 'normal';
  for (const mode of ['light', 'dark']) for (const part of ['price', 'monkey']) out[COLOR_VARS[mode][part]] = s.colors[mode][part];
  return out;
}
export const clone = o => JSON.parse(JSON.stringify(o));
export const sameVars = (a, b) => JSON.stringify(toVars(a)) === JSON.stringify(toVars(b));

export function exportJson(s) {
  const logo = {};
  for (const [key] of NUM) logo[key] = s[key];
  Object.assign(logo, { nudgeUnit: s.nudgeUnit, wiggle: s.wiggle, case: s.case, priceItalic: s.priceItalic,
    monkeyItalic: s.monkeyItalic, colors: clone(s.colors) });
  return {
    version: 1, tool: 'PriceMonkey dev logo panel', exported: new Date().toISOString(),
    units: { markWidth: 'px (height = width x 0.85)', gap: 'px', size: 'px', tracking: 'em', center: 'em above the baseline',
      nudge: 'nudgeUnit, + moves the text down', tilt: 'deg', hoverTilt: 'deg', footerWidth: 'px', footerNudge: 'px, + moves the text down' },
    logo, vars: toVars(s),
  };
}
// a JSON export (string or object) -> settings; unknown or out-of-range values fall back to / are clamped against base
export function importJson(data, base) {
  const j = typeof data === 'string' ? JSON.parse(data) : data;
  if (!j || typeof j !== 'object') throw new Error('not a JSON object');
  const L = j.logo && typeof j.logo === 'object' ? j.logo : null;
  if (!L) throw new Error('no "logo" object (is this a pricemonkey-logo.json?)');
  const s = clone(base);
  for (const [key, , , lo, hi] of NUM) if (key !== 'nudge') s[key] = clampN(L[key], lo, hi, base[key]);
  s.nudgeUnit = L.nudgeUnit === 'em' ? 'em' : L.nudgeUnit === 'px' ? 'px' : base.nudgeUnit;
  const [nlo, nhi] = NUDGE_RANGE[s.nudgeUnit];
  s.nudge = clampN(L.nudge, nlo, nhi, s.nudgeUnit === base.nudgeUnit ? base.nudge : 0);
  for (const k of ['wiggle', 'priceItalic', 'monkeyItalic']) if (typeof L[k] === 'boolean') s[k] = L[k];
  if (CASES.includes(L.case)) s.case = L.case;
  const C = L.colors || {};
  for (const mode of ['light', 'dark']) for (const part of ['price', 'monkey']) {
    const v = C[mode] && typeof C[mode][part] === 'string' ? C[mode][part].trim() : '';
    if (RX_COLOR.test(v)) s.colors[mode][part] = v;
  }
  return s;
}

// a token value -> #rrggbb for <input type=color> (follows var(--x) through the given token map)
export function resolveColor(v, tokens, depth = 0) {
  const m = /^var\((--[\w-]+)\)$/.exec(String(v).trim());
  if (m) return depth > 5 || !tokens[m[1]] ? '#000000' : resolveColor(tokens[m[1]], tokens, depth + 1);
  let h = String(v).trim().toLowerCase();
  if (/^#[0-9a-f]{3,4}$/.test(h)) h = '#' + [...h.slice(1, 4)].map(c => c + c).join('');
  return /^#[0-9a-f]{6}/.test(h) ? h.slice(0, 7) : '#000000';
}

// ---------- the panel (browser only) ----------
const LS_SET = 'pm-logodev.v1', LS_UI = 'pm-logodev-ui.v1';
const isLocal = () => typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1|\[::1\]|::1)$/.test(location.hostname);
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const escH = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let BASE = null, S = null, UI = null, TOK = { light: {}, dark: {} }, showA = false, panel = null, pill = null, started = false;
let guides = null, themeBefore = undefined, cssLoaded = false;

function loadCss() {
  if (cssLoaded) return;
  cssLoaded = true;
  const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/web/css/logodev.css';
  document.head.appendChild(l);
}
const custom = () => !sameVars(S, BASE);
function applyNow() {
  const root = document.documentElement.style;
  if (showA || !custom()) for (const v of VARS) root.removeProperty(v);
  else for (const [k, v] of Object.entries(toVars(S))) root.setProperty(k, v);
  updatePill(); drawGuides();
}
function save() { if (custom()) store.set(LS_SET, exportJson(S)); else store.del(LS_SET); }
function saveUi() { store.set(LS_UI, UI); }
function change() { save(); applyNow(); renderStatus(); }

function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function slider(key, label, val, min, max, step, unit) {
  return `<div class="lgd-row"><label for="lgd-${key}">${label}</label>
    <input type="range" id="lgd-${key}" data-k="${key}" min="${min}" max="${max}" step="${step}" value="${val}">
    <input type="number" class="lgd-num" data-k="${key}" min="${min}" max="${max}" step="${step}" value="${val}"><span class="lgd-unit">${unit}</span></div>`;
}
const numField = key => { const f = NUM.find(x => x[0] === key); return slider(key, f[6], S[key], f[3], f[4], f[5], f[2]); };
function colorRow(mode, part) {
  const v = S.colors[mode][part];
  return `<div class="lgd-row lgd-color"><label for="lgd-c-${mode}-${part}">${part === 'price' ? '"price"' : '"monkey"'}</label>
    <input type="color" id="lgd-c-${mode}-${part}" data-c="${mode}.${part}" value="${resolveColor(v, TOK[mode])}">
    <input type="text" class="lgd-hex" data-c="${mode}.${part}" value="${escH(v)}" spellcheck="false"></div>`;
}

function mount() {
  if (panel) return;
  loadCss();
  panel = el(`<aside id="pm-ld" class="pm-ld" role="dialog" aria-label="Dev logo panel">
    <header class="lgd-head" title="drag to move">
      <b>Logo</b><span class="lgd-sub">dev panel · localhost only</span>
      <div class="lgd-ab" role="group" aria-label="Compare">
        <button type="button" data-ab="a" title="A: the logo in the code now">A</button>
        <button type="button" data-ab="b" title="B: your settings">B</button>
      </div>
      <button type="button" class="lgd-ico" data-act="collapse" aria-label="Collapse" title="Collapse">–</button>
      <button type="button" class="lgd-ico" data-act="close" aria-label="Close" title="Close (Ctrl/Cmd+Shift+L)">×</button>
    </header>
    <div class="lgd-body"></div>
  </aside>`);
  document.body.appendChild(panel);
  const head = panel.querySelector('.lgd-head');
  head.addEventListener('pointerdown', e => {
    if (e.target.closest('button')) return;
    const r = panel.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    head.setPointerCapture(e.pointerId);
    const mv = ev => { UI.x = Math.max(0, Math.min(innerWidth - 80, ev.clientX - dx)); UI.y = Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy)); place(); };
    const up = () => { head.removeEventListener('pointermove', mv); head.removeEventListener('pointerup', up); saveUi(); };
    head.addEventListener('pointermove', mv); head.addEventListener('pointerup', up);
  });
  panel.addEventListener('click', onClick);
  panel.addEventListener('input', onInput);
  panel.addEventListener('change', onChange);
  render(); place(); setAB(showA);
}
function place() {
  if (!panel) return;
  panel.classList.toggle('collapsed', !!UI.collapsed);
  if (UI.x != null) { panel.style.left = Math.min(UI.x, innerWidth - 80) + 'px'; panel.style.top = Math.min(UI.y, innerHeight - 40) + 'px'; panel.style.right = 'auto'; }
}
function setAB(a) {
  showA = a;
  if (panel) panel.querySelectorAll('[data-ab]').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.ab === 'a') === a)));
  applyNow();
}
function centerPreset() { return Object.keys(CENTERS).find(k => Math.abs(CENTERS[k] - S.center) < 1e-9) || 'custom'; }
function render() {
  if (!panel) return;
  const [nlo, nhi, nst] = NUDGE_RANGE[S.nudgeUnit];
  const theme = UI.theme || 'auto';
  panel.querySelector('.lgd-body').innerHTML = `
    <div class="lgd-sec">Mark</div>
    ${numField('markWidth')}${numField('gap')}${numField('tilt')}
    <div class="lgd-row"><span>hover wiggle</span><label class="lgd-chk"><input type="checkbox" data-b="wiggle" ${S.wiggle ? 'checked' : ''}> on</label></div>
    ${S.wiggle ? numField('hoverTilt') : ''}
    <div class="lgd-sec">Vertical centring <small>the mark's middle on the text's</small></div>
    <div class="lgd-row"><label for="lgd-center-s">centre on</label>
      <select id="lgd-center-s">
        <option value="x" ${centerPreset() === 'x' ? 'selected' : ''}>x-height middle (lowercase)</option>
        <option value="cap" ${centerPreset() === 'cap' ? 'selected' : ''}>cap-height middle (CAPS)</option>
        <option value="custom" ${centerPreset() === 'custom' ? 'selected' : ''}>custom (em above baseline)</option>
      </select></div>
    ${centerPreset() === 'custom' ? numField('center') : ''}
    <div class="lgd-row"><label for="lgd-nudge">nudge text</label>
      <input type="range" id="lgd-nudge" data-k="nudge" min="${nlo}" max="${nhi}" step="${nst}" value="${S.nudge}">
      <input type="number" class="lgd-num" data-k="nudge" min="${nlo}" max="${nhi}" step="${nst}" value="${S.nudge}">
      <select class="lgd-unit-s" aria-label="nudge unit"><option ${S.nudgeUnit === 'px' ? 'selected' : ''}>px</option><option ${S.nudgeUnit === 'em' ? 'selected' : ''}>em</option></select></div>
    <div class="lgd-row"><span>guides</span><label class="lgd-chk"><input type="checkbox" data-ui="guides" ${UI.guides ? 'checked' : ''}> show the mark's middle and the text's x/cap band</label></div>
    <div class="lgd-sec">Wordmark <small>font stays ${escH(getComputedStyle(document.documentElement).getPropertyValue('--serif').split(',')[0].trim())}</small></div>
    ${numField('size')}${numField('weight')}${numField('hoverWeight')}${numField('tracking')}
    <div class="lgd-row"><label for="lgd-case">case</label>
      <select id="lgd-case">${CASES.map(c => `<option value="${c}" ${S.case === c ? 'selected' : ''}>${{ lowercase: 'pricemonkey (lowercase)', none: 'PriceMonkey (as written)', uppercase: 'PRICEMONKEY (uppercase)', capitalize: 'Capitalize' }[c]}</option>`).join('')}</select></div>
    <div class="lgd-row"><span>italic</span><span class="lgd-pair">
      <label class="lgd-chk"><input type="checkbox" data-b="priceItalic" ${S.priceItalic ? 'checked' : ''}> price</label>
      <label class="lgd-chk"><input type="checkbox" data-b="monkeyItalic" ${S.monkeyItalic ? 'checked' : ''}> monkey</label></span></div>
    <div class="lgd-sec">Colours <small>light and dark separately</small></div>
    <div class="lgd-row"><span>preview</span><span class="lgd-seg" role="group" aria-label="Preview theme">
      ${['auto', 'light', 'dark'].map(t => `<button type="button" data-theme-set="${t}" aria-pressed="${theme === t}">${t}</button>`).join('')}</span></div>
    <div class="lgd-cols"><div><div class="lgd-cap">light</div>${colorRow('light', 'price')}${colorRow('light', 'monkey')}</div>
      <div><div class="lgd-cap">dark</div>${colorRow('dark', 'price')}${colorRow('dark', 'monkey')}</div></div>
    <div class="lgd-sec">Footer mark</div>
    ${numField('footerWidth')}${numField('footerNudge')}
    <div class="lgd-status"></div>
    <footer class="lgd-foot">
      <div class="lgd-btns">
        <button type="button" data-act="export">Export JSON</button>
        <button type="button" data-act="import">Import…</button>
        <button type="button" data-act="reset">Reset</button>
      </div>
      <div class="lgd-import" hidden>
        <textarea rows="4" placeholder="paste pricemonkey-logo.json here"></textarea>
        <div class="lgd-btns"><button type="button" data-act="import-paste">Apply pasted</button>
        <label class="lgd-file">or a file <input type="file" accept="application/json,.json"></label></div>
      </div>
      <p class="lgd-help">Export copies the JSON and downloads <code>pricemonkey-logo.json</code>. To make it the site's logo:
      <code>.venv/bin/python scripts/apply_logo.py pricemonkey-logo.json</code> (writes the <code>--logo-*</code> tokens in
      web/css/base.css; <code>--dry-run</code> to preview). Docs: docs/DEVTOOLS.md</p>
    </footer>`;
  renderStatus();
}
function renderStatus() {
  const st = panel && panel.querySelector('.lgd-status');
  if (!st) return;
  const diff = Object.entries(toVars(S)).filter(([k, v]) => toVars(BASE)[k] !== v);
  st.innerHTML = UI.msg ? escH(UI.msg) : diff.length ? `${diff.length} changed: ${diff.map(([k, v]) => `<code>${escH(k.slice(7))} ${escH(v)}</code>`).join(' ')}` : 'same as the code (A)';
  UI.msg = '';
}

function setTheme(t) {
  UI.theme = t; saveUi();
  const h = document.documentElement;
  if (themeBefore === undefined) themeBefore = h.getAttribute('data-theme');
  if (t === 'auto') { if (themeBefore == null) h.removeAttribute('data-theme'); else h.setAttribute('data-theme', themeBefore); }
  else h.setAttribute('data-theme', t);
  if (panel) panel.querySelectorAll('[data-theme-set]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.themeSet === t)));
  drawGuides();
}

// guides: a line through the mark's middle and the band (x-height or cap-height) the text is centred by
function drawGuides() {
  if (!UI || !UI.guides || !panel) { if (guides) { guides.remove(); guides = null; } return; }
  const logo = document.querySelector('#bar .logo'), mark = logo && logo.querySelector('.logo-mark'), brand = logo && logo.querySelector('.brand');
  if (!mark || !brand) return;
  if (!guides) { guides = el('<div class="lgd-guides" aria-hidden="true"><i class="lgd-g-band"></i><i class="lgd-g-mid"></i></div>'); document.body.appendChild(guides); }
  const mk = document.createElement('i'); mk.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
  brand.appendChild(mk); const base = mk.getBoundingClientRect().bottom; mk.remove();
  const fs = parseFloat(getComputedStyle(brand).fontSize), m = mark.getBoundingClientRect(), b = logo.getBoundingClientRect();
  const band = (centerPreset() === 'cap' ? 0.7 : centerPreset() === 'x' ? 0.465 : S.center * 2) * fs;
  Object.assign(guides.style, { left: (b.left - 8) + 'px', width: (b.width + 16) + 'px', top: '0px' });
  Object.assign(guides.querySelector('.lgd-g-mid').style, { top: ((m.top + m.bottom) / 2) + 'px' });
  Object.assign(guides.querySelector('.lgd-g-band').style, { top: (base - band) + 'px', height: band + 'px' });
}

function updatePill() {
  const on = custom() && !showA;
  if (on && !panel) {
    if (!pill) {
      loadCss();
      pill = el('<button type="button" class="pm-lgd-pill" title="Custom logo settings from the dev logo panel are applied (localhost only). Click to open.">custom logo</button>');
      pill.addEventListener('click', () => toggle(true));
      document.body.appendChild(pill);
    }
  } else if (pill) { pill.remove(); pill = null; }
}

function onClick(e) {
  const b = e.target.closest('button');
  if (!b) return;
  const act = b.dataset.act;
  if (b.dataset.ab) setAB(b.dataset.ab === 'a');
  else if (b.dataset.themeSet) setTheme(b.dataset.themeSet);
  else if (act === 'collapse') { UI.collapsed = !UI.collapsed; saveUi(); place(); }
  else if (act === 'close') toggle(false);
  else if (act === 'export') doExport();
  else if (act === 'import') { const d = panel.querySelector('.lgd-import'); d.hidden = !d.hidden; }
  else if (act === 'import-paste') doImport(panel.querySelector('.lgd-import textarea').value);
  else if (act === 'reset') { S = clone(BASE); UI.msg = 'reset to the logo in the code'; render(); change(); }
}
function onInput(e) {
  const t = e.target;
  if (t.dataset.k) {
    const k = t.dataset.k, v = parseFloat(t.value);
    if (!Number.isFinite(v)) return;
    const twin = panel.querySelector(`${t.type === 'range' ? '.lgd-num' : 'input[type="range"]'}[data-k="${k}"]`);
    if (twin) twin.value = t.value;
    S[k] = k === 'weight' || k === 'hoverWeight' ? Math.round(v) : v;
    change();
  } else if (t.type === 'color' && t.dataset.c) {
    const [mode, part] = t.dataset.c.split('.');
    S.colors[mode][part] = t.value;
    const tx = panel.querySelector(`.lgd-hex[data-c="${t.dataset.c}"]`); if (tx) tx.value = t.value;
    change();
  }
}
function onChange(e) {
  const t = e.target;
  if (t.dataset.b) { S[t.dataset.b] = t.checked; if (t.dataset.b === 'wiggle') render(); change(); }
  else if (t.dataset.ui === 'guides') { UI.guides = t.checked; saveUi(); drawGuides(); }
  else if (t.id === 'lgd-center-s') { if (t.value !== 'custom') S.center = CENTERS[t.value]; render(); change(); }
  else if (t.id === 'lgd-case') {
    S.case = t.value;
    // caps have no x-height: centre them on the cap-height (and back), unless a custom middle was set
    if (centerPreset() !== 'custom') S.center = t.value === 'uppercase' ? CENTERS.cap : CENTERS.x;
    render(); change();
  } else if (t.classList.contains('lgd-unit-s')) {
    const fs = parseFloat(getComputedStyle(document.querySelector('#bar .logo') || document.documentElement).fontSize) || 26;
    const to = t.value;
    if (to !== S.nudgeUnit) S.nudge = +(to === 'em' ? S.nudge / fs : S.nudge * fs).toFixed(to === 'em' ? 3 : 2);
    S.nudgeUnit = to; render(); change();
  } else if (t.classList.contains('lgd-hex')) {
    const [mode, part] = t.dataset.c.split('.'), v = t.value.trim();
    if (RX_COLOR.test(v)) { S.colors[mode][part] = v; render(); change(); } else { UI.msg = `"${v}" is not a colour (#rrggbb or var(--token))`; renderStatus(); }
  } else if (t.type === 'file' && t.files && t.files[0]) t.files[0].text().then(doImport);
}
function doExport() {
  const text = JSON.stringify(exportJson(S), null, 2) + '\n';
  const msg = panel.querySelector('.lgd-status');
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject(new Error('no clipboard')))
    .then(() => { msg.textContent = 'copied to the clipboard and downloaded pricemonkey-logo.json'; })
    .catch(() => { msg.textContent = 'downloaded pricemonkey-logo.json (clipboard not allowed here)'; });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  a.download = 'pricemonkey-logo.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function doImport(text) {
  try { S = importJson(text, BASE); UI.msg = 'imported'; render(); change(); }
  catch (err) { UI.msg = 'import failed: ' + err.message; renderStatus(); }
}

function toggle(force) {
  const open = force != null ? force : !panel;
  UI.open = open; saveUi();
  if (open) { if (pill) { pill.remove(); pill = null; } mount(); if (UI.theme && UI.theme !== 'auto') setTheme(UI.theme); }
  else if (panel) {
    panel.remove(); panel = null;
    if (themeBefore !== undefined) { const t = UI.theme; setTheme('auto'); UI.theme = t; saveUi(); }
    if (showA) setAB(false); else applyNow();
  }
}

export async function init() {
  if (started || !isLocal()) return;
  started = true;
  UI = Object.assign({ open: false, collapsed: false, x: null, y: null, guides: false, theme: 'auto' }, store.get(LS_UI) || {});
  const params = new URLSearchParams(location.search);
  if (params.get('logodev') === '0') UI.open = false;
  addEventListener('keydown', e => {
    if (!BASE) return;
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'L' || e.key === 'l')) { e.preventDefault(); toggle(); }
  });
  addEventListener('resize', () => drawGuides());
  addEventListener('scroll', () => drawGuides(), { passive: true });
  // the tokens as written in base.css (not computed: keeps "var(--ink)" as var(--ink), and both themes)
  try {
    const r = await fetch('/web/css/base.css', { cache: 'no-cache' });
    TOK = parseTokens(await r.text());
    BASE = fromVars(n => TOK.light[n]);
  } catch (e) {
    const cs = getComputedStyle(document.documentElement);
    BASE = fromVars(n => cs.getPropertyValue(n));
    console.warn('[logodev] base.css not readable, using computed tokens:', e.message);
  }
  S = clone(BASE);
  const saved = store.get(LS_SET);
  if (saved) { try { S = importJson(saved, BASE); } catch (e) { console.warn('[logodev] saved logo settings ignored:', e.message); } }
  if (custom()) applyNow();
  if (params.get('logodev') === '1' || UI.open) toggle(true); else updatePill();
  window.pmLogodev = { get settings() { return S; }, base: () => BASE, toggle, exportJson: () => exportJson(S), importJson: t => doImport(typeof t === 'string' ? t : JSON.stringify(t)) };
}
