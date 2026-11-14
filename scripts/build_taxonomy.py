"""Build agora/taxonomy/tree.json(.gz): ONE tree of everything you can buy online, products and services.

Written at Junction 2026. Usage:
    .venv/bin/python scripts/build_taxonomy.py --fetch     # download seeds + shop menus into .cache/taxonomy/
    .venv/bin/python scripts/build_taxonomy.py             # merge the cached downloads into the tree

Sources (licences in agora/taxonomy/SOURCES, printed into the tree's "sources"):
  curated roots + services backbone (agora/taxonomy/curated.py), Shopify Product Taxonomy (MIT, 13 languages,
  with its Google Product Taxonomy mapping), Google Product Taxonomy labels (fi/de/nl/sv/fr/da/nb/es/it/pl),
  EU CPV 2008 (public procurement vocabulary, 23 languages), NACE Rev. 2 via Statistics Finland TOL 2008
  (en/fi/sv), Yelp category list (names only), and category menus/sitemaps of real shops, marketplaces and
  service platforms read over plain HTTP (no paid API calls).

Merging: every imported node looks for a node with the same normalised label (any shared language) first
among the children of its target parent, then in the target root's subtree, then (services) in every service
root; a hit merges (labels, synonyms, codes, domains), a miss adds a child. Depth is capped at 7 (deeper
nodes fold into their parent's synonyms).
"""
from __future__ import annotations

import argparse
import bisect
import collections
import gzip
import hashlib
import html as _html
import json
import pathlib
import re
import sys
import time
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agora.taxonomy import curated  # noqa: E402
from agora.taxonomy import SOURCES  # noqa: E402
from agora.taxonomy import browse  # noqa: E402

CACHE = ROOT / ".cache" / "taxonomy"
RAW, HTTP, MENUS = CACHE / "raw", CACHE / "http", CACHE / "menus"
OUT_DIR = ROOT / "agora" / "taxonomy"
LANGS = ("en", "fi", "de", "nl", "sv", "fr", "da", "nb", "hu", "pl", "es", "it", "cs")
MAX_DEPTH = 7
VERBOSE = False
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# ------------------------------------------------------------------ fetching (plain HTTP, cached)

SEEDS = {
    **{f"gpt-{l}.txt": f"https://www.google.com/basepages/producttype/taxonomy-with-ids.{l}.txt"
       for l in ("en-US", "fi-FI", "de-DE", "nl-NL", "sv-SE", "fr-FR", "da-DK", "no-NO", "es-ES", "it-IT", "pl-PL")},
    **{f"shopify-{l}.txt": f"https://raw.githubusercontent.com/Shopify/product-taxonomy/main/dist/{l}/categories.txt"
       for l in ("en", "fi", "de", "nl", "sv", "fr", "da", "nb", "hu", "pl", "es", "it", "cs")},
    "shopify-mappings.json": "https://raw.githubusercontent.com/Shopify/product-taxonomy/main/dist/en/integrations/all_mappings.json",
    "cpv.zip": "https://ted.europa.eu/documents/d/ted/cpv_2008_xml",
    "isic4.txt": "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_4_english_structure.txt",
    **{f"tol2008-{l}.json": "https://data.stat.fi/api/classifications/v2/classifications/toimiala_1_20080101/"
       f"classificationItems?content=data&meta=max&lang={l}&format=json" for l in ("fi", "sv", "en")},
    "yelp-categories.html": "https://docs.developer.yelp.com/docs/resources-categories",
}

_last_host: dict[str, float] = {}


def http_get(url: str, *, force: bool = False, delay: float = 0.7) -> str:
    """GET with a disk cache (.cache/taxonomy/http) and per-host politeness delay. '' on failure."""
    import httpx
    HTTP.mkdir(parents=True, exist_ok=True)
    p = HTTP / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".bin")
    if p.exists() and not force:
        b = p.read_bytes()
    else:
        host = urlsplit(url).netloc
        wait = _last_host.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "en;q=0.9,fi;q=0.8,de;q=0.7"},
                          follow_redirects=True, timeout=30)
            b = r.content if r.status_code == 200 else b""
        except Exception as e:  # network errors: empty, the build copes
            print("  fetch failed", url, type(e).__name__, file=sys.stderr)
            b = b""
        _last_host[host] = time.time()
        p.write_bytes(b)
    if b[:2] == b"\x1f\x8b":
        try:
            b = gzip.decompress(b)
        except OSError:
            pass
    return b.decode("utf-8", "replace")


def sitemap_locs(url: str) -> list[str]:
    return [_html.unescape(u) for u in re.findall(r"<loc>\s*([^<\s]+)", http_get(url))]


def fetch_seeds() -> None:
    import httpx
    import zipfile
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in SEEDS.items():
        p = RAW / name
        if p.exists() and p.stat().st_size > 1000:
            continue
        print("seed", name)
        r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=120)
        r.raise_for_status()
        p.write_bytes(r.content)
    if not (RAW / "cpv" / "cpv_2008.xml").exists():
        with zipfile.ZipFile(RAW / "cpv.zip") as z:
            z.extract("cpv_2008.xml", RAW / "cpv")


def _deslug(s: str) -> str:
    s = unquote(s).replace("--", " - ").replace("-", " ").replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:1].upper() + s[1:]


def _anchors(page: str, href_re: str) -> list[tuple[str, str]]:
    """(href, visible text) for <a> tags whose href matches."""
    out = []
    for m in re.finditer(r"<a\b[^>]*?href=\"(" + href_re + r")\"[^>]*>(.*?)</a>", page, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"\s+", " ", _html.unescape(text)).strip()
        if text:
            out.append((_html.unescape(m.group(1)), text))
    return out


def _path_items(urls, rx: str, *, drop_last_num: bool = False, sep: str = "/") -> list[dict]:
    items = []
    for u in urls:
        m = re.search(rx, u)
        if not m:
            continue
        segs = [s for s in m.group(1).strip("/").split(sep) if s]
        if drop_last_num and segs and segs[-1].isdigit():
            segs = segs[:-1]
        segs = [re.sub(r"-\d+$", "", s) for s in segs]
        if segs:
            items.append({"path": [_deslug(s) for s in segs], "url": u})
    return items


def menu_ipon():
    return _path_items(sitemap_locs("https://ipon.hu/sitemap/product-group-hu_HU.xml"), r"/shop/csoport/(.+)$",
                       drop_last_num=True)


def menu_power():
    return _path_items(sitemap_locs("https://www.power.fi/services/sitemap/categories.xml"), r"/c/\d+/(.+)$")


def menu_marktplaats():
    return _path_items(sitemap_locs("https://www.marktplaats.nl/sitemap/category_lrp.1.sitemap.xml.gz"), r"/l/(.+)$")


def menu_kleinanzeigen():
    return _path_items(sitemap_locs("https://www.kleinanzeigen.de/sitemap_categories.xml"), r"/s-([^/]+)/c\d+")


def menu_mediamarkt():
    return _path_items(sitemap_locs("https://www.mediamarkt.de/sitemaps/sitemap-productlistpages.xml"),
                       r"/category/(.+?)-\d+\.html")


def menu_mediamarkt_services():
    return _path_items(sitemap_locs("https://www.mediamarkt.de/sitemaps/sitemap-servicepages.xml"), r"/de/service/(.+)$")


def menu_emag():
    return _path_items(sitemap_locs("https://www.emag.hu/sitemaps/categories-0.xml"), r"emag\.hu/(.+?)/c$")


def menu_prisma():
    return _path_items(sitemap_locs("https://www.prisma.fi/server-sitemap-categories.xml"), r"/kategoriat/\d+/(.+)$")


def menu_otto():
    urls = []
    for sm in sitemap_locs("https://www.otto.de/category-sitemap/sitemap_index.xml.gz"):
        if re.search(r"sitemap_(marken|sale|inspiration|geschenkideen|wm|weihnachten)", sm):
            continue
        urls += [u for u in sitemap_locs(sm) if "?" not in u]
    return _path_items(urls, r"otto\.de/(.+)$")


def menu_fiverr():
    return _path_items(sitemap_locs("https://www.fiverr.com/sitemap_categories.xml.gz"), r"/categories/(.+)$")


def menu_checkatrade():
    return [{"path": [_deslug(u.rsplit("/", 1)[-1].removesuffix(".xml"))], "url": u}
            for u in sitemap_locs("https://www.checkatrade.com/sitemap/trades.xml")]


def menu_myhammer():
    return _path_items(sitemap_locs("https://www.my-hammer.de/sitemap.services.1.xml"), r"my-hammer\.de/(.+)$")


def menu_helpling():
    urls = sitemap_locs("https://www.helpling.de/sitemap_index.xml")
    return _path_items([u for sm in urls if "page" in sm for u in sitemap_locs(sm)], r"helpling\.de/(?:de_en/)?(.+)$")


def menu_ikea():
    """IKEA category sitemaps: the same category code in five languages -> multilingual labels."""
    by_code: dict[str, dict] = {}
    for lang, loc in (("en", "en-FI"), ("fi", "fi-FI"), ("de", "de-DE"), ("nl", "nl-NL"), ("sv", "sv-SE")):
        for u in sitemap_locs(f"https://www.ikea.com/sitemaps/cat-{loc}_1.xml"):
            m = re.search(r"/cat/([a-z0-9\-]+)-([a-z]{0,3}\d{3,6})/?$", u)
            if m:
                lab = m.group(1)
                if lang in ("fi", "sv", "de"):     # IKEA slugs spell ä/ö/ü as ae/oe/ue (and å as aa in sv)
                    lab = lab.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü" if lang == "de" else "ue")
                    if lang == "sv":
                        lab = lab.replace("aa", "å")
                by_code.setdefault(m.group(2), {"path": [], "labels": {}, "url": u})["labels"][lang] = _deslug(lab)
    items = []
    for code, it in by_code.items():
        it["path"] = [it["labels"].get("en") or next(iter(it["labels"].values()))]
        it["code"] = code
        items.append(it)
    return items


def menu_coolblue():
    page = http_get("https://www.coolblue.nl/ons-assortiment")
    seen, items = set(), []
    for href, text in _anchors(page, r"/[a-z0-9\-]+(?:/[a-z0-9\-]+)?"):
        if href in seen or len(text) > 60:
            continue
        seen.add(href)
        segs = href.strip("/").split("/")
        items.append({"path": [_deslug(s) for s in segs], "labels": {"nl": text}, "url": "https://www.coolblue.nl" + href})
    return items


def menu_jimms():
    page = http_get("https://www.jimms.fi/")
    items, seen = [], set()
    for href, text in _anchors(page, r"/fi/Product/List/[0-9A-Z\-]+/[^\"?]+"):
        slug = href.rsplit("/", 1)[-1]
        if href in seen or "jimm" in slug or "jimm" in text.lower():
            continue
        seen.add(href)
        items.append({"path": [_deslug(p) for p in slug.split("--")], "labels": {"fi": text},
                      "url": "https://www.jimms.fi" + href})
    return items


def menu_verkkokauppa():
    out = []
    for lang in ("en",):
        urls = sitemap_locs(f"https://cdn.verkkokauppa.com/gsitemaps1/content-{lang}.xml")
        out += _path_items([u for u in urls if "/catalog/" in u], r"/catalog/(.+)$")
    return out


def menu_schibsted(host: str) -> list[dict]:
    """tori.fi / blocket.se: category -> sub_category -> product_category, real labels from the filter links."""
    base = f"https://www.{host}/recommerce/forsale/search"
    top = http_get(base)
    items = []
    tops = {}
    for m in re.finditer(r'aria-label="([^"]+)"><a href="\?category=(0\.\d+)"', top):
        tops[m.group(2)] = _html.unescape(m.group(1))
    for cid, name in tops.items():
        items.append({"path": [name], "url": f"{base}?category={cid}"})
        page = http_get(f"{base}?category={cid}")
        subs = {m.group(2): _html.unescape(m.group(1)) for m in
                re.finditer(r'aria-label="([^"]+)"><a href="\?sub_category=(1\.[\d.]+)"', page)}
        for sid, sname in subs.items():
            items.append({"path": [name, sname], "url": f"{base}?sub_category={sid}"})
            sp = http_get(f"{base}?sub_category={sid}")
            for m in re.finditer(r'<a href="\?product_category=(2\.[\d.]+)"[^>]*?aria-label="([^"]+)"', sp):
                items.append({"path": [name, sname, _html.unescape(m.group(2))],
                              "url": f"{base}?product_category={m.group(1)}"})
    return items


SHOP_ROOTS = ["electronics", "appliances", "home-garden", "sports-outdoors", "toys-games", "software", "office",
              "health-beauty", "baby-kids", "diy", "hobbies", "media", "vehicles", "furniture"]

