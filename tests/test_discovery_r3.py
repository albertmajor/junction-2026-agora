"""Discovery fixer, eval round 3: regressions from judges reading real live streams (14 Nov).

Each test names the query of the live stream it comes from. URLs, titles and market counts are taken from the
saved streams (tests/fixtures/eval_r3_discovery.json); everything runs offline (the tree, the rules, a mocked
search).
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import hunt as hunt_mod
from agora import intent as I
from agora import marketplaces as M
from agora import need as N
from agora import reader
from agora.models import Event, Need

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "eval_r3_discovery.json").read_text())


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


# ------------------------------------------------------------------ 'volvo v70' / 'bright red car'

def test_car_site_that_ignores_q_reads_the_make_model_page():
    d = used_directs(parsed("volvo v70"))
    netti = [x for x in d if x.site.key == "nettiauto"]
    # was https://www.nettiauto.com/vaihtoautot?q=volvo+v70: the site's cheapest cars of every make
    assert netti and netti[0].url == "https://www.nettiauto.com/volvo/v70"
    assert M.site_for(netti[0].url).key == "nettiauto"           # still split as nettiauto's list page
    for x in d:
        if x.site.key.startswith("autoscout24_"):
            assert "/lst/volvo/v70" in x.url and "q=" not in x.url
    assert dv.car_make_model("vw golf 2015") == ("volkswagen", "golf")
    assert dv.car_make_model("land rover defender") == ("land-rover", "defender")
    assert dv.car_make_model("volvo") == ("volvo", None)
    assert dv.car_make_model("electric") is None


def test_car_hunt_does_not_read_the_general_goods_search():
    for q in ("volvo v70", "bright red car"):
        d = used_directs(parsed(q))
        assert any(x.site.vehicle for x in d), q
        # tori's goods search read 410 rows of 'purkuun' / 'kesärenkaat' and 414 toys (LEGO, BRIO)
        assert not any(x.site.key == "tori" for x in d), q
    # a car query naming no make cannot be put into nettiauto's URL: its site-wide list is not read
    assert not any(x.site.key == "nettiauto" and "?q=" in x.url for x in used_directs(parsed("electric car")))


def _market_records(body: dict, sites: dict[str, str]) -> dict[str, dict]:
    out = {}
    for i, s in enumerate(body["sources"]):
        out[f"https://{s['domain']}/p{i}"] = {**s, "site": sites.get(s["domain"])}
    return out


def test_car_market_total_leaves_out_goods_marketplaces(monkeypatch):
    body = FIX["volvo_v70_market"]
    recs = _market_records(body, {"tori.fi": "tori", "nettiauto.com": "nettiauto", "autotalli.com": "autotalli"})
    monkeypatch.setattr(reader, "MARKET", recs)
    got = hunt_mod.market_body(reader, list(recs), parsed("volvo v70"))
    assert body["total"] == 4183                      # what the stream said: 4,151 of it tori's goods search
    assert "tori.fi" not in {s["domain"] for s in got["sources"]}
    assert got["total"] < 1000


# ------------------------------------------------------------------ 'puhelin' / 'ps5': amazon.co.uk '60,000 results'

def test_market_total_ignores_a_huge_figure_from_a_barely_read_page(monkeypatch):
    for key in ("puhelin_market", "ps5_market"):
        body = FIX[key]
        amazon = next(s for s in body["sources"] if s["domain"] == "amazon.co.uk")
        assert amazon["total"] == 60000 and amazon["read"] == 3
        recs = _market_records(body, {})
        monkeypatch.setattr(reader, "MARKET", recs)
        got = hunt_mod.market_body(reader, list(recs), parsed(key.split("_")[0]))
        a = next(s for s in got["sources"] if s["domain"] == "amazon.co.uk")
        assert a["total"] is None and a["claimed"] == 60000
        assert got["total"] == body["total"] - 60000 + 3, key
        assert got["at_least"]


# ------------------------------------------------------------------ 'Umzugsfirma Hamburg 2-Zimmer-Wohnung'

def test_movers_meaning_scopes_the_hunt_when_the_classifier_was_unsure():
    n = N.parse_need_rules("Umzugsfirma Hamburg 2-Zimmer-Wohnung")
    assert N.categorize(n) is None and n.category is None          # classify: 0.599, just under the bar
    got = I.refine(n)
    assert got and got["category"]["id"] == "home-services.moving-removals"
    assert n.category["id"] == "home-services.moving-removals" and n.kind == "service"


def test_hunt_emits_the_refined_category(monkeypatch):
    seen: list[Need] = []

    async def disc(need):
        seen.append(need)
        yield Event("lane", {"lane": "service", "queries": []})

    async def go():
        kw = fk.kwargs(discover=disc)
        kw.pop("parse_need")
        return [e async for e in hunt_mod.hunt("Umzugsfirma Hamburg 2-Zimmer-Wohnung", **kw, siblings=False,
                                               longtail=False, lookalikes=False)]
    events = asyncio.run(go())
    cat = next(e for e in events if e.type == "category").data
    assert cat["id"] == "home-services.moving-removals"
    assert seen and (seen[0].category or {}).get("id") == "home-services.moving-removals"


def test_refine_keeps_needs_it_does_not_understand_better():
    for q in ("kitchen table", "volvo v70", "puhelin", "polkupyörä", "lunch", "sofa"):
        n = N.parse_need_rules(q)
        N.categorize(n)
        before = (n.thing, (n.category or {}).get("id"), n.kind)
        I.refine(n)
        assert (n.thing, (n.category or {}).get("id"), n.kind) == before, q


# ------------------------------------------------------------------ 'Car insurance' (tree)

def test_insurers_own_pages_are_read_before_calculators_and_comparisons():
    n = N.parse_need_rules("Car insurance")
    N.categorize(n, "finance-insurance.insurance.car-insurance")
    qs = [x[0] for x in dv.lean_plan(n, "service", tokens=10)]
    assert not any("laskuri" in q or "vertailu" in q for q in qs)      # was 'Autovakuutus vertailu laskuri'
    rows = {r["url"]: r["title"] for r in FIX["car_insurance"]}
    calc = [u for u in rows if dv.calculator(u, rows[u])]
    assert "https://www.op.fi/henkiloasiakkaat/vakuutukset/ajoneuvovakuutus/autovakuutus-henkiloautolle/" \
           "autovakuutuslaskuri" in calc
    assert "https://selkoraha.fi/fi/laskurit/autovakuutus-laskuri" in calc
    assert "https://www.autovakuutusvertailu.com/" in calc

    def order(u: str) -> float:
        t = rows[u]
        return dv.expected_yield(u, "service", "service", t) + dv.national_fit(n, u, t)
    insurer = ["https://www.op.fi/henkiloasiakkaat/vakuutukset/ajoneuvovakuutus/autovakuutus-henkiloautolle",
               "https://www.turva.fi/henkilo/vakuutukset/ajoneuvot/autovakuutus/",
               "https://www.fennia.fi/ajoneuvot/autovakuutus",
               "https://www.lahitapiola.fi/henkilo/vakuutukset/ajoneuvovakuutukset/autovakuutus/"]
    assert min(order(u) for u in insurer) > max(order(u) for u in calc)


# ------------------------------------------------------------------ 'winter jacket women' / 'kitchen table'

def test_new_lane_local_query_is_in_the_home_language():
    q = [x[0] for x in dv.lean_plan(parsed("winter jacket women"), "new", tokens=10)]
    assert "naisten talvitakki hinta osta" in q                      # was 'winter jacket women hinta osta'
    q = [x[0] for x in dv.lean_plan(parsed("kitchen table"), "new", tokens=10)]
    assert "ruokapöytä hinta osta" in q                              # was 'kitchen table hinta osta': placemats
    # brand / model words work everywhere: left as typed
    q = [x[0] for x in dv.lean_plan(parsed("ikea kallax shelf"), "new", tokens=10)]
    assert "ikea kallax shelf hinta osta" in q
    # the marketplaces still translate per site (blocket is not searched in Finnish)
    d = {x.site.key: x.query for x in used_directs(parsed("winter jacket women"))}
    assert d.get("blocket") == "dam vinterjacka" and d.get("tori") == "naisten talvitakki"


# ------------------------------------------------------------------ 'robotti-imuri alle 300'

def test_foreign_marketplaces_are_searched_in_their_own_language():
    d = {x.site.key: x.query for x in used_directs(parsed("robotti-imuri alle 300"))}
    assert d["tori"] == "robotti-imuri"                  # typed in Finnish: kept for the Finnish site
    assert d["blocket"] == "robotdammsugare"             # was 'robotti-imuri' (0 kept of 53)
    assert d["kleinanzeigen"] == "saugroboter"
    assert d["finn"] == d["dba"] == "robotstøvsugere"
    assert all("robotti" not in q for k, q in d.items() if k not in ("tori", "vinted_fi")), d


# ------------------------------------------------------------------ 'fiets'

def test_fiets_is_a_bicycle_not_the_finnish_word_for_the_sport():
    n = parsed("fiets")
    assert n.thing == "bicycle"
    assert dv.market_thing(n, "fi") == "polkupyörä"                   # was 'pyöräily'
    qs = [x[0] for lane in dv.lanes_for(n) for x in dv.lean_plan(n, lane, tokens=10)]
    assert not any("pyöräily" in q for q in qs), qs
    d = dv.plan_direct(n, dv.lanes_for(n), 10, 2)
    urls = [x.url for ds in d.values() for x in ds]
    assert not any("py%C3%B6r%C3%A4ily" in u or "pyöräily" in u for u in urls), urls
    mp = [x for x in d.get("used", []) if x.site.key == "marktplaats"]
    assert not mp or mp[0].query in ("fiets", "") or mp[0].category


# ------------------------------------------------------------------ Road Bikes / baby stroller / sofa / kitchen table

def _search_by_query(monkeypatch, results):
    calls = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country})
        return results
    monkeypatch.setattr(cd, "search", search)
    monkeypatch.setenv("AGORA_DIRECT", "0")
    reader._HINTS.clear()
    return calls


@pytest.mark.parametrize("slug,query,cat", [("road_bike", "Road Bikes", "sp:sg-4-4-3-11"),
                                            ("baby_stroller", "baby stroller", None),
                                            ("sofa", "sofa", None),
                                            ("kitchen_table", "kitchen table", None)])
def test_bulky_hunt_in_finland_reads_no_us_shops(monkeypatch, slug, query, cat):
    rows = [{"url": r["url"], "title": r["title"]} for r in FIX[slug] if r["lane"] == "new"]
    calls = _search_by_query(monkeypatch, rows)
    n = N.parse_need_rules(query)
    N.categorize(n, cat) if cat else N.categorize(n)
    assert dv.need_bulky(n)

    async def run():
        return [e async for e in dv.discover(n, tokens=10)]
    events = asyncio.run(run())
    new_calls = [c for c in calls if c["query"] in {x[0] for x in dv.lean_plan(n, "new", 10)}]
    assert new_calls and all(c["country"] == "fi" for c in new_calls)       # the English query too
    emitted = [e.data["url"] for e in events if e.type == "source" and e.data.get("lane") == "new"]
    assert emitted and not any(dv.us_shop(u) for u in emitted), [u for u in emitted if dv.us_shop(u)]
    for u in ("https://www.ikea.com/us/en/p/skogsta-dining-table-acacia-black-70419264/",
              "https://www.specialized.com/us/en/shop/bikes/road-bikes", "https://www.wayfair.com/x",
              "https://www.nordstrom.com/browse/baby/gear/strollers", "https://recycleabicycle.nyc/"):
        assert dv.us_shop(u)
    assert not dv.us_shop("https://www.ikea.com/fi/fi/p/x-70419264/")


def test_ikea_category_page_is_read_from_the_home_store():
    assert dv.localize("https://www.ikea.com/us/en/cat/dining-tables-21825/", "fi") == \
        "https://www.ikea.com/fi/fi/cat/dining-tables-21825/"


# ------------------------------------------------------------------ 'samsng galaxy s24 ultra'

def test_brand_typos_are_corrected_before_searching():
    assert N.correct_spelling("samsng galaxy s24 ultra") == ("samsung galaxy s24 ultra", [("samsng", "samsung")])
    assert N.correct_spelling("iphnoe 13")[0] == "iphone 13"
    for q in ("phone case", "apple watch", "racer bike", "phillips screwdriver", "kahvinkeitin", "sofa",
              "Umzugsfirma Hamburg", "razor"):
        assert N.correct_spelling(q) == (q, []), q
    n = N.parse_need_rules("samsng galaxy s24 ultra")
    assert n.thing == "samsung galaxy s24 ultra"
    d = dv.plan_direct(n, dv.lanes_for(n), 10, 2)
    assert not any("samsng" in x.url for ds in d.values() for x in ds)


def test_hunt_says_what_it_searched_for():
    async def disc(need):
        yield Event("lane", {"lane": "new", "queries": [need.thing]})

    async def go():
        kw = fk.kwargs(discover=disc)
        kw.pop("parse_need")
        return [e async for e in hunt_mod.hunt("samsng galaxy s24 ultra", **kw, siblings=False, longtail=False,
                                               lookalikes=False)]
    need_ev = next(e for e in asyncio.run(go()) if e.type == "need").data
    assert need_ev["corrected"] == {"typed": "samsng galaxy s24 ultra", "searched": "samsung galaxy s24 ultra",
                                    "words": [{"from": "samsng", "to": "samsung"}]}
    assert need_ev["need"]["thing"] == "samsung galaxy s24 ultra"
