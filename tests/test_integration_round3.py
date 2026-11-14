"""Round-3 integration: the builders' cross-module 'needs', wired together (offline)."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from agora import cli, contextdev as cd, fx, reader
from agora.hunt import hunt
from agora.models import Need

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk

NEED = Need(raw="sony a7 iii", thing="sony a7 iii")

SALE_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Sony A7 III body","gtin12":"027242913359",
 "gtin14":"00027242913359","mpn":"ILCE7M3B",
 "offers":{"@type":"Offer","price":"1299.00","priceCurrency":"EUR","availability":"https://schema.org/InStock",
   "priceSpecification":[{"@type":"UnitPriceSpecification","price":"1299.00","priceCurrency":"EUR"},
     {"@type":"UnitPriceSpecification","priceType":"https://schema.org/StrikethroughPrice","price":"1799.00",
      "priceCurrency":"EUR"}]}}
</script></head><body><h1>Sony A7 III</h1><p>Loppuunmyyty</p></body></html>"""


@pytest.fixture(autouse=True)
def _reader(monkeypatch):
    monkeypatch.setattr(fx, "_rates", None)
    reader._HINTS.clear()
    yield
    reader._transport = None


def _serve(pages):
    def handler(r: httpx.Request) -> httpx.Response:
        status, html = pages.get(str(r.url), (404, "nope"))
        return httpx.Response(status, text=html, headers={"content-type": "text/html"})
    reader._transport = httpx.MockTransport(handler)


def test_jsonld_list_price_gtins_and_page_text():
    _serve({"https://shop.fi/a7": (200, SALE_PAGE)})
    o = asyncio.run(reader.read("https://shop.fi/a7", NEED))
    assert o.price == 1299.0
    assert o.raw["regular_price"] == 1799.0           # the strikethrough 'was' price, for the Omnibus check
    assert o.raw["gtin12"] == "027242913359" and o.raw["gtin14"] == "00027242913359"
    assert o.raw["gtin"] == "027242913359"
    assert "Loppuunmyyty" in o.raw["page_text"] and len(o.raw["page_text"]) <= reader.PAGE_TEXT_CHARS


def test_read_fresh_reaches_paid_reads_as_max_age_zero(monkeypatch):
    _serve({"https://shop.fi/x": (500, "")})
    seen = {}

    async def fake_product(url, **kw):
        seen["product"] = kw.get("max_age_ms")
        return None

    async def fake_extract(url, schema, instructions=None, **kw):
        seen["extract"] = kw.get("max_age_ms")
        return None

    monkeypatch.setattr(cd, "product", fake_product)
    monkeypatch.setattr(cd, "extract", fake_extract)
    asyncio.run(reader.read("https://shop.fi/x", NEED, fresh=True))
    assert seen == {"product": 0, "extract": 0}
    seen.clear()
    asyncio.run(reader.read("https://shop.fi/x", NEED))
    assert seen == {"product": None, "extract": None}


def test_watch_pinned_read_asks_for_fresh(monkeypatch):
    from agora import watch
    got = {}

    async def fake_read(url, need, *, fresh=False, **kw):
        got["fresh"] = fresh
        return None

    monkeypatch.setattr(reader, "read", fake_read)
    asyncio.run(watch._read_pinned("https://shop.fi/x", NEED))
    assert got == {"fresh": True}


def test_hunt_carries_hunt_id_and_band_fields():
    async def go():
        return [e async for e in hunt("used sony a7 iii under 900", **fk.kwargs())]
    events = asyncio.run(go())
    need = next(e for e in events if e.type == "need")
    assert need.data["hunt_id"].startswith("h_")
    tcs = [e for e in events if e.type == "truecost"]
    assert tcs and all({"band", "prices_shown", "offer_id", "hunt_id"} <= set(e.data) for e in tcs)


def test_hunt_registers_offers_for_buy_by_id(monkeypatch):
    from agora import buy
    async def go():
        kw = fk.kwargs()
        kw["persist"] = True
        return [e async for e in hunt("used sony a7 iii under 900", **kw)]
    events = asyncio.run(go())
    tc = next(e for e in events if e.type == "truecost" and e.data.get("offer_id"))
    stored = buy.lookup_offer(tc.data["offer_id"], [tc.data["hunt_id"]])
    assert stored is not None and stored["url"] == tc.data["url"]
    res = asyncio.run(buy.buy_offer(tc.data["offer_id"], hunt_id=tc.data["hunt_id"]))
    assert res["status"] == "link_sent"


def test_api_mounts_leases_and_buy():
    from agora.api import app
    c = TestClient(app)
    assert c.get("/leases", params={"client_id": "x"}).status_code == 200
    assert c.get("/leases/nope/deliveries").status_code in (200, 404)
    r = c.post("/buy", json={"offer_id": "nope", "hunt_id": "h_x"})
    assert r.status_code == 200 and r.json()["status"] == "refused"
    assert c.post("/buy", json={}).status_code == 422