# site key -> (domain, language, lane, allowed roots ('products' | 'services' | list), extractor)
MENU_SITES: dict[str, tuple] = {
    "ipon": ("ipon.hu", "hu", "new", SHOP_ROOTS, menu_ipon),
    "power": ("power.fi", "fi", "new", SHOP_ROOTS, menu_power),
    "marktplaats": ("marktplaats.nl", "nl", "used", "all", menu_marktplaats),
    "kleinanzeigen": ("kleinanzeigen.de", "de", "used", "all", menu_kleinanzeigen),
    "mediamarkt": ("mediamarkt.de", "de", "new", SHOP_ROOTS, menu_mediamarkt),
    "mediamarkt_services": ("mediamarkt.de", "de", "service", "services", menu_mediamarkt_services),
    "emag": ("emag.hu", "hu", "new", "products", menu_emag),
    "prisma": ("prisma.fi", "fi", "new", "products", menu_prisma),
    "otto": ("otto.de", "de", "new", "products", menu_otto),
    "ikea": ("ikea.com", "en", "new", ["furniture", "home-garden", "appliances", "baby-kids"], menu_ikea),
    "coolblue": ("coolblue.nl", "nl", "new", SHOP_ROOTS, menu_coolblue),
    "jimms": ("jimms.fi", "fi", "new", ["electronics", "software", "office"], menu_jimms),
    "verkkokauppa": ("verkkokauppa.com", "en", "new", SHOP_ROOTS, menu_verkkokauppa),
    "tori": ("tori.fi", "fi", "used", "all", lambda: menu_schibsted("tori.fi")),
    "blocket": ("blocket.se", "sv", "used", "all", lambda: menu_schibsted("blocket.se")),
    "fiverr": ("fiverr.com", "en", "service", ["digital-services", "professional"], menu_fiverr),
    "checkatrade": ("checkatrade.com", "en", "service", "services", menu_checkatrade),
    "myhammer": ("my-hammer.de", "de", "service", "services", menu_myhammer),
    "helpling": ("helpling.de", "en", "service", ["home-services"], menu_helpling),
}


def _city_page(path: tuple) -> bool:
    try:
        from agora import places
        return bool(places.find_place(path[-1].lower()))
    except Exception:
        return False


# where a service platform's unmatched top-level categories go, and which entries are SEO junk
MENU_ANCHOR = {"mediamarkt_services": "home-services.appliance-electronics-repair", "helpling": "home-services.cleaning",
               "checkatrade": "trades.other-trades-specialists", "myhammer": "trades.other-trades-specialists",
               "fiverr": "digital-services"}
MENU_DROP = {
    "mediamarkt_services": lambda p: _city_page(p) or bool(re.search(r"reparatur\s+\S", p[-1], re.I)) or p[0].lower() in ("ankauf", "filialen", "partner", "kontakt"),
    "helpling": lambda p: len(p) > 1 or _city_page(p),
    "otto": lambda p: p[0].lower() in ("marken", "sale", "inspiration"),
    "coolblue": lambda p: p[0].lower() in ("black friday", "winkels", "klantenservice", "aanbieding", "alle merken"),
}


def fetch_menus(only: list[str] | None = None) -> None:
    MENUS.mkdir(parents=True, exist_ok=True)
    for key, (domain, lang, lane, roots, fn) in MENU_SITES.items():
        if only and key not in only:
            continue
        p = MENUS / f"{key}.json"
        if p.exists() and not only:
            continue
        try:
            items = fn()
        except Exception as e:
            print("menu failed", key, type(e).__name__, e, file=sys.stderr)
            items = []
        p.write_text(json.dumps({"site": key, "domain": domain, "lang": lang, "lane": lane, "items": items},
                                ensure_ascii=False))
        print(f"menu {key}: {len(items)} categories")


# ------------------------------------------------------------------ normalisation

GENERIC = {"accessories", "accessory", "parts", "part", "other", "others", "misc", "miscellaneous", "supplies",
           "equipment", "products", "product", "services", "service", "items", "item", "sets", "set", "kits", "kit",
           "tarvikkeet", "muut", "zubehör", "zubehor", "sonstige", "sonstiges", "overig", "overige", "accessoires",
           "tillbehör", "tillbehor", "övrigt", "ovrigt", "general", "various", "spare"}
STOP = {"and", "or", "the", "of", "for", "with", "a", "an", "in", "&", "ja", "tai", "und", "oder", "für", "fur", "en",
        "of", "voor", "och", "eller", "för", "for", "et", "és", "es", "i", "y", "e", "und", "de", "la", "le", "der",
        "die", "das", "het", "een", "til", "og"}


def fold(s: str, lang: str = "en") -> str:
    s = s.lower().replace("ß", "ss")
    if lang == "de":
        s = s.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    if lang == "de":
        s = s.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return s


def tokens(s: str, lang: str = "en") -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9]+", fold(s, lang)):
        if t in STOP:
            continue
        if len(t) > 4 and t.endswith("ies"):
            t = t[:-3] + "y"
        elif len(t) > 5 and t.endswith("ves") and t[-4] in "lr":
            t = t[:-3] + "f"
        elif len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
            t = t[:-1]
        out.append(t)
    return out


def key(s: str, lang: str = "en") -> str:
    return " ".join(tokens(s, lang))


def is_generic(k: str) -> bool:
    return not k or all(t in GENERIC or t.rstrip("s") in GENERIC for t in k.split())


def parse_label(spec: str) -> tuple[dict[str, str], list[str]]:
    main, _, syn = spec.partition("~")
    parts = [p.strip() for p in main.split("|")]
    labels = {lang: p for lang, p in zip(("en", "fi", "de", "nl", "sv"), parts) if p}
    syns = [s.strip() for s in syn.split(",") if s.strip()]
    return labels, syns


# ------------------------------------------------------------------ the tree under construction

class Tree:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.keys: dict[tuple[str, str], set[str]] = collections.defaultdict(set)   # (lang, key) -> ids
        self.roots: list[str] = []
        self.merges = collections.Counter()
        self.adds = collections.Counter()
        self.folds = collections.Counter()
        self.aliases: dict[str, str] = {}       # removed id -> the node that took it over

    # -- basic ops
    def depth(self, nid: str) -> int:
        return self.nodes[nid]["depth"]

    def root_of(self, nid: str) -> str:
        return self.nodes[nid]["root"]

    def add(self, nid: str, parent: str | None, labels: dict[str, str], *, src: str, kind: str | None = None,
            syn: list[str] | None = None) -> str:
        assert nid not in self.nodes, nid
        d = 1 if parent is None else self.depth(parent) + 1
        n = {"id": nid, "parent": parent, "labels": {}, "syn": [], "kind": kind, "src": {src}, "codes": {},
             "where": [], "children": [], "depth": d, "root": nid if parent is None else self.root_of(parent)}
        self.nodes[nid] = n
        if parent is None:
            self.roots.append(nid)
        else:
            self.nodes[parent]["children"].append(nid)
        self.merge_into(nid, labels, syn or [], src=None)
        self.adds[src] += 1
        return nid

    def merge_into(self, nid: str, labels: dict[str, str], syn: list[str], *, src: str | None,
                   codes: dict | None = None) -> None:
        n = self.nodes[nid]
        if src:
            n["src"].add(src)
            self.merges[src] += 1
        for lang, lab in labels.items():
            lab = (lab or "").strip()
            if not lab:
                continue
            if lang not in n["labels"]:
                n["labels"][lang] = lab
            elif key(n["labels"][lang], lang) != key(lab, lang) and lab not in n["syn"]:
                n["syn"].append(lab)
            self.keys[(lang, key(lab, lang))].add(nid)
        for s in syn:
            if s and s not in n["syn"] and s not in n["labels"].values():
                n["syn"].append(s)
        for k, v in (codes or {}).items():
            n["codes"].setdefault(k, [])
            for x in (v if isinstance(v, list) else [v]):
                if x not in n["codes"][k]:
                    n["codes"][k].append(x)

    def in_subtree(self, nid: str, top: str) -> bool:
        while nid is not None:
            if nid == top:
                return True
            nid = self.nodes[nid]["parent"]
        return False

    def find(self, labels: dict[str, str], parent: str, *, roots: list[str] | None = None) -> str | None:
        """The node that means the same as `labels`: child of parent > parent's subtree > parent's root >
        any of `roots`. Generic labels ('Accessories') only match among the parent's children."""
        cands: set[str] = set()
        hits: collections.Counter = collections.Counter()
        generic = True
        for lang, lab in labels.items():
            k = key(lab, lang)
            if not k:
                continue
            if not is_generic(k):
                generic = False
            got = self.keys.get((lang, k), set())
            cands |= got
            hits.update(got)
        if not cands:
            return None
        if parent in cands:
            return parent
        kids = sorted(c for c in cands if self.nodes[c]["parent"] == parent)
        if kids:
            return kids[0]
        if generic:
            return None
        sub = [c for c in cands if c != parent and self.in_subtree(c, parent)]
        if sub:
            return min(sub, key=lambda c: (self.depth(c), c))
        root = self.root_of(parent)
        same_root = [c for c in cands if self.root_of(c) == root and self.depth(c) > 1
                     and not self.in_subtree(parent, c)]
        if same_root:
            return min(same_root, key=lambda c: (self.depth(c), c))
        if roots:
            other = [c for c in cands if self.root_of(c) in roots and self.depth(c) > 1]
            if other:
                return min(other, key=lambda c: (self.depth(c), c))
        # anywhere in the tree when three or more languages agree (CPV 'Bicycles' = Shopify 'Bicycles')
        strong = [c for c, n in hits.items() if n >= 3 and self.depth(c) > 1 and not self.in_subtree(parent, c)]
        if strong:
            return min(strong, key=lambda c: (-hits[c], self.depth(c), c))
        return None

    def height(self, nid: str) -> int:
        kids = self.nodes[nid]["children"]
        return 1 + max((self.height(c) for c in kids), default=0)

    def move(self, nid: str, new_parent: str) -> None:
        n = self.nodes[nid]
        self.nodes[n["parent"]]["children"].remove(nid)
        self.nodes[new_parent]["children"].append(nid)
        n["parent"] = new_parent
        stack = [nid]
        while stack:
            x = stack.pop()
            px = self.nodes[self.nodes[x]["parent"]]
            self.nodes[x]["depth"] = px["depth"] + 1
            self.nodes[x]["root"] = px["root"]
            stack.extend(self.nodes[x]["children"])

    def absorb(self, src: str, dst: str, *, same: bool) -> None:
        """src disappears into dst: its children, domains, codes and synonyms move; its labels fill dst's missing
        languages when it means the same (same=True), else they become synonyms. src's id becomes an alias."""
        n, d = self.nodes[src], self.nodes[dst]
        assert not self.in_subtree(dst, src), (src, dst)
        for lang, lab in n["labels"].items():
            if same and lang not in d["labels"]:
                d["labels"][lang] = lab
            elif lab not in d["syn"] and lab not in d["labels"].values():
                d["syn"].append(lab)
        for x in n["syn"]:
            if x not in d["syn"] and x not in d["labels"].values():
                d["syn"].append(x)
        for k, v in n["codes"].items():
            for x in v:
                if x not in d["codes"].setdefault(k, []):
                    d["codes"][k].append(x)
        for w in n["where"]:
            if w not in d["where"]:
                d["where"].append(w)
        d["src"] |= n["src"]
        for c in list(n["children"]):
            if d["depth"] + self.height(c) <= MAX_DEPTH:
                self.move(c, dst)
            else:
                self.absorb(c, src, same=False)       # too deep under dst: fold into src first (moves along)
        for c in list(n["children"]):
            self.move(c, dst)
        self.nodes[n["parent"]]["children"].remove(src)
        del self.nodes[src]
        self.aliases[src] = dst

    def index_synonyms(self, nid: str, syns: list[str]) -> None:
        """Make hand-written synonyms merge targets too ('Electricians' -> 'Electrical work')."""
        for s_ in syns:
            for lang in ("en", "fi", "de", "nl", "sv"):
                k = key(s_, lang)
                if k and not is_generic(k):
                    self.keys[(lang, k)].add(nid)

    def place(self, nid: str, parent: str, labels: dict[str, str], *, src: str, kind: str | None = None,
              syn: list[str] | None = None, codes: dict | None = None, roots: list[str] | None = None,
              merge_only: bool = False) -> str | None:
        """Merge into an existing node with the same meaning, or add under parent (folding past MAX_DEPTH)."""
        hit = self.find(labels, parent, roots=roots)
        if hit:
            self.merge_into(hit, labels, syn or [], src=src, codes=codes)
            return hit
        if merge_only:
            return None
        if self.depth(parent) >= MAX_DEPTH:
            self.merge_into(parent, {}, list(labels.values()) + (syn or []), src=None)
            self.folds[src] += 1
            return parent
        new = self.add(nid, parent, labels, src=src, kind=kind, syn=syn)
        if codes:
            self.merge_into(new, {}, [], src=None, codes=codes)
        return new

    def add_where(self, nid: str, domain: str, lane: str) -> None:
        w = self.nodes[nid]["where"]
        if [domain, lane] not in w:
            w.append([domain, lane])


SERVICE_ROOTS = [r for r, (_, k) in curated.ROOTS.items() if k == "service"]
PRODUCT_ROOTS = [r for r, (_, k) in curated.ROOTS.items() if k != "service"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:40]


# ------------------------------------------------------------------ 1. curated

