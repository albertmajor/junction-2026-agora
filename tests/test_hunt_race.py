"""Live race: rank events while offers stream in, redirect dedupe, and a per-hunt bill."""
from __future__ import annotations

import asyncio
import json

from agora import contextdev as cd
from agora.hunt import hunt
from agora.models import Event, Offer
from live_offers import FIX


def replay(name: str):
    events = [json.loads(line) for line in (FIX / f"round1_{name}.jsonl").read_text().splitlines()]
    offers = {e["data"]["offer"]["url"]: e for e in events if e["type"] == "offer"}
    fields = set(Offer.__dataclass_fields__) - {"true_cost", "haggle", "trust", "flags", "thing_id", "raw"}

    async def disc(need):
        for e in events:
            if e["type"] in ("lane", "source"):
                yield Event(e["type"], dict(e["data"]))

    async def read(url, need):
        e = offers.get(url)
        if e is None:
            return None, "no offer on page"
        await asyncio.sleep(e["t_ms"] / 1000 / 50)      # keep the original arrival order, 50x faster
        d = e["data"]["offer"]
        return Offer(**{k: v for k, v in d.items() if k in fields}), d["read_via"]

    return disc, read


def run(name: str, **kw) -> list[Event]:
    disc, read = replay(name)

    async def go():
        return [e async for e in hunt(name.replace("-", " "), discover=disc, read=read, persist=False,
                                      lookalikes=False, **kw)]
    return asyncio.run(go())


def test_sony_replay_races():
    events = run("sony-a7-iii-body")
    ranks = [e for e in events if e.type == "rank"]
    assert ranks and any(r.data["leader_changed"] for r in ranks)
    first = next(r for r in ranks if r.data["leader_changed"])
    assert first.data["reason"] and first.data["top"][0]["per_month"] > 0
    assert any("overtook" in (r.data["reason"] or "") for r in ranks)
    assert [e.t_ms for e in events] == sorted(e.t_ms for e in events)
    tc = [e for e in events if e.type == "truecost" and e.data["true_cost"]]
    assert all("evidence" in e.data and "beat_eur" in e.data for e in tc)
    assert any(e.data["gap_eur"] for e in tc)
    budget = next(e for e in events if e.type == "budget").data
    assert set(budget["free_reads"]) >= {"e-infin.com", "usedlens.co.uk"}
    assert "credit_eur" not in budget                    # no plan price configured: no made-up euros


def test_credit_eur_when_configured(monkeypatch):
    monkeypatch.setenv("AGORA_EUR_PER_CREDIT", "0.002")
    budget = next(e for e in run("sony-a7-iii-body") if e.type == "budget").data
    assert budget["credit_eur"] == 0 and "AGORA_EUR_PER_CREDIT" in budget["credit_eur_basis"]


def test_redirected_page_is_one_offer_under_its_real_domain():
    async def disc(need):
        for u in ("https://novah.fi/en/prices/helsinki", "https://hyvacleaning.fi/home-cleaning-helsinki-prices/"):
            yield Event("source", {"url": u, "lane": "service"})

    async def read(url, need):
        o = Offer(url=url, source=url.split("/")[2], title="One-time home cleaning", price=49.9, currency="EUR",
                  price_eur=49.9, condition="service", unit="hour", read_via="contextdev_json")
        if "hyvacleaning" in url:
            o.raw["final_url"] = "https://novah.fi/en/prices/helsinki"
        return o

    async def go():
        return [e async for e in hunt("home cleaning helsinki 60m2", discover=disc, read=read, persist=False)]
    events = asyncio.run(go())
    offers = [e for e in events if e.type == "offer"]
    assert len(offers) == 1
    assert any(e.type == "skip" and "same offer" in e.data["reason"] for e in events)


def test_per_hunt_ledger_does_not_mix():
    async def disc(need):
        yield Event("source", {"url": "https://x.fi/a"})

    async def read(url, need):
        cd._record("/web/scrape", 2, None)               # this hunt pays 2 credits
        await asyncio.sleep(0)
        return None

    async def one():
        return [e async for e in hunt("thing", discover=disc, read=read, persist=False)]

    async def both():
        return await asyncio.gather(one(), one())
    for evs in asyncio.run(both()):
        assert next(e for e in evs if e.type == "budget").data["credits_used"] == 2
