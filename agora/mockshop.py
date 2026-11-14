"""Agora mock shop: the one merchant our agent is allowed to auto-buy from (live demo, L3).

Mounted at /mockshop. Lower a price on stage -> watchers pinned to it re-check -> agent buys.
Checkout is ACP-flavoured (create checkout session -> complete with a payment token), our own code.
State is in memory (a demo shop); purchases are also logged in agora.store by agora.buy.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agora.models import Offer

PREFIX = "/mockshop"
DOMAIN = "agora-mockshop.local"


@dataclass
class Product:
    id: str
    title: str
    brand: str
    price_eur: float
    stock: int = 3
    condition: str = "new"
    image: str | None = None
    max_discount_pct: float = 10.0   # haggle: how far the shop will go to beat a cheaper competitor
    beat_by_eur: float = 1.0         # haggle: how much under a cheaper competitor the counter goes
    seller: str | None = None        # None = "Agora Mock Shop"
    seller_type: str = "shop"        # "shop" | "private" (a private seller is paid through escrow)
    flags: list[str] | None = None   # None = ["demo merchant"]
    listing_url: str | None = None   # the real listing this demo product stands in for
    location: str | None = None
    price_log: list[tuple[float, float]] = field(default_factory=list)   # (ts, price)


def _seed() -> dict[str, Product]:
    now = time.time()
    items = [
        Product("sony-a7iii", "Sony Alpha A7 III body (ILCE-7M3)", "Sony", 999.0, stock=3),
        Product("macbook-air-m3", "Apple MacBook Air 13 M3 16GB 512GB", "Apple", 1299.0, stock=2),
        Product("sony-fe-85", "Sony FE 85mm F1.8 lens (SEL85F18)", "Sony", 599.0, stock=2),
        used_tori_listing(),
    ]
    for p in items:
        p.price_log.append((now, p.price_eur))
    return {p.id: p for p in items}


# The used pick of the recorded Sony hunt (tests/fixtures/live_sony-a7-iii-body.jsonl): a private seller on
# tori.fi. Title and photo are the real listing's; the mock shop plays that seller for the night-shift demo.
USED_TORI_PID = "sony-a7iii-used-tori"
TORI_LISTING = "https://www.tori.fi/recommerce/forsale/item/40486480"
TORI_IMAGE = "https://img.tori.net/dynamic/1280w/item/40486480/34d5592c-c72a-4782-8692-27575ed644e3"


def used_tori_listing(price_eur: float = 859.0) -> Product:
    return Product(USED_TORI_PID, "Sony A7 III Body", "Sony", price_eur, stock=1, condition="used",
                   image=TORI_IMAGE, max_discount_pct=10.0, beat_by_eur=6.0,
                   seller="private seller on tori.fi", seller_type="private",
                   flags=["demo merchant", "private seller", "seller verified, photos match listing"],
                   listing_url=TORI_LISTING, location="Helsinki")


PRODUCTS: dict[str, Product] = _seed()
SESSIONS: dict[str, dict] = {}
ORDERS: list[dict] = []
# Drip pricing, for the demo: a fee that is NOT on the product page and only shows up in the checkout.
HIDDEN_FEES: dict[str, tuple[str, float]] = {}
# Text shown on the product page only (the JSON-LD is not touched): "Loppuunmyyty" while the
# structured data still says InStock is the lie the watcher's lie detector must catch.
PAGE_BANNERS: dict[str, str] = {}
# Haggle loop: intent traces the shop received, and the counter-offers it made.
FEEDBACK: list[dict] = []
COUNTERS: dict[str, dict] = {}
COUNTER_TTL_S = 15 * 60
# Mandate replay guard: closed mandates and cart signatures the shop already accepted, and how much
# each open mandate has spent here. The shop keeps its own ledger: it never trusts the agent's count.
USED_CLOSED: set[str] = set()
SPENT_BY_MANDATE: dict[str, float] = {}


def reset() -> None:
    """Back to the opening state (tests, or before going on stage)."""
    global PRODUCTS
    PRODUCTS = _seed()
    SESSIONS.clear()
    ORDERS.clear()
    HIDDEN_FEES.clear()
    PAGE_BANNERS.clear()
    FEEDBACK.clear()
    COUNTERS.clear()
    USED_CLOSED.clear()
    SPENT_BY_MANDATE.clear()


def set_hidden_fee(pid: str, fee_eur: float, label: str = "handling fee") -> None:
    """Toggle a checkout-only fee on a product (0 = off). The bait-and-switch the agent must catch."""
    get_product(pid)
    if fee_eur > 0:
        HIDDEN_FEES[pid] = (label, round(float(fee_eur), 2))
    else:
        HIDDEN_FEES.pop(pid, None)


# ---- plain functions (used in-process by agora.buy / agora.watch) -----------

def base_url() -> str:
    return os.environ.get("AGORA_BASE_URL", "http://localhost:8765").rstrip("/")


def product_url(pid: str) -> str:
    return f"{base_url()}{PREFIX}/p/{pid}"


def product_id_from_url(url: str | None) -> str | None:
    m = re.search(rf"{PREFIX}/p/([\w-]+)", url or "")
    return m.group(1) if m and m.group(1) in PRODUCTS else None


def counter_code_from_url(url: str | None) -> str | None:
    m = re.search(r"[?&]counter=(co_[0-9a-f]+)", url or "")
    return m.group(1) if m else None


def set_page_banner(pid: str, text: str | None) -> None:
    """Show `text` on the product page (not in its JSON-LD). Empty/None removes it."""
    get_product(pid)
    if text:
        PAGE_BANNERS[pid] = text
    else:
        PAGE_BANNERS.pop(pid, None)


def get_product(pid: str) -> Product:
    if pid not in PRODUCTS:
        raise KeyError(pid)
    return PRODUCTS[pid]


def set_price(pid: str, price_eur: float) -> Product:
    p = get_product(pid)
    p.price_eur = round(float(price_eur), 2)
    p.price_log.append((time.time(), p.price_eur))
    return p


def as_offer(pid: str) -> Offer:
    p = get_product(pid)
    return Offer(url=product_url(pid), source=DOMAIN, title=p.title, price=p.price_eur, currency="EUR",
                 price_eur=p.price_eur, condition=p.condition, shipping_eur=0.0, in_stock=p.stock > 0,
                 seller=p.seller or "Agora Mock Shop", brand=p.brand, read_via="mockshop", trust=0.95,
                 flags=list(p.flags) if p.flags else ["demo merchant"], image=p.image, location=p.location)


def create_checkout(items: list[dict], buyer: dict | None = None, mandate_id: str | None = None) -> dict:
    lines, total = [], 0.0
    for it in items:
        p = get_product(it["id"])
        qty = int(it.get("quantity", 1))
        if p.stock < qty:
            raise ValueError(f"out of stock: {p.id}")
        unit = p.price_eur
        code = it.get("offer_code")
        if code:
            unit = _redeemable_counter(code, p.id)["price_eur"]
        amount = round(unit * qty, 2)
        line = {"id": p.id, "title": p.title, "quantity": qty, "unit_price_eur": unit,
                "amount_eur": amount, "kind": "product"}
        if code:
            line["offer_code"] = code
        lines.append(line)
        total += amount
        if p.id in HIDDEN_FEES:
            label, fee = HIDDEN_FEES[p.id]
            lines.append({"id": f"fee:{p.id}", "title": label, "quantity": 1, "unit_price_eur": fee,
                          "amount_eur": fee, "kind": "fee"})
            total += fee
    sid = f"cs_{uuid.uuid4().hex[:12]}"
    SESSIONS[sid] = {"id": sid, "status": "ready_for_payment", "line_items": lines, "currency": "EUR",
                     "totals": {"subtotal_eur": round(total, 2), "shipping_eur": 0.0, "total_eur": round(total, 2)},
                     "buyer": buyer or {}, "mandate_id": mandate_id, "created_at": time.time()}
    return SESSIONS[sid]


def cancel_checkout(session_id: str, reason: str = "", intent_trace: dict | None = None) -> dict:
    """Cancel a session. With an ACP-style intent trace (why the agent walked away), the shop may
    answer with a counter-offer: `session['counter_offer']`."""
    s = SESSIONS.get(session_id)
    if not s:
        raise KeyError(session_id)
    if s["status"] == "ready_for_payment":
        s["status"], s["cancel_reason"] = "canceled", reason
    if intent_trace:
        s["intent_trace"] = intent_trace
        pid = next((ln["id"] for ln in s["line_items"] if ln.get("kind", "product") == "product"), None)
        if pid:
            s["counter_offer"] = intent_feedback(pid, intent_trace)["counter_offer"]
    return s


# ---- haggle: intent traces in, counter-offers out --------------------------------------------------

REASON_CODES = ("price_sensitivity", "shipping_cost", "trust_security", "returns_policy", "timing_deferred",
                "comparison", "other")


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def counter_rule(price: float, max_discount_pct: float, competitor: float | None,
                 beat_eur: float = 1.0) -> tuple[float | None, str]:
    """The shop's whole haggling policy: beat a cheaper competitor by €1 (`beat_eur`), but never go more
    than `max_discount_pct` under the current price. No cheaper competitor = no counter."""
    if competitor is None:
        return None, "no competitor price given: price stays"
    if competitor >= price:
        return None, f"competitor €{competitor:,.2f} is not cheaper than our €{price:,.2f}"
    floor = math.ceil(price * (1 - max_discount_pct / 100))
    offer = max(floor, math.floor(competitor) - math.ceil(beat_eur))
    if offer >= price:
        return None, "cannot go lower"
    how = f"beats the competitor by €{math.ceil(beat_eur):g}" if offer < competitor else f"our floor ({max_discount_pct:g}% off)"
    return float(offer), how


def intent_feedback(pid: str, trace: dict) -> dict:
    """Receive why an agent did not buy. Price-type reasons with a cheaper competitor get a
    counter-offer (a code redeemable once at checkout, for 15 minutes)."""
    p = get_product(pid)
    code_in = str(trace.get("reason_code") or "other")
    meta = trace.get("metadata") or {}
    competitor = _num(meta.get("competitor_price_eur"))
    entry = {"product_id": pid, "received_at": time.time(), "trace": trace, "price_eur": p.price_eur}
    counter = None
    if code_in in ("price_sensitivity", "shipping_cost", "comparison"):
        price, why = counter_rule(p.price_eur, p.max_discount_pct, competitor, p.beat_by_eur)
    else:
        price, why = None, f"{code_in}: nothing the price can fix"
    if price is not None and p.stock > 0:
        code = f"co_{uuid.uuid4().hex[:10]}"
        counter = {"code": code, "product_id": pid, "price_eur": price, "was_eur": p.price_eur,
                   "discount_pct": round((p.price_eur - price) / p.price_eur * 100, 1), "why": why,
                   "for_watch": meta.get("watch_id"), "created_at": time.time(),
                   "expires_at": time.time() + COUNTER_TTL_S, "used": False,
                   "url": f"{product_url(pid)}?counter={code}"}
        COUNTERS[code] = counter
    entry["counter_offer"], entry["answer"] = counter, why
    FEEDBACK.append(entry)
    return {"ok": True, "counter_offer": counter, "answer": why}


def get_counter(code: str) -> dict:
    if code not in COUNTERS:
        raise KeyError(code)
    return COUNTERS[code]


def _redeemable_counter(code: str, pid: str) -> dict:
    c = COUNTERS.get(code)
    if not c or c["product_id"] != pid:
        raise ValueError(f"unknown counter-offer {code}")
    if c["used"]:
        raise ValueError(f"counter-offer {code} already used")
    if time.time() > c["expires_at"]:
        raise ValueError(f"counter-offer {code} expired")
    return c


def as_counter_offer(code: str) -> Offer:
    """A counter-offer as an Offer: same product, the counter price, its own URL (carries the code)."""
    c = get_counter(code)
    o = as_offer(c["product_id"])
    o.url, o.price, o.price_eur = c["url"], c["price_eur"], c["price_eur"]
    o.flags = o.flags + [f"counter-offer {c['code']}: was €{c['was_eur']:,.2f}, expires in 15 min"]
    o.raw = {"counter_offer": c, "page_text": page_text(c["product_id"])}
    return o


def complete_checkout(session_id: str, payment_token: str, mandate: dict | None = None,
                      cart: dict | None = None, closed_mandate: dict | None = None) -> dict:
    """Pay a session. An agent paying under a mandate must show it: the shop checks the signature,
    that it is the mandate the session was opened with, and that the total fits under its cap.
    With a signed `cart` (what the agent agreed to pay), the session must match it line by line."""
    s = SESSIONS.get(session_id)
    if not s:
        raise KeyError(session_id)
    if s["status"] != "ready_for_payment":
        raise ValueError(f"session is {s['status']}")
    if not payment_token:
        raise ValueError("payment_token required")
    total = s["totals"]["total_eur"]
    if mandate is not None:
        from agora.proof import verify_mandate
        if not verify_mandate(mandate):
            raise ValueError("mandate signature invalid")
        if s.get("mandate_id") and mandate.get("id") != s["mandate_id"]:
            raise ValueError("mandate does not match this checkout")
        cap = mandate.get("cap_eur")
        if cap is None:
            raise ValueError("mandate has no cap: the shop will not charge an agent without one")
        spent = SPENT_BY_MANDATE.get(str(mandate.get("id")), 0.0)
        if spent + total > float(cap) + 1e-9:
            raise ValueError(f"total {total} (+ {spent} already paid under this mandate) over mandate cap {cap}")
    if cart is not None:
        from agora.proof import cart_mismatch, verify_cart
        if not verify_cart(cart):
            raise ValueError("cart signature invalid")
        if cart.get("session_id") is not None and cart.get("session_id") != session_id:
            raise ValueError("cart was signed for another checkout session")
        if problems := cart_mismatch(cart, s):
            raise ValueError("; ".join(problems))
        if f"cart:{cart['signature']}" in USED_CLOSED:
            raise ValueError("this signed cart was already paid (replay refused)")
    if closed_mandate is not None:
        from agora.proof import verify_closed_mandate
        if not verify_closed_mandate(closed_mandate):
            raise ValueError("closed mandate signature invalid")
        if s.get("mandate_id") and closed_mandate.get("open_mandate_id") != s["mandate_id"]:
            raise ValueError("closed mandate is not under this checkout's mandate")
        if abs(float(closed_mandate.get("total_eur") or 0) - total) > 0.005:
            raise ValueError("closed mandate total does not match the checkout")
        if closed_mandate.get("session_id") is not None and closed_mandate.get("session_id") != session_id:
            raise ValueError("closed mandate was signed for another checkout session")
        if cart is not None and closed_mandate.get("cart_signature") != cart.get("signature"):
            raise ValueError("closed mandate does not point at this cart")
        if f"closed:{closed_mandate.get('id')}" in USED_CLOSED:
            raise ValueError("this closed mandate was already paid (replay refused)")
    if s.get("mandate_id"):   # opened under a mandate: all three proofs are required, no opt-out
        missing = [n for n, v in (("mandate", mandate), ("cart", cart), ("closed_mandate", closed_mandate))
                   if v is None]
        if missing:
            raise ValueError("this checkout was opened under a mandate: missing " + ", ".join(missing))
    for line in s["line_items"]:   # re-check stock and price at pay time
        p = get_product(line["id"])
        if p.stock < line["quantity"]:
            raise ValueError(f"out of stock: {p.id}")
    for line in s["line_items"]:
        if line.get("offer_code"):
            _redeemable_counter(line["offer_code"], line["id"])
    for line in s["line_items"]:
        PRODUCTS[line["id"]].stock -= line["quantity"]
        if line.get("offer_code"):
            COUNTERS[line["offer_code"]]["used"] = True
    s["status"] = "completed"
    if closed_mandate is not None:
        USED_CLOSED.add(f"closed:{closed_mandate.get('id')}")
    if cart is not None:
        USED_CLOSED.add(f"cart:{cart['signature']}")
    if mandate is not None and mandate.get("id"):
        mid = str(mandate["id"])
        SPENT_BY_MANDATE[mid] = round(SPENT_BY_MANDATE.get(mid, 0.0) + total, 2)
    order = {"id": f"ord_{uuid.uuid4().hex[:10]}", "session_id": session_id, "line_items": s["line_items"],
             "total_eur": s["totals"]["total_eur"], "mandate_id": s["mandate_id"], "buyer": s["buyer"],
             "payment": {"token_last4": payment_token[-4:], "rail": "mock"}, "status": "confirmed",
             "created_at": time.time()}
    private = [PRODUCTS[ln["id"]] for ln in s["line_items"]
               if ln["id"] in PRODUCTS and PRODUCTS[ln["id"]].seller_type == "private"]
    if private:   # a private seller is never paid directly: the money waits in escrow until pickup
        order["payment"]["rail"] = "escrow"
        order["escrow"] = {"status": "held", "release": "at pickup, when the body and serial match the photos",
                           "seller": private[0].seller, "listing_url": private[0].listing_url}
    ORDERS.append(order)
    s["order_id"] = order["id"]
    return order


# ---- HTTP -------------------------------------------------------------------

router = APIRouter(prefix=PREFIX, tags=["mockshop"])


class PriceIn(BaseModel):
    price_eur: float = Field(gt=0)
    fire: bool = True   # re-check watches pinned to this product right away (stage demo)


class LineIn(BaseModel):
    id: str
    quantity: int = Field(default=1, ge=1)
    offer_code: str | None = None


class IntentTraceIn(BaseModel):
    """ACP-style intent trace: why the agent walked away."""
    reason_code: str = "price_sensitivity"
    intent: str = "decline"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CancelIn(BaseModel):
    reason: str = ""
    intent_trace: IntentTraceIn | None = None


class BannerIn(BaseModel):
    text: str = ""


class CheckoutIn(BaseModel):
    items: list[LineIn]
    buyer: dict[str, Any] = Field(default_factory=dict)
    mandate_id: str | None = None


class CompleteIn(BaseModel):
    payment_token: str
    mandate: dict[str, Any] | None = None          # required when the session was opened under a mandate
    cart: dict[str, Any] | None = None
    closed_mandate: dict[str, Any] | None = None


class FeeIn(BaseModel):
    fee_eur: float = Field(ge=0)
    label: str = "handling fee"


def _public(p: Product) -> dict:
    return {"id": p.id, "title": p.title, "brand": p.brand, "price_eur": p.price_eur, "stock": p.stock,
            "condition": p.condition, "url": product_url(p.id),
            **({"seller": p.seller, "seller_type": p.seller_type, "listing_url": p.listing_url, "image": p.image}
               if p.seller_type != "shop" else {}),
            "price_log": [{"ts": t, "price_eur": v} for t, v in p.price_log]}


def _get_or_404(pid: str) -> Product:
    try:
        return get_product(pid)
    except KeyError:
        raise HTTPException(404, f"no product {pid}")


@router.get("/products")
def http_products() -> list[dict]:
    return [_public(p) for p in PRODUCTS.values()]


@router.get("/products/{pid}")
def http_product(pid: str) -> dict:
    return _public(_get_or_404(pid))


@router.post("/products/{pid}/price")
async def http_set_price(pid: str, body: PriceIn) -> dict:
    old = _get_or_404(pid).price_eur
    p = set_price(pid, body.price_eur)
    out: dict[str, Any] = {"product": _public(p), "old_price_eur": old, "watch_events": []}
    if body.fire:
        from agora import watch   # lazy: watch imports buy imports mockshop
        events = await watch.check_pinned(product_url(pid))
        out["watch_events"] = [{"type": e.type, "data": e.data} for e in events]
    return out


@router.post("/products/{pid}/hidden_fee")
def http_hidden_fee(pid: str, body: FeeIn) -> dict:
    """Demo toggle: a fee that only appears at checkout (0 turns it off)."""
    _get_or_404(pid)
    set_hidden_fee(pid, body.fee_eur, body.label)
    return {"product": pid, "hidden_fee": HIDDEN_FEES.get(pid)}


@router.post("/products/{pid}/feedback")
def http_feedback(pid: str, body: IntentTraceIn) -> dict:
    """An agent tells the shop why it did not buy. The shop may answer with a counter-offer."""
    _get_or_404(pid)
    return intent_feedback(pid, body.model_dump())


@router.post("/products/{pid}/page_banner")
def http_page_banner(pid: str, body: BannerIn) -> dict:
    """Demo toggle: text on the product page only (e.g. 'Loppuunmyyty'), JSON-LD unchanged."""
    _get_or_404(pid)
    set_page_banner(pid, body.text)
    return {"product": pid, "banner": PAGE_BANNERS.get(pid)}


@router.get("/counter_offers")
def http_counters() -> dict:
    return {"counter_offers": list(COUNTERS.values()), "feedback": FEEDBACK}


@router.get("/p/{pid}", response_class=HTMLResponse)
def http_product_page(pid: str) -> str:
    """A real-looking product page with schema.org JSON-LD, so agora.reader can read it for free."""
    _get_or_404(pid)
    return page_html(pid)


def page_html(pid: str) -> str:
    p = get_product(pid)
    ld = {"@context": "https://schema.org", "@type": "Product", "name": p.title, "sku": p.id,
          "brand": {"@type": "Brand", "name": p.brand},
          "offers": {"@type": "Offer", "price": f"{p.price_eur:.2f}", "priceCurrency": "EUR",
                     "itemCondition": "https://schema.org/" + ("UsedCondition" if p.condition == "used"
                                                               else "NewCondition"),
                     "availability": "https://schema.org/" + ("InStock" if p.stock > 0 else "OutOfStock")}}
    title = html.escape(p.title)
    banner = f"<p class='banner'>{html.escape(PAGE_BANNERS[pid])}</p>" if pid in PAGE_BANNERS else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
            f"<script type='application/ld+json'>{json.dumps(ld)}</script></head>"
            f"<body><h1>{title}</h1><p class='price'>€{p.price_eur:.2f}</p>"
            f"<p>{'In stock' if p.stock > 0 else 'Sold out'} ({p.stock})</p>{banner}</body></html>")


def page_text(pid: str) -> str:
    """What a person sees on the product page (no markup, no JSON-LD)."""
    body = page_html(pid).split("<body>", 1)[-1]
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


@router.post("/checkout_sessions")
def http_create_checkout(body: CheckoutIn) -> dict:
    for it in body.items:
        _get_or_404(it.id)
    try:
        return create_checkout([it.model_dump() for it in body.items], body.buyer, body.mandate_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/checkout_sessions/{sid}/cancel")
def http_cancel_checkout(sid: str, body: CancelIn) -> dict:
    """Cancel, optionally with an intent trace: the answer may carry a `counter_offer`."""
    try:
        return cancel_checkout(sid, body.reason, body.intent_trace.model_dump() if body.intent_trace else None)
    except KeyError:
        raise HTTPException(404, f"no session {sid}")


@router.get("/checkout_sessions/{sid}")
def http_get_checkout(sid: str) -> dict:
    if sid not in SESSIONS:
        raise HTTPException(404, f"no session {sid}")
    return SESSIONS[sid]


@router.post("/checkout_sessions/{sid}/complete")
def http_complete_checkout(sid: str, body: CompleteIn) -> dict:
    try:
        return complete_checkout(sid, body.payment_token, mandate=body.mandate, cart=body.cart,
                                 closed_mandate=body.closed_mandate)
    except KeyError:
        raise HTTPException(404, f"no session {sid}")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/orders")
def http_orders() -> list[dict]:
    return ORDERS


@router.post("/reset")
def http_reset() -> dict:
    reset()
    return {"ok": True}
