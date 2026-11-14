"""SHIPPING: what it costs to get a listing from another European country to the buyer, honestly as a range.

Pure and offline. A marketplace listing abroad has no shipping price on its search row, so the all-in price
would otherwise pretend it is free: here it gets an estimate by size class (what kind of parcel or freight)
and distance band (neighbour, central EU, far EU), e.g. a bike DE -> FI ~€60-120 in a bike box by parcel
service. Pickup-only listings abroad ("Nur Abholung", "alleen ophalen", "endast avhämtning") cannot be
shipped: they are shown but are never the pick. Home-country listings are never given an estimate (pickup
or the seller's own domestic price).

The ranges are typical consumer parcel / pallet prices (DHL, PostNord, Posti, GLS, bike-box services,
2025-26 price lists, rounded), not quotes: every receipt line says "est.".
"""
from __future__ import annotations

import re
from typing import Any

# size class -> (low, high) EUR for a central-EU -> Nordic / central route ("mid" band), and a plain word
SIZES: dict[str, tuple[float, float]] = {
    "clothes": (8.0, 15.0),           # soft parcel
    "small": (10.0, 20.0),            # earbuds, watch, accessories: small parcel
    "phone": (12.0, 25.0),            # small parcel, insured
    "camera": (15.0, 30.0),           # camera / lens / small electronics, insured
    "laptop": (18.0, 35.0),
    "medium": (20.0, 45.0),           # monitor, console, speaker, small appliance, drill
    "bike": (60.0, 120.0),            # bike box by parcel service
    "furniture_small": (40.0, 90.0),  # chair, lamp, side table: large parcel
    "furniture": (120.0, 300.0),      # shelf, sofa, table, bed: freight / pallet
    "large_appliance": (150.0, 350.0),  # fridge, washing machine: freight
    "vehicle": (500.0, 1100.0),       # a car: car transporter / ferry, central EU -> Nordic (no parcel ever)
}
SIZE_WORD = {"clothes": "clothing parcel", "small": "small parcel", "phone": "phone", "camera": "camera",
             "laptop": "laptop", "medium": "medium parcel", "bike": "bike", "furniture_small": "small furniture item",
             "furniture": "furniture item", "large_appliance": "large appliance", "vehicle": "car"}
HOW = {"clothes": "parcel", "small": "parcel", "phone": "insured parcel", "camera": "insured parcel",
       "laptop": "insured parcel", "medium": "parcel", "bike": "parcel in a bike box",
       "furniture_small": "large parcel", "furniture": "freight / pallet", "large_appliance": "freight",
       "vehicle": "car transport (truck or ferry; import tax not included)"}

_SIZE_WORDS: list[tuple[str, re.Pattern[str]]] = [
    # a car (judge prefixes "car " for a vehicle need): never a parcel; car seats / chargers / covers are not cars
    ("vehicle", re.compile(r"^\s*(car|auto)\b(?!\s*(seat|charger|cover|mat|wax|polish|radio|holder|mount|parts?|tyres?|tires?|"
                           r"istuin|laturi|kindersitz))", re.I)),
    ("large_appliance", re.compile(r"\b(fridge|freezer|refrigerator|washing machine|washer|dryer|dishwasher|"
                                   r"cooker|oven|stove|jääkaappi|pesukone|kühlschrank|waschmaschine)\b", re.I)),
    ("bike", re.compile(r"\b(bikes?|bicycles?|e-?bikes?|polkupyörä\w*|pyörä\w*|fahrrad|rennrad|citybike|"
                        r"cykel|fiets|rower|vélo|velo)\b", re.I)),
    ("furniture", re.compile(r"\b(shelf|shelves|shelving|bookcase|kallax|billy|hemnes|pax|malm|sofa|couch|"
                             r"sohva|table|pöytä|desk|bed|sänky|wardrobe|dresser|cabinet|cupboard|mattress|"
                             r"piano|treadmill|hylly\w*|regal|kast)\b", re.I)),
    ("furniture_small", re.compile(r"\b(chair|tuoli|stool|lamp|valaisin|stroller|pram|rattaat|kinderwagen)\b", re.I)),
    ("laptop", re.compile(r"\b(laptop|notebook|macbook|kannettava|thinkpad)\b", re.I)),
    ("phone", re.compile(r"\b(phone|iphone|galaxy s\d+|pixel \d+|smartphone|puhelin|handy)\b", re.I)),
    ("camera", re.compile(r"\b(camera|kamera|lens|objektiivi|objektiv|sony a\d|canon eos|nikon z|fujifilm|"
                          r"gopro|drone|dji)\b", re.I)),
    ("medium", re.compile(r"\b(monitor|tv|television|console|playstation|ps5|xbox|switch|speaker|vacuum|"
                          r"dyson|coffee machine|espresso|printer|drill|guitar|tent|skis|tablet|ipad)\b", re.I)),
    ("clothes", re.compile(r"\b(jacket|coat|shoes|sneakers|boots|dress|jeans|shirt|hoodie|sweater|bag|"
                           r"takki|kengät|jacke|schuhe)\b", re.I)),
    ("small", re.compile(r"\b(airpods|earbuds|headphones|watch|kuulokkeet|kello|charger|case|book)\b", re.I)),
]


