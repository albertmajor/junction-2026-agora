"""Discovery fixer, eval round 1: regressions from judges reading real live streams (14 Nov).

Each test names the query of the live stream it comes from; all offline (the tree, the rules, a mocked search).
"""
from __future__ import annotations

import asyncio

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import hunt as hunt_mod
from agora import longtail
from agora import need as N
from agora import reader
from agora.models import Event, Need

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


def parsed(text: str, category: str | None = None) -> Need:
    n = N.parse_need_rules(text)
    N.categorize(n, category)
    return n


# ------------------------------------------------------------------ 'gift for mom' (was: digital, accounting software)

def test_gift_for_mom_is_a_thing_to_buy_not_software():
    n = parsed("gift for mom")
    assert n.kind == "product"
    assert not (n.category or {}).get("path_ids", [""])[0] == "software"
    assert longtail.classify(n) is None          # no 'Financial, Tax & Accounting Software' long-tail lane
    for q in ("lahja äidille", "christmas present for dad", "geschenk für mama"):
        assert N.parse_need_rules(q).kind == "product", q


def test_taxonomy_flip_needs_a_shared_word():
    c = {"label": "Financial, Tax & Accounting Software", "labels": {"da": "Software til økonomi, moms og regnskab"}}
    assert not N._names_node("gift for mom", c)                  # 'moms' (Danish VAT) is no 'mom'
    assert N._names_node("accounting software for freelancers", c)


# ------------------------------------------------------------------ 'unlimited graphic design subscription'

def test_design_subscription_gets_the_service_node_not_software():
    n = parsed("unlimited graphic design subscription")
    assert n.kind == "digital"                                   # still priced per month
    assert n.category and n.category["id"] != "sp:so-1-10-3"     # not 'Graphic Design & Illustration Software'
    assert n.category["kind"] == "service"
    assert N.priced_per_period(n)
    assert longtail.classify(n)["id"] == n.category["id"]        # the long tail follows the hunt's node
    vpn = parsed("vpn subscription")
    assert vpn.category and vpn.category["kind"] == "digital"     # real software keeps its software node


# ------------------------------------------------------------------ 'volvo v70', 'bright red car'

def test_car_needs_get_the_cars_category():
    for q in ("volvo v70", "bright red car", "käytetty auto"):
        n = parsed(q)
        assert n.category and n.category["id"] == N.CARS_NODE, q
    assert parsed("car seat").category is None or parsed("car seat").category["id"] != N.CARS_NODE


