// Live-mode UI store logic, from the first live test (Nov 2026). Run by tests/test_web_live_ui.py with node.
// Cases are cut down from real live streams: macbook-air-m2 / dyson-v15 / nintendo-switch-oled (an offer
// rejected by the final check), airpods-pro-2 (logo and placeholder photos), and the stuck "checking N more
// shops" status when a hunt ends without a final verdict.
import assert from 'node:assert/strict';
globalThis.fetch = async () => { throw new Error('offline test'); };
const core = await import('../../agora/web/js/core.js');
const stream = await import('../../agora/web/js/stream.js');
const { statusFor } = await import('../../agora/web/js/verdict.js');
const { S, on } = core;
const seen = [];
for (const t of ['offer', 'offer-removed', 'skip', 'error', 'done', 'turn']) on(t, d => seen.push([t, d]));
const ev = (type, data, t_ms = 0) => ({ type, data, t_ms });
const offer = (url, price, extra = {}) => ev('offer', { offer: { url, source: new URL(url).hostname, price_eur: price, condition: 'new', ...extra } });
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('an offer rejected by the final check leaves the store and the line is told', () => {
  stream._test.begin('macbook air m2'); seen.length = 0;
  const bad = 'https://prices.appleinsider.com/macbook-air-2022';
  stream._test.feed(offer(bad, 999));
  stream._test.feed(offer('https://www.mediamarkt.de/x', 1099));
  S.leader = bad;
  stream._test.feed(ev('skip', { url: bad, reason: 'does not match what you asked for', rejected: true }));
  assert.equal(S.offers.has(bad), false);
  assert.equal(S.offers.size, 1);
  assert.equal(S.leader, null);
  assert.ok(seen.some(([t, d]) => t === 'offer-removed' && d.url === bad));
});

test('an ordinary skip (never an offer) removes nothing', () => {
  stream._test.begin('dyson v15'); seen.length = 0;
  stream._test.feed(offer('https://a.example/v15', 500));
  stream._test.feed(ev('skip', { url: 'https://www.dyson.ie/vacuum-cleaners/cordless/v15/all', reason: 'different model', rejected: true }));
  assert.equal(S.offers.size, 1);
  assert.ok(!seen.some(([t]) => t === 'offer-removed'));
});

test('a 429 on one page is a skip, not the end of the live hunt (no swap to another recording)', () => {
  stream._test.begin('ikea kallax shelf'); seen.length = 0;
  stream._test.feed(offer('https://www.ikea.com/fi/kallax', 79));
  stream._test.feed(ev('error', { where: 'read', url: 'https://www.ikea.com/de/x', message: 'ContextDevError: /scrape: still rate limited after retries' }));
  assert.equal(S.offers.size, 1);
  assert.equal(S.done, false);
  assert.ok(seen.some(([t, d]) => t === 'skip' && /rate limit/.test(d.reason)));
  assert.ok(!seen.some(([t]) => t === 'error'));
  stream._test.feed(ev('done', { ms: 20500 }));
  assert.ok(!seen.some(([t]) => t === 'error'), 'offers were found: no error at the end');
});

test('rate limited with zero offers ends with an honest 429 message', () => {
  stream._test.begin('kallax'); seen.length = 0;
  stream._test.feed(ev('error', { where: 'discover', message: 'HTTP 429 Too Many Requests' }));
  stream._test.feed(ev('done', { ms: 20100 }));
  const err = seen.find(([t]) => t === 'error');
  assert.ok(err && err[1].kind === '429' && /10 reads a minute/.test(err[1].message));
  assert.equal(seen[seen.length - 1][0], 'done');
});

test('a stalled or broken stream finishes: Turn fires if costs arrived, done is emitted once', () => {
  stream._test.begin('airpods pro 2'); seen.length = 0;
  const u = 'https://swappie.com/en/airpods/';
  stream._test.feed(offer(u, 179));
  stream._test.feed(ev('truecost', { url: u, true_cost: { per_month_eur: 7.75, per: 'month' } }));
  stream._test.feed(ev('verdict', { provisional: true, pending_reads: 6, verdict: { best_true_cost_url: u } }));
  stream._test.stall();
  stream._test.stall();
  assert.equal(S.done, true);
  assert.equal(S.turned, true);
  assert.equal(seen.filter(([t]) => t === 'done').length, 1);
  assert.ok(seen.some(([t, d]) => t === 'error' && d.kind === 'net'));
});

