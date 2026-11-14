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
    "lego", "nike", "adidas", "puma", "asics", "new balance", "fjallraven", "patagonia", "north face",
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
# a revision of the same item, not another tier: 'PS5 Slim' is a PS5 (live: 65 'Ps5 Slim 1tb' skipped as another
# version). Tier words (pro, max, mini, lite, plus ...) still make another product.
NEUTRAL_VARIANTS = {"slim"}


def _tiers(variants: tuple[str, ...] | list[str]) -> set[str]:
    return set(variants) - NEUTRAL_VARIANTS

ACCESSORY_WORDS = {
    "case", "cover", "sleeve", "bag", "pouch", "skin", "battery", "batteries", "charger", "charging",
    "cable", "adapter", "adaptor", "strap", "screen protector", "protector", "tempered glass", "cage",
    "grip", "lens cap", "cap", "hood", "mount", "tripod", "gimbal", "remote", "dock", "holder",
    # 'stand' alone is the Danish/Norwegian word for condition ('Flot stand', live: 35 dba iPhones dropped)
    "stand for", "floor stand", "charging stand", "laptop stand", "monitor stand", "phone stand", "ständer",
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
    # bike parts and gear sold alone (live, road bike: '26-tuuman sisärenkaita' €2, 'Vanteita 28”', '12V ilma kompura')
    "sisärenkaita", "sisärenkaat", "sisuskumi", "sisuskumit", "vanne", "vanteet", "vanteita", "rengas", "renkaat",
    "renkaita", "nastarengas", "nastarenkaat", "ulkorengas", "ulkorenkaat", "kompura", "kompressori", "satula",
    "polkimet", "poljin", "ketju", "ketjut", "lokasuoja", "lokasuojat", "tavarateline", "pyöräteline", "kypärä",
    "pyöränlukko", "pumppu", "takavaihtaja", "etuvaihtaja", "kasetti", "rattaat ja kuomu",
    # vacuum attachments and spares (live, dyson v15: a €10 'Pölyharjakiinnitys' won; PL/DE/NL/FI words)
    "harja", "harjat", "kiinnitys", "suutin", "suuttimet", "rakosuutin", "suodatin", "suodattimet", "szczotka",
    "elektroszczotka", "końcówka", "koncowka", "ssawka", "pojemnik", "zasilacz", "ładowarka", "ladowarka", "filtr",
    "filtry", "fugendüse", "düse", "bürste", "staubbehälter", "behälter", "ladestation", "zubehör", "zubehor",
    "borstel", "mondstuk", "halterung", "wandhalterung", "seinäteline", "ersatzakku", "akkupack",
    # coffee maker consumables and spares (live, kahvinkeitin: '5kpl suodatinpusseja' €1, 'Mocca masterin kansi' €1)
    "suodatinpussi", "suodatinpussit", "suodatinpusseja", "kansi", "lasikannu", "kannu", "kapseli", "kapselit",
    "kapseleita", "kalkinpoisto", "kalkinpoistoaine", "kaffeekapseln", "kapseln", "entkalker", "filtertüten",
    # phone spares and cables
    "kaapeli", "puhelinkaapeli", "puhelinkaapelit", "näytönsuoja", "suojalasi", "panssarilasi",
    # batteries sold alone (live, dyson v15: 'Originele Dyson V11/V15 Accu' €30 was the pick)
    "accu", "accu's", "batterij", "batterijen", "baterijos", "baterija", "akumulator", "floor dok", "oplaadstandaard",
    "vloerstandaard", "laddstation", "ladestativ",
    # merch named after the item (live, lego technic: 'LEGO 107544 Star Wars Keychain' at €4)
    "keychain", "key chain", "keyring", "avaimenperä", "schlüsselanhänger", "nyckelring", "brelok", "sleutelhanger",
    # boxes and baskets for a shelf (live, kallax: '2kpl punaista laatikkoa Kallax' €10 in the top 3)
    "laatikkoa", "laatikot", "laatikoita", "säilytyslaatikkoa",
    # accessories in Nordic titles (live, dyson v15: 'Originalt Dyson V15s Detect Submarine tilbehør' €361)
    "tilbehør", "tilbehor", "tillbehör", "tillbehor", "suulake", "suulakkeet", "moppaussuulake", "lader",
    # things a fuzzy marketplace search returns for a phone / pram (live, vinted.fi: a lanyard, a fisheye lens, a
    # flower pot, a blanket, a lock cable kept as 'puhelin' / 'kinderwagen')
    "avainnauha", "kaulanauha", "kalansilmä", "kalansilmälinssi", "gimbel", "käsilaukku", "olkalaukku",
    "kukkaruukku", "koriste", "koristeet", "viltti", "villaviltti", "vaijeri", "lukitusvaijeri", "hyttysverkko",
    "myggnät", "myggnat",
    # parts of a pram / sofa / bike sold alone (live: 'Brio lastenrattaiden istuinosa' €5, 'Bugaboo donkey istuin
    # kankaat', 'Twistshake rattaiden lisäosia', 'rattaiden istuinpehmuste', 'Askon taivutettaessa tarjotintaso')
    "istuinosa", "istuinkangas", "kankaat", "lisäosa", "lisäosia", "lisäosat", "pehmuste", "istuinpehmuste",
    "tarjotin", "tarjotintaso", "stemmi", "koppa", "vaunukoppa", "kantokoppa", "babywanne", "liggdel",
}
# words that are an extra in a listing of the item when they come AFTER its name with a separator or a spec between
# ('Sony A7 III Body | SmallRig Cage | OVP', 'iPhone 13 93% - telefon,opakowanie,kabel'): tier A needs a separator
# or a spec, tier B (cases) a spec ('IPhone 13 128GB ... Hülle'); 'iPhone 13 kotelo' stays a case
EXTRA_A = {"pudełko", "pudelko", "opakowanie", "box", "karton", "kabel", "cable", "kaapeli", "charger", "laturi",
           "lader", "ladegerät", "ladekabel", "akku", "battery", "batteries", "batteri", "batterier", "cage", "filter",
           "filtr", "strap", "hihna", "tilbehør", "tillbehör", "zubehör", "ohjain", "ohjaimet", "controller",
           "dualsense", "joy-con", "joycon", "joy con", "dock", "telakka", "renkaat", "rengas", "vanteet", "teline",
           "laukku", "bag", "tasche", "grip", "tripod", "remote", "harja", "harjat", "suutin", "suuttimet",
           "kansi", "kannu", "lasikannu", "pumppu", "lokasuojat", "tavarateline", "satula", "kypärä", "pyöränlukko",
           # 'ruokapöytä pyöreä 106cm / mustat jalat': the table's own legs (live: 3 dining tables dropped)
           "jalat", "jalka", "laatikkoa", "laatikot"}
EXTRA_B = {"kotelo", "case", "etui", "hülle", "cover", "kuori", "suojakuori", "skal", "fodral", "deksel", "hoesje",
           "suojalasi", "panssarilasi", "screen protector", "protector", "tempered glass", "näytönsuoja"}
_EXTRA_SEP = re.compile(r"[,|+&/;(•·]|\s[-–—]\s|\b(?:ja|and|und|og|och|en|i|z|ze|with|mit|med|met|incl\w*|inkl\w*)\b")
_EXTRA_SPEC = re.compile(r"\d+\s?(?:gb|tb|gt|go)\b|\d{2,3}\s?%|\b(?:stan\w*|kunto|kunnossa|zustand|condition|stand|tilstand|"
                         r"skick|staat|body|runko|ovp|komplett\w*|complete|unlocked|sim-?free|kondycj\w*)\b")
# a repair note names a part without selling it: 'akku ja näyttö vaihdettu', 'md nyt batteri', 'neuer Akku'
_PART_OF_ITEM = r"(?:akku|akun|battery|batteri|batterie|bateria|baterie|näyttö|näytön|naytto|screen|display|lasi|takalasi|kamera|camera|rengas|renkaat|ketju|ketjut|satula)"
_REPAIRED = re.compile(rf"\b{_PART_OF_ITEM}\W+(?:\w+\W+){{0,3}}?(?:vaihdettu|vaihdettiin|uusittu|uusittu|replaced|getauscht|"
                       rf"erneuert|wymienion\w*|wymieniony|vervangen|byttet|udskiftet|bytt|uusi|uudet|new|neu\w*)\b"
                       rf"|\b(?:vaihdettu|uusittu|uusi|uudet|uudella|new|neu\w*|nowa|nowy|nowe|nieuwe|ny|nyt|nye|fresh)"
                       rf"\W+(?:\w+\W+){{0,1}}?{_PART_OF_ITEM}\b")
_COMPAT_CODE = re.compile(r"(?<![\w-])([a-z]{1,3})[- ]?(\d{1,3})(?![\w-])")
BATTERY_WORDS = {"akku", "battery", "batteri", "akku-", "accu", "batterij", "baterija", "baterijos", "akumulator"}
MERCH_WORDS = {"keychain", "key chain", "keyring", "avaimenperä", "schlüsselanhänger", "nyckelring", "brelok",
               "sleutelhanger"}
_BATTERY_STATE = re.compile(r"(?:e-?bike|fat\s?bike|sähköpy\w*|sahkopy\w*|pedelec|e-?fahrrad|elcykel|elsykkel)\b.*"
                            r"\b(?:akku|battery|batteri|accu)\b|"
                            r"\b(?:akku|battery|batteri|akkukunto|battery health|akun kunto)\w*\W{0,12}\d{2,3}\s*%|"
                            r"\d{2,3}\s*%\W{0,6}(?:akku|battery|batteri)|"
                            r"\b(?:aito|uusi|alkuperäinen|vaihdettu|new|original|neuer?|neu)\s+(?:akku|battery|batteri)\b")
# compound tails that make a word a cover / charger in Finnish and German titles (whole words are matched below)
_ACC_TAIL = re.compile(r"\b\w{3,}?(kuoret|kuori|suojakuori|suojalasi|panssarilasi|laturi|hülle|ladekabel|"
                       r"ladegerät|ladeschale|kiinnitys|suutin|suuttimet|harja|harjat|suodatin|suodattimet|renkaat|"
                       r"renkaita|rengas|kumi|kumit|kansi|kannu|pussit|pusseja|pussi|ohjain|ohjaimet|bürste|düse|"
                       r"behälter|halterung|zubehör|vanteet|vanne|akseli|ladestation|kapseln|kapselit|kotelo|suulake|suulakkeet|"
                       r"-lader|-laddare|-laturi)\b")
# words that name a part of the item: an accessory when they come *before* the item's name
# ("OLED Display for Nintendo Switch OLED"), not after ("MacBook Air with 15.3" display")
PART_WORDS = ("display", "screen", "panel", "housing", "shell", "back cover", "battery", "beeldscherm", "scherm",
              "bildschirm", "näyttö", "ekran", "skärm", "skjerm", "tastatur", "toetsenbord", "näppäimistö",
              "klawiatura", "moederbord", "emolevy", "mainboard", "scharnier", "accu", "batterij", "bateria",
              "charging port", "speaker", "fan", "keyboard", "trackpad", "hinge", "joystick", "board", "dock",
              "controller", "cable", "remote", "head", "attachment", "tool", "nozzle", "wand", "bin", "cyclone")
_FOR = (r"(?:for|fits|compatible\s+with|works\s+with|designed\s+for|suitable\s+for|für|passend\s+für|pour|sopii|til|för|"
        r"voor|kompatibel(?:\s+mit)?|compatible|compatibile|yhteensopiva|sopiva|passer\s+til|passar(?:\s+till)?|"
        r"pasuje\s+do|do|na|dla|geeignet\s+für)")
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
             "cityrad", "damenrad", "herrenrad", "mtb", "bmx", "ebike", "e-bike", "pedelec", "fatbike", "gravel",
             "hardtail", "maastopyora", "mountainbike", "racefiets", "rennrad", "cykel", "herrecykel", "damecykel"},
    "city": {"kaupunki", "stads", "citybike", "cityrad", "miejski", "ville", "bysykkel"},
    "shelf": {"hylly", "regal", "hylla", "hylle", "reol", "kast", "etagere"},
    "sofa": {"sohva", "couch", "soffa", "sohvasänky", "sohvasanky", "vuodesohva", "divaani", "bäddsoffa",
             "baddsoffa", "schlafsofa", "slaapbank", "sovesofa", "sovesófa", "kanapa", "sofa"},
    "road": {"kilpapyora", "kilpapyörä", "racer", "racercykel", "landeveissykkel", "landevejscykel", "racefiets",
             "rennrad", "maantiepyora", "maantiepyörä"},
    "laptop": {"notebook", "kannettava", "lappari"},
    "phone": {"puhelin", "smartphone", "handy"},
    "camera": {"kamera"},
    "tv": {"television", "televisio", "fernseher"},
    "headphones": {"kuulokkeet", "kopfhorer", "headset", "earbuds"},
    "stroller": {"rattaat", "kinderwagen", "pram", "pushchair", "vaunut", "vaunu", "lastenvaunut", "yhdistelmavaunut",
                 "matkarattaat", "buggy", "barnvagn", "sittvagn", "wozek", "wozki", "poussette", "passeggino",
                 "kinderwagens", "barnevogn", "klapvagn", "duovaunut", "loistovaunut"},
    "car": {"auto", "bil", "pkw", "voiture", "coche", "henkiloauto", "personbil", "vehicle", "automobile", "kasko",
            "liikennevakuutus", "autovakuutus", "kfz", "motor", "bilforsakring", "bilforsikring", "autoverzekering"},
    # services in the local language (live: helsinkibarber.fi 'Hiustenleikkuu' €20, artomarkkanen.fi
    # 'Vihkiminen ja häämuotokuvat' €900, holvi.com 'Kirjanpitopalvelut' were 'not that service')
    "haircut": {"hiustenleikkuu", "hiustenleikkaus", "leikkuu", "leikkaus", "parturi", "kampaamo", "barber",
                "barbershop", "cut", "trim", "haarschnitt", "friseur", "herrenschnitt", "knippen", "kapper", "kapsalon",
                "klippning", "frisor", "frisør", "fryzjer", "strzyzenie", "coiffeur", "coupe", "hair"},
    "wedding": {"haa", "haat", "haakuva", "haamuoto", "haapotre", "haapaketti", "haakuvaus", "vihkimi", "hochzeit",
                "bruiloft", "trouwen", "trouwfoto", "bryllup", "brollop", "slub", "slubn", "mariage", "boda", "bride",
                "morsian", "elopement"},
    "photographer": {"kuvaaja", "valokuva", "kuvaus", "kuvauspaketti", "potretti", "muotokuva", "fotograf",
                     "fotograaf", "fotografie", "photograph", "photo", "photography", "fotografia", "fotografo"},
    "photography": {"kuvaaja", "valokuva", "kuvaus", "kuvauspaketti", "potretti", "muotokuva", "fotograf",
                    "fotograaf", "fotografie", "photograph", "photo", "photographer"},
    "bookkeeping": {"kirjanpito", "kirjanpid", "tilitoimisto", "tilipalvelu", "accounting", "accountant",
                    "buchhaltung", "boekhoud", "bokforing", "regnskab", "regnskap", "ksiegow", "tilinpaatos",
                    "toiminimi", "payroll"},
    "accounting": {"kirjanpito", "kirjanpid", "tilitoimisto", "tilipalvelu", "bookkeeping", "accountant",
                   "buchhaltung", "boekhoud", "bokforing", "regnskab", "ksiegow"},
    "insurance": {"vakuutus", "versicherung", "verzekering", "forsakring", "forsikring", "ubezpieczen", "assurance"},
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


