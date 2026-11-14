// Monkey placement devtool (localhost only): drag the start-screen monkey where you want him, size/flip/tilt him,
// then Export JSON. Opened with ?monkeydev=1 or Ctrl/Cmd+Shift+M. Apply an export with scripts/apply_monkey.py.
import { MONKEY_PLACE, monkeyPlace, placeStartMonkey } from './mascot.js';

const KEY = 'pm.monkeyPlace';
let panel = null;

function save(cfg) { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch {} placeStartMonkey(cfg); sync(cfg); }
let target = 'monkey';   // which one the sliders and drag move: 'monkey' | 'banana'
const bananaOf = cfg => cfg.banana || { dx: cfg.dx, dy: cfg.dy, w: Math.round(cfg.w * 0.55), rot: 0, flip: false };
const cur = cfg => (target === 'banana' ? bananaOf(cfg) : cfg);
const setCur = (cfg, patch) => (target === 'banana' ? { ...cfg, banana: { ...bananaOf(cfg), ...patch } } : { ...cfg, ...patch });
function sync(cfg) {
  if (!panel) return;
  const c = cur(cfg);
  for (const k of ['dx', 'dy', 'w', 'rot']) { const i = panel.querySelector(`[name=${k}]`); if (i) i.value = c[k]; const o = panel.querySelector(`[data-o=${k}]`); if (o) o.textContent = c[k]; }
  panel.querySelector('[name=flip]').checked = !!c.flip;
  for (const b of panel.querySelectorAll('[data-t]')) b.style.background = b.dataset.t === target ? '#4E3818' : 'none';
}

export function openMonkeyDev() {
  const m = document.querySelector('#start .start-monkey');
  if (!m) { console.warn('monkeydev: go to the start screen first'); return; }
  if (panel) { panel.hidden = false; return; }
  let cfg = { ...monkeyPlace() };
  const ban = document.querySelector('#start .start-banana');
  const grab = (el, who) => {
    if (!el) return;
    el.style.pointerEvents = 'auto'; el.style.cursor = 'grab'; el.style.outline = '1px dashed #F0D435'; el.style.zIndex = 50;
    el.addEventListener('pointerdown', e => {
      e.preventDefault(); target = who; sync(cfg); el.setPointerCapture(e.pointerId); el.style.cursor = 'grabbing';
      const x0 = e.clientX, y0 = e.clientY, c0 = cur(cfg);
      // the banana is measured from the box's LEFT edge, so moving right shrinks its gap
      const sx = who === 'banana' ? -1 : 1;
      const move = ev => { cfg = setCur(cfg, { dx: Math.round(c0.dx + sx * (ev.clientX - x0)), dy: Math.round(c0.dy + ev.clientY - y0) }); save(cfg); };
      const up = () => { el.style.cursor = 'grab'; el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); };
      el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
    });
    el.addEventListener('wheel', e => { e.preventDefault(); target = who; const c = cur(cfg); cfg = setCur(cfg, { w: Math.max(20, Math.min(300, Math.round(c.w - Math.sign(e.deltaY) * 3))) }); save(cfg); }, { passive: false });
  };
  grab(m, 'monkey'); grab(ban, 'banana');

  panel = document.createElement('div');
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Monkey placement');
  panel.style.cssText = 'position:fixed;right:16px;bottom:56px;z-index:9999;background:#1d1b18;color:#f4efe6;border:1px solid #4E3818;border-radius:12px;padding:12px 14px;font:13px/1.4 system-ui,sans-serif;width:270px;box-shadow:0 8px 30px rgba(0,0,0,.35)';
  const row = (k, label, min, max, step = 1) => `<label style="display:grid;grid-template-columns:70px 1fr 40px;gap:8px;align-items:center;margin:4px 0">${label}<input type=range name=${k} min=${min} max=${max} step=${step}><span data-o=${k} style="text-align:right;font-variant-numeric:tabular-nums"></span></label>`;
  panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><b>🐒 Monkey placement</b><button data-a=close style="background:none;border:0;color:inherit;cursor:pointer;font-size:16px">×</button></div>
    <div style="display:flex;gap:6px;margin-bottom:6px"><button data-t=monkey style="flex:1;padding:4px;border-radius:8px;border:1px solid #4E3818;color:inherit;cursor:pointer">🐒 Monkey</button><button data-t=banana style="flex:1;padding:4px;border-radius:8px;border:1px solid #4E3818;color:inherit;cursor:pointer">🍌 Banana</button></div>
    <div style="opacity:.75;margin-bottom:6px">Drag either one. Scroll on it to resize. Positions are relative to the search box, so they hold at every width. Banana: ← → is the gap to the box's left edge.</div>
    ${row('dx', '← → (px)', -900, 600)}${row('dy', '↑ ↓ (px)', -400, 400)}${row('w', 'size (px)', 30, 260)}${row('rot', 'tilt (°)', -45, 45)}
    <label style="display:flex;gap:8px;align-items:center;margin:6px 0"><input type=checkbox name=flip> mirror</label>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
      <button data-a=export style="flex:1;padding:6px 8px;border-radius:8px;border:0;background:#F0D435;color:#1d1b18;font-weight:600;cursor:pointer">Export JSON</button>
      <button data-a=import style="padding:6px 8px;border-radius:8px;border:1px solid #4E3818;background:none;color:inherit;cursor:pointer">Import</button>
      <button data-a=reset style="padding:6px 8px;border-radius:8px;border:1px solid #4E3818;background:none;color:inherit;cursor:pointer">Reset</button>
    </div><div data-o=msg style="margin-top:6px;opacity:.75;min-height:1em"></div>`;
  document.body.appendChild(panel);
  sync(cfg); placeStartMonkey(cfg);
  panel.addEventListener('input', e => {
    const t = e.target; if (!t.name) return;
    cfg = setCur(cfg, { [t.name]: t.type === 'checkbox' ? t.checked : Number(t.value) }); save(cfg);
  });
  const msg = t => { panel.querySelector('[data-o=msg]').textContent = t; };
  panel.addEventListener('click', async e => {
    if (e.target.dataset && e.target.dataset.t) { target = e.target.dataset.t; sync(cfg); return; }
    const a = e.target.dataset && e.target.dataset.a; if (!a) return;
    if (a === 'close') { panel.hidden = true; return; }
    if (a === 'reset') { try { localStorage.removeItem(KEY); } catch {} cfg = { ...MONKEY_PLACE }; placeStartMonkey(cfg); sync(cfg); msg('Back to the shipped placement.'); }
    if (a === 'export') {
      const json = JSON.stringify({ version: 2, tool: 'PriceMonkey monkey placement', anchor: 'search box (#ask): monkey dx from its right edge, banana dx from its left edge, dy from its bottom', ...cfg, banana: bananaOf(cfg) }, null, 2);
      try { await navigator.clipboard.writeText(json); } catch {}
      const blob = new Blob([json], { type: 'application/json' }); const u = URL.createObjectURL(blob);
      const l = document.createElement('a'); l.href = u; l.download = 'pricemonkey-monkey.json'; l.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
      msg('Copied + downloaded pricemonkey-monkey.json');
    }
    if (a === 'import') {
      const t = prompt('Paste the JSON'); if (!t) return;
      try { const o = JSON.parse(t); cfg = { ...MONKEY_PLACE, ...['dx', 'dy', 'w', 'rot', 'flip', 'banana'].reduce((x, k) => (k in o ? { ...x, [k]: o[k] } : x), {}) }; save(cfg); msg('Imported.'); } catch { msg('Not valid JSON.'); }
    }
  });
}
