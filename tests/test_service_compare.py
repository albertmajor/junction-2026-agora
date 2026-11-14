"""Service hunts compare like with like. From two live streams (plumber Berlin, home cleaning Tilburg 24 m²):
a radiator-bleeding price, an admin fee or a sofa clean must never win; open-ended trades are compared on a
standard call (hourly rate x 1 h + call-out fee, an estimate); one directory counts once in medians; a voucher
is labelled a deal. All offline."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, judge, reader, resolve
from agora.models import Offer
from agora.need import parse_need

PLUMBER = parse_need("plumber berlin")
TILBURG = parse_need("home cleaning tilburg 24m2")
SPARKY = parse_need("electrician helsinki")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def svc(source: str, title: str, price: float, unit: str | None, url: str | None = None, **raw) -> Offer:
    return Offer(url=url or f"https://{source}/preise", source=source, title=title, price=price, currency="EUR",
                 price_eur=price, condition="service", unit=unit, location=raw.pop("location", None),
                 read_via="contextdev_json", raw=dict(raw))


def run(need, offers):
    things = resolve.resolve(need, offers)
    return things, judge.judge(need, things, history=False)


# ------------------------------------------------------------------ line classification

@pytest.mark.parametrize("title,unit,kind", [
    ("Heizung entlüften", "job", "task"),
    ("Gasheizung Jahreswartung", "job", "task"),
    ("Verstopfungen in Grundleitungen", "job", "task"),
    ("Service- und Verwaltungspauschale", "job", "fee"),
    ("Anfahrtspauschale Berlin", "job", "callout"),
    ("Kurzbesuch", "visit", "callout"),
    ("Visit cost", "visit", "callout"),
    ("Klempner Stundensatz", "hour", "main"),
    ("Notdienst Stundensatz (nachts)", "hour", "premium"),
])
def test_plumber_price_lines(title, unit, kind):
    assert resolve.service_line_kind(PLUMBER, title, unit) == kind


@pytest.mark.parametrize("title,unit,kind", [
    ("Furniture cleaning at your home - Bankstelreinigers", "m2", "off_topic"),
    ("Laundry and ironing service at home", "hour", "off_topic"),
    ("Urgent cleaning jobs, deep cleaning, or work carried out during the weekend", "hour", "off_topic"),
    ("Spoedschoonmaak in het weekend", "hour", "premium"),
    ("End-of-tenancy clean", "job", "off_topic"),
    ("Witte werkster Tilburg gezocht?", "hour", "main"),
    ("3 uur professionele schoonmaakhulp", "job", "main"),
    ("house cleaning – Ines", "hour", "main"),
    ("Thuis schoonmaken", "hour", "main"),
])
def test_cleaning_price_lines(title, unit, kind):
    assert resolve.service_line_kind(TILBURG, title, unit) == kind


def test_a_named_task_is_the_job_when_asked():
    need = parse_need("plumber berlin heizung entlüften")
    assert resolve.service_line_kind(need, "Heizung entlüften", "job") == "main"
    assert not resolve.is_open_trade(need) and resolve.is_open_trade(PLUMBER) and resolve.is_open_trade(SPARKY)


# ------------------------------------------------------------------ reader: one provider page -> one comparable offer

def serve(pages: dict[str, str]) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        html = pages.get(str(r.url))
        if html is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
    reader._transport = httpx.MockTransport(handler)


def test_provider_price_list_becomes_hourly_rate_plus_callout(monkeypatch):
    url = "https://www.werkstueck-berlin.de/leistungen/preisliste/"   # a provider (kennstdueinen.de is a directory)

    async def extract(u, schema, instructions=None, **kw):
        return {"page_type": "service", "offers": [
            {"title": "Heizung entlüften", "price": 35, "currency": "EUR", "unit": "job"},
            {"title": "Service- und Verwaltungspauschale", "price": 32, "currency": "EUR", "unit": "job"},
            {"title": "Anfahrt", "price": 39, "currency": "EUR", "unit": "visit"},
            {"title": "Arbeitsstunde Klempner", "price": 65, "currency": "EUR", "unit": "hour"},
            {"title": "Notdienst Stundensatz", "price": 110, "currency": "EUR", "unit": "hour"}]}
    monkeypatch.setattr(cd, "extract", extract)
    serve({url: "<html><body>Klempner Berlin Preise</body></html>"})
    got, via = asyncio.run(reader.read_with_reason(url, PLUMBER, lane="service", title="Klempner Berlin Preise"))
    assert via == "contextdev_json"
    assert got.title == "Arbeitsstunde Klempner" and got.price == 65 and got.unit == "hour"
    assert got.raw["callout_fee"] == 39 and got.raw["line_kind"] == "main"
    kinds = {x["title"]: x["kind"] for x in got.raw["other_prices"]}
    assert kinds["Heizung entlüften"] == "task" and kinds["Service- und Verwaltungspauschale"] == "fee"
    tc = judge.service_cost(got, PLUMBER)
    assert tc.total_eur == 104 and tc.receipt == [("€65/h x 1 h (typical call, est.)", 65.0), ("call-out fee", 39.0)]
    assert got.raw["calc"] == "€65/h × 1 h + €39 call-out" and "estimate" in tc.basis


def test_page_of_only_fees_is_no_offer():
    offers = [svc("x.de", "Service- und Verwaltungspauschale", 32, "job"),
              svc("x.de", "Materialpauschale", 12, "job")]
    assert reader.best_service_offer(offers, PLUMBER) is None


# ------------------------------------------------------------------ plumber Berlin stream

def plumber_stream() -> list[Offer]:
    return [
        svc("kennstdueinen.de", "Heizung entlüften", 35, "job", url="https://www.kennstdueinen.de/branche-klempner-356.html",
            location="Berlin"),
        svc("gerahome.com", "Plumbing in Berlin", 60, "hour", url="https://gerahome.com/services/plumbing/in/berlin",
            location="Berlin"),
        svc("fragbabsi.de", "Gasheizung Jahreswartung", 180, "job", url="https://fragbabsi.de/sanitaer",
            page_title="Sanitär Notdienst Klempner"),
        svc("kraft-haustechnik.com", "Service- und Verwaltungspauschale", 32, "job",
            url="https://kraft-haustechnik.com/preise/", page_title="Preise - Klempner Kraft Haustechnik"),
        svc("rohrblitz-berlin.de", "Verstopfungen in Grundleitungen", 129, "job",
            url="https://www.rohrblitz-berlin.de/preise-sanitaer-heizung-rohrbruch-berlin/", location="Berlin",
            page_title="Preise Klempner Berlin"),
        Offer(url="https://jesse-berlin.de/price/", source="jesse-berlin.de", title="Plumbing, Drainlaying",
              price=125, currency="USD", price_eur=113.1, condition="service", unit="hour", location="Berlin"),
    ]


def test_plumber_berlin_compares_a_standard_call_not_a_radiator_bleed():
    offers = plumber_stream()
    by = {o.source: o for o in offers}
    assert resolve.explain(PLUMBER, by["kraft-haustechnik.com"])[1] == "a fee or surcharge, not a price for the job"
    things, v = run(PLUMBER, offers)
    kept = {o.source for t in things for o in t.offers}
    assert "kraft-haustechnik.com" not in kept and "kennstdueinen.de" in kept
    # no page states a call-out fee: each gets the trade's typical one, labelled an estimate (never costed as zero)
    assert v.headline == ("€100 for a standard 1-hour call (estimate) at gerahome.com, €60/h × 1 h + €40 call-out "
                          "(est.).")
    assert v.best_offer_url == "https://gerahome.com/services/plumbing/in/berlin"
    assert by["kennstdueinen.de"].true_cost is None
    assert by["kennstdueinen.de"].raw["not_comparable"].startswith("price for one specific task")
    assert by["jesse-berlin.de"].true_cost.sticker_eur == pytest.approx(113.1)
    assert by["jesse-berlin.de"].true_cost.total_eur == pytest.approx(113.1 + judge.TYPICAL_CALLOUT_EUR)
    assert any(ln.startswith("3 more not compared") and "kennstdueinen.de €35" in ln for ln in v.lines)
    assert not any("€35 per job" in ln for ln in v.lines)


def test_callout_fee_counts_and_a_lone_visit_fee_is_not_a_job():
    cheap_rate = svc("a-klempner.de", "Klempner Stundensatz", 45, "hour", location="Berlin", callout_fee=49,
                     callout_title="Anfahrt")
    plain = svc("b-klempner.de", "Klempner Stundensatz", 70, "hour", location="Berlin")
    visit = svc("werkstueck-berlin.de", "Kurzbesuch", 90, "visit", page_title="Klempner Preisliste Berlin",
                location="Berlin")
    _, v = run(PLUMBER, [cheap_rate, plain, visit])
    # like with like (round-1 judges): a page that states no call-out gets the others' usual one, as an estimate,
    # so knowing less never makes a provider look cheaper
    assert cheap_rate.true_cost.total_eur == 94 and plain.true_cost.total_eur == 119
    assert any(lbl.startswith("call-out fee (est.") for lbl, _ in plain.true_cost.receipt)
    assert v.headline.startswith("€94 for a standard 1-hour call (estimate) at a-klempner.de, €45/h × 1 h + €49 call-out")
    assert visit.true_cost is None and visit.raw["not_comparable"] == "call-out / visit fee only, labour extra"


def test_electrician_uses_the_same_standard_call():
    o = svc("sahko.fi", "Sähköasentaja tuntiveloitus", 58, "hour", location="Helsinki", callout_fee=40)
    _, v = run(SPARKY, [o])
    assert o.true_cost.total_eur == 98
    assert v.headline.startswith("€98 for a standard 1-hour call (estimate) at sahko.fi, €58/h × 1 h + €40 call-out")


# ------------------------------------------------------------------ home cleaning Tilburg stream

YOOPIES = "https://en.yoopies.nl/cleaning/tilburg"


def tilburg_stream() -> list[Offer]:
    people = [("Mohamad", 21), ("Ines", 13.5), ("Joaquim", 21), ("Jenny", 21), ("Justyna", 26), ("Stephanie", 26),
              ("Leonardo", 19), ("Ananya", 18), ("Assia", 15), ("Ferna", 16)]
    return [
        svc("ikzoekeenschoonmaakster.nl", "Schoonmaakster Tilburg gezocht?", 18, "hour",
            url="https://www.ikzoekeenschoonmaakster.nl/schoonmaakster-tilburg"),
        svc("bankstelreinigers.nl", "Furniture cleaning at your home - Bankstelreinigers", 3, "m2",
            url="https://bankstelreinigers.nl/en/"),
        svc("socialdeal.nl", "3 uur professionele schoonmaakhulp", 19, "job",
            url="https://www.socialdeal.nl/deals/tilburg/schoonmaak"),
        svc("greenmaidcleaners.nl", "Essential Home Cleaning", 25, "hour", url="https://greenmaidcleaners.nl/"),
        svc("yoojo.nl", "Thuis schoonmaken", 13, "hour", url="https://yoojo.nl/huishouden/schoonmaker/tilburg"),
        svc("zoofy.nl", "Urgent cleaning jobs, deep cleaning, or work carried out during the weekend", 70, "hour",
            url="https://zoofy.nl/en/cleaning/"),
        svc("huishoudelijkehulpdirect.nl", "Laundry and ironing service at home", 17, "hour",
            url="https://huishoudelijkehulpdirect.nl/schoonmaak/"),
        *[svc("en.yoopies.nl", f"house cleaning – {n}", p, "hour", url=f"https://en.yoopies.nl/profile/{n.lower()}",
              from_list_page=YOOPIES, step="contextdev_providers") for n, p in people],
    ]


def test_tilburg_drops_other_services_and_labels_the_deal():
    offers = tilburg_stream()
    by = {o.source: o for o in offers}
    assert resolve.explain(TILBURG, by["bankstelreinigers.nl"])[1].startswith("a different service (furniture")
    assert resolve.explain(TILBURG, by["huishoudelijkehulpdirect.nl"])[1].startswith("a different service (laundry")
    things, v = run(TILBURG, offers)
    kept = {o.source for t in things for o in t.offers}
    assert {"bankstelreinigers.nl", "huishoudelijkehulpdirect.nl"}.isdisjoint(kept)
    assert by["zoofy.nl"].true_cost is None                     # urgent / weekend rate: shown, not compared
    # the voucher is a fair job price for 24 m², labelled a deal; the best regular price is right under it
    assert v.headline == "€19 for one 24 m² clean at socialdeal.nl (deal), 3 h for €19."
    assert v.lines[0] == "without a deal: €26 at yoojo.nl, €13/h × 2 h"
    assert any(ln.startswith("socialdeal.nl (deal):") for ln in v.lines)
    assert sum(ln.startswith("en.yoopies.nl") for ln in v.lines) <= 2


def test_tilburg_without_the_deal_headline_shows_job_price_and_hourly_rate():
    offers = [o for o in tilburg_stream() if o.source != "socialdeal.nl"]
    _, v = run(TILBURG, offers)
    assert v.headline == "€26 for one 24 m² clean at yoojo.nl, €13/h × 2 h."


def test_one_directory_counts_once_in_the_service_median():
    offers = [o for o in tilburg_stream() if o.unit == "hour" and o.source not in ("zoofy.nl",
                                                                                   "huishoudelijkehulpdirect.nl")]
    prices = judge.market_prices(offers, "service")
    # ikzoek 18, greenmaid 25, yoojo 13 + yoopies (10 cleaners, median 20) = 4 voices, not 13
    assert sorted(prices) == [13, 18, 20, 25]


def test_an_hourly_rate_is_not_judged_against_a_per_m2_price():
    o = svc("yoojo.nl", "Thuis schoonmaken", 18, "hour")
    peers = [o, svc("a.nl", "Schoonmaak", 3, "m2"), svc("b.nl", "Schoonmaak", 2.5, "m2"),
             svc("c.nl", "Schoonmaak", 3.5, "m2")]
    _, flags = judge.assess_trust(o, peers)
    assert not any("median" in f for f in flags)


def test_household_help_wanted_ads_on_a_directory_are_not_providers():
    page = "https://www.hulp.nl/huishoudelijke-hulp/tilburg"
    data = {"providers": [
        {"name": "Huishoudelijke hulp gezocht in Goirle", "service": "huishoudelijke hulp", "price": 20,
         "currency": "EUR", "unit": "hour", "url": "/oproep/ef4661b1"},
        {"name": "Gezocht: scholier schoonmaakster", "price": 15, "currency": "EUR", "unit": "hour", "url": "/x/1"},
        {"name": "Schoonmaker / Schoonmaakster", "price": 15, "currency": "EUR", "unit": "hour",
         "url": "/oproep/16c55ff2"},
        {"name": "Poetshulp Anja", "service": "huishoudelijke hulp", "price": 18, "currency": "EUR", "unit": "hour",
         "url": "/profiel/anja"}]}
    got = reader.offers_from_providers(data, page, TILBURG)
    assert [o.seller for o in got] == ["Poetshulp Anja"]


def test_deep_clean_is_another_job_and_lines_go_cheapest_first():
    deep = svc("huishoudelijkehulpdirect.nl", "One-off deep clean", 120, "job", one_time=True)
    two_h = svc("zoofy.nl", "Cleaner for two hours", 99, "job", url="https://zoofy.nl/schoonmaak/tilburg")
    hourly = svc("yoojo.nl", "Thuis schoonmaken", 13, "hour", url="https://yoojo.nl/huishouden/schoonmaker/tilburg")
    assert resolve.explain(TILBURG, deep)[1].startswith("a different service (deep clean)")
    _, v = run(TILBURG, [deep, two_h, hourly])
    assert v.lines[0].startswith("yoojo.nl:") and v.lines[1].startswith("zoofy.nl:")


def test_electrician_helsinki_pages_name_the_trade_and_ex_vat_rates_get_vat():
    sskt = svc("sskt.fi", "Työveloitus sähkötyö (ALV 0 %)", 60, "hour", url="https://www.sskt.fi/hinnasto/")
    kallio = svc("kallion-sahko.fi", "Sähköurakoinnin ja -töiden hinnasto", 61, "hour",
                 url="https://www.kallion-sahko.fi/hinnasto")
    valora = svc("valorasahko.fi", "Sähköasentaja Helsinki – Valora Sähkö", 62.75, "hour",
                 url="https://valorasahko.fi/sahkoasentaja-helsinki")
    assert resolve.explain(SPARKY, sskt)[1] is None and resolve.explain(SPARKY, kallio)[1] is None
    _, v = run(SPARKY, [sskt, kallio, valora])
    assert sskt.true_cost.sticker_eur == pytest.approx(75.3) and sskt.raw["ex_vat_eur"] == 60
    assert "without VAT" in sskt.true_cost.basis
    assert v.headline.startswith("€101 for a standard 1-hour call (estimate) at kallion-sahko.fi, €61/h × 1 h + €40 "
                                 "call-out (est.)")
