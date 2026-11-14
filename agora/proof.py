"""PROOF: signed mandates and a hash-chained decision log, so "the agent bought it" can be checked.

- A mandate (cap, expiry, merchants, confirm threshold, the need text) is signed with HMAC-SHA256.
  Key: env AGORA_SIGNING_KEY, else a random per-install key in `.cache/signing.key` (never logged).
  Edit the cap in the database and the signature no longer matches: the agent refuses to spend.
- Every decision line of a watch carries `prev_hash` and `hash = sha256(prev_hash + canonical(entry))`.
  Change or delete one old row and every hash after it stops matching.
AP2-inspired idea, our own code and shapes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import secrets
from typing import Any

ALG = "HMAC-SHA256"
GENESIS = "0" * 64
MANDATE_FIELDS = ("id", "cap_eur", "expires_at", "merchants", "require_confirm_above_eur", "need")
# Signed only when present, so mandates signed before these existed still verify.
OPEN_FIELDS = ("kind", "constraints", "currency")
CLOSED_FIELDS = ("id", "kind", "open_mandate_id", "open_mandate_digest", "watch_id", "offer_id", "merchant",
                 "items", "total_eur", "currency", "cart_signature", "created_at")
ENTRY_FIELDS = ("watch_id", "ts", "url", "price_eur", "outcome", "reason")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _key_file() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or pathlib.Path(__file__).resolve().parent.parent / ".cache")
    return root / "signing.key"


def signing_key() -> bytes:
    env = os.environ.get("AGORA_SIGNING_KEY")
    if env:
        return env.encode()
    f = _key_file()
    try:
        return f.read_text().strip().encode()
    except OSError:
        f.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        f.write_text(key)
        os.chmod(f, 0o600)
        return key.encode()


# ---- mandates ---------------------------------------------------------------

def mandate_payload(m: dict) -> str:
    body = {k: m.get(k) for k in MANDATE_FIELDS} | {k: m[k] for k in OPEN_FIELDS if k in m}
    return canonical(body)


def sign_mandate(m: dict, need_text: str | None = None) -> dict:
    """Return the mandate with `need`, `alg` and `signature` set."""
    out = dict(m)
    if need_text is not None:
        out["need"] = need_text
    out["alg"] = ALG
    out["signature"] = hmac.new(signing_key(), mandate_payload(out).encode(), hashlib.sha256).hexdigest()
    return out


def verify_mandate(m: dict | None) -> bool:
    if not m or not m.get("signature"):
        return False
    want = hmac.new(signing_key(), mandate_payload(m).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, str(m["signature"]))


# ---- cart mandates (what exactly the agent agreed to pay, signed before checkout) ---------------------

CART_FIELDS = ("mandate_id", "merchant", "items", "total_eur", "created_at")
# Signed only when present (older carts / closed mandates still verify): binds a proof to one checkout.
BIND_FIELDS = ("session_id",)


def _cart_payload(cart: dict) -> str:
    return canonical({k: cart.get(k) for k in CART_FIELDS} | {k: cart[k] for k in BIND_FIELDS if k in cart})


def sign_cart(cart: dict) -> dict:
    """The agent's own promise: these items, this total, under that mandate. The shop must match it."""
    out = dict(cart)
    out["alg"] = ALG
    out["signature"] = hmac.new(signing_key(), _cart_payload(out).encode(), hashlib.sha256).hexdigest()
    return out


def verify_cart(cart: dict | None) -> bool:
    if not cart or not cart.get("signature"):
        return False
    want = hmac.new(signing_key(), _cart_payload(cart).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, str(cart["signature"]))


def cart_mismatch(cart: dict, session: dict) -> list[str]:
    """Everything in a checkout session that the signed cart did not agree to. [] = it matches."""
    problems: list[str] = []
    agreed = {(i["id"], int(i.get("quantity", 1))) for i in cart.get("items") or []}
    lines = session.get("line_items") or []
    got = {(ln["id"], int(ln.get("quantity", 1))) for ln in lines if ln.get("kind", "product") == "product"}
    for ln in lines:
        if ln.get("kind", "product") != "product":
            problems.append(f"extra line '{ln.get('title')}' {_money(ln.get('amount_eur'))}")
        elif ln.get("unit_price_eur") is not None and any(
                i["id"] == ln["id"] and abs(float(i.get("unit_price_eur", ln["unit_price_eur"]))
                                          - float(ln["unit_price_eur"])) > 0.005 for i in cart.get("items") or []):
            problems.append(f"{ln['id']} now {_money(ln['unit_price_eur'])}")
    if got != agreed:
        problems.append("items differ from the cart")
    total = float((session.get("totals") or {}).get("total_eur") or 0)
    if abs(total - float(cart.get("total_eur") or 0)) > 0.005:
        problems.insert(0, f"checkout total {_money(total)} ≠ mandated {_money(cart.get('total_eur'))}")
    return problems


