"""STAGE DEMO "decline, counter, buy": `python -m agora demo-buy` (or `python -m agora.demo_buy`).

Fully offline: the market is a recorded live hunt (tests/fixtures/live_sony-a7-iii-body.jsonl, real
shops and prices), the merchant is our own mock shop, the agent's callback is an in-process receiver.

  1. ARM     a watch for a NEW Sony A7 III <= €1,030 with EU warranty, written as JSON Logic, auto-buy
             inside a signed OPEN mandate (cap €1,050, mock shop only, 7 days). An agent leases signed
             callbacks for it.
  2. LIE     the shop's page says "Loppuunmyyty" while its JSON-LD still says InStock: the watcher
             believes the page and skips.
  3. HAGGLE  back in stock at €1,099: too expensive. The agent declines with an ACP-style intent trace
             (price_sensitivity, competitor €1,029 at e-infin.com). The shop counters: €1,028.
  4. BUY     the counter-offer goes through the same rule, matches, the agent signs a CLOSED mandate for
             that exact cart, links it into the hash chain and pays. The leased agent gets a signed
             watch.match callback and verifies it.
  5. PROOF   open mandate -> closed mandate -> hash chain, every check spelled out.

`run_demo(variant="used", target=825)` tells the same five beats for the hunt's own pick, the USED body a
private seller listed on tori.fi (real title and photo from the recording; our mock shop plays the seller):
ARM a watch for a used A7 III <= your price, seller verified and photos matching the listing, under an OPEN
mandate. LIE: the listing says 'Myyty' (sold) but is still up. HAGGLE: relisted at €859, declined citing
the €825 tori.fi price; the seller counters €819. BUY: CLOSED mandate, paid into escrow (released at
pickup). PROOF.
Written at Junction 2026.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable

import httpx

from agora import lease, mockshop, proof, store, watch
from agora.models import Event

FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "live_sony-a7-iii-body.jsonl"
CAMERA = "sony-a7iii"
TARGET, CAP, SHOP_PRICE = 1030.0, 1050.0, 1099.0
NO_GREY = {"!": {"in": ["grey import", {"var": "flags_text"}]}}
# used variant: the hunt's pick (tori.fi, used, €825), relisted €34 higher by a seller who answers in €6 steps
USED_PID, USED_TARGET, USED_RELIST_UP, USED_CAP_UP = mockshop.USED_TORI_PID, 825.0, 34.0, 25.0
VERIFIED = {"in": ["seller verified", {"var": "flags_text"}]}
DEMO_CLIENT = "demo-agent"   # the leasing agent of every demo run; its leases are released after each run


def replay_hunt(path: pathlib.Path = FIXTURE) -> Callable[[str], AsyncIterator[Event]]:
    """A hunt that replays a recorded live hunt (offer + truecost events), no network."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    async def hunt(text: str) -> AsyncIterator[Event]:
        for r in rows:
            if r.get("type") in ("offer", "truecost"):
                yield Event(r["type"], r["data"], r.get("t_ms", 0))
    return hunt


class AgentInbox:
    """The leasing agent's webhook endpoint, in-process: it verifies every delivery's signature."""

    def __init__(self) -> None:
        self.secret: str | None = None
        self.got: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        def handle(req: httpx.Request) -> httpx.Response:
            body = req.content.decode()
            ok = bool(self.secret) and lease.verify(self.secret, req.headers, body)
            self.got.append({"headers": dict(req.headers), "body": json.loads(body), "signature_ok": ok})
            return httpx.Response(200 if ok else 401)
        return httpx.MockTransport(handle)


