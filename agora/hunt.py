"""HUNT: one live event stream for a whole search.

parse_need -> discover (lanes, sources) -> concurrent reads (offers stream in as they land)
-> resolve (things) -> judge (true cost + verdict) -> budget -> done.

Every stage is injectable so tests (and the MCP server) can run fully offline.
Sibling modules are imported lazily: if one is missing or crashes, the hunt degrades
instead of dying, and says so with an `error` event.
"""
from __future__ import annotations

import asyncio
import contextvars
import copy
import importlib
import inspect
import json
import os
import pathlib
import re
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from agora.models import Event, Need, Offer, Thing, Verdict, to_dict
from agora.origin import origin_for, origin_from_payload

ParseNeed = Callable[[str], Need]
Discover = Callable[[Need], AsyncIterator[Event]]
# a reader returns an Offer, None, or (Offer | None, reason) like reader.read_with_reason
Read = Callable[[str, Need], Awaitable[Offer | None | tuple[Offer | None, str]]]
Resolve = Callable[[Need, list[Offer]], list[Thing]]
Judge = Callable[[Need, list[Thing]], Verdict]

DEFAULT_CONCURRENCY = 10     # free page fetches at once (paid reads have their own lane-fair gate below)
PAID_SLOTS = 3               # paid Context.dev reads in flight at once, handed out lane by lane
SIBLING_MIN_TOKENS = 9.0     # the depreciation lane's 2 searches only when the 10/min bucket has room to spare
DEFAULT_MAX_SOURCES = 32      # free reads are cheap; the paid ones are ordered by expected yield (LaneGate)
DEFAULT_READ_TIMEOUT = 12.0  # seconds of page work (time queued for the shared rate limit does not count)
MAX_QUEUE_ALLOWANCE = 120.0  # never wait more than this for the rate limiter on one page
DEFAULT_BUDGET_S = 20.0      # a live hunt stops waiting for pages after this (AGORA_HUNT_BUDGET_S; 0 = no cap)
PROVISIONAL_AFTER = 8.0      # send a provisional verdict by this many seconds...
SIBLING_DEADLINE = 20.0      # the depreciation lane must be done this many seconds into the hunt
STABLE_FOR = 3.0             # ...or as soon as the leaderboard has not moved for this long
ROOT = pathlib.Path(__file__).resolve().parent.parent
EU_CURRENCIES = {"EUR", "SEK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN"}


def _module(name: str) -> Any | None:
    """Import agora.<name> if it exists, else None (other agents may not have shipped it yet)."""
    try:
        return importlib.import_module(f"agora.{name}")
    except ImportError:
        return None


def offer_payload(offer: Offer) -> dict[str, Any]:
    """Offer as JSON for the stream, without the heavy `raw` blob."""
    d = to_dict(offer)
    d.pop("raw", None)
    d["origin"] = _origin(offer)
    return d


def _origin(offer: Offer | dict[str, Any], flags: list[str] | None = None) -> dict[str, Any] | None:
    """origin.origin_for, never fatal: a flag is a nicety, the hunt must go on."""
    try:
        return origin_for(offer, flags)
    except Exception:
        return None


# ---------- fallbacks (used only when a sibling module is missing) ----------

def _fallback_parse_need(text: str) -> Need:
    return Need(raw=text, thing=text.strip().lower())


async def _no_discover(need: Need) -> AsyncIterator[Event]:
    raise RuntimeError("agora.discover is not available")
    yield  # pragma: no cover  (makes this an async generator)


async def _no_read(url: str, need: Need) -> Offer | None:
    raise RuntimeError("agora.reader is not available")


def _fallback_resolve(need: Need, offers: list[Offer]) -> list[Thing]:
    tid = "t-" + "-".join(need.thing.split())[:40]
    for o in offers:
        o.thing_id = tid
    return [Thing(id=tid, name=need.thing, offers=list(offers))] if offers else []


def _fallback_judge(need: Need, things: list[Thing]) -> Verdict:
    priced = [o for t in things for o in t.offers if o.price_eur is not None]
    if not priced:
        return Verdict(headline="No priced offers found yet.", best_offer_url=None, best_true_cost_url=None)
    best = min(priced, key=lambda o: o.price_eur or 0)
    med = statistics.median(o.price_eur or 0 for o in priced)
    return Verdict(
        headline=f"Cheapest: €{best.price_eur:,.0f} at {best.source} ({best.condition}).",
        best_offer_url=best.url,
        best_true_cost_url=None,
        lines=[f"{len(priced)} priced offers, median €{med:,.0f}", "true cost unavailable (judge offline)"],
    )


# ---------- helpers ----------

def _ensure_eur(offer: Offer) -> None:
    if offer.price_eur is not None or offer.price is None:
        return
    if (offer.currency or "EUR").upper() == "EUR":
        offer.price_eur = float(offer.price)
        return
    fx = _module("fx")
    if fx is not None:
        try:
            offer.price_eur = fx.to_eur(offer.price, offer.currency)
        except Exception:
            pass


def _ledger() -> dict[str, Any]:
    cd = _module("contextdev")
    fn = getattr(cd, "ledger", None)
    if fn is None:
        return {}
    try:
        return dict(fn() or {})
    except Exception:
        return {}


def _num(d: dict[str, Any], *keys: str) -> float:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def dedupe_key(offer: Offer) -> tuple[str, float | None, str | None]:
    """Same page after redirects, same price, same unit = the same offer (hyvacleaning.fi -> novah.fi)."""
    final = str(offer.raw.get("final_url") or offer.url).split("#")[0].rstrip("/")
    return final, offer.price, offer.unit


