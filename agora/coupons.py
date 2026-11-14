"""COUPON STACK, read side: visible discount codes on a page or in its search snippet.
Written at Junction 2026. Idea: Gumroad's "best offer code" (pick the code that takes the most off);
our own code. The reader only EXPOSES what the page says (offer.raw["coupons"]); the judge decides
whether to subtract anything. Every coupon is unverified: we never try a code at a checkout.

Shapes we read (EN/FI/SV/DE/FR/NL/ES/IT):
  "Use code SAVE10 for 10% off"   "10% off with code SAVE10"   "€20 off with code BLACK20"
  "-15 % koodilla KEVAT15"        "Rabattcode: SOMMER15 (15 %)"  "alennuskoodi: TALVI20 -20 %"
"""
from __future__ import annotations

import re
from typing import Any

MAX_COUPONS = 5

_KEYWORD = (r"(?i:promo(?:tion(?:al)?)?\s*code|discount\s*code|coupon(?:\s*code)?|voucher(?:\s*code)?|"
            r"offer\s*code|use\s*code|with\s*(?:the\s*)?code|enter\s*code|code|"
            r"alennuskoodi(?:lla)?|kampanjakoodi(?:lla)?|koodilla|koodi|"
            r"rabattcode|gutscheincode|gutschein|mit\s*dem\s*code|"
            r"rabattkod(?:en)?|kampanjkod(?:en)?|med\s*koden|"
            r"code\s*promo|avec\s*le\s*code|kortingscode|c[oó]digo(?:\s*promocional)?|codice(?:\s*sconto)?)")
# codes are written in capitals on real pages; case-sensitive so ordinary words do not match
_CODE = r"(?P<code>[A-Z0-9][A-Z0-9_-]{2,18}[A-Z0-9])"
CODE_AFTER_KEYWORD = re.compile(_KEYWORD + r"\s*[:=\-–]?\s*[\"'“”‘’«»]?\s*" + _CODE + r"\b")

PERCENT = re.compile(r"(?<![\d.,])(?P<pct>\d{1,2}(?:[.,]\d)?)\s?%")
AMOUNT = re.compile(r"(?:(?P<cur1>€|£|\$|EUR|SEK|kr)\s?(?P<a1>\d{1,4}(?:[.,]\d{2})?)|"
                    r"(?P<a2>\d{1,4}(?:[.,]\d{2})?)\s?(?P<cur2>€|£|\$|EUR\b|eur\b|kr\b|SEK\b))")
OFF_CUE = re.compile(r"(?i)\b(off|discount|alennus|ale|pois|rabatt|rabais|korting|descuento|sconto|säästä|spara|save)\b|(?<!\w)-\s?\d")

NOT_CODES = {"EUR", "USD", "GBP", "SEK", "NOK", "DKK", "VAT", "ALV", "MWST", "SKU", "EAN", "UPC", "GTIN", "MPN",
             "HTTP", "HTTPS", "HTML", "FAQ", "FREE", "SALE", "NEW", "USED", "SIZE", "COLOR", "BLACK", "WHITE",
             "SHOP", "CART", "OK", "INFO", "HELP", "LOGIN", "HOME", "MORE", "NONE", "NULL", "TRUE", "FALSE"}
_CUR = {"€": "EUR", "eur": "EUR", "EUR": "EUR", "£": "GBP", "$": "USD", "kr": "SEK", "SEK": "SEK"}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _is_code(code: str) -> bool:
    if code.upper() in NOT_CODES or code.isdigit():
        return False
    if re.fullmatch(r"[A-Z]{1,3}\d{3,}", code) and len(code) > 8:   # looks like an SKU / part number
        return False
    return any(c.isalpha() for c in code)


def find_coupons(text: str, where: str = "page", price: float | None = None) -> list[dict[str, Any]]:
    """Discount codes in plain text with what they take off, nearest figure wins.
    -> [{code, percent | amount + currency, text, where, verified: False}]"""
    if not text:
        return []
    out: dict[str, dict[str, Any]] = {}
    for m in CODE_AFTER_KEYWORD.finditer(text):
        code = m.group("code")
        if not _is_code(code) or code in out:
            continue
        a, b = max(0, m.start() - 70), min(len(text), m.end() + 70)
        window = text[a:b]
        centre = m.start("code") - a
        best: tuple[int, dict[str, Any]] | None = None
        for p in PERCENT.finditer(window):
            v = _num(p.group("pct"))
            if 1 <= v <= 90:
                d = abs(p.start() - centre)
                if best is None or d < best[0]:
                    best = (d, {"percent": v})
        for q in AMOUNT.finditer(window):
            raw_amt = q.group("a1") or q.group("a2")
            cur = _CUR.get(q.group("cur1") or q.group("cur2") or "", "EUR")
            v = _num(raw_amt)
            near = window[max(0, q.start() - 25):q.end() + 25]
            if v <= 0 or not OFF_CUE.search(near):
                continue   # a plain price next to the code is not what the code takes off
            if price is not None and v >= price * 0.9:
                continue
            d = abs(q.start() - centre)
            if best is None or d < best[0]:
                best = (d, {"amount": v, "currency": cur})
        if best is None:
            continue       # a code with no stated value: nothing to subtract, nothing to show
        snippet = re.sub(r"\s+", " ", window).strip()
        out[code] = {"code": code, **best[1], "text": snippet[:160], "where": where, "verified": False}
        if len(out) >= MAX_COUPONS:
            break
    return list(out.values())


def best_saving(coupons: list[dict[str, Any]], price: float | None) -> float | None:
    """What the best single code would take off `price` (codes do not stack unless a shop says so)."""
    if not coupons or not price:
        return None
    vals = [c["percent"] / 100 * price if "percent" in c else c.get("amount", 0.0) for c in coupons]
    v = max(vals)
    return round(v, 2) if v > 0 else None
