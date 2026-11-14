"""UI round B viewer logic (agora/web/js), checked with node on the recorded city-bike hunt: every listing in
one group, the better ones with reasons, filters, the market line, and a summary that credits Context.dev search."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_listings_logic():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "listings.test.mjs")], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout
