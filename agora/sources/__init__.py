"""SOURCES: the big European source registry (second-hand, new, refurbished, rental and service sites) and how to
search each one, found automatically by `scripts/onboard_sources.py` (free plain HTTP; a few paid Context.dev
checks for important sites that block it).

Data: `agora/sources/registry.json` (+ `registry_summary.csv`). Seeds: `seed_secondhand.json` (Robert's 193
second-hand sources) + `seeds.EXTRA` (shops, price comparison, refurbishers, rental, service platforms).

Status per source:
  verified_free            a test query's results page, fetched plainly, had >= 5 listing links (+ prices):
                           read it with httpx, no Context.dev token, no rate limit (gold)
  verified_contextdev      same, but only through a Context.dev scrape (bot wall / JS for plain fetch)
  search_found_unverified  a search template was found (OpenSearch / SearchAction / form / pattern / known) but its
                           page did not show listings to a plain fetch (JS-rendered, robots, POST, ...)
  no_search                no search URL found (or the site was unreachable: `reason`)
  blocked                  a bot wall answered the plain fetch

API: load(), get(key), for_query(country, lanes, categories), build_url(source, query, page), test_query(source),
as_site_kwargs(source) (-> agora.marketplaces.Site fields).
"""
from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

HERE = pathlib.Path(__file__).resolve().parent
REGISTRY = HERE / "registry.json"

LANES = ("new", "used", "refurb", "rental", "service")
STATUSES = ("verified_free", "verified_contextdev", "search_found_unverified", "no_search", "blocked")
CATEGORIES = (
    "general", "electronics", "computers", "phones", "appliances", "home", "furniture", "fashion", "shoes", "kids",
    "toys", "sports", "bikes", "outdoor", "books", "media", "music", "cameras", "games", "beauty", "health", "pets",
    "garden", "diy", "tools", "cars", "vehicles", "auto_parts", "collectibles", "watches", "luxury", "food",
    "cleaning", "handyman", "trades", "renovation", "moving", "childcare", "eldercare", "petcare", "beauty_services",
    "tutoring", "gardening_services", "housing",
)
SERVICE_CATS = {"cleaning", "handyman", "trades", "renovation", "moving", "childcare", "eldercare", "petcare",
                "beauty_services", "tutoring", "gardening_services", "housing"}

COUNTRY_NAMES = {
    "albania": "al", "andorra": "ad", "armenia": "am", "austria": "at", "azerbaijan": "az", "belarus": "by",
    "belgium": "be", "bosnia and herzegovina": "ba", "bulgaria": "bg", "croatia": "hr", "cyprus": "cy",
    "czechia": "cz", "denmark": "dk", "estonia": "ee", "finland": "fi", "france": "fr", "georgia": "ge",
    "germany": "de", "greece": "gr", "hungary": "hu", "iceland": "is", "ireland": "ie", "italy": "it",
    "kosovo": "xk", "latvia": "lv", "liechtenstein": "li", "lithuania": "lt", "luxembourg": "lu", "malta": "mt",
    "moldova": "md", "monaco": "mc", "montenegro": "me", "netherlands": "nl", "north macedonia": "mk",
    "norway": "no", "poland": "pl", "portugal": "pt", "romania": "ro", "russia": "ru", "san marino": "sm",
    "serbia": "rs", "slovakia": "sk", "slovenia": "si", "spain": "es", "sweden": "se", "switzerland": "ch",
    "turkey": "tr", "ukraine": "ua", "united kingdom": "gb", "uk": "gb", "eu": "eu",
}
COUNTRY_LANGS = {
    "fi": ["fi", "sv"], "se": ["sv"], "no": ["no"], "dk": ["da"], "is": ["is"], "de": ["de"], "at": ["de"],
    "ch": ["de", "fr", "it"], "li": ["de"], "nl": ["nl"], "be": ["nl", "fr"], "lu": ["fr", "de", "lb"],
    "fr": ["fr"], "mc": ["fr"], "es": ["es"], "ad": ["ca", "es"], "it": ["it"], "sm": ["it"], "mt": ["en", "mt"],
    "pt": ["pt"], "ie": ["en"], "gb": ["en"], "pl": ["pl"], "cz": ["cs"], "sk": ["sk"], "hu": ["hu"],
    "ro": ["ro"], "md": ["ro"], "bg": ["bg"], "gr": ["el"], "cy": ["el"], "hr": ["hr"], "si": ["sl"],
    "ba": ["bs"], "rs": ["sr"], "me": ["sr"], "mk": ["mk"], "al": ["sq"], "xk": ["sq"], "ee": ["et"],
    "lv": ["lv"], "lt": ["lt"], "ua": ["uk"], "by": ["ru"], "ru": ["ru"], "tr": ["tr"], "ge": ["ka"],
    "am": ["hy"], "az": ["az"], "eu": ["en"],
}
CURRENCY = {"se": "SEK", "no": "NOK", "dk": "DKK", "pl": "PLN", "gb": "GBP", "cz": "CZK", "ch": "CHF", "li": "CHF",
            "hu": "HUF", "ro": "RON", "bg": "BGN", "is": "ISK", "rs": "RSD", "ba": "BAM", "mk": "MKD", "al": "ALL",
            "md": "MDL", "ua": "UAH", "by": "BYN", "ru": "RUB", "tr": "TRY", "ge": "GEL", "am": "AMD", "az": "AZN"}

