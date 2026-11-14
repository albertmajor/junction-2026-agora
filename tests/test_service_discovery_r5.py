"""Service-discovery fixer, round 5: the "Still weak / Service discovery" and "Audience words" items of
docs/QUALITY_REPORT.md, each turned into an offline regression test first.

URLs and titles come from the saved live streams (scratchpad eval/r2-r4: plumber-berlin, cat-yelp-gunsmith,
lunch, electrician-helsinki, home-cleaning-tilburg-24m2, glazenwasser-utrecht). Everything runs offline:
rules, the tree, and a fake search for the discover-level checks.
"""
from __future__ import annotations

import asyncio

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import hunt as hunt_mod
from agora import need as N
from agora import places
from agora import reader
from agora.models import Need


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AGORA_HOME_CITY", raising=False)
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setenv("AGORA_DIRECT", "0")


def parsed(text: str, category: str | None = None) -> Need:
    n = N.parse_need_rules(text)
    N.categorize(n, category)
    return n


def market_sites(n: Need) -> list[str]:
    return [d for x in dv.lean_plan(n, "service", tokens=10) if len(x) > 2 for d in x[2]]


def fake_search(monkeypatch, results_for):
    """results_for(query) -> (delay seconds, [results])."""
    async def search(query, n=10, highlights=False, country=None, **kw):
        delay, res = results_for(query, kw)
        if delay:
            await asyncio.sleep(delay)
        return res
    monkeypatch.setattr(cd, "search", search)
    reader._HINTS.clear()


def collect(need, **kw):
    async def run():
        return [e async for e in dv.discover(need, settle_s=0.2, **kw)]
    return asyncio.run(run())


# ------------------------------------------------------------------ service sites by trade, not by country

def test_plumber_berlin_gets_no_pet_sitting_childcare_or_tutoring_sites():
    n = parsed("plumber berlin")
    sites = set(market_sites(n))
    assert {"myhammer.de", "blauarbeit.de"} <= sites
    assert not {"rover.com", "betreut.de", "helpling.de", "care.com", "yoopies.de"} & sites
    # the registry's own categories decide for platforms the hand list does not know
    assert not dv.market_fits("rover.com", n, "de")
    es = parsed("plumber madrid")
    assert not dv.market_fits("superprof.es", es, "es")      # tutoring
    assert not dv.market_fits("treatwell.es", es, "es")      # beauty
    assert dv.market_fits("habitissimo.es", es, "es")


def test_home_cleaning_tilburg_gets_no_childcare_site():
    # eval r4 home-cleaning-tilburg-24m2 / glazenwasser-utrecht: sites [..., 'charlycares.com'] (a babysitter app)
    n = parsed("home cleaning tilburg 24m2")
    sites = set(market_sites(n))
    assert "charlycares.com" not in sites and "helpling.nl" in sites
    assert dv.market_fits("charlycares.com", parsed("babysitter amsterdam"), "nl")


def test_goods_marketplace_is_only_searched_for_household_trades():
    # eval r4 cat-yelp-gunsmith: the tori.fi search returned 'Iittala helsinki astiat' (dishes) for a gunsmith
    gun = parsed("Gunsmith", "yelp:gunsmith")
    hunt_mod.default_where(gun)
    assert not dv.market_fits("tori.fi", gun, "fi")
    assert "tori.fi" not in market_sites(gun)
    lunch = parsed("lunch helsinki")
    assert not dv.market_fits("tori.fi", lunch, "fi")
    assert dv.market_fits("tori.fi", parsed("plumber helsinki"), "fi")
    assert dv.market_fits("tori.fi", parsed("moving company helsinki"), "fi")


def test_a_goods_marketplace_page_that_does_not_name_the_job_is_skipped():
    gun = parsed("Gunsmith", "yelp:gunsmith")
    hunt_mod.default_where(gun)
    why = dv.service_skip(gun, "https://www.tori.fi/recommerce/forsale/search?q=Iittala+Helsinki+astiat",
                          "Iittala helsinki astiat | Myydään | Tori")
    assert why and "does not name" in why
    plumber = parsed("plumber helsinki")
    assert dv.service_skip(plumber, "https://www.tori.fi/recommerce/forsale/search?q=putkimies+helsinki",
                           "Putkimies Helsinki | Tori") is None