def adopt_redirect(offer: Offer) -> None:
    """A page that redirected belongs to where it landed: the final URL and its domain are the source."""
    final = offer.raw.get("final_url")
    if final and final != offer.url:
        offer.raw["redirected_from"] = offer.url
        offer.url = str(final)
        offer.source = _domain(offer.url)


def _cache_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or ROOT / ".cache")


# SlowDomains lives in agora.domainstats (the reader reads the same file); re-exported here.
from agora.domainstats import SLOW_READ_TIMEOUT, SLOW_WALL_S, SlowDomains  # noqa: E402,F401


class LaneGate:
    """Hands out PAID read slots so each lane gets its first paid read before any lane gets a second
    (and item pages before search pages). The 10/min Context.dev bucket then pays for one new-shop, one
    refurbished and one used page first, instead of whichever lane's pages happened to queue first."""

    def __init__(self, slots: int = PAID_SLOTS) -> None:
        self.free = max(1, slots)
        self.started: dict[str, int] = {}
        self.waiting: list[tuple[tuple[int, int, int], str, asyncio.Future[None]]] = []
        self.n = 0

    def _wake(self) -> None:
        while self.free > 0 and self.waiting:
            self.waiting.sort(key=lambda w: (self.started.get(w[1], 0),) + w[0][1:])
            _, lane, fut = self.waiting.pop(0)
            if fut.done():
                continue
            self.free -= 1
            self.started[lane] = self.started.get(lane, 0) + 1
            fut.set_result(None)

    async def acquire(self, lane: str, list_page: bool = False, prio: int | None = None) -> None:
        """prio (lower first, inside a lane's turn) defaults to item pages before search pages; the hunt passes
        discover.paid_priority: the reads expected to yield the most offers per rate-limit token go first."""
        self.n += 1
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        me = ((0, int(list_page) if prio is None else int(prio), self.n), lane, fut)
        self.waiting.append(me)
        self._wake()
        try:
            await fut
        except BaseException:
            if me in self.waiting:
                self.waiting.remove(me)
            elif fut.done() and not fut.cancelled():
                self.release()          # the slot was ours but nobody will use it
            raise

    def release(self) -> None:
        self.free += 1
        self._wake()


# url -> (status, html) of the free fetch, so the paid stage of the same page does not fetch it again
FETCH_MEMO: contextvars.ContextVar[dict[str, tuple[int, str]] | None] = contextvars.ContextVar(
    "agora_fetch_memo", default=None)


def _install_fetch_memo(reader: Any) -> None:
    """Wrap reader.fetch_html once: inside a hunt (FETCH_MEMO set) the first fetch of a URL is kept and
    the second one (the paid stage) is answered from it. Outside a hunt it is a plain pass-through."""
    fn = getattr(reader, "fetch_html", None)
    if fn is None or getattr(fn, "_agora_memo", False):
        return

    async def fetch_html(url: str) -> tuple[int, str]:
        memo = FETCH_MEMO.get()
        if memo is not None and url in memo:
            return memo.pop(url)
        got = await fn(url)
        if memo is not None:
            memo[url] = got
        return got

    fetch_html._agora_memo = True  # type: ignore[attr-defined]
    reader.fetch_html = fetch_html


def _tokens_now() -> float:
    fn = getattr(_module("discover"), "tokens_available", None)
    try:
        return float(fn()) if fn is not None else 10.0
    except Exception:
        return 10.0


def _accepts(fn: Any, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())


def _budget_default() -> float | None:
    try:
        v = float(os.environ.get("AGORA_HUNT_BUDGET_S", DEFAULT_BUDGET_S))
    except ValueError:
        return DEFAULT_BUDGET_S
    return v if v > 0 else None


def _judge_quietly(judge: Judge, need: Need, things: list[Thing]) -> Verdict:
    """judge() without the price-history lookup when it supports that (a live preview, not the record)."""
    try:
        if "history" in inspect.signature(judge).parameters:
            return judge(need, things, history=False)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        pass
    return judge(need, things)


def snapshot(need: Need, offers: list[Offer], resolve: Resolve, judge: Judge) -> tuple[Verdict | None, list[Offer]]:
    """The verdict as it stands now plus the judged copies (with their provisional true cost)."""
    if not offers:
        return None, []
    try:
        twins = copy.deepcopy(offers)
        return _judge_quietly(judge, need, resolve(need, twins)), twins
    except Exception:
        return None, []


def snapshot_verdict(need: Need, offers: list[Offer], resolve: Resolve, judge: Judge) -> Verdict | None:
    """The verdict as it stands now, judged on copies (the real offers are judged once, at the end)."""
    return snapshot(need, offers, resolve, judge)[0]


def truecost_payload(o: Offer, hunt_id: str | None = None) -> dict[str, Any]:
    """The `truecost` event body for one judged offer."""
    return {"url": o.url, "true_cost": to_dict(o.true_cost) if o.true_cost else None, "trust": o.trust,
            "flags": list(o.flags), "haggle": to_dict(o.haggle) if o.haggle else None, "thing_id": o.thing_id,
            "evidence": o.raw.get("evidence") or [], "price_check": o.raw.get("price_check"),
            "beat_eur": o.raw.get("beat_eur"), "gap_eur": o.raw.get("gap_eur"), "band": o.raw.get("band"),
            "prices_shown": o.raw.get("prices_shown"), "offer_id": o.raw.get("offer_id"),
            "coupons": o.raw.get("coupons") or None, "injection": o.raw.get("injection") or None,
            "origin": _origin(o, list(o.flags)), "hunt_id": hunt_id}


