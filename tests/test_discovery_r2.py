"""Discovery fixer, eval round 2: regressions from judges reading real live streams (14 Nov, eval/r2).

Each test names the query of the live stream it comes from. The URLs and titles are copied from those streams;
everything runs offline (rules, the tree, a mocked search).
"""
from __future__ import annotations

import asyncio

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import hunt as hunt_mod
from agora import intent as I
from agora import longtail
from agora import need as N
from agora import reader
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
    dv._LIST_HINTS.clear()


def parsed(text: str, category: str | None = None) -> Need:
    n = N.parse_need_rules(text)
    N.categorize(n, category)
    return n


def _search_returning(monkeypatch, by_query):
    calls = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country, **kw})
        return by_query(query, kw) if callable(by_query) else by_query
    monkeypatch.setattr(cd, "search", search)
    monkeypatch.setenv("AGORA_DIRECT", "0")
    reader._HINTS.clear()
    return calls


def collect(need, **kw):
    async def run():
        return [e async for e in dv.discover(need, settle_s=0.3, **kw)]
    return asyncio.run(run())


# ------------------------------------------------------------------ 'winter jacket women'

def test_audience_words_stay_in_the_marketplace_searches(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    n = parsed("winter jacket women")
    assert N.audience(n) == "women"
    used = {d.site.key: d for d in dv.plan_direct(n, dv.lanes_for(n), 10, 2).get("used", [])}
    assert used["tori"].query == "naisten talvitakki" and "naisten+talvitakki" in used["tori"].url
    assert used["kleinanzeigen"].query == "damen winterjacke"
    assert used["blocket"].query == "dam vinterjacka"
    assert used["marktplaats"].query == "dames winterjas"
    assert all(d.url.count("talvitakki") <= 1 for d in used.values())
    for q, who in (("naisten talvitakki", "women"), ("Herren Winterjacke", "men"), ("kids winter boots", "kids"),
                   ("winter jacket", None), ("volvo v70", None)):
        assert N.audience(parsed(q)) == who, q
    plain = {d.site.key: d.query for d in dv.plan_direct(parsed("winter jacket"), ["used"], 10, 2)["used"]}
    assert plain["tori"] == "talvitakki"                  # nothing added when no audience was asked


# ------------------------------------------------------------------ 'bright red car', 'volvo v70'

VOLVO_RESULTS = [   # the 'new' lane's search results of the live 'volvo v70' stream
    ("https://www.autouncle.fi/fi/kaytetyt-autot/Volvo/V70/f-bensiini", "Volvo V70 (bensiini) – 21 käytettyä autoa"),
    ("https://www.kamux.fi/cars/volvo/v/v70", "Volvo V70 vaihtoautot | Kamux"),
    ("https://www.autotie.fi/vaihtoautot/volvo/v70", "Käytetyt VOLVO V70 vaihtoautot"),
    ("https://www.auto1.fi/volvo/v70", "VOLVO V70 vaihtoautot - 185 autoa myynnissä"),
    ("https://www.rinta-jouppi.com/ajoneuvohaku/volvo/v70/458836/", "Volvo V70, 2009, 211 tkm - alk. 149 €/kk"),
    ("https://www.autoscout24.com/lst/volvo/v70", "Used Volvo V70 for sale - AutoScout24 UK"),
    ("https://www.carfax.com/Used-Volvo-V70_w676", "Used Volvo V70 for Sale Near Me - CARFAX"),
    ("https://www.cars.com/shopping/volvo-v70/", "Used Volvo V70 for Sale Near Me | Cars.com"),
    ("https://www.edmunds.com/used-volvo-v70/", "Used Volvo V70 for Sale Near Me | Edmunds"),
    ("https://carsandbids.com/search/volvo/v70", "Used Volvo V70 for Sale - Cars & Bids"),
]


def test_used_car_lists_go_to_the_used_lane_as_list_pages(monkeypatch):
    calls = _search_returning(monkeypatch, lambda q, kw: [{"url": u, "title": t} for u, t in VOLVO_RESULTS])
    n = parsed("volvo v70")
    events = collect(n, tokens=10)
    src = {e.data["url"]: e.data for e in events if e.type == "source"}
    skips = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    for u in ("https://www.autouncle.fi/fi/kaytetyt-autot/Volvo/V70/f-bensiini", "https://www.kamux.fi/cars/volvo/v/v70",
              "https://www.autotie.fi/vaihtoautot/volvo/v70", "https://www.auto1.fi/volvo/v70",
              "https://www.autoscout24.com/lst/volvo/v70"):
        assert src[u]["lane"] == "used", u                # was read as one 'new' offer each (headline: new at autouncle)
        assert dv.is_list_page(u), u                      # cut into listings by the reader
    assert not dv.is_list_page("https://www.rinta-jouppi.com/ajoneuvohaku/volvo/v70/458836/")   # one car
    for u in ("https://www.carfax.com/Used-Volvo-V70_w676", "https://www.cars.com/shopping/volvo-v70/",
              "https://www.edmunds.com/used-volvo-v70/", "https://carsandbids.com/search/volvo/v70"):
        assert u in skips and "outside Europe" in skips[u], u
    # every web search of a car hunt is filtered to the home country (was: open 'volvo v70 price buy online')
    assert calls and all(c["country"] == "fi" for c in calls)


def test_car_plan_scope_and_colour(monkeypatch):
    n = parsed("bright red car")
    used = dv.lean_plan(n, "used", tokens=10)
    assert used[0] == ("punainen auto vaihtoautot myynnissä", "fi")
    assert len(used) == 1                                  # no 'car used kleinanzeigen OR vinted' for a car
    assert all(c == "fi" for _, c in dv.lean_plan(n, "new", tokens=10))
    assert dv.colour_clash(n, "https://www.auto1.fi/haku/vaaleanpunainen",
                           "Vaaleanpunainen vaihtoautot - 3 505 autoa myynnissä, alk. 290 €")
    assert dv.colour_clash(n, "https://www.auto1.fi/haku/punainen", "Punainen vaihtoautot") is None
    scope = dv.vehicle_scope({"scope": "home", "size": "medium", "reason": "shipping a medium parcel"}, "fi")
    assert scope["size"] == "vehicle" and "parcel" not in scope["reason"] and "Finland" in scope["reason"]
    monkeypatch.setenv("AGORA_DIRECT", "1")
    _search_returning(monkeypatch, [])
    monkeypatch.setenv("AGORA_DIRECT", "1")
    sc = next(e.data for e in collect(parsed("volvo v70"), tokens=10) if e.type == "scope")
    assert sc["size"] == "vehicle" and "parcel" not in sc["reason"]


def test_planned_marketplace_page_keeps_full_read_time_on_a_slow_domain():
    """'volvo v70': nettiauto hit 'timeout after 5s (known slow domain)' twice and gave nothing."""
    class Slow:
        def is_slow(self, d):
            return True

        def timeout_for(self, d, default):
            return 0.2

        def wall_for(self, d):
            return 0.3

        def record(self, d, timed_out, seconds=None):
            pass

        def save(self):
            pass

    direct = "https://www.nettiauto.com/vaihtoautot?q=volvo+v70"
    other = "https://www.nettiauto.com/volvo/v70"

    async def disc(need):
        yield Event("lane", {"lane": "used", "queries": []})
        yield Event("source", {"url": direct, "lane": "used", "direct": True, "page": 1})
        yield Event("source", {"url": other, "lane": "used"})

    async def read(url, need):
        await asyncio.sleep(0.6)
        return Offer(url=url, source="nettiauto.com", title="Volvo V70 2.4", price=4000.0, currency="EUR",
                     price_eur=4000.0, condition="used")

    async def go():
        kw = fk.kwargs(discover=disc, read=read, slow_domains=Slow())
        return [e async for e in hunt_mod.hunt("volvo v70", **kw, read_timeout=3.0, siblings=False,
                                               longtail=False, lookalikes=False, budget_s=False)]
    events = asyncio.run(go())
    offers = {e.data["offer"]["url"] for e in events if e.type == "offer"}
    timeouts = {e.data["url"] for e in events if e.type == "skip" and e.data.get("timeout")}
    assert direct in offers and other in timeouts


# ------------------------------------------------------------------ 'cat=yelp:gunsmith|Gunsmith'

def test_gunsmith_searches_no_babysitter_cleaner_or_barber_sites():
    n = parsed("Gunsmith", "yelp:gunsmith")
    hunt_mod.default_where(n)
    plan = dv.lean_plan(n, "service", tokens=10)
    sites = [d for x in plan if len(x) > 2 for d in x[2]]
    assert not {"kotisiivousvertailu.fi", "timma.fi", "care.com", "yoopies.de", "rover.com"} & set(sites)
    assert not {"care.com", "yoopies.de", "rover.com"} & set(dv.category_sites(n, "fi"))
    # pages naming the trade are read before an asbestos firm or a barber
    trade = ("https://www.asejaera.fi/asekauppa/asesepan-palvelut/c/15/", "Aseseppä | Vaimenninkierteet ja")
    asbestos = ("https://www.urakkamaailma.fi/urakoitsija/suomen-asbestipro-oy", "Suomen Asbestipro Oy | Tiedot")
    barber = ("https://timma.fi/parturi-helsinki", "Parturi Helsinki | Timma")
    us = ("https://www.westcoastarmory.com/common-gunsmithing-services", "Common Gunsmithing Services")
    fit = {u: dv.service_fit(n, u, t) for u, t in (trade, asbestos, barber, us)}
    assert fit[trade[0]] > fit[asbestos[0]] and fit[trade[0]] > fit[barber[0]] and fit[trade[0]] > fit[us[0]]


# ------------------------------------------------------------------ 'plumber berlin'

def test_plumber_berlin_gets_trade_sites_of_germany_and_no_us_cost_guide(monkeypatch):
    n = parsed("plumber berlin")
    sites = [d for x in dv.lean_plan(n, "service", tokens=10) if len(x) > 2 for d in x[2]]
    assert "myhammer.de" in sites
    assert not {"helpling.de", "betreut.de", "rover.com", "checkatrade.com"} & set(sites)
    assert dv.service_skip(n, "https://www.homeyou.com/ct/plumbing-repair-berlin-costs",
                           "Plumbing Repair labor cost (lower estimate)")
    assert dv.service_skip(n, "https://www.my-hammer.de/sanitaer/klempner-berufe/berlin",
                           "Klempner in Berlin: Jetzt geeignete Betriebe finden!") is None
    # Helsinki: no cleaning or barber sites for a wedding photographer or school catering
    w = parsed("Wedding photographer", "events-leisure.weddings.wedding-photographer")
    hunt_mod.default_where(w)
    assert not dv.market_fits("kotisiivousvertailu.fi", w, "fi") and not dv.market_fits("timma.fi", w, "fi")
    c = parsed("home cleaning tilburg")
    assert dv.market_fits("helpling.nl", c, "nl") and dv.market_fits("werkspot.nl", c, "nl")


# ------------------------------------------------------------------ 'lunch'

LUNCH = [("https://www.lounaat.info/tampere", "Lounas Tampere, Keskusta"),
         ("https://www.lounaat.info/lahti", "Lounas Lahti, Keskusta"),
         ("https://www.lounaat.info/lounas/ravintola-eliel/lahti", "Ravintola Eliel"),
         ("https://www.raflaamo.fi/en/restaurants/oulu/lunch", "Lunch: Oulu | Raflaamo.fi"),
         ("https://www.lounaat.info/toolo", "Lounas Töölö, Helsinki"),
         ("https://www.lounaat.info/vantaa", "Lounas Vantaa"),
         ("https://www.raflaamo.fi/en/restaurants/helsinki/lunch", "Lunch: Helsinki | Raflaamo.fi"),
         ("https://www.caffitella.fi/lounaslista/", "Lounaslista - Kahvilat, lounaat ja leipomoherkut")]


def test_lunch_searches_the_city_and_skips_other_cities(monkeypatch):
    n = N.parse_need("lunch")
    I.apply(n, "c:lunch.places")
    hunt_mod.default_where(n)
    plan = dv.lean_plan(n, "service", tokens=10)
    assert all("Helsinki" in x[0] for x in plan), plan          # was 'lunch restaurant', 'lounas'
    _search_returning(monkeypatch, [{"url": u, "title": t} for u, t in LUNCH])
    events = collect(n, tokens=10)
    src = [e.data["url"] for e in events if e.type == "source"]
    skips = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    for u in LUNCH[:4]:
        assert u[0] in skips and "another city" in skips[u[0]], u
    for u in ("https://www.lounaat.info/toolo", "https://www.lounaat.info/vantaa",
              "https://www.raflaamo.fi/en/restaurants/helsinki/lunch", "https://www.caffitella.fi/lounaslista/"):
        assert u in src, u
    # a country asked is no city: nothing is 'another city'
    ins = parsed("car insurance finland")
    assert dv.other_city(ins, "https://www.if.fi/tampere", "If Tampere") is None


# ------------------------------------------------------------------ 'car insurance finland' + the tree hunt

def test_insurance_from_the_tree_searches_home_in_finnish():
    n = parsed("Car insurance", "finance-insurance.insurance.car-insurance")
    hunt_mod.default_where(n)
    assert N.national_service(n) and N.quote_based(n)
    plan = dv.lean_plan(n, "service", tokens=10)
    assert all(x[1] == "fi" for x in plan)                       # was country None -> US insurers in USD
    assert plan[0][0] == "Autovakuutus hinta"
    sites = [d for x in plan if len(x) > 2 for d in x[2]]
    assert {"if.fi", "op.fi", "lahitapiola.fi", "fennia.fi"} <= set(sites)
    typed = dv.lean_plan(parsed("car insurance finland"), "service", tokens=10)
    assert typed[0][0] == "Autovakuutus hinta" and not any("pricing plans" in x[0] for x in typed)
    lt = longtail.intent_queries(n, longtail.classify(n))
    assert lt and all(c == "fi" for _, c, _ in lt)
    assert not any("retainer" in q or "productized" in q for q, _, _ in lt)
    assert not N.national_service(parsed("plumber"))


# ------------------------------------------------------------------ 'unlimited graphic design subscription'

def test_design_subscription_means_a_studio_not_software():
    r = I.interpret("unlimited graphic design subscription", llm=False)
    top = r["intents"][0]
    assert r["dominant"] and top["kind"] == "service" and top["id"] == "c:design-subscription.studio"
    assert "designjoy.co" in top["domains"] and "kimp.io" in top["domains"]
    n = parsed("unlimited graphic design subscription")
    assert dv.service_skip(n, "https://apps.apple.com/us/app/standard/id123", "Standard") == \
        "an app store page, not a provider"
    assert dv.service_skip(n, "https://play.google.com/store/apps/details?id=x", "Design app")


# ------------------------------------------------------------------ 'gift for mom'

def test_gift_for_mom_is_translated_and_fans_out():
    r = I.interpret("gift for mom", llm=False)
    ideas = r["intents"][0]
    assert ideas["id"] == "c:gift.ideas"
    assert ideas["queries"]["fi"][0] == "lahja äidille"          # was 'lahjaidea for mom'
    assert ideas["queries"]["de"][0] == "Geschenk für Mama"      # was 'Geschenkidee for mom'
    assert any("koru" in q for q in ideas["queries"]["fi"]) and ideas["lanes"] == ["new"]
    assert I.recipient("for my dad")[1] == "male" and I.recipient("äidille")[1] == "female"
    assert I.recipient("for work") == (None, None)


def test_gift_hunt_takes_the_meaning_and_matches_kinds_not_the_word_mom(monkeypatch):
    from agora import resolve
    n = N.parse_need("gift for mom")
    assert hunt_mod.auto_intent_for(n) == "c:gift.ideas"
    I.apply(n, "c:gift.ideas")
    assert dv.lanes_for(n) == ["new"]                            # no used baby socks, no resale
    monkeypatch.setenv("AGORA_DIRECT", "1")
    assert dv.plan_direct(n, dv.lanes_for(n), 10, 2) == {}       # no marketplace search for 'gift for mom'
    plan = dv.lean_plan(n, "new", tokens=10)
    assert plan[0] == ("lahja äidille", "fi") and all(c == "fi" for _, c in plan)
    assert any("koru" in q for q, _ in plan)

    def ok(title):
        r, why = resolve.explain(n, Offer(url="https://x.fi/a", source="x.fi", title=title, price=30.0, currency="EUR"))
        return why is None
    assert ok("Pandora hopeakoru sydän") and ok("Lahjapakkaus Rituals naisille")
    assert not ok("4-pack babystrumpor – I <3 mom & dad") and not ok("Blue mom shorts")
    assert dv.is_non_shop("https://www.glamour.com/gallery/gifts-for-mom")


def test_gift_hunt_runs_new_lane_with_gift_words(monkeypatch):
    seen: list[Need] = []

    async def disc(need):
        seen.append(need)
        yield Event("lane", {"lane": "new", "queries": []})

    async def go():
        kw = fk.kwargs(discover=disc)
        kw.pop("parse_need")
        return [e async for e in hunt_mod.hunt("gift for mom", **kw, siblings=False, longtail=False,
                                               lookalikes=False)]
    events = asyncio.run(go())
    cat_ev = next(e for e in events if e.type == "category").data
    assert cat_ev.get("auto") and cat_ev["intent"]["id"] == "c:gift.ideas"
    assert seen and seen[0].conditions == ["new"] and "koru" in seen[0].category["synonyms"]


def test_local_job_skips_english_providers_abroad_but_keeps_local_dotcoms():
    g = parsed("Gunsmith", "yelp:gunsmith")
    hunt_mod.default_where(g)
    assert dv.service_skip(g, "https://hallprecision.com/shop-services/gunsmithing/", "Gunsmithing - Hall Precision")
    assert dv.service_skip(g, "https://www.aseteam.fi/", "Etusivu - ASE-Team") is None
    p = parsed("plumber berlin")
    assert dv.service_skip(p, "https://rohrreinigung-berlin.net/rohrreinigung-kosten/", "Rohrreinigung Kosten") is None
    assert dv.service_skip(p, "https://kraft-haustechnik.com/preise/", "Preise | Kraft Haustechnik") is None