@functools.lru_cache(maxsize=65536)
def _fold(text: str) -> str:
    # ™ / ® first: NFKD turns '™' into 'TM' ('M Cut™' was 'm cuttm', no haircut)
    t = unicodedata.normalize("NFKD", text.lower().replace("™", " ").replace("®", " "))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\bi\s+phone\b", "iphone", t)                        # 'I Phone 13' is an iPhone 13
    # '13-serien' / '13 series' / '13-sarja' (a model line, Danish/Swedish/Finnish): the bare number
    t = re.sub(r"\b(\d{1,3})\s*-?\s*(?:serien|serie|series|sarja|sarjan)\b", r"\1", t)
    t = re.sub(r"\b(\d+)[- ]?(core|kern|ytiminen)\b", r" \1core ", t)    # '8-core GPU' is a spec, not a model
    # screen sizes are units, not model numbers: 'OLED 7"' / '15,3""' / '13.6-inch' / '15 Zoll' -> 7in
    t = re.sub(r"(\d+)(?:[.,]\d+)?(?:\s*(?:\"+|''|”|″)|\s*-?\s*(?:inch(?:es)?|zoll|tuumaa?)\b|-?in\b)", r" \1in ", t)
    # warranty / age durations are not models either: 'TAKUU 6kk' (Finnish: 6-month warranty), '12 months'
    t = re.sub(r"\b(\d+)\s*(kk|mo|mos|months?|monate?n?|vuotta|yrs?|years?|jahre?)\b", r" \1mo ", t)
    # ordinal generations: '(2nd generation)' / '2nd gen' / 'second generation' -> a bare number after the name
    # (a 'genN' token: it joins the last model, or the family when there is none: kindle 11th gen -> kindle11)
    t = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b(?:\s*-?\s*gen(?:eration)?\b\.?)?", r" gen\1 ", t)
    # Dutch / German / Nordic / Finnish ordinals: '(2e generatie)', '2de generatie', '2. Generation',
    # '2:a generationen', '2. sukupolvi' (live: 25 'AirPods Pro (2e generatie)' were 'different model (2e)')
    t = re.sub(r"\b(\d{1,2})(?:e|de|ste|:a|:e|\.)?\s*-?\s*(?:generatie|generation\w*|generacj\w*|gen\b\.?|"
               r"sukupolv\w*|génération)", r" gen\1 ", t)
    # a tier word glued to its generation: 'AirPods pro2' is the AirPods Pro 2
    t = re.sub(r"\b(pro|max|plus|mini|ultra|lite)(\d{1,2})\b", r"\1 \2", t)
    # RAM / storage pairs: 'M2 8/256' is 8 GB / 256 GB, not an 'M2 VIII'
    t = re.sub(r"\b(\d{1,2})\s*/\s*(32|64|128|256|512|1024|1000|2000)\b", r" \1gb \2gb ", t)
    # Apple silicon: 'M2-chip' / 'M2 chip' / 'M2-siru' is the M2
    t = re.sub(r"\b(m[1-5])\s*-?\s*(?:chip|siru|prozessor|processor)\b", r"\1", t)
    t = re.sub(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth)\s*-?\s*gen(?:eration)?\b",
               lambda m: f" gen{_ORDINAL_WORDS[m.group(1)]} ", t)
    t = re.sub(r"\bgen(?:eration)?\.?\s*(\d{1,2})\b(?!\s*(?:gb|tb|mm))", r" gen\1 ", t)   # 'Gen 2' / 'Generation 3'
    t = re.sub(r"\b(\d{1,2})\s*-?\s*gen(?:eration)?\b", r" gen\1 ", t)                 # '2-gen' / '3 generation'
    # Apple part numbers ('MQKU3H/A', 'MLY33KS/A') are no model names; the screen size after 'MacBook Air' is no
    # model number either ('MacBook Air 13 (2022)'); an Air of 2022 / 2023 with no chip named is the M2
    t = re.sub(r"\bm[a-z0-9]{4}[a-z]{0,2}/a\b", " ", t)
    t = re.sub(r"\b(\d{2,4})\s+(gb|tb)\b", r"\1\2", t)          # '256 GB' is a size, never 'macbook256
    t = re.sub(r"\b(macbook\s+(?:air|pro))\s+(1[1-6])\b(?![.,]\d)", r"\1 \2in ", t)
    if re.search(r"\bmacbook\s+air\b", t) and re.search(r"\b202[23]\b", t) and not re.search(r"\bm[1-5]\b", t):
        t += " m2"
    # Norwegian / Swedish 'lite brukt' / 'lite använd' = lightly used, never the 'Lite' version
    t = re.sub(r"\blite\s+(brukt|brugt|begagnad|anvand|anvant|slitt|used)\b", r"\1", t)
    # Dyson 'V15s' / 'V12s' (Submarine: the same vacuum with a wet head) is the V15 / V12, not another model
    t = re.sub(r"\b(v1[0-5])s\b", r"\1 submarine", t)
    # 'Sony α 7 III', 'Sony Alpha 7 III' are the a7 III (live: two lens kits were 'does not match')
    t = re.sub(r"(?:α|\balpha)\s?-?\s?(\d{1,4}[a-z]{0,2})\b", r"a\1", t)
    for pat, rep in CODE_ALIASES:
        t = pat.sub(rep, t)
    # "mark iii" / "mk3" / "mkiii" / "mark 3" / "m3 " after a model -> generation number token
    t = re.sub(r"\b(?:mark|mk)\.?\s*(i{1,3}|iv|vi{0,3}|ix|x|\d{1,2})\b", lambda m: " gen" + str(ROMAN.get(m.group(1), m.group(1))), t)
    t = re.sub(r"\b([a-z]{1,4}\d{1,4}[a-z]{0,2})\s*m(\d)\b", r"\1 gen\2", t)         # "a7 m3" / "a7m3"
    # engine sizes / versions are units, never a generation glued to the model: 'Volvo V70 2.0 D4' is no 'v70-2'
    t = re.sub(r"(?<![\d.,])(\d)[.,](\d)(?![\d.,])([a-z]{0,4})\b", r" \1\2l \3 ", t)
    t = re.sub(r"[^\w\s+/-]", " ", t)
    return t


_ROMAN_SUFFIX = re.compile(r"^([a-z]{1,5}\d{1,4}[a-z]{0,2}?)(viii|vii|vi|iv|iii|ii|v|ix)$")
_MODEL_TOKEN = re.compile(r"^(?=.*\d)(?=.*[a-z])[a-z0-9-]{2,12}$")
_UNIT_TOKEN = re.compile(
    r"^\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?mm$|^f\d|^\d+(?:gb|tb|gt|mb|mp|mm|hz|w|k|p|fps|mah|v|cm|kg|l|in|inch|x|mo|kk|"
    r"core|cores|gpu|cpu)$|^\d{4}$|^(?:4k|5g|4g|8k|2k)$"
    # counts and attributes, never a model: '3-vaihteinen' (3-speed), '21-gang', '3-istuttava' / '3-Sitzer' (seats),
    # '2kpl', '6XL', '1930s', '700c' / '29er' (wheels), '120x200', '7-8v' / '126-133' (kids' ages and sizes)
    r"|^\d+-?(?:vaihteinen|vaihteinem|vaihde|vaihdetta|vaihteet|vaiht|gang|gange|ganger|gear|gears|speed|speeds|"
    r"vxl|kpl|stk|st|pcs|pc|pack|pak|osainen|osaa|teilig|tlg|istuttava|istuttavaa|istuinen|paikkainen|hengen|"
    r"sitzer|sits|seater|seaters|zits|zitter|osobowa|seter|sitsig|personers|vuotias|v|y|j)$"
    r"|^\d*x{1,3}[sl]$|^\d+xs$|^\d{1,2}0s$|^\d{3}c$|^\d{2}er$|^\d{3}b$|^\d+x\d+(?:cm|mm)?$"
    r"|^\d+-\d+(?:v|y|j|cm|v\.)?$")
NOT_MODEL = {"y2k", "b2b", "b2c", "a2z", "c2c", "p2p", "3in1", "2in1"}     # style / business words with a digit


def tokenize(title: str) -> list[str]:
    """Normalised tokens with generations as standalone 'genN' tokens (a7iii -> a7 gen3)."""
    out: list[str] = []
    toks: list[str] = []
    for tok in re.split(r"[\s/]+|(?<=[a-z])\+(?=\w)", _fold(title)):     # 'Oled+Sd card': two words
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


# a prime lens sold with the body: 'Aparat Sony A7 III + Sony FE 35mm F/1.8', '..., obiektyw 35mm 1.4'
KIT_LENS = re.compile(r"(?:\+|&|\bwith\b|\bw/|\bmit\b|\bmed\b|\bmet\b|\bja\b|\bz\b|\bobiektyw\w*|\bobjektiiv\w*|"
                      r"\bobjektiv\w*|\bobjectief\w*|\blens\b|\blinssi\w*)\s*(?:[\w.]+\s+){0,3}\d{2,3}\s?mm\b", re.I)
_BUNDLE_SPLIT = re.compile(r"\s(?:\+|&|with|w/|incl\w*|bundle|plus\s+\d)\s", re.I)


_NOT_WORDS = {"ej", "ei", "not", "no", "non", "nicht", "kein", "keine", "ikke", "inte", "ingen", "uten", "ohne",
              "without", "geen", "niet", "nie", "bez"}


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
    early: list[str] = []       # variant words before any name ('OLED Nintendo Switch'): kept once a name follows
    for i, t in enumerate(toks):
        if t in FAMILIES:
            family = t
            seen_family = seen_family or t      # 'AirPods Pro 2 for iPhone' is AirPods
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
        if t in NOT_MODEL:
            words.add(t)
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
        if t in VARIANT_WORDS and i and toks[i - 1] in _NOT_WORDS:
            prev_model = False
            continue            # 'Nintendo Switch (EJ OLED)': not the OLED
        if t in VARIANT_WORDS and (models or family or seen_family):
            # 'Nintendo Switch spelkonsol OLED', 'Switch - Vit OLED': the tier may come after other words
            if t not in variants:
                variants.append(t)
            continue
        if t in VARIANT_WORDS and not models and not seen_family and t not in early:
            early.append(t)
        if t not in FLUFF and len(t) > 1 and not t.isdigit():
            words.add(t)
            family = None     # 'switch oled edition splatoon 3': only a number right after the name glues
        prev_model = False
    kit = any(p.search(title) for p in BUNDLE_PATTERNS[2:]) or bool(re.search(r"\bkit\b|\bw/\s*\d|\bwith\s+\d{2}-\d{2}", title, re.I)) \
        or bool(KIT_LENS.search(title))
    if early and (seen_family or models or found_brand):
        variants += [v for v in early if v not in variants]
        words -= set(early)
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


def _compat_list(low: str, asked: str) -> bool:
    """A title listing 3+ sibling model codes ('Dyson V7 V8 V10 V11 V12 V15'): a part that fits them all."""
    by: dict[str, set[str]] = {}
    for m in _COMPAT_CODE.finditer(low):
        by.setdefault(m.group(1), set()).add(m.group(2))
    for k, v in by.items():
        if re.search(rf"\b{re.escape(k)}\s?\d+\W+{re.escape(k)}\s?\d", asked):
            continue          # they asked for several models themselves
        if len(v) >= 3:
            return True
        # two siblings side by side, one of them asked: 'Dyson V11/V15 Accu', 'Floor Dok V11 V15'
        if len(v) == 2 and any(re.search(rf"\b{re.escape(k)}\s?{n}\b", asked) for n in v) and \
                re.search(rf"\b{re.escape(k)}\s?\d{{1,3}}\s*(?:/|,|&|\+|\s)\s*(?:{re.escape(k)})\s?\d{{1,3}}\b", low):
            return True
    return False


# one family, several generations in a row: 'iPhone 13/14/15', 'Galaxy S21 / S22', 'iPad 7/8/9': fits them all
_FAMILY_RANGE = re.compile(r"\b(?:iphone|ipad|galaxy\s+[asz]|pixel|airpods|macbook\s+(?:air|pro))\s?\d{1,2}"
                           r"(?:\s*(?:pro|max|plus|mini))?\s*(?:/|&)\s*(?:[a-z]\s?)?\d{1,2}\b"
                           r"(?!\s*(?:kk|gb|gt|tb|%|mo|months?|kuukau\w*|v\b|€|e\b|eur))")


@functools.lru_cache(maxsize=256)
def _kind_rx(words: frozenset[str]) -> re.Pattern[str] | None:
    single = sorted((w for w in words if " " not in w and len(w) >= 3), key=len, reverse=True)
    return re.compile(r"(?<!\w)\w*(?:" + "|".join(map(re.escape, single)) + r")") if single else None


def _item_pos(low: str, need: Need | None) -> int | None:
    """Where the item itself is first named: its brand / family / model, or for a generic need ('road bike',
    'kahvinkeitin') the first word naming the kind."""
    if need is None:
        return None
    at = _first_item_pos(low, need)
    if at is not None or need.kind != "product" or not is_generic(need):
        return at
    rx = _kind_rx(_need_words(need))
    m = rx.search(fold_text(low)) if rx is not None else None
    return m.start() if m else None


def _extra_after_item(low: str, start: int, w: str, need: Need | None) -> bool:
    """`w` at `start` is an extra in a listing of the item: it comes after the item's name with a separator or
    a spec between (EXTRA_A), or a spec for a case word (EXTRA_B)."""
    if w not in EXTRA_A and w not in EXTRA_B:
        return False
    at = _item_pos(low, need)
    if at is None or at >= start:
        return False
    between = low[at:start]
    if re.search(rf"\b{_FOR}\W*$", between):
        return False              # 'iPhone 13 ... for' never: the word is what it is for
    if w in EXTRA_A:
        return bool(_EXTRA_SEP.search(between) or _EXTRA_SPEC.search(between))
    return bool(_EXTRA_SPEC.search(between))


_SCREEN_PART = (r"scherm|beeldscherm|skjerm|skærm|skarm|skärm|display|screen|bildschirm|näyttö|naytto|näytön|"
                r"lcd|ekran|matryca|panel|toetsenbord|tastatur|keyboard|näppäimistö|moederbord|motherboard|logic board|"
                r"emolevy|behuizing|gehäuse|kuori|bottom case|top case|palmrest|scharnier|hinge")


