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
from agora.need import is_service, national_service, priced_per_period
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
    "gunsmith": {"fi": "aseseppä", "de": "Büchsenmacher", "nl": "wapensmid", "se": "vapensmed", "dk": "bøssemager",
                 "no": "børsemaker", "fr": "armurier", "es": "armero", "it": "armaiolo", "pl": "rusznikarz",
                 "pt": "armeiro", "cz": "puškař"},
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
                                      "helpling.", "hulp.nl", "klusjebij.app", "care.com", "sittercity.com",
                                      # review / matching directories: many providers, not one (eval r4: a
                                      # kennstdueinen.de cost section was priced as a Berlin plumber)
                                      "my-hammer.de", "kennstdueinen.de", "fragbabsi.de", "11880.com",
                                      "gelbeseiten.de", "werkenntdenbesten.de", "golocal.de", "trustlocal.",
                                      "trustoo.", "werkspot.nl", "starofservice."}))
# cost-of-living statistics: a crowd-sourced average, never a provider (eval r4: expatistan.com 'Hourly rate for
# cleaning help' was priced as an offer)
COST_STATS = ("expatistan.com", "numbeo.com", "livingcost.org", "costoflive.net", "budgetyourtrip.com",
              "salaryexplorer.com", "teleport.org")
PROFILE_PATH = re.compile(r"/(?:profiel|profile|profil|pro|biz|bedrijf|company|firma|yritys|anbieter|handwerker|"
                          r"cleaner|schoonmaker|urakoitsija|yritykset|palveluntarjoaja|tekija)/[^/]+/?$", re.I)
DIRECTORY_PROFILES = 5        # provider profiles read from one directory (each its own provider and price)
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
    r"/(blog|blogs|blogi|news|uutiset|article|articles|artikel|guide|guides|opas|review|reviews|forum|forums|"
    r"gallery|galleries|slideshow|"
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


ISO_OF_LOCAL = {"se": "sv", "dk": "da", "no": "nb", "cz": "cs"}


# a specific job inside a trade (agora.need.SPECIFIC_JOBS), in the local languages (LOCAL keys)
JOB_LOCAL: dict[str, dict[str, str]] = {
    "window cleaning": {"nl": "glazenwasser", "de": "Fensterputzer", "fi": "ikkunanpesu", "se": "fönsterputs",
                        "dk": "vinduespudser", "no": "vindusvask", "fr": "laveur de vitres",
                        "es": "limpieza de cristales", "it": "lavavetri", "pl": "mycie okien", "pt": "limpeza de vidros",
                        "cz": "mytí oken"},
    "carpet cleaning": {"nl": "tapijtreiniging", "de": "Teppichreinigung", "fi": "mattopesu", "se": "mattvätt",
                        "dk": "tæpperens", "fr": "nettoyage de tapis", "es": "limpieza de alfombras",
                        "it": "lavaggio tappeti", "pl": "pranie dywanów"},
    "gutter cleaning": {"nl": "dakgootreiniging", "de": "Dachrinnenreinigung", "fi": "rännien puhdistus",
                        "se": "takrännor rensning", "dk": "tagrenderens", "fr": "nettoyage de gouttières"},
    "upholstery cleaning": {"nl": "bankstel reinigen", "de": "Polsterreinigung", "fi": "sohvan pesu",
                            "se": "möbeltvätt", "fr": "nettoyage canapé"},
    "end of tenancy cleaning": {"nl": "eindschoonmaak", "de": "Endreinigung", "fi": "muuttosiivous",
                                "se": "flyttstädning", "dk": "fraflytningsrengøring", "fr": "ménage fin de bail"},
}


def _specific_job(need: Need) -> str | None:
    try:
        from agora.need import specific_job
    except ImportError:
        return None
    for text in (need.thing, need.raw):
        if job := specific_job(text or ""):
            return job
    return None


def local_words(need: Need, lang: str | None) -> str | None:
    """The job in the local language: the trade's word (SERVICE_LOCAL), else the category node's label in that
    language (a hunt from the tree: 'Gunsmith' -> 'aseseppä'), else None."""
    if not lang:
        return None
    if w := JOB_LOCAL.get(_specific_job(need) or "", {}).get(lang):
        return w                 # 'glazenwasser', never the trade's 'schoonmaker' (eval r4)
    svc = service_name(need)
    if w := SERVICE_LOCAL.get(svc or "", {}).get(lang):
        return w
    labels = (need.category or {}).get("labels") or {}
    return labels.get(ISO_OF_LOCAL.get(lang, lang)) or None


# how a trade states its price: catering per meal / person, a photographer per package, the rest per hour
UNIT_PER_PERSON = re.compile(r"\b(?:cater\w*|ateri\w*|ruokailu\w*|kouluruo\w*|meals?|lunch\w*|lounas\w*|"
                             r"buffet\w*|pitopalvelu\w*|food|ruoka\w*|mittagessen|essen|maaltijd\w*|måltid\w*)\b",
                             re.I)
UNIT_PACKAGE = re.compile(r"\b(?:photograph\w*|valokuva\w*|kuvaaja\w*|wedding|hää\w*|videograph\w*|dj|band|"
                          r"fotograf\w*|hochzeit\w*|bröllop\w*|bruiloft\w*)\b", re.I)
UNIT_PHRASE = {
    "person": {"en": "price per person", "fi": "hinta per henkilö", "de": "Preis pro Person", "se": "pris per person",
               "nl": "prijs per persoon", "dk": "pris pr person", "no": "pris per person", "fr": "prix par personne",
               "es": "precio por persona", "it": "prezzo a persona", "pl": "cena za osobę", "pt": "preço por pessoa",
               "cz": "cena za osobu"},
    # window / gutter / carpet cleaners price per window, per visit or per m², rarely per hour
    "job": {"en": "prices", "fi": "hinnasto", "de": "Preise", "se": "priser", "nl": "prijzen", "dk": "priser",
            "no": "priser", "fr": "tarifs", "es": "precios", "it": "prezzi", "pl": "cennik", "pt": "preços",
            "cz": "ceník"},
    "package": {"en": "prices packages", "fi": "hinnasto", "de": "Preise Pakete", "se": "priser paket",
                "nl": "prijzen pakketten", "dk": "priser pakker", "no": "priser pakker", "fr": "tarifs forfaits",
                "es": "precios paquetes", "it": "prezzi pacchetti", "pl": "cennik pakiety", "pt": "preços pacotes",
                "cz": "ceník balíčky"},
}


def service_unit(need: Need) -> str:
    """'person' (catering, meals), 'package' (photographers, weddings) or 'hour' (the trades)."""
    cat = need.category or {}
    hay = " ".join([need.thing or "", need.raw or "", str(cat.get("label") or ""), " ".join(cat.get("path") or []),
                    " ".join(str(v) for v in (cat.get("labels") or {}).values())])
    if UNIT_PER_PERSON.search(hay):
        return "person"
    if UNIT_PACKAGE.search(hay):
        return "package"
    if _specific_job(need) in ("window cleaning", "gutter cleaning", "carpet cleaning", "upholstery cleaning"):
        return "job"
    return "hour"


def price_words(need: Need, lang: str | None) -> str:
    """The 'price per ...' words of a service query in that language (None = English)."""
    unit = service_unit(need)
    if unit == "hour":
        return LOCAL[lang]["service"] if lang in LOCAL else "price per hour"
    return UNIT_PHRASE[unit].get(lang or "en", UNIT_PHRASE[unit]["en"])


def local_service_query(need: Need, lang: str) -> str:
    """'home cleaning' in Tilburg -> 'schoonmaker Tilburg prijs per uur'."""
    words = local_words(need, lang) or _thing_q(need)
    return re.sub(r"\s+", " ", f"{words} {need.where or ''} {price_words(need, lang)}").strip()


def category_sites(need: Need, cc: str | None) -> list[str]:
    """Where-to-look domains of the need's category node for its service lane: the node's own, and inherited
    ones of the searched country (tori.fi for Finland; never care.com for a gunsmith)."""
    cat = need.category or {}
    out: list[str] = []
    for d in cat.get("domains") or []:
        dom = str(d.get("domain") or "")
        if not dom or d.get("lane") not in ("service", None):
            continue
        if d.get("from") == cat.get("id") or (cc and tld(dom) == cc.lower()):
            if cat.get("intent") or market_fits(dom, need, cc):
                out.append(dom)     # a picked meaning's own where-to-look sites always; the rest when they fit
    return out


def _thing_q(need: Need) -> str:
    """sizes are for pricing the job, not for finding providers: 'home cleaning 60m2' -> 'home cleaning'"""
    thing = need.thing.strip()
    return re.sub(r"\b\d+(?:[.,]\d+)?\s?(?:m2|m²|sqm|neliö\w*)\b", "", thing, flags=re.I).strip() or thing


def service_market_query(need: Need, cc: str | None) -> tuple[str, str | None, list[str]] | None:
    """One search inside the country's service marketplaces (werkspot, helpling, myhammer ...): their city
    pages list many providers, each read as its own offer. None when the country has none we know."""
    domains = [d for d in SERVICE_MARKETS.get(cc or "", ()) if market_fits(d, need, cc)]
    domains += [d for d in category_sites(need, cc) if d not in domains]
    if not domains:
        return None
    lang = lang_of(need, cc) or (_lang(cc) if not need.where else None)
    words = local_words(need, lang) or _thing_q(need)
    q = re.sub(r"\s+", " ", f"{words} {need.where or ''}").strip()
    return q, cc, domains


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


