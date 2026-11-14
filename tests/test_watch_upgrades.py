"""Watch upgrades: JSON Logic rules, min move, restock-only, unchanged skip, sold-out lie detector,
haggle loop, provenance gate, open -> closed mandate chain, agent watch leases, the demo-buy story.
All offline."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora import buy, lease, mcp_server, mockshop, proof, store, watch
from agora.models import Event, Need, Offer

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


def run(coro):
    return asyncio.run(coro)


def offer(url, price, trust=0.9, cond="new", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2], title="Sony A7 III", price=price, currency="EUR",
                 price_eur=price, condition=cond, trust=trust, in_stock=True, **kw)


def fake_hunt(offers, extra=None):
    async def hunt(text):
        for o in offers:
            yield Event("offer", {"offer": o})
        for url, data in (extra or {}).items():
            yield Event("truecost", {"url": url, "true_cost": None} | data)
    return hunt


def lines(events, type_="decision"):
    return [e.data["line"] for e in events if e.type == type_]


# ---- JSON Logic ---------------------------------------------------------------------------------

def test_logic_rule_matches_skips_and_explains():
    rule = {"logic": {"and": [{"<=": [{"var": "price_eur"}, 900]},
                              {"!": {"in": ["grey import", {"var": "flags_text"}]}}]}}
    ok, line = watch.evaluate(rule, {"price_eur": 850, "flags": []})
    assert ok and "rule ok" in line and "price_eur <= 900" in line
    ok, line = watch.evaluate(rule, {"price_eur": 850, "flags": ["possible grey import: no EU warranty"]})
    assert not ok and line.startswith("skipped: rule failed")
    # a variable the rule needs but we do not know is never a silent match
    ok, line = watch.evaluate({"logic": {">=": [{"var": "trust"}, 0.7]}}, {"price_eur": 1})
    assert not ok and "trust" in line and "unknown" in line


def test_logic_is_validated_at_create():
    with pytest.raises(ValueError, match="unknown variable"):
        watch.create_watch(NEED, {"logic": {"<": [{"var": "colour"}, 1]}})
    with pytest.raises(ValueError, match="invalid JSON Logic"):
        watch.create_watch(NEED, {"logic": {"frobnicate": [1, 2]}})
    w = watch.create_watch(NEED, {"max_price_eur": 900, "logic": {"==": [{"var": "condition"}, "new"]}})
    assert "condition = 'new'" in watch.list_watches()[0]["rule_text"]
    assert watch.rule_logic(w["rule"]) == {"and": [{"<=": [{"var": "price_eur"}, 900]},
                                                   {"==": [{"var": "condition"}, "new"]}]}


def test_mini_logic_fallback_agrees_with_library():
    from json_logic import jsonLogic
    logic = {"and": [{"<=": [{"var": "price_eur"}, 900]}, {"in": [{"var": "condition"}, ["new", "used"]]},
                     {"!": {"in": ["grey", {"var": "flags_text"}]}}]}
    for data in ({"price_eur": 800, "condition": "new", "flags_text": ""},
                 {"price_eur": 901, "condition": "new", "flags_text": ""},
                 {"price_eur": 800, "condition": "rental", "flags_text": ""},
                 {"price_eur": 800, "condition": "used", "flags_text": "grey import"}):
        assert bool(watch._mini_logic(logic, data)) == bool(jsonLogic(logic, data))


# ---- min move / restock / unchanged -------------------------------------------------------------

def test_min_move_pct_ignores_wiggles():
    rule = {"max_price_eur": 900, "min_move_pct": 2}
    assert watch.evaluate(rule, {"price_eur": 880}, {"ref_price": 885})[1].startswith("skipped: moved 0.6%")
    ok, line = watch.evaluate(rule, {"price_eur": 850}, {"ref_price": 885})
    assert ok and "moved 4.0%" in line
    assert watch.evaluate(rule, {"price_eur": 880})[0]          # first look: nothing to compare with


def test_restock_only_fires_on_out_to_in():
    rule = {"on_restock": True}
    assert "already in stock" in watch.evaluate(rule, {"price_eur": 9, "in_stock": True}, {"prev_in_stock": True})[1]
    assert "no stock history" in watch.evaluate(rule, {"price_eur": 9, "in_stock": True})[1]
    assert watch.evaluate(rule, {"price_eur": 9, "in_stock": True}, {"prev_in_stock": False})[0]


def test_restock_watch_end_to_end_on_mockshop():
    url = mockshop.product_url(CAM)
    w = watch.create_watch(NEED, {"on_restock": True}, pinned_urls=[url], use_hunt=False)
    mockshop.get_product(CAM).stock = 0
    ev = run(watch.check_watch(w["id"], only_pinned=True))
    assert lines(ev) == ["skipped: out of stock"]
    mockshop.get_product(CAM).stock = 2
    ev = run(watch.check_watch(w["id"], only_pinned=True))
    assert lines(ev)[0].startswith("match") and any(e.type == "action" for e in ev)


def test_unchanged_page_is_not_judged_again():
    w = watch.create_watch(NEED, {"max_price_eur": 800})
    hunt = fake_hunt([offer("https://a.de/1", 950)])
    first = lines(run(watch.check_watch(w["id"], hunt=hunt)))
    assert first == ["skipped: €950 > €800"]
    second = lines(run(watch.check_watch(w["id"], hunt=hunt)))
    assert second[0].startswith("skipped: page unchanged since last check (sha256 ")
    third = lines(run(watch.check_watch(w["id"], hunt=fake_hunt([offer("https://a.de/1", 799)]))))
    assert third[0].startswith("match")


# ---- sold-out lie detector ----------------------------------------------------------------------

@pytest.mark.parametrize("text,phrase", [
    ("Sony A7 III €999 Loppuunmyyty", "Loppuunmyyty"), ("Leider AUSVERKAUFT", "AUSVERKAUFT"),
    ("Kamera – slutsåld i butik", "slutsåld"), ("This item is out of stock.", "out of stock"),
    ("Tuote ei varastossa", "ei varastossa"), ("Rupture de stock", "Rupture de stock"),
])
def test_sold_out_phrases(text, phrase):
    assert watch.sold_out_phrase(text) == phrase


def test_sold_out_not_fooled():
    assert watch.sold_out_phrase("In stock, ships tomorrow") is None
    assert watch.sold_out_phrase("Great news: this is not sold out") is None
    assert watch.sold_out_phrase("soldout-banner-hidden outofstock") is None
    assert watch.sold_out_phrase(None) is None


def test_lie_detector_beats_jsonld_on_the_mockshop_page():
    url = mockshop.product_url(CAM)
    w = watch.create_watch(NEED, {"max_price_eur": 1200}, action="notify", pinned_urls=[url], use_hunt=False)
    mockshop.set_page_banner(CAM, "Loppuunmyyty")
    page = mockshop.page_html(CAM)
    assert '"availability": "https://schema.org/InStock"' in page and "Loppuunmyyty" in page
    ev = run(watch.check_watch(w["id"], only_pinned=True))
    d = next(e.data for e in ev if e.type == "decision")
    assert not d["match"] and "Loppuunmyyty" in d["line"] and d["lie_detector"]["structured_said"] == "InStock"
    assert store.history(url)[-1]["in_stock"] is False
    mockshop.set_page_banner(CAM, None)
    assert lines(run(watch.check_watch(w["id"], only_pinned=True)))[0].startswith("match")


# ---- freshness ----------------------------------------------------------------------------------

def test_pinned_reads_ask_for_fresh_data_when_supported(monkeypatch):
    from agora import reader
    seen = {}

    async def read_fresh(url, need, *, fresh=False, **kw):
        seen["fresh"] = fresh
        return offer(url, 500)

    monkeypatch.setattr(reader, "read", read_fresh)
    monkeypatch.setattr(reader, "read_with_reason", read_fresh)
    assert run(watch._read_pinned("https://shop.fi/a7", NEED)).price_eur == 500 and seen["fresh"] is True

    async def read_old(url, need, **kw):
        assert "fresh" not in kw
        return offer(url, 501)

    async def rwr_old(url, need, *, lane=None, snippet="", title="", paid=True):
        return None, ""

    monkeypatch.setattr(reader, "read", read_old)
    monkeypatch.setattr(reader, "read_with_reason", rwr_old)
    assert run(watch._read_pinned("https://shop.fi/a7", NEED)).price_eur == 501


# ---- haggle loop --------------------------------------------------------------------------------

def test_counter_rule():
    assert mockshop.counter_rule(1099, 10, 1029) == (1028.0, "beats the competitor by €1")
    price, why = mockshop.counter_rule(1099, 5, 900)
    assert price == 1045 and "floor" in why                      # never more than 5% off
    assert mockshop.counter_rule(1099, 10, None)[0] is None
    assert mockshop.counter_rule(1099, 10, 1200)[0] is None


def haggle_watch(target=1030.0, cap=1050.0, **rule):
    return watch.create_watch(
        NEED, {"max_price_eur": target, "min_trust": 0.7, "conditions": ["new"], "haggle": True} | rule,
        action="auto_buy", mandate={"cap_eur": cap, "merchants": [mockshop.DOMAIN], "expires_at": time.time() + 3600},
        pinned_urls=[mockshop.product_url(CAM)], use_hunt=True)


def test_decline_counter_buy():
    mockshop.set_price(CAM, 1099)
    w = haggle_watch(logic={"!": {"in": ["grey import", {"var": "flags_text"}]}})   # the rival itself is not ok
    rival = offer("https://rival.de/a7", 1029, trust=0.8,
                  flags=["possible grey import: no EU warranty"])
    ev = run(watch.check_watch(w["id"], hunt=fake_hunt([rival], {rival.url: {"trust": 0.8, "flags": rival.flags}}),
                               only_pinned=False))
    h = next(e.data for e in ev if e.type == "haggle")
    assert h["trace"]["reason_code"] == "price_sensitivity"
    assert h["trace"]["metadata"]["competitor_price_eur"] == 1029
    c = next(e.data for e in ev if e.type == "counter")["counter_offer"]
    assert c["price_eur"] == 1028 and c["was_eur"] == 1099
    act = next(e.data["result"] for e in ev if e.type == "action")
    assert act["status"] == "bought" and act["receipt"]["paid_eur"] == 1028
    assert act["receipt"]["counter_offer"] == c["code"] and mockshop.COUNTERS[c["code"]]["used"]
    assert mockshop.ORDERS[0]["line_items"][0]["unit_price_eur"] == 1028
    outcomes = [d["outcome"] for d in store.decisions(w["id"])]
    for step in ("haggle", "counter", "match", "mandate", "act"):
        assert step in outcomes
    assert outcomes.index("haggle") < outcomes.index("counter") < outcomes.index("mandate") < outcomes.index("act")
    assert mockshop.FEEDBACK[0]["trace"]["metadata"]["watch_id"] == w["id"]


def test_no_competitor_no_counter_and_no_rehaggle_at_same_price():
    mockshop.set_price(CAM, 1099)
    w = haggle_watch()
    ev = run(watch.check_watch(w["id"], hunt=fake_hunt([])))
    assert lines(ev, "counter") == ["counter: none (no competitor price given: price stays)"]
    assert not any(e.type == "action" for e in ev)
    mockshop.set_price(CAM, 1098)    # page changed, but a counter for that price was not asked yet -> asks again
    ev = run(watch.check_watch(w["id"], hunt=fake_hunt([])))
    assert len(lines(ev, "haggle")) == 1
    w2 = store.get_watch(w["id"])
    w2["fingerprints"] = {}
    w2.pop("active")
    store.save_watch(w["id"], w2)    # even when re-judged, the same price is not haggled twice
    ev = run(watch.check_watch(w["id"], hunt=fake_hunt([])))
    assert lines(ev, "haggle") == []


def test_haggle_is_opt_in():
    mockshop.set_price(CAM, 1099)
    w = haggle_watch(haggle=False)
    rival = offer("https://rival.de/a7", 1029)
    ev = run(watch.check_watch(w["id"], hunt=fake_hunt([rival])))
    assert not any(e.type in ("haggle", "counter") for e in ev) and mockshop.FEEDBACK == []


def test_mockshop_haggle_http():
    app = FastAPI()
    app.include_router(mockshop.router)
    c = TestClient(app)
    s = c.post("/mockshop/checkout_sessions", json={"items": [{"id": CAM}]}).json()
    trace = {"reason_code": "price_sensitivity", "metadata": {"competitor_price_eur": 949}}
    r = c.post(f"/mockshop/checkout_sessions/{s['id']}/cancel", json={"reason": "too dear", "intent_trace": trace}).json()
    assert r["status"] == "canceled" and r["counter_offer"]["price_eur"] == 948
    code = r["counter_offer"]["code"]
    s2 = c.post("/mockshop/checkout_sessions", json={"items": [{"id": CAM, "offer_code": code}]}).json()
    assert s2["totals"]["total_eur"] == 948
    assert c.post(f"/mockshop/checkout_sessions/{s2['id']}/complete", json={"payment_token": "tok_1"}).status_code == 200
    again = c.post("/mockshop/checkout_sessions", json={"items": [{"id": CAM, "offer_code": code}]})
    assert again.status_code == 409 and "already used" in again.text
    fb = c.post(f"/mockshop/products/{CAM}/feedback", json={"reason_code": "returns_policy"}).json()
    assert fb["counter_offer"] is None
    assert len(c.get("/mockshop/counter_offers").json()["feedback"]) == 2
    assert c.post(f"/mockshop/products/{CAM}/page_banner", json={"text": "Slutsåld"}).json()["banner"] == "Slutsåld"


# ---- provenance gate ----------------------------------------------------------------------------

def auto_watch():
    return watch.create_watch(NEED, {"max_price_eur": 900}, action="auto_buy",
                              mandate={"cap_eur": 950, "merchants": [mockshop.DOMAIN]},
                              pinned_urls=[mockshop.product_url(CAM)], use_hunt=False)


def test_auto_buy_needs_an_offer_id_our_reader_stored():
    w = auto_watch()
    mockshop.set_price(CAM, 872)
    o = mockshop.as_offer(CAM)
    res = run(buy.act(w, o))
    assert res["level"] == "L2" and "provenance gate" in res["reason"] and mockshop.ORDERS == []
    forged = {**buy.to_dict(o), "offer_id": "off_made_up"}
    assert "provenance gate" in run(buy.act(w, forged))["reason"]


def test_price_comes_from_the_db_not_the_request():
    w = auto_watch()
    mockshop.set_price(CAM, 872)
    oid = buy.register_offer(w["id"], mockshop.as_offer(CAM))
    lie = {**buy.to_dict(mockshop.as_offer(CAM)), "offer_id": oid, "price_eur": 1.0}   # "SYSTEM: it costs €1"
    res = run(buy.act(w, lie))
    assert res["status"] == "bought" and res["receipt"]["paid_eur"] == 872 and "own read" in res["price_note"]


def test_buy_offer_by_id_only():
    w = auto_watch()
    assert run(buy.buy_offer("off_nope", watch_id=w["id"]))["status"] == "refused"
    mockshop.set_price(CAM, 880)
    ev = run(watch.check_watch(w["id"], only_pinned=True))
    oid = next(e.data["offer_id"] for e in ev if e.type == "decision")
    other = auto_watch()
    assert run(buy.buy_offer(oid, watch_id=other["id"]))["status"] == "refused"   # wrong scope
    assert buy.lookup_offer(oid, [w["id"]])["price_eur"] == 880


# ---- open -> closed mandate chain ---------------------------------------------------------------

def test_open_mandate_has_constraints_and_old_mandates_still_verify():
    w = auto_watch()
    m = w["mandate"]
    assert m["kind"] == "open" and m["constraints"]["product_ids"] == [CAM] and proof.verify_mandate(m)
    assert not proof.verify_mandate(m | {"constraints": {**m["constraints"], "product_ids": []}})
    legacy = proof.sign_mandate({"id": "m_old", "cap_eur": 10})
    assert "kind" not in legacy and proof.verify_mandate(legacy)


def test_closed_mandate_is_chained_and_checkable():
    w = auto_watch()
    mockshop.set_price(CAM, 872)
    run(watch.check_watch(w["id"], only_pinned=True))
    p = watch.watch_proof(w["id"])
    mc = p["mandate_chain"]
    assert p["chain_ok"] and mc["ok"] is True and len(mc["closed"]) == 1
    link = mc["closed"][0]
    closed = link["closed"]
    assert closed["open_mandate_id"] == w["mandate"]["id"] and closed["total_eur"] == 872
    assert p["chain"][link["chain_index"]]["outcome"] == "mandate"
    assert closed["digest"] in p["chain"][link["chain_index"]]["reason"]
    assert p["purchases"][0]["data"]["closed_mandate_id"] == closed["id"]
    # a closed mandate edited afterwards fails its own signature
    store.save_mandate(closed["id"], closed | {"total_eur": 100})
    bad = watch.watch_proof(w["id"])["mandate_chain"]
    assert bad["ok"] is False
    assert {c["check"] for c in bad["closed"][0]["checks"] if not c["ok"]} >= {"closed signature"}


def test_check_closed_catches_a_cart_outside_the_open_mandate():
    open_m = proof.sign_mandate({"id": "m1", "cap_eur": 500, "merchants": ["shop.fi"], "kind": "open",
                                 "constraints": {"product_ids": ["a"]}})
    closed = proof.sign_closed_mandate({"id": "c1", "open_mandate_id": "m1", "open_mandate_digest": proof.mandate_digest(open_m),
                                        "merchant": "evil.example", "items": [{"id": "b", "quantity": 1, "unit_price_eur": 600}],
                                        "total_eur": 600, "created_at": time.time()})
    failed = {c["check"] for c in proof.check_closed_against_open(open_m, closed) if not c["ok"]}
    assert failed == {"under cap", "merchant allowed", "products allowed"}


def test_shop_refuses_a_forged_closed_mandate():
    w = auto_watch()
    m = w["mandate"]
    s = mockshop.create_checkout([{"id": CAM}], mandate_id=m["id"])
    fake = proof.sign_closed_mandate({"id": "c", "open_mandate_id": m["id"], "total_eur": 999, "items": []})
    with pytest.raises(ValueError, match="closed mandate signature invalid"):
        mockshop.complete_checkout(s["id"], "tok", closed_mandate=fake | {"total_eur": 1})
    with pytest.raises(ValueError, match="total does not match"):
        mockshop.complete_checkout(s["id"], "tok", closed_mandate=fake | {"total_eur": 1} | {
            "signature": proof.sign_closed_mandate({**fake, "total_eur": 1})["signature"]})


# ---- leases -------------------------------------------------------------------------------------

def test_standard_webhooks_signature_roundtrip():
    secret = lease.new_secret()
    assert secret.startswith("whsec_")
    body = '{"type":"watch.match"}'
    now = int(time.time())
    h = lease.headers_for(secret, "msg_1", now, body)
    assert h["webhook-signature"].startswith("v1,")
    assert lease.verify(secret, h, body)
    assert not lease.verify(secret, h, body + " ")
    assert not lease.verify(lease.new_secret(), h, body)
    assert not lease.verify(secret, h, body, now=now + 3600)            # replay outside tolerance
    multi = h | {"webhook-signature": "v1,AAAA " + h["webhook-signature"]}
    assert lease.verify(secret, multi, body)                            # key rotation: any valid sig


def test_lease_limits():
    w = watch.create_watch(NEED, {"max_price_eur": 900})
    with pytest.raises(lease.LeaseError, match="ttl"):
        lease.create_lease(w["id"], "https://a.example/h", ttl_s=60)
    with pytest.raises(lease.LeaseError, match="ttl"):
        lease.create_lease(w["id"], "https://a.example/h", ttl_s=2 * 86400)
    with pytest.raises(lease.LeaseError, match="unknown event"):
        lease.create_lease(w["id"], "https://a.example/h", ["order.paid"])
    with pytest.raises(lease.LeaseError, match="http"):
        lease.create_lease(w["id"], "file:///etc/passwd")
    with pytest.raises(lease.LeaseError, match="no watch"):
        lease.create_lease("watch_nope", "https://a.example/h")
    for _ in range(20):
        lease.create_lease(w["id"], "https://a.example/h", client_id="bot")
    with pytest.raises(lease.LeaseError, match="20 live"):
        lease.create_lease(w["id"], "https://a.example/h", client_id="bot")
    assert lease.create_lease(w["id"], "https://a.example/h", client_id="other")["id"]
    first = lease.list_leases(client_id="bot")[0]
    assert "secret" not in first
    assert lease.revoke_lease(first["id"], client_id="bot")
    assert lease.create_lease(w["id"], "https://a.example/h", client_id="bot")   # a slot is free again
    # expired leases do not count
    assert len(lease.list_leases(client_id="bot", now=time.time() + 2 * 86400)) == 0


def test_lease_delivery_signed_and_retried():
    w = auto_watch()
    got, fail = [], {"n": 2}
    lz = lease.create_lease(w["id"], "https://agent.example/cb", ["watch.match"], client_id="t", ttl_s=600)

    def handle(req):
        if fail["n"] > 0:
            fail["n"] -= 1
            return httpx.Response(503)
        got.append((dict(req.headers), req.content.decode()))
        return httpx.Response(204)

    lease.set_transport(httpx.MockTransport(handle))
    mockshop.set_price(CAM, 880)
    run(watch.check_watch(w["id"], only_pinned=True))
    d = lease.deliveries(lz["id"])[0]
    assert d["status"] == "retrying" and d["attempts"] == 1 and d["event"] == "watch.match"
    assert run(lease.retry_due()) == []                                    # backoff not over yet
    r = run(lease.retry_due(now=time.time() + 6))
    assert r[0]["status"] == "retrying" and r[0]["attempts"] == 2
    r = run(lease.retry_due(now=time.time() + 40))
    assert r[0]["status"] == "delivered"
    headers, body = got[0]
    assert headers["webhook-id"] == d["msg_id"]                            # same id on every retry
    assert lease.verify(lz["secret"], headers, body, now=int(headers["webhook-timestamp"]))
    payload = json.loads(body)
    assert payload["type"] == "watch.match" and payload["data"]["status"] == "bought"


def test_failed_deliveries_stop_and_revoked_leases_drop():
    w = watch.create_watch(NEED, {"max_price_eur": 900})
    lz = lease.create_lease(w["id"], "https://agent.example/cb", client_id="t", ttl_s=86400)
    lease.set_transport(httpx.MockTransport(lambda req: httpx.Response(500)))
    now = time.time()
    res = run(lease.publish("price.drop", w["id"], {"to_eur": 1}, now=now))
    assert res[0]["status"] == "retrying"
    t = now
    for wait in lease.BACKOFF_S:
        t += wait + 1
        out = run(lease.retry_due(now=t))
    assert out[0]["status"] == "failed" and out[0]["attempts"] == lease.MAX_ATTEMPTS
    run(lease.publish("price.drop", w["id"], {"to_eur": 1}, now=now))
    lease.revoke_lease(lz["id"])
    assert run(lease.retry_due(now=now + 10))[0]["status"] == "dropped"


def test_lease_router_and_mcp_tool():
    w = watch.create_watch(NEED, {"max_price_eur": 900})
    app = FastAPI()
    app.include_router(lease.router)
    c = TestClient(app)
    r = c.post(f"/watches/{w['id']}/leases", json={"callback_url": "https://a.example/h", "ttl_seconds": 900,
                                                    "client_id": "x"})
    assert r.status_code == 200 and r.json()["secret"].startswith("whsec_")
    assert c.post("/watches/nope/leases", json={"callback_url": "https://a.example/h"}).status_code == 404
    assert c.post(f"/watches/{w['id']}/leases", json={"callback_url": "ftp://x"}).status_code == 422
    assert [x["id"] for x in c.get("/leases", params={"client_id": "x"}).json()] == [r.json()["id"]]
    assert c.delete(f"/leases/{r.json()['id']}").status_code == 403
    assert c.delete(f"/leases/{r.json()['id']}", headers={"x-lease-token": r.json()["manage_token"]}).json()["ok"]
    m = run(mcp_server.subscribe_watch(w["id"], "https://agent.example/cb", ["price.drop"], 300))
    assert m["ok"] and m["lease"]["events"] == ["price.drop"] and m["lease"]["secret"].startswith("whsec_")
    assert run(mcp_server.subscribe_watch(w["id"], "https://agent.example/cb", ttl_seconds=5))["ok"] is False


# ---- the stage demo -----------------------------------------------------------------------------

def test_demo_buy_story_offline():
    from agora import demo_buy
    out: list[str] = []
    res = run(demo_buy.run_demo(out=out.append))
    text = "\n".join(out)
    assert res["status"] == "bought" and res["paid_eur"] == 1028 and res["counter_offer"]
    assert res["chain_ok"] and res["mandate_chain_ok"] is True
    assert "Loppuunmyyty" in text and "competitor €1,029 at e-infin.com" in text
    assert {c["body"]["type"] for c in res["callbacks"]} == {"watch.match", "price.drop"}
    assert all(c["signature_ok"] for c in res["callbacks"])
    assert "verified" in text