def _kind_genitive_lead(low: str, need: Need) -> bool:
    """A generic need's kind word in the Finnish genitive leading the title, then a noun: a part of it."""
    if need.kind != "product" or not is_generic(need):
        return False
    rx = _kind_rx(_need_words(need))
    if rx is None:
        return False
    m = re.match(r"\W*(\w+)n\s+([^\W\d]{3,})", fold_text(low))
    return bool(m and rx.fullmatch(m.group(1)) and not re.match(r"(?:myynti|kanssa|mukana|ja|tai)$", m.group(2)))


def _into_the_item(low: str, need: Need) -> bool:
    """Finnish case endings that make a listing a thing FOR the asked item: illative / allative on its name
    ('Kallaxiin', 'Kallax-hyllyyn', 'iPhonelle', 'Switchille') or '<item> -hyllyn <noun>' (the shelf's doors)."""
    names = dict.fromkeys([*_item_tokens(need), *(w for w in tokenize(need.thing) if w.isalpha())])
    for t in names:
        if len(t) < 4 or t in BRANDS and t not in FAMILIES:
            continue
        if re.search(rf"(?<![\w-]){re.escape(t)}(?:-\w+?)?(?:iin|aan|ään|hin|yyn|een|ille|lle)\b", low):
            return True
        if re.search(rf"(?<![\w-]){re.escape(t)}\s*-?\s*hyllyn(?:\s+\w|\w)", low):
            return True
    return False


def _part_after_model(low: str, need: Need) -> bool:
    """A part word right after the asked model ('MacBook Air m2 scherm', 'Switch OLED näyttö'), with no 'with'
    word in between: the part sold alone. 'MacBook Air M2 with 13.6" display' stays the laptop."""
    models = [t for t in tokenize(need.thing) if _MODEL_TOKEN.match(t) and not _UNIT_TOKEN.match(t)]
    if not models:
        return False
    for m in models:
        if re.search(rf"(?<![\w-]){re.escape(m)}\s*[-:,]?\s*(?:{_SCREEN_PART})(?![\w])", low):
            return True
    return False


# a battery word in front of the whole item's noun is 'cordless': 'Akku Staubsauger', 'akku-imuri', 'battery vacuum'
_CORDLESS_ITEM = re.compile(
    r"\b(?:akku|accu|battery|batteri|batterie)\W{0,2}(?:\w+-)?(?:\w*staubsauger|\w*sauger|\w*stofzuiger|\w*støvsuger|"
    r"\w*dammsugare|\w*imuri|odkurzacz\w*|vacuum|vac|cleaner|\w*bohrschrauber|\w*schrauber|\w*porakone|drill|"
    r"\w*rasenm[aä]her|\w*ruohonleikkuri|\w*trimmer|\w*leikkuri|\w*s[aä]ge|\w*saha)\b", re.I)


def is_accessory(title: str, need: Need | None = None) -> bool:
    """True when the listing is a thing *for* the item rather than the item."""
    # Finnish compound tails on marketplace titles: "AirPods Pro 2 (USB-C) -latauskotelo" = the charging case
    low = re.sub(r"(?<=\s)-(?=\w)", " ", title.lower())
    asked = (need.thing.lower() + " " + " ".join(need.must_have)).lower() if need else ""
    # substring prefilters first (one C-level 'in' per word): the regex per word ran ~900k times for 2,000 rows
    if any(w in asked and re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", asked)
           for w in (*ACCESSORY_WORDS, *PART_WORDS)):
        return False   # they asked for the accessory itself ("battery for sony a7 iii")
    if _compat_list(low, asked) or (_FAMILY_RANGE.search(low) and not _FAMILY_RANGE.search(asked)):
        return True        # 'Tech21 Evo Sparkle MagSafe iPhone 13/14/15' (proshop): a case that fits three phones
    # the condition ('god stand') and repair notes ('akku ja näyttö vaihdettu') name no accessory for sale
    low = re.sub(r"\b(?:god|flot|pæn|paen|fin|fint|perfekt|super|ok|okay|nydelig|normal|brugbar|kanon|velholdt|"
                 r"fejlfri|pen|bra|ny|nyvaerdi|nyværdi|meget|rigtig|særdeles|saerdeles|helt|middel|rimelig|god brugt)\s+"
                 r"(?:stand|standen)\b", lambda m: " " * len(m.group(0)), low)
    low = _REPAIRED.sub(lambda m: " " * len(m.group(0)), low)
    for m in _ACC_TAIL.finditer(low):
        word = m.group(0).strip()
        if word in EXTRA_A and _extra_after_item(low, m.start(), word, need):
            continue           # 'Moccamaster kahvinkeitin, harmaa, lasikannu': the maker's own glass jug comes with it
        if m.group(1) not in asked and not re.search(r"(?:\bwith\b|\bmit\b|\bja\b|\binkl\w*|\+)[^|]*$",
                                                      low[:m.start()]):
            return True        # 'iPhone 13 -Puhelimenkuoret', 'Galaxy S21 Schutzhülle': a cover for the phone
    # a LEGO set with its set number is the set, whatever its name says ('42111 Dom's Dodge Charger', 'Komplett
    # m. manual'); loose parts still go by the parts red flag ('varaosia', 'Ersatzteile')
    lego_set = "lego" in asked and bool(re.search(r"(?<![\d.,])\d{4,6}(?![\d.,])", low))
    for w in (x for x in ACCESSORY_WORDS if x in low and (not lego_set or x in MERCH_WORDS)):
        if w in BATTERY_WORDS and _BATTERY_STATE.search(low):
            continue           # 'akku 93 %', 'aito akku', 'Akku 89%': the phone's battery health, not a battery
        if w in BATTERY_WORDS and _CORDLESS_ITEM.search(low):
            continue           # 'Akku Staubsauger DYSON V15': a cordless vacuum, not a battery for one
        if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low) and w not in asked:
            # "camera with battery and charger" is a bundle, not an accessory: the accessory word
            # must come before "for X" or lead the title, or appear without a main-item word
            # (its FIRST mention: a shop's 'Charging Station ... compact and efficient ... for charging' leads with it)
            wm = re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low)
            if wm and re.search(r"(?:\bwith\b|\bmit\b|\bincl\w*|\binkl\w*|\+|\band\b|\bw/|\bz\b|\bze\b|\bmed\b|\bmet\b"
                                r"|\bsu\b|\bja\b|\bund\b|\ben\b|\boch\b|\bog\b|\bi\b)[^|]*$", low[:wm.start()]):
                continue
            if wm and _extra_after_item(low, wm.start(), w, need):
                continue          # 'Sony A7 III Body | SmallRig Cage', 'iPhone 13 128GB ... pudełko'
            return True
    item_at = _first_item_pos(low, need) if need else None
    if need is not None and _kind_genitive_lead(low, need):
        return True               # 'Polkupyörän ohjaustangot', 'Sohvan päällinen': the bike's handlebars
    if need is not None and _into_the_item(low, need):
        return True               # 'Ristikkohylly Kallaxiin', 'Kallax -hyllyn kaappeja', 'Switchille': made for it
    if need is not None and _part_after_model(low, need):
        return True               # 'MacBook Air m2 scherm space grey' / 'MacBook Air M2 Display': the screen alone
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
    ("part", re.compile(r"\b(?:for parts|parts only|spares|varaos(?!akoodi)\w*|osiksi|ersatzteil\w*|onderdelen|reservdel\w*|"
                        r"reservedel\w*|deler|na czesci|czesci zamienne)\b"), "sold as parts"),
    ("wanted", re.compile(r"\b(?:ostetaan|ostan|etsitaan|etsin|wanted|wtb|looking for|gezocht|gesucht|sucht|suche|"
                          r"kopes|kjopes|kobes|kupie|szukam|cherche|busco|cerco|soker|sokes|soeker|sokes|onskas|onskes)\b"),
     "a wanted ad, not an offer"),
    # for rent, not for sale (live, baby stroller: 'VUOKRATAAN Ora Aina matkarattaat')
    ("rental", re.compile(r"\b(?:vuokrataan|vuokralle|vuokraan|vuokrattavana|uthyres|hyres ut|zu vermieten|vermiete|"
                          r"te huur|verhuur|for rent|for hire|udlejes|leies ut|do wynajecia|wynajme)\b"),
     "for rent, not for sale"),
    ("broken", re.compile(r"\b(?:rikki|rikkinai\w*|hajonn\w*|hajalla|viallinen|vialli\w*|vika|vikaa|vikoja|"
                          r"toimimat\w*|ei toimi|ei lataa|hairio\w*|broken|faulty|defective|defect|not working|"
                          r"doesn ?t work|does not work|dont work|cracked|water damage\w*|defekt\w*|kaputt|"
                          r"funktioniert nicht|bastler\w*|kapot|werkt niet|trasig|fungerar (?:inte|ej)|ej fungerande|"
                          r"virker ikke|fungerer ikke|i stykker|odelagt|uszkodz\w*|zepsut\w*|nie dziala\w*|"
                          # 'knust skjerm' (Norwegian: broken screen), 'Tastaturdefekt', 'Display gesprungen'
                          r"knust\w*|\w+defekt\w*|waterschade|wasserschaden|vesivahin\w*|vattenskad\w*|vandskade\w*|"
                          r"vannskade\w*|water damaged?|zalan\w*|gesprungen|gebrochen|zerbrochen|sprung im|rikkoutun\w*|"
                          r"haljennut|halkeama\w*|säröi\w*|saroi\w*|gebarsten|barst|gebroken|kapotte|"
                          r"do naprawy|wadliw\w*|sugedes|neveikia|"
                          # 'korjattavaksi' (to be repaired), 'ilman akkua' (without its battery), 'Pyörät eivät
                          # kunnolla käänny' (the wheels don't turn): not a working one (live, robotti-imuri)
                          r"korjattava\w*|kunnostettava\w*|korjausta vaativa|ilman akkua|ilman laturia|ilman akkuja|"
                          r"ei kaanny|eivat (?:\w+ ){0,2}kaanny|utan batteri\w*|ohne akku|zonder accu|without (?:the )?battery|"
                          r"no battery|reparaturbedurftig|zum reparieren|for repair|needs repair)\b"), "broken or faulty"),
    ("fake", re.compile(r"(?:\b(?:kopio\w*|replica\w*|replika\w*|fake|clone|klon|klony|high quality copy|hq copy|"
                        r"super copy|master copy|aaa quality|nachbau|namaak|kopia(?! (?:paragon|faktur|rachun|dowod))|podrobk\w*|ei alkuperainen|"
                        r"not original|non original|nie oryginaln\w*|nieoryginaln\w*|niet origineel|kein original|"
                        r"imitat\w*|ei aito|ei aidot)\b|(?<![\d.,:])1 ?: ?1(?![\d.,:]))"), "probably a copy, not the original"),
    ("locked", re.compile(r"\b(?:lukossa|lukittu|icloud\W+(?:\w+\W+)?(?:lock\w*|lukko\w*|lukossa|gesperrt|"
                          r"zablokowan\w*|last|vergrendeld)|activation lock|aktivierungssperre|gesperrt|"
                          r"zablokowan\w*|vergrendeld|apple id\W+(?:\w+\W+)?(?:lock\w*|lukossa|gesperrt))\b"),
     "locked to someone else's account"),
    ("swap", re.compile(r"\b(?:vaihto(?:kauppa\w*)?|vaihdetaan|vaihdossa|vaihtaisin|swap\w*|trade for|tausch\w*|"
                        r"ruil\w*|bytes|byte mot|byts|byts mot|bytas|byttes|bytte mot|zamiana|zamienie|zamienię|zamienie na)\b"), "a swap, not a sale"),
]
_PAIR = re.compile(r"\b(?:pair|pari|paar|par|para|set|sett|zestaw|komplet\w*)\b")
_TITLE_HYPHEN_CASE = re.compile(r"\b[\w]+-(?:case|oplaadcase|ladecase|kotelo|latauskotelo|etui|ladeetui|hulle)\b")
_WITH_BEFORE = re.compile(r"\b(?:with|met|mit|med|kanssa|incl\w*|inkl\w*|z|ze|su|and|en|und|och|og|ja)\b[^,|]*$|\+[^,|]*$")
_ROW_META = re.compile(r",\s*(?:tuotemerkki|malli|kunto|koko|brand|condition|marke|zustand|merk|staat|stan)\s*:")
_TITLE_BOX_END = re.compile(rf"\b(?:{_BOX})\W*$")
_TITLE_BOX_LEAD = re.compile(rf"^\W*(?:\w+\W+)?(?:{_BOX})\b(?!\W*:)")
_IN_BOX = re.compile(r"\b(?:in|i|w|im|met|with|mit|med|kanssa|z|ze|su|ar|s|se|sa|con|avec|com|kun|incl\w*|inkl\w*|og|ja|and|und|en|plus|new|nieuw|uusi|"
                     r"neu|ny|nowe|sealed|geseald)\W+(?:\w+\W+)?$|\+\W*$")
_SINGLE_SIDE_L = re.compile(rf"\b(?:{_SIDE_L})\b")
_SINGLE_SIDE_R = re.compile(rf"\b(?:{_SIDE_R})\b")
_EAR_RX = re.compile(rf"\b(?:{_EAR})\b")
# marketplaces put the seller's brand field in the row text: 'Tuotemerkki: Shein', 'Marke: TWS', 'Merk: Burga'
_BRAND_FIELD = re.compile(r"\b(?:tuotemerkki|brand|marke|merk|marka|marque|marca|varumarke|maerke)\s*:\s*([^,|;]{1,40})")
# a sub-brand in a marketplace's brand field is the maker ('Tuotemerkki: PlayStation' on a PS5 is Sony)
SUB_BRANDS = {"playstation": "sony", "sony playstation": "sony", "sony interactive entertainment": "sony",
              "xbox": "microsoft", "galaxy": "samsung", "samsung galaxy": "samsung", "nintendo switch": "nintendo",
              "switch": "nintendo", "iphone": "apple", "ipad": "apple", "macbook": "apple", "airpods": "apple",
              "beats": "apple", "pixel": "google", "google pixel": "google", "alpha": "sony", "lumix": "panasonic",
              "redmi": "xiaomi", "poco": "xiaomi", "honor": "huawei", "eos": "canon", "kindle": "amazon",
              "lego technic": "lego", "duplo": "lego"}
NO_NAME_BRANDS = {"tws", "ingen", "kita", "other", "others", "muu", "andere", "anders", "inny", "be prekinio zenklo",
                  "no brand", "nobrand", "unbranded", "noname", "no name", "generic", "bluetooth", "idk", "brak",
                  "ei merkkia", "ohne marke", "geen merk", "utan marke"}
