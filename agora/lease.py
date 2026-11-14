"""AGENT WATCH LEASE: an agent rents signed callbacks for one watch, for a while.

The agent-door version of watching (idea from Gumroad's MCP event subscriptions, our own code):
an agent subscribes to `watch.match` and/or `price.drop` for a watch with a callback_url. It gets a
secret in Standard Webhooks format (`whsec_` + base64). Every delivery is a POST with

    webhook-id: msg_...            same id on every retry of the same message (idempotency key)
    webhook-timestamp: 1731600000  unix seconds of this attempt
    webhook-signature: v1,<base64(HMAC-SHA256(key, f"{id}.{timestamp}.{body}"))>

where key = base64-decoded part after `whsec_`. Leases live 5 minutes to 1 day; one client may hold at
most 20 live leases. Failed deliveries are retried with backoff (`retry_due()`, called by the watch loop).
Secrets are stored (we need them to sign) but never logged or listed again after creation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, Header, HTTPException

from agora import store

EVENTS = ("watch.match", "price.drop")
MIN_TTL_S, MAX_TTL_S, DEFAULT_TTL_S = 300, 86_400, 3_600
MAX_LIVE_PER_CLIENT = 20
BACKOFF_S = (5, 30, 120, 600)          # wait after failed attempt 1, 2, 3, 4; attempt 5 is the last
MAX_ATTEMPTS = len(BACKOFF_S) + 1
TOLERANCE_S = 300                      # receivers should reject timestamps further off than this
TIMEOUT_S = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, client_id TEXT, watch_id TEXT, events TEXT,
    callback_url TEXT, secret TEXT, created_at REAL, expires_at REAL, revoked INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS leases_watch ON leases(watch_id);
CREATE TABLE IF NOT EXISTS lease_deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id TEXT, lease_id TEXT,
    event TEXT, body TEXT, attempts INTEGER, status TEXT, next_at REAL, last_status INTEGER, last_error TEXT,
    created_at REAL, delivered_at REAL);
CREATE INDEX IF NOT EXISTS lease_deliveries_due ON lease_deliveries(status, next_at);
"""

_transport: httpx.AsyncBaseTransport | None = None


def _ensure(con: Any) -> None:
    """Create the tables; add the management-token column to databases made before it existed."""
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(leases)").fetchall()}
    if "token_hash" not in cols:
        con.execute("ALTER TABLE leases ADD COLUMN token_hash TEXT")


