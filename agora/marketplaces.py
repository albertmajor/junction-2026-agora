"""MARKETPLACES: direct search pages of the big European marketplaces and shops, and a code-only splitter
that cuts one search page's markdown into listings (no model call).

Written at Junction 2026 (round 8). Ported, with credit, from teammate Robert (rpaszekdev,
agora-junction-2026, same team): `SITES` (search URL templates per country and lane, tested live in his
research/platform-tests.md), `build_url`, and the splitter `split_rows` / `first_price` / `to_number` /
`find_image` with its per-site link patterns (`LISTING_URL`, `HEADING_TITLE`, `PRICE_LAST`). His
shelf/sources.json (193 European second-hand sources) became `SECOND_HAND`, a curated allow/boost list.
Adapted here: one `Site` record per site, per-country vinted/backmarket hosts, more currencies, query
normalisation per site language, canonical listing URLs, and the plan (`direct_pages`) the hunt reads.

Why: a web search spends one rate-limit token to *find* pages; a marketplace's own search page needs no
search at all and lists 20-50 listings. One markdown read (1 credit, 1 token) cut with code gives ~20
offers, where the JSON list read gave 8 for ~5 credits.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from urllib.parse import quote, quote_plus, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class Site:
    key: str
    country: str                  # ISO alpha-2, lower case ("fi"); the scrape is sent from there
    lane: str                     # used | refurbished | new | comparison
    template: str                 # {q} = quote_plus(query), {dash} = words joined by '-'
    listing: str | None           # regex on a listing link's URL; None = no splitter (JSON list read instead)
    lang: str = "en"              # ISO 639-1 of the site's listings (query normalisation)
    heading_title: bool = False   # title is a '## heading', price above it, link below (Schibsted sites)
    price_last: bool = False      # crossed-out comparison price first, the real one last
    itemlist: bool = False        # the page carries schema.org ItemList JSON-LD (free read, no token)
    verified: bool = True         # search URL returned listings live (Robert's platform tests, 13 Nov)
    bulky_ok: bool = True         # worth it for furniture etc. bought from abroad (no: local pickup only)
    vehicle: bool = False         # a cars category: its listings are vehicles (raw['category'] = 'vehicle')
    browse: str | None = None     # the category page itself, for a generic need ('car': every car, newest first)
    # its search / model pages carry a schema.org ItemList of the listings in the plain HTML (nettiauto): read free
    # first (no token), the paid markdown split only when that fetch fails. Planned as paid, so never over-planned.
    ldlist: bool = False

    @property
    def domain(self) -> str:
        host = urlsplit(self.template.replace("{q}", "x").replace("{dash}", "x")).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    @property
    def currency(self) -> str:
        return CURRENCY.get(self.country, "EUR")


SCHIBSTED = r"/recommerce/forsale/item/\d+"
VINTED_TLD = {"fi": "fi", "se": "se", "dk": "dk", "de": "de", "at": "at", "nl": "nl", "be": "be", "fr": "fr",
              "pl": "pl", "es": "es", "it": "it", "cz": "cz", "pt": "pt", "lt": "lt", "lu": "lu", "sk": "sk",
              "hu": "hu", "ro": "ro", "gr": "gr", "hr": "hr", "ie": "ie", "gb": "co.uk"}
VINTED_LANG = {"fi": "fi", "se": "sv", "dk": "da", "de": "de", "at": "de", "nl": "nl", "be": "nl", "fr": "fr",
               "pl": "pl", "es": "es", "it": "it", "cz": "cs", "pt": "pt"}

# Robert's SITES (+ his EXTRA_SITES and platform-test sites), one record each
_SITES: list[Site] = [
    # used: classifieds
    Site("tori", "fi", "used", "https://www.tori.fi/recommerce/forsale/search?q={q}", SCHIBSTED, "fi",
         heading_title=True, itemlist=True),
    Site("blocket", "se", "used", "https://www.blocket.se/recommerce/forsale/search?q={q}", SCHIBSTED, "sv",
         heading_title=True),
    Site("finn", "no", "used", "https://www.finn.no/recommerce/forsale/search?q={q}", SCHIBSTED, "no",
         heading_title=True),
    Site("dba", "dk", "used", "https://www.dba.dk/recommerce/forsale/search?q={q}", SCHIBSTED, "da",
         heading_title=True),
    Site("kleinanzeigen", "de", "used", "https://www.kleinanzeigen.de/s-{dash}/k0", r"/s-anzeige/", "de"),
    Site("marktplaats", "nl", "used", "https://www.marktplaats.nl/q/{q}/", r"/v/", "nl"),
    Site("2dehands", "be", "used", "https://www.2dehands.be/q/{q}/", r"/v/", "nl"),
    Site("olx_pl", "pl", "used", "https://www.olx.pl/oferty/q-{dash}/", r"/d/oferta/", "pl"),
    Site("gumtree", "gb", "used", "https://www.gumtree.com/search?q={q}", r"/p/", "en"),
    Site("leboncoin", "fr", "used", "https://www.leboncoin.fr/recherche?text={q}",
         r"/ad/[\w-]+/\d+|/[a-z_]+/\d+\.htm", "fr", verified=False),
    Site("wallapop", "es", "used", "https://es.wallapop.com/app/search?keywords={q}", r"/item/[\w-]+-\d+", "es",
         verified=False),
    Site("subito", "it", "used", "https://www.subito.it/annunci-italia/vendita/usato/?q={q}",
         r"/[\w-]+/[\w-]+-\d+\.htm", "it", verified=False),
    Site("willhaben", "at", "used", "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword={q}",
         r"/iad/kaufen-und-verkaufen/d/[\w-]+-\d+", "de", verified=False),
    Site("bazos_cz", "cz", "used", "https://www.bazos.cz/search.php?hledat={q}", r"/inzerat/\d+", "cs",
         verified=False),
    Site("ebay_uk", "gb", "used", "https://www.ebay.co.uk/sch/i.html?_nkw={q}", r"/itm/\d+", "en", verified=False),
    Site("ebay_de", "de", "used", "https://www.ebay.de/sch/i.html?_nkw={q}", r"/itm/\d+", "de", verified=False),
    # used: vinted, one host per country (fashion first, electronics and home too); never for bulky things
    *[Site(f"vinted_{cc}", cc, "used", f"https://www.vinted.{tld}/catalog?search_text={{q}}", r"/items/\d+",
           VINTED_LANG.get(cc, "en"), verified=(cc == "fi"), bulky_ok=False) for cc, tld in VINTED_TLD.items()],
    # refurbished
    Site("backmarket", "de", "refurbished", "https://www.backmarket.de/de-de/search?q={q}", r"/p/", "de",
         bulky_ok=False),
    Site("rebuy", "de", "refurbished", "https://www.rebuy.de/kaufen/suchen?q={q}", None, "de", bulky_ok=False),
    # new shops
    Site("verkkokauppa", "fi", "new", "https://www.verkkokauppa.com/fi/search?query={q}", r"/product/\d+", "fi"),
    Site("power_fi", "fi", "new", "https://www.power.fi/haku/?q={q}", r"/p-\d+", "fi"),
    Site("amazon_de", "de", "new", "https://www.amazon.de/s?k={q}", r"/dp/\w+", "de"),
    Site("cdiscount", "fr", "new", "https://www.cdiscount.com/search/10/{q}.html", r"/f-\d+", "fr",
         price_last=True),
    # vehicles: the cars categories (read first for a vehicle need; the general marketplaces still follow while
    # tokens last: every listing is judged on its own). Unverified search URLs are marked verified=False.
    # tori's cars: checked 14 Nov (eval r5) tori.fi/mobility/search/car answers HTTP 404 (Context.dev and plain
    # fetch), autot.tori.fi is an empty script shell (404 on every path) and tori's front page links cars to
    # autovex.fi (a sell-your-car service, no listings). Kept so site_for() still names the old links; never planned.
    Site("tori_autot", "fi", "used", "https://www.tori.fi/mobility/search/car?q={q}", r"/mobility/item/\d+", "fi",
         heading_title=True, verified=False, vehicle=True, browse="https://www.tori.fi/mobility/search/car"),
    # nettiauto: plain fetch checked 14 Nov (eval r5): nettiauto.com/volvo/v70 and /vaihtoautot answer 200 in 1.8-4.4 s
    # (~1 MB) with a schema.org CollectionPage > ItemList of 30+ Car items (url, price, color, mileage, year in the
    # name) and the total in AggregateOffer.offerCount: a free read (ldlist). ?q= and colour parameters are
    # ignored by the site (color=punainen / color=red / colour=10 gave the same cars), so colour is a boost.
    Site("nettiauto", "fi", "used", "https://www.nettiauto.com/vaihtoautot?q={q}", r"^/[\w-]+/[\w-]+/\d{6,}", "fi",
         verified=False, vehicle=True, browse="https://www.nettiauto.com/vaihtoautot", ldlist=True),
    Site("autotalli", "fi", "used", "https://www.autotalli.com/vaihtoautot/listaa?hakusana={q}",
         r"/vaihtoautot/tiedot/\d+", "fi", verified=False, vehicle=True,
         browse="https://www.autotalli.com/vaihtoautot/listaa"),
    Site("blocket_bil", "se", "used", "https://www.blocket.se/mobility/search/car?q={q}", r"/mobility/item/\d+", "sv",
         heading_title=True, verified=False, vehicle=True, browse="https://www.blocket.se/mobility/search/car"),
    Site("finn_bil", "no", "used", "https://www.finn.no/mobility/search/car?q={q}", r"/mobility/item/\d+", "no",
         heading_title=True, verified=False, vehicle=True, browse="https://www.finn.no/mobility/search/car"),
    Site("bilbasen", "dk", "used", "https://www.bilbasen.dk/brugt/bil?free={q}", r"/brugt/bil/[\w/-]+/\d+", "da",
         verified=False, vehicle=True, browse="https://www.bilbasen.dk/brugt/bil"),
    Site("mobile_de", "de", "used",
         "https://suchen.mobile.de/fahrzeuge/search.html?isSearchRequest=true&s=Car&vc=Car&q={q}",
         r"/fahrzeuge/details\.html", "de", verified=False, vehicle=True,
         browse="https://suchen.mobile.de/fahrzeuge/search.html?isSearchRequest=true&s=Car&vc=Car"),
    Site("kleinanzeigen_autos", "de", "used", "https://www.kleinanzeigen.de/s-autos/{dash}/k0c216", r"/s-anzeige/",
         "de", verified=False, vehicle=True, browse="https://www.kleinanzeigen.de/s-autos/c216"),
    Site("marktplaats_auto", "nl", "used", "https://www.marktplaats.nl/l/auto-s/q/{q}/", r"/v/auto-s/", "nl",
         verified=False, vehicle=True, browse="https://www.marktplaats.nl/l/auto-s/"),
    # AutoScout24: its list pages carry the 20 listings of the page in the plain HTML (Next.js __NEXT_DATA__
    # pageProps.listings: url, price, make/model, km, first registration, the seller's town; the colour in the
    # listing's URL slug) and the total in pageProps.numberOfResults (saved 14 Nov, tests/fixtures/cars): free first
    *[Site(f"autoscout24_{cc}", cc, "used", f"https://www.autoscout24.{tld}/lst?atype=C&q={{q}}", rf"/{seg}/[\w-]+",
           lang, verified=False, vehicle=True, browse=f"https://www.autoscout24.{tld}/lst?atype=C", ldlist=True)
      for cc, tld, seg, lang in (("de", "de", "angebote", "de"), ("nl", "nl", "aanbod", "nl"),
                                 ("it", "it", "annunci", "it"), ("be", "be", "aanbod", "nl"),
                                 ("at", "at", "angebote", "de"))],
    # price comparison: 'ab €X' is not an offer (discover.JUNK_DOMAINS); kept for reference, never planned
    Site("idealo", "de", "comparison", "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
         r"OffersOfProduct", "de"),
    Site("pricerunner", "se", "comparison", "https://www.pricerunner.se/results?q={q}", r"/pl/", "sv"),
]


def _registry_sites() -> list[Site]:
    """Verified search pages from the source registry (agora/sources, scripts/onboard_sources.py) for sites
    not hand-listed above. verified_free ones read with a plain fetch (no token)."""
    try:
        from agora import sources as _src
    except Exception:              # registry missing or broken: the hand list still works
        return []
    have = {s.domain for s in _SITES}
    out: list[Site] = []
    templates: set[str] = set()
    try:
        for rec in _src.load():
            if rec.get("status") not in ("verified_free", "verified_contextdev") or rec.get("domain") in have:
                continue
            kw = _src.as_site_kwargs(rec)
            if kw and kw["template"] not in templates:      # one Site per search URL (amazon.co.uk twice)
                templates.add(kw["template"])
                out.append(Site(**{k: v for k, v in kw.items() if k in Site.__dataclass_fields__}))
    except Exception:
        return out
    return out


_SITES += _registry_sites()
SITES: dict[str, Site] = {s.key: s for s in _SITES}
_REC_CACHE: dict[str, dict | None] = {}


def registry_record(site: Site) -> dict | None:
    """The source-registry record of this site (agora.sources), else None. Cached."""
    if site.key not in _REC_CACHE:
        try:
            from agora import sources as _src
            rec = _src.get(site.key[4:]) if site.key.startswith("src_") else _src.for_url(build_url(site, "x"))
        except Exception:
            rec = None
        _REC_CACHE[site.key] = rec if rec and rec.get("status") == "verified_free" and rec.get("free_fetch") else None
    return _REC_CACHE[site.key]


def free_site(site: Site) -> bool:
    """Read without a Context.dev token: tori's ItemList, or a registry source verified readable by plain fetch
    (vinted, marktplaats, kleinanzeigen, blocket, finn, dba ...: rows cut from the HTML by agora.sources)."""
    return site.itemlist or registry_record(site) is not None


# taxonomy root (agora.taxonomy) -> source-registry categories: which free sources to read first (priority only)
ROOT_CATEGORIES = {"electronics": ["electronics", "computers", "phones", "cameras"], "appliances": ["appliances"],
                   "fashion": ["fashion", "shoes"], "home-garden": ["home", "garden"], "furniture": ["furniture", "home"],
                   "diy": ["diy", "tools"], "baby-kids": ["kids"], "toys-games": ["toys", "kids", "games"],
                   "sports-outdoors": ["sports", "bikes"], "media": ["books", "media"], "vehicles": ["cars", "vehicles"],
                   "hobbies": ["collectibles"], "pets": ["pets"], "health-beauty": ["beauty", "health"]}
MAX_REGISTRY_FREE = 3        # extra free registry sources per lane (no token, but page time)


def categories_for(thing: str) -> list[str]:
    try:
        from agora.need import vehicle_need
        if vehicle_need(thing):
            return ["cars", "vehicles"]
        from agora import taxonomy
        c = taxonomy.classify(thing)
    except Exception:
        return []
    if not c or (c.get("confidence") or 0) < 0.45:
        return []
    return ROOT_CATEGORIES.get((c.get("path_ids") or [""])[0], [])
CURRENCY = {"se": "SEK", "no": "NOK", "dk": "DKK", "pl": "PLN", "gb": "GBP", "cz": "CZK", "ch": "CHF",
            "hu": "HUF", "ro": "RON"}

# what to read directly, per country (first = the country's own big marketplace)
HOME_USED: dict[str, tuple[str, ...]] = {
    "fi": ("tori",), "se": ("blocket",), "no": ("finn",), "dk": ("dba",), "de": ("kleinanzeigen",),
    "at": ("willhaben", "kleinanzeigen"), "nl": ("marktplaats",), "be": ("2dehands",), "pl": ("olx_pl",),
    "fr": ("leboncoin",), "es": ("wallapop",), "it": ("subito",), "gb": ("gumtree", "ebay_uk"),
    "cz": ("bazos_cz",),
}
EU_USED = ("kleinanzeigen", "vinted")        # the big EU ones read for everybody (vinted = the home country's host)
HOME_NEW: dict[str, tuple[str, ...]] = {"fi": ("verkkokauppa", "power_fi"), "de": ("amazon_de",),
                                         "at": ("amazon_de",), "fr": ("cdiscount",)}
EU_REFURB = ("backmarket",)


def vinted_for(cc: str | None) -> Site | None:
    return SITES.get(f"vinted_{cc}") if cc in VINTED_TLD else None


def build_url(site: Site, query: str) -> str:
    """Robert's build_url: {q} = 'airpods+pro+2', {dash} = 'airpods-pro-2'."""
    words = query.strip().split()
    return site.template.format(q=quote_plus(query.strip()), dash="-".join(quote(w) for w in words))


