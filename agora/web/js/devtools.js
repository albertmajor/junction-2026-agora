// Dev type panel: pick the fonts and type variables for the three type roles, preview them live on the real page,
// export a JSON the owner hands over, and scripts/apply_fonts.py writes it into index.html + the CSS.
// Local only: main.js imports this module on localhost / 127.0.0.1 / [::1]; it opens with ?dev=1 or
// Ctrl/Cmd+Shift+D. Production users never load it. See docs/DEVTOOLS.md.
//
// How the preview works (and why it matches apply_fonts.py exactly):
//   1. the role tokens (--sans, --sans-size, --display-vs, ...) are set inline on :root;
//   2. every /web/css/*.css sheet is fetched once and run through transformCss() (the same rules as
//      scripts/apply_fonts.py: sizes on the role's modular scale, line-height, tracking and weight deltas,
//      features/labels appended), injected as a <style> next to its <link>, and the <link> is disabled.
//   A/B puts the untouched sheets and tokens back while held on "A".

// ---------- catalog: [family, style, axes "tag:min:max ...", static weights, has italics] ----------
const RAW = [
  ['Instrument Sans', 'grotesk', 'wdth:75:100 wght:400:700', '400,500,600,700', 1],
  ['Inter', 'grotesk', 'opsz:14:32 wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Inter Tight', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Schibsted Grotesk', 'grotesk', 'wght:400:900', '400,500,600,700,800,900', 1],
  ['Hanken Grotesk', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Space Grotesk', 'grotesk', 'wght:300:700', '300,400,500,600,700', 0],
  ['Familjen Grotesk', 'grotesk', 'wght:400:700', '400,500,600,700', 1],
  ['Bricolage Grotesque', 'grotesk', 'opsz:12:96 wdth:75:100 wght:200:800', '200,300,400,500,600,700,800', 0],
  ['Host Grotesk', 'grotesk', 'wght:300:800', '300,400,500,600,700,800', 1],
  ['Funnel Sans', 'grotesk', 'wght:300:800', '300,400,500,600,700,800', 1],
  ['Geist', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Archivo', 'grotesk', 'wdth:62:125 wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Public Sans', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Onest', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 0],
  ['Rethink Sans', 'grotesk', 'wght:400:800', '400,500,600,700,800', 1],
  ['Albert Sans', 'grotesk', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['DM Sans', 'geometric', 'opsz:9:40 wght:100:1000', '100,200,300,400,500,600,700,800,900,1000', 1],
  ['Manrope', 'geometric', 'wght:200:800', '200,300,400,500,600,700,800', 0],
  ['Plus Jakarta Sans', 'geometric', 'wght:200:800', '200,300,400,500,600,700,800', 1],
  ['Outfit', 'geometric', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 0],
  ['Figtree', 'geometric', 'wght:300:900', '300,400,500,600,700,800,900', 1],
  ['Urbanist', 'geometric', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Sora', 'geometric', 'wght:100:800', '100,200,300,400,500,600,700,800', 0],
  ['Lexend', 'geometric', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 0],
  ['Red Hat Text', 'geometric', 'wght:300:700', '300,400,500,600,700', 1],
  ['Poppins', 'geometric', '', '100,200,300,400,500,600,700,800,900', 1],
  ['Source Sans 3', 'humanist', 'wght:200:900', '200,300,400,500,600,700,800,900', 1],
  ['Nunito Sans', 'humanist', 'YTLC:440:540 opsz:6:12 wdth:75:125 wght:200:1000', '200,300,400,500,600,700,800,900,1000', 1],
  ['Work Sans', 'humanist', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Mulish', 'humanist', 'wght:200:1000', '200,300,400,500,600,700,800,900,1000', 1],
  ['Karla', 'humanist', 'wght:200:800', '200,300,400,500,600,700,800', 1],
  ['Libre Franklin', 'humanist', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['IBM Plex Sans', 'humanist', 'wdth:75:100 wght:100:700', '100,200,300,400,500,600,700', 1],
  ['Atkinson Hyperlegible Next', 'humanist', 'wght:200:800', '200,300,400,500,600,700,800', 1],
  ['Commissioner', 'humanist', 'FLAR:0:100 VOLM:0:100 slnt:-12:0 wght:100:900', '100,200,300,400,500,600,700,800,900', 0],
  ['Wix Madefor Text', 'humanist', 'wght:400:800', '400,500,600,700,800', 1],
  ['Reddit Sans', 'humanist', 'wght:200:900', '200,300,400,500,600,700,800,900', 1],
  ['Fraunces', 'serif', 'SOFT:0:100 WONK:0:1 opsz:9:144 wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Newsreader', 'serif', 'opsz:6:72 wght:200:800', '200,300,400,500,600,700,800', 1],
  ['Instrument Serif', 'serif', '', '400', 1],
  ['Playfair Display', 'serif', 'wght:400:900', '400,500,600,700,800,900', 1],
  ['DM Serif Display', 'serif', '', '400', 1],
  ['Source Serif 4', 'serif', 'opsz:8:60 wght:200:900', '200,300,400,500,600,700,800,900', 1],
  ['Literata', 'serif', 'opsz:7:72 wght:200:900', '200,300,400,500,600,700,800,900', 1],
  ['Young Serif', 'serif', '', '400', 0],
  ['EB Garamond', 'serif', 'wght:400:800', '400,500,600,700,800', 1],
  ['Gloock', 'serif', '', '400', 0],
  ['Bodoni Moda', 'serif', 'opsz:6:96 wght:400:900', '400,500,600,700,800,900', 1],
  ['IBM Plex Mono', 'mono', '', '100,200,300,400,500,600,700', 1],
  ['JetBrains Mono', 'mono', 'wght:100:800', '100,200,300,400,500,600,700,800', 1],
  ['DM Mono', 'mono', '', '300,400,500', 1],
  ['Geist Mono', 'mono', 'wght:100:900', '100,200,300,400,500,600,700,800,900', 1],
  ['Space Mono', 'mono', '', '400,700', 1],
  ['Fira Code', 'mono', 'wght:300:700', '300,400,500,600,700', 0],
  ['Roboto Mono', 'mono', 'wght:100:700', '100,200,300,400,500,600,700', 1],
  ['Martian Mono', 'mono', 'wdth:75:112.5 wght:100:800', '100,200,300,400,500,600,700,800', 0],
  ['Red Hat Mono', 'mono', 'wght:300:700', '300,400,500,600,700', 1],
  ['Source Code Pro', 'mono', 'wght:200:900', '200,300,400,500,600,700,800,900', 1],
];
export const CATALOG = RAW.map(([family, style, axes, weights, ital]) => ({
  family, style,
  axes: axes ? axes.split(' ').map(a => { const [tag, min, max] = a.split(':'); return [tag, +min, +max]; }) : [],
  weights: weights.split(',').map(Number), ital: !!ital,
}));
export const STYLES = { grotesk: 'Grotesk sans (closest to Instrument Sans)', geometric: 'Geometric sans', humanist: 'Humanist sans', serif: 'Serif / display', mono: 'Mono' };
const ROLE_STYLES = { main: ['grotesk', 'geometric', 'humanist'], display: ['serif', 'grotesk', 'geometric', 'humanist'], mono: ['mono'] };
export const ROLES = {
  main: { label: 'Main (UI sans)', family: '--sans', p: 'sans' },
  display: { label: 'Display (headlines)', family: '--serif', p: 'display' },
  mono: { label: 'Mono (numbers)', family: '--mono', p: 'mono' },
};
export const RATIOS = [[1.067, 'minor second'], [1.125, 'major second'], [1.2, 'minor third'], [1.25, 'major third'],
  [1.333, 'perfect fourth'], [1.414, 'augmented fourth'], [1.5, 'perfect fifth'], [1.618, 'golden']];
const FEATURE_CHIPS = ['tnum', 'lnum', 'onum', 'zero', 'case', 'ss01', 'ss02', 'ss03', 'ss04', 'cv01', 'cv05', 'cv11', 'salt', 'liga'];

export function findFont(name) {
  const n = String(name || '').trim().toLowerCase();
  return CATALOG.find(f => f.family.toLowerCase() === n) || null;
}

// ---------- numbers (same rounding as scripts/apply_fonts.py: floor(x*10^d + .5) / 10^d) ----------
export function fmt(n, d) {
  const p = Math.pow(10, d);
  const r = Math.floor(n * p + 0.5) / p;
  if (Number.isInteger(r)) return String(r === 0 ? 0 : r);
  return String(r);
}
const near = (a, b) => Math.abs(a - b) < 1e-9;
const emStr = n => (near(n, 0) ? '0' : fmt(n, 4) + 'em');

// ---------- token parsing ----------
export function parseFamilyList(v) {
  const s = String(v || '').trim();
  const m = /^\s*(?:"([^"]+)"|'([^']+)'|([^,]+))\s*(?:,\s*([\s\S]*))?$/.exec(s);
  if (!m) return { family: s, fallback: '' };
  return { family: (m[1] || m[2] || m[3] || '').trim(), fallback: (m[4] || '').trim() };
}
export function parseVs(v) {
  const out = {};
  const s = String(v || '').trim();
  if (!s || s === 'normal') return out;
  for (const m of s.matchAll(/["']([A-Za-z0-9]{4})["']\s+(-?[\d.]+)/g)) out[m[1]] = +m[2];
  return out;
}
export function vsString(axes) {
  const parts = Object.entries(axes || {}).filter(([t]) => t !== 'wght' && t !== 'ital').map(([t, v]) => `"${t}" ${fmt(+v, 2)}`);
  return parts.length ? parts.join(', ') : 'normal';
}
const trackNum = v => { const s = String(v || '').trim(); return !s || s === 'normal' ? 0 : parseFloat(s) || 0; };
export function parseFeatures(s) {
  const out = {};
  const t = String(s || '').trim();
  if (!t || t === 'normal') return out;
  for (const m of t.matchAll(/["']([A-Za-z0-9]{4})["']\s*(on|off|\d+)?/g)) out[m[1]] = m[2] == null || m[2] === 'on' ? 1 : m[2] === 'off' ? 0 : +m[2];
  return out;
}
export function featuresString(map) {
  const parts = Object.entries(map).map(([t, v]) => `"${t}" ${v}`);
  return parts.length ? parts.join(', ') : 'normal';
}

// ---------- settings ----------
// One role: { family, fallback, weight, weights[], axes{tag:value} (not wght), size(px), ratio, letterSpacing(em),
//   lineHeight, features (CSS font-feature-settings string or "normal"), labels? {transform, letterSpacing, maxSize} }
export function baselineFrom(get) {
  // get(name) returns a :root custom property's value (getComputedStyle or a parsed base.css)
  const role = (p, famVar, vsVar) => {
    const { family, fallback } = parseFamilyList(get(famVar));
    const meta = findFont(family);
    const weight = parseFloat(get(`--${p}-weight`)) || 400;
    const avail = meta ? meta.weights : [400, 500];
    return {
      family, fallback, weight,
      weights: [...new Set([weight, 400, 500])].filter(w => avail.includes(w)).sort((a, b) => a - b),
      axes: parseVs(get(vsVar)),
      size: parseFloat(get(`--${p}-size`)) || 15,
      ratio: parseFloat(get(`--${p}-ratio`)) || 1.25,
      letterSpacing: trackNum(get(`--${p}-tracking`)),
      lineHeight: parseFloat(get(`--${p}-lh`)) || 1.4,
      features: String(get(`--${p}-features`) || 'normal').trim() || 'normal',
    };
  };
  const main = role('sans', '--sans', '--sans-vs');
  main.labels = {
    transform: String(get('--label-transform') || 'none').trim() || 'none',
    letterSpacing: trackNum(get('--label-tracking')),
    maxSize: parseFloat(get('--label-max')) || 12,
  };
  return { main, display: role('display', '--serif', '--display-vs'), mono: role('mono', '--mono', '--mono-vs') };
}

export const clone = o => JSON.parse(JSON.stringify(o));

// CSS custom properties on :root for a settings object (scripts/apply_fonts.py writes the same names into base.css)
export function rootVars(s) {
  const fam = r => `"${r.family}"${r.fallback ? ', ' + r.fallback : ''}`;
  const track = n => (near(n, 0) ? 'normal' : emStr(n));
  const v = {
    '--sans': fam(s.main), '--sans-weight': fmt(s.main.weight, 0), '--sans-size': fmt(s.main.size, 2) + 'px',
    '--sans-ratio': fmt(s.main.ratio, 3), '--sans-lh': fmt(s.main.lineHeight, 3), '--sans-tracking': track(s.main.letterSpacing),
    '--sans-features': s.main.features || 'normal', '--sans-vs': vsString(s.main.axes),
    '--label-transform': s.main.labels.transform, '--label-tracking': track(s.main.labels.letterSpacing),
    '--label-max': fmt(s.main.labels.maxSize, 2) + 'px',
    '--serif': fam(s.display), '--display-weight': fmt(s.display.weight, 0), '--display-size': fmt(s.display.size, 2) + 'px',
    '--display-ratio': fmt(s.display.ratio, 3), '--display-lh': fmt(s.display.lineHeight, 3),
    '--display-tracking': track(s.display.letterSpacing), '--display-features': s.display.features || 'normal',
    '--display-vs': vsString(s.display.axes),
    '--mono': fam(s.mono), '--mono-weight': fmt(s.mono.weight, 0), '--mono-size': fmt(s.mono.size, 2) + 'px',
    '--mono-ratio': fmt(s.mono.ratio, 3), '--mono-lh': fmt(s.mono.lineHeight, 3), '--mono-tracking': track(s.mono.letterSpacing),
    '--mono-features': s.mono.features || 'normal', '--mono-vs': vsString(s.mono.axes),
  };
  return v;
}

// ---------- Google Fonts URL ----------
const axisOrder = (a, b) => {
  const la = a === a.toLowerCase(), lb = b === b.toLowerCase();
  if (la !== lb) return la ? -1 : 1;
  return a < b ? -1 : a > b ? 1 : 0;
};
const num = n => fmt(n, 2);
export function familyParam(r, roleName, meta) {
  meta = meta || r.meta || findFont(r.family) || { axes: [], weights: r.weights && r.weights.length ? r.weights : [400], ital: false };
  const name = r.family.trim().replace(/\s+/g, '+');
  const ital = meta.ital && roleName !== 'mono';
  if (meta.axes && meta.axes.length) {
    const axes = [...meta.axes].sort((a, b) => axisOrder(a[0], b[0]));
    const tags = (ital ? ['ital'] : []).concat(axes.map(a => a[0]));
    const vals = i => (ital ? [String(i)] : []).concat(axes.map(a => `${num(a[1])}..${num(a[2])}`)).join(',');
    return `${name}:${tags.join(',')}@${ital ? vals(0) + ';' + vals(1) : vals(0)}`;
  }
  const avail = meta.weights && meta.weights.length ? meta.weights : [400];
  let ws = [...new Set([...(r.weights || []), r.weight])].filter(w => avail.includes(w)).sort((a, b) => a - b);
  if (!ws.length) ws = [avail.includes(400) ? 400 : avail[0]];
  if (ws.length === 1 && ws[0] === 400 && !ital) return name;
  if (ital) return `${name}:ital,wght@${ws.map(w => `0,${w}`).concat(ws.map(w => `1,${w}`)).join(';')}`;
  return `${name}:wght@${ws.join(';')}`;
}
export function googleFontsUrl(s) {
  const seen = new Set(), fams = [];
  for (const k of ['display', 'main', 'mono']) {
    const key = s[k].family.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    fams.push('family=' + familyParam(s[k], k));
  }
  return `https://fonts.googleapis.com/css2?${fams.join('&')}&display=swap`;
}
// meta for every family in a css2 URL (used when importing a JSON that names a family not in the catalog)
export function metaFromUrl(url) {
  const out = {};
  let q;
  try { q = new URL(url).searchParams.getAll('family'); } catch { return out; }
  for (const f of q) {
    const [name, spec] = f.split(':');
    const family = name.replace(/\+/g, ' ');
    if (!spec) { out[family.toLowerCase()] = { axes: [], weights: [400], ital: false }; continue; }
    const [tagsS, valsS] = spec.split('@');
    const tags = tagsS.split(',');
    const tuples = (valsS || '').split(';').map(t => t.split(','));
    const meta = { axes: [], weights: [], ital: tags.includes('ital') && tuples.some(t => t[tags.indexOf('ital')] === '1') };
    tags.forEach((t, i) => {
      if (t === 'ital') return;
      const v = tuples[0] && tuples[0][i];
      if (v && v.includes('..')) { const [a, b] = v.split('..').map(Number); meta.axes.push([t, a, b]); }
      else if (t === 'wght') meta.weights = [...new Set(tuples.map(x => +x[i]))].sort((a, b) => a - b);
    });
    if (!meta.weights.length) meta.weights = [400];
    out[family.toLowerCase()] = meta;
  }
  return out;
}

// ---------- the CSS transform (mirrored 1:1 by scripts/apply_fonts.py) ----------
// plan = { main|display|mono: { oldSize, size, oldRatio, ratio, oldLh, lh, oldLs, ls, oldWeight, weight,
//          oldFeatures, features, oldVs, vs }, labels: { transform, oldTransform, ls, oldLs, maxSize } }
export function makePlan(base, s) {
  const plan = {};
  for (const k of ['main', 'display', 'mono']) {
    const b = base[k], n = s[k];
    plan[k] = {
      oldSize: b.size, size: n.size, oldRatio: b.ratio, ratio: n.ratio, oldLh: b.lineHeight, lh: n.lineHeight,
      oldLs: b.letterSpacing, ls: n.letterSpacing, oldWeight: b.weight, weight: n.weight,
      oldFeatures: b.features || 'normal', features: n.features || 'normal', oldVs: vsString(b.axes), vs: vsString(n.axes),
    };
  }
  const bl = base.main.labels, nl = s.main.labels;
  plan.labels = { oldTransform: bl.transform, transform: nl.transform, oldLs: bl.letterSpacing, ls: nl.letterSpacing, maxSize: bl.maxSize };
  return plan;
}

const RX_BLOCK = /([^{}]*)\{([^{}]*)\}/g;
const RX_FAMILY = /(?<![\w-])font(?:-family)?\s*:[^;]*?var\(--(serif|mono|sans)\)/;
const RX_HAS_TYPE = /(?<![\w-])(?:font|font-size|line-height|letter-spacing|font-weight)\s*:/;
const RX_DECL = /(?<![\w-])(font|font-size|line-height|letter-spacing|font-weight)(\s*:\s*)([^;]*?)(\s*(?:!important)?\s*)(?=;|$)/g;
const RX_SHORT = /^((?:(?:italic|normal|oblique|small-caps|bold|bolder|lighter|\d{3})\s+)*)((?:clamp|min|max|calc)\([^()]*\)|[\d.]+(?:px|em|rem|%))(?:(\s*\/\s*)([\d.]+(?:px|em|%)?|normal))?(\s+)([\s\S]+)$/;
const ROLE_OF = { serif: 'display', mono: 'mono', sans: 'main' };
const cleanSel = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ').trim();
const SKIP_SEL = new Set([':root', 'body', 'html', 'html, body']);

function sizeNoop(p) { return near(p.size, p.oldSize) && near(p.ratio, p.oldRatio); }
function newPx(n, p) {
  const k = Math.log(p.ratio) / Math.log(p.oldRatio);
  return p.size * Math.pow(n / p.oldSize, k);
}
function scaleSize(v, p) {
  if (sizeNoop(p)) return v;
  return v.replace(/(-?[\d.]+)(px|vw)\b/g, (m, n, u) => (u === 'px' ? fmt(newPx(+n, p), 2) + 'px' : fmt(+n * p.size / p.oldSize, 3) + 'vw'));
}
function pxOf(v) { const m = /^\s*([\d.]+)px\s*$/.exec(v); return m ? +m[1] : null; }
function scaleLh(v, p, oldPx) {
  const f = p.lh / p.oldLh;
  const sf = oldPx != null ? newPx(oldPx, p) / oldPx : p.size / p.oldSize;
  if (near(f, 1) && (sizeNoop(p) || near(sf, 1))) return v;
  const t = v.trim();
  let m;
  if ((m = /^([\d.]+)$/.exec(t))) return near(f, 1) ? v : fmt(+m[1] * f, 3);
  if ((m = /^([\d.]+)px$/.exec(t))) return fmt(+m[1] * sf * f, 2) + 'px';
  if ((m = /^([\d.]+)%$/.exec(t))) return near(f, 1) ? v : fmt(+m[1] * f, 1) + '%';
  return v;
}
function addLs(v, d) {
  if (near(d, 0)) return v;
  const t = v.trim();
  if (t === 'normal' || t === '0') return emStr(d);
  const m = /^(-?[\d.]+)em$/.exec(t);
  if (m) return emStr(+m[1] + d);
  return `calc(${t} + ${emStr(d)})`;
}
function adjWeight(v, d) {
  if (near(d, 0)) return v;
  return v.replace(/\b(\d{3,4})\b/g, (m, n) => String(Math.min(1000, Math.max(1, Math.round(+n + d)))));
}
function appendDecl(body, decl) {
  const trail = /\s*$/.exec(body)[0];
  const core = body.slice(0, body.length - trail.length);
  const sep = core.trim() === '' ? ' ' : core.trimEnd().endsWith(';') ? ' ' : '; ';
  return core + sep + decl + ';' + (trail || ' ');
}

export function transformCss(text, plan) {
  // pass 1: which role each selector belongs to (from blocks that name a family token)
  const roleBySel = new Map();
  for (const m of text.matchAll(RX_BLOCK)) {
    const fm = RX_FAMILY.exec(m[2]);
    if (!fm) continue;
    for (const sel of cleanSel(m[1]).split(',').map(x => x.trim()).filter(Boolean)) if (!roleBySel.has(sel)) roleBySel.set(sel, ROLE_OF[fm[1]]);
  }
  const L = plan.labels;
  const labelsOn = L.transform !== L.oldTransform || !near(L.ls, L.oldLs);
  return text.replace(RX_BLOCK, (whole, selRaw, body) => {
    const sel = cleanSel(selRaw);
    if (!sel || sel.startsWith('@') || SKIP_SEL.has(sel) || /(^|,\s*)(:root|body|html)(\s*,|$)/.test(sel)) return whole;
    if (!RX_HAS_TYPE.test(body)) return whole;
    const fm = RX_FAMILY.exec(body);
    const famRole = fm ? ROLE_OF[fm[1]] : null;
    const role = famRole || sel.split(',').map(x => roleBySel.get(x.trim())).find(Boolean) || 'main';
    const p = plan[role];
    // the block's own size (px), before the transform
    let oldPx = null;
    for (const m of body.matchAll(RX_DECL)) {
      if (m[1] === 'font-size') oldPx = pxOf(m[3]) ?? oldPx;
      else if (m[1] === 'font') { const s = RX_SHORT.exec(m[3]); if (s) oldPx = pxOf(s[2]) ?? oldPx; }
    }
    const isLabel = role === 'main' && labelsOn && oldPx != null && oldPx <= L.maxSize + 1e-9;
    const lsDelta = (p.ls - p.oldLs) + (isLabel ? L.ls - L.oldLs : 0);
    const wDelta = p.weight - p.oldWeight;
    let hasLs = false;
    let out = body.replace(RX_DECL, (m, prop, colon, val, imp) => {
      let nv = val;
      if (prop === 'font-size') nv = scaleSize(val, p);
      else if (prop === 'line-height') nv = scaleLh(val, p, oldPx);
      else if (prop === 'letter-spacing') { hasLs = true; nv = addLs(val, lsDelta); }
      else if (prop === 'font-weight') nv = adjWeight(val, wDelta);
      else if (prop === 'font') {
        const s = RX_SHORT.exec(val);
        if (!s) return m;
        const [, pre, size, slash, lh, gap, fam] = s;
        const px = pxOf(size);
        nv = adjWeight(pre, wDelta) + scaleSize(size, p) + (slash ? slash + scaleLh(lh, p, px) : '') + gap + fam;
      }
      return nv === val ? m : prop + colon + nv + imp;
    });
    if (!hasLs) {
      if (famRole && famRole !== 'main' && (!near(p.ls, p.oldLs) || !near(plan.main.ls, plan.main.oldLs))) out = appendDecl(out, `letter-spacing: ${emStr(p.ls - p.oldLs)}`);
      else if (isLabel && !near(L.ls, L.oldLs)) out = appendDecl(out, `letter-spacing: ${emStr(plan.main.ls + L.ls)}`);
    }
    if (famRole && famRole !== 'main' && p.features !== p.oldFeatures) out = appendDecl(out, `font-feature-settings: ${p.features}`);
    if (famRole === 'mono' && p.vs !== p.oldVs) out = appendDecl(out, `font-variation-settings: ${p.vs}`);
    if (isLabel && L.transform !== L.oldTransform) {
      out = appendDecl(out, L.transform === 'small-caps' ? 'font-variant-caps: all-small-caps' : `text-transform: ${L.transform}`);
    }
    return out === body ? whole : selRaw + '{' + out + '}';
  });
}

// ---------- import / export ----------
export function exportJson(s) {
  const role = (r, k) => {
    const o = {
      family: r.family, fallback: r.fallback, weight: r.weight, weights: r.weights, axes: r.axes,
      size: r.size, ratio: r.ratio, letterSpacing: r.letterSpacing, lineHeight: r.lineHeight, features: r.features,
    };
    if (k === 'main') o.labels = r.labels;
    return o;
  };
  return {
    version: 1,
    tool: 'PriceMonkey dev type panel',
    exported: new Date().toISOString(),
    units: { size: 'px', letterSpacing: 'em', lineHeight: 'unitless', ratio: 'modular scale ratio (sizes = size * (css px / old size) ^ (ln ratio / ln old ratio))' },
    roles: { main: role(s.main, 'main'), display: role(s.display, 'display'), mono: role(s.mono, 'mono') },
    googleFontsUrl: googleFontsUrl(s),
  };
}
const clampN = (v, lo, hi, dflt) => { const n = Number(v); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt; };
export function importJson(data, base) {
  if (typeof data === 'string') data = JSON.parse(data);
  if (!data || typeof data !== 'object' || !data.roles) throw new Error('not a type-panel export (no "roles")');
  if (data.version !== 1) throw new Error(`unsupported version ${data.version}`);
  const urlMeta = data.googleFontsUrl ? metaFromUrl(data.googleFontsUrl) : {};
  const out = clone(base);
  for (const k of ['main', 'display', 'mono']) {
    const r = data.roles[k];
    if (!r) continue;
    const o = out[k];
    if (typeof r.family === 'string' && r.family.trim()) {
      o.family = r.family.trim().replace(/["';{}<>]/g, '');
      if (!findFont(o.family) && urlMeta[o.family.toLowerCase()]) o.meta = urlMeta[o.family.toLowerCase()];
      else delete o.meta;
    }
    if (typeof r.fallback === 'string') o.fallback = r.fallback.replace(/[;{}<>]/g, '');
    o.weight = clampN(r.weight, 1, 1000, o.weight);
    if (Array.isArray(r.weights)) o.weights = r.weights.map(Number).filter(w => w >= 1 && w <= 1000);
    if (r.axes && typeof r.axes === 'object') o.axes = Object.fromEntries(Object.entries(r.axes).filter(([t, v]) => /^[A-Za-z0-9]{4}$/.test(t) && Number.isFinite(+v)).map(([t, v]) => [t, +v]));
    o.size = clampN(r.size, 6, 200, o.size);
    o.ratio = clampN(r.ratio, 1.01, 2, o.ratio);
    o.letterSpacing = clampN(r.letterSpacing, -0.2, 0.5, o.letterSpacing);
    o.lineHeight = clampN(r.lineHeight, 0.7, 3, o.lineHeight);
    if (typeof r.features === 'string') o.features = r.features.replace(/[;{}<>]/g, '').trim() || 'normal';
    if (k === 'main' && r.labels) {
      const t = ['none', 'uppercase', 'lowercase', 'capitalize', 'small-caps'].includes(r.labels.transform) ? r.labels.transform : 'none';
      o.labels = { transform: t, letterSpacing: clampN(r.labels.letterSpacing, -0.2, 0.5, 0), maxSize: clampN(r.labels.maxSize, 6, 40, o.labels.maxSize) };
    }
  }
  return out;
}

// =====================================================================================================
// ---------- browser panel (everything below only runs in a page) ----------
const LS_SET = 'pm-devtools-fonts.v1', LS_UI = 'pm-devtools-ui.v1';
const isLocal = () => typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1|\[::1\]|::1)$/.test(location.hostname);
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const escH = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let peek = false, BASE = null, S = null, UI = null, showA = false, panel = null, pill = null, started = false;
const sheetText = new Map();   // href -> original css text
let applied = false, raf = 0;

function metaOf(r) { return r.meta || findFont(r.family) || { axes: [], weights: [400], ital: false, style: 'custom' }; }
function sameAsBase(s) { return JSON.stringify(exportJson(s).roles) === JSON.stringify(exportJson(BASE).roles); }

async function loadSheets() {
  const links = [...document.querySelectorAll('link[rel="stylesheet"]')].filter(l => /\/web\/css\/[^/]+\.css/.test(l.getAttribute('href') || '') && !/devtools\.css/.test(l.href));
  await Promise.all(links.map(async l => {
    if (sheetText.has(l.href)) return;
    try { const r = await fetch(l.href, { cache: 'no-cache' }); if (r.ok) sheetText.set(l.href, await r.text()); } catch { /* offline */ }
  }));
  return links;
}
function clearPreview() {
  for (const k of Object.keys(rootVars(BASE))) document.documentElement.style.removeProperty(k);
  document.querySelectorAll('style[data-dt-for]').forEach(st => st.remove());
  document.querySelectorAll('link[data-dt-off]').forEach(l => { l.disabled = false; delete l.dataset.dtOff; });
  const fl = document.getElementById('dt-fonts'); if (fl) fl.remove();
  applied = false;
}
async function applyNow() {
  if (showA || sameAsBase(S)) { clearPreview(); updatePill(); return; }
  const url = googleFontsUrl(S);
  let fl = document.getElementById('dt-fonts');
  if (!fl) { fl = document.createElement('link'); fl.id = 'dt-fonts'; fl.rel = 'stylesheet'; document.head.appendChild(fl); }
  if (fl.getAttribute('href') !== url) fl.setAttribute('href', url);
  const vars = rootVars(S);
  for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v);
  const links = await loadSheets();
  const plan = makePlan(BASE, S);
  for (const l of links) {
    const src = sheetText.get(l.href);
    if (src == null) continue;
    const css = transformCss(src, plan);
    let st = document.querySelector(`style[data-dt-for="${CSS.escape(l.href)}"]`);
    if (css === src) { if (st) st.remove(); l.disabled = false; delete l.dataset.dtOff; continue; }
    if (!st) { st = document.createElement('style'); st.dataset.dtFor = l.href; l.after(st); }
    if (st.textContent !== css) st.textContent = css;
    l.disabled = true; l.dataset.dtOff = '1';
  }
  applied = true;
  updatePill();
}
function apply() { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { applyNow(); }); }
function save() { if (sameAsBase(S)) store.del(LS_SET); else store.set(LS_SET, exportJson(S)); }
function saveUi() { store.set(LS_UI, UI); }
function change() { save(); apply(); renderSpecimen(); renderStatus(); }

// font names in their own face: one css2 request per style group, only the glyphs of the names (&text=)
const previewLoaded = new Set();
function loadNamePreviews() {
  for (const st of Object.keys(STYLES)) {
    if (previewLoaded.has(st)) continue;
    previewLoaded.add(st);
    const fonts = CATALOG.filter(f => f.style === st);
    const text = [...new Set(fonts.map(f => f.family).join('').split(''))].join('') + 'Aa0123456789';
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.dataset.dtPreview = st;
    l.href = `https://fonts.googleapis.com/css2?${fonts.map(f => 'family=' + f.family.replace(/ /g, '+')).join('&')}&text=${encodeURIComponent(text)}&display=swap`;
    document.head.appendChild(l);
  }
}

// a family typed by hand: ask the Google Fonts CSS API which static weights exist (v1 API ignores missing ones),
// then (if axes were typed, e.g. "wdth 75..100, wght 100..900") check the css2 variable request works
async function probeFamily(name, axesText) {
  const fam = name.trim().replace(/\s+/g, ' ');
  const known = findFont(fam);
  if (known && !axesText) return { family: known.family, meta: null };
  const enc = fam.replace(/ /g, '+');
  const all = [100, 200, 300, 400, 500, 600, 700, 800, 900];
  const missing = () => new Error(`Google Fonts has no family "${fam}" (check the spelling on fonts.google.com, or you are offline)`);
  let r;
  try { r = await fetch(`https://fonts.googleapis.com/css?family=${encodeURIComponent(fam).replace(/%20/g, '+')}:${all.map(w => `${w},${w}i`).join(',')}`); }
  catch { throw missing(); }   // an unknown family answers 400 without CORS headers, so fetch() rejects
  if (!r.ok) throw missing();
  const css = await r.text();
  const weights = [...new Set([...css.matchAll(/font-weight:\s*(\d+)/g)].map(m => +m[1]))].sort((a, b) => a - b);
  const ital = /font-style:\s*italic/.test(css);
  const meta = { axes: [], weights: weights.length ? weights : [400], ital, style: 'custom' };
  // a variable wght axis? (css2 answers a weight range only for variable families)
  if (!axesText && meta.weights.length > 1) {
    const lo = meta.weights[0], hi = meta.weights[meta.weights.length - 1];
    try { if ((await fetch(`https://fonts.googleapis.com/css2?family=${enc}:wght@${lo}..${hi}`)).ok) meta.axes.push(['wght', lo, hi]); } catch { /* static */ }
  }
  if (axesText && axesText.trim()) {
    for (const m of axesText.matchAll(/([A-Za-z0-9]{4})\s*[:=]?\s*(-?[\d.]+)\s*\.\.\s*(-?[\d.]+)/g)) meta.axes.push([m[1], +m[2], +m[3]]);
    if (meta.axes.length) {
      const test = `https://fonts.googleapis.com/css2?family=${familyParam({ family: fam, weights: [], weight: 400 }, 'main', meta)}`;
      const t = await fetch(test);
      if (!t.ok) throw new Error(`"${fam}" exists but not with those axes (${axesText.trim()}); leave axes empty for the static weights`);
    }
  }
  return { family: fam, meta };
}

// ---------- panel DOM ----------
function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function slider(id, label, val, min, max, step, unit = '') {
  return `<div class="dt-row"><label for="${id}">${label}</label>
    <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}">
    <input type="number" class="dt-num" data-for="${id}" min="${min}" max="${max}" step="${step}" value="${val}"><span class="dt-unit">${unit}</span></div>`;
}

function mount() {
  if (panel) return;
  panel = el(`<aside id="pm-dt" class="pm-dt" role="dialog" aria-label="Dev type panel">
    <header class="dt-head" title="drag to move">
      <b>Type</b><span class="dt-sub">dev panel · localhost only</span>
      <div class="dt-ab" role="group" aria-label="Compare">
        <button type="button" data-ab="a" title="A: the fonts in the code now (hold Alt to peek)">A</button>
        <button type="button" data-ab="b" title="B: your settings">B</button>
      </div>
      <button type="button" class="dt-ico" data-act="collapse" aria-label="Collapse" title="Collapse">–</button>
      <button type="button" class="dt-ico" data-act="close" aria-label="Close" title="Close (Ctrl/Cmd+Shift+D)">×</button>
    </header>
    <div class="dt-body">
      <nav class="dt-tabs" role="tablist"></nav>
      <div class="dt-pane"></div>
      <div class="dt-spec" aria-label="Specimen"></div>
      <div class="dt-status"></div>
      <footer class="dt-foot">
        <div class="dt-btns">
          <button type="button" data-act="export">Export JSON</button>
          <button type="button" data-act="import">Import…</button>
          <button type="button" data-act="reset-role">Reset role</button>
          <button type="button" data-act="reset">Reset all</button>
        </div>
        <div class="dt-import" hidden>
          <textarea rows="4" placeholder="paste pricemonkey-fonts.json here"></textarea>
          <div class="dt-btns"><button type="button" data-act="import-paste">Apply pasted</button>
          <label class="dt-file">or a file <input type="file" accept="application/json,.json"></label></div>
        </div>
        <p class="dt-help">Export copies the JSON and downloads <code>pricemonkey-fonts.json</code>. To make it the site's type:
        <code>.venv/bin/python scripts/apply_fonts.py pricemonkey-fonts.json</code> (writes the Google Fonts link in
        index.html and the tokens + sizes in web/css; <code>--dry-run</code> to preview). Docs: docs/DEVTOOLS.md</p>
      </footer>
    </div>
  </aside>`);
  document.body.appendChild(panel);
  const head = panel.querySelector('.dt-head');
  // drag
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
  panel.querySelector('.dt-ab').addEventListener('pointerdown', e => { const b = e.target.closest('[data-ab]'); if (b) setAB(b.dataset.ab === 'a'); });
  renderAll();
  place();
}
function place() {
  if (!panel) return;
  panel.classList.toggle('collapsed', !!UI.collapsed);
  if (UI.x != null) { panel.style.left = Math.min(UI.x, innerWidth - 80) + 'px'; panel.style.top = Math.min(UI.y, innerHeight - 40) + 'px'; panel.style.right = 'auto'; }
}
function setAB(a) {
  showA = a;
  if (panel) panel.querySelectorAll('[data-ab]').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.ab === 'a') === a)));
  applyNow(); renderSpecimen();
}

function renderAll() { renderTabs(); renderPane(); renderSpecimen(); renderStatus(); setAB(showA); }
function renderTabs() {
  panel.querySelector('.dt-tabs').innerHTML = Object.entries(ROLES).map(([k, r]) =>
    `<button type="button" role="tab" data-role="${k}" aria-selected="${UI.role === k}">${r.label}</button>`).join('');
}
function fontList(role) {
  const cur = S[role].family.toLowerCase(), q = (UI.q || '').toLowerCase();
  const groups = ROLE_STYLES[role].map(st => {
    const items = CATALOG.filter(f => f.style === st && (!q || f.family.toLowerCase().includes(q)));
    if (!items.length) return '';
    return `<div class="dt-grp">${STYLES[st]}</div>` + items.map(f => {
      const v = f.axes.length ? f.axes.map(a => a[0]).join(' ') : f.weights.length + ' weights';
      const orig = f.family.toLowerCase() === BASE[role].family.toLowerCase() ? ' <i>now</i>' : '';
      return `<button type="button" class="dt-font${f.family.toLowerCase() === cur ? ' on' : ''}" data-font="${escH(f.family)}">
        <span style="font-family:'${escH(f.family)}', ${role === 'mono' ? 'monospace' : 'sans-serif'}">${escH(f.family)}</span><small>${v}${orig}</small></button>`;
    }).join('');
  }).join('');
  return groups || '<p class="dt-empty">no match: type the exact Google Fonts name below</p>';
}
function renderPane() {
  const role = UI.role, r = S[role], meta = metaOf(r);
  const wAxis = meta.axes.find(a => a[0] === 'wght');
  const wMin = wAxis ? wAxis[1] : Math.min(...meta.weights), wMax = wAxis ? wAxis[2] : Math.max(...meta.weights);
  const axes = meta.axes.filter(a => a[0] !== 'wght');
  const feats = parseFeatures(r.features);
  const ratioOpts = RATIOS.map(([v, n]) => `<option value="${v}"${near(v, r.ratio) ? ' selected' : ''}>${v} ${n}</option>`).join('');
  const custom = !findFont(r.family);
  const pane = panel.querySelector('.dt-pane');
  pane.innerHTML = `
    <div class="dt-pick">
      <input type="search" class="dt-q" placeholder="filter ${CATALOG.filter(f => ROLE_STYLES[role].includes(f.style)).length} fonts…" value="${escH(UI.q || '')}">
      <div class="dt-list">${fontList(role)}</div>
      <div class="dt-custom">
        <input type="text" class="dt-fam" placeholder="any Google Fonts family, e.g. Geologica" value="${custom ? escH(r.family) : ''}">
        <input type="text" class="dt-axes" placeholder="axes (optional) wght 100..900, wdth 75..100" value="${custom && r.meta ? escH(r.meta.axes.map(a => `${a[0]} ${a[1]}..${a[2]}`).join(', ')) : ''}">
        <button type="button" data-act="load-fam">Load</button>
      </div>
      <div class="dt-msg" aria-live="polite"></div>
    </div>
    <div class="dt-cur">${escH(r.family)} <small>${meta.axes.length ? 'variable: ' + meta.axes.map(a => `${a[0]} ${a[1]}–${a[2]}`).join(', ') : 'static: ' + meta.weights.join(' ')}</small></div>
    ${wAxis ? slider('dt-weight', 'weight', r.weight, wMin, wMax, 1)
      : `<div class="dt-row"><label for="dt-weight-s">weight</label><select id="dt-weight-s">${meta.weights.map(w => `<option${w === r.weight ? ' selected' : ''}>${w}</option>`).join('')}</select>
         <span class="dt-ws">${meta.weights.map(w => `<label><input type="checkbox" data-w="${w}"${(r.weights || []).includes(w) || w === r.weight ? ' checked' : ''}>${w}</label>`).join('')}</span></div>`}
    ${axes.map(([t, lo, hi]) => slider('dt-ax-' + t, `<abbr title="variation axis">${t}</abbr>`, r.axes[t] != null ? r.axes[t] : (t === 'opsz' ? Math.min(hi, Math.max(lo, r.size)) : t === 'wdth' ? Math.min(hi, 100) : lo), lo, hi, t === 'WONK' ? 1 : (hi - lo) > 20 ? 1 : 0.1)).join('')}
    ${axes.length ? `<div class="dt-row dt-hint"><span>axes left alone use the font's own default</span><button type="button" class="dt-link" data-act="clear-axes">clear axes</button></div>` : ''}
    ${slider('dt-size', role === 'display' ? 'headline px' : 'base px', r.size, role === 'display' ? 28 : 9, role === 'display' ? 110 : 22, 0.5, 'px')}
    <div class="dt-row"><label for="dt-ratio">ratio</label><input type="range" id="dt-ratio" min="1.05" max="1.62" step="0.001" value="${r.ratio}">
      <select class="dt-ratio-s">${ratioOpts}<option value=""${RATIOS.some(([v]) => near(v, r.ratio)) ? '' : ' selected'}>${fmt(r.ratio, 3)}</option></select></div>
    ${slider('dt-ls', 'tracking', r.letterSpacing, -0.06, 0.12, 0.001, 'em')}
    ${slider('dt-lh', 'line-height', r.lineHeight, 0.8, 2.2, 0.01)}
    <div class="dt-row dt-feat"><label>features</label><span class="dt-chips">${FEATURE_CHIPS.map(t => `<button type="button" class="dt-chip${feats[t] != null && feats[t] !== 0 ? ' on' : ''}${feats[t] === 0 ? ' off' : ''}" data-feat="${t}" title="${t}: click on → off → unset">${t}</button>`).join('')}</span></div>
    <div class="dt-row"><label for="dt-feats">raw</label><input type="text" id="dt-feats" class="dt-wide" value="${escH(r.features)}" spellcheck="false"></div>
    ${role === 'main' ? `
    <div class="dt-sep">small labels (main text at or under the size below)</div>
    <div class="dt-row"><label for="dt-lt">labels</label>
      <select id="dt-lt">${['none', 'uppercase', 'small-caps', 'lowercase', 'capitalize'].map(t => `<option${t === r.labels.transform ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
    ${slider('dt-lmax', 'label ≤', r.labels.maxSize, 9, 16, 0.5, 'px')}
    ${slider('dt-lls', 'label tracking', r.labels.letterSpacing, -0.02, 0.16, 0.001, 'em')}` : ''}`;
  if (UI.msg) { pane.querySelector('.dt-msg').textContent = UI.msg; UI.msg = ''; }
}
function specimenFont(r, role) {
  const vs = vsString(r.axes);
  return `font-family:'${escH(r.family)}', ${role === 'mono' ? 'monospace' : role === 'display' ? 'serif' : 'sans-serif'};font-weight:${r.weight};letter-spacing:${emStr(r.letterSpacing)};font-feature-settings:${escH(r.features)};font-variation-settings:${escH(vs)}`;
}
function renderSpecimen() {
  if (!panel) return;
  const s = showA ? BASE : S;
  const m = s.main, d = s.display, mo = s.mono, role = UI.role, r = s[role];
  const lt = m.labels.transform === 'small-caps' ? 'font-variant-caps:all-small-caps' : `text-transform:${m.labels.transform}`;
  const steps = [-2, -1, 0, 1, 2, 3].map(i => {
    const px = r.size * Math.pow(r.ratio, i);
    const shown = Math.min(px, role === 'display' ? 46 : 30);
    return `<div class="dt-step"><span class="dt-px">${fmt(px, 1)}</span><span style="${specimenFont(r, role)};font-size:${fmt(shown, 2)}px;line-height:${r.lineHeight}">${role === 'mono' ? '€1,249.00 0O1lI' : role === 'display' ? 'Every way to buy' : 'Ranked by what you pay'}</span></div>`;
  }).join('');
  panel.querySelector('.dt-spec').innerHTML = `
    <div class="dt-spec-page${showA ? ' is-a' : ''}">
      <div style="${specimenFont(d, 'display')};font-size:${fmt(Math.min(d.size * 0.4, 28), 2)}px;line-height:${d.lineHeight}">What do you want to <em>buy</em>?</div>
      <p style="${specimenFont(m, 'main')};font-size:${m.size}px;line-height:${m.lineHeight}">A used Fujifilm X100V, refurbished, ships from Berlin in 2 days. Returns 30 days, all in.</p>
      <div class="dt-spec-row">
        <span style="${specimenFont(m, 'main')};font-size:${Math.min(m.labels.maxSize, m.size * 0.8)}px;${lt};letter-spacing:${emStr(m.letterSpacing + m.labels.letterSpacing)};color:var(--dt-ink-2)">best price · 14 shops</span>
        <span style="${specimenFont(mo, 'mono')};font-size:${mo.size}px">€1,249.00</span>
        <span style="${specimenFont(d, 'display')};font-size:${fmt(Math.min(d.size * 0.42, 30), 2)}px;font-weight:${d.weight + 100}">€1,099</span>
      </div>
      <div class="dt-tag">${showA ? 'A · in the code now' : 'B · your settings'}</div>
    </div>
    <div class="dt-steps" title="${ROLES[role].label}: size × ratio^n">${steps}</div>`;
}
function renderStatus() {
  if (!panel) return;
  const diff = [];
  for (const k of ['main', 'display', 'mono']) {
    const a = exportJson(BASE).roles[k], b = exportJson(S).roles[k];
    const ch = Object.keys(b).filter(f => JSON.stringify(a[f]) !== JSON.stringify(b[f]) && f !== 'weights');
    if (ch.length) diff.push(`${k}: ${ch.join(', ')}`);
  }
  panel.querySelector('.dt-status').textContent = diff.length ? 'changed: ' + diff.join(' · ') : 'matches the code (nothing to export yet)';
}
function updatePill() {
  const custom = !sameAsBase(S) && !showA;
  if (custom && !panel) {
    if (!pill) {
      pill = el('<button type="button" class="pm-dt-pill" title="Custom fonts from the dev type panel are applied (localhost only). Click to open.">Aa custom type</button>');
      pill.addEventListener('click', () => toggle(true));
      document.body.appendChild(pill);
    }
  } else if (pill) { pill.remove(); pill = null; }
}

// ---------- events ----------
const roleNow = () => S[UI.role];
function setFamily(role, family, meta) {
  const r = S[role];
  r.family = family;
  if (meta) r.meta = meta; else delete r.meta;
  const m = metaOf(r);
  const wAxis = m.axes.find(a => a[0] === 'wght');
  if (wAxis) r.weight = Math.min(wAxis[2], Math.max(wAxis[1], r.weight));
  else if (!m.weights.includes(r.weight)) r.weight = m.weights.reduce((a, b) => (Math.abs(b - r.weight) < Math.abs(a - r.weight) ? b : a));
  r.weights = [...new Set([r.weight, 400, 500])].filter(w => m.weights.includes(w)).sort((a, b) => a - b);
  // keep only axes the new family has; back on the original family, its original axis values come back
  if (family.toLowerCase() === BASE[role].family.toLowerCase()) r.axes = clone(BASE[role].axes);
  else r.axes = Object.fromEntries(Object.entries(r.axes).flatMap(([t, v]) => {
    const a = m.axes.find(x => x[0] === t);
    return a ? [[t, Math.min(a[2], Math.max(a[1], v))]] : [];
  }));
  if (role === 'main') r.fallback = BASE.main.fallback;
  if (role === 'display') r.fallback = BASE.display.fallback;
  if (role === 'mono') r.fallback = BASE.mono.fallback;
}
async function onClick(e) {
  const t = e.target.closest('button');
  if (!t) return;
  if (t.dataset.role) { UI.role = t.dataset.role; UI.q = ''; saveUi(); renderTabs(); renderPane(); renderSpecimen(); return; }
  if (t.dataset.font) { setFamily(UI.role, t.dataset.font, null); renderPane(); change(); return; }
  if (t.dataset.feat) {
    const r = roleNow(), f = parseFeatures(r.features), k = t.dataset.feat;
    if (f[k] == null) f[k] = 1; else if (f[k] !== 0) f[k] = 0; else delete f[k];
    r.features = featuresString(f); renderPane(); change(); return;
  }
  const act = t.dataset.act;
  if (act === 'close') toggle(false);
  else if (act === 'collapse') { UI.collapsed = !UI.collapsed; saveUi(); place(); }
  else if (act === 'clear-axes') { roleNow().axes = {}; renderPane(); change(); }
  else if (act === 'reset-role') { S[UI.role] = clone(BASE[UI.role]); renderPane(); change(); }
  else if (act === 'reset') { S = clone(BASE); renderPane(); change(); }
  else if (act === 'export') doExport();
  else if (act === 'import') { const box = panel.querySelector('.dt-import'); box.hidden = !box.hidden; }
  else if (act === 'import-paste') doImport(panel.querySelector('.dt-import textarea').value);
  else if (act === 'load-fam') {
    const name = panel.querySelector('.dt-fam').value, axes = panel.querySelector('.dt-axes').value;
    const msg = panel.querySelector('.dt-msg');
    if (!name.trim()) { msg.textContent = 'type a family name first'; return; }
    msg.textContent = 'asking Google Fonts…';
    try {
      const { family, meta } = await probeFamily(name, axes);
      setFamily(UI.role, family, meta);
      UI.msg = `loaded ${family}`;
      renderPane(); change();
    } catch (err) { msg.textContent = err.message; }
  }
}
function numFrom(e) { return parseFloat(e.target.value); }
function onInput(e) {
  const t = e.target, r = roleNow();
  if (t.classList.contains('dt-q')) { UI.q = t.value; panel.querySelector('.dt-list').innerHTML = fontList(UI.role); return; }
  let id = t.id;
  if (t.classList.contains('dt-num') && t.dataset.for) { id = t.dataset.for; const rg = panel.querySelector('#' + id); if (rg) rg.value = t.value; }
  else if (t.type === 'range') { const n = panel.querySelector(`.dt-num[data-for="${id}"]`); if (n) n.value = t.value; }
  const v = numFrom(e);
  if (!Number.isFinite(v) && id !== 'dt-feats') return;
  if (id === 'dt-weight') r.weight = Math.round(v);
  else if (id === 'dt-size') r.size = v;
  else if (id === 'dt-ratio') { r.ratio = v; const s = panel.querySelector('.dt-ratio-s'); const hit = RATIOS.find(([x]) => near(x, v)); s.value = hit ? String(hit[0]) : ''; if (!hit) s.options[s.options.length - 1].textContent = fmt(v, 3); }
  else if (id === 'dt-ls') r.letterSpacing = v;
  else if (id === 'dt-lh') r.lineHeight = v;
  else if (id === 'dt-lls') r.labels.letterSpacing = v;
  else if (id === 'dt-lmax') r.labels.maxSize = v;
  else if (id && id.startsWith('dt-ax-')) r.axes[id.slice(6)] = v;
  else return;
  change();
}
function onChange(e) {
  const t = e.target, r = roleNow();
  if (t.id === 'dt-weight-s') { r.weight = +t.value; if (!r.weights.includes(r.weight)) r.weights.push(r.weight); renderPane(); change(); }
  else if (t.dataset.w) { const w = +t.dataset.w; r.weights = t.checked ? [...new Set([...r.weights, w])].sort((a, b) => a - b) : r.weights.filter(x => x !== w); change(); }
  else if (t.classList.contains('dt-ratio-s') && t.value) { r.ratio = +t.value; panel.querySelector('#dt-ratio').value = t.value; change(); }
  else if (t.id === 'dt-feats') { r.features = t.value.replace(/[;{}<>]/g, '').trim() || 'normal'; renderPane(); change(); }
  else if (t.id === 'dt-lt') { r.labels.transform = t.value; change(); }
  else if (t.type === 'file' && t.files && t.files[0]) t.files[0].text().then(doImport);
}
function doExport() {
  const data = exportJson(S);
  const text = JSON.stringify(data, null, 2) + '\n';
  const msg = panel.querySelector('.dt-status');
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject(new Error('no clipboard')))
    .then(() => { msg.textContent = 'copied to the clipboard and downloaded pricemonkey-fonts.json'; })
    .catch(() => { msg.textContent = 'downloaded pricemonkey-fonts.json (clipboard not allowed here)'; });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  a.download = 'pricemonkey-fonts.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function doImport(text) {
  const msg = panel.querySelector('.dt-status');
  try { S = importJson(text, BASE); panel.querySelector('.dt-import').hidden = true; renderAll(); change(); msg.textContent = 'imported'; }
  catch (err) { msg.textContent = 'import failed: ' + err.message; }
}

function toggle(force) {
  const open = force != null ? force : !panel;
  UI.open = open; saveUi();
  if (open) { if (pill) { pill.remove(); pill = null; } mount(); loadNamePreviews(); }
  else if (panel) { panel.remove(); panel = null; if (showA) setAB(false); updatePill(); }
}

export function init() {
  if (started || !isLocal()) return;
  started = true;
  const css = document.createElement('link');
  css.rel = 'stylesheet'; css.href = '/web/css/devtools.css';
  document.head.appendChild(css);
  const cs = getComputedStyle(document.documentElement);
  BASE = baselineFrom(n => cs.getPropertyValue(n));
  // families applied earlier by apply_fonts.py that are not in the catalog: read their axes from the page's own link
  const gl = document.querySelector('link[href^="https://fonts.googleapis.com/css2"]:not(#dt-fonts):not([data-dt-preview])');
  const linkMeta = gl ? metaFromUrl(gl.href) : {};
  for (const k of ['main', 'display', 'mono']) {
    const m = !findFont(BASE[k].family) && linkMeta[BASE[k].family.toLowerCase()];
    if (m) { BASE[k].meta = m; BASE[k].weights = BASE[k].weights.filter(w => m.weights.includes(w) || m.axes.length); }
  }
  UI = Object.assign({ open: false, role: 'main', collapsed: false, x: null, y: null, q: '' }, store.get(LS_UI) || {});
  const saved = store.get(LS_SET);
  S = clone(BASE);
  if (saved) { try { S = importJson(saved, BASE); } catch (e) { console.warn('[devtools] saved type settings ignored:', e.message); } }
  const params = new URLSearchParams(location.search);
  if (params.get('dev') === '0') UI.open = false;
  addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'D' || e.key === 'd')) { e.preventDefault(); toggle(); }
    else if (panel && e.key === 'Alt' && !showA && !e.repeat) { peek = true; setAB(true); }
  });
  addEventListener('keyup', e => { if (peek && e.key === 'Alt') { peek = false; setAB(false); } });
  if (!sameAsBase(S)) apply();
  if (params.get('dev') === '1' || UI.open) toggle(true); else updatePill();
  window.pmDevtools = { get settings() { return S; }, base: () => BASE, toggle, exportJson: () => exportJson(S), importJson: t => doImport(typeof t === 'string' ? t : JSON.stringify(t)) };
}
