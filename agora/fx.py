"""Currency -> EUR. Written at Junction 2026.

Rates come from frankfurter.app (ECB reference rates, free, no key), cached for a day in
`.cache/fx.json`. If the network is off (AGORA_OFFLINE=1) or the call fails we fall back to a
static table, so `to_eur` always answers for the common currencies.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

import httpx

FRANKFURTER = "https://api.frankfurter.dev/v1/latest?from=EUR"   # .app 301s here since 2025
MAX_AGE_S = 24 * 3600

# 1 EUR = x units. Rough mid-2026 values, used only when live rates are unavailable.
STATIC_RATES: dict[str, float] = {
    "EUR": 1.0, "USD": 1.12, "GBP": 0.85, "SEK": 11.0, "NOK": 11.7, "DKK": 7.46, "CHF": 0.94,
    "PLN": 4.25, "CZK": 25.0, "HUF": 400.0, "RON": 5.0, "BGN": 1.956, "ISK": 145.0, "JPY": 165.0,
    "CNY": 8.1, "CAD": 1.55, "AUD": 1.72, "TRY": 45.0, "INR": 96.0, "KRW": 1550.0,
    "ZAR": 20.5, "HKD": 8.75, "SGD": 1.48, "NZD": 1.9, "TWD": 36.0, "MXN": 21.0, "BRL": 6.2, "AED": 4.1,
    "ILS": 4.1, "THB": 38.0,
}

SYMBOLS: dict[str, str] = {
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "$": "USD", "us$": "USD", "usd": "USD",
    "£": "GBP", "gbp": "GBP", "zł": "PLN", "zl": "PLN", "pln": "PLN", "kč": "CZK", "czk": "CZK",
    "ft": "HUF", "chf": "CHF", "¥": "JPY", "c$": "CAD", "ca$": "CAD", "a$": "AUD", "au$": "AUD",
    "lei": "RON", "₺": "TRY", "₹": "INR", "₩": "KRW", "r": "ZAR", "zar": "ZAR", "hk$": "HKD", "s$": "SGD",
    "nz$": "NZD", "nt$": "TWD",
}

# "kr" means a different currency per country; decide from the shop's TLD.
KR_BY_TLD = {"se": "SEK", "no": "NOK", "dk": "DKK", "is": "ISK"}

# Default currency of a shop by top-level domain (when the page names none).
TLD_CURRENCY = {
    "fi": "EUR", "de": "EUR", "fr": "EUR", "es": "EUR", "it": "EUR", "nl": "EUR", "be": "EUR",
    "at": "EUR", "ie": "EUR", "pt": "EUR", "ee": "EUR", "lv": "EUR", "lt": "EUR", "sk": "EUR",
    "si": "EUR", "gr": "EUR", "lu": "EUR", "mt": "EUR", "cy": "EUR", "hr": "EUR", "eu": "EUR",
    "se": "SEK", "no": "NOK", "dk": "DKK", "is": "ISK", "uk": "GBP", "pl": "PLN", "cz": "CZK",
    "hu": "HUF", "ro": "RON", "bg": "BGN", "ch": "CHF", "us": "USD", "ca": "CAD", "au": "AUD",
    "jp": "JPY", "za": "ZAR", "hk": "HKD", "sg": "SGD", "nz": "NZD", "tw": "TWD",
}

_rates: dict[str, float] | None = None
_rates_source = "static"


def _cache_file() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or pathlib.Path(__file__).resolve().parent.parent / ".cache")
    root.mkdir(parents=True, exist_ok=True)
    return root / "fx.json"


def _offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def _load_cached() -> dict[str, float] | None:
    try:
        entry = json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return None
    if time.time() - entry.get("saved_at", 0) > MAX_AGE_S and not _offline():
        return None
    return entry.get("rates")


def _save(rates: dict[str, float]) -> None:
    _cache_file().write_text(json.dumps({"saved_at": time.time(), "rates": rates}))


def _fetch_sync() -> dict[str, float] | None:
    try:
        r = httpx.get(FRANKFURTER, timeout=4, follow_redirects=True)
        r.raise_for_status()
        rates = {k.upper(): float(v) for k, v in r.json()["rates"].items()}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None
    rates["EUR"] = 1.0
    return rates


async def refresh_rates() -> str:
    """Fetch today's rates (async, call once at hunt start). Returns the source used."""
    global _rates, _rates_source
    if _offline():
        rates()
        return _rates_source
    try:
        async with httpx.AsyncClient(timeout=4, follow_redirects=True) as c:
            r = await c.get(FRANKFURTER)
            r.raise_for_status()
            fresh = {k.upper(): float(v) for k, v in r.json()["rates"].items()}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        rates()
        return _rates_source
    fresh["EUR"] = 1.0
    _save(fresh)
    _rates, _rates_source = {**STATIC_RATES, **fresh}, "frankfurter"
    return _rates_source


