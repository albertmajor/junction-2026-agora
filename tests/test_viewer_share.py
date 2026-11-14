"""Viewer page, static assets, share links and attributed outbound clicks (offline)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from agora import api, mockshop, share


@pytest.fixture
def c():
    mockshop.reset()
    return TestClient(api.app)


def test_root_serves_viewer_to_browsers_and_json_to_agents(c):
    html = c.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "/web/js/main.js" in html.text  # the line (agora/web)
    lab = c.get("/lab", headers={"Accept": "text/html"})
    assert "/static/app.js" in lab.text and "<title>Agora Lab</title>" in lab.text
    js = c.get("/")
    assert js.headers["content-type"].startswith("application/json")
    assert "POST /share" in js.json()["endpoints"]
    assert c.get("/api").json()["endpoints"] == js.json()["endpoints"]
    assert c.get("/viewer").headers["content-type"].startswith("text/html")


def test_static_assets(c):
    css = c.get("/static/app.css")
    assert css.status_code == 200 and "--acc" in css.text
    js = c.get("/static/app.js")
    assert js.status_code == 200 and "EventSource" in js.text
    assert c.get("/static/nope.js").status_code == 404


def test_viewer_uses_existing_endpoints(c):
    """Every path the page calls must exist on the API."""
    js = c.get("/static/app.js").text
    for path in ("/hunt?", "/recordings", "/ledger", "/share", "/go/", "/mockshop/products", "/watches",
                 "/proof", "/demo/story/refusal", "/hidden_fee", "/mockshop/reset"):
        assert path in js, path
    paths = {getattr(r, "path", "") for r in api.app.routes}
    for p in ("/hunt", "/recordings", "/ledger", "/share", "/share/{share_id}", "/s/{share_id}",
              "/go/{offer_token}", "/go/{share_id}/{offer_token}", "/watches", "/watches/{watch_id}/proof",
              "/demo/story/{name}"):
        assert p in paths, p


def test_share_roundtrip(c):
    r = c.post("/share", json={"query": "  sony a7 iii   body ", "sharer": "Albert <script>"})
    assert r.status_code == 200
    s = r.json()
    assert share.valid_id(s["id"]) and s["query"] == "sony a7 iii body" and s["sharer"] == "Albert script"
    assert s["path"] == f"/s/{s['id']}" and s["url"].endswith(s["path"])
    again = c.post("/share", json={"query": "sony a7 iii body", "sharer": "Albert script"}).json()
    assert again["id"] == s["id"]   # same query + sharer = same link
    other = c.post("/share", json={"query": "sony a7 iii body", "sharer": "mia"}).json()
    assert other["id"] != s["id"]

    o = c.get(f"/s/{s['id']}", follow_redirects=False)
    assert o.status_code == 302
    assert o.headers["location"].startswith("/?q=sony+a7+iii+body&share=" + s["id"])
    assert c.get("/s/zzzzzzz", follow_redirects=False).status_code == 404
    assert c.get("/s/../etc", follow_redirects=False).status_code == 404
    assert c.post("/share", json={"query": " "}).status_code == 422


def test_go_logs_attributed_click_and_redirects(c):
    s = c.post("/share", json={"query": "iphone 15 128gb used", "sharer": "mia"}).json()
    url = "https://www.backmarket.fi/fi-fi/p/iphone-15?x=1&y=ä"
    token = share.encode_url(url)
    assert share.decode_url(token) == url
    r = c.get(f"/go/{s['id']}/{token}", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://www.backmarket.fi/fi-fi/p/iphone-15") and "utm_source=agora" in loc
    c.get(f"/go/{token}", follow_redirects=False)            # no share: logged, not attributed
    c.get(f"/go/-/{token}", follow_redirects=False)          # explicit "no share"
    c.get(f"/go/zzzzzzz/{token}", follow_redirects=False)    # unknown share: logged, not attributed

    st = c.get(f"/share/{s['id']}").json()
    assert st["clicks"] == 1 and st["sharer"] == "mia" and st["by_domain"] == {"backmarket.fi": 1}
    assert st["recent"][0]["url"] == url
    rows = share.clicks()
    assert len(rows) == 4 and sum(1 for x in rows if x["sharer"] == "mia") == 1
    assert c.get("/share/zzzzzzz").status_code == 404


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,hi", "ftp://x.com/a", "//evil.com/x",
                                 "https://ok.com/\r\nSet-Cookie: a=b"])
def test_go_refuses_non_http_targets(c, bad):
    assert c.get(f"/go/{share.encode_url(bad)}", follow_redirects=False).status_code == 400
    assert c.get("/go/%%%", follow_redirects=False).status_code in (400, 404)
    assert share.clicks() == []


def test_share_store_helpers():
    a = share.create_share("home cleaning helsinki 60m2", "")
    assert a["sharer"] == "anonymous"
    assert share.get_share(a["id"])["query"] == "home cleaning helsinki 60m2"
    assert share.get_share("nope") is None
    with pytest.raises(ValueError):
        share.create_share("x")
    row = share.log_click("https://cleava.fi/en/", a["id"])
    assert row["sharer"] == "anonymous" and row["domain"] == "cleava.fi" and row["id"]
    assert share.stats(a["id"])["clicks"] == 1
    assert share.clicks(sharer="anonymous")[0]["url"] == "https://cleava.fi/en/"


def test_viewer_watch_flow_on_mockshop(c):
    """Exactly what the WATCH panel does: arm with a mandate, drop the price on stage, read the proof."""
    p = next(x for x in c.get("/mockshop/products").json() if x["id"] == "sony-a7iii")
    w = c.post("/watches", json={
        "query": "sony a7 iii body", "max_eur": 771, "action": "auto_buy",
        "mandate": {"cap_eur": 780, "expires_at": time.time() + 7 * 86400, "merchants": [mockshop.DOMAIN]},
        "pinned_urls": [p["url"]], "use_hunt": False}).json()
    assert w["mandate"]["signature"]

    hi = c.post("/mockshop/products/sony-a7iii/price", json={"price_eur": 980, "fire": True}).json()
    assert not [e for e in hi["watch_events"] if e["type"] == "action" and e["data"]["watch_id"] == w["id"]]
    lo = c.post("/mockshop/products/sony-a7iii/price", json={"price_eur": 760, "fire": True}).json()
    act = next(e for e in lo["watch_events"] if e["type"] == "action" and e["data"]["watch_id"] == w["id"])
    assert act["data"]["result"]["status"] == "bought"
    assert act["data"]["result"]["receipt"]["paid_eur"] == 760

    proof = c.get(f"/watches/{w['id']}/proof").json()
    assert proof["chain_ok"] and proof["signature_ok"]
    assert [r["outcome"] for r in proof["chain"]][-1] == "act"
    assert proof["purchases"][0]["data"]["order_id"] == act["data"]["result"]["receipt"]["order_id"]


def test_viewer_replay_stream_shapes(c):
    """The viewer renders a recorded hunt: check the fields it reads are there."""
    with c.stream("GET", "/hunt", params={"q": "sony a7 iii body", "replay": "auto", "speed": 16}) as r:
        body = "".join(r.iter_text())
    evs = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    types = {e["type"] for e in evs}
    assert {"need", "source", "offer", "truecost", "verdict", "budget", "done"} <= types
    tc = next(e["data"] for e in evs if e["type"] == "truecost" and e["data"].get("true_cost"))
    assert {"receipt", "basis", "per_month_eur", "per"} <= set(tc["true_cost"])
    assert any(e["data"].get("provisional") for e in evs if e["type"] == "verdict")
