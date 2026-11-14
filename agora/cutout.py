"""GET /cut?u=<photo url>: the object lifted out of a listing photo, as a transparent PNG.

The idea and the native tool (agora/native/cutout.m, macOS Vision "lift subject") come from our teammate
rpaszekdev's Agora wall prototype; this is a FastAPI port of his guarded proxy.

Guards (it fetches URLs, so it must not become an open proxy):
- allowlist: photo URLs from the recorded hunts (tests/fixtures/live_*.jsonl), URLs the server handed out
  (`remember(url)`), and shelf image URLs. Anything else -> 403.
- https on a named public host only (no IP literals, no local names, no private resolution).
- no redirects followed, 8 MB cap, image/* only, 20 s timeout.
Cache: .cache/cuts/<sha256(url)>.png is checked first. When cutting fails (no object, not macOS, the tool
does not build) the browser gets a 302 to the raw photo and the front end shows it on a plate. When the shop
refuses the photo itself (403, not an image) a browser could not load it either: /cut answers with a small
monogram plate (SVG, the shop's initial) instead of a broken image.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(__file__).resolve().parent / "native" / "cutout.m"
CACHE = ROOT / ".cache"
CUTS = CACHE / "cuts"
BIN = CACHE / "cutout-bin"
FIXTURES = ROOT / "tests" / "fixtures"
SHELF = pathlib.Path(__file__).resolve().parent / "web" / "assets" / "shelf.json"

MAX_BYTES = 8_000_000
TIMEOUT_S = 20.0
CUT_TIMEOUT_S = 20.0
UA = "Mozilla/5.0 (agora-cutout)"

router = APIRouter()

_allowed: set[str] = set()
_alias: dict[str, str] = {}          # relative photo path from a recording -> absolute URL (joined on its page)
_page: dict[str, str] = {}           # photo URL -> the listing page it came from (for the monogram letter)
DEAD_TTL_S = 6 * 3600                # a photo the shop refused (403, not an image) is not retried for 6 h
_loaded = False
_lock = threading.Lock()
_build_ok: bool | None = None
_inflight: dict[str, asyncio.Future] = {}
_sem = asyncio.Semaphore(3)          # Vision is CPU heavy: at most 3 cutouts at once


# ---------- allowlist ----------

def _fixture_images() -> set[str]:
    out: set[str] = set()
    for path in sorted(FIXTURES.glob("live_*.jsonl")):
        try:
            for line in path.read_text().splitlines():
                if '"offer"' not in line:
                    continue
                row = json.loads(line)
                if row.get("type") == "offer":
                    offer = (row.get("data") or {}).get("offer") or {}
                    img = offer.get("image")
                    if isinstance(img, str) and img:
                        full = absolute(img, offer.get("url"))
                        if full:
                            out.add(full)
                            if offer.get("url"):
                                _page.setdefault(full, offer["url"])
        except (OSError, ValueError):
            continue
    return out


def absolute(img: str, page: str | None) -> str | None:
    """A recorded photo URL made absolute: '/image/3555.webp' on e-infin.com -> https://www.e-infin.com/image/3555.webp."""
    if img.startswith("//"):
        img = "https:" + img
    if img.startswith(("https://", "http://")):
        return img
    if not page:
        return None
    full = urljoin(page, img)
    _alias.setdefault(img, full)
    return full


def resolve(u: str) -> str:
    """The absolute URL for a photo reference the browser sent (relative recorded paths map to their page)."""
    _ensure_loaded()
    return _alias.get(u, u)


def _shelf_images() -> set[str]:
    try:
        rows = json.loads(SHELF.read_text())
    except (OSError, ValueError):
        return set()
    rows = rows.get("items", []) if isinstance(rows, dict) else rows
    return {r["image"] for r in rows if isinstance(r, dict) and isinstance(r.get("image"), str)}


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if not _loaded:
            _allowed.update(_fixture_images() | _shelf_images())
            _loaded = True


