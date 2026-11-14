import pytest

from agora import need as need_mod
from agora.need import parse_budget, parse_need


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.mark.parametrize("text,amount,cur", [
    ("under €900", 900, "EUR"),
    ("<900e", 900, "EUR"),
    ("max 900", 900, None),
    ("up to $1,200", 1200, "USD"),
    ("budget 1.2k eur", 1200, "EUR"),
    ("dyson v15 900€ max", 900, "EUR"),
    ("alle 1 299 €", 1299, "EUR"),
    ("below £450", 450, "GBP"),
    ("enintään 300 euroa", 300, None),
])
def test_budget(text, amount, cur):
    a, c, _ = parse_budget(text)
    assert a == amount
    if cur:
        assert c == cur


@pytest.mark.parametrize("text", ["iPhone 15 Pro Max 256GB", "sony a7 iii", "samsung 55\" tv", "rtx 4090 24gb"])
def test_no_fake_budget(text):
    assert parse_budget(text)[0] is None


def test_headline_query():
    n = parse_need("used sony a7 iii under €900 near Helsinki")
    assert (n.thing, n.budget, n.currency, n.where, n.conditions, n.kind) == (
        "sony a7 iii", 900, "EUR", "Helsinki", ["used"], "product")


@pytest.mark.parametrize("text,cond", [
    ("käytetty iphone 13", ["used"]),
    ("gebrauchte Sony A7 III", ["used"]),
    ("refurbished or used pixel 8", ["refurbished", "used"]),
    ("brand new macbook air m3", ["new"]),
    ("rent a cargo bike in Berlin", ["rental"]),
    ("sony a7 iii", ["new", "refurbished", "used"]),
])
def test_conditions(text, cond):
    assert parse_need(text).conditions == cond


def test_new_york_is_not_new():
    n = parse_need("used camera in New York")
    assert n.conditions == ["used"] and n.where == "New York"


@pytest.mark.parametrize("text,thing,where", [
    ("home cleaning in Espoo", "home cleaning", "Espoo"),
    ("plumber helsingissä", "plumbing", "Helsinki"),
    ("haircut near Kamppi", "haircut", "Kamppi"),
])
def test_services(text, thing, where):
    n = parse_need(text)
    assert n.kind == "service" and n.conditions == ["service"]
    assert n.thing == thing and n.where == where


def test_must_have():
    n = parse_need("Sony a7 iii with 28-70 lens budget 1.2k eur")
    assert n.thing == "sony a7 iii" and n.budget == 1200 and n.must_have == ["28-70 lens"]


def test_gemini_fills_gaps_but_cannot_invent_budget(monkeypatch):
    monkeypatch.setattr(need_mod, "_gemini", lambda text, timeout=6.0: {
        "thing": "sony a7 iii", "kind": "product", "budget": 5000, "currency": "USD",
        "where": "Finland", "conditions": ["used"], "must_have": ["low shutter count"]})
    n = parse_need("that sony full frame a7 3 thing, second generation is too old")
    assert n.thing == "sony a7 iii"
    assert n.budget is None                 # 5000 is nowhere in the text
    assert n.where == "Finland" and "low shutter count" in n.must_have


def test_gemini_failure_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(need_mod.httpx, "post", boom)
    n = parse_need("used sony a7 iii under 900e")
    assert n.thing == "sony a7 iii" and n.budget == 900
