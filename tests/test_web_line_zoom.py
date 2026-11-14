"""THE LINE's zoom (agora/web/js/line.js), checked with node: the robust default fit, the price tag's drag
curve (the tag stays under the finger while the axis follows it) and readable tick steps."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_line_zoom_logic():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "line_zoom.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout
