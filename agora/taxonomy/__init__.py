"""TAXONOMY: one tree of everything you can buy online, products AND services (Junction 2026).

~30 roots (electronics, furniture, ... home services, trades, beauty, health, education, events, travel,
transport, professional, digital, finance & insurance, utilities ...), tens of thousands of nodes with labels in
en/fi/de/nl/sv (+ fr da nb hu pl es it cs where the sources have them), synonyms, a kind
(product | service | digital | vehicle | property | food), a shipping size class (small | medium | large |
pickup, bulky = large or pickup) and "where to look" (domain + lane, inherited from ancestors).

Built offline by scripts/build_taxonomy.py into agora/taxonomy/tree.json (or tree.json.gz). This module only
reads it: everything is in memory, the search index is built on first use.

    from agora import taxonomy
    taxonomy.search("city bike")            # -> [{id, label, path, kind, score, ...}]
    taxonomy.classify("plumber in berlin")  # -> {id, path, kind, confidence, where, lanes, ...}
    taxonomy.node(id); taxonomy.children(id); taxonomy.stats()
"""
from __future__ import annotations

import bisect
import collections
import functools
import gzip
import json
import math
import pathlib
import re
import threading
import unicodedata
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent

# Every source the build reads, with its licence (also written into tree.json["sources"]).
SOURCES: list[dict[str, str]] = [
    {"name": "Agora curated roots + services backbone", "url": "agora/taxonomy/curated.py",
     "licence": "MIT (this project)", "use": "roots, service/digital subtrees, 5-language labels, synonyms, where-to-look"},
    {"name": "Shopify Product Taxonomy", "url": "https://github.com/Shopify/product-taxonomy",
     "licence": "MIT", "use": "product backbone (~14.6k categories), labels in 13 languages, Google mapping"},
    {"name": "Google Product Taxonomy (2021-09-21)",
     "url": "https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt",
     "licence": "published by Google for free use by merchants (no explicit licence; used for ids + labels only)",
     "use": "google ids, fi/de/nl/sv/fr/da/nb/es/it/pl labels and synonyms"},
    {"name": "EU CPV 2008 (Common Procurement Vocabulary)", "url": "https://ted.europa.eu/documents/d/ted/cpv_2008_xml",
     "licence": "EU open data, reuse authorised (Commission Decision 2011/833/EU; CC BY 4.0)",
     "use": "products + services (codes 45-98), 23-language labels (13 kept)"},
    {"name": "NACE Rev. 2 / TOL 2008 (Statistics Finland classification API)",
     "url": "https://data.stat.fi/api/classifications/v2/classifications/toimiala_1_20080101",
     "licence": "CC BY 4.0 (Statistics Finland)", "use": "service activities, en/fi/sv labels, NACE codes"},
    {"name": "ISIC Rev. 4 (UN Statistics Division)",
     "url": "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_4_english_structure.txt",
     "licence": "UN public classification (free reuse with attribution)", "use": "reference only (NACE is derived from it)"},
    {"name": "Yelp category list", "url": "https://docs.developer.yelp.com/docs/resources-categories",
     "licence": "Yelp developer documentation (no open licence): category NAMES + hierarchy used as facts only",
     "use": "local service categories (home services, beauty, health, events ...)"},
    {"name": "Shop / marketplace / service-platform category menus",
     "url": "sitemaps + menu HTML of ipon.hu, power.fi, verkkokauppa.com, jimms.fi, prisma.fi, tori.fi, blocket.se, "
            "marktplaats.nl, kleinanzeigen.de, otto.de, mediamarkt.de, coolblue.nl, emag.hu, ikea.com, fiverr.com, "
            "checkatrade.com, my-hammer.de, helpling.de",
     "licence": "public pages read over plain HTTP (category names/URLs as facts, robots.txt sitemaps)",
     "use": "extra categories, local-language labels, per-node shop domains (where to look)"},
]

