// The mascot's moods (agora/web/js/mascot.js): which animation each spot shows during a hunt, the markup
// (webp + gif fallback + a still frame for reduced motion), and that the files exist. Run by
// tests/test_web_mascot.py with node.
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
const M = await import('../../agora/web/js/mascot.js');
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('over the live log: searching while it reads, thinking once a first answer is costed or the chips decide', () => {
  assert.equal(M.peekMood({ verdict: null }), 'searching');
  assert.equal(M.peekMood({ verdict: { provisional: true, pending_reads: 4 } }), 'thinking');
  assert.equal(M.peekMood({ verdict: null }, true), 'thinking');
});

test('over the pick card: thinking, then found-it once on the final verdict, then a still', () => {
  assert.deepEqual(M.pickMood({ verdict: { provisional: true } }), ['thinking', false]);
  assert.deepEqual(M.pickMood({ verdict: { provisional: false } }), ['found-it', false]);
  assert.deepEqual(M.pickMood({ verdict: { provisional: false } }, { played: true }), ['found-it', true]);
  // a hunt that ends without a final verdict never celebrates and never thinks forever
  assert.deepEqual(M.pickMood({ verdict: { provisional: true } }, { done: true }), ['idle', true]);
});

test('markup: reduced motion gets a still frame first, then animated webp, then the gif', () => {
  const html = M.picture('searching', { cls: 'll-peek', w: 52, h: 91 });
  assert.match(html, /<picture class="mk ll-peek" data-mood="searching" aria-hidden="true">/);
  const order = ['prefers-reduced-motion: reduce', 'monkey-idle-still.png', 'image/webp', 'monkey-searching.webp', 'monkey-searching.gif'];
  let at = -1;
  for (const s of order) { const i = html.indexOf(s); assert.ok(i > at, s); at = i; }
  assert.match(html, /alt=""/);
  assert.equal(M.srcs('found-it', { still: true }).webp, '/web/assets/mascot/monkey-found-it-still.png');
  assert.equal(M.srcs('nope').webp, '/web/assets/mascot/monkey-idle.webp');
});

test('every file the moods point at is in agora/web/assets/mascot', () => {
  for (const mood of M.MOODS) {
    for (const f of new Set(Object.values(M.srcs(mood)))) {
      const p = new URL('../../agora' + f, import.meta.url);
      assert.ok(existsSync(p), f);
    }
  }
});

test('module import touches no DOM (livelog.js and verdict.js load it in node)', () => {
  assert.equal(M.pickMonkey(), null);
  M.setDeciding(true); M.setDeciding(false);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack || e); }
}
process.exit(failed ? 1 : 0);
