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

import contextvars
from collections import Counter
import dataclasses
import os
import functools
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agora.models import Haggle, Need, Offer, Thing, TrueCost, Verdict
from agora.need import is_service, priced_per_period

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
MIXED_LOW = 0.15       # mixed bag: under 15% of the median (10% for bulky things) is shown but never the pick
MIXED_LOW_BULKY = 0.10
GENERIC_PICK_MIN = 0.5  # ... and a vague need's pick costs at least half the hunt's median of its condition
MIXED_PICK_MIN = 0.35  # a mixed bag's pick sits in its usual range: a €45 road bike among €450 ones is never it
MIXED_FLOOR = 0.08     # a mixed bag of models (a kind of thing): only under 8% of its median is a part / misread
SHOWN_FLOOR = 0.20    # a vague need's "new from" / "used from" line skips prices under 20% of their median
SCALE_FLOOR = 0.25     # a price under 25% of the item's overall median is a part/accessory or a misread


def _list_offer(o: Offer) -> bool:
    """A search/category page read as one offer (tori.fi/search?q=...): never a market data point."""
    if o.raw.get("list_page"):
        return True
    return _list_url(o.url)


@functools.lru_cache(maxsize=20000)
def _list_url(url: str) -> bool:
    """discover.is_list_page, cached: market_prices asks it for every offer, many times per judge."""
    try:
        from agora.discover import is_list_page
        return bool(is_list_page(url))
    except Exception:
        return False


def _memo_key(tag: str, offers: list[Offer]) -> tuple[Any, ...] | None:
    """(tag, content token): lists with the same offers share a token. The token is worked out once per list
    object (kept alive in the memo, so its id cannot be reused): hashing a 2,000-id tuple on every market_prices
    call cost 2.5 s per judge of a generic hunt."""
    memo = _MEMO.get()
    if memo is None:
        return None
    by_obj = memo.setdefault("__lists__", {})
    ent = by_obj.get(id(offers))
    if ent is None or ent[0] is not offers or ent[1] != len(offers):
        tokens = memo.setdefault("__tokens__", {})
        ent = (offers, len(offers), tokens.setdefault(tuple(map(id, offers)), len(tokens)))
        by_obj[id(offers)] = ent
    return (tag, ent[2])


def _junk(x: Offer) -> bool:
    """Red-flagged (broken, copy, one earbud ...) or far under the reference new price: never a market price."""
    return bool(x.raw.get("red_flags") or x.raw.get("ref_suspect"))


def market_floor(offers: list[Offer]) -> float:
    """The price under which an offer cannot be the item (ear tips at €10 among €170 AirPods, an OLED
    panel at €90 among €300 consoles): SCALE_FLOOR x the median over all conditions. 0 = too few prices."""
    key = _memo_key("floor", offers)
    memo = _MEMO.get()
    if key is not None and memo is not None and key in memo:
        return memo[key]
    prices = [p for x in offers if x.condition in ("new", "used", "refurbished")
              and (p := price_of(x)) is not None and p > 1 and not _disputed(x) and not _list_offer(x)
              and not _junk(x)]
    out = SCALE_FLOOR * statistics.median(prices) if len(prices) >= 3 else 0.0
    if key is not None and memo is not None:
        memo[key] = out
    return out


def market_prices(offers: list[Offer], condition: str) -> list[float]:
    """Prices of one condition that describe the market: no disputed prices, no search/list pages, no
    'from' prices, nothing under the item's price floor (parts, accessories), nothing red-flagged or far under
    the reference new price, a private seller's 'new' counted as used, used ones not dearer than
    new (bundles, wishful sellers), and the far outliers (< half or > 2.5x the median) dropped once.
    Trust flags, haggle bands and resale all use this same set, so they quote the same median."""
    key = _memo_key("mp:" + condition, offers)
    memo = _MEMO.get()
    if key is not None and memo is not None and key in memo:
        return list(memo[key])
    out = _market_prices(offers, condition)
    if key is not None and memo is not None:
        memo[key] = tuple(out)
    return out


def _market_prices(offers: list[Offer], condition: str) -> list[float]:
    floor = market_floor(offers)
    sel = [x for x in _one_vote_per_listing(offers) if market_condition(x) == condition
           and (p := price_of(x)) is not None and p > 1 and p >= floor and not _disputed(x)
           and not _list_offer(x) and not x.raw.get("from_price") and not _junk(x) and not x.raw.get("with_lens")
           # another audience's item (a men's jacket for women's, told by its description) and a calculator's
           # estimate never set the typical price; nor does a sold-out deal
           and not x.raw.get("other_audience") and not x.raw.get("estimate")
           and not (condition == "service" and sold_out(x))]
    if condition == "service":
        votes: dict[str, list[float]] = {}
        for x in sel:   # one directory page = one voice in the median, however many providers it listed
            votes.setdefault(_directory_key(x), []).append(price_of(x) or 0.0)
        prices = [statistics.median(v) for v in votes.values()]
    else:
        prices = [price_of(x) or 0.0 for x in sel]
    if condition == "used":
        new = [p for x in offers if market_condition(x) == "new" and (p := price_of(x)) is not None
               and not _disputed(x) and x.in_stock is not False and p >= floor and not _list_offer(x) and not _junk(x)]
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
        # listings cut from a marketplace search page are separate sellers: one vote each; several units of one
        # dealer page (Wex: 8 graded A7 III bodies) are one shop: one vote per grade
        if x.raw.get("unit_of"):
            key = (f"{x.raw['unit_of']}|{str(x.raw.get('grade') or '').lower()}", x.condition, -2)
        else:
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
    if len(comps) < MIN_COMPS:
        return []
    if exclude is not None and len(comps) < 3:
        # few comps: check exactly that one is not the costed offer itself (with 3+ comps another one always
        # stays; recomputing the set without each offer made judge O(n^2): 15 s for 2,000 marketplace rows)
        if not used_comps(thing_offers, exclude):
            return []
    return comps


def _comp_urls(thing_offers: list[Offer], exclude: Offer | None = None) -> list[str]:
    comps = set(resale_comps(thing_offers, exclude))
    if not comps:
        return []
    key = _memo_key("comp_urls", thing_offers)      # the same 8 URLs for every offer of the Thing
    memo = _MEMO.get()
    if key is not None and memo is not None and key in memo:
        return list(memo[key])
    out = [x.url for x in thing_offers if x.condition == "used"
           and not _list_offer(x) and price_of(x) in comps][:8]
    if key is not None and memo is not None:
        memo[key] = tuple(out)
    return out


# ---------------------------------------------------------------- REFERENCE PRICE (robust, per hunt)
# Hundreds of marketplace rows (vinted, tori, marktplaats, olx ...) are mostly cases, boxes, single earbuds and
# €30 'new sealed' copies: a median over them calls a €30 'AirPods Pro 2' typical. So the reference is built from
# the most trustworthy signals first: the median NEW price at real shops / comparison sites (gigantti, verkkokauppa,
# hinta.fi, amazon ...), then refurbished shop prices (backmarket, refurbed), and only then the marketplace rows that passed
# the relevance and red-flag filters, taking the median of their UPPER 60% (a flood of cheap junk cannot drag it).
# A used / private 'new' / marketplace listing under REF_FLOOR[category] x that new reference is "too good to be
# true: probably a part, a single earbud, broken or fake": shown, never priced into a median, never the pick.

REF_FLOOR = {"phone": 0.35, "tablet": 0.35, "laptop": 0.30, "camera": 0.40, "lens": 0.40, "console": 0.35,
             "audio": 0.38, "wearable": 0.33, "tv": 0.25, "luxury watch": 0.50}
REF_FLOOR_OTHER_MODEL = 0.30   # any other category, when the need names a model ('dyson v15', 'kindle 11')
REFURB_TO_NEW = 0.85           # a refurbished shop price is ~85% of new: new reference when no shop sells it new
UPPER_SHARE = 0.60             # the marketplace reference is the median of the top 60% of matching listings
MIN_MARKET_REF = 5             # marketplace listings needed before they alone set a reference
MIN_USED_FLOOR_N = 15          # this many marketplace listings set the floor from their own median ...
USED_FLOOR_SHARE = 0.75        # ... at this share of what they ask (when lower than ratio x new)
STALE_FLOOR_SHARE = 0.85       # ... when ratio x new sits above this share of it
PRIVATE_NEW = "new (private seller)"
_MARKET_KINDS = ("classifieds", "resale", "auction", "specialist")


@functools.lru_cache(maxsize=4096)
def _marketplace_host(host: str) -> bool:
    if any(n in host for n in MARKETPLACES):
        return True
    try:
        from agora.marketplaces import second_hand
        sh = second_hand(host)
    except Exception:
        sh = None
    return bool(sh and sh[1] in _MARKET_KINDS)


def is_marketplace(o: Offer) -> bool:
    """A classifieds / resale platform (tori, vinted, marktplaats, olx, ebay ...): private sellers, not a shop."""
    return _marketplace_host(_host(o.url) or (o.source or "").lower())


def private_new(o: Offer) -> bool:
    """'New' from a private seller on a marketplace is not shop-new: no warranty, often a copy. Used-like."""
    return o.condition == "new" and is_marketplace(o)


def market_condition(o: Offer) -> str:
    """The condition an offer is compared in: a private seller's 'new' counts with the used listings."""
    return "used" if private_new(o) else o.condition


def _upper_median(prices: list[float], share: float = UPPER_SHARE) -> float:
    s = sorted(prices)
    if len(s) >= 3:
        s = s[len(s) - max(1, round(len(s) * share)):]
    return statistics.median(s)


@dataclass
class Reference:
    new_eur: float                  # what the item costs new (the yardstick)
    floor_eur: float                # used-like listings under this are suspect
    ratio: float
    basis: str                      # 'median of 5 shop prices (gigantti.fi, hinta.fi, ...)'
    shop_new: int = 0
    shop_refurb: int = 0
    market_eur: float | None = None   # upper-60% median of the marketplace listings
    market_n: int = 0
    floor_basis: str | None = None    # set when the floor comes from the used listings, not ratio x new


def _ref_ratio(cat: Category, need: Need | None) -> float | None:
    base = cat.name.split(",")[0]
    if base in REF_FLOOR:
        return REF_FLOOR[base]
    if need is not None and base == "other":
        try:
            from agora.resolve import signature
            if signature(need.thing).models:
                return REF_FLOOR_OTHER_MODEL
        except Exception:
            return None
    return None


def _red_kinds(o: Offer) -> set[str]:
    return {k for k, _, _ in (o.raw.get("red_flags") or [])}


def _ref_usable(o: Offer) -> bool:
    p = price_of(o)
    return (p is not None and p > 1 and not _disputed(o) and not _list_offer(o) and not o.raw.get("from_price")
            and not _red_kinds(o) and o.condition in ("new", "used", "refurbished") and not o.raw.get("with_lens"))


def reference_price(offers: list[Offer], cat: Category, need: Need | None = None) -> Reference | None:
    """The item's robust reference price (see above). None when the category has no floor or nothing to go on."""
    ratio = _ref_ratio(cat, need)
    if ratio is None:
        return None
    shop_new: list[tuple[float, str]] = []
    shop_ref: list[tuple[float, str]] = []
    market: list[float] = []
    for o in offers:
        if not _ref_usable(o):
            continue
        p = price_of(o) or 0.0
        if is_marketplace(o):
            market.append(p)
        elif o.condition == "new":      # out of stock still says what the shop asks for it
            shop_new.append((p, o.source))
        elif o.condition == "refurbished":
            shop_ref.append((p, o.source))
    market_ref = _upper_median(market) if len(market) >= MIN_MARKET_REF else None
    if market_ref is not None:
        # a 'new' shop price at a fraction of what private sellers ask is an add-on that slipped through (live,
        # ps5: a €20 headset at proshop.fi made every €367 console 'priced 17x'): it never sets the reference
        shop_new = [x for x in shop_new if x[0] >= 0.5 * market_ref]
        shop_ref = [x for x in shop_ref if x[0] >= 0.4 * market_ref]

    def shops(xs: list[tuple[float, str]]) -> str:
        names = list(dict.fromkeys(s for _, s in sorted(xs, reverse=True)))
        return ", ".join(names[:3]) + (", ..." if len(names) > 3 else "")

    if shop_new:
        new = statistics.median(p for p, _ in shop_new)      # shops passed resolve: no flood of junk to resist
        basis = (f"new at {shop_new[0][1]}" if len(shop_new) == 1 else
                 f"median of {len(shop_new)} shop prices: {shops(shop_new)}")
    elif shop_ref:
        new = statistics.median(p for p, _ in shop_ref) / REFURB_TO_NEW
        basis = f"from {len(shop_ref)} refurbished shop price{'s' * (len(shop_ref) != 1)} ({shops(shop_ref)}) / {REFURB_TO_NEW:.0%}"
    elif market_ref is not None:
        new = market_ref / max(cat.used_factor, 0.3)
        basis = (f"no shop price: the upper {UPPER_SHARE:.0%} of {len(market)} marketplace listings (median "
                 f"{fmt(market_ref)}) / the usual used share {cat.used_factor:.0%}")
    else:
        return None
    if market_ref is not None and (shop_new or shop_ref) and new < market_ref:
        # the 'shop' prices are under what private sellers ask: accessories that slipped through, not the item
        new, basis = market_ref / max(cat.used_factor, 0.3), basis + f"; raised to the marketplace level {fmt(market_ref)}"
    floor, floor_basis = ratio * new, None
    if len(market) >= MIN_USED_FLOOR_N:
        # plenty of matching marketplace listings: the floor is what they sell for, not a share of a 'new' price
        # that may be a stale launch price (live, iphone 13: €598 x 0.35 = €209 flagged 677 ordinary €189 phones)
        # (the upper-60% median: only when the ratio floor sits right under what sellers ask, at over 85% of it,
        # is that 'new' price stale; a floor well under it is guarding a flood of ear tips and cases)
        med = market_ref or 0.0
        plain = statistics.median(market)
        if STALE_FLOOR_SHARE * med < floor <= med:
            floor = USED_FLOOR_SHARE * med
            floor_basis = (f"{USED_FLOOR_SHARE:.0%} of what {len(market)} marketplace listings ask (upper "
                           f"{UPPER_SHARE:.0%} median {fmt(med)})")
        if USED_FLOOR_SHARE * plain < floor <= plain:
            # no gap between 75% and 85%: a floor at 83% of the plain used median (live, iphone 13: €192 vs a €200
            # median of 907 listings) threw out 407 ordinary used phones; the floor is 75% of what they sell for
            floor = USED_FLOOR_SHARE * plain
            floor_basis = (f"{USED_FLOOR_SHARE:.0%} of the median of {len(market)} marketplace listings "
                           f"({fmt(plain)})")
    return Reference(round(new, 2), round(floor, 2), ratio, basis, len(shop_new), len(shop_ref),
                     round(market_ref, 2) if market_ref is not None else None, len(market), floor_basis)


def _tier_key(title: str) -> frozenset[str]:
    """The version a title names ('pro', 'mini', 'ultra'; 'slim' is the same console): {} for the base model."""
    try:
        from agora.resolve import _tiers, signature
        return frozenset(_tiers(signature(title).variants))
    except Exception:
        return frozenset()


def reference_line(ref: Reference, n_low: int) -> str:
    """One plain sentence: what the item costs new and where the 'too cheap to be real' line sits."""
    if "raised to the marketplace level" in ref.basis:
        head = (f"reference: private sellers ask about {fmt(ref.market_eur or ref.new_eur)} for it (shop prices "
                f"found were lower, so they were probably accessories or another version)")
    else:
        head = f"reference: new {fmt(ref.new_eur)} ({ref.basis})"
    return (head + f"; used or private listings under {fmt(ref.floor_eur)}"
            + (f" ({ref.floor_basis})" if ref.floor_basis else "")
            + f" are treated as parts, broken or fakes ({n_low} flagged)")


def _what_junk(cat: Category) -> str:
    return ("a single earbud, the case only, broken or a fake" if cat.name.startswith("audio")
            else "a part, broken, locked or a fake")


MODEL_CODE = re.compile(r"\b(?:A[1-3]\d{3}|SM-[A-Z]\d{3}[A-Z]?|ILCE-?\d{1,4}[A-Z]*|WH-1000XM\d|WF-1000XM\d)\b")
NEAR_FLOOR = 0.85


def near_floor_with_model_code(o: Offer, ref: Reference) -> bool:
    """A home-country private listing a little under the floor that names the maker's model code ('Apple AirPods
    pro 2 (A2698)' at €80 vs an €83 floor, live): plausible, so flagged for a check instead of thrown out."""
    p = price_of(o)
    if p is None or not ref.floor_eur or p < NEAR_FLOOR * ref.floor_eur or not MODEL_CODE.search(o.title or ""):
        return False
    home = (_home() or "fi").lower()
    return _host(o.url).rsplit(".", 1)[-1] == home


def reference_flag(o: Offer, ref: Reference | None, cat: Category) -> str | None:
    """'too good to be true: ...' for a used-like listing far under the reference new price."""
    p = price_of(o)
    if ref is None or p is None or p <= 1 or not ref.floor_eur:
        return None
    if not (o.condition in ("used", "refurbished") or private_new(o)):
        return None
    if p >= ref.floor_eur:
        return None
    if near_floor_with_model_code(o, ref):
        return None
    what = PRIVATE_NEW if private_new(o) else o.condition
    if ref.floor_basis:
        return (f"too good to be true: {what} {fmt(p)} is under {fmt(ref.floor_eur)} ({ref.floor_basis}): "
                f"probably {_what_junk(cat)}")
    return (f"too good to be true: {what} {fmt(p)} is {1 - p / ref.new_eur:.0%} under the new price "
            f"({fmt(ref.new_eur)}, {ref.basis}); under {fmt(ref.floor_eur)} it is probably {_what_junk(cat)}")


