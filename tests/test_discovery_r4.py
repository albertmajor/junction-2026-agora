"""Discovery fixer, eval round 4: regressions from judges reading real live streams (14 Nov, eval/r4).

Each test names the query of the live stream it comes from. URLs and titles are copied from those streams (and
from nettiauto pages checked by hand: ?sortCol=dateCreated&ord=DESC is newest first, ?page=N pages); everything
runs offline (rules, the tree, fake discover / read for the hunt-level checks).
"""
from __future__ import annotations

import asyncio

import pytest

from agora import discover as dv
from agora import hunt as hunt_mod
from agora import intent as I
from agora import marketplaces as M
from agora import need as N
from agora.models import Event, Need, Offer

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGORA_HOME_CITY", raising=False)
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setenv("AGORA_DIRECT", "1")


def parsed(q: str) -> Need:
    n = N.parse_need_rules(q)
    N.categorize(n)
    I.refine(n)
    return n


def used_directs(n: Need, tokens: float = 10) -> list:
    return dv.plan_direct(n, dv.lanes_for(n), tokens, 2).get("used", [])


# ------------------------------------------------------------------ 'volvo v70' (market 0/32, 1 page of 664 cars)

def test_volvo_v70_reads_several_newest_first_pages_of_the_model_list():
    d = [x for x in used_directs(parsed("volvo v70"), tokens=7) if x.site.key == "nettiauto"]
    urls = [x.url for x in d]
    # was one page (https://www.nettiauto.com/volvo/v70, cheapest first): 32 of 664 V70s
    assert urls[0] == "https://www.nettiauto.com/volvo/v70?sortCol=dateCreated&ord=DESC"
    assert urls[1] == "https://www.nettiauto.com/volvo/v70?sortCol=dateCreated&ord=DESC&page=2"
    assert [x.page for x in d] == [1, 2, 3]
    for u in urls:
        assert M.site_for(u).key == "nettiauto"          # each page is still split as nettiauto's list
        assert dv.is_list_page(u)


def test_volvo_v70_home_pages_before_car_sites_abroad_when_tokens_are_short():
    keys = [(x.site.key, x.page) for x in used_directs(parsed("volvo v70"), tokens=7)]
    assert ("nettiauto", 2) in keys and not any(k.startswith(("autoscout24", "mobile")) for k, _ in keys)
    # a low bucket: page 1 only, never a page the hunt cannot pay for
    assert [p for k, p in [(x.site.key, x.page) for x in used_directs(parsed("volvo v70"), tokens=4)]
            if k == "nettiauto"] == [1]


def test_volvo_v70_goods_search_and_one_model_year_list():
    # tori's goods search for 'volvo v70': 410 rows of rims, studded tyres and seats
    tori = "https://www.tori.fi/recommerce/forsale/search?q=volvo+v70"
    assert dv.car_page_skip(tori, "Volvo v70 | Myydään | Tori", home_cars=True)
    assert dv.car_page_skip(tori, "Volvo v70 | Myydään | Tori", home_cars=False) is None   # no cars site: read
    # each listing of tori's cars section is still read on its own
    assert dv.car_page_skip("https://www.tori.fi/mobility/item/12345678", "Volvo V70 2.4", home_cars=True) is None
    # autotalli's 2007-only list (12 cars) was read and its whole V70 list skipped as 'already 1 search page'
    assert dv.car_list_base("https://www.autotalli.com/vaihtoautot/listaa/volvo/v70/vuosimalli_min/2007/"
                            "vuosimalli_max/2007") == "https://www.autotalli.com/vaihtoautot/listaa/volvo/v70"
    assert dv.car_list_base("https://www.kamux.fi/cars/volvo/v/v70") == "https://www.kamux.fi/cars/volvo/v/v70"


# ------------------------------------------------------------------ 'bright red car' (30 of 31 cars were €51-€300 scrap)

def test_bright_red_car_browses_newest_first_not_cheapest_first():
    d = [x for x in used_directs(parsed("bright red car"), tokens=7) if x.site.key == "nettiauto"]
    # was https://www.nettiauto.com/vaihtoautot: default order 'Halvin ensin' (cheapest first)
    assert d[0].url == "https://www.nettiauto.com/vaihtoautot?sortCol=dateCreated&ord=DESC"
    assert len(d) >= 2 and all("sortCol=dateCreated" in x.url for x in d)
    assert not any(x.site.key == "tori" for x in used_directs(parsed("bright red car")))


