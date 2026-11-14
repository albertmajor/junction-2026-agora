"""Shared data types for Agora. Every module speaks these. Written at Junction 2026."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Kind = Literal["product", "service", "digital"]   # digital: subscriptions, software, SaaS (priced per period)
Condition = Literal["new", "refurbished", "used", "rental", "service", "unknown"]


@dataclass
class Need:
    """What the person (or agent) wants. Parsed from free text."""
    raw: str
    thing: str                       # cleaned item text, e.g. "sony a7 iii body"
    kind: Kind = "product"
    budget: float | None = None      # in `currency`
    currency: str = "EUR"
    where: str | None = None         # city / country hint
    conditions: list[Condition] = field(default_factory=lambda: ["new", "refurbished", "used"])
    must_have: list[str] = field(default_factory=list)
    # what it must NOT be or come with ('ps5 no gta bundle' -> ['gta bundle']; 'ohne Spiele', 'ei pelejä')
    must_not: list[str] = field(default_factory=list)
    # the node of agora.taxonomy this need is about (a hunt started from the category tree, or a confident
    # classification): {id, label, path, kind, lanes, size, domains, words, source, confidence}. None = unknown.
    category: dict[str, Any] | None = None


@dataclass
class Offer:
    """One way to get the thing, from one page."""
    url: str
    source: str                      # domain, e.g. "ebay.com"
    title: str
    price: float | None
    currency: str | None
    price_eur: float | None = None   # normalised by agora.fx
    condition: Condition = "unknown"
    shipping_eur: float | None = None
    in_stock: bool | None = None
    seller: str | None = None
    location: str | None = None
    image: str | None = None
    sku: str | None = None
    brand: str | None = None
    unit: str | None = None          # services: "hour", "m2", "job"
    read_via: str = "unknown"        # "jsonld" (free) | "contextdev_product" | "contextdev_json" | "search_highlight"
    thing_id: str | None = None      # set by resolve
    trust: float | None = None       # 0..1, set by judge
    flags: list[str] = field(default_factory=list)
    true_cost: "TrueCost | None" = None
    haggle: "Haggle | None" = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrueCost:
    """What owning it really costs. Every number is shown as a receipt line."""
    months: int                      # ownership horizon
    sticker_eur: float
    extras_eur: float                # shipping, fees
    resale_eur: float | None         # expected resale at end of horizon
    total_eur: float                 # sticker + extras - resale
    per_month_eur: float
    confidence: Literal["high", "medium", "low"]
    receipt: list[tuple[str, float]] = field(default_factory=list)   # [("sticker", 799.0), ("resale in 12 mo", -520.0)]
    basis: str = ""                  # e.g. "resale from 7 used listings, median €560, aged 12 mo at -8%/yr"
    per: str = "month"               # "month" (owned things) | "job" (services: per_month_eur is the job total)
    band: dict[str, Any] | None = None   # judge.price_band for this offer: {label: low|typical|high, p25, p75, badges, ...}


@dataclass
class Haggle:
    """For used listings: what to offer and the message to send."""
    fair_low_eur: float
    fair_high_eur: float
    suggested_offer_eur: float
    message: str


@dataclass
class Thing:
    """A cluster of offers that are the same item."""
    id: str
    name: str
    offers: list[Offer] = field(default_factory=list)


@dataclass
class Verdict:
    headline: str                    # one sentence: what to do
    best_offer_url: str | None
    best_true_cost_url: str | None
    buy_or_wait: str | None = None   # "buy now" | "wait ~N days" | None
    lines: list[str] = field(default_factory=list)
    price_band: dict[str, Any] | None = None   # band of the pick's thing + condition (judge.price_band)


@dataclass
class Event:
    """One step of a live hunt. The frontend renders the stream of these."""
    type: str                        # need | lane | source | offer | skip | thing | truecost | verdict | done | error | budget
    data: dict[str, Any]
    t_ms: int = 0                    # ms since hunt start


def to_dict(obj: Any) -> Any:
    """dataclass -> plain JSON-able dict (recursively)."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    return obj