RED_REJECT = ("part", "wanted", "rental")       # not the item / not an offer: resolve drops them
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
        if kind in ("wanted", "swap", "rental") and not title:
            continue      # site chrome says 'Ostetaan' / 'Gesucht' (a category); 'Tausch möglich' on a sale is fine
        for m in rx.finditer(folded):
            if kind not in ("wanted", "part", "rental") and _negated(folded, m.start(), m.end()):
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
        if m is not None and m.re is _TITLE_BOX_END:
            before = head[:m.start()]
            # 'Sony A7 III ... OVP' (German: with its original box), '... stan bardzo dobry, pudełko', '128GB ...
            # Pudełko': the box comes WITH the item; only an 'only / empty' word (the _RED rule above) makes it alone
            if (re.search(r"ovp|verpackung", m.group(0)) or _EXTRA_SPEC.search(before)
                    or re.search(r"(?:[,|+&;]|\s[-–—])\W*$", before)):
                m = None
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
            if not b or need_brand in b or b in need_brand or SUB_BRANDS.get(b) == need_brand:
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
    r"/(?:s|sc|sch|search|searchpage(?:\.jsp)?|haku|suche|b|kp|l|c|list|lists|category|categories|kategorie|"
    r"kategoria|collections|browse|catalogsearch|recommerce/forsale/search)(?:/|$|\?)"
    r"|/s-[^/]+/k0\b|/k0$|[?&](?:k|q|_nkw|query|search|keyword|keywords|searchterm)="
    r"|/(?:all|alle|kaikki)/?$", re.I)
# a used-car site's make / model page: '/fi/kaytetyt-autot/Volvo/V70' lists hundreds of cars (live: 'New from €3,932')
CAR_LIST_PATH = re.compile(r"/(?:kaytetyt-autot|vaihtoautot|used-cars|gebrauchtwagen|gebrauchtwagen-\w+|occasions?|"
                           r"begagnade-bilar|brugte-biler|bruktbil|tweedehands-auto\w*)(?:/[A-Za-z][\w-]*){0,4}/?$"
                           # mobile.de '/en/car/volvo/v70': a make / model page, not one car (no listing id)
                           r"|/(?:car|cars)/[a-z][a-z-]*(?:/[a-z0-9][a-z0-9-]{0,20})?/?$", re.I)
# weekly store flyers on aggregator sites: a page of a printed ad, nothing to buy there (live, kahvinkeitin: the
# pick was 'KAHVINKEITIN VAALEANPUNAINEN' €14.99 on promotheus.fi/halpa-halli-tarjoukset/tarjouslehti-79434-0)
FLYER_URL = re.compile(r"tarjouslehti|tarjouslehde\w*|mainoslehti|/flyers?/|/prospekte?/|reklamblad|kundeavis|"
                       r"tilbudsavis|weekly-?ads?\b|/folders?/\d|//(?:www\.)?(?:promotheus|minuntarjouslehteni|kimbino|"
                       r"tiendeo|ofertolino|marktjagd|kaufda|reklambladet|tjek|etilbudsavis)\.", re.I)
NOT_OFFER_TITLE = re.compile(
    r"\bab\s*€\s*\d|\bpreisvergleich\b|\bprice comparison\b|\bhintavertailu\b|\bprice history\b"
    r"|\bis on sale\b|\bon sale for\b|\bprice drops?\b|\bdeal alert\b"
    # a car / spec database page: 'Volvo V70 Price (EUR) — All Variants | Cars-Data.com'
    r"|\ball\s+(?:variants|versions|trims)\b|\bspecs?\s+(?:and|&)\s+prices?\b|\bprices?\s+(?:and|&)\s+specs?\b"
    # a shop's category archive ('Sofas Archives - Global Discount Furniture', live: 'new from €1,100' for sofa)
    r"|\barchives?\b\s*(?:[-|–—]|$)", re.I)
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
    r"|\s(?:vaihtoautot|käytetyt\s+autot|kaytetyt\s+autot|used\s+cars|gebrauchtwagen|occasions|begagnade\s+bilar|"
    r"brugte\s+biler|bruktbiler)\s*$"
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
KM_EVIDENCE = re.compile(r"\b\d[\d .]*\s?(?:km|tkm|mi|miles)\b", re.I)
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


_MAKE_ALIAS = {"volkswagen": "vw", "mercedes-benz": "mercedes", "škoda": "skoda", "citroën": "citroen",
               "range rover": "land rover"}


def _makes(text: str) -> set[str]:
    try:
        from agora.need import CAR_MAKES
    except ImportError:
        return set()
    return {_MAKE_ALIAS.get(m.lower(), m.lower()) for m in CAR_MAKES.findall(text or "")}


def _is_vehicle_need(need: Need) -> bool:
    try:
        from agora.need import vehicle_need
    except ImportError:
        return False
    return need.kind == "product" and vehicle_need(need.thing or "")


def other_make(need: Need, offer: Offer) -> str | None:
    """A car make asked ('volvo v70') and the listing names only another one ('Saab 96'): another car, whatever
    page or category it came from (live: nettiauto's search returned every cheap car as the V70)."""
    if not _is_vehicle_need(need):
        return None
    asked = _makes(need.thing)
    if not asked:
        return None
    named = _makes(offer.title or "")
    if named and not named & asked:
        return sorted(named)[0]
    return None


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
    # under the floor only a mileage says it is a car: 'Volvo V70 Mk2 Tdi maf' (€30, a sensor) and
    # '2000 volvo v70 mk2 t5 manuaali startti' (a starter motor) name an engine, not a car for sale
    evidence = bool(CAR_MAKES.search(title) and KM_EVIDENCE.search(title))
    p = offer.price_eur
    if p is not None and p < VEHICLE_FLOOR_EUR and not evidence:
        return f"€{p:,.0f} is too little for a car and the listing names no make with its mileage: a part or a toy"
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
    if listy or LIST_URL.search(parts.path + ("?" + parts.query if parts.query else "")) or CAR_LIST_PATH.search(parts.path):
        return "search or list page, not one listing"
    if FLYER_URL.search(url):
        return "a store flyer page, not a buyable listing"
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


# product lines that never stand for each other ('iPad Air M2' is no 'MacBook Air M2')
DISTINCT_FAMILIES = {"iphone", "ipad", "macbook", "airpods", "kindle"}


def _family_clash(need_sig: Signature, off_sig: Signature) -> bool:
    a, b = need_sig.family, off_sig.family
    return bool(a and b and a != b and a in DISTINCT_FAMILIES and b in DISTINCT_FAMILIES)


_APPLE_SILICON = re.compile(r"^m[1-5]$")
_OLD_YEAR = re.compile(r"\b20(?:0\d|1\d)\b")


def _older_than_asked(need_sig: Signature, title: str) -> bool:
    """'MacBook Air 2018' for 'macbook air m2': an Apple-silicon model asked, a pre-2020 (Intel) year offered."""
    return any(_APPLE_SILICON.match(m) for m in need_sig.models) and bool(_OLD_YEAR.search(title or "")) \
        and not re.search(r"\bm[1-5]\b", title or "", re.I)


_ROMAN_TAIL = re.compile(r"^([a-z]{0,2})(\d{1,4})(iv|i{1,3})$")


def _shorthand(nm: str, om: str) -> bool:
    """Sellers' shorthand for a generation: 'A73' / 'a7m3' / '7iii' for the a7 III (asked 'a7-3')."""
    if "-" not in nm or "-" in om:
        return False
    base, gen = nm.split("-", 1)
    if not gen.isdigit():
        return False
    if om == base + gen and base[-1:].isdigit():
        return True                      # 'a73'
    m = _ROMAN_TAIL.match(om)
    if m and ROMAN.get(m.group(3)) == int(gen):
        letters = re.match(r"[a-z]*", base).group(0)     # type: ignore[union-attr]
        return m.group(2) == base[len(letters):] and (not m.group(1) or m.group(1) == letters)
    return False


def _model_match(need_sig: Signature, off_sig: Signature) -> float:
    """1 = all asked models present, ~0.1 = a *different* generation/model, 0.45 = cannot tell."""
    if _family_clash(need_sig, off_sig):
        return 0.1             # 'iPad Air M2' for 'macbook air m2': same chip, another product
    if not need_sig.models:
        # 'nintendo switch oled' asked: 'Nintendo Switch 2' is another console, 'Switch 2019' lacks the OLED
        score = 1.0
        nv, ov = _tiers(need_sig.variants), _tiers(off_sig.variants)
        fam = need_sig.family
        if fam and any(re.fullmatch(re.escape(fam) + r"\d+", m) for m in off_sig.models) and (not nv or nv - ov):
            return 0.1
        if nv - ov and (off_sig.family == fam or off_sig.models):
            score *= 0.4
        return score
    score = 1.0
    for nm in need_sig.models:
        base = nm.split("-")[0]
        if nm in off_sig.models or any(_shorthand(nm, om) for om in off_sig.models):
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
    nv, ov = _tiers(need_sig.variants), _tiers(off_sig.variants)
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
    for also in KIND_ALSO.get(noun or "", ()):
        words |= _noun_words(also)
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


_WITH_SPLIT = re.compile(r"\s(?:\+|&|ja|and|und|og|och|en|with|mit|med|met|incl\w*|inkl\w*|sis\.|plus)\s", re.I)


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
    # what comes with it is no other kind: 'Cannondale Caad 8 2014 ja 42,5 kengät' is a bike (+ shoes)
    head = _WITH_SPLIT.split(offer.title or "", maxsplit=1)[0]
    if len(head.split()) >= 2:
        toks = set(tokenize(head))
    for other, words in sorted(_concepts(), key=lambda c: -len(c[0])):     # 'coffee table' before 'table'
        if not _compatible(other, noun) and _hits(words, toks):
            return other
    return None


@functools.lru_cache(maxsize=64)
def _narrow_broad(noun: str) -> tuple[frozenset[str], frozenset[str]]:
    from agora import marketplaces as M
    head = noun.split()[-1]
    narrow = {w for w in M.translations(noun) if len(w) >= 4}
    if " " in noun:
        narrow |= SYNONYMS.get(noun.split()[0], set())     # 'kilpapyörä', 'racer' name a road bike too
    return (_fold_words(narrow),
            _fold_words(SYNONYMS.get(head, set()) | set(M.translations(head))))


def _only_broad(need: Need, offer: Offer, toks: set[str]) -> bool:
    """A narrower kind was asked ('road bike'), the title names only the broad one ('Polkupyörä', 'pyörä') and no
    maker of the narrower kind: tori's road-bike page is its whole bicycle category searched for the word."""
    noun = _kind_noun(need)
    if not noun or " " not in noun or noun.split()[0] in ("baby", "kids", "women", "men") or noun in KIND_ALSO \
            or noun not in SUBKINDS:
        return False              # 'Pöytä ja tuolit' is a kitchen table (sellers say the broad word for it)
    narrow, broad = _narrow_broad(noun)
    if not narrow or _hits(narrow, frozenset(toks)):
        return False
    if not broad or not _hits(broad, frozenset(toks)):
        return False
    maker = KIND_MAKERS.get(noun)
    return not (maker is not None and maker.search(offer.title or ""))


def _narrow_unnamed(need: Need, offer: Offer, toks: set[str]) -> bool:
    """A narrower kind was asked ('road bike') and the title names neither it nor a maker of it: on an exact
    category page that is still any bike, a part or a bare 'Myydään'."""
    noun = _kind_noun(need)
    if not noun or " " not in noun or noun.split()[0] in ("baby", "kids", "women", "men") or noun in KIND_ALSO \
            or noun not in SUBKINDS:
        return False
    narrow, _ = _narrow_broad(noun)
    if not narrow or _hits(narrow, frozenset(toks)):
        return False
    maker = KIND_MAKERS.get(noun)
    return not (maker is not None and maker.search(offer.title or ""))


def _marketplace_row(offer: Offer) -> bool:
    """A private seller's listing on a marketplace (whose search found it for this kind of thing)."""
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    if raw.get("site") or raw.get("from_list_page") or raw.get("category_page"):
        return True
    try:
        from agora import discover
        return bool(discover.is_marketplace(offer.source or ""))
    except Exception:
        return False


def _generic_coverage(need: Need, offer: Offer, toks: set[str]) -> float | None:
    """Coverage of a generic need (None = not generic: the word rule decides)."""
    if not is_generic(need):
        return None
    if _hits(_need_words(need), toks):
        if _only_broad(need, offer, toks):
            return 0.3                  # 'Polkupyörä', 'Miesten Helkama pyörä' for a road bike: any bike
        return 1.0
    if other_kind(need, offer):
        return 0.0                      # 'vuodetuoli' filed under tori's 'Sohvat ja nojatuolit' is still a chair
    maker = KIND_MAKERS.get(_kind_noun(need) or "")
    if maker is not None and maker.search(offer.title or "") and _marketplace_row(offer):
        return 0.85                     # 'OnePlus Nord 5 256GB' on tori is a phone without saying so
    cp = offer.raw.get("category_page") if isinstance(offer.raw, dict) else None
    if cp and cp.get("exact"):
        if _narrow_unnamed(need, offer, toks):
            return 0.3                  # tori's 'Maantiepyörät' holds city bikes, pedals and 'Myydään' too
        return 1.0                      # the seller filed it under exactly this kind (tori 'Matkapuhelimet')
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    if raw.get("site") and raw.get("from_list_page") and str(raw.get("site")).split(".")[0] not in FUZZY_SEARCH:
        return 0.7                      # the marketplace's own search (or broader category) for this kind
    return None


# marketplaces whose search matches loosely (vinted: a 'puhelin' search returns handbags and lanyards): a row from
# their search is no evidence of the kind; its title must name the kind or a maker of it
FUZZY_SEARCH = frozenset({"vinted"})


# ---------------------------------------------------------------- the wrong kind of thing for a product need
# Judged per listing from its own title, whatever the site: a toy or a magazine is never the coffee maker, a game
# never the console, a dog coat or a kids' jacket never 'winter jacket women', a 3-speed city bike never a road
# bike, a VoIP desk phone never a smartphone.
TOY_RX = re.compile(r"\b(?:toys?|lelu\w*|\w+lelu(?:t|ja|a)?|leikki(?!kuri)\w*|spielzeug\w*|kinderspiel\w*|kinderset|leksak\w*|speelgoed\w*|"
                    r"zabawk\w*|legetøj|legetoj|leketøy|leketoy|jouet\w*|giocattol\w*|juguete\w*|playmobil|lego|duplo|"
                    r"barbie|nuken\w*|nukke\w*|nukkej\w*|puppen\w*|dukke\w*|docka|dockvagn|lalk\w*|poppenwagen|"
                    r"pienoismalli\w*|miniatyyri\w*|miniature|modellauto|1\s?:\s?\d{2,3})\b", re.I)
MEDIA_RX = re.compile(r"\b(?:lehti|lehtiä|lehdet|magazine|zeitschrift|tidning|tijdschrift|czasopism\w*|kirja|kirjat|book|"
                      r"books|buch|bücher|bok|boek|książka|ksiazka|käyttöohje|kayttoohje|manual|anleitung|bedienungsanleitung|"
                      r"juliste|poster|tarra|tarrat|sticker|aufkleber|magneet(?:ti|it|teja|tia)|magnet|magnets|magneten|postikortti\w*|"
                      r"postcard|postkarte|dvd|blu-?ray|vinyyli|lp-levy|cd-levy|"
                      # loose building instructions (live, lego technic: 'LEGO Technic ohjekirja setille 8259' €4)
                      r"ohjekirja\w*|rakennusohje\w*|bauanleitung\w*|building\s+instructions|bygganvisning\w*|"
                      r"byggeinstruktion\w*|bouwinstructie\w*)\b(?!\W+(?:mukana|mukaan|included|inkl\w*|incl\w*|dabei|"
                      r"inklusive|medfølger|medfoljer|ingår|ingar|tallella|jäljellä))", re.I)
