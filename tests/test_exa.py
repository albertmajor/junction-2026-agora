"""Exa look-alike lane: offline, with a mocked transport and a saved response."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import exa
from agora.hunt import hunt
from agora.models import Event, Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"
RESP = json.loads((FIX / "exa_find_similar.json").read_text())


@pytest.fixture(autouse=True)
def reset():
    yield
    exa._transport = None


def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setattr(exa, "_key", lambda: None)
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)

    def boom(req):
        raise AssertionError("network used without a key")
    exa._transport = httpx.MockTransport(boom)
    assert asyncio.run(exa.find_similar("https://shop.eu/x")) == []
    assert exa.enabled() is False


def test_find_similar_posts_and_caches(monkeypatch):
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    monkeypatch.setattr(exa, "_key", lambda: "test-key")
    calls = []

    def handler(req: httpx.Request):
        calls.append((str(req.url), json.loads(req.content), req.headers.get("x-api-key")))
        return httpx.Response(200, json=RESP)
    exa._transport = httpx.MockTransport(handler)
    got = asyncio.run(exa.find_similar("https://dakauf.eu/x", n=8, exclude_domains=["mpb.com"]))
    assert [r["url"] for r in got][:2] == ["https://www.kamerastore.com/products/sony-a7-iii-body",
                                           "https://www.fotoaparat.cz/sony-a7-iii-telo"]
    assert len(got) == 3                                       # junk URL dropped
    url, body, key = calls[0]
    assert url == "https://api.exa.ai/findSimilar" and key == "test-key"
    assert body == {"url": "https://dakauf.eu/x", "numResults": 8, "excludeSourceDomain": True,
                    "excludeDomains": ["mpb.com"]}
    asyncio.run(exa.find_similar("https://dakauf.eu/x", n=8, exclude_domains=["mpb.com"]))
    assert len(calls) == 1                                     # second call from the disk cache


def test_hunt_opens_a_lookalike_lane_after_two_good_eu_offers(monkeypatch):
    sources = ["https://a-shop.fi/a7", "https://b-shop.de/a7", "https://c-shop.com/a7"]

    async def disc(need):
        yield Event("lane", {"lane": "new", "queries": ["q"]})
        for u in sources:
            yield Event("source", {"url": u, "lane": "new"})

    async def read(url, need):
        dom = url.split("/")[2]
        cur = "USD" if dom.endswith(".com") and "kamera" not in dom else "EUR"
        return Offer(url=url, source=dom, title="Sony A7 III body", price=1000.0, currency=cur,
                     price_eur=1000.0, condition="new", read_via="jsonld")

    async def fake_similar(url, n=8, exclude_domains=None):
        assert "a-shop.fi" in exclude_domains
        return [r for r in exa._results(RESP)]

    monkeypatch.setattr(exa, "enabled", lambda: True)
    monkeypatch.setattr(exa, "find_similar", fake_similar)

    async def go():
        return [e async for e in hunt("sony a7 iii body", discover=disc, read=read, persist=False)]
    events = asyncio.run(go())
    lane = next(e for e in events if e.type == "lane" and e.data["lane"] == "lookalike")
    assert lane.data["via"] == "exa" and lane.data["queries"][0].startswith("like ")
    looks = [e for e in events if e.type == "source" and e.data.get("lane") == "lookalike"]
    assert {e.data["domain"] for e in looks} == {"kamerastore.com", "fotoaparat.cz", "dakauf.eu"}
    assert all(e.data["via"] == "exa" and e.data["similar_to"] for e in looks)
    offers = [e for e in events if e.type == "offer"]
    assert any("kamerastore.com" in e.data["offer"]["url"] for e in offers)
    assert events[-1].type == "done"
