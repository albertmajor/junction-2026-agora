"""Offline tests for agora.fx."""
from __future__ import annotations

import json
import time

import pytest

from agora import fx


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setattr(fx, "_rates", None)
    yield tmp_path


def test_static_fallback():
    assert fx.to_eur(100, "EUR") == 100.0
    assert fx.to_eur(112, "USD") == 100.0
    assert fx.to_eur(None, "EUR") is None
    assert fx.to_eur(10, "XXX") is None
    assert fx.source() == "static"


def test_symbols_and_kr_by_domain():
    assert fx.normalize_currency("€") == "EUR"
    assert fx.normalize_currency("£") == "GBP"
    assert fx.normalize_currency("kr", "blocket.se") == "SEK"
    assert fx.normalize_currency("kr", "finn.no") == "NOK"
    assert fx.normalize_currency("kr.", "dba.dk") == "DKK"
    assert fx.normalize_currency(None, "tori.fi") == "EUR"
    assert fx.normalize_currency("usd") == "USD"


def test_cached_rates_win(offline):
    (offline / "fx.json").write_text(json.dumps({"saved_at": time.time(), "rates": {"USD": 2.0}}))
    assert fx.to_eur(100, "USD") == 50.0
    assert fx.source() == "frankfurter"
    assert fx.to_eur(11, "SEK") == 1.0   # static fills currencies the cache lacks
