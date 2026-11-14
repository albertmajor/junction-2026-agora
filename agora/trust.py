"""TRUST SIGNALS: the seller behind the price. Written at Junction 2026.

Three cheap signals that a listing may not be what it looks like:
  1. PHOTO REUSE   the first image of each offer, perceptually hashed (imagehash pHash). The same photo
                   on two different sellers' listings is a stock photo (ask for a real one) or a copied
                   one (a classic scam). An identical image URL on two shops counts too, no fetch needed.
  2. YOUNG DOMAIN  WHOIS creation date (python-whois): a shop domain younger than 90 days is a red flag.
  3. LOOK-ALIKE    the shop's name (registrable domain via tldextract) within a small edit distance of a
                   well-known shop, or a known name with extra words glued on ("verkkokauppa-outlet.shop").

Everything here is best effort and offline-safe: network lookups (image download, WHOIS) only happen in
`warm()` / `prefetch()`, inside a time box, never with AGORA_OFFLINE=1, and every answer is cached under
`.cache/` (`phash.json`, `whois.json`). The judge reads only the cache, so judging is instant and
repeatable. Nothing here raises: a missing library or a failed lookup means "no signal".
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import json
import os
import pathlib
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Iterable

from agora.models import Offer

ROOT = pathlib.Path(__file__).resolve().parent.parent

YOUNG_DAYS = 90             # a shop domain younger than this is a red flag
PHASH_MAX_DISTANCE = 6      # Hamming distance (64-bit pHash) that still counts as "the same photo"
IMAGE_TIMEOUT = 4.0
IMAGE_MAX_BYTES = 6_000_000
WHOIS_TIMEOUT = 4
FAIL_RETRY_S = 24 * 3600    # a failed lookup is retried after a day

# well-known shops people trust, by their registrable name (the "verkkokauppa" in verkkokauppa.com)
KNOWN_NAMES = (
    "amazon", "bhphotovideo", "verkkokauppa", "gigantti", "power", "mediamarkt", "apple", "sony", "jimms",
    "proshop", "fotosidan", "rajala", "japanphoto", "currys", "argos", "walmart", "bestbuy", "adorama",
    "kenmorecamera", "backmarket", "swappie", "refurbed", "cyberport", "foto-erhardt", "calumet",
    "wexphotovideo", "elgiganten", "komplett", "ikea", "ebay", "tori", "zalando", "samsung", "jessops",
    "cvp", "mpb", "keh", "usedlens", "kamerastore", "telia", "elisa", "dna", "clasohlson", "prisma",
    "stockmann", "tokmanni", "motonet", "bauhaus", "hobbyhall", "xxl", "intersport", "alibaba", "aliexpress",
    "otto", "notebooksbilliger", "alternate", "conrad", "galaxus", "digitec", "fnac", "boulanger", "darty",
    "coolblue", "bol", "allegro", "euronics", "expert", "saturn", "dustin", "inet", "webhallen", "netonnet",
)
# names that are plain words: an honest shop can contain them ("power-tools.fi", "expert-camera.de")
GENERIC_NAMES = {"power", "expert", "saturn", "prisma", "otto", "alternate", "conrad", "galaxus", "inet",
                 "elisa", "telia", "bauhaus", "intersport", "euronics"}
# marketplaces host many sellers under one old domain: domain age says nothing about the seller
MARKETPLACE_NAMES = ("ebay", "tori", "huuto", "facebook", "kleinanzeigen", "blocket", "vinted", "craigslist",
                     "marktplaats", "leboncoin", "subito", "olx", "allegro", "mercari", "kijiji", "finn", "dba",
                     "gumtree", "wallapop", "willhaben", "2dehands", "tradera", "swappa", "amazon", "etsy")

_lock = threading.Lock()
_extractor: Any = None
_mem: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------- switches, cache

def offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def _cache_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or ROOT / ".cache")


def _cache(name: str) -> dict[str, Any]:
    """In-memory view of `.cache/<name>.json`, keyed by the cache dir (tests swap it per test)."""
    path = _cache_dir() / f"{name}.json"
    key = str(path)
    with _lock:
        if key not in _mem:
            try:
                _mem[key] = json.loads(path.read_text())
            except (OSError, ValueError):
                _mem[key] = {}
        return _mem[key]


def _save(name: str) -> None:
    path = _cache_dir() / f"{name}.json"
    with _lock:
        data = dict(_mem.get(str(path)) or {})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=0, sort_keys=True))
        tmp.replace(path)
    except OSError:
        pass


def _put(name: str, key: str, value: dict[str, Any]) -> None:
    c = _cache(name)
    with _lock:
        c[key] = value


# ---------------------------------------------------------------- domains (tldextract)

def _tld() -> Any:
    """tldextract with its bundled public-suffix snapshot: never fetches the list over the network."""
    global _extractor
    if _extractor is None:
        try:
            import tldextract
            _extractor = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
        except Exception:
            _extractor = False
    return _extractor


def host_of(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", s)
    host = m.group(1) if m else s.split("/")[0]
    host = host.rsplit("@", 1)[-1].split(":")[0]
    return host.removeprefix("www.")


def registrable(url_or_host: str) -> str:
    """'https://shop.verkkokauppa.com/x' -> 'verkkokauppa.com'; 'foo.co.uk' stays whole."""
    host = host_of(url_or_host)
    ex = _tld()
    if ex:
        try:
            r = ex(host)
            if r.domain and r.suffix:
                return f"{r.domain}.{r.suffix}"
            if r.domain:
                return r.domain
        except Exception:
            pass
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "ac"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def shop_name(url_or_host: str) -> str:
    """The name part of the registrable domain: 'verkkokauppa-outlet.shop' -> 'verkkokauppa-outlet'."""
    return registrable(url_or_host).split(".")[0]


def edit_distance(a: str, b: str, cap: int = 99) -> int:
    """Levenshtein distance (insert / delete / substitute = 1), stops early once every path exceeds `cap`."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def lookalike_of(url_or_host: str, known: Iterable[str] = KNOWN_NAMES) -> str | None:
    """The well-known shop this domain imitates, or None. The real shop on any TLD (mediamarkt.de vs
    mediamarkt.fi) is not a look-alike; 'verkkokaupa.com', 'gigantti-outlet.shop', 'amaz0n.eu' are."""
    name = shop_name(url_or_host)
    if not name:
        return None
    known = tuple(known)
    if name in known:
        return None
    plain = name.replace("-", "")
    for k in known:
        kp = k.replace("-", "")
        if plain == kp:
            return None          # foto-erhardt vs fotoerhardt: the same name, written two ways
    for k in known:
        kp = k.replace("-", "")
        if len(kp) < 5 or k in GENERIC_NAMES:
            continue             # "dna", "keh", "power": too short or too common, too many honest neighbours
        if len(kp) >= 6 and edit_distance(plain, kp, cap=2) <= (2 if len(kp) >= 8 else 1):
            return k
        # a known name (or a near miss of it) with words glued on: "verkkokauppa-outlet", "verkkokaupa-outlet"
        parts = re.split(r"[-_]", name)
        if len(parts) > 1 and any(x == k or (len(kp) >= 8 and edit_distance(x, kp, cap=1) <= 1) for x in parts):
            return k
        if len(kp) >= 7 and plain.startswith(kp) and re.fullmatch(r"\d{1,4}|shop|store|outlet|sale|deals?|eu|fi",
                                                                    plain[len(kp):]):
            return k
    return None


