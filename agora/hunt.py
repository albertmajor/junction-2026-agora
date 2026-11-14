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
from agora.need import is_service, service_view
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
DEFAULT_BUDGET_S = 24.0      # a live hunt stops waiting for pages after this (AGORA_HUNT_BUDGET_S; 0 = no cap)
PROVISIONAL_AFTER = 8.0      # send a provisional verdict by this many seconds...
FOREIGN_PRIO = 4             # paid-read priority penalty for a page abroad when the hunt is scoped home
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
    raw = d.pop("raw", None) or {}
    for k in ("grade", "grade_score", "shutter_count", "battery_health"):   # used-dealer condition, small
        if raw.get(k) is not None:
            d[k] = raw[k]
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


LIVE_SAMPLE = 600           # live re-ranking judges at most this many offers (the final judge sees them all)


def sample_offers(offers: list[Offer], n: int = LIVE_SAMPLE) -> list[Offer]:
    """A generic hunt reads up to ~2,000 marketplace listings; the live leaderboard re-judges a sample: every
    offer that is not a marketplace row, the cheapest third of the rows (the leaders come from there) and an
    even spread of the rest (so market medians and the 'settled' check still see the whole price range)."""
    if len(offers) <= n:
        return offers
    rows = [o for o in offers if o.raw.get("from_list_page")]
    keep = [o for o in offers if not o.raw.get("from_list_page")]
    room = max(0, n - len(keep))
    priced = sorted(rows, key=lambda o: (o.price_eur is None, o.price_eur or 0))
    cheap = priced[: room // 3]
    rest = priced[room // 3:]
    k = max(1, room - len(cheap))
    step = max(1.0, len(rest) / k)
    spread = [rest[int(i * step)] for i in range(min(k, len(rest)))]
    return keep + cheap + spread


class Leaderboard:
    """Cheap live re-ranking while offers stream in: copies the offers, resolves and judges them,
    and reports when the top 3 by true cost per month change. Pure, no I/O."""

    def __init__(self, need: Need, resolve: Resolve, size: int = 3) -> None:
        self.need, self.resolve, self.size = need, resolve, size
        self.top: list[dict[str, Any]] = []
        self._last = 0.0
        self._cost = 0.0

    def update(self, offers: list[Offer]) -> dict[str, Any] | None:
        judge_mod = _module("judge")
        if judge_mod is None or not offers:
            return None
        now = time.monotonic()
        # hundreds of offers (free marketplace pages read 8 deep): re-rank at most once a second, and never
        # spend more than ~1/3 of the event loop on it (a 900-offer judge takes ~1 s)
        if len(offers) > 40 and now - self._last < max(1.0, 3 * self._cost):
            return None
        self._last = now
        twins = copy.deepcopy(sample_offers(offers))
        try:
            things = self.resolve(self.need, twins)
            judge_mod.judge(self.need, things, history=False)
        except Exception:
            return None
        finally:
            self._cost = time.monotonic() - now
        def settled(o: Offer, peers: list[Offer]) -> bool:
            """Only rank a price once something can vouch for it: a second witness, or at least one other
            offer of its condition within 0.5x-2.5x of it. (Otherwise the first too-cheap listing 'leads'
            for a second before the market can call it out.)"""
            if is_service(self.need) or o.raw.get("price_check") == "verified":
                return True
            others = [x.price_eur for x in peers if x is not o and x.condition == o.condition and x.price_eur]
            if not others or not o.price_eur:
                return False
            return 0.5 <= o.price_eur / statistics.median(others) <= 2.5

        pool = [o for t in things for o in t.offers
                if o.true_cost is not None and not judge_mod._risky(o) and o.in_stock is not False
                and settled(o, t.offers)]
        groups = {str(o.raw.get("period_group")) for o in pool if o.raw.get("period_group")}
        if groups and is_service(self.need):
            # like with like: monthly plans are never ranked against hourly rates or project prices
            by: dict[str, list[Offer]] = {}
            for o in pool:
                if o.raw.get("period_group"):
                    by.setdefault(str(o.raw["period_group"]), []).append(o)
            lead = getattr(judge_mod, "lead_group", lambda n, g: max(g, key=lambda k: len(g[k])))(self.need, by)
            pool = by[lead]
        ranked = sorted(pool, key=lambda o: o.true_cost.per_month_eur)[: self.size]  # type: ignore[union-attr]
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
            unit = PER_SUFFIX.get(new["per"], "/mo")
            reason = (f"{new['cond']} at {new['source']} €{new['per_month']:,.0f}{unit} "
                      + (f"overtook {old_leader['cond']} at {old_leader['source']} €{old_leader['per_month']:,.0f}{unit}"
                         if old_leader else "takes the lead"))
        self.top = top
        return {"top": top, "leader_changed": changed, "reason": reason}


PER_SUFFIX = {"job": "/job", "hour": "/h", "day": "/day", "month": "/mo"}


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


# ---------- reading the need (vague words, home city, typed language) ----------

AUTO_INTENT_MIN_CONF = 0.45
_RECIPIENT = re.compile(r"^(?:for|to|för|für|voor|pour|til)\s+(?:my\s+|a\s+|the\s+)?[\w'-]+(?:\s+[\w'-]+)?$|^\w+lle$",
                        re.I)


def auto_intent_for(need: Need) -> str | None:
    """The intent id to hunt for a bare vague word, or None. Only when the words are (almost) just a known
    concept ('lunch', 'gift for mom') and its likeliest meaning is another KIND of thing than the literal parse
    (a service for 'lunch', a product for a gift): a model, a brand or extra nouns keep the typed reading."""
    try:
        from agora import intent as intent_mod
        key, _, rest = intent_mod.match_concept(need.raw)
        if key is None or (rest and not _RECIPIENT.match(rest)):
            return None
        got = intent_mod.interpret(need.raw, llm=False)
    except Exception:
        return None
    top = (got.get("intents") or [None])[0]
    if not top or top.get("as_typed") or (top.get("confidence") or 0) < AUTO_INTENT_MIN_CONF:
        return None
    service_like = top.get("kind") in ("service", "digital")
    # a vague present ('gift for mom') is a thing to buy either way, but hunted literally it matched the token
    # 'mom' (eval r2: used baby socks were the pick): its meaning hunts the kinds of things people give
    vague_gift = str(top.get("id") or "").startswith("c:gift.") and top.get("kind") == "product" \
        and not top.get("node")
    if service_like == is_service(need) and not vague_gift:
        return None               # the parse already reads it as that kind: nothing to fix
    if need.conditions not in (["new", "refurbished", "used"], ["new"], ["service"]):
        return None               # 'used ...' asked for a thing to buy
    return str(top["id"])


HOME_CITY = {"fi": "Helsinki", "se": "Stockholm", "de": "Berlin", "nl": "Amsterdam", "dk": "Copenhagen",
             "no": "Oslo", "ee": "Tallinn", "at": "Vienna", "be": "Brussels", "fr": "Paris", "es": "Madrid",
             "it": "Rome", "pl": "Warsaw", "pt": "Lisbon", "ie": "Dublin", "gb": "London", "cz": "Prague"}


def home_city() -> str | None:
    """AGORA_HOME_CITY, else the home country's capital (AGORA_COUNTRY, default fi -> Helsinki)."""
    env = (os.environ.get("AGORA_HOME_CITY") or "").strip()
    if env:
        return None if env.lower() in ("none", "off", "-") else env[:60]
    dv = _module("discover")
    try:
        cc = dv.home_country() if dv is not None else None
    except Exception:
        cc = None
    return HOME_CITY.get(cc or "")


def default_where(need: Need) -> str | None:
    """A local trade with no place asked ('Plumbing' from the tree, 'plumber') is done where you live: set
    need.where to the home city and return the note to show ('near Helsinki (your home city)'). Subscriptions,
    B2B work and trips are bought from anywhere and keep no place."""
    if need.where or not is_service(need):
        return None
    try:
        from agora.need import priced_per_period
        if priced_per_period(need):
            return None
    except Exception:
        return None
    it = (need.category or {}).get("intent") or {}
    if it.get("travel"):
        return None
    city = home_city()
    if not city:
        return None
    need.where = city
    return f"near {city} (your home city)"


def scope_question(need: Need) -> dict[str, Any] | None:
    """Typed in another country's language with no place ('kinderwagen gebraucht' on a Finnish server): say
    where we search and offer that country's market as one tap."""
    if need.where or need.kind != "product":
        return None
    try:
        from agora.need import LANG_COUNTRY, query_language
        dv = _module("discover")
        home = dv.home_country() if dv is not None else None
        lang = query_language(need.raw)
    except Exception:
        return None
    cc = LANG_COUNTRY.get(lang or "")
    if not cc or not home or cc == home:
        return None
    names = {"de": ("Germany", "germany"), "se": ("Sweden", "sweden"), "nl": ("the Netherlands", "netherlands"),
             "fi": ("Finland", "finland")}
    if cc not in names:
        return None
    name, word = names[cc]
    return {"lang": lang, "country": cc, "home": home,
            "text": f"Typed in {_LANG_NAMES.get(lang or '', lang)}: searching near you in {home.upper()} first, "
                    f"{name} shown as pickup abroad. Search {name} instead?",
            "hunt": {"q": f"{need.raw} in {word}"}}


_LANG_NAMES = {"de": "German", "sv": "Swedish", "nl": "Dutch", "fi": "Finnish"}


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
    longtail: bool = True,
    depth: int = 1,
    check_pick: bool = True,
    category: str | None = None,
    intent: str | None = None,
) -> AsyncIterator[Event]:
    """Run one hunt, yielding Events as they happen. Pass `result` to also collect the final objects.

    `budget_s`: wall-clock seconds after which unfinished page reads stop (True = DEFAULT_BUDGET_S or
    AGORA_HUNT_BUDGET_S, None/False/0 = no cap). A read cut by the budget or its own timeout falls back to
    the price in its search snippet when that is safe (real reader only), else it becomes a `skip`.

    `depth` ("Compare more", 1-3): 2-3 read deeper. More pages (max_sources x depth, <= 60, unless a cap was
    passed), a longer budget (x1.5 / x2), more free tori pages (reader.READ_DEPTH) and page 2-3 of the paid
    marketplaces while the shared bucket allows (discover(pages=depth) -> marketplaces.direct_pages).

    `category` (a node id of agora.taxonomy, from a hunt started in the category tree): the need takes that
    node's kind (a service node runs service lanes only), lanes, size, where-to-look and local words, and a
    `category` event {id, path, kind, confidence, source: "tree"} follows the `need` event. Without it a typed
    need is classified (need.categorize, confidence >= 0.6): source "classified"."""
    t0 = time.monotonic()
    depth = max(1, min(3, int(depth or 1)))
    if depth > 1:
        if max_sources == DEFAULT_MAX_SOURCES:
            max_sources = min(60, max_sources * depth)
        if budget_s is True:
            b = _budget_default()
            budget_s = b * (1 + 0.5 * (depth - 1)) if b else None
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
    base_resolve = resolve

    def resolve(need: Need, offers: list[Offer]) -> list[Thing]:   # noqa: F811
        return base_resolve(service_view(need), offers)    # a digital need is matched like a service
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
    rd_mod = _module("reader")
    if rd_mod is not None and hasattr(rd_mod, "READ_DEPTH"):
        rd_mod.READ_DEPTH.set(depth)    # read tasks created below inherit it: more free tori pages
    if rd_mod is not None and hasattr(rd_mod, "HUNT_LISTINGS"):
        # free marketplace listings for the whole hunt (a generic need reads category pages deep): one shared cap
        rd_mod.HUNT_LISTINGS.set([0, int(rd_mod.HUNT_LISTING_CAP * (1 + 0.5 * (depth - 1)))])
    tokens0 = _tokens_now()            # the shared 10/min bucket as this hunt starts
    trust_mod = _module("trust") if judge is getattr(_module("judge"), "judge", None) else None
    trust_tasks: list[asyncio.Task[Any]] = []

    def prefetch_trust() -> None:
        """Image hashes + WHOIS dates fetched in the background while reads finish, so the final
        judge's own warm-up finds them cached. Offline it does nothing."""
        if trust_mod is None or not hasattr(trust_mod, "prefetch") or not out.offers:
            return
        trust_tasks.append(asyncio.create_task(trust_mod.prefetch(list(out.offers), budget_s=3)))

    # 1 NEED (+ its category: from the tree when the hunt started there, else classified when sure)
    real_parse = parse_need is getattr(_module("need"), "parse_need", None)
    try:
        need = parse_need(text)
    except Exception as exc:
        yield ev("error", where="need", message=str(exc))
        need = _fallback_parse_need(text)
    cat_event: dict[str, Any] | None = None
    need_mod = _module("need")
    if need_mod is not None and hasattr(need_mod, "categorize") and (category or real_parse):
        try:
            cat_event = need_mod.categorize(need, category)
        except Exception as exc:
            yield ev("error", where="category", message=f"{type(exc).__name__}: {exc}"[:300])
    auto_intent = False
    if not intent and not category and real_parse:
        # no meaning picked: a bare vague word ('lunch') takes its likeliest meaning when the literal reading is
        # the wrong KIND of thing (eval r1: 'lunch' hunted fridge magnets and posters, not lunch places)
        intent = auto_intent_for(need)
        auto_intent = intent is not None
    if intent:
        # a meaning picked for vague words (agora.intent: 'lunch' -> lunch places near you): its category, kind,
        # lanes, local words and where-to-look sites replace the literal reading
        try:
            from agora import intent as intent_mod
            ev_i = intent_mod.apply(need, intent)
            if ev_i is not None:
                cat_event = ev_i
                if auto_intent:
                    cat_event["auto"] = True
        except Exception as exc:
            yield ev("error", where="intent", message=f"{type(exc).__name__}: {exc}"[:300])
    where_note = default_where(need) if real_parse or category else None
    out.need = need
    extra_need: dict[str, Any] = {}
    if where_note:
        extra_need["where_default"] = where_note
    if real_parse and (ask := scope_question(need)):
        extra_need["ask_scope"] = ask
    yield ev("need", need=to_dict(need), hunt_id=hunt_id, **extra_need)
    if cat_event is not None:
        yield ev("category", **cat_event)

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
    direct_pages: set[str] = set()     # the marketplaces' own first search pages (discover's direct plan)

    async def timed_read(url: str, fn: Read) -> tuple[Any, float, float]:
        """Run one read with a budget of `limit` seconds of PAGE WORK: time spent queued for the shared
        Context.dev rate limit is added back (up to MAX_QUEUE_ALLOWANCE). Returns (result, limit, queued)."""
        queued = [0.0, 0.0]
        waited = getattr(cd, "queued_seconds", lambda q: q[0])
        if url in direct_pages:
            # the planned marketplace page (nettiauto for a car) is the lane's main source: it keeps the full
            # read time even on a domain that timed out before (eval r2: 'timeout after 5s (known slow domain)')
            limit, wall = read_timeout, None
        else:
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
        if (offer is not None and why in ("jsonld", "snippet_rate", "plain_split")) \
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
        if prio is not None and abroad_last(url):
            prio += FOREIGN_PRIO      # bulky, searched at home: the home shops get the paid reads first
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
            was_slow = slow.is_slow(_domain(url)) and url not in direct_pages
            limit = read_timeout if url in direct_pages else slow.timeout_for(_domain(url), read_timeout)
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
        t_now = time.monotonic()
        if len(out.offers) > 40 and t_now - latest.get("t", 0.0) < max(1.0, 3 * latest.get("cost", 0.0)) \
                and "v" in latest:
            now, twins = None, latest.get("twins")          # re-judged under a second ago: reuse it
        else:
            now, twins = snapshot(need, out.offers, resolve, judge)
            latest["t"] = t_now
            latest["cost"] = time.monotonic() - t_now
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
        # a deeper hunt runs longer, so the shared bucket refills ~2 tokens per extra 12 s
        disc_kw["tokens"] = tokens0 - sib_tokens + (2.0 * (depth - 1) if depth > 1 else 0.0)
    if depth > 1 and _accepts(discover, "pages"):
        disc_kw["pages"] = depth

    scope_now: dict[str, Any] = {}

    def abroad_last(url: str) -> bool:
        """A page from abroad in a hunt scoped to the home country (a sofa, a bike, a car)."""
        if scope_now.get("scope") != "home" or not scope_now.get("country"):
            return False
        fn = getattr(_module("discover"), "home_page", None)
        try:
            return fn is not None and not fn(url, str(scope_now["country"]).lower())
        except Exception:
            return False

    async def produce() -> None:
        try:
            async for e in discover(need, **disc_kw):
                if e.type == "scope":
                    scope_now.update(e.data)
                if e.type == "source":
                    url = str(e.data.get("url") or "")
                    if not url or url in seen:
                        continue
                    if len(seen) >= max_sources:
                        continue
                    seen.add(url)
                    lane_of[url] = str(e.data.get("lane") or "")
                    if e.data.get("direct") and e.data.get("page", 1) in (1, None):
                        direct_pages.add(url)
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

    # 2b LONG TAIL (agora.longtail): providers no registry lists (designjoy.co & co). Its own small paid share
    # (<= 3 Context.dev requests, only while the shared bucket has spare tokens), inside the hunt deadline; its
    # offers go through accept() like any read, so after the provisional verdict they arrive as `late`.
    lt_mod = _module("longtail") if longtail and discover is getattr(_module("discover"), "discover", None) else None
    if lt_mod is not None and hasattr(lt_mod, "LISTICLES"):
        lt_mod.LISTICLES.set([])        # discover hands the 'best X' articles it skips to the lane

    async def longtail_lane() -> None:
        try:
            async for item in lt_mod.lane(need, deadline=deadline, seen_urls=seen):
                if isinstance(item, Offer):
                    await accept(item.url, item)
                else:
                    item.t_ms = int((time.monotonic() - t0) * 1000)
                    out.events.append(item)
                    await queue.put(item)
        except Exception as exc:
            await queue.put(ev("error", where="longtail", message=f"{type(exc).__name__}: {exc}"[:300]))

    producer = asyncio.create_task(produce())
    if lt_mod is not None and hasattr(lt_mod, "lane"):
        reads.add(asyncio.create_task(longtail_lane()))
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

    rd = _module("reader")
    if rd is not None and getattr(rd, "market_for", None) is not None:
        try:
            body = rd.market_for(seen)
        except Exception:
            body = None
        scope = next((e.data for e in out.events if e.type == "scope"), None)
        if body and (body["sources"] or scope):
            yield ev("market", **body, scope=scope)

    # 4 RESOLVE (the optional model relevance check runs first: one batched call, <=2.5 s, never raises)
    rel_mod = _module("relevance")
    if rel_mod is not None:
        try:
            await rel_mod.prefetch(service_view(need), out.offers)
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
                reason = explain(service_view(need), o)[1] or reason
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
    def judge_all() -> Verdict:
        if depreciation is not None and "depreciation" in inspect.signature(judge).parameters:
            return judge(need, things, depreciation=depreciation)  # type: ignore[call-arg]
        return judge(need, things)

    judged = False
    try:
        verdict = judge_all()
        judged = True
    except Exception as exc:
        yield ev("error", where="judge", message=f"{type(exc).__name__}: {exc}"[:300])
        verdict = _fallback_judge(need, things)
    # 5b CHECK THE PICK: the top marketplace candidates' own pages (free fetch), description scanned for red flags
    if judged and check_pick and not is_service(need):
        try:
            verdict, checks = await verify_pick(need, things, verdict, judge_all)
        except Exception as exc:
            checks = []
            yield ev("error", where="pick_check", message=f"{type(exc).__name__}: {exc}"[:300])
        for c in checks:
            yield ev("pick_check", **c)
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


# ---------- pick check: read the would-be pick's own page before the verdict is final ----------

PICK_CHECK_K = 3            # candidates checked per round (cheapest all-in first)
PICK_CHECK_ROUNDS = 2       # a failed round re-judges and checks the next candidates once more
PICK_CHECK_BUDGET_S = 6.0   # wall clock for all rounds; a page that is not back in time is simply not checked


async def verify_pick(need: Need, things: list[Thing], verdict: Verdict, rejudge: Callable[[], Verdict], *,
                      check: Callable[[str, Need], Awaitable[dict[str, Any]]] | None = None,
                      k: int = PICK_CHECK_K, rounds: int = PICK_CHECK_ROUNDS,
                      budget_s: float = PICK_CHECK_BUDGET_S) -> tuple[Verdict, list[dict[str, Any]]]:
    """Free-fetch the top `k` marketplace candidates (the pick first) and scan each seller's description for red
    flags (reader.check_listing). A candidate that fails gets raw['page_red_flags'] (judge: a 'red flag' = never
    the pick, plus a 'skipped ...' verdict line) and the hunt is re-judged, then the next candidates are checked.
    Returns (verdict, [{url, source, price_eur, title, ok, flags, description}])."""
    jm, rd = _module("judge"), _module("reader")
    check = check or getattr(rd, "check_listing", None)
    if jm is None or check is None or not hasattr(jm, "pick_candidates"):
        return verdict, []
    end = time.monotonic() + budget_s
    checked: set[str] = set()
    results: list[dict[str, Any]] = []
    for _ in range(max(1, rounds)):
        by_url = {o.url: o for t in things for o in t.offers}
        cands = ([by_url[verdict.best_offer_url]] if verdict.best_offer_url in by_url else []) + jm.pick_candidates(things, k)
        todo: list[Offer] = []
        for o in cands:
            if o.url not in checked and jm.is_marketplace(o) and all(o is not x for x in todo):
                todo.append(o)
        todo = todo[:k]
        left = end - time.monotonic()
        if not todo or left <= 0.3:
            break
        tasks = {asyncio.create_task(check(o.url, need)): o for o in todo}
        done, pending = await asyncio.wait(tasks, timeout=left)
        for t in pending:
            t.cancel()
        failed = False
        for task, o in tasks.items():
            checked.add(o.url)
            r = task.result() if task in done and not task.cancelled() and task.exception() is None else \
                {"ok": None, "flags": [], "description": ""}
            o.raw["page_check"] = {"ok": r.get("ok"), "flags": r.get("flags") or []}
            results.append({"url": o.url, "source": o.source, "price_eur": o.price_eur, "title": o.title,
                            "ok": r.get("ok"), "flags": r.get("flags") or [],
                            "description": (r.get("description") or "")[:200]})
            if r.get("ok") is False and r.get("flags"):
                o.raw["page_red_flags"] = [list(f) for f in r["flags"]]
                failed = True
        if not failed:
            break
        verdict = rejudge()
    return verdict, results


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
