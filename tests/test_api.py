import functools
import json

from fastapi.testclient import TestClient

from agora import api
from agora import hunt as hunt_mod

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(hunt_mod, "hunt", functools.partial(hunt_mod.hunt, **fk.kwargs()))
    return TestClient(api.app)


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_index_lists_endpoints(monkeypatch):
    r = client(monkeypatch).get("/")
    assert r.status_code == 200
    assert "GET /hunt?q=" in r.json()["endpoints"]


def test_hunt_streams_sse(monkeypatch):
    with client(monkeypatch).stream("GET", "/hunt", params={"q": "sony a7 iii"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = sse_events(body)
    types = [e["type"] for e in events]
    assert types[0] == "need" and types[-1] == "done"
    assert types.count("offer") == 4
    assert all("t_ms" in e and "data" in e for e in events)
    assert "raw" not in next(e for e in events if e["type"] == "offer")["data"]["offer"]


def test_hunt_requires_query(monkeypatch):
    assert client(monkeypatch).get("/hunt").status_code == 422


def test_cors_is_not_a_wildcard(monkeypatch):
    r = client(monkeypatch).options("/hunt?q=xx", headers={"Origin": "https://evil.example",
                                                          "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") not in ("*", "https://evil.example")


def test_mockshop_mounted_if_present(monkeypatch):
    c = client(monkeypatch)
    if api._mockshop_mounted:
        assert c.get("/mockshop/products").status_code == 200
    assert c.get("/").json()["mockshop"] == api._mockshop_mounted


def test_thing_history_from_hunt_index(monkeypatch):
    class FakeStore:
        @staticmethod
        def history(url):
            return [{"url": url, "price_eur": 1.0}]

    monkeypatch.setitem(hunt_mod.THING_URLS, "t-test", {"https://a.example/x"})
    monkeypatch.setattr(api, "_module", lambda name: FakeStore if name == "store" else None)
    r = client(monkeypatch).get("/things/t-test/history")
    assert r.status_code == 200
    assert r.json()["history"]["https://a.example/x"][0]["price_eur"] == 1.0
    assert client(monkeypatch).get("/things/nope/history").status_code == 404


def test_missing_module_is_503(monkeypatch):
    monkeypatch.setattr(api, "_module", lambda name: None)
    assert client(monkeypatch).get("/ledger").status_code == 503


def test_create_and_list_watch_via_engine(monkeypatch):
    made = {}

    class FakeWatch:
        @staticmethod
        def create_watch(need, max_price_eur=None, action="notify"):
            if action not in ("notify", "one_tap", "auto_buy"):
                raise ValueError("bad action")
            made.update(need=need, max_price_eur=max_price_eur)
            return {"id": "w1", "action": action}

        @staticmethod
        def list_watches():
            return [{"id": "w1"}]

    monkeypatch.setattr(api, "_module", lambda name: FakeWatch if name == "watch" else None)
    c = client(monkeypatch)
    r = c.post("/watches", json={"need": "sony a7 iii", "max_price_eur": 900})
    assert r.status_code == 200 and r.json()["id"] == "w1"
    assert c.post("/watches", json={"need": "x", "action": "nope"}).status_code == 422
    made.clear()
    assert c.post("/watches", json={"query": "dyson v15", "max_eur": 450}).status_code == 200
    assert made == {"need": "dyson v15", "max_price_eur": 450}
    assert c.get("/watches").json() == [{"id": "w1"}]


def test_arm_suggests_price_to_beat_watches():
    from agora import mcp_server as ms
    ms.configure(**fk.kwargs())
    try:
        c = TestClient(api.app)
        r = c.post("/arm", json={"query": "used sony a7 iii under 900"})
        assert r.status_code == 200
        body = r.json()
        assert body["created"] == []
        for s in body["suggestions"]:
            assert s["rule"]["max_price_eur"] == s["beat_eur"] < s["price_eur"]
        assert c.post("/arm", json={}).status_code == 422
    finally:
        ms.configure()
