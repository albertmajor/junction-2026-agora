"""Seller reviews (agora.reviews): parsing review pages, the negativity-bias correction, red flags vs
grumbles, the cached reviews phase, the judge's use of it and GET /reviews. Fixture pages only, no network."""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import date

import pytest

from agora import reviews as rv
from agora import store
from agora.models import Need, Offer, Thing

FIX = pathlib.Path(__file__).parent / "fixtures" / "reviews"
TODAY = date(2026, 11, 14)


def read(name: str) -> str:
    return (FIX / name).read_text()


@pytest.fixture(autouse=True)
def _clean():
    rv._MEM.clear()
    rv._LOOKED.clear()
    rv._tp_blocked_until = 0.0
    yield
    rv._MEM.clear()
    rv._LOOKED.clear()
    rv._tp_blocked_until = 0.0


def collect(agen) -> list[dict]:
    async def go():
        return [x async for x in agen]
    return asyncio.run(go())


# ---------------------------------------------------------------- parsing

def test_trustpilot_graph_rating_and_reviews():
    got = rv.parse_rating_page(read("trustpilot_bigshop.html"), "https://www.trustpilot.com/review/bigshop-test.com")
    assert got["rating"] == 4.1 and got["count"] == 12345
    assert len(got["reviews"]) == 10
    assert got["reviews"][1]["rating"] == 1 and got["reviews"][1]["date"] == "2026-10-28"


def test_product_rating_is_not_the_sellers_and_scale_10_is_converted():
    got = rv.parse_rating_page(read("own_site_cleaner.html"), "https://schoon-tilburg-test.nl/")
    assert got["count"] == 57 and got["rating"] == 4.6        # 9.2 / 10, never the product's 4.9 from 999


def test_no_rating_on_a_bot_wall():
    assert rv.parse_rating_page(read("trustpilot_wall.html"), "https://www.trustpilot.com/review/x-test.com") is None


@pytest.mark.parametrize("text,want", [
    ("TrustScore 4.1 out of 5 | 12,345 reviews", (4.1, 12345)),
    ("Schoon Tilburg scoort een 9,1 / 10 op basis van 1.234 beoordelingen", (4.55, 1234)),
    ("4,6 tähteä · 230 arvostelua", (4.6, 230)),
    ("Rated 3.8 by 2.1k customers · 2.1k reviews", (3.8, 2100)),
    ("Free delivery over 50 €, 30 days to return", None),
])
def test_snippet_ratings(text, want):
    assert rv.parse_snippet_rating(text) == want


def test_red_flags_vs_grumbles_and_negation():
    red, grumble = rv.classify("Order never arrived and they refused to refund. Total scam.")
    assert set(red) == {"orders never delivered", "refunds refused", "scams"}
    red, grumble = rv.classify("Delivery was slow and customer service kept me on hold.")
    assert red == [] and set(grumble) == {"slow delivery", "customer service waits"}
    assert rv.classify("Arrived in 3 days, not a scam at all.")[0] == []
    assert rv.classify("Is bigshop-test.com a scam? No, it is legit.")[0] == []
    assert "orders never delivered" in rv.classify("Tilaus ei ole koskaan saapunut")[0]
    assert "orders never delivered" in rv.classify("Pakket nooit ontvangen, oplichters!")[0]


# ---------------------------------------------------------------- the bias correction

def test_big_shop_with_grumbles_is_solid():
    got = rv.parse_rating_page(read("trustpilot_bigshop.html"), "u")
    src = [{"key": "trustpilot", "name": "Trustpilot", "url": "u", **got}]
    texts = [{"text": r["text"], "rating": r["rating"], "date": r["date"], "weight": 1} for r in got["reviews"]]
    sc = rv.score(src, texts, today=TODAY)
    assert sc["label"] == "solid" and not sc["watch"]
    assert sc["grumbles"][0] == "slow delivery"
    s = rv.summarize("bigshop-test.com", sc)
    assert s.startswith("4.1★ from 12k Trustpilot reviews") and "slow delivery" in s and "normal for a big shop" in s


def test_three_point_eight_with_5000_reviews_is_fine():
    sc = rv.score([{"key": "trustpilot", "rating": 3.8, "count": 5000}], [], today=TODAY)
    assert sc["label"] == "solid" and 0.5 <= sc["adjusted_score"] < 0.6


