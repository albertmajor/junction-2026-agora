"""Round 6: live hunts spent the 10/min Context.dev bucket on searches and starved the used lane.

Cases come from the saved live streams (dyson, kallax, macbook, nintendo, airpods): their search
results are in fixtures/live_searches_round6.json, the junk URLs below were read as offers live."""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import hunt as hunt_mod
from agora import reader
from agora.hunt import LaneGate, SlowDomains
from agora.models import Event, Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"
LIVE = json.loads((FIX / "live_searches_round6.json").read_text())


def collect(need, **kw):
    async def run():
        return [e async for e in dv.discover(need, **kw)]
    return asyncio.run(run())


def fake_search(monkeypatch, table, calls=None, delay=None):
    async def search(query, n=10, highlights=False, country=None, **kw):
        if calls is not None:
            calls.append({"query": query, "country": country})
        if delay:
            await asyncio.sleep(delay(query))
        for key, results in table.items():
            if key in query:
                return results
        return []
    monkeypatch.setattr(cd, "search", search)
    reader._HINTS.clear()


# ------------------------------------------------------------------ query budget

def test_live_plan_is_one_query_per_lane_when_the_bucket_is_low(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    calls: list[dict] = []
    fake_search(monkeypatch, {}, calls)
    events = collect(Need(raw="macbook air m2", thing="macbook air m2"), tokens=5)
    lanes = {e.data["lane"]: e.data["queries"] for e in events if e.type == "lane"}
    assert list(lanes) == ["new", "refurbished", "used"]
    assert all(len(q) == 1 for q in lanes.values())
    assert len(calls) == 3                                         # was 6 (2 per lane) + 2 sibling searches
    used = next(c for c in calls if "käytetty" in c["query"])
    assert used["country"] == "fi"                                 # tori.fi, even with no city asked
    refurb = next(c for c in calls if "refurbished" in c["query"])
    assert refurb["country"] is None                               # backmarket/refurbed sell EU-wide


def test_spare_tokens_buy_one_eu_marketplace_query_for_the_used_lane(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    plan = dv.lean_plan(Need(raw="x", thing="dyson v15 vacuum"), "used", tokens=10)
    assert [c for _, c in plan] == ["fi", None]
    assert "kleinanzeigen" in plan[1][0] and "vinted" in plan[1][0]
    assert len(dv.lean_plan(Need(raw="x", thing="dyson v15 vacuum"), "used", tokens=dv.EXTRA_USED_MIN_TOKENS - 1)) == 1
    berlin = dv.lean_plan(Need(raw="x", thing="sony a7 iii", where="Berlin"), "used", tokens=0)
    assert berlin == [("sony a7 iii gebraucht kaufen kleinanzeigen", "de")]


def test_service_hunts_keep_two_queries():
    need = Need(raw="bike repair helsinki", thing="bike repair", kind="service", where="Helsinki")
    assert len(dv.lean_plan(need, "service", tokens=0)) == 2


def test_no_refurbished_lane_for_furniture():
    assert dv.lanes_for(Need(raw="ikea kallax shelf", thing="ikea kallax shelf")) == ["new", "used"]
    assert dv.lanes_for(Need(raw="dyson v15", thing="dyson v15 vacuum")) == ["new", "refurbished", "used"]
    only = Need(raw="refurbished kallax", thing="kallax", conditions=["refurbished"])
    assert dv.lanes_for(only) == ["refurbished"]                   # asked for explicitly: keep it


def test_explicit_depth_keeps_the_old_variants(monkeypatch):
    calls: list[dict] = []
    fake_search(monkeypatch, {}, calls)
    collect(Need(raw="sony a7 iii", thing="sony a7 iii"), depth=2)
    assert len(calls) == 6


# ------------------------------------------------------------------ used lane: marketplace items

def test_dyson_tori_items_are_not_capped_at_two(monkeypatch):
    """Live: 4 tori.fi /item/ pages were skipped 'already 2 pages from tori.fi' and 1 used offer survived."""
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    fake_search(monkeypatch, {"käytetty": LIVE["dyson v15 vacuum käytetty myydään tori"]})
    events = collect(Need(raw="dyson v15", thing="dyson v15 vacuum", conditions=["used"]), tokens=0)
    src = [e.data["url"] for e in events if e.type == "source"]
    items = [u for u in src if "/item/" in u]
    assert len(items) + sum("/search" in u for u in src) == dv.MARKETPLACE_ITEMS   # 3 items + 1 search page
    # round 7: ONE search page is kept even with item pages found (it is 8 listings, free from tori's ItemList),
    # and it is read first; further search pages are capped
    searches = [u for u in src if "/search" in u]
    assert len(searches) <= dv.LIST_PER_DOMAIN and (not searches or src[0] == searches[0])
    skips = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    assert any("search page" in r for r in skips.values())


def test_nintendo_tori_search_pages_count_as_one_list_page(monkeypatch):
    """Live: both tori slots went to /search? pages, which became fake used offers."""
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    fake_search(monkeypatch, {"käytetty": LIVE["nintendo switch oled käytetty myydään tori"]})
    events = collect(Need(raw="switch", thing="nintendo switch oled", conditions=["used"]), tokens=0)
    tori = [e.data["url"] for e in events if e.type == "source" and "tori.fi" in e.data["url"]]
    assert len(tori) <= dv.LIST_PER_DOMAIN


def test_item_pages_rank_before_list_pages_in_a_lane(monkeypatch):
    fake_search(monkeypatch, {"refurbished": [
        {"url": "https://www.amazon.de/airpods-pro-2-refurbished/s?k=airpods", "title": "AirPods Pro 2", "relevance": "high"},
        {"url": "https://www.walmart.com/c/kp/refurbished-airpods", "title": "AirPods Pro 2", "relevance": "high"},
        {"url": "https://www.refurbed.de/en-de/p/apple-airpods-pro-2/", "title": "AirPods Pro 2", "relevance": "low"},
    ]})
    events = collect(Need(raw="x", thing="airpods pro 2", conditions=["refurbished"]), tokens=0)
    assert [e.data["url"] for e in events if e.type == "source"][0].startswith("https://www.refurbed.de")


def test_fast_new_lane_cannot_fill_every_slot_before_used_lands(monkeypatch):
    """Live macbook: the new lane landed at 6 s and took 14 of 24 slots; the used lane (14.7 s) got 1."""
    def shop(prefix, n):
        return [{"url": f"https://{prefix}{i}.de/p/dyson-v15", "title": "Dyson V15 vacuum", "relevance": "high"}
                for i in range(n)]
    table = {"price buy": shop("new", 20), "refurbished": shop("refurb", 3), "käytetty": shop("used", 10)}
    fake_search(monkeypatch, table, delay=lambda q: 0.15 if "käytetty" in q else 0.0)
    events = collect(Need(raw="x", thing="dyson v15 vacuum"), tokens=0, max_sources=12, settle_s=0.05)
    lanes = [e.data["lane"] for e in events if e.type == "source"]
    assert len(lanes) == 12
    assert lanes.count("used") >= 4 and lanes.count("new") <= 8


# ------------------------------------------------------------------ junk sources

@pytest.mark.parametrize("url,title", [
    ("https://www.apartmenttherapy.com/ikea-kallax-price-drop-37426045", "IKEA's KALLAX Shelf Is On Sale for $20 Off"),
    ("https://bbs.io-tech.fi/threads/nintendo-switch-2-oulu.626361/", "Nintendo Switch 2 Oulu"),
    ("http://www.prixretro.com/en/nintendo-switch-oled/neon", "Nintendo Switch OLED Neon"),
    ("https://duckduckgo.com/y.js?ad_domain=amazon.com&ad_provider=bingv7aa&ad_type=txad", "Dyson V15"),
    ("https://www.boards.ie/discussion/2058282935/dyson-v15-detect-abs-cordless-vacuum-441-99", "Dyson V15"),
    ("https://www.gamesindustry.biz/nintendo-drops-base-model-switch-price-in-europe", "Nintendo switch"),
    ("https://www.is.fi/digitoday/art-2000011034842.html", "AirPods Pro 2"),
    ("https://geizhals.de/apple-macbook-air-m2-v103674.html", "Apple MacBook Air M2"),
    ("https://themacindex.com/variants/MLY43/macbook-air-m2-512gb?currency=EUR", "MacBook Air M2"),
    ("https://prices.appleinsider.com/macbook-air-2022", "MacBook Air M2"),
    ("https://webprice.eu/amazon/macbook%20air%20m2%2016gb%20512gb/", "MacBook Air M2"),
    ("https://kauppapaikat.net/Tori/Dyson+imuri", "Dyson imuri"),
    ("https://www.facebook.com/fb-answers/nintendo-switch-refurbished-price/?locale=zh_CN", "Switch"),
    ("https://www.facebook.com/ScanMalta/posts/new-lower-price-nintendo-switch", "Switch"),
    ("https://forum.example.com/t/selling-my-switch-oled/12345", "Switch OLED"),
    ("https://shop.example/kallax", "Kallax price drop: now €49"),
])
def test_live_junk_is_not_read(url, title):
    assert dv.is_non_shop(url, title) is not None


@pytest.mark.parametrize("url,title", [
    ("https://www.tori.fi/recommerce/forsale/item/38231132", "Dyson V15 Detect Absolute varsi-imuri | Tori"),
    ("https://www.refurbed.de/en-de/p/apple-airpods-pro-2/104401/", "Apple AirPods Pro 2"),
    ("https://www.amazon.de/-/en/Nintendo-10010900-Switch-OLED-Modell-Weiss/dp/B098RJXBTY", "Nintendo Switch OLED"),
    ("https://www.dyson.com/outlet/refurbished-vacuum-cleaners/cordless/v15-detect-iron", "Dyson V15 Detect"),
    ("https://store.nintendo.com/en-ie/consoles/nintendo-switch-console/nintendo-switch-oled", "Nintendo Switch OLED"),
    ("https://www.facebook.com/marketplace/item/123456789/", "Nintendo Switch OLED"),
    ("https://www.kleinanzeigen.de/s-anzeige/macbook-air-m2/2912345678-278-3331", "MacBook Air M2"),
    ("https://www.thomann.de/topseller_gitarren.html", "Guitars on sale"),
])
def test_real_shops_still_pass(url, title):
    assert dv.is_non_shop(url, title) is None


# ------------------------------------------------------------------ paid reads: lane-fair gate

def test_lane_gate_gives_every_lane_a_paid_read_before_any_gets_a_second():
    async def run():
        gate = LaneGate(1)
        order: list[str] = []

        async def one(lane, list_page=False):
            await gate.acquire(lane, list_page)
            order.append(lane + ("/list" if list_page else ""))
            await asyncio.sleep(0.01)
            gate.release()
        tasks = [asyncio.create_task(one("new")) for _ in range(4)]
        await asyncio.sleep(0)                                     # the new lane queues first
        tasks += [asyncio.create_task(one("used", True)), asyncio.create_task(one("used")),
                  asyncio.create_task(one("refurbished"))]
        await asyncio.gather(*tasks)
        return order
    order = asyncio.run(run())
    assert order[0] == "new"
    assert set(order[1:3]) == {"used", "refurbished"}              # item page before the used search page
    assert order.index("used/list") > order.index("refurbished")


def test_lane_gate_slot_is_freed_when_a_waiter_times_out():
    async def run():
        gate = LaneGate(1)
        await gate.acquire("new")
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(gate.acquire("used"), timeout=0.05)
        gate.release()
        await asyncio.wait_for(gate.acquire("used"), timeout=0.5)  # not stuck
        return gate.free
    assert asyncio.run(run()) == 0


def _hunt(disc, **kw):
    async def go():
        return [e async for e in hunt_mod.hunt("dyson v15 vacuum", discover=disc, persist=False, lookalikes=False,
                                                siblings=False, provisional_after=None, **kw)]
    return asyncio.run(go())


def test_real_reader_reads_free_first_and_pays_lane_by_lane(monkeypatch, tmp_path):
    calls: list[tuple[str, bool]] = []
    jsonld = "https://shop.fi/dyson-v15"

    async def rwr(url, need, *, paid=True, snippet_ok=None, **kw):
        calls.append((url, paid))
        if url == jsonld:
            return Offer(url=url, source="shop.fi", title="Dyson V15 Detect", price=549.0, currency="EUR",
                         condition="new", read_via="jsonld"), "jsonld"
        if not paid:
            return None, "no structured price"
        assert snippet_ok is True                                   # a safe snippet beats a paid read
        await asyncio.sleep(0.01)
        return None, "no offer in page"
    monkeypatch.setattr(reader, "read_with_reason", rwr)
    monkeypatch.setattr(hunt_mod, "PAID_SLOTS", 1)

    async def disc(need):
        yield Event("source", {"url": jsonld, "lane": "new"})
        for i in range(3):
            yield Event("source", {"url": f"https://new{i}.de/dyson-v15", "lane": "new"})
        yield Event("source", {"url": "https://www.tori.fi/recommerce/forsale/item/1", "lane": "used"})
        yield Event("source", {"url": "https://refurbed.de/p/dyson-v15", "lane": "refurbished"})

    events = _hunt(disc, slow_domains=SlowDomains(tmp_path / "s.json"))
    assert (jsonld, False) in calls and (jsonld, True) not in calls      # JSON-LD page: never paid
    paid = [u for u, p in calls if p]
    assert len(paid) == 5
    assert {"tori.fi", "refurbed.de"} <= {hunt_mod._domain(u) for u in paid[:3]}
    assert any(e.type == "offer" for e in events)


def test_paid_stage_does_not_fetch_the_page_twice(monkeypatch, tmp_path):
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(url)
        return 200, "<html><body>no structured data here</body></html>" + " " * 30000
    monkeypatch.setattr(reader, "fetch_html", fetch)

    async def disc(need):
        yield Event("source", {"url": "https://plain.fi/dyson-v15", "lane": "new"})
    _hunt(disc, slow_domains=SlowDomains(tmp_path / "s.json"))
    assert fetched == ["https://plain.fi/dyson-v15"]


def test_sibling_lane_waits_for_a_full_bucket(monkeypatch, tmp_path):
    async def disc(need):
        if False:
            yield

    async def go(tokens):
        monkeypatch.setattr(hunt_mod, "_tokens_now", lambda: tokens)
        return [e async for e in hunt_mod.hunt("sony a7 iii", discover=disc, read=lambda u, n: None, persist=False,
                                                lookalikes=False, provisional_after=None,
                                                slow_domains=SlowDomains(tmp_path / "s.json"))]
    low = asyncio.run(go(4.0))
    full = asyncio.run(go(10.0))
    sib = lambda evs: [e for e in evs if e.type == "lane" and e.data.get("lane") == "sibling"]  # noqa: E731
    assert not sib(low) and sib(full)


def test_hunt_hands_its_source_cap_and_token_budget_to_discover(monkeypatch, tmp_path):
    seen: dict = {}

    async def disc(need, *, max_sources=40, tokens=None):
        seen.update(max_sources=max_sources, tokens=tokens)
        if False:
            yield
    monkeypatch.setattr(hunt_mod, "_tokens_now", lambda: 7.0)
    _hunt(disc, read=lambda u, n: None, max_sources=24, slow_domains=SlowDomains(tmp_path / "s.json"))
    assert seen == {"max_sources": 24, "tokens": 7.0}


@pytest.mark.parametrize("url,is_list", [
    ("https://www.bestbuy.com/site/searchpage.jsp?id=pcat17071&st=macbook+air+m2", True),
    ("https://www.kleinanzeigen.de/s-macbook-air-m2/k0", True),
    ("https://www.kleinanzeigen.de/s-haus-garten/ikea-kallax/k0c80", True),
    ("https://www.mediamarkt.de/de/list/macbook-air-m2", True),
    ("https://www.saturn.de/de/list/macbook-air-m2", True),
    ("https://www.backmarket.ie/en-ie/l/nintendo-game-console/af5c38b9-a943-49d5-9a45-97c544deda7c", True),
    ("https://www.ikea.com/nl/en/cat/kallax-shelving-units-58285/", True),
    ("https://www.amazon.com/clp/B00RK4W2AA", True),
    ("https://www.kleinanzeigen.de/s-anzeige/macbook-air-m2/2912345678-278-3331", False),
    ("https://www.bhphotovideo.com/c/product/1394217-REG/sony.html", False),
    ("https://shop.example/collections/kallax/products/kallax-shelf-white", False),
    ("https://www.tori.fi/recommerce/forsale/item/39206984", False),
])
def test_more_list_pages_are_recognised(url, is_list):
    assert dv.is_list_page(url) is is_list


def test_facebook_posts_are_not_listings_but_marketplace_items_are():
    assert dv.is_non_shop("https://m.facebook.com/GeekPhoneMalta/photos/d41d8cd9/958840492071958/") is not None
    assert dv.is_non_shop("https://www.facebook.com/marketplace/item/123/") is None
