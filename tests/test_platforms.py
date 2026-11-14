"""ITEM + PLATFORM needs (owner, 15 Nov: 'gta 6 ps5' kept PS5 consoles and threw the game discs out)."""
from __future__ import annotations

import pytest

from agora import discover as D
from agora import intent as I
from agora import judge as J
from agora import need as N
from agora import platforms as P
from agora import resolve as R
from agora.models import Offer


def parsed(q: str):
    n = N.parse_need_rules(q)
    N.categorize(n)
    return n


def row(title: str, price: float = 50, cond: str = "used", dom: str = "tori.fi", i: int = 1) -> Offer:
    return Offer(url=f"https://www.{dom}/item/{i}", source=dom, title=title, price=price, currency="EUR",
                 price_eur=price, condition=cond)


def why(n, title: str, price: float = 50) -> str | None:
    return R.explain(n, row(title, price))[1]


# ---------------------------------------------------------------- need

@pytest.mark.parametrize("q,thing,plat,kind", [
    ("gta 6 ps5", "gta 6", "ps5", "game"),
    ("fifa 25 ps5", "fifa 25", "ps5", "game"),
    ("mario kart switch", "mario kart", "switch", "game"),
    ("iphone 15 case", "case", "iphone 15", "case"),
    ("macbook charger", "charger", "macbook", "charger"),
    ("sony fe 50mm lens", "50mm lens", "sony fe", "lens"),
])
def test_need_splits_item_and_platform(q, thing, plat, kind):
    n = parsed(q)
    assert (n.thing, n.for_platform, n.item_kind) == (thing, plat, kind)
    assert N.search_words(n) == q
    assert "refurbished" not in n.conditions


@pytest.mark.parametrize("q", ["ps5 console", "ps5", "ps5 slim", "ps5 disc", "nintendo switch oled", "iphone 15 pro 256gb",
                               "ps5 gta 6 bundle", "ps5 no gta bundle", "sony a7 iii", "ps5 controller"])
def test_the_device_itself_is_not_split(q):
    n = parsed(q)
    assert n.for_platform is None and n.item_kind is None


def test_format_words_are_wishes():
    assert parsed("gta 6 ps5 levy").prefer == ["disc"]
    n = parsed("gta 6 ps5 digital code")
    assert n.thing == "gta 6" and n.prefer == ["digital"]


def test_game_need_category_is_games_not_consoles():
    cat = parsed("gta 6 ps5").category
    assert cat and "game" in cat["label"].lower() and "console" not in cat["label"].lower()
    assert parsed("iphone 15 case").category["label"] == "Mobile Phone Cases"
    assert parsed("sony fe 50mm lens").category["label"] == "Camera Lenses"
    assert not R.is_generic(parsed("iphone 15 case"))


# ---------------------------------------------------------------- resolve

def test_gta_6_ps5_keeps_the_game_and_drops_consoles():
    n = parsed("gta 6 ps5")
    for t in ("GTA 6 PS5 nieuw in de seal", "Playstation 5 Grand Theft Auto VI", "PS5 GTA 6 - Grand Theft Auto VI",
              "Grand Theft Auto 6voor PS5 - Downloadcode in box sealed", "Grand Theft Auto VI (PS5)", "GTA 6 PS4/PS5",
              "GTA 6 - GRAND THEFT AUTO VI"):
        assert why(n, t) is None, t
    assert "console" in why(n, "PlayStation 5 Disc Versie", 450)
    assert "console" in why(n, "Ps5", 400)
    assert "console" in why(n, "PlayStation 5 GTA 6 Ready mit Controller und Spielen", 520)
    assert "console" in why(n, "PS5 Slim + GTA 6 bundle", 550)
    assert "console" in why(n, "Verkaufe meine Ps5 mit GTA6", 480)
    assert "another platform (Xbox Series X|S)" in why(n, "Grand Theft Auto VI Xbox Series X")
    assert "another platform (PS4)" in why(n, "GTA 6 PS4")
    assert "another game (GTA 5)" in why(n, "Grand Theft Auto V PS5")
    assert "merch" in why(n, "Playstation 5 Kontrollholder GTA 6 Design", 15)
    assert "merch" in why(n, "GTA VI Gtand Theft Auto 6 Aufsteller XBOX PS5", 10)
    assert "service or rental" in why(n, "PS5 Reinigung + Flüssigmetall GTA 6", 60)
    assert "account" in why(n, "PS5 account + gta6", 100)


def test_resolve_groups_the_game_as_one_thing():
    n = parsed("gta 6 ps5")
    offs = [row("GTA 6 PS5", 55, i=1), row("Grand Theft Auto VI (PS5)", 79, "new", "gigantti.fi", 2),
            row("PlayStation 5 Disc Versie", 450, i=3)]
    things = R.resolve(n, offs)
    assert [(t.name, len(t.offers)) for t in things] == [("GTA 6 for PS5", 2)]


