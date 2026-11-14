"""Offline fakes for the surface tests (hunt / api / cli / mcp). Built from the saved Context.dev fixtures."""
from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import AsyncIterator
from typing import Any

from agora.models import Event, Haggle, Need, Offer, Thing, TrueCost, Verdict

FIX = pathlib.Path(__file__).parent / "fixtures"


def fixture_product(n: int) -> dict[str, Any]:
    d = json.loads((FIX / f"product{n}.json").read_text())
    return d["product"]["data"]["product"]


PAGES: dict[str, tuple[str, float, str, str]] = {
    # url: (title, price_eur, condition, read_via)
    "https://shop-new.example/a7iii": ("Sony A7 III body", 1399.0, "new", "contextdev_product"),
    "https://refurb.example/a7iii": ("Sony A7 III body (refurbished, grade A)", 949.0, "refurbished", "jsonld"),
    "https://market.example/a7iii-1": ("Sony a7iii body, 12k shutter", 790.0, "used", "contextdev_json"),
    "https://market.example/a7iii-2": ("A7 III + strap, light use", 850.0, "used", "jsonld"),
}
BROKEN = "https://broken.example/a7iii"
EMPTY = "https://empty.example/a7iii"
SLOW = "https://slow.example/a7iii"


def parse_need(text: str) -> Need:
    return Need(raw=text, thing="sony a7 iii body", budget=900.0)


async def discover(need: Need) -> AsyncIterator[Event]:
    yield Event("lane", {"lane": "new", "queries": ["sony a7 iii body price"]})
    yield Event("lane", {"lane": "used", "queries": ["used sony a7 iii"]})
    for url in [*PAGES, BROKEN, EMPTY, "https://shop-new.example/a7iii"]:  # last one is a duplicate
        yield Event("source", {"url": url, "lane": "x"})
        await asyncio.sleep(0)


async def read(url: str, need: Need) -> Offer | None:
    await asyncio.sleep(0.001)
    if url == BROKEN:
        raise ValueError("page exploded")
    if url == SLOW:
        await asyncio.sleep(5)
    if url not in PAGES:
        return None
    title, price, cond, via = PAGES[url]
    return Offer(url=url, source=url.split("/")[2], title=title, price=price, currency="EUR",
                 condition=cond, read_via=via, raw={"big": "x" * 1000})  # type: ignore[arg-type]


def resolve(need: Need, offers: list[Offer]) -> list[Thing]:
    for o in offers:
        o.thing_id = "sony-a7-iii"
    return [Thing(id="sony-a7-iii", name="Sony A7 III", offers=list(offers))]


def judge(need: Need, things: list[Thing]) -> Verdict:
    offers = [o for t in things for o in t.offers]
    for o in offers:
        resale = 700.0 if o.condition == "new" else 680.0
        total = (o.price_eur or 0) - resale
        o.true_cost = TrueCost(months=12, sticker_eur=o.price_eur or 0, extras_eur=0, resale_eur=resale,
                               total_eur=total, per_month_eur=round(total / 12, 2), confidence="medium",
                               receipt=[("sticker", o.price_eur or 0), ("resale in 12 mo", -resale)],
                               basis="fake resale")
        o.trust = 0.4 if "market" in o.url and o.price_eur == 790.0 else 0.9
        if o.condition == "used":
            o.haggle = Haggle(700, 760, 720, "Hi, would you take €720?")
    best = min(offers, key=lambda o: o.true_cost.per_month_eur)  # type: ignore[union-attr]
    cheapest = min(offers, key=lambda o: o.price_eur or 0)
    return Verdict(headline="Buy the used one: lowest true cost.", best_offer_url=cheapest.url,
                   best_true_cost_url=best.url, buy_or_wait="buy now", lines=["used beats new by 6x per month"])


def kwargs(**extra: Any) -> dict[str, Any]:
    return {"parse_need": parse_need, "discover": discover, "read": read, "resolve": resolve,
            "judge": judge, "persist": False, **extra}