def test_electrician_helsinki_searches_no_dutch_marketplace():
    # eval r4 electrician-helsinki: sites ['tori.fi', 'urakkamaailma.fi', 'marktplaats.nl', 'remonttipalvelu.fi']
    n = parsed("electrician helsinki")
    assert "marktplaats.nl" not in dv.category_sites(n, "fi")
    assert "marktplaats.nl" not in market_sites(n)
    assert "urakkamaailma.fi" in market_sites(n)


# ------------------------------------------------------------------ category domain inheritance

def test_gunsmith_does_not_inherit_care_sites_from_its_parent():
    # eval r3/r4 cat-yelp-gunsmith: domains care.com, yoopies.de, rover.com from 'personal-services'
    info = N.category_info("yelp:gunsmith")
    doms = {d["domain"] for d in info["domains"]}
    assert not {"care.com", "yoopies.de", "rover.com"} & doms
    # a care node keeps them
    gun = parsed("Gunsmith", "yelp:gunsmith")
    assert not {"care.com", "yoopies.de", "rover.com"} & {d["domain"] for d in gun.category["domains"]}


def test_inherited_site_kept_when_it_fits_the_trade():
    # a plumbing node's own sites are its own; a trades site inherited by a trades leaf still fits
    n = parsed("plumber berlin")
    assert dv.family_fits("my-hammer.de", "trades")
    assert not dv.family_fits("care.com", "craft")
    assert dv.family_fits("unknownsite.de", "trades") is None
    assert "my-hammer.de" in dv.category_sites(n, "de") or "my-hammer.de" in market_sites(n)


# ------------------------------------------------------------------ per-domain caps prefer the asked city

LOUNAAT_EARLY = [("https://www.lounaat.info/itis", "Lounas Helsinki, Itäkeskus"),
                 ("https://www.lounaat.info/itakeskus", "Lounas Helsinki, Itäkeskus"),
                 ("https://m.lounaat.info/teak", "Lounas Helsinki, Teatterikorkeakoulu")]
LOUNAAT_LATE = [("https://www.lounaat.info/hy", "Lounas Helsinki, Yliopisto"),
                ("https://www.lounaat.info/helsinki", "Lounas Helsinki"),
                ("https://www.lounaat.info/toolo", "Lounas Töölö, Helsinki")]


def _lunch():
    from agora import intent as I
    n = N.parse_need("lunch")
    I.apply(n, "c:lunch.places")
    hunt_mod.default_where(n)
    return n


def test_lunch_reads_the_city_page_of_lounaat_before_district_pages(monkeypatch):
    # eval r3/r4 lunch: /itis and /itakeskus took lounaat.info's 2 pages; /helsinki 'already 2 pages'
    fake_search(monkeypatch, lambda q, kw: (0, [{"url": u, "title": t} for u, t in LOUNAAT_EARLY + LOUNAAT_LATE]))
    events = collect(_lunch(), tokens=10)
    src = [e.data["url"] for e in events if e.type == "source"]
    assert "https://www.lounaat.info/helsinki" in src
    # m.lounaat.info is lounaat.info: one site, one cap
    assert sum("lounaat.info" in u for u in src) <= 2


def test_lunch_city_page_arriving_late_still_gets_a_slot(monkeypatch):
    def results(q, kw):
        if kw.get("include_domains"):
            return 0.5, [{"url": u, "title": t} for u, t in LOUNAAT_LATE]     # after the first flush
        return 0, [{"url": u, "title": t} for u, t in LOUNAAT_EARLY]
    fake_search(monkeypatch, results)
    events = collect(_lunch(), tokens=10)
    src = [e.data["url"] for e in events if e.type == "source"]
    assert "https://www.lounaat.info/helsinki" in src, src
    assert "https://www.lounaat.info/hy" not in src          # the cap still holds for other district pages


def test_url_names_the_city():
    n = _lunch()
    assert dv.city_in_path(n, "https://www.lounaat.info/helsinki")
    assert dv.city_in_path(n, "https://www.lounaat.info/lounas/klubi/helsinki")
    assert not dv.city_in_path(n, "https://www.lounaat.info/itis")
    assert dv.service_fit(n, "https://www.lounaat.info/helsinki", "Lounas Helsinki") > \
        dv.service_fit(n, "https://www.lounaat.info/itis", "Lounas Helsinki, Itäkeskus")


# ------------------------------------------------------------------ budget: best local pages read first

