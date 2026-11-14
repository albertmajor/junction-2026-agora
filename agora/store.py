"""SQLite store for Agora: needs, offers, price snapshots, watches, mandates, decisions, purchases.

Plain functions, one short-lived connection per call (safe across async tasks).
DB path: env AGORA_DB, default <repo>/agora.db. Rich objects are stored as JSON columns.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from agora.models import Need, Offer, to_dict

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "agora.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS needs (id TEXT PRIMARY KEY, raw TEXT, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS offers (url TEXT PRIMARY KEY, source TEXT, title TEXT, price_eur REAL,
    data TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, price_eur REAL,
    in_stock INTEGER, seen_at REAL);
CREATE INDEX IF NOT EXISTS snapshots_url ON snapshots(url, seen_at);
CREATE TABLE IF NOT EXISTS mandates (id TEXT PRIMARY KEY, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, data TEXT, active INTEGER, created_at REAL,
    updated_at REAL);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id TEXT, ts REAL,
    url TEXT, price_eur REAL, outcome TEXT, reason TEXT, prev_hash TEXT, hash TEXT);
CREATE INDEX IF NOT EXISTS decisions_watch ON decisions(watch_id, ts);
CREATE TABLE IF NOT EXISTS purchases (id TEXT PRIMARY KEY, watch_id TEXT, url TEXT, price_eur REAL,
    data TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS reviews (domain TEXT PRIMARY KEY, data TEXT, label TEXT, checked_at REAL);
"""


def db_path() -> str:
    return os.environ.get("AGORA_DB") or str(DEFAULT_DB)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        _migrate(con)
        yield con
        con.commit()
    finally:
        con.close()


_MIGRATED: set[str] = set()


def _migrate(con: sqlite3.Connection) -> None:
    """Older agora.db files: add the hash-chain columns to the decision log."""
    if db_path() in _MIGRATED:
        return
    cols = {r[1] for r in con.execute("PRAGMA table_info(decisions)")}
    for col in ("prev_hash", "hash"):
        if col not in cols:
            con.execute(f"ALTER TABLE decisions ADD COLUMN {col} TEXT")
    _MIGRATED.add(db_path())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _dump(obj: Any) -> str:
    return json.dumps(to_dict(obj), default=str)


# ---- needs / offers ---------------------------------------------------------

def save_need(need: Need) -> str:
    nid = new_id("need")
    with connect() as con:
        con.execute("INSERT INTO needs VALUES (?,?,?,?)", (nid, need.raw, _dump(need), time.time()))
    return nid


def save_offer(offer: Offer | dict) -> None:
    d = dict(to_dict(offer))   # a copy: to_dict returns the caller's dict itself when given one
    d.pop("raw", None)   # page dumps are big and not needed for history
    with connect() as con:
        con.execute(
            "INSERT INTO offers VALUES (?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
            "source=excluded.source, title=excluded.title, price_eur=excluded.price_eur, "
            "data=excluded.data, updated_at=excluded.updated_at",
            (d["url"], d.get("source"), d.get("title"), d.get("price_eur"), json.dumps(d, default=str),
             time.time()),
        )


