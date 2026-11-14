"""Round 2 demo-proofing: provisional verdict, late witnesses, page-work timeouts, slow domains, replay."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agora import contextdev as cd
from agora import hunt as hunt_mod
from agora.hunt import SlowDomains, hunt, replay
from agora.models import Event, Offer
from test_hunt_race import replay as fixture_reader

SLOW_URL = "https://www.adorama.com/used-sony-a7-iii"


def slow_sony(delay: float):
    """The recorded sony hunt (50x faster), plus one page that only answers after `delay` seconds."""
    disc, read = fixture_reader("sony-a7-iii-body")

    async def disc2(need):
        async for e in disc(need):
            yield e
        yield Event("source", {"url": SLOW_URL, "domain": "adorama.com", "lane": "used"})

    async def read2(url, need):
        if url != SLOW_URL:
            return await read(url, need)
        await asyncio.sleep(delay)
        return Offer(url=url, source="adorama.com", title="Used Sony A7 III body", price=1099.0, currency="EUR",
                     price_eur=1099.0, condition="used", seller="Adorama", read_via="jsonld"), "jsonld"

    return disc2, read2


def run(disc, read, **kw) -> list[Event]:
    async def go():
        return [e async for e in hunt("sony a7 iii body", discover=disc, read=read, persist=False,
                                      lookalikes=False, slow_domains=SlowDomains(), **kw)]
    return asyncio.run(go())


def test_provisional_verdict_before_the_slow_page_then_late_witness():
    disc, read = slow_sony(delay=1.2)
    events = run(disc, read, provisional_after=0.8, stable_for=0.25, read_timeout=5)
    verdicts = [e for e in events if e.type == "verdict"]
    assert len(verdicts) == 2
    prov, final = verdicts
    assert prov.data["provisional"] is True and prov.data["pending_reads"] >= 1
    assert prov.t_ms < 1000                                  # well before the slow page lands
    slow_offer = next(e for e in events if e.type == "offer" and e.data["offer"]["url"] == SLOW_URL)
    assert prov.t_ms < slow_offer.t_ms
    late = next(e for e in events if e.type == "late")
    assert late.data["url"] == SLOW_URL and late.data["changed_verdict"] is False
    assert "adorama.com arrived late" in late.data["note"] and "unchanged" in late.data["note"]
    assert final.data["provisional"] is False and final.data["changed_from"] is None
    assert prov.data["verdict"]["best_true_cost_url"] == final.data["verdict"]["best_true_cost_url"]


def test_late_page_that_wins_moves_the_verdict():
    disc, read = slow_sony(delay=0.9)

    async def read_cheap(url, need):
        got = await read(url, need)
        if url == SLOW_URL:             # a cheap EU used body: it should take over
            got[0].price = got[0].price_eur = 720.0
        return got

    events = run(disc, read_cheap, provisional_after=0.6, stable_for=0.2, read_timeout=5)
    late = next(e for e in events if e.type == "late")
    final = [e for e in events if e.type == "verdict"][-1]
    assert late.data["changed_verdict"] is True and "verdict changed" in late.data["note"]
    assert late.data["delta"]["best_offer_url"][1] == SLOW_URL
    assert final.data["changed_from"] and final.data["changed_from"]["headline"]


def test_fast_hunt_has_no_provisional_verdict():
    disc, read = fixture_reader("sony-a7-iii-body")
    events = run(disc, read, provisional_after=30, stable_for=30)
    verdicts = [e for e in events if e.type == "verdict"]
    assert len(verdicts) == 1 and verdicts[0].data["provisional"] is False
    assert "changed_from" not in verdicts[0].data


def test_timeout_counts_page_work_not_rate_limit_queue():
    async def disc(need):
        yield Event("source", {"url": "https://queued.example/p", "lane": "new"})
        yield Event("source", {"url": "https://hangs.example/p", "lane": "new"})

    async def read(url, need):
        if "queued" in url:              # 0.5 s waiting for a Context.dev token, then a quick answer
            with cd.queueing():
                await asyncio.sleep(0.5)
            return Offer(url=url, source="queued.example", title="Sony A7 III", price=999.0, currency="EUR",
                         price_eur=999.0, condition="new"), "contextdev_product"
        await asyncio.sleep(5)
        return None, "never"

    events = run(disc, read, read_timeout=0.3, provisional_after=None)
    assert any(e.type == "offer" and "queued" in e.data["offer"]["url"] for e in events)
    skip = next(e for e in events if e.type == "skip" and "hangs" in e.data["url"])
    assert skip.data["reason"].startswith("timeout after 0s") and skip.data["timeout"] is True


def test_slow_domains_learn_and_forgive(tmp_path):
    s = SlowDomains(tmp_path / "slow.json")
    assert s.timeout_for("adorama.com", 12) == 12
    s.record("adorama.com", True)
    s.record("adorama.com", True)
    assert s.is_slow("adorama.com") and s.timeout_for("adorama.com", 12) == hunt_mod.SLOW_READ_TIMEOUT
    s.save()
    again = SlowDomains(tmp_path / "slow.json")
    assert again.is_slow("adorama.com")
    again.record("adorama.com", False)
    assert not again.is_slow("adorama.com")


def test_replay_keeps_order_and_pacing():
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    async def go():
        return [e async for e in replay("sony-a7-iii-body", speed=4, sleep=fake_sleep)]

    events = asyncio.run(go())
    recorded = hunt_mod.load_recording("sony-a7-iii-body")
    assert [e.type for e in events] == [e.type for e in recorded]
    last = max(e.t_ms for e in recorded)
    assert sum(slept) == pytest.approx(last / 1000 / 4, abs=0.05)
    assert events[-1].t_ms == pytest.approx(recorded[-1].t_ms / 4, abs=1)


def test_replay_real_clock_within_tolerance(tmp_path, monkeypatch):
    lines = [{"type": "need", "data": {}, "t_ms": 0}, {"type": "offer", "data": {}, "t_ms": 200},
             {"type": "done", "data": {"ms": 400}, "t_ms": 400}]
    (tmp_path / "live_tiny.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    monkeypatch.setattr(hunt_mod, "RECORDINGS", tmp_path)

    async def go():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        stamps = [(e.type, loop.time() - t0) async for e in replay("tiny", speed=2)]
        return stamps

    stamps = asyncio.run(go())
    assert [t for t, _ in stamps] == ["need", "offer", "done"]
    assert stamps[1][1] == pytest.approx(0.1, abs=0.06) and stamps[2][1] == pytest.approx(0.2, abs=0.08)


def test_replay_rejects_paths_and_unknown_slugs():
    assert hunt_mod.recording_path("../../etc/passwd") is None
    assert hunt_mod.recording_path("nope-not-recorded") is None
    assert "sony-a7-iii-body" in hunt_mod.recordings()


def test_api_replay_endpoint(tmp_path, monkeypatch):
    from agora import api
    lines = [{"type": "need", "data": {"need": {"thing": "x"}}, "t_ms": 0},
             {"type": "verdict", "data": {"verdict": {"headline": "h"}, "provisional": True}, "t_ms": 20},
             {"type": "done", "data": {"ms": 30}, "t_ms": 30}]
    (tmp_path / "live_demo-thing.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    monkeypatch.setattr(hunt_mod, "RECORDINGS", tmp_path)
    c = TestClient(api.app)
    r = c.get("/hunt", params={"q": "demo thing", "replay": "auto", "speed": 4})
    got = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
    assert [g["type"] for g in got] == ["need", "verdict", "done"]
    assert c.get("/hunt", params={"q": "zz", "replay": "missing"}).status_code == 404
    assert c.get("/recordings").json() == {"recordings": ["demo-thing"]}


def test_late_compares_with_the_latest_verdict_not_the_first():
    disc, read = fixture_reader("sony-a7-iii-body")
    second = "https://www.fotokoch.de/used-sony-a7-iii"

    async def disc2(need):
        async for e in disc(need):
            yield e
        yield Event("source", {"url": SLOW_URL, "domain": "adorama.com", "lane": "used"})
        yield Event("source", {"url": second, "domain": "fotokoch.de", "lane": "used"})

    async def read2(url, need):
        if url == SLOW_URL:        # cheap EU used body: takes over
            await asyncio.sleep(0.8)
            return Offer(url=url, source="adorama.com", title="Used Sony A7 III body", price=720.0, currency="EUR",
                         price_eur=720.0, condition="used", seller="A", read_via="jsonld"), "jsonld"
        if url == second:          # dearer: changes nothing after the first one
            await asyncio.sleep(1.1)
            return Offer(url=url, source="fotokoch.de", title="Sony A7 III gebraucht", price=990.0, currency="EUR",
                         price_eur=990.0, condition="used", seller="F", read_via="jsonld"), "jsonld"
        return await read(url, need)

    events = run(disc2, read2, provisional_after=0.5, stable_for=0.2, read_timeout=5)
    lates = [e.data for e in events if e.type == "late"]
    assert [x["source"] for x in lates] == ["adorama.com", "fotokoch.de"]
    assert lates[0]["changed_verdict"] is True and lates[1]["changed_verdict"] is False
