"""Async Context.dev client for Agora. Written at Junction 2026.

Three things make it safe to share between many agents and processes:
  * a token bucket (10 req/min for the whole account) kept in `.cache/contextdev_bucket.json`
    behind an `fcntl` file lock, so every process on this machine draws from the same bucket;
  * a disk cache in `.cache/contextdev/`, keyed by endpoint + request body, so the same
    question is never paid for twice;
  * a credit ledger fed by `key_metadata.credits_consumed` in every response.

Env:
  CONTEXT_DEV_API_KEY   the key (or in `.env`). Never printed, never logged.
  AGORA_OFFLINE=1       cache only, never touch the network (tests, demos without wifi).
  AGORA_CACHE_DIR       override `.cache/` (tests use a tmp dir).
"""
from __future__ import annotations

import asyncio
import contextvars
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import random
import re
import time
from collections.abc import Iterator
from typing import Any

import httpx

API = "https://api.context.dev/v1"
RATE_PER_MIN = 10            # account-wide limit
BUCKET_SIZE = 10             # burst allowed when the bucket is full
MAX_IN_FLIGHT = 4            # per process
ROOT = pathlib.Path(__file__).resolve().parent.parent

TTL = {"search": 24 * 3600, "product": 6 * 3600, "json": 12 * 3600}

# Tests inject an httpx.MockTransport here. None = real network.
_transport: httpx.AsyncBaseTransport | None = None


class ContextDevError(RuntimeError):
    """Any failure talking to Context.dev. The message never contains the key."""


# --------------------------------------------------------------------------- paths + key

def cache_root() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or ROOT / ".cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def _key() -> str:
    key = os.environ.get("CONTEXT_DEV_API_KEY")
    if key:
        return key.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CONTEXT_DEV_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ContextDevError("CONTEXT_DEV_API_KEY missing (set it in .env)")


# --------------------------------------------------------------------------- shared file state