COST_GUIDE = re.compile(
    r"\b(?:opas|oppaa\w*|mediaani\w*|keskihinta|mitä\s+[\w\s-]{0,30}maksa\w*|paljonko\s+[\w\s-]{0,30}maksa\w*|"
    r"hinta\s+20\d\d|20\d\d\s+hinta|how\s+much\s+(?:does|do|is)|cost\s+guide|average\s+cost|costs?\s+(?:in\s+)?20\d\d|"
    r"cost\s+per\s+hour\s+20\d\d|was\s+kostet|kosten\s+20\d\d|wat\s+kost|vad\s+kostar|price\s+guide|"
    r"hourly\s+rates?\s+(?:guide|20\d\d)|calculator|laskuri)\b", re.I)
COST_GUIDE_PATH = re.compile(r"/(?:costs?|cost-guide|hub|blogi?|artikkeli\w*|haablogi|opas)/|how-much|"
                             r"-cost(?:s)?(?:-|/|$)|average-|hinta-20\d\d|20\d\d-hinta|mita-\w+-maksaa", re.I)


def cost_guide(url: str, title: str = "") -> bool:
    """An article about what the work costs on average, not a provider's own price: read last."""
    if PRICE_PAGE_PATH.search(urlsplit(url).path) and not COST_GUIDE.search(title or ""):
        return False             # '/hinnasto' is a provider's own price list
    return bool(COST_GUIDE.search(title or "") or COST_GUIDE_PATH.search(urlsplit(url).path))


CALCULATOR = re.compile(r"\w*(?:laskuri|laskurit|rechner|calculator|kalkulator|r[aä]knare|beregner|kalkulačka)\b|"
                        r"\bvertailu\w*|\w+vertailu\b|\bvergleich\w*|\w+vergleich\b|\bcompar(?:e|ison|ateur)\b|"
                        r"\bj[aä]mf[oö]r\w*|\bvergelijk\w*|\bsammenlign\w*|\bkilpailut\w*", re.I)


def calculator(url: str, title: str = "") -> bool:
    """A price calculator or a comparison site ('Autovakuutuslaskuri', 'Vakuutusvertailu', 'Kfz-Vergleich'):
    it asks for your details and states no price of its own (eval r3: car insurance spent its reads and the
    insurers' per-domain cap on calculators, and the pick was a calculator's estimate)."""
    path = urlsplit(url).path.replace("-", " ").replace("/", " ")
    return bool(CALCULATOR.search(f"{domain_of(url).split('.')[0]} {path} {title or ''}"))


def snippet_rate(text: str) -> bool:
    """A price with a unit ('€29 per hour', '25 €/uur', 'ab 35 € pro Stunde') in a search snippet."""
    return any(RATE_UNIT.search(text[m.end():m.end() + 24]) for m in SERVICE_RATE.finditer(text or ""))


def expected_yield(url: str, kind: str, lane: str, title: str = "", snippet: str = "") -> float:
    """How many offers reading this page should give, roughly: the order to read pages in when a search
    returns more than the hunt can read. A service directory lists many providers; a page whose snippet
    shows a rate will price; a guide or a quote form usually will not."""
    if kind in ("service", "digital"):
        if cost_guide(url, title) or calculator(url, title):
            return 0.3           # 'Putkimiehen hinta 2026 - opas': an average, read only when budget is left
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
    if "refurbished" in lanes and len(lanes) > 1 and no_refurb(need):
        lanes.remove("refurbished")      # nobody refurbishes a shelf: the query would only find DIY 'hacks'
    return lanes or ["new"]


# things with no refurbished trade (furniture, clothes, books): the refurbished lane is a wasted search
NO_REFURB = re.compile(
    r"\b(shel(?:f|ves)|shelving|hylly\w*|kallax|billy|sofas?|couch(?:es)?|sohv\w*|tables?|pöytä|pöydät|chairs?|"
    r"tuol\w*|desks?|beds?|sänky|sängyt|wardrobes?|dressers?|lipasto\w*|cabinets?|kaappi|kaapit|rugs?|mat(?:to|ot)|"
    r"curtains?|jackets?|takki|takit|coats?|shoes|kengät|dress(?:es)?|shirts?|jeans|books?|kirja\w*|"
    r"strollers?|rattaat|prams?|kinderwagen)\b", re.I)
NO_REFURB_ROOTS = ("furniture", "apparel", "clothing", "books", "fashion")


def no_refurb(need: Need) -> bool:
    """No refurbished trade for this kind of thing: its words, or its category (a hunt from 'Sofas' typed
    nothing: eval r1 spent the budget on US refurbished sofa sites)."""
    if NO_REFURB.search(f"{need.thing} {need.raw}"):
        return True
    cat = need.category or {}
    root = str((cat.get("path_ids") or [""])[0]).lower()
    return any(root.startswith(r) for r in NO_REFURB_ROOTS) or bool(NO_REFURB.search(str(cat.get("label") or "")))


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
    first = ENGLISH[lane].format(t=thing_q, where=where)
    if lane == "service":
        first = f"{thing_q} {price_words(need, None)} {where}"
    out: list[tuple[str, str | None]] = [(first, cc)]
    lang = _lang(cc)
    if depth >= 2 and lane == "service" and lang_of(need, cc):
        out.append((local_service_query(need, lang_of(need, cc)), cc))    # 'schoonmaker Tilburg prijs per uur'
    elif depth >= 2 and lang in LOCAL:
        words = price_words(need, lang) if lane == "service" else LOCAL[lang][lane]
        out.append((f"{thing_q} {words} {where if lane == 'service' else ''}", None))
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


def intent_plan(need: Need, cc: str | None) -> list[Any] | None:
    """A meaning picked by agora.intent ('lunch' -> lunch places near you): its own queries verbatim (never
    'price per hour' for a lunch), English + the home language, then one search inside its where-to-look sites
    (lounaat.info, wolt.com ...). None when the need carries no picked meaning."""
    it = (need.category or {}).get("intent") or {}
    qs = it.get("queries") or {}
    if not qs:
        return None
    travel = bool(it.get("travel"))              # a trip is bought at home, in the home language
    home = home_country() if travel else (cc or home_country())
    cc = None if travel else cc
    lang = _lang(home) if home else None
    local = (qs.get(ISO_OF_LOCAL.get(lang or "", lang or "")) or [])[:1] if lang else []
    where = need.where if (need.where and not travel and it.get("local", is_service(need))) else ""
    if where:
        # a meaning picked for vague words is done where the person is (eval r2: 'lunch' searched 'lounas'
        # with no city and read Tampere and Lahti pages): the asked / home city goes into its queries
        local = [q if where.lower() in q.lower() else f"{q} {where}" for q in local]
    out: list[Any] = [(q if not where or where.lower() in q.lower() else f"{q} {where}", cc)
                      for q in (qs.get("en") or [])[:1]]
    out += [(q, home) for q in local]
    sites = [d for d in it.get("domains") or [] if "." in d][:8]
    if sites and out:
        out.append(((local or [out[0][0]])[0], home, sites))
    return out or None


def _typed_country(need: Need) -> str | None:
    """The country (LOCAL key) of the language the query is typed in, when its words tell (None = English)."""
    from agora.need import LANG_COUNTRY, query_language
    return LANG_COUNTRY.get(query_language(need.raw) or "")


