"""Relevance regressions from the first live hunts (round 6): parts, list pages, generations, services."""
from __future__ import annotations

import pytest

from agora import judge as J
from agora.models import Need, Offer
from agora.resolve import explain, is_accessory, not_an_offer, relevance, resolve, signature


def need(thing: str, kind: str = "product", where: str | None = None) -> Need:
    return Need(raw=thing, thing=thing, kind=kind, where=where,
                conditions=["service"] if kind == "service" else ["new", "refurbished", "used"])


def offer(title: str, price: float, url: str = "https://shop.example/p/1", cond: str = "new", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price,
                 currency="EUR", price_eur=price, condition=cond, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- parts and accessories

@pytest.mark.parametrize("want,title", [
    ("airpods pro 2", "AirPods Pro 2 Ear Tips - 2 sets (Medium)"),
    ("nintendo switch oled", 'OLED Display for Nintendo Switch OLED 7" (Refurbished)'),
    ("nintendo switch oled", "Joy-Con pair for Nintendo Switch"),
    ("dyson v15 vacuum", "Battery for Dyson V15"),
    ("dyson v15 vacuum", "Dyson V15 Detect brush head"),
    ("ps5", "DualSense Controller PS5"),
    ("airpods pro 2", "AirPods Pro 2 MagSafe Charging Case Only"),
])
def test_parts_and_accessories_are_not_the_item(want: str, title: str) -> None:
    n = need(want)
    assert is_accessory(title, n)
    r, why = explain(n, offer(title, 10))
    assert r < 0.5 and why == "accessory, not the item"


@pytest.mark.parametrize("want,title", [
    ("nintendo switch oled", "Nintendo Switch OLED Model Console, White"),
    ("nintendo switch oled", "CONSOLE NINTENDO SWITCH OLED EDITION SPLATOON 3 SWITCH EURO NEW"),
    ("nintendo switch oled", "Nintendo Switch OLED + 2 Joy-Con"),
    ("nintendo switch oled", "Nintendo Switch (OLED-Modell) Weiss"),
    ("airpods pro 2", "Apple AirPods Pro 2 for iPhone"),
    ("airpods pro 2", "Apple AirPods Pro 2 with MagSafe Charging Case (USB-C)"),
    ("macbook air m2", "Apple MacBook Air M2 13.6-inch display 8GB"),
    ("sony a7 iii", "Full frame mirrorless Sony a7 III body"),
    ("ps5 controller", "DualSense Controller PS5"),
])
def test_the_item_itself_is_kept(want: str, title: str) -> None:
    assert explain(need(want), offer(title, 300))[1] is None


# ---------------------------------------------------------------- generations and units

@pytest.mark.parametrize("title,key", [
    ("Apple AirPods Pro (2nd generation)", "apple|airpods2|pro"),
    ("Apple AirPods Pro 2nd Gen USB-C", "apple|airpods2|pro"),
    ("AirPods Pro second generation", "apple|airpods2|pro"),
    ("Apple AirPods Pro Gen 2", "apple|airpods2|pro"),
    ("AirPods Pro 2 - TAKUU 6kk kuin uusi", "apple|airpods2|pro"),          # 6kk = 6-month warranty
    ("CONSOLE NINTENDO SWITCH OLED EDITION SPLATOON 3 SWITCH EURO NEW", "nintendo|oled"),
    ('OLED Display for Nintendo Switch OLED 7" (Refurbished)', "nintendo|oled"),
    ('APPLE MacBook Air (15,3"") space grau CTO, mit 15,3 Zoll Display, Apple M2', "apple|m2|air"),
    ("Apple MacBook Air 13.6-inch M2", "apple|m2|air"),
    ("Sony A7 2nd gen", "sony|a7-2"),
    ("Sony a7 III", "sony|a7-3"),
    ("Canon EOS R6 Mark II", "canon|r6-2"),
    ("Nintendo Switch 2", "nintendo|switch2"),
])
def test_generation_and_unit_parsing(title: str, key: str) -> None:
    assert signature(title).key == key


def test_second_generation_listings_match_airpods_pro_2() -> None:
    n = need("airpods pro 2")
    for t in ("Apple AirPods Pro (2nd generation)", "Apple AirPods Pro 2nd Gen with MagSafe Case"):
        assert explain(n, offer(t, 180))[1] is None, t


def test_model_less_need_rejects_other_models() -> None:
    n = need("nintendo switch oled")
    assert explain(n, offer("Nintendo Switch 2", 450))[0] < 0.5
    assert explain(n, offer("Nintendo Switch 2019", 230))[0] < 0.5
    assert explain(need("airpods pro"), offer("Apple AirPods Pro 2", 180))[1] is None


# ---------------------------------------------------------------- pages that are not one offer

@pytest.mark.parametrize("url,title", [
    ("https://www.tori.fi/recommerce/forsale/search?q=airpods+pro+2&sub_category=1.93.3906", "Apple AirPods Pro Gen 2"),
    ("https://www.kleinanzeigen.de/s-macbook-air-m2/k0", "Macbook Air M2 kleinanzeigen.de"),
    ("https://www.mediamarkt.de/de/list/macbook-air-m2", "APPLE MacBook Air M2"),
    ("https://www.backmarket.ie/en-ie/l/nintendo-game-console/af5c38b9", "Nintendo Switch OLED"),
    ("https://www.refurbed.fr/en-fr/c/nintendo/", "Nintendo Switch OLED"),
    ("https://www.dyson.ie/vacuum-cleaners/cordless/v15/all", "Dyson V15 Detect"),
    ("https://geizhals.de/apple-macbook-air-m2-v103674.html", "Apple MacBook Air M2 ab € 999,00 (2026) | Preisvergleich"),
])
def test_list_search_and_comparison_pages_are_not_offers(url: str, title: str) -> None:
    o = offer(title, 100, url=url, cond="used")
    assert not_an_offer(o)
    r, why = explain(need("macbook air m2" if "mac" in title.lower() else "nintendo switch oled"), o)
    assert r == 0.0 and why


def test_item_pages_are_offers() -> None:
    for url in ("https://www.tori.fi/recommerce/forsale/item/38231132",
                "https://www.amazon.de/-/en/Nintendo-10010900-Switch-OLED-Modell-Weiss/dp/B098RJXBTY",
                "https://www.refurbed.de/en-de/p/apple-airpods-pro-2/104401/?offer=20272763",
                "https://cyclecenter.fi/osasto/pyorat/gravel/pinarello-nytro"):
        assert not_an_offer(offer("x", 1, url=url)) is None, url


def test_sister_shop_feeds_count_once() -> None:
    title = "APPLE MacBook Air 13 M2 8GB 256GB"
    a = offer(title, 1099, url="https://www.mediamarkt.de/de/product/_apple-macbook-air-1.html")
    b = offer(title, 1099, url="https://www.saturn.de/de/product/_apple-macbook-air-1.html")
    things = resolve(need("macbook air m2"), [a, b])
    assert sum(len(t.offers) for t in things) == 1


def test_thing_without_models_is_named_after_the_need() -> None:
    things = resolve(need("ikea kallax shelf"),
                     [offer("IKEA KALLAX Shelf", 30, url="https://www.tori.fi/recommerce/forsale/item/1", cond="used")])
    assert things[0].name == "Ikea Kallax Shelf"


# ---------------------------------------------------------------- services

def test_service_needs_the_job_named() -> None:
    n = need("bike repair", kind="service", where="Helsinki")
    bike = offer("Pinarello NYTRO E5 GRAVEL e-Bike : Sram RIVAL eTap AXS", 6400,
                 url="https://cyclecenter.fi/osasto/pyorat/gravel/pinarello", cond="service")
    assert relevance(n, bike) < 0.5
    assert "not that service" in (explain(n, bike)[1] or "")
    huolto = offer("Huollon arvio vakuutusyhtiölle", 80, url="https://cyclecenter.fi/huolto/", cond="service")
    check = offer("General checkup (seasonal service) — full suspension bike surcharge", 15,
                  url="https://www.luckybirdbikes.fi/en/serviceprices/", cond="service")
    assert relevance(n, huolto) >= 0.5
    assert relevance(n, check) < 0.5          # a surcharge line on top of a job is not a job
    moto = offer("Moottoripyörähuolto", 120, url="https://moto.example/huolto", cond="service")
    assert relevance(n, moto) < 0.5


def test_two_service_prices_are_no_median() -> None:
    n = need("bike repair", kind="service")
    a = offer("Bike service basic", 80, url="https://a.example/huolto", cond="service", unit="job")
    b = offer("Bike repair checkup", 15, url="https://b.example/repair", cond="service", unit="job")
    things = resolve(n, [a, b])
    J.judge(n, things, history=False)
    assert not any(f.startswith("too good to be true") for f in b.flags)


# ---------------------------------------------------------------- resale bound

def test_resale_never_reaches_the_sticker() -> None:
    o = offer("Dyson V15 Detect", 262, url="https://shop.example/p/v15", cond="refurbished")
    peers = [o, offer("Dyson V15 Detect Absolute", 625, url="https://a.example/p/1"),
             offer("Dyson V15 Detect", 620, url="https://b.example/p/2")]
    tc = J.estimate_true_cost(o, peers, 12, J.category_for("dyson v15 vacuum"))
    assert tc is not None and tc.resale_eur is not None
    assert tc.resale_eur <= 0.9 * 262 + 0.01 and tc.per_month_eur > 0


def test_airpods_live_hunt_is_not_won_by_ear_tips() -> None:
    n = need("airpods pro 2")
    offers = [
        offer("AirPods Pro 2 Ear Tips - 2 sets (Medium)", 10,
              url="https://www.apple.com/ie-edu/shop/product/mwu33zm/a/airpods-pro-2-ear-tips-2-sets-medium"),
        offer("Apple AirPods Pro Gen 2", 100, url="https://www.tori.fi/recommerce/forsale/search?q=airpods+pro+2", cond="used"),
        offer("Apple AirPods Pro 2", 180.99, url="https://www.refurbed.de/en-de/p/apple-airpods-pro-2/104401/", cond="refurbished"),
        offer("AirPods Pro 2", 180, url="https://www.backmarket.ie/en-ie/p/airpods-pro-2", cond="refurbished"),
        offer("Apple AirPods Pro (2nd generation)", 229, url="https://www.amazon.de/dp/B0CHWRXH8B"),
    ]
    things = resolve(n, offers)
    kept = {o.url for t in things for o in t.offers}
    assert offers[0].url not in kept and offers[1].url not in kept and offers[4].url in kept
    v = J.judge(n, things, history=False)
    assert "apple.com" not in (v.best_offer_url or "") and "tori.fi" not in (v.best_offer_url or "")
