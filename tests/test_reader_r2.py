"""Round-2 reader regressions from live eval streams (eval/r2/lego-technic.sse)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, images, reader
from agora.models import Need

LEGO = Need(raw="lego technic", thing="lego technic")
# the 'source' event in the saved stream, verbatim
REEPEAT_URL = "https://www.reepeat.fr/products/lego-technic"
REEPEAT_TITLE = "lego technic refurbished | Reepeat"
REEPEAT_SNIPPET = ("Right now, the cheapest refurbished lego technic Jeu de construction is priced at 16,00 € at "
                   "Fnac Occasions. Compare prices on refurbished products and save big.")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setattr(fx, "_rates", None)
    cd._reset_ledger()
    reader._HINTS.clear()
    yield
    reader._transport = None


def test_comparison_snippet_is_a_from_price_never_safe_to_price_unread():
    assert reader.comparison_snippet(REEPEAT_SNIPPET)
    o = reader.offer_from_snippet(REEPEAT_SNIPPET, REEPEAT_URL, REEPEAT_TITLE, LEGO, "refurbished")
    assert o is not None and o.price == 16.0
    assert o.raw["from_price"] and o.raw["price_comparison"] and "price_comparison" in o.flags
    assert reader.snippet_offer_if_safe(REEPEAT_URL, REEPEAT_TITLE, REEPEAT_SNIPPET, LEGO, "refurbished") is None


@pytest.mark.parametrize("text", [
    "Preisvergleich: LEGO Technic 42143 ab 289,99 € bei 23 Händlern",
    "Vertaa hintoja: LEGO Technic 42143 alk. 299 €",
    "Compare 14 offers for LEGO Technic 42143 from €289",
    "Prisjämförelse LEGO Technic 42143 – 2 990 kr",
    "Comparer les prix : LEGO Technic 42143 dès 289 €",
])
def test_comparison_wordings_in_several_languages(text):
    assert reader.comparison_snippet(text)


@pytest.mark.parametrize("text", [
    "LEGO Technic 42143 Ferrari Daytona SP3. Price €329.99. In stock, ships in 1-2 days.",
    "Sony A7 III body, MSRP: $1,998.00 · Now: $1,698.00 · lowest price guaranteed at checkout",
    "Käytetty LEGO Technic 42115 Lamborghini, hinta 250 €, nouto Helsinki",
])
def test_ordinary_shop_snippets_are_not_comparisons(text):
    assert not reader.comparison_snippet(text)


def test_title_that_is_only_the_query_is_a_landing_page_price():
    assert reader.bare_query_title(REEPEAT_TITLE, REEPEAT_URL, LEGO)
    assert reader.bare_query_title("Buy LEGO Technic online - shop.fi", "https://shop.fi/lego-technic", LEGO)
    assert not reader.bare_query_title("LEGO Technic 42115 Lamborghini Sián FKP 37", "https://tori.fi/x", LEGO)
    assert not reader.bare_query_title("SONY A7 III BODY", "https://kenmorecamera.com/x",
                                       Need(raw="sony a7 iii", thing="sony a7 iii"))
    o = reader.offer_from_snippet("Kunnostettu 120 €", "https://shop.fi/lego-technic", "Lego Technic | Shop", LEGO)
    assert o.raw.get("from_price") and o.raw.get("bare_query_title")


def test_last_resort_snippet_read_flags_the_reepeat_page(monkeypatch):
    """The whole read path: page unreadable, paid steps find nothing, the snippet prices it -> from_price."""
    reader._transport = httpx.MockTransport(lambda r: httpx.Response(
        403, text="<html><head><title>Just a moment...</title></head><body>cf-chl captcha</body></html>"))

    async def nothing(*a, **kw):
        return None
    monkeypatch.setattr(cd, "product", nothing)
    monkeypatch.setattr(cd, "extract", nothing)
    reader.remember_source(REEPEAT_URL, "refurbished", REEPEAT_TITLE, REEPEAT_SNIPPET)
    offer = asyncio.run(reader.read(REEPEAT_URL, LEGO))
    assert offer is not None and offer.read_via == "search_highlight"   # kept as a listing...
    assert offer.raw.get("from_price") is True                            # ...never a pick


def test_from_cue_in_snippet_is_seen_on_the_last_resort_path():
    o = reader.offer_from_snippet("Lego Technic sets from €29.99", "https://toys.fi/lego",
                                  "LEGO Technic 42151 Bugatti Bolide", LEGO)
    reader.add_witnesses(o, "search_highlight", search_title=o.title, snippet="Lego Technic sets from €29.99")
    assert o.raw.get("from_price") is True


def test_site_wide_share_images_are_not_photos():
    for u in ["https://media.reepeat.com/public/reepeat-opengraph.png", "https://x.fi/static/og.png",
              "https://x.fi/img/og-default.jpg", "https://x.fi/assets/twitter-card.jpg"]:
        assert not images.is_product_photo(u), u
    for u in ["https://cdn.x.fi/p/42132-lego-technic.jpg", "https://x.fi/prod/vogue-bag.jpg",
              "https://img.tori.fi/image/dynamic/1600w/item/49569213/abc"]:
        assert images.is_product_photo(u), u
