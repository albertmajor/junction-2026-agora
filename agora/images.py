"""IMAGE BACKFILL + VERIFY: the right product photo for a listing, for free (plain HTTP, no Context.dev).

Why: a marketplace search page cut into rows (marketplaces.split_rows / find_image) often gives a row no
photo (lazy-loaded thumbnails, "no_thumbnail.svg") or, worse, its NEIGHBOUR's photo: find_image skips an
in-card placeholder and takes the first <img> after the link, which belongs to the next card (olx.pl
"Thule Urban Glide 3 gondola bassinet 4 wheel" showed another listing's photo). The listing page itself
still says which photo is its own (JSON-LD Product image, og:image).

What this module does:
- `find_image(url)` -> {image, source}: fetch the listing page (plain GET, normal UA, 6 s, <= 6 at a time,
  <= 2 per host, public hosts only, redirects checked hop by hop) and pick its photo:
  JSON-LD Product/Offer/Vehicle image ("jsonld") > og:image / twitter:image / <link rel=image_src> ("og")
  > the largest <img> whose alt matches the page title ("dom") > nothing ("none").
  Logos, placeholders, sprites, icons, svg and data: URIs are never a photo. Site rules upgrade thumbnails
  (marktplaats/2dehands `?rule=ecg_mp_eps$_83` -> `$_85`, 726 px; `$_86` is 1024 px and kept).
- `verify(url, have)`: the same lookup, then `same_photo(have, found)` (same file id, size params ignored).
  A different photo -> the page's photo replaces the row's.
- `pair_images(page_html, rows)`: a pure re-pairing of split rows to photos by DOM proximity (an <img>
  belongs to the nearest listing link, never across another listing's link; alt text matching the title
  wins; an in-card placeholder means "no photo", not the next card's) + drops a photo used by > 1 row.
  The reader owner can call it after `split_rows` (see `pair_rows_for_reader`).
- Cache: memory + `.cache/images.json` (found: 7 days, nothing found: 15 min, so a later retry can work).
  With AGORA_OFFLINE=1 only cached pages are read (the reader's `.cache/html/` page cache, then ours).
- Router: GET /api/image?url=  and  POST /api/images {urls:[...<=50], have:{url: image}}.
  Only listing URLs a hunt streamed (live hunts of this server, recordings, the offers table, or
  `remember(url)`) are looked up: this must not become an open fetcher.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as _html
import ipaddress
import json
import os
import pathlib
import re
import socket
import sys
import threading
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-GB,en;q=0.9,nl;q=0.8,de;q=0.7,fi;q=0.6"}
TIMEOUT_S = 6.0
MAX_HTML = 2_500_000
MAX_REDIRECTS = 4
CONCURRENCY = 6
PER_HOST = 2
BATCH_MAX = 50
FOUND_TTL_S = 7 * 24 * 3600
NONE_TTL_S = 15 * 60
PAGE_CACHE_TTL_S = 6 * 3600          # the reader's .cache/html page is reused when this fresh

# Tests inject httpx.MockTransport here (then no DNS check, no disk page cache).
_transport: httpx.AsyncBaseTransport | None = None

_sem: asyncio.Semaphore | None = None
_host_sems: dict[str, asyncio.Semaphore] = {}
_inflight: dict[str, asyncio.Future] = {}
_mem: dict[str, dict] = {}
_disk_loaded = False
_lock = threading.Lock()


# ---------------------------------------------------------------- photo rules

# what is never a photo of the thing (mirrors web/js/core.js isProductPhoto, plus placeholders and icons)
NOT_A_PHOTO = re.compile(
    r"(^|[/_.-])(logo|logos|og[_-]?image|og[_-]?logo|ogimage|placeholder|no[_-]?image|no[_-]?thumbnail|"
    r"no[_-]?photo|noimage|nophoto|default[_-]?image|fallback[_-]?images?|favicon|sprite|sprites|banner|header|"
    r"lifestyle|icon|icons|avatar|badge|spacer|pixel|blank|transparent|loader|loading|spinner|flag|flags|"
    r"apple-touch-icon|share[_-]?image|social|opengraph|open[_-]graph|og|og[_-]?default|default[_-]?og|"
    r"social[_-]?share|twitter[_-]?card)([/_.-]|$)|/plp/og|1x1\.", re.I)
IMG_EXT_BAD = re.compile(r"\.(svg|ico|gif)(\?|$)", re.I)


def is_product_photo(url: str | None) -> bool:
    """An http(s) image URL that is not a logo, placeholder, icon, sprite, svg or data: URI."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not u.startswith(("https://", "http://")):
        return False
    try:
        path = urlsplit(u).path
    except ValueError:
        return False
    return not NOT_A_PHOTO.search(path) and not IMG_EXT_BAD.search(path)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_SIZE_TOKEN = re.compile(r"(?:[_-](?:\d{2,4}x\d{0,4}|\d{2,4}w|grande|large|medium|small|thumb|thumbnail|master|"
                         r"compact|original|big|full|lim_full)(?=[._/]|$))|(?:/(?:\d{2,4}w|\d{2,4}x\d{0,4}|"
                         r"thumbs?|thumbnails?|large|medium|small|default|dynamic|resize[^/]*|fit-in|w_\d+[^/]*)"
                         r"(?=/))", re.I)


