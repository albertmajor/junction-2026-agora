"""CATEGORIES: taxonomy node -> the marketplaces' own category pages.

Why: a generic need ('puhelin', 'sofa', a hunt started from the tree at 'Mobile & Smart Phones') typed into a
marketplace's search box finds only listings whose text has that word ('Samsung A52 128GB' never says 'phone'),
and an English category label ('mobile phones') finds next to nothing on a Finnish site. The marketplace's own
category page lists every listing the sellers filed there: tori.fi 'Matkapuhelimet' has ~7,300, its search for
'mobile' a handful. So a generic or tree hunt reads the category page; a specific one ('iphone 13') keeps the
search.

Sources:
  HAND          hand map for the categories people hunt most (ids copied from the cached menus in
                .cache/taxonomy/menus/, i.e. the sites' own filter links). Schibsted ids are shared by tori.fi,
                blocket.se, finn.no and dba.dk (checked live 14 Nov: product_category=2.93.3217.39 is
                'Matkapuhelimet' / 'Mobiltelefoner' on all four).
  category_map.json
                built offline by `build_auto()` from the same menus: a menu entry joins a tree node when
                taxonomy.classify agrees on it (Schibsted: the Finnish and the Swedish label must land on the same
                node). Used where HAND says nothing.
  GENERIC_NODES English generic nouns (agora.marketplaces.WORDS) -> node, so a typed generic need finds its
                category even when the classifier guesses a neighbour ('stroller' -> Pet Strollers).

API: need_node(need) -> node id | None, page_for(site_key, node_id, query=None) -> CategoryPage | None,
entry_for(node_id) -> (entry, mapped node id, hops) | None, build_auto() -> dict.
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote, quote_plus

HERE = pathlib.Path(__file__).resolve().parent
AUTO_PATH = HERE / "category_map.json"
MENUS = HERE.parent.parent / ".cache" / "taxonomy" / "menus"

SCHIBSTED_HOSTS = {"tori": "www.tori.fi", "blocket": "www.blocket.se", "finn": "www.finn.no", "dba": "www.dba.dk"}
KLEINANZEIGEN = "https://www.kleinanzeigen.de"
MARKTPLAATS = "https://www.marktplaats.nl"

_BIKES = ["2.69.3963.257"]
_SOFAS = ["2.78.7756.8374", "2.78.7756.207", "2.78.7756.206"]
_OUTERWEAR = ["2.71.3941.173", "2.71.3941.178", "2.71.3950.183"]
_CAMERAS = ["2.93.3904.66", "2.93.3904.303", "2.93.3904.502"]
_STROLLERS = ["2.68.3914.9460", "2.68.3914.9461", "2.68.3914.9462", "2.68.3914.9463", "2.68.3914.9464",
              "2.68.3914.9465"]                     # every pram / pushchair category, not 'parts and accessories'
_DINING = ["2.78.5196.213"]

# node id -> where its listings are filed. Keys:
#   schibsted: Schibsted category ids (0.x category, 1.x sub_category, 2.x product_category); several = OR
#   schibsted_q: True = the category is broader than the node: send the node's word as the query too
#                (tori 'Polkupyörät' + q=maantiepyörä for road bikes)
#   kleinanzeigen: path ('/s-handy-telekom/c173'); '{q}' in it = category + query ('/s-wohnzimmer/{q}/k0c88')
#   marktplaats: path ('/l/huis-en-inrichting/banken-bankstellen/')
HAND: dict[str, dict[str, Any]] = {
    # electronics
    "sp:el-4-8-5": {"schibsted": ["2.93.3217.39"], "kleinanzeigen": "/s-handy-telekom/c173", "marktplaats": None},
    "sp:el-4-8-5-2": {"schibsted": ["2.93.3217.39"], "kleinanzeigen": "/s-handy-telekom/c173", "marktplaats": None},
    "sp:el-6-8": {"schibsted": ["2.93.3215.48"], "kleinanzeigen": "/s-tablets-reader/c285"},
    "sp:el-6-6": {"schibsted": ["2.93.3215.43"], "kleinanzeigen": "/s-notebooks/c278"},
    "sp:el-6-3": {"schibsted": ["2.93.3215.44"], "kleinanzeigen": "/s-pcs/c228",
                  "marktplaats": "/l/computers-en-software/desktop-pc-s/"},
    "sp:el-17-1": {"schibsted": ["2.93.3215.45"], "marktplaats": "/l/computers-en-software/monitoren/"},
    "sp:el-19": {"schibsted": ["2.93.3905.63"], "kleinanzeigen": "/s-konsolen/c279"},
    "cpv:37532": {"schibsted": ["2.93.3905.64"]},
    "sp:el-2-2-7": {"schibsted": ["2.93.3906.51"], "marktplaats": "/l/audio-tv-en-foto/koptelefoons/"},
    "m:ipon:fejhallgato-3428fc": {"schibsted": ["2.93.3906.51"], "marktplaats": "/l/audio-tv-en-foto/koptelefoons/"},
    "sp:el-2-2-10": {"schibsted": ["2.93.3906.53"]},
    "sp:el-17-4": {"schibsted": ["2.93.3906.62"], "kleinanzeigen": "/s-tv-video/c175",
                   "marktplaats": "/l/audio-tv-en-foto/televisies/"},
    "sp:co-2": {"schibsted": _CAMERAS, "marktplaats": "/l/audio-tv-en-foto/fotocamera-s-digitaal/"},
    "sp:co-2-2": {"schibsted": _CAMERAS, "marktplaats": "/l/audio-tv-en-foto/fotocamera-s-digitaal/"},
    "sp:co-2-2-7": {"schibsted": ["2.93.3904.303"]},
    "sp:co-2-2-5": {"schibsted": ["2.93.3904.66"]},
    "sp:co-2-2-4": {"schibsted": ["2.93.3904.502"]},
    "sp:co-1-2-1": {"schibsted": ["2.93.3904.503"]},
    "sp:aa-6-12": {"schibsted": ["1.69.3967"], "kleinanzeigen": "/s-wearables/c405"},
    "m:blocket:skrivare-72848b": {"marktplaats": "/l/computers-en-software/printers/"},
    # appliances
    "sp:hg-9-10": {"schibsted": ["2.93.3216.81"]},
    "sp:hg-11-7-4": {"schibsted": ["2.93.3216.506"]},
    "sp:hg-9-8-6": {"schibsted": ["2.93.3907.79"]},
    "sp:hg-11-7-41": {"schibsted": ["2.93.3907.292"]},
    "sp:hg-11-7-20": {"schibsted": ["2.93.3907.72"]},
    "sp:hg-11-7-9": {"schibsted": ["2.93.3907.509"]},
    "sp:hg-11-7-31": {"schibsted": ["2.93.3907.508"]},
    "sp:hg-9-8-1": {"schibsted": ["2.93.3907.510"]},
    "sp:hg-11-7-17-1": {"schibsted": ["2.93.3216.83"]},
    # baby & kids
    "sp:bt-6-3": {"schibsted": _STROLLERS, "kleinanzeigen": "/s-kinderwagen-buggys/c25",
                  "marktplaats": "/l/kinderen-en-baby-s/kinderwagens-en-combinaties/"},
    "sp:bt-6-1": {"schibsted": ["2.68.3911.9446"], "kleinanzeigen": "/s-babyschalen-kindersitze/c21",
                  "marktplaats": "/l/kinderen-en-baby-s/autostoeltjes/"},
    "sp:tg-5": {"schibsted": ["1.68.3912"], "kleinanzeigen": "/s-spielzeug/c23"},
    "sp:fr-1-6": {"schibsted": ["2.68.3916.312"], "marktplaats": "/l/kinderen-en-baby-s/babywiegjes-en-ledikanten/"},
    "sp:fr-7-13": {"schibsted": ["2.68.3916.313"], "marktplaats": "/l/kinderen-en-baby-s/kinderstoelen/"},
    "sp:sg-4-4-3-17": {"schibsted": ["2.69.3963.8375"], "marktplaats": "/l/fietsen-en-brommers/fietsen-kinderfietsjes/"},
    # bikes & sport
    "sp:sg-4-4": {"schibsted": _BIKES, "kleinanzeigen": "/s-fahrraeder/c217"},
    "sp:sg-4-4-3-11": {"schibsted": _BIKES, "schibsted_q": True, "kleinanzeigen": "/s-fahrraeder/{q}/k0c217",
                       "marktplaats": "/l/fietsen-en-brommers/fietsen-racefietsen/"},
    "sp:sg-4-4-3-10": {"schibsted": _BIKES, "schibsted_q": True, "kleinanzeigen": "/s-fahrraeder/{q}/k0c217",
                       "marktplaats": "/l/fietsen-en-brommers/fietsen-mountainbikes-en-atb/"},
    "sp:sg-4-4-3-5": {"schibsted": _BIKES, "schibsted_q": True, "kleinanzeigen": "/s-fahrraeder/{q}/k0c217",
                      "marktplaats": "/l/fietsen-en-brommers/elektrische-fietsen/"},
    "sp:sg-4-4-3-2": {"schibsted": _BIKES, "schibsted_q": True, "kleinanzeigen": "/s-fahrraeder/{q}/k0c217"},
    "sp:sg-4-15": {"schibsted": ["2.69.3963.8376"]},
    "sp:sg-4-17-2-13": {"schibsted": ["2.69.3962.253", "2.69.3962.255"]},
    "sp:sg-4-17-2-13-2": {"schibsted": ["2.69.3962.253"]},
    "sp:sg-4-17-2-13-1": {"schibsted": ["2.69.3962.255"]},
    "sp:sg-4-17-2-17": {"schibsted": ["2.69.3962.252"]},
    "sp:sg-4-2-17": {"schibsted": ["2.69.3964.277"], "marktplaats": "/l/caravans-en-kamperen/tenten/"},
    "sp:sg-4-2-14": {"schibsted": ["2.69.3964.276"]},
    "sp:sg-2-4-2-5": {"schibsted": ["2.69.5166.516"]},
    "sp:sg-2-4-2-2": {"schibsted": ["2.69.5166.286"]},
    "sp:sg-4-7-9": {"schibsted": ["2.69.5164.9770"]},
    "sp:sg-1-12-10": {"schibsted": ["2.69.8346.404", "2.69.8346.405"]},
    # furniture & home
    "sp:fr-22": {"schibsted": _SOFAS, "kleinanzeigen": "/s-wohnzimmer/{q}/k0c88",
                 "marktplaats": "/l/huis-en-inrichting/banken-bankstellen/"},
    "sp:fr-22-3": {"schibsted": ["2.78.7756.207"]},
    "sp:fr-8": {"schibsted": ["2.78.7756.206"]},
    "sp:fr-7-1-1": {"schibsted": ["2.78.7756.210"]},
    "sp:fr-15-6-3": {"schibsted": ["2.78.5196.212"], "marktplaats": "/l/huis-en-inrichting/tafels-salontafels/"},
    "sp:fr-24-1-3": {"schibsted": ["2.78.5196.212"], "marktplaats": "/l/huis-en-inrichting/tafels-salontafels/"},
    "sp:fr-15-6-5": {"schibsted": _DINING, "marktplaats": "/l/huis-en-inrichting/tafels-eettafels/"},
    "m:emag:konyha-asztalok-50c55c": {"schibsted": _DINING, "marktplaats": "/l/huis-en-inrichting/tafels-eettafels/"},
    "m:otto:essgruppen-8cc28c": {"schibsted": ["2.78.5196.211"]},
    "sp:fr-24": {"schibsted": ["2.78.5196.211", "2.78.5196.212", "2.78.5196.213", "2.78.5196.214",
                               "2.78.5196.217"]},
    "sp:fr-12-1": {"schibsted": ["2.78.5196.214"], "marktplaats": "/l/huis-en-inrichting/bureaus/"},
    "sp:fr-12-2": {"schibsted": ["2.78.5196.215"], "marktplaats": "/l/huis-en-inrichting/bureaustoelen/"},
    "sp:fr-7": {"schibsted": ["2.78.5196.216"], "marktplaats": "/l/huis-en-inrichting/stoelen/"},
    "sp:fr-2": {"schibsted": ["2.78.5197.202"], "marktplaats": "/l/huis-en-inrichting/slaapkamer-bedden/"},
    "sp:fr-2-2": {"schibsted": ["2.78.5197.202"], "marktplaats": "/l/huis-en-inrichting/slaapkamer-bedden/"},
    "sp:fr-2-6": {"schibsted": ["2.78.5197.203", "2.78.5197.293"],
                  "marktplaats": "/l/huis-en-inrichting/slaapkamer-matrassen-en-bedbodems/"},
    "sp:fr-4-1": {"schibsted": ["2.78.5198.218"], "marktplaats": "/l/huis-en-inrichting/kasten-kledingkasten/"},
    "sp:fr-19": {"schibsted": ["2.78.8345.219"]},
    "sp:fr-19-1": {"schibsted": ["2.78.8345.219"], "marktplaats": "/l/huis-en-inrichting/kasten-boekenkasten/"},
    "sp:fr-4-5": {"schibsted": ["2.78.8345.221"], "marktplaats": "/l/huis-en-inrichting/kasten-ladekasten/"},
    "sp:fr-9": {"schibsted": ["2.78.8345.224"], "marktplaats": "/l/huis-en-inrichting/kasten-televisiemeubels/"},
    "sp:fr-24-6": {"schibsted": ["2.78.8345.223"], "marktplaats": "/l/huis-en-inrichting/slaapkamer-nachtkastjes/"},
    "sp:hg-13-5": {"schibsted": ["1.78.5181"]},
    "sp:hg-13-5-3": {"schibsted": ["2.78.5181.228"], "marktplaats": "/l/huis-en-inrichting/lampen-vloerlampen/"},
    "sp:hg-13-5-5": {"schibsted": ["2.78.5181.229"], "marktplaats": "/l/huis-en-inrichting/lampen-tafellampen/"},
    "sp:hg-3-57": {"schibsted": ["2.78.5180.231"]},
    "sp:hg-3-47": {"schibsted": ["2.78.5222.299"]},
    # fashion
    "sp:aa-1-10-2": {"schibsted": _OUTERWEAR},
    "sp:aa-1-1-8-2": {"schibsted": _OUTERWEAR},
    "sp:aa-8": {"schibsted": ["1.71.3949"]},
    "sp:aa-8-8": {"schibsted": ["2.69.3940.3984"]},
    "sp:aa-6-11": {"schibsted": ["1.71.3945"]},
    "sp:aa-5-4": {"schibsted": ["2.71.3946.9473"]},
    "sp:lb-1": {"schibsted": ["2.71.3946.9472", "2.69.3964.278"]},
    "sp:aa-1-4": {"schibsted": ["2.71.3941.172"]},
    "sp:aa-1-12-4": {"schibsted": ["2.71.3941.8370", "2.71.3950.8373"]},
    "sp:aa-2-27": {"schibsted": ["2.71.8344.199"]},
    # media & games
    "sp:tg-2-5": {"schibsted": ["1.86.5203"]},
    "sp:me-1": {"schibsted": ["1.86.5209"], "kleinanzeigen": "/s-buecher-zeitschriften/c76"},
}

# English generic nouns (as agora.marketplaces.WORDS spells them) -> node: a typed generic need finds its category
GENERIC_NODES: dict[str, str] = {
    "phone": "sp:el-4-8-5", "mobile phone": "sp:el-4-8-5", "smartphone": "sp:el-4-8-5", "cell phone": "sp:el-4-8-5",
    "tablet": "sp:el-6-8", "laptop": "sp:el-6-6", "monitor": "sp:el-17-1", "tv": "sp:el-17-4",
    "television": "sp:el-17-4", "console": "sp:el-19", "games console": "sp:el-19", "headphones": "sp:el-2-2-7",
    "earbuds": "sp:el-2-2-7", "speaker": "sp:el-2-2-10", "camera": "sp:co-2-2", "lens": "sp:co-1-2-1",
    "smartwatch": "sp:aa-6-12", "printer": "m:blocket:skrivare-72848b",
    "vacuum": "sp:hg-9-10", "vacuum cleaner": "sp:hg-9-10", "coffee machine": "sp:hg-11-7-4",
    "washing machine": "sp:hg-9-8-6", "fridge": "sp:hg-11-7-41", "freezer": "sp:hg-11-7-20",
    "dishwasher": "sp:hg-11-7-9", "microwave": "sp:hg-11-7-31",
    "stroller": "sp:bt-6-3", "baby stroller": "sp:bt-6-3", "pram": "sp:bt-6-3", "pushchair": "sp:bt-6-3",
    "car seat": "sp:bt-6-1", "crib": "sp:fr-1-6", "high chair": "sp:fr-7-13", "toys": "sp:tg-5",
    "bike": "sp:sg-4-4", "bicycle": "sp:sg-4-4", "road bike": "sp:sg-4-4-3-11", "mountain bike": "sp:sg-4-4-3-10",
    "e-bike": "sp:sg-4-4-3-5", "kids bike": "sp:sg-4-4-3-17", "city bike": "sp:sg-4-4-3-2",
    "kick scooter": "sp:sg-4-15", "skis": "sp:sg-4-17-2-13", "snowboard": "sp:sg-4-17-2-17", "tent": "sp:sg-4-2-17",
    "sleeping bag": "sp:sg-4-2-14", "treadmill": "sp:sg-2-4-2-5", "exercise bike": "sp:sg-2-4-2-2",
    "ice skates": "sp:sg-1-12-10",
    "sofa": "sp:fr-22", "couch": "sp:fr-22", "corner sofa": "sp:fr-22-3", "sofa bed": "sp:fr-8",
    "armchair": "sp:fr-7-1-1", "coffee table": "sp:fr-15-6-3", "dining table": "sp:fr-15-6-5",
    "kitchen table": "m:emag:konyha-asztalok-50c55c", "table": "sp:fr-24", "desk": "sp:fr-12-1",
    "office chair": "sp:fr-12-2", "chair": "sp:fr-7", "bed": "sp:fr-2-2", "mattress": "sp:fr-2-6",
    "wardrobe": "sp:fr-4-1", "shelf": "sp:fr-19", "shelving unit": "sp:fr-19", "bookcase": "sp:fr-19-1",
    "dresser": "sp:fr-4-5", "tv stand": "sp:fr-9", "nightstand": "sp:fr-24-6", "lamp": "sp:hg-13-5",
    "floor lamp": "sp:hg-13-5-3", "rug": "sp:hg-3-57", "mirror": "sp:hg-3-47",
    "jacket": "sp:aa-1-10-2", "coat": "sp:aa-1-10-2", "shoes": "sp:aa-8", "sneakers": "sp:aa-8-8",
    "watch": "sp:aa-6-11", "handbag": "sp:aa-5-4", "backpack": "sp:lb-1", "dress": "sp:aa-1-4", "jeans": "sp:aa-1-12-4",
    "sunglasses": "sp:aa-2-27", "board game": "sp:tg-2-5", "books": "sp:me-1",
}

MAX_HOPS = 1          # a node without its own entry may use its parent's (marked inexact: titles must say it)


@dataclass(frozen=True)
class CategoryPage:
    url: str
    node: str            # the node whose entry made this page
    exact: bool          # the page lists exactly the node's kind of thing (relevance trusts the site's filing)
    query: str = ""      # a query sent together with the category ('' = the whole category)
    label: str = ""


@lru_cache(maxsize=1)
def _auto() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(AUTO_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _tax() -> Any | None:
    try:
        from agora import taxonomy
        return taxonomy.load()
    except Exception:
        return None


def entry_for(node_id: str | None) -> tuple[dict[str, Any], str, int] | None:
    """(entry, the node it belongs to, hops up the tree) for this node: its own HAND/auto entry, else its parent's
    (MAX_HOPS). Hand entries win per site over automatic ones."""
    if not node_id:
        return None
    t = _tax()
    nid: str | None = node_id
    if t is not None:
        nid = t.resolve(node_id) or node_id
    for hops in range(MAX_HOPS + 1):
        if not nid:
            return None
        own = {k: v for k, v in (_auto().get(nid) or {}).items() if k != "auto"}
        hand = HAND.get(nid) or {}
        own.update(hand)
        own = {k: v for k, v in own.items() if v is not None}       # HAND None = 'no page here' (blocks auto)
        if any(k in own for k in ("schibsted", "kleinanzeigen", "marktplaats")):
            own["hand"] = sorted(k for k in hand if hand[k] is not None)
            return own, nid, hops
        if t is None:
            return None
        try:
            i = t._i(nid)
        except KeyError:
            return None
        p = t.parent[i]
        if p < 0 or t.parent[p] < 0:          # never fall back to a root ('Electronics'): too broad
            return None
        nid = t.ids[p]
    return None


def _schibsted_url(host: str, ids: list[str], query: str = "") -> str:
    names = {"0": "category", "1": "sub_category", "2": "product_category"}
    parts = [f"{names.get(i.split('.')[0], 'product_category')}={i}" for i in ids]
    if query:
        parts.append("q=" + quote_plus(query))
    return f"https://{host}/recommerce/forsale/search?" + "&".join(parts)


def page_for(site_key: str, node_id: str | None, query: str = "") -> CategoryPage | None:
    """This site's category page for the node (None = no category known for this site). `query` = the node's
    word in the site's language, sent along only where the category is broader than the node."""
    got = entry_for(node_id)
    if got is None:
        return None
    entry, nid, hops = got
    hand = set(entry.get("hand") or ())

    def exact_for(key: str) -> bool:      # automatic (classifier-made) entries are never trusted on their own
        return hops == 0 and key in hand
    if site_key in SCHIBSTED_HOSTS and entry.get("schibsted"):
        q = query if entry.get("schibsted_q") else ""
        if entry.get("schibsted_q") and not q:
            return None
        return CategoryPage(_schibsted_url(SCHIBSTED_HOSTS[site_key], list(entry["schibsted"]), q), nid,
                            exact_for("schibsted"), q)
    if site_key == "kleinanzeigen" and entry.get("kleinanzeigen"):
        path = str(entry["kleinanzeigen"])
        q = ""
        if "{q}" in path:
            if not query:
                return None
            q = query
            path = path.replace("{q}", "-".join(quote(w) for w in query.split()))
        return CategoryPage(KLEINANZEIGEN + path, nid, exact_for("kleinanzeigen"), q)
    if site_key == "marktplaats" and entry.get("marktplaats"):
        return CategoryPage(MARKTPLAATS + str(entry["marktplaats"]), nid, exact_for("marktplaats"))
    return None


