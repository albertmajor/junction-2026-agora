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

CACHE = ROOT / ".cache" / "taxonomy"
RAW, HTTP, MENUS = CACHE / "raw", CACHE / "http", CACHE / "menus"
OUT_DIR = ROOT / "agora" / "taxonomy"
LANGS = ("en", "fi", "de", "nl", "sv", "fr", "da", "nb", "hu", "pl", "es", "it", "cs")
MAX_DEPTH = 7
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
               "checkatrade": "trades", "myhammer": "trades", "fiverr": "digital-services"}
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
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
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
        kids = [c for c in cands if self.nodes[c]["parent"] == parent]
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
    return c >= max(5, int(0.8 * m))


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

    def ranked(self, label: str, lang: str, within: str | None = None, n: int = 12) -> list[str]:
        toks = [x for x in tokens(label, lang) if x not in GENERIC]
        score: dict[str, float] = collections.Counter()
        for tok in toks:
            post = self.idx.get(tok, ())
            if not post or len(post) > 4000:
                continue
            w = 1.0 / (1 + len(post)) ** 0.5
            for nid in post:
                if nid in self.t.nodes and (not within or self.t.in_subtree(nid, within)):
                    score[nid] += w
        return [k for k, _ in sorted(score.items(), key=lambda kv: (-kv[1], self.t.depth(kv[0]), kv[0]))[:n]]

    def fuzzy(self, label: str, lang: str, roots: list[str], within: str | None = None) -> str | None:
        """A node whose label (same language, or English) says the same with other inflection/wording:
        token pairs equal or sharing a long prefix ('astianpesukoneet' ~ 'astianpesukone'). Inside a known
        parent it is enough that every token of the menu label is in the node label ('Kannettavat' ~
        'Kannettavat tietokoneet')."""
        a = [x for x in tokens(label, lang) if x not in GENERIC] or tokens(label, lang)
        if not a:
            return None
        for nid in self.ranked(label, lang, within):
            n = self.t.nodes[nid]
            if n["root"] not in roots or not menu_target(n):
                continue
            for l2 in (lang, "en"):
                lab = n["labels"].get(l2)
                if not lab:
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
        if len(a) < 2:
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


def roots_for(spec) -> list[str]:
    if spec == "products":
        return PRODUCT_ROOTS
    if spec == "services":
        return SERVICE_ROOTS
    if spec == "all":
        return PRODUCT_ROOTS + SERVICE_ROOTS
    return list(spec)


def build_menus(t: Tree) -> dict[str, dict]:
    stats = {}
    for key_, (domain, lang, lane, rspec, _fn) in MENU_SITES.items():
        p = MENUS / f"{key_}.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        items = data["items"]
        roots = roots_for(rspec)
        tix = TokenIndex(t, roots)
        mapped: dict[tuple, str | None] = {}
        matched = added = unplaced = 0
        anchor = MENU_ANCHOR.get(key_)
        drop = MENU_DROP.get(key_)
        for it in sorted(items, key=lambda x: len(x["path"])):
            path = tuple(it["path"])
            labels = it.get("labels") or {lang: path[-1]}
            if path in mapped:
                continue
            if drop and drop(path):
                mapped[path] = None
                continue
            lab0, l0 = next(iter(labels.items()))[1], next(iter(labels))
            parent_node = mapped.get(path[:-1]) if len(path) > 1 else None
            node = None
            # 1. same meaning: under the mapped parent (exact, then lenient), else anywhere in the allowed roots
            if parent_node:
                node = t.find(labels, parent_node, roots=roots)
                if node and not menu_target(t.nodes[node]):
                    node = None
                node = node or tix.fuzzy(lab0, l0, roots, within=parent_node)
            if not node:
                max_d = 3 if len(path) == 1 else MAX_DEPTH
                for l2, lab in labels.items():
                    k = key(lab, l2)
                    if is_generic(k):
                        continue
                    for c in sorted(t.keys.get((l2, k), ()), key=lambda c: (t.depth(c), c)):
                        if t.root_of(c) in roots and t.depth(c) <= max_d and menu_target(t.nodes[c]):
                            node = c
                            break
                    if node:
                        break
            if not node:
                node = tix.fuzzy(lab0, l0, roots)
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
                    continue
                nid = f"m:{key_}:{slug(path[-1])[:24]}-{hashlib.sha1('/'.join(path).encode()).hexdigest()[:6]}"
                node = t.place(nid, parent, labels, src="menu:" + key_, kind=t.nodes[parent]["kind"])
                if node == nid:
                    added += 1
            mapped[path] = node
            if node:
                t.add_where(node, domain, lane)
        stats[key_] = {"items": len(items), "matched": matched, "added": added, "unplaced": unplaced}
        print(f"menu {key_}: {len(items)} items, {matched} matched, {added} added, {unplaced} unplaced")
    return stats


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


def export(t: Tree, menu_stats: dict) -> pathlib.Path:
    order: list[str] = []

    def walk(nid: str) -> None:
        order.append(nid)
        for c in t.nodes[nid]["children"]:
            walk(c)

    for r in t.roots:
        walk(r)
    index = {nid: i for i, nid in enumerate(order)}
    rows = []
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
        rows.append(row)
    depth = max(t.depth(n) for n in t.nodes)
    lang_cov = {lang: sum(1 for n in t.nodes.values() if lang in n["labels"]) for lang in LANGS}
    per_root = {r: sum(1 for n in t.nodes.values() if n["root"] == r) for r in t.roots}
    doc = {
        "name": "agora-taxonomy", "version": time.strftime("%Y-%m-%d"), "langs": list(LANGS), "max_depth": depth,
        "kinds": {v: k for k, v in KIND_CODE.items()}, "sources": SOURCES,
        "stats": {"nodes": len(rows), "per_root": per_root, "labels_per_lang": lang_cov,
                  "added": dict(t.adds), "merged": dict(t.merges), "folded": dict(t.folds), "menus": menu_stats},
        "nodes": rows,
    }
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
    assign_kinds_sizes(t)
    return export(t, menu_stats)


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