def photo_key(url: str | None) -> str | None:
    """A size-independent id of a photo: two URLs with the same key show the same picture.
    images.marktplaats.com/.../images/<uuid>?rule=$_83 and ...$_86 -> the uuid; olx /v1/files/<id>-PL/image;s=..
    -> the id; tori img.tori.net/dynamic/1280w/item/<n>/<uuid> -> the uuid; else host-less path minus size tokens."""
    if not url or not isinstance(url, str):
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    path = p.path
    m = _UUID.search(path)
    if m:
        return m.group(0).lower()
    m = re.search(r"/v1/files/([^/;]+)", path)               # olx (apollo.olxcdn.com)
    if m:
        return m.group(1).lower()
    path = path.split(";")[0]
    m = re.search(r"/(?:t|tc)/[^/]+/[^/]+/(\d{6,})\.", path)   # vinted images*.vinted.net/t/<hash>/<size>/<id>.webp
    if m:
        return "vinted:" + m.group(1)
    path = _SIZE_TOKEN.sub("", path)
    path = re.sub(r"\.(jpe?g|png|webp|avif)$", "", path, flags=re.I)
    host = (p.hostname or "").lower()
    host = re.sub(r"^(?:www|img\d*|images?\d*|i\d+|cdn\d*|static\d*|media\d*)\.", "", host)
    return f"{host}{path}".lower() or None


def same_photo(a: str | None, b: str | None) -> bool:
    ka, kb = photo_key(a), photo_key(b)
    return bool(ka and kb and ka == kb)


def upgrade(url: str) -> str:
    """A bigger rendition of a marketplace thumbnail when the site has a known size rule (verified live:
    marktplaats rule $_82 147 px, $_83 358, $_84 498, $_85 726, $_86 1024)."""
    m = re.search(r"([?&]rule=ecg_mp_eps\$_)(\d+)", url)
    if m and "marktplaats.com" in url and int(m.group(2)) in (14, 82, 83, 84):
        return url[:m.start(2)] + "85" + url[m.end(2):]
    return url


# ---------------------------------------------------------------- page parsing

_LDJSON = re.compile(r"<script\b[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_IMG_TAG = re.compile(r"<(?:img|source)\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
_HREF = re.compile(r"""\bhref\s*=\s*["']?([^"'\s>]+)""", re.I)
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
PRODUCT_TYPES = {"product", "offer", "aggregateoffer", "individualproduct", "productmodel", "vehicle", "car",
                 "motorcycle", "book", "productgroup", "realestatelisting", "accommodation", "residence"}


def attrs(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR.finditer(tag):
        k = m.group(1).lower()
        if k not in out:
            out[k] = _html.unescape(m.group(2) if m.group(2) is not None else
                                    m.group(3) if m.group(3) is not None else m.group(4) or "")
    return out


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _types(node: dict) -> set[str]:
    t = node.get("@type") or []
    return {str(x).rsplit("/", 1)[-1].lower() for x in (t if isinstance(t, list) else [t])}


def _img_value(v: Any) -> str | None:
    if isinstance(v, list):
        for x in v:
            got = _img_value(x)
            if got:
                return got
        return None
    if isinstance(v, dict):
        return _img_value(v.get("contentUrl") or v.get("url") or v.get("@id"))
    return v.strip() if isinstance(v, str) and v.strip() else None


def jsonld_blocks(page: str) -> list[Any]:
    out = []
    for m in _LDJSON.finditer(page[:MAX_HTML]):
        body = m.group(1).strip().rstrip(";").strip()
        if body.startswith("<!--"):
            body = body[4:].rsplit("-->", 1)[0]
        try:
            out.append(json.loads(body))
        except ValueError:
            continue
    return out


def jsonld_image(page: str, base: str) -> str | None:
    """The Product (Offer, Vehicle ...) image, else an ImageObject marked representativeOfPage."""
    blocks = jsonld_blocks(page)
    rep = None
    for b in blocks:
        for node in _walk(b):
            types = _types(node)
            if types & PRODUCT_TYPES and node.get("image"):
                u = _good(_img_value(node.get("image")), base)
                if u:
                    return u
            if "imageobject" in types and node.get("representativeOfPage") in (True, "true", "True") and not rep:
                rep = _good(_img_value(node), base)
    return rep


def meta_image(page: str, base: str) -> str | None:
    """og:image (secure_url too) > twitter:image > <link rel=image_src>."""
    found: dict[str, str] = {}
    head = page[:400_000]
    for m in _META.finditer(head):
        a = attrs(m.group(0))
        k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        if k in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src", "image") \
                and a.get("content"):
            found.setdefault(k, a["content"])
    for m in _LINK.finditer(head):
        a = attrs(m.group(0))
        if "image_src" in (a.get("rel") or "").lower() and a.get("href"):
            found.setdefault("image_src", a["href"])
    for k in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src",
              "image_src", "image"):
        u = _good(found.get(k), base)
        if u:
            return u
    return None


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9À-ɏ]{3,}", (s or "").lower())}


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _img_src(a: dict[str, str]) -> tuple[str | None, int]:
    """(best URL, its width) of an <img>/<source>: the widest srcset entry, else src / data-src."""
    best, bw = None, 0
    for key in ("srcset", "data-srcset"):
        for part in (a.get(key) or "").split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = 0
            if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit():
                w = int(bits[1][:-1])
            # the smallest rendition of at least 480 px (else the widest): sharp in a card, not a poster
            if best is None or (bw < 480 and w > bw) or (480 <= w < bw):
                best, bw = bits[0], w
    src = None
    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        v = a.get(key)
        if v and not v.startswith("data:"):
            src = v
            break
    if best and bw:
        return best, bw
    w = a.get("width") or ""
    return src or best, int(w) if w.isdigit() else 0


