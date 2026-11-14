"""Offline tests for agora.reader: the cheap-first cascade with mocked HTTP and a mocked Context.dev."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, reader
from agora.models import Need

FIX = pathlib.Path(__file__).parent / "fixtures"
NEED = Need(raw="sony a7 iii", thing="sony a7 iii")

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"BreadcrumbList"},
 {"@type":"Product","name":"Sony Alpha A7 III runko","sku":"ILCE7M3B","brand":{"@type":"Brand","name":"Sony"},
  "image":["https://img.fi/a7.jpg"],
  "offers":{"@type":"Offer","price":"1 499,00","priceCurrency":"EUR",
            "availability":"https://schema.org/InStock","itemCondition":"https://schema.org/NewCondition",
            "seller":{"@type":"Organization","name":"Kamerakauppa"},
            "shippingDetails":{"@type":"OfferShippingDetails","shippingRate":{"@type":"MonetaryAmount","value":"9.90","currency":"EUR"}}}},
 {"@type":"Product","name":"Sony NP-FZ100 battery","offers":{"@type":"Offer","price":"79","priceCurrency":"EUR"}}]}
</script></head><body>shop</body></html>"""

MICRODATA_PAGE = """<html><body><div itemscope itemtype="https://schema.org/Product">
<span itemprop="name">Sony A7 III body (used, 20k shutter)</span>
<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
<meta itemprop="price" content="899.00"><meta itemprop="priceCurrency" content="EUR">
<link itemprop="itemCondition" href="https://schema.org/UsedCondition"></div></div></body></html>"""

OG_PAGE = """<html prefix="og: http://ogp.me/ns#"><head>
<meta property="og:title" content="Sony A7 III" />
<meta property="product:price:amount" content="1349.90" />
<meta property="product:price:currency" content="EUR" /></head><body></body></html>"""

BLOCKED_PAGE = "<html><head><title>Just a moment...</title></head><body>cf-chl captcha</body></html>"
PLAIN_PAGE = "<html><body><h1>Sony A7 III</h1><p>Hinta 850 €</p>" + ("x" * 30000) + "</body></html>"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def serve(pages: dict[str, tuple[int, str]]):
    def handler(r: httpx.Request) -> httpx.Response:
        status, html = pages.get(str(r.url), (404, "not found"))
        return httpx.Response(status, text=html, headers={"content-type": "text/html; charset=utf-8"})
    reader._transport = httpx.MockTransport(handler)


def paid(monkeypatch, product=None, extract=None):
    """Mock the paid Context.dev steps and record which ran."""
    ran: list[str] = []

    async def fake_product(url, **kw):
        ran.append("product")
        return product

    async def fake_extract(url, schema, instructions=None, **kw):
        ran.append("json")
        assert schema is reader.OFFER_SCHEMA or schema is reader.SERVICE_SCHEMA
        return extract

    monkeypatch.setattr(cd, "product", fake_product)
    monkeypatch.setattr(cd, "extract", fake_extract)
    return ran


def test_jsonld_is_free_and_picks_the_main_product(monkeypatch):
    serve({"https://kamera.fi/a7iii": (200, JSONLD_PAGE)})
    ran = paid(monkeypatch)
    offer, how = asyncio.run(reader.read_with_reason("https://kamera.fi/a7iii", NEED))
    assert how == "jsonld" and ran == []
    assert offer.title.startswith("Sony Alpha A7 III")          # not the battery
    assert offer.price == 1499.0 and offer.currency == "EUR" and offer.price_eur == 1499.0
    assert offer.condition == "new" and offer.in_stock is True
    assert offer.shipping_eur == 9.9 and offer.seller == "Kamerakauppa" and offer.brand == "Sony"
    assert offer.sku == "ILCE7M3B" and offer.image == "https://img.fi/a7.jpg"
    assert cd.ledger()["saved_by_free_reads"] == 1


def test_microdata_used_condition(monkeypatch):
    serve({"https://shop.de/a7": (200, MICRODATA_PAGE)})
    paid(monkeypatch)
    offer = asyncio.run(reader.read("https://shop.de/a7", NEED))
    assert offer.price == 899.0 and offer.condition == "used" and offer.read_via == "jsonld"


def test_opengraph_fallback(monkeypatch):
    serve({"https://shop.fi/a7": (200, OG_PAGE)})
    paid(monkeypatch)
    offer = asyncio.run(reader.read("https://shop.fi/a7", NEED))
    assert offer.price == 1349.9 and offer.read_via == "jsonld"


def test_blocked_page_falls_to_contextdev_product(monkeypatch):
    serve({"https://www.ebay.com/p/12027034774": (403, BLOCKED_PAGE)})
    p = json.loads((FIX / "product3.json").read_text())["product"]["data"]["product"]
    ran = paid(monkeypatch, product=p)
    offer, how = asyncio.run(reader.read_with_reason("https://www.ebay.com/p/12027034774", NEED))
    assert how == "contextdev_product" and ran == ["product"]
    assert offer.currency == "USD" and offer.price == 789.99
    assert offer.price_eur == fx.to_eur(789.99, "USD")
    assert offer.condition == "used"   # ebay = marketplace


def test_listing_skips_product_and_uses_universal_schema(monkeypatch):
    serve({"https://www.tori.fi/vi/123": (200, PLAIN_PAGE)})
    data = {"page_type": "listing", "offers": [
        {"title": "Sony a7 iii + 28-70", "price": 950, "currency": "EUR", "unit": "item", "condition": "new",
         "seller": "Matti", "location": "Helsinki", "posted": "2026-11-10"}]}
    ran = paid(monkeypatch, extract=data)
    offer, how = asyncio.run(reader.read_with_reason("https://www.tori.fi/vi/123", NEED))
    assert ran == ["json"] and how == "contextdev_json"
    assert offer.condition == "used"           # model said "new", domain knows better
    assert offer.location == "Helsinki" and offer.raw["posted"] == "2026-11-10"