def is_marketplace(url_or_host: str) -> bool:
    return shop_name(url_or_host) in MARKETPLACE_NAMES


# ---------------------------------------------------------------- WHOIS (domain age)

def _as_date(x: Any) -> date | None:
    if isinstance(x, list):
        ds = [d for d in (_as_date(y) for y in x) if d]
        return min(ds) if ds else None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", x)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _lookup_whois(domain: str) -> dict[str, Any]:
    try:
        import whois
        w = whois.whois(domain, quiet=True, timeout=WHOIS_TIMEOUT)
        created = _as_date(w.get("creation_date") if hasattr(w, "get") else getattr(w, "creation_date", None))
        return {"created": created.isoformat() if created else None, "ok": True, "ts": time.time()}
    except Exception:
        return {"created": None, "ok": False, "ts": time.time()}


def domain_created(url_or_host: str) -> date | None:
    """Cached WHOIS creation date of the shop's registrable domain (cache only, no network)."""
    rec = _cache("whois").get(registrable(url_or_host))
    return _as_date(rec.get("created")) if rec else None


def domain_age_days(url_or_host: str, today: date | None = None) -> int | None:
    created = domain_created(url_or_host)
    if created is None:
        return None
    return max(0, ((today or date.today()) - created).days)


def _whois_due(domain: str) -> bool:
    rec = _cache("whois").get(domain)
    return rec is None or (not rec.get("ok") and time.time() - float(rec.get("ts") or 0) > FAIL_RETRY_S)


# ---------------------------------------------------------------- photos (pHash)

def hash_image_bytes(data: bytes) -> str | None:
    """64-bit perceptual hash (hex) of an image, None if it cannot be decoded."""
    try:
        import imagehash
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.draft("RGB", (256, 256))          # JPEG: decode small, much faster
            return str(imagehash.phash(im.convert("RGB")))
    except Exception:
        return None


def _download(url: str) -> bytes | None:
    try:
        import httpx
        with httpx.Client(timeout=IMAGE_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; Agora/0.1 image check)"}) as c:
            with c.stream("GET", url) as r:
                if r.status_code != 200:
                    return None
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > IMAGE_MAX_BYTES:
                        return None
                return bytes(buf)
    except Exception:
        return None


def _lookup_image(url: str) -> dict[str, Any]:
    data = _download(url)
    h = hash_image_bytes(data) if data else None
    return {"hash": h, "ok": h is not None, "ts": time.time()}


def image_hash(url: str | None) -> str | None:
    """Cached pHash of an image URL (cache only, no network)."""
    if not url:
        return None
    rec = _cache("phash").get(url)
    return rec.get("hash") if rec else None