def dom_image(page: str, base: str, title: str = "") -> str | None:
    """The largest <img> in the page whose alt text matches the listing title (or, with no title, the largest
    one with a size of at least 300 px stated)."""
    title = title or page_title(page)
    best, score = None, 0.0
    for m in _IMG_TAG.finditer(page[:MAX_HTML]):
        a = attrs(m.group(0))
        src, w = _img_src(a)
        u = _good(src, base)
        if not u:
            continue
        alt = a.get("alt") or a.get("title") or ""
        ov = _overlap(alt, title) if title else 0.0
        h = a.get("height") or ""
        size = max(w, int(h) if h.isdigit() else 0)
        if ov < 0.5 and size < 300:
            continue
        s = ov * 2 + min(size, 1600) / 1600
        if s > score:
            best, score = u, s
    return best


def page_title(page: str) -> str:
    for rx in (_H1, _TITLE):
        m = rx.search(page[:400_000])
        if m:
            t = re.sub(r"<[^>]+>", " ", m.group(1))
            t = " ".join(_html.unescape(t).split())
            if t:
                return t
    return ""


def _good(u: str | None, base: str) -> str | None:
    if not u or not isinstance(u, str):
        return None
    u = _html.unescape(u.strip())
    if u.startswith("//"):
        u = "https:" + u
    u = urljoin(base, u)
    return upgrade(u) if is_product_photo(u) else None


def image_from_html(page: str, url: str) -> dict:
    """{image, source} for a listing page: jsonld > og > dom > none."""
    if not page:
        return {"image": None, "source": "none"}
    for source, fn in (("jsonld", jsonld_image), ("og", meta_image)):
        try:
            u = fn(page, url)
        except Exception:
            u = None
        if u:
            return {"image": u, "source": source}
    u = dom_image(page, url)
    return {"image": u, "source": "dom"} if u else {"image": None, "source": "none"}


# ---------------------------------------------------------------- re-pairing split rows

def _norm_path(u: str) -> str:
    try:
        return urlsplit(u).path.rstrip("/")
    except ValueError:
        return ""


NOT_PHOTO_ALT = re.compile(r"\b(?:logo|avatar|profile|seller|verkoper|myyjä|icon|badge|flag)\b", re.I)


def _enclosing_href(page: str, at: int) -> str | None:
    """The href of the <a> this position sits inside (an <a> opened before it and not closed yet), else None."""
    start = max(0, at - 3000)
    chunk = page[start:at]
    o = max(chunk.rfind("<a "), chunk.rfind("<a\n"), chunk.rfind("<A "))
    if o < 0 or chunk.rfind("</a>") > o or chunk.rfind("</A>") > o:
        return None
    m = _HREF.search(chunk[o:o + 2000].split(">", 1)[0])
    return _html.unescape(m.group(1)) if m else ""


def _row_ids(path: str) -> set[str]:
    """Distinctive ids in a listing path (uuid, 'ID1cper0', 'm2445403041', '31111381') that a photo URL might
    carry. Lower case."""
    last = path.rsplit("/", 1)[-1].lower()
    out = {m.group(0) for m in _UUID.finditer(path.lower())}
    for t in re.findall(r"[a-z0-9]{7,}", last):
        if re.search(r"\d", t) and re.search(r"\d{5,}|[a-z]\d|\d[a-z]", t):
            out.add(t)
    return out