# --------------------------------------------------------------------------- the need's node

_NODE_RE: re.Pattern[str] | None = None


def generic_noun(text: str) -> str | None:
    """The longest GENERIC_NODES noun in the text ('used baby stroller' -> 'baby stroller'), plural tolerated."""
    global _NODE_RE
    if _NODE_RE is None:
        words = sorted(GENERIC_NODES, key=len, reverse=True)
        _NODE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")(?:s|es)?\b", re.I)
    m = _NODE_RE.search(text or "")
    return m.group(1).lower() if m else None


def need_node(need: Any) -> str | None:
    """The node whose category pages a generic need reads: the tree node of a hunt started there; else the node
    of its generic noun (GENERIC_NODES, translated from any language by agora.marketplaces); else the classified
    node when the classifier was sure. None = no category."""
    cat = getattr(need, "category", None) or {}
    if cat.get("source") == "tree" and cat.get("id"):
        return str(cat["id"])
    try:
        from agora import marketplaces
        noun = marketplaces.english_noun(getattr(need, "thing", "") or "")
    except Exception:
        noun = generic_noun(getattr(need, "thing", "") or "")
    if noun and noun in GENERIC_NODES:
        return GENERIC_NODES[noun]
    if cat.get("id") and float(cat.get("confidence") or 0) >= 0.9:
        return str(cat["id"])
    return None


