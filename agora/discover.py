"""DISCOVER: Need -> lanes -> query variants -> candidate shop URLs, as a live Event stream.
Written at Junction 2026.

Lanes follow `need.conditions` (new / refurbished / used / rental) plus a `service` lane when
is_service(need). Each lane gets 1-3 query variants: an English one with a country filter,
one in the local language, and (deep mode) one aimed at EU marketplaces.
HOME COUNTRY (env AGORA_COUNTRY, default "fi"): with no place in the query, the used lane still gets a
local-language variant filtered to the home country (tori.fi, huuto.net for fi), and home shops rank first. Results are deduped by
normalised URL, capped at 2 per domain, EU shops float to the top, and non-shop pages (guides,
news, Q&A, forums, video) are dropped with a `skip` event so the frontend can show the triage.

Events: lane {lane, queries} · source {url, domain, lane, title, query, snippet, eu, score} ·
        skip {url, reason} · error {where, message}
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agora import contextdev
from agora.models import Event, Need
from agora.need import is_service, priced_per_period
from agora.reader import LANE_WORDS, domain_of, lane_hint, remember_source

PER_DOMAIN = 2
RESULTS_PER_QUERY = 15        # one rate-limit token per search, whatever the size: ask for more

# --------------------------------------------------------------------------- geography

PLACES: dict[str, str] = {
    "finland": "fi", "suomi": "fi", "helsinki": "fi", "espoo": "fi", "vantaa": "fi", "tampere": "fi",
    "turku": "fi", "oulu": "fi", "germany": "de", "deutschland": "de", "berlin": "de", "munich": "de",
    "münchen": "de", "hamburg": "de", "sweden": "se", "sverige": "se", "stockholm": "se", "gothenburg": "se",
    "norway": "no", "oslo": "no", "denmark": "dk", "copenhagen": "dk", "estonia": "ee", "tallinn": "ee",
    "france": "fr", "paris": "fr", "netherlands": "nl", "amsterdam": "nl", "spain": "es", "madrid": "es",
    "barcelona": "es", "italy": "it", "rome": "it", "milan": "it", "austria": "at", "vienna": "at",
    "poland": "pl", "warsaw": "pl", "belgium": "be", "brussels": "be", "ireland": "ie", "dublin": "ie",
    "portugal": "pt", "lisbon": "pt", "uk": "gb", "london": "gb",
}
EU_TLDS = {"eu", "fi", "de", "se", "dk", "no", "ee", "lv", "lt", "fr", "nl", "be", "at", "ie", "pt", "es",
           "it", "pl", "cz", "sk", "si", "hu", "ro", "bg", "gr", "hr", "lu", "mt", "cy", "is", "ch", "uk"}
EU_SHOPS = ("amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.nl", "amazon.se", "amazon.pl",
            "backmarket.", "swappie.", "refurbed.", "ebay.de", "ebay.fr", "ebay.it", "ebay.co.uk",
            "verkkokauppa.com", "gigantti.fi", "power.fi", "jimms.fi", "proshop.", "foto-erhardt.",
            "calumetphoto.", "rebuy.", "mpb.com", "kamerastore.com", "zalando.", "ikea.com")
US_FIRST = ("walmart.com", "bestbuy.com", "target.com", "bhphotovideo.com", "adorama.com", "newegg.com",
            "amazon.com", "ebay.com", "costco.com", "kenmorecamera.com", "homedepot.com", "lowes.com")

# local wording per language: (buy/price, used, refurbished, rental, service-price)
LOCAL: dict[str, dict[str, str]] = {
    "fi": {"new": "hinta osta", "used": "käytetty myydään tori", "refurbished": "kunnostettu",
           "rental": "vuokraus hinta", "service": "hinta"},
    "de": {"new": "preis kaufen", "used": "gebraucht kaufen kleinanzeigen", "refurbished": "refurbished generalüberholt",
           "rental": "mieten preis", "service": "preis pro stunde"},
    "se": {"new": "pris köp", "used": "begagnad köpes blocket", "refurbished": "renoverad refurbished",
           "rental": "hyra pris", "service": "pris per timme"},
    "fr": {"new": "prix acheter", "used": "occasion leboncoin", "refurbished": "reconditionné",
           "rental": "location prix", "service": "tarif horaire"},
    "nl": {"new": "prijs kopen", "used": "tweedehands marktplaats", "refurbished": "refurbished",
           "rental": "huren prijs", "service": "prijs per uur"},
    "dk": {"new": "pris køb", "used": "brugt dba", "refurbished": "refurbished", "rental": "leje pris",
           "service": "pris pr time"},
    "no": {"new": "pris kjøp", "used": "brukt finn", "refurbished": "refurbished", "rental": "leie pris",
           "service": "pris per time"},
    "es": {"new": "precio comprar", "used": "segunda mano wallapop", "refurbished": "reacondicionado",
           "rental": "alquiler precio", "service": "precio por hora"},
    "it": {"new": "prezzo acquista", "used": "usato subito", "refurbished": "ricondizionato",
           "rental": "noleggio prezzo", "service": "prezzo all'ora"},
    "pl": {"new": "cena kup", "used": "używany olx", "refurbished": "odnowiony", "rental": "wynajem cena",
           "service": "cena za godzinę"},
    "pt": {"new": "preço comprar", "used": "usado olx", "refurbished": "recondicionado", "rental": "aluguer preço",
           "service": "preço por hora"},
    "cz": {"new": "cena koupit", "used": "bazar použitý", "refurbished": "repasovaný", "rental": "pronájem cena",
           "service": "cena za hodinu"},
}
# ISO 639-1 language (agora.places) -> LOCAL key
LANG_KEY = {"sv": "se", "da": "dk", "cs": "cz", "nb": "no", "nn": "no"}

# the job in the local language, for a service lane's local query (canonical name from need.SERVICE_WORDS)
SERVICE_LOCAL: dict[str, dict[str, str]] = {
    "cleaning": {"nl": "schoonmaker", "de": "Reinigungskraft Haushaltshilfe", "fi": "kotisiivous",
                 "se": "hemstädning", "dk": "rengøringshjælp", "no": "vaskehjelp", "fr": "femme de ménage",
                 "es": "limpieza del hogar", "it": "impresa di pulizie", "pl": "sprzątanie mieszkań",
                 "pt": "limpeza doméstica", "cz": "úklid domácnosti"},
    "plumbing": {"nl": "loodgieter", "de": "Klempner", "fi": "putkimies", "se": "rörmokare",
                 "dk": "vvs-installatør", "no": "rørlegger", "fr": "plombier", "es": "fontanero", "it": "idraulico",
                 "pl": "hydraulik", "pt": "canalizador", "cz": "instalatér"},
    "electrician": {"nl": "elektricien", "de": "Elektriker", "fi": "sähköasentaja", "se": "elektriker",
                    "dk": "elektriker", "no": "elektriker", "fr": "électricien", "es": "electricista",
                    "it": "elettricista", "pl": "elektryk", "pt": "eletricista", "cz": "elektrikář"},
    "moving": {"nl": "verhuisbedrijf", "de": "Umzugsunternehmen", "fi": "muuttofirma", "se": "flyttfirma",
               "dk": "flyttefirma", "no": "flyttebyrå", "fr": "déménageur", "es": "empresa de mudanzas",
               "it": "ditta traslochi", "pl": "firma przeprowadzkowa", "pt": "mudanças", "cz": "stěhování"},
    "painting": {"nl": "schilder", "de": "Maler", "fi": "maalari", "se": "målare", "dk": "maler", "no": "maler",
                 "fr": "peintre en bâtiment", "es": "pintor", "it": "imbianchino", "pl": "malarz", "pt": "pintor",
                 "cz": "malíř"},
    "handyman": {"nl": "klusjesman", "de": "Handwerker", "fi": "remonttimies", "se": "hantverkare",
                 "dk": "handyman", "no": "håndverker", "fr": "bricoleur", "es": "manitas", "it": "tuttofare",
                 "pl": "złota rączka", "pt": "faz-tudo", "cz": "hodinový manžel"},
    "haircut": {"nl": "kapper", "de": "Friseur", "fi": "parturi", "se": "frisör", "dk": "frisør", "no": "frisør",
                "fr": "coiffeur", "es": "peluquería", "it": "parrucchiere", "pl": "fryzjer", "pt": "cabeleireiro",
                "cz": "kadeřnictví"},
    "childcare": {"nl": "oppas", "de": "Babysitter", "fi": "lastenhoitaja", "se": "barnvakt", "dk": "babysitter",
                  "no": "barnevakt", "fr": "baby-sitter", "es": "canguro", "it": "babysitter", "pl": "opiekunka"},
    "gardening": {"nl": "hovenier", "de": "Gärtner", "fi": "puutarhuri", "se": "trädgårdsmästare",
                  "fr": "jardinier", "es": "jardinero", "it": "giardiniere", "pl": "ogrodnik"},
    "tutoring": {"nl": "bijles", "de": "Nachhilfe", "fi": "yksityisopetus", "se": "läxhjälp", "fr": "cours particuliers",
                 "es": "clases particulares", "it": "ripetizioni", "pl": "korepetycje"},
    "massage": {"nl": "massage", "de": "Massage", "fi": "hieronta", "se": "massage", "fr": "massage",
                "es": "masaje", "it": "massaggio", "pl": "masaż"},
}

# service marketplaces and directories per country: one search page there lists many providers
SERVICE_MARKETS: dict[str, tuple[str, ...]] = {
    "nl": ("werkspot.nl", "helpling.nl", "trustoo.nl", "homedeal.nl", "zoofy.nl", "offerteadviseur.nl"),
    "be": ("trustoo.be", "starofservice.be", "bobex.be", "helpling.be"),
    "de": ("helpling.de", "myhammer.de", "betreut.de", "blauarbeit.de", "aroundhome.de", "check24.de"),
    "at": ("helpling.at", "myhammer.at", "betreut.at", "herold.at"),
    "ch": ("helpling.ch", "batmaid.ch", "ofri.ch", "renovero.ch"),
    "fr": ("helpling.fr", "yoojo.fr", "starofservice.fr", "wecasa.fr", "pagesjaunes.fr"),
    "es": ("habitissimo.es", "cronoshare.com", "starofservice.es", "clintu.es"),
    "it": ("helpling.it", "prontopro.it", "instapro.it", "starofservice.it"),
    "pt": ("fixando.pt", "zaask.pt", "starofservice.pt"),
    "ie": ("helpling.ie", "bark.com", "tradesmen.ie"),
    "gb": ("bark.com", "checkatrade.com", "mybuilder.com", "ratedpeople.com"),
    "se": ("offerta.se", "servicefinder.se", "hemfrid.se"),
    "no": ("mittanbud.no", "finn.no"),
    "dk": ("3byggetilbud.dk", "happyhelper.dk", "helpling.dk"),
    "fi": ("tori.fi", "urakkamaailma.fi", "kotisiivousvertailu.fi"),
    "pl": ("oferteo.pl", "fixly.pl", "olx.pl"),
    "cz": ("nejremeslnici.cz", "poptavej.cz"),
}
def _registry_service_markets(per_country: int = 8) -> None:
    """Service platforms per country from the source registry (search-engine include_domains; no template needed)."""
    try:
        from agora import sources as _src
        recs = _src.load()
    except Exception:
        return
    for rec in recs:
        if "service" not in rec.get("lanes", []) or rec.get("kind") != "service":
            continue
        for cc in rec.get("countries", []):
            cur = SERVICE_MARKETS.get(cc, ())
            if cc != "eu" and rec["domain"] not in cur and len(cur) < per_country:
                SERVICE_MARKETS[cc] = cur + (rec["domain"],)


_registry_service_markets()
SERVICE_DIRECTORIES = tuple(sorted({d for ds in SERVICE_MARKETS.values() for d in ds}
                                   | {"yelp.", "treatwell.", "fresha.com", "booksy.com", "yoopies.", "yoojo.",
                                      "helpling.", "hulp.nl", "klusjebij.app", "care.com", "sittercity.com"}))
PROFILE_PATH = re.compile(r"/(?:profiel|profile|profil|pro|biz|bedrijf|company|firma|yritys|anbieter|handwerker|"
                          r"cleaner|schoonmaker)/[^/]+/?$", re.I)
# job boards and job ads: a cleaner's WAGE per hour is not what hiring one costs
JOB_DOMAINS = ("payscale.", "salaryexpert.", "gehalt.de", "erieri.com", "indeed.", "werkzoeken.nl", "nationalevacaturebank.nl", "monsterboard.", "jobbird.com", "stepstone.",
               "glassdoor.", "hups.nl", "staffyou.nl", "randstad.", "tempo-team.", "youngcapital.", "jobted.",
               "careerjet.", "arbeitsagentur.de", "stellenanzeigen.de", "jobware.de", "kimeta.de", "duunitori.fi",
               "monster.", "totaljobs.com", "reed.co.uk", "jooble.", "talent.com", "adzuna.", "jobs.ch",
               "jobat.be", "welcometothejungle.com", "werkenbij", "temper.works", "youbahn.", "studentjob.")
JOB_TITLE = re.compile(r"\b(?:vacatures?|vacanc(?:y|ies)|jobs?|stellenangebote?|stellenanzeigen?|työpaikat?|lediga jobb|"
                       r"offres? d'emploi|werken bij|work (?:at|as)|shifts?|uurloon|salary|salaris|stundenlohn|"
                       r"hourly pay|pay in|wages?|gehalt|verdienst|"
                       r"we are hiring)\b", re.I)
# in a snippet only the unmistakable ones: 'jobs' is also 'popular cleaning jobs', 'uurloon' what a private cleaner asks
JOB_SNIPPET = re.compile(r"\b(?:vacatures?|vacanc(?:y|ies)|stellenangebote?|bruto|gross (?:base|pay|wage)|salary|salaris|"
                         r"gehalt|tuntipalkka|verdien|earn up to)\b", re.I)


def job_ad(url: str, title: str = "", snippet: str = "") -> bool:
    """A job board or a job ad (the hourly figure is a wage, not a price)."""
    dom = domain_of(url)
    if any(dom_match(dom, d) or d in dom for d in JOB_DOMAINS):
        return True
    return bool(JOB_TITLE.search(title or "") or JOB_SNIPPET.search((snippet or "")[:600]))
DIRECTORY_TITLE = re.compile(
    r"\b(?:the\s+)?(?:best|top|beste|bästa|parhaat|meilleurs?|migliori|mejores)\s+\d+\b|\b\d+\s+(?:best|beste|top)\b|"
    r"\b\d+\s+(?:profielen|profiles|profile|anbieter|providers)\b", re.I)
# a provider's own price list: the page most likely to give a rate for one paid read
PRICE_PAGE_PATH = re.compile(r"/(?:[\w-]*-)?(?:preise?|preisliste|pricing|prices?|price-list|tarie?ven|tarifs?|prijzen|"
                             r"prijslijst|kosten|hinnasto|hinnat|priser|prislista|cennik|precios|prezzi|tarifas)"
                             r"(?:-[\w-]*)?(?:/|$|\.html?)", re.I)
PRICE_PAGE_TITLE = re.compile(r"\b(?:preise|preisliste|pricing|prices|price list|tarieven|prijzen|prijslijst|hinnasto|"
                              r"hinnat|priser|prislista|tarifs|cennik|precios|prezzi|kosten)\b", re.I)

ENGLISH = {
    "new": "{t} price buy online €",
    "used": "{t} used for sale",
    "refurbished": "{t} refurbished",
    "rental": "{t} rent per month",
    "service": "{t} price per hour {where}",
}
DEEP = {   # third variant: aim at the big EU marketplaces for that lane
    "new": "{t} best price EU shop",
    "used": "{t} used ebay.de OR kleinanzeigen OR tori.fi OR vinted",
    "refurbished": "{t} backmarket OR refurbed OR swappie OR rebuy",
    "rental": "{t} rent grover OR rental subscription",
    "service": "{t} {where} company quote price list",
}

# --------------------------------------------------------------------------- non-shop filter

JUNK_DOMAINS = ("alibaba.com", "youtube.com", "youtu.be", "reddit.com", "wikipedia.org", "quora.com",
                "pinterest.", "tiktok.com", "instagram.com", "x.com", "twitter.com", "medium.com",
                "dpreview.com", "rtings.com", "techradar.com", "theverge.com", "cnet.com", "tomsguide.com",
                "pcmag.com", "camelcamelcamel.com", "pricespy.", "hintaopas.fi", "idealo.", "pricerunner.",
                "linkedin.com", "stackexchange.com", "fandom.com", "imdb.com",
                # price trackers: they sell nothing (B2B wholesale lots are judged per listing in agora.resolve)
                "flipifyapp.com", "keepa.com", "pricecharting.com",
                # search-engine ad redirects
                "duckduckgo.com", "bing.com",
                # price comparison / trackers ('ab € 999' is not an offer)
                "geizhals.", "themacindex.com", "appleinsider.com", "webprice.eu", "prixretro.com",
                "kauppapaikat.net", "refurb.me", "hoteudeals.com", "billiger.de", "guenstiger.de", "kelkoo.",
                "hintaseuranta.fi", "vertaa.fi", "for-sale.co.uk", "for-sale.ie",
                # news, media and forums
                "apartmenttherapy.com", "gamesindustry.biz", "is.fi", "iltalehti.fi", "hs.fi", "yle.fi",
                "mtvuutiset.fi", "io-tech.fi", "boards.ie", "macobserver.com", "macrumors.com", "9to5mac.com",
                "nintendolife.com", "engadget.com", "goodhousekeeping.com", "sheknows.com", "slickdeals.net")
JUNK_PATH = re.compile(   # whole path segments
    r"/(blog|blogs|news|uutiset|article|articles|artikel|guide|guides|opas|review|reviews|forum|forums|"
    r"community|question|questions|answers|wiki|help|support|manual|manuals|compare|comparison|"
    r"press|magazine|lehti|tag|tags|wholesale|b2b|price-tracker|price-history|"
    r"threads?|discussions?|topics?|digitoday|fb-answers|posts|groups)(/|$)"
    r"|/t/[^/]+/\d+|/art-\d+", re.I)
JUNK_URL = re.compile(r"/y\.js\b|[?&]ad_domain=|/aclk\?|/pagead/", re.I)   # ad click redirects
JUNK_SLUG = re.compile(r"/(review|reviews|how-to|howto|guide|best|top-\d+|vs)-|-vs-|-review(/|$|\.html)", re.I)
JUNK_TITLE = re.compile(
    r"\b(review|reviewed|vs\.?|versus|how to|guide|best \w+ (of|in) 20\d\d|top \d+|(?:the )?best \d+|news|price history|"
    r"specs and price|announced|rumou?rs?|forum|q&a|what you should pay|arvostelu|testi|"
    r"is on sale|on sale for|price drops?|price cut|deal alert|drops? (?:its |the )?price)\b", re.I)


def dom_match(dom: str, pattern: str) -> bool:
    """'ebay.' matches any ebay TLD; 'reddit.com' matches reddit.com and its subdomains."""
    if pattern.endswith("."):
        return dom.startswith(pattern) or ("." + pattern) in dom
    return dom == pattern or dom.endswith("." + pattern)


API_EXCLUDE = [d for d in JUNK_DOMAINS if not d.endswith(".")][:20]


def is_non_shop(url: str, title: str = "") -> str | None:
    """Reason string when the page is clearly not a place to buy, else None."""
    u = url.lower()
    dom = domain_of(url)
    if any(dom_match(dom, d) for d in JUNK_DOMAINS):
        return f"not a shop ({dom})"
    if JUNK_URL.search(u):
        return "ad redirect"
    if dom_match(dom, "facebook.com") and "/marketplace/" not in u:
        return "social post, not a listing"
    if u.split("?")[0].endswith(".pdf"):
        return "pdf"
    path = urlsplit(u).path
    if JUNK_PATH.search(path) or JUNK_SLUG.search(path):
        return "guide/news/forum page"
    if title and JUNK_TITLE.search(title):
        return "review/guide title"
    return None


TRACKING = re.compile(r"^(utm_|gclid$|fbclid$|msclkid$|ref$|ref_$|srsltid$|_ga$|mc_|spm$|campaign)", re.I)


def normalize_url(url: str) -> str:
    """Lower host, drop www, tracking params, fragment and trailing slash. Used as the dedupe key."""
    s = urlsplit(url.strip())
    host = s.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    query = urlencode(sorted((k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not TRACKING.match(k)))
    path = s.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def tld(domain: str) -> str:
    return domain.rsplit(".", 1)[-1]


def is_eu(domain: str) -> bool:
    return tld(domain) in EU_TLDS or any(dom_match(domain, s) for s in EU_SHOPS)


def eu_score(domain: str, country: str | None, relevance: str | None = None) -> float:
    """Ranking inside one query's results: home country > EU > rest > US-only big boxes."""
    s = {"high": 1.0, "medium": 0.5, "low": 0.0}.get(relevance or "", 0.3)
    if country and (tld(domain) == country or (country == "gb" and domain.endswith(".uk"))):
        s += 3
    if is_eu(domain):
        s += 2
    if any(dom_match(domain, d) for d in US_FIRST):
        s -= 1
    return s