def get_offer(url: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT data FROM offers WHERE url=?", (url,)).fetchone()
    return json.loads(row["data"]) if row else None


# ---- snapshots (price history) ---------------------------------------------

def snapshot(url: str, price_eur: float | None, in_stock: bool | None, seen_at: float | None = None) -> None:
    """Append a price point. Skips an exact repeat within 60 s (hunt and watch both snapshot)."""
    stock = None if in_stock is None else int(bool(in_stock))
    ts = seen_at if seen_at is not None else time.time()
    with connect() as con:
        last = con.execute("SELECT price_eur, in_stock, seen_at FROM snapshots WHERE url=? ORDER BY id DESC LIMIT 1",
                           (url,)).fetchone()
        if last and last["price_eur"] == price_eur and last["in_stock"] == stock and 0 <= ts - last["seen_at"] < 60:
            return
        con.execute("INSERT INTO snapshots (url, price_eur, in_stock, seen_at) VALUES (?,?,?,?)",
                    (url, price_eur, stock, ts))


def history(url: str, since: float | None = None) -> list[dict]:
    """Price history for one URL, oldest first."""
    with connect() as con:
        rows = con.execute(
            "SELECT url, price_eur, in_stock, seen_at FROM snapshots WHERE url=? AND seen_at>=? ORDER BY seen_at",
            (url, since or 0.0),
        ).fetchall()
    return [dict(r) | {"in_stock": None if r["in_stock"] is None else bool(r["in_stock"])} for r in rows]


def thing_history(thing_id: str) -> dict[str, list[dict]]:
    """Price history of every known offer URL that resolved to this thing."""
    with connect() as con:
        rows = con.execute("SELECT url, data FROM offers").fetchall()
    urls = [r["url"] for r in rows if json.loads(r["data"]).get("thing_id") == thing_id]
    return {u: history(u) for u in sorted(urls)}


# ---- mandates / watches -----------------------------------------------------

def save_mandate(mid: str, data: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO mandates VALUES (?,?,?)", (mid, json.dumps(data), time.time()))


def get_mandate(mid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT data FROM mandates WHERE id=?", (mid,)).fetchone()
    return json.loads(row["data"]) if row else None


def save_watch(wid: str, data: dict, active: bool = True) -> None:
    now = time.time()
    with connect() as con:
        con.execute(
            "INSERT INTO watches VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "data=excluded.data, active=excluded.active, updated_at=excluded.updated_at",
            (wid, json.dumps(data, default=str), int(active), data.get("created_at", now), now),
        )


def get_watch(wid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT data, active FROM watches WHERE id=?", (wid,)).fetchone()
    return json.loads(row["data"]) | {"active": bool(row["active"])} if row else None


def list_watches(active_only: bool = False) -> list[dict]:
    q = "SELECT data, active FROM watches" + (" WHERE active=1" if active_only else "") + " ORDER BY created_at"
    with connect() as con:
        rows = con.execute(q).fetchall()
    return [json.loads(r["data"]) | {"active": bool(r["active"])} for r in rows]


# ---- decisions (append-only) -----------------------------------------------

def log_decision(watch_id: str, url: str | None, price_eur: float | None, outcome: str, reason: str) -> dict:
    """Append one decision. Each row hashes the one before it (per watch): see agora.proof."""
    from agora.proof import GENESIS, entry_hash
    row = {"watch_id": watch_id, "ts": time.time(), "url": url, "price_eur": price_eur,
           "outcome": outcome, "reason": reason}
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        last = con.execute("SELECT hash FROM decisions WHERE watch_id=? ORDER BY id DESC LIMIT 1",
                           (watch_id,)).fetchone()
        row["prev_hash"] = (last["hash"] if last and last["hash"] else GENESIS)
        row["hash"] = entry_hash(row["prev_hash"], row)
        con.execute("INSERT INTO decisions (watch_id, ts, url, price_eur, outcome, reason, prev_hash, hash) "
                    "VALUES (?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


def decisions(watch_id: str | None = None, limit: int = 200) -> list[dict]:
    with connect() as con:
        if watch_id:
            rows = con.execute("SELECT * FROM decisions WHERE watch_id=? ORDER BY id DESC LIMIT ?",
                               (watch_id, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---- purchases --------------------------------------------------------------

def save_purchase(watch_id: str | None, url: str, price_eur: float, data: dict) -> str:
    pid = new_id("buy")
    with connect() as con:
        con.execute("INSERT INTO purchases VALUES (?,?,?,?,?,?)",
                    (pid, watch_id, url, price_eur, json.dumps(data, default=str), time.time()))
    return pid


def purchases(watch_id: str | None = None) -> list[dict]:
    with connect() as con:
        if watch_id:
            rows = con.execute("SELECT * FROM purchases WHERE watch_id=? ORDER BY ts", (watch_id,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM purchases ORDER BY ts").fetchall()
    return [dict(r) | {"data": json.loads(r["data"])} for r in rows]


def spent_under_mandate(mandate_id: str) -> float:
    """Total EUR already spent by purchases that ran under this mandate."""
    total = 0.0
    for p in purchases():
        if p["data"].get("mandate_id") == mandate_id:
            total += p["price_eur"] or 0.0
    return total


# ---- shop familiarity -------------------------------------------------------

def domains_seen(domains: list[str], bucket_s: float = 600.0) -> dict[str, int]:
    """For each shop domain: in how many separate hunts (10-minute buckets of snapshots) we saw it."""
    if not domains:
        return {}
    marks = ",".join("?" * len(domains))
    with connect() as con:
        rows = con.execute(
            f"SELECT o.source AS source, COUNT(DISTINCT CAST(s.seen_at / ? AS INTEGER)) AS n FROM snapshots s "
            f"JOIN offers o ON o.url = s.url WHERE o.source IN ({marks}) GROUP BY o.source",
            (bucket_s, *domains)).fetchall()
    return {r["source"]: int(r["n"]) for r in rows}


# ---- seller reviews (agora.reviews), cached per registrable domain -----------

def save_review(domain: str, data: dict, checked_at: float | None = None) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
                    (domain, json.dumps(data, default=str, ensure_ascii=False), data.get("label"),
                     checked_at if checked_at is not None else time.time()))


def get_reviews(domains: list[str]) -> dict[str, dict]:
    """domain -> {**data, "checked_at": ts} for the domains we have (any age; the caller applies its TTL)."""
    if not domains:
        return {}
    marks = ",".join("?" * len(domains))
    with connect() as con:
        rows = con.execute(f"SELECT domain, data, checked_at FROM reviews WHERE domain IN ({marks})",
                           tuple(domains)).fetchall()
    return {r["domain"]: json.loads(r["data"]) | {"checked_at": r["checked_at"]} for r in rows}
