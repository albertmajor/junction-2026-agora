"""Cut every offer photo in the recorded hunts (tests/fixtures/live_*.jsonl) into .cache/cuts/.

Image fetches only: zero Context.dev calls. Run once before a demo so /cut answers from disk:
    .venv/bin/python scripts/precut_fixtures.py [--retry]   (--retry forgets earlier failures)
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from agora import cutout  # noqa: E402


async def main(retry: bool = False) -> int:
    urls = sorted(cutout._fixture_images())
    if not cutout.build():
        print("cutout tool unavailable (needs macOS 14+ and /usr/bin/clang): nothing to do")
        return 1
    if retry:
        for u in urls:
            for ext in (".raw", ".dead"):
                (cutout.CUTS / f"{cutout._key(u)}{ext}").unlink(missing_ok=True)
    async with httpx.AsyncClient(follow_redirects=False, timeout=cutout.TIMEOUT_S,
                                 headers={"User-Agent": cutout.UA, "Accept": "image/*"}) as client:
        async def one(u: str) -> tuple[str, str]:
            if cutout.cached_path(u):
                return u, "cached"
            p = await cutout.cut(u, client)
            return u, "cut" if p else ("monogram (shop refused the photo)" if cutout._dead(u) else "raw (no cutout)")
        results = await asyncio.gather(*(one(u) for u in urls))
    for u, how in results:
        print(f"{how:16} {u[:110]}")
    n = sum(1 for _, h in results if h in ("cut", "cached"))
    print(f"\n{n}/{len(urls)} photos have a cutout in {cutout.CUTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--retry" in sys.argv)))
