"""Used-dealer pages with several units (Wex: an Excellent (9) A7 III at £818 and a Good (8) one at £678 on the
same page), the seller's condition grade, like-for-like notes in the receipt, the courier's customs clearance
fee on imports, and rating badges on a shop's own page. Fixtures are trimmed copies of the real pages."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import judge as jd
from agora import reader, units
from agora import reviews as rv
from agora.models import Need, Offer, Thing
from agora.need import parse_need

FIX = pathlib.Path(__file__).parent / "fixtures"
WEX_URL = "https://www.wexphotovideo.com/sony-a7-iii-digital-camera-body-used-3349077/"
WEX_LIST = "https://www.wexphotovideo.com/used-sony-a7-iii/"


@pytest.fixture
def wex_page(monkeypatch):
    html = (FIX / "wex_sony_a7iii_used.html").read_text()
    monkeypatch.setattr(reader, "_transport", httpx.MockTransport(lambda req: httpx.Response(200, html=html)))
    return html


# ---------------------------------------------------------------- grades

@pytest.mark.parametrize("text,grade,score", [
    ("Condition: Excellent (9) | Very little signs of use", "Excellent (9)", 0.9),
    ("Condition: Good (8)", "Good (8)", 0.8),
    ("Condition: Mint (9+)", "Mint (9+)", 0.93),
    ("USED Sony A7 III Digital Camera Body — Very good (9-)", "Very good (9-)", 0.87),
    ("Cosmetic condition: | Well used | €304", "Well used", 0.6),       # MPB
    ("Condition: Like new", "Like new", 0.95),
    ("Grade: Fair", "Fair", 0.6),                                       # Back Market
    ("Zustand: Sehr gut", "Sehr gut", 0.85),                            # rebuy
])
def test_seller_grades(text, grade, score):
    got = units.grade_info(text)
    assert got["grade"] == grade and got["grade_score"] == score


def test_shutter_count_and_battery_health_but_no_false_grades():
    assert units.grade_info("Shutter Count (approximately): 8000")["shutter_count"] == 8000
    assert units.grade_info("Shutter count: | 12,165")["shutter_count"] == 12165
    assert units.grade_info("Battery health: 87%")["battery_health"] == 87
    assert units.grade_info("Condition: Used | shutter speed 1/8000s") == {}
    assert units.grade_info("This lens is in good shape") == {}


def test_mpb_single_unit_grade_from_the_saved_page():
    # MPB product page (trimmed text of the real page): one unit, "Cosmetic condition: Well used", €304
    text = ("Sony E 10-18mm f/4 OSS | 4192191 | We always photograph each unique item, so this is the exact "
            "product you'll receive. | Sony E 10-18mm f/4 OSS | Cosmetic condition: | Well used | €304 | Add to basket")
    assert units.grade_info(text) == {"grade": "Well used", "grade_score": 0.6}


# ---------------------------------------------------------------- units on one page

def test_wex_page_cards_are_the_other_units():
    cards = [c for c in units.cards_from_html((FIX / "wex_sony_a7iii_used.html").read_text(), WEX_URL)
             if c.get("grade")]
    assert len(cards) == 25
    good = next(c for c in cards if c["url"].endswith("-3370914/"))
    assert good["price"] == 678.0 and good["currency"] == "GBP" and good["grade"] == "Good (8)"
    assert good["shutter_count"] == 14641 and good["in_stock"] is True


def test_free_read_of_a_wex_page_gives_every_grade(wex_page):
    need = parse_need("sony a7 iii body")
    got, why = asyncio.run(reader.read_with_reason(WEX_URL, need, paid=False, expand_lists=True))
    assert why == "jsonld" and isinstance(got, list) and len(got) == units.MAX_UNITS
    by_url = {o.url: o for o in got}
    main = by_url[WEX_URL]                      # the page's own unit is always kept
    assert main.price == 818 and main.raw["grade"] == "Excellent (9)" and main.raw["shutter_count"] == 8000
    good = by_url["https://www.wexphotovideo.com/sony-a7-iii-digital-camera-body-used-3370914/"]
    assert good.price == 678 and good.raw["grade"] == "Good (8)" and good.raw["shutter_count"] == 14641
    assert good.raw["from_list_page"] == WEX_URL and good.raw["unit_of"] == WEX_URL
    assert {o.raw["grade"] for o in got} == {"Good (8)", "Very good (9-)", "Excellent (9)", "Mint (9+)"}
    assert all(o.condition == "used" and o.source == "wexphotovideo.com" for o in got)
    assert [o.price for o in got] == sorted(o.price for o in got)
    # without expand_lists the page is still ONE offer (the main unit), now with its grade
    one, _ = asyncio.run(reader.read_with_reason(WEX_URL, need, paid=False))
    assert one.price == 818 and one.raw["grade"] == "Excellent (9)"


def test_paid_read_of_a_dealer_page_keeps_every_unit(monkeypatch):
    """The live miss: Wex's /used-sony-a7-iii/ came back from the paid JSON read with 12 bodies, and only the
    first (£818) survived. Now every in-stock unit is an offer, cheapest of each grade first."""
    data = json.loads((FIX / "wex_used_a7iii_extract.json").read_text())

    async def extract(url, schema, instructions=None, **kw):
        assert "grade" in schema["properties"]["offers"]["items"]["properties"]
        return data

    async def product(url, **kw):
        return None

    monkeypatch.setattr(reader, "_transport", httpx.MockTransport(lambda req: httpx.Response(403, text="")))
    monkeypatch.setattr(cd, "extract", extract)
    monkeypatch.setattr(cd, "product", product)
    need = parse_need("sony a7 iii body")
    got, why = asyncio.run(reader.read_with_reason(WEX_LIST, need, expand_lists=True))
    assert why == "contextdev_json" and isinstance(got, list)
    prices = sorted(o.price for o in got)
    assert prices == [678, 750, 789, 799, 818, 827, 829]     # 12 bodies, 7 distinct price + grade pairs
    good = next(o for o in got if o.price == 678)
    assert good.raw["grade"] == "Good (8)" and good.raw["grade_score"] == 0.8
    assert good.url.endswith("-3370914/") and good.raw["from_list_page"] == WEX_LIST
    one, _ = asyncio.run(reader.read_with_reason(WEX_LIST, need))
    assert isinstance(one, Offer)               # callers that want one offer still get one


def test_ordinary_shop_page_is_not_cut_into_units():
    need = parse_need("sony a7 iii body")
    items = [Offer(url="https://shop.example/a7", source="shop.example", title="Sony A7 III body", price=p,
                   currency="EUR", price_eur=p, condition="new") for p in (1500, 1600)]
    assert reader.schema_units(items, {"page_type": "product"}, "https://shop.example/a7", need) == []


def test_units_without_own_links_get_anchors():
    need = parse_need("iphone 13 128gb")
    page = "https://www.backmarket.fi/fi-fi/p/iphone-13-128gb"
    items = [Offer(url=page, source="backmarket.fi", title="iPhone 13 128GB", price=p, currency="EUR", price_eur=p,
                   condition="refurbished", raw={"grade": g, "grade_score": units.grade_score(g)})
             for p, g in ((389, "Fair"), (429, "Good"), (469, "Excellent"))]
    got = reader.schema_units(items, {"page_type": "product"}, page, need)
    assert [o.url for o in got] == [f"{page}#unit-{i}" for i in (1, 2, 3)]
    assert len({o.url for o in got}) == 3


# ---------------------------------------------------------------- judge: like for like + one vote per grade

def _wex_units():
    mk = lambda p, g, sc, shut, u: Offer(  # noqa: E731
        url=u, source="wexphotovideo.com", title="USED Sony A7 III Digital Camera Body", price=p, currency="GBP",
        price_eur=round(p * 1.2, 2), condition="used",
        raw={"grade": g, "grade_score": sc, "shutter_count": shut, "unit_of": WEX_URL, "from_list_page": WEX_URL})
    return [mk(818, "Excellent (9)", 0.9, 8000, WEX_URL), mk(678, "Good (8)", 0.8, 14641, WEX_URL + "#g"),
            mk(799, "Excellent (9)", 0.9, 5000, WEX_URL + "#e2"), mk(789, "Very good (9-)", 0.87, 38000, WEX_URL + "#v")]


def test_receipt_notes_the_grade_like_for_like():
    offers = _wex_units() + [Offer(url="https://www.tori.fi/x", source="tori.fi", title="Sony A7 III body",
                                   price=825, currency="EUR", price_eur=825, condition="used")]
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    jd.judge(need, [Thing(id="t", name="Sony A7 III", offers=offers)], history=False)
    good = offers[1]
    line = next(label for label, v in good.true_cost.receipt if label.startswith("condition:"))
    assert line.startswith("condition: Good (8), shutter count 14,641 (seller's grade)")
    assert "lower than the usual Excellent (9) here" in line
    exc = offers[0]
    exc_line = next(label for label, v in exc.true_cost.receipt if label.startswith("condition:"))
    assert "same grade elsewhere: €959" in exc_line          # the other Excellent (9) unit, £799
    # an ungraded offer gets no grade line
    assert not any(label.startswith("condition:") for label, _ in offers[-1].true_cost.receipt)


def test_units_of_one_page_vote_once_per_grade():
    kept = jd._one_vote_per_listing(_wex_units())
    assert sorted(o.raw["grade"] for o in kept) == ["Excellent (9)", "Good (8)", "Very good (9-)"]


# ---------------------------------------------------------------- imports: clearance fee + duty note

def test_uk_and_us_imports_get_an_estimated_clearance_fee():
    uk = Offer(url=WEX_URL, source="wexphotovideo.com", title="USED Sony A7 III Digital Camera Body", price=818,
               currency="GBP", price_eur=981.6, condition="used")
    lines = jd.import_lines(uk)
    labels = [label for label, _ in lines]
    assert labels[2].startswith("courier customs clearance fee (est.") and lines[2][1] == 15.0
    assert labels[3] == "customs duty: 0% for cameras (ITA agreement)" and lines[3][1] == 0.0
    us_toy = Offer(url="https://shop.example.com/x", source="shop.example.com", title="LEGO Titanic 10294",
                   price=600, currency="USD", price_eur=552, condition="new")
    assert jd.import_lines(us_toy)[-1][0].startswith("customs duty: possible over €150")
    ebay = Offer(url="https://www.ebay.com/itm/1", source="ebay.com", title="Sony A7 III", price=100,
                 currency="USD", price_eur=92, condition="used")
    assert jd.import_lines(ebay)[-1] == ("postal customs handling fee (est., usually under €10)", 5.0)
    eu = Offer(url="https://x.de/a", source="x.de", title="Sony A7 III", price=900, currency="EUR", price_eur=900,
               condition="used")
    assert jd.import_lines(eu) == [] and jd.import_fee(eu) == 0


def test_clearance_fee_is_in_the_all_in_receipt():
    o = Offer(url=WEX_URL, source="wexphotovideo.com", title="USED Sony A7 III Digital Camera Body", price=818,
              currency="GBP", price_eur=981.6, condition="used")
    tc = jd.estimate_true_cost(o, [o])
    assert any(label.startswith("courier customs clearance") and v == 15.0 for label, v in tc.receipt)
    assert tc.extras_eur == pytest.approx(jd.import_fee(o))
    o.true_cost = tc
    ev = jd.evidence_for(o, [o])
    assert any(e["via"] == "rule" and "customs" in e["quote"] for e in ev)


# ---------------------------------------------------------------- reviews: badges on the shop's own page

def test_wex_badge_and_trustpilot_link_on_its_own_page():
    html = (FIX / "reviews" / "wex_home.html").read_text()
    got = rv.parse_badges(html, "https://wexphotovideo.com/")
    assert got["badges"] == [{"site": "trustpilot", "rating": 4.8, "count": None,
                              "quote": got["badges"][0]["quote"]}]
    assert "4.8 Trustpilot Rating" in got["badges"][0]["quote"]
    assert got["tp_urls"] == ["https://uk.trustpilot.com/review/www.wexphotovideo.com"]
    # the product page carries the same header badge
    assert rv.parse_badges((FIX / "wex_sony_a7iii_used.html").read_text())["badges"][0]["rating"] == 4.8


@pytest.mark.parametrize("text,site,rating,count", [
    ("Rated 4.8 out of 5 on Trustpilot based on 25,123 reviews", "trustpilot", 4.8, 25123),
    ("Feefo rating 4.7/5", "feefo", 4.7, None),
    ("Excellent 4.6 ★ Google reviews", "google", 4.6, None),
    ("Reevoo score 9.2", "reevoo", 4.6, None),
])
def test_badge_texts(text, site, rating, count):
    b = rv.parse_badges(f"<p>{text}</p>")["badges"][0]
    assert (b["site"], b["rating"], b["count"]) == (site, rating, count)


def test_no_badge_without_a_number_and_a_review_site():
    for t in ("Read our Trustpilot reviews", "Chrome version 2.0 by Google", "Free delivery over £4.99"):
        assert rv.parse_badges(f"<p>{t}</p>")["badges"] == []


def _collect(agen):
    async def go():
        return [x async for x in agen]
    return asyncio.run(go())


def _fetch_wex(calls):
    home = (FIX / "reviews" / "wex_home.html").read_text()

    async def fetch(url):
        calls.append(url)
        if "trustpilot.com" in url:
            return 403, "<html>Just a moment...</html>"
        if url.startswith("https://wexphotovideo.com/"):
            return 200, home
        return 404, ""
    return fetch


@pytest.fixture
def _clean_reviews(monkeypatch):
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    rv._MEM.clear(); rv._LOOKED.clear(); rv._tp_blocked_until = 0.0
    yield
    rv._MEM.clear(); rv._LOOKED.clear(); rv._tp_blocked_until = 0.0


def test_badge_only_is_a_labelled_weak_signal_not_no_reviews(_clean_reviews):
    calls: list[str] = []
    evs = _collect(rv.run([{"domain": "wexphotovideo.com", "hosts": ["wexphotovideo.com"], "why": "cheap"}],
                          paid=False, fetch=_fetch_wex(calls)))
    done = evs[-1]
    assert done["status"] == "done" and done["label"] == "unknown" and done["rating"] == 4.8
    assert done["summary"].startswith("4.8★ on Trustpilot, as shown on the shop's own page (not checked independently)")
    src = done["sources"][0]
    assert src["via"] == "shown on the shop's own page" and src["name"] == "Trustpilot (shown on the shop's own page)"
    assert "No reviews found" not in done["summary"]


def test_big_shop_tries_harder_on_its_local_trustpilot(_clean_reviews):
    calls: list[str] = []
    searches: list[tuple] = []
    extracts: list[str] = []

    async def search(q, **kw):
        searches.append((q, tuple(kw.get("include_domains") or ())))
        return []

    async def extract(url, schema, instructions=None):
        extracts.append(url)
        return {"trust_score": 4.8, "review_count": 31500, "recent_reviews": [
            {"stars": 5, "date": "2026-11-02", "text": "Fast delivery, camera as described."},
            {"stars": 2, "date": "2026-10-20", "text": "Delivery was slow."}]}

    evs = _collect(rv.run([{"domain": "wexphotovideo.com", "hosts": ["wexphotovideo.com"], "why": "pick"}],
                          fetch=_fetch_wex(calls), search=search, extract=extract, tokens=lambda: 10.0))
    assert "https://wexphotovideo.com/" in calls          # the shop's own page: badge + Trustpilot link
    assert ("www.wexphotovideo.com reviews", ("trustpilot.com", "uk.trustpilot.com")) in searches
    assert extracts == ["https://uk.trustpilot.com/review/www.wexphotovideo.com"]
    done = evs[-1]
    assert done["status"] == "done" and done["label"] == "solid" and done["count"] >= 31500
    assert any(s["name"] == "Trustpilot" and s["rating"] == 4.8 for s in done["sources"])
