#!/usr/bin/env python3
"""Apply a type-panel export (pricemonkey-fonts.json) to the site in one step.

    .venv/bin/python scripts/apply_fonts.py pricemonkey-fonts.json            # write
    .venv/bin/python scripts/apply_fonts.py pricemonkey-fonts.json --dry-run  # only say what would change

The JSON comes from the dev type panel (agora/web/js/devtools.js, localhost only, ?dev=1 or Ctrl/Cmd+Shift+D).
What it writes, the same as the panel's live preview:
  * agora/web/index.html  the Google Fonts <link> href  -> the export's googleFontsUrl
  * agora/web/css/base.css the role tokens in :root      -> --sans/--serif/--mono families, --*-weight/-size/-ratio/
                                                            -lh/-tracking/-features, --sans-vs, --display-vs, --mono-vs,
                                                            --label-*
  * agora/web/css/*.css   every font size / line-height / tracking / weight of a role, rescaled from the old tokens
                          to the new ones (transform_css below mirrors transformCss() in devtools.js 1:1), plus the
                          appended features / label declarations
With an export equal to the current tokens nothing changes. Run it once per export: the tokens it writes become the
new "old" values, so a second run of the same file is a no-op. See docs/DEVTOOLS.md.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "agora" / "web"
ROLES = ("main", "display", "mono")
PREFIX = {"main": "sans", "display": "display", "mono": "mono"}
FAMILY_VAR = {"main": "--sans", "display": "--serif", "mono": "--mono"}
VS_VAR = {"main": "--sans-vs", "display": "--display-vs", "mono": "--mono-vs"}
LABEL_TRANSFORMS = ("none", "uppercase", "lowercase", "capitalize", "small-caps")


# ---------- numbers (devtools.js fmt(): floor(x*10^d + .5) / 10^d, shortest repr) ----------
def fmt(n: float, d: int) -> str:
    p = 10 ** d
    r = math.floor(n * p + 0.5) / p
    if r == int(r):
        return str(int(r))
    return repr(r)


def near(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


def em_str(n: float) -> str:
    return "0" if near(n, 0) else fmt(n, 4) + "em"


def track_num(v) -> float:
    s = str(v or "").strip()
    if not s or s == "normal":
        return 0.0
    m = re.match(r"-?[\d.]+", s)
    return float(m.group(0)) if m else 0.0


def parse_vs(v: str) -> dict:
    s = str(v or "").strip()
    if not s or s == "normal":
        return {}
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"[\"']([A-Za-z0-9]{4})[\"']\s+(-?[\d.]+)", s)}


def vs_string(axes: dict) -> str:
    parts = [f'"{t}" {fmt(float(v), 2)}' for t, v in (axes or {}).items() if t not in ("wght", "ital")]
    return ", ".join(parts) if parts else "normal"


# ---------- base.css :root ----------
def root_block(css: str) -> tuple[int, int]:
    m = re.search(r"(?m)^:root\s*\{", css)
    if not m:
        raise SystemExit("base.css has no :root block")
    end = css.index("}", m.end())
    return m.end(), end


def root_vars(css: str) -> dict:
    a, b = root_block(css)
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]*);", css[a:b])}


def baseline(tokens: dict) -> dict:
    need = ["--sans-size", "--display-size", "--mono-size"]
    missing = [n for n in need if n not in tokens]
    if missing:
        raise SystemExit(f"base.css :root lacks the type tokens {missing}; it predates the dev type panel")
    out = {}
    for k in ROLES:
        p = PREFIX[k]
        out[k] = {
            "weight": float(tokens.get(f"--{p}-weight", 400)),
            "size": float(tokens[f"--{p}-size"].replace("px", "")),
            "ratio": float(tokens.get(f"--{p}-ratio", 1.25)),
            "lineHeight": float(tokens.get(f"--{p}-lh", 1.4)),
            "letterSpacing": track_num(tokens.get(f"--{p}-tracking")),
            "features": (tokens.get(f"--{p}-features") or "normal").strip() or "normal",
            "axes": parse_vs(tokens.get(VS_VAR[k], "normal")),
        }
    out["main"]["labels"] = {
        "transform": (tokens.get("--label-transform") or "none").strip(),
        "letterSpacing": track_num(tokens.get("--label-tracking")),
        "maxSize": float((tokens.get("--label-max") or "12px").replace("px", "")),
    }
    return out


# ---------- the export ----------
SAFE = re.compile(r"[;{}<>]")


def clamp(v, lo, hi, dflt):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return dflt
    if not math.isfinite(n):
        return dflt
    return min(hi, max(lo, n))


def load_export(data: dict, base: dict, tokens: dict) -> dict:
    if not isinstance(data, dict) or "roles" not in data:
        raise SystemExit('not a type-panel export (no "roles")')
    if data.get("version") != 1:
        raise SystemExit(f"unsupported export version {data.get('version')!r}")
    url = data.get("googleFontsUrl") or ""
    if url and not url.startswith("https://fonts.googleapis.com/css2?"):
        raise SystemExit("googleFontsUrl must be a https://fonts.googleapis.com/css2? URL")
    s = {}
    for k in ROLES:
        b = base[k]
        r = data["roles"].get(k) or {}
        fam_now = tokens.get(FAMILY_VAR[k], "")
        m = re.match(r'\s*(?:"([^"]+)"|\'([^\']+)\'|([^,]+))\s*(?:,\s*(.*))?$', fam_now, re.S)
        cur_family = (m.group(1) or m.group(2) or m.group(3) or "").strip() if m else fam_now
        cur_fallback = (m.group(4) or "").strip() if m else ""
        family = re.sub(r"[\"';{}<>]", "", str(r.get("family") or cur_family)).strip() or cur_family
        fallback = SAFE.sub("", str(r["fallback"])) if isinstance(r.get("fallback"), str) else cur_fallback
        o = {
            "family": family, "fallback": fallback,
            "weight": clamp(r.get("weight"), 1, 1000, b["weight"]),
            "size": clamp(r.get("size"), 6, 200, b["size"]),
            "ratio": clamp(r.get("ratio"), 1.01, 2, b["ratio"]),
            "lineHeight": clamp(r.get("lineHeight"), 0.7, 3, b["lineHeight"]),
            "letterSpacing": clamp(r.get("letterSpacing"), -0.2, 0.5, b["letterSpacing"]),
            "features": (SAFE.sub("", r["features"]).strip() or "normal") if isinstance(r.get("features"), str) else b["features"],
            "axes": b["axes"],
        }
        if isinstance(r.get("axes"), dict):
            o["axes"] = {t: float(v) for t, v in r["axes"].items()
                         if re.fullmatch(r"[A-Za-z0-9]{4}", t) and isinstance(v, (int, float)) and math.isfinite(v)}
        if k == "main":
            bl, rl = b["labels"], r.get("labels") or {}
            o["labels"] = {
                "transform": rl.get("transform") if rl.get("transform") in LABEL_TRANSFORMS else bl["transform"],
                "letterSpacing": clamp(rl.get("letterSpacing"), -0.2, 0.5, bl["letterSpacing"]),
                "maxSize": clamp(rl.get("maxSize"), 6, 40, bl["maxSize"]),
            }
        s[k] = o
    return s


def new_tokens(s: dict) -> dict:
    def fam(r):
        return f'"{r["family"]}"' + (f", {r['fallback']}" if r["fallback"] else "")

    def track(n):
        return "normal" if near(n, 0) else em_str(n)

    v = {}
    for k in ROLES:
        r, p = s[k], PREFIX[k]
        v[FAMILY_VAR[k]] = fam(r)
        v[f"--{p}-weight"] = fmt(r["weight"], 0)
        v[f"--{p}-size"] = fmt(r["size"], 2) + "px"
        v[f"--{p}-ratio"] = fmt(r["ratio"], 3)
        v[f"--{p}-lh"] = fmt(r["lineHeight"], 3)
        v[f"--{p}-tracking"] = track(r["letterSpacing"])
        v[f"--{p}-features"] = r["features"] or "normal"
        v[VS_VAR[k]] = vs_string(r["axes"])
    lab = s["main"]["labels"]
    v["--label-transform"] = lab["transform"]
    v["--label-tracking"] = track(lab["letterSpacing"])
    v["--label-max"] = fmt(lab["maxSize"], 2) + "px"
    return v


def same_token(name: str, old: str, new: str) -> bool:
    """Equal in value (so '-.02em' == '-0.02em', '15px' == '15px', '"tnum" 1, "ss01" 1' kept as written)."""
    if old.strip() == new.strip():
        return True
    norm = lambda x: re.sub(r"\s+", " ", x.strip().replace("'", '"'))
    if norm(old) == norm(new):
        return True
    if name.endswith("-vs"):
        a, b = parse_vs(old), parse_vs(new)
        return a.keys() == b.keys() and all(near(a[t], b[t]) for t in a)
    num = re.compile(r"^(-?[\d.]+)(px|em)?$")
    ma, mb = num.match(old.strip()), num.match(new.strip())
    if ma and mb and (ma.group(2) or "") == (mb.group(2) or ""):
        return near(float(ma.group(1)), float(mb.group(1)))
    if name.endswith("-tracking"):
        return near(track_num(old), track_num(new))
    return False


def write_tokens(css: str, toks: dict) -> tuple[str, list]:
    a, b = root_block(css)
    block = css[a:b]
    changed = []
    have = {m.group(1) for m in re.finditer(r"(--[\w-]+)\s*:", block)}
    for name, val in toks.items():
        if name not in have:
            continue
        m = re.search(r"(" + re.escape(name) + r"\s*:\s*)([^;]*)(;)", block)
        if m and not same_token(name, m.group(2), val):
            block = block[:m.start(2)] + val + block[m.end(2):]
            changed.append(f"{name}: {m.group(2).strip()} -> {val}")
    return css[:a] + block + css[b:], changed


# ---------- the CSS transform (devtools.js transformCss, 1:1) ----------
def make_plan(base: dict, s: dict) -> dict:
    plan = {}
    for k in ROLES:
        b, n = base[k], s[k]
        plan[k] = {
            "oldSize": b["size"], "size": n["size"], "oldRatio": b["ratio"], "ratio": n["ratio"],
            "oldLh": b["lineHeight"], "lh": n["lineHeight"], "oldLs": b["letterSpacing"], "ls": n["letterSpacing"],
            "oldWeight": b["weight"], "weight": n["weight"],
            "oldFeatures": b["features"] or "normal", "features": n["features"] or "normal",
            "oldVs": vs_string(b["axes"]), "vs": vs_string(n["axes"]),
        }
    bl, nl = base["main"]["labels"], s["main"]["labels"]
    plan["labels"] = {"oldTransform": bl["transform"], "transform": nl["transform"], "oldLs": bl["letterSpacing"],
                      "ls": nl["letterSpacing"], "maxSize": bl["maxSize"]}
    return plan


RX_BLOCK = re.compile(r"([^{}]*)\{([^{}]*)\}")
RX_FAMILY = re.compile(r"(?<![\w-])font(?:-family)?\s*:[^;]*?var\(--(serif|mono|sans)\)")
RX_HAS_TYPE = re.compile(r"(?<![\w-])(?:font|font-size|line-height|letter-spacing|font-weight)\s*:")
RX_DECL = re.compile(r"(?<![\w-])(font|font-size|line-height|letter-spacing|font-weight)(\s*:\s*)([^;]*?)(\s*(?:!important)?\s*)(?=;|$)")
RX_SHORT = re.compile(r"^((?:(?:italic|normal|oblique|small-caps|bold|bolder|lighter|\d{3})\s+)*)((?:clamp|min|max|calc)\([^()]*\)|[\d.]+(?:px|em|rem|%))(?:(\s*/\s*)([\d.]+(?:px|em|%)?|normal))?(\s+)([\s\S]+)$")
ROLE_OF = {"serif": "display", "mono": "mono", "sans": "main"}
SKIP_SEL = {":root", "body", "html", "html, body"}
RX_SKIP_LIST = re.compile(r"(^|,\s*)(:root|body|html)(\s*,|$)")


def clean_sel(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"/\*[\s\S]*?\*/", "", s)).strip()


def size_noop(p) -> bool:
    return near(p["size"], p["oldSize"]) and near(p["ratio"], p["oldRatio"])


def new_px(n: float, p) -> float:
    k = math.log(p["ratio"]) / math.log(p["oldRatio"])
    return p["size"] * math.pow(n / p["oldSize"], k)


def scale_size(v: str, p) -> str:
    if size_noop(p):
        return v

    def rep(m):
        n, u = float(m.group(1)), m.group(2)
        return fmt(new_px(n, p), 2) + "px" if u == "px" else fmt(n * p["size"] / p["oldSize"], 3) + "vw"

    return re.sub(r"(-?[\d.]+)(px|vw)\b", rep, v)


def px_of(v: str):
    m = re.match(r"^\s*([\d.]+)px\s*$", v)
    return float(m.group(1)) if m else None


def scale_lh(v: str, p, old_px) -> str:
    f = p["lh"] / p["oldLh"]
    sf = new_px(old_px, p) / old_px if old_px is not None else p["size"] / p["oldSize"]
    if near(f, 1) and (size_noop(p) or near(sf, 1)):
        return v
    t = v.strip()
    m = re.fullmatch(r"([\d.]+)", t)
    if m:
        return v if near(f, 1) else fmt(float(m.group(1)) * f, 3)
    m = re.fullmatch(r"([\d.]+)px", t)
    if m:
        return fmt(float(m.group(1)) * sf * f, 2) + "px"
    m = re.fullmatch(r"([\d.]+)%", t)
    if m:
        return v if near(f, 1) else fmt(float(m.group(1)) * f, 1) + "%"
    return v


def add_ls(v: str, d: float) -> str:
    if near(d, 0):
        return v
    t = v.strip()
    if t in ("normal", "0"):
        return em_str(d)
    m = re.fullmatch(r"(-?[\d.]+)em", t)
    if m:
        return em_str(float(m.group(1)) + d)
    return f"calc({t} + {em_str(d)})"


def js_round(x: float) -> int:
    return math.floor(x + 0.5)


def adj_weight(v: str, d: float) -> str:
    if near(d, 0):
        return v
    return re.sub(r"\b(\d{3,4})\b", lambda m: str(min(1000, max(1, js_round(float(m.group(1)) + d)))), v)


def append_decl(body: str, decl: str) -> str:
    trail = re.search(r"\s*$", body).group(0)
    core = body[: len(body) - len(trail)]
    sep = " " if core.strip() == "" else (" " if core.rstrip().endswith(";") else "; ")
    return core + sep + decl + ";" + (trail or " ")


def transform_css(text: str, plan: dict) -> str:
    role_by_sel: dict = {}
    for m in RX_BLOCK.finditer(text):
        fm = RX_FAMILY.search(m.group(2))
        if not fm:
            continue
        for sel in [x.strip() for x in clean_sel(m.group(1)).split(",") if x.strip()]:
            role_by_sel.setdefault(sel, ROLE_OF[fm.group(1)])
    L = plan["labels"]
    labels_on = L["transform"] != L["oldTransform"] or not near(L["ls"], L["oldLs"])

    def block(m):
        whole, sel_raw, body = m.group(0), m.group(1), m.group(2)
        sel = clean_sel(sel_raw)
        if not sel or sel.startswith("@") or sel in SKIP_SEL or RX_SKIP_LIST.search(sel):
            return whole
        if not RX_HAS_TYPE.search(body):
            return whole
        fm = RX_FAMILY.search(body)
        fam_role = ROLE_OF[fm.group(1)] if fm else None
        role = fam_role or next((role_by_sel[x.strip()] for x in sel.split(",") if x.strip() in role_by_sel), None) or "main"
        p = plan[role]
        old_px = None
        for d in RX_DECL.finditer(body):
            if d.group(1) == "font-size":
                v = px_of(d.group(3))
                old_px = v if v is not None else old_px
            elif d.group(1) == "font":
                s = RX_SHORT.match(d.group(3))
                if s:
                    v = px_of(s.group(2))
                    old_px = v if v is not None else old_px
        is_label = role == "main" and labels_on and old_px is not None and old_px <= L["maxSize"] + 1e-9
        ls_delta = (p["ls"] - p["oldLs"]) + ((L["ls"] - L["oldLs"]) if is_label else 0)
        w_delta = p["weight"] - p["oldWeight"]
        has_ls = False

        def decl(d):
            nonlocal has_ls
            prop, colon, val, imp = d.group(1), d.group(2), d.group(3), d.group(4)
            nv = val
            if prop == "font-size":
                nv = scale_size(val, p)
            elif prop == "line-height":
                nv = scale_lh(val, p, old_px)
            elif prop == "letter-spacing":
                has_ls = True
                nv = add_ls(val, ls_delta)
            elif prop == "font-weight":
                nv = adj_weight(val, w_delta)
            elif prop == "font":
                s = RX_SHORT.match(val)
                if not s:
                    return d.group(0)
                pre, size, slash, lh, gap, fam = s.groups()
                px = px_of(size)
                nv = adj_weight(pre, w_delta) + scale_size(size, p) + (slash + scale_lh(lh, p, px) if slash else "") + gap + fam
            return d.group(0) if nv == val else prop + colon + nv + imp

        out = RX_DECL.sub(decl, body)
        if not has_ls:
            if fam_role and fam_role != "main" and (not near(p["ls"], p["oldLs"]) or not near(plan["main"]["ls"], plan["main"]["oldLs"])):
                out = append_decl(out, f"letter-spacing: {em_str(p['ls'] - p['oldLs'])}")
            elif is_label and not near(L["ls"], L["oldLs"]):
                out = append_decl(out, f"letter-spacing: {em_str(plan['main']['ls'] + L['ls'])}")
        if fam_role and fam_role != "main" and p["features"] != p["oldFeatures"]:
            out = append_decl(out, f"font-feature-settings: {p['features']}")
        if fam_role == "mono" and p["vs"] != p["oldVs"]:
            out = append_decl(out, f"font-variation-settings: {p['vs']}")
        if is_label and L["transform"] != L["oldTransform"]:
            out = append_decl(out, "font-variant-caps: all-small-caps" if L["transform"] == "small-caps" else f"text-transform: {L['transform']}")
        return whole if out == body else sel_raw + "{" + out + "}"

    return RX_BLOCK.sub(block, text)


# ---------- index.html ----------
RX_FONT_LINK = re.compile(r'(<link rel="stylesheet" href=")(https://fonts\.googleapis\.com/css2\?[^"]*)(">)')


def write_link(html: str, url: str) -> tuple[str, bool]:
    m = RX_FONT_LINK.search(html)
    if not m:
        raise SystemExit("index.html has no Google Fonts css2 <link rel=\"stylesheet\">")
    if m.group(2).replace("&amp;", "&") == url:
        return html, False
    return html[:m.start(2)] + url.replace('"', "%22") + html[m.end(2):], True


def apply(data: dict, web: pathlib.Path = WEB, dry_run: bool = False, out=sys.stdout) -> list:
    base_css_p = web / "css" / "base.css"
    base_css = base_css_p.read_text()
    tokens = root_vars(base_css)
    base = baseline(tokens)
    s = load_export(data, base, tokens)
    plan = make_plan(base, s)
    changed = []
    for p in sorted((web / "css").glob("*.css")):
        if p.name == "devtools.css":
            continue
        src = base_css if p == base_css_p else p.read_text()
        dst = transform_css(src, plan)
        notes = []
        if p == base_css_p:
            dst, notes = write_tokens(dst, new_tokens(s))
        if dst != src:
            changed.append(p)
            n_rules = sum(1 for a, b in zip(src.splitlines(), dst.splitlines()) if a != b)
            print(f"{'would update' if dry_run else 'updated'} {p.relative_to(web.parent.parent) if web.parent.parent in p.parents else p}: {n_rules} line(s)", file=out)
            for n in notes:
                print(f"    {n}", file=out)
            if not dry_run:
                p.write_text(dst)
    url = data.get("googleFontsUrl")
    if url:
        idx = web / "index.html"
        html, did = write_link(idx.read_text(), url)
        if did:
            changed.append(idx)
            print(f"{'would update' if dry_run else 'updated'} the Google Fonts link in index.html -> {url}", file=out)
            if not dry_run:
                idx.write_text(html)
    if not changed:
        print("nothing to change: the export matches the site's tokens", file=out)
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("json", help="pricemonkey-fonts.json exported from the dev type panel ('-' for stdin)")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    ap.add_argument("--web", default=str(WEB), help="the web/ folder (default: agora/web)")
    a = ap.parse_args(argv)
    raw = sys.stdin.read() if a.json == "-" else pathlib.Path(a.json).expanduser().read_text()
    apply(json.loads(raw), pathlib.Path(a.web), dry_run=a.dry_run)
    if not a.dry_run:
        print("done. Reload the page; the dev panel's baseline is now these values (its saved B equals A).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
