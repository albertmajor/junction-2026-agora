"""STORY: scripted watcher demos, streamed like a hunt, so the stage shows an agent that acts AND refuses.

`refusal` (the climax of "watchers that act"):
  1. the price is above your price to beat -> logged, no action;
  2. it drops under -> the agent buys by itself, inside the signed mandate;
  3. a second watch: the shop slips a "handling fee" into the checkout -> the agent's signed cart does
     not match, it refuses and pays nothing (even though the total is under the cap);
  4. someone rewrites one old decision in agora.db -> the hash chain shows exactly where.
Every decision row is streamed as a `watch` event with its hash and prev_hash, so the UI can draw the
chain growing. Events: story {step, title, text} · watch {...} · proof {...} · done {ms}.
Drives our own mock shop only (agora.mockshop). Written at Junction 2026.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agora import mockshop, proof, store, watch
from agora.models import Event

CAMERA, LENS = "sony-a7iii", "sony-fe-85"


def _eur(x: float) -> str:
    return f"€{x:,.0f}" if abs(x - round(x)) < 0.005 else f"€{x:,.2f}"


class _Script:
    """Keeps the clock and remembers how many chain rows of each watch were already streamed."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.shown: dict[str, int] = {}

    def ev(self, type_: str, **data: Any) -> Event:
        return Event(type_, data, int((time.monotonic() - self.t0) * 1000))

    def new_rows(self, step: int, watch_id: str) -> list[Event]:
        rows = store.decisions(watch_id, limit=10_000)
        start = self.shown.get(watch_id, 0)
        self.shown[watch_id] = len(rows)
        return [self.ev("watch", step=step, watch_id=watch_id, index=i, decision=r["outcome"], reason=r["reason"],
                        price_eur=r["price_eur"], url=r["url"], hash=r["hash"], prev_hash=r["prev_hash"])
                for i, r in enumerate(rows) if i >= start]

    def proof(self, step: int, watch_id: str) -> Event:
        p = proof.watch_proof(watch_id) or {}
        return self.ev("proof", step=step, watch_id=watch_id, chain_ok=p.get("chain_ok"),
                       first_broken_index=p.get("first_broken_index"), signature_ok=p.get("signature_ok"),
                       head=p.get("head"), rows=len(p.get("chain") or []), purchases=len(p.get("purchases") or []))


def tamper(watch_id: str, index: int, reason: str) -> None:
    """Rewrite one stored decision behind the agent's back (what a sloppy or dishonest operator might do)."""
    rows = store.decisions(watch_id, limit=10_000)
    with store.connect() as con:
        con.execute("UPDATE decisions SET reason=? WHERE id=?", (reason, rows[index]["id"]))


async def refusal(pause: float = 1.5, beat_eur: float = 771.0,
                  sleep: Callable[[float], Awaitable[Any]] | None = None) -> AsyncIterator[Event]:
    nap = sleep or asyncio.sleep
    s = _Script()
    mockshop.reset()
    cap = round(beat_eur + 9)
    cam_url, lens_url = mockshop.product_url(CAMERA), mockshop.product_url(LENS)

    yield s.ev("story", step=0, title="Arm the watcher",
               text=f"Used A7 III bodies cost less to own than new. A new body wins at {_eur(beat_eur)} or less: "
                    f"auto-buy there, signed mandate capped at {_eur(cap)}, our mock shop only.")
    w1 = watch.create_watch("sony a7 iii body", rule={"max_price_eur": beat_eur}, action="auto_buy",
                            mandate={"cap_eur": cap, "merchants": [mockshop.DOMAIN],
                                     "expires_at": time.time() + 7 * 86400},
                            pinned_urls=[cam_url], use_hunt=False)
    for e in s.new_rows(0, w1["id"]):
        yield e
    await nap(pause)

    mockshop.set_price(CAMERA, 980)
    yield s.ev("story", step=1, title="Price is €980",
               text=f"Above your price to beat {_eur(beat_eur)}: the agent looks, logs why, does nothing.")
    await watch.check_watch(w1["id"], only_pinned=True)
    for e in s.new_rows(1, w1["id"]):
        yield e
    await nap(pause)

    mockshop.set_price(CAMERA, 760)
    yield s.ev("story", step=2, title="Price drops to €760",
               text=f"Under {_eur(beat_eur)}: new now beats the used true cost. The agent signs a cart for "
                    f"exactly {_eur(760)} and buys inside the mandate.")
    evs = await watch.check_watch(w1["id"], only_pinned=True)
    for e in s.new_rows(2, w1["id"]):
        yield e
    act = next((e.data["result"] for e in evs if e.type == "action"), {})
    if act.get("receipt"):
        yield s.ev("story", step=2, title="Bought", text=act["receipt"]["savings_line"],
                   order_id=act["receipt"]["order_id"])
    await nap(pause)

    w2 = watch.create_watch("sony fe 85mm f1.8", rule={"max_price_eur": 520}, action="auto_buy",
                            mandate={"cap_eur": 540, "merchants": [mockshop.DOMAIN],
                                     "expires_at": time.time() + 7 * 86400},
                            pinned_urls=[lens_url], use_hunt=False)
    for e in s.new_rows(3, w2["id"]):
        yield e
    mockshop.set_hidden_fee(LENS, 39, "handling fee")
    mockshop.set_price(LENS, 489)
    yield s.ev("story", step=3, title="Bait and switch",
               text="The 85mm lens drops to €489 on its page, but the shop adds a €39 'handling fee' "
                    "only at checkout.")
    evs = await watch.check_watch(w2["id"], only_pinned=True)
    for e in s.new_rows(3, w2["id"]):
        yield e
    act = next((e.data["result"] for e in evs if e.type == "action"), {})
    yield s.ev("story", step=3, title="Refused" if act.get("status") == "refused" else "Unexpected",
               text=act.get("reason") or "no checkout happened", status=act.get("status"))
    await nap(pause)

    yield s.proof(4, w1["id"])
    skip_i = next(i for i, r in enumerate(store.decisions(w1["id"], limit=10_000)) if r["outcome"] == "skip")
    tamper(w1["id"], skip_i, f"match: {_eur(980)} <= {_eur(beat_eur)}")
    yield s.ev("story", step=4, title="Someone edits the log",
               text=f"Decision #{skip_i} is rewritten in agora.db to say €980 was a match. The chain notices.")
    yield s.proof(4, w1["id"])
    yield s.ev("done", ms=int((time.monotonic() - s.t0) * 1000), watches=[w1["id"], w2["id"]])


STORIES: dict[str, Callable[..., AsyncIterator[Event]]] = {"refusal": refusal, "bait-and-switch": refusal}


def run_story(name: str, **kwargs: Any) -> AsyncIterator[Event]:
    if name not in STORIES:
        raise KeyError(name)
    return STORIES[name](**kwargs)