def mark_listings(need: Need, offers: list[Offer]) -> None:
    """Per listing, before anything is judged: red flags in its title / row text / checked description
    (raw['red_flags']), so medians and references never see them. Recomputed on every judge."""
    try:
        from agora.resolve import VEHICLE_FLOOR_EUR, _is_vehicle_need, listing_red_flags, title_red_flags
    except ImportError:
        return
    vehicle = _is_vehicle_need(need)
    body = asks_body(need)
    for o in offers:
        o.raw.pop("with_lens", None)
        if body and _with_lens(o):
            o.raw["with_lens"] = True     # a lens kit never sets the body's reference, band or median
        found = list(title_red_flags(o, need))
        page = o.raw.get("page_red_flags") or []
        found += [tuple(x) for x in page if tuple(x) not in found]
        if o.raw.get("search_text") and is_marketplace(o):
            found += [f for f in listing_red_flags(str(o.raw["search_text"]), need, title=False)
                      if f[0] in ("broken", "fake", "locked") and f not in found]
        if vehicle and o.condition in ("used", "unknown", "new") and (p := price_of(o)) is not None \
                and 1 < p < VEHICLE_FLOOR_EUR and (o.condition != "new" or is_marketplace(o)):
            # a whole car for €100: a scrap / parts car, a placeholder or a scam (live, bright red car: a €100
            # Talbot was the pick and nettiauto's cheapest-first browse page set the 'typical' band)
            found.append(("broken", "too little for a whole car: a scrap or parts car, or a scam", fmt(p)))
        o.raw["red_flags"] = [list(f) for f in found]


def red_flag_flags(o: Offer) -> list[str]:
    """The trust flags for raw['red_flags']: 'red flag: broken or faulty ("rikki")'."""
    out: list[str] = []
    page = {tuple(x) for x in o.raw.get("page_red_flags") or []}
    for f in o.raw.get("red_flags") or []:
        k, what, phrase = f
        where = "the description says " if tuple(f) in page else ""
        out.append(f"red flag: {where}{what} (“{str(phrase)[:40]}”)")
    return out


# memo for market_prices / market_floor within one judge() run (hundreds of offers x several calls per offer)
_MEMO: contextvars.ContextVar[dict[Any, Any] | None] = contextvars.ContextVar("judge_memo", default=None)


def _memo_clear() -> None:
    memo = _MEMO.get()
    if memo is not None:
        memo.clear()


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


@functools.lru_cache(maxsize=50000)
def _host(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""


_NEW_PRICE_MARK = r"\W{0,3}(?:\(?\s*(?:uusi|uutena|new|neu|neupreis|uvp|rrp|msrp|ord\.?|ordinarie|nypris|ny\s?pris|"
_NEW_PRICE_MARK += r"nieuwprijs|listapreis|list\s+price|was|oli|normaalisti|norm\.?)\b|\(\s*u[a-z]{0,3}(?:\.{2,3}|…))"


def _marked_new_price(o: Offer, amount: Any) -> bool:
    """The witness amount is the new / list price printed next to the real one ('FAIR Apple MacBook Air 2022 | M2
    699 € 1 499 € (Uusi)' on refurbed.fi): no disagreement about this offer's price."""
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return False
    whole = f"{int(a):,}".replace(",", r"[\s.,\u00a0]?")
    text = f"{o.title or ''} | {o.raw.get('search_text') or ''}"
    return bool(re.search(rf"(?<!\d){whole}(?:[.,]\d{{2}})?\s?(?:€|eur)?{_NEW_PRICE_MARK}", text, re.I))


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
        if q and not _marked_new_price(o, w.get("price")):
            others.append((str(w.get("via", "?")), q, _independent(o, w)))
    texts = text_prices(o) if p is not None and not any(via == "snippet" for via, _, _ in others) else []
    texts = [q for q in texts if not _marked_new_price(o, q)]
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
                 discount: str | None = None, floor: float = 0.0, ref: Reference | None = None,
                 cat: Category | None = None, mixed: str | None = None, own_shop: bool = False
                 ) -> tuple[float, list[str]]:
    """0..1 plus human-readable flags. `peers` = the offers for the same Thing (may include `o`).
    `photos` = agora.trust.same_photo_groups over the hunt (computed once by judge); `discount` = a
    'discount inflated' flag from `discount_check`; `ref` = the hunt's robust reference price."""
    was_disputed = _disputed(o)
    try:
        return _assess_trust(o, peers, photos=photos, discount=discount, floor=floor, ref=ref, cat=cat,
                             mixed=mixed, own_shop=own_shop)
    finally:
        if _disputed(o) != was_disputed:
            _memo_clear()       # a newly disputed price leaves the market: medians memoised so far are stale


def _assess_trust(o: Offer, peers: list[Offer], *, photos: dict[int, list[Offer]] | None,
                  discount: str | None, floor: float, ref: Reference | None,
                  cat: Category | None, mixed: str | None = None, own_shop: bool = False) -> tuple[float, list[str]]:
    """`mixed`: the offer's Thing is a mixed bag of models (a kind of thing: 'road bike', 'sofa', a tree hunt;
    'mixed-bulky' for furniture / prams): its median is no yardstick for one listing (a €190 used Trek is not
    'too good to be true' next to a €500 median of carbon bikes, a €10 sofa is a giveaway), so the price-ratio
    rules are off and only a far-off price (under MIXED_FLOOR of the median, not for bulky things) is suspect.
    `own_shop`: the maker's own shop (ikea.com for IKEA) sets the new price, it is never too good to be true."""
    score = 1.0
    cap = 1.0
    flags: list[str] = []
    p = price_of(o)
    cond = market_condition(o)
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
    for f in red_flag_flags(o):
        score -= 0.6
        flags.append(f)
    if private_new(o):
        flags.append(f"{PRIVATE_NEW}: sold as new on a marketplace, compared with used listings (no shop warranty)")
    if not mixed and (ref_flag := reference_flag(o, ref, cat or DEFAULT_CATEGORY)):
        score -= 0.6
        flags.append(ref_flag)
    o.raw.pop("near_floor", None)
    if not mixed and ref is not None and p and ref.floor_eur and p < ref.floor_eur \
            and near_floor_with_model_code(o, ref):
        o.raw["near_floor"] = True       # costed and shown, never the pick
        score -= 0.15
        flags.append(f"a little under the usual floor ({fmt(ref.floor_eur)}) but names its model code "
                     f"({MODEL_CODE.search(o.title or '').group(0)}): check the listing")  # type: ignore[union-attr]

    pool = peers if any(x is o for x in peers) else peers + [o]
    floor = max(floor, market_floor(pool))
    if mixed:
        floor = 0.0 if mixed == "mixed-bulky" else floor * MIXED_FLOOR / SCALE_FLOOR
    if own_shop and o.condition == "new":
        floor = 0.0
    if (p and floor and p < floor and o.condition in ("new", "used", "refurbished")
            and o.raw.get("price_check") != "verified" and not any(f.startswith("too good") for f in flags)):
        # ear tips (€10) among €170 AirPods, an OLED panel (€90) among €300 consoles: not the item
        score -= 0.5
        flags.append(f"too good to be true: {fmt(p)} is under a quarter of this item's going price "
                     f"({fmt(floor / SCALE_FLOOR)} median): probably a part, an accessory or a misread")
    # services: an hourly rate is compared with hourly rates, never with a €3/m² line
    same = market_prices([x for x in pool if x.unit == o.unit and x.raw.get("coverage") == o.raw.get("coverage")]
                         if o.condition == "service" else pool, cond)
    med_same = _median(same)
    # services: a 'median' of 2 job prices (a €15 surcharge line and an €80 estimate) is no market
    if p and med_same and len(same) >= (3 if o.condition == "service" else 2) and not _disputed(o) \
            and not mixed and not (own_shop and o.condition == "new"):
        r = p / med_same
        # a plan read off the provider's own pricing page, priced per month / year: a cheaper plan among a handful
        # of agencies is a cheaper plan, not a fake (live: draftss.com $265/mo vs a median of 8 agencies)
        plan = o.condition == "service" and period_of(o) in ("month", "year", "week") and len(same) < 15
        if r < 0.5 and plan:
            score -= 0.2
            flags.append(f"well under the usual {cond} price ({1 - r:.0%} below {fmt(med_same)})")
        elif r < 0.5 and not any(f.startswith("too good to be true") for f in flags):
            score -= 0.5
            flags.append(f"too good to be true: {1 - r:.0%} under the {cond} median ({fmt(med_same)})")
        elif 0.5 <= r < 0.7:
            score -= 0.2
            flags.append(f"well under the usual {cond} price ({1 - r:.0%} below {fmt(med_same)})")
        elif r > 2.5:
            score -= 0.1
            flags.append(f"priced {r:.1f}x the {cond} median ({fmt(med_same)})")
        if r < 0.5 and o.read_via == "contextdev_product" and o.raw.get("price_check") not in ("verified", "consistent"):
            # the product format sometimes reads another item's price off the page (mpb: €239 for an A7 III)
            o.raw["price_check"] = "disputed"
            texts = text_prices(o)
            seen = f"; the listing text says {', '.join(fmt(x) for x in texts[:2])}" if texts else \
                "; nothing in the title or search listing backs it"
            flags.append(f"price disagrees: product read {fmt(p)} vs the {o.condition} market {fmt(med_same)}{seen} "
                         f"(probably another item's price on the page)")

    o.raw.pop("far_under", None)
    o.raw.pop("mixed_ratio", None)
    if mixed and p and med_same and len(same) >= 5 and cond in ("new", "used", "refurbished"):
        o.raw["mixed_ratio"] = round(p / med_same, 3)     # the pick of a mixed bag sits in its usual range
    if mixed and p and med_same and len(same) >= 5 and cond in ("new", "used", "refurbished") \
            and p < (MIXED_LOW_BULKY if mixed == "mixed-bulky" else MIXED_LOW) * med_same \
            and not any(f.startswith("too good to be true") for f in flags):
        # a €5 sofa or a €10 road bike among €800 ones: a giveaway, a placeholder, a kids' or a very old one.
        # Shown and costed, but never the pick while sensibly priced ones exist
        o.raw["far_under"] = True
        score -= 0.1
        flags.append(f"far under the usual {cond} price ({fmt(med_same)} median): a giveaway, an older or "
                     "smaller one, or a placeholder price; check the listing")
    if (p and cond in ("used", "refurbished") and not _disputed(o) and not mixed
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
    if p and cond == "new" and len(used) >= 2 and p < 0.8 * (_median(used) or 0) and not mixed and not own_shop:
        score -= 0.3
        flags.append(f"'new' but cheaper than used ones ({fmt(_median(used) or 0)} median used)")
    if p and cond == "used" and new and p > min(new) and not mixed:
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
        from agora import reviews, trust
        # a marketplace PLATFORM's rating (marktplaats ★1.2 from its own users' gripes) labels the platform; it
        # never sets aside the individual listings of its many sellers, each is judged on its own
        if not trust.is_marketplace(o.url):
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
    # event packages: one band per coverage (a full day is never 'high' against ceremony-only packages)
    covers = {o.raw.get("coverage") for o in thing.offers if o.condition == "service" and "coverage" in o.raw}
    for cov in covers:
        group = [o for o in thing.offers if o.condition == "service" and "coverage" in o.raw
                 and o.raw.get("coverage") == cov]
        b = band_for(group, "service", unit="job", history=history, now=now)
        if b:
            b["coverage"] = COVER_WORDS.get(cov, "coverage not stated")
            out[f"service/job/{cov}"] = b
    return out


def _band_key(o: Offer) -> str:
    if o.condition == "service" and "coverage" in o.raw:
        return f"service/job/{o.raw.get('coverage')}"
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
    if "coverage" in o.raw:
        return f"price per package ({COVER_WORDS.get(o.raw.get('coverage'), 'coverage not stated')})"
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
        # units of a dealer page (#unit-2, or each its own link) are different items, never a VAT pair:
        # £818 vs £678 is a grade apart, not 20% VAT
        page = o.url if o.raw.get("unit_of") else _page_key(str(o.raw.get("final_url") or o.url))
        key = (page, o.condition, o.unit)
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


# Customs clearance: UPS / DHL / FedEx charge the buyer a clearance ("disbursement") fee on top of the import
# VAT, typically €10-20; the post's handling fee is lower. Estimates, labelled "est." on the receipt.
COURIER_CLEARANCE = 15.0        # middle of the typical €10-20
POSTAL_CLEARANCE = 5.0          # private sellers usually post it; postal handling is a few euros
DUTY_FREE_FROM = 150.0          # goods over €150 can owe customs duty on top of VAT
# ITA (WTO Information Technology Agreement): no EU customs duty on these, whatever the price
ITA_ZERO_DUTY = {"camera": "cameras", "phone": "phones", "tablet": "tablets", "laptop": "laptops"}


def clearance_fee(o: Offer) -> tuple[str, float]:
    """(receipt label, est. EUR) for clearing an import through customs."""
    if _domain_in(o.source, MARKETPLACES) or o.raw.get("page_type") == "listing":
        return ("postal customs handling fee (est., usually under €10)", POSTAL_CLEARANCE)
    return ("courier customs clearance fee (est., UPS/DHL/FedEx typically €10–20)", COURIER_CLEARANCE)


def duty_line(o: Offer, p: float) -> tuple[str, float] | None:
    """Customs duty, honestly and simply: 0% for ITA electronics; above €150 other goods may owe some."""
    if p <= DUTY_FREE_FROM:
        return None
    cat = category_for(o.title)
    if cat.name in ITA_ZERO_DUTY:
        return (f"customs duty: 0% for {ITA_ZERO_DUTY[cat.name]} (ITA agreement)", 0.0)
    return ("customs duty: possible over €150, depends on the category (not priced)", 0.0)


def import_lines(o: Offer) -> list[tuple[str, float]]:
    """Receipt lines for buying from a shop outside the EU (judged by the price currency): VAT (theirs off,
    Finland's on), the courier's clearance fee (est.) and a customs-duty note above €150."""
    p = price_of(o)
    cur = (o.currency or "EUR").upper()
    if p is None or o.condition == "service" or cur not in NON_EU_CURRENCIES:
        return []
    if cur in EXPORT_VAT:
        country, vat = EXPORT_VAT[cur]
        net = p / (1 + vat)
        lines = [(f"{country} VAT {vat:.0%} off on export (est.)", -round(p - net, 2)),
                 (f"FI import VAT {IMPORT_VAT:.1%} on the export price (est.)", round(net * IMPORT_VAT, 2))]
    else:
        net = p
        lines = [(f"import VAT {IMPORT_VAT:.1%} (shop outside the EU, est.)", round(p * IMPORT_VAT, 2))]
    lines.append(clearance_fee(o))
    duty = duty_line(o, net)
    if duty:
        lines.append(duty)
    return lines


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


# ---------------------------------------------------------------- PERIOD PRICES (subscriptions, retainers, rates)
# A plan per month is not an owned thing: nothing to resell, and its cost is the price per its period. Offers are
# compared like with like: recurring plans by their monthly price (a yearly plan / 12), hourly rates with hourly
# rates, project prices with project prices.

PERIOD_UNITS = {"month": "month", "mo": "month", "monthly": "month", "kk": "month", "year": "year", "yr": "year",
                "annual": "year", "yearly": "year", "week": "week", "wk": "week", "hour": "hour", "h": "hour",
                "day": "day", "job": "job", "project": "job", "once": "job", "visit": "job"}
PER_MONTH = {"month": 1.0, "year": 1 / 12, "week": 52 / 12}
PERIOD_GROUP = {"month": "month", "year": "month", "week": "month", "hour": "hour", "day": "day", "job": "job"}
PERIOD_WORD = {"month": "month", "year": "year", "week": "week", "hour": "hour", "day": "day", "job": "project"}
_SYM = {"EUR": "€", "USD": "$", "GBP": "£"}


def money(amount: float, currency: str | None) -> str:
    """The price as the provider states it: '$4,995', '€49.90', '1,200 SEK'."""
    cur = (currency or "EUR").upper()
    num = f"{amount:,.2f}" if abs(amount) < 100 and round(amount, 2) != round(amount) else f"{amount:,.0f}"
    return f"{_SYM[cur]}{num}" if cur in _SYM else f"{num} {cur}"


def period_of(o: Offer) -> str | None:
    """month | year | week | hour | day | job for a period-priced offer (a plan, a rate), else None."""
    unit = (o.unit or (o.raw.get("period") if isinstance(o.raw, dict) else None) or "").lower().strip()
    return PERIOD_UNITS.get(unit)


def is_periodic(o: Offer) -> bool:
    """A service / subscription price per period (never resold): a long-tail plan or a service rate."""
    return period_of(o) is not None and (o.condition == "service" or bool(o.raw.get("longtail")))


def period_cost(o: Offer, months: int = DEFAULT_MONTHS) -> TrueCost | None:
    """A plan or rate costed per its period, nothing to resell. Recurring plans: per_month_eur = the monthly
    price (a yearly plan / 12) and total_eur = `months` of it; hour / day / project: per_month_eur = the
    price per that unit (TrueCost.per says which), total_eur = one unit."""
    p = price_of(o)
    per = period_of(o)
    if p is None or per is None:
        return None
    o.raw["period_group"] = PERIOD_GROUP[per]
    stated = money(o.price if o.price is not None else p, o.currency if o.price is not None else "EUR")
    word = PERIOD_WORD[per]
    in_eur = "" if (o.currency or "EUR").upper() == "EUR" else f" (≈ {fmt(p)})"
    plan = (o.raw.get("plan") or {}).get("name") if isinstance(o.raw.get("plan"), dict) else None
    named = f" ({plan})" if plan else ""
    conf = "medium" if o.read_via in ("search_highlight", "longtail_registry") else "high"
    if per in PER_MONTH:
        monthly = p * PER_MONTH[per]
        total = monthly * months
        receipt = [(f"{stated}/{word}{in_eur}{named}", round(p, 2))]
        if per != "month":
            receipt.append((f"= {fmt(monthly)}/month", 0.0))
        receipt.append((f"{months} months", round(total, 2)))
        basis = (f"subscription at {stated} per {word}{in_eur}: nothing to own or resell; "
                 f"{months} months ≈ {fmt(total)}")
        return TrueCost(months, round(p, 2), 0.0, None, round(total, 2), round(monthly, 2), conf,  # type: ignore[arg-type]
                        receipt, basis, per="month")
    receipt = [(f"{stated} per {word}{in_eur}{named}", round(p, 2))]
    basis = {"hour": "hourly rate as stated: the total depends on the hours the work takes",
             "day": "day rate as stated: the total depends on the days the work takes",
             "job": "fixed price per project as stated"}[per]
    return TrueCost(0, round(p, 2), 0.0, None, round(p, 2), round(p, 2), conf, receipt, basis,  # type: ignore[arg-type]
                    per=per)


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
    if is_periodic(o):                 # a monthly plan is not an owned thing: no resale, priced per period
        return period_cost(o, months)
    cat = category or category_for(o.title)
    imports = import_lines(o)
    vat = round(sum(v for _, v in imports), 2)
    fee = buyer_fee(o)
    extras = (o.shipping_eur or 0.0) + vat + fee
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
    if fee:
        receipt.append(("buyer protection fee (platform)", round(fee, 2)))
    if o.shipping_eur:
        receipt.append((_shipping_line(o), round(o.shipping_eur, 2)))
    receipt += imports
    if o.raw.get("shipping_est"):
        basis += f"; shipping is an estimate ({o.raw['shipping_est'].get('basis')})"
    if imports:
        basis += f"; priced in {o.currency}: shop outside the EU, import VAT added"
    if not o.shipping_eur and o.shipping_eur is None and o.condition != "service":
        basis += "; shipping unknown, counted as €0"
    if fxn:
        basis += f"; {fxn[0]}"
        if fxn[1]:
            conf = _STEP_DOWN[conf]
    gnote = grade_note(o, thing_offers)
    if gnote:
        receipt.append((gnote, 0.0))
        basis += f"; {gnote}"
    receipt.append((f"resale in {months} mo", -round(resale, 2)))
    if any(f.startswith("possible grey import") for f in o.flags):
        receipt.append(("warranty risk: possible grey import, no EU manufacturer warranty (not priced)", 0.0))
    return TrueCost(months, round(p, 2), round(extras, 2), round(resale, 2), round(total, 2),
                    round(total / months, 2), conf, receipt, basis)  # type: ignore[arg-type]


GRADE_STEP = 0.05      # grade scores this far apart are a different grade (Excellent 0.9 vs Good 0.8)


def grade_note(o: Offer, thing_offers: list[Offer]) -> str | None:
    """Like for like: the seller's grade of a used / refurbished unit next to the other graded units of the
    same Thing. 'condition: Good (8), shutter count 14,641 (seller's grade); lower than the usual Excellent (9)
    here, so a lower price is expected; same grade elsewhere: €814'. None without a grade."""
    from agora import units
    if o.condition not in ("used", "refurbished") or not isinstance(o.raw.get("grade_score"), (int, float)):
        return None
    desc = units.describe(o.raw)
    note = f"condition: {desc} (seller's grade)"
    mine = float(o.raw["grade_score"])
    peers = [x for x in thing_offers if x is not o and x.condition == o.condition
             and isinstance(x.raw.get("grade_score"), (int, float)) and price_of(x) is not None]
    if len(peers) < 2:
        o.raw["grade_note"] = note
        return note
    scores = sorted(float(x.raw["grade_score"]) for x in peers)
    typical = statistics.median(scores)
    typical_name = next((str(x.raw.get("grade")) for x in sorted(
        peers, key=lambda x: abs(float(x.raw["grade_score"]) - typical))), "")
    same = sorted(p for x in peers if abs(float(x.raw["grade_score"]) - mine) < GRADE_STEP / 2
                  and (p := price_of(x)) is not None)
    if mine <= typical - GRADE_STEP:
        note += f"; lower than the usual {typical_name} here, so a lower price is expected"
    elif mine >= typical + GRADE_STEP:
        note += f"; better than the usual {typical_name} here, so a higher price can be fair"
    if same:
        note += (f"; same grade elsewhere: {fmt(same[0])}" if len(same) == 1 else
                 f"; same grade elsewhere: {fmt(same[0])}–{fmt(same[-1])}")
    o.raw["grade_note"] = note
    return note


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
    if not is_service(need) or o.price_eur is None or "net_of_deduction_eur" in o.raw:
        return
    if AFTER_DEDUCTION.search(o.title or ""):
        r = rate or HOUSEHOLD.rate
        o.raw["net_of_deduction_eur"] = o.price_eur
        o.price_eur = round(o.price_eur / (1 - r), 2)


def _platform(url: str) -> bool:
    try:
        from agora.resolve import _known_platform
        return _known_platform(url)
    except Exception:
        return False


_SLD = {"co", "com", "org", "net", "ac", "gov", "or", "ne"}


def provider_key(o: Offer) -> str:
    """Who sells it: the site's own name without its country ending (holvi.com and holvi.fi are one provider,
    lukro.co.uk is 'lukro'), or the seller's name on a directory / platform / marketplace that lists many."""
    host = _host(o.url).removeprefix("www.")
    raw = o.raw if isinstance(o.raw, dict) else {}
    many = (any(h in host for h in AGGREGATOR_HOSTS) or raw.get("from_list_page") or raw.get("site")
            or _marketplace_host(host) or _platform(o.url))
    if many:
        seller = re.sub(r"\W+", " ", (o.seller or "").lower()).strip()
        return f"{host}|{seller}" if seller else o.url
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SLD:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else host


def _dedupe_service(offers: list[Offer]) -> list[Offer]:
    """One provider's same plan read twice (adcount.fi/en/prices and /en/prices.html, 'EU Sales' €50 both): one
    vote in the median and in 'N plans compared'."""
    seen: set[tuple[str, str, float]] = set()
    same_provider: set[tuple[str, str, str, float]] = set()
    by_seller: dict[tuple[str, str], Offer] = {}
    out: list[Offer] = []
    for o in offers:
        host = _host(o.url).removeprefix("www.")
        price = round(o.price_eur or o.price or 0, 2)
        key = (host, re.sub(r"\W+", " ", (o.title or "").lower()).strip(), price)
        if key in seen and key[2]:
            continue
        seen.add(key)
        # one provider's own site read twice in two languages or on two pages (zoofy.nl 'Schoonmaker voor 2 uur' and
        # 'Cleaner for two hours' €99; tilitoimistonm.fi /en/pricing and / both €99): one provider, one vote. A
        # directory / platform / marketplace lists many providers, so there the seller tells them apart.
        many = (any(h in host for h in AGGREGATOR_HOSTS) or o.raw.get("from_list_page") or o.raw.get("site")
                or _marketplace_host(host) or _platform(o.url))
        if price and not many:
            # ... and one provider on two country domains (holvi.com/fi and holvi.fi, same plan, same price)
            pk = (provider_key(o), "", (o.unit or "").lower(), price)
            if pk in same_provider:
                continue
            same_provider.add(pk)
        # one restaurant / provider listed by several aggregators (live, lunch: UniCafe Kaivopiha 4 times on
        # lounasmenu.fi, luncher.fi and lunchmenu.fi): one row, its lowest price
        # (eval r5: €8.70 at luncher.fi and €9.80 at lunchmenu.fi were two rows): ONE offer, the lower price, with
        # every site that lists it in raw['also_at'] and a note saying so
        sk = (_seller_key(o.seller or ""), (o.unit or "").lower())
        if sk[0] and len(sk[0]) >= 4 and any(h in (o.source or "") for h in AGGREGATOR_HOSTS):
            prev = by_seller.get(sk)
            if prev is not None and _same_place(prev, o):
                keep, drop = (o, prev) if (o.price_eur or 1e9) < (prev.price_eur or 1e9) else (prev, o)
                if keep is o:
                    out[next(i for i, x in enumerate(out) if x is prev)] = o
                    by_seller[sk] = o
                _note_also_at(keep, drop)
                continue
            if prev is None:
                by_seller[sk] = o
        out.append(o)
    for o in out:
        others = [x for x in o.raw.get("also_at") or [] if x.get("source") != o.source]
        if others:
            o.raw["merged_sources"] = sorted({o.source, *(x["source"] for x in others)})
    return out


def also_at_note(o: Offer) -> str | None:
    """'same place also listed at lunchmenu.fi for €9.80: the lower price shown' (a merged aggregator duplicate)."""
    dear = {}
    for x in o.raw.get("also_at") or []:
        if x.get("source") != o.source and (x.get("price_eur") or 0) > (o.price_eur or 0) + 0.004:
            dear.setdefault(x["source"], x)
    if not dear:
        return None
    return ("same place also listed at " + ", ".join(f"{x['source']} for {fmt_rate(x['price_eur'])}"
                                                     for x in list(dear.values())[:3]) + ": the lower price shown")


def _seller_key(name: str) -> str:
    """'UniCafe Kaivopiha' / 'Unicafe Kaivopiha' / 'Lunch – UniCafe Kaivopiha' -> 'unicafe kaivopiha'."""
    t = re.sub(r"\W+", " ", unicodedata.normalize("NFKD", name.lower())).strip()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"^(?:lunch|lounas|ravintola|restaurant|cafe)\s+(?=\w{4})", "", t).strip()


