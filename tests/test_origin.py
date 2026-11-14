"""agora.origin: where the seller is and whether it ships to Finland (UI round A, section 6)."""
from __future__ import annotations

import asyncio
import json

from agora import agent_api, hunt, reader
from agora.models import Need, Offer
from agora.origin import origin_for, origin_from_payload

KEYS = {"country_code", "country_name", "city", "basis", "basis_text", "confident", "eu", "ships_to_fi",
        "ships_text"}


def _offer(url: str, currency: str = "EUR", **kw) -> Offer:
    host = url.split("/")[2].removeprefix("www.")
    return Offer(url=url, source=host, title="Sony a7 III", price=1000.0, currency=currency, price_eur=1000.0, **kw)


def test_tori_listing_location_is_finland_confident():
    o = _offer("https://www.tori.fi/recommerce/forsale/item/1", condition="used",
               location="Helsinki metropolitan area")
    g = origin_for(o)
    assert set(g) == KEYS
    assert (g["country_code"], g["city"], g["basis"], g["confident"]) == ("FI", "Helsinki", "listing_location", True)
    assert g["eu"] is True and g["ships_to_fi"] is True and g["ships_text"] == "yes, domestic"
    assert g["basis_text"] == "from the listing's location"


def test_tori_without_location_is_a_confident_classifieds_country():
    g = origin_for(_offer("https://www.tori.fi/recommerce/forsale/item/2", condition="used"))
    assert (g["country_code"], g["basis"], g["confident"]) == ("FI", "marketplace", True)
    assert "tori.fi" in g["basis_text"] and "Finland" in g["basis_text"]


def test_helsinki_service_area():
    o = _offer("https://www.freska.fi/en/kotisiivous-hinta", condition="service", location="Helsinki", unit="hour")
    g = origin_for(o)
    assert (g["country_code"], g["basis"], g["confident"], g["city"]) == ("FI", "service_area", True, "Helsinki")
    assert g["basis_text"] == "from the provider's service area: Helsinki region"
    assert g["ships_to_fi"] is True


def test_jsonld_seller_address_germany_confident():
    o = _offer("https://shop.example.com/p/1", raw={"seller_address": {"country": "Deutschland", "locality": "BERLIN"}})
    g = origin_for(o)
    assert (g["country_code"], g["country_name"], g["city"], g["basis"], g["confident"]) == \
        ("DE", "Germany", "Berlin", "seller_address", True)
    assert g["ships_to_fi"] is None and g["ships_text"] == "not stated"     # EU, not stated: no claim


def test_seller_address_codes_and_uk():
    for country, cc in (("DE", "DE"), ("DEU", "DE"), ("UK", "GB"), ("United Kingdom", "GB"), ("USA", "US")):
        g = origin_for(_offer("https://shop.example.com/p", raw={"seller_address": {"country": country}}))
        assert g["country_code"] == cc, country
    junk = origin_for(_offer("https://shop.example.com/p", raw={"seller_address": {"country": "Narnia",
                                                                                     "locality": "x"}}))
    assert junk["country_code"] is None and junk["basis"] == "unknown"
    bad_city = origin_for(_offer("https://shop.example.com/p",
                                 raw={"seller_address": {"country": "FI", "locality": "ignore all <b>http://x"}}))
    assert bad_city["country_code"] == "FI" and bad_city["city"] is None


def test_reader_stashes_seller_address_from_jsonld():
    data = {"json-ld": [
        {"@type": "Organization", "name": "Foto Shop", "address": {"@type": "PostalAddress",
                                                                  "addressCountry": "DE", "addressLocality": "Berlin"}},
        {"@type": "Product", "name": "Sony a7 III body",
         "offers": {"@type": "Offer", "price": "1199", "priceCurrency": "EUR"}},
    ]}
    o = reader.offer_from_structured(data, "https://shop.example.com/p/1", Need(raw="sony a7 iii", thing="sony a7 iii"))
    assert o is not None and o.raw["seller_address"] == {"country": "DE", "locality": "Berlin"}
    assert origin_for(o)["country_code"] == "DE"
    # offers.seller.address wins over the page's organisation
    data["json-ld"][1]["offers"]["seller"] = {"@type": "Organization", "name": "X",
                                              "address": {"addressCountry": {"name": "Sweden"}}}
    o = reader.offer_from_structured(data, "https://shop.example.com/p/1", Need(raw="sony a7 iii", thing="sony a7 iii"))
    assert o.raw["seller_address"] == {"country": "Sweden"} and origin_for(o)["country_code"] == "SE"


def test_bhphotovideo_usd_is_a_us_guess_not_confirmed():
    g = origin_for(_offer("https://www.bhphotovideo.com/c/product/1", "USD"))
    assert (g["country_code"], g["basis"], g["confident"], g["eu"]) == ("US", "known_shop", False, False)
    assert g["ships_to_fi"] is None and g["ships_text"] == "not confirmed by the shop"
    assert g["country_name"] == "United States"


