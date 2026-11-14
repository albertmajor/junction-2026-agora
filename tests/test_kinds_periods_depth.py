"""Need kinds (service / digital / vehicle), period-priced offers, long-tail plan names, 'Compare more' depth,
and the 'bright red car' owner report. Offline: fixtures + a stream saved from a live hunt."""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from agora import discover, judge, longtail, marketplaces, need as N, reader, resolve
from agora.models import Event, Need, Offer, Thing

FIX = pathlib.Path(__file__).parent / "fixtures" / "longtail"


# --------------------------------------------------------------------------- 1. need kind

@pytest.mark.parametrize("text,kind", [
    ("unlimited graphic design subscription", "digital"),
    ("web developer for small business", "service"),
    ("bookkeeping service finland", "service"),
    ("software developer", "service"),
    ("vpn", "digital"),
    ("city bike with basket", "product"),
    ("laptop for web developer", "product"),        # an object for a professional stays an object
    ("graphic design book", "product"),
    ("monitor for graphic design", "product"),
    ("coffee subscription", "product"),             # a product delivered monthly
    ("used macbook pro", "product"),
    ("sony a7 iii", "product"),
])
def test_need_kind(text, kind):
    assert N.parse_need_rules(text).kind == kind


def test_service_and_digital_needs_skip_marketplace_lanes():
    for text in ("unlimited graphic design subscription", "web developer for small business",
                 "bookkeeping service finland"):
        n = N.parse_need_rules(text)
        assert discover.lanes_for(n) == ["service"]
        assert discover.plan_direct(n, ["service"], 10, 1) == {}
        assert N.priced_per_period(n)
    n = N.parse_need_rules("bookkeeping service finland")
    plan = discover.lean_plan(n, "service", 10)
    assert plan[0] == ("bookkeeping service pricing plans Finland", "fi")
    assert all(len(x) == 2 for x in plan)            # no tori.fi service-market query for bookkeepers
    home = N.parse_need_rules("home cleaning helsinki")
    assert not N.priced_per_period(home)               # local trades keep the job costing


def test_digital_need_is_resolved_like_a_service():
    n = N.parse_need_rules("unlimited graphic design subscription")
    assert N.service_view(n).kind == "service" and n.kind == "digital"


# --------------------------------------------------------------------------- 2. period prices

def _plan(dom, prov, price, per, cur="USD"):
    return longtail.plans_to_offers([{"name": "Standard", "price": price, "currency": cur, "period": per,
                                      "features": []}], f"https://{dom}/pricing", provider=prov,
                                    tagline="Unlimited graphic design subscription")[0]


def test_monthly_plan_headline_and_year_total_no_resale():
    n = N.parse_need_rules("unlimited graphic design subscription")
    o = _plan("designjoy.co", "Designjoy", 4995, "month")
    v = judge.judge(n, [Thing(id="t", name="x", offers=[o])], history=False)
    assert v.headline.startswith("$4,995/month at designjoy.co · ≈ $59,940 a year")
    tc = o.true_cost
    assert tc.resale_eur is None and tc.per == "month" and "resell" in tc.basis and "used listings" not in tc.basis
    assert tc.total_eur == pytest.approx(tc.per_month_eur * 12)


def test_like_with_like_monthly_vs_yearly_vs_project():
    n = N.parse_need_rules("unlimited graphic design subscription")
    offs = [_plan("designjoy.co", "Designjoy", 4995, "month"), _plan("penji.co", "Penji", 995, "month"),
            _plan("kimp.io", "Kimp", 9000, "year"), _plan("logoco.com", "LogoCo", 300, "job")]
    v = judge.judge(n, [Thing(id="t", name="x", offers=offs)], history=False)
    # the €300 project price is cheaper but not compared with monthly plans
    assert "kimp.io" in v.headline or "penji.co" in v.headline
    assert "logoco.com" not in v.headline
    assert any(l.startswith("project prices (not compared with monthly plans)") for l in v.lines)
    assert offs[2].true_cost.per_month_eur == pytest.approx(offs[2].price_eur / 12, rel=0.01)