def build_curated(t: Tree) -> None:
    for rid, (spec, kind) in curated.ROOTS.items():
        labels, syn = parse_label(spec)
        t.add(rid, None, labels, src="curated", kind=kind, syn=syn)
        for dom, lane in curated.WHERE.get(rid, []):
            t.add_where(rid, dom, lane)

    def walk(parent: str, tree: dict) -> None:
        for spec, kids in tree.items():
            labels, syn = parse_label(spec)
            nid = f"{parent}.{slug(labels['en'])}"
            kind = "service" if t.nodes[parent]["kind"] in ("service",) or parent.startswith("pets.") or \
                "service" in labels["en"].lower() else None
            if t.root_of(parent) == "software":
                kind = "digital"
            if t.root_of(parent) == "food-drink":
                kind = "service"
            t.add(nid, parent, labels, src="curated", kind=kind, syn=syn)
            t.index_synonyms(nid, syn)
            walk(nid, kids)

    for rid, tree in curated.SERVICES.items():
        walk(rid, tree)
    for nid, doms in curated.WHERE.items():
        if nid in t.nodes and t.depth(nid) > 1:
            for dom, lane in doms:
                t.add_where(nid, dom, lane)
        elif nid not in t.nodes:
            print("  WHERE target missing:", nid)
    # pets services subtree: kind service
    for nid, n in t.nodes.items():
        if nid.startswith("pets.pet-services"):
            n["kind"] = "service"


# ------------------------------------------------------------------ 2. Shopify (+ Google labels)

SHOPIFY_ROOT = {
    "ap": "pets", "aa": "fashion", "ae": "hobbies", "ae-1": "events-leisure", "bt": "baby-kids", "bi": "business",
    "co": "electronics", "el": "electronics", "fb": "food-drink", "fr": "furniture", "gc": "software", "ha": "diy",
    "hb": "health-beauty", "hg": "home-garden", "hg-8": "appliances", "hg-9": "appliances", "hg-11-7": "appliances",
    "lb": "fashion", "ma": "health-beauty", "ma-2": "sports-outdoors", "me": "media", "me-9": "education",
    "os": "office", "rc": "hobbies", "so": "software", "sg": "sports-outdoors", "tg": "toys-games", "vp": "vehicles",
    "se": "professional", "se-1": "auto-services", "se-2": "trades", "se-3": "professional", "se-3-2": "transport",
    "se-4": "events-leisure", "se-4-4": "travel", "se-8": "utilities", "se-9": "food-drink", "se-5": "trades",
    "se-6": "personal-services", "se-6-1": "beauty-wellness", "se-6-2": "home-services", "se-6-3": "education",
    "se-6-4": "beauty-wellness", "se-6-5": "health-services", "se-7": "professional", "se-7-2": "finance-insurance",
    "se-7-3": "digital-services", "se-7-5": "property", "se-7-6": "property",
}
SHOPIFY_SKIP = ("bu", "na", "pa")
SHOPIFY_LANG = {"nb": "nb"}
GOOGLE_LANG = {"fi-FI": "fi", "de-DE": "de", "nl-NL": "nl", "sv-SE": "sv", "fr-FR": "fr", "da-DK": "da", "no-NO": "nb",
               "es-ES": "es", "it-IT": "it", "pl-PL": "pl"}


def read_shopify() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """local id -> {lang: own label}, local id -> en full path"""
    labels: dict[str, dict[str, str]] = collections.defaultdict(dict)
    full: dict[str, str] = {}
    for lang in LANGS:
        p = RAW / f"shopify-{lang}.txt"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.startswith("gid://"):
                continue
            gid, _, path = line.partition(" : ")
            lid = gid.strip().rsplit("/", 1)[-1]
            labels[lid][lang] = path.rsplit(" > ", 1)[-1].strip()
            if lang == "en":
                full[lid] = path.strip()
    return labels, full


def read_google() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    labels: dict[str, dict[str, str]] = collections.defaultdict(dict)
    full: dict[str, str] = {}
    for code, lang in [("en-US", "en"), *GOOGLE_LANG.items()]:
        p = RAW / f"gpt-{code}.txt"
        if not p.exists() or p.stat().st_size < 1000:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(\d+) - (.+)$", line)
            if m:
                labels[m.group(1)][lang] = m.group(2).rsplit(" > ", 1)[-1].strip()
                if lang == "en":
                    full[m.group(1)] = m.group(2)
    return labels, full


def shopify_google_map() -> dict[str, list[str]]:
    p = RAW / "shopify-mappings.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    out: dict[str, list[str]] = {}
    for m in data["mappings"]:
        if not m["output_taxonomy"].startswith("google/") or not m["input_taxonomy"].startswith("shopify/2026"):
            continue
        for r in m["rules"]:
            lid = r["input"]["category"]["id"].rsplit("/", 1)[-1]
            out[lid] = [c["id"] for c in r["output"]["category"]]
    return out


def build_shopify(t: Tree) -> dict[str, str]:
    labels, full = read_shopify()
    gl, gfull = read_google()
    gmap = shopify_google_map()
    local2node: dict[str, str] = {}
    used_google = set()
    for lid in sorted(labels, key=lambda x: (x.count("-"), [int(p) if p.isdigit() else p for p in x.split("-")])):
        top = lid.split("-")[0]
        if top in SHOPIFY_SKIP or "en" not in labels[lid]:
            continue
        lab = dict(labels[lid])
        syn: list[str] = []
        gids = gmap.get(lid, [])
        for g in gids:
            # a google node is "the same" only when its own en label matches; else it is just a broader hint
            if key(gl.get(g, {}).get("en", ""), "en") == key(lab["en"], "en"):
                used_google.add(g)
                for lang, glab in gl[g].items():
                    if lang not in lab:
                        lab[lang] = glab
                    elif key(glab, lang) != key(lab[lang], lang):
                        syn.append(glab)
        codes = {"shopify": lid, **({"google": gids} if gids else {})}
        # target parent: explicit re-rooting, else the Shopify parent
        parts = lid.split("-")
        mapped = None
        for i in range(len(parts), 0, -1):
            pre = "-".join(parts[:i])
            if pre in SHOPIFY_ROOT:
                mapped = (pre, SHOPIFY_ROOT[pre])
                break
        if len(parts) == 1:
            # a Shopify root: merge its labels into our root as synonyms
            rid = SHOPIFY_ROOT.get(lid)
            if rid and lid != "se":
                t.merge_into(rid, {}, list(lab.values()), src="shopify", codes=codes)
                local2node[lid] = rid
            continue
        if mapped and mapped[0] == lid:
            parent = mapped[1]
        else:
            parent = local2node.get("-".join(parts[:-1]))
        if not parent:
            continue
        kind = None
        if top == "se":
            kind = "service"
        elif top in ("so", "gc"):
            kind = "digital"
        nid = "sp:" + lid
        local2node[lid] = t.place(nid, parent, lab, src="shopify", kind=kind, syn=syn, codes=codes,
                                  roots=SERVICE_ROOTS if top == "se" else None)
    print(f"shopify: {len(local2node)} categories placed, google ids merged {len(used_google)}")
    return local2node


# ------------------------------------------------------------------ 3. CPV (EU public procurement vocabulary)

# CPV code prefix -> root (or curated node id). The longest prefix wins.
CPV_MAP = {
    "03": "business", "031": "food-drink", "0311": "business", "0312": "home-garden", "033": "food-drink",
    "09": "utilities", "091": "vehicles", "0913": "vehicles", "092": "utilities", "093": "utilities",
    "14": "business", "15": "food-drink", "16": "business", "161": "home-garden", "18": "fashion", "181": "business",
    "19": "business", "22": "media", "224": "office", "228": "office", "24": "business", "30": "electronics",
    "301": "office", "302": "electronics", "31": "diy", "315": "home-garden", "316": "diy", "32": "electronics",
    "33": "health-beauty", "331": "business", "336": "health-beauty", "337": "health-beauty", "34": "vehicles",
    "35": "business", "37": "hobbies", "374": "sports-outdoors", "375": "toys-games", "38": "business",
    "39": "home-garden", "391": "furniture", "392": "home-garden", "397": "appliances", "41": "utilities",
    "42": "business", "43": "business", "44": "diy",
    "45": "trades", "48": "software",
    "50": "trades", "501": "auto-services", "502": "auto-services", "503": "home-services", "504": "business",
    "505": "trades", "508": "home-services", "51": "trades", "55": "travel", "553": "food-drink",
    "554": "food-drink", "555": "food-drink", "556": "food-drink", "60": "transport", "601": "transport",
    "63": "transport", "635": "travel", "64": "transport", "642": "utilities", "65": "utilities",
    "66": "finance-insurance", "70": "property", "71": "professional", "72": "digital-services", "73": "professional",
    "76": "business", "77": "business", "7731": "home-services", "7734": "home-services",
    "79": "professional", "7995": "events-leisure", "7996": "events-leisure", "7997": "professional",
    "80": "education", "85": "health-services", "852": "pets", "853": "personal-services", "90": "utilities",
    "909": "home-services", "92": "events-leisure", "98": "personal-services", "9832": "beauty-wellness",
    "9833": "beauty-wellness",
}
CPV_SKIP = ("75",)   # public administration, defence, social security


def read_cpv() -> dict[str, dict[str, str]]:
    p = RAW / "cpv" / "cpv_2008.xml"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    want = {l.upper(): l for l in LANGS}
    for m in re.finditer(r'<CPV CODE="(\d{8})-\d">(.*?)</CPV>', text, re.S):
        labs = {}
        for lm in re.finditer(r'<TEXT LANG="(\w\w)">(.*?)</TEXT>', m.group(2), re.S):
            if lm.group(1) in want:
                labs[want[lm.group(1)]] = _html.unescape(lm.group(2)).strip()
        out[m.group(1)] = labs
    return out


def cpv_parent(code: str, codes: dict) -> str | None:
    digits = code.rstrip("0")
    while len(digits) > 2:
        digits = digits[:-1]
        cand = digits.ljust(8, "0")
        if cand in codes and cand != code:
            return cand
    return None


def build_cpv(t: Tree) -> None:
    codes = read_cpv()
    placed: dict[str, str] = {}
    for code in sorted(codes, key=lambda c: (len(c.rstrip("0")), c)):
        if code.startswith(CPV_SKIP):
            continue
        sig = code.rstrip("0")
        pre = next((sig[:i] for i in range(min(len(sig), 5), 1, -1) if sig[:i] in CPV_MAP), None)
        if pre is None:
            continue
        target = CPV_MAP[pre]
        par = cpv_parent(code, codes)
        if par and par in placed and par.rstrip("0").startswith(pre):
            parent = placed[par]
        else:
            parent = target
        labs = codes[code]
        if "en" not in labs:
            continue
        kind = "service" if int(code[:2]) >= 45 and code[:2] != "48" else None
        if code[:2] == "48":
            kind = "digital"
        roots = SERVICE_ROOTS if kind == "service" else None
        placed[code] = t.place("cpv:" + code[:8].rstrip("0").ljust(2, "0"), parent, labs, src="cpv", kind=kind,
                               codes={"cpv": code}, roots=roots)
    print(f"cpv: {len(placed)} codes placed")


# ------------------------------------------------------------------ 4. NACE Rev. 2 (TOL 2008, en/fi/sv)

NACE_MAP = {
    "43": "trades", "41": "trades", "452": "auto-services", "49": "transport", "4932": "transport",
    "50": "transport", "51": "travel", "53": "transport", "55": "travel", "56": "food-drink", "61": "utilities",
    "62": "digital-services", "631": "digital-services", "64": "finance-insurance", "65": "finance-insurance",
    "66": "finance-insurance", "68": "property", "69": "professional", "70": "professional", "71": "professional",
    "72": "professional", "73": "professional", "74": "professional", "742": "events-leisure", "75": "pets",
    "77": "professional", "771": "travel", "772": "events-leisure", "78": "professional", "79": "travel",
    "80": "professional", "81": "home-services", "82": "professional", "85": "education", "86": "health-services",
    "87": "personal-services", "88": "personal-services", "90": "events-leisure", "91": "events-leisure",
    "92": "events-leisure", "93": "events-leisure", "95": "home-services", "96": "personal-services",
    "9602": "beauty-wellness", "9604": "beauty-wellness", "35": "utilities", "36": "utilities", "38": "utilities",
}


def read_tol() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lang in ("en", "fi", "sv"):
        p = RAW / f"tol2008-{lang}.json"
        if not p.exists():
            continue
        for it in json.loads(p.read_text()):
            code = it.get("code") or it.get("localId", "")
            names = it.get("classificationItemNames") or []
            name = next((n.get("name") for n in names if n.get("lang") == lang), None) or \
                (names[0].get("name") if names else None)
            if not code or not name:
                continue
            e = out.setdefault(code, {"labels": {}, "level": it.get("level")})
            e["labels"][lang] = name.strip()
    return out


