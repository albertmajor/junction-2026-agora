"""Round-3 reader regressions from live eval streams (eval/r3/*.sse) and the pages those hunts fetched
(.cache/html, saved gzipped under tests/fixtures/r3/)."""
from __future__ import annotations

import asyncio
import gzip
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, images, reader
from agora import sources as S
from agora.models import Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures" / "r3"

LUNCH = Need(raw="lunch", thing="lunch restaurant", kind="service", where="Helsinki", conditions=["service"],
             category={"id": "nace:56101", "label": "Restaurants",
                       "path": ["Food, Drink & Restaurants", "Cafés, bars & catering", "Restaurants"],
                       "path_ids": ["food-drink", "nace:56", "nace:561", "nace:56101"], "kind": "service"})
PS5 = Need(raw="ps5", thing="ps5")
KALLAX = Need(raw="ikea kallax shelf", thing="ikea kallax shelf")
ELECTRICIAN = Need(raw="electrician helsinki", thing="electrician", kind="service", where="Helsinki",
                   conditions=["service"])
CLEANING = Need(raw="home cleaning tilburg 24m2", thing="home cleaning", kind="service", where="Tilburg",
                conditions=["service"])


def page(name: str) -> str:
    with gzip.open(FIX / f"{name}.html.gz", "rt") as f:
        return f.read()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def serve(html: str, status: int = 200) -> None:
    reader._transport = httpx.MockTransport(lambda r: httpx.Response(
        status, text=html, headers={"content-type": "text/html; charset=utf-8"}))


