"""Live-mode viewer logic (agora/web/js), checked with node: rejected offers leave the line, a 429 on one
page does not end a live hunt, a stalled stream finishes, "checking N more shops" never outlives the hunt,
logos and placeholders are never cut out. Cases come from the first live test streams."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_live_ui_store_logic():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "live_ui.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_line_handles_removed_offers_and_quiet_late_labels():
    js = (ROOT / "agora" / "web" / "js" / "line.js").read_text()
    assert "on('offer-removed'" in js
    css = (ROOT / "agora" / "web" / "css" / "line.css").read_text()
    # the "late" word is only drawn where line.js found room for it
    assert "\n.ln-o.late::after" not in css and ".late-lab::after" in css


def test_line_plates_float_on_pins_and_the_pick_says_why():
    """Plates float above the line on a stem (the beads and ticks under them stay in view), are 64-84 px
    instead of 104, and the ringed pick carries a short "why" note with its reasons on hover or tap."""
    js = (ROOT / "agora" / "web" / "js" / "line.js").read_text()
    css = (ROOT / "agora" / "web" / "css" / "line.css").read_text()
    assert "const LIFT = " in js and "floorAt(" in js
    assert "return o.el.classList.contains('mono') ? 64 : 80;" in js
    assert ".ln-o.full { --fw: 80px; --fh: 80px;" in css
    # the note is placed after the plates (never evicts one) and the beads keep clear of it
    assert "function pickWhy(" in js and "function placeWhy(" in js
    assert "['cap', 'body', 'ring', 'note']" in js
    assert ".ln-why-more" in css and ".ln-turning .ln-why" in css
