"""PREFS: a long, chatty request -> the core item + soft preferences.

Owner, 15 Nov: "i want to buy some hawaianas, size 44 1/3 purple color" and "i want to find a roomba that covers
55 square meters, has vacuum plus mop plus automated clean up plus automated refill" both ended with 0 offers from
32 pages: the whole sentence was the item, so the marketplaces were searched for it and every listing missed a word.

Here the sentence is split into the CORE ITEM ('havaianas', 'roomba': what is searched and what relevance checks)
and PREFERENCES (size 44 1/3, purple, 55 m², mop, self-empty, auto-refill). A preference never removes a listing;
it ranks the listings that state it higher and shows the match ('matches: purple, 44').

    split("havaianas size 44 1/3 purple color") -> ("havaianas", [size 44 1/3, colour purple])
    mark(need, offer) -> ['purple', '44']   (also offer.raw['matches'], offer.raw['pref_score'])

Offline, rules only. Each preference is a plain dict (JSON in the need event): {kind, value, label, words?}.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- sizes (shoes, clothes)
_SIZE_LABEL = r"(?:size|sizes|koko|kokoa|größe|grösse|groesse|gr\.?|str\.?|storlek|størrelse|maat|taille|talla|taglia|rozmiar|eu)"
_FRACTION = r"(?:\s*[⅓⅔½]|\s+[12]\s*/\s*[23])"
_SHOE = rf"(?:[1-5]\d(?:[.,]5)?{_FRACTION}?(?:\s*/\s*[1-5]\d(?:{_FRACTION})?)?)"
_CLOTH = r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-5]xl)"
SIZE_ASK = re.compile(rf"(?<![\w-]){_SIZE_LABEL}\s*:?\s*(?P<v>{_SHOE}|{_CLOTH})(?![\w/])", re.I)
# a fraction is a shoe size even without the word 'size' ('havaianas 44 1/3')
SIZE_BARE = re.compile(rf"(?<![\w/.,-])(?P<v>[3-5]\d(?:{_FRACTION}))(?![\w/])", re.I)
_FRAC_VAL = {"⅓": 1 / 3, "⅔": 2 / 3, "½": 0.5}

# ---------------------------------------------------------------- colours
COLOUR_ASK: dict[str, tuple[str, ...]] = {
    "purple": ("purple", "violet", "lilac", "lavender", "violetti", "liila", "lila", "lilla", "paars", "violett",
               "fioletowy", "viola", "morado"),
    "pink": ("pink", "rosa", "pinkki", "vaaleanpunainen", "roze", "lyserød"),
    "red": ("red", "punainen", "rot", "röd", "rood", "rød", "rouge", "rosso", "rojo"),
    "blue": ("blue", "sininen", "blau", "blå", "blauw", "bleu", "navy"),
    "black": ("black", "musta", "schwarz", "svart", "zwart", "sort", "noir", "nero", "negro"),
    "white": ("white", "valkoinen", "weiß", "weiss", "vit", "wit", "hvid", "hvit", "blanc", "bianco", "blanco"),
    "grey": ("grey", "gray", "harmaa", "grau", "grå", "grijs", "gris", "grigio"),
    "green": ("green", "vihreä", "grün", "grön", "groen", "grøn", "vert", "verde"),
    "yellow": ("yellow", "keltainen", "gelb", "gul", "geel", "jaune", "giallo", "amarillo"),
    "orange": ("orange", "oranssi", "oranje", "arancione", "naranja"),
    "brown": ("brown", "ruskea", "braun", "brun", "bruin", "marron"),
    "beige": ("beige",),
    "gold": ("gold", "kulta", "golden"),
    "silver": ("silver", "hopea", "silber", "zilver", "sølv"),
}
_COLOUR_OF: dict[str, str] = {w: c for c, ws in COLOUR_ASK.items() for w in ws}
_COLOUR_WORD = r"(?:" + "|".join(re.escape(w) for w in sorted(_COLOUR_OF, key=len, reverse=True)) + r")"
_COLOUR_RX = re.compile(rf"(?<![\w-])({_COLOUR_WORD})(?![\w-])", re.I)
# 'purple color' / 'colour: purple' / 'in purple' / 'väri violetti': an asked colour for sure
COLOUR_ASK_RX = re.compile(
    rf"(?<![\w-])(?:(?P<a>{_COLOUR_WORD})\s+(?:colou?r(?:ed)?|väri(?:nen)?|farbe|färg|kleur)\b|"
    rf"(?:colou?r|väri|farbe|färg|kleur)\s*:?\s*(?P<b>{_COLOUR_WORD})(?![\w-])|"
    rf"\bin\s+(?P<c>{_COLOUR_WORD})(?![\w-]))", re.I)
# local words for a colour in a marketplace query
COLOUR_LOCAL: dict[str, dict[str, str]] = {
    "purple": {"fi": "violetti", "sv": "lila", "de": "lila", "nl": "paars", "da": "lilla", "nb": "lilla"},
    "pink": {"fi": "pinkki", "sv": "rosa", "de": "rosa", "nl": "roze", "da": "lyserød", "nb": "rosa"},
}

# ---------------------------------------------------------------- area a machine covers (robot vacuums, routers)
AREA_ASK = re.compile(
    r"(?:\b(?:that\s+|which\s+)?(?:covers?|covering|coverage(?:\s+of)?|for|up\s+to|area(?:\s+of)?|homes?\s+of|"
    r"apartments?\s+of|flats?\s+of|houses?\s+of)\s+(?:an?\s+|about\s+|around\s+|approx\.?\s+)?)"
    r"(?P<v>\d{2,4})\s*(?:square\s+met(?:er|re)s?|sq\.?\s*m(?:et(?:er|re)s?)?|sqm|m2|m²|neliö\w*|qm|kvm)\b", re.I)
_AREA_OFFER = re.compile(r"(?<![\d.,])(\d{2,4})\s*(?:m2|m²|sqm|sq\.?\s*m|neliö\w*|qm|kvm)\b", re.I)

# ---------------------------------------------------------------- features: (asked words, words in a listing)
_SELF_EMPTY = (r"self[- ]?empt\w*|auto(?:matic|mated)?[- ]?empt\w*|automat(?:ed|ic)\s+(?:clean[- ]?up|emptying|"
               r"dirt\s+disposal)|auto[- ]?clean[- ]?up|clean\s*base|emptying\s+(?:station|dock|base)|"
               r"itsetyhjent\w*|tyhjennysasem\w*|tyhjennysasema|absaugstation\w*|selbstentleer\w*|"
               r"entleerungsstation|självtömm\w*|tömningsstation|zelfleg\w*|leegstation|selvtømm\w*")
_REFILL = (r"auto(?:matic|mated)?[- ]?(?:re)?fill\w*|self[- ]?(?:re)?fill\w*|(?:water\s+)?refill(?:ing)?\s+(?:dock|"
           r"station|base)|automaattinen\s+(?:veden\s*)?täyttö|automatische\s+(?:wasser)?(?:befüllung|nachfüllung)|"
           r"automatisk\s+(?:vatten)?påfyllning|autowash|auto[- ]?wash")
_MOP = r"mop\w*|moppaa?\w*|moppi\w*|wisch\w*|nass\s*reinig\w*|mopp\w*|dweil\w*|wet\s+clean\w*|vacuum\s+and\s+mop"
FEATURES: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "mop": (re.compile(rf"\b(?:{_MOP})", re.I),
            re.compile(rf"\b(?:{_MOP}|combo|2[- ]?in[- ]?1|imuri\s*(?:ja|&|\+)\s*moppi)", re.I)),
    "self-empty": (re.compile(rf"\b(?:{_SELF_EMPTY})", re.I),
                   # iRobot's '+' models (i7+, j7+, s9+, Combo j9+) come with the Clean Base
                   re.compile(rf"\b(?:{_SELF_EMPTY})|\b[ijs]\d{{1,2}}\s?\+|\bcombo\s+(?:j\d+\s?\+|10\s+max)", re.I)),
    "auto-refill": (re.compile(rf"\b(?:{_REFILL})", re.I),
                    re.compile(rf"\b(?:{_REFILL})|\bcombo\s+(?:j9\s?\+|10\s+max)", re.I)),
    "vacuum": (re.compile(r"\b(?:vacuum\w*|vacuuming|imuri\w*|imuroi\w*|sauger|staubsaug\w*|dammsug\w*|stofzuig\w*)", re.I),
               re.compile(r"\b(?:vacuum\w*|imuri\w*|sauger|saugrobot\w*|staubsaug\w*|dammsug\w*|stofzuig\w*|roomba|"
                          r"robot\w*)", re.I)),
}
# a feature in a marketplace's language (one short word each: the query stays short)
FEATURE_LOCAL: dict[str, dict[str, str]] = {
    "mop": {"en": "mop", "fi": "moppi", "sv": "mopp", "de": "wischfunktion", "nl": "dweil", "da": "moppe", "nb": "mopp"},
    "self-empty": {"en": "self-emptying", "fi": "itsetyhjentävä", "sv": "självtömmande", "de": "absaugstation",
                   "nl": "zelflegend", "da": "selvtømmende", "nb": "selvtømmende"},
    "auto-refill": {"en": "auto-refill", "fi": "automaattinen täyttö"},
}
FEATURE_LABEL = {"mop": "mop", "self-empty": "self-empty", "auto-refill": "auto-refill", "vacuum": "vacuum"}

# ---------------------------------------------------------------- the clause that starts the wishes
# 'roomba THAT COVERS 55 m²...', 'laptop which has 16 gb', 'sandals, size 44': what follows is about the item
CLAUSE = re.compile(r"(?:,\s*|\s+)(?:that|which|who)\s+(?:has|have|covers?|is|are|comes?\s+with|can|does|supports?|"
                    r"includes?|got)\b|\s*,\s*(?:size|colou?r|has|have|having|with|in)\b", re.I)
CONNECTORS = re.compile(r"\b(?:that|which|who|has|have|having|with|plus|and|also|both|covers?|covering|colou?r|size|"
                        r"in|of|a|an|the|some|is|are|can|does|it|its|ja|und|och|en|og|got|comes?|includes?)\b|[+&,;]",
                        re.I)
_NEVER_CORE = re.compile(r"^(?:that|which|who|has|have|with|plus|and|size|colou?r)$", re.I)


def _pref(kind: str, value: Any, label: str, **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "value": value, "label": label, **kw}


def size_value(text: str) -> float | None:
    """'44 1/3' -> 44.333, '44,5' -> 44.5, '43/44' -> 43.5 (a two-size range: its middle), 'm' -> None."""
    t = (text or "").strip().lower()
    m = re.match(r"(\d{2})(?:[.,](5))?\s*(?:([⅓⅔½])|([12])\s*/\s*([23]))?\s*(?:/\s*(\d{2}))?", t)
    if not m:
        return None
    v = float(m.group(1)) + (0.5 if m.group(2) else 0.0)
    if m.group(3):
        v += _FRAC_VAL[m.group(3)]
    elif m.group(4):
        v += int(m.group(4)) / int(m.group(5))
    if m.group(6):
        v = (v + float(m.group(6))) / 2
    return round(v, 3)


def extract(text: str, *, chatty: bool = False, features_from: int | None = 0
            ) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    """All preferences the words state, with their spans (to cut from the item). Bare colour words count only in
    a chatty request (a 'blue yeti' is a microphone; 'purple color' or 'in purple' is always a colour). Features
    ('mop', 'self-empty') only from `features_from` on (None = none): in the item itself a 'steam mop' is a mop."""
    out: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return not any(a < y and x < b for x, y in taken)

    def add(p: dict[str, Any], span: tuple[int, int]) -> None:
        taken.append(span)
        spans.append(span)
        if not any(q["kind"] == p["kind"] and q["value"] == p["value"] for q in out):
            out.append(p)

    for rx in (SIZE_ASK, SIZE_BARE):
        for m in rx.finditer(text):
            if not free(*m.span()):
                continue
            v = re.sub(r"\s+", " ", m.group("v").strip())
            if re.fullmatch(_CLOTH, v, re.I):
                if rx is SIZE_BARE:
                    continue
                add(_pref("size", v.upper(), v.upper()), m.span())
                continue
            num = size_value(v)
            if num is None or not 15 <= num <= 52:
                continue
            add(_pref("size", v, v, num=num), m.span())
    for m in AREA_ASK.finditer(text):
        if free(*m.span()):
            n = int(m.group("v"))
            add(_pref("area", n, f"{n} m²"), m.span())
    for m in COLOUR_ASK_RX.finditer(text):
        w = (m.group("a") or m.group("b") or m.group("c") or "").lower()
        if w in _COLOUR_OF and free(*m.span()):
            c = _COLOUR_OF[w]
            add(_pref("colour", c, c), m.span())
    if chatty:
        for m in _COLOUR_RX.finditer(text):
            if free(*m.span()):
                c = _COLOUR_OF[m.group(1).lower()]
                add(_pref("colour", c, c), m.span())
    for key, (ask, _) in FEATURES.items():
        if features_from is None:
            break
        for m in ask.finditer(text, features_from):
            if free(*m.span()):
                add(_pref("feature", key, FEATURE_LABEL[key]), m.span())
    return out, spans


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, min(b, len(chars))):
            chars[i] = " "
    return "".join(chars)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W_][\w'/-]*", text) if not re.fullmatch(r"\d+", w)]


def split(text: str, *, chatty: bool = False) -> tuple[str, list[dict[str, Any]], list[tuple[int, int]]]:
    """'havaianas size 44 1/3 purple color' -> ('havaianas', [size, colour], spans). The core item is the text
    before the first wish (or the wish clause 'that covers ...'); words after it that name no known wish are
    kept as soft 'words' wishes (they rank, never filter). Returns the text unchanged with no wishes found."""
    prefs, spans = extract(text, chatty=chatty, features_from=None)
    cm = CLAUSE.search(text)
    starts = [a for a, _ in spans] + ([cm.start()] if cm else [])
    if not starts:
        return text, [], []
    first = min(starts)
    # features ('mop', 'self-empty') only in the wishes: in the item itself a 'steam mop' is a mop
    prefs, spans = extract(text, chatty=chatty, features_from=first)
    head = text[:first]
    if not _words(CONNECTORS.sub(" ", head)):
        # the wish comes first ('purple havaianas size 44'): the core is what is left once the wishes are cut
        core = CONNECTORS.sub(" ", _cut(text, spans))
        core = re.sub(r"\s+", " ", core).strip(" ,;-")
        return (core or text), prefs, spans
    tail = _cut(text[first:], [(a - first, b - first) for a, b in spans if a >= first])
    extra = [w.lower() for w in _words(CONNECTORS.sub(" ", tail)) if len(w) >= 3 and not _NEVER_CORE.match(w)]
    # the leftover words of the wish clause (adjectives, 'light', 'quiet') are soft wishes too
    for w in dict.fromkeys(extra):
        if len(prefs) >= 8:
            break
        prefs.append(_pref("word", w, w))
    core = re.sub(r"\s+", " ", _cut(head, [(a, b) for a, b in spans if b <= first])).strip(" ,;-")
    core = re.sub(rf"(?:\s+(?:{CONNECTORS.pattern}))+$", "", core, flags=re.I).strip(" ,;-")
    # a feature the item is by itself is no wish ('roomba ... has vacuum': every Roomba vacuums)
    prefs = [p for p in prefs if not (p["kind"] == "feature" and FEATURES[p["value"]][1].search(core))]
    return (core or text), prefs, [(first, len(text))]


# ---------------------------------------------------------------- does a listing state the wish?

def _listing_text(offer: Any) -> str:
    raw = offer.raw if isinstance(getattr(offer, "raw", None), dict) else {}
    bits = [offer.title or ""]
    for k in ("row_text", "search_text", "description", "page_description", "subtitle", "colour"):
        v = raw.get(k)
        if v:
            bits.append(str(v)[:800])
    return " ".join(bits)


_OFFER_SIZE = re.compile(rf"(?<![\d.,€$£])({_SHOE})(?!\s*(?:€|eur|kr|zł|pln|sek|nok|dkk|%|cm|mm|kg|g\b|w\b|v\b|m2|m²))",
                         re.I)


def size_hit(asked: dict[str, Any], text: str) -> bool:
    want = asked.get("num")
    if want is None:      # a clothing size letter
        return bool(re.search(rf"(?<![\w-]){re.escape(str(asked['value']))}(?![\w-])", text, re.I))
    for m in _OFFER_SIZE.finditer(text):
        tok = m.group(1)
        lo = hi = None
        r = re.match(r"\s*(\d{2})(?:[.,]5)?[^/]*?(?:/\s*(\d{2}))", tok)
        if r and abs(int(r.group(2)) - int(r.group(1))) == 1:
            lo, hi = float(r.group(1)), float(r.group(2))         # '43/44': both sizes
        v = size_value(tok)
        if v is None or not 15 <= v <= 52:
            continue
        if lo is not None and lo - 0.5 <= want <= hi + 0.5:
            return True               # '43/44' (Havaianas, Crocs) fits a 44 1/3 foot
        if abs(v - want) <= 0.5:
            return True
    return False


def hits(prefs: list[dict[str, Any]], offer: Any) -> list[str]:
    """The labels of the wishes this listing states ('purple', '44 1/3', 'mop')."""
    text = _listing_text(offer)
    low = text.lower()
    out: list[str] = []
    for p in prefs or []:
        k = p.get("kind")
        ok = False
        if k == "size":
            ok = size_hit(p, text)
        elif k == "colour":
            ok = any(_COLOUR_OF.get(m.group(1).lower()) == p["value"] for m in _COLOUR_RX.finditer(text))
        elif k == "feature" and p.get("value") in FEATURES:
            ok = bool(FEATURES[p["value"]][1].search(text))
        elif k == "area":
            ok = any(int(m.group(1)) >= int(p["value"]) for m in _AREA_OFFER.finditer(text))
        elif k == "word":
            w = str(p["value"]).lower()
            ok = bool(re.search(rf"(?<![\w-]){re.escape(w[:max(4, len(w) - 2)])}", low)) if len(w) >= 3 else False
        if ok and p.get("label") not in out:
            out.append(str(p.get("label")))
    return out


WEIGHT = {"size": 1.5, "colour": 1.0, "feature": 1.0, "area": 0.5, "word": 0.5}


def weight(p: dict[str, Any]) -> float:
    """A wrong size does not fit at all; a colour or a feature is a wish; the area and free words are hints."""
    return WEIGHT.get(str(p.get("kind")), 1.0)


def mark(need: Any, offer: Any) -> list[str]:
    """offer.raw['matches'] (labels it states) and raw['pref_score'] (0..1 of the wishes, by weight), for a need
    with preferences; [] and no mark otherwise."""
    prefs = getattr(need, "prefs", None) or []
    if not prefs:
        return []
    got = hits(prefs, offer)
    total = sum(weight(p) for p in prefs) or 1.0
    score = sum(weight(p) for p in prefs if p.get("label") in got) / total
    if isinstance(getattr(offer, "raw", None), dict):
        offer.raw["matches"] = got
        offer.raw["pref_score"] = round(score, 3)
    return got


def query_words(need: Any, iso: str | None = None, n: int = 2) -> str:
    """The 1-2 strongest wishes as short marketplace words ('44', 'violetti', 'combo', 'itsetyhjentävä'), for
    one extra search beside the core item's own. '' when the need has none."""
    prefs = getattr(need, "prefs", None) or []
    lang = (iso or "en").lower()
    words: list[str] = []
    feats = {p["value"] for p in prefs if p.get("kind") == "feature"}
    if "mop" in feats and re.search(r"\broomba\b", f"{getattr(need, 'thing', '')}", re.I):
        words.append("combo")              # iRobot sells the vacuum + mop as 'Roomba Combo'
        feats.discard("mop")
        feats.discard("vacuum")
    for p in prefs:
        if len(words) >= n:
            break
        k = p.get("kind")
        if k == "size" and p.get("num") is not None:
            words.append(str(int(p["num"])))
        elif k == "size":
            words.append(str(p["value"]))
        elif k == "colour":
            words.append(COLOUR_LOCAL.get(p["value"], {}).get(lang) or p["value"])
        elif k == "feature" and p["value"] in feats and p["value"] != "vacuum":
            loc = FEATURE_LOCAL.get(p["value"], {})
            words.append(loc.get(lang) or loc.get("en") or p["value"])
    return " ".join(dict.fromkeys(words[:n]))


def best(offers: list[Any]) -> list[Any]:
    """The offers that state the most wishes (pref_score > 0), else []."""
    scored = [o for o in offers if (o.raw or {}).get("pref_score")]
    if not scored:
        return []
    top = max(o.raw["pref_score"] for o in scored)
    return [o for o in scored if o.raw["pref_score"] >= top - 1e-9]
