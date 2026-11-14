"""Depreciation measured from neighbouring generations, not assumed per category."""
from __future__ import annotations

import asyncio

import pytest

from agora import depreciation as dep
from agora.judge import estimate_true_cost, judge
from agora.models import Need, Offer, Thing


def test_find_model_and_siblings():
    fam, i = dep.find_model("sony a7 iii body")
    assert fam == "sony a7" and dep.FAMILIES[fam][i].name == "Sony A7 III"
    assert [m.name for m in dep.siblings(fam, i)] == ["Sony A7 II", "Sony A7 IV"]
    assert dep.find_model("Sony A7 II kit")[1] == 0
    assert dep.find_model("sony a7r iv")[0] == "sony a7r"
    assert dep.find_model("iphone 15 128gb used") == ("iphone", 2)
    assert dep.find_model("dyson v15") is None


def test_measure_from_three_generations():
    pts = [dep.point(dep.FAMILIES["sony a7"][0], [450, 480, 500, 470, 520]),     # A7 II 2014, median 480
           dep.point(dep.FAMILIES["sony a7"][1], [760, 770, 800, 740]),           # A7 III 2018, median 765
           dep.point(dep.FAMILIES["sony a7"][2], [1500, 1550, 1450])]             # A7 IV 2021, median 1500
    m = dep.measure(pts)
    assert m and len(m["pairs"]) == 2
    r1 = 1 - (480 / 765) ** (1 / 4)
    r2 = 1 - (765 / 1500) ** (1 / 3)
    assert m["rate"] == pytest.approx((r1 + r2) / 2, abs=1e-3)
    assert m["basis"].startswith("measured: Sony A7 II used sells for 37% less than Sony A7 III; launched 4 yr apart")
    assert "(5 + 4 listings)" in m["basis"] and "median of 2 generation pairs" in m["basis"]


def test_too_few_comps_means_assumed():
    pts = [dep.point(dep.FAMILIES["sony a7"][0], [480, 500]), dep.point(dep.FAMILIES["sony a7"][1], [770])]
    assert dep.measure(pts) is None


def test_judge_uses_the_measured_rate_and_says_so():
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    offers = [Offer(url=f"https://shop{i}.de/a7iii", source=f"shop{i}.de", title="Sony A7 III", price=p,
                    currency="EUR", price_eur=p, condition="used", seller="s") for i, p in enumerate((740, 770, 790))]
    measured = {"rate": 0.2, "basis": "measured: A7 II 37% less, 4 yr apart"}
    judge(need, [Thing(id="t", name="Sony A7 III", offers=offers)], depreciation=measured)
    tc = offers[1].true_cost
    assert "-20%/yr" in tc.basis and "measured: A7 II" in tc.basis
    assert tc.resale_eur == pytest.approx(770 * 0.8, abs=0.5)


def test_sibling_prices_from_snippets():
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    results = [{"url": "https://a.de/1", "title": "Sony A7 II body used - €480", "description": ""},
               {"url": "https://a.de/2", "title": "Used Sony a7 II Body", "description": "Price: 520 €"},
               {"url": "https://a.de/3", "title": "Sony A7 III used €790", "description": ""},       # wrong generation
               {"url": "https://a.de/4", "title": "Battery for Sony A7 II €25", "description": ""}]  # accessory

    async def search(q):
        return results

    prices = asyncio.run(dep.sibling_prices(dep.FAMILIES["sony a7"][0], need, search))
    assert sorted(prices) == [480.0, 520.0]


def test_hunt_emits_measured_depreciation_event():
    from test_hunt_race import replay as fixture_reader
    from agora.hunt import SlowDomains, hunt
    disc, read = fixture_reader("sony-a7-iii-body")
    shelf = {"sony a7 ii body used": [480, 470, 500, 455], "sony a7 iv body used": [1500, 1450, 1550]}

    async def search(q):
        return [{"url": f"https://x.de/{i}", "title": f"Used {q.split(' body')[0].title()} body €{p}",
                 "description": ""} for i, p in enumerate(shelf[q])]

    async def go():
        return [e async for e in hunt("sony a7 iii body", discover=disc, read=read, persist=False, lookalikes=False,
                                      slow_domains=SlowDomains(), sibling_search=search, provisional_after=None)]
    events = asyncio.run(go())
    lane = next(e for e in events if e.type == "lane" and e.data["lane"] == "sibling")
    assert lane.data["queries"] == ["sony a7 ii body used", "sony a7 iv body used"]
    d = next(e for e in events if e.type == "depreciation").data
    assert d["source"] == "measured" and [p["model"] for p in d["points"]] == ["Sony A7 II", "Sony A7 III", "Sony A7 IV"]
    assert 0.03 <= d["rate"] <= 0.4 and d["basis"].startswith("measured:")
    tcs = [e.data["true_cost"] for e in events if e.type == "truecost" and e.data["true_cost"]]
    assert tcs and all("measured:" in tc["basis"] for tc in tcs)
    assert [e.type for e in events].index("depreciation") < [e.type for e in events].index("truecost")
