"""agora.relevance: one Gemini Decisions call per hunt, mocked; fallback = "unsure" = the rules decide."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agora import relevance as R
from agora.models import Need, Offer
from agora.resolve import explain, resolve


def need(thing: str = "nintendo switch oled", **kw) -> Need:
    return Need(raw=f"{thing} in Helsinki under 300", thing=thing, where="Helsinki", budget=300, **kw)


def offer(title: str, price: float = 250, n: int = 1, cond: str = "used") -> Offer:
    return Offer(url=f"https://tori.fi/item/{n}?seller=matti", source="tori.fi", title=title, price=price,
                 currency="EUR", price_eur=price, condition=cond, seller="Matti Meikäläinen")  # type: ignore[arg-type]


OFFERS = [offer("Nintendo Switch OLED white, boxed", 260, 1),
          offer("Nintendo Switch OLED carrying case", 15, 2),
          offer("OSTETAAN Nintendo Switch OLED", 200, 3)]


def mock(answers: dict, status: int = 200, seen: list | None = None, delay: float = 0.0):
    async def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if delay:
            await asyncio.sleep(delay)
        return httpx.Response(status, json={"answers": answers, "usage": {"total_input_tokens": 300}})
    return httpx.MockTransport(handler)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("AGORA_OFFLINE", raising=False)
    monkeypatch.delenv("AGORA_RELEVANCE_LLM", raising=False)
    R.clear_cache()
    yield monkeypatch
    monkeypatch.setattr(R, "_transport", None)
    R.clear_cache()


ANSWERS = {"l0": {"type": "choice", "choice": "match", "confidence": 0.95},
           "l1": {"type": "choice", "choice": "accessory", "confidence": 0.97},
           "l2": {"type": "choice", "choice": "not_an_offer", "confidence": 0.9}}


def test_one_batched_call_and_verdicts(gemini) -> None:
    seen: list[httpx.Request] = []
    gemini.setattr(R, "_transport", mock(ANSWERS, seen=seen))
    v = asyncio.run(R.classify(need(), OFFERS))
    assert [x["match"] for x in v] == ["yes", "no", "no"]
    assert "accessory" in v[1]["reason"] and v[1]["confidence"] == 0.97
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == R.URL and req.headers["x-goog-api-key"] == "test-key"
    body = json.loads(req.content)
    assert body["model"] == "gemini-decision-1"
    assert set(body["questions"]) == {"l0", "l1", "l2"}
    assert body["questions"]["l0"]["type"] == "choice" and "match" in body["questions"]["l0"]["criteria"]


def test_no_personal_data_is_sent(gemini) -> None:
    seen: list[httpx.Request] = []
    gemini.setattr(R, "_transport", mock(ANSWERS, seen=seen))
    asyncio.run(R.classify(need(), OFFERS))
    sent = seen[0].content.decode()
    for private in ("Helsinki", "300", "Matti", "seller", "https://tori.fi/item"):
        assert private not in sent
    assert "Nintendo Switch OLED carrying case" in sent and "tori.fi" in sent and "260 EUR" in sent


def test_cache_per_need_and_title(gemini) -> None:
    seen: list[httpx.Request] = []
    gemini.setattr(R, "_transport", mock(ANSWERS, seen=seen))
    asyncio.run(R.classify(need(), OFFERS))
    again = asyncio.run(R.classify(need(), [offer("nintendo switch OLED carrying case", 12, 9)]))
    assert len(seen) == 1 and again[0]["match"] == "no" and again[0]["via"] == "cache"


def test_low_confidence_no_is_unsure(gemini) -> None:
    gemini.setattr(R, "_transport", mock({"l0": {"type": "choice", "choice": "other_model", "confidence": 0.4}}))
    assert asyncio.run(R.classify(need(), OFFERS[:1]))[0]["match"] == "unsure"


@pytest.mark.parametrize("transport", [
    lambda: mock({}, status=500),
    lambda: mock(ANSWERS, delay=1.0),
    lambda: httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
])
def test_failures_fall_back_to_unsure_fast(gemini, transport) -> None:
    gemini.setattr(R, "_transport", transport())
    import time
    t = time.monotonic()
    v = asyncio.run(R.classify(need(), OFFERS, timeout=0.2))
    assert time.monotonic() - t < 0.8
    assert all(x["match"] == "unsure" and x["via"] == "fallback" for x in v)
    assert R._cache == {}


def test_no_key_means_fallback_without_network(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(R, "_key", lambda: None)
    monkeypatch.setattr(R, "_transport", httpx.MockTransport(lambda r: pytest.fail("no call without a key")))
    v = asyncio.run(R.classify(need(), OFFERS))
    assert all(x["match"] == "unsure" for x in v) and not R.enabled()


def test_switch_off(gemini) -> None:
    gemini.setenv("AGORA_RELEVANCE_LLM", "0")
    assert not R.enabled()


def test_resolve_drops_vetoed_offers(gemini) -> None:
    gemini.setattr(R, "_transport", mock({"l0": {"type": "choice", "choice": "match", "confidence": 0.9},
                                          "l1": {"type": "choice", "choice": "other_model", "confidence": 0.9}}))
    n = need()
    offs = [offer("Nintendo Switch OLED Model Console, White", 300, 1, "new"),
            offer("Nintendo Switch OLED Model Console, Neon", 290, 2, "new")]
    assert sum(len(t.offers) for t in resolve(n, offs)) == 2   # rules keep both
    asyncio.run(R.prefetch(n, offs))
    kept = [o for t in resolve(n, offs) for o in t.offers]
    assert kept == [offs[0]]
    assert explain(n, offs[1]) == (0.0, "model check: a different model or variant (90% sure)")
    assert explain(n, offs[0])[1] is None


def test_unsure_leaves_rules_alone(monkeypatch) -> None:
    monkeypatch.setattr(R, "_key", lambda: None)
    n = need()
    offs = [offer("Nintendo Switch OLED Model Console, White", 300, 1, "new")]
    asyncio.run(R.prefetch(n, offs))
    assert offs[0].raw["relevance_llm"]["match"] == "unsure"
    assert [o for t in resolve(n, offs) for o in t.offers] == offs


def test_prefetch_sends_only_rule_kept_offers(gemini) -> None:
    seen: list[httpx.Request] = []
    gemini.setattr(R, "_transport", mock({"l0": {"type": "choice", "choice": "match", "confidence": 0.9}}, seen=seen))
    offs = [offer("Nintendo Switch OLED Model Console, White", 300, 1, "new"),
            offer("Joy-Con pair for Nintendo Switch", 60, 2, "new")]
    asyncio.run(R.prefetch(need(), offs))
    assert "Joy-Con" not in seen[0].content.decode() and "relevance_llm" not in offs[1].raw