CONSOLE_NEED = re.compile(r"\b(?:ps[345]|playstation\s?[345]?|xbox(?:\s+(?:series\s+[xs]|one))?|nintendo\s+switch|switch\s+"
                          r"(?:oled|lite|2)|switch|steam\s+deck|game\s?boy|wii\s?u?|ds\b|3ds)\b", re.I)
_PLATFORM = r"(?:ps\s?[345]|playstation\s?[345]|xbox(?:\s+(?:series\s+[xs]|one|360))?|(?:nintendo\s+)?switch(?:\s+(?:oled|2))?)"
_GAME = (r"(?:-?pel(?:i|it|eja|ejä|ien)(?!konsol)|-?peli(?!konsol)\w*|spil(?:let)?|spiele?|spel(?:et)?|games?|gra|gry|jeu|jeux|juego|gioco|"
         r"videogame\w*|videospiel\w*|tv-?spel|steelbook|dlc)")
_CONSOLE_EVIDENCE = re.compile(r"\b(?:konsoli\w*|console\w*|konsole\w*|konsol\w*|konsola|konsolen|spillekonsol|"
                               r"pelikonsoli|825\s?gb|1\s?tb|2\s?tb|500\s?gb|disc\s+edition|digital\s+edition|"
                               r"levyasema\w*|blu-?ray\s+drive|järjestelmä)\b"
                               # 'RIG 300 Pro HS Gaming Kuulokkeet' is a headset: 'pro' / 'slim' / 'digital' prove a
                               # console only right after its name ('PS5 Pro', 'Switch Lite', 'PS5 Slim Digital')
                               r"|(?:ps\s?[345]|playstation\s?[345]|xbox(?:\s+(?:series\s+[xs]|one))?|switch|oled|slim)"
                               r"\s*-?\s*(?:slim|pro|oled|lite|digital|disc|bundle|paketti)\b", re.I)
_GAME_RX = re.compile(
    rf"\(\s*{_PLATFORM}\s*\)|\[\s*{_PLATFORM}\s*\]|\b{_PLATFORM}\s*{_GAME}\b|\b{_GAME}\s*(?:\w+\s+){{0,2}}"
    rf"(?:for|til|till|für|voor|do|na|pour|per|para|ps)?\s*{_PLATFORM}\b|\b(?:til|for|för|für|voor|do|na|pour|"
    rf"yhteensopiva|compatible|kompatibel)\s+(?:with\s+|mit\s+)?{_PLATFORM}\b", re.I)

# headsets, controllers, stands sold for a console (live, ps5: 'Sony 3D Pulse PS5 kuulokkeet', a Turtle Beach
# headset at proshop set 'New from €35')
_CONSOLE_ADDON = re.compile(
    r"\b(?:\w*kuulok\w*|headsets?|headphones?|kopfhörer\w*|hörlurar|høretelefoner|hodetelefoner|koptelefoon\w*|"
    r"słuchawk\w*|pelikuulok\w*|gaming\s+headset|mikrofoni\w*|microphone|ohjain\w*|controller\w*|gamepad|"
    r"peliohjain\w*|kontroller\w*|handkontroll\w*|dualsense|dualshock|joy-?cons?|latausasema\w*|ladestation|"
    r"charging\s+station|lataustelakka\w*|jäähdytys\w*|cooling\s+(?:stand|fan)|kühlständer|cover\s?plates?|"
    r"faceplates?|kuoret|skins?|aufkleber|tarrat|vr2?\b|psvr2?|portal\b|remote\s+player|kamera|camera|"
    r"media\s+remote|kaukosäädin|fernbedienung|ratti\w*|lenkrad|steering\s+wheel|polkimet|pedals|"
    r"\w*laukku|\w*tasche|carry(?:ing)?\s+case|säilytyslaukku|pelilaukku)\b", re.I)
# words that may stand before the console's name in a listing of the console itself
_CONSOLE_PRE_OK = {"sony", "playstation", "microsoft", "nintendo", "myydaan", "myydään", "myyn", "uusi", "uudenveroinen",
                   "kaytetty", "käytetty", "used", "new", "brand", "original", "alkuperainen", "alkuperäinen", "verkaufe",
                   "neu", "neue", "neuwertig", "gebraucht", "saelges", "sælges", "selges", "saljes", "säljes",
                   "sprzedam", "nowa", "nowy", "nieuw", "nieuwe", "koop", "te", "ny", "nyt", "brugt", "begagnad",
                   "sealed", "avaamaton", "mint", "uåpnet", "uapnet", "ubrugt", "oanvänd", "oanvand", "unused",
                   "hyvä", "hyva", "kunto", "toimiva", "edullinen", "halpa", "the", "a", "my", "la", "le", "konsoli",
                   "console", "konsole", "spillekonsol", "pelikonsoli", "konsola", "originale", "originele", "ps", "xbox",
                   "switch", "series", "one", "x", "s", "oled", "slim", "pro", "lite", "edition", "digital", "disc"}
_PLATFORM_RX = re.compile(rf"\b{_PLATFORM}\b", re.I)


def _named_before_platform(title: str) -> str | None:
    """'Battlefield 6 PS5', 'Horizon Forbidden West Complete Edition PS5 (Käytetty)': a name before the platform
    and nothing after it but a condition note is a game. 'Sony PS5', 'Myydään PS5' are the console."""
    m = _PLATFORM_RX.search(title)
    if m is None:
        return None
    pre = [w for w in re.findall(r"[^\W_]+", title[:m.start()].lower())]
    post = re.findall(r"[^\W_]+", title[m.end():].lower())
    if len(post) > 3:
        return None
    named = [w for w in pre if w not in _CONSOLE_PRE_OK and not re.fullmatch(r"\d{1,4}(?:gb|tb)?", w)]
    return title[:m.start()].strip(" -–:|,")[:40] if named else None


# a narrower kind asked: other kinds that share its head word. strong = always another kind (a 3-speed hub bike is
# no road bike even when the seller says 'maantiepyörä'); soft = only when the title names nothing of the asked kind
SUBKINDS: dict[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]] = {
    "road bike": (re.compile(r"\b[1-7]\s*-?\s*(?:vaihteinen|vaihteisen|vaihde\w*|v|gang\w*|speeds?|växl\w*|gears?|"
                             r"vitesses?)\b|napavaiht\w*|\bnexus\b|\bsturmey|kaupunkipy\w*|\bcity\s?(?:bike|rad)\b|"
                             r"cityrad|hollandrad|stadsfiets|stadscykel|omafiets|kids?\s+bike|lasten\s?py\w*|"
                             # 'Myydään lasten polkupyörä', '24" Nopsa tyttöjenpyörä', 'Tunturi retki 5 Naisten
                             # polkupyörä', 'Carrera 24 pyörä' (live, Road Bikes tree hunt: kept in the top 10)
                             r"(?:lasten|tyttöjen|tyttojen|poikien|naisten|miesten|tyttö|poika|junior)\s*(?:polku)?pyör\w*|"
                             r"(?:tyttöjen|tyttojen|poikien|lasten)py\w*|\b(?:12|14|16|18|20|24)\s*(?:\"|”|''|tuuma\w*|"
                             r"inch\w*|zoll)|\b(?:12|14|16|18|20|24)\s+(?:polku)?pyör\w*|retkipy\w*|\bretki\s+\d|"
                             r"kinderfahrrad|kinderrad|potkupy\w*|tasapainopy\w*|laufrad|kuntopy\w*|exercise\s+bike|"
                             r"heimtrainer|spinning\w*", re.I),
                  re.compile(r"maastopy\w*|mountain\s?bike|\bmtb\b|\bbmx\b|fat\s?bike|sähköpy\w*|e-?bike|pedelec|"
                             r"cargo\s?bike|laatikkopy\w*|tandem|damenrad|herrenrad|naisten\s+pyörä", re.I)),
    "phone": (re.compile(r"\bip[- ]?puhelin\w*|\bvoip\b|\bsip\b|\bdect\b|pöytäpuhelin\w*|poytapuhelin\w*|"
                         r"poeytaepuhelin\w*|desk\s?phone|tischtelefon|festnetz\w*|lankapuhelin\w*|"
                         r"konferenssipuhelin\w*|conference\s+phone|puhelinkoppi\w*|phone\s?booth|telefonzelle|"
                         r"numer\w*\s+telefon\w*|puhelinnumero\w*|phone\s+number|puhelinkaapel\w*|puhelintoimin\w*|"
                         r"\bdock(?:ing)?\b|telakka\w*|blacha|\bip[- ]phone\b|ip\s+telefon\w*|fixed\s+cellular|"
                         r"kiinteä\s+matkapuhelin|kiintea\s+matkapuhelin|tischhandy|bordstelefon", re.I),
              None),
    "sofa": (None, re.compile(r"tuoli\w*|\bchairs?\b|armchair|sessel\w*|fåtölj|fatolj|lenestol|lænestol|fotel\w*|"
                              r"pöytä\w*|poyta\w*|\btable\b|\btisch\w*|\bmatto\w*|\brug\b|tyyny\w*|cushion|kissen|"
                              r"päällinen|paallinen|\bpeti\b|lemmikki\w*|hylly\w*|lipasto\w*|sänky\w*|\bbed\b|\w*penkki\w*|"
                              r"\bvuode\b|\bvuoteet\b|\bbench\b", re.I)),
    "coffee machine": (None, re.compile(r"kahvimylly\w*|grinder|kaffeemühle|kvarn|termos\w*|thermos|vedenkeitin\w*|"
                                        r"\bkettle|wasserkocher|leivänpaahdin\w*|toaster|maitovaahdot\w*|frother|"
                                        r"kahvikupp?\w*|\bkupit\b|\bmukit?\b|\bcups?\b|tassen|"
                                        # live, kahvinkeitin: 'Pressopannu' €4 was the pick; Moccamaster gaskets,
                                        # switches and jugs, and iced-coffee packs filled the top 20
                                        r"\w*pannu\w*|french\s?press|stempelkanne|presskanne|pressokannu\w*|"
                                        r"cafeti[eè]re|moka\w*|bialetti|\w*tiiviste\w*|kytkin\w*|gasket|dichtung|"
                                        r"\w*kannu\b|\w*kannut\b|kanne\b|\bjug\b|termostaatti\w*|lämpölevy\w*|"
                                        r"vastus\b|letku\w*|iced\s+coffee|\bpaketti\w*|pakettia|kahvipaketti\w*|"
                                        r"kahvipa(?:pu|vut|puja)\w*|\bpavut\b|jauhettu\w*|kaffeebohnen|bohnen|\bbeans?\b|"
                                        r"\bkahvia\b|caramel\w*|siirappi\w*|sirup\w*|syrup|\btee\b|teetä|\btea\b", re.I)),
    "stroller": (re.compile(r"nuken\w*|nukke\w*|puppen\w*|dukke\w*|docka\w*|lalk\w*|poppen\w*|doll\w*", re.I),
                 re.compile(r"turvaistuin\w*|kaukalo\w*|car\s?seat|babyschale|autositz|bilbarnstol|sitteri\w*|"
                            r"syöttötuoli\w*|hochstuhl|pinnasänky\w*|kantoreppu\w*|kantoliina\w*|babytrage|"
                            r"\w*laukku\w*|\w*laukut\b|\w*verho\w*|\w*kuomu\w*|sadesuoja\w*|\w*pussi\b|\w*pussit\b|"
                            r"\w*suoja\b|mukiteline\w*|teline\w*|\w*tasche\w*|regenschutz|regenverdeck|fußsack|fusssack|"
                            r"sonnensegel|sonnenschirm|insektenschutz|moskitonetz|\w*väska\w*|\w*vaska\b|regnskydd|"
                            r"myggnät|åkpåse|akpase|\btas\b|regenhoes|voetenzak|zonnescherm|\bbag\b|\bbags\b|"
                            r"rain\s?cover|footmuff|sunshade|parasol|cup\s?holder|suitcase\w*|torba\w*|"
                            r"folia\s+przeciwdeszczowa|śpiwór|spiwor|parasolka|moskitier\w*", re.I)),
}
_BIKE_NOT = (r"potkupy\w*|potkulaud\w*|tuplapotku\w*|\bscoot(?:er|ers)?\b|e-?scooter|sähköpotku\w*|tretroller|"
             r"sparkcykel|løbehjul|lobehjul|sparkesykkel|\bstep\b(?![-\s]*(?:through|in\b))|hulajnog\w*|trottinette|monopattino|"
             r"laufräder|laufraeder|\bkiekot\b|kiekkosarja\w*|wheelset|laufradsatz|\bwheels?\b|"
             r"anhänger|anhaenger|peräkärry\w*|perakarry\w*|kärry|karry|trailer|cykelvagn|fietskar|"
             r"satulalaukku\w*|runkolaukku\w*|tarakkalaukku\w*|pyörälaukku\w*|fahrradtasche\w*|satteltasche\w*|"
             r"rahmentasche\w*|rucksack\w*|reppu\w*|backpack|cykelväska\w*|fietstas\w*|"
             r"kypärä\w*|helmet|fahrradhelm|cykelhjälm|fietshelm|kask\w*|ajokenkä\w*|pyöräilykenkä\w*|"
             r"radschuhe|cykelskor|trainer\b|rulla\w*|smart\s?trainer|hometrainer|rollentrainer|kuntopy\w*|"
             r"exercise\s+bike|spinning\w*|heimtrainer|ergometer|motionscykel|hometrainers")
# parts and gear sold alone: another kind only when the title names no bike (live, fiets: pedals, a scooter seat, a
# pump, handlebars, a chain, a helmet and a crank filled the top 30); 'Polkupyörä, uudet renkaat' stays a bike
_BIKE_PARTS = (r"polkim\w*|poljin\w*|pedal\w*|pedaal\w*|pedał\w*|pedaly|istuin\w*|satula\w*|sattel\w*|saddle\w*|"
               r"zadel\w*|siodełk\w*|siodelk\w*|sadel\b|kierownic\w*|ohjaustan\w*|\btanko\b|lenker\w*|handlebar\w*|"
               r"\bstuur\b|styre\b|kedja\w*|ketju\w*|\bkette\b|\bchain\w*|łańcuch\w*|lancuch\w*|korba\w*|kurbel\w*|"
               r"\bcrank\w*|vevparti\w*|vevlager|pompa\w*|pumppu\w*|\bpumpe\b|\bpump\b|hjälm\w*|hjalm\w*|hjelm\w*|"
               r"vaihtaja\w*|derailleur\w*|schaltwerk\w*|przerzut\w*|dźwigni\w*|dzwigni\w*|shifter\w*|jarru\w*|"
               r"\bbrakes?\b|bremse\w*|hamul\w*|\brengas\b|renkaat|renkaita|reifen|\btyres?\b|\btires?\b|opon[ay]|"
               r"vanne\b|vanteet|vanteita|felge\w*|\brims?\b|sisärenka\w*|schlauch\w*|dętk\w*|detk\w*|pyöränlukko\w*|"
               r"\blukko\b|fahrradschloss|cykellås|\btavarateline\w*|gepäckträger|pakethållare|lokasuoj\w*|"
               r"schutzblech\w*|stänkskärm\w*|kasetti\w*|kassette\w*|cassette|\bnapa\b|\bnaba\b|osat\b|"
               r"potku\s*laud\w*|skootteri\w*|\bmopo\w*|\bmopon\b")