def test_low_raw_stars_on_a_complaint_site_are_judged_against_its_baseline():
    sc = rv.score([{"key": "smartcustomer", "rating": 2.6, "count": 2089}], [], today=TODAY)
    assert sc["label"] == "solid"
    assert "about normal there" in rv.summarize("apple.com", sc)


def test_few_reviews_pull_toward_neutral():
    few = rv.score([{"key": "trustpilot", "rating": 5.0, "count": 4}], [], today=TODAY)
    many = rv.score([{"key": "trustpilot", "rating": 5.0, "count": 4000}], [], today=TODAY)
    assert few["adjusted_score"] < 0.6 < many["adjusted_score"]
    assert few["label"] == "unknown" and "too few reviews" in rv.summarize("tiny-test.com", few)


def test_repeated_recent_red_flags_mean_watch_out():
    got = rv.parse_rating_page(read("smartcustomer_scamshop.html"), "u")
    src = [{"key": "smartcustomer", "url": "u", **got}]
    texts = [{"text": r["text"], "rating": r["rating"], "date": r["date"], "weight": 1} for r in got["reviews"]]
    sc = rv.score(src, texts, today=TODAY)
    assert sc["label"] == "watch out"
    assert any(f.startswith("orders never delivered (3 recent reviews)") for f in sc["red_flags"])
    assert "pay with buyer protection" in rv.summarize("cheapods-test.com", sc)


def test_a_big_shop_survives_a_few_red_flags():
    texts = [{"text": "Never received my order, still waiting for my refund", "rating": 1, "date": "2026-10-01"},
             {"text": "Order never arrived", "rating": 1, "date": "2026-10-05"}] + \
            [{"text": "Great, fast delivery", "rating": 5, "date": "2026-10-0%d" % i} for i in range(1, 9)]
    sc = rv.score([{"key": "trustpilot", "rating": 3.9, "count": 40000}], texts, today=TODAY)
    assert sc["label"] == "solid"


def test_low_rating_without_red_flags_is_mixed_never_watch_out():
    texts = [{"text": "Slow delivery again", "rating": 1, "date": "2026-10-01"}] * 6
    sc = rv.score([{"key": "trustpilot", "rating": 1.9, "count": 800}], texts, today=TODAY)
    assert sc["label"] == "mixed"


def test_marketplace_rates_the_platform_not_the_seller():
    sc = rv.score([{"key": "smartcustomer", "rating": 1.6, "count": 3501}], [], platform=True, today=TODAY)
    s = rv.summarize("ebay.com", sc, platform=True)
    assert s.startswith("The ebay.com platform: 1.6★") and "individual seller is not rated" in s
    assert sc["label"] in ("solid", "mixed")
    assert "rated 4.9 there" in rv.summarize("tori.fi", sc, platform=True, seller_rating=4.9)


# ---------------------------------------------------------------- search highlights

def test_sources_from_search_highlights():
    res = json.loads(read("search_schoon_tilburg.json"))["results"]
    src, texts = rv.sources_from_search("schoon-tilburg-test.nl", res)
    by = {s["key"]: s for s in src}
    assert by["trustpilot"]["rating"] == 4.6 and by["trustpilot"]["count"] == 214
    assert by["kiyoh"]["rating"] == 4.55 and by["kiyoh"]["count"] == 88
    assert by["reddit"]["rating"] is None
    assert "web" not in by                      # an unrelated page's rating is never taken
    assert rv.review_query("schoon-tilburg.nl") == "schoon-tilburg.nl ervaringen"
    assert rv.review_query("verkkokauppa.com") == "verkkokauppa.com reviews"
    assert rv.review_query("gigantti.fi") == "gigantti.fi kokemuksia"


# ---------------------------------------------------------------- the phase

def fake_fetch(pages: dict[str, str], calls: list[str]):
    async def fetch(url: str):
        calls.append(url)
        for key, name in pages.items():
            if key in url:
                html = read(name)
                return (403 if "wall" in name else 200), html
        return 404, ""
    return fetch


