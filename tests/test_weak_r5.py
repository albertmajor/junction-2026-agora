"""Round 5 live verification of the weak areas (port 9150 run, 14 Nov): each defect seen live, offline."""
from __future__ import annotations

import pytest

from agora import shipping
from agora.judge import _shipping_flags
from agora.models import Need, Offer


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")


def _abroad(o: Offer) -> Offer:
    o.raw["abroad"] = True
    return o


def test_a_car_abroad_is_not_a_parcel(monkeypatch):
    # live 'volvo v70': "also in the EU: €3,420 all in at autoscout24.de (€3,390 + est. shipping €20–45)"
    o = Offer(url="https://www.autoscout24.de/angebote/volvo-v70-x", source="autoscout24.de", title="Volvo V70 2.4D",
              price=3390.0, currency="EUR", price_eur=3390.0, condition="used")
    monkeypatch.setattr(shipping, "offer_country", lambda _o: "de")
    monkeypatch.setattr(shipping, "is_listing", lambda _o: True)
    _shipping_flags(o, Need(raw="volvo v70", thing="volvo v70"))
    est = o.raw["shipping_est"]
    assert est["size"] == "vehicle"
    assert est["low"] >= 400 and o.shipping_eur >= 400
    assert "car transport" in est["how"]


def test_size_class_knows_cars_but_not_car_accessories():
    assert shipping.size_class("car volvo v70") == "vehicle"
    assert shipping.size_class("auto toyota corolla") == "vehicle"
    assert shipping.size_class("car seat") != "vehicle"
    assert shipping.size_class("car charger") != "vehicle"


# ------------------------------------------------------------------ 'bright red car': colour in the pick

def _car(i: int, title: str, price: float, colour: bool | None = None) -> Offer:
    o = Offer(url=f"https://www.nettiauto.com/x/y/1610{i:04d}", source="nettiauto.com", title=title, price=price,
              currency="EUR", price_eur=price, condition="used")
    o.raw["category"] = "vehicle"          # nettiauto's list: a cars category (reader)
    if colour is not None:
        o.raw["colour"] = "red" if colour else "blue"
        o.raw["colour_match"] = colour
    return o


def _red_need():
    from agora.need import parse_need
    return parse_need("bright red car")


def test_a_car_that_says_it_is_red_beats_a_cheaper_one_of_unknown_colour():
    # live: the pick was a €6,900 'Subaru Outback' with no colour at all; nothing said it was red
    from agora.judge import judge
    from agora.resolve import resolve
    need = _red_need()
    offers = [_car(1, "Subaru Outback", 6900), _car(2, "Skoda Octavia punainen", 7400, True),
              _car(3, "Ford Focus", 7100), _car(4, "Toyota Corolla", 7600), _car(5, "Kia Ceed", 7800)]
    v = judge(need, resolve(need, offers), history=False)
    assert v.best_offer_url == offers[1].url
    assert any("red" in line and "1 of" in line for line in v.lines)


def test_no_car_states_its_colour_says_so_plainly():
    from agora.judge import judge
    from agora.resolve import resolve
    need = _red_need()
    offers = [_car(1, "Subaru Outback", 6900), _car(3, "Ford Focus", 7100), _car(4, "Toyota Corolla", 7600),
              _car(5, "Kia Ceed", 7800)]
    v = judge(need, resolve(need, offers), history=False)
    assert any("colour" in line and "not" in line for line in v.lines)
    assert "colour not confirmed" in v.headline


# ------------------------------------------------------------------ 'haircut helsinki': a clipper-only cut

def test_a_clipper_only_cut_is_not_the_standard_haircut():
    # live: the pick was 'Koneajo' €20 (timma.fi), a clipper-only buzz cut, over €23-26 'Parturileikkaus'
    from agora.need import parse_need
    from agora.resolve import service_line_kind
    need = parse_need("haircut helsinki")
    for t in ("Koneajo", "Buzzcut – Wildan Studio", "Clipper cut", "Koneajo, yksi pituus"):
        assert service_line_kind(need, t, "job") == "extra", t
    for t in ("Parturileikkaus", "Miesten hiusten leikkaus", "Haircut – Thieves Barber", "Parturileikkaus, fade"):
        assert service_line_kind(need, t, "job") == "main", t
    assert service_line_kind(parse_need("buzzcut helsinki"), "Buzzcut – Wildan Studio", "job") == "main"
