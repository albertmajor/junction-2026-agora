"""The night shift buys the hunt's own pick: the used tori.fi body, through escrow, fully offline."""
import asyncio
import json
import socket

import httpx
import pytest


@pytest.fixture
def no_network(monkeypatch):
    """Any real socket or HTTP send fails the test (the in-process MockTransport still works)."""
    calls: list[str] = []

    def refuse_connect(self, *a, **k):
        calls.append(f"socket.connect {a}")
        raise OSError("network disabled in this test")

    real_send = httpx.AsyncClient.send

    async def guarded_send(self, request, *a, **k):
        if not isinstance(self._transport, httpx.MockTransport):
            calls.append(f"httpx {request.url}")
            raise httpx.ConnectError("network disabled in this test", request=request)
        return await real_send(self, request, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_connect)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_send)
    return calls


def test_used_variant_buys_the_pick_offline(no_network):
    from agora import demo_buy, mockshop
    out: list[str] = []
    res = asyncio.run(demo_buy.run_demo(out=out.append, variant="used", target=825.0))
    text = "\n".join(out)
    assert res["status"] == "bought" and res["paid_eur"] is not None and res["paid_eur"] <= 825.0
    assert res["paid_eur"] == 819 and res["counter_offer"] and res["relist_eur"] == 859
    assert res["chain_ok"] and res["mandate_chain_ok"] is True
    assert all(c["signature_ok"] for c in res["callbacks"])
    # the five beats, the lie, the haggle citing the €825 tori.fi price, escrow, proof
    for beat in ("1  ARM", "2  LIE DETECTOR", "3  HAGGLE", "4  BUY", "5  PROOF"):
        assert beat in text
    assert "Myyty" in text and "competitor €825 at tori.fi" in text and "escrow" in text and "verified" in text
    assert res["escrow"] and res["escrow"]["status"] == "held" and res["escrow"]["listing_url"] == mockshop.TORI_LISTING
    assert res["condition"] == "used" and "tori.fi" in res["seller"]
    assert no_network == []


def test_used_listing_seed_is_the_recorded_tori_listing():
    from agora import demo_buy, mockshop
    mockshop.reset()
    seen = demo_buy.recorded_offer(mockshop.TORI_LISTING)
    p = mockshop.get_product(mockshop.USED_TORI_PID)
    assert p.condition == "used" and p.seller_type == "private"
    assert p.title == seen["title"] and p.image == seen["image"]
    assert "UsedCondition" in mockshop.page_html(p.id)
    # the existing products are untouched
    cam = mockshop.get_product("sony-a7iii")
    assert (cam.price_eur, cam.condition, cam.seller_type) == (999.0, "new", "shop")
    assert mockshop.as_offer("sony-a7iii").flags == ["demo merchant"]
    assert mockshop.counter_rule(1099, 10, 1029) == (1028.0, "beats the competitor by €1")


def test_demo_buy_sse_used_variant(no_network):
    from fastapi.testclient import TestClient
    from agora.api import app
    with TestClient(app) as c:
        r = c.get("/demo/buy?pause=0&variant=used&target=825")
        assert c.get("/demo/buy?pause=0&variant=bogus").status_code == 422
        assert c.get("/demo/buy?pause=0&variant=used&target=0").status_code == 422
    evs = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    titles = [e["data"].get("title") for e in evs if e["type"] == "story"]
    assert "counter" in titles and "order" in titles and "escrow" in titles
    proof = next(e["data"] for e in evs if e["type"] == "proof")
    assert proof["chain_ok"] and proof["mandate_chain_ok"] and proof["purchases"] == 1
    done = evs[-1]
    assert done["type"] == "done" and done["data"]["status"] == "bought" and done["data"]["paid_eur"] == 819.0