def best_new_today(path: pathlib.Path = FIXTURE) -> dict | None:
    """The cheapest NEW offer in the recorded hunt, with its flags (for the ARM beat's 'why new')."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    offers = {r["data"]["offer"]["url"]: dict(r["data"]["offer"]) for r in rows if r.get("type") == "offer"}
    for r in rows:
        if r.get("type") == "truecost" and r["data"].get("url") in offers:
            offers[r["data"]["url"]]["flags"] = r["data"].get("flags") or []
    new = [o for o in offers.values() if o.get("condition") == "new" and o.get("price_eur")]
    return min(new, key=lambda o: o["price_eur"]) if new else None


def hunt_winner(path: pathlib.Path = FIXTURE) -> str | None:
    """'used €825 at tori.fi': the recorded hunt's final cheapest-to-own pick."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    final = next((r["data"]["verdict"] for r in reversed(rows) if r.get("type") == "verdict"), None)
    url = (final or {}).get("best_true_cost_url")
    o = next((r["data"]["offer"] for r in rows if r.get("type") == "offer" and r["data"]["offer"].get("url") == url), None)
    return f"{o['condition']} {_eur(o['price_eur'])} at {o['source']}" if o else None


# Lines whose kind is one of these are technical detail (JSON Logic, ids, signatures): the viewer folds them.
DETAIL_KINDS = ("logic", "mandate", "lease", "callback", "ok", "NO", "chain")


def _eur(x: float | None) -> str:
    return "?" if x is None else (f"€{x:,.0f}" if abs(x - round(x)) < 0.005 else f"€{x:,.2f}")


def recorded_offer(url: str, path: pathlib.Path = FIXTURE) -> dict | None:
    """One offer of the recorded hunt, with its judged trust and flags."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    o = next((dict(r["data"]["offer"]) for r in rows if r.get("type") == "offer" and r["data"]["offer"].get("url") == url), None)
    tc = next((r["data"] for r in rows if r.get("type") == "truecost" and r["data"].get("url") == url), {})
    if o is not None:
        o["trust"], o["flags"] = tc.get("trust", o.get("trust")), tc.get("flags") or o.get("flags") or []
    return o


def _release_demo_leases() -> None:
    """The story is over (or failed): the demo agent's lease is done, so it never counts toward the cap."""
    try:
        lease.release_client(DEMO_CLIENT)
    except Exception:   # never let cleanup hide the story's own result or error
        pass