def test_a_plan_in_a_product_hunt_is_never_resold_nor_the_pick():
    n = N.parse_need_rules("graphic design book")
    plan = _plan("penji.co", "Penji", 900, "month")
    books = [Offer(url=f"https://s{i}.fi/b", source=f"s{i}.fi", title="Graphic design book", price=p, currency="EUR",
                   price_eur=p, condition=c) for i, (p, c) in enumerate([(30, "new"), (18, "used"), (22, "used")])]
    v = judge.judge(n, [Thing(id="t", name="book", offers=[plan] + books)], history=False)
    assert plan.true_cost.resale_eur is None and "penji" not in v.headline
    assert any("also as a service / subscription" in l for l in v.lines)


def test_saved_live_stream_no_longer_picks_marktplaats_junk():
    """Live 14 Nov: 'unlimited graphic design subscription' -> '€35 all in: used at marktplaats.nl'."""
    raw = json.loads((FIX / "h1_design_subscription_offers.json").read_text())
    offers = [Offer(**{k: v for k, v in o.items()}) for o in raw]
    for o, r in zip(offers, raw):
        if r["read_via"] == "longtail_free":
            o.raw["longtail"] = True
    n = N.parse_need_rules("unlimited graphic design subscription")
    things = resolve.resolve(N.service_view(n), offers)
    v = judge.judge(n, things, history=False)
    assert "marktplaats" not in v.headline and "/month at" in v.headline and "a year" in v.headline


# --------------------------------------------------------------------------- 3. long tail

@pytest.mark.parametrize("name,ok", [
    ("Monthly Club", True), ("Essentials", True), ("Starter Plan", True), ("Pro", True),
    ("Approach", False), ("Find the", False), ("Both include the same", False), ("Unpredictable", False),
    ("In-house designer", False), ("Sales Tax", False), ("Starts", False), ("Pricing", False),
])
def test_valid_plan_name(name, ok):
    assert longtail.valid_plan_name(name) is ok


def test_comparison_prices_are_not_plans():
    html = ("<html><body><h3>In-house designer</h3><p>$8,400 /mo</p><h3>Flocksy Pro</h3><p>$995 /mo</p>"
            "<h3>Find the</h3><p>$2,000 /mo</p></body></html>")
    plans = longtail.parse_plans_text(html, "flocksy.com")
    assert [p["name"] for p in plans][:1] == ["Flocksy Pro"]
    assert all(p["price"] != 8400 for p in plans)


def test_lane_runs_early_for_service_needs(monkeypatch):
    lane = longtail._Lane(N.parse_need_rules("bookkeeping service finland"), {"id": None, "labels": {}}, 1e18,
                          None, 4)
    assert lane.early
    lane2 = longtail._Lane(Need(raw="x", thing="x"), {"id": None, "labels": {}}, 1e18, None, 3)
    assert not lane2.early


def test_lane_off_for_an_object_for_a_professional(monkeypatch):
    async def run():
        return [x async for x in longtail.lane(N.parse_need_rules("laptop for web developer"), deadline=None)]
    assert asyncio.run(run()) == []


def test_reader_prices_a_provider_page_for_free():
    html = (FIX / "designjoy_home.html").read_text()
    o = reader.period_plan_offer("https://designjoy.co/", html, N.parse_need_rules("unlimited graphic design subscription"))
    assert o is not None and o.unit == "month" and o.read_via == "jsonld" and o.condition == "service"


# --------------------------------------------------------------------------- 4. depth

def test_direct_pages_depth_reads_next_pages():
    one = marketplaces.direct_pages("dyson v15 vacuum", "used", None, "fi", 6)
    two = marketplaces.direct_pages("dyson v15 vacuum", "used", None, "fi", 6, pages=2)
    assert max(d.page for d in one) == 1 and max(d.page for d in two) >= 2   # same tokens, deeper pages
    three = marketplaces.direct_pages("dyson v15 vacuum", "used", None, "fi", 20, pages=3)
    assert {d.page for d in three if d.paid} == {1, 2, 3}


