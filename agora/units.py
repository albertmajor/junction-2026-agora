"""UNITS: one used-dealer page, several units for sale; and each unit's condition GRADE.

Used dealers (Wex, MPB, KEH, Rebuy, Back Market, Kamerastore ...) list the same model several times: Wex's
"USED Sony A7 III" page sells an Excellent (9) body at £818 and, under "Similar used", a Good (8) one with
14,641 shutter actuations at £678. Read as one offer only the first price survived. Here every in-stock unit
becomes its own offer (its own link, or the page URL + `#unit-N` when the page gives none), with the seller's
grade kept as written plus a rough 0..1 score so the judge can compare like with like.

Pure and offline: regexes over page HTML / text, no network.
"""
from __future__ import annotations

import html as htmllib
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

# shops that sell graded second-hand / refurbished units, often several of one model on one page
USED_DEALERS = (
    "wexphotovideo.", "mpb.com", "keh.com", "rebuy.", "backmarket.", "kamerastore.", "usedlens.", "mpex.com",
    "ffordes.", "parkcameras.", "camerajungle.", "cameraland.", "swappie.", "refurbed.", "foto-erhardt.",
    "calumet", "jessops.com/used", "asgoodasnew.", "musicmagpie.", "fotokoch.", "cewe-print", "kamera-express.",
)
MAX_UNITS = 8          # units kept per page: the cheapest of each grade first, then the next cheapest


def is_used_dealer(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in USED_DEALERS)


# ---------------------------------------------------------------- grades

# (pattern, canonical word, score 0..1); most specific first ("very good" before "good", "like new" before "new")
_GRADES: list[tuple[re.Pattern[str], str, float]] = [(re.compile(p, re.I), w, s) for p, w, s in [
    (r"\b(?:mint|like[- ]new|as[- ]new|wie neu|neuwertig|kuin uusi|nieuwstaat|comme neuf|premium|pristine|"
     r"open[- ]box)\b", "like new", 0.95),
    (r"\bexcellent\s*(?:plus|\+)|\bexc\s*\+|\bex\+", "excellent+", 0.92),
    (r"\b(?:excellent|ausgezeichnet|erinomainen|uitstekend|parfait état|stallion)\b", "excellent", 0.9),
    (r"\b(?:very good|sehr gut|erittäin hyvä|très bon|zeer goed|grade a)\b", "very good", 0.85),
    (r"\b(?:good|gut|hyvä|bon état|goed|grade b)\b", "good", 0.75),
    (r"\b(?:fair|correct|well[- ]used|acceptable|stark genutzt|tyydyttävä|grade c|bargain)\b", "fair", 0.6),
    (r"\b(?:heavily[- ]used|heavy wear|ugly|for parts|poor)\b", "heavily used", 0.45),
]]
# Wex / MPB-style numeric grades: "Excellent (9)", "Mint (9+)", "Very good (9-)", "Good (8)"
_NUM_GRADE = re.compile(r"\(\s*(10|[1-9])\s*([+-]?)\s*\)")
# the grade label as a page writes it: "Condition: Excellent (9)", "Cosmetic condition: Well used", "Grade: Fair"
_GRADE_WORDS = (r"mint|like[- ]new|as[- ]new|wie neu|neuwertig|kuin uusi|nieuwstaat|comme neuf|premium|pristine|"
                r"excellent\s*(?:plus|\+)?|exc\s*\+|ex\+|ausgezeichnet|erinomainen|uitstekend|parfait état|"
                r"very good|sehr gut|erittäin hyvä|très bon|zeer goed|good|gut|hyvä|bon état|goed|"
                r"fair|correct|well[- ]used|acceptable|stark genutzt|tyydyttävä|heavily[- ]used|bargain|ugly|"
                r"grade [abc]")
GRADE_LABEL = re.compile(
    r"(?:cosmetic\s+)?(?:condition|grade|zustand|kunto|staat|état)(?:\s+(?:rating|grade))?\s*[:\-–]\s*(?:\|\s*)?"
    r"((?:" + _GRADE_WORDS + r")(?:\s*\(\s*\d{1,2}\s*[+-]?\s*\))?)(?![a-zäöü])", re.I)