# --------------------------------------------------------------------------- lanes + queries

def country_of(need: Need) -> str | None:
    """Country code of need.where: the European gazetteer (agora.places) first, then the old short list."""
    if not need.where:
        return None
    from agora import places
    if cc := places.country_for(need.where):
        return cc
    w = need.where.lower().strip()
    for place, cc in PLACES.items():
        if place in w:
            return cc
    return None


def lang_of(need: Need, cc: str | None = None) -> str | None:
    """LOCAL key of the asked-for place's language ('nl' for Tilburg, 'fr' for Geneva), None = English."""
    from agora import places
    cc = cc or country_of(need)
    if cc is None:
        return None
    iso = places.language_for(need.where, cc)
    key = LANG_KEY.get(iso or "", iso)
    return key if key in LOCAL else None


DEFAULT_HOME = "fi"


def home_country() -> str | None:
    """The user's home market: AGORA_COUNTRY ('fi', 'FI', 'Finland', 'uk' ...), default 'fi'.
    'none' / 'off' / '' = no home country."""
    raw = os.environ.get("AGORA_COUNTRY", DEFAULT_HOME)
    if raw.strip().lower() in ("", "none", "off", "-"):
        return None
    return contextdev.normalize_country(raw)


def _lang(cc: str | None) -> str | None:
    from agora import places
    if not cc:
        return None
    iso = places.LANGUAGE.get(cc, cc)
    key = LANG_KEY.get(iso or "", iso)
    return key if key in LOCAL else None


