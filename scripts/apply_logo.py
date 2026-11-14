#!/usr/bin/env python3
"""Write a logo export (pricemonkey-logo.json) into the --logo-* tokens in agora/web/css/base.css :root.

The JSON comes from the dev logo panel (agora/web/js/logodev.js, localhost only, ?logodev=1 or Ctrl/Cmd+Shift+L).
Every logo rule in base.css reads only these tokens, so the site then looks exactly like the panel's preview.
The conversion settings -> tokens (to_vars) and the import checks (load_export) mirror toVars()/importJson() in
logodev.js; tests/test_logodev.py checks both give the same tokens.

    .venv/bin/python scripts/apply_logo.py pricemonkey-logo.json --dry-run   # show what would change
    .venv/bin/python scripts/apply_logo.py pricemonkey-logo.json             # write it

Only tokens whose value differs are rewritten, so running the same file again changes nothing.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_CSS = ROOT / "agora" / "web" / "css" / "base.css"

# [key, css var, unit, min, max] (logodev.js NUM; the panel's step does not matter here)
NUM = [
    ("markWidth", "--logo-mark-w", "px", 12, 96),
    ("gap", "--logo-gap", "px", -8, 40),
    ("tilt", "--logo-tilt", "deg", -30, 30),
    ("hoverTilt", None, "deg", -30, 30),
    ("size", "--logo-size", "px", 10, 72),
    ("weight", "--logo-weight", "", 100, 900),
    ("hoverWeight", "--logo-hover-weight", "", 100, 900),
    ("tracking", "--logo-tracking", "em", -0.15, 0.3),
    ("center", "--logo-center", "em", 0, 0.8),
    ("nudge", None, "", -24, 24),
    ("footerWidth", "--logo-foot-w", "px", 8, 48),
    ("footerNudge", "--logo-foot-nudge", "px", -8, 8),
]
CASES = ["lowercase", "none", "uppercase", "capitalize"]
NUDGE_RANGE = {"px": (-12, 12), "em": (-0.5, 0.5)}
COLOR_VARS = {"light": {"price": "--logo-price-light", "monkey": "--logo-monkey-light"},
              "dark": {"price": "--logo-price-dark", "monkey": "--logo-monkey-dark"}}
RX_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|var\(--[a-z0-9-]+\))$")
DEFAULT_HOVER_TILT = -7
RX_NUM = re.compile(r"^\s*(-?[\d.]+)\s*([a-z%]*)\s*$", re.I)


def fmt(n: float) -> str:
    """logodev.js fmt(): floor(n*1e4 + .5) / 1e4, shortest form, never "-0"."""
    r = math.floor(n * 1e4 + 0.5) / 1e4
    if r == 0:
        return "0"
    return str(int(r)) if r == int(r) else repr(r)


def root_block(css: str) -> re.Match:
    m = re.search(r":root\s*\{([^}]*)\}", css)
    if not m:
        raise SystemExit("base.css has no :root block")
    return m


def root_vars(css: str) -> dict[str, str]:
    body = re.sub(r"/\*[\s\S]*?\*/", "", root_block(css).group(1))
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]*);", body)}


def _num(v):
    m = RX_NUM.match(str(v if v is not None else ""))
    return (float(m.group(1)), m.group(2).lower()) if m else None


def from_vars(t: dict[str, str]) -> dict:
    s: dict = {}
    for key, var, unit, _lo, _hi in NUM:
        if not var:
            continue
        p = _num(t.get(var))
        if not p or (unit and p[1] and p[1] != unit):
            raise SystemExit(f'{var}: "{t.get(var)}" is not a {unit or "number"}')
        s[key] = p[0]
    nd = _num(t.get("--logo-nudge")) or (0.0, "px")
    s["nudge"], s["nudgeUnit"] = nd[0], ("em" if nd[1] == "em" else "px")
    ht = _num(t.get("--logo-hover-tilt")) or (DEFAULT_HOVER_TILT, "deg")
    s["wiggle"] = ht[0] != 0
    s["hoverTilt"] = ht[0] if ht[0] != 0 else DEFAULT_HOVER_TILT
    c = (t.get("--logo-case") or "").strip()
    s["case"] = c if c in CASES else "lowercase"
    s["priceItalic"] = (t.get("--logo-price-style") or "").strip() != "normal"
    s["monkeyItalic"] = (t.get("--logo-monkey-style") or "").strip() != "normal"
    s["colors"] = {mode: {part: (t.get(COLOR_VARS[mode][part]) or "").strip() for part in ("price", "monkey")}
                   for mode in ("light", "dark")}
    return s


def to_vars(s: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, var, unit, _lo, _hi in NUM:
        if var:
            out[var] = fmt(s[key]) + unit
    out["--logo-nudge"] = fmt(s["nudge"]) + s["nudgeUnit"]
    out["--logo-hover-tilt"] = (fmt(s["hoverTilt"]) if s["wiggle"] else "0") + "deg"
    out["--logo-case"] = s["case"]
    out["--logo-price-style"] = "italic" if s["priceItalic"] else "normal"
    out["--logo-monkey-style"] = "italic" if s["monkeyItalic"] else "normal"
    for mode in ("light", "dark"):
        for part in ("price", "monkey"):
            out[COLOR_VARS[mode][part]] = s["colors"][mode][part]
    return out


def _clamp(v, lo, hi, dflt):
    if v is None or isinstance(v, bool) or v == "":
        return dflt
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        try:
            v = float(v)  # numeric strings, like Number() in JS
        except (TypeError, ValueError):
            return dflt
        if not math.isfinite(v):
            return dflt
    return min(hi, max(lo, v))


def load_export(data, base: dict) -> dict:
    """logodev.js importJson(): unknown values keep base, numbers are clamped to the panel's ranges."""
    j = json.loads(data) if isinstance(data, str) else data
    if not isinstance(j, dict):
        raise SystemExit("not a JSON object")
    L = j.get("logo")
    if not isinstance(L, dict):
        raise SystemExit('no "logo" object (is this a pricemonkey-logo.json?)')
    s = json.loads(json.dumps(base))
    for key, _var, _unit, lo, hi in NUM:
        if key != "nudge":
            s[key] = _clamp(L.get(key), lo, hi, base[key])
    u = L.get("nudgeUnit")
    s["nudgeUnit"] = u if u in ("px", "em") else base["nudgeUnit"]
    lo, hi = NUDGE_RANGE[s["nudgeUnit"]]
    s["nudge"] = _clamp(L.get("nudge"), lo, hi, base["nudge"] if s["nudgeUnit"] == base["nudgeUnit"] else 0)
    for k in ("wiggle", "priceItalic", "monkeyItalic"):
        if isinstance(L.get(k), bool):
            s[k] = L[k]
    if L.get("case") in CASES:
        s["case"] = L["case"]
    C = L.get("colors") if isinstance(L.get("colors"), dict) else {}
    for mode in ("light", "dark"):
        for part in ("price", "monkey"):
            v = C.get(mode, {}).get(part) if isinstance(C.get(mode), dict) else None
            v = v.strip() if isinstance(v, str) else ""
            if RX_COLOR.match(v):
                s["colors"][mode][part] = v
    return s


