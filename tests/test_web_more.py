"""UI round B: "Compare more" (GET /hunt?depth=), the read-only Context.dev bucket in /status, and the
city-bike recording (322 listings, `scope` + `market` events) the all-listings view is tested against."""
import json
import pathlib

from fastapi.testclient import TestClient

from agora import api
from agora import hunt as hunt_mod

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_depth_reads_more_pages_until_hunt_takes_depth(monkeypatch):
    seen = {}

    async def fake_hunt(text, *, max_sources=32, budget_s=True, **kw):
        seen.update({k: v for k, v in kw.items() if k != "result"})
        if max_sources != 32:
            seen["max_sources"] = max_sources
        if budget_s is not True:
            seen["budget_s"] = budget_s
        if False:
            yield None

    monkeypatch.setattr(hunt_mod, "hunt", fake_hunt)
    monkeypatch.delenv("AGORA_HUNT_BUDGET_S", raising=False)
    c = TestClient(api.app)
    c.get("/hunt", params={"q": "city bike", "depth": 2}).read()
    assert seen["max_sources"] == min(60, hunt_mod.DEFAULT_MAX_SOURCES * 2)
    assert seen["budget_s"] == hunt_mod.DEFAULT_BUDGET_S * 1.5
    seen.clear()
    c.get("/hunt", params={"q": "city bike"}).read()
    assert seen == {}                     # a normal hunt is unchanged


def test_depth_passes_through_when_hunt_supports_it(monkeypatch):
    seen = {}

    async def fake_hunt(text, *, depth=1, **kw):
        seen.update({k: v for k, v in kw.items() if k != "result"}, depth=depth)
        if False:
            yield None

    monkeypatch.setattr(hunt_mod, "hunt", fake_hunt)
    TestClient(api.app).get("/hunt", params={"q": "city bike", "depth": 3}).read()
    assert seen == {"depth": 3}


def test_depth_is_bounded():
    c = TestClient(api.app)
    assert c.get("/hunt", params={"q": "city bike", "depth": 9}).status_code == 422


def test_status_peeks_at_the_bucket_without_taking(monkeypatch, tmp_path):
    from agora import contextdev
    monkeypatch.setattr(contextdev, "cache_root", lambda: tmp_path)
    (tmp_path / "contextdev_bucket.json").write_text(json.dumps({"tokens": 2.0, "ts": 0}))
    b = TestClient(api.app).get("/status").json()["bucket"]
    assert b["per_min"] == contextdev.RATE_PER_MIN and b["tokens"] == b["size"]   # refilled long ago
    import time
    (tmp_path / "contextdev_bucket.json").write_text(json.dumps({"tokens": 1.0, "ts": time.time()}))
    b = TestClient(api.app).get("/status").json()["bucket"]
    assert 1.0 <= b["tokens"] < 1.5
    assert json.loads((tmp_path / "contextdev_bucket.json").read_text())["tokens"] == 1.0   # nothing taken


def test_city_bike_recording_has_scope_and_market():
    assert "city-bike-with-basket" in hunt_mod.recordings()
    events = hunt_mod.load_recording("city-bike-with-basket")
    types = [e.type for e in events]
    assert types.index("scope") < types.index("market") < types.index("done")
    market = next(e.data for e in events if e.type == "market")
    assert market["total"] > 10000 and len(market["sources"]) == 4
    assert sum(1 for t in types if t == "offer") > 300


def test_viewer_has_the_market_and_listing_modules():
    web = ROOT / "agora" / "web"
    html = (web / "index.html").read_text()
    assert 'id="market"' in html and "/web/css/listings.css" in html
    main = (web / "js" / "main.js").read_text()
    assert "'market'" in main and "mountMarket" in main