def lean_plan(need: Need, lane: str, tokens: float | None = None) -> list[tuple[str, str | None]]:
    """The live plan: one (query, country filter) per lane.
    new = the English buy query (asked-for country); refurbished = open to all of Europe (backmarket, refurbed,
    swappie sell across borders); used = the local-language marketplace query (tori.fi for a Finn with no city
    asked, kleinanzeigen for Berlin), plus one EU-marketplace query when the bucket has tokens to spare;
    service = English + local (a service hunt has only that lane)."""
    cc = country_of(need)
    avail = tokens if tokens is not None else tokens_available()
    if lane == "service" and national_service(need) and (cc or home_country()):
        return national_plan(need, cc or home_country() or "")
    if lane == "service" and (picked := intent_plan(need, cc)):
        return picked
    if lane == "service" and priced_per_period(need):
        return period_plan(need, cc)
    if lane == "service":
        out_s: list[Any] = list(query_plan(need, lane, 2)[:2])
        home = home_country() if cc is None else None
        if cc is None and home and out_s and out_s[0][1] is None:
            # a local trade with no place asked is done near you: the English query searches the home country
            # too (eval r1: 'plumbing price per hour' unfiltered read angi / homeadvisor cost guides)
            out_s[0] = (out_s[0][0], home)
        if cc is None and home and (lang_h := _lang(home)) and len(out_s) < 2:
            # no place asked: the job in the home country's language, there ('aseseppä hinta' in Finland)
            words = local_words(need, lang_h)
            if words:
                out_s.append((re.sub(r"\s+", " ", f"{words} {price_words(need, lang_h)}").strip(), home))
        market = service_market_query(need, cc or home)
        if market is not None and avail >= MARKET_MIN_TOKENS:
            out_s.append(market)          # (query, country, include_domains)
        return out_s
    thing_q = _thing_q(need)
    if lane == "refurbished":
        return [(ENGLISH[lane].format(t=thing_q, where=""), None)]
    if lane == "new" and (gift := product_intent_plan(need, cc, avail)):
        return gift
    if lane == "new":
        plan = query_plan(need, lane, 1)
        local = cc or home_country()
        if (vehicle(need) or need_bulky(need)) and local:
            # a car is bought near you: the English query is filtered to that country too (eval r2: the open
            # 'volvo v70 price buy online' query read carfax, cars.com and edmunds); so is anything bulky (eval
            # r3: road bike / stroller / sofa / kitchen table read US shops while the Finnish ones timed out)
            plan = [(q, c or local) for q, c in plan]
        lang = _lang(local)
        if lang in LOCAL and avail >= LOCAL_NEW_MIN_TOKENS:
            # the local shops (verkkokauppa, gigantti, bol.com ...) mostly carry JSON-LD: free offers
            words = market_thing(need, lang)
            plan.append((re.sub(r"\s+", " ", f"{words} {LOCAL[lang]['new']}").strip(), local))
        return plan
    if lane != "used":
        return query_plan(need, lane, 1)
    home = home_country() if cc is None else None
    lang = _lang(cc) if cc else _lang(home)
    out: list[tuple[str, str | None]] = []
    if lang in LOCAL:
        words = market_thing(need, lang)
        used_w = VEHICLE_USED.get(lang, LOCAL[lang]["used"]) if vehicle(need) else LOCAL[lang]["used"]
        out.append((re.sub(r"\s+", " ", f"{words} {used_w}").strip(), cc or home))
        typed = _typed_country(need)
        if typed and typed != (cc or home) and typed in LOCAL and not cc:
            # typed in another country's language ('kinderwagen gebraucht' from Finland): its marketplaces too
            out.append((re.sub(r"\s+", " ", f"{thing_q} {LOCAL[typed]['used']}").strip(), typed))
    else:
        out.append((ENGLISH["used"].format(t=thing_q, where=""), cc))
    if avail >= EXTRA_USED_MIN_TOKENS and not vehicle(need):
        out.append((EU_USED.format(t=thing_q), None))
    return out


def product_intent_plan(need: Need, cc: str | None, avail: float) -> list[tuple[str, str | None]] | None:
    """A vague product meaning ('gift for mom' -> gift ideas): its own queries, the home language first, then
    the kinds of things given (jewellery, gift sets) while the bucket allows. None for any other need."""
    it = (need.category or {}).get("intent") or {}
    if need.kind != "product" or not it.get("vague") or not it.get("queries"):
        return None
    qs = it["queries"]
    home = cc or home_country()
    lang = _lang(home) if home else None
    local = list(qs.get(ISO_OF_LOCAL.get(lang or "", lang or "")) or []) if lang else []
    out: list[tuple[str, str | None]] = []
    if local:
        out.append((local[0], home))
    out += [(q, home) for q in (qs.get("en") or [])[:1]]     # bought here: never glamour.com galleries
    extra = 1 if avail >= LOCAL_NEW_MIN_TOKENS else 0
    extra += 1 if avail >= EXTRA_USED_MIN_TOKENS else 0
    out += [(q, home) for q in local[2:2 + extra]]
    return out or None


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
    r"|^/s-[^/?]+(?:/[^/?]+)*/(?:k0)?c\d+/?$"                         # kleinanzeigen category /s-handy-telekom/c173
    r"|[?&](k|q|_nkw|query|search)=",
    re.I)
SETTLE_S = 6.0      # wait this long for all searches, then rank globally; later results stream as they land


def is_list_page(url: str) -> bool:
    """Search results / category pages: many items, slow and costly to read, so they rank last."""
    parts = urlsplit(url)
    if "/products/" in parts.path.lower() and not parts.query:
        return False            # shopify: /collections/<c>/products/<item> is one item
    if _LIST_HINTS and normalize_url(url) in _LIST_HINTS:
        return True             # a used-car list found by its title ('VOLVO V70 vaihtoautot - 185 autoa')
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


_LOCALE_PATH = re.compile(r"^/([a-z]{2})(?:[-_]([a-z]{2}))?(?:/|$)", re.I)


def home_page(url: str, cc: str | None) -> bool:
    """This page sells in country `cc`: its TLD, a /fi/ or /fi-fi/ locale path on a global site, a known
    marketplace of that country, or a registry source that lists it."""
    if not cc:
        return True
    cc = cc.lower()
    dom = domain_of(url)
    if tld(dom) == cc or (cc == "gb" and dom.endswith(".uk")):
        return True
    m = _LOCALE_PATH.match(urlsplit(url).path)
    if m and cc in {(m.group(1) or "").lower(), (m.group(2) or "").lower()}:
        return True
    try:
        from agora import marketplaces
        site = marketplaces.site_for(url)
        if site is not None:
            return site.country == cc
        from agora import sources
        rec = sources.for_url(url)
        if rec is not None:
            return cc in [str(c).lower() for c in rec.get("countries") or []]
    except Exception:
        pass
    return False


# global shops with one store per country: a foreign store's page becomes the home store's
IKEA_LOCALE = {"fi": "fi/fi", "se": "se/sv", "de": "de/de", "nl": "nl/nl", "dk": "dk/da", "no": "no/no",
               "at": "at/de", "fr": "fr/fr", "es": "es/es", "it": "it/it", "pl": "pl/pl", "gb": "gb/en",
               "ie": "ie/en", "be": "be/nl", "ch": "ch/de", "pt": "pt/pt", "cz": "cz/cs", "ee": "ee/et"}
_IKEA_PATH = re.compile(r"^/([a-z]{2})/([a-z]{2})/(p/[^?#]+-s?\d{8}/?|cat/[^?#]*-[a-z]*\d{3,}/?|search/?)(.*)$",
                        re.I)


def localize(url: str, cc: str | None) -> str:
    """ikea.com/us/en/p/kivik-sofa-...-s69440510/ -> ikea.com/fi/fi/p/kivik-sofa-...-s69440510/ for a Finn
    (eval r1: the US store was read for a sofa). Product pages (the article number decides) and search pages
    only; anything else is returned unchanged."""
    if not cc or cc.lower() not in IKEA_LOCALE or not dom_match(domain_of(url), "ikea.com"):
        return url
    parts = urlsplit(url)
    m = _IKEA_PATH.match(parts.path)
    if not m or m.group(1).lower() == cc.lower():
        return url
    path = f"/{IKEA_LOCALE[cc.lower()]}/{m.group(3)}{m.group(4)}"
    return urlunsplit((parts.scheme or "https", parts.netloc, path, parts.query, ""))


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


def need_bulky(need: Need) -> bool:
    """Picked up near you (furniture, a bike, a car): the category says so, else the words."""
    if need.kind != "product":
        return False
    if (need.category or {}).get("bulky"):
        return True
    try:
        from agora import marketplaces
        return marketplaces.is_bulky(_thing_q(need))
    except Exception:
        return False


def market_thing(need: Need, lang: str | None) -> str:
    """The words to type into a marketplace for this need: a generic vehicle in that language ('bright red
    car' -> 'punainen auto' on tori), a generic thing typed in another language by its category's label in this
    one ('kinderwagen' -> 'lastenrattaat' on tori), else the need's own words."""
    from agora.need import vehicle_words
    iso = ISO_OF_LOCAL.get(lang or "", lang)
    if (v := vehicle_words(need, iso)) is not None:
        return v
    return translated_thing(need, iso) or words_in(need, iso) or _thing_q(need)


def direct_thing(need: Need, lang: str | None) -> str:
    """The words handed to marketplaces.direct_pages, which translates generic nouns per site itself: like
    market_thing, without the home-language translation (else blocket would be searched in Finnish)."""
    from agora.need import vehicle_words
    iso = ISO_OF_LOCAL.get(lang or "", lang)
    if (v := vehicle_words(need, iso)) is not None:
        return v
    return translated_thing(need, iso) or _thing_q(need)


def _marketplace_word(thing: str, iso: str) -> str | None:
    """The marketplaces' own translation of a generic noun typed in any language ('winter jacket' ->
    'talvitakki', 'fiets' -> 'polkupyörä'), only when it replaces every word typed (a brand or model word kept
    by the site query, 'ikea kallax', means the words already work in every language). None otherwise."""
    try:
        from types import SimpleNamespace

        from agora import marketplaces
        tr = marketplaces.site_query(thing, SimpleNamespace(lang=iso))
    except Exception:
        return None
    low = (thing or "").lower()
    if not tr or tr == low.strip() or set(tr.split()) & set(re.findall(r"[\w'-]+", low)):
        return None
    return tr


def words_in(need: Need, iso: str | None) -> str | None:
    """A generic need in language `iso` for a web query or a shop search ('winter jacket women' ->
    'naisten talvitakki', eval r3: the new lane searched 'winter jacket women hinta osta' and found one premium
    shop). Who it is for is kept. None when nothing needs translating."""
    if not iso or iso == "en" or need.kind != "product":
        return None
    tr = _marketplace_word(_thing_q(need), iso)
    if tr is None:
        return None
    try:
        from agora.need import AUDIENCE_RE, audience, audience_word
        who = audience(need)
        word = audience_word(who, iso) if who else None
    except Exception:
        word, AUDIENCE_RE = None, None
    if word and AUDIENCE_RE is not None and not AUDIENCE_RE.search(tr):
        tr = f"{tr} {word}" if iso in _AUDIENCE_AFTER else f"{word} {tr}"
    return tr


