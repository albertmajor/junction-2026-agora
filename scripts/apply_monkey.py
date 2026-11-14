"""Apply an exported monkey placement (pricemonkey-monkey.json from the monkey devtool) as the shipped default.

usage: .venv/bin/python scripts/apply_monkey.py pricemonkey-monkey.json [--dry-run]
Rewrites `export const MONKEY_PLACE = {...}` in agora/web/js/mascot.js. Idempotent.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = ROOT / "agora" / "web" / "js" / "mascot.js"

def main(argv):
    if not argv:
        sys.exit(__doc__)
    cfg = json.loads(pathlib.Path(argv[0]).read_text())
    vals = {"dx": int(round(float(cfg.get("dx", 22)))), "dy": int(round(float(cfg.get("dy", 0)))),
            "w": max(20, min(400, int(round(float(cfg.get("w", 75)))))),
            "flip": bool(cfg.get("flip", False)), "rot": round(float(cfg.get("rot", 0)), 1)}
    line = ("export const MONKEY_PLACE = { dx: %(dx)d, dy: %(dy)d, w: %(w)d, flip: %(flip)s, rot: %(rot)s };"
            % {**vals, "flip": "true" if vals["flip"] else "false", "rot": ("%g" % vals["rot"])})
    src = JS.read_text()
    new, n = re.subn(r"export const MONKEY_PLACE = \{[^}]*\};", line, src, count=1)
    if n != 1:
        sys.exit("MONKEY_PLACE not found in mascot.js")
    if "--dry-run" in argv:
        print(line); return
    if new != src:
        JS.write_text(new)
    print("applied:", line)

if __name__ == "__main__":
    main(sys.argv[1:])