def test_paid_reads_of_a_service_hunt_go_to_local_trade_pages_first():
    n = parsed("plumber berlin")
    local = dv.paid_priority("https://werkstueck-berlin.de/leistungen/preisliste/", n.kind, "service",
                             "Preisliste (ab 1.1.2025) - Werkstück, Berlin", "", need=n)
    abroad = dv.paid_priority("https://www.networx.com/plumbers/oh/berlin-center/pricing", n.kind, "service",
                              "Pricing - Plumbers", "", need=n)
    off_trade = dv.paid_priority("https://handymanberlin.com/pricing/", n.kind, "service",
                                 "Pricing - hmb+ - Handyman Berlin", "", need=n)
    assert local < abroad and local <= off_trade
    # without a need the old order stays
    assert dv.paid_priority("https://werkstueck-berlin.de/leistungen/preisliste/", "service", "service",
                            "Preisliste", "") == 0


def test_hunt_hands_its_need_to_paid_priority():
    import inspect
    src = inspect.getsource(hunt_mod.hunt)
    seg = src[src.index("dv.paid_priority"):][:600]
    assert "need=need" in seg


# ------------------------------------------------------------------ Berlin CT vs Berlin DE

def test_berlin_alone_is_berlin_germany():
    n = parsed("plumber berlin")
    assert n.where == "Berlin" and dv.country_of(n) == "de"


@pytest.mark.parametrize("text", ["plumber berlin ct", "plumber in Berlin, Connecticut", "plumber berlin CT usa"])
def test_berlin_with_a_us_state_is_the_us_one(text):
    n = parsed(text)
    assert n.where and n.where.startswith("Berlin") and dv.country_of(n) == "us", (n.where, dv.country_of(n))
    assert "ct" not in n.thing.split() and "connecticut" not in n.thing.lower()


def test_places_us_state_helpers():
    assert places.country_for("Berlin, CT") == "us"
    assert places.country_for("Berlin") == "de"
    assert places.us_state_of("Berlin Center OH Plumbers - Networx") == "OH"
    assert places.us_state_of("/plumbers/oh/berlin-center") == "OH"
    assert places.us_state_of("Klempner Berlin - Preise") is None
    assert places.us_state_of("/de/berlin/klempner") is None       # /de/ is a language, not Delaware


def test_us_namesake_page_is_skipped_for_berlin_germany():
    # eval r4 plumber-berlin: 'Berlin Center OH Plumbers - Networx' was read as a Berlin plumber
    n = parsed("plumber berlin")
    why = dv.service_skip(n, "https://www.networx.com/plumbers/oh/berlin-center", "Berlin Center OH Plumbers - Networx")
    assert why and "US" in why
    assert dv.service_skip(n, "https://www.angi.com/companylist/us/ct/berlin/plumbing.htm",
                           "THE 10 BEST Plumbers in Berlin, CT")
    assert dv.service_skip(n, "https://www.my-hammer.de/sanitaer/klempner-berufe/berlin",
                           "Klempner in Berlin: Jetzt geeignete Betriebe finden!") is None
    # asked for the US one: the US pages are the right ones
    us = parsed("plumber berlin ct")
    assert dv.service_skip(us, "https://www.angi.com/companylist/us/ct/berlin/plumbing.htm",
                           "THE 10 BEST Plumbers in Berlin, CT") is None


# ------------------------------------------------------------------ audience words

@pytest.mark.parametrize("text,who", [("winter jacket women", "women"), ("naisten talvitakki", "women"),
                                      ("Damen Winterjacke", "women"), ("lasten talvitakki", "kids"),
                                      ("kids winter jacket", "kids"), ("miesten kengät", "men")])
def test_audience_word_is_kept_in_must_have(text, who):
    n = N.parse_need_rules(text)
    assert who in n.must_have, n.must_have
    assert N.audience(n) == who


@pytest.mark.parametrize("text", ["reima talvihaalari", "talvitakki 150 cm", "lassie kurahousut koko 110",
                                  "winter jacket size 128"])
def test_kids_brands_and_sizes_mean_kids(text):
    n = N.parse_need_rules(text)
    assert N.audience(n) == "kids", text
    assert "kids" in n.must_have


@pytest.mark.parametrize("text", ["dining table 150 cm", "sofa 200 cm", "tv 55 inch", "ikea kallax"])
def test_sizes_of_furniture_are_not_kids(text):
    assert N.audience(N.parse_need_rules(text)) is None


