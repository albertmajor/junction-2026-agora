"""Signed mandates + the hash-chained decision log (agora.proof)."""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from agora import api, buy, mockshop, proof, store, watch
from agora.models import Need

DEMO = "sony-a7iii"
NEED = Need(raw="sony a7 iii body", thing="sony a7 iii body")


@pytest.fixture(autouse=True)
def fresh_shop():
    mockshop.reset()
    yield
    mockshop.reset()


def demo_watch(**kw):
    m = {"cap_eur": 950, "expires_at": "2099-12-31", "merchants": [mockshop.DOMAIN]} | kw
    return watch.create_watch(NEED, {"max_price_eur": 900}, action="auto_buy", mandate=m,
                              pinned_urls=[mockshop.product_url(DEMO)], use_hunt=False)


def test_mandate_is_signed_and_verifies():
    w = demo_watch()
    m = w["mandate"]
    assert m["alg"] == "HMAC-SHA256" and len(m["signature"]) == 64 and m["need"] == "sony a7 iii body"
    assert proof.verify_mandate(m)
    assert not proof.verify_mandate(m | {"cap_eur": 5000})
    assert not proof.verify_mandate({k: v for k, v in m.items() if k != "signature"})


def test_tampered_cap_blocks_the_buy():
    w = demo_watch()
    data = store.get_watch(w["id"])
    data.pop("active")
    data["mandate"]["cap_eur"] = 5000                  # someone edits the database
    store.save_watch(w["id"], data)
    mockshop.set_price(DEMO, 872)
    events = asyncio.run(watch.check_pinned(mockshop.product_url(DEMO)))
    res = next(e for e in events if e.type == "action").data["result"]
    assert res["status"] == "link_sent" and "mandate signature invalid" in res["reason"]
    assert mockshop.ORDERS == []


def test_mock_shop_checks_the_mandate_itself():
    w = demo_watch()
    m = w["mandate"]
    mockshop.set_price(DEMO, 872)
    s = mockshop.create_checkout([{"id": DEMO, "quantity": 1}], mandate_id=m["id"])
    with pytest.raises(ValueError, match="signature invalid"):
        mockshop.complete_checkout(s["id"], "tok", mandate=m | {"cap_eur": 99999})
    other = proof.sign_mandate({"id": "mandate_other", "cap_eur": 5000})
    with pytest.raises(ValueError, match="does not match"):
        mockshop.complete_checkout(s["id"], "tok", mandate=other)
    small = proof.sign_mandate({"id": m["id"], "cap_eur": 100})
    with pytest.raises(ValueError, match="over mandate cap"):
        mockshop.complete_checkout(s["id"], "tok", mandate=small)
    with pytest.raises(ValueError, match="missing cart, closed_mandate"):
        mockshop.complete_checkout(s["id"], "tok", mandate=m)


def test_chain_after_a_buy_and_tamper_detection():
    w = demo_watch()
    for price in (980, 950, 872):
        mockshop.set_price(DEMO, price)
        asyncio.run(watch.check_pinned(mockshop.product_url(DEMO)))
    p = proof.watch_proof(w["id"])
    assert p["signature_ok"] and p["chain_ok"] and p["first_broken_index"] is None
    chain = p["chain"]
    assert chain[0]["prev_hash"] == proof.GENESIS and chain[0]["outcome"] == "created"
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(chain, chain[1:]))
    assert any(r["outcome"] == "act" and "bought" in r["reason"] for r in chain)
    assert p["purchases"] and p["purchases"][0]["data"]["mandate_signature"] == w["mandate"]["signature"]

    con = sqlite3.connect(store.db_path())                # rewrite history: "skipped" -> "match"
    con.execute("UPDATE decisions SET reason='match: all fine' WHERE id=(SELECT id FROM decisions "
                "WHERE watch_id=? ORDER BY id LIMIT 1 OFFSET 2)", (w["id"],))
    con.commit()
    con.close()
    bad = proof.watch_proof(w["id"])
    assert bad["chain_ok"] is False and bad["first_broken_index"] == 2


def test_proof_endpoint():
    w = demo_watch()
    c = TestClient(api.app)
    r = c.get(f"/watches/{w['id']}/proof").json()
    assert r["signature_ok"] is True and r["chain_ok"] is True and r["chain"][0]["outcome"] == "created"
    assert c.get("/watches/nope/proof").status_code == 404


def test_old_database_gets_hash_columns(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id TEXT, ts REAL, "
                "url TEXT, price_eur REAL, outcome TEXT, reason TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("AGORA_DB", str(db))
    row = store.log_decision("w", None, None, "created", "x")
    assert row["prev_hash"] == proof.GENESIS and proof.verify_chain(store.decisions("w"))[0]