def _same_place(a: Offer, b: Offer) -> bool:
    """Two aggregator rows of one name are one place unless both state different towns ('Fazer Food & Co' in
    Helsinki and in Tampere are two)."""
    la, lb = (_seller_key(x.location or "") for x in (a, b))
    if not la or not lb or la == lb or la in lb or lb in la:
        return True
    ta, tb = la.split()[-1], lb.split()[-1]
    return ta == tb


def _note_also_at(keep: Offer, drop: Offer) -> None:
    seen = keep.raw.setdefault("also_at", [])
    for x in [{"source": drop.source, "url": drop.url, "price_eur": drop.price_eur},
              *(drop.raw.get("also_at") or [])]:
        if x.get("url") != keep.url and all(y.get("url") != x.get("url") for y in seen):
            seen.append(x)


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


# work the Finnish household deduction (kotitalousvähennys) covers: household work (cleaning, care), maintenance
# and renovation of the home, IT installation at home. Not a haircut, a photographer, insurance or bookkeeping.
DEDUCTION_WORK = re.compile(
    r"clean|siivo|kotisiivo|ikkunanpesu|window|household|kotitalous|care|hoiva|hoito(?!la)|nanny|babysit|lastenhoit|"
    r"garden|puutarha|lumity|snow|nurmikko|lawn|plumb|putki|lvi|electric|sähk|sahk|handyman|remont|renovat|"
    r"korjaus|repair|maalaus|paint|kirvesmie|carpent|laatoit|tiling|kattoty|roof|it[- ]?tuki|it support|"
    r"tietokone\w*\s*asennus|install|asennus|huolto|maintenance|muurari|nuohous|chimney|pihaty|kodin", re.I)
NOT_DEDUCTION_WORK = re.compile(r"hair|parturi|kampaamo|beauty|kauneus|nail|kynsi|massage|hieronta|photo|kuvaaja|"
                                r"wedding|\bhää|bike|bicycle|pyörä|pyora|fahrrad|cykel|fiets|gun|\base\w*|shoe|"
                                r"kenkä|watch|kello|phone|puhelin|insur|vakuut|bookkeep|kirjanpi|account|lawyer|legal|tax|"
                                r"car\b|auto(?!mat)|vehicle|tutor|lesson|opetus|course|kurssi|catering", re.I)


def deduction_eligible(need: Need) -> bool:
    """The household deduction applies to this kind of work (home cleaning, care, renovation, trades at home)."""
    cat = need.category or {}
    text = f"{need.thing} {cat.get('id') or ''} {cat.get('label') or ''}"
    return bool(DEDUCTION_WORK.search(text)) and not NOT_DEDUCTION_WORK.search(text)


def deduction_back(gross_labour: float, other_work_this_year: float = 0.0) -> float:
    """What the household deduction gives back for this job, given other household work this year."""
    before = HOUSEHOLD.rate * other_work_this_year - HOUSEHOLD.yearly_excess
    after = HOUSEHOLD.rate * (other_work_this_year + gross_labour) - HOUSEHOLD.yearly_excess
    return round(min(HOUSEHOLD.cap, max(0.0, after)) - min(HOUSEHOLD.cap, max(0.0, before)), 2)


NOT_COMPARABLE = {"fee": "a fee or surcharge, not a price for the job",
                  "off_topic": "a different service",
                  "task": "price for one specific task, not a standard call",
                  "workshop_task": "a price for one specific job (e.g. threading, deactivation), not the hourly "
                                   "rate",
                  "callout": "call-out / visit fee only, labour extra",
                  "premium": "emergency / urgent / weekend rate, not the standard price",
                  "extra": "an add-on line (extra hour, gallery, album), not the package",
                  "hourly_vs_package": "an hourly rate, not compared with full-day packages",
                  "one_off": "a fixed one-off job price, not compared with hourly visits",
                  "tiny_job": "less than one hour of the usual rate: a booking, call or warranty fee, not a clean",
                  "estimate": "a calculator's estimate for example inputs, not a provider's price",
                  "sold_out": "sold out or the deal has ended"}
# 'documentary style wedding photography: 1st hour' €450: the first hour, the following ones cost less
FIRST_HOUR = re.compile(r"\b(?:1st|first)\s+hour|ensimmäinen\s+tunti|ensimmainen\s+tunti|eka\s+tunti|"
                        r"erste\s+stunde|eerste\s+uur|första\s+timmen|forsta\s+timmen", re.I)
FOLLOWING_HOUR = re.compile(r"following\s+hours?|additional\s+hours?|extra\s+hours?|each\s+additional|lisätunti\w*|"
                            r"lisatunti\w*|seuraava\w*\s+tun\w*|weitere\s+stunde\w*|extra\s+uur", re.I)
# a portrait session is not the wedding day (live: 'hääpotrettikuvaus miljöössä — 20 kpl' €460 was the pick)
PORTRAIT_ONLY = re.compile(r"potret\w*|muotokuv\w*|portrait\w*|portret\w*|porträt\w*|engagement|kihla\w*|"
                           r"couple\s+(?:shoot|session)|pariskuva\w*", re.I)
DAY_COVERAGE = re.compile(r"vihki\w*|ceremony|seremonia|dokumentaar\w*|documentary|koko\s+päivä\w*|full\s+day|"
                          r"\d+\s*(?:h|t|tuntia|tunnin|hours?|stunden|uur)\b|juhla\w*|reception|trauung|"
                          r"paketti|package|basic|perus|klassinen|premium", re.I)
TRAVEL_PER_KM = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur)\s*/\s*km|(?:km|kilometri)\w*\s*(?:korvaus|fee|charge)?"
                           r"\s*:?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur)", re.I)


# eval r5 'wedding photographer helsinki': a €550 package of unknown length won over €1,500 full-day ones, which were
# flagged '2.7x median'. A package's coverage (hours / full day / ceremony only) is read from its own line, and
# packages are compared with packages of the same coverage.
COVER_FULL = re.compile(r"koko\s+(?:hää)?päiv\w*|koko\s+(?:haa)?paiv\w*|full[- ]?day|whole\s+day|all[- ]day|"
                        r"ganztag\w*|ganze[nr]?\s+tag|hele\s+dag|heldag\w*|pitkä\s+hääpäivä|pitka\s+haapaiva|"
                        r"long\s+(?:wedding\s+)?day|getting\s+ready\s+(?:to|until|till)\s+(?:the\s+)?(?:first\s+)?"
                        r"dance|aamusta\s+iltaan|from\s+morning", re.I)
COVER_PART = re.compile(r"lyhyt\s+hääpäivä|lyhyt\s+haapaiva|short\s+(?:wedding\s+)?day|half[- ]day|puol\w*\s+päiv\w*|"
                        r"puol\w*\s+paiv\w*|halbtag\w*|halbe[nr]?\s+tag|halve\s+dag|halvdag\w*|mini\s*-?paketti|"
                        r"minipaketti|mini\s+package", re.I)
COVER_CEREMONY = re.compile(r"vihki\w*|ceremony|seremonia\w*|trauung|standesamt\w*|maistraat\w*|elope\w*|"
                            r"registry\s+office|vigsel\w*|bryllupsceremoni|ceremonie", re.I)
COVER_HOURS = re.compile(r"\b(\d{1,2}(?:[.,]5)?)\s*(?:-|–)?\s*(?:h|t|tuntia|tunnin|tunti|hours?|hrs?|stunden|std|uur|"
                         r"timmar|timer|heures)\b", re.I)
COVER_RANK = {"full_day": 4, "part_day": 3, None: 2, "ceremony": 1, "portraits": 0}
COVER_WORDS = {"full_day": "full day", "part_day": "part of the day", "ceremony": "ceremony / short",
               "portraits": "portraits only", None: "coverage not stated"}