def remember(url: str | None) -> None:
    """Allow /cut to fetch this photo URL (call it for every offer image the server streams out)."""
    if isinstance(url, str) and url and public_https(url):
        _ensure_loaded()
        _allowed.add(url)


def remember_event(event) -> None:
    """Convenience for the hunt stream: remember the image of an `offer` Event (or its dict)."""
    try:
        etype = getattr(event, "type", None) or event.get("type")
        data = getattr(event, "data", None) or event.get("data") or {}
        if etype == "offer":
            remember((data.get("offer") or {}).get("image"))
    except AttributeError:
        pass


def allowed(url: str) -> bool:
    _ensure_loaded()
    return url in _allowed


def public_https(url: str) -> bool:
    """True for https URLs on a named public host. Blocks IP literals, local names and odd ports."""
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return False
    if p.scheme != "https" or "." not in host or p.username or p.password:
        return False
    if port not in (None, 443):
        return False
    if host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".arpa")):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        return True


def _resolves_public(host: str) -> bool:
    """Every address the host resolves to must be a global one (no 10/8, 127/8, link-local, ...)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


# ---------- the native tool ----------

def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def cached_path(url: str) -> pathlib.Path | None:
    p = CUTS / f"{_key(url)}.png"
    return p if p.exists() and p.stat().st_size > 0 else None


def _failed(url: str) -> bool:
    return (CUTS / f"{_key(url)}.raw").exists()


def _dead(url: str) -> bool:
    """The shop refused the photo (403, not an image, too big): a browser cannot show it either."""
    p = CUTS / f"{_key(url)}.dead"
    try:
        return time.time() - p.stat().st_mtime < DEAD_TTL_S
    except OSError:
        return False


def monogram(url: str) -> str:
    """A small plate with the shop's initial, for photos nobody can load. Follows the colour scheme."""
    host = (urlsplit(_page.get(url) or url).hostname or "?").lower().removeprefix("www.")
    letter = next((c for c in host if c.isalpha()), "?").upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">