_WORD = re.compile(r"[a-z0-9]+")
KINDS = {"p": "product", "s": "service", "d": "digital", "v": "vehicle", "r": "property", "f": "food"}
LANES_BY_KIND = {"product": ["new", "used", "refurbished"], "vehicle": ["used", "new"], "food": ["new", "service"],
                 "service": ["service"], "digital": ["new"], "property": ["rental", "new"]}
_STOP = {"and", "or", "the", "of", "for", "with", "a", "an", "in", "ja", "tai", "und", "oder", "fur", "en", "voor",
         "och", "eller", "et", "i", "y", "de", "la", "le", "der", "die", "das", "het", "een", "og", "near", "my",
         "me", "some", "to", "at", "on", "from", "buy", "need", "want", "looking", "cheap", "best", "new", "used",
         "osta", "kaufen", "kopen", "kopa", "halpa", "gunstig", "goedkoop", "billig", "kaytetty", "gebraucht"}


def fold(s: str) -> str:
    s = s.lower().replace("ß", "ss")
    if s.isascii():
        return s
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _stem(t: str) -> str:
    """Plural -> singular, crude but the same on both sides (shelves -> shelf, batteries -> battery)."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 5 and t.endswith("ves") and t[-4] in "lr":
        return t[:-3] + "f"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


@functools.lru_cache(maxsize=200_000)
def _tokens(s: str) -> tuple[str, ...]:
    return tuple(_stem(t) for t in _WORD.findall(fold(s)) if t not in _STOP)


def tokens(s: str) -> list[str]:
    return list(_tokens(s))


class Taxonomy:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.meta = {k: v for k, v in doc.items() if k not in ("nodes", "aliases", "missing_en")}
        # ids merged away by a rebuild (a shop-menu node folded into its English equivalent) keep resolving
        self.aliases: dict[str, str] = dict(doc.get("aliases") or {})
        self.missing_en: list[str] = list(doc.get("missing_en") or [])
        rows = doc["nodes"]
        self.ids: list[str] = [r["i"] for r in rows]
        self.parent: list[int] = [r["p"] for r in rows]
        self.labels: list[dict[str, str]] = [r["l"] for r in rows]
        self.syn: list[list[str]] = [r.get("s", []) for r in rows]
        self.codes: list[dict] = [r.get("c", {}) for r in rows]
        self.where_own: list[list] = [r.get("w", []) for r in rows]
        self.by_id: dict[str, int] = {nid: i for i, nid in enumerate(self.ids)}
        self.children_of: list[list[int]] = [[] for _ in rows]
        self.kind: list[str] = []
        self.size: list[str | None] = []
        self.depth: list[int] = []
        for i, r in enumerate(rows):
            p = r["p"]
            if p >= 0:
                self.children_of[p].append(i)
            k = KINDS.get(r.get("k", ""), r.get("k")) if "k" in r else (self.kind[p] if p >= 0 else "product")
            self.kind.append(k)
            self.size.append(r["z"] if "z" in r else (self.size[p] if p >= 0 and k in ("product", "vehicle", "food")
                                                      else None))
            self.depth.append(1 if p < 0 else self.depth[p] + 1)
        self.roots = [i for i, p in enumerate(self.parent) if p < 0]
        # category pages (agora/taxonomy/browse.py): huntable = a concrete thing or service; the rest browse only
        self.about: dict[int, str] = {i: r["a"] for i, r in enumerate(rows) if r.get("a")}
        self.pop: dict[int, list] = {i: r["pop"] for i, r in enumerate(rows) if r.get("pop")}
        self.desc = [0] * len(rows)
        for i in range(len(rows) - 1, -1, -1):      # parents come before children in the export
            p = self.parent[i]
            if p >= 0:
                self.desc[p] += self.desc[i] + 1
        if any("h" in r for r in rows) or "huntable" in (doc.get("stats") or {}):
            self.hunt_ok = [r.get("h", 1) != 0 for r in rows]
            self.why: list[str | None] = [r.get("b") if r.get("h", 1) == 0 else None for r in rows]
        else:                                        # an older tree.json: the same rules, worked out here
            from agora.taxonomy import browse
            verdicts = [browse.assess(self.ids[i], self.label(i), depth=self.depth[i],
                                      n_children=len(self.children_of[i]), n_desc=self.desc[i], kind=self.kind[i])
                        for i in range(len(rows))]
            self.hunt_ok = [v[0] for v in verdicts]
            self.why = [v[1] for v in verdicts]
        self._index_lock = threading.Lock()
        self._post: dict[str, list[tuple[int, float]]] | None = None
        self._vocab: list[str] = []
        self._exact: dict[str, list[int]] = {}

    # ---------------------------------------------------------------- basic lookups
    def __len__(self) -> int:
        return len(self.ids)

    def _i(self, nid: str | int) -> int:
        if isinstance(nid, int):
            return nid
        i = self.by_id.get(nid)
        if i is None:
            i = self.by_id[self.aliases[nid]] if nid in self.aliases else self.by_id[nid]
        return i

    def resolve(self, nid: str) -> str | None:
        """The current id for nid (itself, or the node an old id was merged into); None if unknown."""
        try:
            return self.ids[self._i(nid)]
        except KeyError:
            return None

    def label(self, i: int, lang: str = "en") -> str:
        """The label in lang, else English; a foreign label only when the node has nothing else (the build lists
        those ids in tree.json "missing_en")."""
        lab = self.labels[i]
        return lab.get(lang) or lab.get("en") or next(iter(lab.values()), self.ids[i])

    def path_idx(self, i: int) -> list[int]:
        out = []
        while i >= 0:
            out.append(i)
            i = self.parent[i]
        return out[::-1]

    def path(self, nid: str | int, lang: str = "en") -> list[str]:
        return [self.label(j, lang) for j in self.path_idx(self._i(nid))]

    def where(self, nid: str | int) -> list[dict[str, str]]:
        """Domains + lanes to look at: the node's own first, then inherited from its ancestors."""
        out, seen = [], set()
        for j in reversed(self.path_idx(self._i(nid))):
            for dom, lane in self.where_own[j]:
                if (dom, lane) not in seen:
                    seen.add((dom, lane))
                    out.append({"domain": dom, "lane": lane, "from": self.ids[j]})
        return out

    def node(self, nid: str | int, lang: str = "en") -> dict[str, Any] | None:
        try:
            i = self._i(nid)
        except KeyError:
            return None
        size = self.size[i]
        return {
            "id": self.ids[i], "label": self.label(i, lang), "labels": dict(self.labels[i]),
            "path": self.path(i, lang), "path_ids": [self.ids[j] for j in self.path_idx(i)],
            "depth": self.depth[i], "kind": self.kind[i], "size": size, "bulky": size in ("large", "pickup"),
            "synonyms": list(self.syn[i]), "codes": dict(self.codes[i]),
            "children": [self.ids[c] for c in self.children_of[i]], "where": self.where(i),
            "lanes": self.lanes(i), "huntable": self.hunt_ok[i], "browse_reason": self.why[i],
        }

    def huntable(self, nid: str | int) -> bool:
        """True when the node is a concrete thing or service a hunt can price; False for groupings that open a
        category page instead ('Lifestyle Services', a whole department, an 'Other ...' bucket)."""
        return self.hunt_ok[self._i(nid)]

    def browse_reason(self, nid: str | int) -> str | None:
        return self.why[self._i(nid)]

    def concrete_under(self, nid: str | int, limit: int = 8, *, lang: str = "en") -> list[int]:
        """The most typical concrete (huntable) nodes inside nid, for "Popular:" chips and "e.g." lines.
        No sales data: hand-made and shop-menu nodes first (a shop prints them), then the big product
        taxonomy, then directory lists, official procurement wording last; short plain names win."""
        i0 = self._i(nid)
        want_kind = self.kind[i0]
        best: list[tuple[float, int]] = []
        stack = [(c, 1) for c in self.children_of[i0]]
        while stack:
            i, d = stack.pop()
            if d < 4:
                stack.extend((c, d + 1) for c in self.children_of[i])
            if not self.hunt_ok[i]:
                continue
            nid_i = self.ids[i]
            src = (3.0 if ":" not in nid_i else 2.0 if nid_i.startswith("sp:") else 1.8 if nid_i.startswith("m:")
                   and not nid_i.startswith(("m:checkatrade", "m:fiverr")) else 1.2 if nid_i.startswith(("yelp:", "m:"))
                   else 0.3)
            lab = self.label(i, lang)
            words = len(lab.split())
            score = src - 0.35 * max(0, words - 2) - 0.25 * (d - 1) + 0.05 * min(len(self.syn[i]), 10) \
                - (0.8 if "," in lab or "(" in lab else 0) - (0.4 if not self.children_of[i] and d > 2 else 0) \
                - (1.5 if self.kind[i] != want_kind else 0)        # yoga mats are not a yoga class
            best.append((score, i))
        best.sort(key=lambda x: (-x[0], self.label(x[1], lang)))
        out, seen = [], set()
        for _, i in best:
            k = " ".join(_tokens(self.label(i, lang)))
            if k in seen:
                continue
            seen.add(k)
            out.append(i)
            if len(out) >= limit:
                break
        return out

    def lanes(self, nid: str | int) -> list[str]:
        i = self._i(nid)
        lanes = list(LANES_BY_KIND.get(self.kind[i], ["new"]))
        for w in self.where(i):
            if w["lane"] not in lanes and w["lane"] != "comparison":
                lanes.append(w["lane"])
        if self.size[i] == "pickup" and "refurbished" in lanes:
            lanes.remove("refurbished")
        return lanes

    def children(self, nid: str | int | None = None, lang: str = "en") -> list[dict[str, Any]]:
        idx = self.roots if nid is None else self.children_of[self._i(nid)]
        return [{"id": self.ids[c], "label": self.label(c, lang), "kind": self.kind[c],
                 "n_children": len(self.children_of[c]), "huntable": self.hunt_ok[c]} for c in idx]

    # ---------------------------------------------------------------- search
    def _build_index(self) -> None:
        with self._index_lock:
            if self._post is not None:
                return
            post: dict[str, dict[int, float]] = collections.defaultdict(dict)
            exact: dict[str, list[int]] = collections.defaultdict(list)
            for i in range(len(self.ids)):
                for lab in self.labels[i].values():
                    for t in tokens(lab):
                        if post[t].get(i, 0) < 1.0:
                            post[t][i] = 1.0
                    exact[" ".join(tokens(lab))].append(i)
                for s in self.syn[i]:
                    for t in tokens(s):
                        if post[t].get(i, 0) < 0.9:
                            post[t][i] = 0.9
                    exact[" ".join(tokens(s))].append(i)
            self._exact = {k: v for k, v in exact.items() if k}
            self._vocab = sorted(post)
            self._post = {t: list(d.items()) for t, d in post.items()}

    def _expand(self, tok: str) -> list[tuple[str, float]]:
        """The token itself plus near forms by shared prefix (photographer ~ photography, plumber ~ plumbing,
        fahrrad ~ fahrradhelm at a lower weight)."""
        out = [(tok, 1.0)] if tok in self._post else []
        if len(tok) >= 4:
            stem = tok[:max(4, len(tok) - 3)] if len(tok) >= 6 else tok
            lo = bisect.bisect_left(self._vocab, stem)
            n = 0
            while lo < len(self._vocab) and self._vocab[lo].startswith(stem) and n < 60:
                v = self._vocab[lo]
                lo += 1
                if v == tok:
                    continue
                n += 1
                common = len(stem)
                while common < min(len(v), len(tok)) and v[common] == tok[common]:
                    common += 1
                if v.startswith(tok):            # compound: query is the head (fahrrad -> fahrradhelme)
                    w = 0.55 if len(v) - len(tok) > 3 else 0.85
                else:
                    w = 0.75 * common / max(len(tok), len(v))
                out.append((v, w))
        return out

    def search(self, query: str, *, limit: int = 10, kind: str | None = None, root: str | None = None,
               lang: str = "en") -> list[dict[str, Any]]:
        """Best nodes for a free-text query (any of the tree's languages). Score in [0, ~1.5]."""
        self._build_index()
        q = tokens(query)
        if not q:
            return []
        n_docs = len(self.ids)
        weights, cand_tok = [], []
        near: dict[str, float] = {}       # query token or near form -> closeness
        for t in q:
            exp = self._expand(t)
            df = max((len(self._post[v]) for v, _ in exp if v == t), default=None)
            if df is None:
                df = min((len(self._post[v]) for v, _ in exp), default=n_docs)
            w = math.log(1 + n_docs / (1 + df)) if exp else 0.0
            weights.append(w * 0.35 if t.isdigit() else w)
            hits: dict[int, float] = {}
            for v, w in exp:
                for i, fw in self._post[v]:
                    s = w * fw
                    if s > hits.get(i, 0):
                        hits[i] = s
            cand_tok.append(hits)
            for v, w_ in exp:
                near[v] = max(near.get(v, 0.0), w_)
        total = sum(weights) or 1.0
        known = [w > 0 for w in weights]
        known_total = sum(w for w in weights if w > 0) or 1.0
        cands: set[int] = set()
        for h in cand_tok:
            cands.update(h)
        root_i = self._i(root) if root else None
        exact = set(self._exact.get(" ".join(q), ()))
        scored = []
        for i in cands:
            if kind and self.kind[i] != kind:
                continue
            anc = self.path_idx(i)
            if root_i is not None and anc[0] != root_i:
                continue
            own_cov = ctx_cov = 0.0
            for t_i, h in enumerate(cand_tok):
                if not weights[t_i]:
                    continue
                if i in h:
                    own_cov += weights[t_i] * h[i]
                else:
                    best = max((h.get(a, 0.0) for a in anc[:-1]), default=0.0)
                    ctx_cov += weights[t_i] * best * 0.6
            if own_cov == 0:
                continue
            # how much of the node's own label the query explains (prefer "Game Controllers" over
            # "Game Controller Charging Stations" for "game controller")
            lab_cov = 0.0
            for l in self.labels[i].values():
                lt = set(_tokens(l))
                if lt:
                    lab_cov = max(lab_cov, sum(near.get(x, 0.0) for x in lt) / len(lt))
            for syn in self.syn[i]:
                st = set(_tokens(syn))
                if st and all(x in near for x in st):
                    lab_cov = max(lab_cov, 0.9 * sum(near[x] for x in st) / len(st))
            score = (own_cov + ctx_cov) / known_total
            score *= 0.75 + 0.25 * sum(known) / len(known)
            score += 0.25 * lab_cov + (0.3 if i in exact else 0.0)
            score -= 0.004 * self.depth[i]
            scored.append((score, -self.depth[i], i))
        scored.sort(reverse=True)
        out = []
        for score, _, i in scored[:limit]:
            out.append({"id": self.ids[i], "label": self.label(i, lang), "path": self.path(i, lang),
                        "kind": self.kind[i], "size": self.size[i], "score": round(score, 3)})
        return out

    def classify(self, text: str, *, lang: str = "en") -> dict[str, Any] | None:
        """Need text -> best node + confidence (0..1). Places, budgets and conditions are cut first."""
        thing, service, place = _strip_need(text)
        hits = self.search(thing or text, limit=8, lang=lang)
        if service:
            svc = self.search(service + " " + (thing or ""), limit=5, lang=lang)
            svc = [h for h in svc if h["kind"] == "service"] or self.search(service, limit=5, kind="service", lang=lang)
            if svc and (not hits or hits[0]["kind"] != "service"):
                hits = svc + [h for h in hits if h["id"] not in {s["id"] for s in svc}]
        if not hits:
            return None
        top = hits[0]
        second = hits[1]["score"] if len(hits) > 1 else 0.0
        margin = max(0.0, top["score"] - second)
        conf = max(0.0, min(1.0, 0.65 * min(top["score"], 1.3) / 1.3 + 0.35 * min(1.0, margin * 4)))
        info = self.node(top["id"], lang)
        info.update({"confidence": round(conf, 3), "score": top["score"], "query": thing or text, "place": place,
                     "alternatives": [{"id": h["id"], "path": h["path"], "score": h["score"]} for h in hits[1:5]]})
        return info

    def stats(self) -> dict[str, Any]:
        per_root = {self.ids[r]: 1 + sum(1 for i in range(len(self.ids)) if i != r and self.path_idx(i)[0] == r)
                    for r in self.roots}
        kinds = collections.Counter(self.kind)
        sizes = collections.Counter(s for s in self.size if s)
        lang_cov = collections.Counter(l for lab in self.labels for l in lab)
        return {"nodes": len(self.ids), "roots": len(self.roots), "max_depth": max(self.depth),
                "per_root": per_root, "kinds": dict(kinds), "sizes": dict(sizes),
                "labels_per_lang": dict(lang_cov.most_common()),
                "with_where": sum(1 for w in self.where_own if w),
                "missing_en": len(self.missing_en), "aliases": len(self.aliases),
                "version": self.meta.get("version")}