def test_fifa_25_ps5():
    n = parsed("fifa 25 ps5")
    assert why(n, "EA Sports FC 25 PS5") is None
    assert why(n, "FIFA 25 PS5 peli") is None
    assert "another game (FC 24)" in why(n, "EA FC 24 PS5")
    assert "another platform" in why(n, "FC 25 Xbox Series X")
    assert "console" in why(n, "PS5 Pro 2TB", 700)


def test_mario_kart_switch():
    n = parsed("mario kart switch")
    assert why(n, "Mario Kart 8 Deluxe Nintendo Switch") is None
    assert "console" in why(n, "Nintendo Switch OLED + Mario Kart 8", 280)
    assert "not the game asked" in why(n, "Super Mario Odyssey Switch")
    assert "another platform (Nintendo Switch 2)" in why(n, "Mario Kart World Switch 2")


def test_iphone_15_case_cases_are_the_item_phones_are_not():
    n = parsed("iphone 15 case")
    assert why(n, "Apple iPhone 15 silikonikuori", 25) is None
    assert why(n, "Spigen case iPhone 13/14/15", 15) is None
    assert why(n, "Clear case MagSafe", 15) is None              # no device named: kept
    assert "phone itself" in why(n, "Apple iPhone 15 128GB", 600)
    assert "phone itself" in why(n, "iPhone 15 128GB + kuori", 600)
    assert "another model (iPhone 15 Pro Max)" in why(n, "iPhone 15 Pro Max case", 20)
    assert "another device (Samsung Galaxy)" in why(n, "Samsung Galaxy S24 case", 20)


def test_macbook_charger():
    n = parsed("macbook charger")
    assert why(n, "Apple 67W USB-C Power Adapter MacBook Pro", 60) is None
    assert why(n, "MacBook Air laturi 30W", 30) is None
    assert "laptop itself" in why(n, "MacBook Air M2 2022 8/256", 800)


def test_sony_fe_50mm_lens():
    n = parsed("sony fe 50mm lens")
    assert why(n, "Sony FE 50mm f/1.8", 200) is None
    assert why(n, "Sigma 50mm f/1.4 DG DN Art Sony E", 600) is None
    assert "another mount (Canon RF)" in why(n, "Canon RF 50mm f/1.8 STM", 180)
    assert "another focal length (35mm)" in why(n, "Sony FE 35mm f/1.8", 500)
    assert "camera" in why(n, "Sony A7 III runko", 1100)


def test_ps5_console_is_still_the_console():
    n = parsed("ps5 console")
    assert why(n, "PlayStation 5 Slim Disc 1TB", 450) is None
    assert "game" in why(n, "GTA 6 PS5", 70)


# ---------------------------------------------------------------- judge

def test_game_priced_as_a_game_not_a_console():
    n = parsed("gta 6 ps5")
    rows = [("GTA 6 PS5 nieuw in de seal", 65, "used", "marktplaats.nl"), ("Grand Theft Auto VI (PS5)", 79.99, "new",
            "verkkokauppa.com"), ("PS5 GTA 6 - Grand Theft Auto VI", 55, "used", "tori.fi"),
            ("GTA6 ps5 levy", 50, "used", "tori.fi"), ("Playstation 5 Grand Theft Auto VI", 60, "used", "kleinanzeigen.de"),
            ("GTA 6 PS5", 45, "used", "tori.fi"), ("Grand Theft Auto VI PS5", 74.9, "new", "gigantti.fi"),
            ("PlayStation 5 Disc Versie", 450, "used", "marktplaats.nl")]
    offs = [row(t, p, c, d, i) for i, (t, p, c, d) in enumerate(rows)]
    v = J.judge(n, R.resolve(n, offs))
    assert v.headline.startswith("€45")
    kept = [o for o in offs if o.thing_id]
    assert len(kept) == 7 and not any(o.raw.get("ref_suspect") for o in kept)
    assert J.need_category(n, "GTA 6 PS5").name == "game"


def test_game_reference_never_a_console_price():
    ref = J.reference_price([row(f"PS5 GTA 6 {i}", 480 + i, i=i) for i in range(6)], J.GAME_CATEGORY)
    assert ref is not None and ref.new_eur == J.GAME_NEW_EUR
    assert J.reference_price([], J.GAME_CATEGORY).new_eur == J.GAME_NEW_EUR


# ---------------------------------------------------------------- discover

