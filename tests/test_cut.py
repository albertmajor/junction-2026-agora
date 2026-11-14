"""GET /cut: the guarded cutout proxy (agora/cutout.py). Offline: no image is fetched."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora import cutout

TORI = "https://img.tori.net/dynamic/1280w/item/40486480/34d5592c-c72a-4782-8692-27575ed644e3"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cutout, "CUTS", tmp_path / "cuts")

    async def no_fetch(*a, **k):
        raise AssertionError("tests must not fetch images")
    monkeypatch.setattr(cutout, "fetch_image", no_fetch)
    app = FastAPI()
    app.include_router(cutout.router)
    return TestClient(app, follow_redirects=False)


def test_fixture_photos_are_allowed():
    assert cutout.allowed(TORI)
    # a relative photo path in a recording is joined onto its page
    assert cutout.resolve("/image/1200/estorethumb/3555.webp") == "https://www.e-infin.com/image/1200/estorethumb/3555.webp"


@pytest.mark.parametrize("u", [
    "https://evil.example.com/cat.png",                       # not from a hunt
    "http://img.tori.net/dynamic/1280w/item/40486480/x",       # http
    "https://127.0.0.1/a.png",                                 # IP literal
    "https://localhost/a.png",
    "https://printer.local/a.png",
    "file:///etc/passwd",
])
def test_unknown_or_unsafe_urls_are_403(client, u):
    assert client.get("/cut", params={"u": u}).status_code == 403


def test_http_version_of_allowed_url_is_403(client):
    cutout.remember(TORI)
    assert client.get("/cut", params={"u": TORI.replace("https://", "http://")}).status_code == 403


def test_remember_refuses_unsafe_urls():
    cutout.remember("http://10.0.0.1/x.png")
    cutout.remember("https://192.168.1.1/x.png")
    assert not cutout.allowed("http://10.0.0.1/x.png")
    assert not cutout.allowed("https://192.168.1.1/x.png")


def test_public_https_rules():
    assert cutout.public_https("https://img.tori.net/a.jpg")
    assert not cutout.public_https("https://img.tori.net:8443/a.jpg")
    assert not cutout.public_https("https://user:pw@img.tori.net/a.jpg")
    assert not cutout.public_https("https://[::1]/a.jpg")


def test_cached_cut_is_served_from_disk(client):
    cutout.CUTS.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\nfake"
    (cutout.CUTS / f"{cutout._key(TORI)}.png").write_bytes(png)
    r = client.get("/cut", params={"u": TORI})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png
    assert client.get("/cut/known").json().get(TORI) is True


def test_no_cutout_redirects_to_raw_photo(client, monkeypatch):
    monkeypatch.setattr(cutout, "_build_ok", False)      # e.g. not macOS
    r = client.get("/cut", params={"u": TORI})
    assert r.status_code == 302 and r.headers["location"] == TORI


def test_failed_cut_is_remembered_and_redirects(client, monkeypatch):
    monkeypatch.setattr(cutout, "_build_ok", True)
    cutout.CUTS.mkdir(parents=True)
    (cutout.CUTS / f"{cutout._key(TORI)}.raw").write_text(TORI)
    r = client.get("/cut", params={"u": TORI})
    assert r.status_code == 302 and r.headers["location"] == TORI


def test_refused_photo_gets_a_monogram_not_a_broken_image(client, monkeypatch):
    monkeypatch.setattr(cutout, "_build_ok", True)
    cutout.CUTS.mkdir(parents=True)
    (cutout.CUTS / f"{cutout._key(TORI)}.dead").write_text("HTTP 403")
    r = client.get("/cut", params={"u": TORI})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text and ">T<" in r.text          # tori.fi -> "T"
    assert client.get("/cut/known").json().get(TORI) is False
