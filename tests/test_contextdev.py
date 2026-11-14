"""Offline tests for agora.contextdev: limiter, disk cache, ledger, request shapes. No live calls."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    cd._reset_ledger()
    yield
    cd._transport = None


def mock(handler):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    cd._transport = httpx.MockTransport(wrapped)
    return calls


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_search_body_cache_and_ledger():
    calls = mock(lambda r: httpx.Response(200, json=fixture("search.json")))
    res = asyncio.run(cd.search("sony a7 iii", n=5, highlights=True, country="FI", exclude_domains=["reddit.com"]))
    assert res and res[0]["url"].startswith("https://")
    body = json.loads(calls[0].content)
    assert body == {"query": "sony a7 iii", "numResults": 5, "country": "fi", "excludeDomains": ["reddit.com"],
                    "highlightsOptions": {"enabled": True, "maxCharacters": 1200}}
    assert calls[0].headers["authorization"] == "Bearer test-key-not-real"
    # second identical call: served from disk cache, no new request
    asyncio.run(cd.search("sony a7 iii", n=5, highlights=True, country="FI", exclude_domains=["reddit.com"]))
    assert len(calls) == 1
    led = cd.ledger()
    assert led["requests"] == 1 and led["cache_hits"] == 1
    assert led["credits_used"] == fixture("search.json")["key_metadata"]["credits_consumed"]
    assert led["all_time"]["requests"] == 1


def test_product_parses_fixture_and_not_product_page():
    mock(lambda r: httpx.Response(200, json=fixture("product3.json")))
    p = asyncio.run(cd.product("https://www.ebay.com/p/12027034774"))
    assert p["price"] == 789.99 and p["currency"] == "USD"
    assert cd.parse_product_response({"product": {"data": {"isProductPage": False, "product": None}}}) is None


def test_extract_uses_jsonparams_and_returns_data():
    calls = mock(lambda r: httpx.Response(200, json={"json": {"requested": True, "success": True,
                                                              "data": {"page_type": "listing", "offers": []}}}))
    out = asyncio.run(cd.extract("https://tori.fi/x", {"type": "object"}, "be exact"))
    body = json.loads(calls[0].content)
    assert body["formats"] == {"json": True}
    assert body["jsonParams"] == {"schema": {"type": "object"}, "instructions": "be exact"}
    assert out == {"page_type": "listing", "offers": []}


def test_extract_failure_returns_none():
    mock(lambda r: httpx.Response(200, json={"json": {"success": False, "data": None}}))
    assert asyncio.run(cd.extract("https://x.fi/a", {"type": "object"})) is None


def test_offline_never_calls_network(monkeypatch):
    calls = mock(lambda r: httpx.Response(200, json={}))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    with pytest.raises(cd.ContextDevError):
        asyncio.run(cd.search("anything"))
    assert calls == []


def test_429_drains_bucket_then_retries(monkeypatch):
    seq = iter([httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(200, json={"results": []})])
    calls = mock(lambda r: next(seq))
    monkeypatch.setattr(cd, "RATE_PER_MIN", 6000)   # keep the test fast
    assert asyncio.run(cd.search("q")) == []
    assert len(calls) == 2


def test_country_rejected_retries_without_country():
    def handler(r):
        body = json.loads(r.content)
        if "country" in body:
            return httpx.Response(400, json={"message": "unsupported country"})
        return httpx.Response(200, json={"results": [{"url": "https://a.fi"}]})
    calls = mock(handler)
    assert asyncio.run(cd.search("q", country="zz"))[0]["url"] == "https://a.fi"
    assert len(calls) == 2


def test_errors_never_leak_the_key():
    mock(lambda r: httpx.Response(401, text="bad auth"))
    with pytest.raises(cd.ContextDevError) as e:
        asyncio.run(cd.product("https://a.fi/p"))
    assert "test-key-not-real" not in str(e.value)


def test_token_bucket_is_shared_and_refills(monkeypatch):
    t = 1000.0
    waits = [cd._take_token(now=t) for _ in range(12)]
    assert waits[:10] == [0.0] * 10           # full bucket = burst of 10
    assert waits[10] > 0                       # 11th must wait ~6 s
    assert 5 < waits[10] <= 6.01
    assert cd._take_token(now=t + 6.1) == 0.0  # one token refilled after 6 s


def test_highlight_text():
    r = {"highlights": {"highlights": ["Price 1 299 €", "In stock"], "code": "SUCCESS"}}
    assert cd.highlight_text(r) == "Price 1 299 € … In stock"
    assert cd.highlight_text({"highlights": {"highlights": None, "code": "NOT_REQUESTED"}}) == ""


def test_create_monitor_body():
    calls = mock(lambda r: httpx.Response(201, json={"id": "mon_1", "webhook": {"secret": "s"}}))
    m = asyncio.run(cd.create_monitor("agora w1", url="https://shop.fi/p", instructions="alert if price < 900",
                                      webhook="https://hook", every_hours=6))
    body = json.loads(calls[0].content)
    assert m["id"] == "mon_1"
    assert body["target"] == {"type": "page", "url": "https://shop.fi/p", "instructions": "alert if price < 900"}
    assert body["schedule"] == {"type": "interval", "frequency": 6, "unit": "hours"}
    assert body["webhook"]["url"] == "https://hook"
