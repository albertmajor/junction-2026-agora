"""DEPRECIATION, measured from the shelf instead of assumed per category.

Neighbouring generations of one product line sell used at the same moment for different prices. Their
price gap per year of launch-date difference is a market-measured value loss per year of age:
    A7 II used median €480, A7 III €770, launched 4 years apart -> (480/770)^(1/4) = 0.89 -> -11%/yr.
One cheap search per neighbouring generation (cached 24 h) gives the used comps. The rate is the median
of the adjacent-pair rates, clamped to 3-40%/yr. Fewer than one pair with 3+ comps on both sides
-> the category's assumed rate stays, and the basis says so.

The family table is hand-written launch years (public facts), nothing copied. Written at Junction 2026.
"""
from __future__ import annotations

import asyncio
import re
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

MIN_COMPS = 3
CLAMP = (0.03, 0.40)


@dataclass(frozen=True)
class Model:
    name: str        # what people call it: "Sony A7 III"
    year: int        # launch year
    pattern: str     # regex on lower-case titles/need text (must not match the neighbours)
    query: str       # search words for its used market


FAMILIES: dict[str, list[Model]] = {
    "sony a7": [
        Model("Sony A7 II", 2014, r"\ba7\s?(?:ii|2|m2|mark\s?(?:ii|2))\b(?!i)", "sony a7 ii body used"),
        Model("Sony A7 III", 2018, r"\ba7\s?(?:iii|3|m3|mark\s?(?:iii|3))\b", "sony a7 iii body used"),
        Model("Sony A7 IV", 2021, r"\ba7\s?(?:iv|4|m4|mark\s?(?:iv|4))\b", "sony a7 iv body used"),
    ],
    "sony a7r": [
        Model("Sony A7R III", 2017, r"\ba7r\s?(?:iii|3|m3)\b", "sony a7r iii body used"),
        Model("Sony A7R IV", 2019, r"\ba7r\s?(?:iv|4|m4)\b", "sony a7r iv body used"),
        Model("Sony A7R V", 2022, r"\ba7r\s?(?:v|5)\b", "sony a7r v body used"),
    ],
    "fujifilm x-t": [
        Model("Fujifilm X-T3", 2018, r"\bx-?t3\b", "fujifilm x-t3 body used"),
        Model("Fujifilm X-T4", 2020, r"\bx-?t4\b", "fujifilm x-t4 body used"),
        Model("Fujifilm X-T5", 2022, r"\bx-?t5\b", "fujifilm x-t5 body used"),
    ],
    "canon eos r6": [
        Model("Canon EOS R6", 2020, r"\beos\s?r6\b(?!\s?(?:ii|mark|m2))", "canon eos r6 body used"),
        Model("Canon EOS R6 Mark II", 2022, r"\beos\s?r6\s?(?:ii|mark\s?ii|m2)\b", "canon eos r6 mark ii body used"),
    ],
    "iphone": [
        Model("iPhone 13", 2021, r"\biphone\s?13\b(?!\s?(?:pro|mini))", "iphone 13 128gb used"),
        Model("iPhone 14", 2022, r"\biphone\s?14\b(?!\s?(?:pro|plus))", "iphone 14 128gb used"),
        Model("iPhone 15", 2023, r"\biphone\s?15\b(?!\s?(?:pro|plus))", "iphone 15 128gb used"),
        Model("iPhone 16", 2024, r"\biphone\s?16\b(?!\s?(?:pro|plus|e))", "iphone 16 128gb used"),
    ],
    "macbook air": [
        Model("MacBook Air M1", 2020, r"macbook air.*\bm1\b|\bm1\b.*macbook air", "macbook air m1 used"),
        Model("MacBook Air M2", 2022, r"macbook air.*\bm2\b|\bm2\b.*macbook air", "macbook air m2 used"),
        Model("MacBook Air M3", 2024, r"macbook air.*\bm3\b|\bm3\b.*macbook air", "macbook air m3 used"),
    ],
    "galaxy s": [
        Model("Galaxy S22", 2022, r"\bs22\b(?!\s?(?:\+|plus|ultra))", "samsung galaxy s22 used"),
        Model("Galaxy S23", 2023, r"\bs23\b(?!\s?(?:\+|plus|ultra|fe))", "samsung galaxy s23 used"),
        Model("Galaxy S24", 2024, r"\bs24\b(?!\s?(?:\+|plus|ultra|fe))", "samsung galaxy s24 used"),
    ],
}


def find_model(text: str) -> tuple[str, int] | None:
    """(family, index) of the model the text is about, or None."""
    low = text.lower()
    for fam, models in FAMILIES.items():
        for i, m in enumerate(models):
            if re.search(m.pattern, low):
                return fam, i
    return None


def siblings(family: str, i: int) -> list[Model]:
    """The generation before and after (the closest neighbours tell the most)."""
    models = FAMILIES[family]
    return [models[j] for j in (i - 1, i + 1) if 0 <= j < len(models)]


