"""Round 1 regressions from the saved live hunts: the numbers on screen must survive a sceptic."""
from __future__ import annotations

import pytest

from agora import judge as jd
from agora.judge import (beat_price, deduction_back, estimate_true_cost, import_lines, judge, make_haggle,
                         verify_price)
from agora.models import Need, Offer, Thing
from agora.resolve import resolve
from live_offers import load


def sony():
    need, offers, sources = load("sony-a7-iii-body")
    things = resolve(need, offers)
    v = judge(need, things)
    by = {o.source: o for t in things for o in t.offers}
    return need, things, v, by


def test_one_median_everywhere():
    """Flags, resale basis and haggle all quote the same used median (€774), not €868 vs €774."""
    _, _, v, by = sony()
    used = by["usedlens.co.uk"]
    assert not any("well under" in f for f in used.flags)       # 601 is 22% under 774: fine, no penalty
    assert "median €774" in used.true_cost.basis
    assert any("€774" in f for f in by["mpb.com"].flags)
    assert not any("€868" in line for line in v.lines + [v.headline])


def test_too_good_price_is_shown_but_not_costed_or_cheered():
    _, _, v, by = sony()
    mpb = by["mpb.com"]
    assert mpb.true_cost is None and mpb.haggle is None
    assert any(f.startswith("too good to be true") for f in mpb.flags)
    assert "mpb.com" not in (v.best_true_cost_url or "") and "mpb.com" not in (v.best_offer_url or "")


def test_headline_ratio_is_honest():
    need, offers, _ = load("sony-a7-iii-body")
    for o in offers:
        if o.source == "usedlens.co.uk":
            o.raw["ships_text"] = "anywhere"      # its page says it ships abroad: it may lead the headline
    v = judge(need, resolve(need, offers))
    assert "/mo" not in v.headline
    assert v.headline.startswith("€644 all in: used at usedlens.co.uk")   # it ships here now: cheapest all-in wins
    # (€629 + est. €15 courier customs clearance from the UK)


def test_unconfirmed_shipping_leads_with_what_you_can_surely_buy():
    """usedlens.co.uk (UK) is cheapest to own, but nothing says it ships to Finland."""
    _, _, v, by = sony()
    assert v.headline.startswith("€1,029 all in: new at e-infin.com")
    assert "Used from €644 (may not ship to Finland)" in v.headline
    assert any("usedlens.co.uk is cheaper" in line and "ships to Finland" in line for line in v.lines)
    assert "usedlens" not in v.best_offer_url
    assert any("shipping to Finland unconfirmed" in f for f in by["usedlens.co.uk"].flags)


def test_shop_that_does_not_ship_here_is_never_crowned():
    need, offers, _ = load("sony-a7-iii-body")
    for o in offers:
        if o.source == "usedlens.co.uk":
            o.raw["ships_to"] = ["GB"]
    v = judge(need, resolve(need, offers))
    assert "usedlens" not in (v.best_true_cost_url or "") + (v.best_offer_url or "")


def test_ships_to_from_jsonld_and_text():
    from agora.reader import ships_text, ships_to
    assert ships_to({"shippingDetails": {"@type": "OfferShippingDetails",
                                         "shippingDestination": {"@type": "DefinedRegion", "addressCountry": "FI"}}}) == ["FI"]
    assert ships_to({"eligibleRegion": [{"@type": "Country", "name": "GB"}]}) == ["GB"]
    assert ships_to({}) is None
    assert ships_text("<p>Free UK mainland delivery only</p>") == "home_only"
    assert ships_text("<p>We ship worldwide!</p>") == "anywhere"


