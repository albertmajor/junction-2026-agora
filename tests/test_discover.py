"""Offline tests for agora.discover with a mocked contextdev.search."""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import reader
from agora.models import Need

FIX = pathlib.Path(__file__).parent / "fixtures"


def collect(need, **kw):
    async def run():
        return [e async for e in dv.discover(need, **kw)]
    return asyncio.run(run())


@pytest.fixture
def fake_search(monkeypatch):
    calls: list[dict] = []
    fixture = json.loads((FIX / "search.json").read_text())["results"]
    extra = {
        "used": [{"url": "https://www.tori.fi/vi/1?utm_source=x", "title": "Sony A7 III", "relevance": "high"},
                 {"url": "https://tori.fi/vi/1/", "title": "Sony A7 III (dup)", "relevance": "high"},
                 {"url": "https://www.tori.fi/vi/2", "title": "Sony A7 III runko", "relevance": "high"},
                 {"url": "https://www.tori.fi/vi/3", "title": "Sony A7III", "relevance": "high"},
                 {"url": "https://www.dpreview.com/reviews/sony-a7-iii-review", "title": "Sony a7 III review"}],
        "refurbished": [{"url": "https://www.mpb.com/fi-fi/product/sony-a7-iii", "title": "Sony A7 III used",
                         "relevance": "high",
                         "highlights": {"highlights": ["Excellent condition 979 €"], "code": "SUCCESS"}}],
    }

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country, "highlights": highlights, **kw})
        if "käytetty" in query or "used" in query:
            return extra["used"]
        if "refurbished" in query or "kunnostettu" in query:
            return extra["refurbished"]
        if "boom" in query:
            raise cd.ContextDevError("HTTP 500")
        return fixture

    monkeypatch.setattr(cd, "search", search)
    reader._HINTS.clear()
    return calls


def test_lanes_and_streamed_sources(fake_search):
    need = Need(raw="used sony a7 iii helsinki", thing="sony a7 iii", where="Helsinki")
    events = collect(need)
    lanes = [e.data for e in events if e.type == "lane"]
    assert [l["lane"] for l in lanes] == ["new", "refurbished", "used"]
    assert all(1 <= len(l["queries"]) <= 3 for l in lanes)
    assert any("käytetty" in q for l in lanes for q in l["queries"])   # Finnish variant
    assert fake_search[0]["country"] == "fi"                           # first variant filtered to FI
    assert any(c["country"] is None for c in fake_search)              # others open to Europe

    sources = [e.data for e in events if e.type == "source"]
    urls = [s["url"] for s in sources]
    assert len(urls) == len({dv.normalize_url(u) for u in urls})       # deduped
    by_domain: dict[str, int] = {}
    for s in sources:
        by_domain[s["domain"]] = by_domain.get(s["domain"], 0) + 1
    shops = {d: n for d, n in by_domain.items() if not dv.is_marketplace(d)}
    assert max(shops.values()) <= dv.PER_DOMAIN                        # shops capped at 2
    assert by_domain["tori.fi"] == 3                                   # marketplace items: each its own seller
    assert not any("alibaba" in u or "dpreview" in u for u in urls)    # non-shops dropped
    skips = [e.data for e in events if e.type == "skip"]
    assert any("alibaba" in s["url"] for s in skips)
    tori = next(s for s in sources if s["domain"] == "tori.fi")
    assert tori["lane"] == "used" and tori["eu"] is True
    mpb = next(s for s in sources if s["domain"] == "mpb.com")
    assert "979" in mpb["snippet"]
    assert reader._HINTS[mpb["url"]]["lane"] == "refurbished"          # reader gets the hint


def test_service_need_has_service_lane_with_highlights(fake_search):
    need = Need(raw="window cleaning helsinki price", thing="window cleaning", kind="service", where="Helsinki")
    events = collect(need)
    assert [e.data["lane"] for e in events if e.type == "lane"] == ["service"]
    assert all(c["highlights"] for c in fake_search)
    assert any("Helsinki" in c["query"] for c in fake_search)


def test_search_error_becomes_event(fake_search):
    need = Need(raw="boom", thing="boom", conditions=["new"])
    events = collect(need, depth=1)
    assert [e.type for e in events] == ["lane", "error"]


def test_depth_controls_variants():
    need = Need(raw="x", thing="sony a7 iii", where="Berlin")
    assert len(dv.queries_for(need, "used", 1)) == 1
    two = dv.queries_for(need, "used", 2)
    assert len(two) == 2 and "gebraucht" in two[1]
    assert len(dv.queries_for(need, "used", 3)) == 3