def test_service_audience_is_kept_in_the_local_query():
    n = parsed("naisten parturi helsinki")
    assert "women" in n.must_have
    plan = dv.lean_plan(n, "service", tokens=10)
    local = [q for q, *_ in plan if "parturi" in q.lower() or "kampaamo" in q.lower()]
    assert local and all("naisten" in q.lower() for q in local), plan
    en = parsed("women haircut helsinki")
    assert "women" in en.must_have
    assert any("naisten" in q.lower() for q, *_ in dv.lean_plan(en, "service", tokens=10))


def test_barn_painting_is_no_kids_service():
    assert N.audience(N.parse_need_rules("barn painting service")) is None


# ------------------------------------------------------------------ must_not: 'no X / without X / ei X / ohne X'

@pytest.mark.parametrize("text,thing,nots", [
    ("ps5 no gta bundle", "ps5", ["gta bundle"]),
    ("PS5 without GTA bundle under 400 eur", "ps5", ["gta bundle"]),
    ("ps5 ei pelejä", "ps5", ["pelejä"]),
    ("ps5 konsoli ilman pelejä alle 400", "ps5 konsoli", ["pelejä"]),
    ("PS5 ohne Spiele", "ps5", ["spiele"]),
    ("ps5 slim zonder controller, max 350", "ps5 slim", ["controller"]),
    ("sofa without cushions in helsinki", "sofa", ["cushions"]),
])
def test_must_not_is_parsed_and_cut_from_the_thing(text, thing, nots):
    n = N.parse_need_rules(text)
    assert n.thing == thing and n.must_not == nots, (n.thing, n.must_not)
    assert not set(nots) & set(n.must_have)


def test_must_not_keeps_budget_and_place():
    n = N.parse_need_rules("PS5 without GTA bundle under 400 eur")
    assert n.budget == 400
    assert N.parse_need_rules("sofa without cushions in helsinki").where == "Helsinki"


@pytest.mark.parametrize("text", ["samsung fridge no frost", "No Man's Sky ps5", "no time to die bluray",
                                  "fridge no-frost", "ps5 no"])
def test_product_names_with_no_are_not_exclusions(text):
    n = N.parse_need_rules(text)
    assert n.must_not == [] and n.thing.startswith(text.lower().split()[0])
    assert "men" not in n.must_have


def test_must_not_names_a_lane_drops_it_and_is_no_audience():
    assert "refurbished" not in N.parse_need_rules("iphone 13 no refurbished").conditions
    n = N.parse_need_rules("winter jacket no kids")
    assert n.must_not == ["kids"] and N.audience(n) is None and "kids" not in n.must_have


def test_must_not_hit_is_the_relevance_hook():
    n = N.parse_need_rules("ps5 no gta bundle")
    assert N.must_not_hit(n, "PS5 Slim + GTA V bundle") == "gta bundle"
    assert N.must_not_hit(n, "PS5 GTA5 bundle") == "gta bundle"
    assert N.must_not_hit(n, "PlayStation 5 Digital Edition") is None
    fi = N.parse_need_rules("ps5 ei pelejä")
    assert N.must_not_hit(fi, "PS5 + 3 peliä") and N.must_not_hit(fi, "PS5 ja pelit")
    assert N.must_not_hit(fi, "PS5 levyasema") is None
    de = N.parse_need_rules("PS5 ohne Spiele")
    assert N.must_not_hit(de, "PS5 mit 2 Spielen") and N.must_not_hit(de, "PS5 Spider-Man") is None
    assert N.must_not_hit(N.parse_need_rules("ps5"), "PS5 GTA bundle") is None


def test_need_without_must_not_still_loads_from_storage():
    d = {k: v for k, v in N.parse_need_rules("ps5").__dict__.items() if k != "must_not"}
    assert Need(**d).must_not == []


# ------------------------------------------------------------------ inheritance: nearer parent wins, general directories

def test_root_sites_do_not_come_back_when_the_near_ones_do_not_fit():
    # School catering <- Catering (checkatrade.com, trades) <- Events (ticket sellers): neither fits catering
    info = N.category_info("cpv:55524")
    assert not {"lippu.fi", "ticketmaster.fi", "eventim.de", "checkatrade.com"} & {d["domain"] for d in info["domains"]}


def test_general_lead_gen_directory_fits_every_trade():
    assert dv.families_of("bark.com") is None
    assert "bark.com" in {d["domain"] for d in N.category_info("events-leisure.weddings.wedding-photographer")["domains"]}