def pair_images(page_html: str, rows: list[dict], page_url: str = "", title_key: str = "title",
                max_gap: int = 5000) -> list[dict]:
    """Rows from a search page ([{url, title, image, ...}]) -> the same rows (copies) with `image` re-paired
    by DOM proximity, and `image_check` = 'paired' | 'placeholder' | 'shared' | 'unpaired' | 'kept'.

    An <img> belongs to the listing whose link (any occurrence of its path) is nearest to it in the HTML; the
    nearest link of ANOTHER listing in between ends the claim. An <img> whose alt text matches a row's title
    belongs to that row outright. A row whose own card only holds a placeholder (no_thumbnail.svg, data:)
    gets no image rather than its neighbour's. A photo claimed by more than one row is dropped for all."""
    out = [{**r, "image": r.get("image") or None} for r in rows]
    if not out:
        return out
    paths = [_norm_path(str(r.get("url") or "")) for r in out]
    occ: list[tuple[int, int]] = []        # (position, row index); -1 = a listing that is not one of the rows
    if page_html:
        for i, p in enumerate(paths):
            if len(p) < 6:
                continue
            for m in re.finditer(re.escape(p), page_html):
                occ.append((m.start(), i))
        # other listings' links (cards the splitter dropped, ads) end a row's claim too
        prefixes = {p.rsplit("/", 1)[0] + "/" for p in paths if p.count("/") >= 2}
        prefixes = {x for x in prefixes if len(x) > 2}
        own = {p for p in paths if p}
        if prefixes:
            base = page_url or str(out[0].get("url") or "")
            for m in _HREF.finditer(page_html):
                try:
                    hp = urlsplit(urljoin(base, _html.unescape(m.group(1)))).path.rstrip("/")
                except ValueError:
                    continue
                if hp in own or not any(hp.startswith(x) and len(hp) > len(x) + 3 for x in prefixes):
                    continue
                occ.append((m.start(), -1))
    occ.sort()
    own_paths = {p: i for i, p in enumerate(paths) if p}
    found_rows = {i for _, i in occ if i >= 0}
    ids = [_row_ids(p) for p in paths]
    base = page_url or str(out[0].get("url") or "")

    def row_of_href(href: str) -> int | None:
        try:
            hp = urlsplit(urljoin(base, href)).path.rstrip("/")
        except ValueError:
            return None
        if hp in own_paths:
            return own_paths[hp]
        return next((i for p, i in own_paths.items() if len(p) >= 8 and p in hp), None)

    if page_html and (occ or any(ids)):
        pos = [p for p, _ in occ]
        import bisect
        claims: dict[int, list[tuple[float, str | None]]] = {}
        for m in _IMG_TAG.finditer(page_html):
            a = attrs(m.group(0))
            src, _ = _img_src(a)
            raw = (src or "").strip()
            alt = a.get("alt") or ""
            if NOT_PHOTO_ALT.search(alt):
                continue                       # a seller's logo / avatar in the card
            owner, dist, strong = -1, 10 ** 9, False
            # 1) the photo's file name carries the listing's own id (backmarket <uuid>-1_<..>.jpg)
            if raw:
                low = raw.lower()
                hit = [i for i, t in enumerate(ids) if t and any(x in low for x in t)]
                if len(hit) == 1:
                    owner, dist, strong = hit[0], 0, True
            # 2) wrapped in a link: to one of the rows = that row; to anything else = not a listing photo
            href = _enclosing_href(page_html, m.start())
            if not strong and href is not None:
                j = row_of_href(href)
                if j is None:
                    continue                   # seller profile, ad, another page
                owner, dist, strong = j, 0, True
            if not strong:
                k = bisect.bisect_left(pos, m.start())
                cands = []
                if k > 0:
                    cands.append((m.start() - pos[k - 1], occ[k - 1][1]))
                if k < len(pos):
                    cands.append((pos[k] - m.start(), occ[k][1]))
                if not cands:
                    continue
                dist, owner = min(cands)
                # 3) alt text naming one of the two neighbours
                if alt:
                    scored = [(_overlap(alt, str(out[j].get(title_key) or "")), j) for _, j in cands if j >= 0]
                    if scored:
                        sc, j = max(scored)
                        if sc >= 0.75:
                            owner, dist, strong = j, 0, True
            if owner < 0 or dist > max_gap:
                continue
            good = _good(raw, base) if raw else None
            claims.setdefault(owner, []).append((dist - (10 ** 6 if strong else 0), good))
        for i, r in enumerate(out):
            cs = sorted(claims.get(i, []), key=lambda c: c[0])
            if not cs:
                if i in found_rows and r.get("image"):
                    r["image"] = None          # its card has no photo: the old one came from a neighbour
                    r["image_check"] = "unpaired"
                else:
                    r["image_check"] = "kept"  # its link is not in this HTML: nothing to judge by
                continue
            photo = next((g for _, g in cs if g), None)
            r["image"] = photo
            r["image_check"] = "paired" if photo else "placeholder"
    # a photo on more than one row is somebody's neighbour (or the site's placeholder): drop it everywhere
    keys: dict[str, int] = {}
    for r in out:
        k = photo_key(r.get("image"))
        if k:
            keys[k] = keys.get(k, 0) + 1
    for r in out:
        k = photo_key(r.get("image"))
        if k and keys[k] > 1:
            r["image"] = None
            r["image_check"] = "shared"
        elif r.get("image") and not is_product_photo(r["image"]):
            r["image"] = None
            r["image_check"] = "placeholder"
    return out


# ---------------------------------------------------------------- photos from the page's embedded state
# Lazy-loaded cards (olx.pl: only the first ~4 of 50 cards carry an <img>, the rest "no_thumbnail.svg") still
# ship every listing's photos in the page's app state: `window.__PRERENDERED_STATE__ = "<json>"`,
# `<script id="__NEXT_DATA__" type="application/json">`, `window.__INITIAL_STATE__ = {...}`. A state object
# whose own link is a row's listing URL carries that listing's photo: keyed by URL, so never a neighbour's.

_STATE_ASSIGN = re.compile(r"window\.__[A-Za-z0-9_]+__\s*=\s*", re.S)
_JSON_SCRIPT = re.compile(r"<script\b[^>]*type=[\"']application/json[\"'][^>]*>(.*?)</script>", re.S | re.I)
STATE_MAX_CHARS = 8_000_000
_LINK_KEYS = ("url", "urlPath", "url_path", "href", "link", "permalink", "path", "canonicalUrl", "canonical_url",
              "shareUrl", "itemUrl", "item_url", "adUrl", "detailUrl", "webUrl", "web_url")
_PHOTO_KEYS = ("photosSet", "srcset", "srcSet", "thumbnailUrl", "thumbnail", "thumb", "image", "imageUrl",
               "image_url", "mainImage", "main_image", "primaryImage", "picture", "photo", "images", "photos",
               "pictures", "imageUrls", "image_urls", "media", "gallery")