def build_nace(t: Tree) -> None:
    items = read_tol()
    placed: dict[str, str] = {}
    n = 0
    for code in sorted(items, key=lambda c: (len(c), c)):
        if not code[:2].isdigit() or len(code) > 5:
            continue
        pre = next((code[:i] for i in range(min(len(code), 4), 1, -1) if code[:i] in NACE_MAP), None)
        if not pre:
            continue
        parent = placed.get(code[:-1]) if len(code) > 2 and code[:-1].startswith(pre) else None
        parent = parent or NACE_MAP[pre]
        labs = items[code]["labels"]
        if "en" not in labs:
            continue
        nace = f"{code[:2]}.{code[2:4]}" if len(code) >= 4 else code
        placed[code] = t.place("nace:" + code, parent, labs, src="nace", kind="service",
                               codes={"nace": nace}, roots=SERVICE_ROOTS)
        n += 1
    print(f"nace: {n} activities placed")


# ------------------------------------------------------------------ 5. Yelp categories (names only)

YELP_ROOT = {
    "active": "events-leisure", "arts": "events-leisure", "auto": "auto-services", "beautysvc": "beauty-wellness",
    "bicycles": "sports-outdoors", "education": "education", "eventservices": "events-leisure",
    "financialservices": "finance-insurance", "food": "food-drink", "health": "health-services",
    "homeservices": "home-services", "hotelstravel": "travel", "localservices": "personal-services",
    "pets": "pets", "professional": "professional", "realestate": "property", "restaurants": "food-drink",
    "nightlife": "events-leisure",
}
YELP_ANCHOR = {"restaurants": "food-drink.restaurants-takeaway", "food": "food-drink.restaurants-takeaway",
               "nightlife": "events-leisure.nightlife-bars", "pets": "pets.pet-services"}


def read_yelp() -> list[dict]:
    p = RAW / "yelp-categories.html"
    if not p.exists():
        p = RAW / "yelp-categories.json"   # earlier name of the same page
    if not p.exists():
        return []
    s = _html.unescape(_html.unescape(p.read_text(encoding="utf-8")))
    stack, last, out, seen = [], None, [], set()
    for m in re.finditer(r"<ul>|</ul>|<li>\s*(.+?)\s*\((\w+),\s*(All|\[[^\]]*\])\)\s*</li>", s):
        g = m.group(0)
        if g == "<ul>":
            if last:
                stack.append(last)
        elif g == "</ul>":
            if stack:
                stack.pop()
        else:
            last = m.group(2)
            if last in seen:
                continue
            seen.add(last)
            out.append({"alias": last, "title": m.group(1), "parent": stack[-1] if stack else None})
    return out


def build_yelp(t: Tree) -> None:
    cats = read_yelp()
    by_alias = {c["alias"]: c for c in cats}
    placed: dict[str, str] = {}
    for c in cats:
        chain, a = [], c["alias"]
        while a:
            chain.append(a)
            a = by_alias.get(a, {}).get("parent")
        top = chain[-1]
        if top not in YELP_ROOT:
            continue
        if c["alias"] == top:
            anchor = YELP_ANCHOR.get(top)
            placed[top] = anchor if anchor in t.nodes else YELP_ROOT[top]
            t.merge_into(placed[top], {}, [c["title"]], src="yelp", codes={"yelp": top})
            continue
        parent = placed.get(c["parent"])
        if not parent:
            continue
        placed[c["alias"]] = t.place("yelp:" + c["alias"], parent, {"en": c["title"]}, src="yelp",
                                     kind="service", codes={"yelp": c["alias"]}, roots=SERVICE_ROOTS)
    print(f"yelp: {len(placed)} categories placed")


# ------------------------------------------------------------------ 6. shop / marketplace / service menus

def _tok_eq(x: str, y: str) -> bool:
    if x == y:
        return True
    m = min(len(x), len(y))
    if m < 5:
        return False
    c = 0
    while c < m and x[c] == y[c]:
        c += 1
    # same word, other inflection: a long shared prefix AND only a short tail on the longer word
    # ('astianpesukone' ~ 'astianpesukoneet', but not 'antikt' ~ 'antikalkpatron')
    return c >= max(5, int(0.8 * m)) and max(len(x), len(y)) - c <= 4


def _sim(a: list[str], b: list[str]) -> float:
    used, hit = set(), 0
    for x in a:
        for j, y in enumerate(b):
            if j not in used and _tok_eq(x, y):
                used.add(j)
                hit += 1
                break
    return hit / max(len(a), len(b))


def menu_target(n: dict) -> bool:
    """Shop menus only merge into readable shopper categories, never into CPV/NACE-only nodes."""
    return bool(n["src"] - {"cpv", "nace"})


class TokenIndex:
    """token -> node ids over current labels in the given roots (for placing flat menu entries)."""

    def __init__(self, t: Tree, roots: list[str]) -> None:
        self.t = t
        self.idx: dict[str, set[str]] = collections.defaultdict(set)
        rs = set(roots)
        for nid, n in t.nodes.items():
            if n["root"] not in rs:
                continue
            for lang, lab in n["labels"].items():
                for tok in tokens(lab, lang):
                    self.idx[tok].add(nid)
            for s in n["syn"][:12]:
                for tok in tokens(s, "de" if re.search("[äöü]", s) else "en"):
                    self.idx[tok].add(nid)
        self.n = max(1, len(t.nodes))
        self.vocab = sorted(self.idx)

    def _near(self, tok: str) -> set[str]:
        """Nodes with a token that is the same word inflected ('astianpesukone' ~ 'astianpesukoneet')."""
        if len(tok) < 5:
            return set()
        stem = tok[:max(5, int(0.8 * len(tok)))]
        out: set[str] = set()
        i = bisect.bisect_left(self.vocab, stem)
        while i < len(self.vocab) and self.vocab[i].startswith(stem):
            if _tok_eq(tok, self.vocab[i]):
                out |= self.idx[self.vocab[i]]
            i += 1
        return out

    def ranked(self, label: str, lang: str, within: str | None = None, n: int = 12) -> list[str]:
        toks = [x for x in tokens(label, lang) if x not in GENERIC]
        score: dict[str, float] = collections.Counter()
        for tok in toks:
            post = self.idx.get(tok) or self._near(tok)
            if not post or len(post) > 4000:
                continue
            w = 1.0 / (1 + len(post)) ** 0.5
            for nid in post:
                if nid in self.t.nodes and (not within or self.t.in_subtree(nid, within)):
                    score[nid] += w
        return [k for k, _ in sorted(score.items(), key=lambda kv: (-kv[1], self.t.depth(kv[0]), kv[0]))[:n]]

    def fuzzy(self, label: str, lang: str, roots: list[str], within: str | None = None,
              max_depth: int = MAX_DEPTH) -> str | None:
        """A node whose label (same language, or English) says the same with other inflection/wording:
        token pairs equal or sharing a long prefix ('astianpesukoneet' ~ 'astianpesukone'). Inside a known
        parent it is enough that every token of the menu label is in the node label ('Kannettavat' ~
        'Kannettavat tietokoneet')."""
        a = [x for x in tokens(label, lang) if x not in GENERIC] or tokens(label, lang)
        if not a:
            return None
        for nid in self.ranked(label, lang, within):
            n = self.t.nodes[nid]
            if n["root"] not in roots or not menu_target(n) or n["depth"] > max_depth:
                continue
            for l2 in (lang, "en"):
                lab = n["labels"].get(l2)
                if not lab or not same_shape(label, lab):
                    continue
                b = [x for x in tokens(lab, l2) if x not in GENERIC] or tokens(lab, l2)
                if not b:
                    continue
                if _sim(a, b) >= 0.75 or (within and len(b) <= 3 and _sim(a, b) * max(len(a), len(b)) >= len(a)):
                    return nid
        return None

    def specialize(self, label: str, lang: str, roots: list[str]) -> str | None:
        """The node this label is a narrower case of: every token of the node label is in the menu label
        and the menu label says more ('Mikrowellen mit Grill' -> 'Mikrowellen'). Most specific wins."""
        a = [x for x in tokens(label, lang) if x not in GENERIC]
        if len(a) < 2 or LIST_LABEL.search(label):     # 'Modelling paste, clay and sand' is not 'Sand'
            return None
        best, best_n = None, 0
        for nid in self.ranked(label, lang, n=25):
            n = self.t.nodes[nid]
            if n["root"] not in roots or not menu_target(n) or self.t.depth(nid) >= MAX_DEPTH:
                continue
            lab = n["labels"].get(lang)
            if not lab:
                continue
            b = [x for x in tokens(lab, lang) if x not in GENERIC]
            if b and len(b) < len(a) and all(any(_tok_eq(x, y) for y in a) for x in b) and len(b) > best_n:
                best, best_n = nid, len(b)
        return best

    def best(self, label: str, lang: str, within: str | None = None) -> tuple[str | None, float]:
        toks = [x for x in tokens(label, lang) if x not in GENERIC]
        if not toks:
            return None, 0.0
        score: dict[str, float] = collections.Counter()
        for tok in toks:
            post = self.idx.get(tok, ())
            if not post or len(post) > 4000:
                continue
            w = 1.0 / (1 + len(post)) ** 0.5
            for nid in post:
                if within and not self.t.in_subtree(nid, within):
                    continue
                score[nid] += w
        if not score:
            return None, 0.0
        tot = sum(1.0 / (1 + len(self.idx.get(x, ()))) ** 0.5 for x in toks)
        best = max(score, key=lambda k: (score[k], -self.t.depth(k)))
        return best, score[best] / tot if tot else 0.0


LIST_LABEL = re.compile(r",|&|\+|\b(and|ja|und|en|och|és|es|og|et|i|y|e|sowie|samt)\b", re.I)


def same_shape(a: str, b: str) -> bool:
    """'Computers en software' (a list of two things) is not 'Computer Software' (one thing)."""
    return bool(LIST_LABEL.search(a)) == bool(LIST_LABEL.search(b))


def roots_for(spec) -> list[str]:
    if spec == "products":
        return PRODUCT_ROOTS
    if spec == "services":
        return SERVICE_ROOTS
    if spec == "all":
        return PRODUCT_ROOTS + SERVICE_ROOTS
    return list(spec)


# ------------------------------------------------------------------ 6a. menu hygiene: junk pages, facets, spelling

# Shop menus and sitemaps also list pages that are not categories of goods or services: test pages, campaigns,
# news/info, B2B and reference-customer pages, jobs, account/help/store pages, gift-under-price pages, the shop's own
# vouchers. Those are dropped with everything below them.
JUNK_RULES: list[tuple[str, str]] = [
    ("test page", r"\b(test|beringar\d*|slices|digilife)\b"),
    ("campaign", r"black\s*friday|cyber\s*monday|season\s*sale|\bsale\b|\boutlet\b|\bdeals?\b|aanbieding|\bangebote\b|"
                 r"\baktionen\b|\btarjous|\bkampanja|\bkampanj\b|loppuhuipennus|alennusmyynti|prime\s*day|singles\s*day|"
                 r"\bnieuw!|\bneuheiten\b"),
    ("info/news", r"\b(corona\w*|covid\w*|newsletter|blog|ratgeber|inspiration|ideen|geschenkideen|gift ideas|"
                  r"lahjaideat|cadeautips)\b"),
    ("b2b", r"\bb2b\b|referenzkund"),
    ("jobs", r"\b(jobs|vacatures?|karriere|stellenangebote?|työpaikat|lediga jobb|careers|sonstige berufe|"
             r"callcenter)\b"),
    ("account/help", r"\b(klantenservice|kundenservice|asiakaspalvelu|kundtjänst|customer service|mijn|my account|"
                     r"kundenkonto|login|faq|filialen|winkels|myymälät|store locator|terminvereinbarung|"
                     r"schwachstellen\w*|smartbar|relution|diged|plusgarantie|plusschutz|garantieerweiterung|"
                     r"zahnzusatzversicherung|kaufberatung|tarifberatung|zahlung|lieferung|umtausch|rueckgabe|rückgabe|"
                     r"alle merken|marken|merken|brands|garantie)\b"),
    ("price page", r"\b(lahja|lahjat)\b|\d+\s?(€|euro|eur)\b"),
]
JUNK_KEEP = re.compile(r"penetration|\bpat\b|drug|allergy|\bdna\b|hearing|driving|\bmot\b", re.I)
SELF_NAMES = ("coolblue", "helpling", "mediamarkt", "prisma", "emag", "ipon", "jimms", "blocket", "verkkokauppa",
              "checkatrade", "my-hammer", "myhammer", "fiverr", "kleinanzeigen", "marktplaats", "otto.de")
# 'Other ...' buckets and pure size/spec/price facets are not categories either: a leaf folds into its parent
# (its label becomes a search synonym there), a wrapper with children is skipped over.
FOLD_RULE = re.compile(
    r"^(weitere|sonstige|muut|övrig[at]?|ovrig[at]?|overige?|egyeb|egyéb|other|others|misc|miscellaneous|alle|all|"
    r"kaikki|alla)\b|\b(overig|muut|sonstige|sonstiges|övrigt)$|"
    r"^\W*(alle\s+|under\s+|yli\s+|bis\s+|ab\s+)?[\d.,]+\s*(gb|tb|mb|w|kw|mm|cm|m|zoll|tuumaa|inch|\"|mhz|ghz|v|mah|"
    r"kg|l|hz|k|x)?(\s*-\s*[\d.,]+\s*(gb|tb|mb|w|mm|cm|zoll|tuumaa|inch|\"|kg|l)?)?\W*$|\d+\s*(zoll|tuumaa|inch)\b|\balle\s+\d", re.I)


