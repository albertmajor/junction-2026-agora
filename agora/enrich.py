"""CATEGORY ENRICHMENT: what people usually look for in a niche category, and the providers we know there.

Owner, 14 Nov: "once you reach a super niche category (e.g. 'Transport agency' ...) it can maybe start scraping
for categories too? ... or like what you might look for based on what people usually look for there".

A deep / small node (few children or a leaf) gets
  * suggestions: 4-10 concrete, huntable things in plain words, in the page's language ("freight forwarding
    quote", "pallet shipping"), each {label, query, kind, why};
  * providers: domains we have met for this node before (long-tail registry, curated where-to-look).

Sources, cheapest first:
  (a) our own data: past hunts in agora.db (needs) that classified to this node or a neighbour, curated meanings in
      agora.intent.CONCEPTS for these nodes, the long-tail provider registry (agora.longtail_store);
  (b) free: the marketplaces' own subcategory names for this node (agora.sources.categories mapping + the menus
      read over plain HTTP into .cache/taxonomy/menus/, no request at answer time);
  (c) ONE Context.dev web search (1 credit) only when (a)+(b) give fewer than 4, only for a niche node, and only
      when the shared bucket holds >= 7 tokens (never starve live hunts). Recurring service / product phrases
      are taken from titles and highlight list lines (price lists: "Pallet shipping 49 €").
Then normalise, dedupe, drop navigation words and brand spam (the result sites' own names).

Cached per (node, lang, country) in SQLite (`category_enrich`) for 30 days; a result that wanted the web but could
not have it (offline, bucket low) is kept 1 hour so a later visit fills it in. `get()` answers at once with the
cache or (a)+(b) and runs (c) in the background; a later call returns the full answer.

HTTP: GET /api/categories/enrich?id=&lang=&country= (router below, mounted by agora.api).
"""
from __future__ import annotations

import asyncio
import collections
import functools
import json
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator

TTL_S = 30 * 24 * 3600          # a full answer
SHORT_TTL_S = 3600              # an answer that wanted the web but did not get it
MIN_GOOD = 4                    # fewer suggestions than this from (a)+(b) -> one web search
MAX_SUGGESTIONS = 10
MIN_BUCKET = 7.0                # tokens the shared Context.dev bucket must hold before we take one
NICHE_MAX_CHILDREN = 8
NICHE_MAX_DESC = 40
LANGS = ("en", "fi", "sv", "de", "nl")

SCHEMA = """
CREATE TABLE IF NOT EXISTS category_enrich (
    node TEXT, lang TEXT, country TEXT, data TEXT, source TEXT, at REAL, ttl REAL,
    PRIMARY KEY (node, lang, country));
"""

PRICE_WORD = {"en": "price", "fi": "hinta", "sv": "pris", "de": "Preis", "nl": "prijs"}
# generic heads that make an official label bureaucratic ("Transport agency services" -> "Transport agency")
_GENERIC = re.compile(r"\b(?:services?|palvelut|palvelut|tjänster|dienstleistungen|diensten|dienstverlening|"
                      r"dienste|similar|related|other|muut|övriga|sonstige|overige)\b", re.I)

# --------------------------------------------------------------------------- storage


def _db_path() -> str:
    from agora import store
    return store.db_path()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _cache_get(node: str, lang: str, cc: str, now: float | None = None) -> dict[str, Any] | None:
    now = time.time() if now is None else now
    with _connect() as con:
        r = con.execute("SELECT data, at, ttl FROM category_enrich WHERE node=? AND lang=? AND country=?",
                        (node, lang, cc)).fetchone()
    if r is None or now - float(r["at"]) > float(r["ttl"] or TTL_S):
        return None
    return json.loads(r["data"]) | {"cached": True, "at": r["at"]}


def _cache_put(node: str, lang: str, cc: str, data: dict[str, Any], ttl: float, now: float | None = None) -> None:
    now = time.time() if now is None else now
    body = {k: v for k, v in data.items() if k not in ("cached", "pending", "at")}
    with _connect() as con:
        con.execute("INSERT OR REPLACE INTO category_enrich VALUES (?,?,?,?,?,?,?)",
                    (node, lang, cc, json.dumps(body, ensure_ascii=False), body.get("source", ""), now, ttl))


def clear(node: str | None = None) -> None:
    with _connect() as con:
        if node:
            con.execute("DELETE FROM category_enrich WHERE node=?", (node,))
        else:
            con.execute("DELETE FROM category_enrich")


# --------------------------------------------------------------------------- small helpers