@pytest.mark.parametrize("url", [
    "https://www.autouncle.fi/", "https://www.nettiauto.com/en", "https://www.mobile.de/en",
    "https://www.autoscout24.com/", "https://autot.tori.fi/", "https://oma.almaajo.fi/auton-hinta-arvio",
    "https://www.auto1.fi/hintaseuranta", "https://www.autotalli.com/uudet-autot/uusi-haku",
    "https://www.tori.fi/recommerce/forsale/search?page=10&q=punainen+auto"])
def test_bright_red_car_front_pages_tools_and_toy_searches_are_not_read(url):
    assert dv.car_page_skip(url, "", home_cars=True)


@pytest.mark.parametrize("url", [
    "https://www.auto1.fi/haku/punainen+auto", "https://www.autouncle.fi/fi/kaytetyt-autot",
    "https://www.autouncle.fi/fi/d/7818147-kaytetty-2015-vw-caddy-75-hp", "https://carvago.com/cars"])
def test_bright_red_car_lists_and_cars_are_still_read(url):
    assert dv.car_page_skip(url, "", home_cars=True) is None


def test_car_discover_skips_goods_search_found_by_web_search(monkeypatch):
    n = parsed("volvo v70")

    async def fake_query(lane, q, c, service=False, inc=None):
        return lane, q, [
            {"url": "https://www.tori.fi/recommerce/forsale/search?q=volvo+v70", "title": "Volvo v70 | Myydään | Tori"},
            {"url": "https://www.autotalli.com/vaihtoautot/listaa/volvo/v70/vuosimalli_min/2007/vuosimalli_max/2007",
             "title": "Volvo V70 vaihtoautot | Autotalli.com"},
            {"url": "https://www.autouncle.fi/", "title": "AutoUncle - Hintavertailu"},
            {"url": "https://www.kamux.fi/cars/volvo/v/v70", "title": "Volvo V70 vaihtoautot | Kamux"}]
    monkeypatch.setattr(dv, "_run_query", fake_query)

    async def go():
        return [e async for e in dv.discover(n, settle_s=0.05, tokens=7)]
    events = asyncio.run(go())
    srcs = [e.data["url"] for e in events if e.type == "source"]
    skips = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    assert "https://www.tori.fi/recommerce/forsale/search?q=volvo+v70" in skips
    assert "https://www.autouncle.fi/" in skips
    assert "https://www.autotalli.com/vaihtoautot/listaa/volvo/v70" in srcs
    assert "https://www.kamux.fi/cars/volvo/v/v70" in srcs
    assert sum(1 for u in srcs if "nettiauto.com" in u) >= 2


# ------------------------------------------------------------------ 'glazenwasser utrecht' (every result a house cleaner)

@pytest.mark.parametrize("q,local", [("glazenwasser utrecht", "glazenwasser"), ("fensterputzer berlin", "Fensterputzer"),
                                     ("ikkunanpesu helsinki", "ikkunanpesu"), ("window cleaner helsinki", "ikkunanpesu")])
def test_window_cleaner_is_hunted_as_window_cleaning(q, local):
    n = N.parse_need(q)
    N.categorize(n)
    assert n.kind == "service" and n.thing == "window cleaning"         # was 'cleaning'
    qs = [x[0] for x in dv.lean_plan(n, "service", 10)]
    assert qs[0].startswith("window cleaning")
    assert any(local in x for x in qs[1:]), qs
    assert not any(w in " ".join(qs).lower() for w in ("schoonmaker", "reinigungskraft", "kotisiivous"))
    assert not any("per uur" in x or "pro stunde" in x for x in qs)   # window cleaners price per job / window


def test_house_cleaning_keeps_its_trade_words():
    n = N.parse_need("home cleaning tilburg 24m2")
    N.categorize(n)
    qs = [x[0] for x in dv.lean_plan(n, "service", 10)]
    assert any("schoonmaker Tilburg prijs per uur" == x for x in qs), qs


def test_cost_of_living_stats_are_no_provider():
    n = N.parse_need("glazenwasser utrecht")
    why = dv.service_skip(n, "https://www.expatistan.com/price/cleaning-help/utrecht",
                          "Price of Hourly rate for cleaning help in Utrecht - Expatistan")
    assert why and "statistic" in why
    assert dv.service_skip(n, "https://www.numbeo.com/cost-of-living/in/Utrecht", "Cost of Living in Utrecht")