def package_coverage(title: str, hours: Any = None) -> tuple[str | None, float | None]:
    """(group, hours) of an event package from its own line: 'full_day' (>= 7 h or 'koko päivä'), 'part_day'
    (3-6.5 h, 'lyhyt hääpäivä'), 'ceremony' (<= 2.5 h, 'vihkiminen', 'elopement'), 'portraits' (a portrait session
    with no ceremony or hours), None when the line does not say. hours: the line's own stated hours (min_hours)."""
    t = title or ""
    h: float | None = None
    if m := COVER_HOURS.search(t):
        h = float(m.group(1).replace(",", "."))
    elif isinstance(hours, (int, float)) and 0.5 <= hours <= 16:
        h = float(hours)
    if h is not None and not 0.5 <= h <= 16:
        h = None
    if COVER_FULL.search(t) or (h is not None and h >= 7):
        return "full_day", h
    if COVER_PART.search(t) or (h is not None and h >= 3):
        return "part_day", h
    if COVER_CEREMONY.search(t) or (h is not None and h < 3):
        return "ceremony", h
    if PORTRAIT_ONLY.search(t):
        return "portraits", h
    return None, h


def wedding_need(need: Need) -> bool:
    return bool(JOB_HOURS[0][0].search(f"{need.thing} {(need.category or {}).get('label') or ''}"))


def mark_coverage(need: Need, offers: list[Offer]) -> None:
    """raw['coverage'] / raw['coverage_hours'] on each package of a wedding need (before any median is taken)."""
    wedding = wedding_need(need)
    for o in offers:
        o.raw.pop("coverage", None)
        o.raw.pop("coverage_hours", None)
        if not wedding or (o.unit or "") != "job":
            continue
        group, h = package_coverage(o.title or "", o.raw.get("min_hours"))
        o.raw["coverage"] = group
        if h is not None:
            o.raw["coverage_hours"] = h


def portrait_only(o: Offer, need: Need) -> bool:
    """A wedding asked, a portraits-only package offered (no ceremony, no hours of coverage)."""
    t = o.title or ""
    return bool(JOB_HOURS[0][0].search(need.thing or "") and PORTRAIT_ONLY.search(t) and not DAY_COVERAGE.search(t))
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
    """Providers cut from one directory page vote once in a service median (10 yoopies cleaners = 1 voice), and
    one provider's two pages or two country domains are one voice too."""
    return o.raw.get("from_list_page") or provider_key(o)


# how long one job of these services usually is, when the page prices it by the hour and no size is asked
JOB_HOURS: list[tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"wedding|hää|haa(?:kuva|t\b)|hochzeit|bruiloft|bryllup|bröllop|brollop", re.I), 8.0,
     "a wedding day"),
    (re.compile(r"photograph|kuvaaja|valokuva|fotogra", re.I), 2.0, "a typical shoot"),
    (re.compile(r"haircut|hiustenleik|parturi|barber|friseur|kapper", re.I), 1.0, "one visit"),
    (re.compile(r"moving|movers|muutto|umzug|verhuiz|flytt", re.I), 4.0, "a typical move"),
]


SOLD_OUT = re.compile(r"\b(?:sold\s+out|uitverkocht|ausverkauft|loppuunmyyty|loppuunmyyt\w*|slutsåld|slutsald|"
                      r"udsolgt|utsolgt|deal\s+(?:has\s+)?ended|expired|verlopen|abgelaufen|päättynyt|paattynyt)\b", re.I)
SOLD_OUT_TEXT = re.compile(r"\b(?:sold\s+out|uitverkocht|ausverkauft|loppuunmyyty|loppuunmyyt\w*|slutsåld|slutsald|"
                           r"udsolgt|utsolgt|deal\s+(?:has\s+)?ended|deal\s+expired|niet\s+meer\s+beschikbaar|"
                           r"nicht\s+mehr\s+verfügbar|ei\s+enää\s+saatavilla|tarjous\s+on\s+päättynyt)\b", re.I)


def sold_out(o: Offer) -> bool:
    """A deal / slot you can no longer get: the page says out of stock, or the title (or the deal box of the
    page) says sold out / ended. Per listing: a site's other deals stay."""
    if o.in_stock is False or SOLD_OUT.search(o.title or ""):
        return True
    raw = o.raw if isinstance(o.raw, dict) else {}
    if raw.get("availability") and re.search(r"outofstock|soldout|discontinued", str(raw["availability"]), re.I):
        return True
    return bool(raw.get("deal") or _deal_url(o.url)) and bool(
        SOLD_OUT_TEXT.search(" ".join(str(raw.get(k) or "")[:400] for k in ("description", "snippet"))))


def _deal_url(url: str) -> bool:
    return bool(re.search(r"socialdeal\.|groupon\.|letsdeal\.|tuplaus\.|/deals?/|/aanbieding", url or "", re.I))


# 'no call-out fee' stated: a real zero, never replaced by an estimate
NO_CALLOUT = re.compile(r"\b(?:no|free|without|zero)\s+(?:call[- ]?out|travel|visit)\s+(?:fee|charge|cost)s?|"
                        r"ei\s+(?:käynti|kaynti|lähtö|lahto|matka)\w*|(?:käynti|kaynti|lähtö|lahto)maksu\w*\s+0\s*(?:€|eur)|"
                        r"keine\s+anfahrt\w*|anfahrt\s+(?:kostenlos|gratis|inklusive|inkl)|"
                        r"geen\s+voorrijkosten|gratis\s+voorrij\w*|ingen\s+(?:framkörning|framkorning|utryckning)\w*",
                        re.I)
# a typical call-out / visit fee for an open trade when no provider of the hunt states one (an assumption, shown
# as such on the receipt)
TYPICAL_CALLOUT_EUR = 40.0


def stated_callout(o: Offer, need: Need) -> float | None:
    """The call-out / visit fee the provider's page states: its own field, a call-out line of its price list
    ('Huoltoautokorvaus €35'), or 0 when it says there is none. None = not stated."""
    raw = o.raw if isinstance(o.raw, dict) else {}
    c = raw.get("callout_fee")
    if isinstance(c, (int, float)) and c >= MIN_CALLOUT_EUR:
        return float(c)
    from agora import resolve
    lines = [x for x in raw.get("other_prices") or [] if isinstance(x, dict) and x.get("price_eur")
             and (x.get("kind") == "callout" or resolve.service_line_kind(need, x.get("title") or "", x.get("unit"))
                  == "callout") and MIN_CALLOUT_EUR <= float(x["price_eur"]) <= 250]
    if lines:
        return float(min(x["price_eur"] for x in lines))
    text = " ".join(str(x) for x in (o.title, raw.get("description"), raw.get("snippet"), raw.get("search_text")) if x)
    if NO_CALLOUT.search(text) or (isinstance(c, (int, float)) and c == 0):
        return 0.0
    return None


def travel_per_km(o: Offer) -> float | None:
    """The travel charge per km a page states ('Travelling fee €0.46/km'): the provider's own travel terms, so no
    typical call-out fee is assumed for it (it is not in the total either: the distance is unknown)."""
    raw = o.raw if isinstance(o.raw, dict) else {}
    c = raw.get("callout_fee")
    if isinstance(c, (int, float)) and 0 < c < MIN_CALLOUT_EUR:
        return float(c)
    for x in raw.get("other_prices") or []:
        if isinstance(x, dict) and isinstance(x.get("price_eur"), (int, float)) and 0 < x["price_eur"] < MIN_CALLOUT_EUR \
                and re.search(r"travel|matka|km|kilometr|anfahrt|voorrij|reise", str(x.get("title") or ""), re.I):
            return float(x["price_eur"])
    km = TRAVEL_PER_KM.search(" ".join(str(x) for x in (o.title, raw.get("search_text"), raw.get("description"),
                                                         raw.get("snippet")) if x))
    if km:
        try:
            return float((km.group(1) or km.group(2) or "").replace(",", "."))
        except ValueError:
            return None
    return None


def job_hours(need: Need) -> tuple[float, str] | None:
    cat = need.category or {}
    text = f"{need.thing} {cat.get('label') or ''}"
    return next(((h, what) for rx, h, what in JOB_HOURS if rx.search(text)), None)


def service_cost(o: Offer, need: Need) -> TrueCost | None:
    """One job, with the math shown: unit price x size/hours + call-out fee. The headline is the gross
    price; the household deduction is a conditional note (it depends on the person's whole year).
    `months` is 0, `per` is 'job' and `per_month_eur` is the job total (kept for older readers)."""
    p = price_of(o)
    unit = (o.unit or "").lower()
    if p is None or unit not in ("hour", "m2", "job", "visit"):
        return None
    from agora import resolve
    if sold_out(o):
        # a sold-out deal or a booked-out slot is not a price you can get (eval r1, socialdeal.nl €19 for 3 h)
        o.raw["not_comparable"] = NOT_COMPARABLE["sold_out"]
        return None
    kind = o.raw.get("line_kind") or resolve.service_line_kind(need, o.title or "", o.unit)
    trade = resolve.is_open_trade(need)
    workshop = resolve.is_workshop_trade(need)
    if workshop and unit in ("job", "visit") and kind in ("main", "task"):
        # the firm's own name is no job ('Aseseppä Timo Taskinen' €60 is a general price, not a task)
        kind = "main" if resolve.generic_trade_line(need, o.title or "", o.source or "", o.seller or "") else "task"
        o.raw["line_kind"] = kind
    if workshop and kind == "task":
        o.raw["not_comparable"] = NOT_COMPARABLE["workshop_task"]
        return None
    if kind in ("fee", "off_topic", "premium", "extra") or ((trade or workshop) and kind in ("task", "callout")):
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
    if unit == "job" and (inst := INSTALMENTS.search(o.title or "")):
        # 'Epic hääportretit (neljä maksuerää)' €215 is one of four payments: the job costs 4 x €215
        n = _instalment_count(inst.group(1))
        if n and 2 <= n <= 24:
            o.raw["instalments"] = n
            basis.append(f"the page price {fmt(p)} is one of {n} instalments: {n} x {fmt(p)}")
            p = round(p * n, 2)
    rate = p
    size = job_size_m2(need)
    conf: str = "high"
    tier = f" {o.raw['tier']}" if o.raw.get("tier") else ""
    if unit == "hour":
        stated = o.raw.get("m2_per_hour")
        speed = float(stated) if isinstance(stated, (int, float)) and stated > 0 else M2_PER_HOUR
        mh = o.raw.get("min_hours")
        est_mh = o.raw.get("est_min_hours")       # the minimum the other providers of this trade state
        typical = job_hours(need)
        default = resolve.TRADE_HOURS if trade else (typical[0] if typical else 2.0)
        floor = float(mh) if isinstance(mh, (int, float)) and 0.5 <= mh <= 12 else default   # page's minimum
        if trade and not isinstance(mh, (int, float)) and isinstance(est_mh, (int, float)) and est_mh > floor:
            floor = float(est_mh)
            o.raw["assumed_min"] = True
        if trade and not isinstance(mh, (int, float)):
            o.raw["assumed_min"] = True       # minimum not stated: at the same price a stated one ranks first
        first = FIRST_HOUR.search(o.title or "")
        nxt = None
        if first:
            nxt = next((float(x["price_eur"]) for x in o.raw.get("other_prices") or []
                        if x.get("price_eur") and FOLLOWING_HOUR.search(x.get("title") or "")), None)
        if workshop:
            # you bring the item in: a standard workshop job is the stated rate x WORKSHOP_HOURS (a stated
            # minimum counts), never a call-out
            hours = max(resolve.WORKSHOP_HOURS, float(mh) if isinstance(mh, (int, float)) and 0.5 <= mh <= 12
                        else 0.0)
            conf = "low"
            o.raw["area_rate_source"] = "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h (standard workshop job, est.)"
        elif trade:
            hours = floor
            conf = "low"
            o.raw["area_rate_source"] = "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h (typical call, est.)"
            if hours == est_mh and not isinstance(mh, (int, float)):
                label += ", the usual minimum of the others (this page states none)"
        elif typical and not size:
            hours = max(floor, typical[0])
            conf = "low"
            o.raw["area_rate_source"] = "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h ({typical[1]}, est.)"
        else:
            need_h = round((size or 50) / speed * 2) / 2
            hours = max(floor, need_h)
            conf = ("high" if stated else "medium") if size else "low"
            where = f"page says {speed:g} m²/h" if stated else f"assumed {M2_PER_HOUR:g} m²/h, same for all"
            o.raw["area_rate_source"] = "page" if stated else "assumed"
            label = f"{fmt(rate)}/h{tier} x {hours:g} h" + (f" for {size:g} m² ({where})" if size
                                                            else " (typical visit, est.)")
            if size and hours > need_h and not isinstance(mh, (int, float)):
                label += f"; {size:g} m² takes about {max(0.5, need_h):g} h, but bookings are usually {hours:g} h minimum"
        if isinstance(mh, (int, float)) and hours == floor and floor != default:
            label += f", page minimum {floor:g} h"
        sticker = rate * hours
        calc = f"{fmt_rate(rate)}/h × {hours:g} h"
        if first and hours > 1:
            if nxt is not None:
                # 'first hour 450€, following hours á 175€' (nooiko.com): not 8 x the first hour
                sticker = rate + nxt * (hours - 1)
                label = f"{fmt(rate)} first hour + {fmt(nxt)}/h x {hours - 1:g} h ({o.raw.get('job_what') or 'est.'})"
                calc = f"{fmt_rate(rate)} first hour + {fmt_rate(nxt)}/h × {hours - 1:g} h"
            else:
                sticker, hours = rate, 1.0
                conf = "low"
                label = f"{fmt(rate)} for the first hour (more hours extra, rate not stated)"
                calc = f"{fmt_rate(rate)} first hour"
                basis.append("only the first hour's price is stated: the full job costs more")
                o.raw["job_hours"] = 1.0
                o.raw["partial_job"] = True       # never the pick over a priced full job
                if "first hour only" not in " ".join(o.flags):
                    o.flags.append("first hour only: the whole job costs more (rate for further hours not stated)")
        o.raw["job_hours"] = hours
        if typical and not size and not trade and not workshop:
            o.raw["job_what"] = typical[1]
    elif unit == "m2" and size:
        label, sticker = f"{fmt(rate)}/m²{tier} x {size:g} m²", rate * size
        calc = f"{fmt_rate(rate)}/m² × {size:g} m²"
    elif unit == "m2":
        return None
    elif workshop and not BUNDLE_HOURS.search(o.title or ""):
        # 'Aseseppä palvelut' €60 with nothing on what it buys: a starting price ('services from'), shown with a
        # note and ranked after the hourly rates x a standard job (eval r5: it was the pick over €75-108/h shops)
        label, sticker = f"from {fmt(rate)} (starting price; what the job includes is not stated)", rate
        calc = f"from {fmt_rate(rate)}"
        conf = "low"
        o.raw["starting_price"] = True
        o.raw["partial_job"] = True
        basis.append("a starting price ('services from'): the real job may cost more; ask what it covers")
        if not any(f.startswith("starting price") for f in o.flags):
            o.flags.append(f"starting price ('from {fmt(rate)}'): what it covers is not stated; ranked after "
                           "hourly rates x a standard job")
    else:
        label, sticker = f"{fmt(rate)} per {unit}{tier}", rate
        bundle = BUNDLE_HOURS.search(o.title or "")
        calc = (f"{bundle.group(1).replace(',', '.')} h for {fmt(rate)}" if bundle else f"fixed price per {unit}")
        if "coverage" in o.raw:
            # a package: what it covers, and per covered hour when the hours are stated (like with like)
            cov, ch = o.raw.get("coverage"), o.raw.get("coverage_hours")
            what = COVER_WORDS.get(cov, "coverage not stated") + (f", {ch:g} h" if isinstance(ch, (int, float)) else "")
            label = f"{fmt(rate)} per package{tier} ({what})"
            if isinstance(ch, (int, float)) and ch > 0:
                o.raw["per_covered_hour"] = round(rate / ch, 2)
                basis.append(f"covers {ch:g} h: {fmt(rate / ch)} per covered hour")
            elif cov is None:
                basis.append("the package does not say how many hours it covers: ask before comparing")
    receipt.append((label, round(sticker, 2)))
    callout = None if workshop else stated_callout(o, need)
    extras = float(callout) if isinstance(callout, (int, float)) and callout >= MIN_CALLOUT_EUR else 0.0
    est_callout = o.raw.get("est_callout_fee") if trade and callout is None else None
    o.raw.pop("assumed_terms", None)
    if extras:
        receipt.append(("call-out fee", round(extras, 2)))
        calc += f" + {fmt(extras)} call-out"
    elif isinstance(est_callout, (int, float)) and est_callout > 0:
        # never costed as zero: a page that states no call-out fee gets the others' usual one (or the trade's
        # typical one), labelled an estimate, and ranks after a provider stating its terms at the same price
        extras = float(est_callout)
        whose = ("typical for the trade" if o.raw.get("est_callout_basis") == "typical"
                 else "the others' usual")
        receipt.append((f"call-out fee (est.: {whose}, this page states none)", round(extras, 2)))
        calc += f" + {fmt(extras)} call-out (est.)"
        o.raw["assumed_terms"] = True
        basis.append(f"call-out fee not stated on the page: {fmt(extras)} assumed ({whose}); ask before booking")
    km = travel_per_km(o)
    if km is not None and not extras:
        basis.append(f"plus travel {km:g} €/km (stated, not in the total)")
        o.raw["travel_per_km"] = km
    if resolve.is_deal(o):
        o.raw["deal"] = True
        basis.append("deal / voucher price: check its conditions (often first booking only)")
    if workshop and unit == "hour":
        basis.append(f"estimate: a standard workshop job of {hours:g} h at the stated hourly rate; you bring the "
                     "item in, so no call-out fee")
    if trade:
        used_h = hours if unit == "hour" else resolve.TRADE_HOURS
        basis.append(f"estimate: a standard call of {used_h:g} h labour at the stated hourly rate"
                     + (" plus the call-out fee" if extras else "") + "; the real job may take longer")
    if o.raw.pop("assumed_min", None):
        o.raw["assumed_terms"] = True
    o.raw["calc"] = calc
    total = sticker + extras
    if o.raw.get("recurring_only"):
        basis.append("only recurring-contract prices on the page: highest tier used for one job")
    if FI_PLACES.search(f"{need.where or ''} {need.raw}") and deduction_eligible(need):
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
    from agora.units import is_used_dealer
    if is_used_dealer(o.url) or o.raw.get("unit_of"):
        return False            # a used dealer (Wex, MPB, KEH ...) prices each graded unit; no haggling
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
        elif "VAT" in label or "customs" in label:
            out.append({"line_index": i, "url": None, "via": "rule", "quote": label, "fetched_at": None})
        elif label.startswith("shipping"):
            out.append({"line_index": i, "url": o.url, "via": o.read_via, "quote": "shipping on the page",
                        "fetched_at": wit.get("fetched_at")})
    return out


