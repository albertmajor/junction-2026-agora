// THE LINE's zoom (agora/web/js/line.js): the default fit leaves far outliers out, the price tag's drag curve
// keeps the tag under the finger while the axis follows it, tick steps stay readable. Pure helpers only
// (no DOM). Run by tests/test_web_line_zoom.py with node.
import assert from 'node:assert/strict';
globalThis.fetch = async () => { throw new Error('offline test'); };
const { _test: Z } = await import('../../agora/web/js/line.js');

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('the default fit drops a far outlier, keeps a spread market whole', () => {
  // the owner's hunt: hundreds of offers between €0 and €100, one at €1,500
  const crowd = Array.from({ length: 200 }, (_, i) => 5 + (i % 95));
  const fit = Z.robustVals(crowd.concat([1500]));
  assert.ok(!fit.includes(1500), 'the €1,500 outlier waits in the "+N dearer" stack');
  assert.ok(Math.max(...fit) < 140, `the fit ends near the cluster, not at ${Math.max(...fit)}`);
  // a market that is simply spread out (cameras €800-€1,800) keeps every offer
  const spread = [825, 900, 980, 1029, 1060, 1100, 1200, 1250, 1300, 1450, 1500, 1513, 1600, 1650, 1700];
  assert.equal(Z.robustVals(spread).length, spread.length);
  // a handful of offers: nothing to protect, nothing dropped
  assert.equal(Z.robustVals([10, 12, 15, 900]).length, 4);
});

test('tick steps are 1, 2, 2.5 or 5 × 10^n and never crowd their labels', () => {
  for (const [lo, hi, px] of [[0, 46, 1080], [0, 224, 1080], [0, 1828, 1080], [780, 1900, 1080], [0, 13, 600], [0, 6500, 300]]) {
    const s = Z.tickStep(lo, hi, px);
    const m = s / Math.pow(10, Math.floor(Math.log10(s) + 1e-9));
    assert.ok([1, 2, 2.5, 5].some(k => Math.abs(m - k) < 1e-9), `step ${s} for ${lo}-${hi}`);
    const per = s / (hi - lo) * px;
    assert.ok(per >= 64, `${s} gives ${per.toFixed(0)} px per tick for ${lo}-${hi} on ${px} px`);
    assert.ok((hi - lo) / s <= 14, `not too many ticks: ${((hi - lo) / s).toFixed(1)}`);
  }
});

test('mid-drag the tag stays under the finger: the drag curve inverts exactly and is monotone', () => {
  // the tag starts at €1,570 on a €0-€1,700 axis (the owner's screenshot)
  const D = Z.dragRef(1570, { d0: 0, d1: 1700 }, [0, 1700], [0, 1700]);
  assert.ok(Math.abs(Z.dragHi(D, 1570) - 1700) < 1e-6, 'no jump when the drag begins');
  let last = -Infinity;
  for (let f = -0.1; f <= 1.05; f += 0.01) {
    const v = Z.dragEur(D, f);
    assert.ok(v > last - 1e-9, `monotone at f=${f.toFixed(2)}`);
    last = v;
    const x = (v - D.lo) / (Z.dragHi(D, v) - D.lo);
    assert.ok(Math.abs(x - f) < 1e-6, `the tag drawn at ${x} for a finger at ${f}`);
  }
  // dragging left zooms in: at €100 the axis ends far under €1,700 but still past the tag
  const hi100 = Z.dragHi(D, 100);
  assert.ok(hi100 < 400 && hi100 > 100 * Z.TAG_HEAD, `axis end at €100: ${hi100}`);
  // dragging right zooms out, within a cap
  assert.ok(Z.dragHi(D, 3000) > 1700 && Z.dragHi(D, 1e7) <= D.cap + 1e-9);
});

test('a zoomed domain is exact and its ticks sit inside it', () => {
  const sc = Z.domScale(12.5, 61.3);
  assert.equal(sc.d0, 12.5); assert.equal(sc.d1, 61.3);
  assert.ok(sc.ticks.length >= 2 && sc.ticks.every(t => t >= 12.5 - 1e-9 && t <= 61.3 + 1e-9));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n     ', e.message); }
}
if (failed) process.exit(1);
