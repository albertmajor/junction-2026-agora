"""JUDGE: trust, TRUE COST, haggle, verdict.

TRUE COST over a horizon (default 12 months):
    sticker + extras (shipping, import VAT) - expected resale at month N  =  total  ->  per month
Expected resale = median used price of the same Thing today, aged N months at the category's
depreciation rate. No used comps? Fall back to "new price x typical used discount", aged the same
way, and say so (confidence low). Every number is a receipt line and the basis says where it came from.

Honesty rules (round 1):
- one market median per Thing and condition, used by trust flags, haggle and resale alike;
- a price is checked against a second witness (search snippet, other read step) when we have one;
  a disputed price, or one far under the market with no second witness, is shown but never costed;
- shops outside the EU: their own VAT comes off on export, Finnish import VAT goes on;
- every converted price says which FX rate it used;
- every losing offer learns its "price to beat".

Round 3:
- PRICE BAND per Thing and condition (p25-p75 of today's market plus our snapshot history): every offer
  is "low | typical | high" with Keepa-style badges ("lowest seen in 41 days", "-12% vs 30-day avg");
- FAKE DISCOUNT (EU Omnibus 30-day rule): a "was €X" above anything we saw in 30 days is "discount inflated";
- TRUST SIGNALS from agora.trust: the same photo on another seller's listing, a look-alike shop name,
  a young domain (WHOIS) -> flags and hard trust caps;
- a product-format price far under the market that nothing else backs is disputed, not believed
  (mpb.com read as €239 for a used A7 III); title/snippet prices are witnesses too;
- one page showing a gross and a net (ex-VAT) price is ONE offer, with both prices shown.
"""
from __future__ import annotations

import dataclasses
import os
import re
import statistics
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agora.models import Haggle, Need, Offer, Thing, TrueCost, Verdict

DEFAULT_MONTHS = 12

# ---------------------------------------------------------------- categories

@dataclass(frozen=True)
class Category:
    name: str
    rate: float           # yearly value loss once used (0.12 = -12%/yr)
    used_factor: float    # used price / new price for a typical used unit (fallback when no comps)
    pattern: str          # keywords (regex, matched on need + titles)


CATEGORIES: list[Category] = [
    Category("phone", 0.25, 0.65, r"iphone|galaxy s|galaxy z|pixel \d|smartphone|\bphone\b|puhelin|oneplus|xiaomi"),
    Category("tablet", 0.20, 0.65, r"ipad|tablet|galaxy tab|surface pro"),
    Category("laptop", 0.20, 0.60, r"macbook|laptop|notebook|thinkpad|chromebook|kannettava|zenbook|xps"),
    Category("camera", 0.12, 0.70, r"camera|kamera|\ba7|alpha|eos|nikon z|fujifilm|x100|mirrorless|dslr|gopro|ilce|lumix"),
    Category("lens", 0.07, 0.75, r"\blens\b|objektiivi|\d+-\d+\s?mm|f/?\d\.\d"),
    Category("console", 0.15, 0.70, r"playstation|ps5|xbox|nintendo|switch|steam deck"),
    Category("tv", 0.25, 0.50, r"\btv\b|television|oled|qled|televisio"),
    Category("audio", 0.25, 0.55, r"headphone|airpods|earbuds|wh-?1000|speaker|soundbar|kuulokkeet"),
    Category("wearable", 0.30, 0.55, r"watch|garmin|fitbit|polar|suunto|wearable"),
    Category("appliance", 0.15, 0.50, r"washing|pesukone|dishwasher|fridge|freezer|dryer|oven|vacuum|dyson|roborock|espresso|coffee|microwave|imuri"),
    Category("bike", 0.10, 0.60, r"\bbike\b|bicycle|pyörä|fahrrad|brompton|cargo"),
    Category("ebike", 0.15, 0.55, r"e-?bike|electric bike|sähköpyörä"),
    Category("furniture", 0.20, 0.40, r"sofa|chair|table|desk|bed\b|wardrobe|ikea|sohva|tuoli"),
    Category("car", 0.15, 0.80, r"\bcar\b|auto|tesla|volvo|toyota|bmw|audi|volkswagen"),
    Category("tools", 0.10, 0.60, r"drill|makita|dewalt|festool|saw\b|porakone"),
    Category("luxury watch", 0.03, 0.85, r"rolex|omega|tudor|patek"),
]
DEFAULT_CATEGORY = Category("other", 0.18, 0.60, "")

# marketplaces / classifieds: a listing there is only as good as its seller, and it can be haggled
MARKETPLACES = ("ebay.", "tori.fi", "huuto.net", "facebook.", "kleinanzeigen.", "blocket.", "vinted.",
                "craigslist.", "marktplaats.", "leboncoin.", "subito.", "olx.", "allegro.", "mercari.", "kijiji.",
                "finn.no", "dba.dk", "gumtree.", "wallapop.", "willhaben.", "2dehands.", "tradera.", "swappa.")
KNOWN_SHOPS = ("amazon.", "bhphotovideo.", "verkkokauppa.", "gigantti.", "power.", "mediamarkt.", "apple.",
               "sony.", "jimms.", "proshop.", "fotosidan.", "rajala", "japanphoto.", "currys.", "argos.",
               "walmart.", "bestbuy.", "adorama.", "kenmorecamera.", "backmarket.", "swappie.", "refurbed.",
               "cyberport.", "foto-erhardt.", "calumet", "wexphotovideo.", "elgiganten.", "komplett.", "ikea.")

FX_FALLBACK = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "SEK": 0.087, "NOK": 0.086, "DKK": 0.134,
               "CHF": 1.05, "PLN": 0.23, "CZK": 0.040, "HUF": 0.0025, "JPY": 0.0061}


def category_for(text: str) -> Category:
    low = text.lower()
    # ebike before bike, lens only when it is clearly a lens (not "camera with lens")
    if re.search(CATEGORIES[11].pattern, low):
        return CATEGORIES[11]
    for c in CATEGORIES:
        if c.name == "lens" and re.search(r"camera|kamera|body|a7|eos", low):
            continue
        if re.search(c.pattern, low):
            return c
    return DEFAULT_CATEGORY


# ---------------------------------------------------------------- money helpers

def eur(amount: float | None, currency: str | None) -> float | None:
    if amount is None:
        return None
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return float(amount)
    try:
        from agora import fx  # lazy: another agent owns it
        v = fx.to_eur(amount, cur)
        if v is not None:
            return float(v)
    except Exception:
        pass
    rate = FX_FALLBACK.get(cur)
    return round(amount * rate, 2) if rate else None


def price_of(o: Offer) -> float | None:
    if o.price_eur is None and o.price is not None:
        o.price_eur = eur(o.price, o.currency)
    return o.price_eur


def fmt(x: float) -> str:
    return f"€{x:,.0f}" if abs(x) >= 10 else f"€{x:,.2f}".rstrip("0").rstrip(".")


def fmt_rate(x: float) -> str:
    """A unit rate keeps its cents (€49.90/h, not €50/h): it is what the provider's page says."""
    return f"€{x:,.2f}" if abs(x) < 100 and round(x, 2) != round(x) else fmt(x)


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _round_nice(x: float) -> float:
    step = 5 if x < 200 else 10 if x < 2000 else 50
    return float(round(x / step) * step)


def fx_note(o: Offer) -> tuple[str, bool] | None:
    """('FX: 1 GBP = €1.18 (static fallback rate)', is_static) for a converted price, else None."""
    cur = (o.currency or "EUR").upper()
    if cur == "EUR" or o.price_eur is None:
        return None
    try:
        from agora import fx
        rate = fx.rates().get(cur)
        src = fx.source()
    except Exception:
        return None
    if not rate:
        return None
    static = src != "frankfurter"
    where = "static fallback rate, not today's" if static else "ECB reference rate via frankfurter"
    return f"FX: 1 {cur} = €{1 / rate:.3g} ({where})", static


# ---------------------------------------------------------------- MARKET (one median for everyone)

CROSS_CONDITION_FLOOR = 0.35   # used/refurb under 35% of the cheapest new: suspect when comps are thin


def _disputed(o: Offer) -> bool:
    return o.raw.get("price_check") == "disputed"


MIN_COMPS = 2          # fewer used listings than this: resale comes from the category's depreciation
SCALE_FLOOR = 0.25     # a price under 25% of the item's overall median is a part/accessory or a misread


def _list_offer(o: Offer) -> bool:
    """A search/category page read as one offer (tori.fi/search?q=...): never a market data point."""
    if o.raw.get("list_page"):
        return True
    try:
        from agora.discover import is_list_page
        return bool(is_list_page(o.url))
    except Exception:
        return False


def market_floor(offers: list[Offer]) -> float:
    """The price under which an offer cannot be the item (ear tips at €10 among €170 AirPods, an OLED
    panel at €90 among €300 consoles): SCALE_FLOOR x the median over all conditions. 0 = too few prices."""
    prices = [p for x in offers if x.condition in ("new", "used", "refurbished")
              and (p := price_of(x)) is not None and p > 1 and not _disputed(x) and not _list_offer(x)]
    if len(prices) < 3:
        return 0.0
    return SCALE_FLOOR * statistics.median(prices)