def remember_hash(url: str, h: str | None) -> None:
    """Store a hash computed elsewhere (tests, a reader that already has the bytes)."""
    _put("phash", url, {"hash": h, "ok": h is not None, "ts": time.time()})


def _image_due(url: str) -> bool:
    rec = _cache("phash").get(url)
    return rec is None or (not rec.get("ok") and time.time() - float(rec.get("ts") or 0) > FAIL_RETRY_S)


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


# ---------------------------------------------------------------- warm the caches (the only network part)

def warm(offers: list[Offer], budget_s: float = 3.0, whois_lookups: bool = True) -> dict[str, int]:
    """Fetch missing image hashes and WHOIS dates in parallel, waiting at most `budget_s` seconds.
    Lookups still running after that keep going in the background and land in the cache for next time.
    Offline (AGORA_OFFLINE=1) or AGORA_TRUST_FETCH=0: does nothing."""
    if offline() or os.environ.get("AGORA_TRUST_FETCH", "1") in ("0", "false", "no") or budget_s <= 0:
        return {"images": 0, "whois": 0}
    images = sorted({o.image for o in offers if o.image and o.image.startswith("http") and _image_due(o.image)})
    domains = sorted({registrable(o.url) for o in offers if not is_marketplace(o.url)}) if whois_lookups else []
    domains = [d for d in domains if "." in d and _whois_due(d)]
    if not images and not domains:
        return {"images": 0, "whois": 0}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="agora-trust")
    futs: dict[concurrent.futures.Future[dict[str, Any]], tuple[str, str]] = {}
    for u in images[:40]:
        futs[pool.submit(_lookup_image, u)] = ("phash", u)
    for d in domains[:30]:
        futs[pool.submit(_lookup_whois, d)] = ("whois", d)
    done = {"images": 0, "whois": 0}

    def land(f: concurrent.futures.Future[dict[str, Any]]) -> None:
        name, key = futs[f]
        try:
            _put(name, key, f.result())
            _save(name)
        except Exception:
            pass

    finished, _ = concurrent.futures.wait(futs, timeout=budget_s)
    for f in finished:
        land(f)
        done["images" if futs[f][0] == "phash" else "whois"] += 1
    for f in futs:
        if f not in finished:
            f.add_done_callback(land)       # late answers still fill the cache
    pool.shutdown(wait=False, cancel_futures=False)
    return done


async def prefetch(offers: list[Offer], budget_s: float = 3.0) -> dict[str, int]:
    """`warm` off the event loop: call it while pages are still being read."""
    return await asyncio.to_thread(warm, offers, budget_s)


# ---------------------------------------------------------------- the signals

def same_photo_groups(offers: list[Offer]) -> dict[int, list[Offer]]:
    """id(offer) -> the OTHER sellers' offers showing the same photo (same image URL, or pHash
    within PHASH_MAX_DISTANCE). Only different registrable domains count: one shop reusing its own
    photo across pages is normal."""
    out: dict[int, list[Offer]] = {}
    keyed = [(o, registrable(o.url), o.image, image_hash(o.image)) for o in offers if o.image]
    for i, (a, da, ua, ha) in enumerate(keyed):
        for b, db, ub, hb in keyed[i + 1:]:
            if da == db:
                continue
            same = (ua == ub) or (ha is not None and hb is not None and hamming(ha, hb) <= PHASH_MAX_DISTANCE)
            if same:
                out.setdefault(id(a), []).append(b)
                out.setdefault(id(b), []).append(a)
    return out


def assess(o: Offer, peers: list[Offer], *, photos: dict[int, list[Offer]] | None = None,
           today: date | None = None) -> list[tuple[str, float, float | None]]:
    """Trust signals for one offer: [(flag, score penalty, trust cap or None)]. Cache only, never blocks."""
    out: list[tuple[str, float, float | None]] = []
    used_like = o.condition in ("used", "unknown") or is_marketplace(o.url)

    match = (photos if photos is not None else same_photo_groups(peers + ([o] if o not in peers else []))).get(id(o))
    if match:
        others = sorted({registrable(x.url) for x in match})
        where = ", ".join(others[:3])
        if used_like and any(x.condition in ("used", "unknown") or is_marketplace(x.url) for x in match):
            out.append((f"photo copied from another seller's listing ({where}): ask for a photo of the real unit",
                        0.25, None))
        elif used_like:
            out.append((f"stock photo (same as {where}): ask for a photo of the real unit", 0.05, None))
        # new items from shops share manufacturer photos: normal, no flag

    like = lookalike_of(o.url)
    if like:
        out.append((f"shop name looks like {like} but is {registrable(o.url)}: possible look-alike shop", 0.4, 0.3))

    if not is_marketplace(o.url):
        age = domain_age_days(o.url, today)
        if age is not None and age < YOUNG_DAYS:
            out.append((f"shop domain is only {age} days old ({registrable(o.url)})", 0.3, 0.45))
    return out
