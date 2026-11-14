import pytest

from agora.judge import (CATEGORIES, assess_trust, category_for, estimate_true_cost, judge, make_haggle)
from agora.models import Need, Offer, Thing
from agora.need import parse_need
from agora.resolve import resolve
from brain_fixtures import market


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    # a fixed "today's rates" table: confidence must not depend on which test loaded FX first
    from agora import fx
    monkeypatch.setattr(fx, "_rates", dict(fx.STATIC_RATES))
    monkeypatch.setattr(fx, "_rates_source", "frankfurter")


def a7_thing() -> tuple[Need, Thing, list[Offer]]:
    n = parse_need("sony a7 iii")
    offers = market()
    things = resolve(n, offers)
    return n, things[0], offers


def by(thing: Thing, source: str, cond: str | None = None) -> Offer:
    return next(o for o in thing.offers if o.source == source and (cond is None or o.condition == cond))


def test_categories():
    assert category_for("iPhone 15 Pro").name == "phone"
    assert category_for("Sony a7 III").name == "camera"
    assert category_for("Sony FE 85mm f/1.8 lens").name == "lens"
    assert category_for("Bosch washing machine").name == "appliance"
    assert category_for("cargo e-bike").name == "ebike"
    assert category_for("a garden gnome").name == "other"
    assert {c.name: c.rate for c in CATEGORIES}["camera"] == 0.12


def test_trust_flags_scam_and_missing_price():
    n, t, _ = a7_thing()
    judge(n, [t])
    scam = next(o for o in t.offers if o.price_eur == 290)
    assert scam.trust is not None and scam.trust < 0.5
    assert any("too good to be true" in f for f in scam.flags)
    assert any("seller unknown" in f for f in scam.flags)
    good = by(t, "huuto.net")
    assert good.trust is not None and good.trust >= 0.9 and good.flags == []

    nop = Offer(url="x", source="ebay.com", title="Sony a7 III", price=None, currency=None, condition="used")
    trust, flags = assess_trust(nop, [])
    assert trust <= 0.5 and "no price on the page" in flags and "seller unknown" in flags
    oos = Offer(url="y", source="bhphotovideo.com", title="Sony a7 III", price=1398, currency="USD",
                price_eur=1286, condition="new", in_stock=False)
    assert "out of stock" in assess_trust(oos, [])[1]


def test_true_cost_new_vs_used_receipt():
    n, t, _ = a7_thing()
    judge(n, [t])
    # used comps (trusted): ebay 726.79, 780, 850, 720, 900, 700 -> median 753.4; scam excluded
    new = by(t, "bhphotovideo.com")
    tc = new.true_cost
    assert tc is not None and tc.months == 12 and tc.confidence == "high"
    assert tc.sticker_eur == pytest.approx(1286.16)
    assert tc.resale_eur == pytest.approx(753.4 * 0.88, abs=0.5)
    # B&H prices in USD: import VAT is part of the true cost and has its own receipt line
    assert tc.extras_eur == pytest.approx(1286.16 * 0.255, abs=0.01)
    assert any("import VAT" in label for label, _ in tc.receipt)
    assert tc.total_eur == pytest.approx(tc.sticker_eur + tc.extras_eur - tc.resale_eur, abs=0.01)
    assert tc.per_month_eur == pytest.approx(tc.total_eur / 12, abs=0.01)
    assert tc.receipt[0] == ("sticker", 1286.16) and tc.receipt[-1][0] == "resale in 12 mo"
    assert "6 used listings" in tc.basis and "-12%/yr" in tc.basis

    used = by(t, "tori.fi", "used")
    assert used.true_cost and used.true_cost.per_month_eur < tc.per_month_eur / 4


def test_true_cost_without_used_comps_still_works():
    o = Offer(url="n", source="gigantti.fi", title="Bosch Serie 6 washing machine", price=699, currency="EUR",
              price_eur=699, condition="new", shipping_eur=49)
    tc = estimate_true_cost(o, [o])
    assert tc is not None and tc.confidence == "low"
    assert tc.resale_eur == pytest.approx(699 * 0.5 * 0.85, abs=0.01)    # appliance: 50% used value, -15%/yr
    assert tc.extras_eur == 49 and ("shipping / fees", 49) in tc.receipt
    assert "no used listings" in tc.basis


def test_true_cost_horizon_and_rental():
    o = Offer(url="r", source="grover.com", title="Sony a7 III rent", price=59, currency="EUR", price_eur=59,
              condition="rental", unit="month")
    tc = estimate_true_cost(o, [o], months=6)
    assert tc and tc.total_eur == 354 and tc.resale_eur is None and tc.per_month_eur == 59
    n, t, _ = a7_thing()
    judge(n, [t], months=24)
    tc24 = by(t, "bhphotovideo.com").true_cost
    assert tc24 and tc24.months == 24 and tc24.resale_eur == pytest.approx(753.4 * 0.88 ** 2, abs=0.5)


def test_resale_never_exceeds_price():
    n, t, _ = a7_thing()
    judge(n, [t])
    cheap_used = by(t, "tori.fi", "used")          # bought at the bottom of the market
    tc = cheap_used.true_cost
    assert tc and tc.resale_eur is not None and tc.resale_eur <= tc.sticker_eur and tc.total_eur >= 0