def _state_blobs(page: str) -> list[Any]:
    out: list[Any] = []
    dec = json.JSONDecoder()
    budget = STATE_MAX_CHARS
    for m in _STATE_ASSIGN.finditer(page[:MAX_HTML * 4]):
        if budget <= 0:
            break
        try:
            val, end = dec.raw_decode(page, m.end())
        except ValueError:
            continue
        budget -= end - m.end()
        if isinstance(val, str) and val[:1] in "{[":
            try:
                val = json.loads(val)
            except ValueError:
                continue
        if isinstance(val, (dict, list)):
            out.append(val)
    for m in _JSON_SCRIPT.finditer(page[:MAX_HTML * 4]):
        body = m.group(1).strip()
        if not body or body[:1] not in "{[" or len(body) > budget:
            continue
        budget -= len(body)
        try:
            out.append(json.loads(body))
        except ValueError:
            continue
    return out


def _srcset_pick(s: str) -> str | None:
    """'u1 1x,u2 2x,u3 3x' -> u2 (sharp in a card, not a poster); 'u 320w, v 640w' -> the >= 480 px one."""
    parts = [p.strip().split() for p in re.split(r",(?=\s*(?:https?:)?//|\s*/)", s) if p.strip()]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if any(len(p) > 1 and p[1].endswith("w") for p in parts):
        best, _ = _img_src({"srcset": ", ".join(" ".join(p) for p in parts)})
        return best
    for p in parts:
        if len(p) > 1 and p[1] == "2x":
            return p[0]
    return parts[0][0]


def _state_photo(v: Any, base: str, depth: int = 0) -> str | None:
    if depth > 3 or v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if re.search(r"\s\d+(?:\.\d+)?[xw]\b", s):
            s = _srcset_pick(s) or ""
        return _good(s, base) if s else None
    if isinstance(v, list):
        for x in v[:3]:
            got = _state_photo(x, base, depth + 1)
            if got:
                return got
        return None
    if isinstance(v, dict):
        for k in ("srcset", "srcSet", "url", "src", "href", "uri", "link", "medium", "large", "full", "original",
                  "contentUrl", "thumbnail"):
            if k in v:
                got = _state_photo(v[k], base, depth + 1)
                if got:
                    return got
    return None


def state_photos(page: str, base: str, paths: set[str] | None = None) -> dict[str, str]:
    """{listing path: photo URL} from the page's embedded app state (only paths in `paths`, when given)."""
    out: dict[str, str] = {}
    if not page or (paths is not None and not paths):
        return out
    for blob in _state_blobs(page):
        for node in _walk(blob):
            link = None
            for k in _LINK_KEYS:
                v = node.get(k)
                if isinstance(v, str) and len(v) > 5 and "/" in v:
                    p = _norm_path(urljoin(base, v.strip()))
                    if len(p) >= 6 and (paths is None or p in paths):
                        link = p
                        break
            if link is None or link in out:
                continue
            for k in _PHOTO_KEYS:
                if k in node:
                    got = _state_photo(node[k], base)
                    if got:
                        out[link] = got
                        break
    return out


def fill_from_state(rows: list[dict], page_html: str, page_url: str) -> list[dict]:
    """Rows left without a photo get their own listing's photo from the embedded app state."""
    rows = [dict(r) for r in rows]
    missing = {_norm_path(urljoin(page_url or "", str(r.get("url") or ""))): i
               for i, r in enumerate(rows) if not r.get("image") and r.get("url")}
    missing.pop("", None)
    if not missing or not page_html:
        return rows
    found = state_photos(page_html, page_url or str(rows[0].get("url") or ""), set(missing))
    taken = {photo_key(r.get("image")) for r in rows if r.get("image")}
    for p, i in missing.items():
        u = found.get(p)
        if u and photo_key(u) not in taken:
            rows[i]["image"] = u
            rows[i]["image_check"] = "state"
            taken.add(photo_key(u))
    return rows


# ---------------------------------------------------------------- a service provider's picture
# A plumber's / photographer's / accountant's page has no product photo, but it has a face: its og:image
# (a team or work photo, often a brand card) or its JSON-LD LocalBusiness image / logo. Logos and brand
# cards are fine here (they show WHO the provider is); favicons, 1x1 pixels and data: URIs are not.

BUSINESS_HINT = ("business", "organization", "organisation", "service", "store", "professional", "contractor",
                 "plumber", "electrician", "dentist", "agency", "office", "salon", "restaurant", "corporation",
                 "photograph", "accounting", "insurance", "localbusiness", "homeandconstruction", "website",
                 "webpage", "person")
_NOT_A_FACE = re.compile(r"(^|[/_.-])(favicon|sprite|sprites|spacer|pixel|blank|transparent|loader|loading|"
                         r"spinner|placeholder|1x1)([/_.-]|$)|\.ico(\?|$)", re.I)


def _any_image(u: str | None, base: str) -> str | None:
    if not u or not isinstance(u, str):
        return None
    u = _html.unescape(u.strip())
    if u.startswith("//"):
        u = "https:" + u
    u = urljoin(base, u)
    if not u.startswith(("https://", "http://")) or "#" in u:
        return None                  # '#' = a JSON-LD @id reference (.../#/schema/logo/image/), not a file
    try:
        path = urlsplit(u).path
    except ValueError:
        return None
    if not path.strip("/"):
        return None
    return None if _NOT_A_FACE.search(path) else u


_LOGO = re.compile(r"(^|[/_.-])(logo|logos|logotype|brand[_-]?mark|wordmark)", re.I)