# "— Excellent (9)" at the end of a title
_TITLE_GRADE = re.compile(r"[—–\-|,]\s*([A-Za-z][A-Za-z ]{2,20}?\s*\(\s*\d{1,2}\s*[+-]?\s*\))\s*$")
SHUTTER = re.compile(
    r"(?:shutter\s*(?:count|actuations|clicks|cycles)?|actuations|laukaisu(?:t|ja|määrä)|auslösungen|"
    r"sluiter(?:tellingen)?)\s*(?:\(\s*approx(?:imately|\.)?\s*\))?\s*[:\-–]?\s*(?:\|\s*)?(?:approx(?:imately|\.)?\s*|ca\.?\s*|~\s*)?"
    r"(\d{1,3}(?:[,.   ]\d{3})+|\d{1,7})(?!\s*(?:%|mm|fps|s\b))", re.I)
BATTERY = re.compile(
    r"(?:battery\s*(?:health|capacity|condition|life)?|akun\s*(?:kunto|kapasiteetti)|akku(?:kapazität|zustand)|"
    r"batteriezustand|batterij(?:conditie)?|état de la batterie)\s*[:\-–]?\s*(?:\|\s*)?(?:of\s*)?(\d{2,3})\s*%"
    r"|(\d{2,3})\s*%\s*(?:battery|akku|akun)", re.I)


def _int(s: str) -> int | None:
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else None


def grade_score(grade: str | None) -> float | None:
    """'Excellent (9)' -> 0.9, 'Mint (9+)' -> 0.93, 'Good' -> 0.75. None = no known grade word."""
    if not grade:
        return None
    m = _NUM_GRADE.search(grade)
    if m:
        n = int(m.group(1))
        return round(min(1.0, n / 10 + {"+": 0.03, "-": -0.03}.get(m.group(2), 0.0)), 2)
    for pat, _, s in _GRADES:
        if pat.search(grade):
            return s
    return None


def clean_grade(raw: str | None) -> str | None:
    """A grade as the seller wrote it, trimmed; None unless it holds a known grade word or a (n) score."""
    if not raw:
        return None
    g = re.sub(r"\s+", " ", htmllib.unescape(str(raw))).strip(" -–—:|,.")
    if not g or len(g) > 40 or grade_score(g) is None:
        return None
    if g.lower() in ("new", "used", "refurbished", "unknown"):
        return None
    return g[0].upper() + g[1:]


def grade_info(*texts: str | None) -> dict[str, Any]:
    """{grade, grade_score, shutter_count, battery_health} from a title / snippet / page text (first hit wins,
    texts in order of trust). Empty dict when nothing is stated."""
    out: dict[str, Any] = {}
    for t in texts:
        if not t:
            continue
        t = htmllib.unescape(str(t))
        if "grade" not in out:
            g = None
            m = _TITLE_GRADE.search(t[:300])
            if m:
                g = clean_grade(m.group(1))
            if g is None:
                for m in GRADE_LABEL.finditer(t):
                    g = clean_grade(m.group(1))
                    if g:
                        break
            if g:
                out["grade"] = g
                out["grade_score"] = grade_score(g)
        if "shutter_count" not in out and (m := SHUTTER.search(t)):
            n = _int(m.group(1))
            if n is not None and 0 <= n < 2_000_000:
                out["shutter_count"] = n
        if "battery_health" not in out and (m := BATTERY.search(t)):
            n = _int(m.group(1) or m.group(2))
            if n is not None and 50 <= n <= 100:
                out["battery_health"] = n
    return out


def apply_grade(raw: dict[str, Any], info: dict[str, Any], source: str = "page") -> None:
    """Store grade fields on an offer's raw dict (never overwrites what is already there)."""
    for k in ("grade", "grade_score", "shutter_count", "battery_health"):
        if info.get(k) is not None and raw.get(k) is None:
            raw[k] = info[k]
    if info.get("grade") and "grade_from" not in raw:
        raw["grade_from"] = source


def describe(raw: dict[str, Any]) -> str | None:
    """'Good (8), shutter count 14,641' / 'Excellent, battery 91%' for receipts; None without a grade."""
    bits = []
    if raw.get("grade"):
        bits.append(str(raw["grade"]))
    if isinstance(raw.get("shutter_count"), int):
        bits.append(f"shutter count {raw['shutter_count']:,}")
    if isinstance(raw.get("battery_health"), (int, float)):
        bits.append(f"battery {raw['battery_health']:.0f}%")
    return ", ".join(bits) or None