# ---------------------------------------------------------------- VERDICT

def _budget_eur(need: Need) -> float | None:
    return eur(need.budget, need.currency) if need.budget else None


def _cond(o: Offer) -> str:
    if private_new(o):
        return PRIVATE_NEW
    return {"new": "new", "used": "used", "refurbished": "refurbished", "rental": "renting"}.get(o.condition, o.condition)


# a seller's own low condition grade (vinted 'Kunto: Tyydyttävä', 'Zustand: Akzeptabel', 'Stan: dostateczny')
LOW_GRADE = re.compile(r"\b(?:kunto|zustand|condition|stan|staat|skick|tilstand)\s*:?\s*(?:tyydyttävä|tyydyttava|"
                       r"välttävä|valttava|zufriedenstellend|akzeptabel|ausreichend|satisfactory|fair|acceptable|"
                       r"dostateczny|zadowalający|zadowalajacy|redelijk|acceptabel|godtagbar|okay|ok)\b", re.I)
UNCHECKED_BARGAIN = 0.60   # a used listing under 60% of its band median ...


BODY_ASKED = re.compile(r"\b(?:body|body only|runko|gehäuse|gehause|kropp|korpus|boîtier|boitier|behuizing)\b", re.I)


def asks_body(need: Need) -> bool:
    return need.kind == "product" and bool(BODY_ASKED.search(f"{need.thing} {' '.join(need.must_have)}"))


def _unchecked_bargain(o: Offer, band_of: dict[int, dict[str, Any]]) -> bool:
    """... whose own page was checked and said nothing (raw.page_check.ok is None: no description): too good
    to crown on its title alone (live: an olx.pl 'MacBook Air M2' 47% under the band, empty description)."""
    check = o.raw.get("page_check")
    if not isinstance(check, dict) or check.get("ok") is not None or market_condition(o) != "used":
        return False
    if any(f.startswith(("well under the usual", "too good to be true")) for f in o.flags):
        return True      # live: an olx.pl a7 III kit 35% under the used median, empty page, was the pick
    b = band_of.get(id(o)) or o.raw.get("band") or {}
    med, p = b.get("median"), price_of(o)
    return bool(med and p and p < UNCHECKED_BARGAIN * med)


def _risky(o: Offer) -> bool:
    """Never crowned as the best buy: low trust, a price far under its peers or the reference, a red flag in
    the listing (broken, a copy, one earbud ...), or a disputed price."""
    return ((o.trust if o.trust is not None else 1) < 0.5 or _disputed(o)
            or any(f.startswith(("too good to be true", "red flag")) for f in o.flags))


def _landed(o: Offer) -> float:
    tc = o.true_cost
    if tc is not None:
        return tc.sticker_eur + tc.extras_eur
    return (o.price_eur or 0) + (o.shipping_eur or 0) + import_fee(o) + buyer_fee(o)


def measured_category(cat: Category, depreciation: dict[str, Any] | None) -> Category:
    """The category with its yearly rate replaced by a market-measured one (agora.depreciation)."""
    if not depreciation or not isinstance(depreciation.get("rate"), (int, float)):
        return cat
    return dataclasses.replace(cat, rate=float(depreciation["rate"]),
                               name=f"{cat.name}, {depreciation.get('basis') or 'measured'}")


def _home() -> str | None:
    try:
        from agora.discover import home_country
        return home_country()
    except Exception:
        return "fi"


def _colour_pick(need: Need, pool: list[Offer]) -> tuple[str | None, bool]:
    """(line, unknown) for a need that asks a colour (cars: reader.mark_colour sets raw colour_match).
    line None = no colour asked. unknown = no offer in the pool says it is the asked colour."""
    try:
        from agora.reader import asked_colours
        asked = asked_colours(need)
    except ImportError:
        return None, False
    if not asked or not pool or not any("colour_match" in o.raw for o in pool) and not _vehicle(need):
        return None, False
    colour = "/".join(sorted(asked))
    hits = [o for o in pool if o.raw.get("colour_match") is True]
    if hits:
        return (f"{len(hits)} of {len(pool)} say they are {colour}; the pick is the cheapest of those "
                f"(the rest do not state a colour)"), False
    return (f"none of the {len(pool)} found states its colour as {colour}: colour is not a filter on these "
            f"sites, check the photos"), True


def _vehicle(need: Need) -> bool:
    try:
        from agora.resolve import _is_vehicle_need
        return _is_vehicle_need(need)
    except ImportError:
        return False


def _shipping_flags(o: Offer, need: Need) -> None:
    """agora.shipping: delivery (pickup / ships), estimated cross-border shipping into shipping_eur, flags."""
    try:
        from agora import shipping
    except ImportError:
        return
    home = _home()
    thing = need.thing or ""
    try:
        from agora.resolve import _is_vehicle_need
        if _is_vehicle_need(need):
            thing = f"car {thing}"      # a car abroad ships by car transporter, not as a parcel
    except ImportError:
        pass
    shipping.apply(o, home, thing)
    raw = o.raw
    est = raw.get("shipping_est") or {}
    if raw.get("pickup_abroad"):
        cc = (shipping.offer_country(o) or "").upper()
        o.flags.append(f"pickup only, abroad ({cc}): the seller does not ship to "
                       f"{'Finland' if (home or '').lower() == 'fi' else (home or '').upper()}")
    elif raw.get("abroad") and est:
        o.flags.append(f"abroad ({est.get('src')}): shipping {est.get('text')} estimated, not quoted"
                       + ("; the listing does not say it ships, ask the seller" if shipping.shippable_abroad_unknown(o)
                          else ""))
    elif not raw.get("abroad") and raw.get("delivery") == "pickup" and o.location:
        o.flags.append(f"pickup in {o.location}")


# a vinted row's title ends in both prices: '..., Kunto: Hyvä, 166.50 €, 175.53 €' (the second has the buyer
# protection fee in it); the reader does not always pass it on as raw.price_with_buyer_fee
_TWO_PRICES_END = re.compile(r"(\d{1,6}(?:[.,]\d{1,2})?)\s*€\s*,\s*(\d{1,6}(?:[.,]\d{1,2})?)\s*€\s*(?:,\s*[^,]{0,40})?$")


def _title_buyer_fee(o: Offer) -> float:
    if "vinted" not in (o.source or "") and "vinted" not in (o.url or ""):
        return 0.0
    m = _TWO_PRICES_END.search(o.title or "")
    if not m or o.price is None:
        return 0.0
    first, second = (float(x.replace(",", ".")) for x in m.groups())
    if abs(first - float(o.price)) > 0.02 * max(1.0, first) or not (first < second <= first * 1.25 + 3):
        return 0.0
    rate = (o.price_eur / o.price) if o.price_eur and o.price else 1.0
    return round((second - first) * rate, 2)


def buyer_fee(o: Offer) -> float:
    """Platform buyer fee (vinted's buyer protection), from agora.shipping.apply, else from the row's own two
    prices ('166.50 €, 175.53 €': €9.03 fee)."""
    try:
        fee = float(o.raw.get("buyer_fee_eur") or 0.0)
    except (TypeError, ValueError):
        fee = 0.0
    if not fee and (fee := _title_buyer_fee(o)):
        o.raw["buyer_fee_eur"] = fee
    if not fee:
        for k in ("price_with_buyer_fee", "price_with_fee"):
            try:
                withfee = float(o.raw.get(k) or 0.0)
            except (TypeError, ValueError):
                withfee = 0.0
            if o.price and withfee and o.price < withfee <= o.price * 1.25 + 3:
                rate = (o.price_eur / o.price) if o.price_eur and o.price else 1.0
                fee = round((withfee - o.price) * rate, 2)
                o.raw["buyer_fee_eur"] = fee
                break
    if not fee and ("vinted." in (o.source or "") or "vinted." in (o.url or "")) and (p := price_of(o)):
        # Vinted always adds its buyer protection fee (€0.70 + 5% of the item price) at checkout: never left out
        # of 'all in' (live: 0 of 3,000+ vinted offers carried it)
        fee = round(VINTED_FEE_FIXED + VINTED_FEE_RATE * p, 2)
        o.raw["buyer_fee_eur"] = fee
        o.raw["buyer_fee_est"] = True
    return fee


VINTED_FEE_FIXED = 0.70
VINTED_FEE_RATE = 0.05


SMALL_DELIVERY = (10.0, 20.0)    # a small flat-pack piece (a €29 shelf) goes as a parcel
SMALL_FURNITURE_EUR = 80.0
BULKY_DELIVERY = (30.0, 70.0)    # home delivery of a table / sofa from a Finnish web shop, when the page says nothing


def _bulky_delivery(o: Offer, need: Need) -> None:
    """A bulky thing new from a shop with no delivery fee on the page is not delivered for €0 (live, kitchen table:
    homeroom.fi tables were 'shipping unknown, counted as €0'): a labelled furniture-delivery estimate."""
    if not _bulky(need) or o.condition != "new" or is_marketplace(o) or o.shipping_eur is not None \
            or o.raw.get("shipping_est") or o.raw.get("abroad"):
        return
    lo, hi = BULKY_DELIVERY if (price_of(o) or 0) >= SMALL_FURNITURE_EUR else SMALL_DELIVERY
    o.shipping_eur = round((lo + hi) / 2, 2)
    home = (_home() or "fi").upper()
    o.raw["shipping_est"] = {"src": home, "dst": home, "text": f"€{lo:.0f}–{hi:.0f}", "low": lo, "high": hi,
                             "how": "usual furniture home delivery; the shop's own fee was not on the page",
                             "basis": "furniture delivery estimate"}
    o.flags.append(f"delivery not on the page: €{lo:.0f}–{hi:.0f} estimated for a bulky item")


def _shipping_line(o: Offer) -> str:
    est = o.raw.get("shipping_est") or {}
    if est:
        return f"shipping {est.get('src')}→{est.get('dst')}, est. {est.get('text')} ({est.get('how')})"
    return "shipping / fees"


THIN_PEERS = 3     # a Thing with fewer same-condition prices than this borrows the whole hunt's market


def _peers_for(o: Offer, peers: list[Offer], everyone: list[Offer]) -> list[Offer]:
    """Trust peers: the offer's own Thing, or, when that Thing is too thin to have a market (a listing whose
    title split it off: 'AirPods Pro 2e generatie ... partijhandel' at €25 alone), every offer of the hunt
    so a far-too-cheap one is still called out."""
    if not everyone or len(market_prices(peers, o.condition)) >= THIN_PEERS:
        return peers
    return everyone


def _estimate_missing_minimums(need: Need, offers: list[Offer]) -> None:
    """Like with like for open trades: a page read from a snippet says nothing of a minimum, while fully read
    ones add their 2 h minimum, so the less we knew the cheaper it looked (live: a €55/h x 1 h freelancer beat
    €52/h x 2 h page minimum). The others' usual minimum stands in, labelled an estimate."""
    try:
        from agora import resolve
        if not resolve.is_open_trade(need):
            return
    except Exception:
        return
    known = [float(o.raw["min_hours"]) for o in offers if o.unit == "hour"
             and isinstance(o.raw.get("min_hours"), (int, float)) and 0.5 <= o.raw["min_hours"] <= 12]
    # a per-km travel line (€0.46/km) is no call-out fee: fees under MIN_CALLOUT_EUR never vote (live, plumbing:
    # a €1.63 'call-out (est.)' was added to every provider)
    stated = {id(o): stated_callout(o, need) for o in offers}
    fees = [c for c in stated.values() if c is not None and c >= MIN_CALLOUT_EUR]
    for o in offers:
        o.raw.pop("est_min_hours", None)
        o.raw.pop("est_callout_fee", None)
        o.raw.pop("est_callout_basis", None)
    for o in offers:
        if o.unit != "hour":
            continue
        if known and not isinstance(o.raw.get("min_hours"), (int, float)):
            o.raw["est_min_hours"] = statistics.median(known)
        if stated[id(o)] is None and travel_per_km(o) is None:
            # never costed as zero (eval: an unstated call-out beat honest providers): the others' usual fee, else
            # the trade's typical one
            o.raw["est_callout_fee"] = statistics.median(fees) if fees else TYPICAL_CALLOUT_EUR
            o.raw["est_callout_basis"] = "others" if fees else "typical"


_NUM_WORDS = {"kaksi": 2, "kolme": 3, "neljä": 4, "nelja": 4, "viisi": 5, "kuusi": 6, "two": 2, "three": 3, "four": 4,
              "five": 5, "six": 6, "twelve": 12, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "funf": 5, "sechs": 6,
              "zwölf": 12, "twee": 2, "drie": 3, "tva": 2, "två": 2, "tre": 3, "fyra": 4, "fire": 4}
INSTALMENTS = re.compile(r"\b(\d{1,2}|kaksi|kolme|neljä|nelja|viisi|kuusi|two|three|four|five|six|twelve|zwei|drei|vier|"
                         r"fünf|funf|sechs|zwölf|twee|drie|två|tva|tre|fyra|fire)\s*(?:x\s*)?(?:maksuer\w*|erä\w*|"
                         r"instal+ments?|payments?|monthly\s+payments|raten|termijnen|delbetalning\w*|avdrag)\b", re.I)


def _instalment_count(word: str) -> int | None:
    w = word.lower().strip()
    return int(w) if w.isdigit() else _NUM_WORDS.get(w)


def _family_need(need: Need) -> bool:
    """A maker + product line, no model ('lego technic', 'ikea kallax'): many different items under one name."""
    try:
        from agora.resolve import signature
    except ImportError:
        return False
    sig = signature(need.thing or "")
    return bool(sig.brand and not sig.models and not sig.family and sig.words - {sig.brand})


MIN_CALLOUT_EUR = 10.0     # a 'call-out fee' under €10 is a per-km or per-minute line read as one


def _generic_need(need: Need) -> bool:
    """A kind of thing asked ('road bike', 'sofa', 'puhelin', a tree hunt): no one model's price rules apply."""
    try:
        from agora import resolve
        return resolve.is_generic(need)
    except Exception:
        return False


def _mixed(need: Need, t: Thing) -> str | None:
    """'mixed' / 'mixed-bulky' when the Thing is a mixed bag of models: the need is a kind of thing, or most of its
    offers are marked generic_thing by resolve (late shop rows and merged pages may lack the mark: live, 'road
    bike' lost 406 normal €250-310 bikes to the cheapest-new rule because a few offers were unmarked)."""
    if is_service(need) or not t.offers:
        return None
    marked = sum(1 for o in t.offers if o.raw.get("generic_thing"))
    try:
        from agora.resolve import _is_vehicle_need
        vehicle = _is_vehicle_need(need)
    except Exception:
        vehicle = False
    # one car model spans 20 model years (live, volvo v70: €700 V70s of 2001 were 'under a quarter of this item's
    # going price' next to €4,190 2014 cars): no price ratio says a car is fake; under €500 is flagged on its own
    if not (_generic_need(need) or marked * 2 > len(t.offers) or vehicle):
        return None
    return "mixed-bulky" if _bulky(need) else "mixed"


def _with_lens(o: Offer) -> bool:
    try:
        from agora.resolve import signature
        return signature(o.title or "", o.brand).kit
    except Exception:
        return False


def _main_model_ids(need: Need, things: list[Thing]) -> set[str]:
    """Ids of the Things that are exactly the asked model (same model codes), when the need names one."""
    try:
        from agora.resolve import signature
    except Exception:
        return set()
    want = signature(need.thing).models
    if not want:
        return set()
    out = set()
    for t in things:
        sigs = [signature(o.title or "", o.brand).models for o in t.offers[:15]]
        exact = sum(1 for m in sigs if set(m) == set(want))
        if sigs and exact * 2 >= len(sigs):
            out.add(t.id)
    return out


def _need_brand(need: Need) -> str | None:
    """The maker named in a need for a product line ('ikea kallax shelf' -> ikea). None when a model is named:
    'AirPods Pro 2 Ear Tips' at apple.com are still not AirPods."""
    try:
        from agora.resolve import signature
        sig = signature(need.thing)
        return sig.brand if not sig.models else None
    except Exception:
        return None


_AUD_NAME = {"women": "women's", "men": "men's", "kids": "kids'", "pet": "a pet's"}


def _audience_clash(need: Need, o: Offer) -> str | None:
    """Per listing: the audience asked (women / naisten / Damen, men, kids) against the listing's own words, the
    title first, then its description when the title names none (a 'Talvitakki koko L' whose text says 'miesten').
    -> 'for men's, you asked women's' or None."""
    from agora import resolve
    if not resolve.APPAREL_NEED.search(f"{need.thing} {need.raw}"):
        return None
    want = resolve._audience(f"{need.thing} {need.raw} {' '.join(need.must_have)}") & {"women", "men", "kids"}
    if not want:
        return None
    raw = o.raw if isinstance(o.raw, dict) else {}
    for text in (o.title or "", " ".join(str(raw.get(k) or "")[:600] for k in ("description", "page_description"))):
        have = resolve._audience(text)
        if "pet" in have:
            return "for a pet, not for you"
        if have & {"women", "men", "kids"}:
            if have & want:
                return None
            other = sorted(have & {"women", "men", "kids"})
            return (f"for {'/'.join(_AUD_NAME[x] for x in other)}, you asked "
                    f"{'/'.join(_AUD_NAME[x] for x in sorted(want))}")
    return None


