// Clarify first (agora/web/js/clarify.js): when a typed search is not clearly one thing, ask before hunting.
// The decision: ask = the engine's clarify.ask when it sends one, else !dominant with 2+ meanings; never for a hunt
// from the tree, a chosen meaning, "search everything", an example or a recorded search; a remembered answer is
// reused. Run by tests/test_web_clarify.py with node.
import assert from 'node:assert/strict';
const CL = await import('../../agora/web/js/clarify.js');
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const lunch = { dominant: false, intents: [
  { id: 'c:lunch.places', label: 'Lunch places near you', why: 'A lunch is usually bought at a restaurant near you.', hunt: { q: 'lunch restaurant' } },
  { id: 'c:lunch.delivery', label: 'Lunch delivered near you', why: 'Lunch to your desk or door.', hunt: { q: 'lunch delivery' } },
  { id: 'c:lunch.box', label: 'Lunch boxes and bento', why: 'Or the box you carry your own lunch in.', hunt: { q: 'lunch box' } },
] };
const gtaOld = { dominant: true, intents: [{ id: 'n:sp:el-19', label: 'Video Game Consoles', as_typed: true, hunt: { q: 'gta 6 ps5' } }] };
const gtaNew = { ...gtaOld, clarify: { ask: true, question: 'Just the game, or a PS5 with GTA 6?',
  options: [{ id: 'game', label: 'Just the game', hint: 'GTA 6 for PS5, disc or code', intent_id: 'c:gta.game', hunt: { q: 'gta 6 ps5 game', cat: 'sp:games' } },
            { id: 'bundle', label: 'A PS5 with a GTA 6 deal', hint: 'Console bundles', intent_id: 'n:sp:el-19' }],
  as_typed: { label: 'Search exactly “gta 6 ps5”' } } };

test('no dominant meaning: ask, with the meanings as options (label + why as hint) and a way to search as typed', () => {
  const d = CL.decide('lunch', lunch);
  assert.equal(d.ask, true);
  assert.deepEqual(d.options.map(o => o.label), ['Lunch places near you', 'Lunch delivered near you', 'Lunch boxes and bento']);
  assert.equal(d.options[2].hint, 'Or the box you carry your own lunch in.');
  assert.equal(d.options[0].plan, lunch.intents[0]);
  assert.match(d.question, /“lunch”.*What are you looking for\?/);
  assert.equal(d.asTyped.label, 'Search exactly “lunch”');
});

test('a clear meaning, or nothing to choose between: no question (behave as today)', () => {
  assert.deepEqual(CL.decide('gta 6 ps5', gtaOld), { ask: false });
  assert.deepEqual(CL.decide('sony a7 iii body', { dominant: false, intents: [] }), { ask: false });
  assert.deepEqual(CL.decide('x', { dominant: false, intents: [lunch.intents[0]] }), { ask: false });
  assert.deepEqual(CL.decide('lunch', null), { ask: false });
});

test("the engine's clarify payload wins: its question, options (intent_id or own hunt) and as-typed label", () => {
  const d = CL.decide('gta 6 ps5', gtaNew);
  assert.equal(d.ask, true);
  assert.equal(d.question, 'Just the game, or a PS5 with GTA 6?');
  assert.equal(d.options[0].plan.hunt.q, 'gta 6 ps5 game');
  assert.equal(d.options[0].plan.id, 'c:gta.game');
  assert.equal(d.options[1].plan, gtaOld.intents[0]);
  assert.equal(d.asTyped.label, 'Search exactly “gta 6 ps5”');
  // ask:false from the engine means no question even without a dominant meaning
  assert.deepEqual(CL.decide('lunch', { ...lunch, clarify: { ask: false } }), { ask: false });
});

test('never asks for tree hunts, chosen meanings, search-everything, examples or recordings', () => {
  for (const ctx of [{ cat: { id: 'x' } }, { plan: lunch.intents[1] }, { intent: 'c:lunch.box' }, { free: true }, { example: true }, { recorded: true }])
    assert.deepEqual(CL.decide('lunch', lunch, ctx), { ask: false }, JSON.stringify(ctx));
});

test('a remembered answer is reused (an intent still offered, or the words as typed); a stale one asks again', () => {
  assert.deepEqual(CL.decide('lunch', lunch, { remembered: 'c:lunch.box' }), { ask: false, pick: 'c:lunch.box' });
  assert.deepEqual(CL.decide('lunch', lunch, { remembered: CL.TYPED }), { ask: false, pick: '_typed' });
  assert.equal(CL.decide('lunch', lunch, { remembered: 'gone' }).ask, true);
});

test('at most five options, no duplicates', () => {
  const many = { dominant: false, intents: Array.from({ length: 8 }, (_, i) => ({ id: 'i' + (i % 6), label: 'L' + i })) };
  const d = CL.decide('thing', many);
  assert.equal(d.options.length, 5);
  assert.equal(new Set(d.options.map(o => o.plan.id)).size, 5);
});

test('memory is per words (case and spaces do not matter)', () => {
  const m = new Map();
  const s = { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
  CL.remember('GTA 6  PS5', 'c:gta.game', s);
  assert.equal(CL.recall(' gta 6 ps5', s), 'c:gta.game');
  assert.equal(CL.recall('gta 6', s), '');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok  ', name); }
  catch (e) { failed++; console.log('FAIL', name, '\n', e && e.stack); }
}
if (failed) process.exit(1);
