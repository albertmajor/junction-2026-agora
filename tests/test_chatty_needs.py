"""Long, chatty requests (owner, 15 Nov): both of these ended with "0 offers from 32 pages" because the whole
sentence was the item. Now the core item is searched and checked; size / colour / area / features are soft wishes
that rank the listings stating them first ('matches: purple, 44') and never drop one. Offline: mocked listings."""
from __future__ import annotations

import asyncio

import pytest

from agora import discover as D
from agora import intent, prefs
from agora import judge as J
from agora import need as N
from agora import resolve as R
from agora.hunt import HuntResult, hunt
from agora.models import Event, Need, Offer

HAVAIANAS = "i want to buy some hawaianas, size 44 1/3 purple color"
ROOMBA = ("i want to find a roomba that covers 55 square meters, has vacuum plus mop plus automated clean up plus "
          "automated refill")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")


def listing(title: str, price: float, n: int, site: str = "tori.fi") -> Offer:
    url = f"https://www.{site}/recommerce/forsale/item/{3000000 + n}"
    return Offer(url=url, source=site, title=title, price=price, currency="EUR", price_eur=price,
                 condition="used", location="Helsinki",
                 raw={"from_list_page": f"https://www.{site}/recommerce/forsale/search?q=x", "step": "jsonld_itemlist"})


SANDALS = [
    ("Havaianas flip flops 45/46 musta", 8.0),
    ("Havaianas Top varvassandaalit 43/44", 12.0),
    ("Havaianas Slim lila 41/42", 9.0),
    ("Havaianas Brasil violetti 43/44", 15.0),
    ("Crocs sandaalit 44", 10.0),
]
ROBOTS = [
    ("iRobot Roomba 692 robotti-imuri", 90.0),
    ("iRobot Roomba i7+ itsetyhjentävä", 250.0),
    ("iRobot Roomba Combo j7+ imuri ja moppi", 400.0),
    ("iRobot Roomba Combo j9+ robotti-imuri ja moppi, Clean Base Auto-Fill", 650.0),
    ("Roomba suodatin 3kpl", 15.0),
    ("Roborock S8 MaxV Ultra", 900.0),
]


# ------------------------------------------------------------------ 1. need: core item + soft wishes

def test_havaianas_core_item_and_wishes():
    n = N.parse_need(HAVAIANAS)
    assert n.thing == "havaianas"                       # typo fixed, wrapper and wishes cut
    assert n.kind == "product" and not n.must_have
    by = {p["kind"]: p for p in n.prefs}
    assert by["size"]["value"] == "44 1/3" and abs(by["size"]["num"] - 44.333) < 0.01
    assert by["colour"]["value"] == "purple"


def test_roomba_core_item_and_features():
    n = N.parse_need(ROOMBA)
    assert n.thing == "roomba"
    assert n.kind == "product"
    feats = {p["value"] for p in n.prefs if p["kind"] == "feature"}
    assert feats == {"mop", "self-empty", "auto-refill"}     # 'vacuum' is what every Roomba does: no wish
    assert {"kind": "area", "value": 55, "label": "55 m²"} in n.prefs


@pytest.mark.parametrize("text, thing", [
    ("i'm looking for a laptop which has 16gb ram", "laptop"),
    ("could you find me birkenstock arizona, size 42, black color", "birkenstock arizona"),
    ("winter jacket women size M", "winter jacket women"),
    ("do you have iphone 13", "iphone 13"),
])
def test_wrappers_and_wish_clauses(text, thing):
    assert N.parse_need(text).thing == thing


@pytest.mark.parametrize("text", ["sony a7 iii", "bright red car", "robot vacuum mop", "steam mop", "blue yeti",
                                  "home cleaning tilburg 24m2", "iphone 15 case"])
def test_short_needs_unchanged(text):
    n = N.parse_need(text)
    assert n.prefs == [] or text == "home cleaning tilburg 24m2"
    if text == "bright red car":
        assert n.thing == "car" and n.must_have == ["bright red"]     # the vehicle colour path stays
    if text in ("robot vacuum mop", "steam mop", "blue yeti"):
        assert n.thing == text                                         # a short need's words are the item


