"""Clarify first (agora/web/js/clarify.js), checked with node: an unsure typed search asks what you are looking
for before hunting (options + "Search exactly …"), a clear one hunts as before, tree hunts / examples / recordings
never ask, and the answer is remembered for the same words."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_clarify_decision():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "clarify.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_clarify_card_styles_are_accessible():
    css = (ROOT / "agora" / "web" / "css" / "intent.css").read_text()
    assert ".cl-opt:focus-visible" in css and "prefers-reduced-motion" in css
    js = (ROOT / "agora" / "web" / "js" / "main.js").read_text()
    assert "load('clarify')" in js
