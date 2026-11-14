"""Dev type panel (agora/web/js/devtools.js) + scripts/apply_fonts.py: the panel only loads locally, its unit cases
pass in node, and apply_fonts.py writes exactly the CSS the panel previewed (same transform, byte for byte)."""
import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "agora" / "web"
NODE = shutil.which("node")
spec = importlib.util.spec_from_file_location("apply_fonts", ROOT / "scripts" / "apply_fonts.py")
apply_fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply_fonts)

EXPORT = {
    "version": 1,
    "roles": {
        "main": {"family": "Geist", "fallback": "system-ui, sans-serif", "weight": 420, "weights": [400, 500],
                 "axes": {}, "size": 15.5, "ratio": 1.2, "letterSpacing": -0.005, "lineHeight": 1.45,
                 "features": '"tnum" 1, "ss01" 1, "cv11" 1',
                 "labels": {"transform": "uppercase", "letterSpacing": 0.05, "maxSize": 11}},
        "display": {"family": "Newsreader", "fallback": "Georgia, serif", "weight": 380, "weights": [400],
                    "axes": {"opsz": 72}, "size": 70, "ratio": 1.333, "letterSpacing": -0.025, "lineHeight": 1.0,
                    "features": '"lnum" 1'},
        "mono": {"family": "JetBrains Mono", "fallback": "ui-monospace, monospace", "weight": 400, "weights": [400, 500],
                 "axes": {}, "size": 12.5, "ratio": 1.25, "letterSpacing": 0, "lineHeight": 1.5, "features": '"zero" 1'},
    },
    "googleFontsUrl": "https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,200..800;1,6..72,200..800"
                      "&family=Geist:ital,wght@0,100..900;1,100..900&family=JetBrains+Mono:wght@100..800&display=swap",
}


def test_devtools_load_only_on_localhost():
    main = (WEB / "js" / "main.js").read_text()
    line = next(l for l in main.splitlines() if "devtools.js" in l)
    assert line.startswith("if (/^(localhost|127\\.0\\.0\\.1|\\[::1\\])$/.test(location.hostname)) import('./devtools.js')")
    js = (WEB / "js" / "devtools.js").read_text()
    assert "if (started || !isLocal()) return;" in js
    assert "devtools" not in (WEB / "index.html").read_text()
    # the panel only talks to the Google Fonts CSS API
    hosts = {h for h in __import__("re").findall(r"https://([a-z0-9.-]+)/", js)}
    assert hosts == {"fonts.googleapis.com"}, hosts


def test_base_css_type_tokens_keep_todays_look():
    css = (WEB / "css" / "base.css").read_text()
    t = apply_fonts.root_vars(css)
    assert t["--sans-size"] == "15px" and t["--sans-lh"] == "1.5" and t["--sans-weight"] == "400"
    assert t["--display-size"] == "64px" and t["--display-lh"] == "1.02" and t["--display-tracking"] == "-.02em"
    assert t["--mono-size"] == "12px"
    assert "font: var(--sans-weight) var(--sans-size)/var(--sans-lh) var(--sans);" in css


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_devtools_unit_cases_in_node():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "devtools.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_apply_script_writes_what_the_panel_previews(tmp_path):
    exp = tmp_path / "pricemonkey-fonts.json"
    exp.write_text(json.dumps(EXPORT))
    files = sorted(str(p) for p in (WEB / "css").glob("*.css") if p.name != "devtools.css")
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "devtools.test.mjs"), "transform", str(exp), *files],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    base = apply_fonts.baseline(apply_fonts.root_vars((WEB / "css" / "base.css").read_text()))
    tokens = apply_fonts.root_vars((WEB / "css" / "base.css").read_text())
    s = apply_fonts.load_export(EXPORT, base, tokens)
    plan = apply_fonts.make_plan(base, s)
    changed = 0
    for f in files:
        src = pathlib.Path(f).read_text()
        py = apply_fonts.transform_css(src, plan)
        assert py == js[f], f"{f}: python and js transforms differ"
        changed += py != src
    assert changed >= 5
    assert apply_fonts.new_tokens(s) == js["__vars"]


def test_apply_end_to_end_on_a_copy(tmp_path, capsys):
    web = tmp_path / "web"
    shutil.copytree(WEB, web, ignore=shutil.ignore_patterns("assets"))
    before = {p.name: p.read_text() for p in (web / "css").glob("*.css")}
    apply_fonts.apply(EXPORT, web, dry_run=True)
    assert {p.name: p.read_text() for p in (web / "css").glob("*.css")} == before   # dry run writes nothing
    apply_fonts.apply(EXPORT, web)
    css = (web / "css" / "base.css").read_text()
    t = apply_fonts.root_vars(css)
    assert t["--sans"] == '"Geist", system-ui, sans-serif'
    assert t["--serif"] == '"Newsreader", Georgia, serif' and t["--display-vs"] == '"opsz" 72'
    assert t["--sans-size"] == "15.5px" and t["--display-size"] == "70px" and t["--mono-features"] == '"zero" 1'
    assert t["--label-transform"] == "uppercase"
    assert EXPORT["googleFontsUrl"] in (web / "index.html").read_text()
    # second run of the same export: the tokens are now the baseline, nothing moves
    snap = {p.name: p.read_text() for p in (web / "css").glob("*.css")}
    capsys.readouterr()
    assert apply_fonts.apply(EXPORT, web) == []
    assert {p.name: p.read_text() for p in (web / "css").glob("*.css")} == snap


def test_apply_with_current_values_changes_nothing(tmp_path):
    web = tmp_path / "web"
    shutil.copytree(WEB, web, ignore=shutil.ignore_patterns("assets"))
    tokens = apply_fonts.root_vars((web / "css" / "base.css").read_text())
    same = {"version": 1, "roles": {}}
    assert apply_fonts.apply(same, web) == []
    assert apply_fonts.root_vars((web / "css" / "base.css").read_text()) == tokens


def test_apply_refuses_foreign_font_hosts():
    bad = dict(EXPORT, googleFontsUrl="https://evil.example/css2?family=X")
    with pytest.raises(SystemExit):
        apply_fonts.apply(bad, WEB, dry_run=True)
