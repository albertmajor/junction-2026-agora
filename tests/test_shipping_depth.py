"""Depth (more than page 1), market size, EU-wide scope and cross-border shipping (agora.shipping).
tori pages captured live 14 Nov ("kaupunkipyörä kori": 117 listings, 53 per page; page 9 is past the end),
trimmed to their meta description + JSON-LD."""
from __future__ import annotations

import asyncio
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, reader, shipping
from agora import marketplaces as m
from agora.judge import judge
from agora.models import Need, Offer, Thing

FIX = pathlib.Path(__file__).parent / "fixtures"
BIKE = Need(raw="city bike with basket", thing="city bike")
AIRPODS = Need(raw="airpods pro 2", thing="airpods pro 2")
TORI = "https://www.tori.fi/recommerce/forsale/search?q=kaupunkipy%C3%B6r%C3%A4+kori"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGORA_DIRECT", "1")
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    reader.MARKET.clear()
    yield
    reader._transport = None


# ------------------------------------------------------------------ depth: tori pages 2..N, free

def test_tori_reads_every_page_until_the_stated_total_is_covered(monkeypatch):
    asked: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        asked.append(str(r.url))
        page = r.url.params.get("page", "1")
        f = FIX / f"tori_kaupunkipyora-kori_p{page}.html"
        if not f.exists():
            f = FIX / "tori_kaupunkipyora-kori_p9.html"
        return httpx.Response(200, text=f.read_text(), headers={"content-type": "text/html"})
    reader._transport = httpx.MockTransport(handler)
    need = Need(raw="kaupunkipyörä kori", thing="kaupunkipyörä kori")
    got, via = asyncio.run(reader.read_with_reason(TORI, need, lane="used", paid=False, expand_lists=True))
    assert via == "jsonld" and isinstance(got, list)
    assert len(asked) == 3                       # 117 listings / 53 a page = 3 pages, then it stops
    assert len(got) > 53                         # more than page 1 (was 20)
    assert len({o.url for o in got}) == len(got)
    assert {o.raw.get("page", 1) for o in got} >= {1, 2}
    mk = reader.MARKET[TORI]
    assert mk["total"] == 117 and mk["pages"] == 3 and mk["read"] == len(got) and mk["country"] == "fi"
    assert all(o.raw["market"] is mk and o.raw["site"] == "tori" for o in got)
    summary = reader.market_for([TORI, "https://elsewhere.example/"])
    assert summary["total"] == 117 and summary["read"] == len(got)
    assert summary["sources"][0]["domain"] == "tori.fi" and summary["sources"][0]["country"] == "FI"


def test_tori_stops_when_a_page_has_no_listings(monkeypatch):
    asked: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        asked.append(str(r.url))
        page = r.url.params.get("page", "1")
        f = FIX / ("tori_kaupunkipyora-kori_p1.html" if page == "1" else "tori_kaupunkipyora-kori_p9.html")
        text = f.read_text().replace("117 ilmoitusta", "5000 ilmoitusta")
        return httpx.Response(200, text=text, headers={"content-type": "text/html"})
    reader._transport = httpx.MockTransport(handler)
    need = Need(raw="kaupunkipyörä kori", thing="kaupunkipyörä kori")
    got, _ = asyncio.run(reader.read_with_reason(TORI, need, lane="used", paid=False, expand_lists=True))
    assert len(asked) <= 1 + reader.FREE_PAGE_CONCURRENCY      # one empty batch, then no more
    assert reader.MARKET[TORI]["total"] == 5000 and reader.MARKET[TORI]["pages"] == 1


def test_page_urls():
    s = m.SITES
    assert m.page_url(s["kleinanzeigen"], "https://www.kleinanzeigen.de/s-citybike/k0", 3) == \
        "https://www.kleinanzeigen.de/s-seite:3/citybike/k0"
    assert m.page_url(s["marktplaats"], "https://www.marktplaats.nl/q/stadsfiets/", 2) == \
        "https://www.marktplaats.nl/q/stadsfiets/p/2/"
    assert m.page_url(s["blocket"], "https://www.blocket.se/recommerce/forsale/search?q=stadscykel", 2).endswith(
        "?q=stadscykel&page=2")
    assert m.page_url(s["amazon_de"], "https://www.amazon.de/s?k=x", 2) is None


# ------------------------------------------------------------------ market size