# ---------------------------------------------------------------- unit cards in dealer HTML

_PRICE = re.compile(r"(?:(£|€|\$|EUR|GBP|USD)\s?(\d{1,3}(?:[,.  ]\d{3})*(?:[.,]\d{2})?)"
                    r"|(\d{1,3}(?:[.  ]\d{3})*(?:,\d{2})?)\s?(€|EUR|kr|SEK|NOK|DKK))")
_CUR = {"£": "GBP", "€": "EUR", "$": "USD", "kr": "SEK"}
_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r"<a\b[^>]*\bhref\s*=\s*[\"']?([^\"'\s>]+)[^>]*>(.*?)</a>", re.I | re.S)
_OUT = re.compile(r"\b(?:out of stock|sold out|sold|ausverkauft|loppuunmyyty|reserved|varattu)\b", re.I)
_CARD_START = re.compile(r"<div\b[^>]*\bclass\s*=\s*[\"']?[^\"'>]*\bdetails--\w+", re.I)   # wex unit cards


def _amount(num: str) -> float | None:
    s = num.replace(" ", "").replace(" ", "")
    if re.search(r",\d{2}$", s):                    # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _text(fragment: str) -> str:
    t = re.sub(r"<(?:svg|style|script)\b.*?</(?:svg|style|script)>", " ", fragment, flags=re.S | re.I)
    t = _TAG.sub(" | ", t)
    t = htmllib.unescape(t)
    return re.sub(r"(?:\s*\|\s*)+", " | ", re.sub(r"[ \t\r\n]+", " ", t)).strip(" |")


def cards_from_html(html: str, page_url: str, title_hint: str = "") -> list[dict[str, Any]]:
    """Unit cards on a used dealer's product page (Wex's 'Similar used' row: link, price, In Stock, grade,
    shutter count) -> [{url, title, price, currency, in_stock, grade, grade_score, shutter_count, ...}].
    Only cards linking back into the same site, in page order, de-duplicated by URL."""
    if not html or not is_used_dealer(page_url):
        return []
    host = urlsplit(page_url).netloc.lower().removeprefix("www.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    starts = [m.start() for m in _CARD_START.finditer(html)]
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else s + 8000
        block = html[s:min(end, s + 8000)]
        a = _HREF.search(block)
        if not a:
            continue
        url = urljoin(page_url, htmllib.unescape(a.group(1))).split("#")[0]
        if urlsplit(url).netloc.lower().removeprefix("www.") != host or url in seen:
            continue
        text = _text(block)
        pm = _PRICE.search(text)
        if not pm:
            continue
        if pm.group(1):
            cur, amount = _CUR.get(pm.group(1), pm.group(1).upper()), _amount(pm.group(2))
        else:
            cur, amount = _CUR.get(pm.group(4), pm.group(4).upper()), _amount(pm.group(3))
        if amount is None or amount <= 0:
            continue
        title = _text(a.group(2)) or title_hint
        info = grade_info(text)
        seen.add(url)
        out.append({"url": url, "title": title, "price": amount, "currency": cur,
                    "in_stock": False if _OUT.search(text) and "in stock" not in text.lower() else
                    (True if "in stock" in text.lower() else None), **info})
    return out


# ---------------------------------------------------------------- picking units

def pick_units(units: list[Any], price: Any = lambda u: u.price_eur or u.price or 0,
               grade: Any = lambda u: (u.raw or {}).get("grade"), limit: int = MAX_UNITS) -> list[Any]:
    """The units worth showing: the cheapest of each grade first, then the next cheapest, up to `limit`,
    returned cheapest first. Two units at the same price and grade count once."""
    seen: set[tuple[Any, Any]] = set()
    uniq = []
    for u in sorted(units, key=price):
        k = (round(price(u), 2), (grade(u) or "").lower())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(u)
    keep: list[Any] = []
    grades: set[str] = set()
    for u in uniq:
        g = (grade(u) or "").lower()
        if g not in grades:
            grades.add(g)
            keep.append(u)
    for u in uniq:
        if len(keep) >= limit:
            break
        if u not in keep:
            keep.append(u)
    return sorted(keep[:limit], key=price)