def market_prices(offers: list[Offer], condition: str) -> list[float]:
    """Prices of one condition that describe the market: no disputed prices, no search/list pages, no
    'from' prices, nothing under the item's price floor (parts, accessories), used ones not dearer than
    new (bundles, wishful sellers), and the far outliers (< half or > 2.5x the median) dropped once.
    Trust flags, haggle bands and resale all use this same set, so they quote the same median."""
    floor = market_floor(offers)
    sel = [x for x in _one_vote_per_listing(offers) if x.condition == condition
           and (p := price_of(x)) is not None and p > 1 and p >= floor and not _disputed(x)
           and not _list_offer(x) and not x.raw.get("from_price")]
    if condition == "service":
        votes: dict[str, list[float]] = {}
        for x in sel:   # one directory page = one voice in the median, however many providers it listed
            votes.setdefault(_directory_key(x), []).append(price_of(x) or 0.0)
        prices = [statistics.median(v) for v in votes.values()]
    else:
        prices = [price_of(x) or 0.0 for x in sel]
    if condition == "used":
        new = [p for x in offers if x.condition == "new" and (p := price_of(x)) is not None and not _disputed(x)
               and x.in_stock is not False and p >= floor and not _list_offer(x)]
        new = _trim(new)
        if new:
            prices = [p for p in prices if p <= min(new) * 1.05]
    return _trim(prices)


def _one_vote_per_listing(offers: list[Offer]) -> list[Offer]:
    """One shop listing the same unit at the same price on two URLs (walmart: two 'Restored iPhone 15'
    pages at €145) is one data point, not two: otherwise a suspect price outvotes the market."""
    seen: set[tuple[str, str, int]] = set()
    out: list[Offer] = []
    for x in offers:
        p = price_of(x)
        # listings cut from a marketplace search page are separate sellers: one vote each
        key = (x.url if x.raw.get("from_list_page") else _host(x.url), x.condition, round(p) if p is not None else -1)
        if p is not None and key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _trim(prices: list[float]) -> list[float]:
    if len(prices) < 3:
        return prices
    med = statistics.median(prices)
    return [p for p in prices if 0.5 * med <= p <= 2.5 * med]


def used_comps(thing_offers: list[Offer], exclude: Offer | None = None) -> list[float]:
    """Used prices for the Thing (the resale basis). Same set as the trust flags' used median.
    `exclude`: the offer being costed is never its own comp (tori €395 -> 'resale from 1 listing, €395')."""
    if exclude is not None:
        thing_offers = [x for x in thing_offers if x is not exclude]
    return market_prices(thing_offers, "used")


def resale_comps(thing_offers: list[Offer], exclude: Offer | None = None) -> list[float]:
    """The comps resale may lean on: MIN_COMPS or more, and at least one that is not the offer being
    costed (`exclude`), else none and the category rate is the honest guess. The set itself is the one
    market median everyone quotes, so it keeps the costed offer's own price when there are others."""
    comps = used_comps(thing_offers)
    if len(comps) < MIN_COMPS or (exclude is not None and not used_comps(thing_offers, exclude)):
        return []
    return comps


def _comp_urls(thing_offers: list[Offer], exclude: Offer | None = None) -> list[str]:
    comps = set(resale_comps(thing_offers, exclude))
    return [x.url for x in thing_offers if x.condition == "used"
            and not _list_offer(x) and price_of(x) in comps][:8]


# ---------------------------------------------------------------- TWO WITNESSES

def _independent(o: Offer, w: dict[str, Any]) -> bool:
    """A second witness only counts when it is a different document: another page or another domain.
    The search engine's copy of the same page (old witnesses: via 'snippet') is the same source."""
    doc = str(w.get("doc") or w.get("url") or "")
    if doc and _host(doc) and _host(doc) != _host(o.url):
        return True
    if "independent" in w:
        return bool(w["independent"]) and bool(doc) and doc.split("#")[0] != o.url.split("#")[0]
    return w.get("via") not in ("snippet", "search_highlight")


