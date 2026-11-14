"""Round-5: cost cards arrive with the provisional verdict (no dead air), replays can skip idle time."""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from agora import hunt as hunt_mod
from agora.hunt import replay
from test_hunt_demo import SLOW_URL, run, slow_sony


def test_truecost_cards_come_with_the_provisional_verdict():
    disc, read = slow_sony(delay=1.2)
    events = run(disc, read, provisional_after=0.8, stable_for=0.25, read_timeout=5)
    prov = next(e for e in events if e.type == "verdict" and e.data["provisional"])
    early = [e for e in events if e.type == "truecost" and e.data.get("provisional")]
    assert early and all(e.t_ms <= prov.t_ms + 50 for e in early if e.data["url"] != SLOW_URL)
    assert all(e.data["true_cost"]["per_month_eur"] is not None for e in early)
    late_card = [e for e in early if e.data["url"] == SLOW_URL]
    slow_offer = next(e for e in events if e.type == "offer" and e.data["offer"]["url"] == SLOW_URL)
    assert late_card and late_card[0].t_ms >= slow_offer.t_ms             # the late page got its card at once
    final = [e for e in events if e.type == "truecost" and not e.data.get("provisional")]
    assert final and all("unchanged" in e.data for e in final if e.data["url"] in {x.data["url"] for x in early})
    assert any(e.data.get("unchanged") for e in final)


def test_replay_skips_idle_time_and_says_so():
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    async def go(gap):
        return [e async for e in replay("sony-a7-iii-body", speed=1, sleep=fake_sleep, max_gap_ms=gap)]

    events = asyncio.run(go(1500))
    recorded = hunt_mod.load_recording("sony-a7-iii-body")
    assert [e.type for e in events] == [e.type for e in recorded]
    assert max(slept) <= 1.5 + 1e-9 and sum(slept) < 9.0                  # ~20 s recording -> under 9 s
    assert events[-1].data["idle_skipped_ms"] > 10_000
    assert events[-1].t_ms == recorded[-1].t_ms - events[-1].data["idle_skipped_ms"]
    slept.clear()
    honest = asyncio.run(go(None))
    assert "idle_skipped_ms" not in honest[-1].data and sum(slept) > 19.0


def test_api_replay_max_gap(tmp_path, monkeypatch):
    from agora import api
    lines = [{"type": "need", "data": {}, "t_ms": 0}, {"type": "offer", "data": {}, "t_ms": 50},
             {"type": "done", "data": {"ms": 5050}, "t_ms": 5050}]
    (tmp_path / "live_gap.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    monkeypatch.setattr(hunt_mod, "RECORDINGS", tmp_path)
    r = TestClient(api.app).get("/hunt", params={"q": "gap", "replay": "gap", "speed": 16, "max_gap": 0.1})
    got = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
    assert got[-1]["data"]["idle_skipped_ms"] == 4900 and got[-1]["t_ms"] == 150 // 16