def test_hunt_depth_passes_pages_and_read_depth(monkeypatch):
    from agora import hunt as H
    seen: dict = {}

    async def fake_discover(need, *, max_sources=40, tokens=None, pages=1):
        seen.update(max_sources=max_sources, pages=pages, read_depth=reader.READ_DEPTH.get())
        yield Event("lane", {"lane": "used"}, 0)

    async def fake_read(url, need):
        return None

    async def run():
        return [e async for e in H.hunt("dyson v15", discover=fake_discover, read=fake_read, depth=3,
                                        persist=False, longtail=False, siblings=False, lookalikes=False)]
    asyncio.run(run())
    assert seen["pages"] == 3 and seen["max_sources"] == 60


def test_api_hands_depth_to_hunt():
    from agora import api
    assert api._depth_kwargs(2, {}) == {"depth": 2}


# --------------------------------------------------------------------------- 5. 'bright red car' (owner report)

RED_CAR_PAGE = [   # saved result page, 14 Nov 14:23: every one of these was shown as an offer for a car
    ("tori.fi", "Car for kids 30 cm", 6), ("tori.fi", "Hot Wheels punainen leluauto muscle car", 10),
    ("tori.fi", "Kids Ride-On Car", 10), ("tori.fi", "Toy Car", 11), ("vinted.fi", "Szerokie Cargo Spodnie Vintage", 6),
    ("tori.fi", "VINTAGE TONKA CAR COUPE JAPAN DIECAST METAL STEEL", 15),
    ("vinted.fi", "Vintage Carlotta Red Sweatershirt vintagelove retro og", 11),
    ("vinted.fi", "Vintage czarna koszulka meska Carhartt premium y2k swag big logo workwear drip japan style", 11),
    ("marktplaats.nl", "Handmade wooden race car bed with headlights – 90 200 cm", 50),
    ("marktplaats.nl", "Bright Eyes - Down In The Weeds, Where The World Once Was", 26),
    ("tori.fi", "Carrera GO!!! Paw Patrol Ready Race Rescue Slot Car Racetrack", 57),
    ("marktplaats.nl", "*A used car in very good condition. Bright yellow bodywork sets this ferrari enzo apart", 50),
    ("corashop.fi", "SELEMIX AQUA TINTER Bright Red", 221), ("capitalone.com", "Used Cars for Sale", 6333),
    ("vinted.fi", "Cargo zielone spodenki Bershka XS", 2),
]
REAL_CARS = [("marktplaats.nl", "Volvo XC90 T8 455PK AWD Ultra Bright | Trekhaak | Massagefun", 70950),
             ("tori.fi", "Toyota Corolla 1.6 2012 210 tkm punainen", 4500)]


def _o(src, title, p, i=0):
    return Offer(url=f"https://{src}/item/{i}", source=src, title=title, price=p, currency="EUR", price_eur=p,
                 condition="used")


def test_red_car_need_is_a_car_with_a_colour_wish():
    n = N.parse_need_rules("bright red car")
    assert n.thing == "car" and n.must_have == ["bright red"] and "refurbished" not in n.conditions
    assert N.vehicle_need("car") and not N.vehicle_need("car seat") and not N.vehicle_need("toy car")


def test_red_car_page_rejects_every_non_car_and_keeps_real_cars():
    n = N.parse_need_rules("bright red car")
    for src, title, p in RED_CAR_PAGE:
        r, why = resolve.explain(n, _o(src, title, p))
        assert why is not None, title
    for src, title, p in REAL_CARS:
        assert resolve.explain(n, _o(src, title, p))[1] is None, title


def test_whole_word_matching():
    toks = set(resolve.tokenize("Szerokie Cargo Spodnie Carhartt Carlotta Carrera"))
    assert not resolve.word_hit("car", toks)
    assert resolve.word_hit("car", {"cars"}) and resolve.word_hit("auto", {"autot"})
    assert resolve.word_hit("pyora", {"kaupunkipyora"})