# --------------------------------------------------------------------------- test queries (verification)

_Q_CAT = {"phones": "iphone", "electronics": "samsung", "computers": "lenovo", "appliances": "bosch",
          "games": "playstation", "toys": "lego", "kids": "lego", "fashion": "adidas", "shoes": "nike",
          "luxury": "gucci", "watches": "seiko", "books": "harry potter", "media": "harry potter",
          "music": "yamaha", "cameras": "canon", "bikes": "shimano", "sports": "adidas", "outdoor": "garmin",
          "diy": "bosch", "tools": "bosch", "garden": "bosch", "beauty": "nivea", "health": "nivea",
          "pets": "royal canin", "cars": "volkswagen", "vehicles": "volkswagen", "auto_parts": "bosch",
          "collectibles": "pokemon", "food": "coffee", "general": "lego", "home": "philips"}
_FURNITURE = {"fi": "sohva", "sv": "soffa", "no": "sofa", "da": "sofa", "de": "sofa", "nl": "bank", "fr": "canapé",
              "es": "sofá", "it": "divano", "pt": "sofá", "pl": "sofa", "cs": "pohovka", "sk": "sedačka",
              "hu": "kanapé", "ro": "canapea", "en": "sofa"}
_CLEANING = {"fi": "siivous", "sv": "städning", "no": "rengjøring", "da": "rengøring", "de": "reinigung",
             "nl": "schoonmaak", "fr": "ménage", "es": "limpieza", "it": "pulizie", "pt": "limpeza",
             "pl": "sprzątanie", "cs": "úklid", "en": "cleaning"}
_TRADES = {"fi": "putkimies", "sv": "elektriker", "no": "elektriker", "da": "elektriker", "de": "elektriker",
           "nl": "loodgieter", "fr": "plombier", "es": "fontanero", "it": "idraulico", "pt": "canalizador",
           "pl": "hydraulik", "cs": "elektrikář", "en": "plumber"}
_CAPITAL = {"fi": "helsinki", "se": "stockholm", "no": "oslo", "dk": "københavn", "de": "berlin", "at": "wien",
            "ch": "zürich", "nl": "amsterdam", "be": "bruxelles", "lu": "luxembourg", "fr": "paris", "es": "madrid",
            "it": "roma", "pt": "lisboa", "ie": "dublin", "gb": "london", "pl": "warszawa", "cz": "praha",
            "sk": "bratislava", "hu": "budapest", "ro": "bucuresti", "bg": "sofia", "gr": "athina",
            "hr": "zagreb", "si": "ljubljana", "ee": "tallinn", "lv": "riga", "lt": "vilnius"}


