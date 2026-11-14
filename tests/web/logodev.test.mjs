// Dev logo panel (agora/web/js/logodev.js), checked with node by tests/test_logodev.py.
// Mode 1 (no args): unit cases. Mode 2 (`vars <export.json>`): prints the tokens the panel would set for that export
// against today's base.css, so the python test can check scripts/apply_logo.py writes the same values.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const L = await import('../../agora/web/js/logodev.js');

const baseCss = fs.readFileSync(new URL('../../agora/web/css/base.css', import.meta.url), 'utf8');
const BASE = L.baselineFrom(baseCss);

if (process.argv[2] === 'vars') {
  process.stdout.write(JSON.stringify(L.toVars(L.importJson(fs.readFileSync(process.argv[3], 'utf8'), BASE))));
  process.exit(0);
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('baseline = the logo as it is in base.css (40px mark, 8px gap, 26.31px wordmark, x-height centring)', () => {
  assert.equal(BASE.markWidth, 40); assert.equal(BASE.gap, 8); assert.equal(BASE.size, 26.31);
  assert.equal(BASE.weight, 400); assert.equal(BASE.hoverWeight, 500); assert.equal(BASE.tracking, -0.007);
  assert.equal(BASE.case, 'lowercase'); assert.equal(BASE.priceItalic, true); assert.equal(BASE.monkeyItalic, true);
  assert.equal(BASE.center, L.CENTERS.x); assert.equal(BASE.nudge, 0); assert.equal(BASE.nudgeUnit, 'px');
  assert.equal(BASE.wiggle, true); assert.equal(BASE.hoverTilt, -7); assert.equal(BASE.tilt, 0);
  assert.deepEqual(BASE.colors, { light: { price: 'var(--ink)', monkey: '#4E3818' }, dark: { price: 'var(--ink)', monkey: '#D9B98C' } });
  assert.equal(BASE.footerWidth, 19);
});

test('the baseline round-trips to exactly the tokens written in base.css', () => {
  const t = L.parseTokens(baseCss).light;
  for (const [k, v] of Object.entries(L.toVars(BASE))) assert.equal(v, t[k], k);
  assert.deepEqual(Object.keys(L.toVars(BASE)).sort(), [...L.VARS].sort());
});

test('export -> import is lossless', () => {
  const s = L.clone(BASE);
  Object.assign(s, { markWidth: 46, gap: 10.5, size: 30, weight: 520, tracking: 0.012, case: 'none', monkeyItalic: false,
    center: L.CENTERS.cap, nudge: -0.04, nudgeUnit: 'em', tilt: -3, wiggle: false, footerWidth: 22, footerNudge: 1 });
  s.colors.dark.price = '#f0e9dd';
  const back = L.importJson(JSON.stringify(L.exportJson(s)), BASE);
  assert.deepEqual(L.toVars(back), L.toVars(s));
  assert.equal(L.toVars(s)['--logo-hover-tilt'], '0deg');   // wiggle off
  assert.equal(L.toVars(s)['--logo-nudge'], '-0.04em');
});

test('import clamps numbers, ignores junk and keeps the base for anything missing', () => {
  const s = L.importJson({ logo: { size: 500, weight: 'heavy', gap: null, case: 'shouty', colors: { light: { monkey: 'red; }' }, dark: { monkey: '#abc' } } } }, BASE);
  assert.equal(s.size, 72); assert.equal(s.weight, 400); assert.equal(s.gap, 8); assert.equal(s.case, 'lowercase');
  assert.equal(s.colors.light.monkey, '#4E3818'); assert.equal(s.colors.dark.monkey, '#abc');
  assert.throws(() => L.importJson({ roles: {} }, BASE), /no "logo"/);
});

test('fmt: at most 4 decimals, no -0', () => {
  assert.equal(L.fmt(26.31), '26.31'); assert.equal(L.fmt(40), '40'); assert.equal(L.fmt(-0.00001), '0');
  assert.equal(L.fmt(0.23251), '0.2325'); assert.equal(L.fmt(-7), '-7');
});

test('resolveColor follows var() through the theme tokens', () => {
  const T = L.parseTokens(baseCss);
  assert.equal(L.resolveColor('var(--ink)', T.light), '#1c1b18');
  assert.equal(L.resolveColor('var(--ink)', T.dark), '#eeeae1');
  assert.equal(L.resolveColor('#abc', T.light), '#aabbcc');
});

test('the logo rules read only the tokens (the preview = what apply_logo.py writes)', () => {
  const rule = sel => (new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}').exec(baseCss) || [])[1] || '';
  assert.match(rule('.logo-mark'), /vertical-align: calc\(var\(--logo-center\) - var\(--logo-mark-w\) \* 0\.425 \+ var\(--logo-nudge\)\)/);
  assert.match(rule('.logo .brand'), /letter-spacing: var\(--logo-tracking\)/);
  assert.match(rule('.rule-mark'), /vertical-align: middle/);
  for (const v of L.VARS) assert.ok(baseCss.includes(`var(${v})`) || ['--logo-price-light', '--logo-monkey-light', '--logo-price-dark', '--logo-monkey-dark'].includes(v), v);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); } catch (e) { failed++; console.log('FAIL', name, '\n', e.message); }
}
process.exit(failed ? 1 : 0);