def _strip_need(text: str) -> tuple[str, str | None, str | None]:
    """(thing, service word, place) using agora.need / agora.places when available."""
    thing, service, place = text, None, None
    try:
        from agora import places
        hit = places.find_place(text)
        if hit:
            place = hit[0]
            a, b = hit[2]
            thing = (text[:a] + " " + text[b:]).strip()
            thing = re.sub(r"\b(in|near|around|at|bei|in der nähe von|lähellä|nabij|nära)\s*$", "", thing, flags=re.I)
    except Exception:
        pass
    try:
        from agora import need
        _b, _c, span = need.parse_budget(thing)
        if span:
            thing = (thing[:span[0]] + " " + thing[span[1]:]).strip()
        service, _ = need.detect_service(thing)
        conds, spans = need.detect_conditions(thing)
        if "rental" not in conds:          # 'flat to rent' must keep 'rent'; used/new/refurbished words go
            for a, b in sorted(spans, reverse=True):
                thing = thing[:a] + " " + thing[b:]
    except Exception:
        pass
    return re.sub(r"\s+", " ", thing).strip(), service, place


_DEFAULT: Taxonomy | None = None
_LOCK = threading.Lock()


def tree_path() -> pathlib.Path:
    for name in ("tree.json", "tree.json.gz"):
        p = HERE / name
        if p.exists():
            return p
    raise FileNotFoundError("agora/taxonomy/tree.json(.gz) missing: run scripts/build_taxonomy.py")


def load(path: str | pathlib.Path | None = None) -> Taxonomy:
    """The tree (cached for the default path). Reads tree.json or tree.json.gz transparently."""
    global _DEFAULT
    if path is None and _DEFAULT is not None:
        return _DEFAULT
    p = pathlib.Path(path) if path else tree_path()
    raw = p.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    tax = Taxonomy(json.loads(raw))
    if path is None:
        with _LOCK:
            _DEFAULT = _DEFAULT or tax
            return _DEFAULT
    return tax


def search(query: str, **kw: Any) -> list[dict[str, Any]]:
    return load().search(query, **kw)


def classify(text: str, **kw: Any) -> dict[str, Any] | None:
    return load().classify(text, **kw)


def node(nid: str, lang: str = "en") -> dict[str, Any] | None:
    return load().node(nid, lang)


def children(nid: str | None = None, lang: str = "en") -> list[dict[str, Any]]:
    return load().children(nid, lang)


def stats() -> dict[str, Any]:
    return load().stats()