def test_haggle_for_used():
    n, t, _ = a7_thing()
    judge(n, [t])
    o = by(t, "huuto.net")                           # asking €900, top of the band
    h = o.haggle
    assert h is not None
    assert h.fair_low_eur < h.fair_high_eur and h.fair_low_eur <= h.suggested_offer_eur < 900
    assert h.suggested_offer_eur % 10 == 0
    assert "Sony A7 III" in h.message and f"€{h.suggested_offer_eur:,.0f}" in h.message
    assert by(t, "bhphotovideo.com").haggle is None   # shops do not haggle


def test_haggle_fallback_without_comps():
    new = Offer(url="n", source="apple.com", title="iPhone 15", price=799, currency="EUR", price_eur=799, condition="new")
    used = Offer(url="u", source="tori.fi", title="iPhone 15", price=650, currency="EUR", price_eur=650, condition="used")
    h = make_haggle(used, [new, used], "Apple iPhone 15")
    assert h and h.suggested_offer_eur < 650 and "usually sell around" in h.message


def test_verdict_headline_compares_new_and_used():
    n, t, _ = a7_thing()
    v = judge(n, [t])
    # the headline is the full price you pay once; per-month is a secondary line
    assert "all in" in v.headline and "/mo" not in v.headline
    assert "new" in v.headline.lower() and "used" in v.headline.lower()
    assert any(line.startswith("used:") and "all in" in line for line in v.lines)
    assert any(line.startswith("new:") and "all in" in line for line in v.lines)
    assert any("risky" in line for line in v.lines)
    assert v.buy_or_wait == "buy now"


def test_verdict_budget_and_wait():
    n = parse_need("new sony a7 iii under €1000")
    o = Offer(url="b", source="bhphotovideo.com", title="Sony a7 III", price=1398, currency="USD",
              price_eur=1286.16, condition="new", in_stock=True)
    v = judge(n, [Thing(id="t", name="Sony A7 III", offers=[o])])
    assert v.buy_or_wait == "wait: set a watch"
    assert any("over your €1,000 budget" in line for line in v.lines)


def test_verdict_empty_and_service():
    n = parse_need("sony a7 iii")
    v = judge(n, [])
    assert v.best_offer_url is None and "No priced offers" in v.headline
    s = parse_need("home cleaning in Espoo")
    offs = [Offer(url=str(p), source="siivous.fi", title="Home cleaning", price=p, currency="EUR", price_eur=p,
                  condition="service", unit="hour", seller="x") for p in (35, 42, 39)]
    v = judge(s, [Thing(id="t", name="home cleaning", offers=offs)])
    # no size given: a typical 2 h visit; gross headline, the deduction is conditional (Espoo is in Finland)
    # €70 alone is under the €150 yearly excess: the headline must not promise the deduction outright
    assert v.headline == ("€70 for one clean at siivous.fi, €35/h × 2 h, about €42 after the household deduction "
                          "once your household work this year passes its €150 excess.")
    tc = offs[0].true_cost
    assert tc and tc.months == 0 and tc.per == "job" and tc.confidence == "low" and tc.total_eur == 70.0
    assert all(val > 0 for _, val in tc.receipt)
    # a single €70 job on its own is under the €150 yearly excess: nothing back
    assert any("this job alone gets €0 back" in line for line in v.lines)


def test_service_job_cost_from_size_and_deduction_grossed_up():
    s = parse_need("home cleaning Helsinki 60m2")
    gross = Offer(url="a", source="novah.fi", title="Weekly home cleaning", price=40, currency="EUR",
                  price_eur=40, condition="service", unit="hour", seller="x")
    net = Offer(url="b", source="isojoo.fi", title="Home cleaning (after household tax credit)", price=30,
                currency="EUR", price_eur=30, condition="service", unit="hour", seller="y")
    unknown = Offer(url="c", source="k.fi", title="Home cleaning", price=45, currency="EUR", price_eur=45,
                    condition="service", seller="z")
    v = judge(s, [Thing(id="t", name="home cleaning", offers=[gross, net, unknown])])
    assert net.price_eur == 50 and any("after the household deduction" in f for f in net.flags)
    assert gross.true_cost and gross.true_cost.receipt[0] == ("€40/h x 2.5 h for 60 m² (assumed 25 m²/h, same for all)", 100.0)
    assert gross.true_cost.total_eur == 100.0 and unknown.true_cost is None
    assert v.best_true_cost_url == "a" and v.best_offer_url == "a"
    assert "€100 for one 60 m² clean at novah.fi, €40/h × 2.5 h, about €60 after the household deduction" in v.headline


def test_currency_weirdness():
    o = Offer(url="w", source="shop.xyz", title="Sony a7 III", price=1500, currency="XYZ", condition="new")
    trust, flags = assess_trust(o, [])
    assert trust < 1 and any("could not be converted" in f for f in flags)


def test_used_outlier_above_new_is_not_a_comp_and_cheap_used_resells_from_its_price():
    from agora.judge import estimate_true_cost, used_comps
    from agora.models import Offer

    def o(price, cond, title="Sony A7 III"):
        return Offer(url=f"https://x/{price}{cond}", source="shop.fi", title=title, price=price,
                     currency="EUR", price_eur=price, condition=cond)

    offers = [o(1029, "new"), o(1063, "new"), o(601, "used"), o(1680, "used", "Sony A7III modded astro")]
    assert used_comps(offers) == [601]
    offers.append(o(900, "used"))
    tc = estimate_true_cost(offers[2], offers)          # the €601 one
    assert tc and 0 < tc.resale_eur < 601 and tc.per_month_eur > 0
    assert "your price" in tc.basis
