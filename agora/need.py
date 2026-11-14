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
    r"\b((?:i\s+(?:am|'m)\s+|i'm\s+|im\s+|we\s+(?:are|'re)\s+)?looking\s+(?:to\s+(?:buy|get|find)|for)|"
    r"(?:can|could|would)\s+you\s+(?:please\s+)?(?:find|get|search|show)(?:\s+me)?|help\s+me\s+(?:to\s+)?find|"
    r"where\s+(?:can|do)\s+i\s+(?:buy|get|find)|i(?:'d|\s+would)\s+like(?:\s+to\s+(?:buy|get|find|have))?|"
    r"(?:i|we)\s+(?:want|need|wanna)(?:\s+to\s+(?:buy|get|find|rent|hire|book|purchase|order))?|"
    r"do\s+you\s+(?:have|sell)|searching\s+for|find\s+me|get\s+me|show\s+me|please|pls|cheap(?:est)?|best|good|a\s+good|"
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


# a specific job inside a trade: the job is what is hunted, never the trade's generic name (eval r4: 'glazenwasser
# utrecht' became 'cleaning' and every result was a house cleaner). phrase (any language) -> the job in English
SPECIFIC_JOBS: dict[str, str] = {
    "window cleaning": "window cleaning", "window cleaner": "window cleaning", "window cleaners": "window cleaning",
    "window washing": "window cleaning", "window washer": "window cleaning",
    "glazenwasser": "window cleaning", "glazenwassers": "window cleaning", "glazenwassen": "window cleaning",
    "glazenwasserij": "window cleaning", "ramen wassen": "window cleaning", "glasbewassing": "window cleaning",
    "fensterputzer": "window cleaning", "fensterreinigung": "window cleaning", "fensterputzen": "window cleaning",
    "glasreinigung": "window cleaning", "ikkunanpesu": "window cleaning", "ikkunanpesijä": "window cleaning",
    "ikkunanpesua": "window cleaning", "ikkunoiden pesu": "window cleaning", "fönsterputs": "window cleaning",
    "fönsterputsning": "window cleaning", "fönsterputsare": "window cleaning", "vinduespudsning": "window cleaning",
    "vinduespudser": "window cleaning", "vindusvask": "window cleaning", "laveur de vitres": "window cleaning",
    "nettoyage de vitres": "window cleaning", "limpieza de cristales": "window cleaning",
    "lavavetri": "window cleaning", "mycie okien": "window cleaning",
    "carpet cleaning": "carpet cleaning", "carpet cleaner": "carpet cleaning", "tapijtreiniging": "carpet cleaning",
    "teppichreinigung": "carpet cleaning", "mattopesu": "carpet cleaning", "mattojen pesu": "carpet cleaning",
    "mattvätt": "carpet cleaning", "tæpperens": "carpet cleaning",
    "gutter cleaning": "gutter cleaning", "dakgootreiniging": "gutter cleaning", "dachrinnenreinigung": "gutter cleaning",
    "rännien puhdistus": "gutter cleaning", "kattorännien puhdistus": "gutter cleaning",
    "upholstery cleaning": "upholstery cleaning", "sohvan pesu": "upholstery cleaning",
    "bankstel reinigen": "upholstery cleaning", "polsterreinigung": "upholstery cleaning",
    "oven cleaning": "oven cleaning", "end of tenancy cleaning": "end of tenancy cleaning",
    "muuttosiivous": "end of tenancy cleaning", "eindschoonmaak": "end of tenancy cleaning",
    "opleveringsschoonmaak": "end of tenancy cleaning", "endreinigung": "end of tenancy cleaning",
    "flyttstädning": "end of tenancy cleaning",
}
_FOLD_JOBS = {re.sub(r"\s+", " ", k.lower()): v for k, v in SPECIFIC_JOBS.items()}


def specific_job(text: str) -> str | None:
    """'glazenwasser utrecht' -> 'window cleaning', 'Fensterputzer Berlin' -> 'window cleaning'; None when the
    words name no specific job inside a trade."""
    hits = _find_words((text or "").lower(), _FOLD_JOBS)
    if not hits:
        return None
    first = min(hits, key=lambda h: h[1])
    return _FOLD_JOBS[first[0]]


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
    if us := places.us_place(text):
        # 'plumber berlin ct' / 'Berlin, Connecticut': the user named the US namesake (a bare 'berlin' is Germany)
        name, (a, b) = us
        pre = _PLACE_PREP.search(text[:a])
        return name, [((pre.start() if pre else a), b)]
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