def test_run_free_first_then_paid_then_cache(monkeypatch):
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    calls: list[str] = []
    searches: list[str] = []
    fetch = fake_fetch({"trustpilot.com/review/bigshop-test.com": "trustpilot_bigshop.html",
                        "trustpilot.com/review/": "trustpilot_wall.html",
                        "sitejabber.com/reviews/cheapods-test.com": "smartcustomer_scamshop.html",
                        "schoon-tilburg-test.nl/": "own_site_cleaner.html"}, calls)

    async def search(q, **kw):
        searches.append((q, kw.get("include_domains")))
        return json.loads(read("search_schoon_tilburg.json"))["results"] if "schoon" in q else []

    async def extract(*a, **kw):
        return None

    targets = [{"domain": "bigshop-test.com", "hosts": ["bigshop-test.com"], "why": "pick"},
               {"domain": "cheapods-test.com", "hosts": ["shop.cheapods-test.com"], "why": "cheap"},
               {"domain": "schoon-tilburg-test.nl", "hosts": ["schoon-tilburg-test.nl"], "why": "provider",
                "service": True}]
    stats: dict = {}
    evs = collect(rv.run(targets, fetch=fetch, search=search, extract=extract, tokens=lambda: 10.0,
                         stats=stats, today=TODAY))
    assert [e["status"] for e in evs[:3]] == ["checking"] * 3
    done = {e["domain"]: e for e in evs if e["status"] != "checking"}
    assert done["bigshop-test.com"]["label"] == "solid"
    assert done["cheapods-test.com"]["label"] == "watch out"
    assert done["cheapods-test.com"]["hosts"] == ["shop.cheapods-test.com"]
    cl = done["schoon-tilburg-test.nl"]
    assert cl["label"] == "solid" and cl["count"] >= 214
    assert {s["name"] for s in cl["sources"]} >= {"Trustpilot", "Kiyoh", "the shop's own site"}
    # one batched Trustpilot search, only for the site without a solid free rating
    assert searches == [("schoon-tilburg-test.nl reviews", ["trustpilot.com"])]
    assert stats["paid"] == 1 and stats["free_pages"] >= 6
    assert all("summary" in e and e["bias_note"] for e in done.values())

    # second run: straight from SQLite, nothing fetched or searched
    calls.clear(); searches.clear()
    again = collect(rv.run(targets, fetch=fetch, search=search, extract=extract, tokens=lambda: 10.0))
    assert [e["status"] for e in again] == ["done"] * 3 and all(e["cached"] for e in again)
    assert calls == [] and searches == []


def test_run_respects_the_bucket(monkeypatch):
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    searched = []

    async def search(q, **kw):
        searched.append(q)
        return []

    evs = collect(rv.run([{"domain": "nobody-test.com", "hosts": ["nobody-test.com"], "why": "pick"}],
                         fetch=fake_fetch({}, []), search=search, extract=None, tokens=lambda: 0.3, budget_s=7.5))
    assert searched == [] and evs[-1]["status"] == "none" and evs[-1]["label"] == "unknown"


def test_offline_uses_the_cache_only():
    rv.save({"domain": "known-test.com", "status": "done", "label": "solid", "rating": 4.2, "count": 900})
    evs = collect(rv.run([{"domain": "known-test.com"}, {"domain": "new-test.com"}]))
    assert evs[0]["label"] == "solid" and evs[0]["cached"]
    assert evs[1]["status"] == "none" and evs[1].get("offline")


def test_targets_pick_first_then_cheapest_then_marketplaces():
    def o(url, price, cond="new"):
        return Offer(url=url, source=rv.trust.host_of(url), title="AirPods Pro 2", price=price, currency="EUR",
                     price_eur=price, condition=cond)
    offers = [o(f"https://shop{i}-test.com/p", 200 + i) for i in range(9)] + \
             [o("https://www.tori.fi/item/1", 120, "used"), o("https://picked-test.com/p", 230)]
    ts = rv.targets_from_offers(offers, "https://picked-test.com/p")
    doms = [t["domain"] for t in ts]
    assert doms[0] == "picked-test.com" and doms[1] == "tori.fi"
    assert ts[1]["platform"] is True
    assert len(doms) <= rv.MAX_DOMAINS and "shop0-test.com" in doms
    assert rv.targets_from_hosts(["www.shop-test.com", "bad host", "x.shop-test.com"])[0]["hosts"] == \
        ["shop-test.com", "x.shop-test.com"]


# ---------------------------------------------------------------- the judge

