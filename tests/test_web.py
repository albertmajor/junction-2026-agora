"""The new viewer ("the line") at /, the old lab viewer at /lab, the JSON index for agents (offline)."""
import re

from fastapi.testclient import TestClient

from agora import api

HTML = {"Accept": "text/html,application/xhtml+xml"}


def c() -> TestClient:
    return TestClient(api.app)


def test_root_serves_new_viewer_to_browsers():
    r = c().get("/", headers=HTML)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="/web/js/main.js"></script>' in r.text
    assert "/static/app.js" not in r.text
    for dom_id in ("app", "bar", "ask", "q", "links", "chips", "ticker", "reading", "how-top", "start", "examples",
                   "verdict", "line", "tag", "finale", "sheet", "drawer", "agent", "lab", "rule"):
        assert re.search(rf'id="{dom_id}"', r.text), dom_id
    assert "Ranked by what you pay, all in. No paid placements." in r.text


def test_root_json_index_for_agents_unchanged():
    r = c().get("/")
    assert r.headers["content-type"].startswith("application/json")
    eps = r.json()["endpoints"]
    assert "GET /hunt?q=" in eps and "POST /share" in eps
    assert c().get("/api").json()["endpoints"] == eps


def test_lab_and_viewer_serve_old_viewer():
    for path in ("/lab", "/viewer"):
        r = c().get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert "/static/app.js" in r.text and "<title>Agora Lab</title>" in r.text
    assert c().get("/static/app.css").status_code == 200
    assert c().get("/static/app.js").status_code == 200


def test_web_assets_mounted():
    client = c()
    for path, needle in (("/web/js/core.js", "export const bus"), ("/web/js/stream.js", "EventSource"),
                         ("/web/js/main.js", "mountLine"), ("/web/css/base.css", "--paper")):
        r = client.get(path)
        assert r.status_code == 200, path
        assert needle in r.text, path
    assert client.get("/web/js/nope.js").status_code == 404
    assert client.get("/web/../api.py").status_code == 404


def test_core_contract_exports():
    js = c().get("/web/js/core.js").text
    for name in ("bus", "S"):
        assert f"export const {name}" in js
    for fn in ("emit", "on", "cutSrc", "xValue", "isSetAside", "eur", "goHref", "condLetter"):
        assert re.search(rf"export function {fn}\(", js), fn


def test_viewer_paths_exist_on_api():
    """Every path the new shell calls must exist."""
    js = c().get("/web/js/stream.js").text + c().get("/web/js/core.js").text
    for p in ("/hunt?", "/recordings", "/go/-/", "/cut?u="):
        assert p in js, p
    paths = {getattr(r, "path", "") for r in api.app.routes}
    for p in ("/hunt", "/recordings", "/go/{share_id}/{offer_token}", "/lab", "/viewer", "/"):
        assert p in paths, p


def test_go_token_matches_core_encoding():
    """core.js goHref = '/go/-/' + url-safe base64 without padding; the API must decode it."""
    import base64
    from agora import share
    url = "https://www.tori.fi/recommerce/forsale/item/40486480?ä=1"
    tok = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    assert share.decode_url(tok) == url


def test_replay_auto_for_recorded_slug():
    with c().stream("GET", "/hunt", params={"q": "sony a7 iii body", "replay": "sony-a7-iii-body",
                                            "speed": 16, "max_gap": 0.01}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert '"type": "need"' in body and '"type": "done"' in body
    assert c().get("/hunt", params={"q": "a pony", "replay": "auto"}).status_code == 404
