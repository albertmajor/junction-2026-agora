"""agora.enrich: 'People usually look for here' + 'Providers we know here' for niche categories. Offline: the one
Context.dev search is a fake."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from agora import api, contextdev, enrich, longtail_store, store
from agora.models import Need

NODE = "cpv:6352"          # Transport agency (Travel > Travel agents & tour operators), 4 leaf children


def _res(url: str, title: str, hl: str = "") -> dict:
    return {"url": url, "title": title, "description": "",
            "highlights": {"highlights": [hl] if hl else [], "code": "SUCCESS"}}


WEB = [
    _res("https://www.cargoboys.fi/hinnasto", "Freight forwarding quote | Cargoboys",
         "[Hinnasto > Palvelut]\n\n- Pallet shipping 49 €\n- Car transport Germany 690 €\n- Furniture shipping abroad 250 €\n"
         "- Contact\n- Etusivu"),
    _res("https://www.shipit-now.com/prices", "Pallet shipping and Freight forwarding quote - ShipitNow",
         "## Car transport Germany from 650 €\n## Courier for documents 19 €\n## Shipitnow Premium 99 €"),
    _res("https://www.example-logistics.de/", "Car transport Germany – Example Logistics",
         "Courier for documents · Pallet shipping · Frequently Asked Questions"),
    _res("https://blog.somewhere.com/x", "How much does freight cost? Prices are LABOR ONLY", "Read more"),
]


@pytest.fixture
def fake_search(monkeypatch):
    calls: list[dict] = []

    async def search(query, n=10, highlights=False, country=None, **kw):
        calls.append({"query": query, "country": country, "highlights": highlights})
        return WEB
    monkeypatch.setattr(contextdev, "search", search)
    monkeypatch.setattr(enrich, "web_allowed", lambda: (True, ""))
    enrich._INFLIGHT.clear()
    return calls


def test_unknown_node_is_a_key_error():
    with pytest.raises(KeyError):
        enrich.quick("no-such-node")


def test_niche_rule():
    T = enrich._tax()
    assert enrich.is_niche(T, T._i(NODE))
    assert not enrich.is_niche(T, T._i("travel"))            # a root never is


def test_extract_phrases_recurring_no_nav_no_brands():
    got = enrich.extract_phrases(WEB, "Transport agency", "en")
    labels = [g["label"] for g in got]
    low = [x.lower() for x in labels]
    assert "pallet shipping" in low and "car transport germany" in low and "courier for documents" in low
    assert any("freight forwarding quote" == x for x in low)
    assert not any("shipitnow" in x or "cargoboys" in x for x in low)          # the sites' own names
    assert not any(x in ("contact", "etusivu", "read more", "frequently asked questions") for x in low)
    assert not any("labor" in x or "cost" in x for x in low)                   # price talk, not a thing
    assert all(g["kind"] == "web" and g["why"] and g["query"] == g["label"] for g in got)
    assert 4 <= len(got) <= 10


def test_own_data_past_hunts_and_registry(fake_search):
    n = Need(raw="pallet shipping to Estonia", thing="pallet shipping to Estonia", kind="service",
             category={"id": "cpv:63521", "source": "tree"})          # a child of Transport agency
    store.save_need(n)
    store.save_need(n)
    longtail_store.save_provider("cargoboys.fi", name="Cargoboys", category_id=NODE, category="Transport agency",
                                 terms=["transport", "agency"], home_url="https://cargoboys.fi",
                                 plans=[{"name": "Pallet", "price_eur": 49}])
    out = enrich.quick(NODE, "en", "fi")
    s = out["suggestions"][0]
    assert s["label"] == "pallet shipping to Estonia" and s["kind"] == "asked" and "2 times" in s["why"]
    assert out["providers"][0]["domain"] == "cargoboys.fi" and out["providers"][0]["source"] == "registry"
    assert fake_search == []                                  # quick() never touches the web


def test_complete_uses_one_search_then_cache(fake_search):
    out = asyncio.run(enrich.complete(NODE, "fi", "FI"))
    assert len(fake_search) == 1
    call = fake_search[0]
    assert call["query"].endswith("hinta") and call["country"] == "fi" and call["highlights"]
    assert "web" in out["source"] and 4 <= len(out["suggestions"]) <= 10
    assert any(p["source"] == "web" for p in out["providers"])
    again = asyncio.run(enrich.get(NODE, "fi", "fi"))
    assert again["cached"] and not again["pending"] and len(fake_search) == 1
    assert again["suggestions"] == out["suggestions"]


def test_enough_own_data_skips_the_web(fake_search):
    for raw in ("pallet shipping", "car transport germany", "courier for documents", "furniture shipping abroad"):
        store.save_need(Need(raw=raw, thing=raw, kind="service", category={"id": NODE, "source": "tree"}))
    out = asyncio.run(enrich.complete(NODE, "en", "fi"))
    assert fake_search == [] and out["source"] == "own" and len(out["suggestions"]) == 4


def test_non_niche_never_searches(fake_search):
    out = asyncio.run(enrich.complete("travel", "en", "fi"))
    assert fake_search == [] and out["niche"] is False


def test_bucket_low_or_offline_means_no_search(monkeypatch, tmp_path):
    called = []

    async def search(*a, **k):
        called.append(1)
        return WEB
    monkeypatch.setattr(contextdev, "search", search)
    monkeypatch.setattr(contextdev, "offline", lambda: False)
    monkeypatch.setattr(contextdev, "_key", lambda: "k")
    (contextdev.cache_root() / "contextdev_bucket.json").write_text(json.dumps({"tokens": 3, "ts": time.time()}))
    assert enrich.web_allowed() == (False, "bucket low")
    out = asyncio.run(enrich.complete(NODE, "en", "fi"))
    assert called == [] and out["web_skipped"] == "bucket low"
    # kept only briefly: an hour later it is asked again
    assert enrich._cache_get(NODE, "en", "fi", now=time.time() + 2 * 3600) is None
    (contextdev.cache_root() / "contextdev_bucket.json").write_text(json.dumps({"tokens": 9, "ts": time.time()}))
    assert enrich.web_allowed() == (True, "")
    monkeypatch.setattr(contextdev, "offline", lambda: True)
    assert enrich.web_allowed() == (False, "offline")


def test_full_answer_is_kept_30_days(fake_search):
    asyncio.run(enrich.complete(NODE, "en", "fi"))
    assert enrich._cache_get(NODE, "en", "fi", now=time.time() + 29 * 86400) is not None
    assert enrich._cache_get(NODE, "en", "fi", now=time.time() + 31 * 86400) is None


def test_api_pending_then_full(monkeypatch):
    gate = {"n": 0}

    async def slow(query, **kw):
        gate["n"] += 1
        await asyncio.sleep(0.8)
        return WEB
    monkeypatch.setattr(contextdev, "search", slow)
    monkeypatch.setattr(enrich, "web_allowed", lambda: (True, ""))
    enrich._INFLIGHT.clear()
    with TestClient(api.app) as c:
        r = c.get("/api/categories/enrich", params={"id": NODE, "lang": "en", "country": "fi"})
        assert r.status_code == 200
        j = r.json()
        assert j["pending"] is True and j["id"] == NODE and j["niche"] is True
        assert set(j) >= {"suggestions", "providers", "source", "cached"}
        for _ in range(30):
            time.sleep(0.1)
            j = c.get("/api/categories/enrich", params={"id": NODE, "lang": "en", "country": "fi"}).json()
            if not j["pending"]:
                break
        assert j["pending"] is False and "web" in j["source"]
        assert c.get("/api/categories/enrich", params={"id": NODE, "lang": "en", "country": "fi"}).json()["cached"] is True
        assert all(set(s) == {"label", "query", "kind", "why"} for s in j["suggestions"])
        assert gate["n"] == 1
        assert c.get("/api/categories/enrich", params={"id": "nope:1"}).status_code == 404


def test_word_runs_in_sentences_need_to_recur():
    res = [
        _res("https://a-shipping.example/x", "Sea freight rates explained",
             "Sea freight is cheaper. Sea freight takes weeks. We also arrange sea freight insurance. Road transport once."),
        _res("https://b-cargo.example/y", "Air freight", "Freight forwarding for small firms."),
        _res("https://c-logistics.example/z", "Customs", "Freight forwarding and customs clearance."),
    ]
    got = {g["label"].lower(): g["why"] for g in enrich.extract_phrases(res, "Transport agency", "en",
                                                                    topic={"freight", "transport", "forwarding"})}
    assert "sea freight" in got and "again and again" in got["sea freight"]
    assert "freight forwarding" in got and got["freight forwarding"].startswith("on 2 of")
    assert "road transport" not in got                      # said once on one site


def test_web_query_is_plain_and_local():
    T = enrich._tax()
    i = T._i(NODE)
    assert enrich.web_query(T, i, "en") == "Transport freight price"     # not 'Transport agency' (the authority)
    assert enrich.web_query(T, i, "fi").endswith(" hinta") and "palvelut" not in enrich.web_query(T, i, "fi")
