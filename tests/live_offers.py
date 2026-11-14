"""Rebuild Offers from a saved live hunt (tests/fixtures/round1_*.jsonl: the round-1 recordings, kept frozen for regressions) so judge can be replayed offline."""
from __future__ import annotations

import json
import pathlib

from agora.models import Need, Offer

FIX = pathlib.Path(__file__).parent / "fixtures"
_FIELDS = set(Offer.__dataclass_fields__) - {"true_cost", "haggle", "trust", "flags", "thing_id", "raw"}


def load(name: str) -> tuple[Need, list[Offer], dict]:
    need, offers, sources = None, [], {}
    for line in (FIX / f"round1_{name}.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["type"] == "need":
            need = Need(**e["data"]["need"])
        elif e["type"] == "source":
            sources[e["data"]["url"]] = e["data"]
        elif e["type"] == "offer":
            d = e["data"]["offer"]
            offers.append(Offer(**{k: v for k, v in d.items() if k in _FIELDS}))
    assert need is not None
    return need, offers, sources