class LeaseError(ValueError):
    pass


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route deliveries through this transport (tests and the offline stage demo)."""
    global _transport
    _transport = transport




# ---- Standard Webhooks signing ----------------------------------------------------------------

def new_secret() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()


def _key(secret: str) -> bytes:
    if not secret.startswith("whsec_"):
        raise LeaseError("secret must start with whsec_")
    return base64.b64decode(secret[len("whsec_"):])


def sign(secret: str, msg_id: str, timestamp: int, body: str) -> str:
    mac = hmac.new(_key(secret), f"{msg_id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def headers_for(secret: str, msg_id: str, timestamp: int, body: str) -> dict[str, str]:
    return {"webhook-id": msg_id, "webhook-timestamp": str(timestamp),
            "webhook-signature": sign(secret, msg_id, timestamp, body), "content-type": "application/json"}


def verify(secret: str, headers: Any, body: str | bytes, now: float | None = None,
           tolerance_s: int = TOLERANCE_S, seen_ids: set[str] | None = None) -> bool:
    """What the agent runs on its side: is this delivery from Agora, unmodified and recent?

    Receivers must also dedupe on `webhook-id` (a captured delivery still verifies inside the
    tolerance window). Pass a `seen_ids` set and verify() does it: a repeated id returns False,
    and a valid new id is added to the set."""
    h = {str(k).lower(): v for k, v in dict(headers).items()}
    msg_id, ts, sigs = h.get("webhook-id"), h.get("webhook-timestamp"), h.get("webhook-signature")
    if not (msg_id and ts and sigs):
        return False
    try:
        t = int(ts)
    except ValueError:
        return False
    if abs((now or time.time()) - t) > tolerance_s:
        return False
    text = body.decode() if isinstance(body, bytes) else body
    want = sign(secret, msg_id, t, text).split(",", 1)[1]
    ok = any(s.startswith("v1,") and hmac.compare_digest(s.split(",", 1)[1], want) for s in sigs.split())
    if ok and seen_ids is not None:
        if msg_id in seen_ids:
            return False
        seen_ids.add(msg_id)
    return ok


# ---- leases -----------------------------------------------------------------------------------

def _row(r: Any, with_secret: bool = False) -> dict:
    d = dict(r)
    d["events"] = json.loads(d["events"])
    d["revoked"] = bool(d["revoked"])
    d.pop("token_hash", None)
    if not with_secret:
        d.pop("secret", None)
    return d


_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


def _bad_ip(ip: str) -> str | None:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return None
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    if a.is_loopback:
        return None if os.environ.get("AGORA_ALLOW_LOOPBACK_CALLBACKS") == "1" else "loopback"
    if a.is_link_local:
        return "link-local / cloud metadata"
    if a.is_private or a.is_reserved or a.is_multicast or a.is_unspecified:
        return "private network"
    return None


def _check_url(url: str, resolve: bool = True) -> None:
    """http(s) only, and never at our own machine, the LAN or a cloud metadata service (SSRF)."""
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc or not u.hostname:
        raise LeaseError("callback_url must be an http(s) URL")
    host = u.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS and os.environ.get("AGORA_ALLOW_LOOPBACK_CALLBACKS") != "1":
        raise LeaseError(f"callback_url host {host} is not allowed")
    if why := _bad_ip(host):
        raise LeaseError(f"callback_url points at a {why} address")
    if not resolve or os.environ.get("AGORA_OFFLINE") == "1" or _transport is not None:
        return
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return   # unresolvable now: delivery re-checks before every POST
    for info in infos:
        if why := _bad_ip(str(info[4][0])):
            raise LeaseError(f"callback_url resolves to a {why} address")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def live_count(client_id: str, now: float | None = None) -> int:
    now = now or time.time()
    with store.connect() as con:
        _ensure(con)
        return con.execute("SELECT COUNT(*) FROM leases WHERE client_id=? AND revoked=0 AND expires_at>?",
                           (client_id, now)).fetchone()[0]


def create_lease(watch_id: str, callback_url: str, events: list[str] | None = None, client_id: str = "anon",
                 ttl_s: float = DEFAULT_TTL_S, now: float | None = None) -> dict:
    """Subscribe `callback_url` to events of one watch. The returned dict holds the secret: this is
    the only time it is shown."""
    now = now or time.time()
    if store.get_watch(watch_id) is None:
        raise LeaseError(f"no watch {watch_id}")
    _check_url(callback_url)
    evs = list(dict.fromkeys(events or EVENTS))
    if bad := [e for e in evs if e not in EVENTS]:
        raise LeaseError(f"unknown event(s) {bad}; use {list(EVENTS)}")
    ttl = float(ttl_s)
    if not MIN_TTL_S <= ttl <= MAX_TTL_S:
        raise LeaseError(f"ttl must be {MIN_TTL_S}..{MAX_TTL_S} seconds (5 min to 1 day)")
    if live_count(client_id, now) >= MAX_LIVE_PER_CLIENT:
        raise LeaseError(f"client {client_id} already holds {MAX_LIVE_PER_CLIENT} live leases")
    token = "lmt_" + secrets.token_urlsafe(24)
    lease = {"id": f"lease_{uuid.uuid4().hex[:12]}", "client_id": client_id, "watch_id": watch_id,
             "events": evs, "callback_url": callback_url, "secret": new_secret(), "created_at": now,
             "expires_at": now + ttl, "revoked": False}
    with store.connect() as con:
        _ensure(con)
        con.execute("INSERT INTO leases (id, client_id, watch_id, events, callback_url, secret, created_at, "
                    "expires_at, revoked, token_hash) VALUES (?,?,?,?,?,?,?,?,0,?)",
                    (lease["id"], client_id, watch_id, json.dumps(evs), callback_url, lease["secret"], now,
                     lease["expires_at"], _token_hash(token)))
    return lease | {"manage_token": token,
                    "manage": "send header x-lease-token: <manage_token> to list or revoke this lease (shown once)",
                    "signing": "Standard Webhooks: v1 HMAC-SHA256 over '{webhook-id}.{webhook-timestamp}.{body}'"}


def get_lease(lease_id: str) -> dict | None:
    with store.connect() as con:
        _ensure(con)
        r = con.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()
    return _row(r) if r else None


def list_leases(client_id: str | None = None, watch_id: str | None = None, include_expired: bool = False,
                now: float | None = None) -> list[dict]:
    now = now or time.time()
    q, args = "SELECT * FROM leases WHERE 1=1", []
    if client_id:
        q, args = q + " AND client_id=?", args + [client_id]
    if watch_id:
        q, args = q + " AND watch_id=?", args + [watch_id]
    if not include_expired:
        q, args = q + " AND revoked=0 AND expires_at>?", args + [now]
    with store.connect() as con:
        _ensure(con)
        rows = con.execute(q + " ORDER BY created_at", args).fetchall()
    return [_row(r) for r in rows]


def revoke_lease(lease_id: str, client_id: str | None = None, token: str | None = None) -> bool:
    with store.connect() as con:
        _ensure(con)
        q, args = "UPDATE leases SET revoked=1 WHERE id=?", [lease_id]
        if client_id:
            q, args = q + " AND client_id=?", args + [client_id]
        if token is not None:
            q, args = q + " AND token_hash=?", args + [_token_hash(token)]
        return con.execute(q, args).rowcount > 0


def release_client(client_id: str, now: float | None = None) -> int:
    """Revoke every live lease `client_id` holds (the stage demo calls this before and after each run,
    and the server on start, so 'demo-agent' never piles up to the 20-lease cap). Returns how many."""
    now = now or time.time()
    with store.connect() as con:
        _ensure(con)
        return con.execute("UPDATE leases SET revoked=1 WHERE client_id=? AND revoked=0 AND expires_at>?",
                           (client_id, now)).rowcount


def lease_for_token(lease_id: str, token: str | None) -> dict | None:
    """The lease, only when `token` is its management token."""
    if not token:
        return None
    with store.connect() as con:
        _ensure(con)
        r = con.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()
    if not r or not r["token_hash"] or not hmac.compare_digest(r["token_hash"], _token_hash(token)):
        return None
    return _row(r)


# ---- deliveries -------------------------------------------------------------------------------

def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


async def _attempt(delivery: dict, lease: dict, now: float | None = None) -> dict:
    """One POST. Updates the delivery row: delivered | retrying (next_at) | failed."""
    now = now or time.time()
    ts = int(now)
    body = delivery["body"]
    headers = headers_for(lease["secret"], delivery["msg_id"], ts, body)
    status, error = None, None
    try:
        _check_url(lease["callback_url"])
    except LeaseError as e:
        delivery = delivery | {"attempts": MAX_ATTEMPTS - 1}   # never retry a refused host
        status, error = None, str(e)
    try:
        if error:
            raise httpx.RequestError(error)
        async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT_S, follow_redirects=False) as c:
            r = await c.post(lease["callback_url"], content=body.encode(), headers=headers)
        status = r.status_code
        ok = 200 <= status < 300
        if not ok:
            error = f"HTTP {status}"
    except httpx.HTTPError as e:
        ok, error = False, error or type(e).__name__
    attempts = delivery["attempts"] + 1
    if ok:
        state, next_at = "delivered", None
    elif attempts >= MAX_ATTEMPTS:
        state, next_at = "failed", None
    else:
        state, next_at = "retrying", now + BACKOFF_S[attempts - 1]
    with store.connect() as con:
        con.execute("UPDATE lease_deliveries SET attempts=?, status=?, next_at=?, last_status=?, last_error=?, "
                    "delivered_at=? WHERE id=?",
                    (attempts, state, next_at, status, error, now if ok else None, delivery["id"]))
    return {"lease_id": lease["id"], "msg_id": delivery["msg_id"], "event": delivery["event"], "status": state,
            "attempts": attempts, "http_status": status, "error": error, "next_at": next_at}


async def publish(event: str, watch_id: str, data: dict, now: float | None = None) -> list[dict]:
    """Deliver one event to every live lease on this watch that asked for it (first attempt now)."""
    if event not in EVENTS:
        raise LeaseError(f"unknown event {event}")
    now = now or time.time()
    results = []
    for lz in list_leases(watch_id=watch_id, now=now):
        if event not in lz["events"]:
            continue
        msg_id = f"msg_{uuid.uuid4().hex[:16]}"
        body = json.dumps({"type": event, "timestamp": _iso(now), "lease_id": lz["id"], "data": data},
                          default=str, separators=(",", ":"))
        with store.connect() as con:
            cur = con.execute("INSERT INTO lease_deliveries (msg_id, lease_id, event, body, attempts, status, "
                              "next_at, created_at) VALUES (?,?,?,?,0,'pending',?,?)",
                              (msg_id, lz["id"], event, body, now, now))
            did = cur.lastrowid
        full = _lease_with_secret(lz["id"])
        results.append(await _attempt({"id": did, "msg_id": msg_id, "event": event, "body": body, "attempts": 0},
                                      full, now))
    return results


def _lease_with_secret(lease_id: str) -> dict:
    with store.connect() as con:
        _ensure(con)
        return _row(con.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone(), with_secret=True)


async def retry_due(now: float | None = None) -> list[dict]:
    """Retry every delivery whose backoff is over. Leases that expired or were revoked stop retrying."""
    now = now or time.time()
    with store.connect() as con:
        _ensure(con)
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM lease_deliveries WHERE status='retrying' AND next_at<=? ORDER BY id", (now,)).fetchall()]
    out = []
    for d in rows:
        lz = _lease_with_secret(d["lease_id"])
        if lz["revoked"] or lz["expires_at"] <= now:
            with store.connect() as con:
                con.execute("UPDATE lease_deliveries SET status='dropped', next_at=NULL WHERE id=?", (d["id"],))
            out.append({"lease_id": lz["id"], "msg_id": d["msg_id"], "status": "dropped"})
            continue
        out.append(await _attempt(d, lz, now))
    return out


def deliveries(lease_id: str | None = None, watch_id: str | None = None) -> list[dict]:
    q, args = ("SELECT d.* FROM lease_deliveries d JOIN leases l ON l.id = d.lease_id WHERE 1=1", [])
    if lease_id:
        q, args = q + " AND d.lease_id=?", args + [lease_id]
    if watch_id:
        q, args = q + " AND l.watch_id=?", args + [watch_id]
    with store.connect() as con:
        _ensure(con)
        return [dict(r) for r in con.execute(q + " ORDER BY d.id", args).fetchall()]


# ---- HTTP (the api agent mounts `router`) ------------------------------------------------------

router = APIRouter(tags=["leases"])


def _ttl(body: dict) -> float:
    for k in ("ttl_seconds", "ttl_s"):
        if body.get(k) is not None:
            try:
                return float(body[k])
            except (TypeError, ValueError):
                raise LeaseError(f"{k} must be a number of seconds")
    return DEFAULT_TTL_S


@router.post("/watches/{watch_id}/leases")
def http_create_lease(watch_id: str, body: dict[str, Any] = Body(...)) -> dict:
    """{callback_url, events?, ttl_seconds? (alias ttl_s), client_id?} -> lease incl. its secret and
    management token (both shown once)."""
    try:
        return create_lease(watch_id, body.get("callback_url", ""), body.get("events"),
                            str(body.get("client_id") or "anon"), _ttl(body))
    except LeaseError as e:
        raise HTTPException(404 if str(e).startswith("no watch") else 422, str(e))


@router.get("/leases")
def http_list_leases(client_id: str | None = None, watch_id: str | None = None,
                     x_lease_token: str | None = Header(None), lease_id: str | None = None) -> list[dict]:
    """With x-lease-token + lease_id: that one lease. Otherwise client_id is required, and callback
    URLs are not shown (only the lease's own token holder sees them)."""
    if lease_id:
        lz = lease_for_token(lease_id, x_lease_token)
        if lz is None:
            raise HTTPException(403, "x-lease-token does not match this lease")
        return [lz]
    if not client_id:
        raise HTTPException(422, "client_id required (or lease_id + x-lease-token header)")
    return [{k: v for k, v in lz.items() if k != "callback_url"} for lz in list_leases(client_id, watch_id)]


@router.delete("/leases/{lease_id}")
def http_revoke_lease(lease_id: str, x_lease_token: str | None = Header(None)) -> dict:
    """Revoke a lease. Needs its management token (header x-lease-token), returned when it was made."""
    if get_lease(lease_id) is None:
        raise HTTPException(404, f"no lease {lease_id}")
    if lease_for_token(lease_id, x_lease_token) is None:
        raise HTTPException(403, "x-lease-token required: the manage_token returned when the lease was made")
    revoke_lease(lease_id, token=x_lease_token)
    return {"ok": True, "lease_id": lease_id}


@router.get("/leases/{lease_id}/deliveries")
def http_deliveries(lease_id: str) -> list[dict]:
    return [{k: v for k, v in d.items()} for d in deliveries(lease_id)]


@router.post("/leases/retry")
async def http_retry() -> list[dict]:
    return await retry_due()