async def run_demo(out: Callable[[str], None] = print, pause: float = 0.0, verbose: bool = False,
                   variant: str = "new", target: float | None = None) -> dict:
    """Run the whole story. Returns a summary (used by tests). Every step is also in the decision chain.
    variant "new" (default): the recorded new-body story at €1,030. "used": the hunt's used pick on tori.fi,
    bought at or under `target` (default €825)."""
    if variant == "used":
        return await run_used(out=out, pause=pause, verbose=verbose, target=USED_TARGET if target is None else target)
    if variant != "new":
        raise ValueError(f"unknown variant {variant!r} (new | used)")
    nap = (lambda: asyncio.sleep(pause)) if pause else (lambda: asyncio.sleep(0))
    mockshop.reset()
    hunt = replay_hunt()
    cam_url = mockshop.product_url(CAMERA)
    mockshop.set_price(CAMERA, SHOP_PRICE)
    inbox = AgentInbox()
    lease.set_transport(inbox.transport())

    def show_events(evs: list[Event]) -> None:
        """Our shop's lines first (the beat is about it), each other shop's grey-import skip under its own
        label, everything else folded into one count."""
        ours, grey, quiet = [], [], 0
        for e in evs:
            line = e.data.get("line")
            if not line:
                continue
            if e.type == "decision" and "grey import" in line and not mockshop.product_id_from_url(e.data.get("url")):
                host = (e.data.get("url") or "").split("/")[2:3]
                grey.append(f"{host[0].removeprefix('www.')}: {line}" if host else line)
            elif e.type == "decision" and not verbose and not e.data.get("match") \
                    and not mockshop.product_id_from_url(e.data.get("url")):
                quiet += 1
            else:
                ours.append((e.type, line))
        for kind, line in ours:
            out(f"   {kind:<8} {line}")
        for line in grey:
            out(f"   grey     {line}")
        if quiet:
            out(f"   ...      {quiet} other shops skipped (used/refurb, over target, low trust or unchanged)")

    try:
        out("1  ARM")
        w = watch.create_watch(
            "new sony a7 iii body", rule={"max_price_eur": TARGET, "min_trust": 0.7, "conditions": ["new"],
                                          "logic": NO_GREY, "min_move_pct": 1.0, "haggle": True},
            action="auto_buy", mandate={"cap_eur": CAP, "merchants": [mockshop.DOMAIN],
                                        "expires_at": time.time() + 7 * 86400},
            pinned_urls=[cam_url], use_hunt=True)
        m = w["mandate"]
        bn = best_new_today()
        win = hunt_winner()
        out("   why      " + (f"the hunt says {win} is cheapest to own; " if win else "")
            + "this buyer wants a NEW body with an EU warranty, so the watch only takes new offers from EU shops")
        if bn:
            grey = any("grey" in f for f in bn.get("flags") or [])
            out(f"   today    best new is {bn['source']} {_eur(bn['price_eur'])}"
                + (" (a possible grey import: no EU warranty), so the watch waits for an EU shop" if grey else ""))
        out(f"   shop     our mock shop lists it at {_eur(SHOP_PRICE)} (target {_eur(TARGET)}, cap {_eur(CAP)})")
        out(f"   rule     {watch.describe_rule(w)}")
        out(f"   logic    {json.dumps(watch.rule_logic(w['rule']))}")
        out(f"   mandate  OPEN {m['id']}: cap {_eur(m['cap_eur'])}, merchants {m['merchants']}, "
            f"products {m['constraints']['product_ids']}, signed {m['signature'][:12]}...")
        lease.release_client(DEMO_CLIENT)          # leftovers of a crashed run must not count
        lz = lease.create_lease(w["id"], "https://agent.example/hooks/agora", ["watch.match", "price.drop"],
                                client_id=DEMO_CLIENT, ttl_s=3600)
        inbox.secret = lz["secret"]
        out(f"   lease    agent 'demo-agent' leased {lz['events']} for 1 h ({lz['id']}, signed callbacks)")
        await nap()

        out("2  LIE DETECTOR: the page says 'Loppuunmyyty' (sold out), its data still says InStock")
        mockshop.set_page_banner(CAMERA, "Loppuunmyyty")
        show_events(await watch.check_watch(w["id"], hunt=hunt))
        mockshop.set_page_banner(CAMERA, None)
        await nap()

        out(f"3  HAGGLE: back in stock at {_eur(SHOP_PRICE)}")
        evs = await watch.check_watch(w["id"], hunt=hunt)
        show_events(evs)
        await nap()

        act = next((e.data["result"] for e in evs if e.type == "action"), {})
        rec = act.get("receipt") or {}
        out("4  BUY")
        if act.get("status") == "bought":
            out(f"   order    {rec['order_id']}: paid {_eur(rec['paid_eur'])} under closed mandate "
                f"{rec['closed_mandate_id']} (counter-offer {rec.get('counter_offer')})")
        else:
            out(f"   no buy   {act.get('status')}: {act.get('reason')}")
        for d in inbox.got:
            b = d["body"]
            out(f"   callback {b['type']} -> agent, signature {'valid' if d['signature_ok'] else 'INVALID'} "
                f"(webhook-id {d['headers'].get('webhook-id')})")
        await nap()

        out("5  PROOF")
        p = proof.watch_proof(w["id"]) or {}
        mc = p.get("mandate_chain") or {}
        out(f"   chain    {len(p.get('chain') or [])} decisions, hash chain {'intact' if p.get('chain_ok') else 'BROKEN'}, "
            f"head {str(p.get('head'))[:12]}...")
        for link in mc.get("closed") or []:
            for c in link["checks"]:
                out(f"   {'ok ' if c['ok'] else 'NO '}      {c['check']}: {c['detail']}")
        out(f"   verdict  open -> closed mandate chain {'verified' if mc.get('ok') else 'NOT verified'}")
        mockshop.reset()          # the shop panel and the next story start from the opening state
        return {"watch_id": w["id"], "status": act.get("status"), "paid_eur": rec.get("paid_eur"),
                "counter_offer": rec.get("counter_offer"), "chain_ok": p.get("chain_ok"),
                "mandate_chain_ok": mc.get("ok"), "callbacks": inbox.got,
                "decisions": store.decisions(w["id"], limit=10_000)}
    finally:
        lease.set_transport(None)
        _release_demo_leases()


