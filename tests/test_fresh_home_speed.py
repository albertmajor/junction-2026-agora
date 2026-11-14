"""Freshness (maxAgeMs), home country lane, per-domain read budgets and the hunt budget. Offline."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import reader
from agora.domainstats import SLOW_WALL_S, SlowDomains
from agora.models import Event, Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def live_mock(tmp_path, monkeypatch):
    """contextdev online against a MockTransport (never the network)."""
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    cd._reset_ledger()
    calls: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        calls.append(body)
        if "formats" in body and body["formats"].get("product"):
            return httpx.Response(200, json=json.loads((FIX / "product3.json").read_text()))
        if "formats" in body:
            return httpx.Response(200, json={"json": {"success": True, "data": {"page_type": "listing", "offers": []}}})
        return httpx.Response(200, json=json.loads((FIX / "search.json").read_text()))
    cd._transport = httpx.MockTransport(handler)
    yield calls
    cd._transport = None


# ------------------------------------------------------------------ freshness

def test_product_max_age_zero_sends_maxagems_and_skips_our_cache(live_mock):
    url = "https://www.ebay.com/p/12027034774"
    asyncio.run(cd.product(url))                       # hunt: default, cached
    asyncio.run(cd.product(url))
    assert len(live_mock) == 1 and "maxAgeMs" not in live_mock[0]
    asyncio.run(cd.product(url, max_age_ms=0))         # watcher recheck: fresh, past our cache too
    assert len(live_mock) == 2 and live_mock[1]["maxAgeMs"] == 0
    asyncio.run(cd.product(url))                       # the fresh copy refreshed the normal cache entry
    assert len(live_mock) == 2


def test_extract_and_search_accept_max_age(live_mock):
    asyncio.run(cd.extract("https://tori.fi/x", {"type": "object"}, max_age_ms=0))
    assert live_mock[-1]["maxAgeMs"] == 0
    asyncio.run(cd.search("sony a7 iii", highlights=True, max_age_ms=0))
    assert live_mock[-1]["markdownOptions"] == {"maxAgeMs": 0}
    asyncio.run(cd.search("sony a7 iii", highlights=True, max_age_ms=0))
    assert len(live_mock) == 3                         # 0 = never from our disk cache
    asyncio.run(cd.search("sony a7 iii", highlights=True))
    assert len(live_mock) == 3                         # default: cached copy is fine


def test_max_age_tightens_our_cache_ttl(live_mock, monkeypatch):
    url = "https://www.ebay.com/p/1"
    asyncio.run(cd.product(url))
    real = cd.time.time
    monkeypatch.setattr(cd.time, "time", lambda: real() + 120)
    asyncio.run(cd.product(url, max_age_ms=60_000))    # our copy is 2 min old > 1 min: refetch
    assert len(live_mock) == 2 and live_mock[1]["maxAgeMs"] == 60_000
    asyncio.run(cd.product(url))                       # default TTL (6 h): cached
    assert len(live_mock) == 2


def test_fresh_reads_context_applies_to_every_read(live_mock):
    async def go():
        with cd.fresh_reads():
            await cd.product("https://www.ebay.com/p/2")
            await cd.product("https://www.ebay.com/p/2")
        await cd.product("https://www.ebay.com/p/2")
    asyncio.run(go())
    assert [c.get("maxAgeMs") for c in live_mock] == [0, 0]


def test_search_rejects_markdown_options_then_retries_plain(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    bodies: list[dict] = []

    def handler(r):
        b = json.loads(r.content)
        bodies.append(b)
        if "markdownOptions" in b:
            return httpx.Response(400, json={"message": "unknown field"})
        return httpx.Response(200, json={"results": [{"url": "https://a.fi"}]})
    cd._transport = httpx.MockTransport(handler)
    try:
        assert asyncio.run(cd.search("q", highlights=True, max_age_ms=0))[0]["url"] == "https://a.fi"
    finally:
        cd._transport = None
    assert len(bodies) == 2 and "markdownOptions" not in bodies[1]


# ------------------------------------------------------------------ country

@pytest.mark.parametrize("raw,cc", [("FI", "fi"), (" fi ", "fi"), ("Finland", "fi"), ("suomi", "fi"), ("uk", "gb"),
                                    ("UK", "gb"), ("en-GB", "gb"), ("fi_FI", "fi"), ("Deutschland", "de"),
                                    ("", None), (None, None), ("Helsinki", None), ("123", None), ("f", None)])
def test_normalize_country(raw, cc):
    assert cd.normalize_country(raw) == cc


def test_search_sends_lowercase_alpha2(live_mock):
    asyncio.run(cd.search("q1", country="Finland"))
    asyncio.run(cd.search("q2", country="Helsinki"))       # not a country: no filter rather than a 400
    assert live_mock[0]["country"] == "fi" and "country" not in live_mock[1]


def test_home_country_adds_local_used_query_without_a_city(monkeypatch):
    monkeypatch.delenv("AGORA_COUNTRY", raising=False)
    need = Need(raw="sony a7 iii", thing="sony a7 iii")
    plan = dv.query_plan(need, "used", 2)
    assert plan[1] == ("sony a7 iii käytetty myydään tori", "fi")
    assert plan[0][1] is None                                # the English one stays open
    assert all(c is None for _, c in dv.query_plan(need, "new", 2))
    monkeypatch.setenv("AGORA_COUNTRY", "SE")
    assert dv.query_plan(need, "used", 2)[1] == ("sony a7 iii begagnad köpes blocket", "se")
    monkeypatch.setenv("AGORA_COUNTRY", "none")
    assert dv.query_plan(need, "used", 2)[1] == ("sony a7 iii used Europe €", None)
    # a city in the query wins over home
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    berlin = dv.query_plan(Need(raw="x", thing="sony a7 iii", where="Berlin"), "used", 2)
    assert berlin[0][1] == "de" and "gebraucht" in berlin[1][0]


def test_discover_sends_home_filter_and_ranks_home_shops_first(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    calls: list[dict] = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country})
        if "käytetty" in query:
            return [{"url": "https://www.tori.fi/vi/9", "title": "Sony A7 III runko käytetty", "relevance": "high"}]
        return [{"url": "https://shop.com/sony-a7-iii-used", "title": "Sony A7 III used", "relevance": "high"},
                {"url": "https://kamera.fi/sony-a7-iii-used", "title": "Sony A7 III used", "relevance": "high"}]
    monkeypatch.setattr(cd, "search", search)
    reader._HINTS.clear()

    async def run():
        return [e async for e in dv.discover(Need(raw="used sony a7 iii", thing="sony a7 iii", conditions=["used"]))]
    events = asyncio.run(run())
    lane = next(e.data for e in events if e.type == "lane")
    assert lane["home_country"] == "fi" and any("käytetty" in q for q in lane["queries"])
    assert {"query": "sony a7 iii käytetty myydään tori", "country": "fi"} in calls
    srcs = [e.data["domain"] for e in events if e.type == "source"]
    assert "tori.fi" in srcs and srcs.index("kamera.fi") < srcs.index("shop.com")


# ------------------------------------------------------------------ per-domain read budget

def test_domainstats_learns_latency_and_keeps_old_format(tmp_path):
    p = tmp_path / "slow.json"
    p.write_text(json.dumps({"adorama.com": {"timeouts": 3, "ok": 0, "last": 1}}))   # file from round 2
    s = SlowDomains(p)
    assert s.is_slow("adorama.com") and s.wall_for("adorama.com") == SLOW_WALL_S
    assert s.wall_for("fast.fi") is None and s.timeout_for("fast.fi", 12) == 12
    for secs in (14, 15, 16):
        s.record("parkcameras.com", False, seconds=secs)
    assert s.is_slow("parkcameras.com")                 # never timed out, but always crawls
    s.save()
    assert SlowDomains(p).data["parkcameras.com"]["ema_s"] > 10


def _hunt(disc, read, **kw):
    from agora.hunt import hunt

    async def go():
        return [e async for e in hunt("sony a7 iii", discover=disc, read=read, persist=False, lookalikes=False,
                                       siblings=False, **kw)]
    return asyncio.run(go())


def test_slow_domain_gets_a_wall_clock_cap_even_while_queued(tmp_path):
    s = SlowDomains(tmp_path / "s.json")
    s.record("adorama.com", True)
    s.record("adorama.com", True)
    import agora.hunt as hunt_mod

    async def disc(need):
        yield Event("source", {"url": "https://www.adorama.com/a7", "lane": "used"})

    async def read(url, need):          # forever "queued for the limiter": work timeout never runs out
        with cd.queueing():
            await asyncio.sleep(30)
        return None, "never"

    orig = hunt_mod.SlowDomains.wall_for
    hunt_mod.SlowDomains.wall_for = lambda self, d: 0.3 if self.is_slow(d) else None
    try:
        events = _hunt(disc, read, slow_domains=s, provisional_after=None, budget_s=None)
    finally:
        hunt_mod.SlowDomains.wall_for = orig
    skip = next(e for e in events if e.type == "skip")
    assert skip.data["timeout"] is True and "known slow domain" in skip.data["reason"]
    assert next(e for e in events if e.type == "done").data["ms"] < 2000


def test_hunt_budget_stops_waiting_and_keeps_the_provisional_verdict_early(tmp_path):
    async def disc(need):
        yield Event("source", {"url": "https://fast.example/a7", "lane": "new"})
        yield Event("source", {"url": "https://hang.example/a7", "lane": "new"})

    async def read(url, need):
        if "fast" in url:
            return Offer(url=url, source="fast.example", title="Sony A7 III", price=1399.0, currency="EUR",
                         price_eur=1399.0, condition="new", read_via="jsonld"), "jsonld"
        await asyncio.sleep(30)
        return None, "never"

    events = _hunt(disc, read, slow_domains=SlowDomains(tmp_path / "s.json"), budget_s=0.6,
                   provisional_after=0.3, stable_for=0.1, read_timeout=20)
    skip = next(e for e in events if e.type == "skip" and "hang" in e.data["url"])
    assert "hunt budget" in skip.data["reason"] and skip.data["timeout"] is True
    prov = next(e for e in events if e.type == "verdict" and e.data.get("provisional"))
    assert prov.t_ms < 600
    assert next(e for e in events if e.type == "done").data["ms"] < 1500
    # the budget is not the domain's fault: it is not marked slow
    assert not SlowDomains(tmp_path / "s.json").is_slow("hang.example")


def test_timed_out_read_falls_back_to_a_safe_snippet(tmp_path, monkeypatch):
    """The real reader: a page that runs out of time still counts when its search result priced it."""
    import agora.hunt as hunt_mod
    reader._HINTS.clear()
    url = "https://www.parkcameras.com/sony-a7-iii-body"
    reader.remember_source(url, "new", "Sony A7 III Body | Park Cameras", "Sony A7 III body in stock. Now: £1,399")

    async def slow_read(u, need, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(reader, "read_with_reason", slow_read)

    async def disc(need):
        yield Event("source", {"url": url, "lane": "new"})

    async def go():
        return [e async for e in hunt_mod.hunt("sony a7 iii", discover=disc, persist=False, lookalikes=False,
                                                siblings=False, budget_s=0.4, provisional_after=None,
                                                slow_domains=SlowDomains(tmp_path / "s.json"))]
    events = asyncio.run(go())
    offer = next(e.data["offer"] for e in events if e.type == "offer")
    assert offer["price"] == 1399.0 and offer["currency"] == "GBP" and offer["read_via"] == "search_highlight"
    assert "price_from_snippet" in offer["flags"]