def translated_thing(need: Need, iso: str | None) -> str | None:
    """The category's label in language `iso` when the need is generic and was typed in another language."""
    from agora.need import query_language
    typed = query_language(need.raw)
    if not iso or not typed or typed == iso:
        return None
    if _marketplace_word(_thing_q(need), iso) is not None:
        return None              # the marketplaces translate 'fiets' to 'polkupyörä' (the node label was 'Pyöräily')
    try:
        from agora import resolve
        if not resolve.is_generic(need):
            return None
    except Exception:
        return None
    label = ((need.category or {}).get("labels") or {}).get(iso)
    if not label or len(label.split()) > 3 or re.search(r"[,&/]", label):
        return None              # 'Autot, kuorma-autot ja pakettiautot' is a shelf name, not a search
    return label.lower()


def plan_direct(need: Need, lanes: list[str], tokens: float, n_searches: int, pages: int = 1) -> dict[str, list[Any]]:
    """lane -> [marketplaces.Direct]: the marketplaces' own search pages, read without a web search. Used lane
    first (its pages yield the most), then refurbished, then new; a paid page only while the bucket has
    tokens left after the planned searches (agora.marketplaces.direct_pages)."""
    from agora import marketplaces
    if need.kind != "product" or not direct_enabled():
        return {}
    if ((need.category or {}).get("intent") or {}).get("vague"):
        return {}      # 'gift for mom': no marketplace search for the words (eval r2: 'I <3 mom' baby socks)
    cc = country_of(need)
    home = home_country() if cc is None else None
    left = tokens - n_searches
    out: dict[str, list[Any]] = {}
    # a generic need ('puhelin', 'sofa', a hunt from the tree) reads the marketplaces' own category pages, deeper
    node, generic, tree = None, False, False
    try:
        from agora import resolve
        from agora.sources import categories
        generic = resolve.is_generic(need)
        node = categories.need_node(need) if generic else None
        tree = (need.category or {}).get("source") == "tree"
    except Exception:
        node, generic = None, False
    for lane in ("used", "refurbished", "new"):
        if lane not in lanes:
            continue
        thing = direct_thing(need, _lang(cc or home))
        got = marketplaces.direct_pages(thing, lane, cc, home, left, pages=pages, node=node,
                                        generic=generic, tree=tree)
        left -= sum(1 for d in got if d.paid)
        got = with_site_language(need, got, thing)
        got = with_audience(need, got)
        if vehicle(need):
            before = sum(1 for d in got if d.paid)
            got = car_directs(got, cc or home, left)
            left -= max(0, sum(1 for d in got if d.paid) - before)
        if got:
            out[lane] = got
    return out


def _letters(text: str) -> str:
    return re.sub(r"[^\w]|_|\d", "", (text or "").lower())


def _same_noun(a: str, b: str) -> bool:
    """'robotti-imuri' ~ 'Robotti-imurit', 'saugroboter' ~ 'Saugroboter' (inflection / plural endings)."""
    a, b = _letters(a), _letters(b)
    if len(a) < 4 or len(b) < 4 or abs(len(a) - len(b)) > 3:
        return False
    n = max(4, min(len(a), len(b)) - 2)
    return a[:n] == b[:n]


_SITE_ISO = {"no": "nb"}


def with_site_language(need: Need, directs: list[Any], thing: str) -> list[Any]:
    """Each marketplace searched in its own language for a generic thing the marketplaces' word list does not
    know: the category node's label in the site's language ('robotti-imuri' -> 'robotdammsugare' on blocket,
    'saugroboter' on kleinanzeigen; eval r3: blocket / finn / dba / olx were searched for the Finnish word and gave
    0 kept listings of 196). Only when the whole thing IS the node's label in some language; a site in that
    language, a category page and a car site keep their search."""
    labels = {k: v for k, v in ((need.category or {}).get("labels") or {}).items()
              if v and len(v.split()) <= 3 and not re.search(r"[,&/]", v)}
    if not directs or not labels or not thing:
        return directs
    src = {lg for lg, lab in labels.items() if _same_noun(thing, lab)}
    if not src:
        return directs
    import dataclasses

    from agora import marketplaces
    out: list[Any] = []
    firsts: dict[str, str] = {}
    for d in directs:
        iso = _SITE_ISO.get(d.site.lang, d.site.lang)
        if d.category or d.site.vehicle or iso in src or not _same_noun(d.query or "", thing):
            out.append(d)            # translated by the site query already, or the site speaks that language
            continue
        q = (labels.get(iso) or labels.get("en") or "").lower()
        if not q:
            out.append(d)
            continue
        if d.page <= 1:
            url = firsts[d.site.key] = marketplaces.build_url(d.site, q)
        else:
            base = firsts.get(d.site.key) or marketplaces.build_url(d.site, q)
            url = marketplaces.page_url(d.site, base, d.page) or base
        for store in (marketplaces.PAGE_PLAN, marketplaces.CATEGORY_PAGES):
            if d.url in store:
                marketplaces._remember(store, url, store[d.url])
        out.append(dataclasses.replace(d, query=q, url=url))
    return out


# car sites whose search box ignores ?q= (eval r3: nettiauto.com/vaihtoautot?q=volvo+v70 listed the site's cheapest
# cars of every make): their make / model pages instead. {make} / {model} are URL slugs.
CAR_MODEL_PAGES = {"nettiauto": ("https://www.nettiauto.com/{make}/{model}", "https://www.nettiauto.com/{make}"),
                   **{f"autoscout24_{cc}": (f"https://www.autoscout24.{cc}/lst/{{make}}/{{model}}?atype=C",
                                            f"https://www.autoscout24.{cc}/lst/{{make}}?atype=C")
                      for cc in ("de", "nl", "it", "be", "at")}}
_MAKE_SLUG = {"vw": "volkswagen", "mercedes": "mercedes-benz", "škoda": "skoda", "citroën": "citroen",
              "mini cooper": "mini", "range rover": "land-rover"}
_YEAR = re.compile(r"^(?:19|20)\d\d$")


def car_make_model(query: str) -> tuple[str, str | None] | None:
    """'volvo v70' -> ('volvo', 'v70'), 'land rover defender 2015' -> ('land-rover', 'defender'), 'vw golf' ->
    ('volkswagen', 'golf'); None when no make is named (or words other than make / model / year are left)."""
    from agora.need import CAR_MAKES
    q = (query or "").lower().strip()
    m = CAR_MAKES.search(q)
    if not m or q[:m.start()].strip():
        return None
    make = _MAKE_SLUG.get(m.group(0), m.group(0)).replace(" ", "-")
    rest = [w for w in re.findall(r"[\w-]+", q[m.end():]) if not _YEAR.match(w)]
    if len(rest) > 2:
        return None
    model = "-".join(rest) or None
    return make, model


# car sites whose list pages are paged and sorted by URL (checked live 14 Nov: nettiauto.com/volvo/v70?page=23 is
# the last of 664 V70s; its default order is cheapest first, so page 1 of a site-wide list was 30 scrap cars at
# €51-€300 (eval r4, 'bright red car'). Newest first is a fair sample of what is for sale.
CAR_SORT = {"nettiauto": "sortCol=dateCreated&ord=DESC"}
CAR_PAGED = {"nettiauto"}
CAR_MORE_PAGES = 2            # paid: pages 2-3 of the home cars site while the shared bucket allows
CAR_MORE_PAGES_FREE = 5       # free (read without a token): pages 2-6
CAR_PAGE_MIN_TOKENS = 2.0     # a paid next page (30 cars for 1 token) only while this many stay for item reads


def _with_query(url: str, extra: str) -> str:
    parts = urlsplit(url)
    have = dict(parse_qsl(parts.query, keep_blank_values=True))
    add = [(k, v) for k, v in parse_qsl(extra) if k not in have]
    query = urlencode(list(parse_qsl(parts.query, keep_blank_values=True)) + add)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _hint_list(url: str) -> None:
    if len(_LIST_HINTS) > 5000:
        _LIST_HINTS.clear()
    _LIST_HINTS.add(normalize_url(url))     # a list page of that site (marketplaces.site_for)