def menu_junk(label: str, site: str) -> str | None:
    """'drop' (not a category: drop with its subtree), 'fold' (facet / 'other' bucket) or None."""
    low = label.lower()
    if any(n in low for n in SELF_NAMES):
        return "drop"
    for _why, rx in JUNK_RULES:
        if re.search(rx, low) and not JUNK_KEEP.search(low):
            return "drop"
    if FOLD_RULE.search(low):
        return "fold"
    return None


class Speller:
    """Puts back letters a URL slug lost: 'Waeschetonne' -> 'Wäschetonne', 'Jarjestelmakamerat' ->
    'Järjestelmäkamerat', 'Fenykepezogepek' -> 'Fényképezőgépek', using the words the tree already has in that
    language (whole word, else a compound of two known words; German ae/oe as a last resort)."""

    def __init__(self, t: Tree) -> None:
        forms: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
            lambda: collections.defaultdict(collections.Counter))
        self.ascii_en: set[str] = set()
        self.exact: dict[str, set[str]] = collections.defaultdict(set)
        for n in t.nodes.values():
            for lang, lab in n["labels"].items():
                for w in re.findall(r"[^\W\d_]+", lab.lower()):
                    if lang == "en":
                        self.ascii_en.add(w)
                    self.exact[lang].add(w)
                    forms[lang][fold(w, lang)][w] += 1
        self.forms = {lang: {k: c.most_common(1)[0][0] for k, c in d.items()} for lang, d in forms.items()}

    def word(self, w: str, lang: str) -> str:
        low = w.lower()
        fm = self.forms.get(lang, {})
        if not low.isascii() or len(low) < 3 or low in self.ascii_en and lang != "de":
            return w
        k = fold(low, lang)
        got = fm.get(k)
        if not got:
            for i in range(3, len(k) - 3):           # compound of two known words, longest tail first
                a, b = k[:i], k[i:]
                if b in fm and (a in fm or (a[-1] in "sn" and a[:-1] in fm)):
                    got = (fm.get(a) or fm[a[:-1]] + a[-1]) + fm[b]
                    break
        if not got and lang == "de" and re.search("ae|oe", low) and \
                not any(low in ws for ws in self.exact.values()) and \
                not any(low[:i] in self.exact[lang] and low[i:] in self.exact[lang] for i in range(3, len(low) - 2)):
            # (not for two plain known words: 'Sofaelemente' = 'Sofa' + 'elemente')
            # ae/oe only: 'ue' is too often a real 'ue' (Blues, Duett); ü words are found through the vocabulary
            got = re.sub(r"(?<![aeiou])oe", "ö", re.sub(r"(?<![aeiou])ae", "ä", low))
        if not got or got.isascii():
            return w
        return got[:1].upper() + got[1:] if w[:1].isupper() else got

    def label(self, s: str, lang: str) -> str:
        if lang not in ("de", "fi", "sv", "hu", "nl", "da", "nb", "pl", "cs", "fr", "es", "it"):
            return s
        return re.sub(r"[^\W\d_]+", lambda m: self.word(m.group(0), lang), s)


# Marketplace top levels are lists of several things ('Möbler och inredning'): mapped by hand to our nodes
# (None = not a category). Children are then matched inside that node.
MENU_TOP: dict[str, dict[str, str | None]] = {
    "blocket": {"möbler och inredning": "furniture", "kläder, kosmetika och accessoarer": "fashion",
                "elektronik och vitvaror": "electronics", "föräldrar och barn": "baby-kids",
                "bygg och trädgård": "diy", "underhållning och hobby": "hobbies", "sport och friluftsliv": "sports-outdoors",
                "djur och tillbehör": "pets", "fordonstillbehör": "vehicles", "konst och antikt": "hobbies",
                "affärsverksamhet": "business"},
    "tori": {"koti ja sisustus": "home-garden", "vaatteet, kosmetiikka ja asusteet": "fashion",
             "elektroniikka ja kodinkoneet": "electronics", "lapset ja vanhemmat": "baby-kids",
             "piha ja remontointi": "diy", "viihde ja harrastukset": "hobbies", "eläimet ja eläintarvikkeet": "pets",
             "auto-, vene- ja moottoripyörätarvikkeet": "vehicles", "antiikki ja taide": "hobbies",
             "liiketoiminta ja palvelut": "business"},
    "marktplaats": {"antiek en kunst": "hobbies", "audio tv en foto": "electronics", "auto s": "vehicles",
                    "auto onderdelen": "vehicles", "auto diversen": "vehicles", "caravans en kamperen": "vehicles",
                    "cd s en dvd s": "media", "computers en software": "electronics", "contacten en berichten": None,
                    "diensten en vakmensen": "trades", "dieren en toebehoren": "pets", "doe het zelf en verbouw": "diy",
                    "fietsen en brommers": "sports-outdoors", "hobby en vrije tijd": "hobbies",
                    "huis en inrichting": "home-garden", "huizen en kamers": "property", "kinderen en baby s": "baby-kids",
                    "motoren": "vehicles", "muziek en instrumenten": "hobbies", "postzegels en munten": "hobbies",
                    "sieraden tassen en uiterlijk": "fashion", "spelcomputers en games": "electronics",
                    "sport en fitness": "sports-outdoors", "telecommunicatie": "electronics",
                    "tickets en kaartjes": "events-leisure", "tuin en terras": "home-garden", "vakantie": "travel",
                    "verzamelen": "hobbies", "witgoed en apparatuur": "appliances", "zakelijke goederen": "business",
                    "diversen": None},
}
UNPLACED: dict[str, list[tuple]] = collections.defaultdict(list)     # for inspection (not exported)
SERVICE_WORDS = re.compile(r"dienst|palvelu|tjänst|service|vakmens|handwerk|hantverk|reparat|korjaus|unterricht|"
                           r"lessen|opetus|kurs|cursus|lektion", re.I)


def _lane(t: Tree, node: str, lane: str) -> str:
    """A marketplace's service section ('Diensten en vakmensen') is a service lane, not 'used'."""
    return "service" if lane in ("new", "used") and t.root_of(node) in SERVICE_ROOTS else lane


def build_menus(t: Tree) -> dict[str, dict]:
    stats = {}
    speller = Speller(t)
    for key_, (domain, lang, lane, rspec, _fn) in MENU_SITES.items():
        p = MENUS / f"{key_}.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        items = data["items"]
        all_roots = roots_for(rspec)
        tix = TokenIndex(t, all_roots)
        mapped: dict[tuple, str | None] = {}
        matched = added = unplaced = junk = facets = 0
        dropped: set[tuple] = set()
        flat = all(len(it["path"]) == 1 for it in items)     # a flat sitemap: 'top level' is not broad
        anchor = MENU_ANCHOR.get(key_)
        drop = MENU_DROP.get(key_)
        have = {tuple(it["path"]) for it in items}
        for it in list(items):          # parents that have no page of their own (my-hammer: /bad/badsanierung)
            for n_ in range(1, len(it["path"])):
                pre = tuple(it["path"][:n_])
                if pre not in have:
                    have.add(pre)
                    items.append({"path": list(pre), "url": ""})
        for it in sorted(items, key=lambda x: len(x["path"])):
            path = tuple(it["path"])
            labels = it.get("labels") or {lang: speller.label(path[-1], lang)}
            if path in mapped:
                continue
            if drop and drop(path) or any(path[:k] in dropped for k in range(1, len(path))):
                mapped[path] = None
                continue
            lab0, l0 = next(iter(labels.items()))[1], next(iter(labels))
            parent_node = mapped.get(path[:-1]) if len(path) > 1 else None
            verdict = menu_junk(lab0, key_) or (menu_junk(path[-1], key_) if path[-1] != lab0 else None)
            if verdict == "drop":
                dropped.add(path)
                mapped[path] = None
                junk += 1
                continue
            if verdict == "fold":           # 'Other ...' / '512GB': a synonym of the parent; children skip over it
                mapped[path] = parent_node
                if parent_node:
                    t.merge_into(parent_node, {}, list(labels.values()), src=None)
                    t.add_where(parent_node, domain, _lane(t, parent_node, lane))
                facets += 1
                continue
            top = MENU_TOP.get(key_, {})
            if len(path) == 1 and lab0.lower() in top:
                node = top[lab0.lower()]
                mapped[path] = node
                if node:
                    t.merge_into(node, {}, [lab0], src="menu:" + key_)
                    t.add_where(node, domain, _lane(t, node, lane))
                    matched += 1
                else:
                    dropped.add(path)
                    junk += 1
                continue
            roots = all_roots
            if rspec == "all":              # marketplaces: goods stay among goods, services among services
                if parent_node:
                    roots = SERVICE_ROOTS if t.root_of(parent_node) in SERVICE_ROOTS else PRODUCT_ROOTS
                elif not SERVICE_WORDS.search(lab0):
                    roots = PRODUCT_ROOTS
            node = None
            # 1. same meaning: under the mapped parent (exact, then lenient), else anywhere in the allowed roots
            if parent_node:
                node = t.find(labels, parent_node, roots=roots)
                if node and (not menu_target(t.nodes[node]) or t.root_of(node) != t.root_of(parent_node)
                             and t.depth(node) > 3):
                    node = None             # 'Möbel > Regale' is not the oven 'Racks' in another root
                node = node or tix.fuzzy(lab0, l0, roots, within=parent_node)
            if not node:
                max_d = 3 if len(path) == 1 and not flat else MAX_DEPTH
                for l2, lab in labels.items():
                    k = key(lab, l2)
                    if is_generic(k):
                        continue
                    for c in sorted(t.keys.get((l2, k), ()), key=lambda c: (t.depth(c), c)):
                        if t.root_of(c) in roots and t.depth(c) <= max_d and menu_target(t.nodes[c]) and \
                                same_shape(lab, t.nodes[c]["labels"].get(l2) or t.nodes[c]["labels"].get("en", "")):
                            node = c
                            break
                    if node:
                        break
            if not node:
                node = tix.fuzzy(lab0, l0, roots, max_depth=3 if len(path) == 1 and not flat else MAX_DEPTH)
            if node:
                t.merge_into(node, labels, [], src="menu:" + key_)
                matched += 1
            else:
                # 2. new node: under the mapped parent, else under the node it is a narrower case of,
                #    else (service platforms) under the site's anchor. Otherwise: not placed.
                parent = parent_node or tix.specialize(lab0, l0, roots)
                if not parent and anchor and len(path) == 1:
                    parent = anchor
                if not parent:
                    mapped[path] = None
                    unplaced += 1
                    UNPLACED[key_].append(path)
                    continue
                nid = f"m:{key_}:{slug(path[-1])[:24]}-{hashlib.sha1('/'.join(path).encode()).hexdigest()[:6]}"
                node = t.place(nid, parent, labels, src="menu:" + key_, kind=t.nodes[parent]["kind"])
                if node == nid:
                    added += 1
            mapped[path] = node
            if node:
                t.add_where(node, domain, _lane(t, node, lane))
        stats[key_] = {"items": len(items), "matched": matched, "added": added, "unplaced": unplaced,
                       "junk": junk, "facets": facets}
        print(f"menu {key_}: {len(items)} items, {matched} matched, {added} added, {unplaced} unplaced, "
              f"{junk} junk, {facets} facets")
    return stats


# ------------------------------------------------------------------ 6b. regroup flat service lists

_RSTOP = {"service", "repair", "installation", "supply", "supplie", "hire", "emergency", "specialist", "general",
          "24", "hour", "mobile", "contractor", "company", "local", "professional", "shop", "store", "auto"}


def _rtok(s: str, lang: str = "en") -> set[str]:
    return {x[:7] for x in tokens(s, lang) if x not in GENERIC and x not in _RSTOP}


REGROUP_MIN = 0.55
# groups made for the trades A-Z list whose words are too general to attract other sources' entries
REGROUP_SKIP = {"trades.surveys-planning-inspections", "trades.merchants-trade-suppliers",
                "trades.restoration-specialist-crafts", "trades.energy-renewables", "trades.driveways-paving-fencing",
                "trades.garden-buildings-structures", "trades.damp-flood-structural-repairs",
                "trades.kitchens-bedrooms-fitted-furniture", "trades.accessibility-mobility-adaptations"}


