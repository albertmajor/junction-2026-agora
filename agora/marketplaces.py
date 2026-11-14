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
    # price comparison: 'ab €X' is not an offer (discover.JUNK_DOMAINS); kept for reference, never planned
    Site("idealo", "de", "comparison", "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
         r"OffersOfProduct", "de"),
    Site("pricerunner", "se", "comparison", "https://www.pricerunner.se/results?q={q}", r"/pl/", "sv"),
]
SITES: dict[str, Site] = {s.key: s for s in _SITES}
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
for _s in _SITES:
    _HOST_SITE.setdefault(_s.domain, _s)


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
    if _own_search(s, parts):
        return s
    if s.listing and re.search(s.listing, parts.path):
        return None                   # one listing, not a search page
    from agora.discover import is_list_page
    return s if is_list_page(url) else None


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
}
# words that say how, not what: never part of a marketplace search
FILLER = re.compile(r"\b(?:used|second[- ]hand|secondhand|pre[- ]owned|refurbished|refurb|new|brand new|cheap|"
                    r"cheapest|buy|for sale|deal|best price|käytetty|gebraucht|neu|begagnad|brukt|brugt|"
                    r"tweedehands|occasion|usato|usado|używany)\b", re.I)
_PHRASES = sorted(WORDS, key=len, reverse=True)
_GENERIC_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in _PHRASES) + r")s?\b", re.I)


def site_query(thing: str, site: Site) -> str:
    """The query to type into this site's own search box. Filler ('used', 'cheap') goes; generic nouns go when
    a brand/model word carries the search ('ikea kallax shelf' -> 'ikea kallax', 'dyson v15 vacuum' ->
    'dyson v15'), else they are translated to the site's language ('road bike' -> 'rennrad' on kleinanzeigen)."""
    q = FILLER.sub(" ", thing or "")
    q = re.sub(r"[^\w\s.+&'-]", " ", q)
    rest = _GENERIC_RE.sub(" ", q)
    if re.search(r"[a-zà-ÿ0-9]{2,}", rest, re.I):
        q = rest
    elif site.lang != "en":
        q = _GENERIC_RE.sub(lambda m: WORDS[m.group(1).lower()].get(site.lang, m.group(1)), q)
    return re.sub(r"\s+", " ", q).strip().lower() or (thing or "").strip().lower()


# --------------------------------------------------------------------------- the plan

@dataclass(frozen=True)
class Direct:
    site: Site
    lane: str
    query: str
    url: str
    paid: bool          # needs a Context.dev read (one rate-limit token)


BULKY = re.compile(
    r"\b(shelf|shelves|shelving|hylly\w*|kallax|billy|hemnes|malm|pax|sofa|couch|sohva|table|pöytä|chair|tuoli|"
    r"desk|bed|sänky|wardrobe|dresser|lipasto|cabinet|kaappi|fridge|freezer|washing machine|dishwasher|"
    r"piano|treadmill|bookcase|cupboard|mattress)\b", re.I)

# a paid direct page is planned only while the bucket has this many tokens left for searches and item reads
PAID_DIRECT_MIN_TOKENS = {"used": 3.0, "refurbished": 4.0, "new": 5.0}


def direct_pages(thing: str, lane: str, cc: str | None, home: str | None, tokens: float,
                 max_paid: int = 2) -> list[Direct]:
    """Marketplace search pages to read directly for one lane: the asked-for (else home) country's own
    marketplaces first, then 1-2 big EU ones. Bulky things (furniture, white goods) only at home: nobody
    collects a Kallax from Germany. A page that needs a paid read is planned only while `tokens` (the shared
    Context.dev bucket, minus what is already planned) allows it; tori's ItemList read is free."""
    where = cc or home
    bulky = bool(BULKY.search(thing or ""))
    keys: list[str] = []
    if lane == "used":
        keys += list(HOME_USED.get(where or "", ()))
        if not bulky:
            for k in EU_USED:
                if k == "vinted":
                    v = vinted_for(where)
                    if v is not None:
                        keys.append(v.key)
                elif k not in keys:
                    keys.append(k)
    elif lane == "refurbished" and not bulky:
        keys += list(EU_REFURB)
    elif lane == "new" and not bulky:         # verkkokauppa sells no Kallax
        keys += list(HOME_NEW.get(where or "", ()))[:1]
    out: list[Direct] = []
    left = tokens
    n_paid = 0
    for k in keys:
        s = SITES.get(k)
        if s is None or s.listing is None and not s.itemlist:
            continue
        if bulky and not s.bulky_ok:
            continue
        paid = not s.itemlist
        if paid:
            if n_paid >= max_paid or left < PAID_DIRECT_MIN_TOKENS.get(lane, 99.0):
                continue
            n_paid += 1
            left -= 1
        q = site_query(thing, s)
        out.append(Direct(s, lane, q, build_url(s, q), paid))
    return out


# --------------------------------------------------------------------------- the splitter (Robert's split_rows)

MAX_ROWS = 25
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


def split_rows(md: str, page_html: str, site: Site, max_rows: int = MAX_ROWS) -> list[dict]:
    """Cut one search page into listings with code, no model:
    [{title, price, currency, url, text, image}] (Robert's split_rows, per-site patterns)."""
    links = listing_links(md, site)
    rows: list[dict] = []
    seen: set[str] = set()

    def add(title: str, price: float | None, url: str, text: str, label: str = "") -> None:
        title = _clean_title(title)
        text = re.sub(r"[\\#*]+", " ", text)
        if price and len(title) >= 6 and url not in seen:
            seen.add(url)
            row = {"title": title, "price": price, "currency": site.currency, "url": url,
                   "text": " ".join(LINK.sub(lambda x: x.group(1), text).split())[:200],
                   "image": find_image(page_html, url)}
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
        return rows[:max_rows]
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
    return rows[:max_rows]