def car_directs(directs: list[Any], where: str | None, tokens: float | None = None) -> list[Any]:
    """A car hunt's marketplace pages (eval r3, 'volvo v70' and 'bright red car'):
    - a car site that ignores ?q= reads the make / model page (nettiauto.com/volvo/v70); a query naming no make
      ('electric') cannot be put in its URL, so that site is not read (its site-wide list is any car);
    - when a cars site of the home country is planned, the general goods marketplace (tori's goods search:
      toys, LEGO, tyres, parts) is not read for a car: it spent the read budget and filled the market count.
    eval r4: the home cars site is read newest first (CAR_SORT, never its cheapest-first scrap list) and paged
    (CAR_PAGED: pages 2-3 while `tokens` allow, deeper when the site reads free): 1 page was 32 of 664 V70s."""
    import dataclasses

    from agora import marketplaces
    out: list[Any] = []
    left = float(tokens) if tokens is not None else 0.0
    for d in directs:
        tpl = CAR_MODEL_PAGES.get(d.site.key) if d.site.vehicle else None
        sort = CAR_SORT.get(d.site.key) if d.site.vehicle else None
        if tpl is None or not d.query:
            if sort and d.page <= 1:
                url = _with_query(d.url, sort)
                _hint_list(url)
                d = dataclasses.replace(d, url=url)
            out.append(d)            # a generic car browses the category (no query): the site's own list
            continue
        mm = car_make_model(d.query)
        if mm is None:
            continue
        make, model = mm
        url = tpl[0].format(make=make, model=model) if model else tpl[1].format(make=make)
        if d.page > 1:
            continue                 # the model page is paged below (CAR_PAGED), never with a search's ?page=
        if sort:
            url = _with_query(url, sort)
        _hint_list(url)
        out.append(dataclasses.replace(d, url=url))
    if any(d.site.vehicle and d.site.country == where for d in out):
        out = [d for d in out if d.site.vehicle or d.category]
    # a car is bought near you: the home cars site's next pages come before the marketplaces abroad (`extra`)
    extras = [d for d in out if d.extra and d.paid]
    left += len(extras)
    more: list[Any] = []
    for d in out:
        if d.site.key not in CAR_PAGED or d.page > 1 or d.extra or (where and d.site.country != where):
            continue
        free = not d.paid
        for n in range(2, 2 + (CAR_MORE_PAGES_FREE if free else CAR_MORE_PAGES)):
            if not free and (tokens is None or left - 1 < CAR_PAGE_MIN_TOKENS):
                break
            url = marketplaces.page_url(d.site, d.url, n)
            if not url or any(x.url == url for x in out + more):
                break
            if not free:
                left -= 1
            _hint_list(url)
            more.append(dataclasses.replace(d, url=url, page=n))
    if extras:
        keep = max(0, int(left - CAR_PAGE_MIN_TOKENS + 1)) if more else len(extras)
        drop = {id(d) for d in extras[keep:]}
        out = [d for d in out if id(d) not in drop]
    if more:
        # page 2+ go right after their site's page 1 (discover emits directs in order)
        ordered: list[Any] = []
        for d in out:
            ordered.append(d)
            ordered += [m for m in more if m.site.key == d.site.key and d.page == 1 and m.url.split("?")[0]
                        == d.url.split("?")[0]]
        out = ordered + [m for m in more if m not in ordered]
    return out


# --------------------------------------------------------------------------- eval r2: who it is for

_AUDIENCE_AFTER = {"pl", "fr", "es", "it", "cs"}     # 'kurtka zimowa damska', 'veste hiver femme'


def with_audience(need: Need, directs: list[Any]) -> list[Any]:
    """Keep who the thing is for in the marketplaces' own searches: 'winter jacket women' -> 'naisten talvitakki'
    on tori, 'damen winterjacke' on kleinanzeigen, 'dam vinterjacka' on blocket (eval r2: the audience word was
    dropped, and the pick was a children's jacket). Category pages and car sites are left as they are."""
    from agora.need import AUDIENCE_RE, audience, audience_word
    who = audience(need)
    if not who or not directs:
        return directs
    import dataclasses

    from agora import marketplaces
    out: list[Any] = []
    firsts: dict[str, str] = {}
    for d in directs:
        word = audience_word(who, d.site.lang)
        if d.category or d.site.vehicle or not word or not d.query or AUDIENCE_RE.search(d.query):
            out.append(d)
            continue
        q = f"{d.query} {word}" if d.site.lang in _AUDIENCE_AFTER else f"{word} {d.query}"
        if d.page <= 1:
            url = firsts[d.site.key] = marketplaces.build_url(d.site, q)
        else:
            base = firsts.get(d.site.key) or marketplaces.build_url(d.site, q)
            url = marketplaces.page_url(d.site, base, d.page) or base
        for store in (marketplaces.PAGE_PLAN, marketplaces.CATEGORY_PAGES):
            if d.url in store:
                marketplaces._remember(store, url, store[d.url])
        out.append(dataclasses.replace(d, query=q, url=url))
    return out


# --------------------------------------------------------------------------- eval r2: cars

def vehicle(need: Need) -> bool:
    """A car (or van) itself is wanted: its category says so, else its words."""
    if need.kind != "product":
        return False
    cat = need.category or {}
    if cat.get("kind") == "vehicle":
        return True
    try:
        from agora.need import vehicle_need
        return vehicle_need(need.thing or "")
    except ImportError:
        return False


# a used-car list: a dealer's or aggregator's make/model page ('autouncle.fi/fi/kaytetyt-autot/Volvo/V70',
# 'kamux.fi/cars/volvo/v/v70', 'autoscout24.com/lst/volvo/v70'), not one car (those carry a long id)
_CAR_LIST_SEG = re.compile(
    r"^(?:k[aä]ytetyt-autot|vaihtoautot?|autot|cars|used-cars|gebrauchtwagen|gebrauchte-autos|autos|"
    r"begagnade-bilar|begagnat|bilar|brugte-biler|biler|bruktbil|occasions?|occasion-auto\w*|tweedehands-auto\w*|"
    r"lst|listaa|ajoneuvohaku|haku|osta)$", re.I)
_CAR_USED_WORDS = re.compile(
    r"vaihtoauto|k[aä]ytet|gebraucht|begagna|brugt|brukt|used|occasion|tweedehands|second[- ]hand|"
    r"for sale|myynniss|zu verkaufen|till salu|te koop|/lst\b|ajoneuvohaku|autot?\b", re.I)
_CAR_LIST_TITLE = re.compile(
    r"\b\d[\d\s.,]*\s*(?:autoa|cars|bilar|biler|fahrzeuge|angebote|auto's|occasions|listings)\b|vaihtoautot\b|"
    r"for sale near|k[aä]ytetyt\b", re.I)
_ITEM_ID = re.compile(r"\d{5,}")
# car sellers outside Europe: a car is bought near you (eval r2: carfax / cars.com / edmunds in a Finnish hunt)
CARS_ABROAD = ("carfax.com", "cars.com", "edmunds.com", "jdpower.com", "carsandbids.com", "carmax.com",
               "cargurus.com", "carsforsale.com", "kbb.com", "autotrader.com", "truecar.com", "carvana.com",
               "capitalone.com", "classic.com", "bringatrailer.com", "ebay.com", "autolist.com", "iseecars.com",
               "carpricetracker.com", "carprice.com", "carsdirect.com", "autobytel.com", "motortrend.com",
               "caranddriver.com", "carsoup.com", "hemmings.com")
_LIST_HINTS: set[str] = set()       # pages discovery found to be lists by their title (auto1.fi/volvo/v70)


_US_PATH = re.compile(r"^/(?:us|en-us|en_us|us-en|en/us)(?:/|$)", re.I)
_US_TLDS = ("us", "nyc")
# US home / bike / baby shops that turned up in Finnish bulky hunts (eval r1-r3)
US_SHOPS = ("wayfair.com", "overstock.com", "jordans.com", "nordstrom.com", "dillards.com", "kidslandusa.com",
            "goodbuygear.com", "roomstogo.com", "arhaus.com", "mybobs.com", "furniturelandsouth.com",
            "pricebusters.com", "bikesdirect.com", "bicyclewarehouse.com", "theproscloset.com", "occyclery.com",
            "tomcatbikes.com", "rei.com", "macys.com", "kohls.com", "potterybarn.com", "westelm.com",
            "crateandbarrel.com", "ashleyfurniture.com", "bobsdiscount.com", "buybuybaby.com")


def us_shop(url: str) -> bool:
    """A shop selling in the US: a US-only big box (US_FIRST), a .us / .nyc domain, or a /us/ or /en-us/ store
    of a global site (ikea.com/us/en, specialized.com/us). Used for bulky things only (eval r3)."""
    dom = domain_of(url)
    if tld(dom) in _US_TLDS or any(dom_match(dom, d) for d in US_FIRST + US_SHOPS):
        return True
    return bool(_US_PATH.match(urlsplit(url).path))


def car_list_page(url: str, title: str = "") -> bool:
    """A page listing many cars: a used-car path with no car id, or a title counting cars for sale."""
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if any(_ITEM_ID.search(p) for p in parts):
        return False
    if any(_CAR_LIST_SEG.match(p) for p in parts):
        return True
    return bool(title and _CAR_LIST_TITLE.search(title))


def used_car_page(need: Need, url: str, title: str) -> bool:
    """A page of used cars: its words say so, it is a marketplace (tori, kleinanzeigen), or a used-car site of
    the need's category (nettiauto.com, autotalli.com, mobile.de)."""
    dom = domain_of(url)
    if _CAR_USED_WORDS.search(f"{urlsplit(url).path} {title}") or is_marketplace(dom):
        return True
    return any(d.get("lane") == "used" and dom_match(dom, str(d.get("domain") or "x"))
               for d in (need.category or {}).get("domains") or [])


def car_abroad(dom: str, title: str = "") -> bool:
    if any(dom_match(dom, d) for d in CARS_ABROAD) or tld(dom) in ("us", "ca", "au"):
        return True
    return not is_eu(dom) and bool(re.search(r"\bnear me\b|\$\s?\d", title or "", re.I))


# a colour that contains the asked one but is another: 'vaaleanpunainen' (pink) is not 'punainen' (red)
COLOUR_CLASH = {"red": ("vaaleanpunai", "pinkki", "pink", "rosa", "roze", "lyserød"),
                "blue": ("vaaleansinin", "turkoosi", "turquoise", "türkis"),
                "green": ("vaaleanvihre", "mint")}