# ------------------------------------------------------------------ 'plumber berlin' (a review directory priced as a plumber)

@pytest.mark.parametrize("url,title", [
    ("https://www.kennstdueinen.de/branche-klempner-356.html", "Klempner in der Nähe - Bewertungen, Preise & Kosten"),
    ("https://www.my-hammer.de/sanitaer/klempner-berufe/berlin", "Klempner in Berlin – Jetzt Fachbetrieb finden! | MyHammer"),
    ("https://fragbabsi.de/sanitaer", "Sanitär & Heizung finden – Kosten, Leistungen & Ablauf"),
    ("https://trustlocal.de/berlin/berlin/sanitar/", "Top 10 Sanitärbetriebe in Berlin | Preise & Bewertungen")])
def test_plumber_directories_are_directories(url, title):
    assert dv.is_service_directory(url, title)


def test_plumber_berlin_lane_searches_the_real_my_hammer_domain():
    n = N.parse_need("plumber berlin")
    N.categorize(n)
    sites = [x for x in dv.lean_plan(n, "service", 10) if len(x) > 2]
    assert sites and "my-hammer.de" in sites[0][2]


# ------------------------------------------------------------------ 'winter jacket women' (category pages as offers)

CATEGORY_OFFERS = [
    ("https://www.emp.fi/naisten-vaatteet/takit/talvitakit/", "Talvitakit naiset | Suuri valikoima - osta halvalla | EMP",
     "Talvitakki: / Gothicana by EMP - Talvitakki useilla taskuilla", 95.19),
    ("https://fyndiq.fi/muoti/naisten-vaatteet/ulkovaatteet/takit/talvitakit/",
     "Naisten talvitakki - löydä edulliset tarjoukset täältä - Fyndiq",
     "Naisten hupullinen tekoturkistakki, lyhyet puhvihihat", 93.0),
    ("https://www.cellbes.fi/naiset/jakut-takit/talvitakit", "Osta naisten talvitakit netistä | Cellbes.fi",
     "Lämmin takki pörröisellä toppauksella", 69.95)]
PRODUCT_OFFERS = [
    ("https://www.nettiapteekki.fi/products/laq-lahjapakkaus-naisille-joulu-kaksi-tuotetta-medifon",
     "LAQ Jouluinen lahjapakkaus naisille – Nettiapteekki.fi", "LAQ Jouluinen lahjapakkaus naisille", 18.0),
    ("https://www.oloapteekki.fi/laq-lahjapakkaus-naisille-joulu-kaksi-tuotetta-1-kpl",
     "LaQ Lahjapakkaus naisille Joulu | Olo-apteekki", "LaQ Lahjapakkaus naisille Joulu", 19.9),
    ("https://www.halti.fi/products/naisten-lumi-talvitakki", "Halti Lumi naisten talvitakki", "Lumi naisten talvitakki", 199.0)]


@pytest.mark.parametrize("url,page_title,title,price", CATEGORY_OFFERS)
def test_one_offer_off_a_category_page_is_flagged(url, page_title, title, price):
    assert dv.category_page_offer(url, page_title, url, title)


@pytest.mark.parametrize("url,page_title,title,price", PRODUCT_OFFERS)
def test_a_product_page_offer_is_kept(url, page_title, title, price):
    assert dv.category_page_offer(url, page_title, url, title) is None


def _hunt(sources: list[tuple[str, str]], offers: dict[str, Offer], text: str = "winter jacket women", **kw):
    async def disc(need):
        yield Event("lane", {"lane": "new", "queries": []})
        for url, title in sources:
            yield Event("source", {"url": url, "lane": "new", "title": title})

    async def read(url, need):
        return offers.get(url)

    def parse(t: str) -> Need:
        return Need(raw=t, thing=t)

    async def go():
        k = fk.kwargs(discover=disc, read=read, parse_need=parse)
        return [e async for e in hunt_mod.hunt(text, **k, siblings=False, longtail=False, lookalikes=False,
                                               budget_s=False, check_pick=False, **kw)]
    return asyncio.run(go())


