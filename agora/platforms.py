"""ITEM + PLATFORM: 'gta 6 ps5' is the GTA 6 game for a PS5, not a PS5; 'iphone 15 case' is a case for an iPhone 15,
not an iPhone; 'sony fe 50mm lens' is a 50 mm lens for Sony's E-mount, not a Sony camera.

Owner, 15 Nov: searched "gta 6 ps5" wanting the game disc. The hunt read it as a console (PS5 in the words), kept
PS5 consoles and threw the game discs out as 'too cheap to trust' against console prices.

Pure and offline. `split(text)` finds a platform / device qualifier next to another item and says what the item
is; agora.need stores it on the Need (`for_platform`, `item_kind`, `prefer`), agora.resolve judges each listing
against it (`game_match`, `platforms_in`, `compatible`), agora.judge prices games as games, agora.intent asks
'just the game or a PS5 bundle?' when the words leave it open.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    key: str          # 'ps5', 'xbox-series', 'switch', 'iphone', 'sony-e' ...
    label: str        # 'PS5', 'Xbox Series X|S', 'iPhone', 'Sony E-mount'
    kind: str         # console | pc | phone | tablet | laptop | mount
    pattern: str      # regex on folded lower-case text; group 1 / 2 = model number / tier where the family has them


# most specific first: 'xbox series x' before 'xbox', 'switch 2' before 'switch'
PLATFORMS: tuple[Platform, ...] = (
    Platform("ps5", "PS5", "console", r"(?:sony\s+)?(?:ps\s?-?5|playstation\s?-?5|play\s?station\s?5)(?!\d)"),
    Platform("ps4", "PS4", "console", r"(?:sony\s+)?(?:ps\s?-?4|playstation\s?-?4|play\s?station\s?4)(?!\d)"),
    Platform("ps3", "PS3", "console", r"(?:ps\s?-?3|playstation\s?-?3)(?!\d)"),
    Platform("xbox-series", "Xbox Series X|S", "console",
             r"xbox\s+series\s+(?:x\s*(?:/|\||&|and|or|-)?\s*s\b|x\b|s\b)|xbox\s+series\b|\bxsx\b|xbox\s+sx\b"),
    Platform("xbox-one", "Xbox One", "console", r"xbox\s+one\b"),
    Platform("xbox-360", "Xbox 360", "console", r"xbox\s+360\b"),
    Platform("xbox", "Xbox", "console", r"\bxbox\b"),
    Platform("switch-2", "Nintendo Switch 2", "console", r"(?:nintendo\s+)?\bswitch\s?-?2(?!\d)|\bns2\b"),
    Platform("switch", "Nintendo Switch", "console", r"(?:nintendo\s+)?\bswitch\b(?:\s+(?:oled|lite)\b)?|\bnsw\b"),
    Platform("pc", "PC", "pc", r"\bpc\b(?!\s?-?(?:case|kotelo|kuori))|\bsteam\b(?!\s?deck)"),
    Platform("iphone", "iPhone", "phone", r"\biphone\s?(\d{1,2}e?|se|x[rs]?)\b(?:\s?(pro\s?max|pro|plus|max|mini)\b)?"),
    Platform("galaxy", "Samsung Galaxy", "phone",
             r"(?:samsung\s+)?\bgalaxy\s+([sazm]\s?\d{1,2}|z\s?(?:fold|flip)\s?\d)\b(?:\s?(ultra|plus|\+|fe|edge)\b)?"),
    Platform("pixel", "Google Pixel", "phone", r"(?:google\s+)?\bpixel\s?(\d{1,2}a?)\b(?:\s?(pro\s?xl|pro\s?fold|pro|xl))?"),
    Platform("ipad", "iPad", "tablet", r"\bipad\b(?:\s+(pro|air|mini))?(?:\s?(\d{1,2}(?:[.,]\d)?))?"),
    Platform("macbook", "MacBook", "laptop", r"\bmacbook\b(?:\s+(air|pro))?"),
    Platform("sony-e", "Sony E-mount", "mount", r"\bsony\s+(?:fe|e)\b(?:[-\s]?mount)?|\b(?:fe|e)[-\s]?mount\b"),
    Platform("canon-rf", "Canon RF", "mount", r"\bcanon\s+rf\b(?!-?s\b)|\brf[-\s]?mount\b"),
    Platform("canon-ef", "Canon EF", "mount", r"\bcanon\s+ef(?:-?s)?\b|\bef(?:-s)?[-\s]?mount\b"),
    Platform("nikon-z", "Nikon Z", "mount", r"\bnikon\s+z\b(?!\s?\d)|\bnikkor\s+z\b|\bz[-\s]?mount\b"),
    Platform("nikon-f", "Nikon F", "mount", r"\bnikon\s+f\b(?!\s?\d)|\bf[-\s]?mount\b"),
    Platform("fuji-x", "Fujifilm X", "mount", r"\bfuji(?:film)?\s+x\b(?![-\s]?(?:t|e|s|h|pro|a)?\d)|\bx[-\s]?mount\b|\bxf\b"),
    Platform("mft", "Micro Four Thirds", "mount", r"micro\s+four\s+thirds|\bm4/3\b|\bmft\b|\bm43\b"),
    Platform("l-mount", "L-mount", "mount", r"\bl[-\s]?mount\b"),
)
BY_KEY = {p.key: p for p in PLATFORMS}
_RX = {p.key: re.compile(p.pattern, re.I) for p in PLATFORMS}
CONSOLE_KEYS = {p.key for p in PLATFORMS if p.kind in ("console", "pc")}
FAMILY = {"ps5": "playstation", "ps4": "playstation", "ps3": "playstation", "xbox-series": "xbox", "xbox-one": "xbox",
          "xbox-360": "xbox", "xbox": "xbox", "switch-2": "nintendo", "switch": "nintendo", "pc": "pc"}


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower().replace("ß", "ss"))
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("ł", "l").replace("ø", "o").replace("æ", "ae")
    return re.sub(r"\s+", " ", t)


# ---------------------------------------------------------------- words

# a game, in the languages the marketplaces speak (a 'disc' alone next to a console is its Disc Edition)
GAME_WORDS = re.compile(
    r"\b(?:video\s?games?|games?|gaming\s+title|peli|pelit|pelin|pelejä|peleja|\w+peli|spiel|spiele|spil|spillet|spel|"
    r"spelet|gra|gry|jeu|jeux|juego|juegos|gioco|giochi|videospiel\w*|tv-?spel)\b", re.I)
DISC_WORDS = re.compile(r"\b(?:discs?|disks?|levy|levyllä|levylla|levynä|levyna|levyversio|fyysinen|fyysisenä|"
                        r"physical|physische|fysisk|fysieke|plyta|płyta|boxed|cd|blu-?ray)\b", re.I)
DIGITAL_WORDS = re.compile(r"\b(?:digital|digitaalinen|digi|download\w*|code|codes|koodi|lataus\w*|key|cd-?key|"
                           r"avain|psn\s+code|e-?code|voucher)\b", re.I)
BUNDLE_WORDS = re.compile(r"\b(?:bundle|bundel|paketti|pakke|paket|set|console|konsoli\w*|konsole\w*|konsol\w*|"
                          r"konsola)\b", re.I)
# a console's own words: 'ps5 slim', 'ps5 1tb', 'switch oled' are the console
CONSOLE_REST = re.compile(r"^(?:\s|slim|pro|digital|disc|disk|edition|editio|oled|lite|white|black|valkoinen|musta|"
                          r"\d+\s?(?:gb|tb)|console|konsoli|konsole|used|new|uusi|kaytetty|käytetty|gebraucht)*$", re.I)

# well-known game names (folded): a title next to a platform is a game even without the word 'game'
FRANCHISES = (
    r"gta|grand\s+theft\s+auto|fifa|ea\s+(?:sports\s+)?fc|fc\s?\d{2}|call\s+of\s+duty|\bcod\b|zelda|mario(?:\s+kart|\s+party)?|"
    r"spider-?\s?man|pokemon|minecraft|fortnite|assassin'?s\s+creed|battlefield|red\s+dead(?:\s+redemption)?|"
    r"god\s+of\s+war|horizon|last\s+of\s+us|elden\s+ring|hogwarts\s+legacy|cyberpunk|gran\s+turismo|forza|halo|"
    r"nba\s?2k\d*|madden|nhl\s?\d*|f1\s?\d*|diablo|resident\s+evil|final\s+fantasy|street\s+fighter|"
    r"mortal\s+kombat|tekken|the\s+sims|sims\s?\d|animal\s+crossing|smash\s+bros|metroid|kirby|donkey\s+kong|"
    r"ghost\s+of\s+(?:tsushima|yotei)|uncharted|ratchet|astro\s?bot|death\s+stranding|starfield|star\s+wars|"
    r"crash\s+bandicoot|sonic|monster\s+hunter|splatoon|xenoblade|fire\s+emblem|dragon\s+ball|need\s+for\s+speed|"
    r"far\s+cry|watch\s?dogs|tomb\s+raider|borderlands|doom|wolverine|stellar\s+blade|black\s+myth|silent\s+hill|"
    r"metal\s+gear|persona\s?\d*|yakuza|like\s+a\s+dragon|ea\s+sports|pga\s+tour|wwe\s?2k\d*|it\s+takes\s+two|"
    r"split\s+fiction|hollow\s+knight|baldur'?s\s+gate|witcher|skyrim|fallout|lego\s+\w+\s+(?:saga|game)")
FRANCHISE_RX = re.compile(rf"\b(?:{FRANCHISES})", re.I)
# 'battlefield 6', 'nba 2k26', 'f1 25': a name and a number (a storage size or a year of make is no title)
TITLE_NUMBER = re.compile(r"^[a-z][a-z'\-]{2,}(?:\s+[a-z][a-z'\-]+){0,3}\s+(?:\d{1,2}|[ivx]{1,4}|20[12]\d|2k\d{2})$")

# what a thing FOR a device is, per kind (any language); the canonical name is the item_kind
ACCESSORY_KINDS: dict[str, str] = {
    "screen protector": r"screen\s?protectors?|panssarilas\w*|suojalas\w*|naytonsuoja\w*|panzerglas\w*|schutzfolie\w*|"
                        r"skarmskydd\w*|skaermbeskytt\w*|tempered\s+glass|screenprotector\w*|displayschutz\w*",
    "case": r"cases?|covers?|\w*kuori|\w*kuoret|\w*kotelo\w*|\w*hulle\w*|\w*huelle\w*|etui\w*|\w*skal|fodral\w*|deksel\w*|"
            r"hoes|hoesje\w*|bumper|folio|futera\w*|obudow\w*|smart\s?folio|magsafe\s+case",
    "charger": r"chargers?|\w*laturi\w*|ladegerat\w*|ladegeraet\w*|netzteil\w*|laddare|oplader\w*|lader|ladowark\w*|"
               r"power\s+adapters?|power\s+supply|virtalahde\w*|magsafe\s?\d?|usb-?c\s+(?:power\s+)?adapter|"
               r"\d{2,3}\s?w\s+(?:usb-?c|adapter|charger)",
    "cable": r"cables?|\w*kaapeli\w*|\w*kabel|cords?|johto\w*",
    "lens": r"lens|lenses|objektiivi\w*|objektiv\w*|objectie\w*|obiektyw\w*|optiikka\w*|linssi\w*|"
            r"\d{1,3}(?:\s?[-–]\s?\d{1,3})?\s?mm\b[^,|]{0,20}\bf\s?/?\s?\d|\bf\s?/?\s?\d(?:[.,]\d)?\b[^,|]{0,20}\d{2,3}\s?mm",
    "strap": r"straps?|bands?|\w*ranneke\w*|armband\w*|\w*hihna\w*",
    "stand": r"stands?|\w*teline\w*|docks?|docking\s+station|\w*telakka\w*|stander|halter|holder|hallare",
    "bag": r"bags?|sleeves?|\w*laukku\w*|\w*tasche\w*|\w*vaska\w*|backpack|reppu\w*|rucksack",
    "battery": r"batter(?:y|ies)|\w*akku\w*|batteri\w*|accu",
    "keyboard": r"keyboards?|\w*nappaimisto\w*|tastatur\w*|magic\s+keyboard",
    "adapter": r"adapters?|adapteri\w*|sovitin\w*|hubs?|dongle|mount\s+adapter|adapterring",
    "stylus": r"stylus|pencil|kyna\w*|stift",
}
_KIND_RX = {k: re.compile(rf"(?<![\w-])(?:{v})(?![\w-])", re.I) for k, v in ACCESSORY_KINDS.items()}
_KIND_WORD_EN = {"screen protector": "screen protector", "case": "case", "charger": "charger", "cable": "cable",
                 "lens": "lens", "strap": "strap", "stand": "stand", "bag": "bag", "battery": "battery",
                 "keyboard": "keyboard", "adapter": "adapter", "stylus": "stylus"}
# which accessory kinds a device kind takes (a lens is for a camera mount; a case for a phone or a tablet)
KIND_FITS = {"phone": {"screen protector", "case", "charger", "cable", "strap", "stand", "battery", "adapter"},
             "tablet": {"screen protector", "case", "charger", "cable", "stand", "keyboard", "adapter", "stylus", "bag"},
             "laptop": {"screen protector", "case", "charger", "cable", "stand", "bag", "battery", "keyboard", "adapter"},
             "mount": {"lens", "adapter"}}
FOCAL = re.compile(r"(?<![\d.,])(\d{1,3})(?:\s?[-–]\s?(\d{1,3}))?\s?mm\b", re.I)


@dataclass
class Split:
    item: str                 # the item itself, as typed ('gta 6', 'case', '50mm lens')
    platform: str             # the platform / device as typed ('ps5', 'iphone 15', 'sony fe')
    key: str                  # Platform.key
    item_kind: str            # 'game' or an accessory kind ('case', 'charger', 'lens' ...)
    prefer: list[str] = field(default_factory=list)   # 'disc' | 'digital'
    ambiguous: bool = False   # the words could also mean a bundle ('ps5 gta': no 'game' word, platform first)
    search: str = ""          # the words a search engine / marketplace gets ('gta 6 ps5', 'iphone 15 case')


def find(text: str) -> tuple[Platform, re.Match[str]] | None:
    """The first (most specific) platform named in the text, with its match."""
    low = fold(text)
    best: tuple[Platform, re.Match[str]] | None = None
    for p in PLATFORMS:
        m = _RX[p.key].search(low)
        if m and (best is None or m.start() < best[1].start() or
                  (m.start() == best[1].start() and len(m.group(0)) > len(best[1].group(0)))):
            best = (p, m)
    return best


def platforms_in(title: str) -> list[tuple[Platform, re.Match[str]]]:
    """Every platform the text names (overlaps resolved: 'xbox series x' is not also a bare 'xbox')."""
    low = fold(title)
    taken: list[tuple[int, int]] = []
    out: list[tuple[Platform, re.Match[str]]] = []
    for p in PLATFORMS:
        for m in _RX[p.key].finditer(low):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((p, m))
    return out


def _clean(text: str) -> str:
    t = re.sub(r"[,;:!?()\[\]]", " ", text)
    t = re.sub(r"\b(?:for|til|till|fur|für|voor|do|na|pour|per|para|varten|sopii|to|the|a|an|my|new|used|uusi|"
               r"kaytetty|käytetty|gebraucht|cheap|buy|osta|halpa)\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -/+&")


def split(text: str) -> Split | None:
    """'gta 6 ps5' -> Split(item 'gta 6', platform 'ps5', kind 'game'); 'iphone 15 case' -> (case, iphone 15);
    'sony fe 50mm lens' -> (50mm lens, sony fe); None when the words are the device itself ('ps5', 'ps5 slim',
    'ps5 console', 'iphone 15 pro 256gb') or a bundle is asked ('ps5 gta 6 bundle')."""
    low = fold(text)
    got = find(low)
    if got is None:
        return None
    p, m = got
    plat_typed = m.group(0).strip()
    rest = (low[:m.start()] + " " + low[m.end():]).strip()
    if p.kind in ("console", "pc"):
        return _game_split(low, rest, p, plat_typed, m)
    return _accessory_split(rest, p, plat_typed, m.start())


def _game_split(low: str, rest: str, p: Platform, plat: str, m: re.Match[str]) -> Split | None:
    prefer = []
    if DISC_WORDS.search(rest):
        prefer.append("disc")
    if DIGITAL_WORDS.search(rest):
        prefer.append("digital")
    game_word = bool(GAME_WORDS.search(rest))
    item = GAME_WORDS.sub(" ", rest)
    item = DISC_WORDS.sub(" ", item)
    item = DIGITAL_WORDS.sub(" ", item)
    if re.search(r"\bversion\b|\bversio\b|\bedition\b", item) and (game_word or FRANCHISE_RX.search(item)):
        item = re.sub(r"\b(?:version|versio|edition)\b", " ", item)
    item = _clean(item)
    if BUNDLE_WORDS.search(item):
        return None                         # 'ps5 gta 6 bundle', 'ps5 console gta': the console is asked
    if not item:
        if game_word:
            item = "games"                  # 'ps5 games', 'switch pelit': any game for it
        else:
            return None                     # 'ps5', 'ps5 disc', 'ps5 digital'
    elif CONSOLE_REST.fullmatch(item) and not game_word:
        return None                         # 'ps5 slim 1tb', 'switch oled white'
    named = bool(FRANCHISE_RX.search(item)) or bool(TITLE_NUMBER.fullmatch(item))
    if not (game_word or named or prefer and len(item) > 2):
        return None                         # 'ps5 controller' / 'xbox headset' stay with the console rules
    if re.fullmatch(r"(?:controller|ohjain|headset|kuulokkeet|gamepad|dualsense|joy-?con)s?", item):
        return None
    # 'ps5 gta': no game word, the platform first, a bare name: it could be a PS5 with GTA (the intent asks)
    ambiguous = not game_word and not prefer and m.start() == 0 and not re.search(r"\d|\b[ivx]{1,4}$", item)
    return Split(item=item, platform=plat, key=p.key, item_kind="game", prefer=prefer, ambiguous=ambiguous,
                 search=re.sub(r"\s+", " ", f"{plat} games" if item == "games" else f"{item} {plat}").strip())


def _accessory_split(rest: str, p: Platform, plat: str, at: int) -> Split | None:
    fits = KIND_FITS.get(p.kind, set())
    kind = None
    for k in _KIND_RX:
        if k in fits and _KIND_RX[k].search(rest):
            kind = k
            break
    if kind is None and p.kind == "mount" and FOCAL.search(rest):
        kind = "lens"                       # 'sony fe 50mm': a focal length on a mount is a lens
    if kind is None:
        return None                         # 'iphone 15 pro 256gb' is the phone
    item = _clean(rest)
    if not item:
        return None
    return Split(item=item, platform=plat, key=p.key, item_kind=kind,
                 search=re.sub(r"\s+", " ", f"{plat} {item}").strip())


# ---------------------------------------------------------------- games: does a title name the game asked?

_ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_ALIASES = (
    (r"\bgrand\s+theft\s+auto\b", "gta"), (r"\bcall\s+of\s+duty\b", "cod"),
    (r"\b(?:ea\s*)?(?:sports\s+)?fc\s?(?=\d)", "fc "), (r"\bea\s+sports\s+fc\b", "fc"), (r"\bea\s+fc\b", "fc"),
    (r"\bfifa\s?(?=\d)", "fc "), (r"\bthe\s+legend\s+of\s+zelda\b", "zelda"), (r"\bspider\s*-?\s*man\b", "spiderman"),
    (r"\bred\s+dead\s+redemption\b", "rdr"), (r"\bthe\s+last\s+of\s+us\b", "last of us"),
    (r"\bassassin'?s\s+creed\b", "assassins creed"), (r"\bpokémon\b", "pokemon"),
    (r"\bmarvel'?s\s+", ""), (r"\btom\s+clancy'?s\s+", ""),
)
_NO_ROMAN_BEFORE = {"series", "xbox", "edition", "mark", "the", "s", "x", "and", "ja", "og", "und"}


@functools.lru_cache(maxsize=20000)
def game_norm(text: str) -> str:
    """Folded, aliases unified ('Grand Theft Auto VI' / 'GTA6' / 'gta vi' -> 'gta 6'; 'EA Sports FC 25' /
    'FIFA 25' -> 'fc 25')."""
    t = fold(text)
    t = re.sub(r"[™®:’'`´]", lambda m: "'" if m.group(0) in "’'`´" else " ", t)
    t = re.sub(r"[_|/–—]", " ", t)
    for pat, rep in _ALIASES:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b(gta|rdr|cod|fc|ff)(\d)", r"\1 \2", t)          # 'gta6', 'fc25'
    t = re.sub(r"\b(\d{1,2})([a-z]{3,})\b", r"\1 \2", t)          # 'GTA 6voor' (marktplaats)
    t = re.sub(r"-", " ", t)
    toks = re.findall(r"[a-z0-9']+|\+|&", t)
    out: list[str] = []
    for tok in toks:
        if tok in _ROMAN and out and re.fullmatch(r"[a-z']{2,}", out[-1]) and out[-1] not in _NO_ROMAN_BEFORE:
            out.append(str(_ROMAN[tok]))
        else:
            out.append(tok)
    return " ".join(out)


def game_match(item: str, title: str) -> tuple[bool, str | None]:
    """(the title names the game asked, the other game of the same name it names instead or None).
    'gta 6' ~ 'Grand Theft Auto VI', 'GTA6 PS5'; 'Grand Theft Auto V' -> (False, 'GTA 5')."""
    if item in ("games", "game"):
        return True, None
    it, tt = game_norm(item), game_norm(title)
    if not it:
        return True, None
    if re.search(rf"(?<![\w']){re.escape(it)}(?![\w'])", tt):
        # 'gta 6' must not be the start of 'fc 26' style numbers: the phrase ends at a word boundary already
        return True, None
    head = re.match(r"^(.*?)\s*(\d{1,4})$", it)
    if head and head.group(1):
        h = head.group(1)
        if (o := re.search(rf"(?<![\w']){re.escape(h)}\s+(\d{{1,4}})(?![\w'])", tt)) and o.group(1) != head.group(2):
            return False, f"{h.upper() if len(h) <= 4 else h.title()} {o.group(1)}"
    # every word of the asked name, in any order ('mario kart' ~ 'Kart Mario 8 Deluxe' is rare; titles shuffle words
    # only when a number is not involved)
    words = it.split()
    if not head and len(words) >= 2 and all(re.search(rf"(?<![\w']){re.escape(w)}(?![\w'])", tt) for w in words):
        return True, None
    return False, None


def label_of(key: str | None) -> str:
    p = BY_KEY.get(key or "")
    return p.label if p else (key or "")


def compatible(asked: str, named: str) -> bool:
    """A listing for `named` serves a need for `asked` (Platform keys): the same one, a family word for it
    ('xbox' for Series X), a Switch game on a Switch 2."""
    if asked == named:
        return True
    if "xbox" in (asked, named) and FAMILY.get(asked) == FAMILY.get(named) == "xbox":
        return True
    if asked == "switch-2" and named == "switch":
        return True
    return False


def item_title(item: str, platform: str) -> str:
    """'gta 6', 'ps5' -> 'GTA 6 for PS5' (display)."""
    words = []
    for w in item.split():
        words.append(w.upper() if (len(w) <= 3 and w.isalpha() and w not in ("for", "the", "of", "and")) or
                     w in ("fifa", "pubg", "wwe", "nba", "nhl", "ufc") or
                     re.fullmatch(r"[a-z]{1,3}\d+", w) else w.capitalize() if w.isalpha() else w)
    p = find(platform)
    return f"{' '.join(words)} for {p[0].label if p else platform.upper()}"


# ---------------------------------------------------------------- devices: which model a title is for

_MORE = re.compile(r"\s*(?:/|&|,|\+|\band\b|\bja\b|\bund\b|\bog\b|\boch\b|\ben\b)\s*"
                   r"(?:(?:iphone|galaxy|pixel)\s?)?(\d{1,2}e?|[a-z]?\d{1,2}|air|pro)\b"
                   r"(?:\s?(pro\s?max|pro|plus|max|mini|ultra|fe)\b)?")


def device_mentions(title: str, key: str) -> list[tuple[str | None, str | None]]:
    """(model, tier) for every mention of this device family: 'iPhone 13/14/15 Pro' -> [('13', None),
    ('14', None), ('15', 'pro')]; 'MacBook Air/Pro' -> [(None, 'air'), (None, 'pro')]."""
    low = fold(title)
    rx = _RX[key]
    out: list[tuple[str | None, str | None]] = []
    for m in rx.finditer(low):
        groups = [g for g in m.groups()] + [None, None]
        model, tier = (groups[0], groups[1]) if key not in ("macbook",) else (None, groups[0])
        if key == "ipad":
            model, tier = groups[1], groups[0]
        out.append((_norm_model(model), _norm_tier(tier)))
        tail = low[m.end():m.end() + 40]
        pos = 0
        while (c := _MORE.match(tail, pos)) is not None:
            pos = c.end()
            if key == "macbook":
                out.append((None, _norm_tier(c.group(1))))
            elif c.group(1) in ("air", "pro"):
                out.append((out[-1][0], _norm_tier(c.group(1))))
            else:
                out.append((_norm_model(c.group(1)), _norm_tier(c.group(2))))
    return out


def _norm_model(m: str | None) -> str | None:
    return re.sub(r"\s+", "", m).lower() if m else None


def _norm_tier(t: str | None) -> str | None:
    if not t:
        return None
    t = re.sub(r"\s+", "", t.lower())
    return {"+": "plus", "promax": "pro max"}.get(t, t)


def device_title(platform: str) -> str:
    """'iphone 15' -> 'iPhone 15', 'galaxy s24 ultra' -> 'Samsung Galaxy S24 Ultra', 'macbook air' -> 'MacBook Air',
    'sony fe' -> 'Sony E-mount', 'ps5' -> 'PS5'."""
    got = find(platform)
    if got is None:
        return platform
    p = got[0]
    model, tier = (device_mentions(platform, p.key) or [(None, None)])[0] if p.kind in ("phone", "tablet", "laptop") \
        else (None, None)
    m = (model or "").upper() if model and not model.isdigit() else (model or "")
    return re.sub(r"\s+", " ", f"{p.label} {m} {(tier or '').title()}").strip()


def kind_hit(kind: str, title: str) -> re.Match[str] | None:
    rx = _KIND_RX.get(kind)
    return rx.search(fold(title)) if rx is not None else None


def kind_word(kind: str) -> str:
    return _KIND_WORD_EN.get(kind, kind)
