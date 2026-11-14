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
    b = cfg.get("banana")
    if isinstance(b, dict):
        bv = {"dx": int(round(float(b.get("dx", 0)))), "dy": int(round(float(b.get("dy", 0)))),
              "w": max(10, min(400, int(round(float(b.get("w", 72)))))), "rot": round(float(b.get("rot", 0)), 1),
              "flip": bool(b.get("flip", False))}
        ban = ("{ dx: %d, dy: %d, w: %d, rot: %g, flip: %s }"
               % (bv["dx"], bv["dy"], bv["w"], bv["rot"], "true" if bv["flip"] else "false"))
    else:
        ban = "null"
    line = ("export const MONKEY_PLACE = { dx: %(dx)d, dy: %(dy)d, w: %(w)d, flip: %(flip)s, rot: %(rot)s, banana: %(ban)s };"
            % {**vals, "flip": "true" if vals["flip"] else "false", "rot": ("%g" % vals["rot"]), "ban": ban})
    src = JS.read_text()
    new, n = re.subn(r"export const MONKEY_PLACE = \{.*?\};(?=\n)", line, src, count=1)
    if n != 1:
        sys.exit("MONKEY_PLACE not found in mascot.js")
    if "--dry-run" in argv:
        print(line); return
    if new != src:
        JS.write_text(new)
    print("applied:", line)

if __name__ == "__main__":
    main(sys.argv[1:])