@contextlib.contextmanager
def _locked_json(name: str, default: dict[str, Any]):
    """Open `.cache/<name>` under an exclusive cross-process lock; yields a dict that is saved back."""
    root = cache_root()
    with open(root / f"{name}.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            path = root / name
            try:
                state = json.loads(path.read_text())
            except (OSError, ValueError):
                state = dict(default)
            yield state
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _take_token(now: float | None = None) -> float:
    """Try to take one token. Returns 0 on success, else seconds to wait before trying again."""
    now = time.time() if now is None else now
    rate = RATE_PER_MIN / 60.0
    with _locked_json("contextdev_bucket.json", {"tokens": BUCKET_SIZE, "ts": now}) as s:
        tokens = min(BUCKET_SIZE, float(s.get("tokens", BUCKET_SIZE)) + (now - float(s.get("ts", now))) * rate)
        s["ts"] = now
        if tokens >= 1:
            s["tokens"] = tokens - 1
            return 0.0
        s["tokens"] = tokens
        return (1 - tokens) / rate


def _drain_bucket(seconds: float) -> None:
    """After a 429, tell every process to back off: empty the bucket (and push it into the future)."""
    rate = RATE_PER_MIN / 60.0
    with _locked_json("contextdev_bucket.json", {}) as s:
        s["tokens"] = -seconds * rate
        s["ts"] = time.time()


async def acquire() -> None:
    """Wait until the shared bucket gives us a request slot."""
    while True:
        wait = await asyncio.to_thread(_take_token)
        if wait <= 0:
            return
        await asyncio.sleep(wait + random.uniform(0.05, 0.4))


# --------------------------------------------------------------------------- ledger

_LEDGER: dict[str, Any] = {}
# Per-hunt counters: hunt() sets a fresh dict here, so two hunts in one process never mix their bills.
HUNT_LEDGER: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("agora_hunt_ledger",
                                                                                  default=None)


# [seconds queued so far, monotonic start of the wait in progress or 0] for the current read task (hunt sets
# a fresh list per read), so a page's timeout measures its own work, not the wait for a rate-limit token.
QUEUED: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar("agora_queued", default=None)


@contextlib.contextmanager
def queueing() -> Iterator[None]:
    """Mark the time inside as 'waiting for the shared limiter' for the current read task."""
    q, t = QUEUED.get(), time.monotonic()
    if q is not None:
        q[1] = t
    try:
        yield
    finally:
        if q is not None:
            q[0] += time.monotonic() - t
            q[1] = 0.0


def queued_seconds(q: list[float]) -> float:
    """Total queued time, including a wait still in progress."""
    return q[0] + (time.monotonic() - q[1] if q[1] else 0.0)


def _bump(key: str, n: float = 1) -> None:
    _LEDGER[key] += n
    if (h := HUNT_LEDGER.get()) is not None:
        h[key] = h.get(key, 0) + n


def _reset_ledger() -> None:
    _LEDGER.clear()
    _LEDGER.update(requests=0, credits_used=0, cache_hits=0, saved_by_free_reads=0,
                   errors=0, credits_remaining=None, by_endpoint={})


_reset_ledger()


def _record(endpoint: str, credits: int, remaining: int | None) -> None:
    _bump("requests")
    _bump("credits_used", credits)
    if remaining is not None:
        _LEDGER["credits_remaining"] = remaining
    ep = _LEDGER["by_endpoint"].setdefault(endpoint, {"requests": 0, "credits": 0})
    ep["requests"] += 1
    ep["credits"] += credits
    with _locked_json("contextdev_ledger.json", {"requests": 0, "credits_used": 0}) as total:
        total["requests"] = total.get("requests", 0) + 1
        total["credits_used"] = total.get("credits_used", 0) + credits
        if remaining is not None:
            total["credits_remaining"] = remaining


def note_free_read() -> None:
    """Reader calls this when a page was read without Context.dev (JSON-LD). Shown as 'saved'."""
    _bump("saved_by_free_reads")


def ledger() -> dict[str, Any]:
    """This process: requests, credits_used, cache_hits, saved_by_free_reads, credits_remaining,
    by_endpoint. `all_time` = every process on this machine (from `.cache/contextdev_ledger.json`)."""
    out = json.loads(json.dumps(_LEDGER))
    try:
        out["all_time"] = json.loads((cache_root() / "contextdev_ledger.json").read_text())
    except (OSError, ValueError):
        out["all_time"] = {}
    return out


# --------------------------------------------------------------------------- disk cache

def _cache_key_body(body: dict[str, Any]) -> dict[str, Any]:
    """The request body without freshness knobs: a fresh read refreshes the normal cache entry."""
    out = {k: v for k, v in body.items() if k != "maxAgeMs"}
    mo = out.get("markdownOptions")
    if isinstance(mo, dict) and "maxAgeMs" in mo:
        mo = {k: v for k, v in mo.items() if k != "maxAgeMs"}
        if mo:
            out["markdownOptions"] = mo
        else:
            out.pop("markdownOptions")
    return out


def _cache_path(endpoint: str, body: dict[str, Any]) -> pathlib.Path:
    blob = json.dumps({"endpoint": endpoint, "body": _cache_key_body(body)}, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(blob.encode()).hexdigest()[:32]
    d = cache_root() / "contextdev"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def _cache_get(path: pathlib.Path, max_age_s: float | None) -> dict[str, Any] | None:
    try:
        entry = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if max_age_s is not None and time.time() - entry.get("saved_at", 0) > max_age_s and not offline():
        return None   # offline: stale beats nothing
    return entry.get("response")


def _cache_put(path: pathlib.Path, endpoint: str, body: dict[str, Any], resp: dict[str, Any]) -> None:
    entry = {"saved_at": time.time(), "endpoint": endpoint, "body": body, "response": resp}
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False))
    tmp.replace(path)


# --------------------------------------------------------------------------- transport

_sems: dict[int, asyncio.Semaphore] = {}


def _sem() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _sems:
        _sems[loop_id] = asyncio.Semaphore(MAX_IN_FLIGHT)
    return _sems[loop_id]


