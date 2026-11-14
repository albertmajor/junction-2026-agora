"""The listing dialog (agora/web/js/sheet.js), checked with node: ← / → follow the list order, and the gallery."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_sheet_logic():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "sheet.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout
