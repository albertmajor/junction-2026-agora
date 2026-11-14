"""Offline tests for store / watch / buy / mockshop. No network: fake hunt, fake monitor, mock ntfy."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora import proof, buy, mockshop, store, watch
from agora.models import Event, Need, Offer, TrueCost

DEMO = "sony-a7iii"


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("AGORA_NTFY_TOPIC", raising=False)
    monkeypatch.setenv("AGORA_BASE_URL", "http://test")
    mockshop.reset()
    watch._SEEN_DELIVERIES.clear()


def run(coro):
    return asyncio.run(coro)


def offer(url, price, trust=0.9, cond="used", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2], title="Sony A7 III", price=price, currency="EUR",
                 price_eur=price, condition=cond, trust=trust, in_stock=True, **kw)


def fake_hunt(offers, true_costs=None):
    async def hunt(text):
        yield Event("need", {"need": text})
        for o in offers:
            yield Event("offer", {"offer": o})
        for url, tc in (true_costs or {}).items():
            yield Event("truecost", {"url": url, "true_cost": tc})
    return hunt


NEED = Need(raw="sony a7 iii body under 900", thing="sony a7 iii body", budget=900)


# ---- store ------------------------------------------------------------------

def test_store_roundtrip():
    store.snapshot("u", 10.0, True, seen_at=1)
    store.snapshot("u", 9.0, False, seen_at=2)
    h = store.history("u")
    assert [x["price_eur"] for x in h] == [10.0, 9.0] and h[1]["in_stock"] is False
    store.save_offer(offer("https://a.com/x", 5))
    assert store.get_offer("https://a.com/x")["price_eur"] == 5
    store.log_decision("w", "u", 1.0, "skip", "nope")
    assert store.decisions("w")[0]["reason"] == "nope"


# ---- rule -------------------------------------------------------------------

def test_evaluate_lines():
    rule = {"max_price_eur": 900, "min_trust": 0.7, "conditions": ["used", "new"]}
    assert watch.evaluate(rule, {"price_eur": 872, "trust": 0.4, "condition": "used"}) == \
        (False, "skipped: trust 0.40 < 0.70")
    ok, line = watch.evaluate(rule, {"price_eur": 872, "trust": 0.9, "condition": "used"})
    assert ok and line.startswith("match: €872 <= €900")
    assert watch.evaluate(rule, {"price_eur": 950, "trust": 0.9, "condition": "used"})[1] == "skipped: €950 > €900"
    assert "condition rental" in watch.evaluate(rule, {"price_eur": 1, "trust": 1, "condition": "rental"})[1]
    assert watch.evaluate({"max_true_cost_eur": 300}, {"price_eur": 800, "true_cost": {"total_eur": 350}})[1] \
        == "skipped: true cost €350 > €300"
    assert watch.evaluate({"max_km": 50}, {"price_eur": 800, "km": 80})[1] == "skipped: 80 km > 50 km"


# ---- check_watch with a fake hunt ------------------------------------------

def test_check_watch_logs_every_candidate_and_notifies():
    w = watch.create_watch(NEED, {"min_trust": 0.7, "conditions": ["used"]}, action="notify")
    assert w["rule"]["max_price_eur"] == 900          # from need budget
    tc = TrueCost(months=12, sticker_eur=860, extras_eur=0, resale_eur=600, total_eur=260,
                  per_month_eur=21.7, confidence="medium")
    hunt = fake_hunt([offer("https://shady.com/1", 700, trust=0.4), offer("https://good.de/2", 872),
                      offer("https://pricey.fi/3", 990)], {"https://good.de/2": tc})
    events = run(watch.check_watch(w["id"], hunt=hunt))
    lines = [e.data["line"] for e in events if e.type == "decision"]
    assert "skipped: trust 0.40 < 0.70" in lines
    assert any(line.startswith("match: €872 <= €900") for line in lines)
    assert "skipped: €990 > €900" in lines
    act = next(e for e in events if e.type == "action")
    assert act.data["result"]["level"] == "L1" and act.data["result"]["notified"]["sent"] is False
    assert len(store.history("https://good.de/2")) == 1
    log = store.decisions(w["id"])
    assert [d["outcome"] for d in log].count("skip") == 2 and log[0]["outcome"] == "created"
    # second pass at the same price: held, no double notify
    events = run(watch.check_watch(w["id"], hunt=hunt))
    assert not any(e.type == "action" for e in events)
    assert any("held" in e.data.get("line", "") for e in events)


def test_true_cost_rule_uses_truecost_events():
    w = watch.create_watch(NEED, {"max_true_cost_eur": 300}, action="one_tap")
    tc = {"total_eur": 260}
    events = run(watch.check_watch(w["id"], hunt=fake_hunt([offer("https://good.de/2", 860)],
                                                             {"https://good.de/2": tc})))
    act = next(e for e in events if e.type == "action")
    assert act.data["result"]["level"] == "L2" and "utm_source=agora" in act.data["result"]["link"]


def test_no_match_gives_honest_forecast():
    w = watch.create_watch(NEED, {}, action="notify")
    events = run(watch.check_watch(w["id"], hunt=fake_hunt([offer("https://a.de/1", 990)])))
    f = next(e for e in events if e.type == "forecast")
    assert f.data["advice"] is None and "too little history" in f.data["basis"]


# ---- auto-buy on the mock shop ---------------------------------------------

def demo_watch(**mandate_kw):
    m = {"cap_eur": 950, "expires_at": "2099-12-31", "merchants": [mockshop.DOMAIN]} | mandate_kw
    return watch.create_watch(NEED, {"max_price_eur": 900, "min_trust": 0.7}, action="auto_buy",
                              mandate=m, pinned_urls=[mockshop.product_url(DEMO)], use_hunt=False)


def test_stage_demo_price_drop_buys_via_http():
    w = demo_watch()
    app = FastAPI()
    app.include_router(mockshop.router)
    c = TestClient(app)
    r = c.post(f"/mockshop/products/{DEMO}/price", json={"price_eur": 950}).json()
    assert not any(e["type"] == "action" for e in r["watch_events"])     # still above target
    r = c.post(f"/mockshop/products/{DEMO}/price", json={"price_eur": 872}).json()
    act = next(e for e in r["watch_events"] if e["type"] == "action")["data"]["result"]
    assert act["status"] == "bought" and act["level"] == "L3"
    assert act["savings_line"] == "bought at €872, €28 under target, €127 less than the day you set the watch"
    assert c.get("/mockshop/orders").json()[0]["total_eur"] == 872
    assert store.get_watch(w["id"])["status"] == "filled" and not store.get_watch(w["id"])["active"]
    assert store.purchases(w["id"])[0]["price_eur"] == 872
    # filled watch does not buy again
    r = c.post(f"/mockshop/products/{DEMO}/price", json={"price_eur": 800}).json()
    assert r["watch_events"] == [] and len(mockshop.ORDERS) == 1


def test_mandate_blocks_and_degrades_to_one_tap():
    w = demo_watch(require_confirm_above_eur=500)
    mockshop.set_price(DEMO, 872)
    events = run(watch.check_pinned(mockshop.product_url(DEMO)))
    res = next(e for e in events if e.type == "action").data["result"]
    assert res["status"] == "link_sent" and "needs your confirm" in res["reason"]
    assert mockshop.ORDERS == [] and store.get_watch(w["id"])["active"]


def test_check_mandate_rules():
    o = {"price_eur": 872, "source": mockshop.DOMAIN}
    assert buy.check_mandate(None, o)[0] is False
    sm = proof.sign_mandate
    assert buy.check_mandate(sm({"cap_eur": 900, "expires_at": "2000-01-01"}), o) == (False, "mandate expired")
    assert "allowlist" in buy.check_mandate(sm({"cap_eur": 900, "merchants": ["ebay.com"]}), o)[1]
    assert "cap" in buy.check_mandate(sm({"cap_eur": 800}), o)[1]
    assert buy.check_mandate(sm({"cap_eur": 900, "expires_at": time.time() + 60}), o)[0] is True
    assert "not signed" in buy.check_mandate({"cap_eur": 900}, o)[1]
    assert "no spending cap" in buy.check_mandate(sm({"cap_eur": None}), o)[1]


def test_auto_buy_refuses_real_shops():
    w = watch.create_watch(NEED, {}, action="auto_buy", mandate={"cap_eur": 2000})
    res = run(buy.act(w, offer("https://bigshop.de/x", 800)))
    assert res["level"] == "L2" and "mock shop" in res["reason"]


def test_auto_buy_needs_mandate():
    with pytest.raises(ValueError):
        watch.create_watch(NEED, {}, action="auto_buy")


# ---- ntfy -------------------------------------------------------------------

def test_ntfy_notify_with_mock_transport(monkeypatch):
    monkeypatch.setenv("AGORA_NTFY_TOPIC", "agora-test-topic")
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["body"], seen["click"] = str(req.url), req.content.decode(), req.headers.get("click")
        return httpx.Response(200)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await buy.notify("Agora", "A7 III at €872", click="https://x", client=c)

    assert run(go())["sent"] is True
    assert seen["url"].endswith("/agora-test-topic") and "€872" in seen["body"] and seen["click"] == "https://x"


# ---- monitors + webhook -----------------------------------------------------

def test_monitor_and_webhook_trigger_check():
    w = watch.create_watch(NEED, {"max_price_eur": 900}, action="auto_buy",
                           mandate={"cap_eur": 1000, "merchants": [mockshop.DOMAIN]}, use_hunt=False)
    calls = {}

    async def fake_create(**kw):
        calls.update(kw)
        return {"id": "mon_123"}

    url = mockshop.product_url(DEMO)
    mon = run(watch.create_page_monitor(w["id"], url, "https://hook", creator=fake_create))
    assert mon["monitor_id"] == "mon_123" and "drops below €900" in calls["instructions"]
    mockshop.set_price(DEMO, 880)
    payload = {"type": "change.detected", "data": {"monitor_id": "mon_123", "summary": "price now €880"}}
    out = run(watch.handle_monitor_webhook(payload, delivery_id="d1"))
    evs = out["watches"][0]["events"]
    assert any(e["type"] == "action" and e["data"]["result"]["status"] == "bought" for e in evs)
    assert run(watch.handle_monitor_webhook(payload, delivery_id="d1"))["duplicate"] is True
    assert any(d["outcome"] == "monitor" and "€880" in d["reason"] for d in store.decisions(w["id"]))


# ---- forecast ---------------------------------------------------------------

def test_forecast_trend_and_honesty():
    day = 86400
    pts = [(i * day, 1000 - 5 * i) for i in range(10)]          # -5 €/day, now 955
    f = watch.forecast(pts, 900)
    assert f["advice"] == "wait ~11 days" and f["slope_eur_per_day"] == -5.0
    assert watch.forecast([(0, 999), (3600, 990)], 900)["advice"] is None
    assert watch.forecast([(0, 880)], 900)["advice"] == "buy now"
    flat = watch.forecast([(i * day, 1000) for i in range(5)], 900)
    assert "no drop" in flat["basis"]


# ---- mockshop HTTP ----------------------------------------------------------

def test_mockshop_acp_checkout_and_jsonld():
    app = FastAPI()
    app.include_router(mockshop.router)
    c = TestClient(app)
    page = c.get(f"/mockshop/p/{DEMO}").text
    ld = json.loads(page.split("application/ld+json'>")[1].split("</script>")[0])
    assert ld["offers"]["price"] == "999.00"
    s = c.post("/mockshop/checkout_sessions", json={"items": [{"id": DEMO, "quantity": 1}]}).json()
    assert s["status"] == "ready_for_payment" and s["totals"]["total_eur"] == 999
    o = c.post(f"/mockshop/checkout_sessions/{s['id']}/complete", json={"payment_token": "tok_1234"}).json()
    assert o["status"] == "confirmed"
    assert c.post(f"/mockshop/checkout_sessions/{s['id']}/complete", json={"payment_token": "t"}).status_code == 409
    assert c.get(f"/mockshop/products/{DEMO}").json()["stock"] == 2
    assert c.post("/mockshop/checkout_sessions", json={"items": [{"id": "nope"}]}).status_code == 404


def test_snapshot_dedupe_and_thing_history():
    store.snapshot("u", 10.0, True)
    store.snapshot("u", 10.0, True)                     # same point twice within 60 s
    assert len(store.history("u")) == 1
    store.save_offer(offer("https://a.com/x", 5, thing_id="t1"))
    store.snapshot("https://a.com/x", 5.0, True)
    assert list(store.thing_history("t1")) == ["https://a.com/x"]


def test_api_shaped_create_and_list():
    w = watch.create_watch(need="sony a7 iii", max_price_eur=850, action="notify")
    assert w["rule"]["max_price_eur"] == 850
    assert "price <= €850" in watch.list_watches()[0]["rule_text"]
    assert watch.handle_webhook is watch.handle_monitor_webhook


def test_min_trust_rule_reads_trust_from_real_hunt_truecost_events():
    """The real hunt sends offers as plain dicts and puts trust only on the later truecost event."""
    import asyncio

    from agora import watch
    from agora.models import Event

    url = "https://shop.fi/p/a7"

    async def fake_hunt(text):
        yield Event("offer", {"offer": {"url": url, "source": "shop.fi", "title": "Sony A7 III", "price": 850,
                                        "currency": "EUR", "price_eur": 850, "condition": "used"}})
        yield Event("truecost", {"url": url, "true_cost": None, "trust": 0.9, "flags": []})

    w = watch.create_watch("sony a7 iii", rule={"max_price_eur": 900, "min_trust": 0.7})
    events = asyncio.run(watch.check_watch(w["id"], hunt=fake_hunt))
    decision = next(e for e in events if e.type == "decision")
    assert decision.data["match"] is True, decision.data["line"]