def regroup_services(t: Tree) -> int:
    """Yelp / Checkatrade / CPV entries that landed directly under a service root move under the curated
    node they belong to ('Keys & Locksmiths' -> Handyman > Lock & key services, 'Air Conditioning Repair'
    -> HVAC), by weighted token overlap with the curated labels and synonyms."""
    idx: dict[str, set[str]] = collections.defaultdict(set)
    for nid, n in t.nodes.items():
        if "curated" in n["src"] and n["root"] in SERVICE_ROOTS and n["depth"] >= 2 and nid not in REGROUP_SKIP:
            for lang, lab in n["labels"].items():
                if lang not in ("en", "fi", "de", "nl", "sv"):
                    continue
                for x in _rtok(lab, lang):
                    idx[x].add(nid)
            for syn_ in n["syn"]:
                for x in _rtok(syn_):
                    idx[x].add(nid)
    moved = 0
    holders = SERVICE_ROOTS + [n for n in t.nodes if n.endswith(".other-trades-specialists")]
    for r in holders:
        for c in list(t.nodes[r]["children"]):
            n = t.nodes[c]
            if "curated" in n["src"]:
                continue
            best, best_r = None, 0.0
            for lang, lab in n["labels"].items():       # best single language (CPV adds 12 more)
                toks = _rtok(lab, lang)
                if not toks:
                    continue
                score: collections.Counter = collections.Counter()
                for x in toks:
                    post = idx.get(x, ())
                    for tgt in post:
                        score[tgt] += 1.0 / (1 + len(post)) ** 0.5
                tot = sum(1.0 / (1 + len(idx.get(x, ()))) ** 0.5 for x in toks)
                if not score or not tot:
                    continue
                cand = max(score, key=lambda k: (score[k], -t.depth(k), k))
                covered = sum(1 for x in toks if cand in idx.get(x, ()))
                if len(toks) >= 2 and covered / len(toks) < 0.66:
                    continue
                if score[cand] / tot > best_r:
                    best, best_r = cand, score[cand] / tot
            if not best or best_r < REGROUP_MIN or t.in_subtree(best, c) or best == r:
                continue
            if t.depth(best) + t.height(c) > MAX_DEPTH:
                continue
            t.move(c, best)
            moved += 1
            if VERBOSE:
                print("   move", n["labels"].get("en") or next(iter(n["labels"].values())), "->", t.nodes[best]["labels"]["en"])
    print(f"regroup: {moved} service entries moved under curated nodes")
    return moved


# ------------------------------------------------------------------ 6c. English names for menu nodes

FUNC_WORDS = {
    "de": {"mit": "with", "ohne": "without", "für": "for", "fur": "for", "von": "of", "zum": "for", "zur": "for",
           "im": "in", "aus": "from", "und": "&", "oder": "or", "fürs": "for", "furs": "for"},
    "nl": {"met": "with", "zonder": "without", "voor": "for", "van": "of", "en": "&", "of": "or"},
    "sv": {"med": "with", "utan": "without", "för": "for", "for": "for", "till": "for", "och": "&", "eller": "or"},
    "fi": {"ja": "&", "tai": "or"}, "hu": {"és": "&", "es": "&", "vagy": "or"},
    "da": {"og": "&", "med": "with", "til": "for"}, "nb": {"og": "&", "med": "with", "til": "for"},
}
# A few shop-menu words the parallel labels never show on their own.
SEED_WORDS = {
    "de": {"zubehör": "Accessories", "ersatzteile": "Spare parts", "damen": "Women's", "herren": "Men's",
           "kinder": "Kids'", "mädchen": "Girls'", "jungen": "Boys'", "baby": "Baby", "pflege": "Care",
           "objektiv": "Lenses", "objektive": "Lenses"},
    "fi": {"tarvikkeet": "Accessories", "lisätarvikkeet": "Accessories", "varaosat": "Spare parts",
           "naisten": "Women's", "miesten": "Men's", "lasten": "Children's", "vauvojen": "Baby", "hoito": "Care",
           "objektiivit": "Lenses"},
    "sv": {"tillbehör": "Accessories", "reservdelar": "Spare parts", "dam": "Women's", "herr": "Men's",
           "barn": "Children's", "damkläder": "Women's clothing", "herrkläder": "Men's clothing",
           "barnkläder": "Children's clothing"},
    "nl": {"toebehoren": "Accessories", "accessoires": "Accessories", "onderdelen": "Parts", "dames": "Women's",
           "heren": "Men's", "kinderen": "Children's"},
    "hu": {"kiegészítők": "Accessories", "tartozékok": "Accessories", "alkatrészek": "Parts", "női": "Women's",
           "férfi": "Men's", "gyerek": "Children's"},
}
MIN_EVIDENCE = 6
NO_TRANSLATION = {"de": {"ab", "bis", "andere", "weitere"}, "fi": {"muut"}, "sv": {"övriga", "ovriga"},
                  "nl": {"overige"}}
SMALL_EN = {"with", "without", "for", "of", "in", "from", "or", "and", "&", "the", "a"}
_WORDS_RX = re.compile(r"[^\W_]+(?:['’][^\W_]+)?|[,&/+]")


def _parts(label: str, lang: str) -> list[str]:
    conj = {k for k, v in FUNC_WORDS.get(lang, {}).items() if v == "&"} | ({"and"} if lang == "en" else set())
    out, cur = [], []
    for w in _WORDS_RX.findall(label):
        if w in ",&+/" or w.lower() in conj:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(w)
    if cur:
        out.append(cur)
    return [" ".join(p) for p in out]


def _content(part: str, lang: str) -> list[str]:
    fw = FUNC_WORDS.get(lang, {})
    return [w for w in part.split() if w.lower() not in fw and key(w, lang)]


class Translator:
    """Foreign menu label -> English from the tree's own parallel labels (Shopify/Google/CPV/curated nodes carry the
    same category in up to 13 languages): word and compound alignments, function words, English loanwords. Every
    word must be known, else None (no guessing)."""

    def __init__(self, t: Tree) -> None:
        pairs: list[tuple[str, list[str], list[str]]] = []      # (lang, foreign words, English words)
        self.en_vocab: set[str] = set()
        for nid, n in t.nodes.items():
            en = n["labels"].get("en")
            if not en or nid.startswith("m:"):
                continue
            self.en_vocab.update(w.lower() for w in re.findall(r"[^\W_]+", en))
            ep = _parts(en, "en")
            for lang, lab in n["labels"].items():
                if lang == "en":
                    continue
                lp = _parts(lab, lang)
                if len(lp) == len(ep):
                    pairs += [(lang, _content(x, lang), _content(e, "en")) for x, e in zip(lp, ep)]
        # pass 1: one word <-> one word (3 points), one compound <-> 2-3 English words (2 points)
        words: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
            lambda: collections.defaultdict(collections.Counter))
        for lang, xw, ew in pairs:
            if len(xw) == 1 and len(ew) == 1:
                words[lang][key(xw[0], lang)][ew[0]] += 3
            elif len(xw) == 1 and 2 <= len(ew) <= 3:
                words[lang][key(xw[0], lang)][" ".join(ew)] += 2
        self.words = self._decide(words)
        # pass 2: two-word phrases where one word is already known give the other one, in either order
        # ('Zubehör für Kameras' ~ 'Camera Accessories': kamera = camera, so zubehör = accessories)
        for lang, xw, ew in pairs:
            if len(xw) != 2 or len(ew) != 2:
                continue
            d = self.words.get(lang, {})
            for i in (0, 1):
                known = d.get(key(xw[i], lang))
                if not known or " " in known:
                    continue
                for j in (0, 1):
                    if key(ew[j]) == key(known):
                        words[lang][key(xw[1 - i], lang)][ew[1 - j]] += 3
                        break
        for lang, seed in SEED_WORDS.items():
            for w, en in seed.items():
                words[lang][key(w, lang)][en] += 100
        self.words = self._decide(words)
        self.sorted_keys = {lang: sorted(d) for lang, d in self.words.items()}
        self.rev_keys = {lang: sorted(k[::-1] for k in d if " " not in k) for lang, d in self.words.items()}

    @staticmethod
    def _decide(words: dict) -> dict[str, dict[str, str]]:
        """A translation needs MIN_EVIDENCE points (two clean alignments) and 60% of the word's evidence."""
        out = {}
        for lang, d in words.items():
            ok = {}
            for k, c in d.items():
                best, n_ = c.most_common(1)[0]
                if k and n_ >= MIN_EVIDENCE and n_ >= 0.6 * sum(c.values()):
                    ok[k] = best
            out[lang] = ok
        return out

    def _lookup(self, k: str, lang: str) -> str | None:
        """Exact, else the same word in another inflection ('kylpyhuone' ~ 'kylpyhuoneen')."""
        d = self.words.get(lang, {})
        if k in d:
            return d[k]
        if len(k) < 6:
            return None
        keys_ = self.sorted_keys.get(lang, [])
        i = bisect.bisect_left(keys_, k[:max(5, int(0.8 * len(k)))])
        best = None
        while i < len(keys_) and keys_[i].startswith(k[:max(5, int(0.8 * len(k)))]):
            if " " not in keys_[i] and _tok_eq(k, keys_[i]) and (best is None or len(keys_[i]) < len(best)):
                best = keys_[i]
            i += 1
        return d[best] if best else None

    def _head(self, k: str, lang: str) -> str | None:
        """A word only seen as the head of compounds: 'objektiv' from 'kameraobjektiv' = 'Camera Lenses',
        'teleobjektiv' = 'Telephoto Lenses' -> 'Lenses' (two compounds must agree on the English head)."""
        if len(k) < 6:
            return None
        rk, keys_ = k[::-1], self.rev_keys.get(lang, [])
        i = bisect.bisect_left(keys_, rk)
        heads: collections.Counter = collections.Counter()
        while i < len(keys_) and keys_[i].startswith(rk):
            full = keys_[i][::-1]
            if len(full) - len(k) >= 3:
                en = self.words[lang][full]
                if " " in en:
                    heads[en.rsplit(" ", 1)[1]] += 1
            i += 1
        if len(heads) == 1 and sum(heads.values()) >= 2:
            return next(iter(heads))
        return None

    def _word(self, w: str, lang: str) -> str | None:
        low = w.lower()
        if lang == "nl" and low.endswith("'s") and len(low) > 3:        # Dutch plural "cd's", "pda's"
            base = self._word(w[:-2], lang)
            if not base or " " in base or base.lower().endswith("s"):
                return base
            if len(base) <= 3 and base.isalpha():
                return base.upper() + "s"
            return base[:-1] + "ies" if base.endswith("y") else base + "s"
        fw = FUNC_WORDS.get(lang, {})
        if low in fw:
            return fw[low]
        if low in NO_TRANSLATION.get(lang, ()):
            return None
        if any(ch.isdigit() for ch in w):
            return w.upper() if len(w) <= 4 and w.isalnum() else w
        d = self.words.get(lang, {})
        k = key(w, lang)
        got = self._lookup(k, lang)
        if got:
            return got
        if low in self.en_vocab:
            return w
        head = self._head(k, lang)
        if head:
            return head
        if len(k) >= 10:                              # compound of two known words: modifier + head
            for i in range(5, len(k) - 4):
                a, b = k[:i], k[i:]
                aa = a if a in d else (a[:-1] if a[-1:] in "sn" and a[:-1] in d else None)
                if aa and b in d:
                    return _singular(d[aa]) + " " + d[b]
        return None

    def translate(self, label: str, lang: str, *, title: bool) -> str | None:
        if lang == "en":
            return label
        if lang == "nl":
            label = re.sub(r"(\w) s\b", r"\1's", label)        # slug lost the apostrophe: "Cd s" = "Cd's"
        out: list[str] = []
        for w in _WORDS_RX.findall(label):
            if w in ",&+/":
                out.append({"+": "&"}.get(w, w))
                continue
            tr = self._word(w, lang)
            if tr is None:
                return None
            out.append(tr)
        for i in range(len(out) - 1):                 # modifiers are singular: 'Camera batteries'
            if out[i] not in ",&/" and out[i].lower() not in SMALL_EN and out[i + 1] not in ",&/" \
                    and out[i + 1].lower() not in SMALL_EN:
                out[i] = _singular(out[i])
        if title:                                     # product categories are plural: '4K Cameras', not '4K Camera'
            after_prep = False                        # 'Fans with Water': only the head before 'with' counts
            for i in range(len(out)):
                if out[i] in ",&/":
                    after_prep = False
                    continue
                if out[i].lower() in SMALL_EN:
                    after_prep = True
                    continue
                last = i == len(out) - 1 or out[i + 1] in ",&/" or out[i + 1].lower() in SMALL_EN
                w_ = out[i].rsplit(" ", 1)[-1]
                if last and not after_prep and w_.isalpha() and not w_.lower().endswith("s"):
                    pl = w_[:-1] + "ies" if w_.endswith("y") and w_[-2:-1] not in "aeiou" else w_ + "s"
                    if pl.lower() in self.en_vocab:
                        out[i] = out[i][: len(out[i]) - len(w_)] + pl
        text = " ".join(out).replace(" ,", ",").replace(" / ", "/")
        ws: list[str] = []
        for w in text.split():
            if not ws or w.lower() != ws[-1].lower():
                ws.append(w)
        while ws and ws[-1].lower() in SMALL_EN:
            ws.pop()
        while ws and ws[0].lower() in SMALL_EN:
            ws.pop(0)
        if not ws:
            return None
        res = []
        for i, w in enumerate(ws):
            if w.isupper() and len(w) > 1 or any(ch.isdigit() for ch in w):
                res.append(w)
            elif i == 0 or title and w.lower() not in SMALL_EN:
                res.append(w[:1].upper() + w[1:].lower())
            else:
                res.append(w.lower())
        return " ".join(res)


