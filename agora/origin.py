"""ORIGIN: where an offer's seller is, and whether it ships to Finland. Pure, offline, instant.

Written at Junction 2026 (UI round A, the owner's FLAGS item). The UI shows a small country flag on the line,
the offer list and the sheet; its tooltip says what the guess is based on. Evidence, first hit wins:

1. the listing's own location (places gazetteer); services: the provider's service area   -> confident
2. the seller address the shop states in its JSON-LD (reader stashes raw['seller_address']) -> confident
3. the marketplace: national classifieds (tori.fi, blocket.se ...) -> confident;
   multi-country platforms (vinted.<tld>, ebay.<tld>) -> the TLD's country, a guess
4. a small table of big shops on generic domains (bhphotovideo.com -> US)                  -> guess
5. the ccTLD (.de, .co.uk)                                                                 -> guess
6. the price currency (USD -> US; EUR says nothing); ccTLD + currency agreeing: domain_currency, still a guess

Every string here is built from our own tables (or a cleaned locality), never raw page text.
See docs/UI_ROUND_A.md section 6 and CONTRACT.md "Additive (origin)".
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from agora import marketplaces, places

EU = frozenset("at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se".split())

# English short names for the countries the gazetteer does not cover (shops seen in recordings, currencies)
_WORLD: dict[str, str] = {
    "us": "United States", "ca": "Canada", "au": "Australia", "nz": "New Zealand", "jp": "Japan",
    "cn": "China", "hk": "Hong Kong", "tw": "Taiwan", "kr": "South Korea", "sg": "Singapore", "in": "India",
    "za": "South Africa", "il": "Israel", "ae": "United Arab Emirates", "br": "Brazil", "mx": "Mexico",
    "li": "Liechtenstein", "md": "Moldova", "me": "Montenegro", "mk": "North Macedonia", "al": "Albania",
    "ba": "Bosnia and Herzegovina", "by": "Belarus", "ru": "Russia", "th": "Thailand", "my": "Malaysia",
}
NAMES: dict[str, str] = {**places.COUNTRY_DISPLAY, **_WORLD}

# names / alpha-3 codes a shop might write in addressCountry -> cc
_ALIASES: dict[str, str] = {
    **places.COUNTRY_NAMES,
    **{v.lower(): k for k, v in NAMES.items()},
    "usa": "us", "u.s.a.": "us", "u.s.": "us", "united states of america": "us", "america": "us",
    "the united states": "us", "the united kingdom": "gb", "u.k.": "gb", "korea": "kr", "republic of korea": "kr",
    "people's republic of china": "cn", "prc": "cn", "hongkong": "hk", "uae": "ae",
    "deu": "de", "fin": "fi", "swe": "se", "nor": "no", "dnk": "dk", "nld": "nl", "bel": "be", "fra": "fr",
    "ita": "it", "esp": "es", "prt": "pt", "irl": "ie", "gbr": "gb", "aut": "at", "che": "ch", "pol": "pl",
    "cze": "cz", "svk": "sk", "hun": "hu", "rou": "ro", "bgr": "bg", "grc": "gr", "hrv": "hr", "svn": "si",
    "est": "ee", "lva": "lv", "ltu": "lt", "lux": "lu", "mlt": "mt", "cyp": "cy", "isl": "is",
    "can": "ca", "aus": "au", "jpn": "jp", "chn": "cn", "hkg": "hk", "zaf": "za", "isr": "il",
}

# big shops on generic domains, seen in recordings. Shops we cannot place (e-infin.com, mpb.com) stay out.
KNOWN_SHOPS: dict[str, str] = {
    "bhphotovideo.com": "us", "adorama.com": "us", "keh.com": "us", "walmart.com": "us", "newegg.com": "us",
    "buydig.com": "us", "mpex.com": "us", "allenscamera.net": "us", "swappa.com": "us", "gazelle.com": "us",
    "jessops.com": "gb", "wexphotovideo.com": "gb", "cvp.com": "gb",
}

# ccTLD -> cc (second-level forms first). Generic TLDs (.com .net .org .eu .shop .store .io) say nothing.
_TLD2 = {"co.uk": "gb", "org.uk": "gb", "com.au": "au", "co.jp": "jp", "co.nz": "nz", "com.br": "br",
         "com.mx": "mx", "co.za": "za", "com.cn": "cn", "com.hk": "hk", "com.tw": "tw", "com.sg": "sg",
         "co.kr": "kr", "co.il": "il", "com.tr": "tr", "com.pl": "pl", "com.ua": "ua"}
_TLD = {"fi", "de", "se", "nl", "fr", "it", "es", "pl", "dk", "no", "at", "be", "ch", "ee", "lv", "lt", "ie", "pt",
        "cz", "sk", "hu", "gr", "ro", "bg", "hr", "si", "lu", "mt", "cy", "is", "jp", "au", "ca", "nz", "za", "us",
        "rs", "ua", "tr", "li", "hk", "tw", "kr", "sg", "il", "cn", "br", "mx", "in"}
_TLD_ALIAS = {"uk": "gb"}

# currency -> (cc, plain words). EUR says nothing.
CURRENCY: dict[str, tuple[str, str]] = {
    "USD": ("us", "US dollars"), "GBP": ("gb", "pounds"), "ZAR": ("za", "rand"), "SEK": ("se", "Swedish kronor"),
    "NOK": ("no", "Norwegian kroner"), "DKK": ("dk", "Danish kroner"), "PLN": ("pl", "złoty"),
    "CHF": ("ch", "Swiss francs"), "CZK": ("cz", "Czech koruna"), "HUF": ("hu", "forints"),
    "JPY": ("jp", "yen"), "CAD": ("ca", "Canadian dollars"), "AUD": ("au", "Australian dollars"),
}

SHIPS_TEXT = {"domestic": "yes, domestic", "yes": "yes, the shop says so",
              "no": "no, the shop does not ship to Finland", "unconfirmed": "not confirmed by the shop",
              "unstated": "not stated"}

_LOCALITY_OK = re.compile(r"^[^\W\d_][\w .,'’()/-]{0,58}$", re.U)


# ------------------------------------------------------------------ helpers

def _get(offer: Any, key: str, default: Any = None) -> Any:
    if isinstance(offer, dict):
        return offer.get(key, default)
    return getattr(offer, key, default)


def _host(url: str | None, source: str | None) -> str:
    host = ""
    try:
        host = urlsplit(url or "").hostname or ""
    except ValueError:
        host = ""
    host = (host or source or "").lower().strip().rstrip(".")
    host = host[4:] if host.startswith("www.") else host
    return host if re.fullmatch(r"[a-z0-9.-]{1,120}", host) else ""


def _tld_cc(host: str) -> tuple[str | None, str]:
    """(cc, the domain ending as written: 'co.uk') or (None, '')."""
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TLD2:
        end = ".".join(parts[-2:])
        return _TLD2[end], end
    if len(parts) >= 2:
        end = parts[-1]
        cc = _TLD_ALIAS.get(end, end)
        if end in _TLD or end in _TLD_ALIAS:
            return cc, end
    return None, ""


def norm_country(value: Any) -> str | None:
    """'DE' / 'deu' / 'Germany' / 'Deutschland' / 'UK' -> lower-case cc. None when not a country we know."""
    if not isinstance(value, str):
        return None
    v = places._fold(value).strip().strip(".")
    if not v:
        return None
    if len(v) == 2 and v.isalpha():
        cc = "gb" if v == "uk" else v
        return cc if cc in NAMES else None
    if v in _ALIASES:
        return _ALIASES[v]
    return places.country_for(v) if len(v) <= 40 else None


def _clean_city(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = " ".join(value.split())
    if not _LOCALITY_OK.match(v) or "http" in v.lower() or "@" in v:
        return None
    if v.islower() or v.isupper():
        v = places._display(v.lower())
    return v


def _place(location: str | None) -> tuple[str | None, str | None]:
    """A listing's location text -> (cc, city). Ambiguous names ('Reading', 'Nice') need a preposition
    (places.find_place handles that), so a bare 'reading' is not taken."""
    if not isinstance(location, str) or not location.strip():
        return None, None
    hit = places.find_place(location[:200])
    if hit:
        name, cc, _ = hit
        is_country = name == places.COUNTRY_DISPLAY.get(cc) and places._fold(name) not in places.CITY_CC
        return cc, (None if is_country else name)
    cc = norm_country(location.strip()) if len(location.strip()) <= 2 or \
        places._fold(location.strip()) in _ALIASES else None
    return cc, None


def _site_market(host: str) -> tuple[str | None, bool, str, str]:
    """(cc, confident, basis, basis_text) from the marketplace registry / second-hand list."""
    site = next((s for s in marketplaces.SITES.values() if s.domain == host), None)
    if site is not None and site.lane == "used" and not site.key.startswith(("vinted", "ebay")):
        return (site.country, True, "marketplace",
                f"from {host}, which lists sellers in {NAMES.get(site.country, site.country.upper())}")
    sh = marketplaces.second_hand(host)
    if sh is None and site is None:
        return None, False, "", ""
    cc, kind = sh if sh else (site.country if site else "eu", "retailer")
    if host.startswith(("vinted.", "ebay.")) or (site is not None and site.key.startswith(("vinted", "ebay"))):
        cc = "eu"
    if cc == "eu":                    # a multi-country platform: its TLD says which country's site this is
        tcc, end = _tld_cc(host)
        if tcc is None:
            return None, False, "", ""
        return tcc, False, "marketplace", f"a guess from the {host} site (a marketplace in several countries)"
    if kind in ("classifieds", "resale", "auction"):
        return cc, True, "marketplace", f"from {host}, which lists sellers in {NAMES.get(cc, cc.upper())}"
    return cc, False, "known_shop", "a guess from what we know about this shop"


def _ships(cc: str | None, raw: dict[str, Any] | None, flags: list[str] | None,
           service: bool) -> tuple[bool | None, str]:
    if cc == "fi":
        return True, SHIPS_TEXT["domestic"]
    said: bool | None = None
    if raw and (raw.get("ships_to") or raw.get("ships_text")):
        from agora import judge          # lazy: judge is heavy and origin must stay cheap to import
        said = judge.ships_to_fi(SimpleNamespace(raw=raw))  # type: ignore[arg-type]
    if said is None:
        for f in flags or []:
            low = str(f).lower()
            if "does not ship to finland" in low or "no shipping to fi" in low:
                said = False
                break
            if "unconfirmed" in low:
                continue
            if "ships to finland" in low:
                said = True
                break
    if said is True:
        return True, SHIPS_TEXT["yes"]
    if said is False:
        return False, SHIPS_TEXT["no"]
    if cc is None or cc in EU or service:
        return None, SHIPS_TEXT["unstated"]
    return None, SHIPS_TEXT["unconfirmed"]


def _result(cc: str | None, city: str | None, basis: str, text: str, confident: bool,
            ships: tuple[bool | None, str]) -> dict[str, Any]:
    return {"country_code": cc.upper() if cc else None, "country_name": NAMES.get(cc) if cc else None,
            "city": city if cc else None, "basis": basis if cc else "unknown",
            "basis_text": text if cc else "not stated", "confident": bool(confident and cc),
            "eu": (cc in EU) if cc else None, "ships_to_fi": ships[0], "ships_text": ships[1]}


# ------------------------------------------------------------------ API

def origin_for(offer: Any, flags: list[str] | None = None) -> dict[str, Any]:
    """Offer | offer dict -> the `origin` block (docs/UI_ROUND_A.md section 6). Pure, no network."""
    raw = _get(offer, "raw") or {}
    raw = raw if isinstance(raw, dict) else {}
    if flags is None:
        flags = list(_get(offer, "flags") or [])
    url, source = _get(offer, "url"), _get(offer, "source")
    host = _host(url, source)
    service = _get(offer, "condition") == "service"
    currency = str(_get(offer, "currency") or "").upper()

    def done(cc: str | None, city: str | None, basis: str, text: str, confident: bool) -> dict[str, Any]:
        return _result(cc, city, basis, text, confident, _ships(cc, raw, flags, service and cc is not None))

    # 1. the listing's location / a provider's service area
    cc, city = _place(_get(offer, "location"))
    if cc:
        if service:
            area = f"{city} region" if city else NAMES.get(cc, cc.upper())
            return done(cc, city, "service_area", f"from the provider's service area: {area}", True)
        return done(cc, city, "listing_location", "from the listing's location", True)

    # 2. the seller address the shop states on its page (JSON-LD)
    addr = raw.get("seller_address")
    if isinstance(addr, dict) and (cc := norm_country(addr.get("country"))):
        city = _clean_city(addr.get("locality"))
        return done(cc, city, "seller_address", "from the address the shop states on its page", True)

    cur = CURRENCY.get(currency)
    tcc, tld_end = _tld_cc(host) if host else (None, "")

    # 3. the marketplace
    if host:
        cc, sure, basis, text = _site_market(host)
        if cc:
            if basis == "known_shop" and cur and cur[0] == cc:
                text += f" and its prices in {cur[1]}"
            return done(cc, None, basis, text, sure)

    # 4. big shops on generic domains
    if host:
        base = next((host[i + 1:] for i in [-1] + [j for j, ch in enumerate(host) if ch == "."]
                     if host[i + 1:] in KNOWN_SHOPS), None)
        if base:
            cc = KNOWN_SHOPS[base]
            text = "a guess from what we know about this shop"
            if cur and cur[0] == cc:
                text += f" and its prices in {cur[1]}"
            return done(cc, None, "known_shop", text, False)

    # 5./6. ccTLD, currency, or both agreeing
    if tcc and cur and cur[0] == tcc:
        return done(tcc, None, "domain_currency", f"from the .{tld_end} domain and prices in {cur[1]}", False)
    if tcc:
        return done(tcc, None, "domain", f"from the .{tld_end} domain", False)
    if cur:
        return done(cur[0], None, "currency", f"from prices in {cur[1]}", False)
    return done(None, None, "unknown", "not stated", False)


def origin_from_payload(offer: dict[str, Any], flags: list[str] | None = None) -> dict[str, Any]:
    """A stream / recording `offer` payload (no raw) -> origin. Replays and agent cards use it."""
    return origin_for(offer if isinstance(offer, dict) else {}, flags)
