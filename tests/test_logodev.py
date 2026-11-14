"""Dev logo panel (agora/web/js/logodev.js) + scripts/apply_logo.py: the panel only loads locally, its unit cases pass
in node, apply_logo.py writes exactly the tokens the panel previews, idempotently, and --dry-run writes nothing."""
import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "agora" / "web"
NODE = shutil.which("node")
spec = importlib.util.spec_from_file_location("apply_logo", ROOT / "scripts" / "apply_logo.py")
apply_logo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply_logo)

EXPORT = {
    "version": 1,
    "logo": {"markWidth": 46, "gap": 10.5, "tilt": -2.5, "hoverTilt": -9, "size": 29.4, "weight": 450, "hoverWeight": 560,
             "tracking": -0.012, "center": 0.35, "nudge": 0.75, "nudgeUnit": "px", "footerWidth": 21, "footerNudge": -0.5,
             "wiggle": True, "case": "none", "priceItalic": True, "monkeyItalic": False,
             "colors": {"light": {"price": "#222018", "monkey": "#5a3d14"}, "dark": {"price": "var(--ink)", "monkey": "#e2c49a"}}},
}


def test_logodev_loads_only_on_localhost():
    main = (WEB / "js" / "main.js").read_text()
    line = next(l for l in main.splitlines() if "logodev.js" in l)
    assert line.startswith("if (/^(localhost|127\\.0\\.0\\.1|\\[::1\\])$/.test(location.hostname)) import('./logodev.js')")
    js = (WEB / "js" / "logodev.js").read_text()
    assert "if (started || !isLocal()) return;" in js
    assert "logodev" not in (WEB / "index.html").read_text()
    assert "https://" not in js  # talks to nothing outside the site


def test_logo_markup_and_todays_tokens():
    html = (WEB / "index.html").read_text()
    # no whitespace between the mark and the wordmark: the gap is --logo-gap only
    assert '<img class="logo-mark" src="/web/assets/brand/logo.svg" width="40" height="34" alt=""><span class="brand">' in html
    t = apply_logo.root_vars((WEB / "css" / "base.css").read_text())
    # the owner's applied logo (docs/pricemonkey-logo.json)
    assert t["--logo-mark-w"] == "48.5px" and t["--logo-gap"] == "8.75px" and t["--logo-size"] == "28.47px"
    assert t["--logo-center"] == "0.2325em" and t["--logo-nudge"] == "0.25px" and t["--logo-hover-tilt"] == "5.5deg"
    assert t["--logo-monkey-light"] == "#4E3818" and t["--logo-monkey-dark"] == "#D9B98C"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_logodev_unit_cases_in_node():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "logodev.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("export", [EXPORT, {"logo": {"size": 500, "weight": "x", "gap": None, "nudge": 3, "nudgeUnit": "em",
                                                      "wiggle": False, "case": "loud", "colors": {"dark": {"monkey": "red"}}}}])
def test_apply_script_writes_what_the_panel_previews(tmp_path, export):
    exp = tmp_path / "pricemonkey-logo.json"
    exp.write_text(json.dumps(export))
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "logodev.test.mjs"), "vars", str(exp)],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    js_vars = json.loads(r.stdout)
    css = (WEB / "css" / "base.css").read_text()
    py_vars = apply_logo.to_vars(apply_logo.load_export(export, apply_logo.from_vars(apply_logo.root_vars(css))))
    assert py_vars == js_vars


def test_apply_writes_tokens_idempotently_and_dry_run_writes_nothing(tmp_path, capsys):
    css_path = tmp_path / "base.css"
    original = (WEB / "css" / "base.css").read_text()
    css_path.write_text(original)
    # the panel's own default export changes nothing
    base = apply_logo.from_vars(apply_logo.root_vars(original))
    assert apply_logo.apply(json.dumps({"logo": base}), css_path) == []
    assert apply_logo.apply(json.dumps(EXPORT), css_path, dry_run=True)
    assert css_path.read_text() == original
    changed = apply_logo.apply(json.dumps(EXPORT), css_path)
    assert "--logo-mark-w: 48.5px -> 46px" in changed and "--logo-monkey-style: italic -> normal" in changed
    after = css_path.read_text()
    t = apply_logo.root_vars(after)
    assert t["--logo-size"] == "29.4px" and t["--logo-center"] == "0.35em" and t["--logo-hover-tilt"] == "-9deg"
    assert t["--logo-price-dark"] == "var(--ink)" and t["--logo-monkey-light"] == "#5a3d14"
    # only the :root tokens moved; the rules and the dark blocks are untouched
    assert after.replace(apply_logo.root_block(after).group(1), "") == original.replace(apply_logo.root_block(original).group(1), "")
    assert apply_logo.apply(json.dumps(EXPORT), css_path) == []   # idempotent
    assert css_path.read_text() == after