<style>.p{{fill:#E8E3D8}}.t{{fill:#5E5A52}}@media (prefers-color-scheme:dark){{.p{{fill:#22201C}}.t{{fill:#B5AFA4}}}}</style>
<rect class="p" x="0" y="0" width="120" height="120" rx="14"/>
<text class="t" x="60" y="78" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="56" font-style="italic">{letter}</text>
</svg>"""


def build() -> bool:
    """Compile cutout.m with /usr/bin/clang into .cache/cutout-bin (once, or when the source is newer)."""
    global _build_ok
    if _build_ok is not None:
        return _build_ok
    if sys.platform != "darwin" or not SRC.exists() or not pathlib.Path("/usr/bin/clang").exists():
        _build_ok = False
        return False
    if BIN.exists() and BIN.stat().st_mtime >= SRC.stat().st_mtime:
        _build_ok = True
        return True
    CACHE.mkdir(parents=True, exist_ok=True)
    frameworks = [a for f in ("Foundation", "Vision", "CoreImage", "CoreVideo", "CoreGraphics") for a in ("-framework", f)]
    try:
        done = subprocess.run(["/usr/bin/clang", "-fobjc-arc", "-O2", str(SRC), "-o", str(BIN), *frameworks],
                              capture_output=True, text=True, timeout=120)
        _build_ok = done.returncode == 0
        if not _build_ok:
            print("cutout: cutout.m did not compile, showing photos as they are\n" + done.stderr[-400:], flush=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"cutout: build failed: {exc}", flush=True)
        _build_ok = False
    return _build_ok


async def fetch_image(url: str, client: httpx.AsyncClient | None = None) -> bytes:
    """The photo bytes. Raises ValueError for anything that is not a small public image."""
    if not public_https(url):
        raise ValueError("not a public https URL")
    host = urlsplit(url).hostname or ""
    if not await asyncio.to_thread(_resolves_public, host):
        raise ValueError("host does not resolve to a public address")
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_S,
                                         headers={"User-Agent": UA, "Accept": "image/*"})
    try:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                raise ValueError(f"not an image ({ctype or 'no type'})")
            if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                raise ValueError("too large")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise ValueError("too large")
            return bytes(buf)
    finally:
        if own:
            await client.aclose()


async def _run_tool(data: bytes) -> bytes | None:
    """Photo bytes -> cropped transparent PNG, or None (exit 2 = no object, or any failure)."""
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "photo"), os.path.join(d, "cut.png")
        with open(src, "wb") as f:
            f.write(data)
        proc = await asyncio.create_subprocess_exec(str(BIN), src, out, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=CUT_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            return None
        if proc.returncode != 0:
            if proc.returncode != 2:
                print(f"cutout: exit {proc.returncode} {err.decode(errors='replace').strip()[:200]}", flush=True)
            return None
        try:
            return pathlib.Path(out).read_bytes()
        except OSError:
            return None


async def cut(url: str, client: httpx.AsyncClient | None = None) -> pathlib.Path | None:
    """Cut one photo into the disk cache. Returns the PNG path, or None (then serve the raw photo).
    Concurrent requests for the same URL share one job."""
    hit = cached_path(url)
    if hit or _failed(url) or _dead(url) or not build():
        return hit
    key = _key(url)
    if key in _inflight:
        return await asyncio.shield(_inflight[key])
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        CUTS.mkdir(parents=True, exist_ok=True)
        result: pathlib.Path | None = None
        png, data = None, None
        try:
            data = await fetch_image(url, client)
        except ValueError as exc:            # the shop said no: remember it, show a monogram
            print(f"cutout: {url[:90]}: {exc}", flush=True)
            (CUTS / f"{key}.dead").write_text(f"{url}\n{exc}")
        except (httpx.HTTPError, OSError) as exc:   # network trouble: try again next time
            print(f"cutout: {url[:90]}: {exc}", flush=True)
            fut.set_result(None)
            return None
        if data is not None:
            async with _sem:
                png = await _run_tool(data)
        if png:
            tmp = CUTS / f"{key}.tmp"
            tmp.write_bytes(png)
            tmp.replace(CUTS / f"{key}.png")
            result = CUTS / f"{key}.png"
        elif data is not None:
            (CUTS / f"{key}.raw").write_text(url)        # no object found: do not try again, serve the photo
        fut.set_result(result)
        return result
    except BaseException as exc:
        if not fut.done():
            fut.set_exception(exc)
            fut.exception()       # mark retrieved
        raise
    finally:
        _inflight.pop(key, None)


# ---------- routes ----------

@router.get("/cut")
async def get_cut(u: str = Query(..., max_length=4096, description="photo URL from a hunt")):
    """The cutout PNG (cached), or a 302 to the raw photo when it cannot be cut. 403 for unknown URLs."""
    u = resolve(u)
    if not public_https(u) or not allowed(u):
        raise HTTPException(403, "not a photo from a hunt")
    hit = cached_path(u)
    if hit is None:
        hit = await cut(u)
    if hit is None and _dead(u):
        return Response(monogram(u), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600", "X-Agora-Cut": "monogram"})
    if hit is None:
        return RedirectResponse(u, 302, headers={"Cache-Control": "public, max-age=3600",
                                                 "Referrer-Policy": "no-referrer", "X-Agora-Cut": "raw"})
    return FileResponse(hit, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable", "X-Agora-Cut": "cut"})


@router.get("/cut/known")
def known_cuts() -> JSONResponse:
    """Which allowed photo URLs already have a cutout on disk ({url: true}) and which are raw-only ({url: false}).
    Lets the front end pick plate styling before the image loads."""
    _ensure_loaded()
    out = {}
    for url in list(_allowed):
        if cached_path(url):
            out[url] = True
        elif _failed(url) or _dead(url):
            out[url] = False
    return JSONResponse(out, headers={"Cache-Control": "no-cache"})
