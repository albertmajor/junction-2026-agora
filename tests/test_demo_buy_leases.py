"""/demo/buy runs again and again on stage: the demo agent must never hit the 20-live-lease cap."""
import asyncio
import time

from agora import demo_buy, lease, watch


def test_demo_runs_25_times_in_a_row_without_hitting_the_lease_cap():
    for i in range(25):
        res = asyncio.run(demo_buy.run_demo(out=lambda _l: None))
        assert res["status"] == "bought", f"run {i + 1}: {res['status']}"
        assert lease.live_count(demo_buy.DEMO_CLIENT) == 0, f"run {i + 1} left a live lease"
    assert lease.live_count(demo_buy.DEMO_CLIENT) == 0


def test_used_variant_also_releases_its_lease():
    for _ in range(3):
        res = asyncio.run(demo_buy.run_demo(out=lambda _l: None, variant="used"))
        assert res["status"] == "bought"
    assert lease.live_count(demo_buy.DEMO_CLIENT) == 0


def _fill_cap(client: str) -> None:
    w = watch.create_watch("sony a7 iii", rule={"max_price_eur": 1000})
    for _ in range(lease.MAX_LIVE_PER_CLIENT):
        lease.create_lease(w["id"], "https://agent.example/h", client_id=client, ttl_s=3600)


def test_demo_recovers_when_leftover_leases_fill_the_cap():
    _fill_cap(demo_buy.DEMO_CLIENT)          # e.g. a server killed mid-story, many times over
    assert lease.live_count(demo_buy.DEMO_CLIENT) == lease.MAX_LIVE_PER_CLIENT
    res = asyncio.run(demo_buy.run_demo(out=lambda _l: None))
    assert res["status"] == "bought"
    assert lease.live_count(demo_buy.DEMO_CLIENT) == 0


def test_release_client_only_touches_that_client():
    _fill_cap(demo_buy.DEMO_CLIENT)
    w = watch.create_watch("other", rule={"max_price_eur": 10})
    lease.create_lease(w["id"], "https://agent.example/h", client_id="alice", ttl_s=3600)
    assert lease.release_client(demo_buy.DEMO_CLIENT) == lease.MAX_LIVE_PER_CLIENT
    assert lease.live_count(demo_buy.DEMO_CLIENT) == 0 and lease.live_count("alice") == 1
    assert lease.release_client(demo_buy.DEMO_CLIENT, now=time.time()) == 0


def test_server_start_releases_leftover_demo_leases():
    from fastapi.testclient import TestClient
    from agora.api import app
    _fill_cap(demo_buy.DEMO_CLIENT)
    with TestClient(app):                    # runs the lifespan startup
        assert lease.live_count(demo_buy.DEMO_CLIENT) == 0
