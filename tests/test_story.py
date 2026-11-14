"""The refusal story: skip at €980, buy at €760, refuse a hidden checkout fee, catch a tampered log."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agora import buy, mockshop, proof, store, watch
from agora.story import run_story


@pytest.fixture(autouse=True)
def _shop():
    mockshop.reset()
    yield
    mockshop.reset()


def story_events():
    async def go():
        return [e async for e in run_story("refusal", pause=0)]
    return asyncio.run(go())


def test_full_story_offline():
    events = story_events()
    rows = [e for e in events if e.type == "watch"]
    by_step = {s: [r.data for r in rows if r.data["step"] == s] for s in range(4)}
    assert any(r["decision"] == "skip" and "€980 > €771" in r["reason"] for r in by_step[1])
    assert any(r["decision"] == "act" and "L3 bought" in r["reason"] for r in by_step[2])
    refused = [r for r in by_step[3] if r["decision"] == "refuse"]
    assert refused and "checkout total €528 ≠ mandated €489" in refused[0]["reason"]
    assert "handling fee" in refused[0]["reason"] and "nothing paid" in refused[0]["reason"]
    # the chain grows: every row points at the one before it (per watch)
    w1 = [r.data for r in rows if r.data["watch_id"] == rows[0].data["watch_id"]]
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(w1, w1[1:]))
    proofs = [e.data for e in events if e.type == "proof"]
    assert proofs[0]["chain_ok"] is True and proofs[0]["purchases"] == 1
    assert proofs[1]["chain_ok"] is False and proofs[1]["first_broken_index"] == 1
    assert len(mockshop.ORDERS) == 1 and mockshop.ORDERS[0]["total_eur"] == 760
    assert any(s["status"] == "canceled" for s in mockshop.SESSIONS.values())
    assert events[-1].type == "done"


def test_shop_also_refuses_a_cart_mismatch():
    mockshop.set_hidden_fee("sony-fe-85", 39)
    cart = proof.sign_cart({"mandate_id": "m", "merchant": mockshop.DOMAIN, "total_eur": 599.0,
                            "items": [{"id": "sony-fe-85", "quantity": 1, "unit_price_eur": 599.0}],
                            "created_at": 1})
    s = mockshop.create_checkout([{"id": "sony-fe-85", "quantity": 1}])
    assert s["totals"]["total_eur"] == 638.0
    with pytest.raises(ValueError, match="checkout total €638 ≠ mandated €599"):
        mockshop.complete_checkout(s["id"], "tok", cart=cart)
    forged = cart | {"total_eur": 638.0}
    with pytest.raises(ValueError, match="cart signature invalid"):
        mockshop.complete_checkout(s["id"], "tok", cart=forged)
    mockshop.set_hidden_fee("sony-fe-85", 0)
    s2 = mockshop.create_checkout([{"id": "sony-fe-85", "quantity": 1}])
    assert mockshop.complete_checkout(s2["id"], "tok", cart=cart)["status"] == "confirmed"


def test_refused_checkout_is_retried_when_the_fee_is_gone():
    w = watch.create_watch("sony fe 85mm", rule={"max_price_eur": 520}, action="auto_buy",
                           mandate={"cap_eur": 540, "merchants": [mockshop.DOMAIN]},
                           pinned_urls=[mockshop.product_url("sony-fe-85")], use_hunt=False)
    mockshop.set_hidden_fee("sony-fe-85", 39)
    mockshop.set_price("sony-fe-85", 489)
    evs = asyncio.run(watch.check_watch(w["id"], only_pinned=True))
    assert next(e for e in evs if e.type == "action").data["result"]["status"] == "refused"
    mockshop.set_hidden_fee("sony-fe-85", 0)
    evs = asyncio.run(watch.check_watch(w["id"], only_pinned=True))
    assert next(e for e in evs if e.type == "action").data["result"]["status"] == "bought"
    assert [d["outcome"] for d in store.decisions(w["id"])].count("refuse") == 1


def test_story_over_sse():
    from agora import api
    c = TestClient(api.app)
    r = c.post("/demo/story/refusal", params={"pause": 0})
    got = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
    types = {g["type"] for g in got}
    assert {"story", "watch", "proof", "done"} <= types
    assert c.get("/demo/story/nope").status_code == 404
