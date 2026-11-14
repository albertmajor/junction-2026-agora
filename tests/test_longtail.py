"""Long-tail lane (agora.longtail + agora.longtail_store): offline, saved pages in tests/fixtures/longtail/.

Fixtures are real pages fetched over plain HTTP on 2026-11-14 (scripts/styles stripped): designjoy.co home,
manypixels.co/pricing, penji.co/pricing, and a webtonic.io 'best graphic design subscription' article."""
from __future__ import annotations

import asyncio
import pathlib
import time

import httpx
import pytest

from agora import contextdev, longtail, longtail_store
from agora.models import Event, Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures" / "longtail"


def page(name: str) -> str:
    return (FIX / name).read_text()


MANYPIXELS_HOME = ("<html><head><title>ManyPixels | Unlimited graphic design</title></head><body>"
                   "<nav><a href='/pricing'>Pricing</a><a href='https://twitter.com/manypixels'>x</a></nav>"
                   "<h1>Unlimited graphic design for a flat monthly fee</h1></body></html>")

SITE = {
    "https://designjoy.co/": page("designjoy_home.html"),
    "https://penji.co/pricing/": page("penji_pricing.html"),
    "https://manypixels.co/": MANYPIXELS_HOME,
    "https://manypixels.co/pricing": page("manypixels_pricing.html"),
    "https://www.webtonic.io/blog/8-best-graphic-design-subscription-services-unlimited-design-compared":
        page("listicle_webtonic.html"),
}


