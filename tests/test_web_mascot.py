"""The mascot's animated moods (agora/web/js/mascot.js), checked with node: searching over the live log,
thinking while the first answer is costed, found-it once on the final verdict, still frames for reduced motion."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_mascot_moods():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "mascot.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_start_screen_mascot_is_the_idle_animation_and_lazy():
    html = (ROOT / "agora" / "web" / "index.html").read_text()
    assert 'class="mk start-monkey"' in html and "monkey-idle.webp" in html and 'loading="lazy"' in html
    assert "/web/css/mascot.css" in html
    css = (ROOT / "agora" / "web" / "css" / "mascot.css").read_text()
    assert "prefers-reduced-motion" in css
