"""Category context: a hunt from the category tree (or a confidently classified one) knows what it is looking
for. The owner's case: the Gunsmith node ran product lanes and picked a Vinted manga 'Gunsmith Cats'."""
from __future__ import annotations

import asyncio
import functools
import json
import pathlib

from fastapi.testclient import TestClient

from agora import api, discover, resolve
from agora import hunt as hunt_mod
from agora.models import Event, Offer
from agora.need import categorize, parse_need_rules, priced_per_period

GUNSMITH = "yelp:gunsmith"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def gunsmith_need(text: str = "Gunsmith", cat: str | None = GUNSMITH):
    n = parse_need_rules(text)
    ev = categorize(n, cat)
    return n, ev


def offer(url: str, source: str, title: str, price: float = 50.0, **kw) -> Offer:
    return Offer(url=url, source=source, title=title, price=price, currency="EUR", price_eur=price,
                 condition=kw.pop("condition", "service"), **kw)


# ---------------------------------------------------------------- need + category

def test_tree_node_makes_a_service_need_with_service_lanes_only():
    n, ev = gunsmith_need()
    assert n.kind == "service" and n.conditions == ["service"]
    assert ev["id"] == GUNSMITH and ev["source"] == "tree" and ev["kind"] == "service" and ev["confidence"] == 1.0
    assert ev["path"][-1] == "Gunsmith"
    assert discover.lanes_for(n) == ["service"]
    assert not priced_per_period(n)            # a local trade: rate x job, not a monthly plan


def test_tree_node_wins_over_the_words():
    """A node with no rule words (bookbinding) is still a service when the hunt came from the tree."""
    n = parse_need_rules("Bookbinding")
    assert n.kind == "product"
    ev = categorize(n, "yelp:bookbinding")
    assert n.kind == "service" and ev["source"] == "tree"
    assert discover.lanes_for(n) == ["service"]


def test_product_node_keeps_product_lanes():
    n = parse_need_rules("Gun Safes")
    ev = categorize(n, "sp:hg-2-8-3")
    assert n.kind == "product" and ev["kind"] == "product"
    assert "service" not in discover.lanes_for(n) and "used" in discover.lanes_for(n)


def test_unknown_category_is_ignored():
    n = parse_need_rules("Gunsmith")
    assert categorize(n, "no-such-node-xyz") is None