def _judge_offers(need: Need, t: Thing, months: int, seen: dict[str, int],
                  depreciation: dict[str, Any] | None = None, *, history: bool = False,
                  photos: dict[int, list[Offer]] | None = None, floor: float = 0.0,
                  everyone: list[Offer] | None = None, ref: Reference | None = None) -> None:
    cat = measured_category(category_for(" ".join([need.thing, t.name] + [o.title for o in t.offers[:5]])),
                            depreciation)
    for o in t.offers:
        price_of(o)
    if is_service(need):
        t.offers[:] = _dedupe_service(_merge_net_gross(t.offers))
        for o in t.offers:
            _gross_up(o, need, o.raw.get("page_deduction_rate"))
        _estimate_missing_minimums(need, t.offers)
        mark_coverage(need, t.offers)
    else:
        t.offers[:] = _merge_same_page(t.offers)
    mixed = _mixed(need, t)
    brand = _need_brand(need)
    body = asks_body(need)
    from agora import resolve as _resolve
    quoted = quote_only(need) is not None
    for o in t.offers:
        o.raw.pop("other_audience", None)
        if _resolve.calculator_estimate(o) or (quoted and _resolve.insurance_estimate(o)):
            o.raw["estimate"] = "calculator"
        elif not is_service(need) and (aud := _audience_clash(need, o)):
            o.raw["other_audience"] = aud
    for o in t.offers:
        # the body asked: a lens kit, whatever the site, is marked before any median is taken, so kits never set the
        # 'typical used' band (live, sony a7 iii body: marktplaats / tori / blocket kits made it €799-€1,000)
        o.raw.pop("with_lens", None)
        if body and _with_lens(o):
            o.raw["with_lens"] = True
    _memo_clear()
    for o in t.offers:
        discount = discount_check(o, t.offers, history=history)
        own = bool(brand) and brand in _host(o.url).split(".")[0]
        o.trust, new_flags = assess_trust(o, t.offers if mixed else _peers_for(o, t.offers, everyone or []),
                                          photos=photos, discount=discount,
                                          floor=0.0 if is_service(need) else floor, ref=ref, cat=cat, mixed=mixed,
                                          own_shop=own)
        o.flags = [f for f in o.flags if f in ("bundle",)] + new_flags
        if note := _two_prices_note(o):
            o.flags.append(note)
        if note := also_at_note(o):
            o.flags.append(note)
        if o.raw.get("with_lens"):
            o.flags.append("with a lens (you asked for the body only): ranked after body-only offers")
        if o.raw.get("net_of_deduction_eur") is not None:
            o.flags.append(f"page shows {fmt(o.raw['net_of_deduction_eur'])} after the household deduction; "
                           f"compared at the gross {fmt(o.price_eur or 0)}")
        if o.raw.get("recurring_only"):
            o.flags.append("recurring-contract price (no one-time price on the page)")
        if o.raw.get("estimate"):
            o.flags.append("a calculator's estimate for example inputs, not a quote or an offer")
        if o.raw.get("other_audience"):
            o.flags.append(f"{o.raw['other_audience']}: shown, never the pick")
        if (n := seen.get(o.source, 0)) >= 2:
            o.raw["seen_hunts"] = n        # kept for the record; not a flag a shopper needs to read
        if not is_service(need) and not is_periodic(o):
            _shipping_flags(o, need)
            _bulky_delivery(o, need)
        if is_service(need):
            o.raw.pop("partial_job", None)
            if portrait_only(o, need):
                o.raw["partial_job"] = True
                o.flags.append("portraits only, not the wedding day: ranked after full-day / ceremony packages")
            if (o.currency or "").upper() in ("USD", "CAD", "AUD") and need.where and o.location \
                    and need.where.lower() in o.location.lower() and (_home() or "fi") != "us":
                # wezoree.com: a Helsinki photographer 'priced' $15,000, the directory's figure, not theirs
                o.trust = round(max(0.0, (o.trust or 1.0) - 0.5), 2)
                o.flags.append(f"price in {o.currency} on a local provider's page in {need.where}: probably a "
                               "directory's figure, not this provider's; ask them")
    for o in t.offers:
        if o.raw.get("estimate"):
            # a calculator's figure for example inputs is nothing you can buy: shown, never costed or ranked (eval r4,
            # car insurance: 'selkoraha.fi €29/mo overtook service at ayvens.com' on the live leaderboard)
            o.true_cost, o.haggle = None, None
            o.raw["not_comparable"] = NOT_COMPARABLE["estimate"]
            continue
        if is_service(need) and sold_out(o):
            # a sold-out deal or an ended offer is no price you can get: never costed, so never ranked
            o.true_cost, o.haggle = None, None
            o.raw["not_comparable"] = NOT_COMPARABLE["sold_out"]
            continue
        if priced_per_period(need):
            o.true_cost = period_cost(o, months)
            continue
        if is_service(need):
            o.true_cost = service_cost(o, need)
            continue
        if _disputed(o) or o.raw.get("ref_suspect") or (any(f.startswith("too good to be true") for f in o.flags)
                                                          and o.raw.get("price_check") != "verified"):
            o.true_cost, o.haggle = None, None
            o.flags.append("not costed: price unconfirmed (far off the market or disputed)")
            continue
        o.true_cost = estimate_true_cost(o, t.offers, months, cat)
        o.haggle = None if is_periodic(o) else make_haggle(o, t.offers, t.name, cat)
    if is_service(need) and not priced_per_period(need):
        _separate_unlike(need, t.offers)


def _apart(o: Offer, why: str) -> None:
    o.true_cost = None
    o.raw["not_comparable"] = NOT_COMPARABLE[why]
    o.raw["apart_kind"] = why


ONE_OFF_JOB_OK = re.compile(r"m2|m²|neliö\w*|sqm|\d\s*(?:-|–)?\s*(?:huone|room|zimmer|kamer)", re.I)


def _rank_by_coverage(packages: list[Offer]) -> None:
    """Like with like for event packages: the most complete coverage any package states (a full day, else part of
    the day) is what is compared; shorter stated packages (ceremony only, 2 h) are shown and ranked after it, as is
    a package of unstated length priced like a short one (under 60% of the full-coverage packages' median)."""
    stated = [o for o in packages if o.raw.get("coverage") in ("full_day", "part_day")]
    if not stated:
        return
    top = max(COVER_RANK[o.raw.get("coverage")] for o in stated)
    top_group = [o for o in stated if COVER_RANK[o.raw.get("coverage")] == top]
    med = statistics.median(price_of(o) or 0 for o in top_group)
    top_words = COVER_WORDS["full_day" if top == COVER_RANK["full_day"] else "part_day"]
    for o in packages:
        cov = o.raw.get("coverage")
        if COVER_RANK.get(cov, 2) >= top:
            continue
        short = cov is not None or (len(top_group) >= 2 and (price_of(o) or 0) < 0.6 * med)
        if not short:
            continue
        o.raw["partial_job"] = True
        what = COVER_WORDS.get(cov, "coverage not stated")
        h = o.raw.get("coverage_hours")
        o.flags.append(f"{what}{f' ({h:g} h)' if isinstance(h, (int, float)) else ''}"
                       + (", priced like a short package" if cov is None else "")
                       + f": ranked after {top_words} packages")


def coverage_lines(offers: list[Offer]) -> list[str]:
    """'typical by coverage: full day €1,800-€2,400 (4 packages); ceremony / short €700-€900 (3)'."""
    groups: dict[str | None, list[float]] = {}
    for o in offers:
        if "coverage" in o.raw and o.true_cost is not None and (p := price_of(o)):
            groups.setdefault(o.raw.get("coverage"), []).append(p)
    if len(groups) < 2 and None in groups:
        return []
    bits = []
    for cov in sorted(groups, key=lambda c: -COVER_RANK.get(c, 2)):
        xs = sorted(groups[cov])
        rng = (f"{fmt(_quantile(xs, 0.25))}-{fmt(_quantile(xs, 0.75))}" if len(xs) >= 3
               else f"{fmt(xs[0])}" + (f"-{fmt(xs[-1])}" if len(xs) > 1 else ""))
        bits.append(f"{COVER_WORDS.get(cov, 'coverage not stated')} {rng} ({len(xs)} package{'s' * (len(xs) != 1)})")
    return [f"typical by coverage: {'; '.join(bits)}"]


def _separate_unlike(need: Need, offers: list[Offer]) -> None:
    """Like with like in a service comparison:
    - a wedding (a day's work): packages are compared with packages; hourly rates x an assumed 8 h are listed
      apart when any package is priced (eval: wedding packages were ranked against €250/h x 2 h);
    - home cleaning (standard visits at an hourly rate): a fixed one-off job price ('Perussiivous €79',
      'Calling MrFix' €9.95) is listed apart from rate x hours, and a 'job' under one hour of the usual rate is a
      booking / warranty fee, not a clean."""
    from agora import resolve
    owned = [o for o in offers if o.true_cost is not None]
    if not owned:
        return
    if JOB_HOURS[0][0].search(f"{need.thing} {(need.category or {}).get('label') or ''}"):
        packages = [o for o in owned if (o.unit or "") == "job" and not o.raw.get("partial_job")]
        if packages:
            for o in owned:
                if (o.unit or "") == "hour":
                    _apart(o, "hourly_vs_package")
        _rank_by_coverage(packages)
        return
    if resolve.service_group(need) is not resolve.CLEANING_GROUP or resolve.is_open_trade(need):
        return
    hourly = [o for o in owned if (o.unit or "") == "hour"]
    if len(hourly) < 2:
        return
    rate = statistics.median(price_of(o) or 0 for o in hourly)
    for o in owned:
        if (o.unit or "") != "job":
            continue
        p = price_of(o) or 0
        bundle = BUNDLE_HOURS.search(o.title or "")
        if p < rate and not bundle:
            # under one hour of the usual rate and no hours named: a booking / warranty fee, not a clean ('3 uur
            # schoonmaakhulp' €19 names its hours: a (deal) price for a real clean, compared)
            _apart(o, "tiny_job")
        elif not (bundle or ONE_OFF_JOB_OK.search(o.title or "")
                  or fits_job_size(need, o)):
            _apart(o, "one_off")


def judge(need: Need, things: list[Thing], months: int = DEFAULT_MONTHS, *, history: bool = True,
          depreciation: dict[str, Any] | None = None) -> Verdict:
    """Mutates offers (trust, flags, true_cost, haggle, raw[evidence/beat]) and returns the verdict.
    `history=False` skips the price-history lookup (the hunt's fast live re-ranking).
    `depreciation` = agora.depreciation.measure(...) result: a measured yearly rate replaces the assumed one."""
    token = _MEMO.set({})
    try:
        return _judge(need, things, months, history=history, depreciation=depreciation)
    finally:
        _MEMO.reset(token)


PUBLIC_NOTES = {
    # cpv:55524 school catering (live: 15 articles about free school meals, then 'Set a watch')
    "cpv:55524": "In Finland school meals are free for pupils and run by the municipality (or its caterer). "
                 "For your own event or business, ask caterers for a per-portion price instead.",
}


def public_service_note(need: Need) -> str | None:
    """A public-procurement service (CPV node) with no price found: say why, instead of 'set a watch'."""
    cat = need.category or {}
    cid = str(cat.get("id") or "")
    if not cid.startswith("cpv:"):
        return None
    if cid in PUBLIC_NOTES:
        return "No public price list found. " + PUBLIC_NOTES[cid]
    if is_service(need) and re.search(r"catering|school|hospital|public|municipal|kunta|julkinen",
                                      f"{cat.get('label') or ''} {need.thing}", re.I):
        return ("No public price list found: this service is usually bought by municipalities and companies "
                "through tenders. Ask providers for a quote (per portion, per hour or per contract).")
    return None


# ---------------------------------------------------------------- quote-only services
# Insurance and contract / institutional catering are priced per quote: the price depends on the person (the car,
# the claim-free years, age, home town) or the contract (portions a day, a tender), so no provider lists one. The
# honest verdict says so and links the main providers instead of 'No priced offers yet. Set a watch' (eval r1-r4:
# car insurance finland, School catering). A calculator's figure is an estimate, never a quote.
QUOTE_PROVIDERS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("insurance", "fi"): [("If", "https://www.if.fi"), ("OP Pohjola", "https://www.op.fi"),
                          ("LähiTapiola", "https://www.lahitapiola.fi"), ("Fennia", "https://www.fennia.fi"),
                          ("Turva", "https://www.turva.fi"), ("Pohjantähti", "https://www.pohjantahti.fi")],
    ("catering", "fi"): [("Amica (Compass Group)", "https://www.amica.fi"), ("Fazer Food & Co", "https://www.fazer.fi"),
                         ("Sodexo", "https://www.sodexo.fi")],
}
INSURANCE_NEED = re.compile(r"insur\w*|vakuut\w*|versicher\w*|verzeker\w*|försäkr\w*|forsakr\w*|forsikr\w*|assuranc\w*",
                            re.I)
CONTRACT_CATERING = re.compile(
    r"(?:catering|ruokapalvelu\w*|ateriapalvelu\w*|kouluruoka\w*|kouluateri\w*|lounaspalvelu\w*|"
    r"henkilöstöravintol\w*|henkilostoravintol\w*|verpflegung|gemeinschaftsverpflegung|schoolmaaltijd\w*)", re.I)
CONTRACT_WHO = re.compile(r"school|koulu\w*|päiväko\w*|paivako\w*|daycare|kindergarten|kita|hospital|sairaala|"
                          r"staff|henkilöstö\w*|henkilosto\w*|company|corporate|yritys\w*|b2b|contract|sopimus\w*|"
                          r"tender|kilpailut\w*|canteen|kantiini|institution\w*|municipal|kunta\w*|public|julkinen|"
                          r"cpv", re.I)
INSURANCE_DRIVERS = {
    "car": "the car, your claim-free years (bonus), age, home town and the cover (traffic only, or partial / full kasko)",
    "home": "the home's size, type and location, the cover and the deductible",
    "travel": "your age, the trip length and the cover",
    "pet": "the animal's breed and age and the cover",
    "life": "your age, health and the sum insured",
}


def _country(need: Need) -> str | None:
    try:
        from agora import places
        return places.country_for(need.where) or _home()
    except Exception:
        return _home()


def quote_only(need: Need) -> dict[str, Any] | None:
    """{'kind': 'insurance' | 'catering', 'what', 'drivers', 'providers': [(name, url)]} for a service priced per
    quote (insurance; school / staff / contract catering), else None."""
    if not is_service(need):
        return None
    cat = need.category or {}
    text = f"{need.thing} {need.raw} {cat.get('label') or ''} {cat.get('id') or ''}"
    cc = _country(need) or "fi"
    if INSURANCE_NEED.search(text):
        from agora import resolve
        asked = resolve._fold(f"{need.thing} {cat.get('label') or ''}")
        sub = next((k for k in INSURANCE_DRIVERS if resolve.INSURANCE_KINDS.get(k) is not None
                    and resolve.INSURANCE_KINDS[k].search(asked)), None)
        what = re.sub(r"\s+(?:finland|suomi|helsinki|service)$", "", (need.thing or "insurance").strip(), flags=re.I)
        return {"kind": "insurance", "what": what or "insurance",
                "drivers": INSURANCE_DRIVERS.get(sub or "", "you and the cover you choose"),
                "providers": QUOTE_PROVIDERS.get(("insurance", cc), [])}
    if CONTRACT_CATERING.search(text) and CONTRACT_WHO.search(text):
        return {"kind": "catering", "what": (cat.get("label") or need.thing or "catering").strip(),
                "drivers": "the number of portions a day, the menu and diets, the contract length and delivery",
                "providers": QUOTE_PROVIDERS.get(("catering", cc), [])}
    return None


def _provider_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def quote_lines(q: dict[str, Any]) -> list[str]:
    """One line per main provider ('If: https://www.if.fi'), for the person to ask for a quote."""
    return [f"get a quote: {name} {url}" for name, url in q["providers"][:6]]


def quote_verdict(need: Need, q: dict[str, Any], estimates: list[Offer], all_offers: list[Offer]) -> Verdict:
    """No insurer / caterer lists a price: say why, name and link the main providers, show any calculator estimate."""
    names = [n for n, _ in q["providers"][:4]]
    public = public_service_note(need) if q["kind"] == "catering" else None
    if public:
        head = public
    else:
        head = (f"{q['what'][:1].upper()}{q['what'][1:]} is priced by quote, not listed: the price depends on "
                f"{q['drivers']}.")
    if names:
        head += f" Compare quotes from {_provider_names(names)}" + (
            " (online, a few minutes each)." if q["kind"] == "insurance" else ".")
    else:
        head += " Ask two or three providers for a quote."
    lines = quote_lines(q)
    best: Offer | None = None
    if estimates:
        best = min(estimates, key=lambda o: o.price_eur or 1e12)
        price = _estimate_price(best)
        what = _job_title(best) or best.title or "estimate"
        head += f" A calculator estimates about {price} ({best.source}: {what[:60]}), for its example inputs."
        lines.insert(0, f"estimate, not a quote: {price} at {best.source} (\u201c{(best.title or '')[:60]}\u201d); "
                        "enter your own details there or ask the insurers")
    found = len(all_offers)
    lines.append(f"{found} page{'s' * (found != 1)} read, no provider lists a price you can buy at"
                 if not estimates else "the estimate is a calculator's figure for example inputs, not an offer")
    first_link = q["providers"][0][1] if q["providers"] else None
    return Verdict(head, best.url if best else first_link, None, "get quotes", lines)


