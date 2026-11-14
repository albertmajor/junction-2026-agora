"""Self-growing registry of long-tail providers (agora.longtail). Written at Junction 2026.

Every provider the long-tail lane finds (designjoy.co, a Finnish tilitoimisto, a productized dev shop ...) is
kept with its category, home page, pricing page and the plans read from it, so the next hunt for the same kind
of thing starts from them for free: no search, and while the plans are fresh not even a page fetch.

One small table `longtail_providers` in the main SQLite file (env AGORA_DB, default <repo>/agora.db).
Plain functions, one short connection per call (safe across async tasks; callers use asyncio.to_thread).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

PLANS_TTL_S = 3 * 24 * 3600        # plans younger than this are reused without fetching the page again
SCHEMA = """
CREATE TABLE IF NOT EXISTS longtail_providers (
    domain TEXT PRIMARY KEY, name TEXT, category_id TEXT, category TEXT, terms TEXT,
    home_url TEXT, pricing_url TEXT, found_via TEXT, plans TEXT, plans_at REAL,
    first_seen REAL, last_seen REAL, hits INTEGER DEFAULT 0, no_prices INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS longtail_cat ON longtail_providers(category_id);
"""


def _db_path() -> str:
    from agora import store
    return store.db_path()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def terms_of(text: str) -> list[str]:
    """Search words of a need / category ('Unlimited graphic design subscription' -> [design, graphic, ...])."""
    stop = {"for", "and", "the", "with", "of", "in", "a", "an", "service", "services", "subscription", "unlimited",
            "small", "business", "company", "provider", "best", "cheap", "monthly", "price", "pricing", "plan", "plans"}
    words = re.findall(r"[a-zäöåüß]{3,}", (text or "").lower())
    return sorted({w for w in words if w not in stop})


def save_provider(domain: str, *, name: str | None = None, category_id: str | None = None,
                  category: str | None = None, terms: list[str] | None = None, home_url: str | None = None,
                  pricing_url: str | None = None, found_via: str | None = None,
                  plans: list[dict[str, Any]] | None = None, now: float | None = None) -> None:
    """Insert or update one provider. Plans replace the stored ones only when some were read
    (an empty read does not wipe good plans; it bumps `no_prices`)."""
    now = time.time() if now is None else now
    with _connect() as con:
        row = con.execute("SELECT * FROM longtail_providers WHERE domain=?", (domain,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO longtail_providers (domain, name, category_id, category, terms, home_url, pricing_url,"
                " found_via, plans, plans_at, first_seen, last_seen, hits, no_prices)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (domain, name, category_id, category, json.dumps(sorted(set(terms or []))), home_url, pricing_url,
                 found_via, json.dumps(plans or []), now if plans else None, now, now, 0 if plans else 1))
            return
        old_terms = set(json.loads(row["terms"] or "[]"))
        con.execute(
            "UPDATE longtail_providers SET name=COALESCE(?, name), category_id=COALESCE(category_id, ?),"
            " category=COALESCE(category, ?), terms=?, home_url=COALESCE(?, home_url),"
            " pricing_url=COALESCE(?, pricing_url), found_via=COALESCE(found_via, ?), last_seen=?, hits=hits+1,"
            " plans=CASE WHEN ? THEN ? ELSE plans END, plans_at=CASE WHEN ? THEN ? ELSE plans_at END,"
            " no_prices=CASE WHEN ? THEN 0 ELSE no_prices+1 END WHERE domain=?",
            (name, category_id, category, json.dumps(sorted(old_terms | set(terms or []))), home_url, pricing_url,
             found_via, now, bool(plans), json.dumps(plans or []), bool(plans), now, bool(plans), domain))


def _row(r: sqlite3.Row, now: float) -> dict[str, Any]:
    d = dict(r)
    d["terms"] = json.loads(d.get("terms") or "[]")
    d["plans"] = json.loads(d.get("plans") or "[]")
    d["fresh"] = bool(d["plans"]) and d.get("plans_at") is not None and now - d["plans_at"] < PLANS_TTL_S
    return d


def get(domain: str) -> dict[str, Any] | None:
    with _connect() as con:
        r = con.execute("SELECT * FROM longtail_providers WHERE domain=?", (domain,)).fetchone()
    return _row(r, time.time()) if r is not None else None


def providers_for(category_id: str | None, terms: list[str], limit: int = 8,
                  now: float | None = None) -> list[dict[str, Any]]:
    """Known providers for this category (same taxonomy id), or sharing >= 2 search words (>= 1 when the need
    has only one). Priced ones first, then the most often seen. Providers that never showed a price
    three times in a row are left out."""
    now = time.time() if now is None else now
    want = set(terms)
    need_hits = 1 if len(want) <= 1 else 2
    out: list[dict[str, Any]] = []
    with _connect() as con:
        rows = con.execute("SELECT * FROM longtail_providers WHERE no_prices < 3").fetchall()
    for r in rows:
        d = _row(r, now)
        same_cat = bool(category_id) and d.get("category_id") == category_id
        if same_cat or len(want & set(d["terms"])) >= need_hits:
            out.append(d)
    out.sort(key=lambda d: (not d["plans"], -(d.get("hits") or 0), d["domain"]))
    return out[:limit]


def count() -> int:
    with _connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM longtail_providers").fetchone()[0])