# 'no X / without X / ei X / ilman X / ohne X / kein X / zonder X / utan X / uten X / sans X' -> need.must_not
# (the judges' 'PS5 no GTA bundle'). Product names that start with 'no' are not exclusions.
_NOT_WORD = r"(?:no|without|w/o|ei|ilman|ohne|keine?n?|zonder|geen|utan|uten|uden|sans|senza|bez)"
_NOT_STOP = (r"(?=\s*$|\s*[,;(]|\s+(?:and|or|with|incl\w*|under|below|max|near|in|for|budget|ja|tai|und|oder|"
             r"en|och|og|et|alle|unter|enintään|max\w*|bis|tot|till|but|mutta|aber|maar)\b|\s+[<€$£]|\s+\d)")
NOT_RE = re.compile(rf"(?<![\w-])({_NOT_WORD})\s+((?:[^\W\d][\w'\-+.]*)(?:\s+[^\W\d][\w'\-+.]*){{0,2}}?){_NOT_STOP}",
                    re.I)
# 'no frost' fridges, 'No Man's Sky', 'No Time to Die', a 'no name' brand, 'ei-' compounds handled by (?<!-)
_NOT_PRODUCT_NAME = re.compile(r"^(?:frost|name|man'?s?|time|country|mercy|limits?|strings|doubt|sleep|game|"
                               r"one|more|way|exit|escape|logo|fear|regrets?)\b", re.I)


