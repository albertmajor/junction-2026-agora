"""BUY levels for Agora watchers.

L1 notify   push via ntfy.sh (env AGORA_NTFY_TOPIC; skipped when unset), with the (affiliate) link
L2 one_tap  a link straight to the offer / our checkout, the person pays
L3 auto_buy the agent checks out by itself, ONLY on our own mock shop and ONLY inside the mandate
            (cap, expiry, merchant allowlist, confirm-above threshold). AP2-inspired idea, our own code.

Provenance gate (idea from anthropics/commerce-agents, our own code): a buy only accepts an
`offer_id` that our own reader registered in this watch (or hunt). The price always comes from that
stored row, never from whatever text the caller passes in. Auto-buy signs a CLOSED mandate for the
exact cart under the watch's OPEN mandate and writes it into the watch's hash chain (agora.proof).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from agora import mockshop, proof, store
from agora.models import Offer, to_dict

NTFY_BASE = "https://ntfy.sh"


def _eur(x: float) -> str:
    return f"€{x:,.0f}" if abs(x - round(x)) < 0.005 else f"€{x:,.2f}"


# ---- links ------------------------------------------------------------------

def affiliate_link(url: str) -> str:
    """Affiliate-rewrite hook (placeholder): tags the link so clicks can be attributed later.

    Real programs (Awin, Amazon tag=..., eBay campid=...) plug in here per domain.
    """
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query))
    q.setdefault("utm_source", "agora")
    if tag := os.environ.get("AGORA_AFFILIATE_TAG"):
        q.setdefault("aff", tag)
    return urlunparse(parts._replace(query=urlencode(q)))


def one_tap_link(offer: dict) -> str:
    """Deep link the person taps to buy. Mock shop: prefilled checkout; elsewhere: the offer page."""
    pid = mockshop.product_id_from_url(offer.get("url"))
    if pid:
        return f"{mockshop.base_url()}{mockshop.PREFIX}/products/{pid}?checkout=1"
    return affiliate_link(offer["url"])


# ---- L1 notify --------------------------------------------------------------

async def notify(title: str, message: str, click: str | None = None,
                 client: httpx.AsyncClient | None = None) -> dict:
    topic = os.environ.get("AGORA_NTFY_TOPIC")
    if not topic:
        return {"sent": False, "reason": "AGORA_NTFY_TOPIC not set"}
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Tags": "shopping_cart"}
    if click:
        headers["Click"] = click
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        r = await client.post(f"{NTFY_BASE}/{topic}", content=message.encode("utf-8"), headers=headers)
        return {"sent": r.status_code < 300, "status": r.status_code}
    except httpx.HTTPError as e:
        return {"sent": False, "reason": f"ntfy error: {type(e).__name__}"}
    finally:
        if own:
            await client.aclose()


# ---- provenance: which offers our own reader stored, per watch / hunt --------------------------

PROVENANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS offer_provenance (offer_id TEXT PRIMARY KEY, scope TEXT, url TEXT, price_eur REAL,
    source TEXT, read_via TEXT, data TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS offer_provenance_scope ON offer_provenance(scope, url);
"""


def _offer_id(scope: str, d: dict) -> str:
    key = json.dumps([scope, d.get("url"), d.get("price_eur"), d.get("in_stock"), d.get("condition")],
                     default=str)
    return "off_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def register_offer(scope: str, offer: Offer | dict) -> str:
    """Remember that Agora itself read this offer inside `scope` (a watch id or hunt id).
    Returns the offer id a later buy must present. Same scope + url + price -> same id."""
    d = to_dict(offer)
    d = {k: v for k, v in d.items() if k != "raw"} | {"raw": {k: v for k, v in (d.get("raw") or {}).items()
                                                              if k in ("counter_offer", "lie_detector")}}
    oid = _offer_id(scope, d)
    d["offer_id"] = oid
    with store.connect() as con:
        con.executescript(PROVENANCE_SCHEMA)
        con.execute("INSERT OR REPLACE INTO offer_provenance VALUES (?,?,?,?,?,?,?,?)",
                    (oid, scope, d.get("url"), d.get("price_eur"), d.get("source"), d.get("read_via"),
                     json.dumps(d, default=str), time.time()))
    return oid


