"""Judges' round on the results page (docs/JUDGE_FEEDBACK.md F5-F7), checked with node: the line's robust
price domain, "not this" in the list, and the shop's own currency."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_results_judges():
    r = subprocess.run([NODE, str(ROOT / "tests" / "web" / "results_judges.test.mjs")], capture_output=True,
                       text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout
