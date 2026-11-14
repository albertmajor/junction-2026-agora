"""RESOLVE: offers -> Things.

Shops all name the same camera differently: "SONY A7 III BODY", "Sony a7 III Mirrorless Camera",
"Sony Alpha ILCE-7M3", "a7iii", "A7 Mark 3". We turn every title into a *signature*:
  brand + model tokens (with generation folded in) + variant words (pro/max/r/s...) + kit flag
and ignore colours, "body only", marketing fluff. Same signature -> same Thing.

Also: accessories ("battery for Sony a7 III") are recognised and rejected, bundles flagged,
and `relevance(need, offer)` scores 0..1 how well an offer answers the need.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

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
}
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
]


# same thing, other languages: a hit on any synonym counts as a hit on the need word
SYNONYMS: dict[str, set[str]] = {
    "washing": {"pesukone", "waschmaschine", "tvattmaskin", "washer"},
    "machine": {"pesukone", "waschmaschine", "tvattmaskin", "washer", "kone"},
    "dishwasher": {"astianpesukone", "geschirrspuler", "diskmaskin"},
    "fridge": {"jaakaappi", "kuhlschrank", "kylskap", "refrigerator"},
    "vacuum": {"imuri", "staubsauger", "dammsugare", "hoover"},
    "bike": {"bicycle", "polkupyora", "pyora", "fahrrad", "cykel"},
    "sofa": {"sohva", "couch", "soffa"},
    "laptop": {"notebook", "kannettava", "lappari"},
    "phone": {"puhelin", "smartphone", "handy"},
    "camera": {"kamera"},
    "tv": {"television", "televisio", "fernseher"},
    "headphones": {"kuulokkeet", "kopfhorer", "headset", "earbuds"},
    "stroller": {"rattaat", "kinderwagen", "pram", "pushchair"},
}


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
    if any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", asked) for w in (*ACCESSORY_WORDS, *PART_WORDS)):
        return False   # they asked for the accessory itself ("battery for sony a7 iii")
    for w in ACCESSORY_WORDS:
        if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low) and w not in asked:
            # "camera with battery and charger" is a bundle, not an accessory: the accessory word
            # must come before "for X" or lead the title, or appear without a main-item word
            if re.search(rf"(?:\bwith\b|\bmit\b|\bincl\w*|\+|\band\b|\bw/)[^|]*\b{re.escape(w)}", low):
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
        junk = discover.is_non_shop(url, o.title or "")
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


def relevance(need: Need, offer: Offer) -> float:
    """0..1: how well this offer answers the need."""
    if not_an_offer(offer):
        return 0.0
    ns = signature(need.thing)
    os_ = signature(offer.title or "", offer.brand)
    title_toks = set(tokenize(offer.title or "")) | os_.words | set(os_.models)
    need_words = ns.words
    hay = " ".join(title_toks) + " " + (os_.brand or "")
    covered = sum(1 for w in need_words if w in hay or any(x in hay for x in SYNONYMS.get(w, ())))
    coverage = covered / len(need_words) if need_words else 1.0
    if need.kind == "service":
        return _service_relevance(need, offer)
    model = _model_match(ns, os_)
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
    if why := not_an_offer(offer):
        return r, why
    if need.kind == "service":
        return r, off_topic_reason(need, offer) or "not that service (the page does not name the job)"
    if is_accessory(offer.title or "", need):
        return r, "accessory, not the item"
    ns, os_ = signature(need.thing), signature(offer.title or "", offer.brand)
    if ns.models and os_.models and _model_match(ns, os_) <= 0.2:
        return r, f"different model ({' '.join(os_.models)} vs {' '.join(ns.models)})"
    return r, "does not match what you asked for"


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