def test_generic_car_is_searched_in_the_home_language_with_its_colour(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    n = parsed("bright red car")
    assert n.must_have == ["bright red"]
    assert N.vehicle_words(n, "fi") == "punainen auto"
    assert N.vehicle_words(parsed("volvo v70"), "fi") is None     # make + model work in every language
    used = dv.lean_plan(n, "used", tokens=10)
    assert used[0][0].startswith("punainen auto")                 # was 'car käytetty myydään tori' (229 toys)
    direct = dv.plan_direct(n, dv.lanes_for(n), 10, 2)
    used_d = direct.get("used", [])
    # eval r3: with the home cars site planned, tori's goods search (toys, LEGO) is not read for a car
    assert any(d.site.key == "nettiauto" for d in used_d) and not any(d.site.key == "tori" for d in used_d)
    low = dv.plan_direct(n, dv.lanes_for(n), 3, 2)        # no token for nettiauto: tori, in Finnish
    tori = [d for d in low.get("used", []) if d.site.key == "tori"]
    assert tori and tori[0].query == "punainen auto"


# ------------------------------------------------------------------ 'kinderwagen gebraucht' (typed German from FI)

def test_query_language():
    assert N.query_language("kinderwagen gebraucht") == "de"
    assert N.query_language("puhelin") == "fi"
    assert N.query_language("fiets") == "nl"
    for q in ("iphone 13", "sony a7 iii body", "road bike", "gift for mom", "lunch"):
        assert N.query_language(q) is None, q


def test_german_query_searches_home_in_finnish_and_germany_too():
    n = parsed("kinderwagen gebraucht")
    used = dv.lean_plan(n, "used", tokens=10)
    home_q = used[0]
    assert home_q[1] == "fi" and "kinderwagen" not in home_q[0]  # the category's Finnish word, not 'kinderwagen käytetty'
    assert any(c == "de" and "kinderwagen" in q for q, c in used)
    ask = hunt_mod.scope_question(n)
    assert ask and ask["country"] == "de" and "germany" in ask["hunt"]["q"]
    assert N.parse_need_rules(ask["hunt"]["q"]).where == "Germany"
    assert hunt_mod.scope_question(parsed("käytetty sohva")) is None


# ------------------------------------------------------------------ 'Sofas' from the tree

def test_sofas_from_the_tree_skip_the_refurbished_lane():
    n = N.parse_need_rules("Sofas")
    N.categorize(n, "sp:fr-22")
    assert "refurbished" not in dv.lanes_for(n)
    assert dv.need_bulky(n)


def test_home_pages_and_ikea_locale():
    assert dv.home_page("https://www.boconcept.com/fi-fi/shop/sohvat/", "fi")
    assert dv.home_page("https://www.ikea.com/fi/fi/cat/sohvat-fu003/", "fi")
    assert dv.home_page("https://finsoffat.fi/tuoteryhma/sohvat/", "fi")
    assert not dv.home_page("https://www.wayfair.com/keyword.php?keyword=refurbished+sofa", "fi")
    assert not dv.home_page("https://www.1stdibs.com/furniture/seating/sofas/x", "fi")
    assert dv.localize("https://www.ikea.com/us/en/p/kivik-sofa-hillared-anthracite-s69440510/", "fi") \
        == "https://www.ikea.com/fi/fi/p/kivik-sofa-hillared-anthracite-s69440510/"
    assert dv.localize("https://www.ikea.com/fi/fi/p/x-s69440510/", "fi").startswith("https://www.ikea.com/fi/fi/")


def _search_returning(monkeypatch, results):
    calls = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country, **kw})
        return results
    monkeypatch.setattr(cd, "search", search)
    monkeypatch.setenv("AGORA_DIRECT", "0")
    reader._HINTS.clear()
    return calls


def collect(need, **kw):
    async def run():
        return [e async for e in dv.discover(need, **kw)]
    return asyncio.run(run())


def test_bulky_home_shops_are_emitted_before_shops_abroad(monkeypatch):
    _search_returning(monkeypatch, [
        {"url": "https://www.globaldiscountfurniture.com/product-category/lounge-furniture/sofas/", "title": "Sofas"},
        {"url": "https://www.nfm.com/sofas-and-loveseats", "title": "Sofas"},
        {"url": "https://www.ikea.com/us/en/p/kivik-sofa-hillared-anthracite-s69440510/", "title": "KIVIK sofa"},
        {"url": "https://www.asko.fi/tuotteet/1/olohuone/sohvat", "title": "Sohvat"},
        {"url": "https://hoset.fi/catalog/sofa", "title": "Sohvat"},
    ])
    n = N.parse_need_rules("Sofas")
    N.categorize(n, "sp:fr-22")
    srcs = [e.data["url"] for e in collect(n, tokens=10) if e.type == "source" and e.data.get("lane") == "new"]
    assert "https://www.ikea.com/fi/fi/p/kivik-sofa-hillared-anthracite-s69440510/" in srcs
    home = [i for i, u in enumerate(srcs) if dv.home_page(u, "fi")]
    abroad = [i for i, u in enumerate(srcs) if not dv.home_page(u, "fi")]
    assert home and abroad and max(home) < min(abroad)


# ------------------------------------------------------------------ 'School catering' / 'Wedding photographer' (tree)