@pytest.mark.parametrize("text,want", [
    ('content="Torista löydät 1 234 ilmoitusta hakusanalla', (1234, False)),
    ("# 1 - 25 von 1.742 Ergebnissen für „airpods pro 2“", (1742, False)),
    ("500+ tulosta.", (500, True)),
    ("3.120 resultaten voor 'stadsfiets'", (3120, False)),
    ("Znaleźliśmy ponad 1000 ogłoszeń", (1000, True)),
    ("12 345 annonser", (12345, False)),
    ("- [Versand möglich1.224](https://x)", None),           # a facet count, not the total
])
def test_market_total(text, want):
    assert m.market_total(text) == want


def test_market_summary_adds_pages_of_one_site():
    s = m.market_summary([
        {"domain": "kleinanzeigen.de", "country": "de", "total": 1742, "read": 25, "pages": 1},
        {"domain": "kleinanzeigen.de", "country": "de", "total": 1742, "read": 25, "pages": 1},
        {"domain": "tori.fi", "country": "fi", "total": 117, "read": 117, "pages": 3},
    ])
    assert s["total"] == 1742 + 117 and s["read"] == 167
    k = next(x for x in s["sources"] if x["domain"] == "kleinanzeigen.de")
    assert k["read"] == 50 and k["pages"] == 2 and k["country"] == "DE"


# ------------------------------------------------------------------ scope

def test_site_query_keeps_the_noun_when_only_descriptors_are_left():
    assert m.site_query("city bike", m.SITES["tori"]) == "kaupunkipyörä"     # was 'city'
    assert m.site_query("city bike", m.SITES["marktplaats"]) == "stadsfiets"
    assert m.site_query("ikea kallax shelf", m.SITES["tori"]) == "ikea kallax"


def test_scope_bulky_is_near_you_first_and_small_is_eu_wide():
    bike = m.scope_for("city bike", None, "fi")
    assert bike["scope"] == "home" and bike["country"] == "FI" and bike["bulky"]
    assert "near you in Finland" in bike["reason"] and "€60–120" in bike["reason"]
    pods = m.scope_for("airpods pro 2", None, "fi")
    assert pods["scope"] == "eu" and pods["eu_included"] and not pods["bulky"]


# ------------------------------------------------------------------ delivery + shipping estimates

@pytest.mark.parametrize("text,site,want", [
    ("Citybike 28 Zoll 120 € VB Nur Abholung", "kleinanzeigen", "pickup"),
    ("Citybike 28 Zoll 120 € VB Versand möglich", "kleinanzeigen", "ships"),
    ("Citybike 28 Zoll 120 € VB", "kleinanzeigen", "pickup"),        # kleinanzeigen says 'Versand möglich' or nothing
    ("Stadsfiets met mand € 90 Ophalen", "marktplaats", "pickup"),
    ("Stadsfiets met mand € 90 Ophalen of Verzenden", "marktplaats", "ships"),
    ("Stadscykel endast avhämtning", "blocket", "pickup"),
    ("pickup only, no shipping", "", "pickup"),
    ("anything", "vinted_de", "ships"),
    ("Stadscykel 900 kr", "blocket", None),
])
def test_delivery_of(text, site, want):
    assert m.delivery_of(text, site) == want


def test_estimates_are_honest_ranges():
    e = shipping.estimate("bike", "de", "fi")
    assert (e["low"], e["high"]) == (60, 120) and e["text"] == "€60–120" and "estimate" in e["basis"]
    assert shipping.estimate("bike", "fi", "fi") is None                  # domestic: no cross-border line
    near = shipping.estimate("bike", "se", "fi")
    far = shipping.estimate("bike", "es", "fi")
    assert near["high"] < e["high"] < far["high"]
    assert shipping.size_class("ikea kallax shelf") == "furniture"
    assert shipping.size_class("airpods pro 2") == "small"
    assert shipping.size_class("iphone 15 128gb") == "phone"


def _listing(url, source, price, site, title="Citybike Damen 28 Zoll mit Korb", **raw) -> Offer:
    return Offer(url=url, source=source, title=title, price=price, currency="EUR", price_eur=price,
                 condition="used", read_via="contextdev_markdown_split",
                 raw={"site": site, "from_list_page": f"https://{source}/s", **raw})