def size_class(text: str) -> str:
    """What kind of shipment this thing is (first rule wins; bulky before small). Default: medium parcel."""
    for name, pat in _SIZE_WORDS:
        if pat.search(text or ""):
            return name
    return "medium"


# distance band from the seller's country to the buyer's (lower-case ISO alpha-2)
NORDIC_BALTIC = {"fi", "se", "no", "dk", "ee", "lv", "lt", "is"}
CENTRAL = {"de", "nl", "be", "lu", "at", "pl", "cz", "sk", "fr", "ch", "hu", "si"}
FACTOR = {"near": 0.85, "mid": 1.0, "far": 1.3}


def band(src: str, dst: str) -> str | None:
    """'near' (same region), 'mid', 'far'; None = same country (no cross-border shipping)."""
    src, dst = (src or "").lower(), (dst or "").lower()
    if not src or not dst or src == dst:
        return None
    if src in NORDIC_BALTIC and dst in NORDIC_BALTIC or src in CENTRAL and dst in CENTRAL:
        return "near"
    if (src in CENTRAL and dst in NORDIC_BALTIC) or (src in NORDIC_BALTIC and dst in CENTRAL):
        return "mid"
    return "far"


def _nice(x: float) -> float:
    return float(round(x / 5.0) * 5) if x >= 20 else float(round(x))


def estimate(size: str, src: str | None, dst: str | None) -> dict[str, Any] | None:
    """Cross-border shipping estimate {low, high, eur (the middle, used in the all-in price), text, band,
    size, how, src, dst, basis}. None = same country or unknown country."""
    b = band(src or "", dst or "")
    if b is None:
        return None
    lo, hi = SIZES.get(size, SIZES["medium"])
    f = FACTOR[b]
    low, high = _nice(lo * f), _nice(hi * f)
    mid = _nice((low + high) / 2)
    route = f"{(src or '').upper()}→{(dst or '').upper()}"
    return {"low": low, "high": high, "eur": mid, "text": f"€{low:.0f}–{high:.0f}", "band": b, "size": size,
            "how": HOW.get(size, "parcel"), "src": (src or "").upper(), "dst": (dst or "").upper(),
            "basis": f"{SIZE_WORD.get(size, size)} {route} by {HOW.get(size, 'parcel')}: typically "
                     f"€{low:.0f}–{high:.0f} (estimate, ask the seller)"}


VINTED_SHIPPING = (4.0, 12.0)     # vinted's own label, domestic to cross-border


def offer_country(o: Any) -> str | None:
    """The listing's country (lower case): the marketplace site it came from, else agora.origin's answer."""
    raw = getattr(o, "raw", None) or {}
    try:
        from agora import marketplaces
        site = marketplaces.SITES.get(raw.get("site") or "")
        if site is not None and not site.key.startswith("vinted"):
            return site.country
    except ImportError:
        pass
    try:
        from agora.origin import origin_for
        cc = origin_for(o).get("country_code")
        return cc.lower() if cc else None
    except Exception:
        return None