def _cost_key(d: dict[str, Any]) -> str:
    """What a viewer shows from a truecost event (ids left out): equal key = nothing changed on screen."""
    return json.dumps({k: d.get(k) for k in ("true_cost", "trust", "flags", "band", "thing_id")},
                      sort_keys=True, default=str)


def _picks(v: dict[str, Any] | None) -> tuple[Any, Any]:
    return (v or {}).get("best_true_cost_url"), (v or {}).get("best_offer_url")


class Leaderboard:
    """Cheap live re-ranking while offers stream in: copies the offers, resolves and judges them,
    and reports when the top 3 by true cost per month change. Pure, no I/O."""

    def __init__(self, need: Need, resolve: Resolve, size: int = 3) -> None:
        self.need, self.resolve, self.size = need, resolve, size
        self.top: list[dict[str, Any]] = []

    def update(self, offers: list[Offer]) -> dict[str, Any] | None:
        judge_mod = _module("judge")
        if judge_mod is None or not offers:
            return None
        twins = copy.deepcopy(offers)
        try:
            things = self.resolve(self.need, twins)
            judge_mod.judge(self.need, things, history=False)
        except Exception:
            return None
        def settled(o: Offer, peers: list[Offer]) -> bool:
            """Only rank a price once something can vouch for it: a second witness, or at least one other
            offer of its condition within 0.5x-2.5x of it. (Otherwise the first too-cheap listing 'leads'
            for a second before the market can call it out.)"""
            if self.need.kind == "service" or o.raw.get("price_check") == "verified":
                return True
            others = [x.price_eur for x in peers if x is not o and x.condition == o.condition and x.price_eur]
            if not others or not o.price_eur:
                return False
            return 0.5 <= o.price_eur / statistics.median(others) <= 2.5

        ranked = sorted((o for t in things for o in t.offers
                         if o.true_cost is not None and not judge_mod._risky(o) and o.in_stock is not False
                         and settled(o, t.offers)),
                        key=lambda o: o.true_cost.per_month_eur)[: self.size]  # type: ignore[union-attr]
        top = [{"url": o.url, "source": o.source, "cond": o.condition, "price_eur": o.price_eur,
                "per_month": o.true_cost.per_month_eur, "per": getattr(o.true_cost, "per", "month")}  # type: ignore[union-attr]
               for o in ranked]
        if [x["url"] for x in top] == [x["url"] for x in self.top]:
            return None
        prev = {x["url"]: i for i, x in enumerate(self.top)}
        for i, x in enumerate(top):
            x["delta"] = (prev[x["url"]] - i) if x["url"] in prev else None   # +1 = moved up one place
        old_leader = self.top[0] if self.top else None
        changed = bool(top) and (old_leader is None or old_leader["url"] != top[0]["url"])
        reason = None
        if changed:
            new = top[0]
            unit = "/job" if new["per"] == "job" else "/mo"
            reason = (f"{new['cond']} at {new['source']} €{new['per_month']:,.0f}{unit} "
                      + (f"overtook {old_leader['cond']} at {old_leader['source']} €{old_leader['per_month']:,.0f}{unit}"
                         if old_leader else "takes the lead"))
        self.top = top
        return {"top": top, "leader_changed": changed, "reason": reason}


# thing_id -> offer URLs seen in hunts of this process (lets the API build a thing's price history)
THING_URLS: dict[str, set[str]] = {}


def _persist(need: Need, offers: list[Offer], things: list[Thing]) -> None:
    """Best effort: offers + one price snapshot each via agora.store (if that module exists)."""
    for t in things:
        THING_URLS.setdefault(t.id, set()).update(o.url for o in t.offers)
    store = _module("store")
    if store is None:
        return
    try:
        store.save_need(need)
    except Exception:
        pass
    for o in offers:
        try:
            store.save_offer(o)
            store.snapshot(o.url, o.price_eur, o.in_stock)
        except Exception:
            continue


# ---------- the hunt ----------

@dataclass
class HuntResult:
    need: Need | None = None
    offers: list[Offer] = field(default_factory=list)
    things: list[Thing] = field(default_factory=list)
    verdict: Verdict | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    hunt_id: str | None = None


def new_hunt_id() -> str:
    return "h_" + uuid.uuid4().hex[:12]


def _register(hunt_id: str, offers: list[Offer]) -> None:
    """Provenance at hunt scope: every offer Agora read gets an offer_id an agent can buy by
    (buy.buy_offer(offer_id, hunt_id=...)). Best effort."""
    buy = _module("buy")
    reg = getattr(buy, "register_offer", None)
    if reg is None:
        return
    for o in offers:
        try:
            o.raw["offer_id"] = reg(hunt_id, o)
        except Exception:
            continue