def service_name(need: Need) -> str | None:
    """Canonical service ('cleaning', 'plumbing' ...) of a service need, from its words."""
    try:
        from agora.need import detect_service
    except ImportError:
        return None
    for text in (need.thing, need.raw, " ".join(need.must_have)):
        name, _ = detect_service(text or "")
        if name:
            return name
    return None


def local_service_query(need: Need, lang: str) -> str:
    """'home cleaning' in Tilburg -> 'schoonmaker Tilburg prijs per uur'."""
    thing_q = _thing_q(need)
    svc = service_name(need)
    words = SERVICE_LOCAL.get(svc or "", {}).get(lang) or thing_q
    return re.sub(r"\s+", " ", f"{words} {need.where or ''} {LOCAL[lang]['service']}").strip()


def _thing_q(need: Need) -> str:
    """sizes are for pricing the job, not for finding providers: 'home cleaning 60m2' -> 'home cleaning'"""
    thing = need.thing.strip()
    return re.sub(r"\b\d+(?:[.,]\d+)?\s?(?:m2|m²|sqm|neliö\w*)\b", "", thing, flags=re.I).strip() or thing


def service_market_query(need: Need, cc: str | None) -> tuple[str, str | None, list[str]] | None:
    """One search inside the country's service marketplaces (werkspot, helpling, myhammer ...): their city
    pages list many providers, each read as its own offer. None when the country has none we know."""
    domains = SERVICE_MARKETS.get(cc or "")
    if not domains:
        return None
    lang = lang_of(need, cc)
    words = SERVICE_LOCAL.get(service_name(need) or "", {}).get(lang or "") or _thing_q(need)
    q = re.sub(r"\s+", " ", f"{words} {need.where or ''}").strip()
    return q, cc, list(domains)


