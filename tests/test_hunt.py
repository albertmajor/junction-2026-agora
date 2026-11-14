import asyncio

from agora import hunt as hunt_mod
from agora.hunt import HuntResult, hunt, run_hunt
from agora.models import Event, Need

try:
    from tests import surface_fakes as fk
except ImportError:
    import surface_fakes as fk


def collect(**kw) -> list[Event]:
    async def go():
        return [e async for e in hunt("used sony a7 iii under 900", **fk.kwargs(**kw))]
    return asyncio.run(go())


def test_full_stream_order_and_shape():
    events = collect()
    types = [e.type for e in events]
    assert types[0] == "need"
    assert types[-2:] == ["budget", "done"]
    assert types.index("verdict") > max(i for i, t in enumerate(types) if t == "offer")
    assert types.count("offer") == 4
    assert types.count("source") == 6          # duplicate URL dropped
    assert sum(1 for e in events if e.type == "lane" and e.data["lane"] != "sibling") == 2
    assert types.count("thing") == 1
    assert types.count("truecost") == 4
    assert all(isinstance(e.t_ms, int) and e.t_ms >= 0 for e in events)
    assert [e.t_ms for e in events] == sorted(e.t_ms for e in events)


def test_failing_and_empty_pages_do_not_kill_hunt():
    events = collect()
    errs = [e for e in events if e.type == "error"]
    skips = [e for e in events if e.type == "skip"]
    assert any(e.data.get("url") == fk.BROKEN and "exploded" in e.data["message"] for e in errs)
    assert any(e.data.get("url") == fk.EMPTY for e in skips)
    assert events[-1].type == "done"


def test_offer_payload_is_light_and_has_eur():
    events = collect()
    o = next(e for e in events if e.type == "offer").data["offer"]
    assert "raw" not in o
    assert o["price_eur"] is not None


def test_timeout_becomes_skip():
    async def disc(need):
        yield Event("source", {"url": fk.SLOW})
    events = collect(discover=disc, read_timeout=0.05)
    assert any(e.type == "skip" and "timeout" in e.data["reason"] for e in events)


def test_offers_stream_before_discover_finishes():
    """An offer must be emitted while discover is still producing sources."""
    async def slow_discover(need):
        yield Event("source", {"url": "https://refurb.example/a7iii"})
        await asyncio.sleep(0.2)
        yield Event("source", {"url": "https://market.example/a7iii-1"})
    events = collect(discover=slow_discover)
    types = [e.type for e in events]
    assert types.index("offer") < [i for i, t in enumerate(types) if t == "source"][1]


def test_bounded_concurrency():
    live, peak = 0, 0

    async def read(url, need):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return None

    async def disc(need):
        for i in range(12):
            yield Event("source", {"url": f"https://x{i}.example/p"})
    collect(discover=disc, read=read, concurrency=3)
    assert peak <= 3


def test_max_sources_caps_reads():
    async def disc(need):
        for i in range(50):
            yield Event("source", {"url": f"https://x{i}.example/p"})
    events = collect(discover=disc, max_sources=5)
    assert sum(e.type == "source" for e in events) == 5


def test_stage_crashes_degrade_gracefully():
    def bad_resolve(need, offers):
        raise RuntimeError("resolve down")

    def bad_judge(need, things):
        raise RuntimeError("judge down")

    async def bad_discover(need):
        yield Event("source", {"url": "https://refurb.example/a7iii"})
        raise RuntimeError("search quota")

    events = collect(resolve=bad_resolve, judge=bad_judge, discover=bad_discover)
    wheres = {e.data["where"] for e in events if e.type == "error"}
    assert {"resolve", "judge", "discover"} <= wheres
    verdict = next(e for e in events if e.type == "verdict").data["verdict"]
    assert "949" in verdict["headline"]
    assert events[-1].type == "done"


def test_run_hunt_collects_result_and_budget():
    res: HuntResult = asyncio.run(run_hunt("x", **fk.kwargs()))
    assert isinstance(res.need, Need)
    assert len(res.offers) == 4 and res.verdict is not None
    assert res.budget["saved_by_free_reads"] == 2
    assert res.budget["offers"] == 4


def test_fx_conversion_for_non_eur(monkeypatch):
    class FakeFx:
        @staticmethod
        def to_eur(amount, cur):
            return amount * 0.5

    monkeypatch.setattr(hunt_mod, "_module", lambda name: FakeFx if name == "fx" else None)

    async def read(url, need):
        from agora.models import Offer
        return Offer(url=url, source="b.example", title="t", price=100.0, currency="USD")

    async def disc(need):
        yield Event("source", {"url": "https://b.example/p"})
    events = collect(discover=disc, read=read)
    assert next(e for e in events if e.type == "offer").data["offer"]["price_eur"] == 50.0


def test_consumer_break_cancels_reads():
    async def go():
        gen = hunt("q", **fk.kwargs())
        async for e in gen:
            if e.type == "source":
                break
        await gen.aclose()
    asyncio.run(go())  # must not hang or warn about pending tasks


def test_reader_reason_tuple_becomes_skip_reason():
    async def read(url, need):
        return None, "blocked; not a product page"

    async def disc(need):
        yield Event("source", {"url": "https://a.example/p"})
    events = collect(discover=disc, read=read)
    assert any(e.type == "skip" and e.data["reason"] == "blocked; not a product page" for e in events)