def test_game_queries_carry_the_platform_and_the_local_word(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    n = parsed("gta 6 ps5")
    new = D.lean_plan(n, "new", 10)
    used = D.lean_plan(n, "used", 10)
    assert new[0][0].startswith("gta 6 ps5 ")
    assert any(q.startswith("gta 6 ps5 peli") for q, _ in new)
    assert used[0][0].startswith("gta 6 ps5 levy")
    assert D.queries_for(parsed("iphone 15 case"), "new", 1)[0].startswith("iphone 15 case")


def test_direct_marketplace_search_is_the_game_and_platform(monkeypatch):
    monkeypatch.setenv("AGORA_COUNTRY", "fi")
    monkeypatch.setenv("AGORA_DIRECT", "1")
    plan = D.plan_direct(parsed("gta 6 ps5"), ["new", "used"], 10, 3)
    assert plan and all(d.query == "gta 6 ps5" for ds in plan.values() for d in ds)


# ---------------------------------------------------------------- intent

def test_intent_gta_6_ps5_asks_game_bundle_or_code():
    r = I.interpret("gta 6 ps5", "fi", "en", llm=False)
    top = r["intents"][0]
    assert not r["dominant"] and r["ask"] and top["id"] == "p:game" and top["as_typed"]
    assert top["label"] == "GTA 6 game for PS5"
    assert r["question"] == "GTA 6 for PS5: which do you mean?"
    assert [o["label"] for o in r["options"]] == ["Just the game (disc)", "A PS5 with GTA 6 bundled", "A digital code"]
    assert [o["intent_id"] for o in r["options"]] == ["p:game", "p:bundle", "p:digital"]
    assert r["as_typed"]["label"] == "Search exactly ‘gta 6 ps5’"
    n = parsed(r["options"][0]["hunt"]["q"])
    assert (n.thing, n.for_platform, n.item_kind) == ("gta 6", "ps5", "game")
    assert parsed(r["options"][2]["hunt"]["q"]).prefer == ["digital"]
    # a disc asked in the words: clearly the game
    assert not I.interpret("gta 6 ps5 levy", "fi", "en", llm=False)["ask"]


def test_intent_ps5_gta_asks_game_or_bundle():
    r = I.interpret("ps5 gta", "fi", "en", llm=False)
    assert not r["dominant"] and r["ask"]
    assert r["question"] == "GTA for PS5: which do you mean?"
    labels = [o["label"] for o in r["options"]]
    assert labels[:2] == ["Just the game (disc)", "A PS5 with GTA bundled"] and "A digital code" in labels
    bundle = next(o for o in r["options"] if o["id"] == "p:bundle")
    assert bundle["intent_id"] == "p:bundle" and bundle["hunt"]["q"] == "ps5 gta bundle" and bundle["hint"]
    assert parsed(bundle["hunt"]["q"]).for_platform is None             # the bundle hunt is the console
    game = next(o for o in r["options"] if o["id"] == "p:game")
    assert parsed(game["hunt"]["q"]).item_kind == "game"
    assert I.interpret("ps5 gta", "fi", "fi", llm=False)["question"] == "GTA (PS5): mitä tarkoitat?"
    assert I.plan("p:game", "ps5 gta") is None


def test_intent_ask_for_vague_words_and_not_for_clear_ones():
    lunch = I.interpret("lunch", "fi", "en", llm=False)
    assert lunch["ask"] and lunch["question"] == "What do you mean by “lunch”?"
    assert [o["intent_id"] for o in lunch["options"]][0] == "c:lunch.places"
    assert all(o["label"] and "hunt" in o for o in lunch["options"])
    for q in ("phone", "insurance"):
        assert I.interpret(q, "fi", "en", llm=False)["ask"]
    for q in ("ps5", "iphone 15 case", "sony a7 iii"):
        r = I.interpret(q, "fi", "en", llm=False)
        assert r["ask"] is False and r["question"] is None and r["options"] == [] and r["as_typed"]["label"]


def test_intent_rent_or_buy_only_when_it_matters():
    r = I.interpret("rent a camera", "fi", "en", llm=False)
    assert r["ask"] and r["question"] == "Rent it or buy it?"
    assert [o["id"] for o in r["options"]] == ["rent", "buy"]
    assert r["options"][1]["hunt"]["q"] == "a camera"
    assert I.interpret("rent a car", "fi", "en", llm=False)["question"] != "Rent it or buy it?"   # its own meanings


def test_platform_helpers():
    assert P.game_norm("Grand Theft Auto VI") == "gta 6"
    assert P.game_match("gta 6", "GTA6 ps5") == (True, None)
    assert P.game_match("gta 6", "Grand Theft Auto V PS5") == (False, "GTA 5")
    assert P.device_mentions("Tech21 iPhone 13/14/15", "iphone") == [("13", None), ("14", None), ("15", None)]
    assert P.device_title("galaxy s24 ultra") == "Samsung Galaxy S24 Ultra"
    assert P.split("ps5 gta").ambiguous and not P.split("gta 6 ps5").ambiguous