def test_service_lane_searches_locally_without_marketplace_product_lanes(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    n, _ = gunsmith_need()
    plan = discover.lean_plan(n, "service", tokens=10)
    queries = [p[0] for p in plan]
    assert any("aseseppä" in q for q in queries)              # the job in Finnish, searched in Finland
    assert any(p[1] == "fi" for p in plan)
    market = [p for p in plan if len(p) > 2]
    assert market and "tori.fi" in market[0][2] and "care.com" not in market[0][2]


def test_free_text_local_words_classify_as_gunsmith():
    for text in ("aseseppä helsinki", "Büchsenmacher", "wapensmid amsterdam", "vapensmed", "gunsmith"):
        n = parse_need_rules(text)
        ev = categorize(n, None)
        assert n.kind == "service", text
        assert ev and ev["id"] == GUNSMITH and ev["source"] == "classified" and ev["confidence"] >= 0.6, text
    n = parse_need_rules("aseseppä helsinki")
    categorize(n, None)
    assert n.where == "Helsinki"
    q = [p[0] for p in discover.lean_plan(n, "service", tokens=10)]
    assert any(x.startswith("aseseppä Helsinki") for x in q)


def test_classification_never_turns_things_into_services():
    for text in ("sauna", "pizza", "used bike", "laptop for web developer", "sony a7 iii"):
        n = parse_need_rules(text)
        before = n.kind
        categorize(n, None)
        assert n.kind == before, text
    n = parse_need_rules("sony a7 iii")
    assert categorize(n, None) is None          # 'Sulphates' is no category: never shown


def test_strong_service_node_flips_a_typed_need():
    n = parse_need_rules("locksmith")
    ev = categorize(n, None)
    assert n.kind == "service" and ev["source"] == "classified"


# ---------------------------------------------------------------- per-listing kind check

def test_manga_gunsmith_cats_is_rejected_for_the_gunsmith_service():
    """The owner's top pick: a Vinted manga whose title holds the trade's word."""
    n, _ = gunsmith_need()
    o = offer("https://www.vinted.fi/items/9518894952-manga-gunsmith-cats-po-niemiecku-polskie-tlumaczenie",
              "vinted.fi", "Manga Gunsmith Cats po niemiecku + polskie tłumaczenie", 5.0)
    r, why = resolve.explain(n, o)
    assert r < 0.5 and why.startswith("a product, not a gunsmith service")
    assert resolve.resolve(n, [o]) == [] or all(o not in t.offers for t in resolve.resolve(n, [o]))
    plain = offer("https://www.vinted.fi/items/1-gunsmith-cats", "vinted.fi", "Gunsmith Cats", 5.0)
    assert resolve.explain(n, plain)[1].startswith("a product, not a gunsmith service")


def test_guns_and_parts_are_products_not_the_service():
    n, _ = gunsmith_need()
    for title in ("Sako 85 kivääri .308", "Zeiss kiikaritähtäin 3-12x56", "Browning shotgun for sale"):
        o = offer("https://www.tori.fi/uusimaa/x_1", "tori.fi", title, 900.0)
        assert resolve.explain(n, o)[1].startswith("a product, not a gunsmith service"), title


def test_gunsmith_providers_are_kept():
    n, _ = gunsmith_need("aseseppä helsinki", None)
    keep = [offer("https://asepaja.example.fi/hinnasto", "asepaja.example.fi", "Aseseppä - aseen huolto", 60.0, unit="job"),
            offer("https://gun.example.fi/", "gun.example.fi", "Gunsmith services Helsinki", 70.0, unit="hour"),
            offer("https://x.example.fi/kiikari", "x.example.fi", "Kiikarin asennus ja kohdistus", 45.0, unit="job")]
    for o in keep:
        assert resolve.kind_mismatch(n, o) is None, o.title
    things = resolve.resolve(n, keep)
    assert sum(len(t.offers) for t in things) >= 2


def test_product_need_rejects_service_ads():
    n = parse_need_rules("bike")
    o = Offer(url="https://shop.example/huolto", source="shop.example", title="Bike repair price per hour",
              price=50, currency="EUR", price_eur=50, unit="hour")
    r, why = resolve.explain(n, o)
    assert why == "a service, not a bike"
    ok = Offer(url="https://shop.example/bike", source="shop.example", title="Trek FX 2 hybrid bike", price=600,
               currency="EUR", price_eur=600, condition="new")
    assert resolve.kind_mismatch(n, ok) is None


# ---------------------------------------------------------------- hunt + api + viewer

def _fake_kwargs(seen: list):
    async def disc(need):
        seen.append(need)
        yield Event("lane", {"lane": "service", "queries": []})
    return {"parse_need": parse_need_rules, "discover": disc, "read": None, "persist": False,
            "lookalikes": False, "siblings": False, "longtail": False, "budget_s": None, "check_pick": False}


def test_hunt_with_category_streams_a_category_event():
    seen: list = []

    async def go():
        return [e async for e in hunt_mod.hunt("Gunsmith", category=GUNSMITH, **_fake_kwargs(seen))]
    events = asyncio.run(go())
    types = [e.type for e in events]
    assert types[0] == "need" and types[1] == "category"
    cat = events[1].data
    assert cat["id"] == GUNSMITH and cat["source"] == "tree" and cat["kind"] == "service"
    assert events[0].data["need"]["kind"] == "service"
    assert seen and seen[0].kind == "service" and seen[0].category["id"] == GUNSMITH


def test_api_passes_cat_to_hunt(monkeypatch):
    got: dict = {}
    real = hunt_mod.hunt

    async def fake(text, *, category=None, **kw):
        got["category"] = category
        async for e in real(text, category=category, **_fake_kwargs([])):
            yield e
    monkeypatch.setattr(hunt_mod, "hunt", fake)
    with TestClient(api.app).stream("GET", "/hunt", params={"q": "Gunsmith", "cat": GUNSMITH}) as r:
        body = "".join(r.iter_text())
    events = [json.loads(x[6:]) for x in body.splitlines() if x.startswith("data: ")]
    assert got["category"] == GUNSMITH
    assert any(e["type"] == "category" and e["data"]["source"] == "tree" for e in events)


def test_viewer_sends_cat_to_hunt():
    js = (ROOT / "agora" / "web" / "js" / "stream.js").read_text()
    assert "get('cat')" in js and "p.set('cat'" in js
