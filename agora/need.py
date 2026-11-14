"""NEED: free text -> Need.

Rules first (instant, offline, multilingual-ish: EN/FI/DE/SV), then optionally Gemini
(REST via httpx, only when GEMINI_API_KEY is set) which may fill gaps. Rules always win
on numbers we can read ourselves, so the LLM can never invent a budget.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, get_args

import httpx

from agora.models import Condition, Need

# ---------------------------------------------------------------- vocab

CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "e": "EUR", "eu": "EUR",
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "us$": "USD",
    "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
    "sek": "SEK", "nok": "NOK", "dkk": "DKK", "kr": "SEK",
    "chf": "CHF", "pln": "PLN", "zł": "PLN", "zl": "PLN", "czk": "CZK", "kč": "CZK",
    "huf": "HUF", "ft": "HUF", "¥": "JPY", "jpy": "JPY",
}

CONDITION_WORDS: dict[str, Condition] = {
    # used
    "used": "used", "second hand": "used", "second-hand": "used", "secondhand": "used",
    "pre-owned": "used", "preowned": "used", "pre owned": "used", "käytetty": "used", "kaytetty": "used",
    "käytettynä": "used", "käytettyä": "used", "gebraucht": "used", "gebrauchte": "used", "gebrauchtes": "used",
    "gebrauchten": "used", "begagnade": "used", "begagnat": "used", "begagnad": "used", "brugt": "used", "brukt": "used",
    "occasion": "used", "usato": "used", "usado": "used", "kirpputori": "used",
    # refurbished
    "refurbished": "refurbished", "refurb": "refurbished", "renewed": "refurbished",
    "reconditioned": "refurbished", "kunnostettu": "refurbished", "generalüberholt": "refurbished",
    "generaluberholt": "refurbished", "certified pre-owned": "refurbished", "open box": "refurbished",
    # new
    "brand new": "new", "new": "new", "uusi": "new", "neu": "new", "ny": "new", "sealed": "new", "unopened": "new",
    # rental
    "rent": "rental", "rental": "rental", "hire": "rental", "lease": "rental", "vuokra": "rental",
    "vuokrata": "rental", "mieten": "rental", "miete": "rental", "hyra": "rental", "borrow": "rental",
}

# service keyword -> canonical service name (also used by discover via Need.must_have)
SERVICE_WORDS: dict[str, str] = {
    "cleaning": "cleaning", "cleaner": "cleaning", "clean my": "cleaning", "siivous": "cleaning",
    "siivooja": "cleaning", "putzfrau": "cleaning", "reinigung": "cleaning", "städning": "cleaning",
    "plumber": "plumbing", "plumbing": "plumbing", "putkimies": "plumbing", "klempner": "plumbing",
    "electrician": "electrician", "sähkömies": "electrician", "elektriker": "electrician",
    "haircut": "haircut", "hairdresser": "haircut", "barber": "haircut", "kampaamo": "haircut",
    "parturi": "haircut", "friseur": "haircut",
    "moving": "moving", "movers": "moving", "removal": "moving", "muutto": "moving", "umzug": "moving",
    "flytt": "moving", "man with a van": "moving",
    "painter": "painting", "painting service": "painting", "maalari": "painting",
    "handyman": "handyman", "remontti": "handyman", "carpenter": "handyman",
    "babysitter": "childcare", "nanny": "childcare", "lastenhoitaja": "childcare",
    "dog walker": "pet care", "dog sitter": "pet care", "pet sitter": "pet care",
    "tutor": "tutoring", "tutoring": "tutoring", "lessons": "tutoring",
    "massage": "massage", "hieronta": "massage", "physio": "physiotherapy",
    "repair": "repair", "fix my": "repair", "korjaus": "repair", "reparatur": "repair",
    "car wash": "car wash", "tyre change": "tyre change", "renkaanvaihto": "tyre change",
    "photographer": "photography", "valokuvaaja": "photography", "gardener": "gardening",
    "window cleaning": "cleaning", "ikkunanpesu": "cleaning", "laundry": "laundry",
    "accountant": "accounting", "tilitoimisto": "accounting", "lawyer": "legal",
    # the same jobs in the languages agora.places knows (a local's query: 'schoonmaker den haag')
    "schoonmaker": "cleaning", "schoonmaakster": "cleaning", "schoonmaak": "cleaning", "schoonmaakbedrijf": "cleaning",
    "huishoudelijke hulp": "cleaning", "glazenwasser": "cleaning", "loodgieter": "plumbing", "elektricien": "electrician",
    "verhuizer": "moving", "verhuisbedrijf": "moving", "klusjesman": "handyman", "kapper": "haircut", "oppas": "childcare",
    "reinigungskraft": "cleaning", "haushaltshilfe": "cleaning", "putzhilfe": "cleaning", "fensterputzer": "cleaning",
    "gebäudereinigung": "cleaning", "installateur": "plumbing", "umzugsfirma": "moving", "handwerker": "handyman",
    "babysitterin": "childcare", "nachhilfe": "tutoring",
    "städare": "cleaning", "hemstädning": "cleaning", "rörmokare": "plumbing", "flyttfirma": "moving",
    "frisör": "haircut", "hantverkare": "handyman",
    "rengøring": "cleaning", "rengøringshjælp": "cleaning", "vvs": "plumbing", "flyttefirma": "moving",
    "vaskehjelp": "cleaning", "rørlegger": "plumbing", "flyttebyrå": "moving",
    "kotisiivous": "cleaning", "siivousfirma": "cleaning", "sähköasentaja": "electrician", "muuttofirma": "moving",
    "femme de ménage": "cleaning", "ménage": "cleaning", "plombier": "plumbing", "électricien": "electrician",
    "déménagement": "moving", "déménageur": "moving", "coiffeur": "haircut",
    "limpieza": "cleaning", "fontanero": "plumbing", "electricista": "electrician", "mudanza": "moving",
    "pulizie": "cleaning", "idraulico": "plumbing", "elettricista": "electrician", "trasloco": "moving",
    "sprzątanie": "cleaning", "hydraulik": "plumbing", "elektryk": "electrician", "przeprowadzka": "moving",
    # a gunsmith repairs, services and fits weapons: the trade, never a gun for sale
    "gunsmith": "gunsmith", "gunsmiths": "gunsmith", "gunsmithing": "gunsmith", "aseseppä": "gunsmith",
    "aseseppa": "gunsmith", "asesepät": "gunsmith", "asesepän": "gunsmith", "asekorjaamo": "gunsmith",
    "aseiden huolto": "gunsmith", "aseen huolto": "gunsmith", "büchsenmacher": "gunsmith",
    "buchsenmacher": "gunsmith", "büchsenmacherei": "gunsmith", "waffenschmied": "gunsmith",
    "wapensmid": "gunsmith", "geweermaker": "gunsmith", "vapensmed": "gunsmith", "bøssemager": "gunsmith",
    "børsemaker": "gunsmith", "armurier": "gunsmith", "armero": "gunsmith", "armaiolo": "gunsmith",
    "rusznikarz": "gunsmith", "puškař": "gunsmith",
}

# city (any inflection key) -> display name. Finnish case forms included (Helsingissä ...).
CITIES: dict[str, str] = {
    "helsinki": "Helsinki", "helsingissä": "Helsinki", "helsingistä": "Helsinki", "hki": "Helsinki",
    "espoo": "Espoo", "espoossa": "Espoo", "espoosta": "Espoo",
    "vantaa": "Vantaa", "vantaalla": "Vantaa", "vantaalta": "Vantaa",
    "tampere": "Tampere", "tampereella": "Tampere", "tampereelta": "Tampere",
    "turku": "Turku", "turussa": "Turku", "turusta": "Turku",
    "oulu": "Oulu", "oulussa": "Oulu", "jyväskylä": "Jyväskylä", "jyväskylässä": "Jyväskylä",
    "lahti": "Lahti", "lahdessa": "Lahti", "kuopio": "Kuopio", "kuopiossa": "Kuopio",
    "stockholm": "Stockholm", "göteborg": "Gothenburg", "gothenburg": "Gothenburg", "malmö": "Malmö",
    "oslo": "Oslo", "copenhagen": "Copenhagen", "københavn": "Copenhagen", "tallinn": "Tallinn",
    "riga": "Riga", "vilnius": "Vilnius", "berlin": "Berlin", "munich": "Munich", "münchen": "Munich",
    "hamburg": "Hamburg", "frankfurt": "Frankfurt", "amsterdam": "Amsterdam", "paris": "Paris",
    "london": "London", "madrid": "Madrid", "barcelona": "Barcelona", "rome": "Rome", "milan": "Milan",
    "vienna": "Vienna", "wien": "Vienna", "prague": "Prague", "warsaw": "Warsaw", "budapest": "Budapest",
    "dublin": "Dublin", "brussels": "Brussels", "lisbon": "Lisbon", "zurich": "Zurich", "zürich": "Zurich",
    "new york": "New York", "nyc": "New York", "san francisco": "San Francisco",
}
COUNTRIES: dict[str, str] = {
    "finland": "Finland", "suomi": "Finland", "suomessa": "Finland", "sweden": "Sweden", "sverige": "Sweden",
    "norway": "Norway", "denmark": "Denmark", "estonia": "Estonia", "germany": "Germany",
    "deutschland": "Germany", "france": "France", "spain": "Spain", "italy": "Italy",
    "netherlands": "Netherlands", "poland": "Poland", "austria": "Austria", "uk": "United Kingdom",
    "united kingdom": "United Kingdom", "eu": "EU", "europe": "EU", "usa": "USA", "us": "USA",
}

FILLER = re.compile(
    r"\b(i\s+(?:want|need|would like)(?:\s+to\s+(?:buy|get|find|rent|hire|book))?|looking\s+for|"
    r"searching\s+for|find\s+me|get\s+me|show\s+me|please|pls|cheap(?:est)?|best|good|a\s+good|"
    r"buy|purchase|deal|deals|price|prices|budget|for\s+sale|myydään|ostetaan|halpa)\b",
    re.I,
)
LEAD_ARTICLES = re.compile(r"^(?:(?:a|an|the|some|me|to|for|of|in|on)\s+)+", re.I)
TRAIL_JUNK = re.compile(r"(?:\s+(?:a|an|the|for|in|on|at|of|and|or|with|to|from|near|around))+$", re.I)

# ---------------------------------------------------------------- budget

_NUM = r"((?<![\w.,])\d{1,3}(?:[ .,]\d{3})+|(?<![\d.,])\d+(?:[.,]\d+)?)\s*(k)?(?!\s*(?:gb|tb|mb|mm|mp|hz|cm|kg|w|v|inch|in|\"|m2|m²|l|km|mah|fps|k\b|p\b))"
_CUR_BEFORE = r"(€|\$|£|us\$|¥)"
_CUR_AFTER = r"(€|\$|£|eur(?:os?)?|euros?|usd|dollars?|gbp|pounds?|sek|nok|dkk|kr|chf|pln|zł|zl|czk|kč|huf|ft|jpy|e)(?![a-z])"
_CAP_WORDS = (
    r"under|below|less\s+than|max(?:imum)?\.?|up\s+to|upto|at\s+most|no\s+more\s+than|within|budget(?:\s+of)?|"
    r"alle|enintään|korkeintaan|bis|unter|höchstens|max\.|under\s+than|<=?|≤|tops|cap"
)
BUDGET_PATTERNS = [
    # "under €900", "max $1.2k", "<900e", "budget 900 eur"
    re.compile(rf"(?:{_CAP_WORDS})\s*:?\s*(?:{_CUR_BEFORE})?\s*{_NUM}\s*(?:{_CUR_AFTER})?", re.I),
    # "€900 max", "900€ tops"
    re.compile(rf"(?:{_CUR_BEFORE})?\s*{_NUM}\s*(?:{_CUR_AFTER})?\s*(?:max|tops|or\s+less|at\s+most)\b", re.I),
    # bare money: "€900", "900 €", "900eur"
    re.compile(rf"{_CUR_BEFORE}\s*{_NUM}(?!\w)", re.I),
    re.compile(rf"(?<![\w.]){_NUM}\s*{_CUR_AFTER}", re.I),
]


def _to_number(digits: str, k: str | None) -> float | None:
    s = digits.replace(" ", "")
    # "1.299,00" / "1,299.00" / "1.299" / "1,5"
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{1,2}", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v * 1000 if k else v


def parse_budget(text: str) -> tuple[float | None, str | None, tuple[int, int] | None]:
    """-> (amount, currency or None, span in text). Tries cap phrases before bare amounts."""
    for pat in BUDGET_PATTERNS:
        for m in pat.finditer(text):
            groups = [g for g in m.groups()]
            cur_tok = None
            num = k = None
            # patterns differ in group layout; pick by content
            for g in groups:
                if g is None:
                    continue
                gl = g.lower()
                if num is None and re.fullmatch(r"[\d .,]+", g) and re.search(r"\d", g):
                    num = g
                elif gl == "k" and num is not None and k is None:
                    k = g
                elif gl in CURRENCY_SYMBOLS and cur_tok is None:
                    cur_tok = gl
            if num is None:
                continue
            amount = _to_number(num.strip(), k)
            if amount is None or amount <= 0:
                continue
            is_cap = pat is BUDGET_PATTERNS[0] or pat is BUDGET_PATTERNS[1]
            # "iphone 15 pro max 256": a model name, not a cap
            if is_cap and cur_tok is None and re.search(r"\b(pro|ultra|plus)\s+max\b", m.string[max(0, m.start() - 6): m.end()], re.I):
                continue
            # a bare number with no currency and no cap word ("a7 3") is not a budget
            if not is_cap and cur_tok is None:
                continue
            # "max 3" next to a model ("iphone 15 pro max 256") is not a budget: require money-ish size
            if cur_tok is None and amount < 20:
                continue
            if cur_tok == "e" and not re.search(r"\d\s*e\b", m.group(0), re.I):
                cur_tok = None
            return amount, CURRENCY_SYMBOLS.get(cur_tok or "", None), m.span()
    return None, None, None


# ---------------------------------------------------------------- the rest

def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def _find_words(text: str, vocab: dict[str, Any]) -> list[tuple[str, int, int]]:
    """All vocab keys found as whole words, longest first, non-overlapping."""
    low = text.lower()
    hits: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for key in sorted(vocab, key=len, reverse=True):
        for m in re.finditer(rf"(?<![\w-]){re.escape(key)}(?![\w-])", low):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((key, a, b))
    return hits


def detect_conditions(text: str) -> tuple[list[Condition], list[tuple[int, int]]]:
    hits = _find_words(text, CONDITION_WORDS)
    # "new york" is a place, "news" never matches whole-word anyway
    hits = [h for h in hits if not (h[0] == "new" and re.match(r"new\s+(york|zealand|jersey|delhi)", text.lower()[h[1]:]))]
    conds: list[Condition] = []
    for key, _, _ in sorted(hits, key=lambda h: h[1]):
        c = CONDITION_WORDS[key]
        if c not in conds:
            conds.append(c)
    return conds, [(a, b) for _, a, b in hits]


def detect_service(text: str) -> tuple[str | None, list[tuple[int, int]]]:
    hits = _find_words(text, SERVICE_WORDS)
    if not hits:
        return None, []
    first = min(hits, key=lambda h: h[1])
    return SERVICE_WORDS[first[0]], [(a, b) for _, a, b in hits]


_PLACE_PREP = re.compile(r"(?:\b(?:near|in|around|at|from|within|close\s+to|lähellä)\s+)$", re.I)


def detect_place(text: str) -> tuple[str | None, list[tuple[int, int]]]:
    """City (Finnish case forms, then the European gazetteer in agora.places) before country names.
    'home cleaning tilburg 24m2' -> Tilburg; 'plumber in eindhoven' -> Eindhoven; 'used bike germany' -> Germany."""
    from agora import places
    for vocab in (CITIES, None, COUNTRIES):
        if vocab is None:
            found = places.find_place(text)
            if found is None:
                continue
            name, _, (a, b) = found
            pre = _PLACE_PREP.search(text[:a])
            return name, [((pre.start() if pre else a), b)]
        hits = _find_words(text, vocab)
        if vocab is CITIES:     # 'ikea stockholm rug' is a rug, not a trip
            hits = [h for h in hits if places.place_ok(text, h[0], h[1], places.country_for(vocab[h[0]]))]
        if vocab is COUNTRIES:  # "us"/"eu" only count after a place preposition
            hits = [h for h in hits if len(h[0]) > 2 or re.search(r"\b(in|from|within|to)\s+$", text.lower()[: h[1]])]
        if hits:
            key, a, b = min(hits, key=lambda h: h[1])
            # swallow the preposition before it ("near Helsinki", "in Espoo")
            pre = _PLACE_PREP.search(text[:a])
            return vocab[key], [((pre.start() if pre else a), b)]
    m = re.search(r"\b(?:near|in|around)\s+([A-ZÅÄÖ][\wåäöüß-]+)", text)
    if m and not re.search(r"\d", m.group(1)):
        return m.group(1), [m.span()]
    return None, []


def detect_must_have(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\b(?:with|incl(?:uding|\.)?|must\s+have|that\s+has|\+)\s+([\w\- .\"]+?)(?=\s*$|\s{2,}|,|;|\bunder\b|\bbelow\b|\bmax\b|\bnear\b|\bin\b|\band\b|\bbudget\b)", text, re.I):
        phrase = m.group(1).strip(" .")
        if phrase:
            out.append(phrase.lower())
            spans.append(m.span())
    return out, spans


# ---------------------------------------------------------------- kind: product | service | digital
# A need for a provider's work or a subscription ("web developer for small business", "bookkeeping service
# finland", "unlimited graphic design subscription") is not a thing to buy used: the hunt skips the
# marketplace lanes and lets the service + long-tail lanes lead. Rules first, then agora.taxonomy.

DIGITAL_WORDS = re.compile(
    r"\b(?:subscriptions?|saas|software|licen[cs]es?|vpn|web\s?hosting|hosting|cloud\s+storage|streaming|"
    r"tilaus|kuukausitilaus|abo|abonnement|abonnemang)\b", re.I)
# the provider named by its role: 'software developer' is a person to hire, not software
ROLE_WORDS = re.compile(
    r"\b(?:developers?|designers?|agency|agencies|freelancers?|consultants?|bookkeepers?|accountants?|auditors?|"
    r"lawyers?|attorneys?|solicitors?|translators?|copywriters?|illustrators?|videographers?|programmers?|"
    r"coders?|marketers?|recruiters?|coach|tutors?|virtual\s+assistant)\b", re.I)
SERVICE_HINTS = re.compile(
    r"\b(?:services?|palvelu\w*|dienst\w*|tjänst\w*|developers?|designers?|agency|agencies|freelanc\w*|"
    r"consult\w*|bookkeep\w*|accounting|accountants?|auditors?|lawyers?|attorneys?|solicitors?|notary|"
    r"translat\w*|copywrit\w*|retainer|productized|seo|marketing|branding|web\s?design|web\s?development|"
    r"app\s+development|logo\s+design|graphic\s+design|ux\s+design|video\s?edit\w*|videographer|illustrator|"
    r"virtual\s+assistant|payroll|recruit\w*|coach(?:ing)?|tax\s+advi[sc]\w*|"
    r"kirjanpi\w*|tilitoimist\w*|verkkosivu\w*|mainostoimist\w*|buchhalt\w*|steuerberat\w*|webdesign\w*|"
    r"boekhoud\w*|redovisning\w*|bokför\w*)\b", re.I)
# a thing whose head is an object stays a product: 'laptop for web developer', 'graphic design book'
PRODUCT_HEAD = re.compile(
    r"\b(?:books?|kirja|buch|laptops?|notebooks?|computers?|pc|macbook|monitors?|screens?|displays?|tablets?|"
    r"ipad|phones?|iphone|cameras?|lens(?:es)?|bikes?|bicycles?|chairs?|desks?|tables?|keyboards?|mouse|mice|"
    r"printers?|pens?|headphones|headsets?|speakers?|tv|television|consoles?|shoes|jackets?|bags?|backpacks?|"
    r"kits?|toys?|games?|posters?|mugs?|shirts?|t-shirts?|hoodies?|stickers?|cards?|box|boxes|cables?|"
    r"chargers?|routers?|drives?|ssd|hdd|gpu|cpu|microphones?|mic|lamps?|sofa|bed|shelf|machine|tools?)$",
    re.I)
SPLIT_HEAD = re.compile(r"\s+(?:for|with|to|from|by|för|für|voor|pour|para)\s+", re.I)
TAXO_KIND_ROOTS = {"software": "digital", "professional": "service", "digital-services": "service",
                   "finance-insurance": "service", "utilities": "service", "education": "service"}
TAXO_MIN_CONFIDENCE = 0.55


def product_head(thing: str) -> bool:
    """True when the need names an object ('laptop for web developer', 'graphic design book')."""
    head = SPLIT_HEAD.split(thing.strip(), maxsplit=1)[0].strip()
    return bool(PRODUCT_HEAD.search(head))


def detect_kind(text: str, thing: str | None = None) -> tuple[str | None, str]:
    """-> ('service' | 'digital' | None, why). None = leave the need a product. Keyword rules first
    (a subscription or a provider's work), then agora.taxonomy.classify on the B2B / digital roots only
    (its consumer-service roots catch 'wine club' -> bars), never when the need's head is an object."""
    thing = (thing or text).strip()
    if not thing or product_head(thing):
        return None, "object"
    hay = f"{thing} {text}"
    if ROLE_WORDS.search(hay):
        return "service", "words"
    if DIGITAL_WORDS.search(hay):
        # 'coffee subscription', 'dog food subscription': a product delivered every month stays a product
        core = DIGITAL_WORDS.sub(" ", thing).strip()
        c = _classify(core) if core else None
        if c and c.get("kind") in ("product", "food") and (c.get("confidence") or 0) >= 0.6:
            return None, "physical subscription"
        return "digital", "words"
    if SERVICE_HINTS.search(hay):
        return "service", "words"
    c = _classify(text)
    if c and (c.get("confidence") or 0) >= TAXO_MIN_CONFIDENCE:
        root = (c.get("path_ids") or [""])[0]
        if root in TAXO_KIND_ROOTS:
            return TAXO_KIND_ROOTS[root], "taxonomy"
    return None, "taxonomy"


def _classify(text: str) -> dict[str, Any] | None:
    try:
        from agora import taxonomy
        return taxonomy.classify(text)
    except Exception:            # tree missing or broken: the rules are enough
        return None


def priced_per_period(need: Need) -> bool:
    """A subscription, retainer or B2B service (bookkeeping, a web developer, a design subscription): its
    offers are plans per month / year / hour / project, compared period with period. Local trades the rules
    know (cleaning, plumbing ...) and local-service categories of the tree (a gunsmith, a tailor) keep the job
    costing (rate x hours)."""
    if need.kind == "digital":
        return True
    if need.kind != "service":
        return False
    cat = need.category or {}
    if cat.get("path_ids"):
        if cat.get("kind") == "digital" or cat["path_ids"][0] in TAXO_KIND_ROOTS:
            return True
        return False
    return not any(detect_service(t or "")[0] for t in (need.thing, need.raw))


def service_view(need: Need) -> Need:
    """The need as the service-only stages (agora.resolve, agora.relevance) understand it: a digital need is
    matched like a service (the provider's page names the work), never by product model numbers."""
    if need.kind != "digital":
        return need
    import dataclasses
    return dataclasses.replace(need, kind="service", conditions=list(need.conditions),
                               must_have=list(need.must_have))


# ---------------------------------------------------------------- vehicles
# The tree files 'car' under Scale Models (a toy), so vehicles are told by words: the need's head noun is a
# vehicle ('bright red car', 'volvo xc90', 'käytetty auto'), not something for one ('car seat', 'car charger').
VEHICLE_NOUNS = re.compile(
    r"^(?:cars?|autos?|automobiles?|vehicles?|suvs?|sedans?|saloons?|hatchbacks?|estates?|wagons?|"
    r"station\s?wagons?|convertibles?|cabrio(?:let)?s?|coupes?|minivans?|vans?|pick-?ups?|pickup\s+trucks?|"
    r"autot|henkilöauto\w*|farmari\w*|bil|bilar|bilen|biler|pkw|gebrauchtwagen|kombi|voitures?|coches?|"
    r"macchinas?|samochód|samochody)$", re.I)
CAR_MAKES = re.compile(
    r"\b(?:volvo|toyota|bmw|audi|vw|volkswagen|skoda|škoda|ford|mercedes(?:-benz)?|tesla|nissan|honda|mazda|kia|"
    r"hyundai|peugeot|renault|citroen|citroën|opel|seat|cupra|fiat|alfa romeo|porsche|lexus|subaru|mitsubishi|"
    r"suzuki|dacia|mini cooper|jeep|land rover|range rover|jaguar|polestar|byd|mg|saab|chevrolet|dodge)\b", re.I)
CAR_NOT = re.compile(r"\b(?:seats?|chargers?|holders?|mounts?|covers?|wash|washing|vacuum|cleaner|wax|polish|"
                     r"mats?|parts?|tyres?|tires?|wheels?|rims?|radio|stereo|speakers?|battery|batteries|keys?|"
                     r"rental|rent|insurance|repair|service|toys?|models?|lego|kids?|bed|sticker)\b", re.I)
ATTRIBUTE_WORDS = re.compile(
    r"\b(?:bright|dark|light|pale|deep|metallic|matte|glossy|shiny|red|blue|green|black|white|silver|grey|gray|"
    r"yellow|orange|purple|pink|brown|beige|gold|punainen|sininen|musta|valkoinen|harmaa|rot|blau|schwarz|weiss|"
    r"weiß|röd|blå|svart|vit|rood|blauw|zwart|wit|rouge|noir|blanc)\b", re.I)


def vehicle_need(thing: str) -> bool:
    """True when the need is a vehicle itself: its head noun is one ('bright red car', 'used auto'), or a car
    make heads it without a part/accessory word ('volvo xc90', not 'volvo key cover')."""
    head = SPLIT_HEAD.split((thing or "").strip(), maxsplit=1)[0].strip()
    words = head.split()
    if not words or CAR_NOT.search(head):
        return False
    return bool(VEHICLE_NOUNS.match(words[-1])) or (bool(CAR_MAKES.search(head)) and len(words) <= 5)


def split_attributes(thing: str) -> tuple[str, list[str]]:
    """'bright red car' -> ('car', ['bright red']): colours are a preference, not the item."""
    attrs = [m.group(0) for m in ATTRIBUTE_WORDS.finditer(thing)]
    rest = re.sub(r"\s+", " ", ATTRIBUTE_WORDS.sub(" ", thing)).strip()
    return (rest, [" ".join(attrs).lower()]) if attrs and rest else (thing, [])


def is_service(need: Need) -> bool:
    """Service-like needs (a provider's work, or a digital subscription): no used / refurbished lanes,
    priced per hour / job / month, never resold."""
    return need.kind in ("service", "digital")


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, min(b, len(chars))):
            chars[i] = " "
    return "".join(chars)