def test_no_where_uses_euro_wording():
    need = Need(raw="x", thing="dyson v15")
    qs = dv.queries_for(need, "new", 2)
    assert any("€" in q for q in qs)
    assert dv.country_of(need) is None


@pytest.mark.parametrize("url,title,bad", [
    ("https://electronics.alibaba.com/question/sony-a7", "", True),
    ("https://shop.fi/blog/best-cameras", "", True),
    ("https://www.techradar.com/x", "", True),
    ("https://shop.de/sony-a7-iii-vs-a7-iv", "", True),
    ("https://shop.fi/p/sony-a7-iii", "Sony A7 III review", True),
    ("https://www.tagheuer.com/tag-heuer-carrera", "TAG Heuer Carrera", False),
    ("https://www.verkkokauppa.com/fi/product/123", "Sony A7 III runko", False),
    ("https://www.box.com/x", "box", False),
])
def test_non_shop_filter(url, title, bad):
    assert (dv.is_non_shop(url, title) is not None) is bad


def test_normalize_url_and_eu_score():
    assert dv.normalize_url("https://WWW.Shop.fi/p/1/?utm_source=a&b=2#x") == "https://shop.fi/p/1?b=2"
    assert dv.eu_score("gigantti.fi", "fi", "high") > dv.eu_score("amazon.de", "fi", "high") \
        > dv.eu_score("walmart.com", "fi", "high")


@pytest.mark.parametrize("url,is_list", [
    ("https://www.amazon.com/sony-a7iii/s?k=sony+a7iii", True),
    ("https://www.ebay.com/sch/i.html?_nkw=sony", True),
    ("https://www.ebay.com/b/Sony-A7III-Digital-Cameras/31388/bn_7", True),
    ("https://www.walmart.com/c/kp/a7iii-used", True),
    ("https://www.keh.com/shop/sony-alpha-a7-iii.html", False),
    ("https://www.bhphotovideo.com/c/product/1394217-REG/sony.html", False),
    ("https://www.mpb.com/en-eu/product/sony-alpha-a7-iii", False),
])
def test_list_page_detection(url, is_list):
    assert dv.is_list_page(url) is is_list


def test_title_gate_skips_other_models_for_free():
    need = Need(raw="sony a7 iii", thing="sony a7 iii")
    assert dv.title_gate(need, "Used Sony Alpha A7R III") is not None
    assert dv.title_gate(need, "Battery for Sony a7 III") is not None
    assert dv.title_gate(need, "Sony A7iii | eBay") is None
    assert dv.title_gate(need, "Sony a7 III Mirrorless Camera Body") is None
    assert dv.title_gate(Need(raw="x", thing="cleaning", kind="service"), "anything") is None


def test_small_budget_still_covers_every_lane(monkeypatch):
    def results(prefix):
        return [{"url": f"https://{prefix}{i}.de/p/sony-a7-iii", "title": "Sony A7 III", "relevance": "high"}
                for i in range(10)]

    async def search(query, n=10, highlights=False, country=None, **kw):
        if "refurbished" in query:
            return results("refurb")
        if "used" in query:
            await asyncio.sleep(0.05)      # arrives later, must still get its share
            return results("used")
        return results("new")

    monkeypatch.setattr(cd, "search", search)
    events = collect(Need(raw="sony a7 iii", thing="sony a7 iii"), max_sources=6)
    lanes = [e.data["lane"] for e in events if e.type == "source"]
    assert len(lanes) == 6 and {lanes.count(l) for l in ("new", "refurbished", "used")} == {2}


def test_wholesale_and_price_trackers_are_not_shops():
    # owner: listings are judged one by one, not whole sites: merkandi's page is read, its lot title rejects it
    from agora import resolve
    from agora.models import Offer
    assert dv.is_non_shop("https://merkandi.com/products/iphone-15-128gb/1") is None
    lot = Offer(url="https://merkandi.com/products/iphone-15-128gb/1", source="merkandi.com",
                title="Wholesale lot 50 pcs iPhone 15 128GB", price=20000, currency="EUR")
    assert resolve.not_an_offer(lot) == "a wholesale lot, not one item"
    assert dv.is_non_shop("https://www.mobiledepot.eu/wholesale/exclusive-stock/x") is not None
    assert dv.is_non_shop("https://www.flipifyapp.com/price-tracker/apple-iphone-15") is not None
