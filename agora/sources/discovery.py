"""How to search a site, found from its own pages (pure functions, no network; the onboarder fetches).

Order of evidence for a search URL template:
  1. OpenSearch description (<link rel="search" type="application/opensearchdescription+xml">)
  2. schema.org SearchAction in JSON-LD (potentialAction.target / urlTemplate)
  3. the site's own search <form action> + its text input name
  4. common patterns per language (/search?q=, /s?k=, /haku?q=, /suche?q=, /recherche?q= ...)
A template is verified by reading a test query's result page: several listing links of one repeated path shape
(inferred: /item/123, /p/<slug>-123, /d/oferta/...) that are not on the home page, plus prices.

Templates use {q} (quote_plus of the query) and {dash} (words joined by '-'), like agora.marketplaces.Site.
"""
from __future__ import annotations

import html as _html
import json
import re
from collections import defaultdict
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

# --------------------------------------------------------------------------- hosts

_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}


def root_domain(host: str) -> str:
    """'www.ebay.co.uk' -> 'ebay.co.uk', 'es.wallapop.com' -> 'wallapop.com'."""
    host = (host or "").lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(url: str, base: str) -> bool:
    h = urlsplit(url).netloc
    return not h or root_domain(h) == root_domain(urlsplit(base).netloc)


# --------------------------------------------------------------------------- blocked pages

BLOCK_MARKERS = ("captcha", "cf-chl", "are you a robot", "access denied", "datadome", "perimeterx",
                 "px-captcha", "just a moment...", "attention required", "request unsuccessful. incapsula",
                 "pardon our interruption", "_incapsula_resource", "challenge-platform", "bot detection",
                 "verify you are human", "enable javascript and cookies to continue")


def looks_blocked(status: int, html: str) -> bool:
    if status in (401, 403, 429, 503):
        return True
    head = (html or "")[:6000].lower()
    return len(html or "") < 25000 and any(m in head for m in BLOCK_MARKERS)


# --------------------------------------------------------------------------- robots.txt

def parse_robots(text: str) -> list[tuple[bool, str]]:
    """Rules for 'User-agent: *' as [(allow, pattern)]. Empty = everything allowed."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_rule = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if last_was_rule:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
            last_was_rule = False
        elif k in ("allow", "disallow"):
            last_was_rule = True
            if v or k == "allow":
                rules.append((k == "allow", v))
    if agents:
        groups.append((agents, rules))
    out: list[tuple[bool, str]] = []
    for ags, rs in groups:
        if "*" in ags:
            out.extend(rs)
    return out


def _robots_re(pat: str) -> re.Pattern[str]:
    end = pat.endswith("$")
    body = re.escape(pat[:-1] if end else pat).replace(r"\*", ".*")
    return re.compile("^" + body + ("$" if end else ""))


def robots_allows(rules: list[tuple[bool, str]], url: str) -> bool:
    """Longest match wins (Google's rule); a tie goes to allow."""
    p = urlsplit(url)
    target = (p.path or "/") + ("?" + p.query if p.query else "")
    best: tuple[int, bool] | None = None
    for allow, pat in rules:
        if not pat:
            continue
        if _robots_re(pat).match(target):
            cand = (len(pat), allow)
            if best is None or cand[0] > best[0] or (cand[0] == best[0] and allow):
                best = cand
    return True if best is None else best[1]


# --------------------------------------------------------------------------- template sources

_TAG_ATTR = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))')


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): _html.unescape(m.group(2) or m.group(3) or m.group(4) or "")
            for m in _TAG_ATTR.finditer(tag)}


def opensearch_links(page: str, base: str) -> list[str]:
    out = []
    for tag in re.findall(r"<link\b[^>]*>", page or "", re.I):
        a = _attrs(tag)
        if "search" in a.get("rel", "").lower().split() and "opensearch" in a.get("type", "").lower() and a.get("href"):
            out.append(urljoin(base, a["href"]))
    return out


