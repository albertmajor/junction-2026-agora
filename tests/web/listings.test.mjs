// UI round B: all listings, the market line and the Context.dev summary, on the recorded city-bike hunt
// (322 listings, `scope` + `market`). Run by tests/test_web_listings.py with node (no DOM: store + pure functions).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
globalThis.fetch = async () => { throw new Error('offline test'); };
const core = await import('../../agora/web/js/core.js');
const stream = await import('../../agora/web/js/stream.js');
const ledger = await import('../../agora/web/js/ledger.js');
const market = await import('../../agora/web/js/market.js');
const livelog = await import('../../agora/web/js/livelog.js');
const { S } = core;

const events = readFileSync(new URL('../fixtures/live_city-bike-with-basket.jsonl', import.meta.url), 'utf8')
  .split('\n').filter(Boolean).map(l => JSON.parse(l));
stream._test.begin('city bike with basket', { live: false });
for (const ev of events) stream._test.feed(ev);

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('scope and market events land in the store', () => {
  assert.equal(S.scope.scope, 'home');
  assert.ok(S.scope.bulky);
  assert.equal(S.market.total, 19405);
  assert.equal(S.market.sources.length, 4);
});

test('the market line: size, and the bulky scope reason in plain words', () => {
  assert.equal(market.sizeText(), '≈19,405 listings on 4 marketplaces');
  const t = market.scopeText();
  assert.ok(t.startsWith('Bulky item: searched near you in Finland first'), t);
  assert.ok(/€60–120/.test(t));
  assert.equal(market.scopeText({ reason: 'small enough to ship', bulky: false }), '');
});

test('every listing is in exactly one group; set-aside ones at the bottom with a reason', () => {
  const g = ledger.groups();
  const n = g.main.length + g.eu.length + g.risky.length + g.costing.length;
  assert.equal(n, S.offers.size);
  assert.ok(n > 300);
  assert.ok(g.risky.length > 100, 'the 147 not-costed listings are shown, set aside');
  for (const it of g.risky) assert.ok(core.riskWhy(it).length > 3);
  // the extra EU marketplaces (blocket, kleinanzeigen, marktplaats) are their own group, never the main list
  const ex = core.extraDomains();
  assert.ok(ex.has('blocket.se') && ex.has('kleinanzeigen.de') && !ex.has('tori.fi'));
  assert.ok(g.eu.length > 20 && g.eu.every(it => core.isExtra(it)));
  assert.ok(g.main.every(it => !core.isExtra(it)));
  // main is by what you pay, all in
  const v = g.main.map(it => core.allIn(it)).filter(x => x != null);
  assert.deepEqual(v, v.slice().sort((a, b) => a - b));
});

test('the better ones: the pick first, with short reasons; best new and best trusted too', () => {
  const h = ledger.highlights();
  assert.ok(h.length >= 2 && h.length <= 5);
  assert.equal(h[0].it.url, core.pickUrl());
  assert.equal(h[0].why[0], 'cheapest all-in');
  const why = h.flatMap(x => x.why).join(' | ');
  assert.ok(/cheapest new/.test(why), why);
  assert.ok(/best trusted seller/.test(why), why);
  assert.equal(new Set(h.map(x => x.it.url)).size, h.length, 'one card per listing');
});

test('filters: condition, country, pickup only, price range', () => {
  const g = ledger.groups();
  const all = g.main.concat(g.eu, g.risky, g.costing);
  ledger._test.setFilter({ cond: new Set(['new']) });
  assert.ok(all.filter(ledger._test.passes).every(it => /^new/i.test(it.offer.condition)));
  ledger._test.setFilter({ cc: new Set(['SE']) });
  const se = all.filter(ledger._test.passes);
  assert.ok(se.length > 20 && se.every(it => it.url.includes('blocket.se')));
  ledger._test.setFilter({ ship: 'pickup' });
  const pk = all.filter(ledger._test.passes);
  assert.ok(pk.length > 10 && pk.every(core.isPickupOnly));
  ledger._test.setFilter({ min: 100, max: 150 });
  const mid = all.filter(ledger._test.passes);
  assert.ok(mid.length > 10 && mid.every(it => { const v = core.allIn(it) ?? it.offer.price_eur; return v >= 100 && v <= 150; }));
  ledger._test.setFilter({});
});