_HOST_SITE: dict[str, Site] = {}
_HOST_SITES: dict[str, list[Site]] = {}
for _s in _SITES:
    _HOST_SITE.setdefault(_s.domain, _s)
    _HOST_SITES.setdefault(_s.domain, []).append(_s)
for _s in _SITES:
    if _s.browse:
        _HOST_SITES.setdefault(urlsplit(_s.browse).netloc.lower().removeprefix("www."), [])


def site_for(url: str) -> Site | None:
    """The registry site whose search page this is, else None: our own search URL, or another search /
    category page of that site a web search found (kleinanzeigen /s-haus-garten/ikea-kallax/k0c80): same page
    layout, so the same splitter."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    s = _HOST_SITE.get(host)
    if s is None:
        return None
    for cand in _HOST_SITES.get(host, [s]):     # tori.fi: the cars category before the general search
        if cand.vehicle and (_own_search(cand, parts) or (cand.browse and url.split("?")[0].rstrip("/")
                                                           == cand.browse.split("?")[0].rstrip("/"))):
            return cand
    if _own_search(s, parts):
        return s
    if s.listing and re.search(s.listing, parts.path):
        return None                   # one listing, not a search page
    if s.vehicle and _vehicle_list_path(parts.path):
        return s                      # a cars site's make / model page (nettiauto.com/volvo/v70, autoscout24 /lst/volvo)
    from agora.discover import is_list_page
    return s if is_list_page(url) else None


def _vehicle_list_path(path: str) -> bool:
    """A cars site's list path: make / model words, no car's own id (nettiauto.com/volvo/v70, /vaihtoautot,
    autoscout24 /lst/volvo/v70), not its front page or a bare language root (/en)."""
    segs = [p for p in path.split("/") if p]
    if not segs or (len(segs) == 1 and len(segs[0]) <= 3):
        return False
    return len(segs) <= 4 and not re.search(r"\d{5,}", path)


def _own_search(s: Site, parts) -> bool:
    tpl = urlsplit(build_url(s, "x"))
    if "{dash}" in s.template:        # kleinanzeigen /s-<q>/k0, olx /oferty/q-<q>/
        head = tpl.path.split("x")[0]
        tail = tpl.path.split("x")[-1]
        return parts.path.startswith(head) and parts.path.rstrip("/").endswith(tail.rstrip("/"))
    if tpl.query:                     # ?q= / ?search_text= / ?keywords=
        key = tpl.query.split("=")[0]
        return parts.path.rstrip("/") == tpl.path.rstrip("/") and f"{key}=" in parts.query
    head = tpl.path.split("x")[0]      # marktplaats /q/<q>/, cdiscount /search/10/<q>.html
    return parts.path.startswith(head)


# --------------------------------------------------------------------------- second-hand sources (allow/boost)
# Robert's shelf/sources.json (193 European second-hand sources), reduced to domain -> (country, type).
# Used as an allow/boost list: a search result on one of these domains is a second-hand source.
SECOND_HAND: dict[str, tuple[str, str]] = {}
_SOURCES = """
vinted.com:eu:resale ebay.com:eu:resale wallapop.com:es:classifieds shpock.com:gb:classifieds
etsy.com:eu:auction catawiki.com:eu:auction auctionet.com:eu:auction gumtree.com:gb:classifieds
preloved.co.uk:gb:classifieds freeads.co.uk:gb:classifieds friday-ad.co.uk:gb:classifieds adverts.ie:ie:classifieds
donedeal.ie:ie:classifieds leboncoin.fr:fr:classifieds paruvendu.fr:fr:classifieds label-emmaus.co:fr:resale
easycash.fr:fr:retailer 2dehands.be:be:classifieds marktplaats.nl:nl:classifieds markt2.nl:nl:classifieds
hetgoed.nl:nl:retailer kleinanzeigen.de:de:classifieds quoka.de:de:classifieds markt.de:de:classifieds
hood.de:de:resale willhaben.at:at:classifieds ricardo.ch:ch:resale tutti.ch:ch:classifieds anibis.ch:ch:classifieds
olx.pl:pl:classifieds allegrolokalnie.pl:pl:resale sprzedajemy.pl:pl:classifieds bazos.cz:cz:classifieds
sbazar.cz:cz:classifieds aukro.cz:cz:resale bazos.sk:sk:classifieds bazar.sk:sk:classifieds jofogas.hu:hu:classifieds
vatera.hu:hu:resale hardverapro.hu:hu:classifieds tori.fi:fi:classifieds huuto.net:fi:resale kiertonet.fi:fi:auction
huutokaupat.com:fi:auction kauppa.kierratyskeskus.fi:fi:retailer blocket.se:se:classifieds tradera.com:se:resale
plick.se:se:specialist bukowskis.com:se:auction finn.no:no:classifieds tise.com:no:specialist dba.dk:dk:classifieds
guloggratis.dk:dk:classifieds reshopper.com:dk:specialist bland.is:is:classifieds osta.ee:ee:resale
okidoki.ee:ee:classifieds yaga.ee:ee:specialist ss.com:lv:classifieds andelemandele.lv:lv:specialist
skelbiu.lt:lt:classifieds alio.lt:lt:classifieds milanuncios.com:es:classifieds todocoleccion.net:es:auction
cashconverters.es:es:retailer micolet.com:es:retailer olx.pt:pt:classifieds custojusto.pt:pt:classifieds
subito.it:it:classifieds bakeca.it:it:classifieds mercatinousato.com:it:retailer mercatopoli.it:it:retailer
maltapark.com:mt:classifieds vendora.gr:gr:classifieds xe.gr:gr:classifieds bazaraki.com:cy:classifieds
bolha.com:si:classifieds njuskalo.hr:hr:classifieds oglasnik.hr:hr:classifieds olx.ro:ro:classifieds
publi24.ro:ro:classifieds okazii.ro:ro:resale lajumate.ro:ro:classifieds olx.bg:bg:classifieds bazar.bg:bg:classifieds
alo.bg:bg:classifieds backmarket.com:eu:refurbished refurbed.com:eu:refurbished swappie.com:eu:retailer
rebuy.de:de:retailer asgoodasnew.de:de:retailer clevertronic.de:de:retailer certideal.com:fr:retailer
recommerce.com:fr:retailer uk.webuy.com:gb:retailer musicmagpie.co.uk:gb:retailer cashconverters.co.uk:gb:retailer
depop.com:eu:specialist vestiairecollective.com:eu:specialist sellpy.com:eu:retailer selency.fr:fr:specialist
whoppah.com:eu:specialist pamono.eu:eu:specialist vinterior.co:gb:specialist buycycle.com:eu:specialist
upway.co:eu:retailer troc-velo.com:fr:specialist tuvalum.eu:eu:retailer campsider.com:fr:specialist
mpb.com:eu:retailer kamerastore.com:fi:retailer wexphotovideo.com:gb:retailer reverb.com:eu:specialist
musamaailma.fi:fi:retailer worldofbooks.com:gb:retailer medimops.de:de:retailer momox-shop.fr:fr:retailer
abebooks.com:eu:specialist zvab.com:de:specialist discogs.com:eu:specialist cardmarket.com:eu:specialist
bricklink.com:eu:specialist chrono24.com:eu:specialist watchfinder.com:gb:retailer
"""
for _tok in _SOURCES.split():
    _d, _cc, _t = _tok.split(":")
    SECOND_HAND[_d] = (_cc, _t)


def second_hand(domain: str) -> tuple[str, str] | None:
    """(country, type) when the domain (or its parent, or another TLD of a multi-country brand) is a known
    second-hand source."""
    d = domain.lower().removeprefix("www.")
    while d:
        if d in SECOND_HAND:
            return SECOND_HAND[d]
        if "." not in d:
            break
        d = d.split(".", 1)[1]
    brand = domain.lower().removeprefix("www.").split(".")[0]
    for k, v in SECOND_HAND.items():       # vinted.fi, backmarket.de, refurbed.at ...: brand on another TLD
        if v[0] == "eu" and k.split(".")[0] == brand:
            return v
    return None


# --------------------------------------------------------------------------- query per site language

# generic nouns: dropped when the query has a brand/model word ('ikea kallax shelf' -> 'ikea kallax',
# sellers write 'Kallax-hylly', 'Kallax Regal'), translated when the query is only generic ('road bike')
WORDS: dict[str, dict[str, str]] = {
    "shelf": {"fi": "hylly", "sv": "hylla", "no": "hylle", "da": "reol", "de": "regal", "nl": "kast", "pl": "regał",
              "fr": "étagère", "es": "estantería", "it": "scaffale", "cs": "regál"},
    "shelving unit": {"fi": "hylly", "sv": "hylla", "no": "hylle", "da": "reol", "de": "regal", "nl": "kast",
                      "pl": "regał", "fr": "étagère", "es": "estantería", "it": "scaffale", "cs": "regál"},
    "bookcase": {"fi": "kirjahylly", "sv": "bokhylla", "no": "bokhylle", "da": "bogreol", "de": "bücherregal",
                 "nl": "boekenkast", "pl": "regał na książki", "fr": "bibliothèque", "es": "librería",
                 "it": "libreria", "cs": "knihovna"},
    "sofa": {"fi": "sohva", "sv": "soffa", "no": "sofa", "da": "sofa", "de": "sofa", "nl": "bank", "pl": "sofa",
             "fr": "canapé", "es": "sofá", "it": "divano", "cs": "pohovka"},
    "couch": {"fi": "sohva", "sv": "soffa", "no": "sofa", "da": "sofa", "de": "sofa", "nl": "bank", "pl": "kanapa",
              "fr": "canapé", "es": "sofá", "it": "divano", "cs": "gauč"},
    "table": {"fi": "pöytä", "sv": "bord", "no": "bord", "da": "bord", "de": "tisch", "nl": "tafel", "pl": "stół",
              "fr": "table", "es": "mesa", "it": "tavolo", "cs": "stůl"},
    "desk": {"fi": "työpöytä", "sv": "skrivbord", "no": "skrivebord", "da": "skrivebord", "de": "schreibtisch",
             "nl": "bureau", "pl": "biurko", "fr": "bureau", "es": "escritorio", "it": "scrivania", "cs": "psací stůl"},
    "chair": {"fi": "tuoli", "sv": "stol", "no": "stol", "da": "stol", "de": "stuhl", "nl": "stoel", "pl": "krzesło",
              "fr": "chaise", "es": "silla", "it": "sedia", "cs": "židle"},
    "office chair": {"fi": "työtuoli", "sv": "kontorsstol", "no": "kontorstol", "da": "kontorstol",
                     "de": "bürostuhl", "nl": "bureaustoel", "pl": "krzesło biurowe", "fr": "chaise de bureau",
                     "es": "silla de oficina", "it": "sedia da ufficio", "cs": "kancelářská židle"},
    "bed": {"fi": "sänky", "sv": "säng", "no": "seng", "da": "seng", "de": "bett", "nl": "bed", "pl": "łóżko",
            "fr": "lit", "es": "cama", "it": "letto", "cs": "postel"},
    "wardrobe": {"fi": "vaatekaappi", "sv": "garderob", "no": "garderobe", "da": "garderobe", "de": "kleiderschrank",
                 "nl": "kledingkast", "pl": "szafa", "fr": "armoire", "es": "armario", "it": "armadio", "cs": "skříň"},
    "lamp": {"fi": "valaisin", "sv": "lampa", "no": "lampe", "da": "lampe", "de": "lampe", "nl": "lamp", "pl": "lampa",
             "fr": "lampe", "es": "lámpara", "it": "lampada", "cs": "lampa"},
    "bike": {"fi": "polkupyörä", "sv": "cykel", "no": "sykkel", "da": "cykel", "de": "fahrrad", "nl": "fiets",
             "pl": "rower", "fr": "vélo", "es": "bicicleta", "it": "bicicletta", "cs": "kolo"},
    "bicycle": {"fi": "polkupyörä", "sv": "cykel", "no": "sykkel", "da": "cykel", "de": "fahrrad", "nl": "fiets",
                "pl": "rower", "fr": "vélo", "es": "bicicleta", "it": "bicicletta", "cs": "kolo"},
    "city bike": {"fi": "kaupunkipyörä", "sv": "stadscykel", "no": "bysykkel", "da": "citybike", "de": "citybike",
                  "nl": "stadsfiets", "pl": "rower miejski", "fr": "vélo de ville", "es": "bicicleta de paseo",
                  "it": "bici da città", "cs": "městské kolo"},
    "mountain bike": {"fi": "maastopyörä", "sv": "mountainbike", "no": "terrengsykkel", "da": "mountainbike",
                      "de": "mountainbike", "nl": "mountainbike", "pl": "rower górski", "fr": "vtt",
                      "es": "bicicleta de montaña", "it": "mountain bike", "cs": "horské kolo"},
    "kids bike": {"fi": "lasten polkupyörä", "sv": "barncykel", "no": "barnesykkel", "da": "børnecykel",
                  "de": "kinderfahrrad", "nl": "kinderfiets", "pl": "rower dziecięcy", "fr": "vélo enfant",
                  "es": "bicicleta infantil", "it": "bici bambino", "cs": "dětské kolo"},
    "cargo bike": {"fi": "tavarapyörä", "sv": "lådcykel", "no": "lastesykkel", "da": "ladcykel", "de": "lastenrad",
                   "nl": "bakfiets", "pl": "rower cargo", "fr": "vélo cargo", "es": "bicicleta de carga",
                   "it": "cargo bike", "cs": "nákladní kolo"},
    "road bike": {"fi": "maantiepyörä", "sv": "racercykel", "no": "landeveissykkel", "da": "racercykel",
                  "de": "rennrad", "nl": "racefiets", "pl": "rower szosowy", "fr": "vélo de route",
                  "es": "bicicleta de carretera", "it": "bici da corsa", "cs": "silniční kolo"},
    "e-bike": {"fi": "sähköpyörä", "sv": "elcykel", "no": "elsykkel", "da": "elcykel", "de": "e-bike",
               "nl": "e-bike", "pl": "rower elektryczny", "fr": "vélo électrique", "es": "bicicleta eléctrica",
               "it": "bici elettrica", "cs": "elektrokolo"},
    "stroller": {"fi": "rattaat", "sv": "barnvagn", "no": "barnevogn", "da": "barnevogn", "de": "kinderwagen",
                 "nl": "kinderwagen", "pl": "wózek", "fr": "poussette", "es": "carrito", "it": "passeggino",
                 "cs": "kočárek"},
    "headphones": {"fi": "kuulokkeet", "sv": "hörlurar", "no": "hodetelefoner", "da": "høretelefoner",
                   "de": "kopfhörer", "nl": "koptelefoon", "pl": "słuchawki", "fr": "casque", "es": "auriculares",
                   "it": "cuffie", "cs": "sluchátka"},
    "earbuds": {"fi": "kuulokkeet", "sv": "hörlurar", "no": "ørepropper", "da": "høretelefoner", "de": "kopfhörer",
                "nl": "oordopjes", "pl": "słuchawki", "fr": "écouteurs", "es": "auriculares", "it": "auricolari",
                "cs": "sluchátka"},
    "phone": {"fi": "puhelin", "sv": "telefon", "no": "telefon", "da": "telefon", "de": "handy", "nl": "telefoon",
              "pl": "telefon", "fr": "téléphone", "es": "móvil", "it": "telefono", "cs": "telefon"},
    "laptop": {"fi": "kannettava", "sv": "laptop", "no": "laptop", "da": "bærbar", "de": "laptop", "nl": "laptop",
               "pl": "laptop", "fr": "ordinateur portable", "es": "portátil", "it": "portatile", "cs": "notebook"},
    "camera": {"fi": "kamera", "sv": "kamera", "no": "kamera", "da": "kamera", "de": "kamera", "nl": "camera",
               "pl": "aparat", "fr": "appareil photo", "es": "cámara", "it": "fotocamera", "cs": "fotoaparát"},
    "lens": {"fi": "objektiivi", "sv": "objektiv", "no": "objektiv", "da": "objektiv", "de": "objektiv",
             "nl": "objectief", "pl": "obiektyw", "fr": "objectif", "es": "objetivo", "it": "obiettivo",
             "cs": "objektiv"},
    "watch": {"fi": "kello", "sv": "klocka", "no": "klokke", "da": "ur", "de": "uhr", "nl": "horloge", "pl": "zegarek",
              "fr": "montre", "es": "reloj", "it": "orologio", "cs": "hodinky"},
    "tv": {"fi": "televisio", "sv": "tv", "no": "tv", "da": "tv", "de": "fernseher", "nl": "televisie",
           "pl": "telewizor", "fr": "téléviseur", "es": "televisor", "it": "televisore", "cs": "televize"},
    "monitor": {"fi": "näyttö", "sv": "skärm", "no": "skjerm", "da": "skærm", "de": "monitor", "nl": "monitor",
                "pl": "monitor", "fr": "écran", "es": "monitor", "it": "monitor", "cs": "monitor"},
    "vacuum": {"fi": "imuri", "sv": "dammsugare", "no": "støvsuger", "da": "støvsuger", "de": "staubsauger",
               "nl": "stofzuiger", "pl": "odkurzacz", "fr": "aspirateur", "es": "aspiradora", "it": "aspirapolvere",
               "cs": "vysavač"},
    "vacuum cleaner": {"fi": "imuri", "sv": "dammsugare", "no": "støvsuger", "da": "støvsuger", "de": "staubsauger",
                       "nl": "stofzuiger", "pl": "odkurzacz", "fr": "aspirateur", "es": "aspiradora",
                       "it": "aspirapolvere", "cs": "vysavač"},
    "coffee machine": {"fi": "kahvinkeitin", "sv": "kaffemaskin", "no": "kaffemaskin", "da": "kaffemaskine",
                       "de": "kaffeemaschine", "nl": "koffiemachine", "pl": "ekspres do kawy", "fr": "machine à café",
                       "es": "cafetera", "it": "macchina da caffè", "cs": "kávovar"},
    "espresso machine": {"fi": "espressokeitin", "sv": "espressomaskin", "no": "espressomaskin",
                         "da": "espressomaskine", "de": "siebträgermaschine", "nl": "espressomachine",
                         "pl": "ekspres kolbowy", "fr": "machine expresso", "es": "cafetera espresso",
                         "it": "macchina espresso", "cs": "pákový kávovar"},
    "washing machine": {"fi": "pesukone", "sv": "tvättmaskin", "no": "vaskemaskin", "da": "vaskemaskine",
                        "de": "waschmaschine", "nl": "wasmachine", "pl": "pralka", "fr": "lave-linge",
                        "es": "lavadora", "it": "lavatrice", "cs": "pračka"},
    "fridge": {"fi": "jääkaappi", "sv": "kylskåp", "no": "kjøleskap", "da": "køleskab", "de": "kühlschrank",
               "nl": "koelkast", "pl": "lodówka", "fr": "réfrigérateur", "es": "nevera", "it": "frigorifero",
               "cs": "lednice"},
    "drill": {"fi": "porakone", "sv": "borrmaskin", "no": "drill", "da": "boremaskine", "de": "bohrmaschine",
              "nl": "boormachine", "pl": "wiertarka", "fr": "perceuse", "es": "taladro", "it": "trapano",
              "cs": "vrtačka"},
    "guitar": {"fi": "kitara", "sv": "gitarr", "no": "gitar", "da": "guitar", "de": "gitarre", "nl": "gitaar",
               "pl": "gitara", "fr": "guitare", "es": "guitarra", "it": "chitarra", "cs": "kytara"},
    "speaker": {"fi": "kaiutin", "sv": "högtalare", "no": "høyttaler", "da": "højttaler", "de": "lautsprecher",
                "nl": "speaker", "pl": "głośnik", "fr": "enceinte", "es": "altavoz", "it": "altoparlante",
                "cs": "reproduktor"},
    "tablet": {"fi": "tabletti", "sv": "surfplatta", "no": "nettbrett", "da": "tablet", "de": "tablet",
               "nl": "tablet", "pl": "tablet", "fr": "tablette", "es": "tableta", "it": "tablet", "cs": "tablet"},
    "console": {"fi": "pelikonsoli", "sv": "spelkonsol", "no": "spillkonsoll", "da": "spillekonsol",
                "de": "spielkonsole", "nl": "spelcomputer", "pl": "konsola", "fr": "console", "es": "consola",
                "it": "console", "cs": "konzole"},
    "jacket": {"fi": "takki", "sv": "jacka", "no": "jakke", "da": "jakke", "de": "jacke", "nl": "jas", "pl": "kurtka",
               "fr": "veste", "es": "chaqueta", "it": "giacca", "cs": "bunda"},
    "shoes": {"fi": "kengät", "sv": "skor", "no": "sko", "da": "sko", "de": "schuhe", "nl": "schoenen", "pl": "buty",
              "fr": "chaussures", "es": "zapatos", "it": "scarpe", "cs": "boty"},
    "tent": {"fi": "teltta", "sv": "tält", "no": "telt", "da": "telt", "de": "zelt", "nl": "tent", "pl": "namiot",
             "fr": "tente", "es": "tienda de campaña", "it": "tenda", "cs": "stan"},
    "skis": {"fi": "sukset", "sv": "skidor", "no": "ski", "da": "ski", "de": "ski", "nl": "ski's", "pl": "narty",
             "fr": "skis", "es": "esquís", "it": "sci", "cs": "lyže"},
    "printer": {"fi": "tulostin", "sv": "skrivare", "no": "skriver", "da": "printer", "de": "drucker",
                "nl": "printer", "pl": "drukarka", "fr": "imprimante", "es": "impresora", "it": "stampante",
                "cs": "tiskárna"},
    # coverage round (owner: 'way more we can find'): the generic nouns people type, in each site's language
    "mobile phone": {"fi": "puhelin", "sv": "mobiltelefon", "no": "mobiltelefon", "da": "mobiltelefon",
                     "de": "handy", "nl": "telefoon", "pl": "telefon", "fr": "téléphone", "es": "móvil",
                     "it": "cellulare", "cs": "mobil"},
    "smartphone": {"fi": "älypuhelin", "sv": "smartphone", "no": "smarttelefon", "da": "smartphone",
                   "de": "smartphone", "nl": "smartphone", "pl": "smartfon", "fr": "smartphone", "es": "smartphone",
                   "it": "smartphone", "cs": "smartphone"},
    "winter jacket": {"fi": "talvitakki", "sv": "vinterjacka", "no": "vinterjakke", "da": "vinterjakke",
                      "de": "winterjacke", "nl": "winterjas", "pl": "kurtka zimowa", "fr": "veste d'hiver",
                      "es": "chaqueta de invierno", "it": "giacca invernale", "cs": "zimní bunda"},
    "coat": {"fi": "takki", "sv": "rock", "no": "frakk", "da": "frakke", "de": "mantel", "nl": "jas", "pl": "płaszcz",
             "fr": "manteau", "es": "abrigo", "it": "cappotto", "cs": "kabát"},
    "baby stroller": {"fi": "lastenvaunut", "sv": "barnvagn", "no": "barnevogn", "da": "barnevogn",
                      "de": "kinderwagen", "nl": "kinderwagen", "pl": "wózek dziecięcy", "fr": "poussette",
                      "es": "cochecito", "it": "passeggino", "cs": "kočárek"},
    "pram": {"fi": "lastenvaunut", "sv": "barnvagn", "no": "barnevogn", "da": "barnevogn", "de": "kinderwagen",
             "nl": "kinderwagen", "pl": "wózek", "fr": "landau", "es": "cochecito", "it": "carrozzina",
             "cs": "kočárek"},
    "car seat": {"fi": "turvaistuin", "sv": "bilbarnstol", "no": "bilstol", "da": "autostol", "de": "kindersitz",
                 "nl": "autostoel", "pl": "fotelik", "fr": "siège auto", "es": "silla de coche",
                 "it": "seggiolino auto", "cs": "autosedačka"},
    "kitchen table": {"fi": "ruokapöytä", "sv": "köksbord", "no": "kjøkkenbord", "da": "køkkenbord",
                      "de": "esstisch", "nl": "eettafel", "pl": "stół kuchenny", "fr": "table de cuisine",
                      "es": "mesa de cocina", "it": "tavolo da cucina", "cs": "kuchyňský stůl"},
    "dining table": {"fi": "ruokapöytä", "sv": "matbord", "no": "spisebord", "da": "spisebord", "de": "esstisch",
                     "nl": "eettafel", "pl": "stół", "fr": "table à manger", "es": "mesa de comedor",
                     "it": "tavolo da pranzo", "cs": "jídelní stůl"},
    "coffee table": {"fi": "sohvapöytä", "sv": "soffbord", "no": "salongbord", "da": "sofabord",
                     "de": "couchtisch", "nl": "salontafel", "pl": "stolik kawowy", "fr": "table basse",
                     "es": "mesa de centro", "it": "tavolino", "cs": "konferenční stolek"},
    "armchair": {"fi": "nojatuoli", "sv": "fåtölj", "no": "lenestol", "da": "lænestol", "de": "sessel",
                 "nl": "fauteuil", "pl": "fotel", "fr": "fauteuil", "es": "sillón", "it": "poltrona", "cs": "křeslo"},
    "mattress": {"fi": "patja", "sv": "madrass", "no": "madrass", "da": "madras", "de": "matratze", "nl": "matras",
                 "pl": "materac", "fr": "matelas", "es": "colchón", "it": "materasso", "cs": "matrace"},
    "dresser": {"fi": "lipasto", "sv": "byrå", "no": "kommode", "da": "kommode", "de": "kommode", "nl": "ladekast",
                "pl": "komoda", "fr": "commode", "es": "cómoda", "it": "cassettiera", "cs": "komoda"},
    "rug": {"fi": "matto", "sv": "matta", "no": "teppe", "da": "tæppe", "de": "teppich", "nl": "vloerkleed",
            "pl": "dywan", "fr": "tapis", "es": "alfombra", "it": "tappeto", "cs": "koberec"},
    "mirror": {"fi": "peili", "sv": "spegel", "no": "speil", "da": "spejl", "de": "spiegel", "nl": "spiegel",
               "pl": "lustro", "fr": "miroir", "es": "espejo", "it": "specchio", "cs": "zrcadlo"},
    "freezer": {"fi": "pakastin", "sv": "frys", "no": "fryser", "da": "fryser", "de": "gefrierschrank",
                "nl": "vriezer", "pl": "zamrażarka", "fr": "congélateur", "es": "congelador", "it": "congelatore",
                "cs": "mraznička"},
    "dishwasher": {"fi": "astianpesukone", "sv": "diskmaskin", "no": "oppvaskmaskin", "da": "opvaskemaskine",
                   "de": "geschirrspüler", "nl": "vaatwasser", "pl": "zmywarka", "fr": "lave-vaisselle",
                   "es": "lavavajillas", "it": "lavastoviglie", "cs": "myčka"},
    "treadmill": {"fi": "juoksumatto", "sv": "löpband", "no": "tredemølle", "da": "løbebånd", "de": "laufband",
                  "nl": "loopband", "pl": "bieżnia", "fr": "tapis de course", "es": "cinta de correr",
                  "it": "tapis roulant", "cs": "běžecký pás"},
    "smartwatch": {"fi": "älykello", "sv": "smartklocka", "no": "smartklokke", "da": "smartwatch",
                   "de": "smartwatch", "nl": "smartwatch", "pl": "smartwatch", "fr": "montre connectée",
                   "es": "smartwatch", "it": "smartwatch", "cs": "chytré hodinky"},
    "backpack": {"fi": "reppu", "sv": "ryggsäck", "no": "ryggsekk", "da": "rygsæk", "de": "rucksack",
                 "nl": "rugzak", "pl": "plecak", "fr": "sac à dos", "es": "mochila", "it": "zaino", "cs": "batoh"},
    "snowboard": {"fi": "lumilauta", "sv": "snowboard", "no": "snowboard", "da": "snowboard", "de": "snowboard",
                  "nl": "snowboard", "pl": "deska snowboardowa", "fr": "snowboard", "es": "snowboard",
                  "it": "snowboard", "cs": "snowboard"},
}
# words that only say which kind of the noun ('winter jacket', 'kitchen table', 'baby stroller'): with nothing else
# besides the noun the query is the noun, translated (they are not a brand or model that carries the search)
MODIFIERS = re.compile(r"\b(?:winter|summer|spring|autumn|rain|warm|down|waterproof|kitchen|dining|living|room|"
                       r"bedroom|bathroom|garden|outdoor|indoor|patio|baby|toddler|infant|child|kids'?|mobile|"
                       r"cell|smart|cordless|wireless|portable|leather|fabric|folding|double|single|corner|"
                       r"modern|classic|new|used|cheap|nice|good|large|small|big|little|light|heavy|soft|hard|"
                       r"running|hiking|walking|ski|sports?|casual|formal|men|women|unisex|girl|boy|teen)\b", re.I)
# words that say how, not what: never part of a marketplace search
FILLER = re.compile(r"\b(?:used|second[- ]hand|secondhand|pre[- ]owned|refurbished|refurb|new|brand new|cheap|"
                    r"cheapest|buy|for sale|deal|best price|käytetty|gebraucht|neu|begagnad|brukt|brugt|"
                    r"tweedehands|occasion|usato|usado|używany)\b", re.I)
# words that describe but do not name a thing: 'city bike with basket' minus 'bike' is not a search for 'city'
DESCRIPTORS = re.compile(r"\b(?:city|urban|kids?|children'?s?|women'?s?|men'?s?|ladies|lady|girls?|boys?|electric|"
                         r"mountain|road|gaming|office|wooden|wood|white|black|grey|gray|red|blue|green|small|large|"
                         r"big|mini|old|vintage|retro|good|nice|with|without|and|or|for|a|an|the|in|on|of|basket|"
                         r"cheap|best)\b", re.I)
_PHRASES = sorted(WORDS, key=len, reverse=True)
_GENERIC_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in _PHRASES) + r")s?\b", re.I)


# every translation -> its English key ('puhelin' -> 'phone' / 'mobile phone', 'kinderwagen' -> 'stroller'), so a
# Finnish word typed by the user reaches a German site in German ('puhelin' on kleinanzeigen -> 'handy')
_REVERSE: dict[str, str] = {}
for _en, _tr in WORDS.items():          # first key wins: 'sohva' -> 'sofa' (not 'couch'), 'takki' -> 'jacket'
    for _w in _tr.values():
        _REVERSE.setdefault(_w.lower(), _en)
    _REVERSE.setdefault(_en, _en)
_REVERSE_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in sorted(_REVERSE, key=len, reverse=True))
                         + r")(?:s|es|t|en|er|ar|or|e|n)?(?![\w-])", re.I)


def english_noun(thing: str) -> str | None:
    """The WORDS key a generic need names, in any language ('puhelin' -> 'mobile phone', 'used road bike' ->
    'road bike', 'Kinderwagen' -> 'stroller'), else None."""
    m = _GENERIC_RE.search(thing or "")
    if m:
        return m.group(1).lower()
    m = _REVERSE_RE.search(FILLER.sub(" ", thing or ""))
    return _REVERSE.get(m.group(1).lower()) if m else None


def translations(noun: str) -> set[str]:
    """Every word for this WORDS key, English included (lower case)."""
    return {noun.lower()} | {w.lower() for w in (WORDS.get(noun) or {}).values()}


def _carrier(rest: str) -> bool:
    """Words left besides the generic noun that carry the search on their own: a brand, a model, a product line
    ('ikea kallax', 'dyson v15', 'herman miller'), i.e. anything that is not a descriptor or a kind-of modifier."""
    return bool(re.search(r"[a-zà-ÿ0-9]{2,}", MODIFIERS.sub(" ", DESCRIPTORS.sub(" ", rest)), re.I))


def site_query(thing: str, site: Site) -> str:
    """The query to type into this site's own search box. Filler ('used', 'cheap') goes; generic nouns go when
    a brand/model word carries the search ('ikea kallax shelf' -> 'ikea kallax', 'dyson v15 vacuum' ->
    'dyson v15'), else they are translated to the site's language ('road bike' -> 'rennrad' on kleinanzeigen,
    'winter jacket' -> 'talvitakki' on tori, 'puhelin' -> 'handy' on kleinanzeigen). Modifiers that only say which
    kind ('baby stroller', 'kitchen table') never carry the search alone (was: tori searched 'baby')."""
    q = FILLER.sub(" ", thing or "")
    q = re.sub(r"[^\w\s.+&'-]", " ", q)
    rest = _GENERIC_RE.sub(" ", q)
    m = _GENERIC_RE.search(q)
    if m is None and (mr := _REVERSE_RE.search(q)):
        # a generic noun typed in another language ('puhelin', 'sohva', 'kinderwagen')
        rest_r = (q[:mr.start()] + " " + q[mr.end():])
        if not _carrier(rest_r):
            en = _REVERSE[mr.group(1).lower()]
            q = WORDS.get(en, {}).get(site.lang, en) if site.lang != "en" else en
            return re.sub(r"\s+", " ", q).strip().lower()
        return re.sub(r"\s+", " ", q).strip().lower()
    if _carrier(rest):
        q = rest
    elif m is not None:
        # only descriptors besides the noun ('city bike with basket'): the noun phrase, translated
        q = WORDS[m.group(1).lower()].get(site.lang, m.group(1)) if site.lang != "en" else m.group(0)
    return re.sub(r"\s+", " ", q).strip().lower() or (thing or "").strip().lower()


# --------------------------------------------------------------------------- the plan

@dataclass(frozen=True)
class Direct:
    site: Site
    lane: str
    query: str
    url: str
    paid: bool          # needs a Context.dev read (one rate-limit token)
    page: int = 1       # results page (2, 3: a paid site's next page when the bucket has tokens to spare)
    extra: bool = False  # bulky thing, marketplace abroad: shown as "also in the EU (+ shipping est.)", not the pick
    category: str | None = None   # taxonomy node of the site's own category page read instead of its search
    exact: bool = False  # that category page lists exactly the need's kind of thing (agora.sources.categories)


BULKY = re.compile(
    r"\b(shelf|shelves|shelving|hylly\w*|kallax|billy|hemnes|malm|pax|sofa|couch|sohva|table|pöytä|chair|tuoli|"
    r"desk|bed|sänky|wardrobe|dresser|lipasto|cabinet|kaappi|fridge|freezer|washing machine|dishwasher|"
    r"piano|treadmill|bookcase|cupboard|mattress|bike|bicycle|e-bike|ebike|polkupyörä|pyörä|fahrrad|cykel|"
    r"stroller|pram|rattaat|kinderwagen|lawn ?mower|cooker|oven|stove)s?\b", re.I)

# a paid direct page is planned only while the bucket has this many tokens left for searches and item reads
PAID_DIRECT_MIN_TOKENS = {"used": 2.0, "refurbished": 3.0, "new": 4.0}
MAX_PAID_DIRECT = 5          # paid marketplace pages per hunt (each 1 credit, 1 token of the shared 10/min)
NEXT_PAGE_MIN_TOKENS = 5.0   # a paid site's page 2 only when this many tokens are left after every page 1
DEEP_NEXT_PAGE_MIN_TOKENS = 2.0   # 'Compare more': next pages while 2 tokens stay for searches and item reads
BULKY_EU_MIN_TOKENS = 5.0    # bulky: marketplaces abroad only with tokens to spare after the home country
# big EU marketplaces read for everybody (small things), best yield first; vinted = the home country's host
EU_WIDE_USED = ("vinted", "kleinanzeigen", "marktplaats", "blocket", "olx_pl", "dba", "finn", "leboncoin")
BULKY_EU_USED = ("kleinanzeigen", "blocket", "marktplaats")
NAMES = {"fi": "Finland", "se": "Sweden", "no": "Norway", "dk": "Denmark", "de": "Germany", "at": "Austria",
         "nl": "the Netherlands", "be": "Belgium", "pl": "Poland", "fr": "France", "es": "Spain", "it": "Italy",
         "gb": "the UK", "cz": "Czechia", "ee": "Estonia", "ch": "Switzerland", "ie": "Ireland", "pt": "Portugal"}


EXTRA_PAGES: set[str] = set()   # planned page URLs that are the bulky 'also in the EU' set (reader.note_market)
# planned category page URL -> {node, need_node, exact, site} (the reader tags its listings: raw['category_page'])
CATEGORY_PAGES: dict[str, dict] = {}
# planned page URL -> how many free result pages to read (generic needs read deeper; reader.free_page_cap)
PAGE_PLAN: dict[str, int] = {}
GENERIC_HOME_PAGES = 20      # a generic need's home marketplace: ~1,000 listings (tori 53 a page), still free
GENERIC_PAGES = 6            # a generic need's other free marketplaces (each ~25-50 listings a page)


def _remember(store: dict, url: str, value) -> None:
    if len(store) > 5000:
        store.clear()
    store[url] = value


def is_bulky(thing: str) -> bool:
    if BULKY.search(thing or ""):
        return True
    try:
        from agora.need import vehicle_need
        return vehicle_need(thing or "")        # a car is picked up near you
    except ImportError:
        return False


def vehicle_query(thing: str) -> str:
    """The query for a cars category: make / model words only; '' for a generic 'car' (browse the category)."""
    from agora.need import ATTRIBUTE_WORDS, VEHICLE_NOUNS
    words = [w for w in re.sub(r"[^\w\s.+-]", " ", FILLER.sub(" ", ATTRIBUTE_WORDS.sub(" ", thing or ""))).split()
             if not VEHICLE_NOUNS.match(w)]
    return " ".join(words).lower()


# --------------------------------------------------------------------------- colour (a car's paint, a preference)
# eval r5 'bright red car': the car sites take no colour in their URL (nettiauto ignores color= / colour=), but
# nettiauto's JSON-LD names each car's colour ('Punainen') and sellers write it in titles. Colour is a boost: a car
# that says it is the asked colour goes first, one that says another colour is marked, an unknown one stays.
_COLOUR_EXTRA: dict[str, tuple[str, ...]] = {
    "red": ("rouge", "rosso", "rojo", "czerwony", "červená", "tummanpunainen", "viininpunainen", "bordeaux",
            "burgundy", "maroon", "weinrot", "dunkelrot"),
    "blue": ("bleu", "blu", "azul", "niebieski", "tummansininen", "dunkelblau", "navy"),
    "black": ("noir", "nero", "negro", "czarny"),
    "white": ("weiss", "blanc", "bianco", "blanco", "biały", "helmenvalkoinen"),
    "silver": ("argent", "argento", "plata", "srebrny"),
    "grey": ("gray", "gris", "grigio", "szary", "tummanharmaa", "vaaleanharmaa"),
    "green": ("vert", "verde", "zielony", "tummanvihreä"),
    "yellow": ("jaune", "giallo", "amarillo", "żółty"),
    "orange": ("arancione", "naranja", "pomarańczowy"),
    "brown": ("marron", "marrone", "marrón", "brązowy"),
}
# colours that contain an asked one but are another ('vaaleanpunainen' is pink, not red)
_COLOUR_NOT = {"vaaleanpunainen": "pink", "pinkki": "pink", "pink": "pink", "rosa": "pink", "roze": "pink",
               "lyserød": "pink", "turkoosi": "turquoise", "turquoise": "turquoise", "türkis": "turquoise",
               "beige": "beige", "kulta": "gold", "gold": "gold", "violetti": "purple", "purple": "purple",
               "lila": "purple"}


def _colour_names() -> dict[str, str]:
    try:
        from agora.need import COLOUR_WORDS
    except ImportError:
        COLOUR_WORDS = {}
    out: dict[str, str] = {}
    for en, tr in COLOUR_WORDS.items():
        canon = "grey" if en == "gray" else en
        out.setdefault(en, canon)
        for w in tr.values():
            out.setdefault(w.lower(), canon)
    for en, words in _COLOUR_EXTRA.items():
        out.setdefault(en, en)
        for w in words:
            out.setdefault(w.lower(), en)
    out.update(_COLOUR_NOT)
    return out


COLOUR_NAMES = _colour_names()
_COLOUR_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in sorted(COLOUR_NAMES, key=len, reverse=True))
                        + r")(?![\w])", re.I)


def colour_of(text: str | None) -> str | None:
    """The colour a car's colour field or title names, in English ('Punainen' -> 'red', 'Tummanpunainen metallic'
    -> 'red', 'Vaaleanpunainen' -> 'pink', 'Volvo V70 D4' -> None). The first colour word wins."""
    m = _COLOUR_RE.search(text or "")
    return COLOUR_NAMES.get(m.group(1).lower()) if m else None


def asked_colours(*texts: str) -> set[str]:
    """The colours a need asks for ('bright red car' / must_have ['bright red'] -> {'red'})."""
    out: set[str] = set()
    for t in texts:
        for m in _COLOUR_RE.finditer(t or ""):
            c = COLOUR_NAMES.get(m.group(1).lower())
            if c:
                out.add(c)
    return out


# --------------------------------------------------------------------------- car dealers' and aggregators' lists
# eval r1-r4 'volvo v70': dealer and aggregator pages (kamux.fi/cars/volvo/v/v70, auto1.fi/haku/volvo v70,
# k-auto.fi/autot/volvo/v70, autouncle.fi/fi/kaytetyt-autot/Volvo/V70, mobile.de/en/car/volvo/v70) list dozens of
# cars, each its own offer; read as one page they gave one 'Volvo V70' at the cheapest price, or none. A path
# segment that names a cars list, and no car's own id at the end (rinta-jouppi.com/ajoneuvohaku/volvo/v70/458836).
_CAR_WORD = (r"vaihtoautot|kaytetyt-autot|autot|ajoneuvot|cars|gebrauchtwagen|autos|occasions|"
             r"tweedehands-auto\w*|bilar|biler|samochody")
_CAR_EXACT = r"kaytetyt|car|auto-s|bil|brugt|occasion"       # only as a whole segment ('car-insurance' is no list)
# a path segment that names a cars list ('vaihtoautot', 'used-and-second-hand-cars', 'kaytetyt-autot')
_CAR_LIST_SEG = re.compile(rf"/(?:(?:[\w]+-)*(?:{_CAR_WORD})(?:-[\w]+)*|{_CAR_EXACT})(?:/|$)", re.I)
# pages about cars that list none: insurance, leasing, rental, articles, valuations, 'sell your car'
_CAR_NOT_LIST = re.compile(r"insurance|vakuut|versicher|verzeker|forsikr|leasing|rental|vuokra|mieten|blog|news|"
                           r"uutis|artik|guide|opas|review|arvostel|hinta-arvio|valuation|myy-auto|sell|verkaufen|"
                           r"rahoitus|financ|calculat|laskuri", re.I)
# a search / list segment: a cars list only on a cars site (auto1.fi/haku, autoscout24 /lst, carandclassic /list),
# never a general marketplace's search (tori.fi/recommerce/forsale/search)
_LIST_SEG = re.compile(r"/(?:haku|autohaku|search|suche|zoeken|sok|list|lst)(?:/|$)", re.I)
_CAR_HOST = re.compile(r"auto|car|bil|motor|vehicle|fahrzeug", re.I)
_CAR_OWN_ID = re.compile(r"(?:^|[/_-])[a-z]{0,3}\d{5,}(?:[/_-][\w-]*)?/?$", re.I)
_CAR_ONE = re.compile(r"/(?:vaihtoauto|auto|car|fahrzeug|angebote|aanbod|annunci|offers?|d|item|ilmoitus)/[\w-]*\d{5,}", re.I)
USED_CAR_WORDS = re.compile(r"vaihtoauto|kaytetty|kaytetyt|used|gebraucht|occasion|tweedehands|begagnad|brugt|"
                            r"/car/|/lst/|/cars/", re.I)


def car_list_url(url: str) -> bool:
    """A car dealer's or aggregator's list page (many cars), not one car's page and not an article."""
    parts = urlsplit(url or "")
    path = parts.path or "/"
    if not (_CAR_LIST_SEG.search(path) or (_LIST_SEG.search(path) and _CAR_HOST.search(parts.netloc))):
        return False
    if _CAR_OWN_ID.search(path.rstrip("/")) or _CAR_ONE.search(path) or _CAR_NOT_LIST.search(path):
        return False
    return True