def _placeholders_to_q(tpl: str, main: tuple[str, ...]) -> str | None:
    """'...?q={searchTerms}&page={startPage?}' -> '...?q={q}'. None when a required unknown placeholder stays."""
    tpl = tpl.strip()
    parts = urlsplit(tpl)
    names = "|".join(re.escape(m) for m in main)
    def fix(s: str) -> str | None:
        s = re.sub(r"\{(?:" + names + r")\??\}", "\x00Q\x00", s)
        if re.search(r"\{[^}]*[^?]\}", s):
            return None
        return s
    q_items = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if re.fullmatch(r"\{[^}]*\?\}", v):
            continue                                  # optional parameter: drop
        fv = fix(v)
        if fv is None:
            return None
        q_items.append((k, fv))
    path = fix(parts.path)
    if path is None:
        return None
    query = "&".join(f"{quote_plus(k)}={v if chr(0) in v else quote_plus(v)}" for k, v in q_items)
    out = urlunsplit((parts.scheme or "https", parts.netloc, path, query, ""))
    if "\x00Q\x00" not in out:
        return None
    return out.replace("\x00Q\x00", "{q}")


def parse_opensearch(xml: str) -> str | None:
    """OpenSearch description -> template for the HTML results page."""
    best = None
    for tag in re.findall(r"<(?:\w+:)?Url\b[^>]*>", xml or "", re.I):
        a = _attrs(tag)
        t = a.get("type", "").lower()
        tpl = a.get("template")
        if not tpl:
            continue
        if "html" in t:
            out = _placeholders_to_q(tpl, ("searchTerms",))
            if out:
                return out
        elif best is None and "suggest" not in t and "json" not in t and t != "application/opensearchdescription+xml":
            best = _placeholders_to_q(tpl, ("searchTerms",))
    return best


def _jsonld_blocks(page: str) -> list[object]:
    out = []
    for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page or "", re.I | re.S):
        try:
            out.append(json.loads(m.group(1).strip()))
        except ValueError:
            continue
    return out


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def searchaction_templates(page: str, base: str) -> list[str]:
    out = []
    for block in _jsonld_blocks(page):
        for node in _walk(block):
            t = node.get("@type")
            if t != "SearchAction" and not (isinstance(t, list) and "SearchAction" in t):
                continue
            target = node.get("target")
            cands = []
            if isinstance(target, str):
                cands.append(target)
            elif isinstance(target, dict):
                cands.append(str(target.get("urlTemplate") or ""))
            elif isinstance(target, list):
                cands += [x if isinstance(x, str) else str((x or {}).get("urlTemplate") or "") for x in target]
            if node.get("urlTemplate"):
                cands.append(str(node["urlTemplate"]))
            qi = str(node.get("query-input") or node.get("query") or "")
            m = re.search(r"name=(\w+)", qi)
            names = tuple({m.group(1) if m else "search_term_string", "search_term_string", "search_term",
                           "query", "q", "searchTerms"})
            for c in cands:
                if c and "{" in c:
                    tpl = _placeholders_to_q(urljoin(base, c), names)
                    if tpl and tpl not in out:
                        out.append(tpl)
    return out


SEARCH_WORD = re.compile(
    r"search|such|haku|hae\b|etsi|zoek|recherch|sök|sok\b|søg|soeg|søk|leit|szuk|wyszuk|hled|hlad|hľad|busc|"
    r"pesquis|cerc|ricerc|keres|caut|otsi|mekl|iešk|iesk|paiešk|търс|αναζ|pretra|iskan|išči|trazi|traži", re.I)
SEARCH_NAMES = ("q", "query", "search", "s", "k", "keyword", "keywords", "text", "search_text", "searchTerm",
                "searchterm", "term", "w", "searchtext", "search_query", "hledat", "searchQuery", "qs", "find",
                "phrase", "fraza", "zoekterm", "suche", "sok", "haku", "ss", "kw", "st", "string")
_SEARCH_NAMES_L = {n.lower() for n in SEARCH_NAMES}