def point(model: Model, prices: list[float]) -> dict[str, Any]:
    clean = _trim(prices)
    return {"model": model.name, "year": model.year, "n": len(clean),
            "median_eur": round(statistics.median(clean), 2) if clean else None}


def _trim(prices: list[float]) -> list[float]:
    if len(prices) < 3:
        return prices
    med = statistics.median(prices)
    return [p for p in prices if 0.5 * med <= p <= 2 * med]


def measure(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Yearly decay from adjacent generations. None when no pair has MIN_COMPS on both sides."""
    good = sorted((p for p in points if p.get("median_eur") and p["n"] >= MIN_COMPS), key=lambda p: p["year"])
    pairs = []
    for old, new in zip(good, good[1:]):
        dy = new["year"] - old["year"]
        if dy <= 0 or old["median_eur"] >= new["median_eur"]:
            continue            # an older model selling dearer says nothing about ageing
        keep = (old["median_eur"] / new["median_eur"]) ** (1 / dy)
        pairs.append({"older": old["model"], "newer": new["model"], "years": dy,
                      "gap": round(1 - old["median_eur"] / new["median_eur"], 3), "rate": round(1 - keep, 4),
                      "n": (old["n"], new["n"])})
    if not pairs:
        return None
    rate = min(CLAMP[1], max(CLAMP[0], statistics.median(p["rate"] for p in pairs)))
    first = pairs[0]
    basis = (f"measured: {first['older']} used sells for {first['gap']:.0%} less than {first['newer']}; "
             f"launched {first['years']} yr apart => -{first['rate']:.0%}/yr ({first['n'][0]} + {first['n'][1]} listings)")
    if len(pairs) > 1:
        basis += f"; median of {len(pairs)} generation pairs => -{rate:.0%}/yr"
    return {"rate": round(rate, 4), "pairs": pairs, "basis": basis}


Search = Callable[[str], Awaitable[list[dict[str, Any]]]]
FreeRead = Callable[[str, Any], Awaitable[Any]]
JUNK = re.compile(r"\blens\b|battery|cage|strap|\bcase\b|charger|grip|screen protector", re.I)


async def sibling_prices(model: Model, need: Any, search: Search, free_read: FreeRead | None = None,
                         timeout: float = 8.0) -> list[float]:
    """Used prices for one neighbouring generation. Search titles/snippets first; then each result page
    is read for FREE (direct fetch + JSON-LD, never a paid Context.dev read)."""
    from agora import contextdev
    from agora.models import Need
    from agora.reader import offer_from_snippet
    sib_need = Need(raw=model.query, thing=model.name.lower(), conditions=["used"])
    prices: dict[str, float] = {}
    results = await search(model.query)
    for r in results:
        title = str(r.get("title") or "")
        text = f"{title} {contextdev.highlight_text(r) or ''} {r.get('description') or ''}"
        if not re.search(model.pattern, text.lower()) or JUNK.search(title):
            continue
        o = offer_from_snippet(text, str(r.get("url") or ""), title, sib_need)
        if o is not None and o.price_eur and o.price_eur > 50:
            prices[str(r.get("url"))] = float(o.price_eur)
    if free_read is not None:
        async def one(url: str) -> tuple[str, float | None]:
            try:
                got = await asyncio.wait_for(free_read(url, sib_need), timeout=timeout)
            except Exception:
                return url, None
            o = got[0] if isinstance(got, tuple) else got
            ok = (o is not None and o.price_eur and o.price_eur > 50 and o.condition in ("used", "unknown")
                  and re.search(model.pattern, (o.title or "").lower()) and not JUNK.search(o.title or ""))
            return url, float(o.price_eur) if ok else None
        urls = [str(r.get("url")) for r in results if r.get("url") and str(r.get("url")) not in prices
                and not re.search(r"/(?:sch|b|shop|search|collections)/|[?&](?:_nkw|q)=", str(r.get("url")))]
        for url, price in await asyncio.gather(*(one(u) for u in urls)):
            if price:
                prices[url] = price
    return list(prices.values())


async def default_search(query: str) -> list[dict[str, Any]]:
    from agora import contextdev
    return await contextdev.search(query, n=10, highlights=True)


async def default_free_read(url: str, need: Any) -> Any:
    from agora.reader import read_with_reason
    return await read_with_reason(url, need, paid=False)


def capped_reader(max_paid: int = 3) -> FreeRead:
    """Free read first; a paid Context.dev read only for the first `max_paid` pages that block us
    (cached afterwards, so the next hunt of this family costs nothing)."""
    left = [max_paid]

    async def read(url: str, need: Any) -> Any:
        from agora.reader import read_with_reason
        offer, why = await read_with_reason(url, need, paid=False)
        if offer is not None and offer.price_eur or left[0] <= 0:
            return offer, why
        left[0] -= 1
        return await read_with_reason(url, need, paid=True)
    return read