async def hunt(
    text: str,
    *,
    parse_need: ParseNeed | None = None,
    discover: Discover | None = None,
    read: Read | None = None,
    resolve: Resolve | None = None,
    judge: Judge | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_sources: int = DEFAULT_MAX_SOURCES,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    persist: bool = True,
    result: HuntResult | None = None,
    lookalikes: bool = True,
    provisional_after: float | None = PROVISIONAL_AFTER,
    stable_for: float = STABLE_FOR,
    slow_domains: SlowDomains | None = None,
    siblings: bool = True,
    sibling_search: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
    budget_s: float | None | bool = True,
    fresh: bool = False,
    hunt_id: str | None = None,
) -> AsyncIterator[Event]:
    """Run one hunt, yielding Events as they happen. Pass `result` to also collect the final objects.

    `budget_s`: wall-clock seconds after which unfinished page reads stop (True = DEFAULT_BUDGET_S or
    AGORA_HUNT_BUDGET_S, None/False/0 = no cap). A read cut by the budget or its own timeout falls back to
    the price in its search snippet when that is safe (real reader only), else it becomes a `skip`."""
    t0 = time.monotonic()
    out = result if result is not None else HuntResult()
    out.hunt_id = hunt_id = hunt_id or new_hunt_id()
    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    def ev(type_: str, **data: Any) -> Event:
        e = Event(type=type_, data=data, t_ms=int((time.monotonic() - t0) * 1000))
        out.events.append(e)
        return e

    # resolve stages: injected > sibling module > fallback
    if parse_need is None:
        parse_need = getattr(_module("need"), "parse_need", None) or _fallback_parse_need
    if discover is None:
        discover = getattr(_module("discover"), "discover", None) or _no_discover
    snippet_fallback: Callable[[str, Need], Offer | None] | None = None
    two_phase = False            # real reader: free JSON-LD read of every page first, paid reads lane by lane
    free_read: Read | None = None
    if read is None:
        reader = _module("reader")
        if getattr(reader, "read_with_reason", None) is not None:
            two_phase = True
            _install_fetch_memo(reader)

            async def free_read(url: str, need: Need) -> Any:
                return await reader.read_with_reason(url, need, paid=False, expand_lists=True)

            async def read(url: str, need: Need) -> Any:   # noqa: F811 - the paid stage
                # a safe search-snippet price (one price, every word of the need in the title) beats a paid read
                return await reader.read_with_reason(url, need, snippet_ok=True, expand_lists=True)
        else:
            read = getattr(reader, "read", None) or _no_read
        snippet_fallback = getattr(reader, "snippet_fallback", None)
    if budget_s is True:
        budget_s = _budget_default()
    deadline = t0 + float(budget_s) if budget_s else None
    if resolve is None:
        resolve = getattr(_module("resolve"), "resolve", None) or _fallback_resolve
    if judge is None:
        judge = getattr(_module("judge"), "judge", None) or _fallback_judge

    ledger0 = _ledger()
    cd = _module("contextdev")
    per_hunt: dict[str, Any] | None = None
    if cd is not None and hasattr(cd, "HUNT_LEDGER"):
        per_hunt = {}
        cd.HUNT_LEDGER.set(per_hunt)   # read tasks created below inherit it
    if fresh and cd is not None and hasattr(cd, "MAX_AGE_MS"):
        cd.MAX_AGE_MS.set(0)           # watcher re-hunts: every paid read past the scrape caches
    if two_phase:
        FETCH_MEMO.set({})
    tokens0 = _tokens_now()            # the shared 10/min bucket as this hunt starts
    trust_mod = _module("trust") if judge is getattr(_module("judge"), "judge", None) else None
    trust_tasks: list[asyncio.Task[Any]] = []

    def prefetch_trust() -> None:
        """Image hashes + WHOIS dates fetched in the background while reads finish, so the final
        judge's own warm-up finds them cached. Offline it does nothing."""
        if trust_mod is None or not hasattr(trust_mod, "prefetch") or not out.offers:
            return
        trust_tasks.append(asyncio.create_task(trust_mod.prefetch(list(out.offers), budget_s=3)))

    # 1 NEED
    try:
        need = parse_need(text)
    except Exception as exc:
        yield ev("error", where="need", message=str(exc))
        need = _fallback_parse_need(text)
    out.need = need
    yield ev("need", need=to_dict(need), hunt_id=hunt_id)

    # warm the FX table off the event loop (first use may hit frankfurter.app once a day)
    fx = _module("fx")
    if fx is not None and getattr(fx, "_rates", 1) is None:
        try:
            await asyncio.wait_for(asyncio.to_thread(fx.rates), timeout=5)
        except Exception:
            pass

    # 1b SIBLING LANE: used prices of the generation before/after, to MEASURE depreciation (search only)
    dep_mod = _module("depreciation") if siblings and need.kind == "product" else None
    family = dep_mod.find_model(f"{need.thing} {need.raw}") if dep_mod is not None else None
    if family is not None and sibling_search is None and tokens0 < SIBLING_MIN_TOKENS:
        family = None        # the bucket is low: the lanes' own searches and reads come first
    sib_tokens = 0
    sibling_task: asyncio.Task[list[dict[str, Any]]] | None = None
    sib_done: dict[str, dict[str, Any]] = {}     # siblings measured so far (kept if the lane runs late)
    if family is not None and (sibs := dep_mod.siblings(*family)):
        search = sibling_search or dep_mod.default_search
        sib_tokens = len(sibs)

        async def sibling_points() -> list[dict[str, Any]]:
            async def one(m: Any) -> dict[str, Any]:
                try:
                    prices = await dep_mod.sibling_prices(
                        m, need, search, None if sibling_search is not None else dep_mod.capped_reader(0))   # free reads only
                except Exception:
                    prices = []
                sib_done[m.name] = dep_mod.point(m, prices)
                return sib_done[m.name]
            return list(await asyncio.gather(*(one(m) for m in sibs)))

        yield ev("lane", lane="sibling", queries=[m.query for m in sibs], family=family[0],
                 why="measure depreciation from neighbouring generations")
        sibling_task = asyncio.create_task(sibling_points())

    # 2 DISCOVER + 3 READ, interleaved: a page is read the moment its source shows up
    sem = asyncio.Semaphore(max(1, concurrency))
    seen: set[str] = set()
    offer_keys: dict[tuple[str, float | None, str | None], str] = {}
    board = Leaderboard(need, resolve)
    lookalike = {"anchors": [], "launched": False}
    exa = _module("exa") if lookalikes else None

    def schedule_read(url: str) -> None:
        reads.add(asyncio.create_task(read_one(url)))

    async def lookalike_lane(anchor: Offer) -> None:
        """Exa findSimilar on a good EU shop: more small dealers, read like any other source."""
        try:
            found = await exa.find_similar(anchor.url, n=8, exclude_domains=sorted({_domain(u) for u in seen}))
        except Exception as exc:
            await queue.put(ev("error", where="exa", message=f"{type(exc).__name__}: {exc}"[:300]))
            return
        fresh = [r for r in found if r["url"] not in seen and _domain(r["url"]) not in {_domain(u) for u in seen}]
        if not fresh:
            return
        await queue.put(ev("lane", lane="lookalike", queries=[f"like {anchor.source}"], via="exa"))
        for r in fresh:
            if len(seen) >= max_sources + 8:      # the look-alike lane gets its own small allowance
                break
            seen.add(r["url"])
            await queue.put(ev("source", url=r["url"], domain=_domain(r["url"]), lane="lookalike", via="exa",
                               similar_to=anchor.source, title=r.get("title", "")))
            schedule_read(r["url"])

    def maybe_lookalike(offer: Offer) -> None:
        if exa is None or lookalike["launched"] or not getattr(exa, "enabled", lambda: False)():
            return
        if offer.read_via not in ("jsonld", "contextdev_product") or offer.price_eur is None \
                or offer.raw.get("from_list_page"):
            return
        if (offer.currency or "EUR").upper() not in EU_CURRENCIES or any(m in offer.source for m in ("ebay.", "amazon.")):
            return
        lookalike["anchors"].append(offer)
        if len(lookalike["anchors"]) >= 2:
            lookalike["launched"] = True
            reads.add(asyncio.create_task(lookalike_lane(lookalike["anchors"][0])))
    reads: set[asyncio.Task[None]] = set()
    slow = slow_domains if slow_domains is not None else SlowDomains()

    async def timed_read(url: str, fn: Read) -> tuple[Any, float, float]:
        """Run one read with a budget of `limit` seconds of PAGE WORK: time spent queued for the shared
        Context.dev rate limit is added back (up to MAX_QUEUE_ALLOWANCE). Returns (result, limit, queued)."""
        queued = [0.0, 0.0]
        waited = getattr(cd, "queued_seconds", lambda q: q[0])
        limit = slow.timeout_for(_domain(url), read_timeout)
        wall = getattr(slow, "wall_for", lambda d: None)(_domain(url))

        async def run() -> Any:
            if cd is not None and hasattr(cd, "QUEUED"):
                cd.QUEUED.set(queued)      # this task's own context: other reads never see it
            return await fn(url, need)

        task = asyncio.ensure_future(run())
        start = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                left = limit + min(waited(queued), MAX_QUEUE_ALLOWANCE) - (now - start)
                if wall is not None:
                    left = min(left, wall - (now - start))
                if deadline is not None:
                    left = min(left, deadline - now)
                if left <= 0:
                    raise TimeoutError
                done, _ = await asyncio.wait({task}, timeout=min(left, 1.0) if queued[1] else left)
                if done:
                    return task.result(), limit, queued[0]
        finally:
            if not task.done():
                task.cancel()

    gate = LaneGate(PAID_SLOTS)
    lane_of: dict[str, str] = {}

    async def two_phase_read(url: str) -> tuple[Any, float]:
        """Free read (direct fetch + JSON-LD) first; only a page that needs Context.dev waits for a paid
        slot, handed out lane by lane. Returns (result, seconds not spent on this page's own work)."""
        async with sem:
            got, _, q1 = await timed_read(url, free_read)
        offer, why = got if isinstance(got, tuple) else (got, "")
        if (offer is not None and why in ("jsonld", "snippet_rate")) \
                or (offer is None and str(why).startswith("page gone")):
            (FETCH_MEMO.get() or {}).pop(url, None)      # free: JSON-LD, or a service rate stated in the snippet
            return got, q1
        t = time.monotonic()
        left = None if deadline is None else deadline - t
        if left is not None and left <= 0:
            raise TimeoutError
        dv = _module("discover")
        listy = bool(getattr(dv, "is_list_page", lambda u: False)(url))
        if listy and lane_of.get(url) in ("used", "refurbished"):
            listy = False     # a marketplace search page is the used lane's best page: up to 8 listings in one read
        prio = None
        if getattr(dv, "paid_priority", None) is not None:
            h = getattr(_module("reader"), "_HINTS", {}).get(url) or {}
            try:
                prio = dv.paid_priority(url, need.kind, lane_of.get(url, ""), h.get("title", ""), h.get("snippet", ""))
            except Exception:
                prio = None
        acquire = gate.acquire(lane_of.get(url, ""), listy, prio)
        await (asyncio.wait_for(acquire, timeout=left) if left is not None else acquire)
        waited = time.monotonic() - t
        try:
            got, _, q2 = await timed_read(url, read)
        finally:
            gate.release()
        return got, q1 + q2 + waited

    async def plain_read(url: str) -> tuple[Any, float]:
        async with sem:
            got, _, queued_s = await timed_read(url, read)
        return got, queued_s

    async def read_one(url: str) -> None:
        reason = "no offer on page"
        started = time.monotonic()
        try:
            got, queued_s = await (two_phase_read(url) if two_phase else plain_read(url))
            offer, reason = got if isinstance(got, tuple) else (got, reason)
            work = max(0.0, time.monotonic() - started - queued_s)
            try:
                slow.record(_domain(url), timed_out=False, seconds=work)
            except TypeError:             # an injected SlowDomains without timing
                slow.record(_domain(url), timed_out=False)
        except TimeoutError:
            was_slow = slow.is_slow(_domain(url))
            limit = slow.timeout_for(_domain(url), read_timeout)
            over_budget = deadline is not None and time.monotonic() >= deadline - 0.05
            if not over_budget:           # running out of hunt time says nothing about the domain
                slow.record(_domain(url), timed_out=True)
            why = (f"hunt budget {budget_s:.0f}s reached" if over_budget else f"timeout after {limit:.0f}s"
                   + (" (known slow domain)" if was_slow else ""))
            fallback = None
            if snippet_fallback is not None:
                try:
                    fallback = snippet_fallback(url, need)
                except Exception:
                    fallback = None
            if fallback is None:
                await queue.put(ev("skip", url=url, reason=why, timeout=True))
                return
            fallback.raw["fallback_reason"] = why
            offer = fallback
        except Exception as exc:
            await queue.put(ev("error", where="read", url=url, message=f"{type(exc).__name__}: {exc}"[:300]))
            return
        if offer is None or (isinstance(offer, list) and not offer):
            await queue.put(ev("skip", url=url, reason=reason or "no offer on page"))
            return
        for one in (offer if isinstance(offer, list) else [offer]):   # a search page cut into listings
            await accept(url, one)

    async def accept(url: str, offer: Offer) -> None:
        if offer.raw.get("from_list_page"):
            url = offer.url            # each listing of a search page is its own source
        _ensure_eur(offer)
        adopt_redirect(offer)
        key = dedupe_key(offer)
        if key in offer_keys:
            await queue.put(ev("skip", url=url, reason=f"same offer as {offer_keys[key]} (redirect or duplicate)"))
            return
        offer_keys[key] = url
        out.offers.append(offer)
        await queue.put(ev("offer", offer=offer_payload(offer)))
        rank = board.update(out.offers)
        if rank is not None:
            await queue.put(ev("rank", **rank))
        maybe_lookalike(offer)

    latest: dict[str, Any] = {}

    def late_event(item: Event) -> Event:
        """A page that landed after the provisional verdict: did it change the call (vs the latest one)?"""
        o = item.data.get("offer") or {}
        before = latest.get("v") or provisional
        now, twins = snapshot(need, out.offers, resolve, judge)
        latest["twins"] = twins
        after = to_dict(now) if now is not None else before
        latest["v"] = after
        changed = _picks(after) != _picks(before)
        what = f"{o.get('source')} arrived late ({o.get('condition')} €{(o.get('price_eur') or 0):,.0f})"
        delta: dict[str, Any] = {}
        if changed:
            delta = {"best_true_cost_url": [_picks(before)[0], _picks(after)[0]],
                     "best_offer_url": [_picks(before)[1], _picks(after)[1]],
                     "headline": [(before or {}).get("headline"), (after or {}).get("headline")]}
        note = f"{what}: verdict changed. {(after or {}).get('headline', '')}" if changed \
            else f"{what}: verdict unchanged"
        return ev("late", url=o.get("url"), source=o.get("source"), changed_verdict=changed, delta=delta, note=note)

    disc_kw: dict[str, Any] = {}
    if _accepts(discover, "max_sources"):
        disc_kw["max_sources"] = max_sources
    if _accepts(discover, "tokens"):
        disc_kw["tokens"] = tokens0 - sib_tokens

    async def produce() -> None:
        try:
            async for e in discover(need, **disc_kw):
                if e.type == "source":
                    url = str(e.data.get("url") or "")
                    if not url or url in seen:
                        continue
                    if len(seen) >= max_sources:
                        continue
                    seen.add(url)
                    lane_of[url] = str(e.data.get("lane") or "")
                    e.data.setdefault("domain", urlparse(url).netloc.removeprefix("www."))
                    e.t_ms = int((time.monotonic() - t0) * 1000)
                    out.events.append(e)
                    await queue.put(e)
                    schedule_read(url)
                else:
                    e.t_ms = int((time.monotonic() - t0) * 1000)
                    out.events.append(e)
                    await queue.put(e)
        except Exception as exc:
            await queue.put(ev("error", where="discover", message=f"{type(exc).__name__}: {exc}"[:300]))
        while pending := [t for t in reads if not t.done()]:   # reads can spawn more reads (look-alikes)
            await asyncio.gather(*pending, return_exceptions=True)
        await queue.put(None)

    producer = asyncio.create_task(produce())
    provisional: dict[str, Any] | None = None
    shown_cost: dict[str, str] = {}          # url -> what the provisional truecost event already showed
    moved_at: float | None = None            # last time the leaderboard changed (or the first offer landed)

    def provisional_due() -> float | None:
        """Seconds until the provisional verdict is due (None = not yet possible, or already sent)."""
        if provisional is not None or provisional_after is None or moved_at is None:
            return None
        now = time.monotonic()
        return max(0.0, min(t0 + provisional_after, moved_at + stable_for) - now)

    try:
        while True:
            wait = provisional_due()
            try:
                item = await (asyncio.wait_for(queue.get(), timeout=wait) if wait is not None else queue.get())
            except TimeoutError:
                v, twins = snapshot(need, out.offers, resolve, judge)
                if v is not None:
                    provisional = to_dict(v)
                    pending = sum(1 for t in reads if not t.done())
                    # cost cards right away (judged on copies): no "costing…" while slow pages finish
                    for tw in twins:
                        if tw.true_cost is not None:
                            body = truecost_payload(tw, hunt_id) | {"provisional": True}
                            shown_cost[tw.url] = _cost_key(body)
                            yield ev("truecost", **body)
                    yield ev("verdict", verdict=provisional, provisional=True, pending_reads=pending,
                             offers_so_far=len(out.offers))
                    prefetch_trust()
                else:
                    moved_at = time.monotonic()      # nothing judgeable yet: try again after another quiet spell
                continue
            if item is None:
                break
            yield item
            if item.type == "rank" or (item.type == "offer" and moved_at is None):
                moved_at = time.monotonic()
            if item.type == "offer" and provisional is not None:
                yield late_event(item)
                url = (item.data.get("offer") or {}).get("url")
                tw = next((t for t in latest.get("twins") or [] if t.url == url and t.true_cost is not None), None)
                if tw is not None:      # a late page gets its cost card right away too
                    body = truecost_payload(tw, hunt_id) | {"provisional": True}
                    shown_cost[tw.url] = _cost_key(body)
                    yield ev("truecost", **body)
    finally:
        if not producer.done():  # consumer went away (client disconnect): stop all work
            producer.cancel()
            for t in reads:
                t.cancel()
            if sibling_task is not None:
                sibling_task.cancel()
        slow.save()

    prefetch_trust()               # pages that landed after the provisional verdict (cache skips the rest)
    if trust_tasks:
        try:
            await asyncio.wait_for(asyncio.gather(*trust_tasks, return_exceptions=True), timeout=3.5)
        except TimeoutError:
            pass                   # late lookups keep filling the cache in their threads

    # 4 RESOLVE (the optional model relevance check runs first: one batched call, <=2.5 s, never raises)
    rel_mod = _module("relevance")
    if rel_mod is not None:
        try:
            await rel_mod.prefetch(need, out.offers)
        except Exception:
            pass
    things: list[Thing] = []
    try:
        things = resolve(need, out.offers)
    except Exception as exc:
        yield ev("error", where="resolve", message=f"{type(exc).__name__}: {exc}"[:300])
        things = _fallback_resolve(need, out.offers)
    out.things = things
    kept = {id(o) for t in things for o in t.offers}
    explain = getattr(_module("resolve"), "explain", None)
    for o in out.offers:
        if id(o) in kept:
            continue
        reason = "not the thing you asked for"
        if explain is not None:
            try:
                reason = explain(need, o)[1] or reason
            except Exception:
                pass
        yield ev("skip", url=o.url, reason=reason, rejected=True, title=o.title)
    for t in things:
        yield ev("thing", thing_id=t.id, name=t.name, n_offers=len(t.offers))

    # 4b DEPRECIATION: measured from the shelf when the sibling lane found enough comps
    depreciation: dict[str, Any] | None = None
    if sibling_task is not None and family is not None:
        try:
            left = max(1.0, t0 + SIBLING_DEADLINE - time.monotonic())
            points = await asyncio.wait_for(sibling_task, timeout=left)
        except Exception:
            points = list(sib_done.values())
        judge_mod = _module("judge")
        model = dep_mod.FAMILIES[family[0]][family[1]]
        kept_offers = [o for t in things for o in t.offers]
        used = judge_mod.market_prices(kept_offers, "used") if judge_mod is not None else []
        points = sorted(points + [dep_mod.point(model, used)], key=lambda p: p["year"])
        depreciation = dep_mod.measure(points)
        cat = judge_mod.category_for(need.thing) if judge_mod is not None else None
        assumed = cat.rate if cat is not None else None
        yield ev("depreciation", family=family[0], model=model.name, points=points,
                 rate=depreciation["rate"] if depreciation else assumed,
                 source="measured" if depreciation else "assumed",
                 pairs=depreciation["pairs"] if depreciation else [],
                 basis=depreciation["basis"] if depreciation else
                 (f"assumed -{assumed:.0%}/yr ({cat.name}): too few used listings of neighbouring generations"
                  if cat is not None else "assumed category rate"))

    # 5 JUDGE
    try:
        if depreciation is not None and "depreciation" in inspect.signature(judge).parameters:
            verdict = judge(need, things, depreciation=depreciation)  # type: ignore[call-arg]
        else:
            verdict = judge(need, things)
    except Exception as exc:
        yield ev("error", where="judge", message=f"{type(exc).__name__}: {exc}"[:300])
        verdict = _fallback_judge(need, things)
    if persist:
        try:
            await asyncio.to_thread(_register, hunt_id, out.offers)
        except Exception:
            pass
    for o in out.offers:
        if o.true_cost is not None or o.trust is not None:
            body = truecost_payload(o, hunt_id)
            if o.url in shown_cost:     # costed already at the provisional verdict: say if it moved
                body["unchanged"] = shown_cost[o.url] == _cost_key(body)
            yield ev("truecost", **body)
    out.verdict = verdict
    final = to_dict(verdict)
    extra: dict[str, Any] = {"provisional": False}
    if provisional is not None:
        extra["changed_from"] = ({"headline": provisional.get("headline"),
                                  "best_true_cost_url": provisional.get("best_true_cost_url"),
                                  "best_offer_url": provisional.get("best_offer_url")}
                                 if _picks(provisional) != _picks(final) else None)
    yield ev("verdict", verdict=final, **extra)

    if persist:
        try:
            await asyncio.to_thread(_persist, need, out.offers, things)
        except Exception:
            pass

    # 6 BUDGET
    ledger1 = _ledger()
    if per_hunt is not None:      # this hunt's own bill (other hunts in the process do not leak in)
        delta = {k: _num(per_hunt, k) for k in ("credits_used", "requests", "saved_by_free_reads", "cache_hits")}
    else:
        delta = {k: _num(ledger1, k) - _num(ledger0, k)
                 for k in ("credits_used", "requests", "saved_by_free_reads", "cache_hits")}
    free_domains = sorted({o.source for o in out.offers if o.read_via == "jsonld"})
    free = max(sum(1 for o in out.offers if o.read_via == "jsonld"), int(delta["saved_by_free_reads"]))
    out.budget = {
        "credits_used": round(delta["credits_used"], 2),
        "requests": int(delta["requests"]),
        "saved_by_free_reads": free,
        "free_reads": free_domains,
        "cache_hits": int(delta["cache_hits"]),
        "pages": len(seen),
        "offers": len(out.offers),
    }
    try:
        per_credit = float(os.environ.get("AGORA_EUR_PER_CREDIT", ""))
    except ValueError:
        per_credit = None
    if per_credit is not None:   # only when the plan price is configured: never a made-up number
        out.budget["credit_eur"] = round(delta["credits_used"] * per_credit, 4)
        out.budget["credit_eur_basis"] = f"{delta['credits_used']:g} credits x €{per_credit:g} (AGORA_EUR_PER_CREDIT)"
    yield ev("budget", **out.budget)
    yield ev("done", ms=int((time.monotonic() - t0) * 1000))