def no_paid_reads(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def product(url, **kw):
        calls.append(("product", url))
        return None

    async def extract(url, schema, instr="", **kw):
        calls.append(("extract", url, instr))
        return None
    monkeypatch.setattr(cd, "product", product)
    monkeypatch.setattr(cd, "extract", extract)
    return calls


# ------------------------------------------------------------------ macbook air m2: 'Wie neu' is used

@pytest.mark.parametrize("title", [
    "Wie Neu! Apple MacBook Air 2022 M2, 99% AkkuKapa",
    "Apple MacBook Air 2022 Fast wie Neu",
    "Apple MacBook Air M2 8GB | Wie neu | Extern genutzt | 83%",
    "MacBook Air M2 neuwertig",
    "MacBook Air M2 kuin uusi",
    "MacBook Air M2 som ny",
    "MacBook Air M2 like new",
])
def test_like_new_phrases_on_a_marketplace_are_used(title):
    assert reader.guess_condition("https://www.kleinanzeigen.de/s-anzeige/macbook/3200000000-278-1", title) == "used"


@pytest.mark.parametrize("title", ["MacBook Air M2 NEU OVP", "MacBook Air M2 uusi avaamaton", "Brand new MacBook"])
def test_new_on_a_marketplace_is_still_new(title):
    assert reader.guess_condition("https://www.kleinanzeigen.de/s-anzeige/macbook/3200000000-278-1", title) == "new"


# ------------------------------------------------------------------ airpods pro 2: vinted card labels

def test_vinted_card_label_is_cut_into_title_and_fields():
    t, f = S.split_card_label("Airpods Pro 2, Tuotemerkki: Apple, Malli: AirPods Pro 2 (2022), Kunto: Erittäin hyvä, "
                              "85.0 €, 89.95 €")
    assert t == "Airpods Pro 2" and f == {"tuotemerkki": "Apple", "malli": "AirPods Pro 2 (2022)",
                                         "kunto": "Erittäin hyvä"}
    t, f = S.split_card_label("Naudoti Apple Airpods Pro 2 usb-c, Tuotemerkki: Apple, Kunto: Hyvä, 85.00 €, 89.95 €")
    assert t == "Naudoti Apple Airpods Pro 2 usb-c" and f["kunto"] == "Hyvä"
    assert S.split_card_label("Sony PS5, 825GB") == ("Sony PS5, 825GB", {})


def test_vinted_plain_rows_have_readable_titles_and_keep_grade_and_condition():
    rec = S.for_url("https://www.vinted.fi/catalog?search_text=airpods")
    url = "https://www.vinted.fi/catalog?search_text=airpods%20pro%202"
    rows = S.rows_from_html(page("vinted_fi_airpods"), url, rec, max_rows=50)
    assert len(rows) >= 4
    for r in rows:
        assert "Tuotemerkki" not in r["title"] and "€" not in r["title"], r["title"]
    offers = reader._rows_to_offers(rows, url, Need(raw="airpods pro 2", thing="airpods pro 2"), None, None, 1)
    by = {o.url.split("?")[0].rsplit("/", 1)[-1]: o for o in offers}
    first = by["8866371669-airpods-pro-2nd-generation"]
    assert first.title == "AirPods pro (2nd generation) (AirPods Pro 2 (2022))"
    assert first.raw["grade"] == "Erittäin hyvä" and first.condition == "used" and first.brand == "Apple"
    assert by["10531713591-etui-airpods-pro-2"].condition == "new"          # 'Kunto: Uusi, jossa hintalappu'


# ------------------------------------------------------------------ electrician helsinki: platform logo

def test_platform_logo_is_not_the_providers_photo():
    ok = images.offer_image_ok
    assert not ok("https://tekijatori.fi/wp-content/uploads/2023/03/Tekijatori-logo.svg",
                  "https://tekijatori.fi/profiili/siim-heinaste/", "Siim Heinaste", service=True)
    assert not ok("https://tekijatori.fi/wp-content/uploads/2023/03/Tekijatori-logo.png",
                  "https://tekijatori.fi/profiili/siim-heinaste/", "Siim Heinaste", service=True)
    assert ok("https://paavolainen.com/wp-content/uploads/2024/08/paavolainen-logo-musta.webp",
              "https://paavolainen.com/hinnasto/", "Sähköpalvelu Paavolainen Oy", service=True)
    assert ok("https://x.fi/uploads/team-photo.jpg", "https://x.fi/", "Foo Oy", service=True)
    assert not ok("https://shop.fi/static/logo.png", "https://shop.fi/p/1", None)


def test_annotate_drops_the_platform_logo_from_the_offer():
    o = Offer(url="https://tekijatori.fi/profiili/siim-heinaste/", source="tekijatori.fi", title="Sähköasentaja",
              price=55.0, currency="EUR", price_eur=55.0, condition="service", seller="Siim Heinaste", unit="hour",
              image="https://tekijatori.fi/wp-content/uploads/2023/03/Tekijatori-logo.svg")
    reader._annotate(o, "", "")
    assert o.image is None and o.raw["image_dropped"].endswith("Tekijatori-logo.svg")


# ------------------------------------------------------------------ lunch: lunch-list directories

@pytest.mark.parametrize("name,url,at_least", [
    ("lounasaika_helsinki", "https://www.lounasaika.fi/helsinki", 5),
    ("lunchmenu_helsinki", "https://lunchmenu.fi/en/lunch-lists/helsinki/today", 20),
    ("lounasmenu_helsinki", "https://www.lounasmenu.fi/helsinki/", 12),
])
def test_lunch_list_page_is_cut_into_one_offer_per_restaurant(name, url, at_least):
    offers = reader.offers_from_cards(page(name), url, LUNCH)
    assert len(offers) >= at_least
    assert len({o.url for o in offers}) == len(offers)
    for o in offers:
        assert o.unit == "person" and o.condition == "service" and 3 <= o.price <= 80
        assert "hinnat" not in o.title.lower() and "prices" not in o.title.lower()     # page summary headings


def test_lounasaika_range_becomes_its_low_price():
    offers = reader.offers_from_cards(page("lounasaika_helsinki"), "https://www.lounasaika.fi/helsinki", LUNCH)
    oodi = next(o for o in offers if o.seller == "Food&Co Oodi")
    assert oodi.price == 13.0 and oodi.raw["range_low"] and oodi.raw["price_high"] == 15.0
    assert oodi.url == "https://www.lounasaika.fi/helsinki/food-co-oodi"
    assert not any(o.seller == "Klubi" for o in offers)                      # 'Hinta ei tiedossa'


def test_lunch_directory_read_is_free_and_returns_every_card(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("lunchmenu_helsinki"))
    url = "https://lunchmenu.fi/en/lunch-lists/helsinki/today"
    got, via = asyncio.run(reader.read_with_reason(url, LUNCH, lane="service", expand_lists=True))
    assert via == "plain_cards" and isinstance(got, list) and len(got) >= 20
    assert calls == []


def test_a_providers_own_price_list_is_not_a_directory():
    html = "".join(f"<h3>{s}</h3><p>{p} €/h, alv 0 %</p>" for s, p in
                   [("Sähköasennus", 55), ("Valaistus", 60), ("Vikakorjaus", 65), ("Sähkötarkastus", 70)])
    assert reader.offers_from_cards(html, "https://paavolainen.com/hinnasto/", ELECTRICIAN) == []
    menu = "".join(f"<h3>{d}</h3><p>Lohikeitto 12,50 €</p>" for d in ("Maanantai", "Tiistai", "Keskiviikko"))
    assert reader.offers_from_cards(menu, "https://ravintola.fi/lounas", LUNCH) == []


# ------------------------------------------------------------------ ps5: shop category pages

@pytest.mark.parametrize("name,url", [
    ("verkkokauppa_ps5_catalog", "https://www.verkkokauppa.com/en/catalog/playstation-5-consoles/playstation-5-consoles"),
    ("gigantti_ps5", "https://www.gigantti.fi/gaming/pelikonsolit-ja-tarvikkeet/playstation/ps5-playstation-5-konsolit"),
])
def test_shop_category_page_is_one_list_read_not_a_product_read(monkeypatch, name, url):
    html = page(name)
    assert reader.shop_list_page(url, html, reader._extruct(html, url))
    calls: list[tuple] = []

    async def product(u, **kw):
        calls.append(("product", u))
        return None

    async def extract(u, schema, instr="", **kw):
        calls.append(("extract", u, schema is reader.LIST_SCHEMA))
        return {"listings": [
            {"title": "Sony PlayStation 5 Pro 2TB", "price": 799.0, "currency": "EUR",
             "url": "/fi/product/123456/Sony-PlayStation-5-Pro", "condition": "new"},
            {"title": "Sony PlayStation 5 Slim Digital Edition 825GB", "price": 449.0, "currency": "EUR",
             "url": "/fi/product/234567/Sony-PlayStation-5-Slim-Digital", "condition": "new"}]}
    monkeypatch.setattr(cd, "product", product)
    monkeypatch.setattr(cd, "extract", extract)
    serve(html)
    got, via = asyncio.run(reader.read_with_reason(url, PS5, lane="new", expand_lists=True))
    assert calls == [("extract", url, True)]                     # one paid read, the list schema
    assert via == "contextdev_json" and len(got) == 2 and all(o.raw.get("shop_list_page") for o in got)
    assert {o.condition for o in got} == {"new"}


def test_product_pages_are_never_shop_list_pages():
    url = "https://www.ikea.com/fi/fi/p/kallax-hylly-valkoinen-70301537/"
    html = page("ikea_kallax_fi_70301537")
    assert not reader.shop_list_page(url, html, reader._extruct(html, url))
    assert not reader.shop_list_page("https://shop.fi/collections/x/products/y", "<html></html>", {})


# ------------------------------------------------------------------ ikea kallax: a moved / foreign article

def test_ikea_article_that_redirects_to_the_catalogue_is_skipped_without_paid_reads(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("ikea_us_article_on_fi"))
    url = "https://www.ikea.com/fi/fi/p/kallax-shelf-unit-white-90301555/"
    got, why = asyncio.run(reader.read_with_reason(url, KALLAX))
    assert got is None and why.startswith("item page moved to") and calls == []


def test_ikea_finnish_product_page_is_priced_from_its_json_ld(monkeypatch):
    calls = no_paid_reads(monkeypatch)
    serve(page("ikea_kallax_fi_70301537"))
    url = "https://www.ikea.com/fi/fi/p/kallax-hylly-valkoinen-70301537/"
    got, via = asyncio.run(reader.read_with_reason(url, KALLAX))
    assert via == "jsonld" and got.price == 199.0 and got.condition == "new" and calls == []
    assert reader.moved_off_item(url, page("ikea_kallax_fi_70301537")) is None


# ------------------------------------------------------------------ home cleaning tilburg: sold-out deal

def test_sold_out_service_deal_is_set_aside(monkeypatch):
    no_paid_reads(monkeypatch)
    html = ('<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            '"name":"3 uur professionele schoonmaakhulp","offers":{"@type":"Offer","price":"19.00",'
            '"priceCurrency":"EUR","availability":"https://schema.org/OutOfStock"}}</script></head><body></body></html>')
    serve(html)
    url = "https://www.socialdeal.nl/deals/tilburg/thuishulp-nederland/schoonmaken-januari-2015-tilburg/"
    got, why = asyncio.run(reader.read_with_reason(url, CLEANING))
    assert got is None and "sold out" in why


def test_directory_instructions_accept_a_platforms_from_rate():
    assert "vanaf" in reader.provider_instructions(CLEANING)


def test_proshop_card_title_is_its_heading_not_ean_url_and_description():
    rec = S.for_url("https://www.proshop.fi/?s=ps5")
    rows = S.rows_from_html(page("proshop_fi_ps5"), "https://www.proshop.fi/?s=ps5", rec, max_rows=50)
    ps5 = next(r for r in rows if "/3213234" in r["url"])
    assert ps5["title"] == "Sony PlayStation 5 Digital (Slim) - 825GB" and ps5["price"] == 699.0
    assert not any("http" in r["title"] or "Slim Design" in r["title"] for r in rows)
