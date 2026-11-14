"""Per-domain read speed, learned across hunts. Written at Junction 2026.

`.cache/slow_domains.json` keeps, per domain: timeouts, ok reads, `ema_s` (smoothed seconds of page work
for good reads) and `last`. The hunt uses it to give each domain its own read budget, the reader uses it
to skip a paid read that would only time out when the search snippet already has the price.

A domain is SLOW when it timed out more often than it answered (at least twice), or when its good reads
take >= SLOW_EMA_S on average (seen at least twice). A slow domain gets a short leash: SLOW_READ_TIMEOUT
seconds of page work and at most SLOW_WALL_S on the wall clock (rate-limit queue included), instead of
12 s of work plus up to two minutes of queueing.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLOW_READ_TIMEOUT = 5.0      # page work for a slow domain
SLOW_WALL_S = 12.0           # wall clock for a slow domain, queue for the shared limiter included
SLOW_EMA_S = 10.0            # good reads this slow on average make the domain slow too
EMA_ALPHA = 0.4


def cache_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGORA_CACHE_DIR") or ROOT / ".cache")


class SlowDomains:
    """Learns which domains time out or crawl. Each good read forgives one timeout."""

    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or cache_dir() / "slow_domains.json"
        try:
            data = json.loads(self.path.read_text())
            self.data: dict[str, dict[str, float]] = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    def is_slow(self, domain: str) -> bool:
        d = self.data.get(domain) or {}
        t, ok = d.get("timeouts", 0), d.get("ok", 0)
        if t >= 2 and t > ok:
            return True
        return d.get("n_timed", 0) >= 2 and d.get("ema_s", 0.0) >= SLOW_EMA_S

    def timeout_for(self, domain: str, default: float) -> float:
        """Seconds of page work this domain gets."""
        return min(default, SLOW_READ_TIMEOUT) if self.is_slow(domain) else default

    def wall_for(self, domain: str) -> float | None:
        """Hard wall-clock cap (queue included) for this domain, None = no cap beyond the hunt's own."""
        return SLOW_WALL_S if self.is_slow(domain) else None

    def record(self, domain: str, timed_out: bool, seconds: float | None = None) -> None:
        d = self.data.setdefault(domain, {"timeouts": 0, "ok": 0})
        if timed_out:
            d["timeouts"] = d.get("timeouts", 0) + 1
        else:
            d["ok"] = d.get("ok", 0) + 1
            d["timeouts"] = max(0, d.get("timeouts", 0) - 1)
            if seconds is not None and seconds >= 0:
                prev = d.get("ema_s")
                d["ema_s"] = round(seconds if prev is None else (1 - EMA_ALPHA) * prev + EMA_ALPHA * seconds, 2)
                d["n_timed"] = d.get("n_timed", 0) + 1
        d["last"] = round(time.time())

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
            tmp.replace(self.path)
        except OSError:
            pass


def known_slow(domain: str) -> bool:
    """One-off check from disk (the reader uses this; the hunt keeps its own instance)."""
    return SlowDomains().is_slow(domain)


# ---------------------------------------------------------------- list-page yield
# How many priced offers a paid directory / search-page read gave, per domain, across hunts. A directory
# that lists providers without prices (myhammer, blauarbeit) is then read last instead of first.

def _yield_path() -> pathlib.Path:
    return cache_dir() / "list_yield.json"


def note_list_yield(domain: str, offers: int) -> None:
    path = _yield_path()
    try:
        data = json.loads(path.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    d = data.setdefault(domain, {"reads": 0, "offers": 0})
    d["reads"] = int(d.get("reads", 0)) + 1
    d["offers"] = int(d.get("offers", 0)) + max(0, int(offers))
    d["last"] = round(time.time())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True))
    except OSError:
        pass


def list_yield(domain: str) -> float | None:
    """Average priced offers per paid list read of this domain, None = never read."""
    try:
        d = (json.loads(_yield_path().read_text()) or {}).get(domain)
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(d, dict) or not d.get("reads"):
        return None
    return float(d.get("offers", 0)) / float(d["reads"])