def rates() -> dict[str, float]:
    """1 EUR = x units, for every known currency. Memory -> disk cache -> live (once) -> static."""
    global _rates, _rates_source
    if _rates is not None:
        return _rates
    cached = _load_cached()
    if cached is None and not _offline():
        cached = _fetch_sync()
        if cached:
            _save(cached)
    if cached:
        _rates, _rates_source = {**STATIC_RATES, **cached}, "frankfurter"
    else:
        _rates, _rates_source = dict(STATIC_RATES), "static"
    return _rates


def source() -> str:
    rates()
    return _rates_source


def normalize_currency(cur: str | None, domain: str | None = None) -> str | None:
    """'€' / 'eur' / 'kr' (+ domain) -> ISO code. None if unknown."""
    if not cur:
        return tld_currency(domain) if domain else None
    c = cur.strip().lower().rstrip(".")
    if c in ("kr", "kr.", ":-"):
        tld = (domain or "").rsplit(".", 1)[-1].lower()
        return KR_BY_TLD.get(tld, "SEK")
    if c in SYMBOLS:
        return SYMBOLS[c]
    if len(c) == 3 and c.isalpha():
        return c.upper()
    return None


def tld_currency(domain: str | None) -> str | None:
    if not domain:
        return None
    return TLD_CURRENCY.get(domain.lower().rstrip("/").rsplit(".", 1)[-1])


# Locale segments in shop URLs (backmarket.com/en-us/, nintendo.com/us/, apple.com/ca/): a .com page
# with no currency on it is priced in the locale's currency, not in euros.
LOCALE_CURRENCY = {"us": "USD", "ca": "CAD", "gb": "GBP", "uk": "GBP", "au": "AUD", "nz": "NZD",
                   "ch": "CHF", "se": "SEK", "no": "NOK", "dk": "DKK", "pl": "PLN", "cz": "CZK",
                   "hu": "HUF", "jp": "JPY", "sg": "SGD", "hk": "HKD", "za": "ZAR"}
_LOCALE_SEG = None


def locale_currency(url: str | None) -> str | None:
    """'https://www.backmarket.com/en-us/p/x' -> 'USD'; '/de-de/' or no locale -> None (the TLD decides)."""
    global _LOCALE_SEG
    if not url:
        return None
    if _LOCALE_SEG is None:
        import re
        _LOCALE_SEG = re.compile(r"^/(?:[a-z]{2}[-_])?([a-z]{2})(?:/|$)", re.I)
    from urllib.parse import urlsplit
    m = _LOCALE_SEG.match(urlsplit(url).path)
    return LOCALE_CURRENCY.get(m.group(1).lower()) if m else None


def to_eur(amount: float | None, currency: str | None) -> float | None:
    """Convert to EUR, rounded to cents. None if the amount or currency is unknown."""
    if amount is None:
        return None
    code = normalize_currency(currency)
    if code is None:
        return None
    rate = rates().get(code)
    if not rate:
        return None
    return round(float(amount) / rate, 2)