SUBKINDS["bike"] = (re.compile(_BIKE_NOT, re.I), re.compile(_BIKE_PARTS, re.I))
SUBKINDS["bicycle"] = SUBKINDS["bike"]
# a road bike asked: the scooters, wheels and bags of a plain bike hunt are never one either
SUBKINDS["road bike"] = (re.compile(SUBKINDS["road bike"][0].pattern + "|" + _BIKE_NOT, re.I),
                         re.compile(SUBKINDS["road bike"][1].pattern + "|" + _BIKE_PARTS, re.I))
# a kitchen / dining table asked: other tables share the head word 'pöytä' / 'Tisch'
_TABLE_NOT = re.compile(r"sohvapöy\w*|sohvapoy\w*|coffee\s+table|couchtisch\w*|soffbord\w*|sofabord\w*|salontafel\w*|"
                        r"yöpöy\w*|yopoy\w*|nightstand|nachttisch\w*|sängbord\w*|natbord\w*|nachtkastje\w*|"
                        r"työpöy\w*|tyopoy\w*|\bdesk\b|schreibtisch\w*|skrivbord\w*|skrivebord\w*|bureau\b|biurk\w*|"
                        r"tv-?tason?\b|tv-?taso\w*|tv-?pöy\w*|tv-?poy\w*|sivupöy\w*|sivupoy\w*|side\s?table|beistelltisch\w*|"
                        r"pöytälamppu\w*|poytalamppu\w*|pöytäliina\w*|tablecloth|tischdecke|"
                        r"lastenpöy\w*|leikkipöy\w*|kampauspöy\w*|meikkipöy\w*|hoitopöy\w*|wickeltisch|"
                        r"terassipöy\w*|puutarhapöy\w*|gartentisch\w*|biljardi\w*|pingis\w*|tischtennis\w*|"
                        r"\bjakkar\w*|baarijakkar\w*|barhocker|barstol\w*|\bstools?\b", re.I)
SUBKINDS["kitchen table"] = SUBKINDS["dining table"] = (_TABLE_NOT, None)
# a phone asked (typed or from the tree): cases, wallets, lenses, gimbals and clothes found by a 'puhelin' search are
# another kind when the title names no phone (live, phones tree: 'Accezz ... puhelinkotelo' €20 was the pick)
SUBKINDS["phone"] = (SUBKINDS["phone"][0], re.compile(
    r"\w*kotelo\w*|\w*kuori\b|\w*kuoret\b|\w*suoja\b|\w*suojus\w*|lompakko\w*|\bcases?\b|\bcover\w*|hülle\w*|"
    r"\bskal\b|fodral\w*|etui\w*|hoesje\w*|deksel\w*|gimbal\w*|kalansilmä\w*|fisheye|objektiiv\w*|\blens\w*|"
    r"\w*teline\w*|\bholder\b|halterung|stativ|tripod|laturi\w*|charger\w*|ladegerät\w*|kaapeli\w*|\bcable\w*|"
    r"\w*legginsit|leggings|housut|paita|\w*takki|mekko|kengät|\bkuulok\w*|headset\w*|earbuds?", re.I))
SUBKINDS["smartphone"] = SUBKINDS["mobile phone"] = SUBKINDS["phone"]
# a shelf asked ('ikea kallax shelf'): baskets, inserts, boxes and a desk of the same series are not the shelf
# (live: 'IKEA KALLAX ritiläkorit', '2kpl IKEA Kallax upotettavia lipastoja', 'IKEA KALLAX desk' at €20 in the top 20)
SUBKINDS["shelf"] = (None, re.compile(
    r"\bkor(?:i|it|ia|eja)\b|\w+kor(?:i|it|ia|eja)\b|upotettav\w*|insert\w*|insertti\w*|laatik\w*|lipasto\w*|"
    r"\bdesk\b|työpöy\w*|tyopoy\w*|\bovi\b|\bovet\b|\bovia\b|\bdoors?\b|einsatz\w*|einsätze|drawers?\b|"
    r"schublade\w*|\blåd(?:a|or)\b|\bboxes\b|\bbox\b|baskets?\b|\bkorg\w*|\bkörbe\b|\bkorb\b|säilytys\w*|"
    r"vitriini\w*|\bjalat\b|\bjalka\w*", re.I))
SUBKINDS["baby stroller"] = SUBKINDS["stroller"]

# a narrower kind is also named by a broader word the sellers use: 'Pöytä ja tuolit' is a kitchen table
KIND_ALSO: dict[str, tuple[str, ...]] = {"kitchen table": ("dining table", "table"), "dining table": ("kitchen table", "table")}

# makers whose name alone says the kind ('OnePlus Nord 5 256GB' is a phone, 'Dolce Gusto Circolo' a coffee maker):
# a generic need counts them as naming the kind
KIND_MAKERS: dict[str, re.Pattern[str]] = {
    "phone": re.compile(r"\b(?:iphone|galaxy\s+[asmz]\d|galaxy\s+(?:note|fold|flip)|pixel\s?\d|oneplus|one\s+plus|xiaomi|"
                        r"redmi|poco\s+[a-z]?\d|huawei\s+p\d|honor\s+\d|oppo|realme|vivo\s+[a-z]?\d|motorola|moto\s+[a-z]\d|"
                        r"nokia\s+[a-z]?\d|xperia|fairphone|nothing\s+phone|doro|zenfone|\d{2,4}\s?gb)\b", re.I),
    "coffee machine": re.compile(r"\b(?:dolce\s?gusto|nespresso|tassimo|senseo|moccamaster|delonghi|de'?longhi|jura|"
                                 r"krups|saeco|melitta|siemens\s+eq|philips\s+\d{4}|sage\s+(?:barista|bambino)|"
                                 r"gaggia|rancilio|lelit|bialetti|keurig|espresso\w*)\b", re.I),
}
_ROAD_MAKERS = (r"cannondale|specialized|pinarello|cerv[eé]lo|colnago|bianchi|wilier|ridley|orbea|\bbmc\b|"
                r"lapierre|merida|giant|trek|canyon|scott|cube|focus|felt|\blook\b|\brose\b|basso|de\s?rosa|"
                r"factor|argon\s?18|time\s+(?:alpe|scylon)|caad\s?\d+|supersix|tarmac|allez|domane|emonda|madone|"
                r"\btcr\b|defy|propel|ultimate\s+cf|endurace|aeroad|addict|speedster|scultura|reacto")
KIND_MAKERS["road bike"] = re.compile(rf"\b(?:{_ROAD_MAKERS})", re.I)
KIND_MAKERS["bike"] = KIND_MAKERS["bicycle"] = re.compile(
    rf"\b(?:{_ROAD_MAKERS}|helkama|tunturi|jopo|gazelle|batavus|sparta|cortina|kalkhoff|riese|haibike|"
    rf"brompton|crescent|kona|marin|nishiki|raleigh|stevens|ghost|radon|vanmoof|cowboy)", re.I)
KIND_MAKERS["smartphone"] = KIND_MAKERS["mobile phone"] = KIND_MAKERS["phone"]
KIND_MAKERS["coffee maker"] = KIND_MAKERS["coffee machine"]

# clothing: the audience asked for. 'winter jacket women' never takes a dog coat, a kids' or a men's jacket.
APPAREL_NEED = re.compile(r"jacket|coat|takki|jakke|jacka|jacke|\bjas\b|kurtka|parka|anorak|shoes?|kengät|kenka|boots?|"
                          r"saappaat|dress|mekko|pants|housut|trousers|hoodie|sweater|neule|shirt|paita|jeans|farkut|"
                          r"vest\b|liivi|haalari|overall|toppa|untuva|down\s+jacket|sneakers?|tennarit|hat\b|pipo|"
                          r"gloves?|hanskat|käsineet|scarf|huivi|skirt|hame|blazer|bunda|veste|mantel|manteau", re.I)
_AUD = {
    "women": re.compile(r"\b(?:women\w*|woman|ladies|lady|naisten|nais|nainen|damen|dame|dames|dam|kvinde\w*|kvinn\w*|"
                        r"damsk\w*|female|femme|donna|mujer)\b|\bnais\w+takki", re.I),
    "men": re.compile(r"\b(?:men|mens|men's|man|miesten|mies|herren|herre|herr|heren|męsk\w*|mesk\w*|męski|meski|"
                      r"male|homme|uomo|hombre|herrar|mand)\b|\bmies\w+takki", re.I),
    "kids": re.compile(r"\b(?:kids?|child\w*|lasten|lapsen|lapsille|poikien|tyttöjen|tyttojen|pojan|tytön|tyton|"
                       r"kinder\w*|mädchen|madchen|jungen|junge|jungs|barn\w*|dziec\w*|chłopi\w*|chlopi\w*|dziewcz\w*|"
                       r"girls?|boys?|junior|juniors?|baby|vauva\w*|toddler|taapero\w*|enfant\w*|bambin\w*|niñ\w*)\b"
                       r"|\b(?:gr\.?|größe|grosse|koko|size|str\.?|stl\.?|rozm\.?|rozmiar|maat|taille)\s*:?\s*"
                       r"(?:7[4-9]|[89]\d|1[0-6]\d)(?:\s*/\s*\d{2,3})?\b|\b(?:7[4-9]|[89]\d|1[0-6]\d)\s*cm\b"
                       r"|\b(?:[89]\d|1[0-6]\d)\s*-\s*(?:[89]\d|1[0-7]\d)\b|\b\d{1,2}\s*-\s*\d{1,2}\s*(?:v|vuotta|vuotiaalle|"
                       r"years?|yrs|y|jahre|j|år|lat|ans)\b|\b\d{1,2}\s*(?:v|vuotiaalle|vuotiaan)\b", re.I),
    "pet": re.compile(r"\b(?:koiran\w*|koiralle|koira|kissan|kissalle|hunde\w*|hund|hond\w*|honden\w*|dog|dogs|doggy|"
                      r"puppy|pies|psa|psów|psow|lemmikin|lemmikille|pet|pets|haustier\w*)\b", re.I),
}


# 'Komplett m. manual', 'Lego 42115 mit Anleitung', 'set + ohjekirja': the print comes WITH the item
_WITH_WORD_BEFORE = re.compile(r"\S.*(?:\bm\.|\bmed\b|\bmit\b|\bwith\b|\bw/|\bincl\w*|\binkl\w*|\bja\b|\band\b|\bog\b|"
                               r"\bund\b|\bsis\.|\bsisältää|\bkomplet\w*|\bcomplete\b|\+|&)\s*(?:\S+\s+){0,2}$", re.I)


def _audience(text: str) -> set[str]:
    return {k for k, rx in _AUD.items() if rx.search(text)}


def _kind_noun(need: Need) -> str | None:
    try:
        from agora import marketplaces as M
    except ImportError:
        return None
    noun = M.english_noun(need.thing or "")
    if noun is None and (need.category or {}).get("label"):
        noun = M.english_noun(str(need.category["label"]))
    return noun


def product_clash(need: Need, offer: Offer) -> str | None:
    """Why this listing is another kind of thing than the product asked for (a toy, a magazine, a game for the
    console, a kids' / men's / dog's jacket for a women's jacket, a city bike for a road bike), else None."""
    if need.kind != "product":
        return None
    cat = need.category or {}
    return _product_clash(need.thing or "", " ".join(need.must_have), str(cat.get("id") or ""),
                          str(cat.get("label") or ""), offer.title or "", is_generic(need))


@functools.lru_cache(maxsize=50000)
def _product_clash(thing: str, must: str, cat_id: str, cat_label: str, title: str, generic: bool) -> str | None:
    asked = f"{thing} {must} {cat_label}"
    if (m := TOY_RX.search(title)) and not TOY_RX.search(asked):
        return f"a toy or a model ({m.group(0).strip()}), not a {thing}"
    if (m := MEDIA_RX.search(title)) and not MEDIA_RX.search(asked) and not _WITH_WORD_BEFORE.search(title[:m.start()]):
        return f"a magazine, book or print ({m.group(0).strip()}), not a {thing}"
    # the category label 'Video Game Consoles' says 'game': only the person's own words can ask for a game
    if CONSOLE_NEED.search(thing) and not re.search(rf"\b{_GAME}\b", f"{thing} {must}", re.I):
        if (m := _GAME_RX.search(title)) and not _CONSOLE_EVIDENCE.search(title[:m.start()] + title[m.end():]):
            return f"a game or add-on for it ({m.group(0).strip()}), not the console"
        if not _CONSOLE_EVIDENCE.search(title) and not _CONSOLE_ADDON.search(f"{thing} {must}") \
                and re.fullmatch(r"\W*(?:\w+\W+){0,2}\w*\W*", thing):
            if (m := _CONSOLE_ADDON.search(title)) and not _WITH_WORD_BEFORE.search(title[:m.start()]):
                return f"an add-on for it ({m.group(0).strip()}), not the console"
            if name := _named_before_platform(title):
                return f"a game for it ({name}), not the console"
    if ROBOT_VAC.search(asked) and (m := OTHER_VAC.search(title)) and not ROBOT_VAC.search(title):
        return f"another kind of vacuum ({m.group(0).strip()}), not a robot vacuum"
    if CONSOLE_NEED.search(thing) and (m := STORAGE_RX.search(title)) and not STORAGE_RX.search(f"{thing} {must}") \
            and not _WITH_WORD_BEFORE.search(title[:m.start()]):
        # 'Corsair MP600 Elite SSD 2Tb ... PS5 konsolille' is a drive; 'PS5 Digital 825GB SSD' is the console
        plat = _PLATFORM_RX.search(title)
        if STORAGE_MAKER.search(title) or plat is None or m.start() < plat.start() or "konsoli" in m.group(0).lower():
            return f"storage for it ({m.group(0).strip()}), not the console"
    if APPAREL_NEED.search(asked):
        want = _audience(asked)
        have = _audience(title)
        if "pet" in have and "pet" not in want:
            return "for a pet, not for you"
        if want & {"women", "men", "kids"}:
            other = (have - want) & {"women", "men", "kids"}
            if other and not (have & want):
                return f"another audience ({'/'.join(sorted(other))}), not {'/'.join(sorted(want))}"
    from agora.models import Need as _Need
    n = _Need(raw=thing, thing=thing, category={"id": cat_id, "label": cat_label})
    noun = _kind_noun(n)
    if noun in BIKE_NOUNS and not FRAME_RX.search(asked) and (m := FRAME_RX.search(title)):
        # 'Maantiepyörä runko Crescent' €35 (live pick of the Road Bikes tree hunt); 'runko 56 cm' is a size
        if not re.search(r"\d\s*(?:cm|\"|”|'')?\s*$", title[:m.start()]) and \
                not re.match(r"\s*(?:-?koko|size|\d)", title[m.end():], re.I):
            return f"a frame alone ({m.group(0).strip()}), not a whole {noun}"
    if noun and noun in SUBKINDS:
        strong, soft = SUBKINDS[noun]
        if strong is not None and (m := strong.search(title)) \
                and not _extra_of_named_item(n, title, m.start(), strict=True):
            return f"another kind of thing ({m.group(0).strip()}), not a {noun}"
        if soft is not None and (m := soft.search(title)) and not _extra_of_named_item(n, title, m.start()):
            try:
                from agora import marketplaces as M
                words = {w for w in M.translations(noun) if len(w) >= 4}
                head = noun.split()
                if len(head) == 1 or head[0] in ("baby", "kids", "women", "men"):
                    words |= SYNONYMS.get(head[-1], set())     # 'rattaat', 'vaunut' name a stroller too
                own = _fold_words(words)
            except Exception:
                own = frozenset()
            if not _hits(own, frozenset(tokenize(title))):
                return f"another kind of thing ({m.group(0).strip()}), not a {noun}"
    return None