def is_vinted(o: Any) -> bool:
    return "vinted." in (getattr(o, "source", "") or "") or str((getattr(o, "raw", None) or {}).get("site") or "").startswith("vinted")


def is_listing(o: Any) -> bool:
    """A private seller's marketplace listing (classifieds, vinted): shops state their own shipping."""
    raw = getattr(o, "raw", None) or {}
    if raw.get("site"):
        try:
            from agora import marketplaces
            site = marketplaces.SITES.get(raw["site"])
            return site is None or site.lane == "used"
        except ImportError:
            return True
    try:
        from agora.discover import is_marketplace
        return is_marketplace((getattr(o, "source", "") or "").lower())
    except Exception:
        return False


def apply(o: Any, home: str | None, thing: str = "") -> None:
    """Annotate one product offer in place (idempotent):
    raw['delivery'] pickup|ships|None, raw['abroad'], raw['pickup_abroad'], raw['shipping_est'] {...},
    raw['buyer_fee_eur'] (vinted buyer protection, from raw.price_with_buyer_fee), and offer.shipping_eur = the
    estimate's middle when the listing is abroad and shippable and the page stated no shipping price."""
    raw = o.raw
    if getattr(o, "condition", None) == "service" or not home or not is_listing(o):
        return
    home = home.lower()
    if "delivery" not in raw:
        try:
            from agora import marketplaces
            raw["delivery"] = marketplaces.delivery_of(
                f"{o.title or ''} {raw.get('row_text') or ''}", str(raw.get("site") or ("vinted" if is_vinted(o) else "")))
        except ImportError:
            raw["delivery"] = None
    # vinted's price with buyer protection (shown on the row): the fee is part of what you pay
    fee_total = raw.get("price_with_buyer_fee")
    if fee_total and o.price and "buyer_fee_eur" not in raw:
        rate = (o.price_eur or o.price) / o.price if o.price else 1.0
        raw["buyer_fee_eur"] = round(max(0.0, float(fee_total) - float(o.price)) * rate, 2)
    cc = offer_country(o)
    if cc is None:
        return
    abroad = cc != home
    raw["abroad"] = abroad
    if not abroad:
        if is_vinted(o) and o.shipping_eur is None and "shipping_est" not in raw:
            lo, hi = VINTED_SHIPPING
            raw["shipping_est"] = {"low": lo, "high": lo + 4, "eur": lo + 2, "text": f"€{lo:.0f}–{lo + 4:.0f}",
                                   "band": "domestic", "size": size_class(f"{thing} {o.title or ''}"),
                                   "how": "vinted label", "src": cc.upper(), "dst": home.upper(),
                                   "basis": "vinted shipping label, domestic: typically "
                                            f"€{lo:.0f}–{lo + 4:.0f} (estimate)"}
            o.shipping_eur = lo + 2
        return
    if raw.get("delivery") == "pickup":
        raw["pickup_abroad"] = True
        return
    size = size_class(f"{thing} {o.title or ''}")
    est = estimate(size, cc, home)
    if est is None:
        return
    if is_vinted(o):            # vinted's own cross-border label, cheaper than a courier for parcels
        lo, hi = VINTED_SHIPPING
        if size in ("clothes", "small", "phone", "camera"):
            est = {**est, "low": lo, "high": hi, "eur": (lo + hi) / 2, "text": f"€{lo:.0f}–{hi:.0f}",
                   "how": "vinted label",
                   "basis": f"vinted shipping label {est['src']}→{est['dst']}: typically €{lo:.0f}–{hi:.0f} (estimate)"}
    if o.shipping_eur is None or raw.get("shipping_est"):
        raw["shipping_est"] = est
        o.shipping_eur = est["eur"]


def pickup_abroad(o: Any) -> bool:
    return bool((getattr(o, "raw", None) or {}).get("pickup_abroad"))


def shippable_abroad_unknown(o: Any) -> bool:
    """Abroad and the listing does not say whether the seller ships (classifieds: often pickup)."""
    raw = getattr(o, "raw", None) or {}
    return bool(raw.get("abroad")) and raw.get("delivery") is None and not is_vinted(o)