def test_hunt_never_streams_a_category_page_as_one_offer():
    rows = CATEGORY_OFFERS + PRODUCT_OFFERS[2:]
    offers = {u: Offer(url=u, source=u.split("/")[2].removeprefix("www."), title=t, price=p, currency="EUR",
                       price_eur=p, condition="new", read_via="jsonld") for u, _pt, t, p in rows}
    events = _hunt([(u, pt) for u, pt, _t, _p in rows], offers)
    streamed = {e.data["offer"]["url"] for e in events if e.type == "offer"}
    skipped = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    assert streamed == {PRODUCT_OFFERS[2][0]}
    for u, *_ in CATEGORY_OFFERS:
        assert "category page" in skipped[u]


def test_big_home_retailer_reads_first():
    n = N.parse_need("winter jacket women")
    assert dv.home_retailer("https://www.zalando.fi/naisten-takit-talvitakit/", n)
    assert dv.home_retailer("https://www.stockmann.com/muoti/naiset/vaatteet/takit/talvitakit", n)
    assert not dv.home_retailer("https://en.zalando.de/winter-jackets-sale/", n)         # abroad
    assert not dv.home_retailer("https://www.landsend.com/shop/womens-winter-coats", n)


def test_lane_gate_serves_a_boosted_page_before_earlier_small_shops():
    async def go():
        gate = hunt_mod.LaneGate(1)
        order: list[str] = []
        await gate.acquire("new", False, 2)          # one slot taken: the next ones queue

        async def take(name: str, prio: int) -> None:
            await gate.acquire("new", False, prio)
            order.append(name)
            gate.release()
        tasks = [asyncio.create_task(take("stadium.fi", 2)), asyncio.create_task(take("kappahl.com", 2))]
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(take("zalando.fi", 2 - hunt_mod.HOME_SHOP_BOOST)))
        await asyncio.sleep(0)
        gate.release()
        await asyncio.gather(*tasks)
        return order
    assert asyncio.run(go())[0] == "zalando.fi"


# ------------------------------------------------------------------ 'gift for mom' (a couple's spa day among the gifts)

GIFT_TITLES_OUT = ["Romanttinen kasvohoito ja hieronta kahdelle", "Spa day for two", "Wellness-Tag zu zweit",
                   "Sexy lingerie set"]
GIFT_TITLES_IN = ["Muki omalla kuvalla, valkoinen", "Frameo digitaalinen kuvakehys 10\"", "Kaulakoru Sydän hopea",
                  "LAQ Jouluinen lahjapakkaus naisille"]


def test_gift_for_mom_never_a_romantic_experience_for_two():
    n = Need(raw="gift for mom", thing="gift for mom")
    assert I.apply(n, "c:gift.ideas") is not None
    for t in GIFT_TITLES_OUT:
        why = I.avoid_reason(n, t)
        assert why and why.endswith("not a gift for mom"), t
    for t in GIFT_TITLES_IN:
        assert I.avoid_reason(n, t) is None, t


def test_gift_for_a_partner_may_be_romantic():
    n = Need(raw="gift for my wife", thing="gift for my wife")
    I.apply(n, "c:gift.ideas")
    assert I.avoid_reason(n, "Romanttinen illallinen kahdelle") is None


def test_hunt_skips_couples_experiences_for_mom():
    base = "https://www.elamyslahjat.fi/lahja-naiselle/lahja-aidille/"
    rows = [Offer(url=f"https://www.elamyslahjat.fi/p/{i}-x", source="elamyslahjat.fi", title=t, price=89.0,
                  currency="EUR", price_eur=89.0, condition="new", raw={"from_list_page": base})
            for i, t in enumerate(["Romanttinen kasvohoito ja hieronta kahdelle", "Teekurssi ja iltapäivätee"])]

    async def disc(need):
        yield Event("lane", {"lane": "new", "queries": []})
        yield Event("source", {"url": base, "lane": "new", "title": "Äidille | Lahjakortti | Elamyslahjat"})

    async def read(url, need):
        return rows

    def parse(t: str) -> Need:
        return Need(raw=t, thing=t)

    async def go():
        k = fk.kwargs(discover=disc, read=read, parse_need=parse)
        return [e async for e in hunt_mod.hunt("gift for mom", **k, siblings=False, longtail=False,
                                               lookalikes=False, budget_s=False, check_pick=False,
                                               intent="c:gift.ideas")]
    events = asyncio.run(go())
    titles = {e.data["offer"]["title"] for e in events if e.type == "offer"}
    assert titles == {"Teekurssi ja iltapäivätee"}
    assert any("not a gift for mom" in (e.data.get("reason") or "") for e in events if e.type == "skip")