def _singular(phrase: str) -> str:
    head, _, last = phrase.rpartition(" ")
    lw = last.lower()
    if "'" in lw or "’" in lw:
        pass
    elif len(lw) > 4 and lw.endswith("ies"):
        last = last[:-3] + "y"
    elif len(lw) > 4 and lw.endswith(("ches", "shes", "sses", "xes")):
        last = last[:-2]
    elif len(lw) > 3 and lw.endswith("s") and not lw.endswith(("ss", "us", "is", "ics")):
        last = last[:-1]
    return (head + " " + last).strip()


def _equivalent(t: Tree, nid: str) -> str | None:
    """An existing English-named node that means the same as menu node nid (same label in a shared language, same
    root): its parent, a sibling, an ancestor, else the shallowest such node."""
    n = t.nodes[nid]
    best = None
    for lang, lab in n["labels"].items():
        k = key(lab, lang)
        if not k:
            continue
        cands = [c for c in t.keys.get((lang, k), ()) if c != nid and c in t.nodes and "en" in t.nodes[c]["labels"]
                 and t.root_of(c) == n["root"] and not t.in_subtree(c, nid)]
        if is_generic(k):
            cands = [c for c in cands if c == n["parent"] or t.nodes[c]["parent"] == n["parent"]]
        for c in cands:
            rank = (0 if c == n["parent"] else 1 if t.nodes[c]["parent"] == n["parent"] else
                    2 if t.in_subtree(n["parent"], c) else 3, c.startswith(("cpv:", "nace:")), t.depth(c), c)
            if best is None or rank < best[0]:
                best = (rank, c)
    return best[1] if best else None


SPEC_FACET = re.compile(r"\d\s*(cm|mm|zoll|tuumaa|inch|gb|tb|hz|w|kg|l)\b|\d{3,}", re.I)


def dissolve_wrapper(t: Tree, nid: str) -> bool:
    """A menu wrapper with no English name ('Ruoanlaitto' > 'Steam Ovens'): its English-named children move up to
    its parent (merging with a same-named sibling there; a generic 'Accessories' folds into the parent), and the
    wrapper's labels become synonyms of the parent."""
    n = t.nodes[nid]
    par = n["parent"]
    if par is None or any("en" not in t.nodes[c]["labels"] for c in n["children"]):
        return False
    for c in list(n["children"]):
        k = key(t.nodes[c]["labels"]["en"])
        sib = sorted(x for x in t.nodes[par]["children"] if x != nid and x != c
                     and key(t.nodes[x]["labels"].get("en", "")) == k)
        if is_generic(k) or k == key(t.nodes[par]["labels"].get("en", "")):
            t.absorb(c, par, same=False)
        elif sib:
            t.absorb(c, sib[0], same=True)
        else:
            t.move(c, par)
    t.absorb(nid, par, same=False)
    return True


def localise_menu_nodes(t: Tree) -> dict:
    """Every node a shop menu added gets an English label: merged into the existing node with the same meaning,
    else translated from the tree's multilingual labels. A leaf that still has no English name is a facet of its
    parent ('Dji kameras', 'Brommers puch'): it folds into the parent as a synonym; a wrapper without an English
    name is dissolved into its parent. Whatever still has no English label is listed in tree.json "missing_en"."""
    tr = Translator(t)
    st: collections.Counter = collections.Counter()
    order = sorted((nid for nid in t.nodes if nid.startswith("m:")), key=lambda x: (-t.depth(x), x))
    for nid in order:
        if nid not in t.nodes:
            continue
        n = t.nodes[nid]
        if "en" in n["labels"]:
            continue
        tgt = _equivalent(t, nid)
        if tgt:
            t.absorb(nid, tgt, same=True)
            st["merged"] += 1
            continue
        title = n["kind"] not in ("service",)
        en = next((x for lang, lab in n["labels"].items() if (x := tr.translate(lab, lang, title=title))), None)
        if en and not n["children"] and (not re.search(r"[a-z]{3,}", en) or SPEC_FACET.search(en) or
                                         " " not in en.strip() and en == next(iter(n["labels"].values())) and
                                         not t.keys.get(("en", key(en)))):
            en = None   # 'HDMI', 'Dishwashers 45cm': a spec facet; 'Smart', 'Alpine': a brand that is no category
        if en:
            k, par = key(en), n["parent"]
            if k == key(t.nodes[par]["labels"].get("en", "")):
                t.absorb(nid, par, same=True)
                st["merged"] += 1
                continue
            sib = sorted(c for c in t.nodes[par]["children"] if c != nid and key(t.nodes[c]["labels"].get("en", "")) == k)
            if sib:
                t.absorb(nid, sib[0], same=True)
                st["merged"] += 1
                continue
            n["labels"]["en"] = en
            t.keys[("en", k)].add(nid)
            st["translated"] += 1
            continue
        if not n["children"]:
            t.absorb(nid, n["parent"], same=False)
            st["folded"] += 1
            continue
        if dissolve_wrapper(t, nid):
            st["dissolved"] += 1
        else:
            st["kept_foreign"] += 1
    print("localise:", dict(st))
    return dict(st)


# ------------------------------------------------------------------ 6d. the trades A-Z bucket into groups

BUCKET = "trades.other-trades-specialists"


def regroup_trades_bucket(t: Tree) -> int:
    rules = [(re.compile(rx), tgt) for rx, tgt in curated.TRADE_BUCKET_RULES]
    for _, tgt in rules:
        if tgt != "-fold" and tgt not in t.nodes:
            print("  bucket rule target missing:", tgt)
    moved = 0
    for c in list(t.nodes[BUCKET]["children"]):
        n = t.nodes[c]
        en = n["labels"].get("en")
        if not en:
            continue
        tgt = next((g for rx, g in rules if rx.search(en.lower())), None)
        if not tgt or (tgt != "-fold" and tgt not in t.nodes):
            continue
        if tgt == "-fold":
            t.absorb(c, BUCKET, same=False)
        elif n["children"]:            # a platform's own top category ('Badezimmer'): the same thing as the group
            t.absorb(c, tgt, same=True)
        else:
            t.move(c, tgt)
        moved += 1
    print(f"trades bucket: {moved} entries grouped, {len(t.nodes[BUCKET]['children'])} left")
    return moved


# ------------------------------------------------------------------ 6e. shopper names for CPV / NACE wordings

_ACT = (r"repair|maintenance|installation|inspection|testing|transport|disposal|supply|preservation|reconditioning|"
        r"rental|hire|leasing|renting|design|printing|training|management|operation|consultancy|translation|removal|"
        r"collection|storage|demolition|construction|decoration|conversion|refurbishment|cleaning|servicing|"
        r"overhaul|dismantling|assembly|sterilisation|calibration|programming|insurance")