def test_query(src: dict) -> str:
    """A query that a working search of this site answers with many listings (brands travel across languages)."""
    dom = src.get("domain", "")
    cats = src.get("categories") or ["general"]
    lang = (src.get("languages") or ["en"])[0]
    cc = (src.get("countries") or ["eu"])[0]
    if "ikea." in dom:
        return "billy"
    if "housing" in cats:
        return _CAPITAL.get(cc, "apartment")
    if set(cats) & {"cleaning"}:
        return _CLEANING.get(lang, "cleaning")
    if set(cats) & {"trades", "handyman", "renovation"}:
        return _TRADES.get(lang, "plumber")
    if set(cats) & {"childcare", "eldercare"}:
        return _CAPITAL.get(cc, "babysitter")
    if set(cats) & {"beauty_services", "petcare", "tutoring", "moving", "gardening_services"}:
        return _CAPITAL.get(cc, "london")
    if cats[0] == "general":
        return "lego"
    if cats[0] == "furniture":
        return _FURNITURE.get(lang, "sofa")
    for c in cats:
        if c in _Q_CAT and c != "general":
            return _Q_CAT[c]
    return "lego"


# --------------------------------------------------------------------------- seeds -> source records

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def key_for(url: str) -> str:
    p = urlsplit(url if "//" in url else "https://" + url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = p.path.strip("/")
    path = path if path and len(path) <= 12 else ""
    return _slug(host + ("_" + path if path else ""))


def _countries(market: str) -> list[str]:
    m = market.lower()
    out = []
    for part in re.split(r",| and ", m):
        part = part.strip()
        if part in COUNTRY_NAMES:
            out.append(COUNTRY_NAMES[part])
        elif "selected european" in part or part.startswith("eu") or "international" in part \
                or "cross-border" in part or "nearby" in part:
            out.append("eu")
    for name, cc in COUNTRY_NAMES.items():
        if len(name) > 3 and name in m and cc not in out:
            out.append(cc)
    return list(dict.fromkeys(out)) or ["eu"]


_CAT_WORDS = [
    (r"vehicle|car\b|cars\b|motor", ["cars", "vehicles"]), (r"bike|cycl", ["bikes"]), (r"book", ["books"]),
    (r"media|music|vinyl|record", ["media", "music"]), (r"camera|photo", ["cameras"]), (r"watch", ["watches"]),
    (r"fashion|cloth|apparel", ["fashion"]), (r"luxury|designer", ["luxury", "fashion"]),
    (r"kid|baby|child|family", ["kids"]), (r"furniture|design|home|interior|vintage", ["home", "furniture"]),
    (r"phone", ["phones"]), (r"tech|electronic|computer|laptop", ["electronics", "computers"]),
    (r"collect|card|stamp|coin|lego|antique|art", ["collectibles"]), (r"sport|outdoor|ski|camp", ["sports", "outdoor"]),
    (r"instrument|guitar|gear", ["music"]), (r"general|goods", ["general"]),
]


def _cats_from(text: str) -> list[str]:
    out: list[str] = []
    for rx, cats in _CAT_WORDS:
        if re.search(rx, text, re.I):
            out += [c for c in cats if c not in out]
    return out or ["general"]


def secondhand_seed(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        typ = r.get("type", "")
        group = r.get("group", "")
        lanes = ["refurb"] if "Refurbished" in typ else ["used"]
        if "Refurbished" in group and "refurb" not in lanes:
            lanes.append("refurb")
        kind = {"Classifieds": "classifieds", "Resale retailer": "resale_retailer", "Vehicle marketplace": "vehicles",
                "Vintage and auctions": "auction", "Specialist marketplace": "specialist",
                "General resale": "marketplace", "Refurbished marketplace": "refurbisher"}.get(typ, "marketplace")
        ccs = _countries(r.get("market", ""))
        cats = _cats_from(r.get("cats", "") + " " + (group if group not in ("Multi-market",) and "Europe" not in group
                                                       and group not in ("Nordics", "Baltics") else ""))
        url = r.get("url") or f"https://{r['domain']}/"
        out.append({"key": key_for(url), "name": r.get("name") or r["domain"], "domain": r["domain"].lower(),
                    "home": url, "countries": ccs, "languages": _langs(ccs), "lanes": lanes, "categories": cats,
                    "kind": kind, "seed": "secondhand_xlsx", "market": r.get("market"), "group": group})
    return out


def _langs(ccs: list[str]) -> list[str]:
    out: list[str] = []
    for c in ccs:
        out += [x for x in COUNTRY_LANGS.get(c, ["en"]) if x not in out]
    return out


def extra_seed(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        url, ccs, lanes, cats, kind = parts[:5]
        name = " ".join(parts[5:]) or urlsplit(url).netloc
        host = urlsplit(url).netloc.lower()
        ccl = ccs.split(",")
        out.append({"key": key_for(url), "name": name, "domain": host[4:] if host.startswith("www.") else host,
                    "home": url, "countries": ccl, "languages": _langs(ccl), "lanes": lanes.split(","),
                    "categories": cats.split(","), "kind": kind, "seed": "extra"})
    return out


def seed_records() -> list[dict]:
    """All seeds, deduplicated by key (lanes / categories / countries merged)."""
    from agora.sources.seeds import EXTRA
    rows = json.loads((HERE / "seed_secondhand.json").read_text())
    merged: dict[str, dict] = {}
    for rec in secondhand_seed(rows) + extra_seed(EXTRA):
        k = rec["key"]
        if k in merged:
            m = merged[k]
            for f in ("lanes", "categories", "countries", "languages"):
                m[f] = list(dict.fromkeys(m[f] + rec[f]))
            m["seed"] = m["seed"] + "+" + rec["seed"]
        else:
            merged[k] = rec
    return list(merged.values())


# --------------------------------------------------------------------------- runtime API

# hand fixes for listing-link patterns the onboarding guessed wrong (coverage audit, 14 Nov): kleinanzeigen's
# '^/[^/]+/[^/]*\d{3,}' matched the category menu (/s-immobilien/c195) and missed most listings
# (/s-anzeige/ps5-slim/3568005049-279-3214: no 3 digits in the slug), so a page of 27 listings gave ~2 rows
LISTING_FIX = {
    "kleinanzeigen.de": r"^/s-anzeige/[^/?#]+/\d{6,}",
}


@lru_cache(maxsize=1)
def _load_cached(path: str, mtime: float) -> tuple[dict, ...]:
    data = json.loads(pathlib.Path(path).read_text())
    rows = data.get("sources", data) if isinstance(data, dict) else data
    for r in rows:
        if r.get("domain") in LISTING_FIX:
            r["listing"] = LISTING_FIX[r["domain"]]
    return tuple(rows)


def load(path: str | pathlib.Path | None = None) -> list[dict]:
    """Every source in the registry (dicts; copy before mutating)."""
    p = pathlib.Path(path or REGISTRY)
    if not p.exists():
        return []
    return list(_load_cached(str(p), p.stat().st_mtime))


def get(key: str, path: str | pathlib.Path | None = None) -> dict | None:
    return next((s for s in load(path) if s["key"] == key), None)


STATUS_WEIGHT = {"verified_free": 1.0, "verified_contextdev": 0.7, "search_found_unverified": 0.25,
                 "no_search": 0.0, "blocked": 0.0}


def for_query(country: str | None = None, lanes: list[str] | tuple[str, ...] | str | None = None,
              categories: list[str] | tuple[str, ...] | str | None = None, *, include_unverified: bool = False,
              include_comparison: bool = False, limit: int | None = None,
              path: str | pathlib.Path | None = None) -> list[dict]:
    """Searchable sources for a need, best first: the country's own sources, then EU-wide ones; the lane must match;
    a category match (or a general store) is required when categories are given. Free-readable first."""
    cc = (country or "").lower() or None
    if cc == "uk":
        cc = "gb"
    want_l = {lanes} if isinstance(lanes, str) else set(lanes or ())
    want_l = {"refurb" if x == "refurbished" else x for x in want_l}
    want_c = {categories} if isinstance(categories, str) else set(categories or ())
    out = []
    for s in load(path):
        w = STATUS_WEIGHT.get(s.get("status", ""), 0.0)
        if w <= 0 or not s.get("template"):
            continue
        if s["status"] == "search_found_unverified" and not include_unverified:
            continue
        if s.get("kind") == "comparison" and not include_comparison:
            continue
        if want_l and not want_l & set(s.get("lanes", [])):
            continue
        ccs = s.get("countries", [])
        if cc and cc not in ccs and "eu" not in ccs:
            continue
        cats = set(s.get("categories", []))
        cat_hit = len(want_c & cats)
        if want_c and not cat_hit and not ("general" in cats and not want_c & SERVICE_CATS):
            continue
        score = w * (0.4 + 0.6 * float(s.get("yield") or 0.3))
        score += 0.5 if cc and cc in ccs else 0.0
        score += 0.25 * min(cat_hit, 2) - (0.05 * max(0, len(cats) - 4) if cat_hit else 0)
        out.append((score, s))
    out.sort(key=lambda x: -x[0])
    res = [dict(s, rank_score=round(sc, 3)) for sc, s in out]
    return res[:limit] if limit else res


def build_url(src: dict, query: str, page: int = 1) -> str:
    """The source's search URL for `query` (results page `page`, when the site's paging is known)."""
    tpl = src["template"]
    words = query.strip().split()
    url = tpl.replace("{q}", quote_plus(query.strip())).replace("{dash}", "-".join(quote(w) for w in words))
    if page <= 1:
        return url
    pg = src.get("pagination") or {}
    if pg.get("param"):
        p = urlsplit(url)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != pg["param"]]
        q.append((pg["param"], str(page)))
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))
    if pg.get("path_suffix"):
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/") + pg["path_suffix"].replace("{page}", str(page)),
                           p.query, ""))
    return url