def used_car_list(url: str) -> bool:
    """A car list page whose URL says it lists used cars ('vaihtoautot', 'kaytetyt-autot', 'gebrauchtwagen'):
    its listings are used whatever a reader guessed ('Volvo V70 2,4D Momentum' read as 'new' in eval r1)."""
    return car_list_url(url) and bool(USED_CAR_WORDS.search(urlsplit(url).path + "/"))


# live 14 Nov: tori / blocket / finn 'mobility' pages and autotalli render their listings with JS (the markdown
# scrape has none), so they are not planned until a reader handles them; nettiauto's list splits fine
HOME_VEHICLE: dict[str, tuple[str, ...]] = {
    "fi": ("nettiauto",), "dk": ("bilbasen",),
    "de": ("mobile_de", "autoscout24_de", "kleinanzeigen_autos"), "at": ("autoscout24_at",),
    "nl": ("marktplaats_auto", "autoscout24_nl"), "be": ("autoscout24_be",), "it": ("autoscout24_it",)}
EU_VEHICLE = ("autoscout24_de", "mobile_de")


def scope_for(thing: str, cc: str | None, home: str | None, eu_included: bool | None = None) -> dict:
    """Why the hunt searched where it did, in words the UI can show verbatim:
    {scope: home|eu, country: 'FI', reason, eu_included, bulky, size}."""
    from agora import shipping
    where = cc or home
    bulky = is_bulky(thing)
    size = shipping.size_class(thing)
    name = NAMES.get(where or "", (where or "your country").upper())
    if bulky:
        est = shipping.estimate(size, "de", where or "fi")
        cost = f"; shipping a {shipping.SIZE_WORD.get(size, size)} from abroad costs ≈{est['text']}" if est else ""
        reason = f"bulky item: searched near you in {name} first{cost}"
        if eu_included:
            reason += ". Big EU marketplaces shown separately, with shipping estimated"
        return {"scope": "home", "country": (where or "").upper() or None, "reason": reason,
                "eu_included": bool(eu_included), "bulky": True, "size": size}
    asked = f"asked for {name}" if cc else f"home: {name}"
    return {"scope": "eu", "country": (where or "").upper() or None,
            "reason": f"small enough to ship: searched {name} and the big EU marketplaces ({asked}); "
                      "foreign prices include estimated shipping",
            "eu_included": True if eu_included is None else bool(eu_included), "bulky": False, "size": size}