def test_same_page_search_listing_is_not_double_verification():
    """wedio: 'from € 1,608' in the search title and €1,608 on the page are one source, and a list price."""
    from agora.reader import add_witnesses
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    o = Offer(url="https://www.wedio.com/en/sony-alpha-a7-iii", source="wedio.com", title="Sony a7 III",
              price=1608.0, currency="EUR", price_eur=1608.0, condition="used")
    add_witnesses(o, "contextdev_product", search_title="Sony Alpha a7 III | Buy Used & New from € 1,608 - Wedio",
                  need=need)
    trust, flags = jd.assess_trust(o, [o])
    assert o.raw["from_price"] and o.raw["price_check"] == "consistent"
    assert not any("verified" in f for f in flags)
    assert "from-price, not a specific unit" in flags
    # a different shop's page quoting the same price IS independent
    o.raw["witnesses"].append({"via": "jsonld", "price": 1600, "currency": "EUR", "primary": False,
                               "doc": "https://www.other-shop.de/a7iii"})
    o.raw.pop("from_price")
    assert verify_price(o) == "price verified x2 (independent sources)"


def test_grey_import_is_flagged_with_a_warranty_line():
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    grey = Offer(url="https://www.e-infin.com/eu/item/3555", source="e-infin.com", title="Sony a7 III (Body Only)",
                 price=1029, currency="EUR", price_eur=1029, condition="new", seller="e-infin",
                 raw={"search_text": "€1,029.00 - 12 Months Warranty - 100% Brand New - Import Tax Included"})
    eu = Offer(url="https://dakauf.eu/a7", source="dakauf.eu", title="Sony a7 III", price=1063, currency="EUR",
               price_eur=1063, condition="new", seller="dakauf")
    judge(need, [Thing(id="t", name="Sony A7 III", offers=[grey, eu])])
    assert any(f.startswith("possible grey import") and "import tax included" in f.lower() for f in grey.flags)
    assert any(lbl.startswith("warranty risk") and v == 0.0 for lbl, v in grey.true_cost.receipt)
    assert not any(f.startswith("possible grey import") for f in eu.flags)
    # outside the EU and far under the EU new median: grey even without the words
    us = Offer(url="https://us.shop/a7", source="us.shop", title="Sony a7 III", price=700, currency="USD",
               price_eur=650, condition="new", seller="x")
    assert jd.grey_import(us, [us, eu, grey]) and "under the EU new median" in jd.grey_import(us, [us, eu, grey])


def test_service_lines_say_where_the_area_rate_comes_from():
    from agora.need import parse_need
    s = parse_need("home cleaning Helsinki 60m2")
    a = Offer(url="a", source="a.fi", title="Home cleaning", price=38, currency="EUR", price_eur=38,
              condition="service", unit="hour", seller="x")
    b = Offer(url="b", source="b.fi", title="Home cleaning", price=40, currency="EUR", price_eur=40,
              condition="service", unit="hour", seller="y", raw={"m2_per_hour": 30})
    v = judge(s, [Thing(id="t", name="home cleaning", offers=[a, b])])
    assert "assumed 25 m²/h, same for all" in a.true_cost.receipt[0][0]
    assert "page says 30 m²/h" in b.true_cost.receipt[0][0] and b.true_cost.total_eur == 80.0
    assert v.lines[0].startswith("b.fi")          # the stated rate is listed first


def test_uk_vat_comes_off_before_finnish_import_vat():
    o = Offer(url="u", source="cvp.com", title="Sony A7III", price=1169, currency="GBP", price_eur=1375.29,
              condition="new")
    lines = import_lines(o)
    assert [round(v, 2) for _, v in lines] == [-229.21, round(1375.29 / 1.2 * 0.255, 2), 15.0, 0.0]
    assert "courier customs clearance" in lines[2][0] and "est." in lines[2][0]
    assert lines[3][0] == "customs duty: 0% for cameras (ITA agreement)"
    assert jd.import_fee(o) == pytest.approx(1375.29 / 1.2 * 1.255 - 1375.29 + 15, abs=0.02)   # ~ +4.6% + clearance
    us = Offer(url="b", source="bh.com", title="x", price=100, currency="USD", price_eur=90, condition="new")
    assert jd.import_fee(us) == pytest.approx(90 * 0.255 + 15)          # under €150: no duty note


