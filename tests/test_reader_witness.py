"""Reader round 1: price witnesses, service tiers, redirects and offline-safe fetching."""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from agora import contextdev as cd
from agora import fx, reader
from agora.judge import judge
from agora.models import Need, Thing

FIX = pathlib.Path(__file__).parent / "fixtures"
SERVICE = Need(raw="home cleaning helsinki 60m2", thing="home cleaning", kind="service", where="Helsinki")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(fx, "_rates", None)
    reader._HINTS.clear()
    yield
    reader._transport = None


def saved_extract(name: str):
    """A real saved Context.dev /web/scrape json response, parsed the way contextdev.extract does."""
    saved = json.loads((FIX / f"cd_json_{name}.json").read_text())
    resp, req = saved["response"], saved["request_url"]
    data = dict(resp["json"]["data"])
    if resp["url"].rstrip("/") != req.rstrip("/"):
        data["_final_url"] = resp["url"]
    return req, data


def read_service(monkeypatch, name: str):
    url, data = saved_extract(name)

    async def fake_extract(u, schema, instructions=None, **kw):
        return data
    monkeypatch.setattr(cd, "extract", fake_extract)
    return asyncio.run(reader.read_with_reason(url, SERVICE))


def test_novah_one_job_is_the_one_time_tier(monkeypatch):
    offer, via = read_service(monkeypatch, "novah")
    assert via == "contextdev_json"
    assert offer.price == 49.9 and offer.raw["tier"] == "one-time" and not offer.raw.get("recurring_only")
    v = judge(SERVICE, [Thing(id="t", name="home cleaning", offers=[offer])])
    assert offer.true_cost.total_eur == pytest.approx(124.75)
    assert "€125 for one 60 m² clean at novah.fi (one-time rate), €49.90/h × 2.5 h" in v.headline


def test_cleava_only_recurring_takes_the_dearest_and_says_so(monkeypatch):
    offer, _ = read_service(monkeypatch, "cleava")
    assert offer.price == 49 and offer.raw["recurring_only"] and offer.raw["tier"] == "monthly"
    judge(SERVICE, [Thing(id="t", name="home cleaning", offers=[offer])])
    assert any("recurring-contract price" in f for f in offer.flags)


def test_hyvacleaning_redirect_is_recorded(monkeypatch):
    offer, _ = read_service(monkeypatch, "hyvacleaning")
    assert offer.raw["final_url"] == "https://novah.fi/en/prices/helsinki"
    from agora.hunt import adopt_redirect, dedupe_key
    adopt_redirect(offer)
    assert offer.source == "novah.fi" and offer.raw["redirected_from"].startswith("https://hyvacleaning.fi")
    assert dedupe_key(offer)[0] == "https://novah.fi/en/prices/helsinki"


JSONLD = """<html><head><script type="application/ld+json">{"@type":"Product","name":"Sony A7 III",
"offers":{"@type":"Offer","price":"849.00","priceCurrency":"EUR"}}</script></head><body>Now 849.00 EUR</body></html>"""


def test_jsonld_read_carries_two_witnesses(monkeypatch):
    url = "https://shop.example.fi/a7"
    reader._transport = httpx.MockTransport(
        lambda r: httpx.Response(200, text=JSONLD, headers={"content-type": "text/html"}))
    reader.remember_source(url, "new", title="Sony A7 III | Shop", snippet="In stock. Price €829,00 incl. VAT")
    offer = asyncio.run(reader.read(url, Need(raw="sony a7 iii", thing="sony a7 iii")))
    wits = offer.raw["witnesses"]
    assert wits[0]["via"] == "jsonld" and wits[0]["primary"] and "849" in wits[0]["quote"]
    assert wits[1]["via"] == "snippet" and wits[1]["price"] == 829 and "829" in wits[1]["quote"]
    assert wits[0]["fetched_at"] > 0


def test_offline_fetch_makes_no_network_calls_and_uses_saved_html(monkeypatch, tmp_path):
    monkeypatch.setenv("AGORA_OFFLINE", "1")
    monkeypatch.setenv("AGORA_CACHE_DIR", str(tmp_path))
    real = httpx.AsyncClient.send

    async def boom(self, *a, **kw):
        raise AssertionError("network used while AGORA_OFFLINE=1")
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    assert asyncio.run(reader.fetch_html("https://shop.example.fi/never")) == (0, "")
    reader._html_cache("https://shop.example.fi/a7").parent.mkdir(parents=True, exist_ok=True)
    reader._html_cache("https://shop.example.fi/a7").write_text(JSONLD)
    status, html = asyncio.run(reader.fetch_html("https://shop.example.fi/a7"))
    assert status == 200 and "849.00" in html
    monkeypatch.setattr(httpx.AsyncClient, "send", real)
