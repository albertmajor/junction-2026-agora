"""Which categories can start a hunt, and which are only shelves to browse (Junction 2026).

Owner, 14 Nov: clicking "Lifestyle Services" hunted for the literal words and showed junk. A hunt needs a
concrete thing or service a person buys ("Gunsmith", "City bikes", "Wedding photographer", "iPhone 15");
groupings ("Lifestyle Services", "Personal, Family & Care Services", "Other ...", "Supplies", procurement
wording) open a category page instead.

Pure functions, no tree access: the build (scripts/build_taxonomy.py) stores the verdict per node in tree.json
("h": 0 + "b": reason for browse-only nodes); the loader falls back to the same rules for an older tree.
"""
from __future__ import annotations

import re

# words that name a KIND of offer, not the thing itself ("X services", "X supplies", "X accessories")
GENERIC_HEADS = {
    "service", "services", "product", "products", "supply", "supplies", "equipment", "equipments", "accessory",
    "accessories", "item", "items", "good", "goods", "article", "articles", "material", "materials", "thing",
    "things", "stuff", "provider", "providers", "solution", "solutions", "activity", "activities", "part", "parts",
    "essentials", "gear", "categories", "category", "options", "offers", "deals", "needs", "resources",
}
# modifiers that say nothing about what you get ("Lifestyle", "General", "Personal", "Professional")
ABSTRACT = {
    "lifestyle", "general", "other", "others", "miscellaneous", "misc", "various", "related", "specialist",
    "specialists", "specialised", "specialized", "special", "specialty", "personal", "professional", "business",
    "household", "family", "consumer", "consumers", "leisure", "auxiliary", "ancillary", "associated", "assorted",
    "basic", "everyday", "wellbeing", "wellness", "community", "social", "hospitality",
    "recreation", "recreational", "entertainment", "commercial", "industrial", "technical", "creative", "local",
    "domestic", "public", "private", "support", "care", "health", "healthcare", "beauty", "medical", "lifestyles",
    "more", "extra", "extras", "additional", "selected", "popular", "featured", "new", "top", "best", "essential",
    "premium", "quality", "standard", "custom", "complete", "full", "mixed", "combined", "multi", "all", "any",
    "incl", "including", "excl", "excluding", "nec", "n", "e", "c", "etc", "type", "types", "kind", "kinds",
    "online", "digital", "virtual", "living", "life", "home", "homes", "house", "people", "person", "individual",
}
STOP = {"and", "or", "the", "of", "for", "with", "a", "an", "in", "on", "to", "by", "from", "at", "as", "via",
        "&", "+", "your", "you", "our"}
# two abstract words that together name a real service or thing ("home care", "personal trainer")
CONCRETE_PHRASES = re.compile(
    r"\b(home (health )?care|home help|home nursing|day care|child ?care|elder(ly)? care|pet care|skin ?care|hair ?care|"
    r"nail care|foot care|personal train(er|ing)|personal assistants?|personal shoppers?|personal chefs?|"
    r"personal stylists?|health checks?|health insurance|home insurance|business cards?|home cinema|home theat(er|re)|"
    r"beauty salons?|medical spas?|private (tutors?|schools?|investigat\w+|chefs?)|public transport)\b", re.I)
OTHER_START = re.compile(r"^\s*(other|others|misc\.?|miscellaneous|various|assorted|more)\b", re.I)
LIST_SEP = re.compile(r"[,;/&+]|\band\b", re.I)
_WORD = re.compile(r"[a-z0-9]+")
OFFICIAL_PREFIX = ("cpv:", "nace:")

# words of the reason, for the API and the page ("why can't I hunt this?")
REASONS = {
    "root": "a whole department",
    "vague": "too vague to price",
    "other": "a catch-all bucket",
    "group": "a group of different things",
    "department": "too broad to price as one thing",
    "official": "an official classification heading",
}


def _words(label: str) -> list[str]:
    return _WORD.findall((label or "").lower().replace("’", "'"))


def core_words(label: str) -> list[str]:
    """The words that say WHAT it is: label minus stop words, generic heads and abstract modifiers.
    'Lifestyle Services' -> [], 'Locksmith services' -> ['locksmith'], 'Rangefinder Accessories' -> ['rangefinder']."""
    m = CONCRETE_PHRASES.search(label or "")
    out = [m.group(0).lower()] if m else []
    for w in _words(label):
        if w in STOP or w in GENERIC_HEADS or w in ABSTRACT or w.isdigit():
            continue
        # plural heads ('activities', 'supplies') are listed; catch other plurals of listed words too
        if w.endswith("s") and (w[:-1] in GENERIC_HEADS or w[:-1] in ABSTRACT):
            continue
        out.append(w)
    return out


def is_list_label(label: str) -> bool:
    """'Hair salons & barbers', 'Seats, chairs & related products': several things in one label."""
    return bool(LIST_SEP.search(label or ""))


def ends_generic(label: str) -> bool:
    w = _words(label)
    return bool(w) and w[-1] in GENERIC_HEADS


def is_official(nid: str, label: str) -> bool:
    """A heading copied from the EU procurement (CPV) or statistics (NACE) lists that no shop would print:
    long, a list, or bureaucratic words. Short ones ('Courier services') read fine."""
    if not str(nid).startswith(OFFICIAL_PREFIX):
        return False
    w = _words(label)
    return (len(w) >= 5 or ";" in label or "(" in label or label.count(",") >= 1
            or bool(re.search(r"\b(related|auxiliary|ancillary|n\.e\.c|activities|apparatus|associated|"
                              r"other|thereof|articles|products|equipment)\b", label, re.I)))


def assess(nid: str, label: str, *, depth: int, n_children: int, n_desc: int, kind: str) -> tuple[bool, str | None]:
    """(huntable, browse_reason). Huntable = a concrete thing or service a person buys; browse-only nodes open a
    category page with their concrete subcategories instead of hunting their own label."""
    if depth <= 1:
        return False, "root"
    if OTHER_START.match(label or ""):
        return False, "other"
    if not core_words(label):
        return False, "vague"
    if n_children:
        if is_official(nid, label):
            return False, "official"
        if ends_generic(label):
            return False, "group"
        if is_list_label(label):
            # 'Headphones & Headsets', 'Taps & Dies': two names for one small shelf still hunt fine
            parts = [p for p in re.split(r"[,;/&+]|\band\b", label, flags=re.I) if p.strip()]
            if len(parts) > 2 or n_desc > 15 or not all(core_words(p) for p in parts):
                return False, "group"
        limit = 200 if kind in ("service", "digital") else 40
        if n_desc > limit:
            return False, "department"
    return True, None


def should_fold(label: str, *, depth: int, n_children: int) -> bool:
    """An empty (or almost empty) umbrella to merge into its parent: a leaf like 'Lifestyle Services',
    'Accessories', 'Other personal services' (nothing to hunt, nothing to browse)."""
    if depth <= 2 and n_children:
        return False
    vague = not core_words(label) or bool(OTHER_START.match(label or ""))
    return vague and n_children <= 2