def form_templates(page: str, base: str) -> list[dict]:
    """[{template, method}] from the page's search forms, best first."""
    out: list[tuple[int, dict]] = []
    for m in re.finditer(r"(<form\b[^>]*>)(.*?)</form>", page or "", re.I | re.S):
        fa = _attrs(m.group(1))
        inner = m.group(2)
        inputs = [_attrs(t) for t in re.findall(r"<input\b[^>]*>", inner, re.I)]
        text_in = None
        score = 0
        for a in inputs:
            typ = a.get("type", "text").lower()
            name = a.get("name", "")
            if not name or typ not in ("text", "search", ""):
                continue
            s = (3 if typ == "search" else 0) + (2 if name.lower() in _SEARCH_NAMES_L else 0) \
                + (1 if re.search(r"(?:^|[_-])(?:q|query|search|stext|keywords?|term|text)$", name, re.I) else 0) \
                + (1 if SEARCH_WORD.search(" ".join(a.values())) else 0)
            if s > score:
                score, text_in = s, a
        action = fa.get("action", "")
        role = (fa.get("role", "") + " " + fa.get("class", "") + " " + fa.get("id", "") + " " + action).lower()
        if SEARCH_WORD.search(role) or "catalog" in role:
            score += 2
        if text_in is None or score < 2:
            continue
        if re.search(r"login|signin|newsletter|subscribe|password", role):
            continue
        method = fa.get("method", "get").lower() or "get"
        act = urljoin(base, action or urlsplit(base).path or "/")
        ap = urlsplit(act)
        params = [(k, v) for k, v in parse_qsl(ap.query, keep_blank_values=True)]
        hidden = [(a.get("name"), a.get("value", "")) for a in inputs
                  if a.get("type", "").lower() == "hidden" and a.get("name") and 0 < len(a.get("value", "")) <= 30
                  and not re.search(r"token|csrf|nonce|form_key|__", a.get("name", ""), re.I)]
        params += hidden[:3]
        query = urlencode(params)
        query = (query + "&" if query else "") + f"{quote_plus(text_in['name'])}={{q}}"
        tpl = urlunsplit((ap.scheme, ap.netloc, ap.path or "/", query, ""))
        out.append((score, {"template": tpl, "method": "post" if method == "post" else "get"}))
    out.sort(key=lambda x: -x[0])
    seen, res = set(), []
    for _, d in out:
        if d["template"] not in seen:
            seen.add(d["template"])
            res.append(d)
    return res


COMMON: dict[str, tuple[str, ...]] = {
    "_": ("/search?q={q}", "/search?query={q}", "/s?k={q}", "/search/?q={q}", "/catalogsearch/result/?q={q}",
          "/search?text={q}", "/search?keyword={q}", "/search?keywords={q}", "/?s={q}&post_type=product",
          "/catalog?search_text={q}", "/q/{q}/", "/search/{q}"),
    "fi": ("/haku?q={q}", "/haku/?q={q}", "/search?q={q}", "/haku?query={q}"),
    "sv": ("/sok?q={q}", "/search?q={q}", "/sok?query={q}"),
    "no": ("/sok?q={q}", "/search?q={q}"),
    "da": ("/soeg?q={q}", "/search?q={q}", "/sog?q={q}"),
    "de": ("/suche?q={q}", "/search?q={q}", "/suche/{q}/", "/suche?query={q}"),
    "nl": ("/zoeken?query={q}", "/zoeken?q={q}", "/search?q={q}", "/zoeken/?q={q}"),
    "fr": ("/recherche?q={q}", "/recherche?text={q}", "/search?q={q}", "/recherche/?q={q}"),
    "es": ("/buscar?q={q}", "/search?q={q}", "/busqueda?q={q}"),
    "it": ("/cerca?q={q}", "/ricerca?q={q}", "/search?q={q}"),
    "pt": ("/pesquisa?q={q}", "/search?q={q}", "/busca?q={q}"),
    "pl": ("/szukaj?q={q}", "/search?q={q}", "/szukaj?query={q}"),
    "cs": ("/hledat?q={q}", "/vyhledavani?q={q}", "/search?q={q}"),
    "sk": ("/hladat?q={q}", "/vyhladavanie?q={q}", "/search?q={q}"),
    "hu": ("/kereses?q={q}", "/search?q={q}"),
    "ro": ("/cauta?q={q}", "/search?q={q}"),
    "et": ("/otsi?q={q}", "/search?q={q}"),
}