# ---------- replay: a recorded hunt, streamed back at its real pace (demo-proof, zero credits) ----------

RECORDINGS = ROOT / "tests" / "fixtures"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def recordings() -> list[str]:
    return sorted(p.stem.removeprefix("live_") for p in RECORDINGS.glob("live_*.jsonl"))


def recording_path(slug: str) -> pathlib.Path | None:
    """tests/fixtures/live_<slug>.jsonl, or None. Only plain slugs: no paths from the outside world."""
    if not _SLUG.match(slug or ""):
        return None
    path = RECORDINGS / f"live_{slug}.jsonl"
    return path if path.is_file() else None


def load_recording(slug: str) -> list[Event]:
    path = recording_path(slug)
    if path is None:
        raise FileNotFoundError(f"no recording '{slug}' (have: {', '.join(recordings())})")
    return [Event(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def add_origins(events: list[Event]) -> list[Event]:
    """Recordings made before round A have no `origin`: add it in memory (files are not rewritten).
    Offer events get it from the payload + that url's last truecost flags; truecost events from the
    matching offer payload + their own flags."""
    flags: dict[str, list[str]] = {}
    for e in events:
        if e.type == "truecost" and e.data.get("url"):
            flags[e.data["url"]] = list(e.data.get("flags") or [])
    offers: dict[str, dict[str, Any]] = {}
    out: list[Event] = []
    for e in events:
        data = e.data
        if e.type == "offer" and isinstance(data.get("offer"), dict):
            o = data["offer"]
            offers.setdefault(o.get("url") or "", o)
            if "origin" not in o:
                try:
                    data = dict(data) | {"offer": dict(o) | {"origin": origin_from_payload(o, flags.get(o.get("url")))}}
                except Exception:
                    pass
        elif e.type == "truecost" and "origin" not in data:
            o = offers.get(data.get("url") or "") or {"url": data.get("url")}
            try:
                data = dict(data) | {"origin": origin_from_payload(o, list(data.get("flags") or []))}
            except Exception:
                pass
        out.append(e if data is e.data else Event(type=e.type, data=data, t_ms=e.t_ms))
    return out


REPLAY_MAX_GAP_MS = 1500     # the viewer's default: idle waits longer than this are skipped (and labelled)


async def replay(slug: str, speed: float = 1.0,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 max_gap_ms: float | None = None) -> AsyncIterator[Event]:
    """Stream a recorded hunt with its original t_ms gaps (divided by `speed`). t_ms is rescaled too,
    so a frontend timer shows the replayed pace. Order is exactly as recorded.

    `max_gap_ms` (None = honest real pace): any wait between two events longer than this (on the
    recorded clock) is cut to it, e.g. the 16 s a live hunt spends waiting on slow pages. Each event
    then carries `data["idle_skipped_ms"]`, the recorded time skipped so far."""
    speed = max(0.25, min(float(speed), 16.0))
    events = add_origins(load_recording(slug))
    clock, skipped = 0, 0
    for e in events:
        gap = max(0, e.t_ms - clock)
        if max_gap_ms is not None and gap > max_gap_ms:
            skipped += gap - int(max_gap_ms)
            gap = int(max_gap_ms)
        if gap:
            await sleep(gap / 1000 / speed)
        clock = max(clock, e.t_ms)
        data = e.data if max_gap_ms is None else (dict(e.data) | {"idle_skipped_ms": skipped})
        yield Event(type=e.type, data=data, t_ms=int((e.t_ms - skipped) / speed))


async def run_hunt(text: str, **kwargs: Any) -> HuntResult:
    """Drain a hunt and return everything it found (for MCP / scripts)."""
    res = HuntResult()
    async for _ in hunt(text, result=res, **kwargs):
        pass
    return res