def test_cli_dispatches_demo_buy(monkeypatch):
    import agora.demo_buy as demo
    called = {}
    monkeypatch.setattr(demo, "main", lambda argv=None: called.setdefault("argv", argv) and 0 or 0)
    assert cli.main(["demo-buy", "--tmp-db"]) == 0
    assert called["argv"] == ["--tmp-db"]


# ---- root-cause fixes found in the live round-3 hunts ----

from agora import judge as jd
from agora.models import Offer


def _o(url, price, cond, via="contextdev_product", **raw):
    return Offer(url=url, source=url.split("/")[2], title="Sony a7 III body", price=price, currency="EUR",
                 price_eur=price, condition=cond, read_via=via, raw=dict(raw))


def test_snippet_threshold_is_not_an_item_price():
    n = Need(raw="sony a7 iii", thing="sony a7 iii")
    assert reader.offer_from_snippet("Free shipping on most orders over $100!", "https://mpex.com/a", "a7 III", n) is None
    assert reader.offer_from_snippet("Save €300 today · Price: €1,099", "https://x.fi/a", "a7", n).price == 1099
    assert reader.offer_from_snippet("Sony A7 II body used - €480", "https://x.de/a", "a7", n).price == 480


def test_lone_used_misread_far_under_new_is_disputed_early():
    """Provisional verdicts judge few offers: one used price and no used comps must not win."""
    mpb = _o("https://www.mpb.com/a7", 239, "used")
    new = _o("https://e-infin.com/a7", 1029, "new", via="jsonld")
    trust, flags = jd.assess_trust(mpb, [mpb, new])
    assert mpb.raw["price_check"] == "disputed" and trust <= 0.5
    assert any("cheapest new" in f for f in flags)


def test_one_shop_two_urls_is_one_market_vote():
    a = _o("https://www.walmart.com/ip/1", 145, "refurbished")
    b = _o("https://www.walmart.com/ip/2", 145, "refurbished")
    c = _o("https://swappa.com/x", 298, "refurbished")
    d = _o("https://backmarket.com/x", 340, "refurbished")
    # counted twice, €145 would pull the median to €221 and stay "in the market"; counted once it is the outlier
    assert sorted(jd.market_prices([a, b, c, d], "refurbished")) == [298, 340]


def test_used_was_price_is_retail_not_a_fake_discount():
    o = _o("https://buy.gazelle.com/x", 357, "used", regular_price=723)
    assert jd.discount_check(o, [o]) is None and o.raw["was_is_retail"] is True
    n = _o("https://shop.fi/x", 1000, "new", regular_price=1500)
    peers = [n, _o("https://a.fi/x", 1050, "new"), _o("https://b.fi/x", 1100, "new"), _o("https://c.fi/x", 1200, "new")]
    assert jd.discount_check(n, peers, history=False).startswith("discount inflated")


def test_service_rate_not_disputed_by_its_own_listing_numbers():
    o = Offer(url="https://kotihandi.fi/x", source="kotihandi.fi", title="Home cleaning", price=45, currency="EUR",
              price_eur=45, condition="service", unit="hour", read_via="jsonld",
              raw={"witnesses": [{"via": "jsonld", "price": 45, "currency": "EUR", "primary": True},
                                 {"via": "snippet", "price": 1600, "currency": "EUR", "primary": False,
                                  "doc": "https://kotihandi.fi/x", "independent": False}]})
    assert jd.verify_price(o) is None and o.raw["price_check"] is None


def test_demo_buy_sse_streams_haggle_and_proof():
    import json as _json
    from agora.api import app
    with TestClient(app) as c:
        r = c.get("/demo/buy?pause=0")
    evs = [_json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    titles = [e["data"].get("title") for e in evs if e["type"] == "story"]
    assert "counter" in titles and "order" in titles
    proof = next(e["data"] for e in evs if e["type"] == "proof")
    assert proof["chain_ok"] and proof["signature_ok"] and proof["mandate_chain_ok"] and proof["purchases"] == 1
    done = evs[-1]
    assert done["type"] == "done" and done["data"]["status"] == "bought" and done["data"]["paid_eur"] == 1028.0


def test_lease_http_accepts_ttl_s_alias():
    from agora import watch
    from agora.api import app
    w = watch.create_watch("sony a7 iii body", max_price_eur=900, use_hunt=False)
    c = TestClient(app)
    r = c.post(f"/watches/{w['id']}/leases", json={"callback_url": "https://agent.example/h", "ttl_s": 600})
    d = r.json()
    assert r.status_code == 200 and round(d["expires_at"] - d["created_at"]) == 600