def test_school_catering_queries_price_per_meal_and_no_ticket_sites():
    n = N.parse_need_rules("School catering")
    N.categorize(n, "cpv:55524")
    doms = [d["domain"] for d in n.category["domains"]]
    assert not {"lippu.fi", "ticketmaster.fi", "eventim.de", "getyourguide.com"} & set(doms)
    hunt_mod.default_where(n)
    qs = [x[0] for x in dv.lean_plan(n, "service", tokens=10)]
    assert qs and not any("per hour" in q for q in qs)
    assert any("per person" in q for q in qs) and any("henkilö" in q for q in qs)
    assert dv.service_unit(n) == "person"


def test_wedding_photographer_keeps_wedding_sites_drops_ticket_sellers():
    n = N.parse_need_rules("Wedding photographer")
    N.categorize(n, "events-leisure.weddings.wedding-photographer")
    doms = {d["domain"] for d in n.category["domains"]}
    assert "bark.com" in doms and not {"lippu.fi", "ticketmaster.fi"} & doms
    assert dv.service_unit(n) == "package"
    # a shallow node still inherits its root's sites (Plumbing <- Trades: tori.fi, remonttipalvelu.fi)
    p = N.parse_need_rules("Plumbing")
    N.categorize(p, "trades.plumbing")
    assert "remonttipalvelu.fi" in {d["domain"] for d in p.category["domains"]}


# ------------------------------------------------------------------ 'Plumbing' from the tree

def test_local_trade_from_the_tree_is_searched_near_the_home_city():
    n = N.parse_need_rules("Plumbing")
    N.categorize(n, "trades.plumbing")
    note = hunt_mod.default_where(n)
    assert n.where == "Helsinki" and "Helsinki" in note
    plan = dv.lean_plan(n, "service", tokens=10)
    assert plan[0][1] == "fi"                                    # never an unfiltered 'plumbing price per hour'
    assert any("putkimies" in x[0] and "Helsinki" in x[0] for x in plan)
    for q, cat in (("bookkeeping service finland", None), ("car insurance finland", None)):
        m = parsed(q, cat)
        m.where = None
        assert hunt_mod.default_where(m) is None and m.where is None, q    # bought from anywhere
    assert hunt_mod.default_where(parsed("sofa")) is None


def test_typed_service_without_place_filters_english_query_home():
    n = parsed("gunsmith")
    n.where = None
    plan = dv.lean_plan(n, "service", tokens=10)
    assert plan[0][1] == "fi"


def test_cost_guides_are_read_after_providers():
    guides = [("https://oferta.fi/putkimies-hinta/", "Putkimiehen Hinta 2025: Laaja Opas"),
              ("https://fixmera.com/blogi/putkimies-hinta-2026", "Putkimies hinta 2026 — Mitä putkityöt maksavat?"),
              ("https://putkarit.fi/putkimies/yleisimmat-putkityot-hinnat/", "Putkimiehen tuntihinta 2026 — mediaani"),
              ("https://www.homeadvisor.com/cost/plumbing/hire-a-plumber/", "How Much Does a Plumber Cost?")]
    for url, title in guides:
        assert dv.cost_guide(url, title), url
        assert dv.paid_priority(url, "service", "service", title) == 3
    own = ("https://www.normiputki.fi/hinnasto", "Hinnasto - Normiputki")
    assert not dv.cost_guide(*own)
    assert dv.paid_priority(own[0], "service", "service", own[1]) == 0


def test_directory_provider_profiles_get_more_than_two_reads(monkeypatch):
    _search_returning(monkeypatch, [
        {"url": f"https://www.urakkamaailma.fi/urakoitsija/firma-{i}", "title": f"LVI Firma {i} Oy"} for i in range(6)])
    n = N.parse_need_rules("Plumbing")
    N.categorize(n, "trades.plumbing")
    n.where = "Helsinki"
    srcs = [e for e in collect(n, tokens=10) if e.type == "source"]
    assert len([s for s in srcs if "urakkamaailma.fi/urakoitsija/" in s.data["url"]]) == dv.DIRECTORY_PROFILES