def fold(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", s)).strip()


def _lang(lang: str | None) -> str:
    lang = (lang or "en").lower()[:2]
    return lang if lang in LANGS else "en"


def _cc(country: str | None) -> str:
    from agora import contextdev
    return contextdev.normalize_country(country or os.environ.get("AGORA_COUNTRY") or "fi") or "fi"


@functools.lru_cache(maxsize=1)
def _tax() -> Any | None:
    try:
        from agora import taxonomy
        return taxonomy.load()
    except Exception:
        return None


def plain_label(label: str) -> str:
    """'Transport agency services' -> 'Transport agency'; never empty."""
    out = re.sub(r"\s+", " ", _GENERIC.sub(" ", label)).strip(" ,&-")
    out = re.sub(r"(?:^|\s+)(?:&|and|ja|och|und|en)$", "", out, flags=re.I).strip()
    return out or label


def is_niche(T: Any, i: int) -> bool:
    """A deep or small node: a leaf, or a handful of children and a small subtree, not a root."""
    if T.parent[i] < 0:
        return False
    kids = T.children_of[i]
    return not kids or (len(kids) <= NICHE_MAX_CHILDREN and T.desc[i] <= NICHE_MAX_DESC)


def neighbours(T: Any, i: int) -> dict[str, float]:
    """node id -> how close it is to node i (1 itself, 0.9 inside it, 0.6 parent, 0.5 siblings)."""
    near: dict[str, float] = {T.ids[i]: 1.0}
    stack = [(c, 1) for c in T.children_of[i]]
    while stack:
        c, d = stack.pop()
        near.setdefault(T.ids[c], 0.9)
        if d < 3:
            stack.extend((g, d + 1) for g in T.children_of[c])
    p = T.parent[i]
    if p >= 0 and T.parent[p] >= 0:            # never a root ('Travel & Accommodation' is not a neighbour)
        near.setdefault(T.ids[p], 0.6)
        for s in T.children_of[p]:
            near.setdefault(T.ids[s], 0.5)
    return near


# --------------------------------------------------------------------------- (a) our own data


@functools.lru_cache(maxsize=4096)
def _classify(raw: str) -> str | None:
    T = _tax()
    if T is None:
        return None
    try:
        hit = T.classify(raw)
    except Exception:
        return None
    if not hit or float(hit.get("confidence") or 0) < 0.6:
        return None
    return str(hit["id"])


def from_hunts(T: Any, near: dict[str, float], limit_rows: int = 400) -> list[dict[str, Any]]:
    """Past hunts whose need landed on this node or a neighbour (the need's own category, else classified)."""
    from agora import store
    try:
        with store.connect() as con:
            rows = con.execute("SELECT raw, data FROM needs ORDER BY created_at DESC LIMIT ?",
                               (limit_rows,)).fetchall()
    except sqlite3.Error:
        return []
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        raw = re.sub(r"\s+", " ", (r["raw"] or "")).strip()
        if len(raw) < 3:
            continue
        try:
            cat = (json.loads(r["data"] or "{}").get("category") or {}).get("id")
        except ValueError:
            cat = None
        nid = cat or _classify(raw)
        if not nid or nid not in near:
            continue
        key = fold(raw)
        got = seen.get(key)
        if got:
            got["n"] += 1
            continue
        seen[key] = {"label": raw, "query": raw, "kind": "asked", "n": 1, "w": near[nid] + 0.5, "node": nid}
    out = list(seen.values())
    for s in out:
        s["why"] = ("asked here before" if s["n"] == 1 else f"asked here {s['n']} times")
    return out


def from_concepts(near: dict[str, float], lang: str) -> list[dict[str, Any]]:
    """Curated meanings (agora.intent.CONCEPTS) that hunt in this node or a neighbour, in the page's language."""
    try:
        from agora import intent
    except Exception:
        return []
    out = []
    for c in intent.CONCEPTS:
        for it in c.get("intents", []):
            nid = it.get("node")
            if nid not in near:
                continue
            label = re.sub(r"\{[a-z]+\}", "", (it.get("label") or {}).get(lang) or it.get("hunt") or "").strip()
            qs = (it.get("q") or {}).get(lang) or []
            query = re.sub(r"\s+", " ", (qs[0] if qs else (label if lang != "en" else it.get("hunt") or label))
                           .replace("{place}", "")).strip()
            if label:
                why = (it.get("why") or "").split(". ")[0].rstrip(".")
                out.append({"label": label, "query": query or label, "kind": "common", "w": near[nid] + 0.2,
                            "why": why or "a common request here", "node": nid})
    return out


def providers_known(T: Any, i: int, near: dict[str, float], cc: str, limit: int = 10) -> list[dict[str, Any]]:
    """Providers we met before for this node: the long-tail registry (same node, a neighbour, or shared words),
    then the node's own curated where-to-look domains (not the ones inherited from a root)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        from agora import longtail_store
        terms = longtail_store.terms_of(" ".join([T.label(i, "en")] + list(T.syn[i])))
        rows = longtail_store.providers_for(T.ids[i], terms, limit=limit * 2)
        with longtail_store._connect() as con:          # neighbours' providers too (read-only)
            marks = ",".join("?" * len(near))
            extra = con.execute(f"SELECT domain FROM longtail_providers WHERE category_id IN ({marks})"
                                " AND no_prices < 3", tuple(near)).fetchall()
        have = {r["domain"] for r in rows}
        for r in extra:
            if r["domain"] not in have:
                got = longtail_store.get(r["domain"])
                if got:
                    rows.append(got)
        for r in rows:
            plans = r.get("plans") or []
            out[r["domain"]] = {"domain": r["domain"], "name": r.get("name") or r["domain"],
                                "url": r.get("pricing_url") or r.get("home_url") or f"https://{r['domain']}",
                                "why": ("prices read before" if plans else "found in an earlier hunt"),
                                "source": "registry", "priced": bool(plans), "hits": r.get("hits") or 0}
    except Exception:
        pass
    try:
        from agora import intent
        ok = intent.dom_ok
    except Exception:
        def ok(dom: str, cc: str) -> bool:
            return True
    for j in reversed(T.path_idx(i)):
        if T.parent[j] < 0:
            break                                # a root's where-to-look list is too broad for a niche
        for dom, lane in T.where_own[j]:
            if dom not in out and ok(dom, cc):
                out[dom] = {"domain": dom, "name": dom, "url": f"https://{dom}", "why": f"where to look ({lane})",
                            "source": "curated", "priced": False, "hits": 0}
    ranked = sorted(out.values(), key=lambda p: (p["source"] != "registry", not p["priced"], -p["hits"], p["domain"]))
    return ranked[:limit]


# --------------------------------------------------------------------------- (b) marketplace menus (cached)

# only menus in the page's language (a Finnish page does not get Swedish filter names); helpling's second level
# is cities, not services, so it is left out
MENU_LANG_SITES = {"fi": ["tori"], "sv": ["blocket"], "de": ["kleinanzeigen", "myhammer"],
                   "nl": ["marktplaats"], "en": ["checkatrade", "fiverr"]}
FLAT_MENUS = {"checkatrade"}            # one level of trades: entries that contain the node's words


@functools.lru_cache(maxsize=32)
def _menu(site: str) -> list[dict[str, Any]]:
    from agora.sources import categories
    try:
        return list(json.loads((categories.MENUS / f"{site}.json").read_text()).get("items") or [])
    except (OSError, ValueError, AttributeError):
        return []


def _prettify(s: str) -> str:
    s = re.sub(r"\s+", " ", s.replace("_", " ")).strip()
    return s[:1].upper() + s[1:]


def from_menus(T: Any, i: int, lang: str) -> list[dict[str, Any]]:
    """The marketplaces' own subcategory names under this node's category page (the site's filters), and
    service-platform menu entries named like this node. No request: the menus are cached files."""
    from agora.sources import categories
    out: list[dict[str, Any]] = []
    sites = MENU_LANG_SITES.get(lang, [])
    got = categories.entry_for(T.ids[i])
    keys: dict[str, list[str]] = {}
    if got:
        entry, _nid, _hops = got
        for s in ("tori", "blocket"):
            keys[s] = [f"={x}" for x in entry.get("schibsted") or []]
        if entry.get("kleinanzeigen"):
            keys["kleinanzeigen"] = [str(entry["kleinanzeigen"]).split("{q}")[0]]
        if entry.get("marktplaats"):
            keys["marktplaats"] = [str(entry["marktplaats"])]
    names = {fold(plain_label(T.label(i, l))) for l in T.labels[i]} | {fold(plain_label(x)) for x in T.syn[i]}
    names.discard("")
    for site in sites:
        items = _menu(site)
        if not items:
            continue
        heads: list[tuple[str, ...]] = []
        for x in items:
            url = x.get("url") or ""
            path = tuple(x.get("path") or ())
            if not path:
                continue
            if any(url.endswith(k) or (k in url and not k.startswith("=")) or re.search(re.escape(k) + r"(?:&|$)", url)
                   for k in keys.get(site, [])):
                heads.append(path)
            elif fold(path[-1]) in names:
                heads.append(path)
        if site in FLAT_MENUS:                          # '24 Hour Emergency Plumber' for 'Plumber'
            want = [set(n.split()) for n in names if n]
            for x in items:
                path = tuple(x.get("path") or ())
                words = set(fold(path[-1]).split()) if path else set()
                if any(w and w < words for w in want):
                    out.append({"label": _prettify(path[-1]), "query": _prettify(path[-1]), "kind": "marketplace",
                                "why": f"a trade on {site}", "w": 0.7, "site": site})
            continue
        for head in heads[:3]:
            for x in items:
                path = tuple(x.get("path") or ())
                if len(path) == len(head) + 1 and path[:len(head)] == head:
                    label = _prettify(path[-1])
                    if categories._SKIP.search(label):
                        continue
                    out.append({"label": label, "query": label, "kind": "marketplace",
                                "why": f"a category on {site}", "w": 0.8, "site": site})
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


# --------------------------------------------------------------------------- (c) one web search


def bucket_tokens() -> float:
    """Tokens in the shared Context.dev bucket right now (read-only peek, no token taken)."""
    from agora import contextdev
    try:
        st = json.loads((contextdev.cache_root() / "contextdev_bucket.json").read_text())
    except (OSError, ValueError):
        st = {}
    size = float(getattr(contextdev, "BUCKET_SIZE", contextdev.RATE_PER_MIN))
    now = time.time()
    return min(size, float(st.get("tokens", size)) + (now - float(st.get("ts", now))) * contextdev.RATE_PER_MIN / 60)


def web_allowed() -> tuple[bool, str]:
    from agora import contextdev
    if contextdev.offline():
        return False, "offline"
    try:
        if not contextdev._key():
            return False, "no key"
    except Exception:
        return False, "no key"
    if bucket_tokens() < MIN_BUCKET:
        return False, "bucket low"
    return True, ""


_QUERY_GENERIC = {"agency", "agencies", "company", "companies", "office", "bureau", "firm", "provider", "providers",
                  "work", "works", "activities", "toimisto", "liike", "byrå", "büro", "agentur", "bureau", "kantoor",
                  "preparation", "laadinta", "management"}


def web_query(T: Any, i: int, lang: str) -> str:
    """The node in plain words + up to two telling words of its first child (or a synonym) + 'price' in the page's
    language: 'Transport agency' alone finds the Finnish transport *authority*'s fees; 'Transport freight price'
    finds what freight costs."""
    base = [w for w in plain_label(T.label(i, lang)).split() if fold(w) not in _QUERY_GENERIC and w not in "&"]
    have = {fold(w) for w in base}
    extra: list[str] = []
    pool = [T.label(c, lang) for c in T.children_of[i]] or [x for x in T.syn[i] if lang == "en"]
    for lab in pool:
        words = [w for w in re.findall(r"[\w-]+", plain_label(lab))
                 if fold(w) not in have and fold(w) not in _QUERY_GENERIC and fold(w) not in _STOP and len(w) > 2]
        if words:
            extra = words[:2]
            break
    q = " ".join(base + [w.lower() for w in extra]) or plain_label(T.label(i, lang))
    return f"{q} {PRICE_WORD.get(lang, 'price')}"


_NAV = {
    # navigation, contact and shop chrome in the five languages
    "home", "contact", "contact us", "about", "about us", "login", "log in", "sign in", "sign up", "cart", "menu",
    "search", "blog", "news", "faq", "privacy", "privacy policy", "cookies", "terms", "careers", "read more",
    "learn more", "get started", "our services", "services", "pricing", "prices", "price list", "get a quote",
    "request a quote", "free quote", "etusivu", "palvelut", "yhteystiedot", "ota yhteyttä", "hinnasto",
    "työhinnasto", "meistä", "tietoa meistä", "kirjaudu", "ostoskori", "lue lisää", "tarjouspyyntö",
    "startsida", "kontakt", "kontakta oss", "om oss", "tjänster", "priser", "prislista", "logga in",
    "startseite", "über uns", "impressum", "datenschutz", "anmelden", "warenkorb", "leistungen", "preise",
    "preisliste", "mehr erfahren", "home", "over ons", "inloggen", "winkelwagen", "diensten", "prijzen",
    "prijslijst", "lees meer", "offerte aanvragen", "näytä koko kuvaus", "tuotteen kuvaus", "myydään",
    "frequently asked questions", "faqs", "usein kysytyt kysymykset", "vanliga frågor", "häufige fragen",
    "veelgestelde vragen", "ostetaan", "find out more", "see more", "view all", "show more",
}
_STOP = {
    "the", "and", "or", "for", "with", "of", "in", "a", "an", "to", "on", "at", "by", "from", "your", "our", "you",
    "we", "is", "are", "be", "it", "this", "that", "best", "cheap", "top", "free", "new", "online", "now", "all",
    "how", "what", "why", "much", "does", "cost", "costs", "price", "prices", "pricing", "per", "vs",
    "ja", "tai", "on", "ovat", "sekä", "kanssa", "hinta", "hinnat", "edullinen", "edullisesti", "halpa", "paras",
    "och", "eller", "med", "för", "pris", "billig", "bästa", "und", "oder", "mit", "für", "der", "die", "das", "den",
    "preis", "günstig", "beste", "en", "of", "met", "voor", "het", "de", "een", "prijs", "goedkoop", "beste",
    "von", "van", "av", "alk", "alkaen", "from", "ab", "vanaf", "från", "inkl", "incl", "alv", "vat", "mwst", "btw", "moms",
}
_JUNK = re.compile(r"@|https?:|www\.|\.(?:com|fi|de|se|nl|net|org)\b|\+?\d[\d\s-]{6,}|©|cookie", re.I)
_PRICE = re.compile(r"(?:€|eur\b|e/|kr\b|sek\b|\$|£|/h\b|/kk\b|/pv\b|/month)", re.I)
_LINE_SPLIT = re.compile(r"\n+|\s+[|•·–—]\s+|\s+-\s+|\s*…\s*|(?<=[.!?])\s+")


def _brand_words(results: list[dict[str, Any]]) -> set[str]:
    out = set()
    for r in results:
        host = re.sub(r"^https?://(?:www\.)?", "", (r.get("url") or "")).split("/")[0]
        parts = host.split(".")
        if len(parts) >= 2:
            sld = parts[-2]
            out.add(fold(sld))
            out.add(fold(sld).replace("-", ""))
            out.update(fold(w) for w in re.split(r"[-_]", sld) if len(w) >= 4)
    return {w for w in out if w}


def _clean_phrase(s: str) -> str:
    s = re.sub(r"\[[^\]]*>\s*", "", s)                      # '[Page > Section]' breadcrumbs of highlights
    s = re.sub(r"[*_`\\\[\]|#]+", " ", s)                   # markdown marks
    s = re.sub(r"\(.*?\)|\(.*$", "", s)
    s = re.split(r"\s(?:alk\.?|alkaen|from|ab|vanaf|från|starting|eur|euro|euros|sek|kr)(?:\s|$)|\d|[€$£:?!=]",
                 " " + s + " ",
                 maxsplit=1, flags=re.I)[0]                   # drop the price tail
    s = re.sub(r"^[^\w]+", "", s.strip())                    # leading marks, bullets
    s = re.sub(r"[\s,;:./+&()-]+$", "", s)
    return re.sub(r"\s+", " ", s).strip(" -–—:,")


# words about the price itself, not a thing or a job ('hourly rate', 'Tuntiveloitus', 'Kosten im Überblick')
_META = re.compile(r"(?:cost|kost|pric|preis|prijs|pris|hint|hinn|rate|fee|total|profit|labo|veloitus|tunti|stunde|"
                   r"hour|minimum|starts|overview|uberblick|overzicht|list|includ|sisalt|sisaly|exkl|inkl|incl|"
                   r"guest|staff|deposit|surcharge|charge|discount|alennus|district|salar|palk|lohn|gehalt|loon|lön|estimat|calculat|"
                   r"laskuri|rechner|guide|opas|indicator|index|market|markkin|wage|apprentic|oppisopim|metropol|area$|alue$|region|pages?$)", re.I)
_CONNECT = {"and", "ja", "och", "und", "en", "&", "with", "for", "to"}
_DANGLING = {"under", "over", "alle", "yli", "unter", "uber", "onder", "boven", "inom", "within", "up", "till"}
_QUESTION = {"was", "wat", "what", "how", "mita", "mika", "vad", "hur", "wie", "hoe", "paljonko", "kuinka"}


def _phrase_ok(ph: str, words: list[str], brands: set[str]) -> bool:
    if not ph or not ph[0].isupper() and not ph[0].isdigit():       # list entries and titles start capitalised
        return False
    if (ph.isupper() and len(ph) > 4) or "," in ph:              # 'PRICES ARE LABOR ONLY', 'helsinki, espoo'
        return False
    if any(w in _STOP and w not in _CONNECT for w in words) or any(w in _QUESTION for w in words):
        return False                                              # a sentence, not a name of a thing
    if any(_META.match(w) for w in words) or any(w in brands for w in words):
        return False
    return True


def extract_phrases(results: list[dict[str, Any]], label: str, lang: str, limit: int = 10,
                    topic: set[str] | None = None) -> list[dict[str, Any]]:
    """Recurring service / product phrases in search titles and highlights.

    Candidates: title segments and highlight lines (list items and headings; a line that names a price is a
    price-list entry and counts double), 2-6 words, no digits, links, phones, navigation words, or words that are
    one of the result sites' own names; and 2-3 word runs inside sentences ('sea freight', 'freight forwarding')
    that name a topic word (the query's / the node's) and recur on >= 2 sites. Scored by how many sites say it
    (and its word pairs); a shorter phrase inside a kept longer one is dropped."""
    from agora import contextdev
    brands = _brand_words(results)
    own = set(fold(label).split())
    cands: dict[str, dict[str, Any]] = {}
    pair_df: collections.Counter[tuple[str, str]] = collections.Counter()
    docs: list[list[tuple[str, bool]]] = []
    hosts: list[str] = []
    by_host: dict[str, int] = {}
    for r in results:
        url = r.get("url") or ""
        if _NEWS.search(url):                             # an article about prices, not a price list
            continue
        host = _host(url)
        if host in by_host:                               # one site says it once, however many of its pages match
            lines = docs[by_host[host]]
        else:
            by_host[host] = len(docs)
            lines = []
            docs.append(lines)
            hosts.append(host)
        title = r.get("title") or ""
        for seg in _LINE_SPLIT.split(title):
            # 'Pallet shipping and freight forwarding quote' names two things
            parts = re.split(r"\s+(?:and|ja|och|und|en)\s+", seg) if len(seg.split()) > 5 else [seg]
            lines.extend((x[:1].upper() + x[1:], False) for x in parts if x)
        for raw in re.split(r"\n+", contextdev.highlight_text(r)):
            listy = bool(re.match(r"\s*(?:[-*•·]|#{1,4}|\d+[.)])\s", raw))
            priced = bool(_PRICE.search(raw))
            for seg in _LINE_SPLIT.split(raw):
                lines.append((seg, priced and listy))
    for d, lines in enumerate(docs):
        seen_pairs: set[tuple[str, str]] = set()
        for seg, priced in lines:
            if _JUNK.search(seg):
                continue
            ph = _clean_phrase(seg)
            words = fold(ph).split()
            if not 1 <= len(words) <= 5 or len(ph) > 44 or len(ph) < 4:
                continue
            core = [w for w in words if w not in _STOP]
            if not core or fold(ph) in _NAV or not _phrase_ok(ph, words, brands):
                continue
            if len(words) == 1 or words[-1] in _STOP or words[-1] in _CONNECT or words[-1] in _DANGLING:
                continue                                # 'Adults', 'Children under': not a thing to hunt
            if set(core) <= own:                        # just the category's own name again
                continue
            key = " ".join(core)
            c = cands.setdefault(key, {"label": ph, "docs": set(), "priced": 0})
            c["docs"].add(d)
            c["priced"] += int(priced)
            for a, b in zip(core, core[1:]):
                seen_pairs.add((a, b))
        pair_df.update(seen_pairs)
    # word runs inside sentences: only recurring ones about the topic
    topic_w = {w for w in (topic or own) if w not in _STOP and w not in _QUERY_GENERIC and len(w) > 2}
    own_phrases = {fold(label), " ".join(sorted(topic_w))}
    run_docs: dict[str, set[int]] = collections.defaultdict(set)
    run_tf: collections.Counter[tuple[str, int]] = collections.Counter()
    surface: dict[str, str] = {}
    for d, lines in enumerate(docs):
        for seg, _p in lines:
            if _JUNK.search(seg):
                continue
            for part in re.split(r"[,.;:!?()|\[\]>*#/\"“”]+|\s[-–—]\s", seg):
                toks = re.findall(r"[^\W\d_][\w'’-]*", part)
                low = [fold(t) for t in toks]
                for n in (2, 3):
                    for k in range(len(toks) - n + 1):
                        ws = low[k:k + n]
                        if (ws[0] in _STOP or ws[-1] in _STOP or ws[-1] in _CONNECT or ws[-1] in _DANGLING
                                or any(w in _QUESTION or w in brands or _META.match(w) for w in ws)
                                or any(w in _STOP and w not in _CONNECT for w in ws)
                                or not any(w in topic_w for w in ws) or " ".join(ws) in own_phrases):
                            continue
                        key = " ".join(w for w in ws if w not in _STOP)
                        run_docs[key].add(d)
                        run_tf[(key, d)] += 1
                        surface.setdefault(key, " ".join(toks[k:k + n]))
    for key, ds in run_docs.items():
        # on two sites, or said again and again on one (a heading and its text)
        if (len(ds) < 2 and max(run_tf[(key, d)] for d in ds) < 3) or fold(surface[key]) in _NAV:
            continue
        c = cands.setdefault(key, {"label": surface[key], "docs": set(), "priced": 0})
        c["docs"] |= ds
        c["run"] = True
        core = key.split()
        for a, b in zip(core, core[1:]):
            pair_df[(a, b)] = max(pair_df[(a, b)], len(ds))
    scored = []
    for key, c in cands.items():
        core = key.split()
        pairs = [pair_df[(a, b)] for a, b in zip(core, core[1:])]
        score = 2.0 * len(c["docs"]) + 1.5 * min(c["priced"], 2) + (max(pairs) - 1 if pairs else 0)
        if len(c["docs"]) < 2 and not c["priced"] and not c.get("run") and (not pairs or max(pairs) < 2):
            continue                                    # said once, by one page, without a price: not recurring
        if sum(1 for w in core if w in own) and len(core) == 1:
            continue
        scored.append((score, key, c))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    kept: list[tuple[float, str, dict[str, Any]]] = []
    per_doc: collections.Counter[int] = collections.Counter()
    for s, key, c in scored:
        if _mostly_place(c["label"]):
            continue
        ks = set(key.split())
        if any(ks <= set(k.split()) or set(k.split()) <= ks for _, k, _ in kept):
            continue
        if len(c["docs"]) == 1:                     # one page's price list may not fill the whole row
            d = next(iter(c["docs"]))
            if per_doc[d] >= 3:
                continue
            per_doc[d] += 1
        kept.append((s, key, c))
        if len(kept) >= limit:
            break
    n = len(docs)
    out = []
    for s, key, c in kept:
        k = len(c["docs"])
        sites = [hosts[d] for d in sorted(c["docs"])]
        why = (f"on {k} of {n} sites about it" if k > 1 else f"again and again on {sites[0]}" if c.get("run")
               and not c["priced"] else f"in a price list on {sites[0]}") + \
            (", with a price" if c["priced"] and k > 1 else "")
        lab = c["label"]
        if lang != "de" and len(lab.split()) > 1 and all(w[:1].isupper() for w in lab.split() if w.isalpha()) \
                and not lab.isupper():
            lab = lab[:1] + lab[1:].lower()                # 'Road Transport' -> 'Road transport'
        lab = lab[:1].upper() + lab[1:]
        out.append({"label": lab, "query": lab, "kind": "web", "why": why, "w": 0.3 + s / 10, "sites": sites,
                    "priced_on": sites if c["priced"] else []})
    return out


def _mostly_place(ph: str) -> bool:
    """'Electrician Helsinki', 'Helsinki and Uusimaa': a place with at most one word left is not a thing to hunt
    ('Car transport Germany' keeps two)."""
    try:
        from agora import places
        hit = places.find_place(ph)
    except Exception:
        return False
    if not hit:
        return False
    a, b = hit[2]
    rest = [w for w in fold(ph[:a] + " " + ph[b:]).split() if w not in _STOP and w not in _CONNECT]
    return len(rest) < 2


_NEWS = re.compile(r"/(?:news|uutiset|nachrichten|nieuws|nyheter|article|articles|artikel)/|\.pdf$", re.I)


def _host(url: str) -> str:
    return re.sub(r"^https?://(?:www\.)?", "", url or "").split("/")[0].lower()


async def from_web(T: Any, i: int, lang: str, cc: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """ONE Context.dev search -> (suggestions, provider domains seen, the query)."""
    from agora import contextdev
    q = web_query(T, i, lang)
    results = await contextdev.search(q, n=10, highlights=True, country=cc, highlight_chars=1500)
    label = T.label(i, lang)
    topic = set(fold(re.sub(PRICE_WORD.get(lang, "price"), " ", q)).split())
    for j in [i] + list(T.children_of[i]):
        topic |= set(fold(plain_label(T.label(j, lang))).split()) | set(fold(plain_label(T.label(j, "en"))).split())
    sugg = extract_phrases(results, label + " " + T.label(i, "en"), lang, topic=topic)
    # providers: only the sites whose own price list gave a kept suggestion
    useful = {h for x in sugg for h in x.get("priced_on", [])}       # articles about prices are not providers
    provs, seen = [], set()
    for r in results:
        host = _host(r.get("url") or "")
        if host in useful and host not in seen:
            seen.add(host)
            name = re.split(r"\s[|–—-]\s", r.get("title") or "")[-1].strip()[:40]
            provs.append({"domain": host, "name": name if 2 < len(name) < 30 else host, "url": r.get("url"),
                          "why": "has a price list for this", "source": "web", "priced": True, "hits": 0})
    return sugg, provs, q


# --------------------------------------------------------------------------- merge


def merge(groups: list[list[dict[str, Any]]], label: str | list[str], limit: int = MAX_SUGGESTIONS) -> list[dict[str, Any]]:
    """Normalise, dedupe (same words, or one inside the other: keep the more specific), best first."""
    flat = [s for g in groups for s in g]
    flat.sort(key=lambda s: -float(s.get("w", 0)))
    own = {fold(plain_label(x)) for x in ([label] if isinstance(label, str) else label)} | \
        {fold(x) for x in ([label] if isinstance(label, str) else label)}
    out: list[dict[str, Any]] = []
    keys: list[set[str]] = []
    for s in flat:
        lab = re.sub(r"\s+", " ", s.get("label") or "").strip()
        k = set(fold(lab).split()) - _STOP
        if not lab or not k or fold(lab) in own or fold(lab) in _NAV:
            continue
        dup = next((n for n, have in enumerate(keys) if k == have or k < have or have < k), None)
        if dup is not None:
            if len(k) > len(keys[dup]) and out[dup]["kind"] == s.get("kind"):   # same source: more specific wins
                out[dup] = {**_public(s), "label": lab}
                keys[dup] = k
            continue
        out.append({**_public(s), "label": lab})
        keys.append(k)
        if len(out) >= limit:
            break
    return out


def _names(T: Any, i: int) -> list[str]:
    """The node's own names in every language, and its children's (already on the page as things to hunt)."""
    kids = [T.label(c, l) for c in T.children_of[i] for l in T.labels[c]]
    return [T.label(i, l) for l in T.labels[i]] + list(T.syn[i]) + kids


def _public(s: dict[str, Any]) -> dict[str, Any]:
    return {"label": s.get("label"), "query": s.get("query") or s.get("label"), "kind": s.get("kind"),
            "why": s.get("why") or ""}


def _merge_providers(*lists: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for p in lst:
            out.setdefault(p["domain"], {k: p.get(k) for k in ("domain", "name", "url", "why", "source")})
    return list(out.values())[:limit]


# --------------------------------------------------------------------------- the answer


def quick(node: str, lang: str = "en", country: str | None = None) -> dict[str, Any]:
    """(a) + (b): no network, a few ms. Raises KeyError for an unknown node."""
    T = _tax()
    if T is None:
        raise KeyError(node)
    cur = T.resolve(node)
    if cur is None:
        raise KeyError(node)
    i = T._i(cur)
    lang, cc = _lang(lang), _cc(country)
    near = neighbours(T, i)
    hunts = from_hunts(T, near)
    concepts = from_concepts(near, lang)
    menus = from_menus(T, i, lang)
    sugg = merge([hunts, concepts, menus], _names(T, i))
    kinds = {x["kind"] for x in sugg}
    used = [n for n, k in (("own", {"asked", "common"}), ("menus", {"marketplace"})) if kinds & k]
    return {"id": cur, "label": T.label(i, lang), "lang": lang, "country": cc, "niche": is_niche(T, i),
            "suggestions": sugg, "providers": providers_known(T, i, near, cc), "source": "+".join(used) or "none",
            "cached": False, "pending": False}


_INFLIGHT: dict[tuple[str, str, str], asyncio.Task[Any]] = {}


async def complete(node: str, lang: str = "en", country: str | None = None) -> dict[str, Any]:
    """The full answer: (a)+(b), and (c) when it is short and the web is allowed. Stores it."""
    base = quick(node, lang, country)
    T = _tax()
    i = T._i(base["id"])
    lang, cc = base["lang"], base["country"]
    ttl = TTL_S
    if base["niche"] and len(base["suggestions"]) < MIN_GOOD:
        ok, why_not = web_allowed()
        if ok:
            try:
                web, provs, q = await from_web(T, i, lang, cc)
                base["suggestions"] = merge([base["suggestions"], web], _names(T, i))
                base["providers"] = _merge_providers(base["providers"], provs)
                if any(x["kind"] == "web" for x in base["suggestions"]):
                    base["source"] = (base["source"] + "+web") if base["source"] != "none" else "web"
                base["web_query"] = q
            except Exception as e:                      # a failed search: keep (a)+(b), try again later
                base["web_error"] = type(e).__name__
                ttl = SHORT_TTL_S
        else:
            base["web_skipped"] = why_not
            ttl = SHORT_TTL_S
    _cache_put(base["id"], lang, cc, base, ttl)
    return base


async def get(node: str, lang: str = "en", country: str | None = None, *, wait: bool = False) -> dict[str, Any]:
    """Fast: the cached answer, else (a)+(b) now and the rest in the background (`pending`: ask again)."""
    T = _tax()
    if T is None or T.resolve(node) is None:
        raise KeyError(node)
    cur = T.resolve(node)
    lang, cc = _lang(lang), _cc(country)
    hit = await asyncio.to_thread(_cache_get, cur, lang, cc)
    if hit is not None:
        return hit | {"pending": False}
    key = (cur, lang, cc)
    task = _INFLIGHT.get(key)
    if task is None or task.done():
        task = asyncio.get_running_loop().create_task(complete(cur, lang, cc))
        _INFLIGHT[key] = task
        task.add_done_callback(lambda _t, k=key: _INFLIGHT.pop(k, None))
    try:
        done = await asyncio.wait_for(asyncio.shield(task), timeout=None if wait else 0.35)
        return done | {"pending": False}
    except asyncio.TimeoutError:
        base = await asyncio.to_thread(quick, cur, lang, cc)
        return base | {"pending": True}


# --------------------------------------------------------------------------- HTTP

try:
    from fastapi import APIRouter, HTTPException, Query, Response
except ImportError:          # fastapi missing: the module still works as a library
    APIRouter = None         # type: ignore[assignment,misc]


def _router() -> Any:
    r = APIRouter()

    @r.get("/api/categories/enrich")
    async def enrich_endpoint(response: Response, id: str = Query(..., max_length=120), lang: str = Query("en"),
                              country: str | None = Query(None, max_length=40)) -> dict[str, Any]:
        """What people usually look for in a niche category ({suggestions: [{label, query, kind, why}], providers,
        source, cached, pending}). pending=true: the web part is still being read; ask again in a few seconds."""
        try:
            out = await get(id, lang, country)
        except KeyError:
            raise HTTPException(404, f"no category {id!r}") from None
        response.headers["Cache-Control"] = "no-store" if out.get("pending") else "public, max-age=600"
        return out

    return r


router = _router() if APIRouter is not None else None
