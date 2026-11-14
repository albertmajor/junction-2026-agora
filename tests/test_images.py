"""agora/images.py: free listing-photo backfill + verify, row re-pairing, the guarded router. Offline (fixtures)."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest
from fastapi.testclient import TestClient

from agora import images

FIX = pathlib.Path(__file__).parent / "fixtures" / "images"
MP_URL = ("https://www.marktplaats.nl/v/kinderen-en-baby-s/kinderwagens-en-combinaties/"
          "m2445403041-babyzenyoyo-reiswieg-bassinet-grijs-adapters-muggennet")
OLX_URL = "https://www.olx.pl/d/oferta/thule-urban-glide-3-gondola-bassinet-4-wheel-CID88-ID128q6q.html"
MP_PHOTO = "2909804d-8f5b-4ef8-8404-c9cdec9b3239"


@pytest.fixture(autouse=True)
def _fresh():
    images.clear_cache()
    images._allowed.clear()
    images._allow_loaded = False
    images._transport = None
    yield
    images._transport = None
    images.clear_cache()


def _serve(pages: dict[str, str], hits: list | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if hits is not None:
            hits.append(str(req.url))
        body = pages.get(str(req.url))
        if body is None:
            return httpx.Response(404, text="nope")
        if body.startswith("REDIRECT "):
            return httpx.Response(302, headers={"location": body[9:]})
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})
    images._transport = httpx.MockTransport(handler)


# ---------- page -> photo ----------

def test_marktplaats_jsonld_photo():
    page = (FIX / "marktplaats_babyzen_bassinet.html").read_text()
    res = images.image_from_html(page, MP_URL)
    assert res["source"] == "jsonld"
    assert MP_PHOTO in res["image"] and res["image"].endswith("$_86")


def test_olx_jsonld_photo_is_the_listings_own():
    page = (FIX / "olx_thule_4wheel.html").read_text()
    res = images.image_from_html(page, OLX_URL)
    assert res == {"image": "https://ireland.apollo.olxcdn.com:443/v1/files/qvxjblyb834r2-PL/image", "source": "jsonld"}


def test_og_then_dom_then_none():
    og = '<html><head><meta property="og:image" content="/media/p/123-front.jpg"></head></html>'
    assert images.image_from_html(og, "https://shop.example.com/p/1") == {
        "image": "https://shop.example.com/media/p/123-front.jpg", "source": "og"}
    logo_only = '<meta property="og:image" content="https://shop.example.com/static/logo.png">'
    dom = logo_only + ('<title>Thule Urban Glide 3 bassinet</title><img src="/s/sprite.png" width="900">'
                       '<img src="/u/a.jpg" alt="Thule Urban Glide 3 bassinet, grey" width="800">')
    assert images.image_from_html(dom, "https://shop.example.com/p/1") == {
        "image": "https://shop.example.com/u/a.jpg", "source": "dom"}
    assert images.image_from_html(logo_only, "https://shop.example.com/p/1") == {"image": None, "source": "none"}


def test_photo_rules():
    assert not images.is_product_photo("https://www.olx.pl/app/static/media/no_thumbnail.15f456ec5.svg")
    assert not images.is_product_photo("https://x.example.com/img/placeholder.jpg")
    assert not images.is_product_photo("data:image/png;base64,AAAA")
    assert images.is_product_photo("https://images.marktplaats.com/api/v1/hz-mp-pro-listing/images/ab?rule=ecg_mp_eps$_86")
    # marktplaats sizes (measured): $_83 = 358 px -> $_85 = 726 px; $_86 (1024 px) stays
    small = f"https://images.marktplaats.com/api/v1/hz-mp-pro-listing/images/{MP_PHOTO}?rule=ecg_mp_eps$_83"
    assert images.upgrade(small).endswith("$_85")
    assert images.upgrade(small.replace("$_83", "$_86")).endswith("$_86")


def test_same_photo_ignores_size():
    a = f"https://images.marktplaats.com/api/v1/hz-mp-pro-listing/images/{MP_PHOTO}?rule=ecg_mp_eps$_83"
    assert images.same_photo(a, a.replace("$_83", "$_86"))
    o1 = "https://ireland.apollo.olxcdn.com:443/v1/files/qvxjblyb834r2-PL/image;s=216x152;q=50"
    assert images.same_photo(o1, "https://ireland.apollo.olxcdn.com:443/v1/files/qvxjblyb834r2-PL/image")
    assert not images.same_photo(o1, "https://ireland.apollo.olxcdn.com:443/v1/files/9sn937km6nh7-PL/image")
    t = "https://img.tori.net/dynamic/1280w/item/40486480/34d5592c-c72a-4782-8692-27575ed644e3"
    assert images.same_photo(t, t.replace("1280w", "640w"))
    s = "https://shop.example.com/files/cradle_1024x1024.jpg?v=1"
    assert images.same_photo(s, "https://shop.example.com/files/cradle_grande.jpg")


# ---------- re-pairing split rows (the off-by-one) ----------

def test_pair_images_fixes_neighbour_photos():
    data = json.loads((FIX / "olx_search_rows.json").read_text())
    rows = data["rows"]
    html = (FIX / "olx_search_cards.html").read_text()
    by = {r["url"].rsplit("-", 1)[-1]: r for r in rows}
    # what the splitter gave: ID1bRJIZ (no photo in its card) took its neighbour's photo,
    # ID128q6q (no photo) took a seller's logo from further down
    assert "c11b1a7qkn9a1" in by["ID1bRJIZ.html"]["image"] and "c11b1a7qkn9a1" in by["ID1cQKLn.html"]["image"]
    assert "1110692614" in by["ID128q6q.html"]["image"]
    out = {r["url"].rsplit("-", 1)[-1]: r for r in images.pair_images(html, rows, data["page_url"])}
    assert "c11b1a7qkn9a1" in out["ID1cQKLn.html"]["image"] and out["ID1cQKLn.html"]["image_check"] == "paired"
    assert "9sn937km6nh7" in out["ID1cper0.html"]["image"]
    assert "5a5bsd0eo0bv3" in out["ID1cQhoD.html"]["image"]
    for k in ("ID1bRJIZ.html", "ID128q6q.html", "ID1aleBO.html"):
        assert out[k]["image"] is None and out[k]["image_check"] == "placeholder", k
    assert rows[0].get("image_check") is None          # the input rows are not changed


def test_pair_images_drops_shared_and_keeps_unknown():
    html = ('<div><a href="/v/a/1111111"><img src="https://cdn.example.com/p/aaa.jpg" alt="Red chair"></a></div>'
            '<div><a href="/v/a/2222222"><img src="https://cdn.example.com/p/aaa.jpg" alt="Blue chair"></a></div>')
    rows = [{"url": "https://m.example.com/v/a/1111111", "title": "Red chair", "image": None},
            {"url": "https://m.example.com/v/a/2222222", "title": "Blue chair", "image": None},
            {"url": "https://m.example.com/v/a/3333333", "title": "Green chair", "image": "https://cdn.example.com/p/c.jpg"}]
    out = images.pair_images(html, rows, "https://m.example.com/q/chair/")
    assert [r["image"] for r in out[:2]] == [None, None] and out[0]["image_check"] == "shared"
    assert out[2]["image"] == "https://cdn.example.com/p/c.jpg" and out[2]["image_check"] == "kept"
    assert images.pair_rows_for_reader(rows, "", "x")[2]["image"] == rows[2]["image"]


# ---------- fetching, cache, verify ----------

def test_find_image_fetches_once_and_caches():
    hits: list = []
    _serve({MP_URL: (FIX / "marktplaats_babyzen_bassinet.html").read_text()}, hits)

    async def go():
        a, b = await asyncio.gather(images.find_image(MP_URL), images.find_image(MP_URL))
        c = await images.find_image(MP_URL)
        return a, b, c
    a, b, c = asyncio.run(go())
    assert a == b == c and a["source"] == "jsonld" and MP_PHOTO in a["image"]
    assert len(hits) == 1


def test_verify_replaces_a_wrong_photo():
    _serve({OLX_URL: (FIX / "olx_thule_4wheel.html").read_text()})
    wrong = "https://ireland.apollo.olxcdn.com:443/v1/files/1wrfytzbmpk43-PL/image;s=216x152;q=50"
    res = asyncio.run(images.verify(OLX_URL, wrong))
    assert res["match"] == "replaced" and "qvxjblyb834r2" in res["image"]
    same = "https://ireland.apollo.olxcdn.com:443/v1/files/qvxjblyb834r2-PL/image;s=216x152;q=50"
    assert asyncio.run(images.verify(OLX_URL, same))["match"] == "same"
    assert asyncio.run(images.verify(OLX_URL, None))["match"] == "filled"


def test_redirect_to_private_host_is_refused():
    _serve({"https://shop.example.com/p/1": "REDIRECT http://127.0.0.1:8765/secret"})
    status, page = asyncio.run(images.fetch_page("https://shop.example.com/p/1"))
    assert status == 0 and page == ""


def test_public_url_guard():
    for bad in ("http://127.0.0.1/x", "https://localhost/x", "https://10.0.0.1/a", "ftp://x.example.com/a",
                "https://user:pw@x.example.com/", "https://x.example.com:8765/", "file:///etc/passwd",
                "https://printer.local/"):
        assert not images.public_url(bad), bad
    assert images.public_url("https://ireland.apollo.olxcdn.com:443/v1/files/a/image")


def test_offline_reads_the_reader_page_cache(monkeypatch):
    # conftest sets AGORA_OFFLINE=1 and a temp cache dir: only cached pages are read, never the network
    p = images._reader_page_cache(MP_URL)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((FIX / "marktplaats_babyzen_bassinet.html").read_text())
    res = asyncio.run(images.find_image(MP_URL))
    assert res["source"] == "jsonld"
    assert asyncio.run(images.find_image("https://www.marktplaats.nl/v/x/m1-not-cached")) == {"image": None, "source": "none"}


# ---------- router ----------

@pytest.fixture
def client():
    from agora import api
    return TestClient(api.app)


def test_router_only_serves_hunt_listings(client):
    _serve({MP_URL: (FIX / "marktplaats_babyzen_bassinet.html").read_text()})
    assert client.get("/api/image", params={"url": MP_URL}).status_code == 403
    assert client.get("/api/image", params={"url": "http://169.254.169.254/latest"}).status_code == 403
    images.remember(MP_URL)
    r = client.get("/api/image", params={"url": MP_URL})
    assert r.status_code == 200 and r.json()["source"] == "jsonld" and MP_PHOTO in r.json()["image"]
    r = client.post("/api/images", json={"urls": [MP_URL, "https://evil.example.com/x"],
                                         "have": {MP_URL: "https://images.marktplaats.com/api/v1/x/images/"
                                                          "11111111-2222-3333-4444-555555555555?rule=ecg_mp_eps$_83"}})
    body = r.json()
    assert body[MP_URL]["match"] == "replaced" and body["https://evil.example.com/x"]["source"] == "denied"
    assert client.post("/api/images", json={"urls": ["https://a.example.com/%d" % i for i in range(51)]}).status_code == 422


def test_recorded_listings_are_allowed():
    # offers in the recordings (tests/fixtures/live_*.jsonl) may be looked up (replays)
    assert images.allowed("https://www.wexphotovideo.com/sony-a7-iii-digital-camera-body-used-3349077/")