def node_label(node_id: str | None, lang: str = "en") -> str:
    t = _tax()
    if t is None or not node_id:
        return ""
    try:
        return t.label(t._i(node_id), lang)
    except Exception:
        return ""


def related(a: str | None, b: str | None) -> bool:
    """a == b, or b lies under a (a 'Cycling' need is answered by the 'Road Bikes' page too)."""
    if not a or not b:
        return False
    if a == b:
        return True
    t = _tax()
    if t is None:
        return False
    try:
        i, j = t._i(a), t._i(b)
    except KeyError:
        return False
    return i in t.path_idx(j)


# --------------------------------------------------------------------------- automatic map from the menus

_SKIP = re.compile(r"\b(?:muu|muut|övrig\w*|tarvikke\w*|tillbehör|osat|delar|reservdelar|varaosat|zubeh\w*|"
                   r"accessoires|onderdelen|overige|toebehoren|teile|sonstige)\b|tarvikkeet|tillbehör|zubehoer",
                   re.I)


def build_auto(menus: pathlib.Path = MENUS, min_conf: float = 0.8) -> dict[str, dict[str, Any]]:
    """Menu entries -> nodes with taxonomy.classify; writes category_map.json. Offline (cached menus only).
    Schibsted ids join a node only when the Finnish (tori) and the Swedish (blocket) labels agree."""
    from agora import taxonomy as T
    out: dict[str, dict[str, Any]] = {}

    def items(name: str) -> list[dict]:
        try:
            return json.loads((menus / f"{name}.json").read_text())["items"]
        except (OSError, ValueError, KeyError):
            return []

    def node(label: str, lang: str) -> str | None:
        if _SKIP.search(label):
            return None
        c = T.classify(label, lang=lang)
        if not c or (c.get("confidence") or 0) < min_conf or c.get("id") in ("electronics", "fashion"):
            return None
        if T.node(c["id"]) is None or T.node(c["id"])["kind"] not in ("product", "vehicle"):
            return None
        return str(c["id"])

    sv = {re.search(r"=([\d.]+)", x["url"]).group(1): x["path"][-1] for x in items("blocket")
          if re.search(r"=([\d.]+)", x.get("url") or "")}
    for x in items("tori"):
        m = re.search(r"=([\d.]+)", x.get("url") or "")
        if not m or m.group(1).startswith("0."):
            continue
        cid = m.group(1)
        a = node(x["path"][-1], "fi")
        b = node(sv.get(cid, ""), "sv") if sv.get(cid) else None
        if a and a == b:
            ids = out.setdefault(a, {}).setdefault("schibsted", [])
            if cid not in ids:
                ids.append(cid)
    for site, lang, host in (("kleinanzeigen", "de", "kleinanzeigen.de"), ("marktplaats", "nl", "marktplaats.nl")):
        for x in items(site):
            url = x.get("url") or ""
            if host not in url or len(x["path"]) < (1 if site == "kleinanzeigen" else 2):
                continue
            n = node(x["path"][-1], lang)
            if n:
                out.setdefault(n, {}).setdefault(site, url.split(host, 1)[1])
    for v in out.values():         # a node filed in several product categories keeps the most specific ones
        if len(v.get("schibsted") or []) > 1 and any(i.startswith("2.") for i in v["schibsted"]):
            v["schibsted"] = [i for i in v["schibsted"] if i.startswith("2.")]
        v["auto"] = True
    AUTO_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True))
    _auto.cache_clear()
    return out
