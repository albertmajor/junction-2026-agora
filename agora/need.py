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
    elif conds:
        need.conditions = conds
    return need


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
    if llm.get("kind") in ("product", "service") and rules.kind == "product":
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