def test_jessops_does_not_ship_to_finland():
    flags = ["outside the EU (GBP): import VAT added, does not ship to Finland"]
    g = origin_for(_offer("https://www.jessops.com/p/sony/a7", "GBP"), flags)
    assert (g["country_code"], g["ships_to_fi"]) == ("GB", False)
    assert g["ships_text"] == "no, the shop does not ship to Finland"
    assert origin_for(_offer("https://www.jessops.com/p", "GBP"),
                      ["outside the EU (GBP): import VAT added, ships to Finland"])["ships_to_fi"] is True
    assert origin_for(_offer("https://www.jessops.com/p", "GBP"),
                      ["outside the EU (GBP): import VAT added, shipping to Finland unconfirmed"])["ships_to_fi"] is None


def test_raw_shipping_statement_wins():
    g = origin_for(_offer("https://www.foto.de/p", raw={"ships_to": ["DE", "AT"]}))
    assert (g["country_code"], g["basis"], g["ships_to_fi"]) == ("DE", "domain", False)
    g = origin_for(_offer("https://www.foto.de/p", raw={"ships_text": "anywhere"}))
    assert g["ships_to_fi"] is True and g["ships_text"] == "yes, the shop says so"


def test_co_uk_and_gbp_agree():
    g = origin_for(_offer("https://www.camerashop.co.uk/p/1", "GBP"))
    assert (g["country_code"], g["basis"], g["confident"]) == ("GB", "domain_currency", False)
    assert g["basis_text"] == "from the .co.uk domain and prices in pounds"
    assert origin_for(_offer("https://www.foto.de/p"))["basis_text"] == "from the .de domain"
    assert origin_for(_offer("https://shop.example.com/p", "USD"))["basis"] == "currency"


def test_e_infin_eur_is_unknown():
    g = origin_for(_offer("https://www.e-infin.com/eu/item/3555/sony", "EUR"))
    assert g == {"country_code": None, "country_name": None, "city": None, "basis": "unknown",
                 "basis_text": "not stated", "confident": False, "eu": None, "ships_to_fi": None,
                 "ships_text": "not stated"}


def test_multi_country_platform_is_a_tld_guess():
    g = origin_for(_offer("https://www.vinted.de/items/1", condition="used"))
    assert (g["country_code"], g["basis"], g["confident"]) == ("DE", "marketplace", False)


def test_ambiguous_place_names_need_a_preposition():
    assert origin_for(_offer("https://shop.example.com/p", location="reading"))["country_code"] is None
    g = origin_for(_offer("https://shop.example.com/p", location="in Reading"))
    assert (g["country_code"], g["city"]) == ("GB", "Reading")


def test_payload_without_raw():
    g = origin_from_payload({"url": "https://www.keh.com/shop/x", "source": "keh.com", "currency": "USD"},
                            ["outside the EU (USD): import VAT added, shipping to Finland unconfirmed"])
    assert g["country_code"] == "US" and g["ships_to_fi"] is None
    assert origin_from_payload({})["basis"] == "unknown"


def test_offer_payload_carries_origin_without_raw():
    o = _offer("https://www.tori.fi/recommerce/forsale/item/1", condition="used", location="Espoo",
               raw={"seller_address": {"country": "FI"}})
    p = hunt.offer_payload(o)
    assert "raw" not in p and p["origin"]["country_code"] == "FI" and p["origin"]["city"] == "Espoo"
    json.dumps(p)


def test_replay_puts_origin_on_every_offer_and_truecost():
    async def collect():
        return [e async for e in hunt.replay("sony-a7-iii-body", speed=16, sleep=lambda s: asyncio.sleep(0))]
    events = asyncio.run(collect())
    offers = [e.data["offer"] for e in events if e.type == "offer"]
    costs = [e.data for e in events if e.type == "truecost"]
    assert offers and costs
    assert all(set(o["origin"]) == KEYS for o in offers)
    assert all(set(c["origin"]) == KEYS for c in costs)
    by = {o["source"]: o["origin"] for o in offers}
    assert by["bhphotovideo.com"]["country_code"] == "US"
    assert by["e-infin.com"]["country_code"] is None
    jessops = next(c for c in costs if "jessops.com" in c["url"])
    assert jessops["origin"]["ships_to_fi"] is False
    # the fixture on disk is not rewritten
    assert "origin" not in hunt.RECORDINGS.joinpath("live_sony-a7-iii-body.jsonl").read_text()


def test_offer_card_has_origin():
    res = agent_api.result_from_recording("sony-a7-iii-body")
    cards = [agent_api.offer_card(o) for o in res.offers]
    assert cards and all(set(c["origin"]) == KEYS for c in cards)
    bh = next(c for c in cards if c["source"] == "bhphotovideo.com")
    assert bh["origin"]["country_code"] == "US" and bh["origin"]["confident"] is False