def as_site_kwargs(src: dict) -> dict | None:
    """Fields for agora.marketplaces.Site (product lanes only; services go to discover.SERVICE_MARKETS)."""
    lanes = src.get("lanes", [])
    lane = next((x for x in ("used", "refurb", "new") if x in lanes), None)
    if lane is None or not src.get("template") or src.get("method", "get") != "get":
        return None
    if src.get("kind") == "comparison":
        lane = "comparison"
    cc = next((c for c in src.get("countries", []) if c != "eu"), "eu")
    return {"key": "src_" + src["key"], "country": cc, "lane": "refurbished" if lane == "refurb" else lane,
            "template": src["template"].replace("{", "{{").replace("}", "}}").replace("{{q}}", "{q}")
            .replace("{{dash}}", "{dash}"),
            "listing": src.get("listing"), "lang": (src.get("languages") or ["en"])[0],
            "itemlist": bool(src.get("itemlist")) and src.get("status") == "verified_free",
            "verified": src.get("status") in ("verified_free", "verified_contextdev"),
            "bulky_ok": True}


def for_url(url: str, path: str | pathlib.Path | None = None) -> dict | None:
    """The registry source this URL belongs to (longest home-path match on the same host), else None."""
    p = urlsplit(url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    best, best_len = None, -1
    for s in load(path):
        if s.get("domain") != host:
            continue
        hp = urlsplit(s.get("home") or "").path.rstrip("/")
        if p.path.startswith(hp) and len(hp) > best_len:
            best, best_len = s, len(hp)
    return best


# screen-reader / button text inside a listing link, not part of the title ('Bewaren in Mijn Favorieten Sony PS5')
TITLE_JUNK = re.compile(r"\b(?:Bewaren in Mijn Favorieten|Opslaan als favoriet|Zu Favoriten hinzufügen|"
                        r"Merkliste|Lisää suosikkeihin|Spara som favorit|Add to favou?rites|"
                        r"Product images?,? \d+ (?:of|/) \d+|Tuotekuva\w*,? \d+ / \d+)", re.I)


def rows_from_html(page: str, page_url: str, src: dict, max_rows: int = 25) -> list[dict]:
    """Cut a plainly fetched results page into listings with code (no model, no Context.dev):
    [{title, url, price, currency, text}], one per distinct listing URL matching the source's `listing` regex.
    A row's text runs from its link to the next listing link; its price is the first price in that text."""
    import html as _html
    from urllib.parse import urljoin

    from agora.sources import discovery as D
    rx = src.get("listing")
    if not rx or not page:
        return []
    pat = re.compile(rx)
    anchors = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page, re.I | re.S):
        hm = re.search(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", m.group(1), re.I)
        if not hm:
            continue
        u = urljoin(page_url, _html.unescape(hm.group(1) or hm.group(2) or ""))
        up = urlsplit(u)
        if not D.same_site(u, page_url) or not pat.search(up.path + ("?" + up.query if up.query else "")):
            continue
        anchors.append((m.start(), m.end(), u.split("#")[0], m.group(1), m.group(2)))
    rows: dict[str, dict] = {}
    order: list[str] = []
    for i, (start, end, u, attrs, inner) in enumerate(anchors):
        nxt = next((a[0] for a in anchors[i + 1:] if a[2] != u), len(page))
        text = D.visible_text(page[start:min(nxt, start + 6000)])
        title = TITLE_JUNK.sub(" ", D.visible_text(inner)).strip()
        if not title:
            t = re.search(r"""\b(?:title|aria-label)\s*=\s*["']([^"']+)""", attrs) or \
                re.search(r"""<img\b[^>]*\balt\s*=\s*["']([^"']+)""", inner, re.I)
            title = TITLE_JUNK.sub(" ", _html.unescape(t.group(1))).strip() if t else ""
            title = "" if re.fullmatch(r"[\W\d]*", title) else title     # 'Product images, 1 of 2' leftovers
        pm = D.PRICE.search(text)
        price = _amount(pm.group(0)) if pm else None
        cur = CURRENCY.get(next((c for c in src.get("countries", []) if c != "eu"), ""), "EUR")
        r = rows.get(u)
        if r is None:
            rows[u] = {"title": title[:200], "url": u, "price": price, "currency": cur, "text": text[:400]}
            order.append(u)
        else:
            if len(title) > len(r["title"]):
                r["title"] = title[:200]
            if r["price"] is None and price is not None:
                r["price"] = price
    return [rows[u] for u in order][:max_rows]


def _amount(s: str) -> float | None:
    m = re.search(r"\d[\d .,  ']*", s)
    if not m:
        return None
    n = re.sub(r"[   ']", "", m.group(0)).rstrip(".,")
    if re.search(r"[.,]\d{1,2}$", n):
        whole, frac = n[:-3 if n[-3] in ".," else -2], n[-2:] if n[-3] in ".," else n[-1:]
        whole = re.sub(r"[.,]", "", whole)
        try:
            return float(f"{whole}.{frac}")
        except ValueError:
            return None
    try:
        return float(re.sub(r"[.,]", "", n))
    except ValueError:
        return None


# --------------------------------------------------------------------------- embedded results (Next.js)

_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
NO_PRICE_TYPES = {"SEE_DESCRIPTION", "EXCHANGE", "FREE", "RESERVED", "NOTK", "ON_REQUEST"}


def rows_from_next_data(page: str, page_url: str, src: dict) -> list[dict]:
    """marktplaats / 2dehands embed the result list as JSON (__NEXT_DATA__ ... searchRequestAndResponse.listings):
    clean titles, prices in cents, the seller's town. The HTML anchors carry the whole card as their text
    ('Lego Set - 7237 € 25,00 Details Nieuw ... onderdelen'), which made good sets look like 'sold as parts'.
    -> [{title, url, price, currency, text, location, image}]; [] when the page has no such data."""
    import json as _json
    from urllib.parse import urljoin
    m = _NEXT.search(page or "")
    if not m:
        return []
    try:
        data = _json.loads(m.group(1))
    except ValueError:
        return []
    found: list[dict] = []

    def walk(x: Any, depth: int = 0) -> None:
        if found or depth > 8:
            return
        if isinstance(x, dict):
            lst = x.get("listings")
            if isinstance(lst, list) and lst and isinstance(lst[0], dict) and "title" in lst[0]:
                found.extend(lst)
                return
            for v in x.values():
                walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x[:50]:
                walk(v, depth + 1)
    walk(data)
    cur = CURRENCY.get(next((c for c in src.get("countries", []) if c != "eu"), ""), "EUR")
    rows = []
    for it in found:
        url = it.get("vipUrl") or it.get("url")
        title = str(it.get("title") or "").strip()
        if not url or not title:
            continue
        pi = it.get("priceInfo") or {}
        cents = pi.get("priceCents")
        price = (cents / 100.0) if isinstance(cents, (int, float)) and cents > 0 \
            and str(pi.get("priceType") or "").upper() not in NO_PRICE_TYPES else None
        imgs = it.get("imageUrls") or []
        img = urljoin("https:", imgs[0]) if imgs and isinstance(imgs[0], str) else None
        loc = (it.get("location") or {}).get("cityName")
        rows.append({"title": title[:200], "url": urljoin(page_url, url).split("#")[0], "price": price,
                     "currency": cur, "text": str(it.get("description") or "")[:400], "location": loc,
                     "image": img, "price_type": pi.get("priceType")})
    return rows
