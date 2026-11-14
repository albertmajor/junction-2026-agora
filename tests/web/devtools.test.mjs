// Dev type panel (agora/web/js/devtools.js), checked with node by tests/test_devtools_fonts.py.
// Mode 1 (no args): unit cases. Mode 2 (`transform <settings.json> <css...>`): prints {file: transformed css} as JSON
// so the python test can check scripts/apply_fonts.py produces byte-identical CSS.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const dt = await import('../../agora/web/js/devtools.js');

const baseCss = fs.readFileSync(new URL('../../agora/web/css/base.css', import.meta.url), 'utf8');
const rootBlock = /:root\s*\{([^}]*)\}/.exec(baseCss)[1];
const tokens = Object.fromEntries([...rootBlock.matchAll(/(--[\w-]+)\s*:\s*([^;]*);/g)].map(m => [m[1], m[2].trim()]));
const BASE = dt.baselineFrom(n => tokens[n]);

if (process.argv[2] === 'transform') {
  const s = dt.importJson(fs.readFileSync(process.argv[3], 'utf8'), BASE);
  const plan = dt.makePlan(BASE, s);
  const out = {};
  for (const f of process.argv.slice(4)) out[f] = dt.transformCss(fs.readFileSync(f, 'utf8'), plan);
  out.__vars = dt.rootVars(s);
  out.__url = dt.googleFontsUrl(s);
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('baseline is read from the base.css tokens', () => {
  assert.equal(BASE.main.family, 'Instrument Sans');
  assert.equal(BASE.display.family, 'Fraunces');
  assert.equal(BASE.mono.family, 'IBM Plex Mono');
  assert.equal(BASE.main.size, 15); assert.equal(BASE.display.size, 64); assert.equal(BASE.mono.size, 12);
  assert.equal(BASE.display.letterSpacing, -0.02);
  assert.deepEqual(BASE.display.axes, { opsz: 96, SOFT: 50, WONK: 0 });
  assert.equal(BASE.main.features, '"tnum" 1, "ss01" 1');
});

test('the default settings change no stylesheet', () => {
  const plan = dt.makePlan(BASE, BASE);
  for (const f of fs.readdirSync(new URL('../../agora/web/css/', import.meta.url))) {
    const t = fs.readFileSync(new URL('../../agora/web/css/' + f, import.meta.url), 'utf8');
    assert.equal(dt.transformCss(t, plan), t, f);
  }
});

test('the baseline URL loads the three current families from fonts.googleapis.com', () => {
  const u = dt.googleFontsUrl(BASE);
  assert.ok(u.startsWith('https://fonts.googleapis.com/css2?'));
  assert.ok(u.includes('family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,100..900,0..100,0..1;1,'));
  assert.ok(u.includes('family=Instrument+Sans:ital,wdth,wght@0,75..100,400..700;1,75..100,400..700'));
  assert.ok(u.includes('family=IBM+Plex+Mono:wght@400;500'));
});

test('sizes follow the role scale, weights/tracking shift, display picks up its own tracking', () => {
  const s = dt.clone(BASE);
  s.main.size = 16; s.main.weight = 450; s.main.letterSpacing = 0.01;
  s.display.size = 72; s.display.ratio = 1.25; s.display.letterSpacing = -0.03;
  const css = `.a { font: 500 13px/18px var(--sans); }\n.b { font: 400 32px/1.1 var(--serif); letter-spacing: -.01em; }\n` +
    `.c { font-size: 15px; }\n@media (max-width: 640px) { .b { font-size: 24px; } }\n.d { font: 400 20px/1 var(--serif); }`;
  const out = dt.transformCss(css, dt.makePlan(BASE, s));
  assert.ok(out.includes('.a { font: 550 13.87px/19.2px var(--sans); }'), out);
  assert.ok(out.includes('.b { font: 400 36px/1.1 var(--serif); letter-spacing: -0.02em; }'), out);
  assert.ok(out.includes('.c { font-size: 16px; }'), out);
  assert.ok(out.includes('.b { font-size: 27px; }'), out);   // media rule: role found from the selector
  assert.ok(out.includes('.d { font: 400 22.5px/1 var(--serif); letter-spacing: -0.01em; }'), out);
});

test('ratio changes the contrast around the base size', () => {
  const s = dt.clone(BASE);
  s.main.ratio = 1.5;
  const out = dt.transformCss('.x { font-size: 12px; } .y { font-size: 15px; } .z { font-size: 20px; }', dt.makePlan(BASE, s));
  const [x, y, z] = [...out.matchAll(/([\d.]+)px/g)].map(m => +m[1]);
  assert.ok(x < 12 && y === 15 && z > 20, out);
});

test('labels: small main text gets the transform and label tracking', () => {
  const s = dt.clone(BASE);
  s.main.labels = { transform: 'uppercase', letterSpacing: 0.06, maxSize: 12 };
  const out = dt.transformCss('.l { font: 400 11px/1 var(--sans); } .big { font-size: 15px; } .h { font: 400 11px/1 var(--serif); }', dt.makePlan(BASE, s));
  assert.ok(out.includes('.l { font: 400 11px/1 var(--sans); letter-spacing: 0.06em; text-transform: uppercase; }'), out);
  assert.ok(out.includes('.big { font-size: 15px; }') && out.includes('.h { font: 400 11px/1 var(--serif); }'), out);
});

test('export / import round trip, custom family meta survives through googleFontsUrl', () => {
  const s = dt.clone(BASE);
  s.main.family = 'Geologica'; s.main.meta = { axes: [['wght', 100, 900], ['slnt', -12, 0]], weights: [400], ital: false };
  s.main.axes = { slnt: -6 };
  const json = JSON.parse(JSON.stringify(dt.exportJson(s)));
  assert.equal(json.version, 1);
  assert.deepEqual(Object.keys(json.roles), ['main', 'display', 'mono']);
  for (const k of ['family', 'weights', 'axes', 'size', 'ratio', 'letterSpacing', 'lineHeight', 'features']) assert.ok(k in json.roles.main, k);
  assert.ok(json.googleFontsUrl.includes('family=Geologica:slnt,wght@-12..0,100..900'), json.googleFontsUrl);
  const back = dt.importJson(json, BASE);
  assert.equal(back.main.family, 'Geologica');
  assert.deepEqual(back.main.meta.axes, [['slnt', -12, 0], ['wght', 100, 900]]);
  assert.equal(dt.googleFontsUrl(back), json.googleFontsUrl);
  assert.throws(() => dt.importJson({ version: 2, roles: {} }, BASE));
  assert.throws(() => dt.importJson({ nope: 1 }, BASE));
});

test('import sanitises values that would break out of a declaration', () => {
  const s = dt.importJson({ version: 1, roles: { main: { family: 'Inter"; } body { x', features: '"ss01" 1; } *{', size: 9999 } } }, BASE);
  assert.ok(!/[";{}]/.test(s.main.family));
  assert.ok(!/[;{}]/.test(s.main.features));
  assert.equal(s.main.size, 200);
});

test('static families load only the chosen weights; mono never asks for italics', () => {
  const s = dt.clone(BASE);
  s.main.family = 'Poppins'; s.main.weight = 400; s.main.weights = [400, 600];
  s.mono.family = 'Space Mono'; s.mono.weights = [400, 700];
  const u = dt.googleFontsUrl(s);
  assert.ok(u.includes('family=Poppins:ital,wght@0,400;0,600;1,400;1,600'), u);
  assert.ok(u.includes('family=Space+Mono:wght@400;700'), u);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok  ', name); } catch (e) { failed++; console.log('FAIL', name, '\n', e.message); }
}
if (failed) process.exit(1);