def direct_pages(thing: str, lane: str, cc: str | None, home: str | None, tokens: float,
                 max_paid: int = MAX_PAID_DIRECT, pages: int = 1, vehicle: bool | None = None,
                 categories: list[str] | None = None, node: str | None = None, generic: bool = False,
                 tree: bool = False) -> list[Direct]:
    """Marketplace search pages to read directly for one lane.
    Small things: the asked-for (else home) country's marketplaces, then the big EU ones (vinted, kleinanzeigen,
    marktplaats, blocket, olx, dba, finn, leboncoin) while the shared bucket allows; then page 2 of the first
    paid ones. Bulky things (bikes, furniture, white goods): the home country gets the depth (tori paginates
    for free); marketplaces abroad only with tokens to spare, marked `extra` (shown apart, never the pick when
    pickup only). tori's ItemList read is free (it paginates inside the read).
    pages ('Compare more', 1-3): 2 = page 2 of the paid sites at a lower token floor, 3 = pages 2 and 3.
    node + generic (a generic need, or a hunt from the category tree: `tree`): the used marketplaces' own
    category page for that taxonomy node (agora.sources.categories) replaces their search when it lists exactly
    that kind of thing (or always for a tree hunt), and the free pages are read deeper (PAGE_PLAN)."""
    pages = max(1, min(3, int(pages or 1)))
    if pages > 1:
        max_paid += 2 * (pages - 1)
    where = cc or home
    bulky = is_bulky(thing)
    if vehicle is None:
        try:
            from agora.need import vehicle_need
            vehicle = vehicle_need(thing)
        except ImportError:
            vehicle = False
    home_keys: list[str] = []
    eu_keys: list[str] = []
    if vehicle:
        # a vehicle: the country's cars categories first (priority, not a filter: the general marketplace
        # follows while tokens last and every listing is judged on its own), the big EU car sites as extras
        if lane != "used":
            return []
        home_keys += [k for k in HOME_VEHICLE.get(where or "", ()) if k in SITES]
        home_keys += [k for k in HOME_USED.get(where or "", ()) if k not in home_keys]
        eu_keys += [k for k in EU_VEHICLE if SITES[k].country != where]
    elif lane == "used":
        home_keys += list(HOME_USED.get(where or "", ()))
        for k in (BULKY_EU_USED if bulky else EU_WIDE_USED):
            if k == "vinted":
                v = vinted_for(where)
                if v is not None:
                    eu_keys.append(v.key)
            elif k not in home_keys and SITES[k].country != where:
                eu_keys.append(k)
    elif lane == "refurbished" and not bulky:
        home_keys += list(EU_REFURB)
    elif lane == "new" and not bulky:         # verkkokauppa sells no Kallax
        home_keys += list(HOME_NEW.get(where or "", ()))[:1]
    out: list[Direct] = []
    left = tokens
    n_paid = 0
    floor = PAID_DIRECT_MIN_TOKENS.get(lane, 99.0)

    def add(k: str, extra: bool) -> None:
        nonlocal left, n_paid
        s = SITES.get(k)
        if s is None or s.listing is None and not s.itemlist:
            return
        if bulky and not s.bulky_ok:
            return
        paid = not free_site(s)
        if paid:
            if n_paid >= max_paid or left < floor:
                return
            n_paid += 1
            left -= 1
        q = vehicle_query(thing) if s.vehicle else site_query(thing, s)
        url = build_url(s, q) if q or not s.browse else s.browse
        cat_node, exact = None, False
        if node and generic and lane == "used" and not s.vehicle:
            try:
                from agora.sources import categories as _cats
                cp = _cats.page_for(s.key, node, q)
            except Exception:
                cp = None
            if cp is not None and (cp.exact or tree):
                url, cat_node, exact = cp.url, cp.node, cp.exact
                q = cp.query
                _remember(CATEGORY_PAGES, url, {"node": cp.node, "need_node": node, "exact": cp.exact,
                                                "site": s.key})
        if generic and not paid:
            _remember(PAGE_PLAN, url, GENERIC_HOME_PAGES if s.country == where else GENERIC_PAGES)
        out.append(Direct(s, lane, q, url, paid, 1, extra, cat_node, exact))

    def next_pages() -> None:
        nonlocal left, n_paid
        if lane != "used" and not (pages > 1 and lane == "refurbished"):
            return
        floor_next = NEXT_PAGE_MIN_TOKENS if pages == 1 else DEEP_NEXT_PAGE_MIN_TOKENS
        for n in range(2, min(3, pages + 1) + 1):      # depth 1: page 2; 'Compare more': pages 2-3
            for d in [d for d in out if d.paid and d.page == 1 and not d.extra and d.site.verified
                      and page_url(d.site, d.url, n) and not any(x.url == page_url(d.site, d.url, n) for x in out)]:
                if n_paid >= max_paid + 2 or left < floor_next:
                    return
                n_paid += 1
                left -= 1
                out.append(Direct(d.site, lane, d.query, page_url(d.site, d.url, n) or d.url, True, n, False))

    if lane in ("used", "refurbished", "new"):
        # free registry sources for this country / lane / category (priority, never a filter): no token spent
        try:
            from agora import sources as _src
            cats = categories if categories is not None else categories_for(thing)
            n_extra = 0
            for rec in _src.for_query(where, [lane], cats or None):
                k = "src_" + rec["key"]
                site = SITES.get(k) or next((x for x in _HOST_SITES.get(rec.get("domain") or "", [])
                                             if x.lane == lane), None)
                if site is None or site.key in home_keys or site.key in eu_keys or not free_site(site):
                    continue
                if cats and not set(cats) & set(rec.get("categories") or []):
                    continue          # a general store is no first read for a car
                if site.country not in (where, "eu") and (bulky and not site.bulky_ok):
                    continue
                (home_keys if site.country == where else eu_keys).append(site.key)
                n_extra += 1
                if n_extra >= MAX_REGISTRY_FREE:
                    break
        except Exception:
            pass
    for k in home_keys:
        add(k, False)
    if bulky:
        next_pages()                  # the home country gets the depth first
        if left >= BULKY_EU_MIN_TOKENS:
            for k in eu_keys:
                add(k, True)
    else:
        for i, k in enumerate(eu_keys):
            add(k, False)
            if pages > 1 and i == 1:
                next_pages()          # 'Compare more': deeper pages of the best sites before the 3rd+ EU site
        next_pages()                  # then page 2 of the paid pages while tokens are left over
    return out