def shopper_name(label: str) -> str | None:
    """'Repair and maintenance services of microcomputers' -> 'Microcomputer repair & maintenance',
    'Satellite telecommunications activities' -> 'Satellite telecommunications', 'Courier services' stays."""
    s = label.strip()
    s = re.sub(r"\s*\((?:except|excluding|other than|not elsewhere)[^)]*\)", "", s, flags=re.I)
    s = re.sub(r",?\s+(?:other than|except|excluding|not elsewhere classified)\b.*$", "", s, flags=re.I)
    s = re.sub(r",?\s*n\.e\.c\.?$", "", s, flags=re.I)
    s = re.sub(r"^miscellaneous\s+", "Other ", s, flags=re.I)
    s = re.sub(r"^(?:services (?:provided|furnished) by|activities of)\s+", "", s, flags=re.I)
    s = re.sub(r"^renting and leasing\b", "Rental", s, flags=re.I)
    s = re.sub(r"^repair, maintenance and associated services (?:of|related to|for)\b", "Repair and maintenance of", s,
               flags=re.I)
    m = re.match(rf"^({_ACT})(?:(?:,| and) ({_ACT}))?(?: and associated)?(?: services?| works?)? (?:of|for|on|to|related to)"
                 rf" (?:the )?(.+)$", s, flags=re.I)
    if m and len(m.group(3).split()) <= 4 and not re.search(r"\b(relating|related|for|of|to|in|with|on|by)\b",
                                                           m.group(3), re.I):
        acts = m.group(1).lower() + (" & " + m.group(2).lower() if m.group(2) else "")
        s = f"{_singular(m.group(3))} {acts}"           # 'Microcomputer repair & maintenance'
    m = re.match(r"^services related to (.+)$", s, flags=re.I)
    if m:
        s = m.group(1) + " services"
    s = re.sub(r" service activities$", " services", s, flags=re.I)
    m = re.match(r"^(.+?) (?:services|activities)$", s, flags=re.I)
    if m:
        body = m.group(1)
        last = body.split()[-1].lower()
        if last.endswith(("al", "ic", "ive", "ary", "ory")):
            s = body + " services" if s.lower().endswith("activities") else s
        elif re.search(r"(ing|tion|sion|ment|ance|ence|ery|cy|ure|sis|age|care|work|repair|maintenance|advice|design|"
                       r"support|training|transport|aid|research|hire|rental|education|therapy|surgery|"
                       r"telecommunications|insurance|accommodation|security)$", last):
            s = body
        elif s.lower().endswith("activities"):
            s = body + " services"
    s = re.sub(r"\b(repair|maintenance|installation|construction|insulation|building|demolition) works?$", r"\1", s,
               flags=re.I)
    s = re.sub(r"\s+and\s+", " & ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    if not s:
        return None
    s = s[:1].upper() + s[1:]
    return s if s != label else None


def shorten_official_labels(t: Tree) -> int:
    n_ = 0
    for nid, n in t.nodes.items():
        if not nid.startswith(("cpv:", "nace:")) or "en" not in n["labels"]:
            continue
        official = n["labels"]["en"]
        short = shopper_name(official)
        if short and len(short) <= len(official):
            n["labels"]["en"] = short
            if official not in n["syn"]:
                n["syn"].insert(0, official)
            n_ += 1
    print(f"official names shortened: {n_}")
    return n_



# ------------------------------------------------------------------ 6f. category pages: plain names, no empty umbrellas

def tidy_categories(t: Tree) -> dict:
    """Owner, 14 Nov: 'like wtf even is a lifestyle service'. Plain names for vague labels (old ones stay as
    synonyms), misplaced imports moved to the root a shopper would open, and empty umbrellas ('Lifestyle
    Services', 'Accessories', 'Other personal services') merged into their parent (ids become aliases)."""
    out = {"renamed": 0, "moved": 0, "folded": 0}
    for nid, new_parent in curated.MOVES.items():
        if nid in t.nodes and new_parent in t.nodes and t.nodes[nid]["parent"] != new_parent \
                and not t.in_subtree(new_parent, nid) and t.depth(new_parent) + t.height(nid) <= MAX_DEPTH:
            t.move(nid, new_parent)
            out["moved"] += 1
    for nid, spec in curated.RENAMES.items():
        if nid not in t.nodes:
            continue
        n = t.nodes[nid]
        for lang, lab in zip(("en", "fi", "de", "nl", "sv"), spec.split("|")):
            lab = lab.strip()
            old = n["labels"].get(lang)
            if not lab or lab == old:
                continue
            if old and old not in n["syn"]:
                n["syn"].insert(0, old)
            n["labels"][lang] = lab
        out["renamed"] += 1
    # Shopify PRODUCT categories merged into a service node (yoga mats under 'Yoga & pilates', golf balls under
    # 'Sports clubs & venues') stay products: hunting them runs shop lanes, not a provider search
    for nid, n in t.nodes.items():
        if nid.startswith("sp:") and not nid.startswith("sp:se") and not n["kind"] and n["root"] in SERVICE_ROOTS:
            n["kind"] = "product"
            out["kind_fixed"] = out.get("kind_fixed", 0) + 1
    # ... and go back to a shop's shelf: the product node with the service parent's name ('Yoga & Pilates' in
    # Sports & Outdoors), else their own Shopify grandparent ('Household Supplies' for pest traps)
    def product_home(svc_parent: str, nid: str) -> str | None:
        en = t.nodes[svc_parent]["labels"].get("en", "")
        same = sorted((c for c in t.keys.get(("en", key(en)), ()) if c in t.nodes and c != svc_parent
                       and t.nodes[c]["root"] not in SERVICE_ROOTS), key=lambda c: (t.depth(c), c))
        if same:
            return same[0]
        x = nid.rsplit("-", 1)[0]
        while "-" in x:
            x = x.rsplit("-", 1)[0]
            if x in t.nodes and t.nodes[x]["root"] not in SERVICE_ROOTS:
                return x
        return None
    for nid in sorted(t.nodes, key=lambda x: t.depth(x)):
        n = t.nodes.get(nid)
        if not n or not (nid.startswith("sp:") and not nid.startswith("sp:se")) or n["root"] not in SERVICE_ROOTS:
            continue
        par = n["parent"]
        if par.startswith("sp:") and not par.startswith("sp:se"):
            continue                                  # moves along with its product parent
        home = product_home(par, nid)
        if home and not t.in_subtree(home, nid) and t.depth(home) + t.height(nid) <= MAX_DEPTH:
            t.move(nid, home)
            out["products_rehomed"] = out.get("products_rehomed", 0) + 1
    fold = set(curated.FOLD_UP)
    for nid in sorted(t.nodes, key=lambda x: -t.depth(x)):
        n = t.nodes.get(nid)
        if not n or not n["parent"]:
            continue
        en = n["labels"].get("en") or ""
        auto = ":" in nid and en and browse.should_fold(en, depth=n["depth"], n_children=len(n["children"]))
        if nid in fold or auto:
            t.absorb(nid, n["parent"], same=False)
            out["folded"] += 1
    print(f"category pages: {out}")
    return out

# ------------------------------------------------------------------ 7. synonyms, kinds, sizes

def apply_synonyms(t: Tree) -> None:
    for label, syns in curated.SYNONYMS.items():
        hits = sorted(t.keys.get(("en", key(label)), ()), key=lambda c: (t.depth(c), c))
        if hits:
            t.merge_into(hits[0], {}, [s.strip() for s in syns.split(",")], src=None)
            t.index_synonyms(hits[0], [s.strip() for s in syns.split(",")])
        else:
            print("  synonym target missing:", label)


PICKUP = re.compile(r"\b(cars?|trucks?|vans?|boats?|yachts?|caravans?|campers?|motorhomes?|trailers?|tractors?|"
                    r"forklifts?|excavators?|motorcycles?|scooters & mopeds|sheds?|saunas?|hot tubs?|jacuzzis?|"
                    r"pianos?|pool tables?|billiard tables?|greenhouses?|playhouses?|heavy machinery|"
                    r"vehicles?|aircraft|snowmobiles?|atvs?|containers?|garden buildings?|fitted kitchens?)\b", re.I)
LARGE = re.compile(r"\b(sofas?|couch(es)?|beds?|bed frames?|mattress(es)?|wardrobes?|armoires?|dressers?|"
                   r"cabinets?|cupboards?|bookcases?|shelving units?|tables?|desks?|sideboards?|refrigerators?|"
                   r"fridges?|freezers?|washing machines?|washers?|dryers?|dishwashers?|ovens?|ranges?|stoves?|"
                   r"cookers?|bicycles?|bikes?|treadmills?|exercise bikes?|rowing machines?|cross trainers?|"
                   r"ellipticals?|strollers?|prams?|lawn mowers?|ride-on|grills?|barbecues?|trampolines?|"
                   r"patio|garden furniture|outdoor furniture|furniture sets?|televisions?|tvs?|air conditioners?|"
                   r"heat pumps?|kayaks?|canoes?|paddle ?boards?|bathtubs?|radiators?|wood stoves?|fireplaces?|"
                   r"arcade|cribs?|cots?|high chairs?|playpens?|chairs?)\b", re.I)
MEDIUM = re.compile(r"\b(microwaves?|vacuums?|vacuum cleaners?|coffee (machines?|makers?)|espresso|monitors?|"
                    r"desktop computers?|printers?|speakers?|soundbars?|amplifiers?|suitcases?|luggage|car seats?|"
                    r"lamps?|rugs?|carpets?|guitars?|keyboards? instruments?|drums?|projectors?|food processors?|"
                    r"blenders?|air fryers?|kettles?|toasters?|heaters?|fans?|dehumidifiers?|humidifiers?|"
                    r"air purifiers?|sewing machines?|power tools?|drills?|saws?|consoles?|pc cases?|towers?|"
                    r"curtains?|bedding|duvets?|pillows?|backpacks?|tents?|sleeping bags?|car parts?|tyres?|tires?|"
                    r"wheels?|rims?|pots?|pans?|cookware|aquariums?|cages?)\b", re.I)
SMALL = re.compile(r"\b(accessor(y|ies)|parts?|covers?|cases?|filters?|bags?|cables?|chargers?|batteries|bulbs?|"
                   r"refills?|cartridges?|screws?|bolts?|replacement|spare|stickers?|cards?|controllers?|remotes?)\b",
                   re.I)
ROOT_SIZE = {"furniture": "large", "appliances": "medium", "vehicles": "pickup", "electronics": "small",
             "fashion": "small", "home-garden": "medium", "diy": "medium", "business": "medium",
             "sports-outdoors": "medium", "baby-kids": "medium", "toys-games": "small", "hobbies": "small",
             "media": "small", "food-drink": "small", "pets": "small", "office": "small", "health-beauty": "small"}


def assign_kinds_sizes(t: Tree) -> None:
    order = sorted(t.nodes, key=lambda n: t.depth(n))
    n_desc: dict[str, int] = {}
    for nid in reversed(order):
        n_desc[nid] = sum(n_desc[c] + 1 for c in t.nodes[nid]["children"])
    browse_only = collections.Counter()
    for nid in order:
        n = t.nodes[nid]
        par = t.nodes[n["parent"]] if n["parent"] else None
        if not n["kind"]:
            n["kind"] = par["kind"] if par else "product"
        # sizes: physical things only
        if n["kind"] not in ("product", "vehicle", "food") or n["root"] in ("software", "property"):
            n["size"] = None
            continue
        en = n["labels"].get("en") or next(iter(n["labels"].values()), "")
        if n["root"] == "vehicles" and re.search(r"\b(parts?|accessor|care|tools?|electronics)\b", en, re.I):
            size = "small" if SMALL.search(en) else None
        else:
            size = None
        if not size:
            if SMALL.search(en) and not PICKUP.search(en):
                size = "small"
            elif PICKUP.search(en):
                size = "pickup"
            elif LARGE.search(en):
                size = "large"
            elif MEDIUM.search(en):
                size = "medium"
        if not size:
            size = (par.get("size") if par else None) or ROOT_SIZE.get(n["root"], "small")
        n["size"] = size


# ------------------------------------------------------------------ output

KIND_CODE = {"product": "p", "service": "s", "digital": "d", "vehicle": "v", "property": "r", "food": "f"}


def previous_tree() -> tuple[dict[str, str | None], dict[str, str]]:
    """(id -> parent id, aliases) of the tree.json currently on disk, if any."""
    for name in ("tree.json", "tree.json.gz"):
        p = OUT_DIR / name
        if p.exists():
            raw = p.read_bytes()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            doc = json.loads(raw)
            rows = doc.get("nodes", [])
            return ({r["i"]: (rows[r["p"]]["i"] if r["p"] >= 0 else None) for r in rows}, dict(doc.get("aliases") or {}))
    return {}, {}


def export(t: Tree, menu_stats: dict, cleanup: dict | None = None) -> pathlib.Path:
    order: list[str] = []

    def walk(nid: str) -> None:
        order.append(nid)
        for c in t.nodes[nid]["children"]:
            walk(c)

    for r in t.roots:
        walk(r)
    index = {nid: i for i, nid in enumerate(order)}
    rows = []
    n_desc: dict[str, int] = {}
    for nid in reversed(order):
        n_desc[nid] = sum(n_desc[c] + 1 for c in t.nodes[nid]["children"])
    browse_only = collections.Counter()
    for nid in order:
        n = t.nodes[nid]
        par = t.nodes[n["parent"]] if n["parent"] else None
        row = {"i": nid, "p": index[n["parent"]] if n["parent"] else -1,
               "l": {lang: n["labels"][lang] for lang in LANGS if lang in n["labels"]}}
        if not row["l"]:
            row["l"] = dict(n["labels"])
        if n["syn"]:
            row["s"] = n["syn"][:40]
        if not par or n["kind"] != par["kind"]:
            row["k"] = KIND_CODE.get(n["kind"], n["kind"])
        if n.get("size") and (not par or n["size"] != par.get("size")):
            row["z"] = n["size"]
        if n["codes"]:
            row["c"] = n["codes"]
        if n["where"]:
            row["w"] = n["where"]
        # huntable (absent) vs browse-only ("h": 0 + "b": reason): only concrete things start a hunt
        en = n["labels"].get("en") or next(iter(n["labels"].values()), "")
        ok, why = browse.assess(nid, en, depth=n["depth"], n_children=len(n["children"]), n_desc=n_desc[nid],
                                kind=n["kind"] or "product")
        if nid in curated.HUNTABLE:
            ok, why = curated.HUNTABLE[nid], (None if curated.HUNTABLE[nid] else (why or "group"))
        if not ok:
            row["h"], row["b"] = 0, why
            browse_only[why] += 1
        if nid in curated.ABOUT:
            row["a"] = curated.ABOUT[nid]
        rows.append(row)
    def live(x: str | None) -> str | None:
        seen = set()
        while x is not None and x not in t.nodes and x in t.aliases and x not in seen:
            seen.add(x)
            x = t.aliases[x]
        return x if x in t.nodes else None

    aliases = {}
    for old, new in {**curated.ID_ALIASES, **t.aliases}.items():
        if old not in t.nodes and live(new):
            aliases[old] = live(new)
    # ids the previous tree.json served keep resolving: to what they were merged into, else (a dropped junk page,
    # a facet folded at menu time) to their nearest surviving ancestor
    prev_parent, prev_alias = previous_tree()
    for old in list(prev_parent) + list(prev_alias):
        if old in t.nodes or old in aliases:
            continue
        x, seen = old, set()
        while x is not None and x not in seen:
            seen.add(x)
            got = live(x) or aliases.get(x)
            if got:
                aliases[old] = got
                break
            x = prev_alias.get(x) or prev_parent.get(x)
    missing_en = [nid for nid in order if "en" not in t.nodes[nid]["labels"]]
    depth = max(t.depth(n) for n in t.nodes)
    lang_cov = {lang: sum(1 for n in t.nodes.values() if lang in n["labels"]) for lang in LANGS}
    per_root = {r: sum(1 for n in t.nodes.values() if n["root"] == r) for r in t.roots}
    doc = {
        "name": "agora-taxonomy", "version": time.strftime("%Y-%m-%d"), "langs": list(LANGS), "max_depth": depth,
        "kinds": {v: k for k, v in KIND_CODE.items()}, "sources": SOURCES,
        "stats": {"nodes": len(rows), "per_root": per_root, "labels_per_lang": lang_cov,
                  "added": dict(t.adds), "merged": dict(t.merges), "folded": dict(t.folds), "menus": menu_stats,
                  "cleanup": cleanup or {}, "missing_en": len(missing_en), "aliases": len(aliases)},
        "missing_en": missing_en,       # nodes still shown with a foreign label in the English view
        "aliases": aliases,             # ids that were merged away -> the node that holds them now
        "nodes": rows,
    }
    doc["stats"]["browse_only"] = dict(browse_only)
    doc["stats"]["huntable"] = len(rows) - sum(browse_only.values())
    # "Popular:" chips per root: the curated words, each pinned to its best node inside that root
    from agora.taxonomy import Taxonomy
    tax = Taxonomy(doc)
    for root, words in curated.POPULAR.items():
        if root not in index:
            continue
        pop = []
        for spec in words:
            w, _, pin = spec.partition("=>")       # 'bed=>sp:fr-2' pins the node by hand
            if pin and tax.resolve(pin):
                pop.append([w, tax.resolve(pin)])
                continue
            hits = tax.search(w, root=root, limit=1)
            pop.append([w, hits[0]["id"] if hits and hits[0]["score"] >= 0.6 else None])
        rows[index[root]]["pop"] = pop
    print(f"huntable {doc['stats']['huntable']}, browse-only {sum(browse_only.values())} {dict(browse_only)}")
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    plain, gz = OUT_DIR / "tree.json", OUT_DIR / "tree.json.gz"
    if len(raw) > 15_000_000:
        gz.write_bytes(gzip.compress(raw, 9, mtime=0))
        plain.unlink(missing_ok=True)
        out = gz
    else:
        plain.write_bytes(raw)
        gz.unlink(missing_ok=True)
        out = plain
    print(f"wrote {out.relative_to(ROOT)}: {len(rows)} nodes, depth {depth}, {len(raw)/1e6:.1f} MB raw, "
          f"{out.stat().st_size/1e6:.1f} MB on disk")
    return out


def build() -> pathlib.Path:
    t = Tree()
    build_curated(t)
    build_shopify(t)
    apply_synonyms(t)
    build_yelp(t)
    build_nace(t)
    build_cpv(t)
    menu_stats = build_menus(t)
    cleanup = {"localise": localise_menu_nodes(t)}
    regroup_services(t)
    cleanup["trades_bucket_grouped"] = regroup_trades_bucket(t)
    cleanup["official_names_shortened"] = shorten_official_labels(t)
    cleanup["category_pages"] = tidy_categories(t)
    assign_kinds_sizes(t)
    return export(t, menu_stats, cleanup)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="download seeds and menus (plain HTTP, cached)")
    ap.add_argument("--menus", nargs="*", help="re-fetch only these menu sites")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch_seeds()
        fetch_menus()
    if a.menus:
        fetch_menus(a.menus)
    if not a.no_build:
        build()


if __name__ == "__main__":
    main()
