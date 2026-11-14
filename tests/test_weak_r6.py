"""Round 6 weak areas (live r5 streams, 14 Nov): car facts on list offers, commercial vehicles in a car hunt, the
gunsmith (a workshop trade), wedding packages by coverage, one place on two aggregators, and the hunt budget.
Offline: titles, prices and sites come from the saved streams; every rule is judged per listing, never per site."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from agora import hunt
from agora import judge as J
from agora import reader
from agora import resolve as R
from agora.models import Need, Offer


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")


def svc(thing: str, where: str = "Helsinki", raw: str | None = None) -> Need:
    return Need(raw=raw or f"{thing} {where}", thing=thing, kind="service", where=where, conditions=["service"])


def page(url: str, title: str, price: float, unit: str | None = "job", **kw) -> Offer:
    raw = kw.pop("raw", {})
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price, currency="EUR",
                 price_eur=price, condition="service", unit=unit, raw=dict(raw), **kw)


def run(n: Need, offers: list[Offer]):
    things = R.resolve(n, offers)
    return things, J.judge(n, things, history=False)


# ------------------------------------------------------------------ 1. car facts on list offers

def test_car_facts_from_a_list_row():
    f = reader.car_facts_from_text("Volvo V70 2.4D 2012 182 000 km Diesel Automaatti Farmari")
    assert f == {"year": 2012, "km": 182000, "fuel": "Diesel", "gearbox": "Automaatti"}
    assert reader.car_facts_from_text("Toyota Corolla 1.6 2009 210 tkm manuaali")["km"] == 210000
    assert reader.car_facts_from_text("Volvo V70")== {}


def test_subtitle_leaves_out_what_the_title_says():
    sub = reader.car_subtitle("Nissan Micra Bensiini (1996)", {"year": 1996, "km": 164709, "fuel": "Bensiini",
                                                              "gearbox": "Manuaali"}, "Punainen")
    assert sub == "164 709 km · Manuaali · Punainen"


ITEMLIST_HTML = """<html><head><script type="application/ld+json">{"@context": "https://schema.org",
"@type": "ItemList", "numberOfItems": 3, "itemListElement": [%s]}</script></head><body>cars</body></html>"""


def _car_item(i: int, name: str, price: int, year: int, km: int, colour: str) -> str:
    return json.dumps({"@type": "ListItem", "position": i, "item": {
        "@type": "Car", "name": name, "url": f"https://www.nettiauto.com/volvo/v70/1600000{i}",
        "vehicleModelDate": str(year), "mileageFromOdometer": {"@type": "QuantitativeValue", "value": km,
                                                               "unitCode": "KMT"},
        "fuelType": "Diesel", "vehicleTransmission": "Manuaali", "color": colour,
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR"}}})


def test_list_cars_carry_year_km_fuel_gearbox_colour_in_the_shown_title():
    # live r5: nettiauto's list gave bare 'Volvo V70' titles (the paid markdown split); its HTML has every car's facts
    html = ITEMLIST_HTML % ",".join([_car_item(1, "Volvo V70", 2750, 2008, 312000, "Punainen"),
                                     _car_item(2, "Volvo V70", 3900, 2011, 254000, "Musta"),
                                     _car_item(3, "Volvo V70", 4500, 2012, 199000, "Hopea")])
    url = "https://www.nettiauto.com/volvo/v70"
    need = Need(raw="volvo v70", thing="volvo v70")
    cars = reader.car_page_offers(html, reader._extruct(html, url), url, need, "used")
    assert len(cars) == 3
    by = {o.price: o for o in cars}
    assert by[2750].raw["subtitle"] == "2008 · 312 000 km · Diesel · Manuaali · Punainen"
    d = hunt.offer_payload(by[3900])
    assert d["subtitle"] == "2011 · 254 000 km · Diesel · Manuaali · Musta"
    assert d["title"] == "Volvo V70 · 2011 · 254 000 km · Diesel · Manuaali · Musta"
    assert d["vehicle"]["km"] == 254000
    assert by[3900].title == "Volvo V70"          # the matching title itself is untouched


def test_markdown_split_cars_get_facts_from_their_row():
    class Site:
        key, lane, vehicle = "nettiauto", "used", True
    o = Offer(url="https://www.nettiauto.com/volvo/v70/16000001", source="nettiauto.com", title="Volvo V70",
              price=2750.0, currency="EUR", price_eur=2750.0, condition="used")
    o.raw["vehicle"] = reader.car_facts_from_text("Volvo V70 2.4 2008 312 000 km Diesel Manuaali")
    reader.set_car_subtitle(o)
    assert o.raw["subtitle"] == "2008 · 312 000 km · Diesel · Manuaali"


def test_the_car_pick_line_names_its_facts():
    from agora.need import parse_need
    need = parse_need("volvo v70")
    offers = []
    for i, (p, y, km) in enumerate([(2750, 2008, 312000), (3900, 2011, 254000), (4500, 2012, 199000),
                                    (5200, 2013, 180000)]):
        o = Offer(url=f"https://www.nettiauto.com/volvo/v70/1600000{i}", source="nettiauto.com", title="Volvo V70",
                  price=p, currency="EUR", price_eur=p, condition="used")
        o.raw["category"] = "vehicle"
        o.raw["vehicle"] = {"year": y, "km": km, "fuel": "Diesel"}
        reader.set_car_subtitle(o)
        offers.append(o)
    v = J.judge(need, R.resolve(need, offers), history=False)
    pick = next(o for o in offers if o.url == v.best_offer_url)
    assert any(ln.startswith("the car: Volvo V70 · ") and str(pick.raw["vehicle"]["year"]) in ln for ln in v.lines)


# ------------------------------------------------------------------ 2. commercial vehicles in a car hunt

def _autoline(path: str, title: str, price: float) -> Offer:
    return Offer(url=f"https://autoline.info/-/sale/{path}", source="autoline.info", title=title, price=price,
                 currency="EUR", price_eur=price, condition="used")


def test_trucks_vans_buses_tractors_are_not_a_car_per_listing():
    from agora.need import parse_need
    need = parse_need("bright red car")
    truck = _autoline("trucks/Scania/R450--2611", "Scania R450", 39000)
    van = _autoline("vans/Mercedes-Benz/Sprinter--2611", "Mercedes-Benz Sprinter 316", 12900)
    tractor = _autoline("farm-tractors/Valtra/N174--2611", "Valtra N174", 52000)
    bus = Offer(url="https://www.nettiauto.com/x/y/16000009", source="nettiauto.com", title="Iveco Crossway linja-auto",
                price=25000, currency="EUR", price_eur=25000, condition="used")
    hilux = _autoline("cars/Toyota/Hilux-2-4--2611", "Toyota Hilux 2.4", 6000)
    rav4 = _autoline("cars/Toyota/RAV4--2611", "Toyota RAV4", 2200)
    for o, kind in ((truck, "truck"), (van, "van"), (tractor, "tractor"), (bus, "bus")):
        assert R.commercial_vehicle(need, o) == kind, o.title
        assert "not a passenger car" in (R.vehicle_mismatch(need, o) or "")
    for o in (hilux, rav4):
        assert R.commercial_vehicle(need, o) is None, o.title
    kept = {o.url for t in R.resolve(need, [truck, van, tractor, bus, hilux, rav4]) for o in t.offers}
    assert hilux.url in kept and truck.url not in kept and van.url not in kept


def test_a_van_asked_keeps_vans():
    from agora.need import parse_need
    van = _autoline("vans/Mercedes-Benz/Sprinter--2611", "Mercedes-Benz Sprinter 316", 12900)
    assert R.commercial_vehicle(parse_need("mercedes sprinter van"), van) is None


def test_car_titles_that_only_look_commercial_stay_cars():
    from agora.need import parse_need
    need = parse_need("bright red car")
    for t in ("Subaru Outback 2.5 Boxer", "VW Multivan", "Hyundai Solaris", "Ford Focus daily driver"):
        o = Offer(url="https://www.nettiauto.com/a/b/16000001", source="nettiauto.com", title=t, price=5000,
                  currency="EUR", price_eur=5000, condition="used")
        assert R.commercial_vehicle(need, o) is None, t


# ------------------------------------------------------------------ 3. gunsmith: a workshop trade

GUNSMITH = svc("gunsmith", raw="gunsmith")


def _gunsmith_offers() -> list[Offer]:
    # the live r5 stream's offers, as read
    return [page("http://www.aseseppataskinen.fi/hinnasto_met.html", "Aseseppä Timo Taskinen - Hinnasto, metsästysaseet",
                 90, "hour"),
            page("https://www.aawee.fi/en/shooting-and-firearms/asesepantyot-tunti", "Asesepäntyöt / tunti – Aawee Oy",
                 99, "hour"),
            page("https://www.aawee.fi/en/shooting-and-firearms/koneistus-optiikalle",
                 "Koneistus optiikalle pistoolin luistiin – Aawee Oy", 230),
            page("https://www.aawee.fi/en/shooting-and-firearms/aanenvaimenninkierre", "Äänenvaimenninkierre – Aawee Oy",
                 100),
            page("https://www.xxl.fi/palvelut/aseseppapalvelut/aseseppapalvelut-ja-asehuolto",
                 "Aseseppäpalvelut ja asehuolto", 100, "hour"),
            page("http://aseseppa.pro/Tyohinnasto/", "Työhinnasto - aseseppa.pro", 75, "hour"),
            page("https://www.tva-asepaja.fi/tyohinnasto", "Työhinnasto", 108, "hour"),
            page("https://www.aseteam.fi/", "Aseseppä palvelut", 60),
            page("https://www.rihlatuote.fi/hscms/asesepan-palvelut.html",
                 "Aseiden deaktivointi (varastossa olevat aseet)", 450)]


def test_gunsmith_compares_an_hourly_rate_times_a_standard_job_with_no_call_out():
    offers = _gunsmith_offers()
    _, v = run(GUNSMITH, offers)
    by = {o.title: o for o in offers}
    pick = by["Työhinnasto - aseseppa.pro"]
    assert v.best_true_cost_url == pick.url, v.headline
    assert pick.true_cost.total_eur == 75 and pick.true_cost.extras_eur == 0
    assert "standard workshop job" in pick.true_cost.receipt[0][0]
    for o in offers:
        if o.true_cost is not None:
            assert not any("call-out" in lbl for lbl, _ in o.true_cost.receipt), o.title
    # specific jobs are listed apart as 'other prices', never ranked
    for t in ("Äänenvaimenninkierre – Aawee Oy", "Aseiden deaktivointi (varastossa olevat aseet)",
              "Koneistus optiikalle pistoolin luistiin – Aawee Oy"):
        assert by[t].true_cost is None, t
    jobs = next(ln for ln in v.lines if ln.startswith("other prices (specific jobs"))
    assert "Äänenvaimenninkierre" in jobs and "deaktivointi" in jobs
    # the unexplained flat '€60 services' is a starting price, shown with a note, ranked after
    flat = by["Aseseppä palvelut"]
    assert flat.raw.get("starting_price") and flat.true_cost is not None
    assert flat.true_cost.receipt[0][0].startswith("from €60")
    assert any(f.startswith("starting price") for f in flat.flags)
    assert any("starting price" in ln and "aseteam.fi" in ln for ln in v.lines)


def test_gunsmith_line_kinds():
    assert R.is_workshop_trade(GUNSMITH) and not R.is_open_trade(GUNSMITH)
    assert R.generic_trade_line(GUNSMITH, "Aseseppä palvelut", "aseteam.fi")
    assert R.generic_trade_line(GUNSMITH, "Aseseppä Timo Taskinen", "aseseppataskinen.fi", "Timo Taskinen")
    assert not R.generic_trade_line(GUNSMITH, "Äänenvaimenninkierre – Aawee Oy", "aawee.fi")
    assert R.service_line_kind(GUNSMITH, "Aseiden deaktivointi", "job") == "task"
    assert R.service_line_kind(GUNSMITH, "Asesepäntyöt / tunti", "hour") == "main"


# ------------------------------------------------------------------ 4. wedding packages by coverage

WEDDING = svc("wedding photographer", raw="wedding photographer helsinki")


def test_package_coverage_is_read_from_the_line():
    pc = J.package_coverage
    assert pc("Koko päivän dokumentaarinen hääkuvaus", 6) == ("full_day", 6.0)
    assert pc("Hääpaketti 8 h") == ("full_day", 8.0)
    assert pc("Regular Wedding Package, 9 hours of photography")[0] == "full_day"
    assert pc("Lyhyt hääpäivä") == ("part_day", None)
    assert pc("Hääkuvaus 4 tuntia") == ("part_day", 4.0)
    assert pc("Vihkiminen ja häämuotokuvat") == ("ceremony", None)
    assert pc("Hääpotretit & vihkimisen kuvaus", 2) == ("ceremony", 2.0)
    assert pc("Elopements")[0] == "ceremony"
    assert pc("Wedding portraits") == ("portraits", None)
    assert pc("Hääkuvaus") == (None, None)


def test_a_photographers_page_offers_its_most_complete_package():
    # live r5: artomarkkanen.fi's offer was 'Vihkiminen ja häämuotokuvat' €900 over its 'Koko päivän' €1,800
    url = "https://www.artomarkkanen.fi/haakuvaus-hinnasto/"
    lines = [page(url, "Koko päivän dokumentaarinen hääkuvaus", 1800, raw={"min_hours": 6}),
             page(url, "Koko päivän dokumentaarinen hääkuvaus", 2400, raw={"min_hours": 6}),
             page(url, "Vihkiminen ja häämuotokuvat", 900)]
    pick = reader.best_service_offer(lines, WEDDING)
    assert pick.price == 1800
    assert any(x["price_eur"] == 900 for x in pick.raw["other_prices"])


def test_short_packages_never_win_against_full_day_ones():
    offers = [page("https://studiohappymoment.fi/hinnasto", "Hääpotretit & vihkimisen kuvaus", 780,
                   raw={"min_hours": 2}),
              page("https://tuomasmakela.eu/hinnasto", "Potretit & vihki", 700),
              page("https://susannanordvall.com/pricing", "Wedding photography, full day", 1500),
              page("https://artomarkkanen.fi/hinnasto", "Koko päivän dokumentaarinen hääkuvaus", 1800),
              page("https://iidahakala.com/pricing", "Regular Wedding Package 9 hours", 2960),
              page("https://anitavartiainen.com/pricing", "Documentary wedding photography 8h", 2650),
              page("https://tuomasmakela2.eu/hinnasto", "Lyhyt hääpäivä", 2099)]
    _, v = run(WEDDING, offers)
    full = offers[2]
    assert v.best_true_cost_url == full.url, v.headline
    assert not any("x the" in f and "median" in f for f in full.flags), full.flags     # was '2.7x median'
    for o in offers[:2]:
        assert o.raw.get("partial_job") and any("ranked after full day" in f for f in o.flags), o.title
    cov = next(ln for ln in v.lines if ln.startswith("typical by coverage: "))
    assert "full day €" in cov and "ceremony / short €700" in cov
    assert offers[4].raw["per_covered_hour"] == round(2960 / 9, 2)
    assert any("per covered hour" in b for b in [offers[4].true_cost.basis])
    band = v.price_band or {}
    assert "full day" in band.get("what", "")


def test_unknown_coverage_priced_like_a_short_package_ranks_after_full_days():
    offers = [page("https://a.fi/h", "Hääkuvaus", 550),
              page("https://b.fi/h", "Koko päivän hääkuvaus", 1500),
              page("https://c.fi/h", "Hääkuvaus 8 h", 1800),
              page("https://d.fi/h", "Hääkuvaus 10 h", 2200)]
    _, v = run(WEDDING, offers)
    assert v.best_true_cost_url == offers[1].url
    assert offers[0].raw.get("partial_job")


# ------------------------------------------------------------------ 5. one place on two aggregators

def _lunch(url: str, price: float, seller: str) -> Offer:
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=f"Lunch – {seller}", price=price,
                 currency="EUR", price_eur=price, condition="service", unit="person", seller=seller,
                 location="Helsinki")


def test_the_same_restaurant_on_two_aggregators_is_one_offer_at_the_lower_price():
    a = _lunch("https://lunchmenu.fi/en/lunch-lists/helsinki/unicafe-kaivopiha", 9.8, "Unicafe Kaivopiha")
    b = _lunch("https://www.luncher.fi/helsinki/#unicafe-kaivopiha", 8.7, "UniCafe Kaivopiha")
    c = _lunch("https://www.lounasmenu.fi/keskusta/#unicafe-kaivopiha", 8.7, "UniCafe Kaivopiha")
    other = _lunch("https://www.luncher.fi/helsinki/#cafe-x", 11.5, "Cafe Xenia")
    out = J._dedupe_service([a, b, c, other])
    assert len(out) == 2 and b in out and other in out
    assert {x["source"] for x in b.raw["also_at"]} == {"lunchmenu.fi", "lounasmenu.fi"}
    assert b.raw["merged_sources"] == ["lounasmenu.fi", "luncher.fi", "lunchmenu.fi"]
    assert J.also_at_note(b) == "same place also listed at lunchmenu.fi for €9.80: the lower price shown"


def test_one_chain_name_in_two_towns_is_two_places():
    a = _lunch("https://www.luncher.fi/helsinki/#fazer", 11.0, "Fazer Food & Co")
    b = _lunch("https://lunchmenu.fi/tampere/fazer", 10.0, "Fazer Food & Co")
    b.location = "Tampere"
    assert len(J._dedupe_service([a, b])) == 2


def test_merged_provider_note_reaches_the_flags_and_verdict():
    n = svc("home cleaning", raw="home cleaning helsinki")
    a = page("https://www.trustoo.nl/x/siivous-oy", "Kotisiivous", 39, "hour", seller="Siivous Kiilto Oy",
             location="Helsinki")
    b = page("https://www.werkspot.nl/y/siivous-kiilto", "Kotisiivous", 35, "hour", seller="Siivous Kiilto Oy",
             location="Helsinki")
    c = page("https://clean1.fi/hinnat", "Kotisiivous", 45, "hour")
    d = page("https://clean2.fi/hinnat", "Kotisiivous", 48, "hour")
    _, v = run(n, [a, b, c, d])
    assert v.best_true_cost_url == b.url
    assert any(f.startswith("same place also listed at trustoo.nl for €39") for f in b.flags)
    assert any("same place also listed at trustoo.nl" in ln for ln in v.lines)


# ------------------------------------------------------------------ 6. the hunt budget covers the whole hunt

def test_finish_reserve_grows_with_offers_and_stays_a_share_of_the_budget():
    assert hunt.finish_reserve(0, 25) == pytest.approx(1.0)
    assert hunt.finish_reserve(2000, 25) == pytest.approx(6.0)
    assert hunt.finish_reserve(2000, 0.6) == pytest.approx(0.15)


def test_no_new_result_pages_near_the_hunt_deadline(monkeypatch):
    # live r5 'winter jacket women': big marketplace result pages ran the hunt to 35 s on a 25 s budget
    fetched: list[str] = []

    async def fake_fetch(url):
        fetched.append(url)
        return 200, "<html></html>"

    class Site:
        key, itemlist, lane = "tori", True, "used"
    monkeypatch.setattr(reader, "fetch_html", fake_fetch)
    monkeypatch.setattr(reader, "free_page_cap", lambda url: 8)
    from agora import marketplaces
    monkeypatch.setattr(marketplaces, "page_url", lambda site, url, k: f"{url}&page={k}")
    monkeypatch.setattr(marketplaces, "market_total", lambda html: None)
    first = [Offer(url=f"https://www.tori.fi/i/{i}", source="tori.fi", title="naisten talvitakki", price=20,
                   currency="EUR", price_eur=20, condition="used") for i in range(50)]
    need = Need(raw="winter jacket women", thing="winter jacket women")

    async def go(end):
        token = reader.HUNT_DEADLINE.set(lambda: end)
        try:
            return await reader.more_itemlist_pages("https://www.tori.fi/s?q=x", Site(), need, None, first, "")
        finally:
            reader.HUNT_DEADLINE.reset(token)

    out, pages = asyncio.run(go(time.monotonic() + 1.0))        # 1 s left: no page 2 is started
    assert out == [] and pages == 1 and fetched == []


def test_one_slow_page_parse_is_dropped_not_waited_for(monkeypatch):
    monkeypatch.setattr(reader, "PAGE_PARSE_CAP_S", 0.2)

    def slow():
        time.sleep(0.6)
        return [1]
    t = time.monotonic()
    assert asyncio.run(reader._parse_capped(slow)) is None
    assert time.monotonic() - t < 0.55