STORAGE_RX = re.compile(r"\b(?:ssd|nvme|m\.2|kiintolevy\w*|hårddisk\w*|harddisk\w*|festplatte\w*|hard\s?drive|"
                        r"\w+konsolille|\w+konsoliin)\b", re.I)
STORAGE_MAKER = re.compile(r"\b(?:corsair|wd_?black|western\s+digital|seagate|crucial|kingston|sabrent|lexar|"
                           r"firecuda|sn\d{3}\w*|mp\d{3}\w*|990\s?pro|980\s?pro|samsung\s+9\d0)\b", re.I)
ROBOT_VAC = re.compile(r"robot\w*[\s-]?(?:imur\w*|vac\w*|staubsauger|dammsugare|stofzuiger|odkurzacz)|saugroboter|"
                       r"robotdammsugare|robotstøvsuger|robotstovsuger|robotstofzuiger|roomba|roborock|\bdreame\b|"
                       r"robotti\w*|\brobot\b", re.I)
OTHER_VAC = re.compile(r"\b(?:varsi-?imur\w*|rikkaimur\w*|käsi-?imur\w*|kasi-?imur\w*|keskusimur\w*|märkäimur\w*|"
                       r"markaimur\w*|vesi-?imur\w*|stick\s+vac\w*|hand(?:held)?\s+vac\w*|handstaubsauger|"
                       r"stielstaubsauger|akkustaubsauger|bodenstaubsauger|skaftdammsugare|handdammsugare|"
                       r"steelstofzuiger|kruimeldief|stangstøvsuger|håndstøvsuger)", re.I)


_EXTRA_LEAD = re.compile(r"(?:\+|&|\s[-–—]\s|\b(?:ja|and|und|og|och|en|with|mit|med|met|incl\w*|inkl\w*|ilman|"
                         r"without|ohne|utan|uden|uten|plus|sis\.?|sekä|samt|m\.)\b)")


_EXTRA_LEAD_STRICT = re.compile(_EXTRA_LEAD.pattern.replace("|\\s[-–—]\\s", ""))


def _extra_of_named_item(need: Need, title: str, at: int, strict: bool = False) -> bool:
    """The other-kind word at `at` comes after the item itself and a with-word: 'Apple iPhone 16 128 GB + 5 cover',
    'Felt Z85 maantiepyörä 56 cm – Shimano 105 & Ultegra-kiekot', 'vuodesohvan runko ilman patjaa'. The item is
    named before it by its kind word, a maker of the kind or a model code."""
    before = title[:at]
    rx = _EXTRA_LEAD_STRICT if strict else _EXTRA_LEAD
    if not rx.search(before):
        return False
    lead = rx.split(before, maxsplit=1)[0]
    toks = frozenset(tokenize(lead))
    noun = _kind_noun(need) or ""
    maker = KIND_MAKERS.get(noun)
    narrow = _narrow_broad(noun)[0] if " " in noun else frozenset()
    return bool(_hits(_need_words(need), toks) or (narrow and _hits(narrow, toks))
                or (maker is not None and maker.search(lead)) or signature(lead).models)


BIKE_NOUNS = {"bike", "bicycle", "road bike", "mountain bike", "city bike", "gravel bike", "hybrid bike", "e-bike"}
FRAME_RX = re.compile(r"\b(?:runko|rungot|runkosarja|frame|frameset|frames|rahmen|rahmenset|rahmenkit|ram|ramset|"
                      r"rama|frameset|frame\s?kit|cadre|telaio|cuadro|frameset)\b", re.I)

_SEARCH_WORDS = {"refurbished", "refurb", "renewed", "used", "new", "buy", "cheap", "cheapest", "sale", "deals", "deal",
                 "price", "prices", "online", "shop", "kaufen", "gebraucht", "generaluberholt", "osta", "kaytetty",
                 "kaytetyt", "kunnostettu", "kunnostetut", "uusi", "uudet", "hinta", "halpa", "tilbud", "brugt",
                 "begagnad", "begagnade", "tweedehands", "gebruikt", "refurbished.", "best", "for", "occasion"}


def search_title(need: Need, offer: Offer) -> bool:
    """A shop's search / category page read as one offer: its title is the person's own words plus a condition or
    shopping word ('lego technic refurbished | Reepeat'): its price is some item's on it."""
    if need.kind != "product":
        return False
    raw = offer.raw if isinstance(offer.raw, dict) else {}
    if raw.get("from_list_page") or raw.get("site") or offer.image or offer.read_via != "search_highlight":
        return False              # only a search snippet with no photo: a product page that read is one item
    head = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[A-Z][\w.]+$)", offer.title or "")[0]
    toks = [t for t in tokenize(head) if t]
    asked = set(tokenize(need.thing))
    extra = [t for t in toks if t not in asked]
    return bool(toks) and bool(extra) and all(t in _SEARCH_WORDS for t in extra) and len(set(toks) & asked) >= 1


def _line_missing(ns: Signature, need_words: set[str], toks: set[str]) -> bool:
    """A maker + product line asked ('lego technic', 'ikea kallax'): the title names the maker but not the line."""
    try:
        from agora import marketplaces as M
    except ImportError:
        return False
    line = [w for w in need_words if w != ns.brand and w not in ATTRIBUTE_ONLY and w not in FAMILIES
            and not M.english_noun(w)
            and w not in SYNONYMS and not any(w in v for v in SYNONYMS.values()) and len(w) >= 3]
    return bool(line) and not all(word_hit(w, toks) for w in line)


def relevance(need: Need, offer: Offer) -> float:
    """0..1: how well this offer answers the need."""
    if not_an_offer(offer) or search_title(need, offer):
        return 0.0
    if kind_mismatch(need, offer) or far_provider(need, offer):
        return 0.05            # a gun for a gunsmith hunt, a repair rate for a product hunt, a US gunsmith
    ns = signature(need.thing)
    os_ = signature(offer.title or "", offer.brand)
    title_toks = set(tokenize(offer.title or "")) | os_.words | set(os_.models)
    need_words = {w for w in ns.words if w not in ATTRIBUTE_ONLY}
    hay = " ".join(title_toks) + " " + (os_.brand or "")
    toks = title_toks | ({os_.brand} if os_.brand else set())
    nv = _tiers(ns.variants)
    implied = (ns.family if ns.family and ns.brand and os_.brand == ns.brand and not os_.models and nv
               and nv <= _tiers(os_.variants) else None)     # 'Nintendo Oled ja peli': the Switch OLED
    covered = sum(1 for w in need_words if word_hit(w, toks) or any(word_hit(x, toks) for x in SYNONYMS.get(w, ()))
                  or _is_a_vehicle(w, offer) or w == implied)
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
    if ns.models and not os_.models and _older_than_asked(ns, offer.title or ""):
        model = 0.1            # 'MacBook Air 2018' for 'macbook air m2'
    if ns.models and not ns.variants and os_.variants and CONSOLE_NEED.search(need.thing or "") \
            and re.fullmatch(r"\W*(?:\w+\W+){0,1}\w+\W*", need.thing or ""):
        # a bare console name ('ps5'): the Pro and Slim are that console too (the tier shows in the title)
        model = _model_match(ns, Signature(os_.brand, os_.models, (), os_.kit, os_.words, os_.family))
    if ns.models and not os_.models and model > 0.45 and _marketplace_row(offer) and not _is_vehicle_need(need):
        model = 0.45           # a seller's 'Dyson dammsugare' for a 'dyson v15': not shown to be the one asked
    vehicle = _is_vehicle_need(need)
    if vehicle and ns.models:
        # a car's trim words are no tier ('V70 2.0 D4 Polar plus edition' is a V70); a car with no model named is
        # not shown to be the one asked ('Volvo 940' / 'Volvo farmari' for a V70)
        model = _model_match(ns, Signature(os_.brand, os_.models, ns.variants, os_.kit, os_.words, os_.family))
        if not os_.models:
            model = min(model, 0.3)
    brand_ok = 1.0
    if ns.brand and os_.brand and ns.brand != os_.brand:
        brand_ok = 0.2
    elif other_make(need, offer):
        brand_ok = 0.2          # 'Saab 96' for a 'volvo v70' (the title's make is not in BRANDS)
    elif ns.brand and not os_.brand and ns.brand not in hay:
        brand_ok = 0.95
    if ns.brand and not ns.models and (os_.brand == ns.brand or ns.brand in hay) and _line_missing(ns, need_words, toks):
        coverage = min(coverage, 0.2)    # 'lego technic': a LEGO City set names the maker, not the line asked
    # model identity dominates; extra words only nudge ("sony a7 iii" vs "a7 iii body black")
    score = model * (0.75 + 0.25 * coverage) if ns.models else (0.2 + 0.8 * coverage) * model
    score *= brand_ok
    if is_accessory(offer.title or "", need):
        score *= 0.15
    elif any(k in RED_REJECT for k, _, _ in title_red_flags(offer, need)):
        score *= 0.15     # one earbud, the box, a wanted ad: not the item
    if vehicle_mismatch(need, offer):
        score *= 0.05
    elif product_clash(need, offer):
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
# a trade's stem, at the start of a word: firm names ('24 Sähkö Oy', 'Putkihuolto Arina Oy') and domains name the job
TRADE_STEMS: dict[frozenset[str], tuple[str, ...]] = {
    ELECTRICIAN_GROUP: ("sahko", "elektro", "elektri", "electric", "elinstall", "elfirma", "elservice"),
    PLUMBER_GROUP: ("putki", "lvi", "plumb", "sanitar", "loodgiet", "klempner", "rormok", "vvs", "installat"),
    CLEANING_GROUP: ("siivo", "clean", "schoonm", "reinig", "stadning", "stadfirma"),
}
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
# an add-on line on an event service's price list: never the base package (live: 'Koko galleria' €100 was the
# wedding-photographer pick; 'Lisätunti' €180 x 8 h became a €1,440 'package'; 'Live Stream' kept as an offer)
EXTRA_LINE = re.compile(
    r"lisatunti\w*|lisa\s*tunti|extra\s+(?:hour|time)|additional\s+hours?|each\s+additional|following\s+hours?|"
    r"seuraava\w*\s+tunni\w*|jokainen\s+alkava|zusatz(?:liche)?\s*stunde\w*|weitere\s+stunde\w*|extra\s+uur|"
    r"\bgalleria\w*|\bgallery\b|album\w*|valokuvakirja\w*|kuvakirja\w*|photo\s?book\w*|fotobuch|"
    r"live\s?-?stream\w*|striimau\w*|lisapalvelu\w*|lisakuva\w*|extra\s+photos?|\badd-?ons?\b|"
    r"second\s+(?:photographer|shooter)|toinen\s+kuvaaja|kakkoskuvaaja|drone\w*|drooni\w*|"
    r"matkakulu\w*|matkakorvau\w*|travel\s+(?:fee|cost|expenses)|kilometrikorvau\w*", re.I)
EVENT_NEED = re.compile(r"wedding|haa|hochzeit|bruiloft|bryllup|brollop|photograph|kuvaaja|kuvaus|fotogra|video\w*|"
                        r"\bdj\b|band|bandi|juhla|event|tapahtuma|party", re.I)
# a weekday daytime 'päivystys' slot is a standard rate (live, lvirundstrom.fi 'Päivystys – arkisin klo 7–17' €55/h)
WEEKDAY_LINE = re.compile(r"arkisin|arkipaiv\w*|ma\s*-\s*pe|mon(?:day)?\s*-\s*fri(?:day)?|weekdays?|werktags|"
                          r"maandag\s*(?:t/m|-)\s*vrijdag|vardagar|hverdag\w*", re.I)
_OFF_HOURS = re.compile(r"\bnacht|\bnight|weekend|wochenende|sunday|sonntag|holiday|feiertag|\bilta|\byo\b|yolla|"
                        r"viikonlop\w*|pyha\w*|lauantai|sunnuntai|klo\s*(?:1[7-9]|2\d)\s*-", re.I)
# one figure for a whole market, not a provider ('Average price of women haircut' at finlandprices.com,
# 'Putkimiehen tuntihinta 2026 — mediaani 62,75 €/h (45 yritystä)'): a reference, never an offer
MARKET_STAT = re.compile(r"\baverage\s+(?:price|cost|rate|hourly)|\bmedian\b|\bmediaani\w*|\bkeskihin\w*|"
                         r"\bkeskimaar\w*|\bdurchschnitt\w*|\bgemiddeld\w*|\bgenomsnitt\w*|\bgjennomsnitt\w*|"
                         r"\bprice\s+index\b|\bhintataso\w*|\(\s*\d+\s+(?:yritys\w*|companies|firms|providers|"
                         r"betriebe|bedrijven)\s*\)|\bhow\s+much\s+(?:does|do|is)\b", re.I)
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
    if EXTRA_LINE.search(t) and not EXTRA_LINE.search(asked) and EVENT_NEED.search(asked):
        return "extra"
    if CALLOUT_LINE.search(t) or (unit or "") == "visit" and g in OPEN_TRADES:
        return "callout"
    if PREMIUM_LINE.search(t) and not PREMIUM_LINE.search(asked) \
            and not (WEEKDAY_LINE.search(t) and not _OFF_HOURS.search(t)):
        return "premium"
    if g in OPEN_TRADES and (unit or "") in ("job", "m2"):
        tw = _task_words(need)
        if not (tw and any(w in t for w in tw)):
            return "task"
    return "main"


