"""Shared fixtures for the brain tests (need / resolve / judge): a realistic Sony a7 III market."""
from __future__ import annotations

import json
import pathlib

from agora.models import Offer

FIX = pathlib.Path(__file__).parent / "fixtures"


def fixture_offers() -> list[Offer]:
    """The three real Context.dev product pages (Kenmore $1398, B&H $1398, eBay $789.99)."""
    out = []
    for i, (src, cond) in enumerate([("kenmorecamera.com", "new"), ("bhphotovideo.com", "new"), ("ebay.com", "used")], 1):
        p = json.loads((FIX / f"product{i}.json").read_text())["product"]["data"]["product"]
        out.append(Offer(url=f"https://{src}/a7iii", source=src, title=p["name"], price=float(p["price"]),
                         currency=p["currency"], price_eur=round(float(p["price"]) * 0.92, 2), condition=cond,
                         brand=p.get("brand"), sku=p.get("sku"), in_stock=p.get("availability") == "in_stock",
                         seller="camera_pro_fi" if src == "ebay.com" else None, read_via="contextdev_product"))
    return out


def market() -> list[Offer]:
    """A7 III: new $1398 x2, six used €700-900, a refurb, a too-cheap scam, an accessory, a wrong model."""
    def o(title: str, eur: float | None, cond: str, src: str, **kw) -> Offer:
        return Offer(url=f"https://{src}/{abs(hash((title, eur, src))) % 10**6}", source=src, title=title,
                     price=eur, currency="EUR" if eur is not None else None, price_eur=eur,
                     condition=cond, **kw)  # type: ignore[arg-type]

    return fixture_offers() + [
        o("Sony a7 III runko, käytetty", 780, "used", "tori.fi", seller="mikko", location="Helsinki"),
        o("Sony A7III body - 12k shutter count", 850, "used", "ebay.de", seller="fotofan"),
        o("Sony Alpha ILCE-7M3 gebraucht", 720, "used", "kleinanzeigen.de", seller="anna"),
        o("Sony a7 mark 3 body, mint", 900, "used", "huuto.net", seller="pekka"),
        o("Sony a7 iii kamera", 700, "used", "tori.fi", seller="liisa"),
        o("Sony A7 III (refurbished)", 999, "refurbished", "backmarket.fi", in_stock=True),
        o("SONY A7 III BODY NEW SEALED", 290, "used", "tori.fi"),                       # scam bait
        o("NP-FZ100 battery for Sony a7 III", 39, "new", "amazon.de", in_stock=True),   # accessory
        o("Sony A7 II body", 520, "used", "tori.fi", seller="x"),                       # wrong generation
    ]
