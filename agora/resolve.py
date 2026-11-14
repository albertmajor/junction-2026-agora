"""RESOLVE: offers -> Things.

Shops all name the same camera differently: "SONY A7 III BODY", "Sony a7 III Mirrorless Camera",
"Sony Alpha ILCE-7M3", "a7iii", "A7 Mark 3". We turn every title into a *signature*:
  brand + model tokens (with generation folded in) + variant words (pro/max/r/s...) + kit flag
and ignore colours, "body only", marketing fluff. Same signature -> same Thing.

Also: accessories ("battery for Sony a7 III") are recognised and rejected, bundles flagged,
and `relevance(need, offer)` scores 0..1 how well an offer answers the need.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agora.models import Need, Offer, Thing

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
ROMAN_OUT = {v: k.upper() for k, v in ROMAN.items()}

BRANDS = {
    "sony", "canon", "nikon", "fujifilm", "fuji", "panasonic", "olympus", "om system", "leica", "sigma",
    "tamron", "gopro", "dji", "apple", "samsung", "google", "xiaomi", "oneplus", "huawei", "nokia",
    "motorola", "oppo", "lenovo", "dell", "hp", "asus", "acer", "msi", "microsoft", "lg", "philips",
    "bosch", "siemens", "miele", "electrolux", "aeg", "dyson", "roborock", "irobot", "nintendo",
    "playstation", "xbox", "valve", "steam", "bose", "sennheiser", "jbl", "garmin", "polar", "suunto",
    "fitbit", "kindle", "amazon", "logitech", "razer", "ikea", "delonghi", "de'longhi", "nespresso",
    "jura", "sage", "breville", "kitchenaid", "weber", "makita", "dewalt", "festool", "trek",
    "specialized", "canyon", "cube", "brompton", "tesla", "volvo", "toyota", "bmw", "audi", "vw",
}
BRAND_ALIASES = {"fuji": "fujifilm", "alpha": "sony", "ilce": "sony", "eos": "canon", "iphone": "apple",
                 "ipad": "apple", "macbook": "apple", "airpods": "apple", "galaxy": "samsung", "pixel": "google",
                 "playstation": "sony", "ps5": "sony", "switch": "nintendo"}

COLOURS = {
    "black", "white", "silver", "grey", "gray", "blue", "red", "green", "gold", "rose", "pink", "purple",
    "midnight", "starlight", "graphite", "titanium", "natural", "space", "sierra", "alpine", "yellow",
    "orange", "beige", "bronze", "charcoal", "musta", "valkoinen", "schwarz", "weiß", "weiss", "svart",
}
FLUFF = {
    "body", "only", "camera", "digital", "mirrorless", "full", "frame", "fullframe", "interchangeable",
    "lens", "new", "brand", "used", "refurbished", "renewed", "excellent", "condition", "mint", "boxed",
    "free", "shipping", "sale", "deal", "official", "genuine", "original", "edition", "version", "the",
    "and", "with", "for", "a", "an", "of", "in", "by", "w", "unlocked", "smartphone", "phone", "mobile",
    "international", "eu", "uk", "us", "model", "warranty", "kamera", "runko",
    "ilce", "alpha", "mp", "4k", "hdr", "wifi", "wi", "fi", "bluetooth", "nfc", "megapixel", "sensor",
    "mark", "mk", "gen", "generation", "vlog", "vlogging", "pre", "owned", "preowned", "grade", "condition",
}
FAMILIES = {"eos", "iphone", "ipad", "pixel", "galaxy", "playstation", "ps", "xbox", "switch", "kindle", "airpods", "watch", "series", "macbook"}
FAMILY_DISPLAY = {"iphone": "iPhone", "ipad": "iPad", "pixel": "Pixel", "playstation": "PlayStation", "ps": "PS",
                  "xbox": "Xbox", "switch": "Switch", "kindle": "Kindle", "airpods": "AirPods", "watch": "Watch",
                  "series": "Series", "galaxy": "Galaxy", "macbook": "MacBook", "eos": "EOS"}
VARIANT_WORDS = {"pro", "max", "plus", "mini", "ultra", "air", "lite", "se", "slim", "oled", "neo"}

ACCESSORY_WORDS = {
    "case", "cover", "sleeve", "bag", "pouch", "skin", "battery", "batteries", "charger", "charging",
    "cable", "adapter", "adaptor", "strap", "screen protector", "protector", "tempered glass", "cage",
    "grip", "lens cap", "cap", "hood", "mount", "tripod", "gimbal", "remote", "dock", "stand", "holder",
    "replacement", "spare", "parts", "stylus", "keyboard cover", "film", "decal", "sticker", "manual",
    "box only", "empty box", "dummy", "eyecup", "hotshoe", "hot shoe", "filter", "memory card", "sd card",
    "kotelo", "suojakuori", "akku", "laturi", "hülle", "ladegerät", "akku-", "np-fz100", "np-fw50", "lp-e6",
    # spare parts and wearables of the item (live: €10 AirPods ear tips won a hunt as "new AirPods")
    "ear tips", "eartips", "ear tip", "tips", "earhooks", "ear hooks", "digitizer", "lcd", "motherboard",
    "logic board", "flex cable", "joy-con", "joycon", "joy con", "thumbstick", "battery door", "brush head",
    "brush bar", "brushroll", "filter head", "wall mount", "charging case only", "left earbud", "right earbud",
    "korvatyynyt", "varaosa", "näyttö", "latauskotelo", "ladecase", "ladeetui",
    # protective covers in Nordic/Dutch/Polish/German titles (live: 'Nike airpods pro 2 suoja' €25 won airpods)
    "suoja", "suojus", "suojakotelo", "kuori", "kuoret", "suojakuoret", "hoesje", "hoes", "fodral", "skal",
    "etui", "deksel", "futerał", "schutzhülle", "case only", "cover only", "silicone case", "silikonikuori",
    # bike parts sold on their own (live: a €25 'Kaupunkipyörä ohjaustanko' handlebar won 'city bike')
    "ohjaustanko", "sisärengas", "cykelslang", "slang", "fahrradschlauch", "schlauch", "montageständer",
    "kaasukahva", "binnenband", "dętka",
    # shelf inserts and add-ons sold alone (live: 'IKEA DRÖNA säilytyslaatikot (sopii Kallax-hyllyyn)' at €8
    # won 'ikea kallax shelf')
    "insert", "inserts", "upotettava", "lokerikko", "säilytyslaatikot", "säilytyslaatikko", "hyllynjakaja",
    "jakaja", "somiste", "pulloteline", "viinipulloteline", "jalat", "einsatz", "einsätze", "drahtkorb",
    "förvaringslåda", "förvaringslådor", "laatikosto", "lasihylly", "lasihyllyt", "kello-ovi", "liitoshela",
    "säilytyskori", "ritiläkori", "teline", "jalusta", "ovi", "ovet", "latikosto", "lemmikkipeti",
    # cases, covers and ear tips in Lithuanian / Polish / Nordic marketplace titles (live, vinted.fi: 'Airpods pro 2
    # dėkliukas' €1, 'Obudowa AirPods Pro 2' €3, 'Silikonepropper AirPods Pro' €10 were costed as AirPods)
    "dėklas", "deklas", "dėkliukas", "dekliukas", "dėkliukai", "obudowa", "obudowy", "pokrowiec", "okładka",
    "okladka", "nakładki", "końcówki", "koncowki", "gumki", "vaihtopäät", "silikonepropper", "propper",
    "örontoppar", "tulpat", "muistivaahtotulpat", "laddningsfodral", "laddningsetui", "kotelosuoja", "beskytter",
    "oplaadcase", "ladeetui", "dėžutė", "dėžutę", "dezute", "dežute", "pudełko", "pudelko", "opakowanie",
    # game controllers sold alone (coverage audit: 'PlayStation 5 ohjain DualSense' kept as a PS5)
    "ohjain", "ohjaimet", "dualsense", "dualshock", "controller", "handkontroll", "kontroller",
}
BATTERY_WORDS = {"akku", "battery", "batteri", "akku-"}
_BATTERY_STATE = re.compile(r"\b(?:akku|battery|batteri|akkukunto|battery health|akun kunto)\w*\W{0,12}\d{2,3}\s*%|"
                            r"\d{2,3}\s*%\W{0,6}(?:akku|battery|batteri)|"
                            r"\b(?:aito|uusi|alkuperäinen|vaihdettu|new|original|neuer?|neu)\s+(?:akku|battery|batteri)\b")
# compound tails that make a word a cover / charger in Finnish and German titles (whole words are matched below)
_ACC_TAIL = re.compile(r"\b\w{3,}?(kuoret|kuori|suojakuori|suojalasi|panssarilasi|laturi|hülle|ladekabel|"
                       r"ladegerät|ladeschale)\b")
# words that name a part of the item: an accessory when they come *before* the item's name
# ("OLED Display for Nintendo Switch OLED"), not after ("MacBook Air with 15.3" display")
PART_WORDS = ("display", "screen", "panel", "housing", "shell", "back cover", "battery",
              "charging port", "speaker", "fan", "keyboard", "trackpad", "hinge", "joystick", "board", "dock",
              "controller", "cable", "remote", "head", "attachment", "tool", "nozzle", "wand", "bin", "cyclone")
_FOR = r"(?:for|fits|compatible\s+with|works\s+with|designed\s+for|suitable\s+for|für|passend\s+für|pour|sopii|til|för)"
ACCESSORY_PATTERNS = [
    re.compile(rf"\b{_FOR}\s+(?:the\s+)?(?:sony|canon|nikon|apple|iphone|samsung|galaxy|fuji|a\d|ilce|eos|pixel|macbook|ipad"
               r"|nintendo|switch|playstation|ps[45]|xbox|dyson|airpods|garmin|kindle|bose|gopro|dji)\b", re.I),
    re.compile(r"\b(?:replacement|spare)\b", re.I),
    # Finnish 'fits into X': 'Kallaxiin sopiva laatikosto', 'sopii Kallax-hyllyyn'
    re.compile(r"\w+(?:iin|aan|ään|hin|yyn)\s+sopiva\b|\bsopii\s+[\w-]+(?:iin|aan|ään|hin|yyn)\b", re.I),
    re.compile(r"\bhyll\w*(?:yyn|köön|yihin|ykköihin)\b", re.I),     # 'into a shelf' (Finnish illative): an insert
    re.compile(r"\b(?:till|in)\s+(?:ikea\s+)?kallax\b", re.I),
    re.compile(rf"\b{_FOR}\s+(?:the\s+)?(?:ikea\s+)?(?:kallax|billy|pax|hemnes|malm|expedit)\b", re.I),
]
BUNDLE_PATTERNS = [
    re.compile(r"\bbundle\b|\bkit\b|\bcombo\b|\bpaketti\b|\bset\b", re.I),
    re.compile(r"\+\s*\w|\bw/\s*\w|\bwith\s+(?:\d+|extra|two|spare|lens|\w+-\w+\s*mm)", re.I),
    re.compile(r"\b\d{2,3}\s*-\s*\d{2,3}\s*mm\b", re.I),  # kit lens: 28-70mm
]

# whole-code aliases: maker part numbers -> marketing names (folded before tokenising)
CODE_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bilce[- ]?7([rsc]?)m(\d)[a-z]*\b"), r"a7\1 \2"),     # ILCE-7M3 / ILCE7RM4A -> a7 3 / a7r 4
    (re.compile(r"\bilce[- ]?7([rsc]?)\b"), r"a7\1"),                    # ILCE-7 -> a7 (first gen)
    (re.compile(r"\bilce[- ]?(\d{4})[a-z]*\b"), r"a\1"),                 # ILCE-6400 -> a6400
    (re.compile(r"\bdsc[- ]?rx100m(\d)[a-z]*\b"), r"rx100 \1"),
    (re.compile(r"\bzv[- ]?e(\d+)\b"), r"zv-e\1"),
    # 'PlayStation 5' is the 'PS5' (coverage audit: 87 PS5 listings were 'a different model (playstation5 vs ps5)')
    (re.compile(r"\bplay\s?station\s?([1-6])\b"), r"ps\1"),
]


# same thing, other languages: a hit on any synonym counts as a hit on the need word
SYNONYMS: dict[str, set[str]] = {
    "washing": {"pesukone", "waschmaschine", "tvattmaskin", "washer"},
    "machine": {"pesukone", "waschmaschine", "tvattmaskin", "washer", "kone"},
    "dishwasher": {"astianpesukone", "geschirrspuler", "diskmaskin"},
    "fridge": {"jaakaappi", "kuhlschrank", "kylskap", "refrigerator"},
    "vacuum": {"imuri", "staubsauger", "dammsugare", "hoover"},
    "bike": {"bicycle", "polkupyora", "pyora", "fahrrad", "cykel", "fiets", "rower", "velo", "sykkel", "citybike",
             "cityrad", "damenrad", "herrenrad"},
    "city": {"kaupunki", "stads", "citybike", "cityrad", "miejski", "ville", "bysykkel"},
    "shelf": {"hylly", "regal", "hylla", "hylle", "reol", "kast", "etagere"},
    "sofa": {"sohva", "couch", "soffa"},
    "laptop": {"notebook", "kannettava", "lappari"},
    "phone": {"puhelin", "smartphone", "handy"},
    "camera": {"kamera"},
    "tv": {"television", "televisio", "fernseher"},
    "headphones": {"kuulokkeet", "kopfhorer", "headset", "earbuds"},
    "stroller": {"rattaat", "kinderwagen", "pram", "pushchair"},
    "car": {"auto", "bil", "pkw", "voiture", "coche", "henkiloauto", "personbil", "vehicle", "automobile"},
    "auto": {"car", "bil", "pkw", "henkiloauto", "vehicle"},
}


# ---------------------------------------------------------------- whole-word matching
# 'car' must never match 'cargo', 'Carhartt', 'Carlotta' or 'Carrera': a need word matches a title token
# exactly, with a plural / case ending (cars, autot, Autos, hyllyt), or as the head of a compound
# (kaupunkipyörä ends in pyörä, Gebrauchtwagen in wagen); never as the start of another word.
_SHORT_ENDINGS = ("s", "es")
_ENDINGS = ("s", "es", "n", "en", "e", "er", "t", "a", "ä", "ja", "jä", "ar", "or", "na", "ssa", "sta", "lla", "lle",
            "ksi", "ine", "an", "on", "un", "yn", "in", "ta")


def word_hit(w: str, toks: set[str] | list[str]) -> bool:
    """`w` (folded, one word) is one of the title tokens, as a whole word."""
    if not w:
        return False
    if " " in w:                       # a phrase synonym: every word of it
        return all(word_hit(x, toks) for x in w.split())
    for t in toks:
        if t == w:
            return True
        if t.startswith(w):
            if t[len(w):] in (_SHORT_ENDINGS if len(w) < 4 else _ENDINGS):
                return True
        elif len(w) >= 4 and len(t) >= len(w) + 3 and t.endswith(w):
            return True                # compound head: henkilöauto, kirjahylly, damenfahrrad
    return False


ATTRIBUTE_ONLY = {"bright", "dark", "pale", "deep", "metallic", "matte", "glossy", "shiny"}


@dataclass
class Signature:
    brand: str | None
    models: tuple[str, ...]          # e.g. ("a7-3",) or ("15",)
    variants: tuple[str, ...]        # e.g. ("pro", "max")
    kit: bool = False
    words: set[str] = field(default_factory=set)   # remaining content words (for fuzzy overlap)
    family: str | None = None                       # display only ("iphone", "eos", "galaxy")

    @property
    def key(self) -> str:
        parts = [self.brand or "", *self.models, *self.variants]
        if self.kit:
            parts.append("kit")
        return "|".join(parts)


_ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("™", " ").replace("®", " ")
    t = re.sub(r"\b(\d+)[- ]?(core|kern|ytiminen)\b", r" \1core ", t)    # '8-core GPU' is a spec, not a model
    # screen sizes are units, not model numbers: 'OLED 7"' / '15,3""' / '13.6-inch' / '15 Zoll' -> 7in
    t = re.sub(r"(\d+)(?:[.,]\d+)?(?:\s*(?:\"+|''|”|″)|\s*-?\s*(?:inch(?:es)?|zoll|tuumaa?)\b|-?in\b)", r" \1in ", t)
    # warranty / age durations are not models either: 'TAKUU 6kk' (Finnish: 6-month warranty), '12 months'
    t = re.sub(r"\b(\d+)\s*(kk|mo|mos|months?|monate?n?|vuotta|yrs?|years?|jahre?)\b", r" \1mo ", t)
    # ordinal generations: '(2nd generation)' / '2nd gen' / 'second generation' -> a bare number after the name
    # (a 'genN' token: it joins the last model, or the family when there is none: kindle 11th gen -> kindle11)
    t = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b(?:\s*-?\s*gen(?:eration)?\b\.?)?", r" gen\1 ", t)
    t = re.sub(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth)\s*-?\s*gen(?:eration)?\b",
               lambda m: f" gen{_ORDINAL_WORDS[m.group(1)]} ", t)
    t = re.sub(r"\bgen(?:eration)?\.?\s*(\d{1,2})\b(?!\s*(?:gb|tb|mm))", r" gen\1 ", t)   # 'Gen 2' / 'Generation 3'
    t = re.sub(r"\b(\d{1,2})\s*-?\s*gen(?:eration)?\b", r" gen\1 ", t)                 # '2-gen' / '3 generation'
    for pat, rep in CODE_ALIASES:
        t = pat.sub(rep, t)
    # "mark iii" / "mk3" / "mkiii" / "mark 3" / "m3 " after a model -> generation number token
    t = re.sub(r"\b(?:mark|mk)\.?\s*(i{1,3}|iv|vi{0,3}|ix|x|\d{1,2})\b", lambda m: " gen" + str(ROMAN.get(m.group(1), m.group(1))), t)
    t = re.sub(r"\b([a-z]{1,4}\d{1,4}[a-z]{0,2})\s*m(\d)\b", r"\1 gen\2", t)         # "a7 m3" / "a7m3"
    t = re.sub(r"[^\w\s+/-]", " ", t)
    return t


_ROMAN_SUFFIX = re.compile(r"^([a-z]{1,5}\d{1,4}[a-z]{0,2}?)(viii|vii|vi|iv|iii|ii|v|ix)$")
_MODEL_TOKEN = re.compile(r"^(?=.*\d)(?=.*[a-z])[a-z0-9-]{2,12}$")
_UNIT_TOKEN = re.compile(r"^\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?mm$|^f\d|^\d+(?:gb|tb|mb|mp|mm|hz|w|k|p|fps|mah|v|cm|kg|l|in|inch|x|mo|kk|core|cores|gpu|cpu)$|^\d{4}$|^(?:4k|5g|4g|8k|2k)$")


def tokenize(title: str) -> list[str]:
    """Normalised tokens with generations as standalone 'genN' tokens (a7iii -> a7 gen3)."""
    out: list[str] = []
    toks: list[str] = []
    for tok in re.split(r"[\s/]+", _fold(title)):
        # 'OLED-Modell' / 'Pro-Version' are two words; 'WH-1000XM5' / 'X-T5' / 'zv-e10' stay one code
        toks += tok.split("-") if "-" in tok.strip("-") and not re.search(r"\d", tok) else [tok]
    for tok in toks:
        tok = tok.strip("-+")
        if not tok:
            continue
        m = _ROMAN_SUFFIX.match(tok)
        if m and not _UNIT_TOKEN.match(tok):
            out += [m.group(1), "gen" + str(ROMAN[m.group(2)])]
            continue
        if tok in ROMAN and tok not in ("i", "x", "v") and out and _MODEL_TOKEN.match(out[-1]):
            out.append("gen" + str(ROMAN[tok]))
            continue
        if tok in ("v",) and out and _MODEL_TOKEN.match(out[-1]):
            out.append("gen5")
            continue
        out.append(tok)
    return out


_BUNDLE_SPLIT = re.compile(r"\s(?:\+|&|with|w/|incl\w*|bundle|plus\s+\d)\s", re.I)


def signature(title: str, brand: str | None = None) -> Signature:
    """Identity of the main item. Text after '+'/'with' (kit lens, batteries) is not identity."""
    toks = tokenize(_BUNDLE_SPLIT.split(title, maxsplit=1)[0])
    seen_family: str | None = None
    found_brand = (brand or "").lower().strip() or None
    if found_brand:
        found_brand = BRAND_ALIASES.get(found_brand, found_brand)
        if found_brand not in BRANDS:
            found_brand = None      # shops put their own name in `brand` ("Allen's Camera"): trust the title
    models: list[str] = []
    variants: list[str] = []
    words: set[str] = set()
    family: str | None = None   # "iphone", "galaxy", "pixel"... glues to a following bare number
    prev_model = False
    for t in toks:
        if t in FAMILIES:
            family = seen_family = t
            words.add(t)
            if not found_brand and t in BRAND_ALIASES:
                found_brand = BRAND_ALIASES[t]
            continue
        if t in BRANDS and not found_brand:
            found_brand = BRAND_ALIASES.get(t, t)
            continue
        if t in BRAND_ALIASES and not found_brand:
            found_brand = BRAND_ALIASES[t]
        if t.startswith("gen") and t[3:].isdigit():
            if models and "-" not in models[-1]:
                models[-1] = models[-1] + "-" + t[3:]
            elif not models and seen_family:
                models.append(seen_family + t[3:])      # 'AirPods Pro (2nd generation)' == 'AirPods Pro 2'
            prev_model = False
            continue
        if _UNIT_TOKEN.match(t) or t in COLOURS:
            prev_model = False
            continue
        if _MODEL_TOKEN.match(t):
            models.append(t.replace("-", ""))
            prev_model, family = True, None
            continue
        if t.isdigit() and family and len(t) <= 3:
            models.append(family + t)                  # "iphone 15" -> iphone15 (== "iPhone15")
            prev_model, family = True, None
            continue
        if t.isdigit() and len(t) == 1 and prev_model and models and "-" not in models[-1]:
            models[-1] = models[-1] + "-" + t           # "a7 3" -> a7-3
            prev_model = False
            continue
        if t in VARIANT_WORDS and (models or family):
            if t not in variants:
                variants.append(t)
            continue
        if t not in FLUFF and len(t) > 1 and not t.isdigit():
            words.add(t)
            family = None     # 'switch oled edition splatoon 3': only a number right after the name glues
        prev_model = False
    kit = any(p.search(title) for p in BUNDLE_PATTERNS[2:]) or bool(re.search(r"\bkit\b|\bw/\s*\d|\bwith\s+\d{2}-\d{2}", title, re.I))
    return Signature(found_brand, tuple(dict.fromkeys(models)), tuple(variants), kit, words, seen_family)


def _item_tokens(need: Need) -> list[str]:
    """Words that name the asked item itself: brand, family and model ('nintendo', 'switch', 'v15')."""
    ns = signature(need.thing)
    toks = [t for t in tokenize(need.thing) if t in FAMILIES or t in BRANDS or t in BRAND_ALIASES or _MODEL_TOKEN.match(t)]
    if ns.brand:
        toks.append(ns.brand)
    return list(dict.fromkeys(toks))


def _first_item_pos(low: str, need: Need) -> int | None:
    pos = [m.start() for t in _item_tokens(need) if (m := re.search(rf"(?<![\w-]){re.escape(t)}", low))]
    return min(pos) if pos else None


def is_accessory(title: str, need: Need | None = None) -> bool:
    """True when the listing is a thing *for* the item rather than the item."""
    # Finnish compound tails on marketplace titles: "AirPods Pro 2 (USB-C) -latauskotelo" = the charging case
    low = re.sub(r"(?<=\s)-(?=\w)", " ", title.lower())
    asked = (need.thing.lower() + " " + " ".join(need.must_have)).lower() if need else ""
    # substring prefilters first (one C-level 'in' per word): the regex per word ran ~900k times for 2,000 rows
    if any(w in asked and re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", asked)
           for w in (*ACCESSORY_WORDS, *PART_WORDS)):
        return False   # they asked for the accessory itself ("battery for sony a7 iii")
    for m in _ACC_TAIL.finditer(low):
        if m.group(1) not in asked and not re.search(r"(?:\bwith\b|\bmit\b|\bja\b|\binkl\w*|\+)[^|]*$",
                                                      low[:m.start()]):
            return True        # 'iPhone 13 -Puhelimenkuoret', 'Galaxy S21 Schutzhülle': a cover for the phone
    for w in (x for x in ACCESSORY_WORDS if x in low):
        if w in BATTERY_WORDS and _BATTERY_STATE.search(low):
            continue           # 'akku 93 %', 'aito akku', 'Akku 89%': the phone's battery health, not a battery
        if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low) and w not in asked:
            # "camera with battery and charger" is a bundle, not an accessory: the accessory word
            # must come before "for X" or lead the title, or appear without a main-item word
            if re.search(rf"(?:\bwith\b|\bmit\b|\bincl\w*|\binkl\w*|\+|\band\b|\bw/|\bz\b|\bze\b|\bmed\b|\bmet\b"
                         rf"|\bsu\b|\bja\b|\bund\b|\ben\b|\boch\b|\bog\b|\bi\b)[^|]*\b{re.escape(w)}", low):
                continue
            return True
    item_at = _first_item_pos(low, need) if need else None
    if item_at is not None:
        # a part named before the item: "OLED Display for Nintendo Switch OLED", "Battery Dyson V15"
        for w in PART_WORDS:
            m = re.search(rf"(?<![\w-]){re.escape(w)}s?(?![\w-])", low)
            if m and m.start() < item_at:
                return True
        # "<anything> for <the asked item>": the thing is made *for* it
        for m in re.finditer(rf"\b{_FOR}\s+(?:the\s+|your\s+)?", low):
            if low[:m.start()].strip() and m.end() <= item_at <= m.end() + 12:
                return True       # the first mention of the item comes after "for": a thing made for it
        if any(p.search(title) for p in ACCESSORY_PATTERNS):
            # "for iPhone" after the asked item's name ("AirPods Pro 2 for iPhone") is not an accessory
            m = ACCESSORY_PATTERNS[0].search(title)
            if m is None or m.start() < item_at:
                return True
        return False
    return any(p.search(title) for p in ACCESSORY_PATTERNS)


# ---------------------------------------------------------------- listing red flags (title + description)
# Marketplace listings say in plain words what they are: 'vain vasen kuuloke', 'kapot', 'replica', 'ostetaan'.
# Matched on a folded copy of the text (lower case, accents off, ł->l, ø->o, æ->a: one char per char, so a
# match maps back to the seller's own words). Negated or conditional mentions ('ei vikoja', 'keine Mängel',
# 'Vervanging bij verlies of defect') do not count.

_FOLD_1 = {"ł": "l", "ø": "o", "æ": "a", "ß": "s", "đ": "d", "ı": "i", "œ": "o"}


@functools.lru_cache(maxsize=8192)
def _fold1(c: str) -> str:
    if c in _FOLD_1:
        return _FOLD_1[c]
    d = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
    return d[:1] if d else " "


def fold_text(text: str) -> str:
    """Lower case, accents off, one output character per input character (indices map back)."""
    return "".join(_fold1(c) for c in (text or "").lower())


_SIDE_L = (r"left|vasen|vasemp\w*|vasemma\w*|links|linke[rnms]?|linker|lewa|lewy|lewe|lewej|vanster|venstre|kaire|"
           r"gauche|izquierd\w*|sinistr\w*")
_SIDE_R = (r"right|oikea|oikean|oikeanpuole\w*|rechts|rechte[rnms]?|rechter|prawa|prawy|prawe|prawej|hoger|hojre|"
           r"hoyre|desine|droit\w*|derech\w*|destr\w*")
_EAR = (r"earbuds?|airpods?|buds?|ear ?pieces?|earphones?|kuuloke\w*|nappi\w*|nappikuulok\w*|ohrhorer\w*|"
        r"ohrstopsel|kopfhorer\w*|oortje\w*|oordopje\w*|sluchawk\w*|horlur\w*|orepropp\w*|oresnegl\w*|ausin\w*|"
        r"ecouteur\w*|auricular\w*|auricolar\w*")
_CASE = (r"(?:charging |wireless charging |magsafe )?case|cases|kotelo|latauskotelo|ladecase|ladeetui|ladeschale|"
         r"etui|oplaadcase|oplaaddoos|laddningsetui|laddfodral|laddningsfodral|ladeboks|ladeetui|ladeskal|"
         r"dekl\w*|pudelko ladujace|etui ladujace")
_BOX = (r"box|boxen|laatikko|pakkaus|myyntipakkaus|ovp|verpackung|originalverpackung|karton|schachtel|doos|"
        r"verpakking|pudelk[oa]|opakowani[ae]|lada|kartong|aske|eske|dezut\w*")
_ONLY = r"only|vain|pelkka|pelkat|pelkastaan|ainoastaan|nur|alleen|bara|kun|tylko|just|solo|seulement|enkel|losse"
_WITHOUT = r"without|ilman|ohne|zonder|utan|uden|uten|bez|sans|sin|senza"
# words that may sit between 'only' and 'case' ('only the original Apple charging case'), nothing else
_FILL = (r"(?:(?:the|a|an|de|het|een|das|die|der|den|det|la|le|el|il|original\w*|oryginaln\w*|alkuperai\w*|apple|"
         r"airpods?|pro|2|usb ?c|usb|lightning|magsafe|lataus|charging|wireless|lade|oplaad|" + _SIDE_L + "|" + _SIDE_R +
         r")\W+){0,3}")
_NEG = re.compile(r"(?:\b(?:no|not|never|without|ei|eika|ilman|kein\w*|nicht|ohne|geen|niet|zonder|ingen|inga|inte|"
                  r"ej|ikke|uden|uten|nie|bez|brak|zero|nada|zadn\w*|falls|wenn|if|jos|bij|als|in case|om|hvis|"
                  r"jesli|gdy|vid|ved|bei|case of)\b[^.!?;\n]{0,56})$")

# kind -> (pattern, what it means); kinds 'part' and 'wanted' are not the item at all (resolve drops them),
# the others are the item with a problem (judge flags them: never the pick, never a market price)
_RED: list[tuple[str, re.Pattern[str], str]] = [
    ("part", re.compile(rf"\b(?:single|one|1 ?st|jedn[aey]|jeden|einzeln\w*|einzige[rn]?|losse|yksittai\w*|"
                        rf"enkel\w*)\W+{_FILL}(?:{_EAR})\b"), "only one earbud"),
    ("part", re.compile(rf"\b(?:{_ONLY}|single|one|1 ?st|einzeln\w*)\W+(?:the\W+)?(?:{_SIDE_L}|{_SIDE_R})\b"),
     "only one earbud"),
    ("part", re.compile(rf"\b(?:{_SIDE_L}|{_SIDE_R})\W+(?:{_EAR})\W+(?:only|alleen|vain)\b"), "only one earbud"),
    ("part", re.compile(rf"\b(?:{_ONLY})\W+{_FILL}(?:{_CASE})\b(?!\W+(?:and|ja|und|en|och|og|i|\+)\b)"),
     "only the charging case"),
    ("part", re.compile(rf"\b(?:{_CASE})\W+(?:\w+\W+)?(?:only|alleen|ilman kuulokkeita|ohne)\b"), "only the charging case"),
    ("part", re.compile(rf"\b(?:{_WITHOUT})\W+{_FILL}(?:{_EAR})\b"), "only the charging case (no earbuds)"),
    ("part", re.compile(rf"\b(?:{_WITHOUT})\W+{_FILL}(?:charging case|case|kotelo\w*|latauskotelo\w*|ladecase|"
                        rf"ladeetui|oplaadcase|etui|laddningsetui|dekl\w*)\b"), "earbuds without their charging case"),
    ("part", re.compile(rf"\b(?:empty|tyhja\w*|leer\w*|lege|pust[aey]|tom|tomt|tomme|{_ONLY})\W+{_FILL}"
                        rf"(?:{_BOX})\b"), "only the box"),
    ("part", re.compile(rf"\b(?:{_BOX})\W+(?:only|po|od|von|from|of|till|af|til)\b"), "only the box"),
    ("part", re.compile(r"\b(?:for parts|parts only|spares|varaosa(?!koodi)\w*|osiksi|ersatzteil\w*|onderdelen|reservdel\w*|"
                        r"reservedel\w*|deler|na czesci|czesci zamienne)\b"), "sold as parts"),
    ("wanted", re.compile(r"\b(?:ostetaan|ostan|etsitaan|etsin|wanted|wtb|looking for|gezocht|gesucht|sucht|"
                          r"kopes|kjopes|kobes|kupie|szukam|cherche|busco|cerco)\b"), "a wanted ad, not an offer"),
    ("broken", re.compile(r"\b(?:rikki|rikkinai\w*|hajonn\w*|hajalla|viallinen|vialli\w*|vika|vikaa|vikoja|"
                          r"toimimat\w*|ei toimi|ei lataa|hairio\w*|broken|faulty|defective|defect|not working|"
                          r"doesn ?t work|does not work|dont work|cracked|water damage\w*|defekt\w*|kaputt|"
                          r"funktioniert nicht|bastler\w*|kapot|werkt niet|trasig|fungerar (?:inte|ej)|ej fungerande|"
                          r"virker ikke|fungerer ikke|i stykker|odelagt|uszkodz\w*|zepsut\w*|nie dziala\w*|"
                          r"do naprawy|wadliw\w*|sugedes|neveikia)\b"), "broken or faulty"),
    ("fake", re.compile(r"(?:\b(?:kopio\w*|replica\w*|replika\w*|fake|clone|klon|klony|high quality copy|hq copy|"
                        r"super copy|master copy|aaa quality|nachbau|namaak|kopia(?! (?:paragon|faktur|rachun|dowod))|podrobk\w*|ei alkuperainen|"
                        r"not original|non original|nie oryginaln\w*|nieoryginaln\w*|niet origineel|kein original|"
                        r"imitat\w*|ei aito|ei aidot)\b|(?<![\d.,:])1 ?: ?1(?![\d.,:]))"), "probably a copy, not the original"),
    ("locked", re.compile(r"\b(?:lukossa|lukittu|icloud\W+(?:\w+\W+)?(?:lock\w*|lukko\w*|lukossa|gesperrt|"
                          r"zablokowan\w*|last|vergrendeld)|activation lock|aktivierungssperre|gesperrt|"
                          r"zablokowan\w*|vergrendeld|apple id\W+(?:\w+\W+)?(?:lock\w*|lukossa|gesperrt))\b"),
     "locked to someone else's account"),
    ("swap", re.compile(r"\b(?:vaihto(?:kauppa\w*)?|vaihdetaan|vaihdossa|vaihtaisin|swap\w*|trade for|tausch\w*|"
                        r"ruil\w*|bytes|byte mot|byttes|zamiana|zamienie)\b"), "a swap, not a sale"),
]
_PAIR = re.compile(r"\b(?:pair|pari|paar|par|para|set|sett|zestaw|komplet\w*)\b")
_TITLE_HYPHEN_CASE = re.compile(r"\b[\w]+-(?:case|oplaadcase|ladecase|kotelo|latauskotelo|etui|ladeetui|hulle)\b")
_WITH_BEFORE = re.compile(r"\b(?:with|met|mit|med|kanssa|incl\w*|inkl\w*|z|ze|su|and|en|und|och|og|ja)\b[^,|]*$|\+[^,|]*$")
_ROW_META = re.compile(r",\s*(?:tuotemerkki|malli|kunto|koko|brand|condition|marke|zustand|merk|staat|stan)\s*:")
_TITLE_BOX_END = re.compile(rf"\b(?:{_BOX})\W*$")
_TITLE_BOX_LEAD = re.compile(rf"^\W*(?:\w+\W+)?(?:{_BOX})\b(?!\W*:)")
_IN_BOX = re.compile(r"\b(?:in|i|w|im|met|with|mit|med|kanssa|z|ze|incl\w*|inkl\w*|og|ja|and|und|en|plus|new|nieuw|uusi|"
                     r"neu|ny|nowe|sealed|geseald)\W+(?:\w+\W+)?$|\+\W*$")
_SINGLE_SIDE_L = re.compile(rf"\b(?:{_SIDE_L})\b")
_SINGLE_SIDE_R = re.compile(rf"\b(?:{_SIDE_R})\b")
_EAR_RX = re.compile(rf"\b(?:{_EAR})\b")
# marketplaces put the seller's brand field in the row text: 'Tuotemerkki: Shein', 'Marke: TWS', 'Merk: Burga'
_BRAND_FIELD = re.compile(r"\b(?:tuotemerkki|brand|marke|merk|marka|marque|marca|varumarke|maerke)\s*:\s*([^,|;]{1,40})")
NO_NAME_BRANDS = {"tws", "ingen", "kita", "other", "others", "muu", "andere", "anders", "inny", "be prekinio zenklo",
                  "no brand", "nobrand", "unbranded", "noname", "no name", "generic", "bluetooth", "idk", "brak",
                  "ei merkkia", "ohne marke", "geen merk", "utan marke"}
RED_REJECT = ("part", "wanted")       # not the item / not an offer: resolve drops them
RED_RISKY = ("broken", "fake", "locked", "swap")    # the item with a problem: judge never picks or prices them


# negation AFTER the word: Finnish / Nordic / German word order ('Mitään vikoja ei ole ilmennyt', 'Mängel sind keine')
_NEG_AFTER = re.compile(r"^[^.!?;\n]{0,24}?\b(?:ei (?:ole|ilmene|esiinny|loydy|havaittu|ilmennyt)|eika|ei mitaan|"
                        r"not (?:found|present|any)|sind keine|gibt es (?:nicht|keine)|zijn er niet|niet aanwezig|"
                        r"finns (?:inte|ej)|finnes ikke|findes ikke|nie ma|nie stwierdzono|brak)\b")


def _negated(folded: str, start: int, end: int | None = None) -> bool:
    if _NEG.search(folded[max(0, start - 64):start]):
        return True
    return end is not None and bool(_NEG_AFTER.search(folded[end:end + 40]))


def _earbuds(need: Need | None) -> bool:
    return bool(need and re.search(r"airpods|earbuds|buds\b|earphones|in-ear|nappikuulok|kuulokkeet|"
                                   r"galaxy buds|pixel buds|wf-\d", need.thing.lower()))


@functools.lru_cache(maxsize=50000)
def _red_flags_cached(text: str, need_thing: str, need_brand: str, earbuds: bool, title: bool
                      ) -> tuple[tuple[str, str, str], ...]:
    folded = fold_text(text)
    asked = fold_text(need_thing)
    out: list[tuple[str, str, str]] = []
    for kind, rx, what in _RED:
        if kind in ("wanted", "swap") and not title:
            continue      # site chrome says 'Ostetaan' / 'Gesucht' (a category); 'Tausch möglich' on a sale is fine
        for m in rx.finditer(folded):
            if kind not in ("wanted", "part") and _negated(folded, m.start(), m.end()):
                continue
            if kind == "part" and _negated(folded, m.start()) and not re.match(rf"(?:{_WITHOUT})\b", m.group(0)):
                continue
            if m.group(0).strip() in asked:
                continue      # they asked for it ('airpods pro 2 case', 'broken iphone')
            if kind == "part" and _PAIR.search(m.group(0)):
                continue      # 'one pair of AirPods' is the whole thing
            phrase = text[m.start():m.end()].strip()
            if not any(k == kind and w == what for k, w, _ in out):
                out.append((kind, what, phrase))
            break
    if title and not any(k == "part" for k, _, _ in out):
        # 'AirPods Pro 2 Lightning-case goede staat' / 'USB-C-case': a hyphenated case word is the case alone
        m = _TITLE_HYPHEN_CASE.search(folded)
        if m and not _WITH_BEFORE.search(folded[max(0, m.start() - 30):m.start()]) and "case" not in asked.split():
            out.append(("part", "only the charging case", text[m.start():m.end()].strip()))
    if title and not any(k == "part" for k, _, _ in out):
        # 'Original AirPods Pro (2nd generation) box', 'Airpods pro (Laatikko)', 'Pudełko AirPods Pro 2'
        head = folded[:m0.start()] if (m0 := _ROW_META.search(folded)) else folded
        m = _TITLE_BOX_END.search(head) or _TITLE_BOX_LEAD.search(head)
        if m and not _IN_BOX.search(head[max(0, m.start() - 24):m.start()]) and "box" not in asked.split():
            out.append(("part", "only the box", text[m.start():m.end()].strip(" ()")))
    # one earbud: a side named without the other ('AirPods Pro 2 Oikea A3047', 'lewa słuchawka')
    if earbuds and not any(k == "part" and w == "only one earbud" for k, w, _ in out):
        lm, rm = _SINGLE_SIDE_L.search(folded), _SINGLE_SIDE_R.search(folded)
        side = lm if lm and not rm else rm if rm and not lm else None
        if side is not None and (title or _near_ear(folded, side.start())) and not _negated(folded, side.start()):
            out.append(("part", "only one earbud", text[side.start():side.end()].strip()))
    if title and need_brand:
        for m in _BRAND_FIELD.finditer(folded):
            b = m.group(1).strip()
            if not b or need_brand in b or b in need_brand:
                continue
            if b in NO_NAME_BRANDS:
                out.append(("fake", "a no-name brand, not the original", text[m.start(1):m.end(1)].strip()))
            else:
                out.append(("part", f"another brand ({text[m.start(1):m.end(1)].strip()}), so a case or accessory",
                            text[m.start(1):m.end(1)].strip()))
            break
    return tuple(out)


def _near_ear(folded: str, at: int) -> bool:
    return bool(_EAR_RX.search(folded[max(0, at - 30):at + 30]))


def listing_red_flags(text: str, need: Need | None = None, *, title: bool = True) -> list[tuple[str, str, str]]:
    """[(kind, what it means, the seller's words)] for a listing title (title=True) or its description.
    kinds: part (one earbud, the case or box only, sold as parts, another brand's case), wanted (a wanted ad),
    broken, fake (copy / no-name), locked (iCloud), swap. Empty when nothing is wrong."""
    if not text:
        return []
    brand = signature(need.thing).brand if need is not None and need.kind != "service" else None
    return list(_red_flags_cached(text[:6000], need.thing if need else "", brand or "", _earbuds(need), title))


def red_flag_text(kind: str, what: str, phrase: str) -> str:
    """'only one earbud ("Oikea")' for a verdict line or a skip reason."""
    return f"{what} (“{phrase[:40]}”)"


def title_red_flags(o: Offer, need: Need | None) -> list[tuple[str, str, str]]:
    """Red flags in what the listing row itself says: its title (+ the row text a split marketplace page gave)."""
    if need is not None and need.kind == "service":
        return []
    return listing_red_flags(o.title or "", need, title=True)


# ---------------------------------------------------------------- pages that are not one offer

# search results, category and list pages: the price is one of many items, the url is not a listing
LIST_URL = re.compile(
    r"/(?:s|sch|search|searchpage(?:\.jsp)?|haku|suche|b|kp|l|c|list|lists|category|categories|kategorie|"
    r"kategoria|collections|browse|catalogsearch|recommerce/forsale/search)(?:/|$|\?)"
    r"|/s-[^/]+/k0\b|/k0$|[?&](?:k|q|_nkw|query|search|keyword|keywords|searchterm)="
    r"|/(?:all|alle|kaikki)/?$", re.I)
NOT_OFFER_TITLE = re.compile(
    r"\bab\s*€\s*\d|\bpreisvergleich\b|\bprice comparison\b|\bhintavertailu\b|\bprice history\b"
    r"|\bis on sale\b|\bon sale for\b|\bprice drops?\b|\bdeal alert\b", re.I)
SISTER_SHOPS = ({"mediamarkt", "saturn"}, {"gigantti", "elgiganten", "elkjop"}, {"power", "expert"})


def _host(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/?#]+)", url or "")
    return m.group(1).lower() if m else ""


# a whole site or category page read as one 'offer': 'Used Cars for Sale' (capitalone.com, €6,333), 'Autot',
# 'Gebrauchtwagen', '1 234 results'. Its price is some item's on it: never an offer (expanded into its listings
# by the reader when it knows the site, else skipped).
CATEGORY_TITLE = re.compile(
    r"^(?:(?:used|new|cheap|best|all|buy|shop|find|browse|second[- ]hand|pre[- ]owned|certified)\s+)*"
    r"(?:[a-z]+\s+){0,2}(?:cars|autos|vehicles|trucks|vans|suvs|bikes|bicycles|phones|laptops|cameras|"
    r"listings|products|items|deals|offers|ads)\b(?:\s+(?:for\s+sale|near\s+(?:you|me)|in\s+\w+(?:\s+\w+)?|"
    r"online|today|from\s+dealers?|and\s+\w+))*\s*$"
    r"|^(?:käytetyt|myytävät|vaihtoautot|autot|gebrauchtwagen|gebrauchte\s+autos|occasions?|tweedehands\s+auto'?s|"
    r"begagnade\s+bilar|brugte\s+biler|bruktbiler|voitures\s+d'occasion|coches\s+de\s+segunda\s+mano|auto\s+usate)"
    r"(?:\s+\w+){0,3}\s*$"
    r"|\b\d[\d .,]*\s+(?:results|listings|ads|ilmoitusta|angebote|anzeigen|resultaten|advertenties|annonser|"
    r"annoncer|cars|autos|autoa)\b", re.I)
WHOLESALE_TITLE = re.compile(r"\b(?:wholesale|bulk\s+lot|job\s+lot|lot\s+of\s+\d+|\d+\s*(?:x|pcs|pieces|stk|kpl)\b.*"
                             r"\b(?:lot|pallet|bulk|wholesale)|pallets?\b|partijhandel|grossiste|großhandel|"
                             r"restposten|moq\b|min(?:imum)?\.?\s+order)", re.I)


def category_page(title: str) -> bool:
    t = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[A-Z][\w.]+$)", (title or "").strip())[0].strip(" .!:")
    return bool(t) and bool(CATEGORY_TITLE.search(t))


# ---------------------------------------------------------------- vehicles: is THIS listing a vehicle?
NOT_VEHICLE = re.compile(
    r"\b(?:toys?|lelu\w*|spielzeug\w*|leksak\w*|speelgoed\w*|kids?|children'?s?|lasten|kinder\w*|barn|"
    r"hot\s?wheels|matchbox|diecast|die-cast|1\s?:\s?\d{2,3}|scale\s+model|pienoismalli\w*|modelauto|modellauto|"
    r"ride[- ]on|pedal\s+car|slot\s?car|racetrack|race\s?track|carrera|lego|duplo|rc\b|radio[- ]controlled|"
    r"remote[- ]control\w*|kauko-ohja\w*|bed|sänky|bett|seng|poster|sticker|keychain|key\s?ring|costume|puzzle|"
    r"tinter|paint|maali|lack|lp\b|vinyl|album|cd\b|dvd|book|kirja|buch|t-?shirt|hoodie|sweat\w*|jacket|"
    r"spodnie|jeans|trousers|pants|cargo\s+\w*pants|car\s+seat|turvaistuin|kindersitz|bilbarnstol|"
    r"car\s+charger|cover|mat|matto|cam\b|dashcam|vacuum|imuri|shades?|aurinkosuoj\w*|sun\s?shades?|"
    r"vaihdelaatikko|gearbox|getriebe|moottori\s+osat?|varaosa\w*|spare\s+parts?|parts\s+car|osiksi|"
    r"hyll\w*|shelving|laatikosto\w*|trailer|peräkärry|anhänger|släpvagn|aanhanger|\w*takki|jacket|"
    r"alut|alumiinivantee\w*|\w*vanteet|nastat|\w*renkaat|tyres?|tires?|rims?|rig|golf\s?(?:cart|car)|"
    r"golfauto|sähkökärry|opas|brochure|showcase|magazine|lehti|collection|kokoelma|figure|figuuri)\b", re.I)
VEHICLE_EVIDENCE = re.compile(
    r"\b(?:19[5-9]\d|20[0-2]\d)\b|\b\d[\d .]*\s?(?:km|tkm|mi|miles)\b|\b(?:diesel|bensiini|benzin|petrol|"
    r"gasoline|hybrid|electric|sähkö|automatic|automaatti|manual|manuaali|vaihteisto|kw|hp|ps|hv|cc|tdi|tsi|"
    r"awd|4wd|4x4|katsastettu|inspected|registered|rekisteröity)\b", re.I)
# a year alone is no proof ('Toyota Corolla New Car Features -opas Apr. 1997' is a brochure)
STRONG_EVIDENCE = re.compile(
    r"\b\d[\d .]*\s?(?:km|tkm|mi|miles)\b|\b(?:diesel|bensiini|benzin|petrol|gasoline|hybrid|automatic|"
    r"automaatti|manuaali|vaihteisto|tdi|tsi|awd|4wd|4x4|katsastettu|inspected|registered|rekisteröity)\b", re.I)
VEHICLE_FLOOR_EUR = 500.0      # a whole used car for less is a toy, a part or a scam unless the listing says so


def _is_a_vehicle(word: str, offer: Offer) -> bool:
    """'car' is covered by a listing that is a car without saying so: 'Toyota Corolla 1.6 2012 210 tkm', or a
    listing filed under a cars category (raw['category'] == 'vehicle', set by the reader)."""
    try:
        from agora.need import CAR_MAKES, VEHICLE_NOUNS
    except ImportError:
        return False
    if not VEHICLE_NOUNS.match(word):
        return False
    title = offer.title or ""
    if NOT_VEHICLE.search(title):
        return False
    return offer.raw.get("category") == "vehicle" or bool(CAR_MAKES.search(title) and VEHICLE_EVIDENCE.search(title))


def vehicle_mismatch(need: Need, offer: Offer) -> str | None:
    """For a vehicle need, why this listing is not a vehicle: a toy / kids' car / model, an item that only
    shares a word (paint 'Bright Red', an LP, a bed), or a 'car' under VEHICLE_FLOOR_EUR with nothing that
    says it is one (no make, year, km, fuel). Judged per listing, whatever the site."""
    try:
        from agora.need import CAR_MAKES, vehicle_need
    except ImportError:
        return None
    if need.kind != "product" or not vehicle_need(need.thing):
        return None
    title = offer.title or ""
    if m := NOT_VEHICLE.search(title):
        return f"not a vehicle ({m.group(0).lower()})"
    if offer.raw.get("category") == "vehicle":
        return None            # listed in a cars category (nettiauto, tori autot ...): a vehicle, cheap or not
    evidence = bool(CAR_MAKES.search(title) and STRONG_EVIDENCE.search(title))
    p = offer.price_eur
    if p is not None and p < VEHICLE_FLOOR_EUR and not evidence:
        return f"€{p:,.0f} is too little for a car and the listing names no make with mileage, fuel or gearbox"
    return None


def not_an_offer(o: Offer) -> str | None:
    """Reason when the page is not one buyable listing: a search/list/category page, a price-comparison
    or news site. Such a page's price belongs to some item on it, so it must never set the market."""
    url = o.url or ""
    if not url:
        return None
    if o.raw.get("mirror_of"):
        return f"same listing as {o.raw['mirror_of']} (sister shop feed)"
    try:
        from agora import discover
        # a marketplace row's title is a seller's words ('LEGO Batman vs Riddler' is a set, not a review)
        row = bool(o.raw.get("site") and o.raw.get("from_list_page"))
        junk = discover.is_non_shop(url, "" if row else (o.title or ""))
        if junk:
            return junk
        listy = discover.is_list_page(url)
    except Exception:
        listy = False
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if listy or LIST_URL.search(parts.path + ("?" + parts.query if parts.query else "")):
        return "search or list page, not one listing"
    if NOT_OFFER_TITLE.search(o.title or ""):
        return "price comparison or news page, not a shop listing"
    if not o.raw.get("from_list_page") and category_page(o.title or ""):
        return "a category / search page (many listings), not one listing"
    if WHOLESALE_TITLE.search(o.title or ""):
        return "a wholesale lot, not one item"
    return None


def _mark_mirrors(offers: list[Offer]) -> None:
    """One retail group's sister shops (MediaMarkt / Saturn) serve the same feed: same title, price and
    condition on both is one offer, not two votes."""
    seen: dict[tuple[int, str, str, int], str] = {}
    for o in offers:
        host = _host(o.url)
        group = next((i for i, g in enumerate(SISTER_SHOPS) if host.split(".")[0] in g), None)
        if group is None or o.price_eur is None:
            continue
        key = (group, re.sub(r"\W+", " ", (o.title or "").lower()).strip(), o.condition, round(o.price_eur))
        if key in seen and seen[key] != host:
            o.raw["mirror_of"] = seen[key]
        else:
            seen.setdefault(key, host)


def is_bundle(title: str) -> bool:
    return any(p.search(title) for p in BUNDLE_PATTERNS)


def _model_match(need_sig: Signature, off_sig: Signature) -> float:
    """1 = all asked models present, ~0.1 = a *different* generation/model, 0.45 = cannot tell."""
    if not need_sig.models:
        # 'nintendo switch oled' asked: 'Nintendo Switch 2' is another console, 'Switch 2019' lacks the OLED
        score = 1.0
        nv, ov = set(need_sig.variants), set(off_sig.variants)
        fam = need_sig.family
        if fam and any(re.fullmatch(re.escape(fam) + r"\d+", m) for m in off_sig.models) and (not nv or nv - ov):
            return 0.1
        if nv - ov and (off_sig.family == fam or off_sig.models):
            score *= 0.4
        return score
    score = 1.0
    for nm in need_sig.models:
        base = nm.split("-")[0]
        if nm in off_sig.models:
            continue
        same_base = [om for om in off_sig.models if om.split("-")[0] == base]
        if same_base:
            # a7 vs a7-3: if the need names a generation and the offer names another, wrong item
            if "-" in nm and all("-" in om for om in same_base):
                return 0.1
            score = min(score, 0.7)
        elif off_sig.models:
            return 0.1 if base[:1].isalpha() and any(om[:1] == base[:1] for om in off_sig.models) else 0.2
        else:
            score = min(score, 0.55)
    # variants asked but missing (iphone 15 pro vs iphone 15) or extra (pro max vs pro)
    nv, ov = set(need_sig.variants), set(off_sig.variants)
    if nv - ov:
        score *= 0.4
    if ov - nv and need_sig.models:
        score *= 0.45   # iphone 15 asked, iphone 15 pro offered: a different (dearer) product
    return score


# ---------------------------------------------------------------- generic needs ('puhelin', 'sofa', a tree hunt)
# A need for a KIND of thing has no brand or model to match: 'Samsung A52 128GB' is a phone without saying 'phone',
# and a Finnish title never says 'sofa'. Such a need accepts: a title naming the kind in any language (the
# marketplaces' WORDS, the category node's labels and synonyms), every listing of a category page that lists
# exactly that kind, and a listing of the need's own marketplace search that names no OTHER kind of thing
# ('sohvapöytä' on a 'sohva' search is a coffee table, not a sofa). Cases, parts and wanted ads still go.

_CAT_SKIP = re.compile(r"tarvik|tillbeh|zubeh|accessor|osat\b|delar\b|teile\b|onderdel|parts?\b|varaos|reserv",
                       re.I)


@functools.lru_cache(maxsize=512)
def _is_generic_text(thing: str, tree: bool) -> bool:
    sig = signature(thing)
    if sig.brand or sig.models or sig.family:
        return False
    try:
        from agora import marketplaces as M
    except ImportError:
        return False
    noun = M.english_noun(thing)
    if noun is None:
        return tree
    rest = M.FILLER.sub(" ", thing)
    rest = M._GENERIC_RE.sub(" ", rest)
    rest = M._REVERSE_RE.sub(" ", rest)
    rest = re.sub(r"[^\w\s'-]", " ", rest)
    return tree or not M._carrier(rest)


def is_generic(need: Need) -> bool:
    """A product need for a kind of thing ('puhelin', 'phone', 'baby stroller', 'kitchen table', a hunt from the
    category tree) rather than a product ('iphone 13', 'lego', 'herman miller chair')."""
    if need.kind != "product":
        return False
    tree = (need.category or {}).get("source") == "tree"
    return _is_generic_text(need.thing or "", tree)


def _fold_words(words: Any) -> frozenset[str]:
    out: set[str] = set()
    for w in words:
        f = " ".join(t for t in tokenize(str(w)) if t)
        if len(f) >= 3:
            out.add(f)
    return frozenset(out)


@functools.lru_cache(maxsize=256)
def _noun_words(noun: str) -> frozenset[str]:
    from agora import marketplaces as M
    words = set(M.translations(noun))
    for w in noun.split():
        words |= SYNONYMS.get(w, set())
    # a narrower kind is still the kind: 'road bike' words count for 'bike' ('maantiepyörä' is a bike)
    for other in M.WORDS:
        if other != noun and other.endswith(" " + noun):
            words |= M.translations(other)
    return _fold_words(words)


def _need_words(need: Need) -> frozenset[str]:
    """Folded words that name the need's kind: its noun in every language + the category node's own words."""
    cat = need.category or {}
    return _need_words_cached(need.thing or "", str(cat.get("id") or ""), str(cat.get("label") or ""),
                              tuple(sorted((cat.get("labels") or {}).values())), tuple(cat.get("synonyms") or ()))


@functools.lru_cache(maxsize=256)
def _need_words_cached(thing: str, cat_id: str, cat_label: str, labels: tuple[str, ...],
                       synonyms: tuple[str, ...]) -> frozenset[str]:
    from agora.models import Need as _Need
    need = _Need(raw=thing, thing=thing, category={"id": cat_id, "label": cat_label,
                                                   "labels": dict(enumerate(labels)), "synonyms": list(synonyms)})
    return _need_words_build(need)


def _need_words_build(need: Need) -> frozenset[str]:
    from agora import marketplaces as M
    noun = M.english_noun(need.thing or "")
    words = set(_noun_words(noun)) if noun else set()
    cat = need.category or {}
    extra: list[str] = []
    for lab in (cat.get("labels") or {}).values():
        extra += [t for t in tokenize(str(lab)) if len(t) >= 5 and not M.MODIFIERS.search(t)]
    for syn in cat.get("synonyms") or []:
        if not _CAT_SKIP.search(str(syn)) and len(str(syn).split()) <= 2:
            extra.append(str(syn))
    if cat.get("label") and not noun:
        extra += [t for t in tokenize(str(cat["label"])) if len(t) >= 4 and not M.MODIFIERS.search(t)]
    return frozenset(words | _fold_words(extra))


@functools.lru_cache(maxsize=1)
def _concepts() -> tuple[tuple[str, frozenset[str]], ...]:
    """Every WORDS noun with the words that name it, for the 'another kind of thing' check. Short foreign words
    collide across languages (Czech 'stan' = tent is Polish 'condition', 'kolo', 'kast', 'ski'), so only the
    English word and translations of 5+ letters count here."""
    from agora import marketplaces as M
    out = []
    for noun in M.WORDS:
        words = {w for w in M.translations(noun) if w == noun or len(w) >= 5}
        words |= {w for x in noun.split() for w in SYNONYMS.get(x, set()) if len(w) >= 5}
        out.append((noun, _fold_words(words)))
    return tuple(out)


def _compatible(a: str, b: str) -> bool:
    """Two WORDS nouns name the same kind of thing: one is a narrower kind of the other ('road bike' / 'bike',
    'winter jacket' / 'jacket'), or both lead to the same category node ('jacket' / 'coat', 'sofa' / 'couch')."""
    if a == b or a.endswith(" " + b) or b.endswith(" " + a):
        return True
    try:
        from agora.sources.categories import GENERIC_NODES
    except ImportError:
        return False
    def node(x: str) -> str | None:
        return GENERIC_NODES.get(x) or GENERIC_NODES.get(x.split()[-1])
    return node(a) is not None and node(a) == node(b)


def _hits(words: frozenset[str], toks: set[str]) -> bool:
    return _hits_cached(words, frozenset(toks))


@functools.lru_cache(maxsize=512)
def _word_re(words: frozenset[str]) -> tuple[re.Pattern[str] | None, tuple[str, ...]]:
    """word_hit for many single words at once, as one regex over one token: exact, word + ending, or compound
    head (3+ letters before a 4+ letter word). Phrases are returned apart (word_hit checks them)."""
    single = sorted((w for w in words if " " not in w and w), key=len, reverse=True)
    phrases = tuple(w for w in words if " " in w)
    if not single:
        return None, phrases
    short = [re.escape(w) for w in single if len(w) < 4]
    long_ = [re.escape(w) for w in single if len(w) >= 4]
    alts = []
    if short:
        alts.append(r"(?:" + "|".join(short) + r")(?:es|s)?")
    if long_:
        ends = "|".join(re.escape(e) for e in sorted(_ENDINGS, key=len, reverse=True))
        alts.append(r"(?:" + "|".join(long_) + r")(?:" + ends + r")?")
        alts.append(r"\w{3,}(?:" + "|".join(long_) + r")")
    return re.compile(r"^(?:" + "|".join(alts) + r")$"), phrases


@functools.lru_cache(maxsize=50000)
def _hits_cached(words: frozenset[str], toks: frozenset[str]) -> bool:
    """Any of the words in the title tokens (whole word, ending or compound head). Cached: one hunt asks it for
    the same 2,000 titles from relevance, explain and the kind check."""
    if words & toks:
        return True
    rx, phrases = _word_re(words)
    if rx is not None and any(rx.match(t) for t in toks):
        return True
    return any(word_hit(w, toks) for w in phrases)


def other_kind(need: Need, offer: Offer) -> str | None:
    """The WORDS noun of ANOTHER kind of thing this listing names ('coffee table' for 'sofa': 'sohvapöytä'),
    when it names nothing of the need's own kind. Generic needs only."""
    from agora import marketplaces as M
    noun = M.english_noun(need.thing or "")
    if not noun:
        return None
    toks = set(tokenize(offer.title or ""))
    if _hits(_need_words(need), toks):
        return None
    for other, words in sorted(_concepts(), key=lambda c: -len(c[0])):     # 'coffee table' before 'table'
        if not _compatible(other, noun) and _hits(words, toks):
            return other
    return None


def _generic_coverage(need: Need, offer: Offer, toks: set[str]) -> float | None:
    """Coverage of a generic need (None = not generic: the word rule decides)."""
    if not is_generic(need):
        return None
    if _hits(_need_words(need), toks):
        return 1.0
    cp = offer.raw.get("category_page") if isinstance(offer.raw, dict) else None
    if cp and cp.get("exact"):
        return 1.0                      # the seller filed it under exactly this kind (tori 'Matkapuhelimet')
    if other_kind(need, offer):
        return 0.0
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    if raw.get("site") and raw.get("from_list_page"):
        return 0.7                      # the marketplace's own search (or broader category) for this kind
    return None


def relevance(need: Need, offer: Offer) -> float:
    """0..1: how well this offer answers the need."""
    if not_an_offer(offer):
        return 0.0
    if kind_mismatch(need, offer) or far_provider(need, offer):
        return 0.05            # a gun for a gunsmith hunt, a repair rate for a product hunt, a US gunsmith
    ns = signature(need.thing)
    os_ = signature(offer.title or "", offer.brand)
    title_toks = set(tokenize(offer.title or "")) | os_.words | set(os_.models)
    need_words = {w for w in ns.words if w not in ATTRIBUTE_ONLY}
    hay = " ".join(title_toks) + " " + (os_.brand or "")
    toks = title_toks | ({os_.brand} if os_.brand else set())
    covered = sum(1 for w in need_words if word_hit(w, toks) or any(word_hit(x, toks) for x in SYNONYMS.get(w, ()))
                  or _is_a_vehicle(w, offer))
    coverage = covered / len(need_words) if need_words else 1.0
    if need.kind == "service":
        return _service_relevance(need, offer)
    gen = _generic_coverage(need, offer, toks | set(tokenize(offer.title or "")))
    if gen is not None:
        coverage = gen
    model = _model_match(ns, os_)
    if ns.models and not os_.models and any(re.fullmatch(r"iphone\d+", x) for x in ns.models) \
            and re.search(r"\biphone\s*(?:x[rs]?|se)\b", offer.title or "", re.I):
        model = 0.1            # 'iPhone XR' / 'iPhone SE' carry no number but are other models
    brand_ok = 1.0
    if ns.brand and os_.brand and ns.brand != os_.brand:
        brand_ok = 0.2
    elif ns.brand and not os_.brand and ns.brand not in hay:
        brand_ok = 0.95
    # model identity dominates; extra words only nudge ("sony a7 iii" vs "a7 iii body black")
    score = model * (0.75 + 0.25 * coverage) if ns.models else (0.2 + 0.8 * coverage) * model
    score *= brand_ok
    if is_accessory(offer.title or "", need):
        score *= 0.15
    elif any(k in RED_REJECT for k, _, _ in title_red_flags(offer, need)):
        score *= 0.15     # one earbud, the box, a wanted ad: not the item
    if vehicle_mismatch(need, offer):
        score *= 0.05
    if os_.kit and not ns.kit and not need.must_have:
        score *= 0.9   # body asked, kit offered: same camera, slightly different deal
    if offer.condition not in ("unknown", *need.conditions):
        score *= 0.8
    return round(max(0.0, min(1.0, score)), 3)


# what a service *is*: a page must name the job, not just the object ('bike' alone is a bike shop)
SERVICE_NOUNS: tuple[frozenset[str], ...] = (
    frozenset({"repair", "repairs", "service", "servicing", "maintenance", "fix", "fixing", "korjaus", "korjaamo",
               "huolto", "huollon", "huollot", "huoltoon", "huoltopaketti", "checkup", "check-up", "tune-up",
               "tuneup", "overhaul", "reparatur", "werkstatt", "wartung", "inspection", "puncture"}),
    frozenset({"cleaning", "clean", "cleaner", "cleaners", "siivous", "siivouksen", "siivoja", "kotisiivous",
               "reinigung", "putzen", "stadning", "housekeeping", "schoonmaak", "schoonmaken", "schoonmaker",
               "schoonmaakster", "schoonmaakbedrijf", "huishoudelijke", "poetshulp", "haushaltshilfe", "putzhilfe",
               "reinigungskraft", "hemstadning", "stadare", "stadfirma", "rengoring", "rengoringshjaelp",
               "vaskehjelp", "rengøring", "menage", "nettoyage", "limpieza", "pulizie", "pulizia", "sprzatanie", "uklid",
               "limpeza", "maid", "maids", "housecleaning", "werkster", "huishoudhulp", "poetsvrouw", "putzfrau"}),
    frozenset({"moving", "movers", "removal", "muutto", "muuttopalvelu", "umzug", "flytt", "verhuizing",
               "verhuisbedrijf", "umzugsfirma", "umzugsunternehmen", "flyttfirma", "flyttefirma", "demenagement",
               "mudanza", "trasloco", "przeprowadzka"}),
    frozenset({"painting", "painter", "maalaus", "maalari", "schilder", "schilderwerk", "maler", "malerarbeiten",
               "malare", "peintre", "pintor", "imbianchino"}),
    frozenset({"plumber", "plumbing", "putkimies", "lvi", "loodgieter", "klempner", "sanitar", "installateur",
               "rormokare", "vvs", "rorlegger", "plombier", "plomberie", "fontanero", "idraulico", "hydraulik",
               "canalizador", "instalater"}),
    frozenset({"electrician", "sahkoasentaja", "sahkotyot", "elektricien", "elektriker", "electricien",
               "electricista", "elettricista", "elektryk", "eletricista", "electrical", "sahkotyo", "sahkoasennu",
               "sahkomies", "sahkourako", "sahkoliike", "sahkopalvelu", "elektroinstall", "elektrotechn",
               "elektrotechnik", "elektriciteit"}),
    frozenset({"handyman", "handymen", "klusjesman", "klusser", "klusbedrijf", "hausmeister", "hausmeisterservice",
               "handwerker", "allrounder", "talonmies", "remonttimies", "fixare", "hantverkare", "vicevaert",
               "bricoleur", "manitas", "tuttofare", "fachowiec"}),
)
GUNSMITH_GROUP = frozenset({"gunsmith", "gunsmiths", "gunsmithing", "aseseppa", "asesepat", "asesepan", "asesepalla",
                            "asesepalle", "asesepaksi", "asekorjaamo", "asekorjaus", "asehuolto", "asepaja",
                            "buchsenmacher", "buchsenmacherei", "buchsenmachermeister", "waffenschmied",
                            "waffenwerkstatt", "wapensmid", "geweermaker", "vapensmed", "bossemager", "bøssemager",
                            "borsemaker", "børsemaker", "armurier", "armurerie", "armero", "armaiolo", "rusznikarz",
                            "puskar", "armeiro", "aseiden", "aseen", "asekunnostus", "firearm", "firearms",
                            "waffenservice", "wapenonderhoud", "vapenservice"})
SERVICE_NOUNS = SERVICE_NOUNS + (GUNSMITH_GROUP,)
CLEANING_GROUP, PLUMBER_GROUP, ELECTRICIAN_GROUP, HANDYMAN_GROUP = (SERVICE_NOUNS[1], SERVICE_NOUNS[4],
                                                                    SERVICE_NOUNS[5], SERVICE_NOUNS[6])
# open-ended trades: the job is unknown until they come, so the fair comparison is a standard call
OPEN_TRADES = (PLUMBER_GROUP, ELECTRICIAN_GROUP, HANDYMAN_GROUP)
TRADE_HOURS = 1.0     # a standard call: 1 h of labour (+ call-out fee), shown as an estimate

# a line on a price list that is not a price for the job at all: an admin fee, a surcharge, materials, parking
FEE_LINE = re.compile(
    r"verwaltung|bearbeitungsgebuhr|servicepauschale|admin(?:istrat\w*)?\s*(?:fee|charge|kosten)|administratiekosten|"
    r"booking fee|boekingskosten|service fee|servicekosten|toimistomaksu|laskutuslisa|invoic\w* fee|"
    r"rechnungsgebuhr|surcharge|zuschlag|aufpreis|toeslag|lisamaksu|lisahinta|add-on|extra charge|"
    r"\bparking|parkeer|parkgebuhr|materialpauschale|kleinmaterial|materiaalikulu|\bper km\b|km-pauschale|"
    r"kilometer", re.I)
# a call-out / visit fee: added on top of the hourly rate, never a job price on its own
CALLOUT_LINE = re.compile(
    r"call[- ]?out|visit (?:fee|cost|charge)|^visit\b|house call|travel (?:fee|cost|charge)|anfahrt|fahrtkosten|"
    r"kurzbesuch|hausbesuch|einsatzpauschale|voorrij|starttarief|uitrukkosten|kaynti|matkakulu|lahtomaksu|"
    r"startavgift|utryckning|framkorning|deplacement|desplazamiento|diritto di chiamata", re.I)
# a premium rate (emergency, night, weekend, urgent): not the standard price
PREMIUM_LINE = re.compile(
    r"notdienst|notfall|emergency|urgent|spoed|noodgeval|paivystys|\bkiire|weekend|wochenende|sonntag|sunday|"
    r"feiertag|holiday|\bnacht|\bnight|after[- ]hours|\babend", re.I)
# a different service than the one asked (sofa cleaning is not home cleaning), per service group
OFF_TOPIC: dict[frozenset[str], re.Pattern[str]] = {
    CLEANING_GROUP: re.compile(
        r"furniture|sofa|couch|bankstel|meubel|upholster|stoffeer|matras|mattress|carpet|\brugs?\b|tapijt|"
        r"vloerkleed|teppich|polster|\bmatto|laundry|ironing|strijk|wasserij|wassen en|wasche|bugel|pyykki|"
        r"silitys|window|ramen|glazenwas|fenster|ikkun|\bcar\b|\bauto\b|oven|gutter|dakgoot|facade|gevel|solar|"
        r"zonnepan|zwembad|\bpool\b|office|kantoor|\bburo|toimisto|construction|bouwschoonmaak|oplever|baustelle|"
        r"rakennus|graffiti|ontruim|entrumpel|tatort|crime scene|deep[- ]?clean|dieptereinig|grundreinigung|"
        r"perusteellinen|suursiivous|eindschoonmaak|verhuisschoonmaak|umzugsreinigung|endreinigung|muuttosiivous|"
        r"move[- ]?(?:out|in) clean|end[- ]of[- ]tenancy|storstadning|flyttstadning", re.I),
}
DEAL_SITES = ("socialdeal.", "groupon.", "dealdonkey.", "tiketti.", "letsdeal.", "outspot.", "vakantieveilingen.")
DEAL_TITLE = re.compile(r"\bdeal\b|voucher|gutschein|aanbieding|kortingsbon|tarjous|\bactie\b|coupon", re.I)


def service_group(need: Need) -> frozenset[str] | None:
    """The kind of service asked for (cleaning, plumbing, ...), from the need's words."""
    words = [w for w in re.findall(r"\w+", _fold(need.thing)) if len(w) > 1]
    return next((g for g in SERVICE_NOUNS if any(w in g for w in words)), None)


def is_open_trade(need: Need) -> bool:
    """A plumber / electrician / handyman asked for without a specific task: compare a standard call."""
    g = service_group(need)
    return g is not None and g in OPEN_TRADES and not _task_words(need)


def _task_words(need: Need) -> list[str]:
    """Words of the need beyond the trade and the job size ('drain' in 'plumber drain unblocking')."""
    g = service_group(need) or frozenset()
    return [w for w in re.findall(r"\w+", _fold(need.thing)) if len(w) > 2 and w not in g
            and not _JOB_SIZE.match(w) and w not in ("service", "services", "price", "prices", "home")]


def is_deal(o: Offer) -> bool:
    """A voucher / deal-site price (socialdeal '3 uur schoonmaak €19'): fine to show, labelled a deal."""
    return any(d in (o.source or "") for d in DEAL_SITES) or bool(DEAL_TITLE.search(o.title or ""))


def service_line_kind(need: Need, title: str, unit: str | None) -> str:
    """What one price line of a service provider is, for this need:
    'main' (a price for the asked job: hourly / per m² / per clean), 'callout' (a visit fee on top),
    'fee' (admin fee, surcharge: never an offer), 'premium' (emergency/weekend rate), 'task' (a price for one
    specific job of an open-ended trade, e.g. bleeding a radiator), 'off_topic' (another service)."""
    t = _fold(title or "")
    g = service_group(need)
    asked = _fold(need.thing)
    if FEE_LINE.search(t) and not FEE_LINE.search(asked):
        return "fee"
    if (off := OFF_TOPIC.get(g)) is not None and (m := off.search(t)) and not off.search(asked):
        return "off_topic"
    if CALLOUT_LINE.search(t) or (unit or "") == "visit" and g in OPEN_TRADES:
        return "callout"
    if PREMIUM_LINE.search(t) and not PREMIUM_LINE.search(asked):
        return "premium"
    if g in OPEN_TRADES and (unit or "") in ("job", "m2"):
        tw = _task_words(need)
        if not (tw and any(w in t for w in tw)):
            return "task"
    return "main"


def off_topic_reason(need: Need, offer: Offer) -> str | None:
    """Why a single service offer is not an offer for this need: an admin fee / surcharge, or another service."""
    if need.kind != "service":
        return None
    kind = (offer.raw or {}).get("line_kind") or service_line_kind(need, offer.title or "", offer.unit)
    if kind == "fee":
        return "a fee or surcharge, not a price for the job"
    if kind == "off_topic":
        g = service_group(need)
        m = OFF_TOPIC[g].search(_fold(offer.title or "")) if g in OFF_TOPIC else None
        return f"a different service ({m.group(0) if m else 'other'}), not {need.thing}"
    return None
# ---------------------------------------------------------------- product vs service (per listing)
# A service need never takes a thing for sale (a gun, a scope, a manga called 'Gunsmith Cats'); a product need
# never takes a service ad (a repair shop's hourly rate). Judged per listing from its title, description, unit
# and page type; no site is ever blocked.
SERVICE_UNITS = {"hour", "h", "job", "visit", "m2", "session", "lesson", "day", "month", "year", "week", "night",
                 "person", "project"}
SERVICE_WORDING = re.compile(
    r"\b(?:services?|servicing|repairs?|repairing|maintenance|installation|install|fitting|mounting|cleaning|"
    r"overhaul|restoration|refinish\w*|cerakote|bluing|blueing|engraving|alteration\w*|inspection|appointment|"
    r"workshop|price\s*list|pricelist|rates?|labou?r|per\s+hour|hourly|an\s+hour|/\s?h\b|/\s?hr\b|per\s+job|"
    r"huolto\w*|korjau\w*|korjaamo\w*|asennu\w*|kiikaroin\w*|tyo|tyot|tyon|tyota|tuntihinta|hinnasto\w*|palvelu\w*|"
    r"reparatur\w*|wartung|instandsetzung|werkstatt|einschiessen|montage|stundensatz|preisliste|dienstleistung\w*|"
    r"onderhoud|reparatie\w*|werkplaats|uurtarief|prijslijst|reparation\w*|underhall|verkstad|timpris|prislista|"
    r"tjanst\w*|entretien|atelier|tarifs?|riparazion\w*|naprawa|serwis)\b", re.I)
# a thing whose name merely contains the trade's word: books, manga, films, games, merch, toys
MEDIA_MERCH = re.compile(
    r"\b(?:manga|anime|comics?|graphic\s+novel|novel|books?|paperback|hardcover|ebook|kirja\w*|sarjakuva\w*|"
    r"buch|bucher|boek|boeken|bok|bocker|livre|libro|fumetto|ksiazka|komiks|tlumaczenie|tłumaczenie|"
    r"volume|vol\.?\s*\d|tom\s*\d|band\s*\d|osa\s*\d|dvd|blu-?ray|vhs|film|movie|elokuva|soundtrack|vinyl|"
    r"\bcd\b|album|video\s*game|ps[2-5]|playstation|xbox|nintendo|switch\s+game|pc\s+game|steam\s+key|"
    r"board\s*game|lautapeli|brettspiel|poster|julisteet?|t-?shirt|hoodie|paita|sticker|tarra|mug|muki|"
    r"figure|figuuri|figurine|action\s+figure|lego|toy|lelu|spielzeug|cosplay|costume|keychain|avaimenperä|"
    r"magazine|lehti|zeitschrift)\b", re.I)
# a thing for sale: listing wording and, for the gun trade, the guns and parts themselves
FOR_SALE = re.compile(
    r"\b(?:for\s+sale|myydaan|myyd\w*|myynnissa|zu\s+verkaufen|verkaufe|te\s+koop|saljes|til\s+salgs|"
    r"a\s+vendre|se\s+vende|vendo|sprzedam|brand\s+new|new\s+in\s+box|nib|unused|kayttamaton|"
    r"kaytetty|gebraucht|tweedehands|begagnad|used|shipping|toimitus|versand|in\s+stock|varastossa|"
    r"add\s+to\s+cart|lisaa\s+ostoskoriin|warenkorb)\b", re.I)
GUN_ITEMS = re.compile(
    r"\b(?:rifles?|shotguns?|pistols?|revolvers?|handguns?|airguns?|air\s+rifle|scopes?|riflescope|"
    r"kivaari\w*|haulikko\w*|pistooli\w*|revolveri\w*|ilmakivaari\w*|kiikaritahtain\w*|kiikari\w*|"
    r"tahtain\w*|aanenvaimen\w*|vaimennin|lipas|lippaat|patruun\w*|ammo|ammunition|cartridges?|"
    r"gewehr\w*|buchse|flinte|zielfernrohr|schalldampfer|munition|geweer|jachtgeweer|vapen\b|gevar|"
    r"stocks?|magazines?|barrels?|holsters?|gun\s+safe|asekaappi|waffenschrank|bipod|asepussi|asekotelo|"
    r"gun\s+(?:bag|case|cabinet)|futteral|waffenkoffer)\b", re.I)
# marketplaces of goods only (no service ads): a listing there is a thing unless it states a rate or the work
GOODS_ONLY = ("vinted.", "ebay.", "backmarket.", "amazon.", "refurbed.", "swappie.", "rebuy.", "momox.", "etsy.",
              "zalando.", "aliexpress.", "temu.", "wish.com", "huuto.net", "tradera.com", "catawiki.")
_MARKET_SPLIT = ("contextdev_markdown_split", "contextdev_list", "jsonld_itemlist")


FAR_CURRENCIES = {"USD", "CAD", "AUD", "NZD"}


def far_provider(need: Need, offer: Offer) -> str | None:
    """A local trade (a gunsmith, a cleaner) is done where you are: a provider pricing in dollars is on another
    continent, whatever its page says. B2B / digital services are delivered from anywhere and stay."""
    if need.kind != "service" or (offer.currency or "").upper() not in FAR_CURRENCIES:
        return None
    try:
        from agora.discover import country_of, domain_of, home_country, is_eu
        from agora.need import priced_per_period
        if priced_per_period(need) or is_eu(domain_of(offer.url or "") or offer.source or ""):
            return None          # a .de page quoting dollars is still a Berlin plumber
        if offer.location and need.where and need.where.lower() in offer.location.lower():
            return None
        cc = country_of(need) or home_country()
    except Exception:
        return None
    if not cc or cc.lower() in ("us", "ca", "au", "nz"):
        return None
    return f"a provider abroad (prices in {offer.currency.upper()}), not a {service_label(need)} near you"


def service_label(need: Need) -> str:
    """How the hunt names the service asked for: 'gunsmith', 'home cleaning'."""
    cat = need.category or {}
    if cat.get("label") and cat.get("source") == "tree":
        return str(cat["label"]).lower()
    return (need.thing or "").strip() or "that"


def _service_signal(offer: Offer, text: str) -> bool:
    if (offer.unit or "").lower() in SERVICE_UNITS:
        return True
    return bool(SERVICE_WORDING.search(text))


def _listing_text(offer: Offer) -> str:
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    return _fold(" ".join([offer.title or "", str(raw.get("description") or "")[:600],
                           str(raw.get("search_text") or "")[:300]]))


def kind_mismatch(need: Need, offer: Offer) -> str | None:
    """Reason a listing is the wrong KIND of offer for the need, else None.
    Service need: a thing for sale (a book / manga / game / merch whose title merely holds the trade's word, a
    marketplace or product-page listing with no service wording, a gun or part) -> "a product, not a
    gunsmith service". Product need: a service ad (an hourly / per-job rate, a repair shop's price list)
    -> "a service, not a <thing>"."""
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    title = _fold(offer.title or "")
    text = _listing_text(offer)
    if need.kind in ("service", "digital"):
        if need.kind == "digital":
            return None
        label = service_label(need)
        asked = _fold(f"{need.thing} {' '.join(need.must_have)}")
        media = MEDIA_MERCH.search(title)
        if media and not MEDIA_MERCH.search(asked) and (offer.unit or "").lower() not in SERVICE_UNITS:
            return f"a product, not a {label} service (a book, film or merch item that only shares the name: {media.group(0).strip()})"
        if _service_signal(offer, title + " " + text):
            return None
        gun = GUN_ITEMS.search(title)
        if gun and not GUN_ITEMS.search(asked):
            return f"a product, not a {label} service (a gun or part for sale)"
        goods_only = any(d in (offer.source or "") for d in GOODS_ONLY)
        g = service_group(need)
        if not goods_only and g is not None and any(
                x in set(re.findall(r"\w+", title)) or (len(x) >= 6 and x in title) for x in g):
            return None           # the listing names the trade itself ('Putzhilfe', 'Aseseppä Virtanen')
        try:
            from agora.need import priced_per_period
            if priced_per_period(need):
                return None       # a SaaS / B2B plan page looks like a product page: only titles above count
        except Exception:
            pass
        page_product = (offer.read_via == "contextdev_product" or raw.get("step") in _MARKET_SPLIT
                        or bool(raw.get("grade")) or bool(raw.get("shutter_count"))
                        or any(raw.get(k) for k in ("gtin14", "gtin13", "gtin12", "gtin8")))
        try:
            from agora import discover
            market = discover.is_marketplace(offer.source or "") and not any(
                discover.dom_match(offer.source or "", d) for d in discover.SERVICE_DIRECTORIES)
        except Exception:
            market = False
        sale = FOR_SALE.search(text)
        if goods_only or page_product or market or sale or offer.shipping_eur:
            return f"a product, not a {label} service"
        return None
    if "rental" in need.conditions:
        return None
    unit = (offer.unit or "").lower()
    if offer.condition == "service" or unit in ("hour", "h", "visit", "session", "lesson"):
        return f"a service, not a {need.thing}"
    asked = _fold(need.thing)
    if SERVICE_WORDING.search(asked):
        return None                    # 'repair kit', 'cleaning robot': the need itself uses the words
    if re.search(r"\b(?:per\s+hour|hourly|/\s?h\b|tuntihinta|stundensatz|uurtarief|timpris|hinnasto|"
                 r"price\s*list|preisliste|prijslijst)\b", title) and not re.search(r"\d\s*(?:km|w|wh|mah)\s*/\s?h", title):
        return f"a service, not a {need.thing}"
    return None


_JOB_SIZE = re.compile(r"^\d+(?:[.,]\d+)?(?:m2|m²|sqm|nelio\w*)?$")
# a bike shop's motorbike page shares 'pyora' and 'huolto'; a car garage shares 'repair'
_SERVICE_CLASH = {"bike": re.compile(r"moottori|motor(?:cycle|rad|bike)|\bmopo|skootteri|\bauto(?!ma)|\bcar\b", re.I)}


def _service_relevance(need: Need, offer: Offer) -> float:
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    if off_topic_reason(need, offer):
        return 0.1         # an admin fee, or sofa cleaning when home cleaning was asked
    text = _fold(" ".join([offer.title or "", str(raw.get("description") or ""), str(raw.get("page_title") or ""),
                           offer.url or ""]))
    words = set(re.findall(r"\w+", text))
    # '24m2' sizes the job, it is not a word the provider's page has to say
    thing_words = [w for w in re.findall(r"\w+", _fold(need.thing)) if len(w) > 1 and not _JOB_SIZE.match(w)]
    groups = [g for g in SERVICE_NOUNS if any(w in g for w in thing_words)]

    def hit(w: str) -> bool:
        alts = {w} | SYNONYMS.get(w, set())
        return any(a in words or (len(a) >= 4 and a in text) for a in alts)

    svc = [m for m in need.must_have if m.lower() in text] + [w for w in thing_words if hit(w)]
    def named(g: frozenset[str]) -> bool:
        """The page names the job: a word of the group, or a long one inside a compound ('Schoonmaakbedrijf')."""
        return any(x in words or (len(x) >= 6 and x in text) for x in g)

    for g in groups:   # the job named in another language / form ('huollon' for 'repair') covers that word
        if any(w in g for w in thing_words if not hit(w)) and named(g):
            svc.append(next(w for w in thing_words if w in g and not hit(w)))
    score = 0.4 + 0.6 * min(1.0, len(set(svc)) / max(1, len(thing_words)))
    if groups and not any(any(x in words or (len(x) >= 5 and x in text) for x in g) for g in groups):
        score *= 0.3       # 'bike repair' asked, a €6,400 e-bike product page offered
    for w, clash in _SERVICE_CLASH.items():
        if w in thing_words and clash.search(text) and not clash.search(need.thing):
            score *= 0.3
    if re.search(r"surcharge|lisamaksu|lisahinta|aufpreis|zuschlag|add-on|extra charge", _fold(offer.title or "")):
        score *= 0.4       # 'full suspension bike surcharge' (€15) is a line on top of a job, not a job
    if need.where and offer.location and need.where.lower() not in offer.location.lower():
        score *= 0.6
    return round(min(score, 1.0), 3)


def explain(need: Need, offer: Offer, threshold: float = 0.5) -> tuple[float, str | None]:
    """-> (relevance, reason it was rejected or None)."""
    r = relevance(need, offer)
    if r >= threshold and (why := _llm_veto(need, offer)):
        return 0.0, why
    if r >= threshold:
        return r, None
    if why := kind_mismatch(need, offer) or far_provider(need, offer):
        return r, why
    if why := not_an_offer(offer):
        return r, why
    if need.kind == "service":
        return r, off_topic_reason(need, offer) or "not that service (the page does not name the job)"
    if why := vehicle_mismatch(need, offer):
        return r, why
    if is_accessory(offer.title or "", need):
        return r, "accessory, not the item"
    if is_generic(need) and (other := other_kind(need, offer)):
        return r, f"another kind of thing ({other}), not a {_need_noun(need)}"
    if bad := [f for f in title_red_flags(offer, need) if f[0] in RED_REJECT]:
        k, what, phrase = bad[0]
        return r, (f"not an offer: {red_flag_text(k, what, phrase)}" if k == "wanted"
                   else f"a part, not the whole item: {red_flag_text(k, what, phrase)}")
    ns, os_ = signature(need.thing), signature(offer.title or "", offer.brand)
    if ns.models and os_.models and _model_match(ns, os_) <= 0.2:
        return r, f"different model ({' '.join(os_.models)} vs {' '.join(ns.models)})"
    if ns.models and set(ns.models) <= set(os_.models) and set(ns.variants) != set(os_.variants):
        return r, f"another version ({_pretty(os_)} vs {_pretty(ns)})"     # iphone 13 pro / mini for iphone 13
    return r, "does not match what you asked for"


def _need_noun(need: Need) -> str:
    try:
        from agora import marketplaces as M
        return M.english_noun(need.thing or "") or need.thing
    except ImportError:
        return need.thing


def _pretty(sig: Signature) -> str:
    parts: list[str] = []
    if sig.brand:
        parts.append(sig.brand.title() if len(sig.brand) > 3 else sig.brand.upper())
    if sig.family and not any(m.startswith(sig.family) for m in sig.models):
        parts.append(FAMILY_DISPLAY.get(sig.family, sig.family.title()))
    for m in sig.models:
        base, _, gen = m.partition("-")
        fam = re.match(r"^([a-z]+?)(\d+)$", base)
        if fam and fam.group(1) in FAMILY_DISPLAY:
            base = f"{FAMILY_DISPLAY[fam.group(1)]} {fam.group(2)}"
        else:
            base = base.upper()
        parts.append(base + (" " + ROMAN_OUT.get(int(gen), gen) if gen.isdigit() else ""))
    parts += [v.title() for v in sig.variants]
    if sig.kit:
        parts.append("kit")
    return " ".join(parts)


def _need_name(need: Need, sig: Signature) -> str:
    """The Thing's name when titles carry no model: the signature when it says more than the brand
    ('Nintendo Switch Oled'), else the words they asked for ('Ikea Kallax Shelf', not 'Ikea')."""
    pretty = _pretty(sig)
    if pretty and (sig.models or sig.family or sig.variants):
        return pretty
    return " ".join(w if any(c.isupper() for c in w) else w.capitalize() for w in need.thing.split()) or pretty


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "thing"


# ---------------------------------------------------------------- GTIN / MPN: exact product keys

GTIN_FIELDS = ("gtin14", "gtin13", "gtin12", "gtin8", "gtin", "ean", "ean13", "upc", "barcode")
_GTIN_LENGTHS = (8, 12, 13, 14)


def gtin_check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits before it: weights 3,1,3,... from the right."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def normalize_gtin(code: object) -> str | None:
    """Any GTIN-8/12/13/14 (UPC-A, EAN-13...) -> the zero-padded GTIN-14, or None when it is not a valid
    GTIN (wrong length, bad check digit, all zeros). UPC-A 012345678905 == EAN-13 0012345678905."""
    if code is None or isinstance(code, bool):
        return None
    if isinstance(code, int):
        code = str(code)
    if not isinstance(code, str):
        return None
    digits = re.sub(r"[\s-]", "", code.strip())
    if not digits.isdigit() or len(digits) not in _GTIN_LENGTHS:
        return None
    g = digits.zfill(14)
    if set(g) == {"0"} or gtin_check_digit(g[:-1]) != int(g[-1]):
        return None
    return g


def normalize_mpn(code: object) -> str | None:
    """Manufacturer part number, compared without spaces/dashes/slashes ('ILCE-7M3/B' -> 'ILCE7M3B').
    Only codes that look like part numbers (letters AND digits, 5+ chars) are used as keys."""
    if not isinstance(code, str):
        return None
    m = re.sub(r"[^A-Z0-9]", "", code.upper())
    if len(m) < 5 or not re.search(r"\d", m) or not re.search(r"[A-Z]", m) or normalize_gtin(m):
        return None
    return m


def product_keys(o: Offer) -> set[str]:
    """Exact identity keys of an offer: 'gtin:<14 digits>' and 'mpn:<code>' from reader fields
    (JSON-LD gtin/gtin13/mpn kept in raw, or a barcode-shaped sku). Also stores raw['gtin14']."""
    raw = o.raw if isinstance(o.raw, dict) else {}
    keys: set[str] = set()
    for f in GTIN_FIELDS:
        g = normalize_gtin(raw.get(f))
        if g:
            keys.add("gtin:" + g)
    g = normalize_gtin(o.sku)
    if g:
        keys.add("gtin:" + g)
    gt = sorted(k[5:] for k in keys if k.startswith("gtin:"))
    if gt:
        raw["gtin14"] = gt[0]
    for f in ("mpn", "model_number"):
        m = normalize_mpn(raw.get(f))
        if m:
            keys.add("mpn:" + m)
    return keys


def _llm_veto(need: Need, offer: Offer) -> str | None:
    """The model's confident "no" stored on the offer by `agora.relevance.prefetch` (None without it)."""
    from agora.relevance import veto
    return veto(need, offer)


def resolve(need: Need, offers: list[Offer], threshold: float = 0.5) -> list[Thing]:
    """Cluster relevant offers into Things (biggest first). Irrelevant offers are left out
    (thing_id stays None); bundles get a 'bundle' flag. Use `explain` for the skip reason."""
    sigs: dict[str, Signature] = {}
    buckets: dict[str, list[Offer]] = {}
    loose: list[Offer] = []
    need_sig = signature(need.thing)
    _mark_mirrors(offers)
    keys_of = {id(o): product_keys(o) for o in offers}
    rel = {id(o): relevance(need, o) for o in offers}
    vetoed = {id(o) for o in offers if _llm_veto(need, o)}   # agora.relevance: a confident model "no" drops it
    # an exact GTIN/MPN shared with a relevant offer is the same product, even under a vague title
    trusted = {k for o in offers if rel[id(o)] >= threshold for k in keys_of[id(o)]}
    for o in offers:
        if id(o) in vetoed:
            continue
        if rel[id(o)] < threshold:
            if not (keys_of[id(o)] & trusted) or is_accessory(o.title or "", need) or not_an_offer(o):
                continue
            o.raw["matched_by"] = "gtin" if any(k.startswith("gtin:") for k in keys_of[id(o)] & trusted) else "mpn"
        s = signature(o.title or "", o.brand)
        if is_bundle(o.title or "") and "bundle" not in o.flags:
            o.flags.append("bundle")
        if need.kind == "service" or not s.models:
            loose.append(o)
            continue
        # fold brand-less titles into the need's brand so "a7 III" == "Sony a7 III"
        if not s.brand and need_sig.brand:
            s.brand = need_sig.brand
        k = s.key
        sigs.setdefault(k, s)
        buckets.setdefault(k, []).append(o)
    # merge brand-less buckets into a branded bucket with the same models
    for k in list(buckets):
        s = sigs[k]
        if s.brand:
            continue
        twin = next((k2 for k2, s2 in sigs.items() if s2.brand and s2.models == s.models and s2.variants == s.variants and s2.kit == s.kit), None)
        if twin:
            buckets[twin] += buckets.pop(k)
    _merge_by_keys(buckets, sigs, loose, keys_of)
    things: list[Thing] = []
    for k, offs in buckets.items():
        s = sigs[k]
        name = _pretty(s)
        things.append(Thing(id="t-" + _slug(name), name=name, offers=offs))
    if loose:
        if things and need.kind != "service":
            max(things, key=lambda t: len(t.offers)).offers.extend(loose)   # vague titles join the main thing
        else:
            name = need.thing if need.kind == "service" else _need_name(need, need_sig)
            things.append(Thing(id="t-" + _slug(name), name=name, offers=loose))
    things.sort(key=lambda t: len(t.offers), reverse=True)
    for t in things:
        for o in t.offers:
            o.thing_id = t.id
    return things


def _merge_by_keys(buckets: dict[str, list[Offer]], sigs: dict[str, Signature], loose: list[Offer],
                   keys_of: dict[int, set[str]]) -> None:
    """Exact-key pass: buckets that share a GTIN-14 (or an MPN) are one product, whatever the titles say;
    a vague-titled ('loose') offer with a known GTIN joins the bucket that has it. The bigger bucket
    keeps its name. Mutates `buckets` and `loose` in place."""
    def owner_of(key: str) -> str | None:
        for k, offs in buckets.items():
            if any(key in keys_of.get(id(o), ()) for o in offs):
                return k
        return None

    changed = True
    while changed:
        changed = False
        for k in list(buckets):
            if k not in buckets:
                continue
            mine = {key for o in buckets[k] for key in keys_of.get(id(o), ())}
            for k2 in list(buckets):
                if k2 == k or k2 not in buckets:
                    continue
                theirs = {key for o in buckets[k2] for key in keys_of.get(id(o), ())}
                shared = mine & theirs
                if not shared:
                    continue
                if any(x.startswith("mpn:") for x in shared) and not any(x.startswith("gtin:") for x in shared):
                    b1, b2 = sigs[k].brand, sigs[k2].brand
                    if b1 and b2 and b1 != b2:
                        continue        # the same part number from two brands is a coincidence
                big, small = (k, k2) if len(buckets[k]) >= len(buckets[k2]) else (k2, k)
                for o in buckets[small]:
                    o.raw.setdefault("matched_by", "gtin" if any(x.startswith("gtin:") for x in shared) else "mpn")
                buckets[big] += buckets.pop(small)
                changed = True
                break
            if changed:
                break
    for o in list(loose):
        for key in sorted(keys_of.get(id(o), ()), key=lambda x: not x.startswith("gtin:")):
            k = owner_of(key)
            if k is not None:
                o.raw.setdefault("matched_by", key.split(":")[0])
                buckets[k].append(o)
                loose.remove(o)
                break


def most_common_brand(offers: list[Offer]) -> str | None:
    c = Counter((o.brand or "").lower() for o in offers if o.brand)
    return c.most_common(1)[0][0] if c else None