def test_cheapest_up_front_is_landed_and_best_link_prefers_eu():
    need, offers, _ = load("iphone-15-128gb-used")
    v = judge(need, resolve(need, offers))
    assert v.headline.startswith("€392 all in: refurbished at remobile.eu")    # the winner comes first
    assert any("swappa.com" in line and "€374" in line for line in v.lines)    # €294 + €75 import VAT + €5 postal handling
    assert "remobile.eu" in (v.best_offer_url or "")     # an EU shop exists: no US-only marketplace link


def test_fx_static_rate_is_in_basis_and_lowers_confidence(monkeypatch):
    from agora import fx
    monkeypatch.setattr(fx, "_rates", None)
    o = Offer(url="u", source="usedlens.co.uk", title="Used Sony A7 III", price=510.84, currency="GBP",
              price_eur=600.99, condition="used")
    comps = [Offer(url=f"c{i}", source="tori.fi", title="Sony A7 III", price=p, currency="EUR", price_eur=p,
                   condition="used") for i, p in enumerate((700, 750, 800, 820, 760))]
    tc = estimate_true_cost(o, comps + [o])
    assert "FX: 1 GBP = €1.18 (static fallback rate" in tc.basis
    assert tc.confidence == "medium"                     # 6 comps would be high; static FX steps it down


def test_zar_converts_now():
    from agora import fx
    assert fx.to_eur(25999, "ZAR") == pytest.approx(25999 / 20.5, abs=0.01)


def test_haggle_only_for_private_listings_in_their_currency():
    need, things, _, by = sony()
    for src in ("usedlens.co.uk", "wexphotovideo.com", "henrys.com", "mpb.com"):
        assert by[src].haggle is None, src                # dealers / risky: no script
    used = [Offer(url=f"https://www.ebay.co.uk/itm/{i}", source="ebay.co.uk", title="Sony A7 III", price=p,
                  currency="GBP", price_eur=round(p * 1.176, 2), condition="used", seller="s")
            for i, p in enumerate((600, 640, 680, 720, 700))]
    h = make_haggle(used[3], used, "Sony A7 III")
    assert h and "GBP" in h.message and "€" not in h.message
    cheap = make_haggle(used[0], used, "Sony A7 III")
    assert cheap and "serial number" in cheap.message and "fair" not in cheap.message


def test_two_witnesses_verify_or_dispute():
    o = Offer(url="u", source="shop.fi", title="x", price=239, currency="EUR", price_eur=239, condition="used",
              raw={"witnesses": [{"via": "contextdev_product", "price": 239, "currency": "EUR", "primary": True},
                                 {"via": "snippet", "price": 849, "currency": "EUR", "primary": False}]})
    assert verify_price(o) == "price disagrees: page €239 vs search €849"
    assert o.raw["price_check"] == "disputed"
    ok = Offer(url="v", source="shop.fi", title="x", price=849, currency="EUR", price_eur=849, condition="used",
               raw={"witnesses": [{"via": "jsonld", "price": 849, "currency": "EUR", "primary": True},
                                  {"via": "snippet", "price": 829, "currency": "EUR", "primary": False}]})
    # the search listing is the same page seen twice: consistent, never "verified"
    assert verify_price(ok).startswith("price matches the search listing")
    assert ok.raw["price_check"] == "consistent"


def test_disputed_price_is_left_out_of_comps_and_verdict():
    need, offers, _ = load("sony-a7-iii-body")
    mpb = next(o for o in offers if o.source == "mpb.com")
    mpb.raw["witnesses"] = [{"via": "contextdev_product", "price": 239, "currency": "EUR", "primary": True},
                            {"via": "snippet", "price": 849, "currency": "EUR", "primary": False}]
    things = resolve(need, offers)
    v = judge(need, things)
    assert mpb.true_cost is None and mpb.raw["price_check"] == "disputed"
    assert any("price disagrees" in line for line in v.lines)
    assert 239.0 not in jd.used_comps([o for t in things for o in t.offers])


