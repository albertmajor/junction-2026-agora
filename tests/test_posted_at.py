"""When a listing was posted (sort: newest first): read with code from the result cards, offline on saved pages."""
import json
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo

from agora import marketplaces as m
from agora import reader
from agora.hunt import offer_payload
from agora.models import Need, Offer

FX = pathlib.Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 15, 16, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def test_card_words_to_iso():
    P = lambda t, k: m.posted_at(t, k, now=NOW)        # noqa: E731
    assert P("53773 Hennef (Sieg) Heute, 11:37 AirPods Pro 2", "kleinanzeigen") == "2026-11-15T11:37:00+01:00"
    assert P("Gestern, 09:05", "kleinanzeigen") == "2026-11-14T09:05:00+01:00"
    assert P("12.11.2026", "kleinanzeigen") == "2026-11-12"
    assert P("Wrocław, Krzyki - 12 listopada 2026", "olx_pl") == "2026-11-12"
    assert P("Wałbrzych - Dzisiaj o 14:18", "olx_pl") == "2026-11-15T14:18:00+01:00"
    assert P("Odświeżono dzisiaj o 07:36", "olx_pl") == "2026-11-15T07:36:00+01:00"
    assert P("Vandaag", "marktplaats") == "2026-11-15"
    assert P("12 nov 26", "marktplaats") == "2026-11-12"
    assert P("tänään 14:12 Helsinki", "tori") == "2026-11-15T14:12:00+02:00"     # tori's own time zone
    assert P("vor 3 Tagen", "kleinanzeigen") == "2026-11-12"


def test_not_a_date():
    P = lambda t, k: m.posted_at(t, k, now=NOW)        # noqa: E731
    assert P("heute abholen, nur Abholung", "kleinanzeigen") is None     # the seller's words, no time stamp
    assert P("Abholung hier in Berlin", "kleinanzeigen") is None
    assert P("Kaufdatum 12.03.2019", "kleinanzeigen") is None            # years old: a purchase date, not the post
    assert P("iPhone 15 128 GB 2 Jahre alt", "kleinanzeigen") is None
    assert P("31.12.2026", "kleinanzeigen") is None                      # in the future
    assert P("", "olx_pl") is None and P(None, "olx_pl") is None


def test_olx_page_every_card_dated():
    d = json.loads((FX / "olx_pl_telefon_split.json").read_text())
    rows = m.split_rows(d["markdown"], d["html"], m.SITES["olx_pl"])
    assert rows and all(r.get("posted") for r in rows)
    first = {r["title"]: r["posted"] for r in rows}
    assert first["Telefon NOKIA TMF-4SP"] == "2026-11-12"
    offs = reader.offers_from_split(d["markdown"], "", "https://www.olx.pl/oferty/q-telefon/", m.SITES["olx_pl"],
                                    Need(raw="telefon", thing="telefon"))
    assert offs and all(offer_payload(o).get("posted_at") for o in offs)


def test_kleinanzeigen_page_dated_vinted_not():
    md = (FX / "md_kleinanzeigen_airpods-pro-2.md").read_text()
    rows = m.split_rows(md, "", m.SITES["kleinanzeigen"])
    dated = [r for r in rows if r.get("posted")]
    assert len(dated) >= len(rows) - 2
    assert all(r["posted"][:4].isdigit() and r["posted"][4] == "-" for r in dated)
    md = (FX / "md_vinted_fi_airpods-pro-2.md").read_text()
    assert not any(r.get("posted") for r in m.split_rows(md, "", m.SITES["vinted_fi"]))   # vinted cards say no date


def test_plain_rows_and_itemlist():
    need = Need(raw="airpods pro 2", thing="airpods pro 2")
    rows = [{"title": "AirPods Pro 2 USB-C", "url": "https://www.kleinanzeigen.de/s-anzeige/airpods-pro-2/3570916187-172-1697",
             "price": 120, "currency": "EUR", "text": "53773 Hennef (Sieg) Gestern, 18:02 AirPods Pro 2 USB-C 120 €"}]
    o = reader._rows_to_offers(rows, "https://www.kleinanzeigen.de/s-airpods-pro-2/k0", need, None,
                               m.SITES["kleinanzeigen"], 1)[0]
    assert o.raw["posted_at"].startswith(m.posted_at("Gestern, 18:02", "kleinanzeigen")[:10])
    data = {"json-ld": [{"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": {
        "@type": "Product", "name": "AirPods Pro 2", "url": "https://www.tori.fi/recommerce/forsale/item/1234567",
        "datePosted": "2026-11-10T08:30:00+02:00",
        "offers": {"@type": "Offer", "price": "120", "priceCurrency": "EUR"}}}]}]}
    got = reader.offers_from_itemlist(data, "https://www.tori.fi/recommerce/forsale/search?q=airpods", need)
    assert got and got[0].raw["posted_at"] == "2026-11-10T08:30:00+02:00"
    assert reader.iso_posted("not a date") is None and reader.iso_posted("2999-01-01") is None


def test_offer_payload_exposes_posted_at():
    o = Offer(url="https://www.olx.pl/d/oferta/x-ID1.html", source="olx.pl", title="x", price=1, currency="PLN",
              price_eur=0.25, condition="used", raw={"posted_at": "2026-11-12", "step": "markdown_split"})
    d = offer_payload(o)
    assert d["posted_at"] == "2026-11-12" and "raw" not in d
    o.raw = {}
    assert "posted_at" not in offer_payload(o)
