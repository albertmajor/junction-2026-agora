"""SHARE A HUNT: short share links + attributed outbound clicks (global-affiliate idea, our own code).

Anyone can share a hunt: POST /share {query, sharer} -> a short id, opened at /s/{id}. Every outbound offer
link in the viewer goes through /go/{share_id}/{offer_token}: we log one CLICK row with the sharer it is
attributed to, then redirect to the shop (through buy.affiliate_link). Later, part of the affiliate
commission on that click goes to the sharer: that is the growth loop.

Own tables (`shares`, `clicks`) in the same SQLite file as agora.store (env AGORA_DB).
Offer tokens are the offer URL in url-safe base64 without padding, so the browser can build them itself.
Written at Junction 2026.
"""
from __future__ import annotations

import base64
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

from agora import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS shares (id TEXT PRIMARY KEY, query TEXT NOT NULL, sharer TEXT NOT NULL,
    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, share_id TEXT, sharer TEXT,
    url TEXT NOT NULL, domain TEXT, out_url TEXT, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS clicks_share ON clicks(share_id, ts);
CREATE INDEX IF NOT EXISTS clicks_sharer ON clicks(sharer, ts);
"""

# no look-alike characters (0/o, 1/l/i): ids get read aloud and typed from a slide
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
ID_LEN = 7
_ID = re.compile(rf"^[{ALPHABET}]{{{ID_LEN}}}$")
_SHARER = re.compile(r"[^\w .@-]+", re.UNICODE)
MAX_QUERY = 200
MAX_URL = 2048


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(store.db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def valid_id(share_id: str | None) -> bool:
    return bool(share_id) and bool(_ID.match(share_id))


def clean_sharer(sharer: str | None) -> str:
    s = _SHARER.sub("", (sharer or "").strip())[:40].strip()
    return s or "anonymous"


def new_share_id() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))


def create_share(query: str, sharer: str | None = None) -> dict[str, Any]:
    """Save a shareable hunt. Same query + same sharer -> the same id (no duplicate links)."""
    q = " ".join((query or "").split())[:MAX_QUERY]
    if len(q) < 2:
        raise ValueError("query required")
    who = clean_sharer(sharer)
    with connect() as con:
        row = con.execute("SELECT * FROM shares WHERE query=? AND sharer=?", (q, who)).fetchone()
        if row:
            return dict(row)
        for _ in range(8):
            sid = new_share_id()
            try:
                con.execute("INSERT INTO shares VALUES (?,?,?,?)", (sid, q, who, time.time()))
                return {"id": sid, "query": q, "sharer": who, "created_at": time.time()}
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("could not allocate a share id")


def get_share(share_id: str) -> dict[str, Any] | None:
    if not valid_id(share_id):
        return None
    with connect() as con:
        row = con.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    return dict(row) if row else None


# ---- offer tokens -----------------------------------------------------------

def encode_url(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def decode_url(token: str) -> str | None:
    """Offer token -> URL, or None when it is not a plain http(s) URL (no javascript:, data:, ...)."""
    if not token or len(token) > MAX_URL * 2:
        return None
    try:
        url = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or len(url) > MAX_URL or any(c in url for c in "\r\n"):
        return None
    return url


# ---- clicks -----------------------------------------------------------------

def outbound(url: str) -> str:
    """Where the click finally lands: the affiliate-rewritten shop URL."""
    try:
        from agora.buy import affiliate_link
        return affiliate_link(url)
    except Exception:
        return url


def log_click(url: str, share_id: str | None = None) -> dict[str, Any]:
    """One CLICK row. An unknown share id is kept off the row (no attribution), never an error."""
    share = get_share(share_id) if share_id else None
    out = outbound(url)
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    row = {"share_id": share["id"] if share else None, "sharer": share["sharer"] if share else None,
           "url": url, "domain": domain, "out_url": out, "ts": time.time()}
    with connect() as con:
        cur = con.execute("INSERT INTO clicks (share_id, sharer, url, domain, out_url, ts) VALUES (?,?,?,?,?,?)",
                          (row["share_id"], row["sharer"], url, domain, out, row["ts"]))
        row["id"] = cur.lastrowid
    return row


def clicks(share_id: str | None = None, sharer: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM clicks", []
    if share_id:
        sql, args = sql + " WHERE share_id=?", [share_id]
    elif sharer:
        sql, args = sql + " WHERE sharer=?", [clean_sharer(sharer)]
    with connect() as con:
        rows = con.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def stats(share_id: str) -> dict[str, Any] | None:
    """A share plus its attributed clicks: total, per shop, last few."""
    share = get_share(share_id)
    if share is None:
        return None
    rows = clicks(share_id=share_id, limit=10_000)
    by_domain: dict[str, int] = {}
    for r in rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    return share | {"clicks": len(rows),
                    "by_domain": dict(sorted(by_domain.items(), key=lambda kv: -kv[1])),
                    "recent": rows[:10]}
