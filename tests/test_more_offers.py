"""Round 7: more offers per hunt. Any European city or country is a place (gazetteer), service hunts search in
the local language and inside the country's service marketplaces, directory pages become many providers, a
search snippet stating one rate prices a provider for free, and paid reads go where they yield most.
All offline: searches, page fetches and Context.dev reads are mocked."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from agora import contextdev as cd
from agora import discover as dv
from agora import fx, hunt as hunt_mod, judge, places, reader
from agora.hunt import LaneGate
from agora.models import Event, Need, Offer
from agora.need import parse_need

TILBURG = parse_need("home cleaning tilburg 24m2")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def serve(pages: dict[str, str]) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        html = pages.get(str(r.url))
        if html is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
    reader._transport = httpx.MockTransport(handler)


# ------------------------------------------------------------------ places

@pytest.mark.parametrize("text,name,cc", [
    ("home cleaning tilburg 24m2", "Tilburg", "nl"),
    ("plumber berlin", "Berlin", "de"),
    ("schoonmaker den haag", "Den Haag", "nl"),
    ("klempner münchen", "München", "de"),
    ("cleaner in Nice", "Nice", "fr"),
    ("used bike netherlands", "Netherlands", "nl"),
    ("electrician in eindhoven", "Eindhoven", "nl"),
    ("coiffeur genève", "Genève", "ch"),
])
def test_gazetteer_finds_european_places(text, name, cc):
    got = places.find_place(text)
    assert got is not None and got[0] == name and got[1] == cc


@pytest.mark.parametrize("text", ["nice camera", "reading lamp", "ikea stockholm rug", "sony a7 iii body",
                                  "ikea kallax shelf", "oxford shirt"])
def test_ambiguous_words_are_not_places(text):
    assert places.find_place(text) is None


def test_country_and_language_for_a_place():
    assert places.country_for("Tilburg") == "nl" and places.country_for("Tilburg, Netherlands") == "nl"
    assert places.country_for("nl") == "nl" and places.country_for("Atlantis") is None
    assert places.language_for("Tilburg") == "nl" and places.language_for("Geneva") == "fr"
    assert places.language_for("Lugano") == "it" and places.language_for("Dublin") is None


def test_need_parses_tilburg_as_the_place():
    assert (TILBURG.kind, TILBURG.where, TILBURG.thing) == ("service", "Tilburg", "home cleaning 24m2")
    n = parse_need("schoonmaker den haag")
    assert n.kind == "service" and n.thing == "cleaning" and n.where == "Den Haag"
    assert parse_need("ikea stockholm rug").where is None


# ------------------------------------------------------------------ query plans

def test_service_plan_is_english_local_and_marketplaces():
    plan = dv.lean_plan(TILBURG, "service", tokens=10)
    assert plan[0] == ("home cleaning price per hour Tilburg", "nl")
    assert plan[1] == ("schoonmaker Tilburg prijs per uur", "nl")
    q, c, sites = plan[2]
    assert q == "schoonmaker Tilburg" and c == "nl" and "werkspot.nl" in sites and "helpling.nl" in sites
    assert len(dv.lean_plan(TILBURG, "service", tokens=0)) == 2           # a dry bucket: no marketplace search
    berlin = dv.lean_plan(parse_need("plumber berlin"), "service", tokens=10)
    assert berlin[1][0] == "Klempner Berlin preis pro stunde" and "myhammer.de" in berlin[2][2]


def test_new_lane_gets_a_local_shop_query_when_tokens_allow():
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    plan = dv.lean_plan(need, "new", tokens=10)
    assert plan[1] == ("sony a7 iii body hinta osta", "fi")              # home country: Finnish shops
    assert len(dv.lean_plan(need, "new", tokens=dv.LOCAL_NEW_MIN_TOKENS - 1)) == 1
    nl = dv.lean_plan(Need(raw="x", thing="sony a7 iii", where="Utrecht"), "new", tokens=10)
    assert nl[1] == ("sony a7 iii prijs kopen", "nl")


def test_expected_yield_orders_rates_and_price_lists_then_directories():
    y = dv.expected_yield
    assert y("https://lumi.nl/tilburg", "service", "service", "", "Residential €29 Per Hour") == 3
    assert y("https://www.rohrblitz-berlin.de/preise-sanitaer-heizung-rohrbruch-berlin/", "service", "service") == 3
    assert y("https://jesse-berlin.de/price/", "service", "service") == 3
    assert y("https://www.werkspot.nl/schoonmaak/tilburg", "service", "service") == 2.5
    assert y("https://x.nl/a", "service", "service", "THE BEST 10 HOME CLEANING IN TILBURG") == 2.5
    assert y("https://quote.nl/form", "service", "service", "", "Request a quote") < 1
    assert dv.paid_priority("https://jesse-berlin.de/price/", "service", "service") == 0
    assert dv.paid_priority("https://www.werkspot.nl/x", "service", "service") == 1
    assert not dv.is_service_directory("https://www.kleinanzeigen.de/s-putzfrau/k0")   # a goods marketplace


def test_a_directory_that_listed_no_prices_is_read_last_next_time():
    from agora import domainstats
    url = "https://www.blauarbeit.de/klempner/branchenbuch/berlin"
    assert dv.paid_priority(url, "service", "service") == 1
    domainstats.note_list_yield("blauarbeit.de", 0)
    assert domainstats.list_yield("blauarbeit.de") == 0
    assert dv.paid_priority(url, "service", "service") == 3          # after even the pages without a rate
    domainstats.note_list_yield("werkspot.nl", 6)
    assert dv.paid_priority("https://www.werkspot.nl/x", "service", "service") == 1


def _fake_search(monkeypatch, results):
    calls: list[dict] = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country, **kw})
        return results(query, kw)
    monkeypatch.setattr(cd, "search", search)
    return calls


def test_service_discover_sends_marketplace_sites_and_reads_directories_first(monkeypatch):
    def results(query, kw):
        if kw.get("include_domains"):
            return [{"url": "https://www.werkspot.nl/schoonmaakbedrijven/tilburg", "title": "Schoonmaakbedrijven Tilburg"}]
        if "schoonmaker" in query:
            return [{"url": "https://lumi.nl/tilburg", "title": "Lumi schoonmaak",
                     "highlights": {"highlights": ["Huishoudelijke hulp €24 per uur"]}}]
        return [{"url": "https://quote.nl/tilburg", "title": "Cleaning Tilburg"},
                {"url": "https://www.yelp.com/search?cflt=homecleaning&find_loc=Tilburg",
                 "title": "THE BEST 10 HOME CLEANING IN TILBURG"},
                {"url": "https://www.housecallpro.com/x", "title": "House cleaning prices: a guide"}]
    calls = _fake_search(monkeypatch, results)

    async def go():
        return [e async for e in dv.discover(TILBURG, tokens=10, settle_s=0.5)]
    events = asyncio.run(go())
    assert any(c.get("include_domains") and "werkspot.nl" in c["include_domains"] for c in calls)
    assert all(c["country"] == "nl" for c in calls)
    lane = next(e for e in events if e.type == "lane")
    assert len(lane.data["queries"]) == 3 and "werkspot.nl" in lane.data["sites"]
    sources = [e.data["url"] for e in events if e.type == "source"]
    assert sources[0] == "https://lumi.nl/tilburg"                                             # a stated rate first
    assert sources[1:3] == ["https://www.werkspot.nl/schoonmaakbedrijven/tilburg",
                            "https://www.yelp.com/search?cflt=homecleaning&find_loc=Tilburg"]  # then directories
    skips = {e.data["url"]: e.data["reason"] for e in events if e.type == "skip"}
    assert "housecallpro" in next(iter(skips))                          # a guide is still not a source


# ------------------------------------------------------------------ reader: services

def test_snippet_with_one_rate_prices_a_provider_for_free(monkeypatch):
    async def no_paid(*a, **kw):
        raise AssertionError("no paid read for a stated rate")
    monkeypatch.setattr(cd, "extract", no_paid)
    serve({"https://lumi.nl/tilburg": "<html><body>Schoonmaak Tilburg</body></html>"})
    got, via = asyncio.run(reader.read_with_reason(
        "https://lumi.nl/tilburg", TILBURG, paid=False, title="Lumi schoonmaak Tilburg",
        snippet="Huishoudelijke hulp vanaf €24 per uur, ook eenmalig"))
    assert via == "snippet_rate" and got.unit == "hour" and got.price == 24 and got.condition == "service"
    assert got.read_via == "search_highlight"
    assert got.raw["skipped_paid_read"]


@pytest.mark.parametrize("snippet", ["Budget €25–€35 per hour for a regular clean",
                                     "Huishoudelijke hulp, wekelijks | €17 tot €22 per uur",
                                     "Een uurloon tussen de €15.52 - €17.05 per uur",
                                     "Residential €29 Per Hour … Deep cleaning €39 Per Hour",
                                     "Request a quote today"])
def test_ranges_two_rates_or_no_rate_are_not_snippet_offers(snippet):
    assert reader.service_snippet_offer("https://x.nl/a", "X", snippet, TILBURG) is None


def test_directory_page_becomes_one_offer_per_priced_provider(monkeypatch):
    page = "https://www.werkspot.nl/schoonmaakbedrijven/tilburg"
    seen: list[dict] = []

    async def extract(url, schema, instructions=None, **kw):
        seen.append({"schema": schema, "instructions": instructions})
        return {"providers": [
            {"name": "Schoonmaak Ster", "service": "schoonmaak", "price": 27.5, "currency": "EUR", "unit": "hour",
             "min_hours": 3, "url": "/profiel/schoonmaak-ster", "location": "Tilburg"},
            {"name": "Clean & Co", "price": 25, "currency": "EUR", "unit": "hour", "url": None},
            {"name": "No Price BV", "price": None, "currency": None, "unit": None, "url": "/profiel/np"},
            {"name": "Glans", "price": 95, "currency": "EUR", "unit": "job", "url": "https://glans.nl/"},
        ]}
    monkeypatch.setattr(cd, "extract", extract)
    serve({page: "<html><body>" + "<p>werkspot</p>" * 50 + "</body></html>"})
    free, why = asyncio.run(reader.read_with_reason(page, TILBURG, lane="service", paid=False, expand_lists=True))
    assert free is None and "list read" in why
    got, via = asyncio.run(reader.read_with_reason(page, TILBURG, lane="service", expand_lists=True))
    assert via == "contextdev_json" and len(seen) == 1 and seen[0]["schema"] is reader.SERVICE_LIST_SCHEMA
    assert [o.seller for o in got] == ["Schoonmaak Ster", "Clean & Co", "Glans"]
    assert got[0].url == "https://www.werkspot.nl/profiel/schoonmaak-ster" and got[0].raw["min_hours"] == 3
    assert got[1].url == page + "#clean-co"                                  # no own link: kept apart by name
    assert all(o.condition == "service" and o.raw["from_list_page"] == page for o in got)
    assert {o.unit for o in got} == {"hour", "job"}


def test_service_page_read_uses_the_rate_schema_and_min_hours(monkeypatch):
    url = "https://12bclean.nl/schoonmaakbedrijf-tilburg/"
    seen: list = []

    async def extract(u, schema, instructions=None, **kw):
        seen.append(schema)
        return {"page_type": "service", "offers": [
            {"title": "Eenmalige schoonmaak", "price": 32, "currency": "EUR", "unit": "hour", "min_hours": 3,
             "one_time": True},
            {"title": "Wekelijkse schoonmaak", "price": 28, "currency": "EUR", "unit": "hour", "one_time": False}]}
    monkeypatch.setattr(cd, "extract", extract)
    serve({url: "<html><body>Schoonmaakbedrijf Tilburg. Vanaf €28 per uur.</body></html>"})
    got, via = asyncio.run(reader.read_with_reason(url, TILBURG, lane="service"))
    assert via == "contextdev_json" and seen == [reader.SERVICE_SCHEMA]
    assert got.price == 32 and got.raw["tier"] == "one-time" and got.raw["min_hours"] == 3
    tc = judge.service_cost(got, TILBURG)
    assert tc.total_eur == 96 and "minimum 3 h" in tc.receipt[0][0]      # 24 m² is 1 h, the page says 3 h minimum


# ------------------------------------------------------------------ hunt: paid reads by expected yield

def test_lane_gate_honours_priority_inside_a_lane():
    async def run():
        gate = LaneGate(1)
        order: list[str] = []

        async def one(name, prio):
            await gate.acquire("service", False, prio)
            order.append(name)
            await asyncio.sleep(0.01)
            gate.release()
        first = asyncio.create_task(one("first", 2))
        await asyncio.sleep(0)
        rest = [asyncio.create_task(one(n, p)) for n, p in (("quote-form", 2), ("rate", 1), ("directory", 0))]
        await asyncio.gather(first, *rest)
        return order
    assert asyncio.run(run()) == ["first", "directory", "rate", "quote-form"]


def test_service_hunt_takes_snippet_rates_free_and_expands_directories(monkeypatch):
    calls: list[tuple[str, bool]] = []
    directory = "https://www.werkspot.nl/schoonmaakbedrijven/tilburg"

    async def rwr(url, need, *, paid=True, **kw):
        calls.append((url, paid))
        if url.startswith("https://rate"):
            return Offer(url=url, source="rate.nl", title="home cleaning Tilburg", price=25.0, currency="EUR",
                         unit="hour", condition="service", read_via="search_highlight"), "snippet_rate"
        if not paid:
            return None, "search page: needs a list read"
        return [Offer(url=f"{directory}#p{i}", source="werkspot.nl", title=f"home cleaning – P{i}", price=20.0 + i,
                      currency="EUR", unit="hour", condition="service", location="Tilburg", read_via="contextdev_json",
                      raw={"from_list_page": directory}) for i in range(6)], "contextdev_json"
    monkeypatch.setattr(reader, "read_with_reason", rwr)

    async def disc(need, **kw):
        yield Event("source", {"url": directory, "lane": "service"})
        for i in range(3):
            yield Event("source", {"url": f"https://rate{i}.nl/tilburg", "lane": "service"})

    async def go():
        return [e async for e in hunt_mod.hunt("home cleaning tilburg 24m2", discover=disc, persist=False,
                                                lookalikes=False, siblings=False, provisional_after=None)]
    events = asyncio.run(go())
    offers = [e for e in events if e.type == "offer"]
    assert len(offers) == 9                                              # 6 providers + 3 stated rates
    assert [u for u, p in calls if p] == [directory]                    # the only paid read
    verdict = next(e for e in events if e.type == "verdict")
    assert "24 m²" in verdict.data["verdict"]["headline"]


def test_lenient_fallback_takes_the_first_rate_but_never_a_unitless_price():
    two = "Residential €29 Per Hour … Deep cleaning €39 Per Hour"
    got = reader.service_snippet_offer("https://x.nl/a", "X schoonmaak", two, TILBURG, lenient=True)
    assert got.price == 29 and got.unit == "hour"
    assert reader.service_snippet_offer("https://x.nl/a", "X", "Cleaning from €199", TILBURG, lenient=True) is None
    guide = "Kosten schoonmaker - ontdek actuele prijzen"
    assert reader.service_snippet_offer("https://x.nl/a", guide, "€18 per uur", TILBURG, lenient=True) is None


def test_job_ads_are_not_providers():
    assert dv.job_ad("https://nl.indeed.com/q-schoonmaak-tilburg-vacatures.html")
    assert dv.job_ad("https://hups.example/x", "Vacature huishoudelijke hulp | Tilburg")
    assert dv.job_ad("https://staff.example/x", "Cleaning staff", "€15.52 gross base/hour")
    assert dv.job_ad("https://www.payscale.com/research/DE/Job=Plumber/Hourly_Rate", "Plumber Hourly Pay in Germany")
    assert not dv.job_ad("https://lumi.nl/tilburg", "Lumi schoonmaak", "Huishoudelijke hulp €24 per uur")


def test_directory_page_whose_fetch_fails_still_waits_for_its_list_read(monkeypatch):
    url = "https://m.yelp.com/search?cflt=homecleaning&find_loc=Tilburg"
    serve({})                                                            # the free fetch gets a 404-less failure
    reader._transport = httpx.MockTransport(lambda r: httpx.Response(403, text="blocked"))
    reader.remember_source(url, "service", "THE BEST 10 HOME CLEANING IN TILBURG", "20EUR/hour. came up to 145 euro")
    got, why = asyncio.run(reader.read_with_reason(url, TILBURG, paid=False, expand_lists=True))
    assert got is None and "list read" in why                            # not a unit-less snippet price
    assert not dv.is_service_directory("https://www.werkspot.nl/profiel/tara-schoonmaakbedrijf")


def test_service_unit_read_from_the_title_when_the_price_has_none():
    assert reader.service_unit_from_title("Gemiddeld uurtarief") == "hour"
    assert reader.service_unit_from_title("3 uur professionele schoonmaakhulp") == "job"
    assert reader.service_unit_from_title("Huishoudelijke hulp Tilburg gezocht?") is None