def write_vars(css: str, new: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite each token in the first :root block (only those whose value changes)."""
    m = root_block(css)
    body, changed = m.group(1), []
    for name, value in new.items():
        rx = re.compile(r"(?<![\w-])(" + re.escape(name) + r"\s*:\s*)([^;]*)(;)")
        hit = rx.search(body)
        if not hit:
            raise SystemExit(f"{name} is not in base.css :root (was the logo refactor reverted?)")
        if hit.group(2).strip() == value:
            continue
        body = body[:hit.start(2)] + value + body[hit.end(2):]
        changed.append(f"{name}: {hit.group(2).strip()} -> {value}")
    return css[:m.start(1)] + body + css[m.end(1):], changed


def apply(export, css_path: pathlib.Path = BASE_CSS, dry_run: bool = False, out=sys.stdout) -> list[str]:
    css = css_path.read_text()
    base = from_vars(root_vars(css))
    s = load_export(export, base)
    new_css, changed = write_vars(css, to_vars(s))
    if not changed:
        print("base.css: nothing to change (the logo already matches this export)", file=out)
        return []
    for c in changed:
        print("  " + c, file=out)
    if dry_run:
        out.writelines(difflib.unified_diff(css.splitlines(True), new_css.splitlines(True),
                                            str(css_path), str(css_path) + " (new)"))
        print(f"dry run: {len(changed)} token(s) would change", file=out)
    else:
        css_path.write_text(new_css)
        print(f"base.css: {len(changed)} token(s) written", file=out)
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("json", type=pathlib.Path, help="pricemonkey-logo.json exported by the dev logo panel")
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    ap.add_argument("--css", type=pathlib.Path, default=BASE_CSS, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    apply(a.json.read_text(), a.css, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