def _estimate_price(o: Offer) -> str:
    """'€350/year (≈ €29/month)' for a calculator's figure (it has no true cost: it is nothing you can buy)."""
    per = period_of(o)
    stated = money(o.price if o.price is not None else (o.price_eur or 0), o.currency if o.price is not None else "EUR")
    if per in PER_MONTH:
        tail = f" (≈ {fmt((o.price_eur or 0) * PER_MONTH[per])}/month)" if per != "month" and o.price_eur else ""
        return f"{stated}/{PERIOD_WORD[per]}{tail}"
    if per:
        return f"{stated} per {PERIOD_WORD[per]}"
    return fmt(o.price_eur or 0)


def quote_headline(q: dict[str, Any], listed: Offer) -> str:
    """A quote-priced service that some page lists a price for anyway: lead with how it is priced, show the
    listed price as an example, name the providers to ask."""
    what = f"{q['what'][:1].upper()}{q['what'][1:]}"
    price = _period_price(listed) if period_of(listed) else fmt(_landed(listed))
    title = _job_title(listed)
    names = [n for n, _ in q["providers"][:4]]
    head = (f"{what} is priced by quote: the price depends on {q['drivers']}. Lowest listed price: {price} at "
            f"{_who(listed)}" + (f" ({title})" if title else "") + ", an example or 'from' price.")
    if names:
        head += f" Compare quotes from {_provider_names(names)}."
    else:
        head += " Ask two or three providers for a quote."
    return head


def _tc_key(o: Offer) -> float:
    return o.true_cost.per_month_eur if o.true_cost is not None else 1e12


def _svc_key(o: Offer) -> tuple[float, bool, float]:
    """Cheapest job first; at the same price (to the euro) a provider stating its call-out fee and minimum ranks
    before one whose terms we assumed."""
    t = _tc_key(o)
    return (round(t), bool(o.raw.get("assumed_terms")), t)


