"""Round-5 critic fixes: mandate replay at the shop, mandate-less completion, caller-controlled
mandates, lease routes (SSRF, tokens, ttl 0, webhook replays), cross-origin state changes. Offline."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from agora import buy, lease, mockshop, proof, store, watch
from agora.models import Need

CAM = "sony-a7iii"
NEED = Need(raw="sony a7 iii body", thing="sony a7 iii body")


@pytest.fixture(autouse=True)
def fresh_shop(monkeypatch):
    monkeypatch.setenv("AGORA_BASE_URL", "http://test")
    mockshop.reset()
    lease.set_transport(None)
    yield
    mockshop.reset()
    lease.set_transport(None)


def armed(cap=900, **kw):
    return watch.create_watch(NEED, {"max_price_eur": 900}, action="auto_buy",
                              mandate={"cap_eur": cap, "merchants": [mockshop.DOMAIN]} | kw,
                              pinned_urls=[mockshop.product_url(CAM)], use_hunt=False)


def legit_buy(w, price=800.0):
    mockshop.set_price(CAM, price)
    o = buy.lookup_offer(buy.register_offer(w["id"], mockshop.as_offer(CAM)), [w["id"]])
    return asyncio.run(buy.buy_on_mockshop(w, o, w["mandate"]))


# ---- mock shop: replay + spend ledger -------------------------------------------------------------

def test_closed_mandate_cannot_be_replayed_and_shop_keeps_its_own_cap_ledger():
    w = armed(cap=900)
    res = legit_buy(w, 800)
    closed = store.get_mandate(res["receipt"]["closed_mandate_id"])
    m = w["mandate"]
    for _ in range(2):
        s = mockshop.create_checkout([{"id": CAM}], mandate_id=m["id"])
        with pytest.raises(ValueError):
            mockshop.complete_checkout(s["id"], "tok", mandate=m, closed_mandate=closed)
    assert len(mockshop.ORDERS) == 1 and mockshop.SPENT_BY_MANDATE[m["id"]] == 800.0


def test_same_closed_mandate_on_a_fresh_session_is_refused_as_replay():
    w = armed(cap=5000)
    res = legit_buy(w, 800)
    m = w["mandate"]
    closed = store.get_mandate(res["receipt"]["closed_mandate_id"])
    s = mockshop.create_checkout([{"id": CAM}])          # no mandate id on the session: only replay guard left
    with pytest.raises(ValueError, match="another checkout session|already paid"):
        mockshop.complete_checkout(s["id"], "tok", closed_mandate=closed)
    assert len(mockshop.ORDERS) == 1 and m["id"] in mockshop.SPENT_BY_MANDATE


def test_shop_refuses_cumulative_spend_over_cap():
    w = armed(cap=900)
    m = w["mandate"]
    mockshop.SPENT_BY_MANDATE[m["id"]] = 500.0
    s = mockshop.create_checkout([{"id": CAM}], mandate_id=m["id"])
    with pytest.raises(ValueError, match="over mandate cap"):
        mockshop.complete_checkout(s["id"], "tok", mandate=m)


def test_mandate_session_cannot_be_paid_without_the_mandate():
    w = armed()
    s = mockshop.create_checkout([{"id": CAM}], mandate_id=w["mandate"]["id"])
    with pytest.raises(ValueError, match="opened under a mandate"):
        mockshop.complete_checkout(s["id"], "tok")
    from agora.api import app
    c = TestClient(app)
    r = c.post(f"/mockshop/checkout_sessions/{s['id']}/complete", json={"payment_token": "tok"})
    assert r.status_code == 409 and "mandate" in r.json()["detail"]
    assert mockshop.ORDERS == []


def test_plain_sessions_still_pay_without_a_mandate():
    s = mockshop.create_checkout([{"id": CAM}])
    assert mockshop.complete_checkout(s["id"], "tok")["status"] == "confirmed"


# ---- caller-controlled mandates -------------------------------------------------------------------

def test_caller_cannot_choose_mandate_id_or_widen_constraints():
    first = armed()
    second = watch.create_watch(NEED, {}, action="auto_buy",
                                mandate={"cap_eur": 900, "id": first["mandate"]["id"], "constraints": {}},
                                pinned_urls=[mockshop.product_url(CAM)], use_hunt=False)
    assert second["mandate"]["id"] != first["mandate"]["id"]
    assert second["mandate"]["constraints"]["product_ids"] == [CAM]
    assert store.get_mandate(first["mandate"]["id"])["signature"] == first["mandate"]["signature"]
    with pytest.raises(ValueError, match="narrow"):
        watch.create_watch(NEED, {}, action="auto_buy", mandate={"cap_eur": 900, "constraints": {"product_ids": ["x"]}},
                           pinned_urls=[mockshop.product_url(CAM)], use_hunt=False)


def test_auto_buy_needs_a_positive_cap():
    for m in ({}, {"cap_eur": None}, {"cap_eur": 0}):
        with pytest.raises(ValueError, match="cap_eur"):
            watch.create_watch(NEED, {}, action="auto_buy", mandate=m, use_hunt=False)
    from agora.api import app
    r = TestClient(app).post("/watches", json={"query": "macbook air m3", "action": "auto_buy", "mandate": {}})
    assert r.status_code == 422


# ---- leases -------------------------------------------------------------------------------------

def test_lease_refuses_metadata_private_and_loopback_callbacks():
    w = watch.create_watch(NEED, {"max_price_eur": 900})
    for bad in ("http://169.254.169.254/latest/meta-data", "http://10.0.0.5/h", "http://127.0.0.1:9/h",
                "http://localhost/h", "http://[::1]/h", "http://192.168.1.2/h"):
        with pytest.raises(lease.LeaseError):
            lease.create_lease(w["id"], bad)


def test_lease_routes_need_the_management_token_and_ttl_zero_is_an_error():
    from agora.api import app
    w = watch.create_watch(NEED, {"max_price_eur": 900})
    c = TestClient(app)
    assert c.post(f"/watches/{w['id']}/leases", json={"callback_url": "https://a.example/h", "ttl_s": 0}).status_code == 422
    r = c.post(f"/watches/{w['id']}/leases", json={"callback_url": "https://a.example/h", "client_id": "alice"}).json()
    assert r["manage_token"].startswith("lmt_")
    assert c.get("/leases").status_code == 422
    listed = c.get("/leases", params={"client_id": "alice"}).json()
    assert listed and "callback_url" not in listed[0] and "secret" not in listed[0]
    assert c.delete(f"/leases/{r['id']}").status_code == 403
    assert c.delete(f"/leases/{r['id']}", headers={"x-lease-token": "lmt_wrong"}).status_code == 403
    own = c.get("/leases", params={"lease_id": r["id"]}, headers={"x-lease-token": r["manage_token"]}).json()
    assert own[0]["callback_url"] == "https://a.example/h"
    assert c.delete(f"/leases/{r['id']}", headers={"x-lease-token": r["manage_token"]}).status_code == 200


def test_verify_dedupes_webhook_ids():
    secret = lease.new_secret()
    body = '{"type":"watch.match"}'
    h = lease.headers_for(secret, "msg_1", int(time.time()), body)
    seen: set[str] = set()
    assert lease.verify(secret, h, body, seen_ids=seen)
    assert not lease.verify(secret, h, body, seen_ids=seen)      # captured and replayed: refused


# ---- HTTP: cross-origin state changes, webhook throttle ------------------------------------------

def test_foreign_origin_cannot_arm_or_move_prices():
    from agora.api import app
    c = TestClient(app)
    evil = {"Origin": "https://evil.example"}
    assert c.post("/watches", json={"query": "sony a7 iii"}, headers=evil).status_code == 403
    assert c.post(f"/mockshop/products/{CAM}/price", json={"price_eur": 1, "fire": False}, headers=evil).status_code == 403
    assert c.get("/demo/buy?pause=0", headers=evil).status_code == 403
    assert mockshop.get_product(CAM).price_eur == 999.0
    same = {"Origin": "http://testserver"}
    assert c.post(f"/mockshop/products/{CAM}/price", json={"price_eur": 990, "fire": False}, headers=same).status_code == 200
    assert c.get("/hunt?q=xx&replay=nope", headers=evil).status_code == 404     # reads stay open


def test_demo_token_required_for_scripts_when_set(monkeypatch):
    from agora.api import app
    monkeypatch.setenv("AGORA_DEMO_TOKEN", "t0k")
    c = TestClient(app)
    assert c.post("/mockshop/reset").status_code == 401
    assert c.post("/mockshop/reset", headers={"x-agora-token": "t0k"}).status_code == 200


def test_contextdev_hook_is_throttled_per_url(monkeypatch):
    from agora import api
    calls = []

    async def fake(payload, delivery_id=None):
        calls.append(payload)
        return {"ok": True}

    monkeypatch.setattr(watch, "handle_monitor_webhook", fake)
    monkeypatch.setattr(watch, "handle_webhook", fake)
    api._hook_last.clear()
    c = TestClient(api.app)
    assert c.post("/hooks/contextdev", json={"url": "https://shop.example/a"}).json()["ok"]
    assert c.post("/hooks/contextdev", json={"url": "https://shop.example/a"}).json().get("throttled")
    assert len(calls) == 1
    monkeypatch.setenv("CONTEXT_DEV_WEBHOOK_SECRET", lease.new_secret())
    assert c.post("/hooks/contextdev", json={"url": "https://shop.example/b"}).status_code == 401


def test_demo_tamper_breaks_the_chain_where_it_was_edited():
    from agora.api import app
    w = armed(cap=900)
    legit_buy(w, 800)
    c = TestClient(app)
    r = c.post("/demo/tamper", json={"watch_id": w["id"]}).json()
    assert r["chain_ok"] is False and r["first_broken_index"] == r["index"] and r["now"] != r["was"]
    assert c.post("/demo/tamper", json={"watch_id": "nope"}).status_code == 404