def test_watch_out_seller_is_never_the_pick():
    from agora.judge import judge
    need = Need(raw="airpods pro 2", thing="airpods pro 2")

    def o(src, price):
        return Offer(url=f"https://{src}/airpods-pro-2", source=src, title="Apple AirPods Pro 2", price=price,
                     currency="EUR", price_eur=price, condition="new", in_stock=True)
    things = [Thing(id="t", name="airpods pro 2", offers=[o("cheapods-test.com", 199), o("bigshop-test.com", 229),
                                                          o("third-test.com", 239)])]
    v = judge(need, things)
    assert v.best_offer_url == "https://cheapods-test.com/airpods-pro-2"

    rv.save({"domain": "cheapods-test.com", "status": "done", "label": "watch out",
             "red_flags": ["orders never delivered (3 recent reviews)"], "rating": 2.1, "count": 38})
    rv._LOOKED.clear()
    things = [Thing(id="t", name="airpods pro 2", offers=[o("cheapods-test.com", 199), o("bigshop-test.com", 229),
                                                          o("third-test.com", 239)])]
    v = judge(need, things)
    assert v.best_offer_url == "https://bigshop-test.com/airpods-pro-2"
    bad = things[0].offers[0]
    assert bad.trust < 0.5 and any(f.startswith("reviews: red flags") for f in bad.flags)


# ---------------------------------------------------------------- the API

def test_reviews_endpoint_streams_cached_and_offline(monkeypatch):
    from fastapi.testclient import TestClient
    from agora import api
    rv.save({"domain": "bigshop-test.com", "status": "done", "label": "solid", "rating": 4.1, "count": 12345,
             "summary": "4.1★ from 12k Trustpilot reviews."})
    c = TestClient(api.app)
    r = c.get("/reviews", params={"domains": "www.bigshop-test.com,shop.unknown-test.com"})
    assert r.status_code == 200
    evs = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in evs] == ["review", "review", "done"]
    assert evs[0]["data"]["label"] == "solid" and evs[0]["data"]["hosts"] == ["bigshop-test.com"]
    assert evs[1]["data"]["status"] == "none"
    assert evs[2]["data"]["cached"] == 1
    assert c.get("/reviews", params={"hunt_id": "h_nope"}).status_code == 404


def test_store_roundtrip():
    store.save_review("a-test.com", {"label": "mixed", "status": "done"}, checked_at=1.0)
    assert store.get_reviews(["a-test.com", "b-test.com"]) == {"a-test.com": {"label": "mixed", "status": "done",
                                                                          "checked_at": 1.0}}
    assert rv.cached(["a-test.com"]) == {"a-test.com": {"label": "mixed", "status": "done", "checked_at": 1.0}}


# ---------------------------------------------------------------- batched Trustpilot search (real shapes, Nov 2026)

def test_batched_trustpilot_search_covers_several_shops():
    res = json.loads(read("search_tp_batch.json"))["results"]
    doms = ["verkkokauppa.com", "gigantti.fi", "backmarket.fi", "tori.fi"]
    per = rv.sources_by_domain(doms, res)
    bm = per["backmarket.fi"][0][0]
    assert bm["key"] == "trustpilot" and bm["rating"] is None and bm["count"] == 59 and bm["sentiment"] == 1
    vk = per["verkkokauppa.com"][0][0]
    assert vk["count"] == 83 and vk["sentiment"] == -1
    assert vk["url"] == "https://www.trustpilot.com/review/www.verkkokauppa.com"
    assert per["tori.fi"] == ([], [])
    assert len(per["verkkokauppa.com"][1]) == 2         # the same summary on two pages counts once
    # stars are never made up from a summary: the mood only nudges the score
    sc = rv.score([bm], [], today=TODAY)
    assert sc["rating"] is None and sc["adjusted_score"] > 0.5 and sc["label"] == "solid"
    assert rv.summarize("backmarket.fi", sc).startswith("Trustpilot's summary of 59 reviews: mostly happy buyers")
    sc = rv.score([vk], [], today=TODAY)
    assert sc["label"] == "mixed"


def test_page_numbers_and_blog_scores_are_not_ratings():
    assert rv.parse_snippet_rating("Arvostelut Vinted FI | 5/5 · Arvioitaessa 75 arviota") is None
    res = [{"url": "https://kokemuksia.blog/vinted", "title": "Vinted kokemuksia",
            "highlights": {"highlights": ["Kokonaisarvosana 3,8 / 5, Trustpilot (vinted.fi) 113 arvostelua"]}}]
    src, texts = rv.sources_from_search("vinted.fi", res)
    assert src == [] and len(texts) == 1


