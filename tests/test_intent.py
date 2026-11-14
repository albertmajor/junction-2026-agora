"""Intent interpretation (owner, 14 Nov: typed "lunch" -> €4 lunch boxes from tori.fi, "not even services";
"School catering" -> "Nothing here yet."). Offline: rules + the taxonomy only, no network."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from agora import api, intent
from agora.models import Need

WEB = pathlib.Path(api.__file__).resolve().parent / "web"


def top(q: str, **kw):
    r = intent.interpret(q, "fi", "en", **kw)
    assert 1 <= len(r["intents"]) <= intent.MAX_INTENTS
    return r, r["intents"][0]


def test_lunch_means_a_place_to_eat_not_a_lunch_box():
    r, t = top("lunch")
    assert t["id"] == "c:lunch.places" and t["kind"] == "service"
    assert "lounaat.info" in t["domains"]
    assert any("lounas" in q for q in t["queries"]["fi"])
    assert t["hunt"]["cat"] and not t["as_typed"]
    ids = [i["id"] for i in r["intents"]]
    assert "c:lunch.delivery" in ids and "c:lunch.box" in ids
    assert ids.index("c:lunch.box") > ids.index("c:lunch.delivery")      # the box is the least likely meaning
    delivery = next(i for i in r["intents"] if i["id"] == "c:lunch.delivery")
    assert "wolt.com" in delivery["domains"]
    assert not r["dominant"]                       # chips: the other meanings are one tap away
    assert abs(sum(i["confidence"] for i in r["intents"]) - 1) < 0.01


@pytest.mark.parametrize("q", ["lounas", "Lounas", "mittagstisch", "lunch?"])
def test_lunch_in_other_languages(q):
    assert top(q)[1]["id"] == "c:lunch.places"


def test_labels_follow_the_language_and_the_place():
    assert intent.interpret("lunch", "fi", "fi")["intents"][0]["label"].startswith("Lounaspaikat")
    r = intent.interpret("lunch", "fi", "en", near="Helsinki")
    assert r["intents"][0]["label"] == "Lunch places near you in Helsinki"
    r, t = top("haircut helsinki")
    assert r["place"] == "Helsinki" and t["label"].endswith("in Helsinki") and t["kind"] == "service"
    assert r["dominant"]                           # a place makes the local service clearly it
    assert intent.interpret("flight to berlin", "fi", "en")["intents"][0]["label"] == "Flights to Berlin"


def test_school_catering_plans_providers_not_marketplace_products():
    r, t = top("school catering")
    assert t["id"] == "c:school-catering.providers" and t["kind"] == "service"
    assert t["hunt"]["cat"] == "cpv:55524"
    assert "kouluruokailu palvelu" in t["queries"]["fi"] and any("ateriapalvelu" in q for q in t["queries"]["fi"])
    assert "tori.fi" not in t["domains"]


def test_an_empty_category_page_gets_next_steps():
    r = intent.interpret("School catering", "fi", "en", "cpv:55524")
    labels = [i["label"] for i in r["intents"]]
    assert labels[0].startswith("School catering companies")
    assert any(lab.startswith("Catering companies") for lab in labels)
    kinds = {n["kind"] for n in r["next"]}
    assert "providers" in kinds and "broader" in kinds          # never a dead end
    prov = next(n for n in r["next"] if n["kind"] == "providers")
    assert prov["hunt"]["cat"] == "cpv:55524"


def test_category_siblings_are_the_same_sort_of_thing():
    r = intent.interpret("Catering", "fi", "en", "events-leisure.catering")
    assert not any("Zoo" in i["label"] or "Farm" in i["label"] for i in r["intents"])
    assert not any("checkatrade" in d for i in r["intents"] for d in i["domains"])   # British-only site


@pytest.mark.parametrize("q,want", [
    ("catering", "c:catering.event"), ("cleaning", "c:cleaning.home"), ("phone", "c:phone.device"),
    ("gift for mom", "c:gift.ideas"), ("birthday", "c:birthday.gift"), ("car", "c:car.buy"),
    ("insurance", "c:insurance.home"), ("tv", "c:tv.set"), ("coffee", "c:coffee.beans"), ("sofa", "c:sofa.sofa"),
    ("moving", "c:moving.movers"), ("internet", "c:internet.broadband"), ("kitchen", "c:kitchen.renovation"),
    ("bike", "c:bike.bike"), ("shoes", "c:shoes.shoes"), ("wedding", "c:wedding.venue"),
    ("siivous", "c:cleaning.home"), ("muutto", "c:moving.movers"), ("fahrrad", "c:bike.bike"),
])
def test_common_vague_words(q, want):
    r, t = top(q)
    assert t["id"] == want
    assert len(r["intents"]) >= 2


def test_gift_for_mom_keeps_the_recipient():
    r, t = top("gift for mom")
    assert t["label"] == "Gift ideas for mom" and "for mom" in t["hunt"]["q"]


def test_specific_things_stay_as_typed():
    r, t = top("ps5")
    assert r["dominant"] and t["as_typed"] and t["hunt"] == {"q": "ps5", "cat": None, "intent": t["id"]}
    r, t = top("sofa")
    assert r["dominant"] and t["as_typed"]
    # a concept word inside a long specific request is not vague
    r = intent.interpret("lunch box with three compartments and a spoon", "fi", "en")
    assert r["concept"] is None


def test_dominant_needs_a_clear_lead():
    assert not intent.interpret("lunch", "fi", "en")["dominant"]
    assert not intent.interpret("insurance", "fi", "en")["dominant"]
    assert intent.interpret("school catering", "fi", "en")["dominant"]


def test_domains_never_cross_borders():
    for q in ("cleaning", "sofa", "catering", "wedding"):
        for it in intent.interpret(q, "fi", "en")["intents"]:
            for d in it["domains"]:
                assert intent.dom_ok(d, "fi"), (q, d)


def test_plan_and_apply_fit_the_need():
    from agora import need as need_mod
    n = need_mod.parse_need_rules("lunch")
    ev = intent.apply(n, "c:lunch.places", country="fi")
    assert ev and ev["intent"]["id"] == "c:lunch.places"
    assert n.kind == "service" and n.conditions == ["service"]
    assert n.category["labels"]["fi"] == "lounas"
    assert {"domain": "lounaat.info", "lane": "service", "from": "nace:56101"} in n.category["domains"]
    assert n.thing == "lunch restaurant"
    n2 = need_mod.parse_need_rules("haircut helsinki")
    intent.apply(n2, "c:haircut.salon")
    assert n2.where == "Helsinki" and n2.thing == "haircut"
    assert intent.apply(Need(raw="x", thing="x"), "c:nope.nothing") is None
    n3 = need_mod.parse_need_rules("lunch")
    assert intent.apply(n3, "c:lunch.box")["kind"] == "product" and n3.kind == "product"


def test_gemini_answers_are_parsed_strictly():
    good = {"intents": [{"label": "Lunch buffet", "kind": "service", "search": "lunch buffet", "confidence": 0.7,
                         "where": ["restaurants"]},
                        {"label": "<script>", "kind": "weapon", "search": "x", "confidence": 2}]}
    out = intent.parse_gemini(good)
    assert out and len(out) == 1 and out[0]["label"] == "Lunch buffet"
    assert intent.parse_gemini({"intents": "nope"}) is None and intent.parse_gemini([1]) is None


def test_no_gemini_offline(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    called = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: called.append(1))
    intent.interpret("lunch", "fi", "en")
    assert not called                          # AGORA_OFFLINE=1 (conftest): never a network call


def test_gemini_merge(monkeypatch):
    monkeypatch.setattr(intent, "_gemini", lambda q, cc, timeout=2.0: [
        {"label": "Lunch buffet", "kind": "service", "search": "lunch buffet restaurant", "where": [], "confidence": 0.9}])
    r = intent.interpret("lunch", "fi", "en")
    assert len(r["intents"]) <= intent.MAX_INTENTS
    assert r["intents"][0]["id"].startswith("c:lunch")       # the curated likeliest meaning keeps the lead


def test_endpoint():
    c = TestClient(api.app)
    j = c.get("/api/intent", params={"q": "lunch", "country": "fi", "lang": "en"}).json()
    assert j["intents"][0]["label"] == "Lunch places near you" and j["dominant"] is False
    assert {"id", "label", "kind", "node", "hunt", "queries", "lanes", "domains", "why", "confidence"} <= set(j["intents"][0])
    j = c.get("/api/intent", params={"q": "School catering", "cat": "cpv:55524"}).json()
    assert j["category"]["id"] == "cpv:55524" and j["next"]
    assert c.get("/api/intent", params={"q": "x"}).json()["intents"] == []
    assert "GET /api/intent?q=&country=&lang=&cat=&near=" in c.get("/api").json()["endpoints"]


def test_viewer_wires_the_row():
    html = (WEB / "index.html").read_text()
    assert 'id="intents"' in html and "/web/css/intent.css" in html
    main = (WEB / "js" / "main.js").read_text()
    assert "load('intent')" in main and "I.rewrites(plan)" in main and "intent: params.get('intent')" in main
    js = (WEB / "js" / "intent.js").read_text()
    assert "/api/intent" in js and "We think you mean:" in js
    stream = (WEB / "js" / "stream.js").read_text()
    assert "p.set('intent', plan.intent)" in stream
    cp = (WEB / "js" / "catpage.js").read_text()
    assert "intent.nextSteps(d.id, d.label)" in cp