def transport(served: list[str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        served.append(url)
        html = SITE.get(url)
        if html is None:
            return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
    return httpx.MockTransport(handler)


def need(text: str = "unlimited graphic design subscription") -> Need:
    from agora.need import parse_need_rules
    return parse_need_rules(text)


# --------------------------------------------------------------------------- pure parts

def test_designjoy_home_plan_parsed_free():
    plans = longtail.parse_plans_text(page("designjoy_home.html"), "designjoy.co")
    assert [(p["name"], p["price"], p["currency"], p["period"]) for p in plans] == [
        ("Monthly Club", 4995.0, "USD", "month")]
    assert "One request at a time" in plans[0]["features"]
    assert all("$" not in f for f in plans[0]["features"])        # the struck-through $5,995 is not a feature


def test_pricing_pages_parse_every_plan_once():
    mp = longtail.parse_plans_text(page("manypixels_pricing.html"), "manypixels.co")
    assert [(p["name"], p["price"]) for p in mp] == [("Advanced", 699.0), ("Business", 1199.0),
                                                     ("Assigned designer", 1399.0), ("Design team", 2599.0)]
    pj = longtail.parse_plans_text(page("penji_pricing.html"), "penji.co")
    assert [(p["name"], p["price"], p["period"]) for p in pj] == [
        ("Essentials", 995.0, "month"), ("Agency Partner", 1995.0, "month"), ("Dedicated Team", 4500.0, "month")]


def test_local_currency_and_periods():
    html = ("<div><h3>Pienyritys</h3><p>89 € / kk</p><li>Kirjanpito</li></div>"
            "<div><h3>Kasvuyritys</h3><p>1 290 € / vuosi</p></div>"
            "<div><h3>Konsultointi</h3><p>95 €/h + alv</p></div>")
    plans = longtail.parse_plans_text(html, "tilitoimisto.fi")
    assert [(p["name"], p["price"], p["currency"], p["period"]) for p in plans] == [
        ("Pienyritys", 89.0, "EUR", "month"), ("Kasvuyritys", 1290.0, "EUR", "year"),
        ("Konsultointi", 95.0, "EUR", "hour")]


def test_jsonld_plans():
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"Service","name":"Bookkeeping",
      "offers":[{"@type":"Offer","name":"Starter","price":"79","priceCurrency":"EUR",
                 "priceSpecification":{"@type":"UnitPriceSpecification","price":79,"unitCode":"MON"}}]}</script>"""
    assert longtail.parse_plans_jsonld(html, "https://x.fi/") == [
        {"name": "Starter", "price": 79.0, "currency": "EUR", "period": "month", "features": []}]


def test_listicle_names_and_links():
    html = page("listicle_webtonic.html")
    assert longtail.listicle_names(html)[:4] == ["Design Pickle", "Penji", "ManyPixels", "Kimp"]
    found = [("https://twitter.com/x", "t"), ("https://www.kimp.io/?ref=abc", "Kimp"), ("https://flocksy.com/", "F"),
             ("https://www.webtonic.io/other", "own"), ("https://cdn.prod.website-files.com/a.png", ""),
             ("https://forbes.com/a", "media"), ("https://superside.com/go/xyz", "aff?"),
             ("https://www.fiverr.com/x", "platform"), ("https://flocksy.com/pricing", "dup")]
    # kimp (?ref=) and superside (/go/) are affiliate links, twitter social, forbes media, fiverr a platform
    assert longtail.provider_links(found, "https://www.webtonic.io/blog/x") == ["https://flocksy.com/"]


def test_markdown_listicle():
    md = "# Best design subscriptions\n## 1. [Designjoy](https://designjoy.co/?via=blog)\n## 2. Penji\ntext [Kimp](https://www.kimp.io/)"
    names, lk = longtail.markdown_names_and_links(md)
    assert names == ["Designjoy", "Penji"]
    assert longtail.provider_links(lk, "https://blog.example.com/x") == ["https://kimp.io/"]


def test_is_listicle():
    assert longtail.is_listicle("https://x.com/blog/a", "13 Best unlimited graphic design services in 2026")
    assert longtail.is_listicle("https://x.com/designjoy-alternatives", "")
    assert longtail.is_listicle("https://x.com/a", "Penji vs ManyPixels")
    assert not longtail.is_listicle("https://designjoy.co/", "Designjoy - Design as a Subscription")


def test_pricing_link():
    assert longtail.pricing_link(MANYPIXELS_HOME, "https://manypixels.co/") == "https://manypixels.co/pricing"
    assert longtail.pricing_link(page("designjoy_home.html"), "https://designjoy.co/") == "https://designjoy.co/"
    other = "<a href='https://elsewhere.com/pricing'>Pricing</a><a href='/hinnasto'>Hinnasto</a>"
    assert longtail.pricing_link(other, "https://tili.fi/") == "https://tili.fi/hinnasto"


def test_intent_queries_variants_and_local():
    qs = longtail.intent_queries(need(), {"kind": "digital"})
    texts = [q for q, _, _ in qs]
    assert 3 <= len(qs) <= 5
    assert texts[0] == "unlimited graphic design subscription pricing per month"
    assert "graphic design agency monthly retainer price" in texts
    assert "productized graphic design service pricing" in texts
    assert any(p == "listicle" for _, _, p in qs)
    fi = longtail.intent_queries(need("bookkeeping service finland"),
                                 {"kind": "service", "labels": {"fi": "Kirjanpito", "en": "Accounting"}})
    assert ("Kirjanpito hinnasto", "fi", "local") in fi
    assert longtail.core_of(need("web developer for small business")) == "web development"


def test_classify_applies_to_digital_not_local_trades_or_products():
    assert longtail.classify(need()) is not None
    assert longtail.classify(need("web developer for small business")) is not None
    assert longtail.classify(need("bookkeeping service finland")) is not None
    assert longtail.classify(need("home cleaning tilburg 60m2")) is None
    assert longtail.classify(need("sony a7 iii body")) is None


def test_plans_to_offers_entry_plan():
    plans = longtail.parse_plans_text(page("penji_pricing.html"), "penji.co")
    offers = longtail.plans_to_offers(plans, "https://penji.co/pricing/", provider="Penji",
                                      tagline="Unlimited Graphic Design Subscription")
    assert len(offers) == 1
    o = offers[0]
    assert (o.price, o.currency, o.unit, o.condition, o.source) == (995.0, "USD", "month", "service", "penji.co")
    assert o.raw["longtail"] and len(o.raw["plans"]) == 3 and o.raw["period"] == "month"
    assert "Penji Essentials" in o.title and "Subscription" in o.title
    assert len(longtail.plans_to_offers(plans, "https://penji.co/pricing/", provider="Penji", all_plans=True)) == 3
    assert longtail.normalize_plans([{"name": "X", "price": 5, "currency": "eur", "period": "project"}])[0]["period"] == "job"


def test_note_listicle_only_when_collecting():
    longtail.note_listicle("https://x.com/best-design", "10 best design subscriptions")   # nobody collecting: no-op
    tok = longtail.LISTICLES.set([])
    try:
        longtail.note_listicle("https://x.com/a", "Designjoy alternatives")
        longtail.note_listicle("https://x.com/b", "Buy a sofa")
        longtail.note_listicle("https://x.com/a", "Designjoy alternatives")
        assert [x["url"] for x in longtail.LISTICLES.get()] == ["https://x.com/a"]
    finally:
        longtail.LISTICLES.reset(tok)


def test_discover_hands_skipped_listicles_to_the_long_tail(monkeypatch):
    from agora import discover

    async def fake_search(query, n=10, highlights=False, country=None, **kw):
        return [{"url": "https://www.manypixels.co/blog/graphic-design/top-unlimited-companies",
                 "title": "13 Best unlimited graphic design services in 2026"}]
    monkeypatch.setattr(discover.contextdev, "search", fake_search)

    async def run():
        longtail.LISTICLES.set([])
        evs = [e async for e in discover.discover(need(), settle_s=0.1, tokens=2)]
        return evs, longtail.LISTICLES.get()
    evs, bag = asyncio.run(run())
    assert any(e.type == "skip" for e in evs)
    assert bag and bag[0]["url"].endswith("top-unlimited-companies")


# --------------------------------------------------------------------------- registry

def test_store_roundtrip_and_lookup():
    longtail_store.save_provider("designjoy.co", name="Designjoy", category_id="cat:design", category="Design",
                                 terms=["graphic", "design"], home_url="https://designjoy.co/",
                                 pricing_url="https://designjoy.co/", found_via="search",
                                 plans=[{"name": "Monthly Club", "price": 4995, "currency": "USD", "period": "month",
                                         "features": []}])
    longtail_store.save_provider("designjoy.co", terms=["subscription", "design"], plans=[])   # empty read keeps plans
    got = longtail_store.get("designjoy.co")
    assert got["plans"][0]["price"] == 4995 and got["fresh"] and got["hits"] == 2
    assert "subscription" in got["terms"]
    assert [p["domain"] for p in longtail_store.providers_for("cat:design", [])] == ["designjoy.co"]
    assert [p["domain"] for p in longtail_store.providers_for(None, ["graphic", "design", "logo"])] == ["designjoy.co"]
    assert longtail_store.providers_for(None, ["bookkeeping", "finland"]) == []
    old = longtail_store.providers_for("cat:design", [], now=time.time() + 10 * 24 * 3600)
    assert not old[0]["fresh"]


# --------------------------------------------------------------------------- the lane, end to end (offline)

def run_lane(monkeypatch, results_by_query, served, *, paid_max=3, deadline_s=8.0):
    calls: list[str] = []

    async def fake_search(query, n=10, highlights=False, country=None, **kw):
        calls.append(query)
        for key, res in results_by_query.items():
            if key in query:
                return res
        return []
    monkeypatch.setattr(longtail.contextdev, "search", fake_search)

    async def no_extract(*a, **k):
        calls.append("extract")
        return None
    monkeypatch.setattr(longtail.contextdev, "extract", no_extract)
    monkeypatch.setattr(longtail, "_transport", transport(served))
    monkeypatch.setattr(longtail, "PAID_START_DELAY", 0.0)

    async def go():
        out = []
        async for item in longtail.lane(need(), deadline=time.monotonic() + deadline_s, paid_max=paid_max):
            out.append(item)
        return out
    t = time.monotonic()
    items = asyncio.run(go())
    return items, calls, time.monotonic() - t


def test_lane_finds_designjoy_and_listicle_providers(monkeypatch):
    served: list[str] = []
    results = {
        "unlimited graphic design subscription pricing": [
            {"url": "https://designjoy.co/", "title": "Designjoy - Design as a Subscription"},
            {"url": "https://penji.co/pricing/", "title": "Pricing Plans | Penji"},
            {"url": "https://www.webtonic.io/blog/8-best-graphic-design-subscription-services-unlimited-design-compared",
             "title": "8 Best Graphic Design Subscription Services: Unlimited Design Compared"},
            {"url": "https://www.instagram.com/designjoy", "title": "designjoy on instagram"},
        ],
    }
    items, calls, took = run_lane(monkeypatch, results, served)
    offers = [x for x in items if isinstance(x, Offer)]
    events = [x for x in items if isinstance(x, Event)]
    by_source = {o.source: o for o in offers}
    assert by_source["designjoy.co"].price == 4995 and by_source["designjoy.co"].unit == "month"
    assert by_source["penji.co"].price == 995
    assert by_source["manypixels.co"].price == 699            # named in the article, domain guessed, /pricing read
    assert by_source["manypixels.co"].raw["found_via"] == "listicle"
    assert all(o.condition == "service" and o.raw["longtail"] for o in offers)
    assert events[0].type == "lane" and events[0].data["lane"] == "longtail" and len(events[0].data["queries"]) >= 3
    assert any(e.type == "source" and e.data.get("listicle") for e in events)
    assert not any("instagram" in u for u in served)
    summary = events[-1]
    assert summary.type == "longtail" and summary.data["paid"] <= 3
    assert len([c for c in calls]) <= 3
    assert "designjoy.co alternatives" in calls or any("alternatives" in c for c in calls)
    assert took < 8.5
    # the registry learned them
    assert longtail_store.get("designjoy.co")["pricing_url"] == "https://designjoy.co/"
    assert longtail_store.get("manypixels.co")["plans"][0]["name"] == "Advanced"


def test_lane_second_hunt_reuses_registry_for_free(monkeypatch):
    served: list[str] = []
    results = {"unlimited graphic design subscription pricing": [
        {"url": "https://designjoy.co/", "title": "Designjoy - Design as a Subscription"}]}
    run_lane(monkeypatch, results, served)
    served.clear()
    items, calls, _ = run_lane(monkeypatch, {}, served, paid_max=0)
    offers = [x for x in items if isinstance(x, Offer)]
    assert [o.source for o in offers] == ["designjoy.co"]
    assert offers[0].read_via == "longtail_registry" and offers[0].price == 4995
    assert calls == [] and served == []                      # no search, no fetch: free


def test_lane_respects_paid_cap_and_deadline(monkeypatch):
    served: list[str] = []
    items, calls, took = run_lane(monkeypatch, {}, served, paid_max=1, deadline_s=3.0)
    assert len(calls) <= 1
    assert took < 3.5
    assert [x for x in items if isinstance(x, Event)][-1].data["paid"] <= 1


def test_lane_off_for_products_and_env(monkeypatch):
    async def go(n):
        return [x async for x in longtail.lane(n, deadline=time.monotonic() + 2)]
    assert asyncio.run(go(need("sony a7 iii body"))) == []
    monkeypatch.setenv("AGORA_LONGTAIL", "0")
    assert asyncio.run(go(need())) == []
