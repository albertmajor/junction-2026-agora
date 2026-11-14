// Judges' round (docs/JUDGE_FEEDBACK.md F5-F7) on the recorded hunts, with node (no DOM): the robust price
// domain of the line, "not this" (out of the ranking, re-pick, put back), and the shop's own currency.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
globalThis.fetch = async () => { throw new Error('offline test'); };
globalThis.matchMedia = globalThis.matchMedia || (() => ({ matches: false, addEventListener() {} }));
const core = await import('../../agora/web/js/core.js');
const stream = await import('../../agora/web/js/stream.js');
const ledger = await import('../../agora/web/js/ledger.js');
const { robustBounds } = await import('../../agora/web/js/line.js');
const { S } = core;

const feed = slug => {
  const events = readFileSync(new URL(`../fixtures/live_${slug}.jsonl`, import.meta.url), 'utf8')
    .split('\n').filter(Boolean).map(l => JSON.parse(l));
  stream._test.begin(slug.replace(/-/g, ' '), { live: false });
  for (const ev of events) stream._test.feed(ev);
};

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('robust domain: one €4,900 outlier is pinned, a normal spread is not', () => {
  const sony = [633, 949, 979, 1009, 1196, 1231, 1265, 1265, 1265, 1387, 1399, 1448];
  assert.equal(robustBounds(sony), null, 'a normal spread keeps raw min/max');
  const b = robustBounds(sony.concat(4900));
  assert.ok(b && b.hi < 4900 && b.hi > 1448, JSON.stringify(b));
  const c = robustBounds(sony.concat(12));
  assert.ok(c && c.lo > 12 && c.lo < 633, JSON.stringify(c));
  assert.equal(robustBounds([10, 4000, 20, 30, 5000]), null, 'fewer than 6 prices: nothing pinned');
  // more than a quarter outside the fences = the prices are just spread: nothing pinned
  assert.equal(robustBounds([100, 100, 100, 100, 100, 100, 5000, 6000, 7000]), null);
});

test('"not this": out of the ranking, the pick moves, it waits in not counted, and comes back', () => {
  feed('sony-a7-iii-body');
  const n = S.offers.size;
  const pick = core.pickUrl();
  assert.ok(pick);
  const removed = [];
  const off = core.bus.addEventListener('offer-removed', e => removed.push(e.detail.url));
  void off;
  assert.ok(ledger.notThis(pick));
  assert.equal(S.offers.size, n - 1);
  assert.ok(!S.offers.has(pick));
  assert.notEqual(core.pickUrl(), pick, 'a new pick');
  assert.equal(S.leader, core.pickUrl());
  assert.deepEqual(removed, [pick]);
  const g = ledger.groups();
  assert.ok(g.risky.some(it => it.url === pick && it.userOut), 'shown in not counted');
  assert.ok(!g.main.some(it => it.url === pick));
  assert.ok(ledger.isDismissed(pick));
  assert.ok(ledger.putBack(pick));
  assert.equal(S.offers.size, n);
  assert.equal(core.pickUrl(), pick, 'put back: it is the pick again');
  assert.ok(!ledger.groups().risky.some(it => it.url === pick));
});

test('original currency: the shop price and the rate our conversion used, never for euros', () => {
  feed('sony-a7-iii-body');
  const usd = [...S.offers.values()].find(it => it.offer.currency === 'USD' && it.offer.price === 699.95);
  const f = ledger.origPrice(usd);
  assert.equal(f.orig, '$699.95');
  assert.equal(f.eur, '€633.32');
  assert.match(f.rate, /^1 USD = €0\.90\d$/);
  const eurIt = [...S.offers.values()].find(it => it.offer.currency === 'EUR');
  assert.equal(ledger.origPrice(eurIt), null);
  assert.equal(ledger.origPrice({ offer: { currency: 'USD', price: null, price_eur: 10 } }), null);
  const sek = ledger.origPrice({ offer: { currency: 'SEK', price: 1700, price_eur: 153.05 } });
  assert.equal(sek.orig.replace(/\s/g, ' '), 'SEK 1,700');
  assert.match(sek.rate, /^€1 = 11\.\d+ SEK$/);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack || e); }
}
process.exit(failed ? 1 : 0);
