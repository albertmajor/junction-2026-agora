"""Regression (eval r4, 'unlimited graphic design subscription'): 0 of 10 kept design studios had a picture.
Offline: the <head> of the studios' saved pages (designjoy, delesign, cueball creatives, pixzocraft).
- a plan read for free from the provider's own page (reader.period_plan_offer) never got the page's picture;
- an .svg logo / favicon.png og:image was taken, then dropped as 'not a photo', leaving nothing, when the
  site's apple-touch-icon (its own square brand mark) was right there."""
from __future__ import annotations

import asyncio
import json
import pathlib

from agora import images, reader
from agora.models import Need

FIX = pathlib.Path(__file__).parent / "fixtures"
HEADS = json.loads((FIX / "design_studio_heads.json").read_text())


def _need() -> Need:
    return Need(raw="unlimited graphic design subscription", thing="unlimited graphic design subscription",
                kind="digital", conditions=["service"])


def test_every_saved_studio_page_yields_a_showable_picture():
    for url, head in HEADS.items():
        u = images.service_image(head, url)
        assert u, url
        assert images.offer_image_ok(u, url, None, service=True), (url, u)
        assert not u.lower().split("?")[0].endswith((".svg", ".ico", ".gif")), u


def test_svg_logo_is_passed_over_for_the_touch_icon():
    url = "https://www.delesign.com/"
    u = images.service_image(HEADS[url], url)
    assert u.endswith("favi-256.png")             # not logo-light.svg (dropped later) and not favi-32.png


def test_favicon_og_image_falls_back_to_apple_touch_icon():
    url = "https://pixzocraft.com/pricing"
    assert images.service_image(HEADS[url], url) == "https://pixzocraft.com/apple-touch-icon.png"


def test_touch_icon_ignores_tiny_favicons_and_svg_mask():
    page = ('<head><link rel="icon" sizes="32x32" href="/f32.png"><link rel="mask-icon" href="/m.svg">'
            '<link rel="icon" type="image/png" sizes="192x192" href="/android-192.png"></head>')
    assert images.touch_icon(page, "https://x.example/") == "https://x.example/android-192.png"
    assert images.touch_icon('<link rel="icon" sizes="32x32" href="/f.png">', "https://x.example/") is None


def test_free_plan_read_carries_the_providers_picture(monkeypatch):
    url = "https://www.designjoy.co/"
    page = HEADS[url].replace("</head>", "</head>") + (
        "<body><h1>Design subscriptions for everyone</h1><p>Unlimited graphic design requests.</p>"
        "<div><h3>Monthly Club</h3><p>$4,995/month</p><p>One request at a time. Pause or cancel anytime.</p></div>"
        "</body></html>")

    async def fetch(u):
        return 200, page
    monkeypatch.setattr(reader, "fetch_html", fetch)
    got, via = asyncio.run(reader.read_with_reason(url, _need(), lane="service", paid=False))
    assert via == "jsonld", via
    assert got is not None and got.price == 4995
    assert got.image and images.offer_image_ok(got.image, url, got.seller, service=True), got.image