def _host(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def verify_price(o: Offer) -> str | None:
    """Compare the read price with other witnesses (search snippet, a second read step, another page).
    Sets raw['price_check']:
      'verified'   an INDEPENDENT witness (another document or domain) agrees within 10%;
      'consistent' only the same page's search listing agrees (one source seen twice: not verification);
      'disputed'   a witness is > 40% off;  None otherwise.
    A 'from €X' price is a list price, never verified. Returns the flag text, if any."""
    p = price_of(o)
    others: list[tuple[str, float, bool]] = []
    for w in o.raw.get("witnesses") or []:
        if not isinstance(w, dict) or w.get("primary"):
            continue
        q = eur(w.get("price"), w.get("currency"))
        if q:
            others.append((str(w.get("via", "?")), q, _independent(o, w)))
    texts = text_prices(o) if p is not None and not any(via == "snippet" for via, _, _ in others) else []
    others += [("snippet", q, False) for q in texts]
    if p is None or not others:
        o.raw["price_check"] = None
        return None
    agree = [x for x in others if abs(x[1] - p) / p <= 0.10]
    indep = [x for x in agree if x[2]]
    if indep and not o.raw.get("from_price"):
        o.raw["price_check"] = "verified"
        return f"price verified x{1 + len(indep)} (independent sources)"
    if agree:
        o.raw["price_check"] = "consistent"
        return "price matches the search listing of the same page (one source, not independent)"
    real = others[:len(others) - len(texts)]
    # a read witness that is far off disputes; title/snippet text only when ALL its prices are far off
    via, q, indep = (max(real, key=lambda x: abs(x[1] - p)) if real
                     else min(others, key=lambda x: abs(x[1] - p)))
    if o.condition == "service" and not indep:
        # a rate (€45/h) vs a number in its own search listing (deduction cap €1,600, a monthly plan
        # €150): different units, not a disagreement about the price
        o.raw["price_check"] = None
        return None
    if abs(q - p) / max(p, q) > 0.40:
        o.raw["price_check"] = "disputed"
        return f"price disagrees: page {fmt(p)} vs {_VIA.get(via, via)} {fmt(q)}"
    o.raw["price_check"] = None
    return None


_TEXT_PRICE = re.compile(
    r"(?:€|eur\b|\$|£|usd\b|gbp\b)\s?\d[\d ,.]*\d|\d[\d ,.]*\d\s?(?:€|eur\b|\$|£|usd\b|gbp\b)|"
    r"(?:€|\$|£)\s?\d", re.I)
# amounts that are not the price of the item: savings, monthly plans, shipping thresholds
_NOT_A_PRICE_BEFORE = re.compile(r"(?:save|saves|off|discount|säästä|spare|sparen|over|above|yli|ab|"
                                 r"shipping|delivery|toimitus|cashback|deposit|-)\W{0,3}$", re.I)
_NOT_A_PRICE_AFTER = re.compile(r"^\W{0,2}(?:/\s?(?:mo|month|kk|kuukausi|week|day|h)|per\s|a\s?month|off\b|"
                                r"cashback|kk\b)", re.I)
_CUR_OF = {"€": "EUR", "eur": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP"}


def text_prices(o: Offer) -> list[float]:
    """The price (EUR) written in the offer's title and its search listing text: a same-page witness.
    reader.witness_price picks it: savings ('Save up to €434'), old prices ('was €749'), net prices,
    plans and thresholds are skipped; one that agrees with the page wins; a 'from €X' the page is above
    is no disagreement. [] when the text has no such price."""
    if o.read_via == "search_highlight":
        return []                       # the price came from that very text
    text = f"{o.title or ''} | {o.raw.get('search_text') or ''}"
    try:
        from agora.reader import witness_price
    except ImportError:
        witness_price = None  # type: ignore[assignment]
    if witness_price is not None:
        w = witness_price(text, o.price, _host(o.url))
        if w is None:
            return []
        q = eur(w[0], w[1] or o.currency or "EUR")
        return [q] if q else []
    out: list[float] = []
    try:
        from price_parser import Price
    except ImportError:
        return []
    for m in _TEXT_PRICE.finditer(text):
        if _NOT_A_PRICE_BEFORE.search(text[max(0, m.start() - 14):m.start()]):
            continue
        if _NOT_A_PRICE_AFTER.search(text[m.end():m.end() + 14]):
            continue
        pr = Price.fromstring(m.group(0))
        if pr.amount is None or pr.amount <= 1:
            continue
        sym = next((k for k in _CUR_OF if k in m.group(0).lower()), None)
        q = eur(float(pr.amount), _CUR_OF.get(sym or "", o.currency or "EUR"))
        if q:
            out.append(q)
    return out


_VIA = {"snippet": "search", "jsonld": "page data", "contextdev_product": "product read",
        "contextdev_json": "page read", "regular_price": "list price"}


# ---------------------------------------------------------------- TRUST

def _domain_in(source: str, names: tuple[str, ...]) -> bool:
    s = (source or "").lower()
    return any(n in s for n in names)


def assess_trust(o: Offer, peers: list[Offer], *, photos: dict[int, list[Offer]] | None = None,
                 discount: str | None = None, floor: float = 0.0) -> tuple[float, list[str]]:
    """0..1 plus human-readable flags. `peers` = the offers for the same Thing (may include `o`).
    `photos` = agora.trust.same_photo_groups over the hunt (computed once by judge); `discount` = a
    'discount inflated' flag from `discount_check`."""
    score = 1.0
    cap = 1.0
    flags: list[str] = []
    p = price_of(o)

    if o.price is None:
        score -= 0.4
        flags.append("no price on the page")
    elif o.price <= 1:
        score -= 0.5
        flags.append(f"placeholder price ({o.price:g})")
    elif p is None:
        score -= 0.15
        flags.append(f"price in {o.currency or 'unknown currency'} could not be converted")
    if o.price is not None and not o.currency:
        score -= 0.1
        flags.append("currency not stated")

    check = verify_price(o)
    if check and o.raw.get("price_check") == "verified":
        score += 0.05
        flags.append(check)
    elif check and o.raw.get("price_check") == "consistent":
        flags.append(check)
    elif check:
        score -= 0.3
        flags.append(check)
    if o.raw.get("from_price"):
        score -= 0.05
        flags.append("from-price, not a specific unit")

    pool = peers if any(x is o for x in peers) else peers + [o]
    floor = max(floor, market_floor(pool))
    if (p and floor and p < floor and o.condition in ("new", "used", "refurbished")
            and o.raw.get("price_check") != "verified"):
        # ear tips (€10) among €170 AirPods, an OLED panel (€90) among €300 consoles: not the item
        score -= 0.5
        flags.append(f"too good to be true: {fmt(p)} is under a quarter of this item's going price "
                     f"({fmt(floor / SCALE_FLOOR)} median): probably a part, an accessory or a misread")
    # services: an hourly rate is compared with hourly rates, never with a €3/m² line
    same = market_prices([x for x in pool if x.unit == o.unit] if o.condition == "service" else pool, o.condition)
    med_same = _median(same)
    # services: a 'median' of 2 job prices (a €15 surcharge line and an €80 estimate) is no market
    if p and med_same and len(same) >= (3 if o.condition == "service" else 2) and not _disputed(o):
        r = p / med_same
        if r < 0.5:
            score -= 0.5
            flags.append(f"too good to be true: {1 - r:.0%} under the {o.condition} median ({fmt(med_same)})")
        elif r < 0.7:
            score -= 0.2
            flags.append(f"well under the usual {o.condition} price ({1 - r:.0%} below {fmt(med_same)})")
        elif r > 2.5:
            score -= 0.1
            flags.append(f"priced {r:.1f}x the {o.condition} median ({fmt(med_same)})")
        if r < 0.5 and o.read_via == "contextdev_product" and o.raw.get("price_check") not in ("verified", "consistent"):
            # the product format sometimes reads another item's price off the page (mpb: €239 for an A7 III)
            o.raw["price_check"] = "disputed"
            texts = text_prices(o)
            seen = f"; the listing text says {', '.join(fmt(x) for x in texts[:2])}" if texts else \
                "; nothing in the title or search listing backs it"
            flags.append(f"price disagrees: product read {fmt(p)} vs the {o.condition} market {fmt(med_same)}{seen} "
                         f"(probably another item's price on the page)")

    if (p and o.condition in ("used", "refurbished") and not _disputed(o)
            and not any(f.startswith("too good to be true") for f in flags)
            and (new_ref := market_prices(pool, "new"))):
        # too few comps of its own condition (early in a hunt): a used/refurb price far under the
        # cheapest NEW one is the same warning sign (mpb's €239 for a €1,029 camera)
        r = p / min(new_ref)
        if r < CROSS_CONDITION_FLOOR:
            score -= 0.5
            flags.append(f"too good to be true: {1 - r:.0%} under the cheapest new ({fmt(min(new_ref))}); "
                         + (f"too few {o.condition} listings to compare yet" if len(same) < 2 else
                          f"the {o.condition} listings around it may be odd too"))
            if o.read_via == "contextdev_product" and o.raw.get("price_check") not in ("verified", "consistent"):
                o.raw["price_check"] = "disputed"
                flags.append(f"price disagrees: product read {fmt(p)} vs new from {fmt(min(new_ref))} "
                             f"(probably another item's price on the page)")

    used = market_prices(pool, "used")
    new = market_prices(pool, "new")
    if p and o.condition == "new" and len(used) >= 2 and p < 0.8 * (_median(used) or 0):
        score -= 0.3
        flags.append(f"'new' but cheaper than used ones ({fmt(_median(used) or 0)} median used)")
    if p and o.condition == "used" and new and p > min(new):
        flags.append(f"costs more than new ({fmt(min(new))})")

    if outside_eu(o):
        ships = ships_to_fi(o)
        where = {True: "ships to Finland", False: "does not ship to Finland"}.get(ships, "shipping to Finland unconfirmed")  # type: ignore[call-overload]
        flags.append(f"outside the EU ({o.currency}): import VAT added, {where}")
        if ships is False:
            score -= 0.5
    grey = grey_import(o, pool)
    if grey:
        score -= 0.1
        flags.append(f"possible grey import: no EU warranty ({grey})")
    if o.in_stock is False:
        score -= 0.3
        flags.append("out of stock")
    if _domain_in(o.source, MARKETPLACES) and not o.seller:
        score -= 0.1
        flags.append("seller unknown")
    if o.condition == "unknown":
        score -= 0.05
        flags.append("condition not stated")
    if o.read_via == "search_highlight":
        score -= 0.1
        flags.append("price from a search snippet, not the page")
    if discount:
        score -= 0.1
        flags.append(discount)
    young_cheap = False
    for flag, penalty, limit in _trust_signals(o, pool, photos):
        score -= penalty
        flags.append(flag)
        if limit is not None:
            cap = min(cap, limit)
        if "days old" in flag and p and med_same and p < 0.7 * med_same:
            young_cheap = True
    if young_cheap:
        score -= 0.3
        flags.append("scam pattern: a brand-new shop selling far under the market")
    return round(max(0.0, min(cap, score)), 2), flags


def _trust_signals(o: Offer, pool: list[Offer], photos: dict[int, list[Offer]] | None) -> list[tuple[str, float, float | None]]:
    """agora.trust signals (photo reuse, look-alike name, young domain). Never raises."""
    out: list[tuple[str, float, float | None]] = []
    try:
        from agora import trust
        out += trust.assess(o, pool, photos=photos)
    except Exception:
        pass
    try:   # seller reviews (agora.reviews), cache only: a "watch out" shop is capped under the risky line
        from agora import reviews
        out += reviews.signals_for(o)
    except Exception:
        pass
    return out


def _seen_counts(sources: list[str]) -> dict[str, int]:
    """How many earlier hunts saw each shop (from the price history). Best effort, {} on any error."""
    try:
        from agora import store
        return store.domains_seen(sources)
    except Exception:
        return {}


# ---------------------------------------------------------------- PRICE BAND ("is this a good price?")

DAY = 86400.0
BAND_WINDOW_DAYS = 90
OMNIBUS_DAYS = 30


def _history(url: str, since: float) -> list[dict[str, Any]]:
    """Snapshots of one URL since `since` (agora.store). [] when the store is missing or fails."""
    try:
        from agora import store
        return [r for r in store.history(url, since) if r.get("price_eur")]
    except Exception:
        return []


def _band_points(offers: list[Offer], condition: str, unit: str | None, history: bool,
                 now: float) -> tuple[list[float], list[tuple[float, float]]]:
    """(today's market prices, [(seen_at, price)] from earlier hunts: one point per URL per day)."""
    group = [o for o in offers if o.condition == condition and (unit is None or (o.unit or None) == unit)]
    market = market_prices(group, condition)
    past: list[tuple[float, float]] = []
    if history:
        since = now - BAND_WINDOW_DAYS * DAY
        today = int(now // DAY)
        for url in sorted({o.url for o in group if not _disputed(o)}):
            per_day: dict[int, tuple[float, float]] = {}
            for r in _history(url, since):
                d = int(float(r["seen_at"]) // DAY)
                if d >= today:
                    continue            # today's price is already in the market set
                if d not in per_day or r["price_eur"] < per_day[d][1]:
                    per_day[d] = (float(r["seen_at"]), float(r["price_eur"]))
            past += per_day.values()
    return market, past


def band_for(offers: list[Offer], condition: str, *, unit: str | None = None, history: bool = True,
             now: float | None = None) -> dict[str, Any] | None:
    """The 'typical' price range for one condition of a Thing: p25-p75 over today's market plus our price
    snapshots of the last 90 days (same trimmed set as every median here). None below 3 data points."""
    now = time.time() if now is None else now
    market, past = _band_points(offers, condition, unit, history, now)
    points = _trim(market + [x for _, x in past])
    if len(points) < 3:
        return None
    days = max(1, round((now - min(t for t, _ in past)) / DAY)) if past else 0
    p25, p75 = _quantile(points, 0.25), _quantile(points, 0.75)
    basis = (f"{len(market)} {condition} price{'s' * (len(market) != 1)} today"
             + (f" + {len(past)} from our price history ({days} days)" if past else ""))
    return {"condition": condition, "unit": unit, "p25": round(p25, 2), "p75": round(p75, 2),
            "median": round(statistics.median(points), 2), "low_seen": round(min(points), 2),
            "n_market": len(market), "n_history": len(past), "days": days, "basis": basis}


def price_band(thing: Thing, *, history: bool = True, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Per condition (and per unit for services): {'used': {p25, p75, median, ...}, 'service/hour': {...}}."""
    out: dict[str, dict[str, Any]] = {}
    for cond, unit in sorted({(o.condition, o.unit if o.condition == "service" else None) for o in thing.offers},
                             key=lambda x: (x[0], x[1] or "")):
        b = band_for(thing.offers, cond, unit=unit, history=history, now=now)
        if b:
            out[cond if unit is None else f"{cond}/{unit}"] = b
    return out


def _band_key(o: Offer) -> str:
    return o.condition if o.condition != "service" or not o.unit else f"{o.condition}/{o.unit}"


def offer_band(o: Offer, bands: dict[str, dict[str, Any]], *, history: bool = True,
               now: float | None = None) -> dict[str, Any] | None:
    """Where this offer sits in its band: label low | typical | high, plus Keepa-style badges."""
    b = bands.get(_band_key(o))
    p = price_of(o)
    if not b or p is None or _disputed(o):
        return None
    now = time.time() if now is None else now
    label = "low" if p < b["p25"] * 0.995 else "high" if p > b["p75"] * 1.005 else "typical"
    what = _band_what(o)
    badges: list[str] = []
    if p <= b["low_seen"] * 1.001:
        badges.append(f"lowest seen in {b['days']} days" if b["n_history"] and b["days"] >= 1
                      else f"cheapest {what} right now")
    if label != "typical" and b["median"] and abs(p / b["median"] - 1) >= 0.05:   # "typical, -13%" reads as a contradiction
        badges.append(f"{p / b['median'] - 1:+.0%} vs typical {what} {fmt(b['median'])}")
    if history:
        own = [r["price_eur"] for r in _history(o.url, now - OMNIBUS_DAYS * DAY) if r["seen_at"] < now - 60]
        if len(own) >= 2:
            avg = statistics.mean(own)
            if abs(p / avg - 1) >= 0.05:
                badges.append(f"{p / avg - 1:+.0%} vs this shop's 30-day avg {fmt(avg)}")
    return {"label": label, "p25": b["p25"], "p75": b["p75"], "median": b["median"], "condition": b["condition"],
            "badges": badges, "basis": b["basis"], "what": what,
            "text": f"{label}: typical {what} is {fmt(b['p25'])}-{fmt(b['p75'])}"}


def _band_what(o: Offer) -> str:
    """What the band is about, in words: 'used', 'new', or for services 'hourly rate' / 'price per m²'."""
    if o.condition != "service":
        return o.condition
    return {"hour": "hourly rate", "m2": "price per m²", "job": "price per job", "visit": "price per visit"}.get(
        (o.unit or "").lower(), "service price")


def _was_price_eur(o: Offer) -> float | None:
    """The shop's 'was' / regular / list price in EUR, when it claims one."""
    raw = o.raw if isinstance(o.raw, dict) else {}
    for k in ("regular_price", "was_price", "list_price", "strikethrough_price"):
        v = raw.get(k)
        if isinstance(v, str):
            try:
                from price_parser import Price
                v = Price.fromstring(v).amount
            except Exception:
                v = None
        if isinstance(v, (int, float, Decimal)) and float(v) > 0:
            factor = (o.price_eur / o.price) if o.price and o.price_eur else 1.0
            return round(float(v) * factor, 2)
    return None


def discount_check(o: Offer, peers: list[Offer], *, history: bool = True, now: float | None = None) -> str | None:
    """EU Omnibus Directive art. 6a: a price cut must be measured from the lowest price of the previous 30 days.
    We check a shop's 'was €X' against what we saw: X above the MAX of our 30-day snapshots of that page
    -> 'discount inflated'. Without history, a NEW item's 'was' above every new price on the market also is."""
    was, p = _was_price_eur(o), price_of(o)
    if was is None or p is None or was <= p * 1.03:
        return None
    o.raw["was_eur"] = was
    if o.condition in ("used", "refurbished"):
        # a used/refurb shop's 'was' is the NEW retail price it compares with (gazelle: 'was $799'),
        # not an earlier price of this unit: the 30-day rule does not apply to it
        o.raw["was_is_retail"] = True
        return None
    o.raw["discount_claim_pct"] = round(1 - p / was, 3)
    now = time.time() if now is None else now
    own = [float(r["price_eur"]) for r in _history(o.url, now - OMNIBUS_DAYS * DAY)] if history else []
    if own:
        seen = own + [p]
        if was > max(seen) * 1.02:
            return (f"discount inflated: 'was {fmt(was)}' but we saw at most {fmt(max(seen))} here in 30 days "
                    f"(EU 30-day rule: the reference must be the 30-day low, {fmt(min(seen))})")
        return None
    if o.condition == "new":
        market = market_prices([x for x in peers if x is not o] + [o], "new")
        if len(market) >= 3 and was > max(market) * 1.05:
            return (f"discount inflated: 'was {fmt(was)}' is above every new price on the market "
                    f"(highest {fmt(max(market))})")
    return None


# ---------------------------------------------------------------- one page, two prices (gross / net)

NET_WORDS = re.compile(r"\b(?:excl\.?|excluding|ex\.?|without|zzgl\.?|ohne|exkl\.?|hors)\s*(?:vat|tax|mwst|alv|moms|tva)\b|"
                       r"\balv\s*0\s*%|\bveroton\b|\bnetto\b|\bnet price\b|\bex-vat\b|\bb2b\b", re.I)
VAT_RATIOS = (1.17, 1.28)     # EU standard VAT rates run 17% (LU) .. 27% (HU)


def _page_key(url: str) -> str:
    """One page, however it was linked: no tracking params (srsltid, utm_*), www, fragment or trailing slash."""
    try:
        from agora.discover import normalize_url
        return normalize_url(url)
    except Exception:
        return url.split("#")[0].rstrip("/")


def _merge_same_page(offers: list[Offer]) -> list[Offer]:
    """The same product page read twice at two prices (incl. and excl. VAT) is ONE offer: keep the gross
    price, remember the net one in raw['prices_shown'] and say so in a flag."""
    by_url: dict[tuple[str, str, str | None], list[Offer]] = {}
    for o in offers:
        if price_of(o) is None:
            continue
        key = (_page_key(str(o.raw.get("final_url") or o.url)), o.condition, o.unit)
        by_url.setdefault(key, []).append(o)
    drop: set[int] = set()
    for group in by_url.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda x: price_of(x) or 0, reverse=True)
        gross = next((g for g in group if not NET_WORDS.search(g.title or "")), group[0])
        for n in group:
            if n is gross or id(n) in drop:
                continue
            g, q = price_of(gross) or 0, price_of(n) or 0
            ratio = g / q if q else 0
            if q == g or NET_WORDS.search(n.title or "") or VAT_RATIOS[0] <= ratio <= VAT_RATIOS[1]:
                drop.add(id(n))
                if q != g:
                    shown = gross.raw.setdefault("prices_shown", [{"label": "incl. VAT", "price_eur": g}])
                    if not any(x.get("price_eur") == q for x in shown):
                        shown.append({"label": "excl. VAT" if ratio >= VAT_RATIOS[0] or NET_WORDS.search(n.title or "")
                                      else "also shown", "price_eur": q})
                    gross.raw["net_price_eur"] = q
    return [o for o in offers if id(o) not in drop]


def _two_prices_note(o: Offer) -> str | None:
    shown = o.raw.get("prices_shown")
    if not shown or len(shown) < 2:
        return None
    a, b = shown[0], shown[1]
    return (f"page shows {fmt(a['price_eur'])} {a['label']} and {fmt(b['price_eur'])} {b['label']}: "
            f"compared at {fmt(a['price_eur'])}")


# ---------------------------------------------------------------- IMPORT

IMPORT_VAT = 0.255          # Finland's VAT; buying from outside the EU adds it at the border
# Countries whose shelf prices include VAT/GST that comes off when the shop exports to the EU.
EXPORT_VAT: dict[str, tuple[str, float]] = {
    "GBP": ("UK", 0.20), "CHF": ("Swiss", 0.081), "NOK": ("Norway", 0.25), "ISK": ("Iceland", 0.24),
    "AUD": ("Australia", 0.10), "NZD": ("New Zealand", 0.15), "JPY": ("Japan", 0.10), "ZAR": ("South Africa", 0.15),
    "SGD": ("Singapore", 0.09), "TRY": ("Turkey", 0.20), "INR": ("India", 0.18),
}
# Shelf prices quoted before sales tax (US, Canada) or tax-free exporters: import VAT on the full price.
NO_EXPORT_VAT = {"USD", "CAD", "CNY", "HKD", "KRW", "TWD", "AED", "MXN", "BRL"}
NON_EU_CURRENCIES = set(EXPORT_VAT) | NO_EXPORT_VAT


def import_lines(o: Offer) -> list[tuple[str, float]]:
    """Receipt lines for buying from a shop outside the EU (judged by the price currency)."""
    p = price_of(o)
    cur = (o.currency or "EUR").upper()
    if p is None or o.condition == "service" or cur not in NON_EU_CURRENCIES:
        return []
    if cur in EXPORT_VAT:
        country, vat = EXPORT_VAT[cur]
        net = p / (1 + vat)
        return [(f"{country} VAT {vat:.0%} off on export (est.)", -round(p - net, 2)),
                (f"FI import VAT {IMPORT_VAT:.1%} on the export price (est.)", round(net * IMPORT_VAT, 2))]
    return [(f"import VAT {IMPORT_VAT:.1%} (shop outside the EU, est.)", round(p * IMPORT_VAT, 2))]


def import_fee(o: Offer) -> float:
    """Net extra cost of importing (can be small for VAT-inclusive countries like the UK)."""
    return round(sum(v for _, v in import_lines(o)), 2)


def outside_eu(o: Offer) -> bool:
    return bool(import_lines(o))


FI_OK = {"FI", "FIN", "FINLAND", "SUOMI", "EU", "EUROPE", "WORLDWIDE", "WORLD", "*"}


def ships_to_fi(o: Offer) -> bool | None:
    """Does this shop deliver to Finland? From JSON-LD shippingDetails/eligibleRegion, else page text.
    None = the page does not say (most pages don't)."""
    regions = o.raw.get("ships_to")
    if regions:
        return any(str(r).upper() in FI_OK for r in regions)
    return {"anywhere": True, "home_only": False}.get(o.raw.get("ships_text") or "")


def surely_buyable(o: Offer) -> bool:
    """An EU shop, or a shop outside the EU whose page says it ships to Finland."""
    return not outside_eu(o) or ships_to_fi(o) is True


GREY_WORDS = re.compile(r"import (?:tax|taxes|duty|duties) included|international version|global version|"
                        r"grey import|gray import|grey market|gray market|asian? version|hk version|"
                        r"non-eu (?:version|stock)", re.I)


def grey_import(o: Offer, peers: list[Offer]) -> str | None:
    """A 'new' unit that is probably a parallel import (no EU manufacturer warranty). Returns why, or None."""
    if o.condition != "new" or (p := price_of(o)) is None:
        return None
    m = GREY_WORDS.search(f"{o.title} {o.raw.get('search_text') or ''}")
    if m:
        return f"listing says '{m.group(0)}'"
    if outside_eu(o):
        eu_new = _trim([q for x in peers if x is not o and x.condition == "new" and not outside_eu(x)
                        and (q := price_of(x)) and not _disputed(x)])
        med = _median(eu_new)
        if med and p < 0.8 * med:
            return f"{1 - p / med:.0%} under the EU new median {fmt(med)} from a shop outside the EU"
    return None


# ---------------------------------------------------------------- TRUE COST

def _horizon_cost(o: Offer, months: int) -> tuple[float, list[tuple[str, float]], str] | None:
    """Rental/period prices -> (total sticker over the horizon, receipt, basis)."""
    p = price_of(o)
    if p is None:
        return None
    unit = (o.unit or "").lower()
    per_month = {"month": 1, "mo": 1, "kk": 1, "week": 52 / 12, "wk": 52 / 12, "day": 30, "year": 1 / 12}.get(unit)
    if per_month is None:
        return None
    total = p * per_month * months
    return total, [(f"rent {fmt(p)}/{unit} x {months} mo", round(total, 2))], f"rental at {fmt(p)} per {unit}"


_STEP_DOWN = {"high": "medium", "medium": "low", "low": "low"}
RESALE_CAP = 0.9      # resale never above 90% of the sticker: no €0/mo ownership


def estimate_true_cost(
    o: Offer,
    thing_offers: list[Offer],
    months: int = DEFAULT_MONTHS,
    category: Category | None = None,
) -> TrueCost | None:
    p = price_of(o)
    if p is None:
        return None
    cat = category or category_for(o.title)
    imports = import_lines(o)
    vat = round(sum(v for _, v in imports), 2)
    extras = (o.shipping_eur or 0.0) + vat
    years = months / 12
    fxn = fx_note(o)

    if o.condition == "rental":
        rental = _horizon_cost(o, months)
        if rental:
            total, receipt, basis = rental
            receipt += [("shipping / fees", extras)] if extras else []
            total += extras
            return TrueCost(months, round(total, 2), round(extras, 2), None, round(total, 2),
                            round(total / months, 2), "high", receipt, basis + ", nothing to resell")

    comps = resale_comps(thing_offers, exclude=o)
    thin = len(used_comps(thing_offers)) if not comps else 0
    keep = (1 - cat.rate) ** years
    if comps:
        med = statistics.median(comps)
        # a used/refurb unit bought under the market resells like what you paid, not like the median
        base = min(med, p) if o.condition in ("used", "refurbished") else med
        resale = base * keep
        conf = "high" if len(comps) >= 5 else "medium" if len(comps) >= 2 else "low"
        basis = (f"resale from {len(comps)} used listing{'s' * (len(comps) != 1)}, median {fmt(med)}"
                 + (f" (your price {fmt(p)} is lower, so that is the base)" if base < med else "")
                 + f", aged {months} mo at -{cat.rate:.0%}/yr ({cat.name})")
    else:
        new = market_prices(thing_offers, "new")
        ref = statistics.median(new) if new else p
        resale = ref * cat.used_factor * keep
        conf = "low"
        basis = (("no used listings found" if not thin else
                  f"only {thin} used listing{'s' * (thin != 1)}, too few to price resale")
                 + f": {fmt(ref)} {'new median' if new else 'this price'} x "
                 f"{cat.used_factor:.0%} typical used value, aged {months} mo at -{cat.rate:.0%}/yr ({cat.name})")
    # never promise a profit, nor a free year: selling costs fees, haggling and time, so resale stays
    # under RESALE_CAP x what you pay (a used €395 never 'resells for €395' -> €0/mo)
    capped = resale > RESALE_CAP * p
    resale = min(resale, RESALE_CAP * p)
    if capped:
        basis += f"; resale capped at {RESALE_CAP:.0%} of what you pay"
    total = p + extras - resale
    receipt = [("sticker", round(p, 2))]
    if o.shipping_eur:
        receipt.append(("shipping / fees", round(o.shipping_eur, 2)))
    receipt += imports
    if imports:
        basis += f"; priced in {o.currency}: shop outside the EU, import VAT added"
    if not o.shipping_eur and o.shipping_eur is None and o.condition != "service":
        basis += "; shipping unknown, counted as €0"
    if fxn:
        basis += f"; {fxn[0]}"
        if fxn[1]:
            conf = _STEP_DOWN[conf]
    receipt.append((f"resale in {months} mo", -round(resale, 2)))
    if any(f.startswith("possible grey import") for f in o.flags):
        receipt.append(("warranty risk: possible grey import, no EU manufacturer warranty (not priced)", 0.0))
    return TrueCost(months, round(p, 2), round(extras, 2), round(resale, 2), round(total, 2),
                    round(total / months, 2), conf, receipt, basis)  # type: ignore[arg-type]


def beat_price(o: Offer, thing_offers: list[Offer], target_per_month: float, months: int = DEFAULT_MONTHS,
               category: Category | None = None) -> float | None:
    """The highest sticker (EUR) at which `o` would cost less per month than `target_per_month`.
    True cost is piecewise linear and non-decreasing in the sticker, so bisection is exact enough.
    None when no price would win (e.g. resale too weak even at €0)."""
    p = price_of(o)
    if p is None:
        return None
    factor = (o.price / p) if o.price and p else 1.0
    goal = target_per_month - 0.01

    def per_month(x: float) -> float:
        twin = dataclasses.replace(o, price=x * factor, price_eur=x, raw=o.raw, flags=list(o.flags))
        tc = estimate_true_cost(twin, thing_offers, months, category)
        return tc.per_month_eur if tc else float("inf")

    if per_month(p) <= goal:
        return round(p, 2)
    if per_month(0.0) > goal:
        return None
    lo, hi = 0.0, p
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if per_month(mid) <= goal else (lo, mid)
    return float(int(lo * 100) / 100)


# ---------------------------------------------------------------- SERVICES: what one job costs

@dataclass(frozen=True)
class Deduction:
    """Finnish household deduction (kotitalousvähennys) on labour, per person per year."""
    rate: float
    yearly_excess: float     # omavastuu, taken off the deduction itself
    cap: float
    year: int
    source: str


HOUSEHOLD = Deduction(0.40, 150.0, 2100.0, 2026,
                      "vero.fi press release 2026: 40% of labour, €150 yearly excess, max €2,100 (2026-2027)")
HOUSEHOLD_DEDUCTION = HOUSEHOLD.rate   # kept for older callers
M2_PER_HOUR = 25.0          # a standard home clean covers roughly 25 m² an hour (estimate, shown as such)
AFTER_DEDUCTION = re.compile(r"after (the )?(household )?(tax )?(credit|deduction)|vähennyksen jälkeen", re.I)
FI_PLACES = re.compile(r"finland|suomi|helsin|espoo|vantaa|tampere|turku|oulu|jyväskylä|kuopio|lahti", re.I)


def job_size_m2(need: Need) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s?(?:m2|m²|sqm|neliö)", need.raw, re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def _gross_up(o: Offer, need: Need, rate: float | None = None) -> None:
    """Some providers advertise the price after the household deduction. Compare everyone gross."""
    if need.kind != "service" or o.price_eur is None or "net_of_deduction_eur" in o.raw:
        return
    if AFTER_DEDUCTION.search(o.title or ""):
        r = rate or HOUSEHOLD.rate
        o.raw["net_of_deduction_eur"] = o.price_eur
        o.price_eur = round(o.price_eur / (1 - r), 2)


def _merge_net_gross(offers: list[Offer]) -> list[Offer]:
    """A page that shows both a gross and an after-deduction price is ONE provider: keep the gross one,
    and remember the deduction rate that page itself implies."""
    by_url: dict[str, list[Offer]] = {}
    for o in offers:
        by_url.setdefault(o.raw.get("final_url") or o.url, []).append(o)
    drop: set[int] = set()
    for group in by_url.values():
        nets = [o for o in group if AFTER_DEDUCTION.search(o.title or "")]
        gross = [o for o in group if o not in nets and o.price_eur]
        if nets and gross and nets[0].price_eur:
            g = gross[0]
            g.raw["page_deduction_rate"] = round(1 - nets[0].price_eur / g.price_eur, 3)  # type: ignore[operator]
            drop.update(id(n) for n in nets)
    return [o for o in offers if id(o) not in drop]


def deduction_back(gross_labour: float, other_work_this_year: float = 0.0) -> float:
    """What the household deduction gives back for this job, given other household work this year."""
    before = HOUSEHOLD.rate * other_work_this_year - HOUSEHOLD.yearly_excess
    after = HOUSEHOLD.rate * (other_work_this_year + gross_labour) - HOUSEHOLD.yearly_excess
    return round(min(HOUSEHOLD.cap, max(0.0, after)) - min(HOUSEHOLD.cap, max(0.0, before)), 2)


NOT_COMPARABLE = {"fee": "a fee or surcharge, not a price for the job",
                  "off_topic": "a different service",
                  "task": "price for one specific task, not a standard call",
                  "callout": "call-out / visit fee only, labour extra",
                  "premium": "emergency / urgent / weekend rate, not the standard price"}
# a business rate without VAT ('ALV 0 %', 'zzgl. MwSt.', 'excl. btw'): a household pays it with VAT
EX_VAT = re.compile(r"alv\s*0|veroton|\b(?:excl?|exkl?|ohne|zzgl|plus|\+)\.?\s*(?:vat|mwst|ust|btw|moms|alv|tva|iva)\b|"
                    r"\b(?:vat|alv|mwst|btw)\s*0\s*%|excluding vat|exclusief btw", re.I)
SERVICE_VAT = {"fi": 0.255, "de": 0.19, "nl": 0.21, "se": 0.25, "dk": 0.25, "no": 0.25, "ee": 0.24, "at": 0.20,
               "be": 0.21, "fr": 0.20, "es": 0.21, "it": 0.22, "pl": 0.23, "ie": 0.23, "pt": 0.23, "lv": 0.21,
               "lt": 0.21, "cz": 0.21, "ch": 0.081, "gb": 0.20}


def _vat_for(need: Need) -> float | None:
    try:
        from agora import places
        return SERVICE_VAT.get(places.country_for(need.where) or "")
    except Exception:
        return None


BUNDLE_HOURS = re.compile(r"\b(\d+(?:[.,]5)?)\s*(?:uur|hours?|stunden|tuntia|timmar|heures|horas|h)\b", re.I)


def _directory_key(o: Offer) -> str:
    """Providers cut from one directory page vote once in a service median (10 yoopies cleaners = 1 voice)."""
    return o.raw.get("from_list_page") or o.url


def service_cost(o: Offer, need: Need) -> TrueCost | None:
    """One job, with the math shown: unit price x size/hours + call-out fee. The headline is the gross
    price; the household deduction is a conditional note (it depends on the person's whole year).
    `months` is 0, `per` is 'job' and `per_month_eur` is the job total (kept for older readers)."""
    p = price_of(o)
    unit = (o.unit or "").lower()
    if p is None or unit not in ("hour", "m2", "job", "visit"):
        return None
    from agora import resolve
    kind = o.raw.get("line_kind") or resolve.service_line_kind(need, o.title or "", o.unit)
    trade = resolve.is_open_trade(need)
    if kind in ("fee", "off_topic", "premium") or (trade and kind in ("task", "callout")):
        # not a price for the asked job: shown as 'other prices', never compared
        o.raw["not_comparable"] = NOT_COMPARABLE.get(kind, kind)
        return None
    o.raw.pop("not_comparable", None)
    receipt: list[tuple[str, float]] = []
    basis: list[str] = []
    if EX_VAT.search(o.title or "") and (vat := _vat_for(need)):
        # compare what a household pays: the page's price without VAT, plus the country's VAT
        o.raw["ex_vat_eur"] = p
        p = round(p * (1 + vat), 2)
        basis.append(f"page price {fmt(o.raw['ex_vat_eur'])} is without VAT; {vat:.1%} VAT added")
    rate = p
    size = job_size_m2(need)
    conf: str = "high"
    tier = f" {o.raw['tier']}" if o.raw.get("tier") else ""
    if unit == "hour":
        stated = o.raw.get("m2_per_hour")
        speed = float(stated) if isinstance(stated, (int, float)) and stated > 0 else M2_PER_HOUR
        mh = o.raw.get("min_hours")
        default = resolve.TRADE_HOURS if trade else 2.0
        floor = float(mh) if isinstance(mh, (int, float)) and 0.5 <= mh <= 12 else default   # page's minimum
        if trade:
            hours = floor
            conf = "low"
            o.raw["area_rate_source"] = "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h (typical call, est.)"
        else:
            hours = max(floor, round((size or 50) / speed * 2) / 2)
            conf = ("high" if stated else "medium") if size else "low"
            where = f"page says {speed:g} m²/h" if stated else f"assumed {M2_PER_HOUR:g} m²/h, same for all"
            o.raw["area_rate_source"] = "page" if stated else "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h" + (f" for {size:g} m² ({where})" if size
                                                            else " (typical visit, est.)")
        if isinstance(mh, (int, float)) and hours == floor and floor != default:
            label += f", page minimum {floor:g} h"
        sticker = rate * hours
        calc = f"{fmt_rate(rate)}/h × {hours:g} h"
    elif unit == "m2" and size:
        label, sticker = f"{fmt(rate)}/m²{tier} x {size:g} m²", rate * size
        calc = f"{fmt_rate(rate)}/m² × {size:g} m²"
    elif unit == "m2":
        return None
    else:
        label, sticker = f"{fmt(rate)} per {unit}{tier}", rate
        bundle = BUNDLE_HOURS.search(o.title or "")
        calc = (f"{bundle.group(1).replace(',', '.')} h for {fmt(rate)}" if bundle else f"fixed price per {unit}")
    receipt.append((label, round(sticker, 2)))
    callout = o.raw.get("callout_fee") if isinstance(o.raw, dict) else None
    extras = float(callout) if isinstance(callout, (int, float)) else 0.0
    if extras:
        receipt.append(("call-out fee", round(extras, 2)))
        calc += f" + {fmt(extras)} call-out"
    if resolve.is_deal(o):
        o.raw["deal"] = True
        basis.append("deal / voucher price: check its conditions (often first booking only)")
    if trade:
        basis.append(f"estimate: a standard call of {resolve.TRADE_HOURS:g} h labour at the stated hourly rate"
                     + (" plus the call-out fee" if extras else "") + "; the real job may take longer")
    o.raw["calc"] = calc
    total = sticker + extras
    if o.raw.get("recurring_only"):
        basis.append("only recurring-contract prices on the page: highest tier used for one job")
    if FI_PLACES.search(f"{need.where or ''} {need.raw}"):
        full = round(min(HOUSEHOLD.cap, total * HOUSEHOLD.rate), 2)
        o.raw["deduction_eur"] = full
        o.raw["deduction_alone_eur"] = deduction_back(total)
        basis.append(f"household deduction: up to {fmt(full)} back ({HOUSEHOLD.rate:.0%} of labour) once your "
                     f"household work this year passes the {fmt(HOUSEHOLD.yearly_excess)} excess "
                     f"({HOUSEHOLD.source})")
    return TrueCost(0, round(sticker, 2), round(extras, 2), None, round(total, 2), round(total, 2),
                    conf, receipt, "; ".join(basis) or "one job at the listed rate", per="job")  # type: ignore[arg-type]


# ---------------------------------------------------------------- HAGGLE

def _haggleable(o: Offer) -> bool:
    """Only private sellers / classified listings get a haggle script; dealers have fixed prices."""
    return _domain_in(o.source, MARKETPLACES) or o.raw.get("page_type") == "listing"


def _local(o: Offer, x_eur: float) -> str:
    """Money in the listing's own currency (a seller in the UK thinks in pounds)."""
    cur = (o.currency or "EUR").upper()
    if cur == "EUR" or not o.price or not o.price_eur:
        return fmt(x_eur)
    return f"{x_eur * o.price / o.price_eur:,.0f} {cur}"


def make_haggle(o: Offer, thing_offers: list[Offer], thing_name: str, category: Category | None = None) -> Haggle | None:
    p = price_of(o)
    if p is None or o.condition != "used" or _risky(o) or not _haggleable(o):
        return None
    comps = used_comps(thing_offers)
    if len(comps) >= 2:
        lo, hi = _quantile(comps, 0.25), _quantile(comps, 0.75)
        mid = statistics.median(comps)
        evidence = f"similar ones go for {_local(o, lo)}-{_local(o, hi)}"
    else:
        new = market_prices(thing_offers, "new")
        if not new:
            return None
        cat = category or category_for(thing_name)
        mid = statistics.median(new) * cat.used_factor
        lo, hi = mid * 0.9, mid * 1.1
        evidence = f"used ones usually sell around {_local(o, mid)}"
    if p <= lo:
        offer = p
        msg = (f"Hi! Is your {thing_name} still available? Before I buy: could you send the serial number, "
               f"a few photos and the shutter count / battery health? Thanks!")
    else:
        offer = _round_nice(max(lo, min(p * 0.9, mid)))
        msg = (f"Hi! Is your {thing_name} still available? I'm ready to buy this week and can pay right away. "
               f"Would you take {_local(o, offer)}? {evidence[0].upper() + evidence[1:]}. Thanks!")
    return Haggle(round(lo, 2), round(hi, 2), round(offer, 2), msg)


# ---------------------------------------------------------------- EVIDENCE

def evidence_for(o: Offer, thing_offers: list[Offer]) -> list[dict[str, Any]]:
    """Where each receipt line comes from: {line_index, url, via, quote, fetched_at}."""
    tc = o.true_cost
    if tc is None:
        return []
    wit = next((w for w in o.raw.get("witnesses") or [] if isinstance(w, dict) and w.get("primary")), {})
    out: list[dict[str, Any]] = []
    for i, (label, _) in enumerate(tc.receipt):
        if i == 0:
            out.append({"line_index": i, "url": o.url, "via": wit.get("via", o.read_via),
                        "quote": wit.get("quote") or f"{o.price:g} {o.currency or ''}".strip() if o.price else None,
                        "fetched_at": wit.get("fetched_at")})
        elif label.startswith("resale"):
            urls = _comp_urls(thing_offers, exclude=o)
            out.append({"line_index": i, "url": urls[0] if urls else None, "urls": urls, "via": "used comps",
                        "quote": tc.basis.split(";")[0], "fetched_at": None})
        elif "VAT" in label:
            out.append({"line_index": i, "url": None, "via": "rule", "quote": label, "fetched_at": None})
        elif label.startswith("shipping"):
            out.append({"line_index": i, "url": o.url, "via": o.read_via, "quote": "shipping on the page",
                        "fetched_at": wit.get("fetched_at")})
    return out


# ---------------------------------------------------------------- VERDICT

def _budget_eur(need: Need) -> float | None:
    return eur(need.budget, need.currency) if need.budget else None


def _cond(o: Offer) -> str:
    return {"new": "new", "used": "used", "refurbished": "refurbished", "rental": "renting"}.get(o.condition, o.condition)


def _risky(o: Offer) -> bool:
    """Never crowned as the best buy: low trust, a price far under its peers, or a disputed price."""
    return ((o.trust if o.trust is not None else 1) < 0.5 or _disputed(o)
            or any(f.startswith("too good to be true") for f in o.flags))


def _landed(o: Offer) -> float:
    tc = o.true_cost
    if tc is not None:
        return tc.sticker_eur + tc.extras_eur
    return (o.price_eur or 0) + (o.shipping_eur or 0) + import_fee(o)


def measured_category(cat: Category, depreciation: dict[str, Any] | None) -> Category:
    """The category with its yearly rate replaced by a market-measured one (agora.depreciation)."""
    if not depreciation or not isinstance(depreciation.get("rate"), (int, float)):
        return cat
    return dataclasses.replace(cat, rate=float(depreciation["rate"]),
                               name=f"{cat.name}, {depreciation.get('basis') or 'measured'}")


def _judge_offers(need: Need, t: Thing, months: int, seen: dict[str, int],
                  depreciation: dict[str, Any] | None = None, *, history: bool = False,
                  photos: dict[int, list[Offer]] | None = None, floor: float = 0.0) -> None:
    cat = measured_category(category_for(" ".join([need.thing, t.name] + [o.title for o in t.offers[:5]])),
                            depreciation)
    for o in t.offers:
        price_of(o)
    if need.kind == "service":
        t.offers[:] = _merge_net_gross(t.offers)
        for o in t.offers:
            _gross_up(o, need, o.raw.get("page_deduction_rate"))
    else:
        t.offers[:] = _merge_same_page(t.offers)
    for o in t.offers:
        discount = discount_check(o, t.offers, history=history)
        o.trust, new_flags = assess_trust(o, t.offers, photos=photos, discount=discount,
                                          floor=0.0 if need.kind == "service" else floor)
        o.flags = [f for f in o.flags if f in ("bundle",)] + new_flags
        if note := _two_prices_note(o):
            o.flags.append(note)
        if o.raw.get("net_of_deduction_eur") is not None:
            o.flags.append(f"page shows {fmt(o.raw['net_of_deduction_eur'])} after the household deduction; "
                           f"compared at the gross {fmt(o.price_eur or 0)}")
        if o.raw.get("recurring_only"):
            o.flags.append("recurring-contract price (no one-time price on the page)")
        if (n := seen.get(o.source, 0)) >= 2:
            o.flags.append(f"seen before in {n} hunts")
    for o in t.offers:
        if need.kind == "service":
            o.true_cost = service_cost(o, need)
            continue
        if _disputed(o) or (any(f.startswith("too good to be true") for f in o.flags)
                            and o.raw.get("price_check") != "verified"):
            o.true_cost, o.haggle = None, None
            o.flags.append("not costed: price unconfirmed (far off the market or disputed)")
            continue
        o.true_cost = estimate_true_cost(o, t.offers, months, cat)
        o.haggle = make_haggle(o, t.offers, t.name, cat)


def judge(need: Need, things: list[Thing], months: int = DEFAULT_MONTHS, *, history: bool = True,
          depreciation: dict[str, Any] | None = None) -> Verdict:
    """Mutates offers (trust, flags, true_cost, haggle, raw[evidence/beat]) and returns the verdict.
    `history=False` skips the price-history lookup (the hunt's fast live re-ranking).
    `depreciation` = agora.depreciation.measure(...) result: a measured yearly rate replaces the assumed one."""
    seen = _seen_counts(sorted({o.source for t in things for o in t.offers})) if history else {}
    everyone = [o for t in things for o in t.offers]
    try:
        from agora import reviews
        reviews.preload(o.url for o in everyone)
    except Exception:
        pass
    photos = _photo_groups(everyone, warm=history)
    all_offers: list[Offer] = []
    cat_of: dict[int, Category] = {}
    offers_of: dict[int, list[Offer]] = {}
    band_of: dict[int, dict[str, Any]] = {}
    floor = market_floor(everyone) if need.kind != "service" else 0.0   # across Things: a lone part is its own Thing
    for t in things:
        _judge_offers(need, t, months, seen, depreciation, history=history, photos=photos, floor=floor)
        cat = measured_category(category_for(" ".join([need.thing, t.name] + [o.title for o in t.offers[:5]])),
                                depreciation)
        bands = price_band(t, history=history)
        for o in t.offers:
            cat_of[id(o)], offers_of[id(o)] = cat, t.offers
            o.raw["evidence"] = evidence_for(o, t.offers)
            ob = offer_band(o, bands, history=history)
            o.raw["band"] = ob
            if ob:
                band_of[id(o)] = ob
                if o.true_cost is not None:
                    o.true_cost.band = ob
        all_offers += t.offers

    priced = [o for o in all_offers if o.price_eur is not None]
    if not priced:
        return Verdict("No priced offers yet. Set a watch and Agora keeps looking.", None, None, None,
                       [f"{len(all_offers)} offers found, none with a readable price"])
    good = [o for o in priced if not _risky(o) and o.in_stock is not False and ships_to_fi(o) is not False] or priced
    eu = [o for o in good if not outside_eu(o)]

    cheapest = min(good, key=_landed)
    best_link = min(eu, key=_landed) if eu else cheapest
    owned = [o for o in good if o.true_cost]
    best_tc = min(owned, key=lambda o: o.true_cost.per_month_eur) if owned else None  # type: ignore[union-attr]
    lines: list[str] = []

    if need.kind == "service" and best_tc is not None:
        headline = _service_headline(need, best_tc)
        # cheapest job first; at most 2 lines per site (one directory's ten cleaners do not fill the comparison)
        per_site: dict[str, int] = {}
        for o in sorted(owned, key=lambda o: o.true_cost.per_month_eur):  # type: ignore[union-attr]
            if len(lines) >= 4 or per_site.get(o.source, 0) >= 2:
                continue
            per_site[o.source] = per_site.get(o.source, 0) + 1
            tc = o.true_cost
            assert tc is not None
            deal = " (deal)" if o.raw.get("deal") else ""
            parts = [f"{fmt(v)} call-out" if lbl == "call-out fee" else lbl for lbl, v in tc.receipt if v > 0]
            lines.append(f"{o.source}{deal}: {' + '.join(parts)} -> {fmt(tc.total_eur)}")
        if best_tc.raw.get("deal"):
            regular = [o for o in owned if not o.raw.get("deal")]
            if regular:
                r = min(regular, key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
                lines.insert(0, f"without a deal: {fmt(r.true_cost.total_eur)} at {r.source}"  # type: ignore[union-attr]
                             + (f", {r.raw['calc']}" if r.raw.get("calc") else ""))
        others = [x for x in best_tc.raw.get("other_prices") or [] if x.get("price_eur")]
        if others:
            lines.append(f"other prices at {best_tc.source}: " + ", ".join(
                f"{x['title'][:40]} {fmt(x['price_eur'])}" + {"hour": "/h", "m2": "/m²"}.get(x.get("unit") or "", "")
                for x in others[:3]))
        if best_tc.raw.get("deduction_eur"):
            lines.append(f"household deduction ({HOUSEHOLD.year}): {HOUSEHOLD.rate:.0%} of labour minus a "
                         f"{fmt(HOUSEHOLD.yearly_excess)} yearly excess per person; this job alone gets "
                         f"{fmt(best_tc.raw.get('deduction_alone_eur') or 0)} back")
        apart = [o for o in priced if o.true_cost is None and o.raw.get("not_comparable")]
        if apart:
            why = sorted({o.raw["not_comparable"] for o in apart})
            shown = ", ".join(f"{o.source} {fmt(o.price_eur or 0)} ({(o.title or '')[:30]})" for o in apart[:3])
            lines.append(f"{len(apart)} more not compared ({'; '.join(why)}): {shown}")
        no_unit = len(priced) - len(owned) - len(apart)
        if no_unit:
            lines.append(f"{no_unit} more offer{'s' * (no_unit != 1)} without a clear unit (per hour / m² / job)")
        best_link = best_tc
    elif need.kind == "service" or best_tc is None:
        unit = f"/{cheapest.unit}" if cheapest.unit else ""
        headline = f"Cheapest: {fmt(_landed(cheapest))}{unit} at {cheapest.source}."
        if len(good) > 1:
            med = statistics.median(o.price_eur or 0 for o in good)
            lines.append(f"{len(good)} trustworthy offers, median {fmt(med)}{unit}")
    else:
        # Products: people want the full price they pay once (tag + shipping + import + fees), so the
        # pick is the lowest ALL-IN price among offers you can surely buy. Owning cost per month stays
        # a secondary line (true_cost on every offer), never the headline.
        sure = [o for o in good if surely_buyable(o)]
        best_all = min(sure or good, key=_landed)
        for o in good:
            extras = _landed(o) - (o.price_eur or 0)
            beat = round(_landed(best_all) - extras, 2)
            o.raw["beat_eur"] = beat
            o.raw["gap_eur"] = round((o.price_eur or 0) - beat, 2)
        headline = all_in_headline(good, best_all, lines)
        if best_all is not cheapest and not surely_buyable(cheapest):
            lines.append(f"{cheapest.source} is cheaper ({fmt(_landed(cheapest))} all in) but does not say it ships to Finland")
        if best_all.true_cost is not None and best_all.true_cost.resale_eur:
            btc = best_all.true_cost
            lines.append(f"if you resell it after {months} mo for ~{fmt(btc.resale_eur)}, it costs you about "
                         f"{fmt(btc.total_eur)} net ({fmt(btc.per_month_eur)}/mo)")
        if outside_eu(best_all):
            lines.append(f"{best_all.source} is outside the EU: import VAT is included in its all-in price")
        if best_all.haggle and best_all.haggle.suggested_offer_eur < (best_all.price_eur or 0):
            h = best_all.haggle
            lines.append(f"haggle: offer {fmt(h.suggested_offer_eur)} (fair {fmt(h.fair_low_eur)}-{fmt(h.fair_high_eur)})")
        best_link = best_all
        best_tc = best_all if best_all.true_cost is not None else best_tc

    flagged = [o for o in all_offers if _risky(o)]
    if flagged:
        reasons = sorted({next((f for f in o.flags if f.startswith(("too good", "price disagrees"))),
                               next((f for f in o.flags if f != "bundle"), "low trust")) for o in flagged})
        verb = "looks" if len(flagged) == 1 else "look"
        lines.append(f"{len(flagged)} offer{'s' * (len(flagged) != 1)} {verb} risky: " + "; ".join(reasons)[:200])

    pick = best_tc or cheapest
    budget = _budget_eur(need)
    buy_or_wait: str | None = None
    if budget is not None:
        if (pick.price_eur or 0) <= budget:
            buy_or_wait = "buy now" if (pick.trust or 0) >= 0.6 else "check the seller first"
            lines.append(f"within your {fmt(budget)} budget")
        else:
            buy_or_wait = "wait: set a watch"
            over = (pick.price_eur or 0) - budget
            lines.append(f"{fmt(over)} over your {fmt(budget)} budget: set a watch for <= {fmt(budget)}")
    elif (pick.trust or 0) >= 0.7:
        buy_or_wait = "buy now"
    # the offer the headline tells you to buy: a possible grey import is never a plain "buy now"
    led = best_link if headline.startswith("Best you can surely buy") else pick
    grey = next((o for o in (led, pick) if _is_grey(o)), None)
    if buy_or_wait == "buy now" and grey is not None:
        buy_or_wait = "check the warranty first"
        lines.append(f"{grey.source} may be a grey import (no EU manufacturer warranty): ask before you buy")

    vband = band_of.get(id(led)) or band_of.get(id(pick))
    if vband:
        which = led if id(led) in band_of else pick
        lines.append(f"price band ({vband.get('what') or which.condition}): {fmt(vband['p25'])}-{fmt(vband['p75'])} is typical; "
                     f"{which.source} at {fmt(which.price_eur or 0)} is {vband['label']}"
                     + (f" ({vband['badges'][0]})" if vband["badges"] else ""))
        vband = {**vband, "url": which.url, "thing_id": which.thing_id}
    return Verdict(headline, best_link.url, best_tc.url if best_tc else None, buy_or_wait, lines, price_band=vband)


def _is_grey(o: Offer) -> bool:
    return any(f.startswith("possible grey import") for f in o.flags)


def _photo_groups(offers: list[Offer], warm: bool) -> dict[int, list[Offer]] | None:
    """Same-photo groups across the whole hunt (agora.trust). The final judge first fills the image and
    WHOIS caches within a short time box (AGORA_TRUST_BUDGET seconds, default 1.5; offline: never)."""
    try:
        from agora import trust
        if warm:
            try:
                budget = float(os.environ.get("AGORA_TRUST_BUDGET", "1.5"))
            except ValueError:
                budget = 1.5
            trust.warm(offers, budget_s=budget)
        return trust.same_photo_groups(offers)
    except Exception:
        return None


def all_in_headline(good: list[Offer], best: Offer, lines: list[str]) -> str:
    """'€825 all in: used at tori.fi. New from €1,029, refurbished from €899.' Every number is the full
    price you pay once (tag + shipping + import VAT + fees)."""
    per_cond: dict[str, Offer] = {}
    for o in good:
        if o.condition in ("new", "refurbished", "used", "rental"):
            cur = per_cond.get(o.condition)
            if cur is None or _landed(o) < _landed(cur):
                per_cond[o.condition] = o
    for c, o in sorted(per_cond.items(), key=lambda kv: _landed(kv[1])):
        extra = _landed(o) - (o.price_eur or 0)
        how = f" ({fmt(o.price_eur or 0)} + {fmt(extra)} shipping/import/fees)" if extra >= 1 else ""
        lines.append(f"{c}: {fmt(_landed(o))} all in at {o.source}{how}")
    head = f"{fmt(_landed(best))} all in: {_cond(best)} at {best.source}."
    others = [f"{c} from {fmt(_landed(o))}" + ("" if surely_buyable(o) else " (may not ship to Finland)")
              for c, o in sorted(per_cond.items(), key=lambda kv: _landed(kv[1])) if c != best.condition]
    if others:
        tail = ", ".join(others)
        head += f" {tail[0].upper()}{tail[1:]}."
    return head


def _service_headline(need: Need, best: Offer) -> str:
    from agora import resolve
    btc = best.true_cost
    assert btc is not None
    size = job_size_m2(need)
    g = resolve.service_group(need)
    noun = "clean" if g is resolve.CLEANING_GROUP else "job"
    if resolve.is_open_trade(need):
        job = f"a standard {resolve.TRADE_HOURS:g}-hour call (estimate)"
    else:
        job = f"one {size:g} m² {noun}" if size else f"one {noun}"
    tier = f" ({best.raw['tier']} rate)" if best.raw.get("tier") else ""
    tier += " (deal)" if best.raw.get("deal") else ""
    calc = f", {best.raw['calc']}" if best.raw.get("calc") else ""
    ded = best.raw.get("deduction_eur")
    alone = best.raw.get("deduction_alone_eur")
    if ded and alone is not None and alone < ded:
        # the deduction has a yearly excess: this job alone may give back less (or nothing)
        after = (f", about {fmt(btc.total_eur - ded)} after the household deduction once your household work "
                 f"this year passes its {fmt(HOUSEHOLD.yearly_excess)} excess")
    else:
        after = (f", about {fmt(btc.total_eur - ded)} after the household deduction if you claim it"
                 if ded else "")
    return f"{fmt(btc.total_eur)} for {job} at {best.source}{tier}{calc}{after}."


def _sure_headline(safe: Offer, best: Offer, months: int) -> str:
    """The cheapest-to-own offer may not even ship here: lead with what you can surely buy."""
    stc, btc = safe.true_cost, best.true_cost
    assert stc is not None and btc is not None
    grey = " (possible grey import: no EU warranty)" if any(f.startswith("possible grey import")
                                                            for f in safe.flags) else ""
    return (f"Best you can surely buy: {_cond(safe)} {fmt(_landed(safe))} at {safe.source}{grey}, "
            f"{fmt(stc.per_month_eur)}/mo over {months} mo. Cheaper if {best.source} ships to Finland: "
            f"{_cond(best)} {fmt(_landed(best))} landed, {fmt(btc.per_month_eur)}/mo.")


def winner_vs_cheapest_headline(best_tc: Offer, cheapest: Offer, months: int) -> str:
    """Winner first, then the cheapest sticker and why it loses, with every number on the page:
    'Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo. The cheapest
    sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo.'"""
    btc, ctc = best_tc.true_cost, cheapest.true_cost
    assert btc is not None and ctc is not None
    head = f"Buy {_cond(best_tc)} at {best_tc.source} for {fmt(_landed(best_tc))}: "
    if btc.resale_eur:
        head += (f"resell in {months} mo for ~{fmt(btc.resale_eur)}, so it costs {fmt(btc.per_month_eur)}/mo. ")
    else:
        head += f"it costs {fmt(btc.per_month_eur)}/mo over {months} mo. "
    sticker, landed = ctc.sticker_eur, _landed(cheapest)
    if landed - sticker >= 1:
        how = "with import costs" if import_fee(cheapest) > 0 else "with shipping"
        tail = (f"The cheapest sticker ({fmt(sticker)} at {cheapest.source}) lands at {fmt(landed)} {how} "
                f"and costs {fmt(ctc.per_month_eur)}/mo.")
    else:
        tail = f"The cheapest sticker ({fmt(sticker)} at {cheapest.source}) costs {fmt(ctc.per_month_eur)}/mo to own."
    return head + tail


def _product_headline(owned: list[Offer], best_tc: Offer, cheapest: Offer, months: int, lines: list[str]) -> str:
    per_cond: dict[str, Offer] = {}
    for o in owned:
        cur = per_cond.get(o.condition)
        if cur is None or o.true_cost.per_month_eur < cur.true_cost.per_month_eur:  # type: ignore[union-attr]
            per_cond[o.condition] = o
    for c, o in sorted(per_cond.items(), key=lambda kv: kv[1].true_cost.per_month_eur):  # type: ignore[union-attr]
        tc = o.true_cost
        assert tc is not None
        resale = f"resale {fmt(tc.resale_eur)}" if tc.resale_eur is not None else "no resale"
        landed = f" ({fmt(tc.sticker_eur + tc.extras_eur)} landed)" if tc.extras_eur else ""
        lines.append(f"{c}: {fmt(tc.sticker_eur)}{landed} at {o.source} -> {fmt(tc.per_month_eur)}/mo over "
                     f"{months} mo ({resale}, {tc.confidence} confidence)")
    btc = best_tc.true_cost
    assert btc is not None
    if cheapest is not best_tc and cheapest.true_cost:
        ctc = cheapest.true_cost
        headline = winner_vs_cheapest_headline(best_tc, cheapest, months)
    else:
        rivals = [o for c, o in per_cond.items() if c != best_tc.condition]
        if rivals:
            # the story people know is new vs used: compare against new when we have it
            rival = per_cond.get("new") if best_tc.condition != "new" and "new" in per_cond else \
                min(rivals, key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
            rtc = rival.true_cost
            assert rtc is not None
            diff = rtc.per_month_eur - btc.per_month_eur
            ratio = rtc.per_month_eur / btc.per_month_eur if btc.per_month_eur > 0 else None
            wins = f", {fmt(diff)}/mo less" + (f" ({ratio:.1f}x)" if ratio and ratio >= 1.2 else "") if diff >= 1 else ""
            headline = (f"{_cond(rival).capitalize()} costs {fmt(rtc.per_month_eur)}/mo, "
                        f"{_cond(best_tc)} {fmt(btc.per_month_eur)}/mo: {_cond(best_tc)} at {best_tc.source} "
                        f"({fmt(_landed(best_tc))}) wins{wins}.")
        else:
            headline = (f"Best buy: {_cond(best_tc)} {fmt(_landed(best_tc))} at {best_tc.source}, "
                        f"really costs you {fmt(btc.per_month_eur)}/mo over {months} mo.")
    for c, o in per_cond.items():
        if o is best_tc or c == best_tc.condition:
            continue
        beat = o.raw.get("beat_eur")
        if beat is None:
            lines.append(f"cheapest {c.upper()} cannot beat {_cond(best_tc)} at any price over {months} mo")
        elif beat < (o.price_eur or 0):
            lines.append(f"cheapest {c.upper()} ({o.source}) would need to drop {fmt((o.price_eur or 0) - beat)} "
                         f"(to {fmt(beat)}) to beat {_cond(best_tc)}")
    return headline