INSURANCE_KINDS: dict[str, re.Pattern[str]] = {
    "car": re.compile(r"\b(?:car|cars|auto\w*|vehicle|motor\w*|kasko\w*|liikenne\w*|kfz|bil\w*|traffic|"
                      r"moottoriajoneuvo\w*)\b", re.I),
    "home": re.compile(r"\b(?:home\w*|house\w*|koti\w*|condo|renters?|tenants?|hausrat\w*|inboedel\w*|hem\w*|"
                       r"landlord|property)\b", re.I),
    "life": re.compile(r"\b(?:life|term\s+life|henki\w*|lebens\w*|levens\w*|livforsakring)\b", re.I),
    "pet": re.compile(r"\b(?:pets?|lemmikki\w*|dog|cat|tier\w*|huisdier\w*)\b", re.I),
    "travel": re.compile(r"\b(?:travel|matka\w*|reise\w*|reis\w*|rese\w*)\b", re.I),
    "health": re.compile(r"\b(?:health|dental|medical|sairaus\w*|terveys\w*|kranken\w*|zorg\w*)\b", re.I),
    "umbrella": re.compile(r"\bumbrella\b", re.I),
    "business": re.compile(r"\b(?:business|commercial|yritys\w*|gewerbe\w*)\b", re.I),
}


def _insurance_clash(need: Need, offer: Offer) -> str | None:
    """'Progressive Umbrella insurance' / 'Lemonade Term Life' for car insurance: another insurance."""
    asked = _fold(need.thing)
    if not re.search(r"insur|vakuut|versicher|verzeker|forsakr|forsikr", asked):
        return None
    want = [k for k, rx in INSURANCE_KINDS.items() if rx.search(asked)]
    if not want:
        return None
    title = _fold(offer.title or "")
    have = [k for k, rx in INSURANCE_KINDS.items() if rx.search(title)]
    if have and not set(have) & set(want):
        return f"a different insurance ({have[0]}), not {need.thing}"
    return None


def off_topic_reason(need: Need, offer: Offer) -> str | None:
    """Why a single service offer is not an offer for this need: an admin fee / surcharge, or another service."""
    if need.kind != "service":
        return None
    if why := _insurance_clash(need, offer):
        return why
    kind = (offer.raw or {}).get("line_kind") or service_line_kind(need, offer.title or "", offer.unit)
    if kind == "fee":
        return "a fee or surcharge, not a price for the job"
    if kind == "extra":
        return "an add-on line (extra hour, gallery, album, stream), not the package"
    if MARKET_STAT.search(offer.title or ""):
        return "a market statistic (an average of many providers), not one provider's price"
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
    """A local trade (a gunsmith, a cleaner) is done where you are: a provider pricing in dollars (or pounds, for
    a place outside the UK) on a non-EU domain is on another continent, whatever its page says; so is one located
    in a US state ('Berlin, CT' for Berlin). B2B / digital services are delivered from anywhere and stay, unless
    they are bound to the country's own rules (insurance, bookkeeping, tax, legal: a Finnish car insurance or a
    Finnish company's books are never bought from progressive.com or pilot.com) or the person named a place."""
    if need.kind != "service":
        return None
    loc = (offer.location or "").strip()
    try:
        from agora.discover import country_of, domain_of, home_country, is_eu
        from agora.need import priced_per_period
        cc = (country_of(need) or home_country() or "").lower()
    except Exception:
        return None
    if not cc or cc in ("us", "ca", "au", "nz"):
        return None
    if loc and _US_STATE.search(loc):
        return f"a provider abroad (in {loc}, USA), not a {service_label(need)} near you"
    cur = (offer.currency or "").upper()
    far_cur = cur in FAR_CURRENCIES or (cur == "GBP" and cc not in ("gb", "uk", "ie"))
    if not far_cur:
        return None
    try:
        if cur != "GBP" and is_eu(domain_of(offer.url or "") or offer.source or ""):
            return None          # a .de page quoting dollars is still a Berlin plumber
        if priced_per_period(need) and not need.where and not LOCAL_RULES.search(
                f"{need.thing} {(need.category or {}).get('id') or ''} {(need.category or {}).get('label') or ''}"):
            return None
    except Exception:
        return None
    if loc and need.where and need.where.lower() in loc.lower():
        return None
    return f"a provider abroad (prices in {cur}), not a {service_label(need)} near you"


# services bound to the country's own rules: bought at home even when priced per month / year
LOCAL_RULES = re.compile(r"insur|vakuut|versicher|verzeker|forsakr|forsikr|bookkeep|accounting|accountant|kirjanpi|"
                         r"tilitoimi|buchhalt|boekhoud|bokfor|regnskab|tax\b|vero|steuer|legal|lawyer|asianaja|"
                         r"rechtsanw|advoca|notar|payroll|palkanlask|mortgage|asuntolaina|pension|elake", re.I)


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
    thing_words = [w for w in re.findall(r"\w+", _fold(need.thing)) if len(w) > 1 and not _JOB_SIZE.match(w)
                   and w not in _SERVICE_FILLER and w != _fold(need.where or "")]
    thing_words = thing_words or [w for w in re.findall(r"\w+", _fold(need.thing)) if len(w) > 1]
    groups = [g for g in SERVICE_NOUNS if any(w in g for w in thing_words)]

    def hit(w: str) -> bool:
        alts = {w} | SYNONYMS.get(w, set())
        return any(a in words or (len(a) >= 4 and a in text) for a in alts)

    svc = [m for m in need.must_have if m.lower() in text] + [w for w in thing_words if hit(w)]
    host = _host(offer.url or "")
    def named(g: frozenset[str]) -> bool:
        """The page names the job: a word of the group, or a long one inside a compound ('Schoonmaakbedrijf'),
        or the trade's stem in the firm's name or address ('SähköHessu Oy', 'SK-Putki Oy', normiputki.fi)."""
        return any(x in words or (len(x) >= 6 and x in text) for x in g) or any(
            re.search(rf"(?<![a-z]){st}", text) or st in host for st in TRADE_STEMS.get(g, ()))

    for g in groups:   # the job named in another language / form ('huollon' for 'repair') covers that word
        if any(w in g for w in thing_words if not hit(w)) and named(g):
            svc.append(next(w for w in thing_words if w in g and not hit(w)))
    score = 0.4 + 0.6 * min(1.0, len(set(svc)) / max(1, len(thing_words)))
    if groups and not any(named(g) or any(x in words or (len(x) >= 5 and x in text) for x in g) for g in groups):
        score *= 0.3       # 'bike repair' asked, a €6,400 e-bike product page offered
    for w, clash in _SERVICE_CLASH.items():
        if w in thing_words and clash.search(text) and not clash.search(need.thing):
            score *= 0.3
    if re.search(r"surcharge|lisamaksu|lisahinta|aufpreis|zuschlag|add-on|extra charge", _fold(offer.title or "")):
        score *= 0.4       # 'full suspension bike surcharge' (€15) is a line on top of a job, not a job
    if _ARTICLE_TITLE.search(offer.title or ""):
        score *= 0.3       # 'Find a cleaning service in the Netherlands' (dutchreview.com): an article
    if other_place(need, offer):
        score *= 0.45      # a cleaner in Amsterdam for Tilburg
    elif need.where and offer.location and need.where.lower() not in offer.location.lower():
        score *= 0.8       # a region or a country ('Uusimaa', 'Deutschland'): may well cover the place
    return round(min(score, 1.0), 3)


_SERVICE_FILLER = {"service", "services", "palvelu", "palvelut", "palvelun", "company", "companies", "firm", "yritys",
                   "dienst", "dienstleistung", "price", "prices", "hinta", "hinnat", "cost", "costs", "near", "me",
                   "local", "best", "cheap", "edullinen"}
_ARTICLE_TITLE = re.compile(r"^\W*(?:find\s+(?:a|an|the|your)\b|how\s+(?:to|much)\b|the\s+best\b|best\s+\d*|top\s?\d+\b|"
                            r"\d+\s+best\b|(?:a\s+)?guide\s+to\b|what\s+(?:does|is)\b|compare\s|cheapest\s+\w+\s+in\b)", re.I)
# a metro area's own towns: an Espoo provider serves Helsinki
METRO = {"helsinki": {"espoo", "vantaa", "kauniainen", "sipoo", "kerava"}, "espoo": {"helsinki", "vantaa", "kauniainen"},
         "vantaa": {"helsinki", "espoo", "kerava"}, "amsterdam": {"amstelveen", "diemen", "zaandam"},
         "rotterdam": {"schiedam", "capelle", "vlaardingen"}, "den haag": {"'s-gravenhage", "rijswijk", "delft"},
         "'s-gravenhage": {"den haag", "rijswijk", "delft"}, "tampere": {"pirkkala", "nokia", "kangasala", "ylojarvi"},
         "turku": {"kaarina", "raisio", "naantali"}}
_US_STATE = re.compile(r",\s*(?:A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|"
                       r"S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b(?:\s+\d{5})?\s*(?:,\s*(?:usa|us|united states))?\s*$")


def other_place(need: Need, offer: Offer) -> str | None:
    """'in Amsterdam, not Tilburg': a local service provider whose stated location is another town (not the asked
    one, not one of its metro towns, not a region or country that may cover it). A US state suffix ('Berlin, CT')
    is always another place for a European town."""
    if need.kind != "service" or not need.where or not offer.location:
        return None
    loc = offer.location.strip()
    if _US_STATE.search(loc):
        return f"in {loc} (USA), not {need.where}"
    try:
        from agora import places as P
        where, floc = P._fold(need.where).strip(), P._fold(loc)
        if where and where in floc:
            return None
        if where not in P.CITY_CC:
            return None              # a country or region asked: the location test is the country's (far_provider)
        hits = [k for k, _, _ in P._hits(floc, P.CITY_CC)]
    except Exception:
        return None
    if not hits or any(h in METRO.get(where, ()) for h in hits):
        return None
    return f"in {loc[:40]}, not {need.where}"


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
    if search_title(need, offer):
        return r, "a shop's search page (its title is the search words), not one listing"
    if need.kind == "service":
        if why := off_topic_reason(need, offer) or other_place(need, offer):
            return r, why
        if _ARTICLE_TITLE.search(offer.title or ""):
            return r, "an article or guide, not a provider's price"
        return r, "not that service (the page does not name the job)"
    if why := vehicle_mismatch(need, offer):
        return r, why
    if make := other_make(need, offer):
        return r, f"another make ({make.title() if len(make) > 3 else make.upper()}), not the car asked"
    if is_generic(need) and (other := other_kind(need, offer)):
        return r, f"another kind of thing ({other}), not a {_need_noun(need)}"
    if is_accessory(offer.title or "", need):
        return r, "accessory, not the item"
    if why := product_clash(need, offer):
        return r, why
    if is_generic(need) and (_only_broad(need, offer, set(tokenize(offer.title or "")))
                             or _narrow_unnamed(need, offer, set(tokenize(offer.title or "")))):
        noun = _kind_noun(need) or _need_noun(need)
        return r, f"any {noun.split()[-1]}: the listing does not say it is a {noun}"
    if bad := [f for f in title_red_flags(offer, need) if f[0] in RED_REJECT]:
        k, what, phrase = bad[0]
        return r, (f"not an offer: {red_flag_text(k, what, phrase)}" if k in ("wanted", "rental")
                   else f"a part, not the whole item: {red_flag_text(k, what, phrase)}")
    ns, os_ = signature(need.thing), signature(offer.title or "", offer.brand)
    if _family_clash(ns, os_):
        return r, (f"another product ({FAMILY_DISPLAY.get(os_.family or '', os_.family)} vs "
                   f"{FAMILY_DISPLAY.get(ns.family or '', ns.family)})")
    if ns.brand and not ns.models and _line_missing(ns, {w for w in ns.words if w not in ATTRIBUTE_ONLY},
                                                     set(tokenize(offer.title or "")) | ({os_.brand} if os_.brand else set())):
        line = " ".join(w for w in tokenize(need.thing) if w != ns.brand)
        return r, f"another product line (asked: {ns.brand.upper() if len(ns.brand) <= 4 else ns.brand.title()} {line.title()})"
    if ns.models and _is_vehicle_need(need) and not os_.models:
        return r, f"the listing names no model (asked: {' '.join(ns.models).upper()})"
    if ns.models and set(ns.models) <= set(os_.models) and _tiers(ns.variants) != _tiers(os_.variants):
        return r, f"another version ({_pretty(os_)} vs {_pretty(ns)})"     # iphone 13 pro / mini for iphone 13
    if ns.models and os_.models and _model_match(ns, os_) <= 0.2:
        return r, f"different model ({' '.join(os_.models)} vs {' '.join(ns.models)})"
    if ns.models and not os_.models and _older_than_asked(ns, offer.title or ""):
        return r, "an older model (a pre-2020 year, not the one asked)"
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
    generic = is_generic(need)
    # a product line without a model ('lego technic', 'ikea kallax shelf') is a mixed bag like a kind of thing:
    # its loose listings never join (and are never named after) one model's bucket ('GT3' held 2,579 LEGO sets)
    mixed = generic or (need.kind == "product" and not need_sig.models and not need_sig.family
                        and not need_sig.variants)
    if mixed:
        # a kind of thing asked ('road bike', 'puhelin', a tree hunt): a model is a Thing only when the market
        # has it (GENERIC_MIN_THING listings); '3-vaihteinen' x3 or 'Y2K' x2 never set a price band of their own
        # nor does a code without a maker ('3D-paperi' on five tables, 'Di2' on five bikes): only branded models
        for k in [k for k, offs in buckets.items() if len(offs) < GENERIC_MIN_THING or (generic and not sigs[k].brand)]:
            loose += buckets.pop(k)
    things: list[Thing] = []
    for k, offs in buckets.items():
        s = sigs[k]
        name = _pretty(s)
        things.append(Thing(id="t-" + _slug(name), name=name, offers=offs))
    for o in offers:
        if isinstance(o.raw, dict):
            o.raw.pop("generic_thing", None)
    if loose:
        if things and need.kind != "service" and not mixed:
            max(things, key=lambda t: len(t.offers)).offers.extend(loose)   # vague titles join the main thing
        else:
            name = need.thing if need.kind == "service" else _generic_name(need) if generic else _need_name(need, need_sig)
            things.append(Thing(id="t-" + _slug(name), name=name, offers=loose))
            if mixed:
                for o in loose:
                    o.raw["generic_thing"] = True    # judge: a mixed bag of models, no model-level price rules
    things.sort(key=lambda t: len(t.offers), reverse=True)
    for t in things:
        for o in t.offers:
            o.thing_id = t.id
    return things


GENERIC_MIN_THING = 5


def _generic_name(need: Need) -> str:
    """The Thing of a generic hunt: the category's own name ('Road Bikes'), else the words asked."""
    cat = need.category or {}
    if cat.get("label") and (cat.get("source") == "tree" or (cat.get("confidence") or 0) >= 0.6):
        return str(cat["label"])
    return " ".join(w if any(c.isupper() for c in w) else w.capitalize() for w in (need.thing or "").split()) or "Any"


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