# --------------------------------------------------------------------------- pages, market size, delivery

def page_url(site: Site, url: str, n: int) -> str | None:
    """Results page n of this site's search URL (None = unknown scheme). Page 1 = the URL itself."""
    if n <= 1:
        return url
    parts = urlsplit(url)
    path, query = parts.path, parts.query
    if site.key == "kleinanzeigen":               # /s-<q>/k0 -> /s-seite:2/<q>/k0
        if not path.startswith("/s-"):
            return None
        cat = re.match(r"^(/s-[^/]+)(?:/seite:\d+)?((?:/[^/]+)?/(?:k0)?c\d+/?)$", path)
        if cat:                                    # category page /s-handy-telekom/c173 -> .../seite:2/c173
            path = f"{cat.group(1)}/seite:{n}{cat.group(2)}"
        else:
            path = re.sub(r"^/s-(?:seite:\d+/)?", f"/s-seite:{n}/", path)
    elif site.key in ("marktplaats", "2dehands"):  # /q/<q>/ -> /q/<q>/p/2/
        path = re.sub(r"/p/\d+/?$", "/", path.rstrip("/") + "/") + f"p/{n}/"
    elif site.key in ("amazon_de", "verkkokauppa", "power_fi", "cdiscount", "idealo", "pricerunner"):
        return None
    else:                                          # ?page=2 (Schibsted, vinted, olx, leboncoin, gumtree ...)
        query = re.sub(r"(?:^|&)page=\d+", "", query)
        query = (query + "&" if query else "") + f"page={n}"
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