def _money(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    return f"€{v:,.0f}" if abs(v - round(v)) < 0.005 else f"€{v:,.2f}"


# ---- decision chain ---------------------------------------------------------

def entry_hash(prev_hash: str, entry: dict) -> str:
    body = canonical({k: entry.get(k) for k in ENTRY_FIELDS})
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def verify_chain(rows: list[dict]) -> tuple[bool, int | None]:
    """(ok, index of the first broken row). Rows oldest first, as stored."""
    prev = GENESIS
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev or r.get("hash") != entry_hash(prev, r):
            return False, i
        prev = r["hash"]
    return True, None


# ---- open -> closed mandate chain (AP2-inspired, our own shapes) ----------------------------------
#
# OPEN mandate  (the person -> the agent): constraints only. Merchants, which products/conditions,
#               max amount, expiry. Signed when the watch is created.
# CLOSED mandate (the agent, at buy time): this exact cart, this total, at this merchant, pointing at
#               the open mandate by id AND by digest. Signed before paying and written into the
#               watch's hash chain, so "this purchase fits what the person signed" can be checked later.

def mandate_digest(m: dict) -> str:
    """sha256 over the signed payload + signature: what a closed mandate points at."""
    return hashlib.sha256((mandate_payload(m) + str(m.get("signature") or "")).encode()).hexdigest()


def _closed_payload(c: dict) -> str:
    return canonical({k: c.get(k) for k in CLOSED_FIELDS} | {k: c[k] for k in BIND_FIELDS if k in c})


def sign_closed_mandate(c: dict) -> dict:
    out = dict(c)
    out["kind"] = "closed"
    out.setdefault("currency", "EUR")
    out["alg"] = ALG
    out["signature"] = hmac.new(signing_key(), _closed_payload(out).encode(), hashlib.sha256).hexdigest()
    out["digest"] = hashlib.sha256((_closed_payload(out) + out["signature"]).encode()).hexdigest()
    return out


def verify_closed_mandate(c: dict | None) -> bool:
    if not c or c.get("kind") != "closed" or not c.get("signature"):
        return False
    want = hmac.new(signing_key(), _closed_payload(c).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, str(c["signature"]))


def closed_mandate_line(c: dict) -> str:
    """The decision-log line that links a closed mandate into the hash chain (full digest on purpose)."""
    items = ", ".join(f"{i.get('quantity', 1)}x {i.get('id')} @ {_money(i.get('unit_price_eur'))}"
                      for i in c.get("items") or [])
    return (f"closed mandate {c.get('id')}: {items} = {_money(c.get('total_eur'))} at {c.get('merchant')}, "
            f"under open mandate {c.get('open_mandate_id')}; digest {c.get('digest')}")


def _ts(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def check_closed_against_open(open_m: dict | None, closed: dict | None) -> list[dict]:
    """Every rule of the open mandate, checked against one closed mandate. [{check, ok, detail}]."""
    out: list[dict] = []

    def add(check: str, ok: bool, detail: str) -> None:
        out.append({"check": check, "ok": bool(ok), "detail": detail})

    if not open_m or not closed:
        add("present", False, "open or closed mandate missing")
        return out
    add("open signature", verify_mandate(open_m), "the person's open mandate is signed and unchanged")
    add("closed signature", verify_closed_mandate(closed), "the agent's closed mandate is signed and unchanged")
    add("points at open", closed.get("open_mandate_id") == open_m.get("id")
        and closed.get("open_mandate_digest") == mandate_digest(open_m),
        f"open mandate {open_m.get('id')} by id and digest")
    total = float(closed.get("total_eur") or 0)
    cap = open_m.get("cap_eur")
    add("under cap", cap is None or total <= float(cap) + 1e-9, f"{_money(total)} <= cap {_money(cap)}")
    merchants = [m.lower() for m in open_m.get("merchants") or []]
    merchant = str(closed.get("merchant") or "").lower()
    add("merchant allowed", not merchants or any(merchant == m or merchant.endswith("." + m) for m in merchants),
        f"{merchant} in {merchants or 'any'}")
    exp = _ts(open_m.get("expires_at"))
    made = _ts(closed.get("created_at")) or 0.0
    add("before expiry", exp is None or made <= exp, "closed before the open mandate expired")
    cons = open_m.get("constraints") or {}
    pids = cons.get("product_ids") or []
    ids = [i.get("id") for i in closed.get("items") or []]
    add("products allowed", not pids or all(i in pids for i in ids), f"{ids} in {pids or 'any'}")
    lines = sum(float(i.get("unit_price_eur") or 0) * int(i.get("quantity", 1)) for i in closed.get("items") or [])
    add("total adds up", abs(lines - total) < 0.005, f"lines {_money(lines)} = total {_money(total)}")
    return out


def mandate_chain(w: dict, chain: list[dict]) -> dict:
    """The watch's open mandate, every closed mandate the agent signed under it, and where each one
    sits in the hash chain."""
    from agora import store
    open_m = w.get("mandate")
    links = []
    for cid in w.get("closed_mandates") or []:
        c = store.get_mandate(cid)
        checks = check_closed_against_open(open_m, c)
        idx = next((i for i, r in enumerate(chain)
                    if r.get("outcome") == "mandate" and c and c.get("digest") and c["digest"] in (r.get("reason") or "")),
                   None)
        checks.append({"check": "in hash chain", "ok": idx is not None,
                       "detail": f"decision #{idx}" if idx is not None else "not found in the decision log"})
        links.append({"closed": c, "chain_index": idx, "checks": checks, "ok": all(x["ok"] for x in checks)})
    return {"open": open_m, "open_digest": mandate_digest(open_m) if open_m else None,
            "closed": links, "ok": all(link["ok"] for link in links) if links else None}


def watch_proof(watch_id: str) -> dict | None:
    """Everything a skeptic needs: the mandate, whether its signature holds, and the decision chain."""
    from agora import store
    w = store.get_watch(watch_id)
    if w is None:
        return None
    chain = store.decisions(watch_id, limit=10_000)
    ok, broken = verify_chain(chain)
    m = w.get("mandate")
    return {
        "watch_id": watch_id,
        "mandate": m,
        "signature_ok": verify_mandate(m) if m else None,
        "alg": ALG,
        "chain": chain,
        "chain_ok": ok,
        "first_broken_index": broken,
        "head": chain[-1]["hash"] if chain else GENESIS,
        "purchases": store.purchases(watch_id),
        "mandate_chain": mandate_chain(w, chain),
    }