def is_service_directory(url: str, title: str = "") -> bool:
    """A page listing many service providers: a known marketplace / directory, a search page, or a
    'The best 10 cleaners in Tilburg' title."""
    dom = domain_of(url)
    if PROFILE_PATH.search(urlsplit(url).path):
        return False                  # one provider's profile: read it as one provider
    if any(dom_match(dom, d) for d in SERVICE_DIRECTORIES):
        return True
    if is_marketplace(dom):          # a product marketplace's search page (kleinanzeigen /s-...) is not one
        return False
    return is_list_page(url) or bool(title and DIRECTORY_TITLE.search(title))


SERVICE_RATE = re.compile(
    r"(?:€|eur\b|\$|£|kr\b|sek\b|nok\b|dkk\b|zł|chf\b)\s?\d[\d.,]*|\d[\d.,]*\s?(?:€|eur\b|euro\b|kr\b|zł|chf\b)", re.I)
RATE_UNIT = re.compile(
    r"^\W{0,8}(?:per\s+|pro\s+|par\s+|por\s+|all'|a\s+|an\s+|in\s+|/\s?)?(hour|hr|h|uur|u|stunde|std|tunti|h\.|"
    r"timme|time|heure|hora|ora|godz\w*|hodin\w*|m2|m²|sqm|job|visit|klus|einsatz|kerta)\b", re.I)


