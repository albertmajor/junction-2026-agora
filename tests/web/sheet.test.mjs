// The listing dialog (agora/web/js/sheet.js): the ← / → order and the photo gallery, on the recorded
// city-bike hunt. Pure functions only (no DOM). Run by tests/test_web_sheet.py with node.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
globalThis.fetch = async () => { throw new Error('offline test'); };
const core = await import('../../agora/web/js/core.js');
const stream = await import('../../agora/web/js/stream.js');
const ledger = await import('../../agora/web/js/ledger.js');
const sheet = await import('../../agora/web/js/sheet.js');
await new Promise(r => setTimeout(r, 20));   // sheet.js picks up ledger.js lazily
const { S } = core;

const events = readFileSync(new URL('../fixtures/live_city-bike-with-basket.jsonl', import.meta.url), 'utf8')
  .split('\n').filter(Boolean).map(l => JSON.parse(l));
stream._test.begin('city bike with basket', { live: false });
for (const ev of events) stream._test.feed(ev);

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('← / → follow the list: main by all-in, then the EU group, still costing, set aside last', () => {
  const ord = sheet.listOrder();
  const g = ledger.groups();
  const want = [].concat(g.main, g.eu, g.costing, g.risky).map(it => it.url);
  assert.deepEqual(ord, want);
  assert.equal(new Set(ord).size, ord.length, 'no listing twice');
  assert.ok(ord.includes(core.pickUrl()), 'the pick is in the order');
  // set-aside ones come after every ranked one
  const firstRisky = ord.findIndex(u => core.isRisky(S.offers.get(u)));
  assert.ok(firstRisky > 0 && ord.slice(firstRisky).every(u => core.isRisky(S.offers.get(u))));
});

test('gallery: the main photo first, extra listing photos after, no doubles, at most 8', () => {
  const it = { url: 'https://shop.example/x', offer: { image: 'https://img.example/a.jpg',
    images: ['https://img.example/a.jpg', 'https://img.example/b.jpg', { url: 'https://img.example/c.jpg' }, 'javascript:alert(1)'] } };
  assert.deepEqual(sheet.gallery(it), ['https://img.example/a.jpg', 'https://img.example/b.jpg', 'https://img.example/c.jpg']);
  const many = { url: 'u', offer: { image: 'https://i/0.jpg', images: Array.from({ length: 12 }, (_, i) => `https://i/${i}.jpg`) } };
  assert.equal(sheet.gallery(many).length, 8);
  assert.deepEqual(sheet.gallery({ url: 'u', offer: {} }), []);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack || e); }
}
process.exit(failed ? 1 : 0);
