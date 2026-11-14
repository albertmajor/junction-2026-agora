"""Every test runs offline, against a throwaway cache dir and database."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("AGORA_DB", str(tmp_path / "agora-test.db"))
    # direct marketplace search pages (agora.marketplaces) off by default: older tests count the sources a web
    # search finds; tests/test_marketplaces.py turns them on
    monkeypatch.setenv("AGORA_DIRECT", "0")
    monkeypatch.delenv("AGORA_NTFY_TOPIC", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
