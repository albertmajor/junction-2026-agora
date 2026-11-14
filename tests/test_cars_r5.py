"""Cars (eval r1-r4 'volvo v70' / 'bright red car', QUALITY_REPORT 'Still weak: Cars'): vehicle list pages are read
for free and split into one offer per car (nettiauto's ItemList of Car items, AutoScout24's Next.js listings), an
aggregator's price range (mobile.de / autoscout24 AggregateOffer) is never one car, dealer list pages are used-car
list pages, and an asked colour is a per-listing boost (never a filter). Pages saved 14 Nov in tests/fixtures/cars/
(trimmed to their JSON-LD / __NEXT_DATA__)."""
from __future__ import annotations

import asyncio
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, marketplaces, reader
from agora.models import Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures" / "cars"
VOLVO = Need(raw="volvo v70", thing="volvo v70")
RED_CAR = Need(raw="bright red car", thing="car", must_have=["bright red"])


def page(name: str) -> str:
    return (FIX / name).read_text()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setenv("AGORA_DIRECT", "1")          # the cars sites' own pages (agora.marketplaces)
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def serve(html: str, status: int = 200) -> list[str]:
    seen: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(str(r.url))
        return httpx.Response(status, text=html, headers={"content-type": "text/html; charset=utf-8"})
    reader._transport = httpx.MockTransport(handler)
    return seen