_COUNT_NUM = r"(\d{1,3}(?:[ .,\u00a0\u202f]\d{3})+|\d+)"
COUNT_PATTERNS = [
    re.compile(rf"\bvon\s+{_COUNT_NUM}\s+Ergebnis", re.I),                  # kleinanzeigen '1 - 25 von 1.742 Ergebnissen'
    re.compile(rf"löydät\s+{_COUNT_NUM}\s+ilmoitus", re.I),                  # tori meta 'Torista löydät 117 ilmoitusta'
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:ilmoitusta|tulosta|osumaa)", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:Ergebnisse|Anzeigen|Treffer)\b", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:resultaten|advertenties|zoekresultaten)\b", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:annonser|annoncer|träffar|resultater|resultat)\b", re.I),
    re.compile(rf"(?:Znaleźliśmy|Znaleziono)\s+(?:ponad\s+)?{_COUNT_NUM}", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:ogłosze\w*|wyników)", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:annonces|résultats)\b", re.I),
    re.compile(rf"{_COUNT_NUM}(\+)?\s+(?:results|listings|ads|items)\b", re.I),
    re.compile(rf"{_COUNT_NUM}\s+kappaletta\b", re.I),                       # nettiauto 'Nettiautossa on 665 kappaletta'
    re.compile(r'"numberOfResults"\s*:\s*(\d+)'),                               # AutoScout24 __NEXT_DATA__
    re.compile(r'"offerCount"\s*:\s*"?(\d+)'),                                # schema.org AggregateOffer (car lists)
]