# ------------------------------------------------------------------ 'lunch' (a vague word)

def test_lunch_takes_its_likeliest_meaning():
    assert hunt_mod.auto_intent_for(N.parse_need("lunch")) == "c:lunch.places"
    for q in ("iphone 13", "sofa", "kitchen table", "used lunch box", "lunch box with 3 compartments",
              "bright red car", "puhelin"):
        assert hunt_mod.auto_intent_for(N.parse_need(q)) is None, q
    # eval r2: 'gift for mom' hunted literally matched the token 'mom' (baby socks): it now takes its meaning
    assert hunt_mod.auto_intent_for(N.parse_need("gift for mom")) == "c:gift.ideas"


def test_lunch_hunt_runs_the_service_lane(monkeypatch):
    seen: list[Need] = []

    async def disc(need):
        seen.append(need)
        yield Event("lane", {"lane": "service", "queries": []})

    async def go():
        kw = fk.kwargs(discover=disc)
        kw.pop("parse_need")
        return [e async for e in hunt_mod.hunt("lunch", **kw, siblings=False, longtail=False, lookalikes=False)]
    events = asyncio.run(go())
    need_ev = next(e for e in events if e.type == "need").data
    cat_ev = next(e for e in events if e.type == "category").data
    assert need_ev["need"]["kind"] == "service"
    assert cat_ev.get("auto") and cat_ev["intent"]["id"] == "c:lunch.places"
    assert seen and seen[0].kind == "service" and seen[0].where == "Helsinki"
    assert need_ev.get("where_default")


# ------------------------------------------------------------------ intent: 'car insurance finland', 'wedding photographer'

def _intents(q):
    from agora import intent as I
    return I.interpret(q, llm=False)


def test_words_that_name_one_meaning_make_it_dominant():
    for q, want, hunt_q in (("car insurance finland", "c:insurance.car", "car insurance"),
                            ("wedding photographer", "c:wedding.photographer", "wedding photographer"),
                            ("travel insurance", "c:insurance.travel", "travel insurance")):
        r = _intents(q)
        assert r["dominant"] and r["intents"][0]["id"] == want, q
        assert r["intents"][0]["hunt"]["q"] == hunt_q, q
        for it in r["intents"]:                      # never 'home insurance car', 'wedding venue photographer'
            words = it["hunt"]["q"].lower().split()
            assert len(words) == len(set(words)) and not (it["id"] != want and words[-1] in hunt_q.split()[:1]), it
    assert not _intents("insurance")["dominant"]     # the bare word still fans out
    assert not _intents("wedding")["dominant"]


def test_colour_words_only_describe_the_thing():
    r = _intents("bright red car")
    by = {i["id"]: i["hunt"]["q"] for i in r["intents"]}
    assert by["c:car.buy"] == "bright red car"
    assert by["c:car.rental"] == "car rental" and "red" not in by["c:car.insurance"]


# ------------------------------------------------------------------ intent: 'volvo v70', 'nintendo switch oled' had no intents

def test_model_names_get_their_family_node():
    v = _intents("volvo v70")
    assert v["intents"] and v["intents"][0]["node"] == N.CARS_NODE and v["intents"][0]["kind"] == "vehicle"
    assert v["dominant"] and v["intents"][0]["as_typed"]
    for q, node in (("nintendo switch oled", "sp:el-19"), ("dyson v15", "sp:hg-9-10")):
        r = _intents(q)
        assert r["intents"] and r["intents"][0]["node"] == node, q


def test_intent_reports_the_typed_language():
    assert _intents("kinderwagen gebraucht")["query_lang"] == "de"
    assert _intents("puhelin")["query_lang"] == "fi"
    assert _intents("iphone 13")["query_lang"] is None
