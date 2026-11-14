"""Exa client: the LOOK-ALIKE lane. Once a hunt finds a good EU shop, ask Exa for pages like it,
which surfaces small EU dealers that keyword search misses.

Small async httpx client for POST https://api.exa.ai/search and /findSimilar.
- No EXA_API_KEY: every call returns [] (the hunt simply has no look-alike lane).
- Disk cache in `.cache/exa/` keyed by request body; AGORA_OFFLINE=1 reads only the cache.
Tests inject `_transport` (httpx.MockTransport).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from typing import Any

import httpx

BASE = "https://api.exa.ai"
TTL_S = 6 * 3600
TIMEOUT = 20.0
_transport: httpx.AsyncBaseTransport | None = None


def _key() -> str | None:
    key = os.environ.get("EXA_API_KEY")
    if key:
        return key
    env = pathlib.Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in env.read_text().splitlines():
            if line.startswith("EXA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"') or None
    except OSError:
        pass
    return None


def _offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def _cache_dir() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or pathlib.Path(__file__).resolve().parent.parent / ".cache")
    return root / "exa"


def _cache_path(path: str, body: dict[str, Any]) -> pathlib.Path:
    h = hashlib.sha256((path + json.dumps(body, sort_keys=True)).encode()).hexdigest()[:32]
    return _cache_dir() / f"{h}.json"


def enabled() -> bool:
    """True when a call could return something (a key, or offline with a cache to replay)."""
    return bool(_key()) or (_offline() and _cache_dir().exists())


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    cpath = _cache_path(path, body)
    try:
        hit = json.loads(cpath.read_text())
        if _offline() or time.time() - hit.get("saved_at", 0) < TTL_S:
            return hit["response"]
    except (OSError, ValueError, KeyError):
        pass
    key = _key()
    if _offline() or not key:
        return {}
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT) as c:
            r = await c.post(BASE + path, json=body, headers={"x-api-key": key, "content-type": "application/json"})
            r.raise_for_status()
            resp = r.json()
    except (httpx.HTTPError, ValueError):
        return {}
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps({"saved_at": time.time(), "path": path, "body": body, "response": resp}))
    return resp


def _results(resp: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in resp.get("results") or []:
        if isinstance(r, dict) and str(r.get("url", "")).startswith("http"):
            out.append({"url": r["url"], "title": r.get("title") or "", "score": r.get("score"),
                        "published": r.get("publishedDate")})
    return out


async def search(query: str, n: int = 10, *, exclude_domains: list[str] | None = None,
                 category: str | None = None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"query": query[:500], "numResults": max(1, min(n, 25)), "type": "auto"}
    if exclude_domains:
        body["excludeDomains"] = sorted(set(exclude_domains))[:100]
    if category:
        body["category"] = category
    return _results(await _post("/search", body))


async def find_similar(url: str, n: int = 8, *, exclude_domains: list[str] | None = None) -> list[dict[str, Any]]:
    """Pages like `url` on other sites (Exa excludes the source domain)."""
    body: dict[str, Any] = {"url": url, "numResults": max(1, min(n, 25)), "excludeSourceDomain": True}
    if exclude_domains:
        body["excludeDomains"] = sorted(set(exclude_domains))[:100]
    return _results(await _post("/findSimilar", body))
