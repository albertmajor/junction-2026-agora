"""Coverage round (owner: "look how many listings there are here bro and it only find like one?").

Offline, against the owner's own saved tori.fi page (trimmed: tests/fixtures/tori_puhelimet_category.html, the
category 'Puhelimet ja tarvikkeet' with 19,370 listings, 54 on the page) and small synthetic pages.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import time

import pytest

from agora import discover as dv
from agora import hunt as H
from agora import judge as J
from agora import marketplaces as m
from agora import reader
from agora import resolve as R
from agora import sources as S
from agora.models import Need, Offer
from agora.need import categorize, parse_need
from agora.sources import categories as C

FIX = pathlib.Path(__file__).parent / "fixtures"
TORI_URL = "https://www.tori.fi/recommerce/forsale/search?sub_category=1.93.3217"


@pytest.fixture(autouse=True)
def _direct_on(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    monkeypatch.setenv("AGORA_COUNTRY", "fi")


def tori_page() -> str:
    return (FIX / "tori_puhelimet_category.html").read_text()


def tori_offers(need: Need, url: str = TORI_URL) -> list[Offer]:
    data = reader._extruct(tori_page(), url)
    items = reader.offers_from_itemlist(data, url, need, "used", reader.MAX_SPLIT_OFFERS)
    for o in items:
        o.raw["site"] = "tori"
    return items


def need(text: str, cat: str | None = None) -> Need:
    n = parse_need(text)
    categorize(n, cat)
    return n


def offer(title: str, price: float = 100.0, **raw) -> Offer:
    return Offer(url=f"https://www.tori.fi/recommerce/forsale/item/{abs(hash(title)) % 10**8}", source="tori.fi",
                 title=title, price=price, currency="EUR", price_eur=price, condition="used",
                 raw={"site": "tori", "from_list_page": TORI_URL, **raw})


# ------------------------------------------------------------------ the owner's page

def test_owner_page_total_is_the_sites_own_count():
    # '19&nbsp;370 ilmoitusta' in the meta tag was read as 370
    assert m.market_total(tori_page()[:400000]) == (19370, False)


def test_owner_page_every_listing_is_read_and_a_generic_phone_need_keeps_the_phones():
    n = need("puhelin")
    items = tori_offers(n)
    assert len(items) >= 40                              # every priced row on the page (no title gate any more)
    things = R.resolve(n, items)
    kept = {id(o) for t in things for o in t.offers}
    assert len(kept) >= 40                               # was 4 (the page also lists cases, a battery, a box)
    reasons = {R.explain(n, o)[1] for o in items if id(o) not in kept}
    assert any(r and "another kind of thing" in r for r in reasons)      # the smartwatch / AirPods on the page
    assert all(r and re.search(r"accessory|a part|another kind", r) for r in reasons)   # only non-phones go


def test_tree_hunt_on_mobile_phones_keeps_the_phones():
    # a hunt from the tree: thing = the node's English label (was: 0 kept, 'mobile' was searched)
    n = need("Mobile & Smart Phones", "sp:el-4-8-5")
    assert R.is_generic(n)
    items = tori_offers(n)
    things = R.resolve(n, items)
    assert sum(len(t.offers) for t in things) >= 40


def test_specific_need_still_strict():
    n = need("iphone 13")
    items = tori_offers(n)
    kept = [o for t in R.resolve(n, items) for o in t.offers]
    assert kept and all(re.search(r"iphone\s*13", o.title, re.I) for o in kept
                        if re.search(r"iphone\s*(?:\d|x|se)", o.title, re.I))    # never another model


# ------------------------------------------------------------------ generic needs

@pytest.mark.parametrize("text,cat,generic", [
    ("puhelin", None, True), ("phone", None, True), ("baby stroller", None, True), ("kitchen table", None, True),
    ("used winter jacket", None, True), ("Mobile & Smart Phones", "sp:el-4-8-5", True), ("sofas", "sp:fr-22", True),
    ("iphone 13", None, False), ("lego", None, False), ("herman miller chair", None, False), ("ps5", None, False),
    ("ikea kallax shelf", None, False),
])
def test_is_generic(text, cat, generic):
    assert R.is_generic(need(text, cat)) is generic


def test_generic_need_rejects_another_kind_and_cases_but_keeps_unnamed_phones():
    n = need("sofa")
    coffee = offer("Sohvapöytä tammi")                              # a coffee table on the 'sohva' search
    r, why = R.explain(n, coffee)
    assert why and "coffee table" in why
    assert R.explain(n, offer("Kulmasohva harmaa"))[1] is None
    p = need("puhelin")
    assert R.explain(p, offer("Samsung Galaxy A52 128GB"))[1] is None         # names no kind: the site's search
    assert R.explain(p, offer("Puhelimen suojakuori iPhone 12"))[1]            # a case is still a case


def test_exact_category_page_vouches_for_titles_without_the_word():
    n = need("road bike")
    plain = Offer(url="https://x.example/a", source="x.example", title="Canyon Endurace CF 7", price=900,
                  currency="EUR", price_eur=900, condition="used")
    assert R.relevance(n, plain) < 0.5                          # a web page naming no bike: not trusted
    from_cat = offer("Canyon Endurace CF 7", 900, category_page={"node": "sp:sg-4-4-3-11", "exact": True})
    assert R.relevance(n, from_cat) >= 0.5


# ------------------------------------------------------------------ query wording

@pytest.mark.parametrize("thing,site,want", [
    ("puhelin", "kleinanzeigen", "handy"),          # a Finnish word on a German site (was: 'puhelin')
    ("puhelin", "marktplaats", "telefoon"),
    ("baby stroller", "tori", "lastenvaunut"),      # was 'baby'
    ("kitchen table", "tori", "ruokapöytä"),        # was 'kitchen'
    ("winter jacket", "tori", "talvitakki"),        # was 'winter'
    ("mobile phones", "blocket", "mobiltelefon"),   # was 'mobile'
    ("herman miller chair", "tori", "herman miller"),
    ("sohva", "kleinanzeigen", "sofa"),
])
def test_site_query_coverage_round(thing, site, want):
    assert m.site_query(thing, m.SITES[site]) == want


# ------------------------------------------------------------------ category pages in the plan

def test_generic_need_reads_the_marketplaces_category_pages():
    n = need("Mobile & Smart Phones", "sp:el-4-8-5")
    plan = dv.plan_direct(n, dv.lanes_for(n), 0.0, 0)
    used = {d.site.key: d for d in plan["used"]}
    assert "product_category=2.93.3217.39" in used["tori"].url and used["tori"].category == "sp:el-4-8-5"
    assert used["tori"].exact and "q=" not in used["tori"].url
    for k in ("blocket", "finn", "dba"):                         # Schibsted ids are shared
        assert "product_category=2.93.3217.39" in used[k].url
    assert used["kleinanzeigen"].url.endswith("/s-handy-telekom/c173")
    assert m.CATEGORY_PAGES[used["tori"].url]["exact"] is True
    assert m.PAGE_PLAN[used["tori"].url] == m.GENERIC_HOME_PAGES          # home marketplace read deep
    assert m.PAGE_PLAN[used["blocket"].url] == m.GENERIC_PAGES
    # the plain search for a specific need is unchanged
    p = need("iphone 13")
    tori = next(d for d in dv.plan_direct(p, dv.lanes_for(p), 0.0, 0)["used"] if d.site.key == "tori")
    assert tori.url.endswith("q=iphone+13") and tori.category is None


def test_broader_category_sends_the_word_too():
    page = C.page_for("tori", "sp:sg-4-4-3-11", "maantiepyörä")
    assert page and "product_category=2.69.3963.257" in page.url and "q=maantiepy" in page.url and page.exact


def test_category_map_nodes_exist_and_auto_entries_are_never_exact():
    from agora import taxonomy
    for nid in list(C.HAND) + list(C.GENERIC_NODES.values()):
        assert taxonomy.node(nid) is not None, nid
    auto_only = next(nid for nid, v in C._auto().items() if "schibsted" in v and nid not in C.HAND
                     and C.entry_for(nid)[1] == nid)
    page = C.page_for("tori", auto_only)
    assert page is not None and page.exact is False


def test_site_for_knows_category_pages_and_their_next_pages():
    for url in ("https://www.kleinanzeigen.de/s-handy-telekom/c173",
                "https://www.tori.fi/recommerce/forsale/search?product_category=2.93.3217.39",
                "https://www.marktplaats.nl/l/huis-en-inrichting/banken-bankstellen/"):
        assert m.site_for(url) is not None, url
    kz = m.SITES["kleinanzeigen"]
    assert m.page_url(kz, "https://www.kleinanzeigen.de/s-handy-telekom/c173", 2) == \
        "https://www.kleinanzeigen.de/s-handy-telekom/seite:2/c173"
    assert m.page_url(kz, "https://www.kleinanzeigen.de/s-fahrraeder/rennrad/k0c217", 3) == \
        "https://www.kleinanzeigen.de/s-fahrraeder/seite:3/rennrad/k0c217"
    assert m.page_url(kz, "https://www.kleinanzeigen.de/s-ps5/k0", 2) == "https://www.kleinanzeigen.de/s-seite:2/ps5/k0"


# ------------------------------------------------------------------ pagination

def _paged_tori(n_pages: int):
    """fetch_html stub: page k of the fixture with item ids made unique per page."""
    base = tori_page()
    calls: list[str] = []

    async def fake(url: str):
        calls.append(url)
        k = int((re.search(r"[?&]page=(\d+)", url) or [None, 1])[1])
        if k > n_pages:
            return 200, "<html><head><title>x</title></head><body></body></html>"
        return 200, re.sub(r"/item/(\d+)", lambda mm: f"/item/{k}{mm.group(1)}", base)
    return fake, calls


def test_category_page_is_read_deep_and_never_stops_on_word_match(monkeypatch):
    n = need("Mobile & Smart Phones", "sp:el-4-8-5")
    url = C.page_for("tori", "sp:el-4-8-5").url
    m.CATEGORY_PAGES[url] = {"node": "sp:el-4-8-5", "need_node": "sp:el-4-8-5", "exact": True, "site": "tori"}
    m.PAGE_PLAN[url] = 12
    fake, calls = _paged_tori(30)
    monkeypatch.setattr(reader, "fetch_html", fake)
    got, via = asyncio.run(reader.read_with_reason(url, n, paid=False, expand_lists=True))
    assert via == "jsonld" and isinstance(got, list)
    assert len(calls) == 12 and len(got) >= 11 * 40            # 12 pages: the plan's depth, all rows kept
    assert all(o.raw["category_page"]["exact"] for o in got)
    assert got[0].raw["market"]["total"] == 19370


def test_translated_search_keeps_paginating(monkeypatch):
    # an English need, Finnish titles: the page's own query words count as a match (was: stop after a batch)
    n = need("sofa")
    url = "https://www.tori.fi/recommerce/forsale/search?q=sohva"
    items = [offer(t) for t in ("Kulmasohva harmaa", "Sohva 3h nahka", "Vuodesohva", "Isku sohvat", "Nojatuoli")]
    assert reader._page_match(items, n, url) >= 0.8              # the Finnish titles match the Finnish query
    assert reader.page_terms(url) == {"sohva"}
    assert reader.page_terms("https://www.kleinanzeigen.de/s-seite:2/winterjacke/k0") == {"winterjacke"}


def test_hunt_listing_cap_stops_pagination(monkeypatch):
    n = need("Mobile & Smart Phones", "sp:el-4-8-5")
    url = C.page_for("tori", "sp:el-4-8-5").url
    m.PAGE_PLAN[url] = 20
    fake, calls = _paged_tori(30)
    monkeypatch.setattr(reader, "fetch_html", fake)

    async def run():
        reader.HUNT_LISTINGS.set([0, 120])
        return await reader.read_with_reason(url, n, paid=False, expand_lists=True)
    got, _ = asyncio.run(run())
    assert len(calls) <= 4                                    # 120 listings ~ 3 pages, then it stops


# ------------------------------------------------------------------ splitter

def test_kleinanzeigen_rows_are_listings_not_the_category_menu():
    rec = S.get("kleinanzeigen_de")
    page = ('<a href="/s-immobilien/c195">Immobilien</a><a href="/s-mode-beauty/c153">Mode</a>'
            + "".join(f'<article><a href="/s-anzeige/ps5-slim-digital/{3500000000 + i}-279-3214">PS5 Slim {i}</a>'
                      f'<p>{300 + i} € VB</p></article>' for i in range(25)))
    rows = S.rows_from_html(page, "https://www.kleinanzeigen.de/s-ps5/k0", rec, max_rows=100)
    assert len(rows) == 25 and all("/s-anzeige/" in r["url"] for r in rows)


def test_marktplaats_rows_from_embedded_json():
    data = {"props": {"pageProps": {"searchRequestAndResponse": {"listings": [
        {"itemId": "m1", "title": "Lego Set - 7237 - City - Police Station", "description": "compleet",
         "priceInfo": {"priceCents": 2500, "priceType": "FIXED"}, "vipUrl": "/v/speelgoed/lego/m1-lego-set",
         "location": {"cityName": "Utrecht"}, "imageUrls": ["//images.marktplaats.com/x.jpg"]},
        {"itemId": "m2", "title": "Lego partij", "priceInfo": {"priceCents": 0, "priceType": "SEE_DESCRIPTION"},
         "vipUrl": "/v/speelgoed/lego/m2-partij"},
        {"itemId": "m3", "title": "Lego Technic 42115", "priceInfo": {"priceCents": 19900, "priceType": "FIXED"},
         "vipUrl": "/v/speelgoed/lego/m3-technic"}]}}}}
    import json
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    rows = S.rows_from_next_data(page, "https://www.marktplaats.nl/q/lego/", S.get("marktplaats_nl"))
    assert [r["title"] for r in rows][0] == "Lego Set - 7237 - City - Police Station"    # no card text in it
    assert rows[0]["price"] == 25.0 and rows[0]["location"] == "Utrecht" and rows[1]["price"] is None
    assert rows[0]["url"] == "https://www.marktplaats.nl/v/speelgoed/lego/m1-lego-set"


def test_carousel_labels_are_not_titles():
    rec = S.get("blocket_se")
    page = "".join(f'<article><a href="https://www.blocket.se/recommerce/forsale/item/{28000000 + i}" '
                   f'aria-label="Product images, 1 of 3"></a><h2><a href="https://www.blocket.se/recommerce/forsale/'
                   f'item/{28000000 + i}">Lego {i}</a></h2><span>{100 + i} kr</span></article>' for i in range(8))
    rows = S.rows_from_html(page, "https://www.blocket.se/recommerce/forsale/search?q=lego", rec)
    assert rows and all(r["title"].startswith("Lego") for r in rows)


# ------------------------------------------------------------------ speed at 2,000 offers

def test_resolve_and_judge_stay_fast_at_2000_offers():
    n = need("puhelin")
    base = tori_offers(n)
    offers = []
    for k in range(2000):
        o = base[k % len(base)]
        offers.append(Offer(url=f"{o.url}?n={k}", source=o.source, title=o.title,
                            price=round(o.price * (0.8 + (k % 7) / 10), 2), currency="EUR",
                            price_eur=round(o.price * (0.8 + (k % 7) / 10), 2), condition="used",
                            raw={"site": "tori", "from_list_page": f"{TORI_URL}&page={k // 50}"}))
    t = time.monotonic()
    things = R.resolve(n, offers)
    J.judge(n, things, history=False)
    assert time.monotonic() - t < 8.0          # was ~16 s (O(n^2) resale comps + memo keys)
    assert sum(len(t.offers) for t in things) >= 1500


def test_live_leaderboard_samples_big_hunts():
    n = need("puhelin")
    base = tori_offers(n)
    offers = [Offer(url=f"{o.url}?n={k}", source=o.source, title=o.title, price=o.price, currency="EUR",
                    price_eur=o.price, condition="used", raw={"from_list_page": TORI_URL})
              for k in range(30) for o in base]
    s = H.sample_offers(offers)
    assert len(s) <= H.LIVE_SAMPLE and min(o.price_eur for o in s) == min(o.price_eur for o in offers)
    assert H.sample_offers(offers[:100]) == offers[:100]