def clean_thing(text: str) -> str:
    t = FILLER.sub(" ", text)
    t = re.sub(r"[,;:!?()\[\]]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    t = LEAD_ARTICLES.sub("", t)
    t = TRAIL_JUNK.sub("", t)
    t = re.sub(r"^(?:or|and)\s+|\s+(?:or|and)$", "", t).strip(" -")
    return t


def parse_need_rules(text: str) -> Need:
    raw = _norm(text)
    work = raw
    budget, currency, bspan = parse_budget(work)
    spans: list[tuple[int, int]] = [bspan] if bspan else []
    conds, cspans = detect_conditions(work)
    service, sspans = detect_service(work)
    where, wspans = detect_place(work)
    from agora import places
    wspans += [(a, b) for k, a, b in _find_words(work, CITIES)
               if places.place_ok(work, k, a, places.country_for(CITIES[k]))]
    must, mspans = detect_must_have(_cut(work, spans + wspans))
    spans += cspans + wspans + mspans
    thing = clean_thing(_cut(work, spans))
    need = Need(raw=raw, thing=thing or raw.lower(), budget=budget, currency=currency or "EUR", where=where, must_have=must)
    if service:
        need.kind = "service"
        need.conditions = ["service"]
        if not need.thing or need.thing in SERVICE_WORDS:
            need.thing = service
        if service not in need.must_have and service not in need.thing:
            need.must_have.insert(0, service)
    else:
        _kind_rules(need, raw, conds)    # 'used ...' = a product; else a service / digital need by words + tree
    if need.kind == "product" and vehicle_need(need.thing):
        thing, attrs = split_attributes(need.thing)     # 'bright red car': the thing is 'car', red is a wish
        need.thing = thing
        need.must_have += [a for a in attrs if a not in need.must_have]
        if "refurbished" in need.conditions and len(need.conditions) > 1:
            need.conditions = [c for c in need.conditions if c != "refurbished"]
    return need


def _kind_rules(need: Need, raw: str, conds: list[Condition]) -> None:
    if conds and conds != ["rental"] and any(c != "new" for c in conds):
        need.conditions = conds
    else:
        kind, _ = detect_kind(raw, need.thing)
        if kind is not None:
            need.kind = kind             # type: ignore[assignment]
            need.conditions = ["service"]
        elif conds:
            need.conditions = conds


# ---------------------------------------------------------------- category context (agora.taxonomy)
# A hunt started from the category tree knows what it is looking for: the node's kind (a gunsmith is a
# service, never a gun or a manga called 'Gunsmith Cats'), its lanes, size class, where to look, and its
# labels in the local languages. A typed hunt gets the same context from taxonomy.classify when it is sure.

CLASSIFY_MIN_CONFIDENCE = 0.6
CLASSIFY_MIN_SCORE = 0.85      # 'sony a7 iii' -> 'Sulphates' (0.71 sure, score 0.72) is no category at all
FLIP_MIN_SCORE = 1.0           # a typed need becomes a service only on a strong service node...
FLIP_MIN_MARGIN = 0.3          # ...clearly ahead of the best product node ('sauna' is a thing to buy too)
NO_FLIP_ROOTS = {"food-drink"}  # 'pizza' is a restaurant node, but a price hunt for pizza is not a trade
TREE_KINDS = {"service": "service", "digital": "digital"}   # vehicle / property / food / product -> product
_LANG_OF_LOCAL = {"fi": "fi", "de": "de", "nl": "nl", "se": "sv", "sv": "sv", "dk": "da", "da": "da", "no": "nb",
                  "nb": "nb", "fr": "fr", "es": "es", "it": "it", "pl": "pl", "pt": "pt", "cz": "cs", "cs": "cs"}


def _taxonomy() -> Any | None:
    try:
        from agora import taxonomy
        taxonomy.load()
        return taxonomy
    except Exception:
        return None


def category_words(node: dict[str, Any]) -> dict[str, Any]:
    """The node's names to search with: its labels per language, synonyms, and the trade's local words
    (agora.discover.SERVICE_LOCAL) when the tree only has an English label ('Gunsmith' -> 'aseseppä')."""
    labels = {k: v for k, v in (node.get("labels") or {}).items() if isinstance(v, str) and v}
    svc = detect_service(labels.get("en") or node.get("label") or "")[0]
    try:
        from agora.discover import SERVICE_LOCAL
        local = SERVICE_LOCAL.get(svc or "", {})
    except Exception:
        local = {}
    for key, word in local.items():
        lang = _LANG_OF_LOCAL.get(key, key)
        labels.setdefault(lang, word)
    return {"labels": labels, "synonyms": list(node.get("synonyms") or [])[:12], "service": svc}


def category_info(node_id: str, *, source: str = "tree", confidence: float = 1.0) -> dict[str, Any] | None:
    """A taxonomy node as hunt context (None when the id is unknown or the tree is missing)."""
    tax = _taxonomy()
    if tax is None or not node_id:
        return None
    nid = tax.load().resolve(str(node_id))
    node = tax.node(nid) if nid else None
    if node is None:
        return None
    words = category_words(node)
    domains = [w for w in node.get("where") or [] if w.get("lane") != "comparison"]
    return {"id": node["id"], "label": node["label"], "path": node["path"], "path_ids": node["path_ids"],
            "kind": node["kind"], "lanes": node.get("lanes") or [], "size": node.get("size"),
            "bulky": bool(node.get("bulky")), "domains": domains[:12], "labels": words["labels"],
            "synonyms": words["synonyms"], "service": words["service"], "source": source,
            "confidence": round(float(confidence), 3)}


def apply_category(need: Need, cat: dict[str, Any]) -> Need:
    """Fit the need to its category: the kind (service / digital / product), the lanes (conditions) and, for
    a hunt from the tree, the trade's canonical name so the local-language queries know the job."""
    need.category = cat
    tree_kind = TREE_KINDS.get(cat.get("kind") or "", "product")
    if tree_kind in ("service", "digital"):
        need.kind = tree_kind          # type: ignore[assignment]
        need.conditions = ["service"] + (["rental"] if "rental" in need.conditions else [])
        svc = cat.get("service")
        if svc and svc not in need.must_have and svc not in need.thing:
            need.must_have.insert(0, svc)
        return need
    need.kind = "product"
    lanes = [c for c in (cat.get("lanes") or []) if c in ("new", "used", "refurbished", "rental")]
    asked = [c for c in need.conditions if c != "service"]
    if not asked or asked == ["new", "refurbished", "used"] or asked == ["service"]:
        need.conditions = lanes or ["new", "refurbished", "used"]   # type: ignore[assignment]
    return need


def categorize(need: Need, category: str | None = None) -> dict[str, Any] | None:
    """Attach the category context; returns the `category` event payload {id, path, kind, confidence,
    source: "tree" | "classified"} or None.

    category given (a hunt from the tree): that node decides the kind, always.
    Typed text: taxonomy.classify (confidence >= CLASSIFY_MIN_CONFIDENCE), combined with the rules: a need the
    rules made a service stays one and gains the node's words; a need the rules left a product becomes a
    service only on a strong, unambiguous service node with no condition words ('used ...') and no object
    head ('laptop for ...'); otherwise the node is attached only when its kind agrees."""
    if category:
        cat = category_info(category, source="tree", confidence=1.0)
        if cat is None:
            return None
        apply_category(need, cat)
        return _cat_event(cat)
    tax = _taxonomy()
    if tax is None:
        return None
    try:
        c = tax.classify(need.raw)
    except Exception:
        c = None
    def weak(x: dict[str, Any] | None) -> bool:
        return not x or (x.get("confidence") or 0) < CLASSIFY_MIN_CONFIDENCE \
            or (x.get("score") or 0) < CLASSIFY_MIN_SCORE
    if weak(c) and need.kind == "service":
        svc = detect_service(need.raw)[0]
        try:   # 'aseseppä helsinki', 'wapensmid amsterdam' -> the trade's English name finds the node
            c2 = tax.classify(svc) if svc else None
        except Exception:
            c2 = None
        c = c2 if not weak(c2) else c
    if weak(c):
        return None
    cat = category_info(c["id"], source="classified", confidence=c.get("confidence") or 0)
    if cat is None:
        return None
    node_kind = TREE_KINDS.get(cat["kind"], "product")
    if need.kind in ("service", "digital"):
        if node_kind == "product":
            return None                 # the rules' words beat a weak product guess
        need.category = cat
        if not need.must_have and cat.get("service") and cat["service"] not in need.thing:
            need.must_have.insert(0, cat["service"])
        return _cat_event(cat)
    if node_kind == "product":
        need.category = cat
        return _cat_event(cat)
    # the rules said product, the tree says service: flip only when the tree is sure and nothing says object
    if need.conditions not in (["new", "refurbished", "used"], ["new"]) or product_head(need.thing) \
            or vehicle_need(need.thing) or cat["path_ids"][0] in NO_FLIP_ROOTS \
            or (c.get("score") or 0) < FLIP_MIN_SCORE:
        return None
    try:
        prod = tax.search(c.get("query") or need.thing, limit=1, kind="product")
    except Exception:
        prod = []
    if prod and (c.get("score") or 0) - prod[0]["score"] < FLIP_MIN_MARGIN:
        return None
    apply_category(need, cat)
    return _cat_event(cat)


def _cat_event(cat: dict[str, Any]) -> dict[str, Any]:
    return {"id": cat["id"], "label": cat["label"], "path": cat["path"], "kind": cat["kind"],
            "confidence": cat["confidence"], "source": cat["source"], "lanes": cat["lanes"],
            "size": cat.get("size"), "domains": [d["domain"] for d in cat.get("domains") or []][:8]}


# ---------------------------------------------------------------- Gemini (optional)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_PROMPT = """You turn a shopping request into JSON.
{request}
Return only JSON with keys:
thing (short lowercase item or service, no budget/place/condition words, keep model numbers),
kind ("product"|"service"), budget (number or null, only if stated), currency (ISO code or null),
where (city/country or null), conditions (subset of new, refurbished, used, rental, service; [] if not stated),
must_have (list of short strings)."""


def gemini_prompt(text: str) -> str:
    """The request goes in fenced and cleaned (agora.fence): it may come from an agent that copied page
    text, so role tags, control characters and 'ignore previous instructions' are inert data here."""
    from agora import fence
    return _PROMPT.format(request=fence.fence(text, source="shopping request", max_chars=1000))


def _gemini(text: str, timeout: float = 6.0) -> dict[str, Any] | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = {
        "contents": [{"parts": [{"text": gemini_prompt(text)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    try:
        r = httpx.post(GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": key}, timeout=timeout)
        r.raise_for_status()
        part = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(part)
        return data if isinstance(data, dict) else None
    except Exception:  # network, quota, bad JSON: rules are good enough
        return None


def _merge(rules: Need, llm: dict[str, Any]) -> Need:
    valid_conds = set(get_args(Condition))
    thing = llm.get("thing")
    if isinstance(thing, str) and 1 < len(thing) < 120:
        rules.thing = thing.strip().lower()
    if llm.get("kind") in ("product", "service") and rules.kind == "product" and not product_head(rules.thing):
        rules.kind = llm["kind"]
        if rules.kind == "service":
            rules.conditions = ["service"]
    # numbers: trust what we read ourselves; take the LLM's only if it is literally in the text
    b = llm.get("budget")
    if rules.budget is None and isinstance(b, (int, float)) and b > 0 and re.search(rf"\b{int(b)}\b", rules.raw.replace(" ", "")):
        rules.budget = float(b)
        if isinstance(llm.get("currency"), str) and len(llm["currency"]) == 3:
            rules.currency = llm["currency"].upper()
    if rules.where is None and isinstance(llm.get("where"), str) and llm["where"].strip():
        rules.where = llm["where"].strip()
    conds = [c for c in llm.get("conditions") or [] if c in valid_conds]
    if conds and rules.conditions == ["new", "refurbished", "used"] and rules.kind == "product":
        rules.conditions = conds
    for m in llm.get("must_have") or []:
        if isinstance(m, str) and m.lower() not in rules.must_have:
            rules.must_have.append(m.lower())
    return rules


def parse_need(text: str) -> Need:
    """Free text -> Need. Rules always; Gemini fills gaps when GEMINI_API_KEY is set."""
    need = parse_need_rules(text)
    llm = _gemini(text)
    return _merge(need, llm) if llm else need