def test_evidence_points_at_the_page():
    _, _, _, by = sony()
    ev = by["e-infin.com"].raw["evidence"]
    assert ev[0]["line_index"] == 0 and ev[0]["url"].startswith("https://www.e-infin.com")
    assert any(e["via"] == "used comps" and e["urls"] for e in ev)


def test_price_to_beat():
    """beat_eur = the tag price at which an offer's ALL-IN price would match the pick's all-in price."""
    need, things, v, by = sony()
    pick = next(o for t in things for o in t.offers if o.url == v.best_offer_url)
    for o in (by["usedlens.co.uk"], by["sacameraland.com"]):
        beat = o.raw["beat_eur"]
        extras = (o.true_cost.sticker_eur + o.true_cost.extras_eur) - o.price_eur if o.true_cost else 0
        pick_all_in = pick.true_cost.sticker_eur + pick.true_cost.extras_eur
        assert beat == pytest.approx(pick_all_in - extras, abs=0.02)
        assert o.raw["gap_eur"] == pytest.approx(o.price_eur - beat, abs=0.02)


def test_service_one_job_uses_one_time_tier_and_conditional_deduction():
    need = Need(raw="home cleaning helsinki 60m2", thing="home cleaning", kind="service", where="Helsinki")
    o = Offer(url="https://novah.fi/en/prices/helsinki", source="novah.fi", title="One-time home cleaning",
              price=49.9, currency="EUR", price_eur=49.9, condition="service", unit="hour",
              raw={"tier": "one-time"})
    v = judge(need, [Thing(id="t", name="home cleaning", offers=[o])])
    assert o.true_cost.total_eur == pytest.approx(124.75) and o.true_cost.per == "job"
    assert "€49.90/h one-time" in o.true_cost.receipt[0][0] or "€50/h one-time" in o.true_cost.receipt[0][0]
    assert v.headline.startswith("€125 for one 60 m² clean at novah.fi (one-time rate), €49.90/h × 2.5 h, about €75 after")
    assert deduction_back(124.75) == 0.0                         # alone: under the €150 excess
    assert deduction_back(124.75, other_work_this_year=1000) == pytest.approx(49.9)


def test_net_and_gross_from_one_page_are_one_provider():
    need = Need(raw="home cleaning helsinki 60m2", thing="home cleaning", kind="service", where="Helsinki")
    url = "https://www.isojoo.fi/en/home-cleaning"
    gross = Offer(url=url, source="isojoo.fi", title="Home cleaning", price=49.8, currency="EUR", price_eur=49.8,
                  condition="service", unit="hour")
    net = Offer(url=url, source="isojoo.fi", title="Home cleaning (after household tax credit)", price=29.88,
                currency="EUR", price_eur=29.88, condition="service", unit="hour")
    t = Thing(id="t", name="home cleaning", offers=[gross, net])
    judge(need, [t])
    assert t.offers == [gross] and gross.raw["page_deduction_rate"] == pytest.approx(0.4)


def test_seen_before_replaces_unknown_shop_noise():
    from agora import store
    _, _, _, by = sony()
    assert not any("shop not known" in f for o in by.values() for f in o.flags)
    o = by["e-infin.com"]
    store.save_offer(o)
    for ts in (1_000_000.0, 1_100_000.0):
        store.snapshot(o.url, o.price_eur, True, seen_at=ts)
    _, _, _, again = sony()
    # round-1 judges: 'seen before in N hunts' on every row is noise to a shopper; kept in raw, not in flags
    assert again["e-infin.com"].raw.get("seen_hunts") == 2
    assert not any(f.startswith("seen before") for f in again["e-infin.com"].flags)


def test_area_rate_from_page_text():
    from agora.reader import area_rate
    assert area_rate("<p>Siivoamme noin 25 neliötä tunnissa</p>") == 25.0
    assert area_rate("we clean about 30 m²/h") == 30.0
    assert area_rate("apartment 60 m2") is None