def _credits(resp: dict[str, Any], headers: httpx.Headers) -> tuple[int, int | None]:
    meta = resp.get("key_metadata") or {}
    used = meta.get("credits_consumed")
    if used is None:
        try:
            used = int(headers.get("x-credits-used", 0))
        except ValueError:
            used = 0
    return int(used or 0), meta.get("credits_remaining")


async def _send(method: str, path: str, body: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    """One live call: limiter, retries on 429/5xx, ledger. No cache here."""
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    sem = _sem()
    with queueing():
        await sem.acquire()
    try:
        for attempt in range(4):
            with queueing():
                await acquire()
            try:
                async with httpx.AsyncClient(transport=_transport, timeout=timeout) as client:
                    r = await client.request(method, API + path, json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                _LEDGER["errors"] += 1
                raise ContextDevError(f"{path}: network error {type(e).__name__}") from None
            if r.status_code == 429:
                wait = float(r.headers.get("retry-after") or 10 * (attempt + 1))
                await asyncio.to_thread(_drain_bucket, wait)
                continue
            if r.status_code >= 500 and attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                _LEDGER["errors"] += 1
                raise ContextDevError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
            data = r.json() if r.content else {}
            used, remaining = _credits(data, r.headers)
            await asyncio.to_thread(_record, path.strip("/").split("/")[-1] or path, used, remaining)
            return data
    finally:
        sem.release()
    _LEDGER["errors"] += 1
    raise ContextDevError(f"{path}: still rate limited after retries")


async def _post(path: str, body: dict[str, Any], *, kind: str, fresh: bool = False,
                max_age_s: float | None = None, timeout: float = 90) -> dict[str, Any]:
    """Cached POST. `kind` picks the TTL. `fresh=True` skips the cache read (still writes).
    `max_age_s` tightens our own TTL (never loosens it)."""
    cpath = _cache_path(path, body)
    if not fresh:
        ttl = TTL.get(kind)
        if max_age_s is not None:
            ttl = max_age_s if ttl is None else min(ttl, max_age_s)
        hit = _cache_get(cpath, ttl)
        if hit is not None:
            _bump("cache_hits")
            return hit
    if offline():
        raise ContextDevError(f"{path}: offline and not cached")
    resp = await _send("POST", path, body, timeout)
    _cache_put(cpath, path, body, resp)
    return resp


# --------------------------------------------------------------------------- freshness

# Default page age for reads in this context (None = provider + our cache defaults). A watcher recheck
# runs inside `fresh_reads()` so every read it triggers asks for a fresh copy (maxAgeMs 0).
MAX_AGE_MS: contextvars.ContextVar[int | None] = contextvars.ContextVar("agora_max_age_ms", default=None)
MAX_AGE_LIMIT_MS = 365 * 24 * 3600 * 1000      # the API accepts at most 365 days


@contextlib.contextmanager
def fresh_reads(max_age_ms: int = 0) -> Iterator[None]:
    """Inside this block, product/extract/search default to `max_age_ms` (0 = fetch fresh)."""
    tok = MAX_AGE_MS.set(max_age_ms)
    try:
        yield
    finally:
        MAX_AGE_MS.reset(tok)


def _max_age(max_age_ms: int | None, fresh: bool) -> int | None:
    """Explicit argument > fresh=True (0) > the context default. Clamped to what the API accepts."""
    if max_age_ms is None:
        max_age_ms = 0 if fresh else MAX_AGE_MS.get()
    if max_age_ms is None:
        return None
    return max(0, min(int(max_age_ms), MAX_AGE_LIMIT_MS))


def _freshness(max_age_ms: int | None) -> tuple[bool, float | None]:
    """-> (skip our disk cache?, our cache max age in seconds)."""
    if max_age_ms is None:
        return False, None
    return max_age_ms == 0, max_age_ms / 1000


# --------------------------------------------------------------------------- country

# ISO 3166-1 alpha-2 codes the search accepts in lower case ("fi" verified live 2026-11-13, see the cache).
COUNTRY_ALIASES = {
    "uk": "gb", "england": "gb", "britain": "gb", "great britain": "gb", "united kingdom": "gb",
    "finland": "fi", "suomi": "fi", "germany": "de", "deutschland": "de", "sweden": "se", "sverige": "se",
    "norway": "no", "norge": "no", "denmark": "dk", "danmark": "dk", "estonia": "ee", "eesti": "ee",
    "france": "fr", "netherlands": "nl", "holland": "nl", "spain": "es", "españa": "es", "italy": "it",
    "italia": "it", "austria": "at", "österreich": "at", "poland": "pl", "polska": "pl", "belgium": "be",
    "ireland": "ie", "portugal": "pt", "switzerland": "ch", "schweiz": "ch", "czechia": "cz",
    "czech republic": "cz", "greece": "gr", "el": "gr", "latvia": "lv", "lithuania": "lt", "hungary": "hu",
    "romania": "ro", "bulgaria": "bg", "croatia": "hr", "slovakia": "sk", "slovenia": "si",
    "luxembourg": "lu", "iceland": "is", "united states": "us", "usa": "us", "canada": "ca", "japan": "jp",
}


def normalize_country(value: str | None) -> str | None:
    """'FI' / ' fi ' / 'Finland' / 'uk' / 'fi-FI' -> 'fi' / 'gb'. Anything else -> None (send no filter)."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower().replace("_", "-")
    if v in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[v]
    if re.fullmatch(r"[a-z]{2}-[a-z]{2}", v):          # locale: fi-fi, en-gb -> region part
        v = v.split("-")[1]
    if re.fullmatch(r"[a-z]{2}", v):
        return COUNTRY_ALIASES.get(v, v)
    return None


# --------------------------------------------------------------------------- public API

async def search(query: str, n: int = 10, highlights: bool = False, country: str | None = None, *,
                 include_domains: list[str] | None = None, exclude_domains: list[str] | None = None,
                 languages: list[str] | None = None, freshness: str | None = None,
                 highlight_chars: int = 1200, fresh: bool = False,
                 max_age_ms: int | None = None) -> list[dict[str, Any]]:
    """DISCOVER: ranked pages for a query. 1 credit per 10 results (+1 with highlights).

    Each result: {url, title, description, relevance, highlights: {highlights: [...], code}}.
    `country` is an ISO-3166 alpha-2 code ("fi", "de"; names like "Finland" and "uk" are mapped, junk is
    dropped). If the API rejects it, we retry without it.
    `max_age_ms` (0 = fresh) bounds the age of the highlight passages (`markdownOptions.maxAgeMs`) and of
    our own disk cache; the search index itself has no age knob.
    """
    age = _max_age(max_age_ms, fresh)
    skip_cache, cache_age = _freshness(age)
    body: dict[str, Any] = {"query": query[:500], "numResults": max(1, min(int(n), 100))}
    cc = normalize_country(country)
    if cc:
        body["country"] = cc
    if include_domains:
        body["includeDomains"] = include_domains[:100]
    if exclude_domains:
        body["excludeDomains"] = exclude_domains[:100]
    if languages:
        body["languages"] = languages
    if freshness:
        body["freshness"] = freshness
    if highlights:
        body["highlightsOptions"] = {"enabled": True, "maxCharacters": max(100, min(highlight_chars, 20000))}
        if age is not None:
            body["markdownOptions"] = {"maxAgeMs": age}
    try:
        resp = await _post("/web/search", body, kind="search", fresh=skip_cache, max_age_s=cache_age)
    except ContextDevError as e:
        if "HTTP 400" not in str(e) or not ("country" in body or "markdownOptions" in body):
            raise
        # validation errors are free: drop what the API may not support (country first) and retry once
        body.pop("country", None)
        body.pop("markdownOptions", None)
        resp = await _post("/web/search", body, kind="search", fresh=skip_cache, max_age_s=cache_age)
    return list(resp.get("results") or [])


def highlight_text(result: dict[str, Any]) -> str:
    """Joined highlight passages of a search result ('' when none)."""
    h = result.get("highlights") or {}
    items = h.get("highlights") if isinstance(h, dict) else h
    if not items:
        return ""
    return " … ".join(x if isinstance(x, str) else str(x.get("text", "")) for x in items)


async def product(url: str, *, fresh: bool = False, max_age_ms: int | None = None) -> dict[str, Any] | None:
    """READ: product page -> {name, brand, sku, price, regularPrice, currency, availability, images, ...}.
    None when the page is not a product page. ~2 credits. `max_age_ms=0` (or fresh=True) = a fresh scrape,
    past Context.dev's cache and ours."""
    age = _max_age(max_age_ms, fresh)
    skip_cache, cache_age = _freshness(age)
    body: dict[str, Any] = {"url": url, "formats": {"product": True}, "productParams": {"dedupeImages": True}}
    if age is not None:
        body["maxAgeMs"] = age
    resp = await _post("/web/scrape", body, kind="product", fresh=skip_cache, max_age_s=cache_age)
    return parse_product_response(resp)


def parse_product_response(resp: dict[str, Any]) -> dict[str, Any] | None:
    block = resp.get("product") or {}
    data = block.get("data") or {}
    if not data.get("isProductPage"):
        return None
    return data.get("product") or None


async def extract(url: str, schema: dict[str, Any], instructions: str | None = None, *,
                  fresh: bool = False, max_age_ms: int | None = None) -> dict[str, Any] | None:
    """READ: any page -> object following `schema` (a JSON Schema with a top-level object). ~5 credits.
    `max_age_ms=0` (or fresh=True) = a fresh scrape, past Context.dev's cache and ours."""
    age = _max_age(max_age_ms, fresh)
    skip_cache, cache_age = _freshness(age)
    params: dict[str, Any] = {"schema": schema}
    if instructions:
        params["instructions"] = instructions[:2000]
    body: dict[str, Any] = {"url": url, "formats": {"json": True}, "jsonParams": params}
    if age is not None:
        body["maxAgeMs"] = age
    resp = await _post("/web/scrape", body, kind="json", fresh=skip_cache, max_age_s=cache_age)
    block = resp.get("json") or {}
    if block.get("success") is False:
        return None
    data = block.get("data")
    if not (isinstance(data, dict) and data):
        return None
    final = resp.get("url")
    if isinstance(final, str) and final.rstrip("/") != url.rstrip("/"):
        data = {**data, "_final_url": final}   # the page redirected: callers dedupe on this
    return data


async def create_monitor(name: str, *, url: str | None = None, query: str | None = None,
                         instructions: str | None = None, webhook: str | None = None,
                         every_hours: int = 24, tags: list[str] | None = None) -> dict[str, Any]:
    """WATCH: a page monitor (url [+ semantic instructions]) or a search monitor (query).
    Returns the monitor object incl. `id` and `webhook.secret`. Never cached."""
    if not (url or query):
        raise ValueError("create_monitor needs url or query")
    target: dict[str, Any] = {"type": "page", "url": url} if url else {"type": "search", "query": query}
    if instructions:
        target["instructions"] = instructions
    body: dict[str, Any] = {"name": name[:200], "target": target,
                            "schedule": {"type": "interval", "frequency": every_hours, "unit": "hours"}}
    if webhook:
        body["webhook"] = {"url": webhook, "retry": {}}
    if tags:
        body["tags"] = tags[:20]
    if offline():
        raise ContextDevError("/monitors: offline")
    return await _send("POST", "/monitors", body, timeout=60)


async def delete_monitor(monitor_id: str) -> None:
    if offline():
        raise ContextDevError("/monitors: offline")
    await _send("DELETE", f"/monitors/{monitor_id}", None, timeout=30)


if __name__ == "__main__":   # tiny smoke test: python -m agora.contextdev "query"  (1 live credit)
    import sys

    async def _main() -> None:
        for r in await search(" ".join(sys.argv[1:]) or "Sony A7 III body price", 5):
            print(r.get("relevance"), r["url"])
        print({k: v for k, v in ledger().items() if k != "all_time"})

    asyncio.run(_main())