def _brand_of(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return max(host.split(".")[:-1] or [host], key=len)


def offer_image_ok(image: str | None, page_url: str, seller: str | None = None, service: bool = False) -> bool:
    """May this picture stand for the offer? Never an .svg / icon / pixel. A product needs a real photo
    (is_product_photo). A service may show a logo only when it is the PROVIDER's own (its name or its own site's
    brand), never the platform's: tekijatori.fi/profiili/siim-heinaste with Tekijatori-logo.svg is the
    directory's logo, not the electrician."""
    if not image or not isinstance(image, str):
        return False
    try:
        path = urlsplit(image).path
    except ValueError:
        return False
    if IMG_EXT_BAD.search(path) or _NOT_A_FACE.search(path):
        return False
    if not service:
        return is_product_photo(image)
    if not _LOGO.search(path):
        return True
    fname = re.sub(r"[^a-z0-9äöüå]+", " ", path.rsplit("/", 1)[-1].lower())
    seller_words = {w for w in re.findall(r"[a-z0-9äöüå]{4,}", (seller or "").lower())}
    if seller_words & set(fname.split()):
        return True                                  # 'paavolainen-logo-musta.webp' for Sähköpalvelu Paavolainen
    brand = _brand_of(page_url)
    # the page's own site, and the seller IS that site (no other named seller): its logo is the provider's
    return not seller_words or any(brand.startswith(w) or w in brand for w in seller_words)


def _face(u: str | None, base: str) -> str | None:
    """_any_image that a viewer can show as the offer's picture: never an .svg / .ico / .gif (offer_image_ok
    drops those later, so taking one here would leave the provider with no picture at all)."""
    u = _any_image(u, base)
    if not u:
        return None
    try:
        return None if IMG_EXT_BAD.search(urlsplit(u).path) else u
    except ValueError:
        return None


_TOUCH_ICON = re.compile(r"\bapple-touch-icon(?:-precomposed)?\b|\bmask-icon\b|\bicon\b", re.I)


def touch_icon(page: str, url: str) -> str | None:
    """The site's own square brand mark: <link rel=apple-touch-icon> (180-256 px PNG), else the largest
    PNG/JPG/WebP <link rel=icon sizes=NxN> of at least 96 px. Tiny favicons (16/32/48 px) are no picture."""
    best: tuple[int, str] | None = None
    for m in _LINK.finditer(page[:400_000]):
        a = attrs(m.group(0))
        rel = (a.get("rel") or "").lower()
        if not _TOUCH_ICON.search(rel) or "mask-icon" in rel:
            continue
        href = a.get("href")
        if not href:
            continue
        u = urljoin(url, _html.unescape(href.strip()))
        if not u.startswith(("https://", "http://")):
            continue
        try:
            path = urlsplit(u).path
        except ValueError:
            continue
        if IMG_EXT_BAD.search(path):
            continue
        sizes = [int(x) for x in re.findall(r"(\d{2,4})x\d{2,4}", a.get("sizes") or "")]
        size = max(sizes) if sizes else 0
        if "apple-touch-icon" in rel:
            size = size or 180
        elif not size:
            size = int(m2.group(1)) if (m2 := re.search(r"(\d{2,4})(?:x\d{2,4})?\D*\.(?:png|jpe?g|webp)$", path,
                                                        re.I)) else 0
        if size < 96:
            continue
        if best is None or size > best[0]:
            best = (size, u)
    return best[1] if best else None


def service_image(page: str, url: str) -> str | None:
    """A provider's picture (eval r4 'unlimited graphic design subscription': 0 of 10 studios had one):
    og:image > JSON-LD business image > JSON-LD logo > the site's apple-touch-icon (its own brand mark)
    > a real product-style photo on the page. An .svg / .ico / favicon candidate is passed over, not taken."""
    if not page:
        return None
    head = page[:400_000]
    found: dict[str, str] = {}
    for m in _META.finditer(head):
        a = attrs(m.group(0))
        k = (a.get("property") or a.get("name") or "").lower()
        if k in ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src") \
                and a.get("content"):
            found.setdefault(k, a["content"])
    for k in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        u = _face(found.get(k), url)
        if u:
            return u
    logo = None
    try:
        for b in jsonld_blocks(page):
            for node in _walk(b):
                types = " ".join(_types(node))
                if not any(h in types for h in BUSINESS_HINT):
                    continue
                u = _face(_img_value(node.get("image")), url)
                if u:
                    return u
                logo = logo or _face(_img_value(node.get("logo")), url)
    except Exception:
        pass
    if logo:
        return logo
    try:
        icon = touch_icon(page, url)
    except Exception:
        icon = None
    if icon:
        return icon
    try:
        return dom_image(page, url)
    except Exception:
        return None


def pair_rows_for_reader(rows: list[dict], page_html: str, page_url: str) -> list[dict]:
    """Drop-in for reader.offers_from_split / marketplaces.split_rows callers:
        rows = marketplaces.split_rows(md, page_html, site)
        rows = images.pair_rows_for_reader(rows, page_html, page_url)
    Rows keep every field; `image` is re-paired and `image_check` says why. Rows that end without an image
    are what the front end backfills via /api/images. Never raises."""
    try:
        rows = pair_images(page_html, rows, page_url)
    except Exception:
        pass
    try:
        return fill_from_state(rows, page_html, page_url)
    except Exception:
        return rows


# ---------------------------------------------------------------- SSRF guards

def public_url(url: str) -> bool:
    """http(s) on a named public host, default port (443/80), no credentials, no IP literals or local names."""
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return False
    if p.scheme not in ("https", "http") or "." not in host or p.username or p.password:
        return False
    if port not in (None, 443, 80):
        return False
    if host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".arpa", ".test", ".invalid")):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        return True