def test_service_unit_price(monkeypatch):
    need = Need(raw="home cleaning helsinki", thing="home cleaning", kind="service", where="Helsinki")
    serve({"https://siivous.fi/hinnasto": (200, PLAIN_PAGE)})
    data = {"page_type": "service", "offers": [
        {"title": "Kotisiivous", "price": 39, "currency": "EUR", "unit": "hour", "condition": "service",
         "callout_fee": 15},
        {"title": "Ikkunanpesu", "price": 120, "currency": "EUR", "unit": "job", "condition": "service"}]}
    ran = paid(monkeypatch, extract=data)
    offer = asyncio.run(reader.read("https://siivous.fi/hinnasto", need))
    assert ran == ["json"]                      # services never pay for the product format
    assert offer.unit == "hour" and offer.condition == "service" and offer.raw["callout_fee"] == 15


def test_gone_page_costs_nothing(monkeypatch):
    serve({})
    ran = paid(monkeypatch)
    offer, why = asyncio.run(reader.read_with_reason("https://shop.fi/missing", NEED))
    assert offer is None and "gone" in why and ran == []


def test_article_is_rejected(monkeypatch):
    serve({"https://blog.fi/x": (200, PLAIN_PAGE)})
    paid(monkeypatch, product=None, extract={"page_type": "article", "offers": [{"title": "a", "price": 1,
                                                                                 "currency": "EUR"}]})
    offer, why = asyncio.run(reader.read_with_reason("https://blog.fi/x", NEED))
    assert offer is None and "article" in why


def test_snippet_fallback_uses_discover_hint(monkeypatch):
    serve({"https://kenmorecamera.com/sony-a7-iii-body/": (403, BLOCKED_PAGE)})
    paid(monkeypatch, product=None, extract=None)
    reader.remember_source("https://kenmorecamera.com/sony-a7-iii-body/", "new", "SONY A7 III BODY",
                           "MSRP: $1,998.00 · Was: $1,998.00 · Now: $1,698.00 · SKU: 113037")
    offer = asyncio.run(reader.read("https://kenmorecamera.com/sony-a7-iii-body/", NEED))
    assert offer.price == 1698.0 and offer.currency == "USD"
    assert offer.read_via == "search_highlight" and "price_from_snippet" in offer.flags


def test_paid_false_stays_free(monkeypatch):
    serve({"https://x.fi/a": (200, PLAIN_PAGE)})
    ran = paid(monkeypatch)
    assert asyncio.run(reader.read("https://x.fi/a", NEED, paid=False)) is None and ran == []


@pytest.mark.parametrize("url,title,expected", [
    ("https://www.swappie.com/fi/iphone-13", "iPhone 13", "refurbished"),
    ("https://www.backmarket.de/de-de/p/iphone", "iPhone 13", "refurbished"),
    ("https://www.tori.fi/vi/1", "iPhone 13", "used"),
    ("https://www.vinted.fi/items/1", "iPhone 13", "used"),
    ("https://www.kleinanzeigen.de/s-anzeige/1", "iPhone 13 neu OVP", "new"),
    ("https://www.verkkokauppa.com/fi/product/1", "iPhone 13 128 GB", "new"),
    ("https://shop.de/p/1", "iPhone 13 generalüberholt", "refurbished"),
    ("https://shop.fi/p/1", "Käytetty iPhone 13", "used"),
    ("https://www.grover.com/de-en/products/iphone", "Rent iPhone 13", "rental"),
    ("https://kauppa.fi/p/1", "Kamera vuokraus", "rental"),
])
def test_guess_condition(url, title, expected):
    assert reader.guess_condition(url, title) == expected


def test_parse_price_formats():
    assert reader.parse_price("1.299,00 €") == (1299.0, "EUR")
    assert reader.parse_price("$1,698.00") == (1698.0, "USD")
    assert reader.parse_price("4 995 kr", domain="blocket.se") == (4995.0, "SEK")
    assert reader.parse_price(799, "eur") == (799.0, "EUR")
    assert reader.parse_price("850", domain="tori.fi") == (850.0, "EUR")
    assert reader.parse_price("free")[0] is None


def test_universal_schema_is_valid_json_schema_shape():
    s = reader.OFFER_SCHEMA
    assert s["type"] == "object" and "offers" in s["properties"]
    item = s["properties"]["offers"]["items"]["properties"]
    for field in ("price", "currency", "unit", "condition", "callout_fee", "location", "seller"):
        assert field in item
    assert len(json.dumps(s)) < 50_000


def test_lane_hint_needs_search_title_backing():
    assert reader.lane_hint("refurbished", "Sony Alpha a7 III Body") is None
    assert reader.lane_hint("refurbished", "Sony a7 III (Refurbished)") == "refurbished"
    assert reader.lane_hint("used", "USED Sony Alpha A7 III Body") == "used"
    assert reader.lane_hint("new", "") == "new"


def test_used_dealers_and_paths_are_used():
    assert reader.guess_condition("https://www.keh.com/shop/sony-a7-iii.html", "Sony a7 III") == "used"
    assert reader.guess_condition("https://www.parkcameras.com/used/cameras/sony/x", "Sony A7 III") == "used"
    assert reader.guess_condition("https://www.walmart.com/ip/x", "Restored Sony a7III") == "refurbished"