def colour_clash(need: Need, url: str, title: str) -> str | None:
    """'another colour (pink), not red' when the page names a different colour that contains the asked one."""
    try:
        from agora.need import COLOUR_WORDS
    except ImportError:
        return None
    asked = " ".join(need.must_have + [need.raw or ""]).lower()
    hay = f"{urlsplit(url).path} {title}".lower()
    for colour, clashes in COLOUR_CLASH.items():
        names = {colour} | set((COLOUR_WORDS.get(colour) or {}).values())
        if not any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", asked) for n in names):
            continue
        for c in clashes:
            if c in hay and c not in asked:
                return f"another colour ({c}), not {colour}"
    return None


# a used-car list narrowed by a filter in its path ('/vaihtoautot/listaa/volvo/v70/vuosimalli_min/2007/
# vuosimalli_max/2007': 12 cars of one model year, eval r4) is read as the whole make / model list
_CAR_FILTER_SEG = re.compile(r"^[a-z]+_(?:min|max|from|to|alku|loppu)$", re.I)
# a car site's front page or a valuation / price-history tool is no car and no list of cars (eval r4, 'bright red
# car': autouncle.fi/, nettiauto.com/en, mobile.de/en, oma.almaajo.fi/auton-hinta-arvio, auto1.fi/hintaseuranta)
_CAR_TOOL = re.compile(r"hinta-?arvio|hintaseuranta|arvonm[aä][aä]ritys|valuation|bewertung|price-?tracker|"
                       r"rahoitus|financing|vakuutus|insurance|uudet-autot/uusi-haku|myy-autosi|sell-your-car|"
                       r"auto-verkaufen", re.I)
_FRONT_PATH = re.compile(r"^/(?:[a-z]{2}(?:[-_][a-z]{2})?/?)?$", re.I)


def car_list_base(url: str) -> str:
    """The used-car list without its path filters (autotalli's year range), else the URL unchanged."""
    parts = urlsplit(url)
    segs = parts.path.split("/")
    for i, seg in enumerate(segs):
        if i >= 3 and _CAR_FILTER_SEG.match(seg) and car_list_page(url):
            return urlunsplit((parts.scheme, parts.netloc, "/".join(segs[:i]), parts.query, ""))
    return url


def car_page_skip(url: str, title: str = "", home_cars: bool = False) -> str | None:
    """Why a page found by search is no car and no list of cars for a car hunt, else None:
    - a site's front page (autouncle.fi/, mobile.de/en): no car on it;
    - a valuation / price-history / financing tool;
    - the general goods marketplace's search (tori's 'volvo v70' = rims, tyres, seats; 'punainen auto' = toys)
      when the home country's cars site is read anyway (`home_cars`); its car listings come from there."""
    parts = urlsplit(url)
    if _FRONT_PATH.match(parts.path or "/") and not parts.query:
        return "a car site's front page, not a car or a list of cars"
    if _CAR_TOOL.search(parts.path):
        return "a valuation, finance or configurator tool, not a car for sale"
    if home_cars and is_marketplace(domain_of(url)) and is_list_page(url):
        try:
            from agora import marketplaces
            site = marketplaces.site_for(url)
        except Exception:
            site = None
        if site is not None and not site.vehicle:
            return "the goods marketplace's search (parts, tyres, toys); cars are read from the cars site"
    return None


VEHICLE_USED = {"fi": "vaihtoautot myynnissä", "de": "Gebrauchtwagen kaufen", "se": "begagnad bil till salu",
                "nl": "occasion te koop", "dk": "brugt bil til salg", "no": "bruktbil til salgs",
                "fr": "voiture d'occasion à vendre", "es": "coche de segunda mano", "it": "auto usata in vendita",
                "pl": "samochód używany sprzedam", "pt": "carro usado à venda", "cz": "ojeté auto prodej"}


def vehicle_scope(scope: dict[str, Any], where: str | None) -> dict[str, Any]:
    """The scope line for a car: bought and picked up near you (never 'shipping a medium parcel')."""
    from agora import marketplaces
    name = marketplaces.NAMES.get(where or "", (where or "your country").upper())
    return {**scope, "scope": "home", "bulky": True, "size": "vehicle",
            "reason": f"a car: searched near you in {name} (cars are bought and picked up locally)"}


# --------------------------------------------------------------------------- eval r2: services that fit the job

# the kind of work a service marketplace lists; a domain missing here lists any work ('general')
DOMAIN_FAMILIES: dict[str, frozenset[str]] = {
    "helpling.": frozenset({"cleaning"}), "kotisiivousvertailu.fi": frozenset({"cleaning"}),
    "hemfrid.se": frozenset({"cleaning"}), "happyhelper.dk": frozenset({"cleaning"}),
    "batmaid.ch": frozenset({"cleaning"}), "clintu.es": frozenset({"cleaning"}),
    "wecasa.fr": frozenset({"cleaning", "beauty"}),
    "betreut.": frozenset({"care", "pets", "cleaning"}), "care.com": frozenset({"care", "pets", "cleaning"}),
    "yoopies.": frozenset({"care", "pets", "cleaning"}), "sittercity.com": frozenset({"care", "pets"}),
    "rover.com": frozenset({"pets"}),
    "timma.fi": frozenset({"beauty", "health"}), "treatwell.": frozenset({"beauty", "health"}),
    "fresha.com": frozenset({"beauty", "health"}), "booksy.com": frozenset({"beauty", "health"}),
    "urakkamaailma.fi": frozenset({"trades", "moving", "cleaning"}),
    "remonttipalvelu.fi": frozenset({"trades"}),
    "myhammer.": frozenset({"trades", "moving", "cleaning"}), "my-hammer.": frozenset({"trades", "moving", "cleaning"}),
    "blauarbeit.de": frozenset({"trades", "moving", "cleaning"}), "aroundhome.de": frozenset({"trades"}),
    "werkspot.nl": frozenset({"trades", "moving", "cleaning"}), "homedeal.nl": frozenset({"trades", "cleaning"}),
    "zoofy.nl": frozenset({"trades"}), "offerteadviseur.nl": frozenset({"trades", "moving", "cleaning"}),
    "checkatrade.com": frozenset({"trades"}), "mybuilder.com": frozenset({"trades"}),
    "ratedpeople.com": frozenset({"trades"}), "tradesmen.ie": frozenset({"trades"}),
    "habitissimo.es": frozenset({"trades", "cleaning"}), "3byggetilbud.dk": frozenset({"trades", "cleaning"}),
    "renovero.ch": frozenset({"trades"}), "nejremeslnici.cz": frozenset({"trades"}),
    "mittanbud.no": frozenset({"trades", "moving", "cleaning"}),
    "servicefinder.se": frozenset({"trades", "moving", "cleaning"}),
    "offerta.se": frozenset({"trades", "moving", "cleaning"}), "ofri.ch": frozenset({"trades", "moving", "cleaning"}),
    "lounaat.info": frozenset({"food"}), "lounasaika.net": frozenset({"food"}), "lounasinfo.fi": frozenset({"food"}),
    "wolt.com": frozenset({"food"}), "foodora.": frozenset({"food"}),
}
SERVICE_FAMILY = {"cleaning": "cleaning", "laundry": "cleaning", "plumbing": "trades", "electrician": "trades",
                  "painting": "trades", "handyman": "trades", "gardening": "trades", "repair": "trades",
                  "moving": "moving", "haircut": "beauty", "massage": "beauty", "physiotherapy": "health",
                  "childcare": "care", "pet care": "pets", "tutoring": "lessons", "gunsmith": "craft",
                  "photography": "events", "car wash": "auto", "tyre change": "auto", "accounting": "business",
                  "legal": "business"}
_FAMILY_WORDS = (("food", r"lunch|lounas|restaurant|ravintol|catering|ateri|food|ruoka|meal|buffet"),
                 ("cleaning", r"clean|siivo|reinig|städ|schoonma"),
                 ("trades", r"plumb|electric|renovat|construct|trades|home-services|roof|carpent|paint|hvac|"
                            r"remont|putki|sähkö"),
                 ("beauty", r"beauty|hair|barber|nail|spa\b|parturi|kampaamo|kosmet"),
                 ("pets", r"\bpets?\b|dog|koira|cat sitting"),
                 ("care", r"babysit|childcare|nanny|elder|senior care|lastenhoi"),
                 ("events", r"wedding|photograph|event|party|juhla|hää"))


def service_family(need: Need) -> str | None:
    """The kind of work asked for ('trades', 'cleaning', 'food' ...), None = unknown (only general sites fit)."""
    name = service_name(need)
    if name in SERVICE_FAMILY:
        return SERVICE_FAMILY[name]
    cat = need.category or {}
    hay = " ".join([need.thing or "", str(cat.get("label") or ""), " ".join(str(p) for p in cat.get("path_ids") or [])])
    for fam, rx in _FAMILY_WORDS:
        if re.search(rx, hay, re.I):
            return fam
    return None


def market_fits(dom: str, need: Need, cc: str | None) -> bool:
    """A service marketplace fits the job: it lists that kind of work (no pet-sitters for a gunsmith, no
    cleaners for a plumber) and serves the searched country (no checkatrade.com for Berlin)."""
    fams = next((f for d, f in DOMAIN_FAMILIES.items() if dom_match(dom, d)), None)
    if fams is not None and service_family(need) not in fams:
        return False
    owners = {c for c, ds in SERVICE_MARKETS.items() if any(dom_match(dom, d) for d in ds)}
    if owners and cc and cc not in owners and tld(dom) != cc:
        return False
    return True