def _resolves_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


# ---------------------------------------------------------------- allowlist

_allowed: set[str] = set()
_allow_loaded = False


def _canon(url: str) -> str:
    return (url or "").strip()


def remember(url: str | None) -> None:
    """Allow lookups for this listing URL (call it for every offer the server streams out)."""
    if isinstance(url, str) and url and public_url(url):
        _allowed.add(_canon(url))


def remember_event(event: Any) -> None:
    """For the hunt stream: remember the listing URL of an `offer` Event (or its dict)."""
    try:
        etype = getattr(event, "type", None) or event.get("type")
        data = getattr(event, "data", None) or event.get("data") or {}
        if etype == "offer":
            remember((data.get("offer") or {}).get("url"))
    except AttributeError:
        pass


def _load_recordings() -> None:
    global _allow_loaded
    if _allow_loaded:
        return
    with _lock:
        if _allow_loaded:
            return
        for path in sorted(FIXTURES.glob("live_*.jsonl")):
            try:
                for line in path.read_text().splitlines():
                    if '"offer"' not in line:
                        continue
                    row = json.loads(line)
                    if row.get("type") == "offer":
                        remember(((row.get("data") or {}).get("offer") or {}).get("url"))
            except (OSError, ValueError):
                continue
        _allow_loaded = True


_scanned: dict[int, int] = {}       # id(HuntResult) -> events already remembered


def _in_live_hunts(url: str) -> bool:
    """An offer event of a live hunt this server is streaming / streamed (agora.api._HUNTS)."""
    api = sys.modules.get("agora.api")
    hunts = getattr(api, "_HUNTS", None) or {}
    for res in list(hunts.values()):
        events = list(getattr(res, "events", []) or [])
        start = _scanned.get(id(res), 0)
        _scanned[id(res)] = len(events)
        for e in events[start:]:
            if getattr(e, "type", None) == "offer":
                o = (getattr(e, "data", None) or {}).get("offer") or {}
                u = o.get("url") if isinstance(o, dict) else getattr(o, "url", None)
                if u:
                    remember(u)
        for o in list(getattr(res, "offers", []) or []):
            remember(getattr(o, "url", None))
    return url in _allowed


def _in_store(url: str) -> bool:
    try:
        from agora import store
        return store.get_offer(url) is not None
    except Exception:
        return False


def allowed(url: str) -> bool:
    url = _canon(url)
    if not public_url(url):
        return False
    _load_recordings()
    if url in _allowed or _in_live_hunts(url):
        return True
    if _in_store(url):
        _allowed.add(url)
        return True
    return False


# ---------------------------------------------------------------- cache

def _cache_root() -> pathlib.Path:
    try:
        from agora import contextdev
        return contextdev.cache_root()
    except Exception:
        d = pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or ROOT / ".cache")
        d.mkdir(parents=True, exist_ok=True)
        return d


def _offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def _disk_path() -> pathlib.Path:
    return _cache_root() / "images.json"


def _load_disk() -> None:
    global _disk_loaded
    if _disk_loaded:
        return
    with _lock:
        if _disk_loaded:
            return
        try:
            data = json.loads(_disk_path().read_text())
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        _mem.setdefault(k, v)
        except (OSError, ValueError):
            pass
        _disk_loaded = True


_save_pending = False


def _save_disk() -> None:
    """Found photos only (a 'none' is short-lived anyway). Keeps the newest 5000."""
    global _save_pending
    _save_pending = False
    rows = {k: v for k, v in _mem.items() if v.get("image")}
    if len(rows) > 5000:
        rows = dict(sorted(rows.items(), key=lambda kv: -kv[1].get("at", 0))[:5000])
    p = _disk_path()
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows))
        tmp.replace(p)
    except OSError:
        pass


def _schedule_save() -> None:
    global _save_pending
    if _transport is not None:          # tests: no disk writes
        return
    if _save_pending:
        return
    _save_pending = True
    try:
        asyncio.get_running_loop().call_later(2.0, _save_disk)
    except RuntimeError:
        _save_disk()


def cached(url: str) -> dict | None:
    _load_disk()
    v = _mem.get(url)
    if not v:
        return None
    ttl = FOUND_TTL_S if v.get("image") else NONE_TTL_S
    return v if time.time() - v.get("at", 0) < ttl else None


def _put(url: str, res: dict) -> dict:
    res = {"image": res.get("image"), "source": res.get("source") or "none", "at": time.time()}
    _mem[url] = res
    if res["image"]:
        _schedule_save()
    return res


def clear_cache() -> None:
    _mem.clear()


# ---------------------------------------------------------------- fetching

def _reader_page_cache(url: str) -> pathlib.Path:
    """The reader's own page cache file for this URL (agora.reader._html_cache naming)."""
    return _cache_root() / "html" / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")


def _cached_page(url: str, any_age: bool) -> str | None:
    p = _reader_page_cache(url)
    try:
        if any_age or time.time() - p.stat().st_mtime < PAGE_CACHE_TTL_S:
            return p.read_text(errors="replace")
    except OSError:
        return None
    return None


