"""Direct marketplace search pages (agora.marketplaces): the registry, the per-site query, the plan, the code-only
splitter on real pages (markdown captured live 14 Nov from kleinanzeigen.de, vinted.fi, backmarket.de), and the
reader / discover wiring. Splitter ported from teammate Robert's (rpaszekdev) agora-junction-2026."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import fx, reader
from agora import marketplaces as m
from agora.models import Need

FIX = pathlib.Path(__file__).parent / "fixtures"
AIRPODS = Need(raw="airpods pro 2", thing="airpods pro 2")


def md(name: str) -> tuple[str, str]:
    text = (FIX / f"md_{name}.md").read_text()
    first, rest = text.split("\n", 1)
    return first.removeprefix("<!-- ").removesuffix(" -->"), rest


@pytest.fixture(autouse=True)
def direct_on(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None
    cd._transport = None


# ------------------------------------------------------------------ registry

def test_every_search_url_maps_back_to_its_site():
    for site in m.SITES.values():
        assert m.site_for(m.build_url(site, "airpods pro 2")) is site, site.key
    assert m.build_url(m.SITES["kleinanzeigen"], "airpods pro 2") == "https://www.kleinanzeigen.de/s-airpods-pro-2/k0"
    assert m.build_url(m.SITES["tori"], "ikea kallax") == "https://www.tori.fi/recommerce/forsale/search?q=ikea+kallax"


def test_listing_pages_are_not_search_pages_but_found_category_pages_are():
    assert m.site_for("https://www.tori.fi/recommerce/forsale/item/49853401") is None
    assert m.site_for("https://www.kleinanzeigen.de/s-anzeige/airpods-pro-2/3570916187-172-1697") is None
    assert m.site_for("https://www.vinted.fi/items/10793030086-lewy-airpod") is None
    assert m.site_for("https://www.verkkokauppa.com/fi/product/123/x") is None
    assert m.site_for("https://example.com/search?q=x") is None
    # a web search found another kleinanzeigen search page: same layout, same splitter
    assert m.site_for("https://www.kleinanzeigen.de/s-haus-garten/ikea-kallax-untergestell/k0c80").key == "kleinanzeigen"


def test_second_hand_sources_from_roberts_list():
    assert m.second_hand("www.tori.fi") == ("fi", "classifieds")
    assert m.second_hand("vinted.fi") is not None and m.second_hand("backmarket.de") is not None
    assert m.second_hand("verkkokauppa.com") is None
    assert dv.is_marketplace("okidoki.ee") and not dv.is_marketplace("swappie.com")   # classifieds only


# ------------------------------------------------------------------ query per site

@pytest.mark.parametrize("thing,site,want", [
    ("ikea kallax shelf", "tori", "ikea kallax"),           # sellers write 'Kallax-hylly', 'Kallax Regal'
    ("dyson v15 vacuum", "kleinanzeigen", "dyson v15"),
    ("used airpods pro 2", "vinted_fi", "airpods pro 2"),
    ("road bike", "kleinanzeigen", "rennrad"),               # only generic words: translated
    ("road bike", "marktplaats", "racefiets"),
    ("road bike", "gumtree", "road bike"),
    ("nintendo switch oled", "tori", "nintendo switch oled"),
])
def test_site_query(thing, site, want):
    assert m.site_query(thing, m.SITES[site]) == want


# ------------------------------------------------------------------ the plan

def test_plan_home_marketplace_free_then_big_eu_ones_while_tokens_last():
    full = m.direct_pages("airpods pro 2", "used", None, "fi", tokens=10)
    # the source registry (agora.sources) verified vinted, kleinanzeigen, marktplaats, blocket, dba, finn readable by
    # plain fetch: they cost no token now, only olx / leboncoin still need a paid read
    assert [(d.site.key, d.paid, d.page) for d in full][:6] == [
        ("tori", False, 1), ("vinted_fi", False, 1), ("kleinanzeigen", False, 1), ("marktplaats", False, 1),
        ("blocket", False, 1), ("olx_pl", True, 1)]                     # small thing: EU-wide
    assert sum(d.paid for d in full) <= m.MAX_PAID_DIRECT + 2 and not any(d.extra for d in full)
    dry = m.direct_pages("airpods pro 2", "used", None, "fi", tokens=0)
    assert not any(d.paid for d in dry) and dry[0].site.key == "tori"   # free pages need no token: always
    assert "olx_pl" not in [d.site.key for d in dry]
    assert [d.site.key for d in m.direct_pages("airpods pro 2", "refurbished", None, "fi", 10)][0] == "backmarket"
    assert [d.site.key for d in m.direct_pages("airpods pro 2", "new", None, "fi", 10)][0] == "verkkokauppa"


def test_plan_bulky_things_only_at_home():
    assert [d.site.key for d in m.direct_pages("ikea kallax shelf", "used", None, "fi", 4)] == ["tori"]
    spare = m.direct_pages("city bike", "used", None, "fi", 10)       # tokens to spare: 'also in the EU' set
    assert spare[0].site.key == "tori" and not spare[0].extra
    assert spare[1:] and all(d.extra and d.page == 1 for d in spare[1:])
    assert not any(d.site.key.startswith("vinted") for d in spare)
    assert m.direct_pages("ikea kallax shelf", "new", None, "fi", 10) == []
    koln = m.direct_pages("kallax", "used", "de", None, 10)
    assert koln[0].site.key == "kleinanzeigen" and koln[0].url.endswith("/s-kallax/k0") and not koln[0].extra
    assert not koln[0].paid             # read free, its pages 2..N paginated by the reader (no paid page 2)
    assert all(d.extra for d in koln[1:])


def test_discover_emits_direct_pages_first_and_drops_the_eu_used_search(monkeypatch):
    calls: list[str] = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append(query)
        return []
    monkeypatch.setattr(cd, "search", search)

    async def run():
        return [e async for e in dv.discover(AIRPODS, tokens=10, settle_s=0.05)]
    events = asyncio.run(run())
    used = next(e.data for e in events if e.type == "lane" and e.data["lane"] == "used")
    assert [d["site"] for d in used["direct"]][:3] == ["tori", "vinted_fi", "kleinanzeigen"]
    scope = next(e.data for e in events if e.type == "scope")
    assert scope["scope"] == "eu" and scope["eu_included"] and scope["country"] == "FI"
    assert not any("kleinanzeigen OR vinted" in q for q in calls)     # read directly instead of searched
    srcs = [e.data for e in events if e.type == "source"]
    assert srcs[0]["url"].startswith("https://www.tori.fi/recommerce/forsale/search?q=airpods")
    assert all(s["direct"] and s["list_page"] for s in srcs[:4])
    assert reader._HINTS[srcs[1]["url"]]["lane"] == "used"
    assert dv.paid_priority(srcs[1]["url"], "product", "used") == 0          # read before item pages


def test_direct_off_is_the_old_plan(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "0")
    assert dv.plan_direct(AIRPODS, ["used"], 10, 0) == {}
    assert reader.direct_site("https://www.kleinanzeigen.de/s-airpods-pro-2/k0", AIRPODS) is None


# ------------------------------------------------------------------ splitter (Robert's split_rows) on real pages

@pytest.mark.parametrize("text,want", [("1.199,00", 1199.0), ("4 500", 4500.0), ("368.83", 368.83),
                                        ("1,299", 1299.0), ("41,34", 41.34)])
def test_to_number(text, want):
    assert m.to_number(text) == want


def test_first_price_skips_monthly_and_prefers_bold():
    assert m.first_price("from 12 €/kk or **399 €** once") == 399.0
    assert m.first_price("12 €/month then 299 €") == 299.0
    assert m.first_price("EUR 1.234,50 incl.") == 1234.5
    assert m.first_price("1 200 kr.") == 1200.0 and m.first_price("no price") is None


def test_split_kleinanzeigen_page():
    url, text = md("kleinanzeigen_airpods-pro-2")
    rows = m.split_rows(text, "", m.SITES["kleinanzeigen"])
    assert len(rows) == 25                                           # every row on the page, no cap
    assert all(r["url"].startswith("https://www.kleinanzeigen.de/s-anzeige/") and r["currency"] == "EUR" for r in rows)
    one = next(r for r in rows if r["url"].endswith("/3570916187-172-1697"))
    assert one["title"] == "AirPods Pro 2" and one["price"] == 39.0
    assert len({r["url"] for r in rows}) == len(rows)


def test_split_vinted_page_cleans_titles_and_keeps_the_buyer_fee():
    _, text = md("vinted_fi_airpods-pro-2")
    rows = m.split_rows(text, "", m.SITES["vinted_fi"])
    assert len(rows) == 96                                           # every row (was cut at 25)
    first = rows[0]
    assert first["title"] == "lewy airpod pro 2 gen lightning"            # ', Tuotemerkki: Apple, ...' cut
    assert first["price"] == 41.34 and first["price_with_fee"] == 44.11
    assert all("?" not in r["url"] and "/items/" in r["url"] for r in rows)   # ?referrer=catalog dropped


def test_split_backmarket_page():
    _, text = md("backmarket_airpods-pro-2")
    rows = m.split_rows(text, "", m.SITES["backmarket"])
    assert len(rows) == 8 and rows[0]["title"] == "AirPods Pro 2" and rows[0]["price"] == 175.0


def test_split_heading_title_layout():
    """Schibsted (tori, blocket, finn, dba): price above a '## title', the item link below it."""
    page = ("[Ilmoitukset](https://www.tori.fi/recommerce/forsale/search)\n\n"
            "![kuva](https://img.tori.net/1.jpg)\n\n120 €\n\n## AirPods Pro 2 hyvä kunto\n\n"
            "[Katso](https://www.tori.fi/recommerce/forsale/item/111)\n\nHelsinki\n\n"
            "1 450 kr\n\n## Nintendo Switch OLED valkoinen\n\n[Katso](https://www.blocket.se/recommerce/forsale/item/222)\n")
    rows = m.split_rows(page, "", m.SITES["tori"])
    assert [(r["title"], r["price"]) for r in rows] == [("AirPods Pro 2 hyvä kunto", 120.0)]   # other site's link
    se = m.split_rows(page.replace("tori.fi/recommerce/forsale/item/111", "blocket.se/recommerce/forsale/item/111"),
                      "", m.SITES["blocket"])
    assert [r["price"] for r in se] == [120.0, 1450.0] and se[1]["currency"] == "SEK"


def test_find_image_near_the_listing_link():
    html = ('<div><a href="/s-anzeige/airpods-pro-2/3570916187-172-1697"><img src="data:x"/>'
            '<img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/1.jpg?rule=$_2.AUTO"/></a></div>')
    got = m.find_image(html, "https://www.kleinanzeigen.de/s-anzeige/airpods-pro-2/3570916187-172-1697")
    assert got == "https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/1.jpg?rule=$_2.AUTO"


# ------------------------------------------------------------------ reader: one markdown read per page

@pytest.fixture
def cd_md(monkeypatch):
    """Context.dev online against a MockTransport: markdown scrapes answer with the captured page."""
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    calls: list[dict] = []
    pages = {"markdown": md("kleinanzeigen_airpods-pro-2")[1]}

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        calls.append(body)
        if body.get("formats", {}).get("markdown"):
            return httpx.Response(200, json={"markdown": {"data": pages["markdown"]}, "html": {"data": ""},
                                             "key_metadata": {"credits_consumed": 1}})
        if body.get("formats", {}).get("json"):
            return httpx.Response(200, json={"json": {"data": {"listings": []}}})
        return httpx.Response(500, json={"message": "unexpected call in test"})
    cd._transport = httpx.MockTransport(handler)

    def no_fetch(*a, **kw):
        raise AssertionError("a known marketplace without ItemList is not fetched directly")
    monkeypatch.setattr(reader, "fetch_html", no_fetch)
    return calls, pages


def test_known_marketplace_page_is_one_markdown_read_cut_into_listings(cd_md):
    calls, _ = cd_md
    url, _ = md("kleinanzeigen_airpods-pro-2")
    free, why = asyncio.run(reader.read_with_reason(url, AIRPODS, lane="used", paid=False, expand_lists=True))
    assert free is None and "list read" in why and calls == []      # free phase: straight to the paid phase
    got, via = asyncio.run(reader.read_with_reason(url, AIRPODS, lane="used", snippet_ok=True, expand_lists=True))
    assert via == "contextdev_markdown_split" and len(calls) == 1
    body = calls[0]
    assert body["formats"] == {"markdown": True, "html": True} and body["sharedParams"] == {"country": "DE"}
    assert body["maxAgeMs"] == reader.SPLIT_MAX_AGE_MS
    assert isinstance(got, list) and 10 <= len(got) <= reader.MAX_SPLIT_OFFERS
    for o in got:
        assert o.source == "kleinanzeigen.de" and o.read_via == "contextdev_markdown_split"
        assert o.raw["from_list_page"] == url and o.raw["step"] == "markdown_split"
        assert o.url.startswith("https://www.kleinanzeigen.de/s-anzeige/") and o.price_eur
    # every row is kept (the read count stays honest); another product is rejected by resolve, with its reason
    from agora import resolve
    other = [o for o in got if "iPhone 16" in o.title]
    assert other and all(resolve.explain(AIRPODS, o)[1] for o in other)
    assert sum(o.condition == "used" for o in got) >= len(got) - 3


def test_page_without_listing_links_spends_no_second_read(cd_md):
    calls, pages = cd_md
    pages["markdown"] = "# Keine Ergebnisse\n\nLeider nichts gefunden."
    got, why = asyncio.run(reader.read_with_reason("https://www.kleinanzeigen.de/s-zzqx/k0", AIRPODS, lane="used",
                                                   expand_lists=True))
    assert got is None and "no listings" in why and len(calls) == 1


def test_links_without_prices_fall_back_to_the_json_list_read(cd_md):
    calls, pages = cd_md
    pages["markdown"] = "".join(f"[AirPods Pro 2 nummer {i}](https://www.kleinanzeigen.de/s-anzeige/airpods/{i}-172-1)\n\n"
                                "Preis auf Anfrage\n\n" for i in range(5))
    asyncio.run(reader.read_with_reason("https://www.kleinanzeigen.de/s-airpods/k0", AIRPODS, lane="used",
                                        expand_lists=True))
    assert [("markdown" in c["formats"]) for c in calls] == [True, False]
    assert calls[1]["jsonParams"]["schema"] == reader.LIST_SCHEMA