def _judge(need: Need, things: list[Thing], months: int, *, history: bool,
           depreciation: dict[str, Any] | None) -> Verdict:
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
    ref: Reference | None = None
    if not is_service(need) and not priced_per_period(need):
        mark_listings(need, everyone)
        # a mixed bag of models (a kind of thing) has no one 'new price': a €142 VoIP phone or a €20 headset must
        # never become every smartphone's yardstick
        refs: dict[frozenset[str], Reference | None] = {}
        if not any(o.raw.get("generic_thing") for o in everyone) and not _generic_need(need):
            refcat = category_for(" ".join([need.thing] + [o.title for o in everyone[:5]]))
            # one reference per version: a PS5 Pro is never judged against the base PS5's new price, nor sets it
            # (live, ps5: Pro listings made the reference €1,068 and were 'costs more than new (€699)')
            by_tier: dict[frozenset[str], list[Offer]] = {}
            for o in everyone:
                by_tier.setdefault(_tier_key(o.title or ""), []).append(o)
            want = _tier_key(need.thing)
            if len(by_tier) > 1 and len(by_tier.get(want, [])) >= MIN_MARKET_REF:
                for k, group in by_tier.items():
                    refs[k] = reference_price(group, refcat, need) if len(group) >= MIN_MARKET_REF else None
                ref = refs.get(want)
            else:
                ref = reference_price(everyone, refcat, need)
        for o in everyone:
            own = refs.get(_tier_key(o.title or ""), ref) if refs else ref
            o.raw["ref_suspect"] = bool(own and reference_flag(o, own, DEFAULT_CATEGORY))
    else:
        for o in everyone:
            o.raw.pop("red_flags", None)
            o.raw.pop("ref_suspect", None)
    floor = market_floor(everyone) if not is_service(need) else 0.0   # across Things: a lone part is its own Thing
    for t in things:
        _judge_offers(need, t, months, seen, depreciation, history=history, photos=photos, floor=floor,
                      everyone=everyone if not is_service(need) else None, ref=ref)
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
    quote = quote_only(need)
    estimates = [o for o in priced if o.raw.get("estimate")]
    if quote and not [o for o in priced if not o.raw.get("estimate")]:
        return quote_verdict(need, quote, estimates, all_offers)
    if not priced:
        if public := public_service_note(need):
            return Verdict(public, None, None, None, [f"{len(all_offers)} offers found, none with a readable price"])
        return Verdict("No priced offers yet. Set a watch and Agora keeps looking.", None, None, None,
                       [f"{len(all_offers)} offers found, none with a readable price"])
    good = [o for o in priced if not _risky(o) and o.in_stock is not False and ships_to_fi(o) is not False
            and not (is_service(need) and sold_out(o))
            and not o.raw.get("pickup_abroad")] or [o for o in priced if not o.raw.get("pickup_abroad")] or priced
    # never crowned while a checked one exists: a giveaway-priced one of a mixed bag ('far_under'), or a used
    # listing far under its band whose page told us nothing (pick check: no description to read)
    good = [o for o in good if not o.raw.get("far_under") and not _unchecked_bargain(o, band_of)] or good
    # a calculator's estimate is shown, never crowned while a provider's own price exists
    good = [o for o in good if not o.raw.get("estimate")] or good
    # a listing for another audience (a men's / kids' / dog's jacket when women's was asked), told by its
    # description when the title says nothing: shown, never the pick
    good = [o for o in good if not o.raw.get("other_audience")] or good
    good = [o for o in good if not o.raw.get("partial_job") and not o.raw.get("near_floor")] or good
    # a model asked ('dyson v15'): the pick comes from that model's own group, never from a small group of
    # titles naming several models ('Dyson V11 V15': batteries and docks that fit both, live pick €56)
    if is_service(need):
        try:
            from agora.resolve import not_shown_local
            good = [o for o in good if not not_shown_local(need, o)] or good
        except ImportError:
            pass
    if not is_service(need) and (main := _main_model_ids(need, things)):
        good = [o for o in good if o.thing_id in main] or good
    # the 'New from / refurbished from' line names the cheapest kept offer of each condition, even one too cheap to
    # crown (live, kitchen table: 'New from €165' while €112 and €120 new tables at homeroom.fi were kept)
    shown = list(good)
    if not is_service(need) and _generic_need(need):
        # ... but not a vague need's giveaway end ('Used from €20' for a bicycle): under a fifth of its median
        cmeds = {c: statistics.median(xs) for c in ("new", "used", "refurbished")
                 if len(xs := [x for o in shown if market_condition(o) == c and (x := price_of(o))]) >= 5}
        shown = [o for o in shown if not (cmeds.get(market_condition(o)) and (price_of(o) or 0)
                                          < SHOWN_FLOOR * cmeds[market_condition(o)])] or shown
    # a kind of thing ('road bike', 'puhelin', 'sofa'): the pick is a sensibly priced one, not the €35 frame or
    # the €19 diaper bag at the bottom of the bag (live): shown, but crowned only when nothing else is left
    good = [o for o in good if (o.raw.get("mixed_ratio") or 1.0) >= MIXED_PICK_MIN] or good
    if not is_service(need) and (_generic_need(need) or _family_need(need)):
        # a vague need ('puhelin', 'sofa') or a product line ('lego technic'): the pick sits in the hunt's usual
        # range, not at its giveaway end (live: a €9 Monster Jam set was the 'lego technic' pick)
        meds: dict[str, float] = {}
        for c in ("new", "used", "refurbished"):
            xs = [x for o in priced if market_condition(o) == c and (x := price_of(o))]
            if len(xs) >= 5:
                meds[c] = statistics.median(xs)

        def _low_end(o: Offer) -> bool:
            m, p = meds.get(market_condition(o)), price_of(o)
            return bool(m and p and p < GENERIC_PICK_MIN * m)
        good = [o for o in good if not _low_end(o)] or good
    # the body asked: a body + lens kit is shown ('with a lens') but never crowned over a body alone
    if asks_body(need):
        good = [o for o in good if not o.raw.get("with_lens")] or good
    # bulky things: the home country is the pickable set; listings abroad are shown as "also in the EU"
    eu_extra: list[Offer] = []
    if not is_service(need) and _bulky(need):
        home_set = [o for o in good if not o.raw.get("abroad")]
        if home_set:
            eu_extra = [o for o in good if o.raw.get("abroad")]
            good = home_set
            shown = [o for o in shown if not o.raw.get("abroad")] or shown
    eu = [o for o in good if not outside_eu(o)]

    cheapest = min(good, key=_landed)
    best_link = min(eu, key=_landed) if eu else cheapest
    owned = [o for o in good if o.true_cost]
    best_tc = min(owned, key=_svc_key if is_service(need) else _tc_key) if owned else None
    if is_service(need) and best_tc is not None and best_tc.raw.get("job_what"):
        # a provider's fixed price for exactly this job size beats an hourly rate x a guessed number of hours (live,
        # Umzug Hamburg 2-Zimmer: 'Umzug für kleine 1-2 Zimmer Wohnung (bis 60 m²)' €400 lost to €80/h x 4 h)
        sized = [o for o in owned if (o.unit or "") == "job" and fits_job_size(need, o)]
        if sized:
            best_tc = min(sized, key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
    lines: list[str] = []

    periodic = [o for o in owned if o.raw.get("period_group")] if priced_per_period(need) else []
    if periodic:
        headline, best_tc = _period_verdict(need, periodic, priced, months, lines)
        best_link = best_tc
    elif is_service(need) and best_tc is not None:
        headline = _service_headline(need, best_tc)
        # cheapest job first; one line per provider, at most 2 per directory / platform (one directory's ten
        # cleaners do not fill the comparison, one provider's two pages are not two providers)
        per_site: dict[str, int] = {}
        for o in sorted(owned, key=_svc_key):
            cap = 2 if any(h in (o.source or "") for h in AGGREGATOR_HOSTS) or o.raw.get("from_list_page") else 1
            if len(lines) >= 4 or per_site.get(o.source, 0) >= cap:
                continue
            per_site[o.source] = per_site.get(o.source, 0) + 1
            tc = o.true_cost
            assert tc is not None
            deal = " (deal)" if o.raw.get("deal") else ""
            parts = [f"{fmt(v)} call-out" if lbl == "call-out fee" else f"{fmt(v)} call-out (est.)"
                     if lbl.startswith("call-out fee (est.") else lbl for lbl, v in tc.receipt if v > 0]
            lines.append(f"{o.source}{deal}: {' + '.join(parts)} -> {fmt(tc.total_eur)}")
        if best_tc.raw.get("deal"):
            regular = [o for o in owned if not o.raw.get("deal")]
            if regular:
                r = min(regular, key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
                lines.insert(0, f"without a deal: {fmt(r.true_cost.total_eur)} at {r.source}"  # type: ignore[union-attr]
                             + (f", {r.raw['calc']}" if r.raw.get("calc") else ""))
        if dup := also_at_note(best_tc):
            lines.append(f"{_who(best_tc)}: {dup}")
        others = [x for x in best_tc.raw.get("other_prices") or [] if x.get("price_eur")]
        if others:
            lines.append(f"other prices at {best_tc.source}: " + ", ".join(
                f"{x['title'][:40]} {fmt(x['price_eur'])}" + {"hour": "/h", "m2": "/m²"}.get(x.get("unit") or "", "")
                for x in others[:3]))
        if best_tc.raw.get("deduction_eur"):
            lines.append(f"household deduction ({HOUSEHOLD.year}): {HOUSEHOLD.rate:.0%} of labour minus a "
                         f"{fmt(HOUSEHOLD.yearly_excess)} yearly excess per person; this job alone gets "
                         f"{fmt(best_tc.raw.get('deduction_alone_eur') or 0)} back")
        apart = [o for o in priced if o.true_cost is None and o.raw.get("not_comparable")
                 and not (quote and o.raw.get("estimate"))]
        jobs = [o for o in apart if o.raw.get("not_comparable") == NOT_COMPARABLE["workshop_task"]]
        if jobs:
            # a workshop's prices for specific jobs (gunsmith: threading, deactivation): their own list, never ranked
            lines.append("other prices (specific jobs, not ranked against hourly rates): " + ", ".join(
                f"{(o.title or '')[:40]} {fmt(o.price_eur or 0)} ({o.source})"
                for o in sorted(jobs, key=lambda x: x.price_eur or 0)[:5]))
            apart = [o for o in apart if all(o is not j for j in jobs)]
        if apart:
            why = sorted({o.raw["not_comparable"] for o in apart})
            shown = ", ".join(f"{o.source} {fmt(o.price_eur or 0)} ({(o.title or '')[:30]})" for o in apart[:3])
            lines.append(f"{len(apart)} more not compared ({'; '.join(why)}): {shown}")
        apart += jobs
        partial = [o for o in priced if o.raw.get("partial_job") and all(o is not x for x in apart)]
        starting = [o for o in partial if o.raw.get("starting_price")]
        if starting:
            lines.append(f"{len(starting)} starting price{'s' * (len(starting) != 1)} with no job named ("
                         + ", ".join(f"from {fmt(o.price_eur or 0)} at {o.source}" for o in starting[:3])
                         + "): ranked after hourly rates x a standard job; ask what they cover")
            partial = [o for o in partial if not o.raw.get("starting_price")]
        if partial:
            # live, wedding photographer: twelve portrait-only packages were '12 more offers without a clear unit'
            lines.append(f"{len(partial)} portrait-only or partial package{'s' * (len(partial) != 1)}, ranked after "
                         f"full packages")
        if wedding_need(need):
            lines += coverage_lines(priced)
        no_unit = len([o for o in priced if o.true_cost is None and all(o is not x for x in apart)
                       and all(o is not x for x in partial)])
        if no_unit:
            lines.append(f"{no_unit} more offer{'s' * (no_unit != 1)} without a clear unit (per hour / m² / job)")
        best_link = best_tc
    elif is_service(need) or best_tc is None:
        unit = f"/{cheapest.unit}" if cheapest.unit else ""
        headline = f"Cheapest: {fmt(_landed(cheapest))}{unit} at {_who(cheapest)}."
        if len(good) > 1:
            med = statistics.median(o.price_eur or 0 for o in good)
            lines.append(f"{len(good)} trustworthy offers, median {fmt(med)}{unit}")
    else:
        # Products: people want the full price they pay once (tag + shipping + import + fees), so the
        # pick is the lowest ALL-IN price among offers you can surely buy. Owning cost per month stays
        # a secondary line (true_cost on every offer), never the headline.
        plans = [o for o in good if is_periodic(o)]
        if plans and len(plans) < len(good):
            good = [o for o in good if not is_periodic(o)]
            cheapest = min(good, key=_landed)
            pl = min(plans, key=lambda o: o.true_cost.per_month_eur if o.true_cost else 1e12)
            lines.append(f"also as a service / subscription: {_period_price(pl)} at {pl.source} "
                         "(priced per period, not compared with buying one)")
        sure = [o for o in good if surely_buyable(o)]
        best_all = min(sure or good, key=_landed)
        if LOW_GRADE.search(best_all.title or ""):
            # 'Kunto: Tyydyttävä' (satisfactory) by a few euros: a 'Hyvä' one within 10% is the better buy
            better = [o for o in (sure or good) if not LOW_GRADE.search(o.title or "")
                      and _landed(o) <= 1.10 * _landed(best_all)]
            if better:
                best_all = min(better, key=_landed)
        # a colour asked ('bright red car', live r5): a car that says it is that colour is the pick over a cheaper
        # one of unknown colour; when none says so, the verdict says the colour is not confirmed
        colour_line, colour_unknown = _colour_pick(need, sure or good)
        if colour_line is not None:
            in_colour = [o for o in (sure or good) if o.raw.get("colour_match") is True]
            if in_colour:
                best_all = min(in_colour, key=_landed)
        for o in good:
            extras = _landed(o) - (o.price_eur or 0)
            beat = round(_landed(best_all) - extras, 2)
            o.raw["beat_eur"] = beat
            o.raw["gap_eur"] = round((o.price_eur or 0) - beat, 2)
        # a vague need ('puhelin', a tree hunt): say which one the price buys ('used iPhone 13 128GB at tori.fi')
        headline = all_in_headline(_headline_pool(good, shown, best_all), best_all, lines, named=_generic_need(need),
                                   titled=_names_more_than_asked(need, best_all), ref=ref)
        lines[0:0] = skipped_lines(priced)
        if colour_line:
            lines.insert(0, colour_line)
        if _vehicle(need) and best_all.raw.get("subtitle"):
            # which car the price buys: year, km, fuel, gearbox, colour (eval r5: a bare 'Subaru Outback')
            lines.insert(0, f"the car: {best_all.title} · {best_all.raw['subtitle']}")
        if colour_unknown:
            headline = headline.rstrip(".") + "; colour not confirmed."
        if ref is not None:
            n_low = sum(1 for o in all_offers if o.raw.get("ref_suspect"))
            lines.append(reference_line(ref, n_low))
        if best_all is not cheapest and not surely_buyable(cheapest):
            lines.append(f"{cheapest.source} is cheaper ({fmt(_landed(cheapest))} all in) but does not say it ships to Finland")
        if eu_extra:
            ex = min(eu_extra, key=_landed)
            est = ex.raw.get("shipping_est") or {}
            lines.append(f"also in the EU: {fmt(_landed(ex))} all in at {ex.source} ({fmt(ex.price_eur or 0)}"
                         f" + est. shipping {est.get('text', '')}); bulky, so we pick near you")
        pickups = [o for o in priced if o.raw.get("pickup_abroad")]
        if pickups:
            lines.append(f"{len(pickups)} listing{'s' * (len(pickups) != 1)} abroad are pickup only: shown, never the pick")
        if best_all.raw.get("shipping_est") and best_all.raw.get("abroad"):
            lines.append(f"{best_all.source}: shipping {best_all.raw['shipping_est'].get('text')} is an estimate, "
                         "not the seller's quote")
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
        lines.append(risky_line(flagged))
    if quote:
        # the headline says how it is priced (quote_headline); the lines link the providers to ask
        lines += quote_lines(quote)[:4]
        if estimates:
            e = min(estimates, key=lambda o: o.price_eur or 1e12)
            lines.append(f"calculator estimate (not a quote): {_estimate_price(e)} at {e.source}")
        # a listed price of a quote-priced service is an example or a 'from' price, never a 'buy now' (eval r4, car
        # insurance finland: '€373/year at k-auto.fi', a car dealer's add-on, headed the verdict as the price)
        listed = best_tc or cheapest
        headline = quote_headline(quote, listed)

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
    if quote and buy_or_wait in ("buy now", "check the seller first", "check the warranty first"):
        buy_or_wait = "get quotes"

    vband = band_of.get(id(led)) or band_of.get(id(pick))
    if vband:
        which = led if id(led) in band_of else pick
        typical = (f"about {fmt(vband['p25'])}" if fmt(vband['p25']) == fmt(vband['p75'])
                   else f"{fmt(vband['p25'])}-{fmt(vband['p75'])}")      # never '€14-€14' (live, lunch)
        lines.append(f"price band ({vband.get('what') or which.condition}): {typical} is typical; "
                     f"{_who(which)} at {fmt(which.price_eur or 0)} is {vband['label']}"
                     + (f" ({vband['badges'][0]})" if vband["badges"] else ""))
        vband = {**vband, "url": which.url, "thing_id": which.thing_id}
    return Verdict(headline, best_link.url, best_tc.url if best_tc else None, buy_or_wait, lines, price_band=vband)


def skipped_lines(offers: list[Offer]) -> list[str]:
    """'skipped €30 tori.fi: the description says broken or faulty ("häiriötä")' for every candidate whose
    listing page was checked (hunt.verify_pick) and failed."""
    out: list[str] = []
    for o in sorted((o for o in offers if o.raw.get("page_red_flags")), key=_landed):
        k, what, phrase = o.raw["page_red_flags"][0]
        out.append(f"skipped {fmt(_landed(o))} {o.source} ({(o.title or '')[:40]}): the description says "
                   f"{what} (\u201c{str(phrase)[:40]}\u201d)")
    return out[:4]


def _bulky(need: Need) -> bool:
    try:
        from agora import marketplaces
        return marketplaces.is_bulky(need.thing)
    except ImportError:
        return False


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


def short_title(o: Offer, n: int = 40) -> str:
    """The listing's own name, short: 'iPhone 13 128GB' from 'iPhone 13 128GB, Tuotemerkki: Apple, Kunto: Hyvä'."""
    t = re.split(r",\s*(?:tuotemerkki|malli|kunto|koko|brand|condition|marke|zustand|merk|staat|stan)\s*:|\s[|–—]\s",
                 (o.title or "").strip(), maxsplit=1, flags=re.I)[0].strip(" ,.-")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(" ,.-/") + "…"
    return t


_RISK_GROUPS = (      # flag start -> (one, many)
    ("price disagrees", ("whose price disagrees between the page and the search",
                         "whose price disagrees between the page and the search")),
    ("too good", ("priced too low to be real", "priced too low to be real")),
    ("red flag: too little for a whole car", ("priced too low to be a whole car", "priced too low to be a whole car")),
    ("red flag: the description says", ("with a problem in its description", "with a problem in their description")),
    ("red flag: a swap", ("is a swap, not a sale", "are swaps, not sales")),
    ("red flag: broken", ("broken or faulty", "broken or faulty")),
    ("red flag: locked", ("locked to an account", "locked to an account")),
    ("red flag: probably a copy", ("possibly a copy", "possibly copies")),
    ("red flag", ("with another red flag in the title", "with another red flag in the title")),
    ("outside the EU", ("may not ship to Finland", "may not ship to Finland")),
    ("out of stock", ("out of stock", "out of stock")),
    ("photo copied", ("with a photo copied from another listing", "with photos copied from other listings")),
    ("scam pattern", ("matching a scam pattern", "matching a scam pattern")),
)
_OTHER_RISK = ("low trust for other reasons", "low trust for other reasons")


def _risk_group(o: Offer) -> tuple[str, str]:
    for f in o.flags:
        for start, label in _RISK_GROUPS:
            if f.startswith(start):
                return label
    return _OTHER_RISK


def risky_line(flagged: list[Offer]) -> str:
    """'375 offers look risky: 200 priced too low to be real, 120 are swaps, not sales, 40 broken or faulty':
    plain counts per reason, never raw flag strings, never cut mid-word."""
    counts = Counter(_risk_group(o) for o in flagged)
    verb = "looks" if len(flagged) == 1 else "look"
    top = counts.most_common(4)
    parts = [f"{n} {label[0] if n == 1 else label[1]}" for label, n in top]
    rest = sum(counts.values()) - sum(n for _, n in top)
    if rest:
        parts.append(f"{rest} for other reasons")
    return f"{len(flagged)} offer{'s' * (len(flagged) != 1)} {verb} risky: " + "; ".join(parts)


def _names_more_than_asked(need: Need, o: Offer) -> bool:
    """Name the pick in the headline unless its title is just the words asked ('Saab 96' for 'volvo v70' must
    show; 'iPhone 13' for 'iphone 13' need not)."""
    try:
        from agora.resolve import tokenize
    except ImportError:
        return True
    t = short_title(o)
    if not t:
        return False
    asked = set(tokenize(f"{need.thing} {need.raw}"))
    return not set(tokenize(t)) <= asked


LANE_OUTLIER = 5.0     # a condition's cheapest offer over 5x the cheapest used one is no useful 'from' line


def _headline_pool(good: list[Offer], shown: list[Offer], best: Offer) -> list[Offer]:
    """The pick's own condition comes from `good` (what may be crowned); the other conditions' 'from' prices from
    every kept, unflagged offer (`shown`)."""
    mine = market_condition(best)
    return [o for o in good if market_condition(o) == mine] + [o for o in shown if market_condition(o) != mine]


def all_in_headline(good: list[Offer], best: Offer, lines: list[str], named: bool = False,
                    titled: bool = False, ref: Reference | None = None) -> str:
    """'€825 all in: used at tori.fi. New from €1,029, refurbished from €899.' Every number is the full
    price you pay once (tag + shipping + import VAT + fees)."""
    per_cond: dict[str, Offer] = {}
    for o in good:
        c = market_condition(o)          # a private seller's 'new' is in the used row, labelled as such
        if c in ("new", "refurbished", "used", "rental"):
            cur = per_cond.get(c)
            if cur is None or _landed(o) < _landed(cur):
                per_cond[c] = o
    used = [_landed(o) for o in good if market_condition(o) == "used"]
    if len(used) >= 3:
        # 'refurbished from €330' for a coffee maker whose used ones start at €25 is another kind of thing
        med = statistics.median(used)
        per_cond = {c: o for c, o in per_cond.items()
                    if c == "used" or o is best or _landed(o) <= LANE_OUTLIER * med}
    for c, o in sorted(per_cond.items(), key=lambda kv: _landed(kv[1])):
        extra = _landed(o) - (o.price_eur or 0)
        how = f" ({fmt(o.price_eur or 0)} + {fmt(extra)} shipping/import/fees)" if extra >= 1 else ""
        label = f" ({PRIVATE_NEW})" if private_new(o) else ""
        lines.append(f"{c}: {fmt(_landed(o))} all in at {o.source}{label}{how}")
    what = f" {short_title(best)}" if named and short_title(best) else ""
    # the pick's own name after the shop when it says more than the words asked ('Saab 96' for a 'volvo v70')
    after = f" ({short_title(best)})" if titled and not what and short_title(best) else ""
    head = f"{fmt(_landed(best))} all in: {_cond(best)}{what} at {best.source}{after}."
    others = [f"{c} from {fmt(_landed(o))}" + ("" if surely_buyable(o) else " (may not ship to Finland)")
              for c, o in sorted(per_cond.items(), key=lambda kv: _landed(kv[1])) if c != market_condition(best)]
    if "new" not in per_cond and market_condition(best) != "new" and ref is not None and ref.shop_new:
        # no new offer survived, but shops' new prices were seen: say it (live, macbook air m2: '€475 all in ...
        # Refurbished from €699' with the €968 new price only deep in the lines)
        others.append(f"new about {fmt(ref.new_eur)} in shops")
    if others:
        tail = ", ".join(others)
        head += f" {tail[0].upper()}{tail[1:]}."
    return head


GROUP_WORDS = {
    "month": re.compile(r"\b(?:subscriptions?|monthly|per month|a month|/mo|retainer|unlimited|plans?|membership|saas|"
                        r"kuukausi\w*|monatlich|abo\w*)\b", re.I),
    "hour": re.compile(r"\b(?:hourly|per hour|an hour|/h|tuntihinta|stundensatz)\b", re.I),
    "job": re.compile(r"\b(?:project|one[- ]off|one[- ]time|fixed price|website|logo|kertamaksu|projekt\w*)\b", re.I),
}
GROUP_ORDER = ("month", "job", "hour", "day")
GROUP_NOUN = {"month": "monthly plans", "job": "project prices", "hour": "hourly rates", "day": "day rates"}


def lead_group(need: Need, groups: dict[str, list[Offer]]) -> str:
    """Which period the comparison is in: what the need asks for ('subscription' -> monthly, 'project' ->
    per project), else the period most offers state (ties: monthly, project, hourly, daily)."""
    for g, rx in GROUP_WORDS.items():
        if g in groups and rx.search(need.raw or need.thing):
            return g
    return max(groups, key=lambda g: (len(groups[g]), -GROUP_ORDER.index(g) if g in GROUP_ORDER else -9))


def _period_price(o: Offer) -> str:
    """'$4,995/month', '€1,200/year (≈ €100/month)', '€85 per hour', '€2,500 per project'."""
    per = period_of(o) or "job"
    stated = money(o.price if o.price is not None else (o.price_eur or 0), o.currency if o.price is not None else "EUR")
    if per in PER_MONTH:
        tail = f" (≈ {fmt(o.true_cost.per_month_eur)}/month)" if per != "month" and o.true_cost else ""
        return f"{stated}/{PERIOD_WORD[per]}{tail}"
    return f"{stated} per {PERIOD_WORD[per]}"


def _year_total(o: Offer) -> str:
    """'≈ $59,940 a year' in the offer's own currency (EUR added when it is another one)."""
    per = period_of(o)
    if per not in PER_MONTH or o.price is None:
        return ""
    yearly = o.price * PER_MONTH[per] * 12
    eur_note = "" if (o.currency or "EUR").upper() == "EUR" or o.price_eur is None else \
        f" (≈ {fmt((o.price_eur or 0) * PER_MONTH[per] * 12)})"
    return f"≈ {money(yearly, o.currency)} a year{eur_note}"


def _period_verdict(need: Need, periodic: list[Offer], priced: list[Offer], months: int,
                    lines: list[str]) -> tuple[str, Offer]:
    """Subscriptions / retainers / rates: like with like. The lead period's cheapest trustworthy offer heads
    the verdict ('$4,995/month at designjoy.co · ≈ $59,940 a year'); other periods are listed apart."""
    groups: dict[str, list[Offer]] = {}
    for o in periodic:
        groups.setdefault(o.raw["period_group"], []).append(o)
    lead = lead_group(need, groups)
    ranked = sorted(groups[lead], key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
    best = ranked[0]
    year = _year_total(best)
    headline = f"{_period_price(best)} at {best.source}" + (f" · {year}" if year else "") + "."
    # one provider, one voice: its entry plan (eval r4, bookkeeping: tilitoimistonm.fi's /en/pricing and front page,
    # and a provider's three tiers, were three of '11 monthly plans compared')
    entry: dict[str, Offer] = {}
    for o in ranked:
        entry.setdefault(provider_key(o), o)
    providers = list(entry.values())
    if len(providers) > 1:
        for o in providers[:5]:
            plan = (o.raw.get("plan") or {}).get("name") if isinstance(o.raw.get("plan"), dict) else None
            lines.append(f"{o.source}: {_period_price(o)}" + (f" ({plan})" if plan else ""))
        med = statistics.median(o.true_cost.per_month_eur for o in providers)  # type: ignore[union-attr]
        unit = "/month" if lead == "month" else f" per {PERIOD_WORD.get(lead, lead)}"
        tiers = f" ({len(ranked)} {GROUP_NOUN.get(lead, 'offers')})" if len(ranked) > len(providers) else ""
        lines.append(f"{len(providers)} providers compared{tiers}, median of their lowest {fmt(med)}{unit}")
    for g in GROUP_ORDER:
        if g == lead or g not in groups:
            continue
        o = min(groups[g], key=lambda x: x.true_cost.per_month_eur)  # type: ignore[union-attr]
        lines.append(f"{GROUP_NOUN[g]} (not compared with {GROUP_NOUN.get(lead, lead)}): from {_period_price(o)} "
                     f"at {o.source}" + (f", {len(groups[g])} in all" if len(groups[g]) > 1 else ""))
    quoted = quote_only(need) is not None      # its estimates get their own line (calculator estimate, not a quote)
    apart = [o for o in priced if o.true_cost is None and o.raw.get("not_comparable")
             and not (quoted and o.raw.get("estimate"))]
    if apart:
        why = sorted({o.raw["not_comparable"] for o in apart})
        lines.append(f"{len(apart)} more not compared ({'; '.join(why)}): "
                     + ", ".join(f"{o.source} {fmt(o.price_eur or 0)}" for o in apart[:3]))
    loose = len([o for o in priced if o.true_cost is None and not o.raw.get("not_comparable")
                 and not o.raw.get("estimate")])
    if loose:
        lines.append(f"{loose} more offer{'s' * (loose != 1)} without a clear period (per month / hour / project)")
    return headline, best


_ROOMS = r"(?:zimmer|zi\.?|rooms?|huone\w*|h\b|rum|rok|kamer\w*|værelse\w*|vaerelse\w*|pokoj\w*)"


def fits_job_size(need: Need, o: Offer) -> bool:
    """The offer's own title names the asked job size: '2-Zimmer' asked, '1-2 Zimmer Wohnung' / '2 Zimmer' offered."""
    m = re.search(rf"\b(\d)\s*-?\s*{_ROOMS}", f"{need.raw} {need.thing}", re.I)
    if not m:
        return False
    n = int(m.group(1))
    for a, b in re.findall(rf"\b(\d)(?:\s*[-–]\s*(\d))?\s*-?\s*{_ROOMS}", o.title or "", re.I):
        lo, hi = int(a), int(b or a)
        if lo <= n <= hi:
            return True
    return False


def _service_headline(need: Need, best: Offer) -> str:
    from agora import resolve
    btc = best.true_cost
    assert btc is not None
    size = job_size_m2(need)
    g = resolve.service_group(need)
    noun = "clean" if g is resolve.CLEANING_GROUP else "job"
    if resolve.is_open_trade(need):
        hrs = best.raw.get("job_hours") or resolve.TRADE_HOURS
        job = f"a standard {hrs:g}-hour call (estimate)"
    elif best.raw.get("job_what") and not size:
        job = f"{best.raw['job_what']} (estimate)"
    else:
        job = f"one {size:g} m² {noun}" if size else f"one {noun}"
        what = _job_title(best)
        if what and not size and (best.unit or "") == "job":
            job = f"{job} (“{what}”)"      # '€60 for one job (“Perushuolto”) at aseteam.fi': which job it is
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
    return f"{fmt(btc.total_eur)} for {job} at {_who(best)}{tier}{calc}{after}."


AGGREGATOR_HOSTS = ("lounasmenu.", "lunchmenu.", "luncher.", "lounaat.", "lounasinfo.", "lounastutka.", "trustoo.",
                    "yoojo.", "helpling.", "treatwell.", "fresha.", "timma.", "varaaheti.", "werkspot.", "myhammer.",
                    "check24.", "checkatrade.", "mittanbud.", "offerta.", "tori.fi", "pro.tori.")


def _who(o: Offer) -> str:
    """'UniCafe Kaivopiha (via lounasmenu.fi)' when an aggregator or platform lists the provider; else the site."""
    src = o.source or _host(o.url)
    seller = (o.seller or "").strip()
    if seller and any(h in src for h in AGGREGATOR_HOSTS) and seller.lower() not in src.lower() \
            and len(seller) <= 60:
        return f"{seller} (via {src})"
    return src


def _job_title(o: Offer) -> str | None:
    """The offer's own name for the job when it says more than the provider's name ('Perushuolto', 'Umzug für
    kleine 1-2 Zimmer Wohnung'), cut short."""
    t = re.split(r"\s+[|–—]\s+|\s+-\s+", (o.title or "").strip())[0].strip(" .:")
    if not t or len(t) < 3:
        return None
    host = _host(o.url).split(".")[0]
    if host and host.replace("-", "") in re.sub(r"\W", "", t.lower()):
        return None
    return t[:48] + ("…" if len(t) > 48 else "")


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


def pick_candidates(things: list[Thing], k: int = 3) -> list[Offer]:
    """The k offers the verdict would crown next, cheapest all-in first (the same pickable set as judge's
    product branch): the ones worth a look at their own page before the pick is final."""
    priced = [o for t in things for o in t.offers if o.price_eur is not None]
    good = [o for o in priced if not _risky(o) and o.in_stock is not False and ships_to_fi(o) is not False
            and not o.raw.get("pickup_abroad") and not is_periodic(o) and not o.raw.get("estimate")]
    return sorted(good, key=_landed)[:k]