def _semaphores(host: str) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(CONCURRENCY)
    hs = _host_sems.get(host)
    if hs is None:
        hs = _host_sems[host] = asyncio.Semaphore(PER_HOST)
    return _sem, hs


BLOCK_MARKERS = ("captcha", "cf-chl", "are you a robot", "datadome", "perimeterx", "px-captcha",
                 "just a moment...", "attention required")


async def fetch_page(url: str) -> tuple[int, str]:
    """GET a listing page politely. (status, html); status 0 = refused / network error.
    Redirects are followed by hand (<= 4) and every hop must be a public host."""
    if not public_url(url):
        return 0, ""
    if _transport is None:
        page = _cached_page(url, any_age=_offline())
        if page is not None:
            return 200, page
        if _offline():
            return 0, ""
    host = (urlsplit(url).hostname or "").lower()
    sem, hs = _semaphores(host)
    async with sem, hs:
        try:
            async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT_S, follow_redirects=False,
                                         headers=HEADERS) as c:
                cur = url
                for _ in range(MAX_REDIRECTS + 1):
                    if not public_url(cur):
                        return 0, ""
                    h = (urlsplit(cur).hostname or "").lower()
                    if _transport is None and not await asyncio.to_thread(_resolves_public, h):
                        return 0, ""
                    async with c.stream("GET", cur) as r:
                        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                            cur = urljoin(cur, r.headers["location"])
                            continue
                        ctype = r.headers.get("content-type", "").lower()
                        if r.status_code != 200 or (ctype and "html" not in ctype and "xml" not in ctype):
                            return r.status_code, ""
                        buf = bytearray()
                        async for chunk in r.aiter_bytes():
                            buf += chunk
                            if len(buf) > MAX_HTML:
                                break
                        return 200, buf.decode(r.encoding or "utf-8", errors="replace")
                return 0, ""
        except (httpx.HTTPError, ValueError, OSError):
            return 0, ""


async def find_image(url: str, fresh: bool = False) -> dict:
    """{image, source: jsonld|og|dom|none} for a listing URL. Cached; concurrent calls share one fetch."""
    url = _canon(url)
    if not fresh:
        hit = cached(url)
        if hit:
            return {"image": hit["image"], "source": hit["source"]}
    if url in _inflight:
        return await asyncio.shield(_inflight[url])
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _inflight[url] = fut
    try:
        status, page = await fetch_page(url)
        head = page[:5000].lower()
        if status == 200 and page and not (len(page) < 20000 and any(m in head for m in BLOCK_MARKERS)):
            res = image_from_html(page, url)
        else:
            res = {"image": None, "source": "none"}
        res = _put(url, res)
        out = {"image": res["image"], "source": res["source"]}
        fut.set_result(out)
        return out
    except BaseException as exc:
        if not fut.done():
            fut.set_exception(exc)
            fut.exception()
        raise
    finally:
        _inflight.pop(url, None)


async def verify(url: str, have: str | None = None, fresh: bool = False) -> dict:
    """find_image + how it compares with the photo the row has:
    match: 'same' (same file), 'replaced' (the page shows another photo: use the page's), 'filled' (the row
    had none), 'unknown' (the page gave nothing: keep what the row has)."""
    res = await find_image(url, fresh=fresh)
    page_img = res.get("image")
    if not page_img:
        return {**res, "image": None, "match": "unknown"}
    if not have:
        return {**res, "match": "filled"}
    if same_photo(have, page_img):
        return {**res, "match": "same"}
    return {**res, "match": "replaced"}


async def find_many(urls: list[str], have: dict[str, str] | None = None, fresh: bool = False) -> dict[str, dict]:
    have = have or {}
    uniq = list(dict.fromkeys(_canon(u) for u in urls if isinstance(u, str) and u))[:BATCH_MAX]
    out: dict[str, dict] = {}

    async def one(u: str) -> None:
        if not allowed(u):
            out[u] = {"image": None, "source": "denied", "match": "unknown"}
            return
        try:
            out[u] = await verify(u, have.get(u), fresh=fresh)
        except Exception:
            out[u] = {"image": None, "source": "none", "match": "unknown"}

    await asyncio.gather(*(one(u) for u in uniq))
    return out


# ---------------------------------------------------------------- routes

router = APIRouter()


@router.get("/api/image")
async def get_image(url: str = Query(..., max_length=2048, description="listing URL a hunt streamed"),
                    have: str | None = Query(None, max_length=2048, description="the photo the row shows now"),
                    fresh: bool = Query(False, description="look again even if a 'none' is cached")) -> dict:
    """{url, image, source: jsonld|og|dom|none, match: same|replaced|filled|unknown}. 403 for unknown URLs."""
    if not allowed(url):
        raise HTTPException(403, "not a listing from a hunt")
    res = await verify(url, have, fresh=fresh)
    return {"url": url, **res}


class _Batch(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=BATCH_MAX)
    have: dict[str, str | None] = Field(default_factory=dict)
    fresh: bool = False


@router.post("/api/images")
async def post_images(body: _Batch) -> dict:
    """{url: {image, source, match}} for up to 50 listing URLs (others are ignored)."""
    have = {k: v for k, v in (body.have or {}).items() if isinstance(v, str) and len(v) < 2048}
    return await find_many([u for u in body.urls if len(u) < 2048], have, fresh=body.fresh)