def common_templates(home: str, lang: str | None) -> list[str]:
    p = urlsplit(home)
    base = f"{p.scheme or 'https'}://{p.netloc}"
    prefix = p.path.rstrip("/")
    paths = list(COMMON.get(lang or "", ())) + list(COMMON["_"])
    out = []
    for path in paths:
        for pre in ((prefix, "") if prefix else ("",)):
            u = base + pre + path
            if u not in out:
                out.append(u)
    return out


# --------------------------------------------------------------------------- reading a results page

_HREF = re.compile(r"<a\b[^>]*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)
NAV_FIRST = {"search", "s", "suche", "haku", "recherche", "zoeken", "sok", "help", "hilfe", "account", "login",
             "cart", "basket", "blog", "news", "tag", "tags", "brand", "brands", "marken", "category", "categories",
             "kategorie", "kategoria", "kategori", "c", "cat", "stores", "store-locator", "cms", "info", "about",
             "contact", "kontakt", "faq", "service", "customer-service", "my", "user", "wishlist", "compare",
             "auth", "register", "static", "assets", "cdn-cgi", "legal", "privacy", "terms", "magazin",
             "magazine", "inspiration", "ratgeber", "jobs", "careers", "press"}
_EXT = re.compile(r"\.(html?|php|aspx?|jsp)$", re.I)
_ASSET = re.compile(r"\.(jpe?g|png|gif|webp|svg|css|js|pdf|ico|xml|json)$", re.I)


def page_links(page: str, base: str) -> list[str]:
    """Absolute same-site links (no fragments, no assets)."""
    out = []
    for m in _HREF.finditer(page or ""):
        href = _html.unescape(m.group(1) or m.group(2) or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        u = urljoin(base, href).split("#")[0]
        if not u.startswith("http") or not same_site(u, base) or _ASSET.search(urlsplit(u).path):
            continue
        out.append(u)
    return out


def _seg_token(seg: str) -> str:
    s = _EXT.sub("", seg)
    if not s:
        return seg
    if s.isdigit():
        return "#"
    if re.fullmatch(r"[A-Za-z0-9]{8,}", s) and re.search(r"\d", s) and re.search(r"[A-Za-z]", s):
        return "@"
    if re.search(r"\d{3,}", s) and re.search(r"[A-Za-z]", s):
        return "slug#"
    if s.count("-") + s.count("_") >= 2 or (len(s) >= 18 and ("-" in s or "_" in s)):
        return "slug"
    if re.search(r"\d", s):
        return "x#"                       # ref=sr_1_3, p-12, a1 ... a varying token, never a fixed path word
    return "=" + seg.lower()


def link_shape(url: str) -> tuple[str, ...]:
    p = urlsplit(url)
    segs = [s for s in p.path.split("/") if s]
    toks = [_seg_token(s) for s in segs]
    ext = _EXT.search(segs[-1]).group(0).lower() if segs and _EXT.search(segs[-1]) else ""
    ids = [i for i, t in enumerate(toks) if t in ("#", "@", "slug#")]
    if ids and ids[-1] < len(toks) - 1:
        toks, ext = toks[: ids[-1] + 1], ""      # /dp/B0ABC/ref=sr_1_3 -> /dp/B0ABC (the rest is tracking)
    if ext:
        toks.append("ext" + ext)
    if all(t.startswith("=") or t.startswith("ext") for t in toks):
        ids = [k for k, v in parse_qsl(p.query) if re.fullmatch(r"\d{3,}|[A-Za-z0-9-]{10,}", v)]
        if ids:
            toks.append("?" + sorted(ids)[0])
    return tuple(toks)


def _variable(shape: tuple[str, ...]) -> bool:
    return any(not (t.startswith("=") or t.startswith("ext")) for t in shape)


_TOKEN_RE = {"x#": r"[^/?#]*\d[^/?#]*", "#": r"\d+", "@": r"[A-Za-z0-9]+", "slug#": r"[^/?#]*\d{3,}[^/?#]*", "slug": r"[^/?#]+"}


def shape_regex(shape: tuple[str, ...]) -> str:
    segs, ext, qkey, last_var = [], "", "", False
    for t in shape:
        if t.startswith("ext"):
            ext = t[3:]
        elif t.startswith("?"):
            qkey = t[1:]
        elif t.startswith("="):
            segs.append(re.escape(t[1:]))
            last_var = False
        else:
            segs.append(_TOKEN_RE[t])
            last_var = True
    if ext and segs and last_var:           # a literal last segment already carries its extension
        segs[-1] += re.escape(ext)
    rx = "^/" + "/".join(segs)
    if qkey:
        return rx + r"/?\?(?:.*&)?" + re.escape(qkey) + "="
    return rx + r"(?:[/?#]|$)"


def infer_listing(page: str, url: str, home: str = "", query: str = "") -> dict:
    """The repeated listing-link shape on a results page that is not navigation (not on the home page).
    -> {regex, count, sample, shape} ({count: 0} when nothing repeats)."""
    links = page_links(page, url)
    home_paths = {urlsplit(u).path.rstrip("/") for u in page_links(home, url)} if home else set()
    groups: dict[tuple[str, ...], set[str]] = defaultdict(set)
    qwords = [w.lower() for w in query.split() if len(w) > 2]
    here = urlsplit(url).path.rstrip("/")
    for u in links:
        p = urlsplit(u)
        key_path = p.path.rstrip("/")
        if key_path == here and p.query:
            continue                      # another view of the same search (page 2, sort, filter)
        shape = link_shape(u)
        if p.query and not _variable(shape[:-1] if shape and shape[-1].startswith("?") else shape) \
                and any(w in p.query.lower() for w in qwords):
            continue
        if not _variable(shape) or not key_path:
            continue
        first = next((t[1:] for t in shape if t.startswith("=")), None)
        if shape and shape[0].startswith("=") and shape[0][1:] in NAV_FIRST:
            continue
        if first in ("search",):
            continue
        if key_path in home_paths and not shape[-1].startswith("?"):
            continue
        groups[shape].add(key_path + ("?" + p.query if shape[-1].startswith("?") else ""))
    if not groups:
        return {"count": 0}
    def rank(item):
        shape, paths = item
        bonus = 1.2 if any(t in ("#", "slug#", "@") for t in shape) else 0.8 if shape[-1].startswith("?") else 1.0
        return len(paths) * bonus
    shape, paths = max(groups.items(), key=rank)
    rx = shape_regex(shape)
    try:
        cre = re.compile(rx)
    except re.error:
        return {"count": 0}
    ok = [p for p in paths if cre.search(p)]
    return {"regex": rx, "count": len(ok), "sample": sorted(ok)[:3], "shape": "/".join(shape)}


_NUM = r"\d{1,3}(?:[ .,  ']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
CUR_AFTER = r"€|EUR\b|kr\.?|SEK\b|NOK\b|DKK\b|zł|PLN\b|Kč|CZK\b|Ft\b|HUF\b|lei\b|RON\b|лв\.?|BGN\b|CHF\b|£|GBP\b|,-"
CUR_BEFORE = r"€|£|EUR\b|CHF\b|kr\.?|SEK\b|NOK\b|DKK\b|PLN\b"
PRICE = re.compile(rf"(?:(?:{CUR_BEFORE})\s?(?:{_NUM}))|(?:(?<![\w.,])(?:{_NUM})\s?(?:{CUR_AFTER}))")


def visible_text(page: str) -> str:
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", page or "", flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t))


def count_prices(page: str) -> int:
    return len(PRICE.findall(visible_text(page)))


def structured(page: str) -> dict:
    """JSON-LD ItemList / Product counts and embedded app-state prices (results present but drawn by JS)."""
    itemlist, products = False, 0
    for block in _jsonld_blocks(page):
        for node in _walk(block):
            t = node.get("@type")
            ts = t if isinstance(t, list) else [t]
            if "ItemList" in ts or "OfferCatalog" in ts:
                itemlist = True
            if "Product" in ts or "Offer" in ts and "itemOffered" in node:
                products += 1
    micro = len(re.findall(r'itemtype=["\']https?://schema\.org/Product["\']', page or "", re.I))
    embedded = len(re.findall(r'"(?:price|priceAmount|amount|current_price|salePrice|price_amount)"\s*:\s*"?\d',
                              page or ""))
    return {"itemlist": itemlist, "jsonld_products": products + micro, "embedded_prices": embedded,
            "next_data": "__NEXT_DATA__" in (page or "") or "__NUXT__" in (page or "")}


PAGE_PARAMS = ("page", "p", "pg", "pagina", "seite", "sida", "side", "strana", "sivu", "pageNumber", "currentPage",
               "pn", "pag", "o", "pagenumber", "page_number", "pageIndex")


def detect_pagination(page: str, url: str) -> dict:
    """{param} (?page=2) or {path_template} (/page/2/) from the results page's own page-2 link, else {}."""
    path = urlsplit(url).path.rstrip("/")
    for u in page_links(page, url):
        p = urlsplit(u)
        for k, v in parse_qsl(p.query):
            if v == "2" and k in PAGE_PARAMS and (p.path.rstrip("/") == path or not path):
                return {"param": k}
        m = re.search(r"/(page|p|seite|sivu|strona|pagina)[/:-]?2/?$", p.path)
        if m and p.path.startswith(path) and path:
            return {"path_suffix": p.path[len(path):].replace("2", "{page}")}
    return {}


def query_echo(page: str, query: str) -> bool:
    words = [w.lower() for w in query.split() if len(w) > 2]
    low = (page or "").lower()
    return bool(words) and all(w in low for w in words)


def evaluate(page: str, url: str, query: str, home: str = "", service: bool = False) -> dict:
    """Score one results page. verified = a real results page we can cut with code from a plain fetch:
    >= 5 listing links of one shape, and (products) >= 3 of those listings carry their own price, and the
    listings are about the query (its first word in >= 30 % of the rows) or the page states structured products."""
    from agora.sources import rows_from_html
    lst = infer_listing(page, url, home, query)
    prices = count_prices(page)
    st = structured(page)
    links = lst.get("count", 0)
    rows = rows_from_html(page, url, {"listing": lst.get("regex")}, max_rows=60) if lst.get("regex") else []
    priced_rows = sum(1 for r in rows if r["price"] is not None)
    w = next((x.lower() for x in query.split() if len(x) > 2), "")
    import unicodedata
    def fold(t: str) -> str:
        return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    on_topic = sum(1 for r in rows if w and fold(w) in fold(r["title"] + " " + r["text"] + " " + r["url"]))
    relevant = bool(rows) and (on_topic >= max(2, 0.3 * len(rows)) or st["jsonld_products"] >= 3)
    priced = priced_rows >= 3 or st["jsonld_products"] >= 3 or st["itemlist"]
    verified = links >= 5 and ((priced and relevant) or (service and (relevant or not w)))
    y = min(1.0, links / 20) * 0.5 + min(1.0, max(priced_rows, st["jsonld_products"]) / 20) * 0.3 \
        + (0.1 if st["itemlist"] else 0.0) + (0.1 * min(1.0, on_topic / max(1, len(rows))))
    return {"verified": verified, "links": links, "listing": lst.get("regex"), "sample": lst.get("sample", []),
            "prices": prices, "priced_rows": priced_rows, "on_topic": on_topic, **st, "echo": query_echo(page, query),
            "pagination": detect_pagination(page, url), "yield": round(y, 3)}