def detect_must_not(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """What the thing must not be or come with: (phrases lower-cased, spans to cut from the thing)."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in NOT_RE.finditer(text):
        word, phrase = m.group(1).lower(), m.group(2).strip(" .").lower()
        if not phrase or (word == "no" and _NOT_PRODUCT_NAME.match(phrase)):
            continue
        if phrase not in out:
            out.append(phrase)
        spans.append(m.span())
    # never cut the whole text away ('no frost' is caught above; 'ohne' alone is not a need)
    if spans and not _cut(text, spans).strip(" ,;"):
        return [], []
    return out, spans


def _not_stem(w: str) -> str:
    """A word start that survives inflection: 'spiele' -> 'spiel', 'cushions' -> 'cushio', Finnish partitive
    plurals keep only the root ('pelejä' -> 'pel', so 'peliä' / 'pelit' hit)."""
    if len(w) >= 5 and re.search(r"(?:jä|ja|iä|ia|tä|ta|ä)$", w):
        return w[:3]
    return w if len(w) <= 4 else w[:max(4, len(w) - 2)]


def must_not_hit(need: Need, text: str) -> str | None:
    """The must-not phrase a title / page text names, else None. Every word of the phrase must appear (as a word
    or a word start: 'gta' hits 'GTA V', 'pelejä' needs 'peli'); for agora.resolve's relevance check."""
    hay = (text or "").lower()
    if not hay:
        return None
    for phrase in getattr(need, "must_not", None) or []:
        words = [w for w in re.findall(r"[^\W_][\w'+]*", phrase.lower()) if len(w) >= 2]
        if words and all(re.search(rf"(?<![^\W_]){re.escape(_not_stem(w))}", hay) for w in words):
            return phrase
    return None


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
# a gift is a thing to buy (eval r1: 'gift for mom' became a 'Financial, Tax & Accounting Software' need)
GIFT_WORDS = re.compile(
    r"^(?:\w+\s+){0,2}(?:gifts?|presents?|gift\s+ideas?|lahja\w*|lahjaidea\w*|geschenk\w*|geschenkidee\w*|"
    r"present(?:er|idé\w*)?|gåva|gåvor|cadeau\w*|gave(?:r|idé\w*)?)\b", re.I)
# the words that make a subscription software / a digital good, not a provider's work
SOFTWARE_WORDS = re.compile(
    r"\b(?:saas|software|apps?|licen[cs]es?|vpn|web\s?hosting|hosting|cloud\s+storage|streaming|ohjelm\w*|"
    r"programm?e?s?|tool|tools|plugin|plugins|template|templates|fonts?)\b", re.I)
PERIOD_WORDS = re.compile(r"\b(?:subscriptions?|unlimited|retainer|kuukausitilaus\w*|abo|abonnement\w*|abonnemang)\b",
                          re.I)


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
    if GIFT_WORDS.search(thing) and not DIGITAL_WORDS.search(thing) and not ROLE_WORDS.search(thing):
        return None, "gift"              # 'gift for mom', 'lahja äidille': things to buy, never software
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
    if c and (c.get("confidence") or 0) >= TAXO_MIN_CONFIDENCE and _names_node(thing, c):
        root = (c.get("path_ids") or [""])[0]
        if root in TAXO_KIND_ROOTS:
            return TAXO_KIND_ROOTS[root], "taxonomy"
    return None, "taxonomy"


_STOP = {"for", "with", "and", "the", "a", "an", "my", "of", "to", "in", "on", "best", "cheap", "new", "used"}


def _stem(w: str) -> str:
    return re.sub(r"(?:ies|es|s)$", "", w.lower())[:6]


def _names_node(thing: str, c: dict[str, Any]) -> bool:
    """The classified node shares a word with the need (its label, synonyms or labels in any language): a
    software / B2B root may only flip a need it actually names ('gift for mom' is no accounting software)."""
    words = {_stem(w) for w in re.findall(r"[^\W\d_]{4,}", thing or "") if w.lower() not in _STOP}
    if not words:
        return False
    names = [str(c.get("label") or "")] + [str(x) for x in (c.get("synonyms") or [])]
    names += [str(v) for v in (c.get("labels") or {}).values() if isinstance(v, str)]
    have = {_stem(w) for n in names for w in re.findall(r"[^\W\d_]{4,}", n)}
    return bool(words & have)


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
    if PERIOD_WORDS.search(f"{need.thing} {need.raw}"):
        return True                  # 'unlimited graphic design subscription': plans per month, whatever the node
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


# ---------------------------------------------------------------- the language a query is typed in
# eval r1: 'kinderwagen gebraucht' was read as English and searched as 'kinderwagen käytetty myydään tori'.
LANG_WORDS: dict[str, re.Pattern[str]] = {
    "fi": re.compile(r"\b(?:käytetty\w*|kaytetty|uusi|myydään|ostetaan|halpa|hinta|lähellä|puhelin|pyörä|sohva|"
                     r"rattaat|lastenrattaat|auto[nt]?|kahvinkeitin|pöytä|tuoli|hylly|takki|kengät|lahja\w*|äidille|"
                     r"isälle|siivous|putkimies|parturi|kampaamo|helsingissä|espoossa|tampereella|turussa)\b", re.I),
    "de": re.compile(r"\b(?:gebraucht\w*|neu|neue[rsn]?|günstig\w*|kaufen|für|mit|kinderwagen|fahrrad|handy|"
                     r"waschmaschine|kühlschrank|tisch|stuhl|schrank|jacke|schuhe|geschenk\w*|mutter|mama|"
                     r"klempner|friseur|reinigung|putzfrau|in der nähe|preis)\b", re.I),
    "sv": re.compile(r"\b(?:begagnad\w*|ny|nya|billig\w*|köpa|cykel|barnvagn|soffa|bord|stol|jacka|skor|"
                     r"present|mamma|rörmokare|frisör|städning|pris)\b", re.I),
    "nl": re.compile(r"\b(?:tweedehands|gebruikt\w*|nieuw\w*|goedkoop|kopen|fiets|kinderwagen|bank|tafel|stoel|"
                     r"jas|schoenen|cadeau\w*|moeder|loodgieter|kapper|schoonmaak\w*|prijs)\b", re.I),
}
LANG_COUNTRY = {"fi": "fi", "de": "de", "sv": "se", "nl": "nl"}
# words several languages share do not decide alone ('kinderwagen' is Dutch and German, 'auto' half of Europe)
SHARED_WORDS = {"kinderwagen", "auto", "autot", "bank", "present", "ny"}


def query_language(text: str) -> str | None:
    """ISO language the query is typed in when its words say so ('kinderwagen gebraucht' -> 'de', 'puhelin' ->
    'fi'), else None (English, a brand or a model number: nothing to tell)."""
    low = (text or "").lower()
    scores: dict[str, float] = {}
    for lang, rx in LANG_WORDS.items():
        for m in rx.finditer(low):
            w = m.group(0)
            scores[lang] = scores.get(lang, 0.0) + (0.5 if w in SHARED_WORDS else 1.0)
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 1.0 or (len(ranked) > 1 and ranked[0] - ranked[1] < 0.5):
        return None
    return best


# ---------------------------------------------------------------- a generic vehicle, in the home language
CAR_WORD = {"fi": "auto", "de": "auto", "sv": "bil", "nl": "auto", "da": "bil", "nb": "bil", "fr": "voiture",
            "es": "coche", "it": "auto", "pl": "samochód", "cs": "auto"}
COLOUR_WORDS: dict[str, dict[str, str]] = {
    "red": {"fi": "punainen", "de": "rot", "sv": "röd", "nl": "rood", "da": "rød", "nb": "rød"},
    "blue": {"fi": "sininen", "de": "blau", "sv": "blå", "nl": "blauw", "da": "blå", "nb": "blå"},
    "black": {"fi": "musta", "de": "schwarz", "sv": "svart", "nl": "zwart", "da": "sort", "nb": "svart"},
    "white": {"fi": "valkoinen", "de": "weiß", "sv": "vit", "nl": "wit", "da": "hvid", "nb": "hvit"},
    "silver": {"fi": "hopea", "de": "silber", "sv": "silver", "nl": "zilver", "da": "sølv", "nb": "sølv"},
    "grey": {"fi": "harmaa", "de": "grau", "sv": "grå", "nl": "grijs", "da": "grå", "nb": "grå"},
    "gray": {"fi": "harmaa", "de": "grau", "sv": "grå", "nl": "grijs", "da": "grå", "nb": "grå"},
    "green": {"fi": "vihreä", "de": "grün", "sv": "grön", "nl": "groen", "da": "grøn", "nb": "grønn"},
    "yellow": {"fi": "keltainen", "de": "gelb", "sv": "gul", "nl": "geel", "da": "gul", "nb": "gul"},
    "orange": {"fi": "oranssi", "de": "orange", "sv": "orange", "nl": "oranje", "da": "orange", "nb": "oransje"},
    "brown": {"fi": "ruskea", "de": "braun", "sv": "brun", "nl": "bruin", "da": "brun", "nb": "brun"},
}


def vehicle_words(need: Need, lang: str | None) -> str | None:
    """A generic vehicle need in the marketplace's language: 'bright red car' -> 'punainen auto' for tori
    (eval r1: tori was searched for the English 'car' and returned 229 toys). None when the need names a make or
    model (those words work in every language) or is no vehicle."""
    if need.kind != "product" or not vehicle_need(need.thing) or CAR_MAKES.search(need.thing or ""):
        return None
    words = [w for w in re.findall(r"[\w-]+", need.thing.lower()) if not VEHICLE_NOUNS.match(w)
             and not ATTRIBUTE_WORDS.fullmatch(w)]
    if words:
        return None                      # 'electric car', 'family car': keep the person's own words
    lang = lang or "en"
    colours = [COLOUR_WORDS[c].get(lang, c) if lang != "en" else c
               for m in need.must_have for c in re.findall(r"[a-z]+", m.lower()) if c in COLOUR_WORDS]
    noun = CAR_WORD.get(lang, "car") if lang != "en" else "car"
    return " ".join(colours[:1] + [noun])


def is_service(need: Need) -> bool:
    """Service-like needs (a provider's work, or a digital subscription): no used / refurbished lanes,
    priced per hour / job / month, never resold."""
    return need.kind in ("service", "digital")


# ---------------------------------------------------------------- services bought from the home country's market
# Insurance, banking, energy and phone contracts are sold per country (licensed, priced per driver / home / meter),
# quoted rather than listed, and bought where you live even when no place was typed (eval r2: 'Car insurance' from
# the tree searched in English with no country and found only US insurers in USD).
NATIONAL_WORDS = re.compile(
    r"\b(?:insurances?|vakuutu\w*|versicherung\w*|försäkring\w*|forsikring\w*|verzekering\w*|assurance|"
    r"mortgages?|asuntolaina\w*|loans?|laina|kredit\w*|hypothek\w*|bolån|hypotheek|bank accounts?|pankkitili\w*|"
    r"electricity contracts?|electricity|sähkösopimu\w*|sähkö|strom(?:tarif\w*|vertrag\w*)?|elavtal|energiecontract|"
    r"broadband|laajakaista\w*|mobile plans?|phone plans?|liittymä\w*|handyvertrag\w*|mobilabonnemang)\b", re.I)
NATIONAL_ROOTS = ("finance-insurance", "utilities")


def national_service(need: Need) -> bool:
    """A service sold per country and priced by quote (insurance, loans, energy, phone plans): searched in the
    home country and its language when no place is asked."""
    if need.kind not in ("service", "digital"):
        return False
    cat = need.category or {}
    ids = [str(x) for x in cat.get("path_ids") or []]
    if ids and any(ids[0].startswith(r) for r in NATIONAL_ROOTS) and not ids[0].startswith("software"):
        return True
    return bool(NATIONAL_WORDS.search(f"{need.thing} {need.raw} {cat.get('label') or ''}"))


QUOTE_WORDS = re.compile(r"\b(?:insurances?|vakuutu\w*|versicherung\w*|försäkring\w*|forsikring\w*|"
                         r"verzekering\w*|assurance|mortgages?|loans?|laina\w*|kredit\w*|catering|pitopalvelu\w*)\b",
                         re.I)


def quote_based(need: Need) -> bool:
    """Priced by a personal quote (insurance per driver, a loan per applicant, catering per event): providers
    publish calculators and examples, rarely a price list."""
    cat = need.category or {}
    return need.kind in ("service", "digital") and bool(
        QUOTE_WORDS.search(f"{need.thing} {need.raw} {cat.get('label') or ''} {' '.join(cat.get('path') or [])}"))


# ---------------------------------------------------------------- who a thing is for (women's, men's, kids')
AUDIENCE_RE = re.compile(
    r"\b(?:(women|womens|women's|woman's|ladies|ladies'|female|naisten|damen|dames|dam)|"
    r"(men|mens|men's|man's|male|miesten|herren|heren|herr)|"
    r"(kids|kid's|kids'|children|children's|childrens|child|lasten|kinder|barn|girls?|boys?|tyttöjen|poikien))\b",
    re.I)
AUDIENCE_WORDS: dict[str, dict[str, str]] = {
    "women": {"en": "women", "fi": "naisten", "sv": "dam", "nb": "dame", "no": "dame", "da": "dame", "de": "damen",
              "nl": "dames", "pl": "damska", "fr": "femme", "es": "mujer", "it": "donna", "cs": "dámská"},
    "men": {"en": "men", "fi": "miesten", "sv": "herr", "nb": "herre", "no": "herre", "da": "herre", "de": "herren",
            "nl": "heren", "pl": "męska", "fr": "homme", "es": "hombre", "it": "uomo", "cs": "pánská"},
    "kids": {"en": "kids", "fi": "lasten", "sv": "barn", "nb": "barn", "no": "barn", "da": "børne", "de": "kinder",
             "nl": "kinder", "pl": "dziecięca", "fr": "enfant", "es": "niño", "it": "bambino", "cs": "dětská"},
}


# words that are also something else in a service ('barn painting', 'dam repair', 'Herr Müller'): products only
_SERVICE_NOT_AUDIENCE = frozenset({"barn", "dam", "herr", "child", "female", "male", "girl", "boy", "girls", "boys"})
# children's clothing brands: 'reima talvihaalari' is a kids' snowsuit (QUALITY_REPORT: Reima, 150 cm)
KIDS_BRANDS = re.compile(r"\b(?:reima|lassie|molo|polarn\s*o\.?\s*pyret|ticket\s+to\s+heaven|mini\s+rodini|"
                         r"kuling|color\s+kids|name\s+it|joha|metsola\s+kids|tutta|gugguu)\b", re.I)
# clothing sizes in cm (50-170) or a size label: kids' sizes ('talvitakki 150 cm', 'koko 110', 'size 128')
_KIDS_SIZE = re.compile(r"\b(?:(?:koko|size|gr\.?|größe|grösse|str\.?|storlek|maat|taille)\s*)?"
                        r"(5[0-9]|6[0-9]|[7-9][0-9]|1[0-6][0-9]|170)(?:\s*/\s*\d{2,3})?\s*(cm)?\b", re.I)
_SIZE_LABEL = re.compile(r"\b(?:koko|size|gr\.?|größe|grösse|str\.?|storlek|maat|taille)\s*\d", re.I)


def _kids_by_size(text: str) -> bool:
    """A garment with a children's size: '150 cm' or 'koko 110' next to clothing words (a '150 cm' table is no
    kids' table: the garment check comes first)."""
    try:
        from agora.resolve import APPAREL_NEED
    except Exception:
        return False
    if not APPAREL_NEED.search(text):
        return False
    for m in _KIDS_SIZE.finditer(text):
        if m.group(2) or _SIZE_LABEL.match(text, m.start()):
            return True
    return False


def audience(need: Need) -> str | None:
    """'women' | 'men' | 'kids' when the words say who the thing is for ('winter jacket women', 'naisten
    talvitakki', 'Damen Winterjacke', 'reima talvihaalari', 'talvitakki 150 cm'; services: 'naisten parturi'),
    else None. Never for a vehicle."""
    if need.kind not in ("product", "service") or vehicle_need(need.thing or ""):
        return None
    raw = _cut(need.raw, detect_must_not(need.raw)[1]) if getattr(need, "must_not", None) else need.raw
    text = f"{raw} {need.thing} {' '.join(need.must_have)}"
    for m in AUDIENCE_RE.finditer(text):
        if need.kind == "service" and m.group(0).lower() in _SERVICE_NOT_AUDIENCE:
            continue
        if re.search(r"\bno\s+$", text[:m.start()], re.I):       # 'No Man's Sky' is a game, not men's wear
            continue
        return "women" if m.group(1) else "men" if m.group(2) else "kids"
    if need.kind == "product" and (KIDS_BRANDS.search(text) or _kids_by_size(text)):
        return "kids"
    return None


def keep_audience(need: Need) -> None:
    """Who it is for stays in need.must_have ('women', 'men', 'kids'): every lane and the relevance check see it
    (QUALITY_REPORT: 'women', 'naisten', 'Damen' were dropped)."""
    who = audience(need)
    if who and who not in need.must_have:
        need.must_have.append(who)


def audience_word(who: str | None, lang: str | None) -> str | None:
    """The audience in a marketplace's language ('women', 'fi' -> 'naisten')."""
    if not who:
        return None
    words = AUDIENCE_WORDS.get(who) or {}
    return words.get(lang or "en") or words.get({"se": "sv", "dk": "da", "cz": "cs"}.get(lang or "", ""))


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


# ---------------------------------------------------------------- typos in brand and product-line names
# eval r3: 'samsng galaxy s24 ultra' searched every marketplace for 'samsng' (tori gave no total, proshop sold SSDs).
# Only distinctive names (no common word is one edit away), only words of 5+ letters, never the first letter.
BRAND_NAMES = (
    "samsung", "iphone", "macbook", "airpods", "playstation", "nintendo", "xiaomi", "huawei", "lenovo", "logitech",
    "philips", "electrolux", "garmin", "fujifilm", "oneplus", "motorola", "nvidia", "geforce", "radeon", "galaxy",
    "volkswagen", "mercedes", "hyundai", "porsche", "peugeot", "renault", "citroen", "polestar", "makita",
    "dewalt", "husqvarna", "karcher", "roomba", "nespresso", "delonghi", "thinkpad", "chromebook", "sennheiser",
    "marshall", "panasonic", "olympus", "toshiba", "gigabyte", "corsair", "razer", "steelseries", "playstation",
    "ikea", "dyson", "bosch", "siemens", "miele", "whirlpool", "jabra", "gopro", "hasselblad", "pixel",
    # owner 15 Nov: 'hawaianas' searched every marketplace for a word nobody sells
    # (never a name one edit from a common word: 'shark'/'share', 'braun'/'brain', 'dreame'/'dreams')
    "havaianas", "birkenstock", "reebok", "timberland", "ecovacs", "roborock", "irobot", "rowenta", "fiskars",
    "marimekko", "iittala", "patagonia", "fjällräven", "haglöfs", "playmobil", "brompton", "shimano", "bugaboo",
    "breville", "vileda")
_NOT_TYPOS = {"phone", "phones", "galaxie", "pixels", "razor", "razors", "racer", "racers", "marshal", "phillips"}


def _one_edit(a: str, b: str) -> bool:
    """True when a and b differ by one insertion, deletion, substitution or swap of two neighbours."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


def correct_spelling(text: str) -> tuple[str, list[tuple[str, str]]]:
    """'samsng galaxy s24 ultra' -> ('samsung galaxy s24 ultra', [('samsng', 'samsung')]). A word is corrected
    only to a known brand / product-line name one edit away with the same first letter (so 'phone' never becomes
    'iphone'); everything else is left exactly as typed."""
    fixes: list[tuple[str, str]] = []

    def fix(m: re.Match[str]) -> str:
        w = m.group(0)
        low = w.lower()
        if len(low) < 5 or low in BRAND_NAMES or low in _NOT_TYPOS or any(c.isdigit() for c in low):
            return w
        for b in BRAND_NAMES:
            if len(b) >= 5 and b[0] == low[0] and _one_edit(low, b):
                fixes.append((w, b))
                return b
        return w
    out = re.sub(r"[^\W\d_]+", fix, text or "")
    return out, fixes


# a request typed as a sentence ('i want to buy some ...', 'looking for a ...'): its colour words are wishes too
CHATTY = re.compile(r"^\s*(?:hi|hey|hello|please|pls)?[\s,]*(?:(?:i|we)\s+(?:want|need|wanna|would\s+like|'d\s+like)|"
                    r"i'd\s+like|(?:i\s+am\s+|i'm\s+|im\s+)?looking\s+(?:for|to)|can\s+you|could\s+you|"
                    r"help\s+me|where\s+can\s+i|searching\s+for|find\s+me|get\s+me)\b", re.I)


def split_wishes(raw: str, text: str, thing: str) -> tuple[str, list[dict[str, Any]]]:
    """A chatty or detailed product request -> (core item, soft wishes) via agora.prefs: 'i want to buy some
    havaianas, size 44 1/3 purple color' -> ('havaianas', [size 44 1/3, purple]). A vehicle keeps its own colour
    handling ('bright red car'); a request with no wish comes back unchanged."""
    if not thing or vehicle_need(thing):
        return thing, []
    from agora import prefs
    chatty = bool(CHATTY.search(raw)) or len(re.findall(r"[^\W\d_]+", raw)) >= 8
    core_text, wishes, _ = prefs.split(text, chatty=chatty)
    if not wishes:
        return thing, []
    core = clean_thing(core_text)
    if not core or vehicle_need(core):
        return thing, []
    return core, wishes


def parse_need_rules(text: str) -> Need:
    raw = correct_spelling(_norm(text))[0]
    work = raw
    budget, currency, bspan = parse_budget(work)
    spans: list[tuple[int, int]] = [bspan] if bspan else []
    must_not, nspans = detect_must_not(_cut(work, spans))
    spans += nspans
    conds, cspans = detect_conditions(_cut(work, nspans))
    service, sspans = detect_service(work)
    where, wspans = detect_place(work)
    from agora import places
    wspans += [(a, b) for k, a, b in _find_words(work, CITIES)
               if places.place_ok(work, k, a, places.country_for(CITIES[k]))]
    must, mspans = detect_must_have(_cut(work, spans + wspans))
    spans += cspans + wspans + mspans
    thing = clean_thing(_cut(work, spans))
    wishes: list[dict[str, Any]] = []
    if not service:
        thing, wishes = split_wishes(raw, _cut(work, spans), thing)
    need = Need(raw=raw, thing=thing or raw.lower(), budget=budget, currency=currency or "EUR", where=where,
                must_have=must, must_not=must_not, prefs=wishes)
    if service:
        need.kind = "service"
        need.conditions = ["service"]
        if job := specific_job(raw):
            need.thing = job              # 'glazenwasser' is a window cleaner, not any cleaner
        elif not need.thing or need.thing in SERVICE_WORDS:
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
    _drop_unwanted_conditions(need)
    keep_audience(need)
    apply_platform(need)
    return need


def apply_platform(need: Need) -> Need:
    """ITEM + PLATFORM (agora.platforms): 'gta 6 ps5' is the game GTA 6 for a PS5 (thing 'gta 6', for_platform
    'ps5', item_kind 'game'), 'iphone 15 case' a case for an iPhone 15, 'sony fe 50mm lens' a lens for Sony's
    E-mount. Format words ('levy', 'disc', 'digital code') become soft wishes in need.prefer. A product need
    only; the device itself ('ps5', 'ps5 console', 'iphone 15 pro') is left as it is."""
    if need.kind != "product" or need.for_platform:
        return need
    try:
        from agora import platforms
        sp = platforms.split(need.thing or "")
    except Exception:
        sp = None
    if sp is None:
        return need
    need.thing = sp.item
    need.for_platform = sp.platform
    need.item_kind = sp.item_kind
    need.prefer = list(dict.fromkeys([*need.prefer, *sp.prefer]))
    if "refurbished" in need.conditions and len(need.conditions) > 1:
        need.conditions = [c for c in need.conditions if c != "refurbished"]   # nobody refurbishes a disc or a case
    return need


def search_words(need: Need) -> str:
    """The words a search engine or a marketplace gets: the item AND its platform ('gta 6 ps5', 'iphone 15
    case'); need.thing alone for any other need."""
    if not getattr(need, "for_platform", None):
        return need.thing or ""
    if need.item_kind == "game":
        return f"{need.for_platform} games" if need.thing in ("games", "game") else f"{need.thing} {need.for_platform}"
    return f"{need.for_platform} {need.thing}"


def _drop_unwanted_conditions(need: Need) -> None:
    """'iphone 13 no refurbished' / 'ohne gebraucht': a lane named in must_not is not searched (when another
    lane is left)."""
    for phrase in need.must_not:
        for c in detect_conditions(phrase)[0]:
            if c in need.conditions and len(need.conditions) > 1 and c != "service":
                need.conditions = [x for x in need.conditions if x != c]


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


def own_domains(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Where-to-look sites of a node. A service leaf two or more levels down does not inherit its ROOT's sites
    when the node or a nearer parent has its own (eval r1: 'Wedding photographer' and 'School catering' got
    lippu.fi / ticketmaster / eventim from 'Events, Tickets & Leisure')."""
    doms = [w for w in node.get("where") or [] if w.get("lane") != "comparison"]
    path = list(node.get("path_ids") or [])
    if node.get("kind") not in ("service", "digital"):
        return doms
    if len(path) >= 3 and any(w.get("from") not in (None, path[0]) for w in doms):
        # the node or a nearer parent has its own sites: the root's are too broad, even when the nearer ones
        # turn out not to fit the trade (School catering: checkatrade.com is trades -> no ticket sellers back)
        doms = [w for w in doms if w.get("from") not in (None, path[0])]
    return _fitting_inherited(node, doms)


def _fitting_inherited(node: dict[str, Any], doms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sites a service node inherits from a parent must list its kind of work (QUALITY_REPORT: 'Gunsmith' under
    'Care, Family & Everyday Help' inherited care.com, yoopies and rover). The node's own sites always stay; an
    inherited site whose work is known (agora.discover.DOMAIN_FAMILIES / the source registry) stays only when that
    work is the node's."""
    try:
        from agora.discover import family_fits, family_of_words
    except Exception:
        return doms
    words = " ".join([str(node.get("label") or ""), " ".join(str(v) for v in (node.get("labels") or {}).values()),
                      " ".join(str(p) for p in node.get("path_ids") or [])[-60:]])
    fam = family_of_words(str(node.get("label") or ""), words)
    out = []
    for w in doms:
        if w.get("from") in (None, node.get("id")):
            out.append(w)
            continue
        fits = family_fits(str(w.get("domain") or ""), fam)
        if fits is False:
            continue
        out.append(w)
    return out


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
    domains = own_domains(node)
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
        keep_audience(need)
        return need
    need.kind = "product"
    lanes = [c for c in (cat.get("lanes") or []) if c in ("new", "used", "refurbished", "rental")]
    asked = [c for c in need.conditions if c != "service"]
    if not asked or asked == ["new", "refurbished", "used"] or asked == ["service"]:
        need.conditions = lanes or ["new", "refurbished", "used"]   # type: ignore[assignment]
    keep_audience(need)
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
    if need.for_platform and need.kind == "product":
        cat = _platform_node(tax, need)       # 'gta 6 ps5': PS5 Games, never Video Game Consoles
        if cat is None:
            return None
        need.category = cat
        return _cat_event(cat)
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
    if need.kind == "product" and vehicle_need(need.thing) and (weak(c) or c.get("kind") != "vehicle"):
        # 'volvo v70', 'bright red car': the tree files 'car' under toys and knows no model names; the rules
        # know a vehicle (make + model, or a vehicle noun) -> Vehicles > Cars, so the car lanes switch on
        cat = category_info(CARS_NODE, source="rules", confidence=0.9)
        if cat is not None:
            need.category = cat
            return _cat_event(cat)
    if weak(c):
        return None
    cat = category_info(c["id"], source="classified", confidence=c.get("confidence") or 0)
    if cat is None:
        return None
    node_kind = TREE_KINDS.get(cat["kind"], "product")
    if need.kind in ("service", "digital") and node_kind == "digital" and not SOFTWARE_WORDS.search(need.raw) \
            and (need.kind == "service" or SERVICE_HINTS.search(need.raw)):
        # the words named a provider's work ('unlimited graphic design subscription'): its service node, not the
        # software one ('Graphic Design & Illustration Software' kept an App Store app and a marketing agency)
        cat = _service_node(tax, need)
        if cat is None:
            return None
        need.category = cat
        return _cat_event(cat)
    if need.kind in ("service", "digital"):
        if node_kind == "product":
            return None                 # the rules' words beat a weak product guess
        need.category = cat
        if not [m for m in need.must_have if m not in AUDIENCE_WORDS] and cat.get("service") \
                and cat["service"] not in need.thing:
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


_DEVICE_NOUN = {"phone": "phone", "tablet": "tablet", "laptop": "laptop", "mount": "camera"}


def _platform_node(tax: Any, need: Need) -> dict[str, Any] | None:
    """The tree node of an ITEM + PLATFORM need: '<platform> games' (PS5 Games), else Video games; an accessory
    by its device's kind ('phone cases', 'laptop chargers', 'camera lenses')."""
    from agora import platforms
    p = platforms.find(need.for_platform or "")
    if need.item_kind == "game":
        queries = [f"{p[0].label} games" if p else "", "video games"]
    else:
        noun = _DEVICE_NOUN.get(p[0].kind if p else "", "")
        word = platforms.kind_word(need.item_kind or "")
        plural = word + ("es" if word.endswith(("s", "sh", "ch")) else "s")
        queries = [f"{noun} {plural}".strip(), plural]
    for q in [x for x in queries if x]:
        try:
            hits = tax.search(q, limit=3, kind="product")
        except Exception:
            hits = []
        for h in hits:
            label = str(h.get("label") or "").lower()
            if (h.get("score") or 0) < 1.0 or re.search(r"console|controller|konsol", label):
                continue
            if need.item_kind == "game" and "game" not in label:
                continue
            cat = category_info(h["id"], source="classified", confidence=min(1.0, round(h["score"] / 1.5, 3)))
            if cat is not None:
                return cat
    return None


CARS_NODE = "sp:vp-2-2-1"         # Vehicles > Motor Vehicles > Cars, Trucks & Vans
SERVICE_NODE_MIN_SCORE = 1.2


def _service_node(tax: Any, need: Need) -> dict[str, Any] | None:
    """The best service node for a service need's core words (subscription / plan words dropped)."""
    core = re.sub(r"\s+", " ", PERIOD_WORDS.sub(" ", DIGITAL_WORDS.sub(" ", need.thing or need.raw))).strip()
    try:
        hits = tax.search(core or need.thing, limit=1, kind="service")
    except Exception:
        hits = []
    if not hits or (hits[0].get("score") or 0) < SERVICE_NODE_MIN_SCORE:
        return None
    return category_info(hits[0]["id"], source="classified", confidence=min(1.0, hits[0]["score"] / 1.6))


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
    # a chatty need's core item came from the rules (agora.prefs): the model's longer item would make every wish a
    # word each listing must carry again
    if isinstance(thing, str) and 1 < len(thing) < 120 and not rules.for_platform and not rules.prefs:
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
        if isinstance(m, str) and m.lower() not in rules.must_have and m.lower() not in rules.must_not:
            rules.must_have.append(m.lower())
    if rules.must_not:      # the LLM's thing may still say 'ps5 no gta bundle'
        cut = clean_thing(_cut(rules.thing, detect_must_not(rules.thing)[1]))
        rules.thing = cut or rules.thing
    return rules


def parse_need(text: str) -> Need:
    """Free text -> Need. Rules always; Gemini fills gaps when GEMINI_API_KEY is set."""
    need = parse_need_rules(text)
    llm = _gemini(text)
    return _merge(need, llm) if llm else need