def snippet_rate(text: str) -> bool:
    """A price with a unit ('€29 per hour', '25 €/uur', 'ab 35 € pro Stunde') in a search snippet."""
    return any(RATE_UNIT.search(text[m.end():m.end() + 24]) for m in SERVICE_RATE.finditer(text or ""))


def expected_yield(url: str, kind: str, lane: str, title: str = "", snippet: str = "") -> float:
    """How many offers reading this page should give, roughly: the order to read pages in when a search
    returns more than the hunt can read. A service directory lists many providers; a page whose snippet
    shows a rate will price; a guide or a quote form usually will not."""
    if kind in ("service", "digital"):
        if is_service_directory(url, title):
            from agora.domainstats import list_yield
            seen = list_yield(domain_of(url))
            return 0.4 if seen is not None and seen < 1 else 2.5     # learned: lists providers without prices
        if snippet_rate(snippet) or PRICE_PAGE_PATH.search(urlsplit(url).path) or PRICE_PAGE_TITLE.search(title or ""):
            return 3.0           # a stated rate or the provider's own price list
        return 1.0 if SERVICE_RATE.search(snippet or "") else 0.5
    if kind == "product" and _direct_site(url) is not None:
        return 3.0               # a known marketplace / shop search page: ~20 listings cut by code (1 token)
    if is_list_page(url):
        if is_marketplace(domain_of(url)):
            return 3.0           # tori / kleinanzeigen search page: up to 8 listings (tori's free via ItemList)
        return 0.8 if lane in ("used", "refurbished") else 0.3
    return 1.0


def paid_priority(url: str, kind: str, lane: str, title: str = "", snippet: str = "") -> int:
    """Order of the paid Context.dev reads (lower first): the reads that yield the most offers per token.
    Services: price lists / stated rates, then directories, then the rest."""
    y = expected_yield(url, kind, lane, title, snippet)
    return 0 if y >= 3 else (1 if y >= 2 else (2 if y >= 1 else 3))


def lanes_for(need: Need) -> list[str]:
    lanes: list[str] = []
    if is_service(need):
        lanes.append("service")
        if "rental" in need.conditions:
            lanes.append("rental")
        return lanes
    for c in need.conditions:
        if c in ("new", "refurbished", "used", "rental") and c not in lanes:
            lanes.append(c)
    if "refurbished" in lanes and len(lanes) > 1 and NO_REFURB.search(f"{need.thing} {need.raw}"):
        lanes.remove("refurbished")      # nobody refurbishes a shelf: the query would only find DIY 'hacks'
    return lanes or ["new"]


# things with no refurbished trade (furniture, clothes, books): the refurbished lane is a wasted search
NO_REFURB = re.compile(
    r"\b(shelf|shelves|shelving|hylly\w*|kallax|billy|sofa|couch|sohva|table|pöytä|chair|tuoli|desk|bed|sänky|"
    r"wardrobe|dresser|lipasto|cabinet|kaappi|rug|matto|curtains?|jacket|takki|coat|shoes|kengät|dress|"
    r"shirt|jeans|book|kirja|stroller|rattaat)\b", re.I)


def query_plan(need: Need, lane: str, depth: int = 2) -> list[tuple[str, str | None]]:
    """1-3 (query, country filter) variants for one lane. depth: 1 = English only, 2 = + local language,
    3 = + EU marketplaces. The first variant is filtered to the asked-for country; with no place in the
    query, the used lane's local-language variant is filtered to the HOME country instead."""
    thing = need.thing.strip()
    # sizes are for pricing the job, not for finding providers: "home cleaning 60m2" -> "home cleaning"
    thing_q = re.sub(r"\b\d+(?:[.,]\d+)?\s?(?:m2|m²|sqm|neliö\w*)\b", "", thing, flags=re.I).strip() or thing
    where = need.where or ""
    cc = country_of(need)
    home = home_country() if cc is None else None
    out: list[tuple[str, str | None]] = [(ENGLISH[lane].format(t=thing_q, where=where), cc)]
    lang = _lang(cc)
    if depth >= 2 and lane == "service" and lang_of(need, cc):
        out.append((local_service_query(need, lang_of(need, cc)), cc))    # 'schoonmaker Tilburg prijs per uur'
    elif depth >= 2 and lang in LOCAL:
        out.append((f"{thing_q} {LOCAL[lang][lane]} {where if lane == 'service' else ''}", None))
    elif depth >= 2 and lane == "used" and _lang(home) in LOCAL:
        out.append((f"{thing_q} {LOCAL[_lang(home)][lane]}", home))      # tori.fi & co, even without a city
    elif depth >= 2 and lane != "service":
        out.append((f"{thing_q} {lane if lane != 'new' else 'buy'} Europe €", None))
    if depth >= 3:
        out.append((DEEP[lane].format(t=thing_q, where=where), None))
    seen: list[tuple[str, str | None]] = []
    for q, c in out:
        q = re.sub(r"\s+", " ", q).strip()
        if q not in [x for x, _ in seen]:
            seen.append((q, c))
    return seen[:3]


def queries_for(need: Need, lane: str, depth: int = 2) -> list[str]:
    """1-3 query variants for one lane (see query_plan for the country filter of each)."""
    return [q for q, _ in query_plan(need, lane, depth)]


# --------------------------------------------------------------------------- lean (live) plan
# Context.dev allows 10 requests a minute for the whole account, and a hunt lasts ~20 s: about 13 tokens.
# Every search spends one, so a live hunt asks ONE query per lane and keeps the rest for reading pages.

EXTRA_USED_MIN_TOKENS = 9.0   # a 2nd used query (EU marketplaces) only when the bucket can afford it
LOCAL_NEW_MIN_TOKENS = 6.0    # a local-language shop query for the new lane (home or asked-for country)
MARKET_MIN_TOKENS = 3.0       # a service search inside the country's service marketplaces
EU_USED = "{t} used kleinanzeigen OR vinted OR ebay.de OR blocket"


def tokens_available() -> float:
    """Tokens in the shared Context.dev bucket right now (a peek: nothing is taken). Offline = full."""
    full = float(getattr(contextdev, "BUCKET_SIZE", 10))
    if contextdev.offline():
        return full
    try:
        import json
        s = json.loads((contextdev.cache_root() / "contextdev_bucket.json").read_text())
        rate = float(getattr(contextdev, "RATE_PER_MIN", 10)) / 60.0
        return min(full, float(s.get("tokens", full)) + max(0.0, time.time() - float(s.get("ts", time.time()))) * rate)
    except (OSError, ValueError, TypeError, AttributeError):
        return full