def market_total(text: str) -> tuple[int, bool] | None:
    """How many listings the site says the search has: (count, at_least). '500+ tulosta' -> (500, True).
    Facet counts ('Versand möglich1.224') are not totals: patterns need the word after the number."""
    if "&" in (text or ""):
        text = _html.unescape(text)     # tori's meta says '19&nbsp;370 ilmoitusta' (was read as 370)
    for pat in COUNT_PATTERNS:
        for m in pat.finditer(text or ""):
            raw = m.group(1)
            n = int(re.sub(r"\D", "", raw))
            if n <= 0 or n > 5_000_000:
                continue
            plus = bool(m.lastindex and m.lastindex >= 2 and m.group(2)) or "ponad" in m.group(0).lower()
            return n, plus
    return None


PICKUP = re.compile(
    r"\b(?:nur\s+(?:selbst)?abholung|nur\s+abholen|nur\s+an\s+selbstabholer|selbstabholung|alleen\s+ophalen|"
    r"ophalen\s+only|enkel\s+ophalen|endast\s+(?:avhämtning|upphämtning|hämtas)|kun\s+afhentning|"
    r"kun\s+(?:henting|hentes)|pick[- ]?up\s+only|collection\s+only|collect\s+only|vain\s+nouto|"
    r"noudettava|haettava|odbiór\s+osobisty|tylko\s+odbiór|remise\s+en\s+main\s+propre\s+uniquement|"
    r"retrait\s+uniquement|solo\s+ritiro|ritiro\s+a\s+mano|solo\s+recogida)\b", re.I)
SHIPS = re.compile(
    r"\b(?:versand\s+möglich|versand\b|verzenden|kan\s+verzonden|verzending|frakt\b|kan\s+skickas|skickas|"
    r"sendes|kan\s+sendes|forsendelse|wysyłka|livraison\s+possible|envío|spedizione|toimitus|postitus|"
    r"shipping\s+available|can\s+ship|ships\b|delivery\s+available|direkt\s+kaufen|tori\s+diili)\b", re.I)


def delivery_of(text: str, site_key: str = "") -> str | None:
    """'pickup' (the seller hands it over in person only), 'ships', or None (not stated).
    vinted always ships (its own shipping labels)."""
    if site_key.startswith("vinted"):
        return "ships"
    if PICKUP.search(text or ""):
        return "pickup"
    if site_key in ("marktplaats", "2dehands") and re.search(r"\bOphalen\b(?!\s+of\s+verzenden)", text or "", re.I) \
            and not re.search(r"\bverzenden\b", text or "", re.I):
        return "pickup"           # marktplaats rows say 'Ophalen' (pickup) or 'Verzenden' / 'Ophalen of Verzenden'
    if SHIPS.search(text or ""):
        return "ships"
    if site_key == "kleinanzeigen":
        return "pickup"           # kleinanzeigen rows say 'Versand möglich' when the seller ships; else pickup only
    return None


_PLZ = re.compile(r"^\s*(\d{4,5})\s+([A-ZÄÖÜa-zäöüß][^\n]{1,40}?)\s*$", re.M)


def row_location(text: str) -> str | None:
    """The seller's place in a result row: kleinanzeigen '53773 Hennef (Sieg)', marktplaats/2dehands 'Utrecht'."""
    m = _PLZ.search(text or "")
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    return None


# ------------------------------------------------------------------ when a listing was posted (sort: newest first)
# A result card says when it went up in the site's own words: kleinanzeigen 'Heute, 14:12' / 'Gestern, 09:30' /
# '12.11.2026', olx 'Wrocław - Dzisiaj o 14:12' / '14 listopada 2026' / 'Odświeżono dzisiaj o 07:36' (olx shows
# the bump date as the listing's date), marktplaats 'Vandaag' / '12 nov 26', the Nordic 'i dag 14:12' / 'igår',
# tori 'tänään 14:12' / 'eilen'. Read with code from the card's first few hundred characters (where the date sits,
# before any description), in the site's own time zone, and kept only when it is not in the future and not years old.

POSTED_TZ = {"fi": "Europe/Helsinki", "se": "Europe/Stockholm", "no": "Europe/Oslo", "dk": "Europe/Copenhagen",
             "de": "Europe/Berlin", "at": "Europe/Vienna", "ch": "Europe/Zurich", "nl": "Europe/Amsterdam",
             "be": "Europe/Brussels", "pl": "Europe/Warsaw", "fr": "Europe/Paris", "es": "Europe/Madrid",
             "it": "Europe/Rome", "pt": "Europe/Lisbon", "cz": "Europe/Prague", "gb": "Europe/London",
             "ie": "Europe/Dublin", "lt": "Europe/Vilnius", "ee": "Europe/Tallinn", "lv": "Europe/Riga"}
_MONTHS = {}
for _i, _names in enumerate((
        "january jan januar jänner stycznia styczeń styczen januari tammikuuta janvier enero gennaio",
        "february feb februar lutego luty februari helmikuuta février fevrier febrero febbraio",
        "march mar märz maerz mrz marca marzec maart maaliskuuta mars marzo",
        "april apr kwietnia kwiecień kwiecien huhtikuuta avril abril aprile",
        "may mai maja maj mei toukokuuta mayo maggio",
        "june jun juni czerwca czerwiec kesäkuuta juin junio giugno",
        "july jul juli lipca lipiec heinäkuuta juillet julio luglio",
        "august aug sierpnia sierpień sierpien augustus elokuuta août aout agosto",
        "september sep sept września wrzesień wrzesien syyskuuta septembre septiembre settembre",
        "october oct okt oktober października październik pazdziernika oktober lokakuuta octobre octubre ottobre",
        "november nov listopada listopad marraskuuta novembre noviembre",
        "december dec dez dezember grudnia grudzień grudzien joulukuuta décembre decembre diciembre dicembre"), 1):
    for _w in _names.split():
        _MONTHS[_w] = _i
_TODAY = r"heute|dzisiaj|vandaag|i\s*dag|tänään|tanaan|today|aujourd'hui|hoy|oggi"
_YESTERDAY = r"gestern|wczoraj|gisteren|i\s*går|i\s*gar|eilen|yesterday|ayer|ieri"
_DAY_REL = re.compile(rf"(?<![\w-])(?:odświeżono\s+)?(?:(?P<t>{_TODAY})|(?P<y>{_YESTERDAY})|(?P<yy>vorgestern|eergisteren))"
                      r"(?:\s*,?\s*(?:o|om|um|at|à|klo\.?|kl\.?)?\s*(?P<h>[0-2]?\d)[:.](?P<m>[0-5]\d))?(?![\w])", re.I)
_DMY = re.compile(r"(?<![\d.])(?P<d>[0-3]?\d)\.(?P<mo>[01]?\d)\.(?P<y>20\d\d|\d\d)(?![\d.])"
                  r"(?:\s*,?\s*(?:um\s+|klo\s+|kl\.?\s*)?(?P<h>[0-2]?\d)[:.](?P<m>[0-5]\d))?")
_D_MON_Y = re.compile(r"(?<![\w])(?P<d>[0-3]?\d)\.?\s+(?P<mon>[^\W\d_]{3,13})\.?\s+(?P<y>20\d\d|\d\d)(?![\d])", re.I)
_AGO = re.compile(r"(?:vor|for|för)?\s*(?P<n>\d{1,3})\s*(?P<u>min(?:ute[ns]?|uter|utter|uuttia|s)?|minuten|"
                  r"h|hrs?|hours?|stunden?|timmar|timer|tuntia|tunti|days?|tag(?:e|en)?|dagar|dage|dager|päivää|pv|"
                  r"weeks?|wochen?|veckor|uger|uker|viikkoa)\s*(?:ago|sedan|siden|sitten)?(?![\w])", re.I)