def _stems(words: str) -> set[str]:
    out = set()
    for w in re.findall(r"[^\W\d_]{4,}", (words or "").lower()):
        out.add(w[:max(4, len(w) - 3)])
    return out


_TRADE_STOP = {"price", "hinta", "preis", "prijs", "pris", "service", "palvelu", "near", "with", "your", "home",
               "koti", "kotisiivous", "restaurant"}


def trade_hit(need: Need, url: str, title: str) -> bool:
    """The page's URL or title names the job ('asesepan-palvelut' for a gunsmith, 'klempner' for a plumber)."""
    words = " ".join([need.thing or "", local_words(need, _lang(country_of(need) or home_country())) or "",
                      str((need.category or {}).get("label") or "")])
    stems = {s for s in _stems(words) if s not in _TRADE_STOP and len(s) >= 4}
    if not stems:
        return False
    hay = f"{urlsplit(url).path} {title}".lower()
    return any(s in hay for s in stems)


def _local_service(need: Need) -> bool:
    return is_service(need) and not priced_per_period(need)


def other_city(need: Need, url: str, title: str) -> str | None:
    """The page is about another city of the searched country (a lunch list for Tampere when Helsinki was
    asked): that city's name, else None. Pages naming the asked city (or its area) too are fine."""
    if not need.where or not _local_service(need):
        return None
    from agora import places
    home = places.country_for(need.where)
    if not home or need.where.strip().lower() not in places.CITY_CC:
        return None                       # a country was asked ('Finland'): every city is in it
    hay = re.sub(r"[-_/.?=&+]", " ", urlsplit(url).path) + " | " + (title or "")
    found = places.cities_in(hay)
    if not found or any(places.same_area(need.where, c) for c, _cc in found):
        return None
    other = next(((c, k) for c, k in found if k == home), None)
    return other[0].title() if other else None


def place_hit(need: Need, url: str, title: str) -> bool:
    if not need.where:
        return False
    from agora import places
    parts = urlsplit(url)
    hay = re.sub(r"[-_/.?=&+]", " ", f"{parts.netloc} {parts.path}") + " | " + (title or "")
    return any(places.same_area(need.where, c) for c, _cc in places.cities_in(hay))


def service_fit(need: Need, url: str, title: str) -> float:
    """Read-order bonus for a service page: it names the job (+1), the asked city (+0.8); a provider abroad
    for a local job comes after the local ones (-1.5)."""
    s = 0.0
    if trade_hit(need, url, title):
        s += 1.0
    if place_hit(need, url, title):
        s += 0.8
    elif _local_service(need) and _foreign_generic(domain_of(url)):
        s -= 1.5
    return s


def _foreign_generic(dom: str) -> bool:
    """A .com / .net / .org site for a local job in Europe (westcoastarmory.com for a Helsinki gunsmith)."""
    return tld(dom) in ("com", "net", "org", "us", "io", "co") and not is_eu(dom)


APP_STORES = ("apps.apple.com", "play.google.com", "itunes.apple.com", "apps.microsoft.com", "chromewebstore.google.com")
_COST_WORDS = re.compile(r"\b(?:labou?r cost|cost guide|costs?\b|lower estimate|average price|how much)", re.I)


def service_skip(need: Need, url: str, title: str) -> str | None:
    """Why a service page is no provider for this hunt (an app store, a cost guide from abroad, another city)."""
    dom = domain_of(url)
    if any(dom_match(dom, d) for d in APP_STORES):
        return "an app store page, not a provider"
    if any(dom_match(dom, d) for d in COST_STATS):
        return "a cost-of-living statistic (an average), not a provider"
    cc = country_of(need) or home_country()
    if _local_service(need) and cc and cc not in ("gb", "ie") and _foreign_generic(dom) \
            and (cost_guide(url, title) or _COST_WORDS.search(f"{urlsplit(url).path.replace('-', ' ')} {title}")):
        return "a cost guide from abroad (foreign prices), not a provider near you"
    if city := other_city(need, url, title):
        return f"another city ({city}), not {need.where}"
    if _local_service(need) and need.where and _foreign_generic(dom) and english_hit(need, url, title) \
            and not place_hit(need, url, title) and not local_hit(need, url, title) \
            and not any(dom_match(dom, d) for d in SERVICE_DIRECTORIES):
        # 'gunsmithing services' at a US gun shop for a Helsinki gunsmith: priced in USD, rejected after a read
        return f"a provider abroad, not near {need.where}"
    return None


def english_hit(need: Need, url: str, title: str) -> bool:
    """The page names the job in English ('gunsmithing', 'plumbing'): an English-language provider."""
    stems = {x for x in _stems(need.thing or "") if x not in _TRADE_STOP}
    hay = f"{url} {title}".lower()
    return bool(stems) and any(x in hay for x in stems)


def local_hit(need: Need, url: str, title: str) -> bool:
    """The page names the job in the local language ('aseseppä', 'Klempner'): a local provider on a .com."""
    cc = country_of(need) or home_country()
    lang = _lang(cc)
    if not lang or lang == "en":
        return True                      # an English-speaking place: an English page may be local
    stems = {x for x in _stems(local_words(need, lang) or "") if x not in _TRADE_STOP}
    hay = f"{url} {title}".lower()
    return bool(stems) and any(x in hay for x in stems)


# --------------------------------------------------------------------------- eval r2: bought at home (insurance)

# (price word, 'from ... a month' words): the second query looks for the providers' own stated prices
# (eval r3: 'vertailu laskuri' found calculators and comparison sites, none an insurer's price)
NATIONAL_LOCAL = {"fi": ("hinta", "alkaen €/kk"), "de": ("Preis", "ab € monatlich"),
                  "se": ("pris", "från kr/mån"), "nl": ("prijs", "vanaf € per maand"), "dk": ("pris", "fra kr/md"),
                  "no": ("pris", "fra kr/mnd"), "fr": ("prix", "à partir de €/mois"), "es": ("precio", "desde €/mes"),
                  "it": ("prezzo", "da €/mese"), "pl": ("cena", "od zł/mies"), "pt": ("preço", "desde €/mês"),
                  "cz": ("cena", "od Kč/měsíc")}
# where a country's insurers, banks and energy companies publish prices and calculators
NATIONAL_SITES: dict[str, dict[str, tuple[str, ...]]] = {
    "fi": {"insurance": ("if.fi", "op.fi", "lahitapiola.fi", "fennia.fi", "pohjola.fi", "turva.fi", "pop.fi", "popvakuutus.fi",
                         "pohjantahti.fi",
                         "aktia.fi", "tryg.fi"),
           "energy": ("sahkovertailu.fi", "helen.fi", "fortum.fi", "oomi.fi", "vaasansahko.fi"),
           "loan": ("op.fi", "nordea.fi", "danskebank.fi", "s-pankki.fi", "aktia.fi")},
    "de": {"insurance": ("check24.de", "verivox.de", "huk.de", "allianz.de", "devk.de", "ergo.de"),
           "energy": ("check24.de", "verivox.de"), "loan": ("check24.de", "verivox.de", "smava.de")},
    "se": {"insurance": ("folksam.se", "if.se", "trygghansa.se", "lf.se", "compricer.se"),
           "energy": ("elskling.se", "elpriskollen.se")},
    "nl": {"insurance": ("independer.nl", "centraalbeheer.nl", "interpolis.nl", "nn.nl"),
           "energy": ("independer.nl", "pricewise.nl")},
}
_NATIONAL_KIND = (("insurance", r"insur|vakuut|versicher|försäkr|forsikr|verzeker|assuranc"),
                  ("energy", r"electric|sähkö|strom|elavtal|energ"),
                  ("loan", r"loan|laina|kredit|mortgage|hypothe|bolån"))


def national_kind(need: Need) -> str | None:
    cat = need.category or {}
    hay = f"{need.thing} {need.raw} {cat.get('label') or ''} {' '.join(cat.get('path_ids') or [])}"
    return next((k for k, rx in _NATIONAL_KIND if re.search(rx, hay, re.I)), None)


def national_plan(need: Need, cc: str) -> list[Any]:
    """Insurance, loans, energy: bought in your own country, in its language, priced by quote. The country's
    word for it with 'price' and 'compare / calculator', the English one filtered to the country, then one
    search inside its insurers' / banks' own sites (eval r2: 'Car insurance' found only US insurers in USD)."""
    lang = _lang(cc)
    iso = ISO_OF_LOCAL.get(lang or "", lang or "")
    label = ((need.category or {}).get("labels") or {}).get(iso) or local_words(need, lang) or ""
    label = label.strip() if label and len(label.split()) <= 3 and not re.search(r"[,&/]", label) else ""
    price_w, compare_w = NATIONAL_LOCAL.get(lang or "", ("price", "compare"))
    from agora import marketplaces
    country = marketplaces.NAMES.get(cc, cc.upper())
    out: list[Any] = []
    if label:
        out.append((f"{label} {price_w}", cc))
    out.append((re.sub(r"\s+", " ", f"{_thing_q(need)} price {country}").strip(), cc))
    if label:
        out.append((f"{label} {compare_w}", cc))
    sites = list(NATIONAL_SITES.get(cc, {}).get(national_kind(need) or "", ()))
    sites += [d for d in category_sites(need, cc) if d not in sites]
    if sites:
        out.append(((label or _thing_q(need)) + (f" {price_w}" if label else ""), cc, sites[:10]))
    return out