def test_one_json_read_for_the_pick_without_stars(monkeypatch):
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    calls = []

    async def search(q, **kw):
        calls.append(("search", q))
        return json.loads(read("search_tp_batch.json"))["results"]

    async def extract(url, schema, instructions=None):
        calls.append(("extract", url))
        return {"trust_score": 2.4, "review_count": 1530, "recent_reviews": [
            {"stars": 1, "date": "2026-11-01", "text": "Delivery was a week late."},
            {"stars": 5, "date": "2026-10-30", "text": "Fast and cheap."}]}

    targets = [{"domain": "verkkokauppa.com", "hosts": ["verkkokauppa.com"], "why": "pick"},
               {"domain": "backmarket.fi", "hosts": ["backmarket.fi"], "why": "cheap"}]
    evs = collect(rv.run(targets, fetch=fake_fetch({}, []), search=search, extract=extract,
                         tokens=lambda: 10.0, today=TODAY))
    done = {e["domain"]: e for e in evs if e["status"] != "checking"}
    assert calls[0] == ("search", "verkkokauppa.com backmarket.fi reviews")
    assert calls[1] == ("extract", "https://www.trustpilot.com/review/www.verkkokauppa.com")
    assert len(calls) == 2
    vk = done["verkkokauppa.com"]
    assert vk["rating"] == 2.4 and vk["count"] == 1530 and vk["label"] in ("solid", "mixed")
    assert done["backmarket.fi"]["label"] == "solid"


def test_a_marketplace_with_typical_platform_grumbles_is_not_watch_out():
    # live, Nov 2026: vinted.fi 1.4★ from 183 Trustpilot reviews, a couple of recent scam / account stories
    texts = [{"text": "Scam, my account was closed and they kept my money", "rating": 1, "date": "2026-11-02"},
             {"text": "Scammers everywhere, Vinted does nothing", "rating": 1, "date": "2026-10-20"},
             {"text": "Got a fake bag, counterfeit", "rating": 1, "date": "2026-10-11"}] + \
            [{"text": "Customer service is a bot", "rating": 1, "date": "2026-10-0%d" % i} for i in range(1, 8)]
    sc = rv.score([{"key": "trustpilot", "rating": 1.4, "count": 183}], texts, platform=True, today=TODAY)
    assert sc["label"] == "mixed" and not sc["watch"]
    assert "buyer protection" in rv.summarize("vinted.fi", sc, platform=True)


def test_old_scam_words_are_not_a_red_flag_pattern():
    # live, Nov 2026: klarna.com on SmartCustomer, angry "scam" reviews mostly older than 6 months
    texts = [{"text": "Klarna is a scam, they charged me twice", "rating": 1, "date": "2025-0%d-10" % i} for i in range(1, 9)] + \
            [{"text": "Order never arrived and refund refused", "rating": 1, "date": "2025-03-01"}]
    sc = rv.score([{"key": "smartcustomer", "rating": 2.1, "count": 49}], texts, today=TODAY)
    assert sc["label"] != "watch out"


def test_own_site_ratings_are_self_reported_not_too_few():
    sc = rv.score([{"key": "own site", "rating": 4.8, "count": 15003}],
                  [{"text": "beware of scams in this sector", "rating": None, "date": None, "weight": 0.5}] * 3,
                  service=True, today=TODAY)
    s = rv.summarize("zoofy.nl", sc)
    assert sc["label"] == "unknown" and sc["red_flags"] == []
    assert s == "4.8★ from 15k reviews shown on its own site (self-reported, not checked); no independent reviews found."


def test_same_brand_trustpilot_page_and_french_summary():
    # live, Nov 2026: yoojo.nl's reviews live on trustpilot.com/review/yoojo.fr
    res = [{"url": "https://fr-be.trustpilot.com/review/yoojo.fr?page=8", "title": "Yoojo Avis",
            "highlights": {"highlights": ["[Yoojo Avis > Résumé des avis] En évaluant 6 888 avis, les critiques ont "
                                          "eu une expérience exceptionnelle avec cette entreprise."]}},
           {"url": "https://www.trustpilot.com/review/power.com", "title": "Power", "highlights": {"highlights": ["x"]}}]
    per = rv.sources_by_domain(["yoojo.nl", "power.fi"], res)
    tp = per["yoojo.nl"][0][0]
    assert tp["count"] == 6888 and tp["sentiment"] == 1 and tp["name"] == "Trustpilot (yoojo.fr, same brand)"
    assert per["power.fi"] == ([], [])           # a generic name is never "the same brand"


def test_subscription_traps_are_red_flags():
    red, _ = rv.classify("Be aware: by creating a free account you are tied to a hidden annual subscription")
    assert red == ["subscription traps or surprise invoices"]
