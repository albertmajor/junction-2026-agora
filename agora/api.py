"""HTTP door: FastAPI app. `uvicorn agora.api:app --reload`

GET /hunt?q=...  streams Server-Sent Events, one JSON Event per message:
    data: {"type": "offer", "data": {...}, "t_ms": 1234}
A browser can just do `new EventSource("/hunt?q=...")` and switch on `JSON.parse(e.data).type`.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import os
import pathlib
import re
import time
from urllib.parse import urlparse
from collections.abc import AsyncIterator
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agora import hunt as hunt_mod
from agora.models import Event, to_dict

@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """On start: release the stage demo agent's leftover leases (a killed server or crashed run must not
    leave 'demo-agent' at the 20-live-lease cap, which would break /demo/buy)."""
    try:
        from agora import demo_buy, lease
        lease.release_client(demo_buy.DEMO_CLIENT)
    except Exception:
        pass
    yield


app = FastAPI(title="Agora", version="0.1.0", lifespan=_lifespan,
              description="One search box for everything you can buy. True cost, live watchers, agent door.")


def _allowed_origins() -> list[str]:
    """The viewer's own origin(s). AGORA_BASE_URL plus AGORA_ALLOWED_ORIGINS (comma separated)."""
    out = {o.rstrip("/") for o in os.environ.get("AGORA_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    if base := os.environ.get("AGORA_BASE_URL"):
        u = urlparse(base)
        out.add(f"{u.scheme}://{u.netloc}")
    return sorted(out)


# No wildcard: other web pages may not read our answers. Same-origin requests need no CORS at all.
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins(), allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["content-type", "x-agora-token", "x-lease-token"])

_STATE_PATHS = ("/demo/", "/mockshop/", "/watches", "/arm", "/buy", "/share", "/leases", "/hooks/")


def _changes_state(request: Request) -> bool:
    path = request.url.path
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return path.startswith("/demo/")       # the demo stories run on GET (EventSource) and buy things
    return path.startswith(_STATE_PATHS)


def _same_origin(request: Request, origin: str) -> bool:
    o = urlparse(origin)
    host = request.headers.get("host", "")
    return o.netloc == host or origin.rstrip("/") in _allowed_origins()


@app.middleware("http")
async def guard_state_changes(request: Request, call_next: Any) -> Any:
    """A web page open in the presenter's browser must not be able to arm an auto-buy, move a shop
    price or run a demo against this server. Browsers always send Origin on cross-site POSTs and on
    EventSource: refuse a foreign one. With AGORA_DEMO_TOKEN set, state changes also need the header
    x-agora-token (curl / agents), except from the viewer itself (same origin)."""
    if _changes_state(request):
        origin = request.headers.get("origin")
        if origin and origin != "null" and not _same_origin(request, origin):
            return Response(f"cross-origin {request.method} refused", status_code=403)
        if origin == "null":
            return Response("opaque origin refused", status_code=403)
        token = os.environ.get("AGORA_DEMO_TOKEN")
        if token and not request.url.path.startswith("/hooks/") and not origin \
                and request.headers.get("x-agora-token") != token:
            return Response("x-agora-token required", status_code=401)
    return await call_next(request)

@app.middleware("http")
async def _no_stale_ui(request: Request, call_next):
    """Browsers revalidate UI files every load, so a changed JS file is never served stale."""
    resp = await call_next(request)
    p = request.url.path
    if p.startswith(("/web/", "/static/")) and not p.startswith("/web/assets/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


STATIC = pathlib.Path(__file__).resolve().parent / "static"   # the old lab viewer, served at /lab
WEB = pathlib.Path(__file__).resolve().parent / "web"         # the new viewer ("the line"), served at /
if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
if WEB.is_dir():
    app.mount("/web", StaticFiles(directory=WEB), name="web")


def _module(name: str) -> Any | None:
    try:
        return importlib.import_module(f"agora.{name}")
    except ImportError:
        return None


def _fn(module: str, *names: str) -> Any:
    mod = _module(module)
    for n in names:
        f = getattr(mod, n, None)
        if callable(f):
            return f
    raise HTTPException(503, f"agora.{module} does not provide {' / '.join(names)} yet")


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        res = await res
    return to_dict(res)


def sse(event: Any) -> str:
    """One Event -> one SSE message."""
    return f"data: {json.dumps(to_dict(event), default=str, ensure_ascii=False)}\n\n"


# ---------- viewer + index ----------

def _wants_html(request: Request) -> bool:
    """Browsers ask for text/html; curl, TestClient and agents get the JSON index (same as /api)."""
    return "text/html" in request.headers.get("accept", "")


def _page(page: pathlib.Path) -> Response:
    if not page.is_file():
        raise HTTPException(503, f"viewer not built ({page.relative_to(page.parents[2])} missing)")
    return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-cache"})


def _viewer() -> Response:
    """The old lab viewer (dark, every panel open)."""
    return _page(STATIC / "index.html")


@app.get("/", response_model=None)
def index(request: Request) -> Any:
    """The new viewer for browsers; the JSON endpoint index for everyone else."""
    return _page(WEB / "index.html") if _wants_html(request) else api_index()


@app.get("/lab", response_model=None)
def lab() -> Response:
    return _viewer()


@app.get("/viewer", response_model=None)
def viewer() -> Response:
    return _viewer()


@app.get("/status")
def status() -> dict[str, Any]:
    """Can this server run live hunts? (key present and not AGORA_OFFLINE)."""
    from agora import contextdev
    try:
        has_key = bool(contextdev._key())
    except Exception:
        has_key = False
    return {"live": has_key and not contextdev.offline()}


@app.get("/api")
def api_index() -> dict[str, Any]:
    return {
        "name": "agora",
        "endpoints": {
            "GET /hunt?q=&replay=<slug>&speed=2": "replay a recorded hunt at its real pace (no credits)",
            "GET /recordings": "slugs of recorded hunts",
            "GET /reviews?hunt_id=&domains=": "SSE: seller reviews after a hunt (review events, then done)",
            "GET|POST /demo/story/refusal?pause=1.5": "SSE: watcher skips, buys, refuses a hidden fee, catches a tampered log",
            "GET|POST /demo/buy?pause=1.2": "SSE: lie detector, haggle counter-offer, auto-buy under open->closed mandates, proof",
            "GET /hunt?q=": "SSE stream of hunt Events (optional &max_sources=N caps pages read) (need, lane, source, offer, skip, thing, truecost, verdict, budget, done, error)",
            "POST /watches": "create a watch {query|need, max_eur|max_price_eur, rule, action, mandate, pinned_urls, use_hunt}",
            "GET /watches": "list watches",
            "POST /watches/{id}/check": "run a watch check now",
            "GET /watches/{id}/proof": "signed mandate + hash-chained decision log (tamper-evident)",
            "POST /arm": "arm watches at each losing offer's price-to-beat {query, action, create}",
            "POST /hooks/contextdev": "Context.dev monitor webhook",
            "GET /things/{id}/history": "price history snapshots for a thing",
            "GET /history?url=": "price history snapshots for one offer URL",
            "GET /ledger": "Context.dev credit ledger",
            "/mockshop/*": "demo shop for auto-buy (if mounted)",
            "GET /": "browser viewer (Accept: text/html), else this index; also GET /api",
            "GET /lab": "the lab viewer (every panel open; also GET /viewer)",
            "GET /cut?u=": "photo cutout of an offer image (if mounted)",
            "POST /share": "share a hunt {query, sharer} -> {id, url}",
            "GET /s/{id}": "open the viewer on a shared hunt",
            "GET /share/{id}": "a share + its attributed clicks",
            "GET /go/{share_id}/{offer_token}": "log a click (attributed to the sharer) and redirect; "
                                                 "offer_token = url-safe base64 of the offer URL, no padding",
            "POST /buy": "agent-door buy by offer id {offer_id, watch_id?, hunt_id?} (provenance-gated)",
            "POST /watches/{id}/leases": "subscribe a callback to watch.match / price.drop (signed webhooks)",
            "GET /leases": "list leases (secrets never listed)",
            "DELETE /leases/{id}": "revoke a lease",
            "GET /leases/{id}/deliveries": "delivery log of a lease",
            "GET /docs": "OpenAPI UI",
        },
        "mockshop": _mockshop_mounted,
    }


# ---------- hunt ----------

@app.get("/hunt")
async def hunt_stream(request: Request, q: str = Query(..., min_length=2, description="what you want"),
                      max_sources: int | None = Query(None, ge=1, le=60, description="cap pages read (credits)"),
                      replay: str | None = Query(None, description="stream a recorded hunt instead "
                                                 "(slug, e.g. sony-a7-iii-body; 'auto' = from q)"),
                      speed: float = Query(1.0, ge=0.25, le=16, description="replay speed (1, 2, 4)"),
                      max_gap: float = Query(0, ge=0, le=60, description="replay: cut idle waits longer than "
                                             "this many seconds (0 = real pace, the honest default)"),
                      ) -> StreamingResponse:
    if replay is not None:
        slug = hunt_mod.slugify(q) if replay in ("", "1", "auto", "true") else replay
        if hunt_mod.recording_path(slug) is None:
            raise HTTPException(404, f"no recording '{slug}' (have: {', '.join(hunt_mod.recordings())})")

    async def gen() -> AsyncIterator[str]:
        yield ": agora hunt\n\n"  # comment line: flushes headers right away
        res = hunt_mod.HuntResult()
        stream = (hunt_mod.replay(slug, speed, max_gap_ms=max_gap * 1000 if max_gap else None) if replay is not None
                  else hunt_mod.hunt(q, result=res, **({"max_sources": max_sources} if max_sources else {})))
        try:
            async for e in stream:
                if await request.is_disconnected():
                    break
                if e.type == "need" and replay is None and res.hunt_id:
                    _remember_hunt(res)      # GET /reviews?hunt_id= reads its offers once it is done
                _cut = _module("cutout")
                if _cut is not None:
                    _cut.remember_event(e)   # live offer photos may be cut out (allowlist guard)
                yield sse(e)
        finally:
            await stream.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- seller reviews (after a hunt) ----------

_HUNTS: dict[str, Any] = {}       # hunt_id -> HuntResult of recent live hunts (for GET /reviews)
_HUNTS_MAX = 24


def _remember_hunt(res: Any) -> None:
    _HUNTS[res.hunt_id] = res
    while len(_HUNTS) > _HUNTS_MAX:
        _HUNTS.pop(next(iter(_HUNTS)))


@app.get("/reviews")
async def reviews_stream(request: Request,
                         hunt_id: str | None = Query(None, max_length=40, description="a live hunt of this server"),
                         domains: str | None = Query(None, max_length=1200,
                                                     description="comma-separated shop hosts, most important first "
                                                                 "(used for replays, or added after the hunt's own)"),
                         paid: bool = Query(True, description="false = free reads and the cache only"),
                         service: bool = Query(False, description="the hosts are service providers"),
                         ) -> StreamingResponse:
    """SSE: seller reviews for a finished hunt. One `review` event per site (checking -> done | none;
    cached sites come straight as done), then `done` {ms, domains, cached, free_pages, paid}. Bounded by
    agora.reviews.PHASE_BUDGET_S. See agora/reviews.py for sources and the negativity-bias correction."""
    from agora import reviews as rv
    targets: list[dict[str, Any]] = []
    res = _HUNTS.get(hunt_id or "")
    if res is not None and res.verdict is not None:
        targets = rv.hunt_targets(res)
    if domains:
        have = {t["domain"] for t in targets}
        hosts = [h.strip().lower() for h in domains.split(",") if h.strip()][:20]
        extra = [t for t in rv.targets_from_hosts(hosts, service=service) if t["domain"] not in have]
        for t in targets:     # the viewer's hosts for a domain we already target ride along
            t["hosts"] = sorted(set(t["hosts"]) | {h for h in hosts if rv.domain_of(h) == t["domain"]})
        targets = (targets + extra)[:rv.MAX_DOMAINS]
    if not targets:
        raise HTTPException(404, "nothing to check: unknown hunt_id and no domains")

    async def gen() -> AsyncIterator[str]:
        yield ": agora reviews\n\n"
        t0 = time.monotonic()
        stats: dict[str, Any] = {}
        stream = rv.run(targets, paid=paid, stats=stats)
        try:
            async for body in stream:
                if await request.is_disconnected():
                    break
                yield sse(Event("review", body, int((time.monotonic() - t0) * 1000)))
        finally:
            await stream.aclose()
        yield sse(Event("done", {"ms": int((time.monotonic() - t0) * 1000), **stats},
                        int((time.monotonic() - t0) * 1000)))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/recordings")
def recordings() -> dict[str, Any]:
    return {"recordings": hunt_mod.recordings()}


# ---------- scripted demo stories ----------

@app.api_route("/demo/story/{name}", methods=["GET", "POST"])
async def demo_story(request: Request, name: str,
                     pause: float = Query(1.5, ge=0, le=10, description="seconds between steps"),
                     beat: float = Query(771.0, gt=0, description="price to beat (EUR) for the first watch"),
                     ) -> StreamingResponse:
    """SSE stream of a scripted watcher story on the mock shop (story, watch, proof, done events).
    `refusal`: no action at €980 -> auto-buy at €760 -> refuse a hidden checkout fee -> tamper is caught."""
    story = _module("story")
    if story is None or name not in getattr(story, "STORIES", {}):
        raise HTTPException(404, f"no story '{name}'")

    async def gen() -> AsyncIterator[str]:
        yield ": agora story\n\n"
        stream = story.run_story(name, pause=pause, beat_eur=beat)
        try:
            async for e in stream:
                if await request.is_disconnected():
                    break
                yield sse(e)
        finally:
            await stream.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.api_route("/demo/buy", methods=["GET", "POST"])
async def demo_buy_story(request: Request,
                         pause: float = Query(1.2, ge=0, le=10, description="seconds between beats"),
                         variant: Literal["new", "used"] = Query("new", description="new: the recorded new body; used: the hunt's tori.fi pick"),
                         target: float | None = Query(None, ge=1, le=100000, description="your price (used variant)")) -> StreamingResponse:
    """SSE of the offline buy story (agora/demo_buy.py) on the mock shop: arm an OPEN mandate + a signed
    webhook lease -> the lie detector skips a 'sold out' page -> €1,099 declined, intent trace sent ->
    the shop counters at €1,028 -> auto-buy under a CLOSED mandate -> proof. Events: `story`
    {step, title, text}, `proof` {chain_ok, signature_ok, mandate_chain_ok, rows, purchases, head}, `done` {watch_id}."""
    demo = _module("demo_buy")
    if demo is None:
        raise HTTPException(503, "agora.demo_buy is not available")

    async def gen() -> AsyncIterator[str]:
        yield ": agora demo buy\n\n"
        # one story at a time: the mock shop is shared state (run_demo resets it), so a second viewer
        # waits for the first night to finish instead of wiping it mid-story
        while True:
            try:
                await asyncio.wait_for(_DEMO_LOCK.acquire(), timeout=1.0)
                break
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": waiting\n\n"
        try:
            async for chunk in _demo_story(request, demo, pause, variant, target):
                yield chunk
        finally:
            _DEMO_LOCK.release()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


_DEMO_LOCK = asyncio.Lock()


async def _demo_story(request: Request, demo: Any, pause: float, variant: str,
                      target: float | None) -> AsyncIterator[str]:
    lines: asyncio.Queue[str] = asyncio.Queue()
    kw: dict[str, Any] = {}
    if variant != "new":
        kw["variant"] = variant
    if target is not None:
        kw["target"] = target
    task = asyncio.create_task(demo.run_demo(out=lines.put_nowait, pause=pause, **kw))
    step, title = 0, ""
    t0 = time.monotonic()
    detail = set(getattr(demo, "DETAIL_KINDS", ()))

    def ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    try:
        while not (task.done() and lines.empty()):
            try:
                line = await asyncio.wait_for(lines.get(), timeout=0.25)
            except TimeoutError:
                continue
            if await request.is_disconnected():
                task.cancel()
                return
            head = re.match(r"^(\d+)\s+(.*)$", line)
            if head:
                step, title = int(head.group(1)), head.group(2)
                yield sse(Event("story", {"step": step, "title": title, "text": ""}, ms()))
                continue
            kind, _, text = line.strip().partition(" ")
            yield sse(Event("story", {"step": step, "title": kind, "text": text.strip(), "beat": title,
                                      "detail": kind in detail}, ms()))
        res = task.result()
    except Exception as exc:
        yield sse(Event("error", {"where": "demo_buy", "message": f"{type(exc).__name__}: {exc}"[:300]}))
        return
    finally:
        if not task.done():
            task.cancel()
    p = to_dict(_fn("proof", "watch_proof")(res["watch_id"])) or {}
    yield sse(Event("proof", {"watch_id": res["watch_id"], "chain_ok": p.get("chain_ok"),
                              "receipt": next(iter(p.get("purchases") or []), None),
                              "signature_ok": p.get("signature_ok"),
                              "first_broken_index": p.get("first_broken_index"),
                              "mandate_chain_ok": (p.get("mandate_chain") or {}).get("ok"),
                              "rows": len(p.get("chain") or []), "purchases": len(p.get("purchases") or []),
                              "head": p.get("head")}, ms()))
    yield sse(Event("done", {"watch_id": res["watch_id"], "status": res.get("status"),
                             "paid_eur": res.get("paid_eur"), "counter_offer": res.get("counter_offer")}, ms()))


@app.post("/demo/tamper")
async def demo_tamper(body: dict[str, Any] = Body(...)) -> Any:
    """Stage demo: rewrite ONE stored decision of a watch behind the agent's back (the paid line, by
    default), then return the proof. The hash chain shows exactly where the log was changed."""
    wid = str(body.get("watch_id") or "")
    store = _module("store")
    rows = store.decisions(wid, limit=10_000) if store else []
    if not rows:
        raise HTTPException(404, f"no decisions for watch {wid!r}")
    idx = body.get("index")
    if idx is None:
        idx = next((i for i, r in enumerate(rows) if r.get("outcome") == "mandate"), len(rows) - 1)
    idx = int(idx)
    if not 0 <= idx < len(rows):
        raise HTTPException(422, f"index must be 0..{len(rows) - 1}")
    reason = re.sub(r"€(\d[\d,]*)", lambda m: "€" + format(max(1, int(m.group(1).replace(",", "")) - 100), ","),
                    rows[idx].get("reason") or "", count=1)
    if reason == rows[idx].get("reason"):
        reason = (reason or "") + " (edited)"
    _fn("story", "tamper")(wid, idx, reason)
    p = to_dict(_fn("proof", "watch_proof")(wid)) or {}
    return {"watch_id": wid, "index": idx, "was": rows[idx].get("reason"), "now": reason,
            "chain_ok": p.get("chain_ok"), "first_broken_index": p.get("first_broken_index"),
            "rows": len(p.get("chain") or []), "head": p.get("head")}


# ---------- watches ----------

@app.post("/watches")
async def create_watch(body: dict[str, Any] = Body(...)) -> Any:
    fn = _fn("watch", "create_watch")
    body = dict(body)
    # friendly aliases (what the index advertises) -> watch.create_watch parameter names
    if "query" in body and "need" not in body:
        body["need"] = body.pop("query")
    if "max_eur" in body and "max_price_eur" not in body:
        body["max_price_eur"] = body.pop("max_eur")
    try:
        return await _call(fn, **body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/watches")
async def list_watches() -> Any:
    try:
        fn = _fn("watch", "list_watches", "all_watches")
    except HTTPException:
        fn = _fn("store", "list_watches", "get_watches")
    return await _call(fn)


@app.post("/watches/{watch_id}/check")
async def check_watch(watch_id: str) -> Any:
    fn = _fn("watch", "check_watch")
    wid: Any = int(watch_id) if watch_id.isdigit() else watch_id
    events = await _call(fn, wid)
    return {"watch_id": watch_id, "events": events}


@app.get("/watches/{watch_id}/proof")
async def watch_proof(watch_id: str) -> Any:
    """Signed mandate + hash-chained decision log: {mandate, signature_ok, chain, chain_ok}."""
    res = _fn("proof", "watch_proof")(watch_id)
    if res is None:
        raise HTTPException(404, f"no watch {watch_id}")
    return to_dict(res)


@app.post("/arm")
async def arm(body: dict[str, Any] = Body(...)) -> Any:
    """Turn a hunt into standing orders: one watch per losing offer at its price-to-beat.
    Body: {query, action?: notify|one_tap, create?: bool (default false = only suggest)}."""
    query = str(body.get("query") or "").strip()
    if len(query) < 2:
        raise HTTPException(422, "query required")
    fn = _fn("mcp_server", "arm_watches")
    return await _call(fn, query, action=body.get("action", "notify"), create=bool(body.get("create", False)))


HOOK_MIN_INTERVAL_S = 60.0
_hook_last: dict[str, float] = {}


def _hook_signature_ok(request: Request, raw: bytes) -> bool:
    """With CONTEXT_DEV_WEBHOOK_SECRET set (a Standard Webhooks whsec_ secret), require a valid signature."""
    secret = os.environ.get("CONTEXT_DEV_WEBHOOK_SECRET")
    if not secret:
        return True
    from agora import lease
    try:
        return lease.verify(secret, request.headers, raw)
    except Exception:
        return False


@app.post("/hooks/contextdev")
async def contextdev_hook(request: Request) -> Any:
    """Context.dev monitor webhook. Unsigned hooks (no secret configured) are rate-limited per
    monitor/URL, because each one can start fresh page reads on the shared credit budget."""
    raw = await request.body()
    if not _hook_signature_ok(request, raw):
        raise HTTPException(401, "webhook signature invalid")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(422, "body must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "body must be a JSON object")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    key = str(payload.get("monitor_id") or data.get("monitor_id") or payload.get("url") or data.get("url") or "?")
    now = time.monotonic()
    if now - _hook_last.get(key, -1e9) < HOOK_MIN_INTERVAL_S:
        return {"ok": True, "throttled": True, "retry_after_s": round(HOOK_MIN_INTERVAL_S - (now - _hook_last[key]))}
    _hook_last[key] = now
    fn = _fn("watch", "handle_webhook", "handle_monitor_webhook")
    delivery = request.headers.get("webhook-id") or request.headers.get("x-delivery-id")
    kwargs = {"delivery_id": delivery} if "delivery_id" in inspect.signature(fn).parameters else {}
    return {"ok": True, "result": await _call(fn, payload, **kwargs)}


# ---------- history / ledger ----------

@app.get("/history")
async def url_history(url: str = Query(...)) -> Any:
    return {"url": url, "history": await _call(_fn("store", "history"), url)}


@app.get("/things/{thing_id}/history")
async def thing_history(thing_id: str) -> Any:
    """Snapshots of every offer URL that resolved to this thing, grouped by URL."""
    store = _module("store")
    if callable(getattr(store, "thing_history", None)):
        return {"thing_id": thing_id, "history": await _call(store.thing_history, thing_id)}
    hist = _fn("store", "history")
    urls = sorted(hunt_mod.THING_URLS.get(thing_id, set()))
    if not urls:
        raise HTTPException(404, f"no offers known for thing {thing_id} (run a hunt first)")
    return {"thing_id": thing_id, "history": {u: hist(u) for u in urls}}


@app.get("/ledger")
async def ledger() -> Any:
    return await _call(_fn("contextdev", "ledger"))


@app.post("/buy")
async def buy_by_id(body: dict[str, Any] = Body(...)) -> Any:
    """Agent door: buy an offer Agora itself read, by id. Price and URL come from our stored row;
    with a watch the mandate decides (auto-buy / one-tap), without one it is a one-tap link."""
    offer_id = str(body.get("offer_id") or "").strip()
    if not offer_id:
        raise HTTPException(422, "offer_id required")
    fn = _fn("buy", "buy_offer")
    return await _call(fn, offer_id, watch_id=body.get("watch_id"), hunt_id=body.get("hunt_id"))


# ---------- share a hunt (attributed outbound clicks) ----------

@app.post("/share")
def create_share(request: Request, body: dict[str, Any] = Body(...)) -> Any:
    share = _module("share")
    try:
        res = share.create_share(str(body.get("query") or ""), body.get("sharer"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return res | {"path": f"/s/{res['id']}", "url": str(request.base_url).rstrip("/") + f"/s/{res['id']}"}


@app.get("/share/{share_id}")
def share_stats(share_id: str) -> Any:
    res = _module("share").stats(share_id)
    if res is None:
        raise HTTPException(404, f"no share {share_id}")
    return res


@app.get("/s/{share_id}")
def open_share(share_id: str) -> RedirectResponse:
    s = _module("share").get_share(share_id)
    if s is None:
        raise HTTPException(404, f"no share {share_id}")
    return RedirectResponse("/?" + urlencode({"q": s["query"], "share": s["id"], "by": s["sharer"]}), 302)


def _go(token: str, share_id: str | None) -> RedirectResponse:
    share = _module("share")
    url = share.decode_url(token)
    if url is None:
        raise HTTPException(400, "bad offer link")
    row = share.log_click(url, share_id)
    return RedirectResponse(row["out_url"], 302, headers={"Cache-Control": "no-store",
                                                          "Referrer-Policy": "no-referrer"})


@app.get("/go/{offer_token}")
def go(offer_token: str) -> RedirectResponse:
    return _go(offer_token, None)


@app.get("/go/{share_id}/{offer_token}")
def go_shared(share_id: str, offer_token: str) -> RedirectResponse:
    return _go(offer_token, None if share_id in ("-", "_") else share_id)


# ---------- optional routers from sibling modules ----------

def _mount_mockshop() -> bool:
    for name in ("mockshop", "buy"):
        router = getattr(_module(name), "router", None)
        if router is not None:
            prefix = "" if any(getattr(r, "path", "").startswith("/mockshop") for r in router.routes) else "/mockshop"
            app.include_router(router, prefix=prefix)
            return True
    return False


try:
    _mockshop_mounted = _mount_mockshop()
except Exception:  # a broken sibling must never take the API down
    _mockshop_mounted = False

try:
    _lease_router = getattr(_module("lease"), "router", None)
    if _lease_router is not None:
        app.include_router(_lease_router)
except Exception:
    pass

try:  # plain HTTP JSON for agents that don't speak MCP (GET /api/offers, /api/offer, /api/offer/receipt)
    _agent_router = getattr(_module("agent_http"), "router", None)
    if _agent_router is not None:
        app.include_router(_agent_router)
except Exception:
    pass

try:  # photo cutouts (GET /cut); optional, a missing or broken module must not take the API down
    _cutout_router = getattr(_module("cutout"), "router", None)
    if _cutout_router is not None:
        app.include_router(_cutout_router)
except Exception:
    pass