def national_fit(need: Need, url: str, title: str) -> float:
    """Read-order bonus for an insurer's / bank's / energy company's own product page in an insurance, loan or
    energy hunt (+1.5); their calculators and comparison sites get none (eval r3: if.fi, op.fi, turva.fi product
    pages were cut by the budget and the per-domain cap while calculators were read)."""
    if not national_service(need) or calculator(url, title) or cost_guide(url, title):
        return 0.0
    cc = country_of(need) or home_country() or ""
    sites = NATIONAL_SITES.get(cc, {}).get(national_kind(need) or "", ())
    sites += tuple(category_sites(need, cc))
    dom = domain_of(url)
    return 1.5 if any(dom_match(dom, d) for d in sites) else 0.0


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
    car = vehicle(need)
    plan: list[tuple[str, str, str | None, list[str] | None]] = []
    lanes = lanes_for(need)
    bulky = need_bulky(need)
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
        scope = marketplaces.scope_for(_thing_q(need), cc, home if cc is None else None,
                                       eu_included=any(d.site.country != (cc or home) for d in planned))
        if vehicle(need):
            scope = vehicle_scope(scope, cc or home)
        yield ev("scope", **scope)
    # a car hunt reading a cars site of the home country: the goods marketplaces' searches list parts and toys
    home_cars = car and any(d.site.vehicle and d.site.country == (cc or home)
                            for ds in directs.values() for d in ds)
    for lane in lanes:
        qp = plans[lane]
        extra: dict[str, Any] = {}
        if cc is None and (any(x[1] for x in qp) or directs.get(lane)):
            extra["home_country"] = home
        if any(len(x) > 2 for x in qp):
            extra["sites"] = [d for x in qp if len(x) > 2 for d in x[2]]
        if directs.get(lane):
            extra["direct"] = [{"site": d.site.key, "domain": d.site.domain, "url": d.url, "query": d.query,
                                "paid": d.paid, "page": d.page, "extra": d.extra,
                                **({"category": d.category, "exact": d.exact} if d.category else {})}
                               for d in directs[lane]]
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
            cat_extra: dict[str, Any] = {}
            if d.category:
                from agora.sources import categories as _cats
                label = _cats.node_label(d.category)
                title = f"{dom} category: {label}" + (f" + '{d.query}'" if d.query else "")
                cat_extra = {"category": d.category, "category_label": label, "exact": d.exact}
            remember_source(d.url, lane, title, "")
            yield ev("source", url=d.url, domain=dom, lane=lane, title=title, query=d.query, snippet="",
                     eu=True, score=9.0, list_page=True, direct=True, site=d.site.key, paid=d.paid,
                     page=d.page, extra=d.extra, country=d.site.country.upper(), **cat_extra)
    tasks = {asyncio.ensure_future(_run_query(lane, q, c, lane == "service", inc)) for lane, q, c, inc in plan}

    def _yield_of(r: dict[str, Any]) -> float:
        return expected_yield(r["url"], need.kind, "service", r.get("title") or "",
                              contextdev.highlight_text(r) or r.get("description") or "")

    def refuse(url: str, dom: str) -> str | None:
        """Why this page may not be emitted now (per-domain caps), else None."""
        if is_service(need) and any(dom_match(dom, d) for d in SERVICE_DIRECTORIES):
            # one provider's profile on a directory is its own offer (urakkamaailma /urakoitsija/<firm>)
            cap = DIRECTORY_PROFILES if PROFILE_PATH.search(urlsplit(url).path) else PER_DOMAIN
            if items.get(dom, 0) + lists.get(dom, 0) >= cap:
                return f"already {cap} pages from {dom}"
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
                # pages naming the job and the asked city first (eval r2: a gunsmith hunt spent its budget on
                # asbestos and barber pages; lunch read Tampere before Helsinki)
                cands.sort(key=lambda x: (-(_yield_of(x[2]) + service_fit(need, x[2]["url"], x[2].get("title") or "")
                                            + national_fit(need, x[2]["url"], x[2].get("title") or "")),
                                          -x[0], x[1]))
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
                q_lane, query, res = fut.result()
                if isinstance(res, Exception):
                    yield ev("error", where="discover", message=f"search '{query}': {str(res)[:160]}")
                    continue
                for r in res:
                    lane = q_lane      # a car dealer page found by the new lane moves to used
                    url = r.get("url") or ""
                    if not url.startswith("http"):
                        continue
                    if car and (base := car_list_base(url)) != url:
                        r = {**r, "url": base, "narrowed_from": url}     # the whole list, not one model year
                        url = base
                    if need.kind == "product" and (local_url := localize(url, rank_cc)) != url:
                        r = {**r, "url": local_url, "localized_from": url}
                        url = local_url
                    key = normalize_url(url)
                    if key in seen:
                        old = pooled_in.get(key)
                        used_car = car and lane == "new" and used_car_page(need, url, r.get("title") or "")
                        if old and old != lane and not used_car \
                                and fit(lane, r.get("title") or "") > fit(old, r.get("title") or ""):
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
                    if not reason and is_service(need):
                        reason = service_skip(need, url, title)
                    if not reason and bulky and not car and rank_cc and rank_cc != "us" and us_shop(url):
                        reason = "a US shop (a bulky thing is bought near you)"
                    if not reason and car:
                        if car_abroad(domain_of(url), title):
                            reason = "a car seller outside Europe (a car is bought near you)"
                        else:
                            reason = colour_clash(need, url, title) or car_page_skip(url, title, home_cars)
                    if not reason and car:
                        if lane == "new" and "used" in pool and used_car_page(need, url, title):
                            lane = "used"      # a used-car dealer / aggregator page is no new car (eval r2)
                        if car_list_page(url, title) and not is_list_page(url):
                            if len(_LIST_HINTS) > 5000:
                                _LIST_HINTS.clear()
                            _LIST_HINTS.add(normalize_url(url))
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
                    if bulky and rank_cc and not home_page(url, rank_cc):
                        score -= 3.0     # a sofa from abroad: home shops are read first (eval r1: US sofa sites)
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


# --------------------------------------------------------------------------- eval r4: shop category pages, home shops

_CAT_MARKER = re.compile(r"/(?:c|cat|category|categories|collections?|kategoria|kategorie|kategori|catalog|"
                         r"catalogue|osasto|tuote-osasto|tuoteryhma|g)/", re.I)
_WORD = re.compile(r"[^\W\d_]{3,}", re.U)


def category_like(url: str) -> bool:
    """A shop's category path (/naisten-vaatteet/takit/talvitakit/, /c/..., /collections/...), not one product:
    no product id, a short last segment, at least two levels."""
    if is_list_page(url):
        return True
    path = urlsplit(url).path
    low = path.lower()
    if "/products/" in low or "/product/" in low or "/p/" in low or low.endswith((".html", ".htm")) \
            and re.search(r"\d{4,}", low):
        return False
    if _CAT_MARKER.search(path + "/"):
        return True
    segs = [x for x in path.split("/") if x]
    if len(segs) < 2:
        return False
    last = segs[-1]
    return not re.search(r"\d", last) and len(last.split("-")) <= 3


def category_page_offer(src_url: str, src_title: str, offer_url: str, offer_title: str) -> str | None:
    """Why a single offer read off a page is not one product's own offer, else None: the offer carries the
    page's own URL, the page is a shop's category page, and the page title is not that product's title
    (eval r4: emp.fi / fyndiq.fi / cellbes.fi category pages each gave one jacket linked to the category)."""
    if normalize_url(offer_url or src_url) != normalize_url(src_url) or not category_like(src_url):
        return None
    a = {w.lower() for w in _WORD.findall(offer_title or "")}
    b = {w.lower() for w in _WORD.findall(src_title or "")}
    if a and b and len(a & b) / max(1, min(len(a), len(b))) >= 0.6:
        return None              # the page title names this product: a product page with a category-like path
    return "a shop's category page: one product picked off a list, its own page unknown"


_RETAILERS: dict[str, list[dict[str, Any]]] | None = None


def home_retailer(url: str, need: Need) -> bool:
    """A retailer of the hunt's country (asked-for, else home) that the source registry lists for this kind of
    thing (zalando.fi for a winter jacket): its pages are read before small shops'."""
    global _RETAILERS
    cc = country_of(need) or home_country()
    if not cc or need.kind != "product":
        return False
    if _RETAILERS is None:
        try:
            from agora import sources as _src
            idx: dict[str, list[dict[str, Any]]] = {}
            for rec in _src.load():
                if rec.get("kind") in ("retailer", "department_store", "shop") and "new" in (rec.get("lanes") or []):
                    idx.setdefault(str(rec.get("domain") or "").lower().removeprefix("www."), []).append(rec)
            _RETAILERS = idx
        except Exception:
            _RETAILERS = {}
    recs = _RETAILERS.get(domain_of(url))
    if not recs:
        return False
    try:
        from agora import marketplaces
        cats = set(marketplaces.categories_for(need.thing or ""))
    except Exception:
        cats = set()
    for rec in recs:
        if cc not in (rec.get("countries") or []):
            continue
        rc = set(rec.get("categories") or [])
        if not cats or cats & rc:
            return True
    return False