PERIOD_LOCAL = {"fi": "hinnasto kuukausi", "de": "Preise pro Monat", "se": "pris per månad", "nl": "prijzen per maand",
                "fr": "tarifs par mois", "dk": "priser pr måned", "no": "priser per måned", "es": "precios al mes",
                "it": "prezzi al mese", "pl": "cennik miesięcznie", "pt": "preços por mês", "cz": "ceník měsíčně"}


def period_plan(need: Need, cc: str | None) -> list[tuple[str, str | None]]:
    """A subscription / retainer / B2B service (need.priced_per_period): providers' pricing pages, not a
    rate per hour and not the local trades' service marketplaces (tori.fi lists no bookkeepers' plans).
    English first; the asked-for country's language second (its own providers are what the person wants)."""
    thing_q = _thing_q(need)
    where = need.where or ""
    out = [(re.sub(r"\s+", " ", f"{thing_q} pricing plans {where}").strip(), cc)]
    lang = lang_of(need, cc)
    if lang in PERIOD_LOCAL:
        out.append((re.sub(r"\s+", " ", f"{thing_q} {where} {PERIOD_LOCAL[lang]}").strip(), cc))
    return out


def lean_plan(need: Need, lane: str, tokens: float | None = None) -> list[tuple[str, str | None]]:
    """The live plan: one (query, country filter) per lane.
    new = the English buy query (asked-for country); refurbished = open to all of Europe (backmarket, refurbed,
    swappie sell across borders); used = the local-language marketplace query (tori.fi for a Finn with no city
    asked, kleinanzeigen for Berlin), plus one EU-marketplace query when the bucket has tokens to spare;
    service = English + local (a service hunt has only that lane)."""
    cc = country_of(need)
    avail = tokens if tokens is not None else tokens_available()
    if lane == "service" and priced_per_period(need):
        return period_plan(need, cc)
    if lane == "service":
        out_s: list[Any] = list(query_plan(need, lane, 2)[:2])
        market = service_market_query(need, cc)
        if market is not None and avail >= MARKET_MIN_TOKENS:
            out_s.append(market)          # (query, country, include_domains)
        return out_s
    thing_q = _thing_q(need)
    if lane == "refurbished":
        return [(ENGLISH[lane].format(t=thing_q, where=""), None)]
    if lane == "new":
        plan = query_plan(need, lane, 1)
        local = cc or home_country()
        lang = _lang(local)
        if lang in LOCAL and avail >= LOCAL_NEW_MIN_TOKENS:
            # the local shops (verkkokauppa, gigantti, bol.com ...) mostly carry JSON-LD: free offers
            plan.append((re.sub(r"\s+", " ", f"{thing_q} {LOCAL[lang]['new']}").strip(), local))
        return plan
    if lane != "used":
        return query_plan(need, lane, 1)
    home = home_country() if cc is None else None
    lang = _lang(cc) if cc else _lang(home)
    out: list[tuple[str, str | None]] = []
    if lang in LOCAL:
        out.append((re.sub(r"\s+", " ", f"{thing_q} {LOCAL[lang]['used']}").strip(), cc or home))
    else:
        out.append((ENGLISH["used"].format(t=thing_q, where=""), cc))
    if avail >= EXTRA_USED_MIN_TOKENS:
        out.append((EU_USED.format(t=thing_q), None))
    return out


# --------------------------------------------------------------------------- the stream

async def _run_query(lane: str, query: str, country: str | None, highlights: bool,
                     include: list[str] | None = None) -> tuple[str, str, list[dict[str, Any]] | Exception]:
    try:
        kw: dict[str, Any] = {"include_domains": include} if include else {"exclude_domains": API_EXCLUDE}
        res = await contextdev.search(query, n=RESULTS_PER_QUERY, highlights=highlights, country=country, **kw)
        return lane, query, res
    except Exception as e:  # one bad query must not kill the hunt
        return lane, query, e


LIST_PAGE = re.compile(
    r"/(s|sch|search|haku|suche|b|kp|category|categories|collections|browse|list|l|cat|clp)(/|$|\?)"
    r"|/c/(?!product/)|searchpage\.jsp|/s-[^/?]+(?:/[^/?]+)*/k0"       # bestbuy, kleinanzeigen /s-<q>/k0
    r"|[?&](k|q|_nkw|query|search)=",
    re.I)
SETTLE_S = 6.0      # wait this long for all searches, then rank globally; later results stream as they land


def is_list_page(url: str) -> bool:
    """Search results / category pages: many items, slow and costly to read, so they rank last."""
    parts = urlsplit(url)
    if "/products/" in parts.path.lower() and not parts.query:
        return False            # shopify: /collections/<c>/products/<item> is one item
    return bool(LIST_PAGE.search(parts.path + ("?" + parts.query if parts.query else "")))


def title_gate(need: Need, title: str) -> str | None:
    """Free pre-read check on the search title: a different model or an accessory is never read
    (a paid read would just be thrown away by resolve). Services and vague titles pass."""
    if is_service(need) or not title:
        return None
    try:
        from agora import resolve
        from agora.models import Offer
    except ImportError:
        return None
    r, why = resolve.explain(need, Offer(url="", source="", title=title, price=None, currency=None))
    if why and (why.startswith("different model") or why.startswith("accessory")) and r < 0.3:
        return why
    return None


def rank_score(url: str, dom: str, cc: str | None, relevance: str | None) -> float:
    return eu_score(dom, cc, relevance) + (-1.5 if is_list_page(url) else 0.5)


MARKETPLACES = ("tori.fi", "kleinanzeigen.", "vinted.", "blocket.se", "finn.no", "dba.dk", "olx.", "huuto.net",
                "willhaben.at", "marktplaats.nl", "leboncoin.fr", "subito.it", "wallapop.com", "gumtree.",
                "ebay.", "tradera.com", "jofogas.hu", "bazos.")
MARKETPLACE_ITEMS = 4      # item pages per marketplace (each listing is its own seller, not one shop twice)
LIST_PER_DOMAIN = 1        # search / category pages per domain


def is_marketplace(dom: str) -> bool:
    """A marketplace of many sellers: the list above, or a classifieds site on Robert's (rpaszekdev) list of
    193 European second-hand sources (agora.marketplaces.SECOND_HAND)."""
    if any(dom_match(dom, m) for m in MARKETPLACES):
        return True
    from agora import marketplaces
    sh = marketplaces.second_hand(dom)
    return sh is not None and sh[1] == "classifieds"