def test_brand_typos():
    assert N.correct_spelling("hawaianas")[0] == "havaianas"
    assert N.correct_spelling("birkenstok sandals")[0] == "birkenstock sandals"
    assert N.correct_spelling("share the brain")[0] == "share the brain"     # no brand one edit from a word


# ------------------------------------------------------------------ 2. discovery: short marketplace queries

def test_discovery_sends_short_queries(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    for text, core, local in ((HAVAIANAS, "havaianas", "havaianas 44 violetti"),
                              (ROOMBA, "roomba", "roomba combo itsetyhjentävä")):
        n = N.parse_need(text)
        lanes = D.lanes_for(n)
        plans = {lane: D.lean_plan(n, lane, 10.0) for lane in lanes}
        queries = [q[0] for p in plans.values() for q in p]
        assert all(len(q.split()) <= 8 for q in queries if " OR " not in q), queries
        assert all(core in q for q in queries)
        assert not any("want" in q or "square" in q or "color" in q for q in queries)
        assert any(q.startswith(local) for q in queries), queries       # the wishes, in Finnish, once
        direct = D.plan_direct(n, lanes, 10.0, 4)
        urls = [getattr(x, "url", x) for xs in direct.values() for x in xs]
        assert any(u.endswith(f"q={core}") for u in urls), urls        # tori.fi searched for the core item
    assert "refurbished" not in D.lanes_for(N.parse_need(HAVAIANAS))    # nobody refurbishes flip-flops


# ------------------------------------------------------------------ 3. relevance + ranking

def test_size_and_colour_matching():
    n = N.parse_need(HAVAIANAS)
    assert prefs.mark(n, listing("Havaianas Brasil violetti 43/44", 15, 1)) == ["44 1/3", "purple"]
    assert prefs.mark(n, listing("Havaianas Top 44 1/3 Purple", 15, 2)) == ["44 1/3", "purple"]
    assert prefs.mark(n, listing("Havaianas Slim lila 41/42", 9, 3)) == ["purple"]
    assert prefs.mark(n, listing("Havaianas 45/46 hinta 44 €", 44, 4)) == []          # a price is no size


def test_feature_matching_by_model():
    n = N.parse_need(ROOMBA)
    o = listing("iRobot Roomba Combo j9+", 650, 1)
    assert set(prefs.mark(n, o)) == {"mop", "self-empty", "auto-refill"} and o.raw["pref_score"] < 1  # no area
    assert prefs.mark(n, listing("iRobot Roomba i7+", 250, 2)) == ["self-empty"]
    assert prefs.mark(n, listing("iRobot Roomba 692", 90, 3)) == []


def _verdict(text: str, rows):
    n = N.parse_need(text)
    offers = [listing(t, p, i) for i, (t, p) in enumerate(rows)]
    things = R.resolve(n, offers)
    kept = [o for t in things for o in t.offers]
    return n, kept, J.judge(n, things, history=False)


def test_havaianas_listings_kept_and_purple_44_picked():
    n, kept, v = _verdict(HAVAIANAS, SANDALS)
    titles = {o.title for o in kept}
    assert "Crocs sandaalit 44" not in titles
    assert len(kept) == 4                               # no listing dropped for not stating a wish
    best = next(o for o in kept if o.url == v.best_offer_url)
    assert best.title == "Havaianas Brasil violetti 43/44"
    assert best.raw["matches"] == ["44 1/3", "purple"]
    assert any("state 44 1/3, purple" in line for line in v.lines)


def test_roomba_listings_kept_and_full_combo_picked():
    n, kept, v = _verdict(ROOMBA, ROBOTS)
    titles = {o.title for o in kept}
    assert "Roomba suodatin 3kpl" not in titles and "Roborock S8 MaxV Ultra" not in titles
    assert {"iRobot Roomba 692 robotti-imuri", "iRobot Roomba i7+ itsetyhjentävä"} <= titles
    best = next(o for o in kept if o.url == v.best_offer_url)
    assert "Combo j9+" in best.title
    assert set(best.raw["matches"]) == {"mop", "self-empty", "auto-refill"}
    assert any("state mop, self-empty, auto-refill" in line and "no listing states 55 m²" in line for line in v.lines)


def test_no_wish_stated_still_gives_offers():
    n, kept, v = _verdict(HAVAIANAS, [("Havaianas flip flops 39/40 musta", 8.0), ("Havaianas Top 37/38", 11.0)])
    assert len(kept) == 2 and v.best_offer_url
    assert any("none of the 2 found states" in line for line in v.lines)


def test_relaxes_to_the_core_item():
    n = Need(raw="i want havaianas flip flops, purple color", thing="havaianas flip flops",
             prefs=[{"kind": "colour", "value": "purple", "label": "purple"}])
    things = R.resolve(n, [listing("Havaianas Top lila 43/44", 12, 1), listing("Havaianas Slim 41/42", 9, 2)])
    kept = [o for t in things for o in t.offers]
    assert len(kept) == 2 and all(o.raw.get("relaxed_to") for o in kept)
    assert [o.raw["matches"] for o in kept] == [["purple"], []]


# ------------------------------------------------------------------ 4. intent: a clear core never asks

def test_clear_core_does_not_ask():
    for text in (HAVAIANAS, ROOMBA):
        assert intent.interpret(text, country="fi", lang="en", llm=False)["ask"] is False


def test_ambiguous_core_still_asks():
    out = intent.interpret("i am looking for a phone, black colour", country="fi", lang="en", llm=False)
    assert out["ask"] is True
    buy = next(o for o in out["options"] if o["label"].lower().startswith("a phone to buy"))
    assert buy["hunt"]["q"] == "i am looking for a phone, black colour"     # the wishes go with the hunt


# ------------------------------------------------------------------ 5. the whole hunt, mocked pages

def _hunt(text: str, rows) -> tuple[HuntResult, list[Event]]:
    seen: dict[str, Need] = {}

    async def disc(need):
        seen["need"] = need
        yield Event("lane", {"lane": "used", "queries": [f"{need.thing} käytetty"]})
        yield Event("source", {"url": f"https://www.tori.fi/recommerce/forsale/search?q={need.thing}",
                               "lane": "used"})

    async def read(url, need):
        return [listing(t, p, i) for i, (t, p) in enumerate(rows)]

    async def go():
        res = HuntResult()
        evs = [e async for e in hunt(text, parse_need=N.parse_need, discover=disc, read=read, persist=False,
                                     result=res, siblings=False, longtail=False, lookalikes=False,
                                     check_pick=False, budget_s=60, provisional_after=None)]
        return res, evs
    res, evs = asyncio.run(go())
    assert seen["need"].thing in ("havaianas", "roomba")
    return res, evs


@pytest.mark.parametrize("text, rows, pick, chips", [
    (HAVAIANAS, SANDALS, "Havaianas Brasil violetti 43/44", ["44 1/3", "purple"]),
    (ROOMBA, ROBOTS, "iRobot Roomba Combo j9+ robotti-imuri ja moppi, Clean Base Auto-Fill",
     ["mop", "self-empty", "auto-refill"]),
])
def test_hunt_ends_with_offers_and_the_matching_pick(text, rows, pick, chips):
    res, evs = _hunt(text, rows)
    kept = [o for t in res.things for o in t.offers]
    assert len(kept) >= 4
    v = next(e for e in reversed(evs) if e.type == "verdict").data["verdict"]
    best = next(o for o in kept if o.url == v["best_offer_url"])
    assert best.title == pick
    streamed = [e.data["offer"] for e in evs if e.type == "offer" and e.data["offer"]["title"] == pick]
    assert sorted(streamed[0]["matches"]) == sorted(chips)              # chips on the card as it streams