async def run_used(out: Callable[[str], None] = print, pause: float = 0.0, verbose: bool = False,
                   target: float = USED_TARGET) -> dict:
    """The used-listing night: the hunt's own pick, a private seller on tori.fi, bought through escrow."""
    nap = (lambda: asyncio.sleep(pause)) if pause else (lambda: asyncio.sleep(0))
    target = round(float(target), 2)
    seen = recorded_offer(mockshop.TORI_LISTING) or {}
    # the seller relists €34 over what the hunt saw (€825 -> €859), whatever your price is
    relist, cap = round((seen.get("price_eur") or USED_TARGET) + USED_RELIST_UP), round(target + USED_CAP_UP)
    mockshop.reset()
    hunt = replay_hunt()
    url = mockshop.product_url(USED_PID)
    prod = mockshop.set_price(USED_PID, relist)
    inbox = AgentInbox()
    lease.set_transport(inbox.transport())

    def show_events(evs: list[Event]) -> None:
        """The listing's own lines; every other listing of the recorded hunt folded into one count."""
        ours, quiet = [], 0
        for e in evs:
            line = e.data.get("line")
            if not line:
                continue
            if e.type == "decision" and not verbose and not e.data.get("match") \
                    and not mockshop.product_id_from_url(e.data.get("url")):
                quiet += 1
            else:
                ours.append((e.type, line))
        for kind, line in ours:
            out(f"   {kind:<8} {line}")
        if quiet:
            out(f"   ...      {quiet} other listings skipped (new/refurb, over your price, low trust, "
                "unverified seller or unchanged)")

    try:
        out("1  ARM")
        w = watch.create_watch(
            "used sony a7 iii body", rule={"max_price_eur": target, "min_trust": 0.85, "conditions": ["used"],
                                           "logic": VERIFIED, "min_move_pct": 1.0, "haggle": True},
            action="auto_buy", mandate={"cap_eur": cap, "merchants": [mockshop.DOMAIN],
                                        "expires_at": time.time() + 7 * 86400},
            pinned_urls=[url], use_hunt=True)
        m = w["mandate"]
        win = hunt_winner()
        out("   why      " + (f"the hunt says {win} is cheapest to own; " if win else "")
            + "the watch buys it only from a verified seller whose photos match the listing")
        out(f"   listing  tori.fi '{seen.get('title') or prod.title}', used, private seller "
            f"(recorded live: real title and photo; our mock shop plays the seller)")
        out(f"   shop     the seller has it at {_eur(relist)} (your price {_eur(target)}, cap {_eur(cap)})")
        out(f"   rule     {watch.describe_rule(w)}")
        out(f"   logic    {json.dumps(watch.rule_logic(w['rule']))}")
        out(f"   mandate  OPEN {m['id']}: cap {_eur(m['cap_eur'])}, merchants {m['merchants']}, "
            f"products {m['constraints']['product_ids']}, signed {m['signature'][:12]}...")
        lease.release_client(DEMO_CLIENT)          # leftovers of a crashed run must not count
        lz = lease.create_lease(w["id"], "https://agent.example/hooks/agora", ["watch.match", "price.drop"],
                                client_id=DEMO_CLIENT, ttl_s=3600)
        inbox.secret = lz["secret"]
        out(f"   lease    agent 'demo-agent' leased {lz['events']} for 1 h ({lz['id']}, signed callbacks)")
        await nap()

        # 'Myyty' is what tori.fi shows on a sold listing. Older lie detectors only know 'loppuunmyyty'.
        banner = "Myyty" if watch.sold_out_phrase("Myyty") else "Myyty (loppuunmyyty)"
        out("2  LIE DETECTOR: the listing says 'Myyty' (sold), yet it is still listed and its data says InStock")
        mockshop.set_page_banner(USED_PID, banner)
        show_events(await watch.check_watch(w["id"], hunt=hunt))
        mockshop.set_page_banner(USED_PID, None)
        await nap()

        out(f"3  HAGGLE: relisted at {_eur(relist)}")
        evs = await watch.check_watch(w["id"], hunt=hunt)
        show_events(evs)
        await nap()

        act = next((e.data["result"] for e in evs if e.type == "action"), {})
        rec = act.get("receipt") or {}
        order = next((o for o in mockshop.ORDERS if o["id"] == rec.get("order_id")), {})
        escrow = order.get("escrow")
        out("4  BUY")
        if act.get("status") == "bought":
            out(f"   order    {rec['order_id']}: paid {_eur(rec['paid_eur'])} under closed mandate "
                f"{rec['closed_mandate_id']} (counter-offer {rec.get('counter_offer')})")
            out(f"   escrow   a private seller is never paid directly: {_eur(rec['paid_eur'])} waits in escrow, "
                "released at pickup when the body and serial match the photos")
        else:
            out(f"   no buy   {act.get('status')}: {act.get('reason')}")
        for d in inbox.got:
            b = d["body"]
            out(f"   callback {b['type']} -> agent, signature {'valid' if d['signature_ok'] else 'INVALID'} "
                f"(webhook-id {d['headers'].get('webhook-id')})")
        await nap()

        out("5  PROOF")
        p = proof.watch_proof(w["id"]) or {}
        mc = p.get("mandate_chain") or {}
        out(f"   chain    {len(p.get('chain') or [])} decisions, hash chain {'intact' if p.get('chain_ok') else 'BROKEN'}, "
            f"head {str(p.get('head'))[:12]}...")
        for link in mc.get("closed") or []:
            for c in link["checks"]:
                out(f"   {'ok ' if c['ok'] else 'NO '}      {c['check']}: {c['detail']}")
        out(f"   verdict  open -> closed mandate chain {'verified' if mc.get('ok') else 'NOT verified'}")
        mockshop.reset()
        return {"watch_id": w["id"], "status": act.get("status"), "paid_eur": rec.get("paid_eur"),
                "counter_offer": rec.get("counter_offer"), "chain_ok": p.get("chain_ok"),
                "mandate_chain_ok": mc.get("ok"), "callbacks": inbox.got,
                "decisions": store.decisions(w["id"], limit=10_000), "variant": "used",
                "target_eur": target, "relist_eur": relist, "escrow": escrow,
                "seller": prod.seller, "listing_url": mockshop.TORI_LISTING, "condition": "used"}
    finally:
        lease.set_transport(None)
        _release_demo_leases()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agora demo-buy",
                                 description="Offline stage demo: the agent declines, the shop counters, the agent buys.")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between beats (stage pacing)")
    ap.add_argument("--verbose", action="store_true", help="print every decision line")
    ap.add_argument("--tmp-db", action="store_true", help="use a throwaway database instead of agora.db")
    ap.add_argument("--variant", choices=("new", "used"), default="new",
                    help="new: the recorded new body at €1,030; used: the hunt's tori.fi pick, through escrow")
    ap.add_argument("--target", type=float, default=None, help="your price (used variant, default €825)")
    args = ap.parse_args(argv)
    if args.tmp_db:
        os.environ["AGORA_DB"] = str(pathlib.Path(tempfile.mkdtemp(prefix="agora-demo-")) / "demo.db")
    kw = {"variant": args.variant, "target": args.target} if args.variant != "new" else {}
    res = asyncio.run(run_demo(pause=args.pause, verbose=args.verbose, **kw))
    print(f"\nwatch {res['watch_id']}: GET /watches/{res['watch_id']}/proof")
    return 0 if res["status"] == "bought" and res["chain_ok"] and res["mandate_chain_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