test('"checking N more shops" never outlives the hunt', () => {
  const prov = { provisional: true, pending_reads: 6 };
  assert.match(statusFor(prov, false, 3)[1], /checking 6 more shops/);
  assert.doesNotMatch(statusFor(prov, true, 3)[1], /checking/);
  assert.equal(statusFor({ provisional: false }, false, 3)[1], '');
  assert.equal(statusFor(null, true, 0)[1], '');
});

test('logos, social cards and placeholders are not product photos (no cut-out of them)', () => {
  for (const u of ['https://uptradeit.com/og_logo.png', 'https://www.backmarket.ie/img/plp/ogImage.png',
                   'https://www.dyson.ie/image/content/dam/dyson/fallback-images/en/lifestyle_en.png',
                   'https://s5.appleinsider.com/price_guide/m2-macbook-air-pg-header.png']) {
    assert.equal(core.isProductPhoto(u), false, u);
    assert.equal(core.cutSrc(u), null, u);
  }
  for (const u of ['https://files.refurbed.com/ii/apple-airpods-pro-2-1699965335.jpg',
                   'https://store.storeimages.cdn-apple.com/4668/as-images.apple.com/is/MQJ23?wid=4000&hei=4000',
                   'https://images.tori.fi/dynamic/1280w/item/49853401/554cec19']) {
    assert.equal(core.isProductPhoto(u), true, u);
    // background removal is off by default (CUTOUTS=false): the plain photo is used
    assert.equal(core.cutSrc(u), core.CUTOUTS ? '/cut?u=' + encodeURIComponent(u) : u, u);
  }
  assert.ok(core.CUT_MIN_PX >= 240 && core.CUT_MIN_PX <= 400);
});

test('seller reviews: trust marks fill in, a watch-out shop loses the pick with a recheck note', () => {
  stream._test.begin('airpods pro 2'); seen.length = 0;
  const cheap = 'https://shop.cheapods-test.com/airpods', good = 'https://www.bigshop-test.com/airpods';
  const tc = (url, sticker) => ev('truecost', { url, true_cost: { sticker_eur: sticker, extras_eur: 0, total_eur: sticker, per: 'month' }, flags: [] });
  stream._test.feed(offer(cheap, 199)); stream._test.feed(offer(good, 229));
  stream._test.feed(tc(cheap, 199)); stream._test.feed(tc(good, 229));
  stream._test.feed(ev('verdict', { verdict: { best_offer_url: cheap }, provisional: false }));
  assert.equal(S.leader, cheap);
  assert.deepEqual(stream.reviewHosts(), ['shop.cheapods-test.com', 'bigshop-test.com']);
  S.reviewsState = 'checking'; ['shop.cheapods-test.com', 'bigshop-test.com'].forEach(h => S.reviewTargets.add(h));
  assert.equal(core.trustMark(S.offers.get(good)).text, 'checking reviews…');
  const rechecks = []; on('recheck', d => rechecks.push(d));
  stream._test.review({ domain: 'bigshop-test.com', hosts: ['bigshop-test.com'], status: 'done', label: 'solid', rating: 4.1, count: 12345 });
  assert.equal(core.trustMark(S.offers.get(good)).text, '★ 4.1 · 12k · solid');
  assert.equal(S.leader, cheap);
  stream._test.review({ domain: 'cheapods-test.com', hosts: ['shop.cheapods-test.com'], status: 'done', label: 'watch out', rating: 2.1, count: 38, red_flags: ['orders never delivered (3 recent reviews)'] });
  assert.equal(core.trustMark(S.offers.get(cheap)).label, 'watch out');
  assert.equal(core.pickUrl(), good);
  assert.equal(S.leader, good);
  assert.deepEqual(rechecks.map(r => [r.from, r.to]), [[cheap, good]]);
  stream._test.review({ domain: 'none-test.com', hosts: ['none-test.com'], status: 'none', label: 'unknown' });
  S.reviewsState = 'done';
  assert.equal(core.fmtCount(2089), '2.1k');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack || e); }
}
process.exit(failed ? 1 : 0);
