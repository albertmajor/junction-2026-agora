"""Regression (eval r1, 'puhelin' / 'ps5' / 'nintendo-switch-oled'): olx.pl listings came out without a photo
(4 of 41 kept), and no service offer had a photo or logo. Offline: a saved olx.pl search page, trimmed."""
from __future__ import annotations

import json
import pathlib

from agora import images, marketplaces, reader
from agora.models import Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"


def _olx() -> dict:
    return json.loads((FIX / "olx_pl_telefon_split.json").read_text())


def test_olx_split_rows_get_their_own_photo_from_the_page_state():
    f = _olx()
    need = Need(raw="puhelin", thing="telefon", kind="product")
    offers = reader.offers_from_split(f["markdown"], f["html"], f["url"], marketplaces.SITES["olx_pl"], need)
    assert len(offers) >= 30
    with_img = [o for o in offers if o.image]
    assert len(with_img) >= 0.9 * len(offers), (len(with_img), len(offers))
    # every photo is the listing's own: the state maps the listing URL to it, never a neighbour's
    state = images.state_photos(f["html"], f["url"])
    for o in with_img:
        assert images.is_product_photo(o.image)
    keys = [images.photo_key(o.image) for o in with_img]
    assert len(keys) == len(set(keys)), "a photo shared by two listings"
    by_path = {images._norm_path(o.url): o.image for o in with_img}
    hit = 0
    for p, u in state.items():
        if p in by_path and images.same_photo(by_path[p], u):
            hit += 1
    assert hit >= len(with_img) - 6        # the few DOM-paired first cards may use another size of the same file


def test_lazy_card_listing_named_in_eval_now_has_its_photo():
    f = _olx()
    rows = [{"url": "https://www.olx.pl/d/oferta/sprzedam-telefon-CID99-ID1dgcIV.html?search_reason=search%7Corganic",
             "title": "Sprzedam telefon", "image": None}]
    out = images.pair_rows_for_reader(rows, f["html"], f["url"])
    assert out[0]["image"] and "n5c63cu9bugw2" in out[0]["image"]
    assert out[0]["image_check"] == "state"
    assert rows[0]["image"] is None            # the caller's rows are not mutated


def test_state_photos_reads_next_data_and_srcsets():
    page = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"items": [
                {"href": "/item/123456789", "image": {"url": "https://cdn.example.eu/p/123456789.jpg"}},
                {"url": "https://shop.example.eu/item/987654321",
                 "srcset": "https://cdn.example.eu/a_320.jpg 320w, https://cdn.example.eu/a_640.jpg 640w"},
                {"url": "/item/555555555", "image": "https://cdn.example.eu/static/no_thumbnail.svg"},
            ]}}) + "</script>")
    got = images.state_photos(page, "https://shop.example.eu/search?q=x")
    assert got["/item/123456789"] == "https://cdn.example.eu/p/123456789.jpg"
    assert got["/item/987654321"] == "https://cdn.example.eu/a_640.jpg"
    assert "/item/555555555" not in got          # a placeholder is no photo


def test_state_photo_never_reused_for_two_rows():
    page = ('<script>window.__INITIAL_STATE__ = {"ads":[{"url":"/d/a-111111","photos":["https://c.eu/x/1.jpg"]},'
            '{"url":"/d/b-222222","photos":["https://c.eu/x/1.jpg"]}]};</script>')
    rows = [{"url": "https://m.eu/d/a-111111", "title": "a"}, {"url": "https://m.eu/d/b-222222", "title": "b"}]
    out = images.fill_from_state(rows, page, "https://m.eu/s?q=a")
    assert [bool(r.get("image")) for r in out] == [True, False]


SERVICE_PAGE = """<html><head><title>Accounting prices</title>
<meta property="og:image" content="/img/kuva1.jpg">
<script type="application/ld+json">{"@type":"AccountingService","name":"Ad Count","logo":"https://adcount.fi/logo.png"}</script>
</head><body><h1>Prices</h1></body></html>"""

YOAST_PAGE = """<html><head><script type="application/ld+json">{"@graph":[{"@type":"Organization","name":"E",
"logo":{"@id":"https://eaccounting.fi/en/#/schema/logo/image/"},"image":{"@id":"https://eaccounting.fi/en/#/schema/logo/image/"}},
{"@type":"ImageObject","@id":"https://eaccounting.fi/en/#/schema/logo/image/","url":"https://eaccounting.fi/wp/logo.png"}]}</script>
</head><body></body></html>"""


def test_service_image_og_then_business_logo_never_an_id_reference():
    assert images.service_image(SERVICE_PAGE, "https://adcount.fi/en/prices") == "https://adcount.fi/img/kuva1.jpg"
    no_og = SERVICE_PAGE.replace('<meta property="og:image" content="/img/kuva1.jpg">', "")
    assert images.service_image(no_og, "https://adcount.fi/en/prices") == "https://adcount.fi/logo.png"
    assert images.service_image(YOAST_PAGE, "https://eaccounting.fi/en/") is None
    fav = '<html><head><meta property="og:image" content="https://x.fi/favicon.ico"></head></html>'
    assert images.service_image(fav, "https://x.fi/") is None


def test_reader_gives_a_service_offer_the_providers_picture():
    o = Offer(url="https://adcount.fi/en/prices", source="adcount.fi", title="Bookkeeping", price=90.0,
              currency="EUR", price_eur=90.0, condition="service", read_via="jsonld")
    reader._annotate(o, SERVICE_PAGE, "", "")
    assert o.image == "https://adcount.fi/img/kuva1.jpg"
    p = Offer(url="https://shop.example.eu/p/1", source="shop.example.eu", title="Kahvinkeitin Moccamaster",
              price=99.0, currency="EUR", price_eur=99.0, condition="new", read_via="jsonld")
    reader._annotate(p, '<html><head><meta property="og:image" content="https://shop.example.eu/media/kbg.jpg">'
                        '</head></html>', "", "")
    assert p.image == "https://shop.example.eu/media/kbg.jpg"
    q = Offer(url="https://shop.example.eu/p/2", source="shop.example.eu", title="x", price=1.0, currency="EUR",
              price_eur=1.0, condition="new", read_via="jsonld", image="https://shop.example.eu/media/own.jpg")
    reader._annotate(q, '<meta property="og:image" content="https://shop.example.eu/media/other.jpg">', "", "")
    assert q.image == "https://shop.example.eu/media/own.jpg"     # an offer's own photo is never replaced