def test_pickup_abroad_is_shown_but_never_the_pick_and_foreign_shipping_is_estimated():
    pickup = _listing("https://www.kleinanzeigen.de/s-anzeige/a/1", "kleinanzeigen.de", 40, "kleinanzeigen",
                      delivery="pickup")
    home = _listing("https://www.tori.fi/recommerce/forsale/item/1", "tori.fi", 150, "tori",
                    title="Kaupunkipyörä kori 28")
    home2 = _listing("https://www.tori.fi/recommerce/forsale/item/2", "tori.fi", 170, "tori",
                     title="Naisten kaupunkipyörä korilla")
    ships = _listing("https://www.kleinanzeigen.de/s-anzeige/b/2", "kleinanzeigen.de", 110, "kleinanzeigen",
                     delivery="ships")
    v = judge(BIKE, [Thing(id="t", name="city bike", offers=[pickup, home, home2, ships])], history=False)
    assert v.best_offer_url not in (pickup.url, ships.url)              # bulky: home is the pickable set
    assert v.best_offer_url == home.url
    assert any(f.startswith("pickup only, abroad (DE)") for f in pickup.flags)
    assert pickup.shipping_eur is None and pickup.raw["pickup_abroad"]
    assert ships.shipping_eur == 90 and ships.raw["shipping_est"]["text"] == "€60–120"
    assert any("est. €60–120" in label for label, _ in ships.true_cost.receipt)
    assert any(line.startswith("also in the EU: €200 all in at kleinanzeigen.de") for line in v.lines)
    assert any("pickup only" in line for line in v.lines)
    assert home.shipping_eur is None                                    # home: pickup is fine, no estimate


def test_small_thing_abroad_can_be_the_pick_with_shipping_and_the_vinted_fee_all_in():
    de = _listing("https://www.kleinanzeigen.de/s-anzeige/c/3", "kleinanzeigen.de", 100, "kleinanzeigen",
                  title="AirPods Pro 2 USB-C", delivery="ships")
    fi = _listing("https://www.tori.fi/recommerce/forsale/item/3", "tori.fi", 140, "tori", title="AirPods Pro 2")
    fi2 = _listing("https://www.tori.fi/recommerce/forsale/item/4", "tori.fi", 150, "tori", title="AirPods Pro 2 gen")
    vin = _listing("https://www.vinted.fi/items/5", "vinted.fi", 95, "vinted_fi", title="AirPods Pro 2",
                   price_with_buyer_fee=100.45)
    v = judge(AIRPODS, [Thing(id="t", name="airpods pro 2", offers=[de, fi, fi2, vin])], history=False)
    assert de.shipping_eur == 15 and de.raw["shipping_est"]["text"] == "€10–20"
    assert vin.raw["buyer_fee_eur"] == pytest.approx(5.45)
    assert any(label.startswith("buyer protection fee") for label, _ in vin.true_cost.receipt)
    assert vin.true_cost.extras_eur == pytest.approx(5.45 + 6)        # fee + vinted's domestic label (est.)
    assert v.best_offer_url == vin.url                                  # €106.45 all in < de €115 < tori €140
    assert v.headline.startswith("€106 all in")
    de.raw.pop("shipping_est"); de.shipping_eur = None
    vin.price = vin.price_eur = 130
    vin.raw.pop("buyer_fee_eur")
    v = judge(AIRPODS, [Thing(id="t", name="airpods pro 2", offers=[de, fi, fi2, vin])], history=False)
    assert v.best_offer_url == de.url and de.shipping_eur == 15         # small thing abroad: pickable, €115 all in


def test_kleinanzeigen_citybike_rows_carry_pickup_only_and_the_place():
    """kleinanzeigen.de/s-citybike/k0, captured live 14 Nov (7.664 results, 6.065 of them 'Nur Abholung')."""
    text = (FIX / "md_kleinanzeigen_citybike.md").read_text().split("\n", 1)[1]
    assert m.market_total(text) == (7664, False)
    rows = m.split_rows(text, "", m.SITES["kleinanzeigen"])
    assert len(rows) == 27
    assert sum(r["delivery"] == "pickup" for r in rows) >= 20 and any(r["delivery"] == "ships" for r in rows)
    rose = next(r for r in rows if r["title"].startswith("ROSE Sneak Citybike"))
    assert rose["delivery"] == "ships" and rose["location"] == "42655 Solingen"
    assert all(r["location"] for r in rows[:6])