def lookup_offer(offer_id: str | None, scopes: list[str | None]) -> dict | None:
    """The stored offer, only if it was registered in one of `scopes`. Price = the stored price."""
    scopes = [s for s in scopes if s]
    if not offer_id or not scopes:
        return None
    with store.connect() as con:
        con.executescript(PROVENANCE_SCHEMA)
        row = con.execute(f"SELECT * FROM offer_provenance WHERE offer_id=? AND scope IN ({','.join('?' * len(scopes))})",
                          (offer_id, *scopes)).fetchone()
    if not row:
        return None
    d = json.loads(row["data"])
    d["price_eur"], d["url"], d["offer_id"] = row["price_eur"], row["url"], row["offer_id"]
    return d


def _scopes(watch: dict) -> list[str | None]:
    return [watch.get("id"), *(watch.get("hunt_ids") or [])]


# ---- mandate ----------------------------------------------------------------

def _ts(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def check_mandate(mandate: dict | None, offer: dict, now: float | None = None) -> tuple[bool, str]:
    """Can the agent spend on this offer by itself? Returns (ok, reason)."""
    if not mandate:
        return False, "no mandate signed"
    if not mandate.get("signature"):
        return False, "mandate is not signed: the agent never spends on an unsigned mandate"
    if not proof.verify_mandate(mandate):
        return False, "mandate signature invalid: it was changed after you signed it"
    now = now or time.time()
    price = offer.get("price_eur")
    if price is None:
        return False, "price unknown"
    exp = _ts(mandate.get("expires_at"))
    if exp is not None and now > exp:
        return False, "mandate expired"
    merchants = [m.lower() for m in mandate.get("merchants") or []]
    source = (offer.get("source") or "").lower()
    if merchants and not any(source == m or source.endswith("." + m) for m in merchants):
        return False, f"merchant {source} not in mandate allowlist"
    cap = mandate.get("cap_eur")
    if cap is None or float(cap) <= 0:
        return False, "mandate has no spending cap: auto-buy needs one"
    spent = store.spent_under_mandate(mandate["id"]) if mandate.get("id") else 0.0
    if cap is not None and spent + price > cap:
        return False, f"{_eur(price)} + {_eur(spent)} already spent > cap {_eur(cap)}"
    confirm = mandate.get("require_confirm_above_eur")
    if confirm is not None and price > confirm:
        return False, f"{_eur(price)} > {_eur(confirm)}: needs your confirm"
    cons = mandate.get("constraints") or {}
    if (pids := cons.get("product_ids")) and mockshop.product_id_from_url(offer.get("url")) not in pids:
        return False, "product not in the open mandate"
    if (conds := cons.get("conditions")) and offer.get("condition") not in conds:
        return False, f"condition {offer.get('condition')} not in the open mandate ({'/'.join(conds)})"
    return True, f"inside mandate: {_eur(price)} <= cap {_eur(cap)}"


# ---- receipts ---------------------------------------------------------------

def baseline_price(watch: dict, url: str) -> float | None:
    """What it cost the day the watch was set: explicit baseline, else first snapshot since then."""
    if watch.get("baseline_eur") is not None:
        return float(watch["baseline_eur"])
    hist = [h for h in store.history(url, since=watch.get("created_at")) if h["price_eur"] is not None]
    return hist[0]["price_eur"] if hist else None


def savings_line(price: float, target: float | None, baseline: float | None) -> str:
    parts = [f"bought at {_eur(price)}"]
    if target is not None:
        d = target - price
        parts.append(f"{_eur(d)} under target" if d >= 0 else f"{_eur(-d)} over target")
    if baseline is not None and baseline > price:
        parts.append(f"{_eur(baseline - price)} less than the day you set the watch")
    elif baseline is not None and price - baseline >= 0.005:
        parts.append(f"{_eur(price - baseline)} more than the day you set the watch")
    elif baseline is not None:
        parts.append("same as the day you set the watch")
    return ", ".join(parts)


def _target(watch: dict) -> float | None:
    rule = watch.get("rule") or {}
    return rule.get("max_price_eur") or rule.get("max_true_cost_eur")


# ---- act --------------------------------------------------------------------

async def _send(watch: dict, offer: dict, result: dict, client: httpx.AsyncClient | None) -> dict:
    title = f"Agora: {watch.get('need', {}).get('thing') or offer.get('title')}"
    msg = result.get("savings_line") or (
        f"{offer.get('title')} at {_eur(offer['price_eur'])} on {offer.get('source')}. {result.get('reason', '')}")
    result["notified"] = await notify(title, msg.strip(), click=result.get("link"), client=client)
    return result


class CheckoutRefused(ValueError):
    """The checkout asked for something the signed cart did not agree to. Nothing was paid."""

    def __init__(self, message: str, session_id: str, cart: dict) -> None:
        super().__init__(message)
        self.session_id, self.cart = session_id, cart


def sign_closed(watch: dict, offer: dict, mandate: dict, cart: dict) -> dict:
    """The agent's closed mandate for this exact cart, linked to the open mandate and into the chain."""
    closed = proof.sign_closed_mandate({
        "id": store.new_id("closed"), "open_mandate_id": mandate.get("id"),
        "open_mandate_digest": proof.mandate_digest(mandate), "watch_id": watch.get("id"),
        "offer_id": offer.get("offer_id"), "merchant": cart["merchant"], "items": cart["items"],
        "total_eur": cart["total_eur"], "currency": "EUR", "cart_signature": cart["signature"],
        "created_at": round(time.time(), 3)} | ({"session_id": cart["session_id"]} if cart.get("session_id") else {}))
    store.save_mandate(closed["id"], closed)
    if watch.get("id"):
        store.log_decision(watch["id"], offer.get("url"), cart["total_eur"], "mandate", proof.closed_mandate_line(closed))
    watch["closed_mandates"] = (watch.get("closed_mandates") or []) + [closed["id"]]
    return closed


async def buy_on_mockshop(watch: dict, offer: dict, mandate: dict) -> dict:
    """L3: sign a cart (these items, this total), open an ACP-style checkout session on our mock shop,
    and pay only if the session matches the cart exactly. A hidden fee or a price bump = refuse.
    A counter-offer URL (?counter=co_...) is redeemed at its counter price."""
    pid = mockshop.product_id_from_url(offer["url"])
    code = mockshop.counter_code_from_url(offer["url"])
    line = {"id": pid, "quantity": 1} | ({"offer_code": code} if code else {})
    session = mockshop.create_checkout([line], buyer={"watch_id": watch.get("id")},
                                       mandate_id=mandate.get("id"))
    # The cart is what WE agreed to pay (from our own read of the offer), bound to this one session.
    cart = proof.sign_cart({"mandate_id": mandate.get("id"), "merchant": mockshop.DOMAIN,
                            "items": [{"id": pid, "quantity": 1, "unit_price_eur": offer["price_eur"]}],
                            "total_eur": offer["price_eur"], "session_id": session["id"],
                            "created_at": round(time.time(), 3)})
    paid = session["totals"]["total_eur"]
    if problems := proof.cart_mismatch(cart, session):
        cap = mandate.get("cap_eur")
        msg = "; ".join(problems) + (f", cap {_eur(cap)}" if cap is not None else "")
        if cap is not None and paid <= float(cap):
            msg += " (under the cap, but not what you agreed to)"
        mockshop.cancel_checkout(session["id"], msg)
        raise CheckoutRefused(msg + ": refused, nothing paid", session["id"], cart)
    closed = sign_closed(watch, offer, mandate, cart)
    order = mockshop.complete_checkout(session["id"], payment_token=f"mandate_{mandate.get('id', 'x')}_tok",
                                       mandate=mandate, cart=cart,
                                       closed_mandate=closed)
    target, base = _target(watch), baseline_price(watch, offer["url"])
    line = savings_line(paid, target, base)
    receipt = {"order_id": order["id"], "merchant": offer.get("source"), "item": offer.get("title"),
               "paid_eur": paid, "target_eur": target, "baseline_eur": base,
               "mandate_id": mandate.get("id"), "mandate_signature": mandate.get("signature"),
               "cart_signature": cart["signature"], "session_id": session["id"], "savings_line": line,
               "closed_mandate_id": closed["id"], "closed_mandate_digest": closed["digest"],
               "offer_id": offer.get("offer_id"), "counter_offer": code}
    receipt["purchase_id"] = store.save_purchase(watch.get("id"), offer["url"], paid, receipt)
    return {"receipt": receipt, "savings_line": line}


async def act(watch: dict, offer: Offer | dict, client: httpx.AsyncClient | None = None) -> dict:
    """Do what the watch says for a matching offer. Never raises; returns what happened."""
    offer = to_dict(offer)
    action = watch.get("action", "notify")
    link = affiliate_link(offer["url"])
    if action == "notify":
        return await _send(watch, offer, {"level": "L1", "status": "notified", "link": link,
                                          "reason": "rule matched"}, client)
    if action == "one_tap":
        return await _send(watch, offer, {"level": "L2", "status": "link_sent", "link": one_tap_link(offer),
                                          "reason": "rule matched: tap to buy"}, client)
    # auto_buy: degrade to a one-tap link whenever we may not spend by ourselves
    fallback = {"level": "L2", "status": "link_sent", "link": one_tap_link(offer)}
    if not mockshop.product_id_from_url(offer["url"]):
        return await _send(watch, offer, fallback | {"reason": "auto-buy only runs on our mock shop"}, client)
    stored = lookup_offer(offer.get("offer_id"), _scopes(watch))
    if stored is None:   # provenance gate: we only spend on offers our own reader stored for this watch
        return await _send(watch, offer, fallback | {
            "reason": "provenance gate: this offer id was not read by Agora for this watch"}, client)
    price_note = None
    if stored.get("price_eur") != offer.get("price_eur"):
        price_note = f"price taken from Agora's own read ({_eur(stored['price_eur'])}), not from the request"
    offer = stored
    ok, why = check_mandate(watch.get("mandate"), offer)
    if not ok:
        return await _send(watch, offer, fallback | {"reason": why}, client)
    try:
        bought = await buy_on_mockshop(watch, offer, watch["mandate"])
    except CheckoutRefused as e:
        return await _send(watch, offer, {"level": "L3", "status": "refused", "link": one_tap_link(offer),
                                          "reason": str(e), "session_id": e.session_id,
                                          "cart_total_eur": e.cart.get("total_eur")}, client)
    except (ValueError, KeyError) as e:
        return await _send(watch, offer, fallback | {"reason": f"checkout failed: {e}"}, client)
    result = {"level": "L3", "status": "bought", "link": link, "reason": why} | bought
    if price_note:
        result["price_note"] = price_note
    return await _send(watch, offer, result, client)


async def buy_offer(offer_id: str, watch_id: str | None = None, hunt_id: str | None = None,
                    client: httpx.AsyncClient | None = None) -> dict:
    """Agent-door buy: by offer id only. The id must have been stored by our reader in this watch
    (or hunt); price and URL are re-joined from that row, never taken from the caller."""
    w = store.get_watch(watch_id) if watch_id else None
    scopes = [watch_id, hunt_id]
    stored = lookup_offer(offer_id, scopes)
    if stored is None:
        return {"level": None, "status": "refused", "offer_id": offer_id,
                "reason": "provenance gate: unknown offer id for this watch/hunt (only offers Agora read can be bought)"}
    if w is None:   # no watch, no mandate: the person taps
        return {"level": "L2", "status": "link_sent", "link": one_tap_link(stored), "offer_id": offer_id,
                "price_eur": stored["price_eur"], "reason": "no watch mandate: tap to buy"}
    return await act(w, stored, client=client)


buy = buy_offer