def _second_hand(dom: str) -> bool:
    from agora import marketplaces
    return marketplaces.second_hand(dom) is not None


def _direct_site(url: str) -> Any:
    from agora import marketplaces
    if not direct_enabled():
        return None
    s = marketplaces.site_for(url)
    return s if s is not None and s.lane != "comparison" else None


def direct_enabled() -> bool:
    """AGORA_DIRECT=0 turns the direct marketplace pages off (default on)."""
    return os.environ.get("AGORA_DIRECT", "1").strip().lower() not in ("0", "off", "false", "no")


def plan_direct(need: Need, lanes: list[str], tokens: float, n_searches: int, pages: int = 1) -> dict[str, list[Any]]:
    """lane -> [marketplaces.Direct]: the marketplaces' own search pages, read without a web search. Used lane
    first (its pages yield the most), then refurbished, then new; a paid page only while the bucket has
    tokens left after the planned searches (agora.marketplaces.direct_pages)."""
    from agora import marketplaces
    if need.kind != "product" or not direct_enabled():
        return {}
    cc = country_of(need)
    home = home_country() if cc is None else None
    left = tokens - n_searches
    out: dict[str, list[Any]] = {}
    for lane in ("used", "refurbished", "new"):
        if lane not in lanes:
            continue
        got = marketplaces.direct_pages(_thing_q(need), lane, cc, home, left, pages=pages)
        left -= sum(1 for d in got if d.paid)
        if got:
            out[lane] = got
    return out


EU_USED_SITES = ("kleinanzeigen", "vinted")


def _listicle(url: str, title: str) -> bool:
    try:
        from agora import longtail
        return longtail.is_listicle(url, title)
    except Exception:
        return False


def _note_listicle(url: str, title: str, snippet: str) -> None:
    """Hand a skipped 'best X / alternatives' page to the long-tail lane (agora.longtail), when a hunt collects
    them. Never fatal: the long tail is optional."""
    try:
        from agora import longtail
        longtail.note_listicle(url, title, snippet)
    except Exception:
        pass