// price value: how far under the middle price of its condition (the teammate's bananas.py steps: 10/20/30%)
const item = (url, condition, eur, bananas) => ({ url, offer: { condition, price_eur: eur, title: url }, ...(bananas !== undefined ? { tc: { bananas } } : {}) });
test('value: tiers by share under the middle price of the same condition; too good to be true gets none', () => {
  const list = [item('a', 'used', 100), item('b', 'used', 85), item('c', 'used', 75), item('d', 'used', 65),
    item('e', 'used', 35), item('f', 'used', 110), item('n', 'new', 300), item('m', 'new', 200), item('o', 'new', 250)];
  const mids = ledger.middles(list);
  assert.equal(mids.used, 80);  // median of 100 85 75 65 35 110
  assert.equal(mids.new, 250);
  const t = id => ledger.valueOf(list.find(x => x.url === id), mids).tier;
  assert.equal(t('f'), 0);       // dearer than the middle
  assert.equal(t('a'), 0);       // 25% over
  assert.equal(t('c'), 0);       // 6% under: under one step
  assert.equal(t('d'), 1);       // 19% under
  assert.equal(t('m'), 2);       // 20% under the new middle
  assert.equal(t('e'), 0);       // 56% under: not believed
  assert.equal(ledger.valueOf(list[0], {}).tier, 0);  // no middle: no value
  assert.equal(ledger.valueTier(0.3), 3);
  assert.equal(ledger.valueTier(0.51), 0);
});

test('best value first: most value icons, then the biggest share under the middle, then the cheapest', () => {
  const list = [item('a', 'used', 100), item('b', 'used', 70), item('c', 'used', 60), item('d', 'used', 90), item('e', 'used', 100)];
  const mids = ledger.middles(list);   // 90
  assert.deepEqual(ledger.sortBy(list, 'value', mids).map(x => x.url), ['c', 'b', 'd', 'a', 'e']);
  assert.deepEqual(ledger.sortBy(list, 'price', mids).map(x => x.url), ['c', 'b', 'd', 'a', 'e']);
  const mixed = [item('u', 'used', 60), item('v', 'used', 100), item('w', 'used', 100), item('n1', 'new', 300), item('n2', 'new', 200), item('n3', 'new', 310)];
  const m2 = ledger.middles(mixed);   // used 100, new 300
  assert.deepEqual(ledger.sortBy(mixed, 'value', m2).slice(0, 2).map(x => x.url), ['u', 'n2']); // 40% then 33% under
  assert.equal(ledger.sortBy(mixed, 'price', m2)[0].url, 'u');
});

test('filters: bananas (trust, from the truecost) and value', () => {
  const list = [item('g3', 'used', 50, { n: 3, state: 'good', why: 'x' }), item('g1', 'used', 52, { n: 1, state: 'good' }),
    item('ea', 'used', 54, { n: 0, state: 'eaten', why: 'looks like a scam pattern' }), item('no', 'used', 100, null), item('nx', 'used', 100)];
  assert.deepEqual(ledger.bananasOf(list[2]), { n: 0, eaten: true, why: 'looks like a scam pattern' });
  assert.equal(ledger.bananasOf(list[3]), null);
  ledger._test.setFilter({ bn: 1 });
  assert.deepEqual(list.filter(ledger._test.passes).map(x => x.url), ['g3', 'g1']);
  ledger._test.setFilter({ bn: 3 });
  assert.deepEqual(list.filter(ledger._test.passes).map(x => x.url), ['g3']);
  ledger._test.setMids(ledger.middles(list));   // used middle 54: 50 is 7% under, 52 4%
  ledger._test.setFilter({ vt: 1 });
  assert.deepEqual(list.filter(ledger._test.passes).map(x => x.url), []);
  ledger._test.setMids({ used: 100 });
  assert.deepEqual(list.filter(ledger._test.passes).map(x => x.url), ['g3', 'g1', 'ea']);
  ledger._test.setFilter({}); ledger._test.setMids({});
});

test('the summary credits Context.dev for search too (never "0 via Context.dev")', () => {
  const st = livelog._test.cdStats();
  assert.equal(st.searches, 4);
  assert.ok(st.found > 10, `pages found ${st.found}`);
  assert.ok(st.reads >= 6, `reads ${st.reads}`);
  assert.ok(st.listings > 100);
  assert.equal(st.free[0][0], 'tori.fi');
  assert.ok(st.free[0][1] > 200);
});

test('compareMore: a recorded/offline hunt cannot read more', async () => {
  const r = await stream.compareMore();
  assert.equal(r.error, 'offline');
  assert.equal(stream.waitFor({ tokens: 2, per_min: 10 }), 24);
  assert.equal(stream.waitFor({ tokens: 9, per_min: 10 }), 0);
  assert.equal(stream.waitFor(null), 0);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack || e); }
}
process.exit(failed ? 1 : 0);