def no_paid_reads(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def product(url, **kw):
        calls.append(("product", url))
        return None

    async def extract(url, schema, instr="", **kw):
        calls.append(("extract", url))
        return None

    async def scrape(url, country, max_age_ms=None):
        calls.append(("markdown", url))
        return "", ""
    monkeypatch.setattr(cd, "product", product)
    monkeypatch.setattr(cd, "extract", extract)
    monkeypatch.setattr(reader, "scrape_markdown", scrape)
    return calls


def run(url: str, need: Need, paid: bool = False, lane: str | None = "used"):
    return asyncio.run(reader.read_with_reason(url, need, lane=lane, paid=paid, expand_lists=True))


# ------------------------------------------------------------------ nettiauto: a free read of every car on the page

def test_nettiauto_model_page_is_read_free_one_offer_per_car(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("nettiauto_volvo_v70.html"))
    url = "https://www.nettiauto.com/volvo/v70?sortCol=dateCreated&ord=DESC"
    offers, how = run(url, VOLVO)
    assert how == "jsonld" and not calls                # plain fetch + JSON-LD: no token (was a paid markdown read)
    assert len(offers) >= 30
    assert all(o.url.startswith("https://www.nettiauto.com/volvo/v70/") for o in offers)
    assert all(o.condition == "used" and o.raw.get("category") == "vehicle" for o in offers)
    first = next(o for o in offers if o.url.endswith("/16073096"))
    assert first.price_eur == 8990 and first.raw["vehicle"]["km"] == 179000
    assert first.raw["vehicle"]["year"] == 2011 and first.raw["colour"] == "black"
    assert "179" in first.raw["row_text"] and "km" in first.raw["row_text"]
    assert first.raw["market"]["total"] == 665          # 'offerCount': the whole V70 market on nettiauto


def test_nettiauto_paid_phase_still_free_when_fetch_works(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("nettiauto_volvo_v70.html"))
    offers, how = run("https://www.nettiauto.com/volvo/v70", VOLVO, paid=True)
    assert how == "jsonld" and len(offers) >= 30 and not calls


def test_nettiauto_blocked_fetch_falls_back_to_the_paid_split(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve("<html>Access denied</html>", status=403)
    got, why = run("https://www.nettiauto.com/volvo/v70", VOLVO, paid=True)
    assert ("markdown", "https://www.nettiauto.com/volvo/v70") in calls
    assert not got


def test_free_phase_does_not_spend_when_fetch_fails(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve("", status=500)
    got, why = run("https://www.nettiauto.com/volvo/v70", VOLVO, paid=False)
    assert not got and "list read" in why and not calls


# ------------------------------------------------------------------ colour: a boost per listing, never a filter

def test_bright_red_car_puts_red_cars_first_and_keeps_the_rest(monkeypatch):
    no_paid_reads(monkeypatch)
    serve(page("nettiauto_vaihtoautot.html"))
    offers, how = run("https://www.nettiauto.com/vaihtoautot?sortCol=dateCreated&ord=DESC", RED_CAR)
    assert how == "jsonld" and len(offers) >= 30         # every car kept: colour is a preference
    red = [o for o in offers if o.raw.get("colour_match") is True]
    assert len(red) == 8 and all(o.raw["colour"] == "red" for o in red)
    assert offers[:8] == red                              # the asked colour first
    assert offers[0].raw["market"]["total"] == 76775      # the site-wide list's own count (numberOfItems)
    assert any(o.raw.get("colour_match") is False for o in offers)


@pytest.mark.parametrize("text,colour", [
    ("Punainen", "red"), ("Tummanpunainen metallic", "red"), ("Vaaleanpunainen", "pink"), ("Musta", "black"),
    ("Volvo V70 D4 Summum", None), ("VW Golf 1.4 TSI rot", "red"), ("Hopea", "silver"), ("Harmaa", "grey")])
def test_colour_of(text, colour):
    assert marketplaces.colour_of(text) == colour


def test_asked_colours():
    assert marketplaces.asked_colours("car", "bright red") == {"red"}
    assert marketplaces.asked_colours("volvo v70") == set()
    assert marketplaces.asked_colours("punainen auto") == {"red"}


def test_colour_on_a_single_car_page_title():
    o = Offer(url="https://www.kamux.fi/cars/x/123456", source="kamux.fi", title="Toyota Yaris punainen 2015",
              price=8000, currency="EUR", price_eur=8000, condition="used")
    reader.mark_colour(o, RED_CAR)
    assert o.raw["colour"] == "red" and o.raw["colour_match"] is True
    o2 = Offer(url="https://www.kamux.fi/cars/x/123457", source="kamux.fi", title="Toyota Yaris 2015",
               price=8000, currency="EUR", price_eur=8000, condition="used")
    reader.mark_colour(o2, RED_CAR)
    assert "colour_match" not in o2.raw                  # unknown colour: stays, unmarked
    reader.mark_colour(o, VOLVO)                          # no colour asked: no verdict on it
    assert "colour_match" not in o.raw or o.raw["colour_match"] is True


# ------------------------------------------------------------------ AutoScout24: its Next.js listings, free

def test_autoscout24_model_page_split_free(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("autoscout24_de_volvo_v70.html"))
    offers, how = run("https://www.autoscout24.de/lst/volvo/v70?atype=C", VOLVO)
    assert how == "jsonld" and not calls
    assert len(offers) == 20                              # not the AggregateOffer 'Volvo V70 €3,119'
    assert all("/angebote/" in o.url and o.raw.get("category") == "vehicle" for o in offers)
    o = next(o for o in offers if o.price_eur == 10000)
    assert o.condition == "used" and o.location and "DE" in o.location
    assert o.raw["vehicle"]["km"] == 129345 and o.raw["vehicle"]["year"] == 2016
    assert o.raw["colour"] == "black"                     # '-diesel-schwarz-cat_' in its URL
    assert o.raw["market"]["total"] == 223


def test_autoscout24_com_found_by_search_is_split_too(monkeypatch):
    no_paid_reads(monkeypatch)
    serve(page("autoscout24_de_volvo_v70.html").replace("autoscout24.de", "autoscout24.com"))
    offers, how = run("https://www.autoscout24.com/lst/volvo/v70?atype=C", VOLVO)
    assert how == "jsonld" and len(offers) == 20


def test_plain_product_itemlist_on_a_cars_page_is_every_listing(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("autoline_cars.html"))
    offers, how = run("https://autoline.info/-/cars--c1169", RED_CAR)
    assert how == "jsonld" and not calls and len(offers) == 6     # r4: 'Toyota Hilux 2.4' alone
    assert all("/-/sale/cars/" in o.url for o in offers)
    assert all(o.raw.get("category") != "vehicle" for o in offers)  # Products, not Cars: the price floor still applies


# ------------------------------------------------------------------ mobile.de: a price range is not a car

def test_mobile_de_aggregate_is_not_one_car(monkeypatch):
    no_paid_reads(monkeypatch)
    serve(page("mobile_de_volvo_v70.html"))
    got, why = run("https://www.mobile.de/en/car/volvo/v70", VOLVO)
    assert not got                                        # r4: 'Volvo V70 €989' (the cheapest of 740) as one offer
    assert "list" in why


def test_mobile_de_aggregate_gets_a_list_read_when_paid(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("mobile_de_volvo_v70.html"))
    got, why = run("https://www.mobile.de/en/car/volvo/v70", VOLVO, paid=True)
    assert not got and ("extract", "https://www.mobile.de/en/car/volvo/v70") in calls
    assert not any(c[0] == "product" for c in calls)


# ------------------------------------------------------------------ dealer / aggregator list pages

@pytest.mark.parametrize("url,is_list", [
    ("https://www.auto1.fi/haku/volvo%20v70", True),
    ("https://www.kamux.fi/cars/volvo/v/v70", True),
    ("https://www.k-auto.fi/autot/volvo/v70/", True),
    ("https://www.rintajouppi.fi/vaihtoautot/volvo/v70/", True),
    ("https://www.rinta-jouppi.com/osta/vaihtoautot/volvo/v70/", True),
    ("https://www.autouncle.fi/fi/kaytetyt-autot/Volvo/V70", True),
    ("https://www.autotie.fi/vaihtoautot/volvo/v70", True),
    ("https://www.mobile.de/en/car/volvo/v70", True),
    ("https://www.autoscout24.com/lst/volvo/v70?atype=C", True),
    ("https://www.rinta-jouppi.com/ajoneuvohaku/volvo/v70/458836/", False),     # one car
    ("https://www.auto-suni.fi/vaihtoauto/volvo-v70-ila-346/", False),          # one car
    ("https://www.auto1.fi/volvo/v70/221741", False),
    ("https://www.autouncle.fi/fi/d/7761258-kaytetty-2015-volvo-v70-momentum-181-hp", False),
    ("https://www.taloustaito.fi/vapaalla/auton-lisavarien-hinnoissa-vaihtelua/", False),
    ("https://www.rintajouppi.fi/used-and-second-hand-cars/", True),
    ("https://www.carandclassic.com/list/102/v70/", True),
    ("https://www.tori.fi/recommerce/forsale/search?q=punainen+auto", False),   # goods search, not a cars list
    ("https://www.if.fi/car-insurance/", False),
    ("https://www.k-auto.fi/myy-autosi/", False),
    ("https://oma.almaajo.fi/auton-hinta-arvio", False),
])
def test_car_list_url(url, is_list):
    assert marketplaces.car_list_url(url) is is_list


def test_dealer_list_page_is_a_list_read_in_any_lane():
    assert reader.wants_list_read("https://www.kamux.fi/cars/volvo/v/v70", VOLVO, "new")
    assert not reader.wants_list_read("https://www.kamux.fi/cars/volvo/v/v70",
                                      Need(raw="ps5", thing="ps5"), "new")


def test_dealer_list_listings_are_used_cars(monkeypatch):
    serve("<html><body>Volvo V70 vaihtoautot</body></html>")

    async def extract(url, schema, instr="", **kw):
        return {"listings": [
            {"title": "Volvo V70 D4 Summum punainen", "price": 12990, "currency": "EUR",
             "url": "https://www.kamux.fi/cars/volvo-v70-d4-summum/1234567", "condition": "new"},
            {"title": "Volvo V70 2,4D Momentum", "price": 5990, "currency": "EUR",
             "url": "https://www.kamux.fi/cars/volvo-v70-2-4d/1234568", "condition": "unknown"}]}
    monkeypatch.setattr(cd, "extract", extract)
    offers, how = run("https://www.kamux.fi/cars/volvo/v/v70", VOLVO, paid=True, lane="new")
    assert how == "contextdev_json" and len(offers) == 2
    assert all(o.condition == "used" and o.raw.get("car_list_page") for o in offers)


# ------------------------------------------------------------------ the plan and the market count

def test_market_total_reads_car_site_counts():
    assert marketplaces.market_total(page("nettiauto_volvo_v70.html")) == (665, False)
    assert marketplaces.market_total(page("autoscout24_de_volvo_v70.html"))[0] == 223


def test_autoscout24_sites_read_their_list_free_first():
    assert marketplaces.SITES["autoscout24_de"].ldlist and marketplaces.SITES["nettiauto"].ldlist
    assert not marketplaces.SITES["mobile_de"].ldlist           # suchen.mobile.de: no listings in its HTML


def test_dead_tori_cars_category_is_never_planned():
    plan = marketplaces.direct_pages("volvo v70", "used", "fi", None, 8)
    assert plan and plan[0].site.key == "nettiauto"
    assert all(d.site.key != "tori_autot" for d in plan)