async def discover(need: Need, *, depth: int | None = None, max_sources: int = 40,
                   settle_s: float = SETTLE_S, tokens: float | None = None, pages: int = 1) -> AsyncIterator[Event]:
    """Need -> stream of lane / source / skip / error Events. Searches run concurrently (the shared
    rate limiter in contextdev paces them). Results are pooled for up to `settle_s`, then sources
    are emitted round-robin across lanes, best first (home country > EU > product page > list page),
    so a small `max_sources` still covers new, refurbished and used. Until every search has landed a
    lane gets at most its fair share of `max_sources`, so a fast new-shop search cannot fill the hunt
    before the used marketplaces answer.

    depth: None = the lean live plan (one query per lane, see lean_plan); 1-3 = query_plan variants.
    pages: 'Compare more' (hunt depth 2-3): results pages 2..pages+1 of the paid marketplaces while tokens allow."""
    t0 = time.monotonic()

    def ev(type_: str, **data: Any) -> Event:
        return Event(type_, data, int((time.monotonic() - t0) * 1000))

    cc = country_of(need)
    home = home_country()
    rank_cc = cc or home          # no place asked: the home market's shops float up
    plan: list[tuple[str, str, str | None, list[str] | None]] = []
    lanes = lanes_for(need)
    if depth is None and tokens is None:
        tokens = tokens_available()
    plans = {lane: (lean_plan(need, lane, tokens) if depth is None else query_plan(need, lane, depth))
             for lane in lanes}

    def eu_used(x: tuple[Any, ...]) -> bool:
        return x[0] == re.sub(r"\s+", " ", EU_USED.format(t=_thing_q(need))).strip()
    n_search = sum(1 for lane, qp in plans.items() for x in qp if not (lane == "used" and eu_used(x)))
    # the marketplaces' own search pages (no web search spent): lean live plan only
    directs = plan_direct(need, lanes, float(tokens or 0), n_search, pages) if depth is None else {}
    if any(d.site.key.split("_")[0] in EU_USED_SITES for d in directs.get("used", [])):
        plans["used"] = [x for x in plans["used"] if not eu_used(x)]   # read them directly instead
    if need.kind == "product" and depth is None and direct_enabled():
        from agora import marketplaces
        planned = [d for ds in directs.values() for d in ds]
        for d in planned:
            if d.extra:
                marketplaces.EXTRA_PAGES.add(d.url)
        # why the hunt looks where it looks (bulky: near you first; small: the big EU marketplaces too)
        yield ev("scope", **marketplaces.scope_for(_thing_q(need), cc, home if cc is None else None,
                                                   eu_included=any(d.site.country != (cc or home)
                                                                   for d in planned)))
    for lane in lanes:
        qp = plans[lane]
        extra: dict[str, Any] = {}
        if cc is None and (any(x[1] for x in qp) or directs.get(lane)):
            extra["home_country"] = home
        if any(len(x) > 2 for x in qp):
            extra["sites"] = [d for x in qp if len(x) > 2 for d in x[2]]
        if directs.get(lane):
            extra["direct"] = [{"site": d.site.key, "domain": d.site.domain, "url": d.url, "query": d.query,
                                "paid": d.paid, "page": d.page, "extra": d.extra} for d in directs[lane]]
        yield ev("lane", lane=lane, queries=[x[0] for x in qp], country=cc, **extra)
        for q, c, *rest in qp:
            # the first variant is filtered to the asked-for country, local used to home, the rest open;
            # a service marketplace query searches only those sites
            plan.append((lane, q, c, rest[0] if rest else None))

    seen: set[str] = set()
    pooled_in: dict[str, str] = {}      # url key -> lane, for candidates found but not emitted yet
    items: dict[str, int] = {}          # domain -> item pages emitted
    lists: dict[str, int] = {}          # domain -> list pages emitted
    item_domains: set[str] = set()      # marketplaces with at least one item page found
    per_lane: dict[str, int] = {lane: 0 for lane in lanes}
    share = max(1, -(-max_sources // max(1, len(lanes))))
    pool: dict[str, list[tuple[float, int, dict[str, Any], str]]] = {lane: [] for lane in lanes}

    def fit(lane: str, title: str) -> tuple[int, int]:
        """Which lane a page found by two lanes belongs to: the one its title speaks of, else the earlier lane
        (a local 'used' query often finds the same new-shop pages as the new lane)."""
        return (1 if lane in LANE_WORDS and lane_hint(lane, title) == lane else 0, -lanes.index(lane))
    emitted = 0
    order = 0
    # direct marketplace pages go out first (used lane first): no search to wait for, ~20 listings each
    for lane in directs:
        for d in directs[lane]:
            if emitted >= max_sources:
                break
            dom = d.site.domain
            seen.add(normalize_url(d.url))
            lists[dom] = lists.get(dom, 0) + 1
            per_lane[lane] += 1
            emitted += 1
            title = f"{dom} search: {d.query}" + (f" (page {d.page})" if d.page > 1 else "")
            remember_source(d.url, lane, title, "")
            yield ev("source", url=d.url, domain=dom, lane=lane, title=title, query=d.query, snippet="",
                     eu=True, score=9.0, list_page=True, direct=True, site=d.site.key, paid=d.paid,
                     page=d.page, extra=d.extra, country=d.site.country.upper())
    tasks = {asyncio.ensure_future(_run_query(lane, q, c, lane == "service", inc)) for lane, q, c, inc in plan}

    def _yield_of(r: dict[str, Any]) -> float:
        return expected_yield(r["url"], need.kind, "service", r.get("title") or "",
                              contextdev.highlight_text(r) or r.get("description") or "")

    def refuse(url: str, dom: str) -> str | None:
        """Why this page may not be emitted now (per-domain caps), else None."""
        if is_service(need) and any(dom_match(dom, d) for d in SERVICE_DIRECTORIES):
            if items.get(dom, 0) + lists.get(dom, 0) >= PER_DOMAIN:
                return f"already {PER_DOMAIN} pages from {dom}"
            return None
        if is_list_page(url):
            # a marketplace search page is kept even when item pages were found: it is up to 8 listings in one
            # read (free from tori's ItemList), an item page is one
            if lists.get(dom, 0) >= LIST_PER_DOMAIN:
                return f"already {LIST_PER_DOMAIN} search page from {dom}"
            if items.get(dom, 0) + lists.get(dom, 0) >= PER_DOMAIN:
                return f"already {PER_DOMAIN} pages from {dom}"
            return None
        cap = MARKETPLACE_ITEMS if is_marketplace(dom) else PER_DOMAIN
        if items.get(dom, 0) + lists.get(dom, 0) >= cap:
            return f"already {cap} pages from {dom}"
        return None

    def flush(final: bool) -> list[Event]:
        """Round-robin over lanes, best candidate of each lane first (item pages before list pages).
        Not final (searches still running): each lane stops at its share of max_sources."""
        out: list[Event] = []
        for lane_, cands in pool.items():
            if lane_ == "service":     # stated rates / price lists first, then directories (many providers)
                cands.sort(key=lambda x: (-_yield_of(x[2]), -x[0], x[1]))
            elif lane_ in ("used", "refurbished"):   # a marketplace search page first: many listings in one read
                cands.sort(key=lambda x: (-expected_yield(x[2]["url"], need.kind, lane_), -x[0], x[1]))
            else:
                cands.sort(key=lambda x: (is_list_page(x[2]["url"]), -x[0], x[1]))
        for cap in ((share, max_sources) if final else (share,)):   # every lane's share first, then the rest
            out += _round_robin(cap)
        return out

    def _round_robin(cap: int) -> list[Event]:
        nonlocal emitted
        out: list[Event] = []
        progress = True
        while progress and emitted < max_sources:
            progress = False
            for lane in lanes:
                while pool[lane] and per_lane[lane] < cap and emitted < max_sources:
                    score, _, r, query = pool[lane].pop(0)
                    url = r["url"]
                    pooled_in.pop(normalize_url(url), None)
                    dom = domain_of(url)
                    why = refuse(url, dom)
                    if why:
                        out.append(ev("skip", url=url, reason=why, lane=lane))
                        continue
                    listy = is_list_page(url)
                    (lists if listy else items)[dom] = (lists if listy else items).get(dom, 0) + 1
                    per_lane[lane] += 1
                    emitted += 1
                    progress = True
                    title = r.get("title") or ""
                    snippet = contextdev.highlight_text(r) or r.get("description") or ""
                    remember_source(url, lane, title, snippet)
                    out.append(ev("source", url=url, domain=dom, lane=lane, title=title, query=query,
                                  snippet=snippet[:500], eu=is_eu(dom), score=round(score, 2),
                                  list_page=listy))
                    break
        return out

    settled = False
    try:
        pending = set(tasks)
        while pending:
            timeout = None if settled else max(0.0, settle_s - (time.monotonic() - t0))
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                lane, query, res = fut.result()
                if isinstance(res, Exception):
                    yield ev("error", where="discover", message=f"search '{query}': {str(res)[:160]}")
                    continue
                for r in res:
                    url = r.get("url") or ""
                    if not url.startswith("http"):
                        continue
                    key = normalize_url(url)
                    if key in seen:
                        old = pooled_in.get(key)
                        if old and old != lane and fit(lane, r.get("title") or "") > fit(old, r.get("title") or ""):
                            for i, cand in enumerate(pool[old]):
                                if normalize_url(cand[2]["url"]) == key:
                                    moved = pool[old].pop(i)
                                    pool[lane].append((moved[0], moved[1], moved[2], query))
                                    pooled_in[key] = lane
                                    break
                        continue
                    seen.add(key)
                    title = r.get("title") or ""
                    # 'The best 10 home cleaners in Tilburg' is a directory to a service hunt, not a listicle
                    directory = is_service(need) and is_service_directory(url, title) \
                        and not (priced_per_period(need) and _listicle(url, title))   # B2B: 'best X' = listicle
                    reason = is_non_shop(url, "" if directory else title) or title_gate(need, title)
                    if not reason and is_service(need) and job_ad(
                            url, title, contextdev.highlight_text(r) or r.get("description") or ""):
                        reason = "job ad (a wage, not a price)"
                    if reason:
                        if not directory:     # a 'best X' article: the long-tail lane mines it for providers
                            _note_listicle(url, title, contextdev.highlight_text(r) or r.get("description") or "")
                        yield ev("skip", url=url, reason=reason, lane=lane)
                        continue
                    order += 1
                    pooled_in[key] = lane
                    dom = domain_of(url)
                    if is_marketplace(dom) and not is_list_page(url):
                        item_domains.add(dom)
                    score = rank_score(url, dom, rank_cc, r.get("relevance"))
                    if lane in ("used", "refurbished") and _second_hand(dom):
                        score += 1.0     # Robert's curated second-hand sources (agora.marketplaces.SECOND_HAND)
                    pool[lane].append((score, order, r, query))
            if not pending or not done or settled:
                settled = True
                for e in flush(final=not pending):
                    yield e
    finally:
        for t in tasks:
            t.cancel()