def test_category_pages_are_not_offers():
    for t in ("Used Cars for Sale", "Autot", "Gebrauchtwagen in Berlin", "1 234 results", "Used cars near you"):
        assert resolve.category_page(t), t
    for t in ("Volvo XC90 T8 2019", "Toyota Corolla for sale 2012", "Kids Ride-On Car"):
        assert not resolve.category_page(t), t


def test_red_car_pick_is_never_a_toy():
    n = N.parse_need_rules("bright red car")
    offers = [_o(s, t, p, i) for i, (s, t, p) in enumerate(RED_CAR_PAGE + REAL_CARS)]
    things = resolve.resolve(n, offers)
    v = judge.judge(n, things, history=False)
    best = next(o for t in things for o in t.offers if o.url == v.best_offer_url)
    assert best.price_eur >= 500 and "kids" not in best.title.lower()


def test_vehicle_routes_to_car_marketplaces_first_without_excluding_others():
    pages = marketplaces.direct_pages("car", "used", None, "fi", 10)
    keys = [d.site.key for d in pages]
    assert keys[0] == "nettiauto" and "tori" in keys                            # priority, not exclusion
    assert pages[0].url == "https://www.nettiauto.com/vaihtoautot"              # generic 'car': browse the category
    assert marketplaces.site_for("https://www.tori.fi/mobility/search/car").key == "tori_autot"


def test_marketplace_platform_rating_never_sets_listings_aside(monkeypatch):
    from agora import reviews
    monkeypatch.setattr(reviews, "signals_for", lambda o: [("reviews: red flags", 0.45, 0.4)])
    o = _o("marktplaats.nl", "Volvo XC90 T8 2019", 30000)
    assert judge._trust_signals(o, [o], None) == [] or all("reviews" not in s[0] for s in judge._trust_signals(o, [o], None))
    shop = Offer(url="https://badshop.example/p/1", source="badshop.example", title="x", price=1, currency="EUR")
    assert any("reviews" in s[0] for s in judge._trust_signals(shop, [shop], None))


# --------------------------------------------------------------------------- 6. free registry sources, paginated

def _mp_page(start: int, n: int) -> str:
    rows = "".join(f'<li><a href="/v/audio-tv-en-foto/koptelefoons/a{100000 + i}-airpods-pro-2">'
                   f'AirPods Pro 2 used</a><span>€ {120 + i % 50},00</span></li>' for i in range(start, start + n))
    return f"<html><body><ul>{rows}</ul></body></html>"


def test_marktplaats_is_read_free_and_paginated(monkeypatch):
    """Owner: 'are we even checking multiple pages? marktplaats has multiple pages'."""
    monkeypatch.setenv("AGORA_DIRECT", "1")
    site = marketplaces.SITES["marktplaats"]
    assert marketplaces.free_site(site)
    asked: list[str] = []

    async def fetch(url):
        asked.append(url)
        page = 1 if "/p/" not in url else int(url.rstrip("/").rsplit("/", 1)[-1])
        return (200, _mp_page(page * 100, 20)) if page <= 3 else (200, "<html><body>geen resultaten</body></html>")
    monkeypatch.setattr(reader, "fetch_html", fetch)
    n = N.parse_need_rules("airpods pro 2")
    url = marketplaces.build_url(site, "airpods pro 2")
    got, via = asyncio.run(reader.read_with_reason(url, n, lane="used", paid=False, expand_lists=True))
    assert via == "plain_split" and isinstance(got, list) and len(got) == 60
    assert {o.raw["page"] for o in got} == {1, 2, 3} and any(u.endswith("/p/2/") for u in asked)
    assert all(o.read_via == "plain_split" and o.condition == "used" for o in got)


def test_free_registry_pages_cost_no_token_in_the_plan():
    plan = marketplaces.direct_pages("airpods pro 2", "used", None, "fi", tokens=0)
    assert {"vinted_fi", "marktplaats", "kleinanzeigen"} <= {d.site.key for d in plan}
    assert not any(d.paid for d in plan)