def posted_at(text: str | None, site_key: str = "", now=None) -> str | None:
    """When the card says the listing went up -> ISO: '2026-11-15T14:12:00+01:00' (a time given) or
    '2026-11-12' (a day only); None when the card does not say (or says something we cannot trust)."""
    from datetime import datetime, timedelta
    if not text:
        return None
    cc = SITES[site_key].country if site_key in SITES else (site_key.split("_")[1] if "_" in (site_key or "") else "")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(POSTED_TZ.get(cc, "Europe/Helsinki"))
    except Exception:            # no tz database: UTC is a day off at most
        from datetime import timezone
        tz = timezone.utc
    now = (now or datetime.now(tz)).astimezone(tz)
    head = " ".join(str(text).split())[:300]
    found: list[tuple[int, str]] = []        # (where in the card, iso)

    def ok(dt) -> bool:
        return now - timedelta(days=3 * 366) <= dt <= now + timedelta(hours=26)

    m = _DAY_REL.search(head)
    if m and not m.group("h") and site_key not in ("marktplaats", "2dehands"):
        m = None             # a bare 'heute' / 'i dag' can be the seller's words; the card's own stamp has a time
    if m:
        day = now - timedelta(days=0 if m.group("t") else 1 if m.group("y") else 2)
        if m.group("h") and int(m.group("h")) < 24:
            dt = day.replace(hour=int(m.group("h")), minute=int(m.group("m")), second=0, microsecond=0)
            found.append((m.start(), dt.isoformat()))
        else:
            found.append((m.start(), day.date().isoformat()))
    m = _DMY.search(head)
    if m:
        y = int(m.group("y")) + (2000 if len(m.group("y")) == 2 else 0)
        try:
            dt = datetime(y, int(m.group("mo")), int(m.group("d")), tzinfo=tz)
            if m.group("h") and int(m.group("h")) < 24:
                dt = dt.replace(hour=int(m.group("h")), minute=int(m.group("m")))
                iso = dt.isoformat()
            else:
                iso = dt.date().isoformat()
            if ok(dt):
                found.append((m.start(), iso))
        except ValueError:
            pass
    for m in _D_MON_Y.finditer(head):
        mon = _MONTHS.get(m.group("mon").lower())
        if not mon:
            continue
        y = int(m.group("y")) + (2000 if len(m.group("y")) == 2 else 0)
        try:
            dt = datetime(y, mon, int(m.group("d")), tzinfo=tz)
        except ValueError:
            continue
        if ok(dt):
            found.append((m.start(), dt.date().isoformat()))
        break
    m = _AGO.search(head)
    if m and (m.group(0).lower().startswith(("vor", "for", "för")) or
              re.search(r"ago|sedan|siden|sitten", m.group(0), re.I)):
        n, u = int(m.group("n")), m.group("u").lower()
        if u.startswith("min"):
            d = timedelta(minutes=n)
        elif u.startswith(("day", "tag", "dag", "päi", "pv")):
            d = timedelta(days=n)
        elif u.startswith(("w", "v", "u")):
            d = timedelta(weeks=n)
        else:
            d = timedelta(hours=n)
        dt = now - d
        if ok(dt):
            found.append((m.start(), dt.replace(second=0, microsecond=0).isoformat() if d < timedelta(days=1)
                          else dt.date().isoformat()))
    return min(found)[1] if found else None


def market_summary(pages: list[dict]) -> dict:
    """Per-page market records (reader.MARKET values) -> the hunt's `market` event body:
    {sources: [{domain, country, total, at_least, read, pages, extra}], total, read}. One record per domain
    (pages of the same site add up their rows; the site's total is the largest stated)."""
    by: dict[str, dict] = {}
    for p in pages:
        if not p:
            continue
        d = by.setdefault(p["domain"], {"domain": p["domain"], "country": (p.get("country") or "").upper() or None,
                                        "total": None, "at_least": False, "read": 0, "pages": 0,
                                        "extra": bool(p.get("extra"))})
        d["read"] += int(p.get("read") or 0)
        d["pages"] += int(p.get("pages") or 1)
        if p.get("total") is not None and (d["total"] is None or p["total"] > d["total"]):
            d["total"], d["at_least"] = int(p["total"]), bool(p.get("at_least"))
    sources = sorted(by.values(), key=lambda d: (d["extra"], -(d["total"] or d["read"])))
    total = sum((d["total"] if d["total"] is not None else d["read"]) for d in sources)
    return {"sources": sources, "total": total, "read": sum(d["read"] for d in sources),
            "at_least": any(d["at_least"] or d["total"] is None for d in sources)}


# --------------------------------------------------------------------------- the splitter (Robert's split_rows)

MAX_ROWS: int | None = None     # every row on the page (resolve/judge filter); was 25
LINK = re.compile(r"\[((?:[^\[\]\\]|\\.)*)\]\((https?://[^\s)]+)[^)]*\)")   # [text](url "title")
_NUM = r"\d{1,3}(?:[ .,  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
PRICE = re.compile(rf"(?<![\d.,])(?:(?:[€£]|EUR\b|CHF\b)\s*({_NUM})|({_NUM})\s*(?:€|EUR\b|kr\b|kr\.|zł|PLN\b|SEK\b|"
                   rf"NOK\b|DKK\b|Kč|CZK\b|CHF\b|£|:-))", re.I)
IMG = re.compile(r'''<(?:img|source)\b[^>]*?\b(?:src|data-src|srcset|data-srcset)=["']([^"' ,]+)''', re.I)
_MONTHLY = re.compile(r"\s*/\s*(?:mois|mo\b|kk|month|monat|mån|md|kuukausi)", re.I)


def to_number(text: str) -> float:
    """'1.199,00' -> 1199.0, '4 500' -> 4500.0, '368.83' -> 368.83. (Robert's to_number.)"""
    t = re.sub(r"[   ]", "", text)
    last = max(t.rfind("."), t.rfind(","))
    if last >= 0 and len(t) - last - 1 == 3 and not ("." in t and "," in t):
        return float(re.sub(r"[.,]", "", t))     # a lone separator before three digits groups thousands
    if last >= 0:
        return float(re.sub(r"[.,]", "", t[:last]) + "." + t[last + 1:])
    return float(t)


def first_price(text: str, last: bool = False) -> float | None:
    """First (or last) price in the text; a price in **bold** wins, monthly plan prices are ignored."""
    def prices(t: str) -> list[float]:
        out = []
        for m in PRICE.finditer(t):
            if _MONTHLY.match(t[m.end():m.end() + 14]):
                continue
            try:
                v = to_number(m.group(1) or m.group(2))
            except ValueError:
                continue
            if v > 0:
                out.append(v)
        return out
    found = prices(" ".join(re.findall(r"\*\*([^*]{1,40})\*\*", text))) or prices(text)
    return (found[-1] if last else found[0]) if found else None


def canonical(url: str, site: Site) -> str:
    """The listing's own URL without tracking: query and fragment dropped, amazon cut after /dp/<asin>."""
    parts = urlsplit(url)
    path = parts.path
    if site.key == "amazon_de":
        m = re.search(r"/dp/\w+", path)
        path = m.group(0) if m else path
    path = path.split("/ref=")[0]
    return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


def find_image(page_html: str, url: str) -> str | None:
    """Photo for a listing: the first <img> near where its link sits in the page HTML. (Robert's find_image.)"""
    path = urlsplit(url).path
    if len(path) < 8 or not page_html:
        return None

    def ok(u: str) -> bool:
        return not u.startswith("data:") and ".svg" not in u

    for m in list(re.finditer(re.escape(path), page_html))[:8]:
        after = [u for u in IMG.findall(page_html[m.start():m.start() + 6000]) if ok(u)]
        if after:
            return urljoin(url, _html.unescape(after[0]))
        before = [u for u in IMG.findall(page_html[max(0, m.start() - 4000):m.start()]) if ok(u)]
        if before:
            return urljoin(url, _html.unescape(before[-1]))
    return None


def _clean_title(title: str) -> str:
    # vinted appends ', brand: x, condition: y'
    title = re.split(r", [^,:]{3,20}: ", title.replace("**", ""))[0]
    title = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", title)
    title = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", title)
    return " ".join(title.split())[:110]


def _brand(domain: str) -> str:
    """'vinted.co.uk' -> 'vinted', 'es.wallapop.com' -> 'wallapop'."""
    return max(domain.split(".")[:-1] or [domain], key=len)


def listing_links(md: str, site: Site) -> list[tuple[re.Match[str], str]]:
    """Markdown links whose URL is a listing of this site -> [(match, canonical url)]."""
    if not site.listing:
        return []
    pat = re.compile(site.listing)
    out = []
    for m in LINK.finditer(md or ""):
        u = m.group(2)
        if not pat.search(urlsplit(u).path + ("?" + urlsplit(u).query if urlsplit(u).query else "")):
            continue
        if _brand(site.domain) not in urlsplit(u).netloc.lower():
            continue           # an ad or a link to another site
        out.append((m, canonical(u, site)))
    return out


def split_rows(md: str, page_html: str, site: Site, max_rows: int | None = MAX_ROWS) -> list[dict]:
    """Cut one search page into listings with code, no model:
    [{title, price, currency, url, text, image, delivery, location}] (Robert's split_rows, per-site patterns).
    delivery: 'pickup' / 'ships' / None from the row's own words ('Nur Abholung', 'Versand möglich')."""
    links = listing_links(md, site)
    rows: list[dict] = []
    seen: set[str] = set()

    def add(title: str, price: float | None, url: str, text: str, label: str = "") -> None:
        title = _clean_title(title)
        loc = row_location(LINK.sub(lambda x: x.group(1), text))
        text = re.sub(r"[\\#*]+", " ", text)
        if price and len(title) >= 6 and url not in seen:
            seen.add(url)
            flat = " ".join(LINK.sub(lambda x: x.group(1), text).split())
            row = {"title": title, "price": price, "currency": site.currency, "url": url,
                   "text": flat[:200], "image": find_image(page_html, url),
                   "delivery": delivery_of(f"{title} {flat}", site.key), "location": loc}
            posted = posted_at(flat, site.key)
            if posted:
                row["posted"] = posted
            if site.key.startswith("vinted"):
                # vinted's link label: 'title, brand: x, condition: y, 41.34 €, 44.11 €' = price, price + buyer fee
                both = [to_number(a or b) for a, b in PRICE.findall(label)]
                if len(both) >= 2 and both[1] > both[0] == price:
                    row["price_with_fee"] = both[1]
            rows.append(row)

    if site.heading_title:
        for h in re.finditer(r"^#{2,4} (.+)$", md, re.M):
            before = max([m.end() for m, _ in links if m.end() <= h.start()], default=0)
            after = next(((m, k) for m, k in links if m.start() >= h.end()), None)
            heading = h.group(1)
            inline = LINK.search(heading)        # '## [Title](item url)'
            if inline and any(k == canonical(inline.group(2), site) for _, k in links):
                add(inline.group(1), first_price(md[before:h.start()], last=True) or
                    first_price(md[h.end():h.end() + 300]), canonical(inline.group(2), site), "")
            elif after and after[0].start() - h.end() < 600:
                add(heading, first_price(md[before:h.start()], last=True), after[1],
                    md[h.end():after[0].start()])
        return rows[:max_rows] if max_rows else rows
    firsts = [(m, key) for i, (m, key) in enumerate(links) if key not in {k for _, k in links[:i]}]
    for n, (m, key) in enumerate(firsts):
        end = min(firsts[n + 1][0].start() if n + 1 < len(firsts) else len(md), m.start() + 3000)
        seg = LINK.sub(lambda x: x.group(1), md[m.start():end])
        slug = set(re.findall(r"[a-z0-9]+", key.lower()))
        parts = [p.strip() for mm, k in links if k == key
                 for p in re.split(r"(?:\\+\s*)+|\n+", re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", mm.group(1)))
                 if len(p.strip()) >= 6 and not PRICE.fullmatch(p.strip())]
        if parts:
            title = max(parts, key=lambda p: (len(slug & set(re.findall(r"[a-z0-9]+", p.lower()))), -parts.index(p)))
            price = first_price(m.group(1), last=True) if site.price_last else first_price(seg)
            add(title, price, key, seg.replace(title, ""), m.group(1))
    return rows[:max_rows] if max_rows else rows
