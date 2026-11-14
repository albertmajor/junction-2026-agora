"""Marketplace search pages cut into listings: free from ItemList JSON-LD, else ONE paid Context.dev list read.
Offline: the page fetch and Context.dev both answer from mocks / a recorded-style fixture."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, hunt as hunt_mod, reader
from agora.models import Event, Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"
TORI = "https://www.tori.fi/recommerce/forsale/search?q=airpods+pro+2&sub_category=1.93.3906"
KA = "https://www.kleinanzeigen.de/s-nintendo-switch-oled/k0"
AIRPODS = Need(raw="airpods pro 2", thing="airpods pro 2")
SWITCH = Need(raw="nintendo switch oled", thing="nintendo switch oled")


def _tori_item(i: int, name: str, price: str) -> dict:
    return {"@type": "ListItem", "position": i, "item": {
        "@type": "Product", "name": name, "brand": {"@type": "Brand", "name": "Apple"},
        "image": f"https://img.tori.net/item/{i}.jpg", "url": f"https://www.tori.fi/recommerce/forsale/item/{4900 + i}",
        "itemCondition": "https://schema.org/UsedCondition",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock", "itemCondition": "https://schema.org/UsedCondition"}}}


TORI_PAGE = "<html><head><script type='application/ld+json'>" + json.dumps({
    "@context": "https://schema.org", "@type": "CollectionPage", "url": TORI,
    "mainEntity": {"@type": "ItemList", "itemListElement": [
        _tori_item(1, "Apple AirPods Pro Gen 2", "100"),
        _tori_item(2, "Apple AirPods Pro 2 kuulokkeet", "120"),
        _tori_item(3, "AirPods Pro 2 USB-C alkuperäiset", "140"),
        {"@type": "ListItem", "position": 4, "item": {"@type": "Product", "name": "AirPods Pro 2 no url",
                                                      "offers": {"@type": "Offer", "price": "90"}}},
    ]}}) + "</script></head><body>Torista löydät 67 ilmoitusta</body></html>"

KA_PAGE = "<html><body><h1>Nintendo Switch OLED Anzeigen</h1>" + ("<p>anzeige</p>" * 3000) + "</body></html>"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None
    cd._transport = None


def serve(pages: dict[str, str]) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        html = pages.get(str(r.url))
        if html is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
    reader._transport = httpx.MockTransport(handler)


@pytest.fixture
def cd_list(monkeypatch):
    """Context.dev online against a MockTransport answering with the recorded list fixture."""
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    calls: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        calls.append(body)
        if body.get("formats", {}).get("json"):
            return httpx.Response(200, json=json.loads((FIX / "contextdev_list_kleinanzeigen.json").read_text()))
        return httpx.Response(500, json={"message": "unexpected call in test"})
    cd._transport = httpx.MockTransport(handler)
    return calls


def _no_paid(monkeypatch):
    async def boom(*a, **kw):
        raise AssertionError("no paid read expected")
    monkeypatch.setattr(cd, "extract", boom)
    monkeypatch.setattr(cd, "product", boom)


# ------------------------------------------------------------------ free: ItemList JSON-LD

def test_itemlist_jsonld_becomes_one_offer_per_listing_for_free(monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    _no_paid(monkeypatch)
    serve({TORI: TORI_PAGE})
    got, via = asyncio.run(reader.read_with_reason(TORI, AIRPODS, lane="used", paid=False, expand_lists=True))
    assert via == "jsonld" and isinstance(got, list) and len(got) == 3      # the item without a url is dropped
    assert [o.price for o in got] == [100.0, 120.0, 140.0]
    for o in got:
        assert o.url.startswith("https://www.tori.fi/recommerce/forsale/item/")
        assert o.source == "tori.fi" and o.read_via == "jsonld" and o.condition == "used"
        assert o.raw["from_list_page"] == TORI and o.raw["witnesses"][0]["doc"] == o.url
        assert o.image and o.brand == "Apple"
    assert cd.ledger()["saved_by_free_reads"] >= 1


def test_without_expand_lists_the_best_listing_comes_back_alone(monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    _no_paid(monkeypatch)
    serve({TORI: TORI_PAGE})
    offer = asyncio.run(reader.read(TORI, AIRPODS, lane="used", paid=False))
    assert isinstance(offer, Offer) and "/forsale/item/" in offer.url


def test_itemlist_on_an_item_page_is_ignored(monkeypatch):
    """'Related products' ItemList on a single listing page must not turn it into many offers."""
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    item = "https://www.tori.fi/recommerce/forsale/item/4901"
    serve({item: TORI_PAGE})
    got, _ = asyncio.run(reader.read_with_reason(item, AIRPODS, lane="used", paid=False, expand_lists=True))
    assert not isinstance(got, list)


# ------------------------------------------------------------------ paid: ONE list read per search page

def test_search_page_is_read_once_with_the_list_schema(cd_list):
    serve({KA: KA_PAGE})
    free, why = asyncio.run(reader.read_with_reason(KA, SWITCH, lane="used", paid=False, expand_lists=True))
    assert free is None and "list read" in why          # the hunt's free phase hands it to the paid phase
    got, via = asyncio.run(reader.read_with_reason(KA, SWITCH, lane="used", snippet_ok=True, expand_lists=True))
    assert via == "contextdev_json"
    assert len(cd_list) == 1                             # one paid read, no product read first
    body = cd_list[0]
    assert body["url"] == KA and body["jsonParams"]["schema"] == reader.LIST_SCHEMA
    assert "nintendo switch oled" in body["jsonParams"]["instructions"]
    assert isinstance(got, list) and len(got) == reader.MAX_LIST_OFFERS == 8
    urls = [o.url for o in got]
    assert len(set(urls)) == len(urls)
    for o in got:
        assert o.url.startswith("https://www.kleinanzeigen.de/s-anzeige/")   # relative link made absolute
        assert o.source == "kleinanzeigen.de" and o.read_via == "contextdev_json"
        assert o.raw["from_list_page"] == KA and o.condition == "used" and o.price_eur == o.price
        assert o.location == "Berlin"
    assert not any("mediamarkt" in u for u in urls)     # another site's ad on the page
    assert KA not in urls                               # the search page itself is not a listing
    # a second read of the same page is a cache hit, not another paid request
    asyncio.run(reader.read_with_reason(KA, SWITCH, lane="used", expand_lists=True))
    assert len(cd_list) == 1


def test_list_offers_validation():
    data = json.loads((FIX / "contextdev_list_kleinanzeigen.json").read_text())["json"]["data"]
    offers = reader.offers_from_list(data, KA, SWITCH, "used")
    assert len(offers) == 8
    assert reader.listing_url("/s-anzeige/x/1-2-3", KA) == "https://www.kleinanzeigen.de/s-anzeige/x/1-2-3"
    assert reader.listing_url("https://ads.doubleclick.net/x", KA) is None
    assert reader.listing_url("https://www.kleinanzeigen.de/s-nintendo/k0", KA) is None
    assert reader.listing_url("https://www.ebay.co.uk/itm/1", "https://www.ebay.co.uk/sch/i.html?_nkw=x")
    assert reader.listing_url("https://www.amazon.co.uk/dp/1", "https://www.ebay.co.uk/sch/i.html?_nkw=x") is None


def test_new_lane_shop_category_page_is_not_list_read():
    assert not reader.wants_list_read("https://shop.example/collections/consoles", SWITCH, "new")
    assert reader.wants_list_read("https://shop.example/collections/consoles", SWITCH, "refurbished")
    assert reader.wants_list_read(KA, SWITCH, None)                         # a known marketplace
    assert not reader.wants_list_read(KA, Need(raw="x", thing="x", kind="service"), "used")


# ------------------------------------------------------------------ hunt: listings are normal offers

def test_hunt_turns_a_search_page_into_used_offers_that_survive_resolve(cd_list):
    serve({KA: KA_PAGE})

    async def disc(need):
        yield Event("lane", {"lane": "used", "queries": ["q"]})
        yield Event("source", {"url": KA, "lane": "used", "title": "Nintendo Switch Oled kaufen", "list_page": True})

    async def go():
        return [e async for e in hunt_mod.hunt("nintendo switch oled", discover=disc, persist=False,
                                                lookalikes=False, siblings=False, provisional_after=None)]
    events = asyncio.run(go())
    offers = [e.data["offer"] for e in events if e.type == "offer"]
    assert len(offers) == 8 and all(o["url"] != KA for o in offers)
    assert {o["source"] for o in offers} == {"kleinanzeigen.de"}
    rejected = [e.data for e in events if e.type == "skip" and e.data.get("rejected")]
    assert not any("search or list page" in (r.get("reason") or "") for r in rejected)
    things = [e for e in events if e.type == "thing"]
    assert things and sum(t.data["n_offers"] for t in things) >= 6
    assert len(cd_list) == 1
    assert any(e.type == "verdict" for e in events)
    budget = next(e for e in events if e.type == "budget").data
    assert budget["requests"] == 1 and budget["offers"] == 8


def test_cases_on_a_search_page_do_not_take_listing_slots():
    """Live tori.fi: '-latauskotelo' / '-kotelo' (the charging case alone) sat among the AirPods listings."""
    data = {"listings": [
        {"title": "AirPods Pro 2 (USB-C) -latauskotelo – AITO Apple", "price": 45, "currency": "EUR",
         "url": "/recommerce/forsale/item/1", "condition": "used"},
        {"title": "AirPods Pro 2 (Lightning) -kotelo", "price": 38, "currency": "EUR",
         "url": "/recommerce/forsale/item/2", "condition": "used"},
        {"title": "Apple AirPods Pro 2 -kuulokkeet", "price": 100, "currency": "EUR",
         "url": "/recommerce/forsale/item/3", "condition": "used"},
    ]}
    got = reader.offers_from_list(data, TORI, AIRPODS, "used")
    assert [o.price for o in got] == [100.0]
