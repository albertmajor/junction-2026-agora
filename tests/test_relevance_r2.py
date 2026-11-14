"""Round-2 judges' relevance / pricing / verdict defects, as offline regressions.

Titles, prices and sites are copied from the live streams the judges read (eval r2, 14 Nov). Each test names the
defect it pins down; every fix is a rule per listing (never a blocked site).
"""
from __future__ import annotations

import pytest

from agora import judge as J
from agora import resolve as R
from agora.models import Need, Offer

ROAD_CAT = {"id": "sp:sg-4-4-3-11", "label": "Road Bikes", "source": "tree", "confidence": 1.0,
            "labels": {"en": "Road Bikes", "fi": "Maantiepyörät", "de": "Rennräder"}}
ROAD_TYPED = {"id": "sp:sg-4-4-3-11", "label": "Road Bikes", "source": "classified", "confidence": 0.9}
PHONE_CAT = {"id": "sp:el-4-8-5", "label": "Mobile & Smart Phones", "source": "tree", "confidence": 1.0}
PHONE_TYPED = {"id": "sp:el-4-8-5", "label": "Mobile & Smart Phones", "source": "classified", "confidence": 0.9}
CONSOLE_CAT = {"id": "sp:el-19", "label": "Video Game Consoles", "source": "classified", "confidence": 0.9}
STROLLER_CAT = {"id": "sp:bt-6-3", "label": "Baby Strollers", "source": "classified", "confidence": 0.9}
COFFEE_CAT = {"id": "m:power:kahvi-ja-tee-ac1e64", "label": "Coffee & Tees", "source": "classified", "confidence": 0.8}
CYCLING_CAT = {"id": "sp:sg-4-4", "label": "Cycling", "source": "classified", "confidence": 0.8}
SOFA_CAT = {"id": "sp:fr-22", "label": "Sofas", "source": "classified", "confidence": 0.9}


def need(thing: str, cat: dict | None = None, **kw) -> Need:
    return Need(raw=kw.pop("raw", thing), thing=thing, category=cat, **kw)


def svc(thing: str, where: str = "Helsinki", cat: dict | None = None) -> Need:
    return Need(raw=f"{thing} {where}", thing=thing, kind="service", where=where, conditions=["service"], category=cat)


def row(title: str, price: float = 100.0, source: str = "tori.fi", condition: str = "used", **raw) -> Offer:
    site = source.split(".")[0]
    return Offer(url=f"https://www.{source}/item/{abs(hash((title, price, source))) % 10**9}", source=source,
                 title=title, price=price, currency="EUR", price_eur=price, condition=condition,
                 raw={"site": site, "from_list_page": f"https://www.{source}/search", **raw})


def shop(title: str, price: float, source: str = "verkkokauppa.com", condition: str = "new") -> Offer:
    return Offer(url=f"https://www.{source}/p/{abs(hash((title, price))) % 10**9}", source=source, title=title,
                 price=price, currency="EUR", price_eur=price, condition=condition)


def line(title: str, price: float, url: str, unit: str | None = "job", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price, currency="EUR",
                 price_eur=price, condition="service", unit=unit, **kw)


def kept(n: Need, o: Offer) -> bool:
    return R.explain(n, o)[1] is None


def why(n: Need, o: Offer) -> str:
    return R.explain(n, o)[1] or ""


def by_url(things, url):
    return next(o for t in things for o in t.offers if o.url == url)


# ------------------------------------------------------------------ road bike / winter jacket: mixed by the need

def test_road_bike_is_a_mixed_bag_even_when_some_offers_lack_the_generic_mark():
    """406 used road bikes at €250-310 were 'too good to be true: 66% under the cheapest new (€899)' because
    late shop offers carried no generic_thing mark, so the Thing was not treated as a mix of models."""
    n = need("road bike", ROAD_TYPED)
    offers = [row(t, p) for t, p in [("Felt F75-maantiepyörä", 300), ("Crescent giga comp Täyshiilikuitu maantiepyörä", 300),
                                     ("Tunturi Professional maantiepyörä, 60", 300), ("Merida maantiepyörä S/M", 420),
                                     ("Giant TCR maantiepyörä", 650), ("Canyon Endurace maantiepyörä", 900),
                                     ("Cube Attain maantiepyörä", 520), ("Ridley maantiepyörä", 480)]]
    offers.append(shop("Cube Attain maantiepyörä", 899, "hi5bikes.fi"))
    things = R.resolve(n, offers)
    for o in offers[-2:]:
        o.raw.pop("generic_thing", None)        # a late re-judge without the mark
    J.judge(n, things, history=False)
    for o in offers[:3]:
        assert not any(f.startswith("too good to be true") for f in o.flags), o.flags
        assert o.true_cost is not None


def test_mixed_follows_the_need_not_only_the_marks():
    n = need("winter jacket women")
    t = R.resolve(n, [row("Naisten talvitakki", 40), row("Vero Moda talvitakki naisten", 30)])[0]
    for o in t.offers:
        o.raw.pop("generic_thing", None)
    assert J._mixed(n, t) == "mixed"
    assert J._mixed(need("sony a7 iii"), t) is None


def test_vague_phone_need_has_no_flagship_reference():
    """puhelin: one €679 'new' reference flagged 1,051 normal cheap phones as fakes (iPhone SE €60 ...)."""
    n = need("puhelin", PHONE_TYPED)
    offers = [row(t, p) for t, p in [("Apple iPhone SE 64 GB", 60), ("Samsung Galaxy A53 5G 128 Gt", 70),
                                     ("iPhone 12 128 GB", 72), ("Samsung Galaxy S21", 150), ("iPhone 13 128GB", 239),
                                     ("OnePlus Nord 2", 120), ("Xiaomi Redmi Note 12", 90)]]
    offers += [shop("Samsung Galaxy S25 puhelin", 679), shop("Apple iPhone 16 puhelin", 899, "gigantti.fi")]
    things = R.resolve(n, offers)
    J.judge(n, things, history=False)
    for o in offers[:3]:
        assert not any(f.startswith("too good to be true") for f in o.flags), (o.title, o.flags)
        assert not o.raw.get("ref_suspect")


def test_vague_need_pick_is_in_the_usual_range_and_the_headline_names_it():
    """Road Bikes tree hunt picked a €35 frame, kinderwagen a €19 diaper bag, and the headline never said what
    the pick was ('€19 all in: used at tori.fi')."""
    n = need("road bike", ROAD_TYPED)
    offers = [row("Peugeot maantiepyörä", 45), row("Basso coral maantiepyörä", 280)] + [
        row(f"{m} maantiepyörä", p) for m, p in [("Merida", 420), ("Giant", 650), ("Canyon", 900), ("Cube", 520),
                                                 ("Ridley", 480), ("Trek", 560), ("Scott", 610)]]
    v = J.judge(n, R.resolve(n, offers), history=False)
    assert v.best_offer_url == offers[1].url, v.headline
    assert v.headline.startswith("€280 all in: used Basso coral maantiepyörä at tori.fi"), v.headline


# ------------------------------------------------------------------ Road Bikes tree hunt: frames, kids' and plain bikes

@pytest.mark.parametrize("title,reason", [
    ("Maantiepyörä runko Crescent", "frame"), ("Vintage peugeot pyörän runko/bike frame", "frame"),
    ("Musta miesten polkupyörä", "another kind"), ('24" Nopsa tyttöjenpyörä', "another kind"),
    ("Cresent naisten/tyttöjen polkupyörä", "another kind"), ("Tunturi retki 5 Naisten polkupyörä", "another kind"),
    ("Carrera 24 pyörä", "another kind"), ("Myydään lasten polkupyörä", "another kind"),
    ("Polkupyörä", "any bike"), ("Pyörä", "any bike")])
def test_road_bikes_tree_rejects_frames_kids_and_plain_bikes(title, reason):
    n = need("road bikes", ROAD_CAT)
    o = row(title, 60, category_page={"exact": True, "node": "sp:sg-4-4-3-11"})
    assert reason in why(n, o), why(n, o)


@pytest.mark.parametrize("title", ["Trek Domane runko 56cm", "Felt F75-maantiepyörä", "Cannondale pyörä",
                                   "Tunturi Professional maantiepyörä, 60", "Rennrad Carbon Rahmen 56"])
def test_road_bikes_tree_keeps_road_bikes(title):
    assert kept(need("road bikes", ROAD_CAT), row(title, 400))


# ------------------------------------------------------------------ consoles

@pytest.mark.parametrize("title", ["Nintendo Switch OLED -pelikonsoli", "Nintendo Switch Oled Pelikonsoli Neon (Käytetty)",
                                   "Nintendo Switch OLED pelikonsoli valkoinen"])
def test_pelikonsoli_is_the_console_not_a_game(title):
    assert kept(need("nintendo switch oled"), row(title, 250))


def test_switch_game_still_rejected():
    assert "game" in why(need("nintendo switch oled"), row("Zelda peli Nintendo Switch OLED", 30))


def test_ps5_headset_with_pro_in_its_name_is_an_add_on():
    """'RIG 300 Pro HS Gaming Kuulokkeet' (proshop new lane) was the ps5 pick: a bare 'pro' proved a console."""
    n = need("ps5", CONSOLE_CAT)
    assert "add-on" in why(n, shop("RIG 300 Pro HS Gaming Kuulokkeet - Musta", 19.57, "proshop.fi"))
    for t in ("PS5 slim digital", "Konsola PS5", "Sony PlayStation 5 Pro 2TB"):
        assert kept(n, row(t, 400)) or "another version" in why(n, row(t, 400)), t


def test_shop_new_price_far_under_the_market_is_no_reference():
    n = need("ps5", CONSOLE_CAT)
    offers = [row(f"PS5 konsoli {i}", p) for i, p in enumerate([367, 380, 400, 420, 450, 390, 410])]
    offers.append(shop("PS5 konsoli lisävaruste", 21, "proshop.fi"))
    ref = J.reference_price(offers, J.category_for("ps5 konsoli"), n)
    assert ref is not None and ref.new_eur > 300, ref


# ------------------------------------------------------------------ iphone 13: 'with its box', magnetic cases

def test_with_original_box_in_lithuanian_is_the_phone():
    n = need("iphone 13", PHONE_TYPED)
    assert kept(n, row("Apple iPhone 13 žalias su originalia dėžute", 145, "vinted.lt"))


def test_magnetic_case_is_a_case_not_a_magazine():
    w = why(need("iphone 13"), shop("iPhone 13 magneettisen kotelo", 20, "proshop.fi"))
    assert "magazine" not in w and w


def test_case_for_three_generations_is_an_accessory():
    assert R.is_accessory("Tech21 Evo Sparkle MagSafe iPhone 13/14/15 Kirkas", need("iphone 13"))
    assert not R.is_accessory("iPhone 13, 12 kk takuu", need("iphone 13"))
    assert not R.is_accessory("iPhone 13 / 128GB / musta", need("iphone 13"))


# ------------------------------------------------------------------ dyson v15: parts for several models

@pytest.mark.parametrize("title", ["Dyson V11/V15 Baterija", "Originele Dyson V11/V15 Accu - Perfect Werkend",
                                   "Dyson Vloerstandaard / Floor Dok voor oa V11/V15", "Dyson V7 V8 V10 V11 V15 laddstation"])
def test_dyson_parts_for_several_models_are_accessories(title):
    assert "accessory" in why(need("dyson v15"), row(title, 56, "vinted.lt"))


def test_pick_comes_from_the_asked_models_group():
    n = need("dyson v15")
    main = [row("Dyson V15 Detect Absolute", p) for p in (250, 280, 300, 320, 350)]
    side = [row("Dyson V11 V15 akku", 45)]
    side[0].raw["matched_by"] = "x"
    things = R.resolve(n, main)
    from agora.models import Thing
    things.append(Thing(id="t-dyson-v11-v15", name="Dyson V11 V15", offers=side))
    v = J.judge(n, things, history=False)
    assert v.best_offer_url == main[0].url


# ------------------------------------------------------------------ strollers, coffee makers, bikes, shelves

@pytest.mark.parametrize("title", ["Bugaboo hoitolaukku, harmaa", "Vaunuverho", "Petite Chérie lasten UV-suojaava kuomuverho",
                                   "Lasten matkalaukut / Turtles (2 kpl)"])
def test_stroller_accessories_are_another_kind(title):
    assert not kept(need("baby stroller", STROLLER_CAT), row(title, 19))


@pytest.mark.parametrize("title", ["CYBEX EOS Lux yhdistelmävaunut, Moon Black", "Emmaljunga NXT90 duo-vaunut",
                                   "Bugaboo Fox 3 rattaat", "kevyet matkarattaat"])
def test_finnish_pram_compounds_are_strollers(title):
    n = need("baby stroller", STROLLER_CAT)
    o = shop(title, 600) if title.startswith("CYBEX") else row(title, 300)
    assert kept(n, o)
    assert R._hits(R._need_words(n), set(R.tokenize(title)))


@pytest.mark.parametrize("title", ["Pressopannu", "Mutteripannu", "moccamaster tiiviste", "moccamaster kytkin",
                                   "Moccamasterin kahvipannu", "2 pakettia Cafe Rene iced coffee caramel",
                                   "Tee- / kahvipannu 1 litra"])
def test_coffee_maker_rejects_presses_parts_and_coffee(title):
    assert not kept(need("kahvinkeitin", COFFEE_CAT), row(title, 5))


def test_coffee_maker_with_its_glass_jug_is_the_coffee_maker():
    assert kept(need("kahvinkeitin", COFFEE_CAT), row("Moccamaster kahvinkeitin, harmaa, lasikannu", 60))


@pytest.mark.parametrize("title", ["Erä Shimano flat- ja enduro - polkimia", "sähkö potku laudan istuin",
                                   "VEVOR pompa powietrza", "Kierownica Burgtec", "Raven Airborne Evo Hjälm",
                                   "SRAM XX1 Eagle kedja", "Korba rowerowa", "Mopon/skooterin tanko"])
def test_bike_hunt_rejects_parts_and_gear(title):
    assert not kept(need("fiets", CYCLING_CAT), row(title, 40))


def test_bike_with_new_tyres_is_still_a_bike():
    assert kept(need("fiets", CYCLING_CAT), row("Gazelle damesfiets", 200, "marktplaats.nl"))
    assert kept(need("fiets", CYCLING_CAT), row("Polkupyörä, uudet renkaat", 120))


@pytest.mark.parametrize("title", ["IKEA KALLAX ritiläkorit", "Nyt lähtee halvalla Kallax ritiläkorit (3kpl)",
                                   "2kpl IKEA Kallax upotettavia lipastoja", "Kallax laatikkot, 2kpl", "IKEA KALLAX desk",
                                   "Ikea Kallax-hyllyn kori 2 kpl"])
def test_kallax_baskets_inserts_and_desk_are_not_the_shelf(title):
    assert not kept(need("ikea kallax shelf"), row(title, 20))


@pytest.mark.parametrize("title", ["IKEA Kallax hylly 4x4", "Kallax hyllykkö"])
def test_kallax_shelf_kept(title):
    assert kept(need("ikea kallax shelf"), row(title, 40))


# ------------------------------------------------------------------ phones from the category tree

@pytest.mark.parametrize("title", ["Accezz läpinäkyvä silikoninen puhelinkotelo 19,99 €", "HoldIt Lompakkopuhelinkotelo",
                                   "agood™ kasvipohjainen puhelinkotelo"])
def test_phones_tree_drops_cases_and_lenses(title):
    assert not kept(need("mobile & smart phones", PHONE_CAT), shop(title, 20, "refurbed.fi", "refurbished"))


def test_phones_tree_keeps_phones():
    n = need("mobile & smart phones", PHONE_CAT)
    assert kept(n, row("OnePlus 8, 128GB siistikuntoinen", 110))
    assert kept(n, row("Samsung Galaxy A33 5G 128gt", 139))


# ------------------------------------------------------------------ macbook air m2

def test_broken_screen_and_swap_are_red_flags():
    n = need("macbook air m2")
    broken = R.title_red_flags(row("Apple MacBook Air M2 13\" grå laptop knust skjerm", 404, "finn.no"), n)
    assert any(k == "broken" for k, _, _ in broken)
    swap = R.title_red_flags(row("Gigabyte g5 2022 ke byts mot MacBook Air m2", 500, "blocket.se"), n)
    assert any(k == "swap" for k, _, _ in swap)


# ------------------------------------------------------------------ sony a7 iii body: lens kits

def test_alpha_written_out_is_the_a7():
    assert R.signature("Sony α 7 III + 28-70mm").models == ("a7-3",)
    assert R.signature("Sony Alpha 7 III + Tamron 28-75mm").models == ("a7-3",)
    assert R.signature("Aparat Sony A7 III + Sony FE 35mm F/1.8").kit
    assert R.signature("Aparat sony a7 III, stan b.dobry, obiektyw 35mm 1.4").kit


def test_body_asked_keeps_kits_consistently_but_picks_a_body():
    n = need("sony a7 iii body")
    kits = [row("Aparat sony a7 III, stan b.dobry, obiektyw 35mm 1.4", 566, "olx.pl"),
            row("Sony α 7 III + 28-70mm", 900), row("Sony Alpha 7 III + Tamron 28-75mm", 1100)]
    bodies = [row("Sony A7 III -järjestelmäkamera", 600), row("Sony Alpha A7 III (A7M3) OVP", 650, "kleinanzeigen.de"),
              row("Sony A7 III body", 700), row("Sony A7III runko", 720)]
    for o in kits:
        assert kept(n, o), o.title
    v = J.judge(n, R.resolve(n, kits + bodies), history=False)
    assert v.best_offer_url == bodies[0].url, v.headline
    assert any("with a lens" in f for f in kits[0].flags)


def test_unchecked_listing_well_under_the_usual_is_not_crowned():
    o = row("Aparat sony a7 III", 566, "olx.pl")
    o.flags = ["well under the usual used price (35% below €875)"]
    o.raw["page_check"] = {"ok": None}
    assert J._unchecked_bargain(o, {})


# ------------------------------------------------------------------ list pages read as one offer

def test_category_pages_are_not_offers():
    assert R.not_an_offer(shop("Fietsen en (e)steps", 139, "refurbed.be", "refurbished").__class__(
        url="https://www.refurbed.be/sc/fietsen-e-steps/", source="refurbed.be", title="Fietsen en (e)steps",
        price=139, currency="EUR", price_eur=139, condition="refurbished"))
    arch = Offer(url="https://globaldiscountfurniture.com/product-category/sofas/", source="globaldiscountfurniture.com",
                 title="Sofas Archives - Global Discount Furniture", price=1100, currency="EUR", price_eur=1100,
                 condition="new")
    assert R.not_an_offer(arch)


# ------------------------------------------------------------------ airpods: a model-coded listing near the floor

def test_model_coded_home_listing_a_little_under_the_floor_is_costed_not_picked():
    ref = J.Reference(219.0, 83.0, 0.38, "shops", 5, 0, None, 0)
    o = row("Apple AirPods pro 2 (A2698)", 80)
    assert J.reference_flag(o, ref, J.category_for("airpods")) is None
    trust, flags = J.assess_trust(o, [o], ref=ref, cat=J.category_for("airpods"))
    assert o.raw.get("near_floor") and any("model code" in f for f in flags)
    far = row("Apple AirPods pro 2 (A2698)", 40)
    assert J.reference_flag(far, ref, J.category_for("airpods"))


# ------------------------------------------------------------------ services: haircut, trades, weddings

@pytest.mark.parametrize("title,url", [
    ("Hiustenleikkuu", "https://www.helsinkibarber.fi/fi"), ("Hiustenleikkaus, kampaamopalvelu", "https://www.cityhair.net/hinnasto"),
    ("Parturileikkaus", "https://timma.fi/yritys/janna-parturi-kampaamo-haaga"), ("Trim & Basic Cut", "https://www.onnihair.fi/pricing"),
    ("M Cut™", "https://mroom.com/fi/parturit/helsinki/toolo/"), ("Leikkaus 30 min", "https://www.saloncaramel.fi/hinnasto/"),
    ("Ladies Hair Cut (Short) – Taper360", "https://www.fresha.com/a/taper360-helsinki-simonkatu-10-oziaz2fe")])
def test_haircut_salons_name_the_job(title, url):
    assert kept(svc("haircut"), line(title, 35, url))


def test_price_statistics_are_no_provider():
    assert "statistic" in why(svc("haircut"), line("Average price of women haircut", 35, "https://finlandprices.com/x"))
    assert "statistic" in why(svc("plumbing"), line("Putkimiehen tuntihinta 2026 — mediaani 62,75 €/h (45 yritystä)",
                                                     62.75, "https://putkarit.fi/putkimies/helsinki", "hour"))


@pytest.mark.parametrize("thing,title,url", [
    ("electrician", "SähköHessu Oy", "https://www.urakkamaailma.fi/urakoitsija/sahkohessu-oy"),
    ("electrician", "24 Sähkö Oy", "https://www.urakkamaailma.fi/urakoitsija/24-sahko-oy"),
    ("electrician", "Arki Sähkötiimi Oy", "https://www.urakkamaailma.fi/urakoitsija/arki-sahkotiimi-oy"),
    ("plumbing", "SK-Putki Oy", "https://www.urakkamaailma.fi/urakoitsija/sk-putki-oy"),
    ("plumbing", "Putkihuolto Arina Oy", "https://www.urakkamaailma.fi/urakoitsija/putkihuolto-arina-oy"),
    ("plumbing", "Weekdays (Mon-Fri) from 07.00 to 16.00", "https://www.normiputki.fi/hp-services")])
def test_trade_firm_names_name_the_job(thing, title, url):
    assert kept(svc(thing), line(title, 60, url, "hour"))


def test_weekday_paivystys_is_a_standard_rate():
    n = svc("plumbing")
    assert R.service_line_kind(n, "Päivystys – arkisin klo 7–17", "hour") == "main"
    assert R.service_line_kind(n, "Päivystys – viikonloppuisin", "hour") == "premium"


@pytest.mark.parametrize("title", ["Koko galleria", "Lisätunti", "Live Stream", "Hääalbumi 30 sivua"])
def test_wedding_add_on_lines_are_never_the_package(title):
    n = svc("wedding photographer")
    assert R.service_line_kind(n, title, "job") == "extra"
    o = line(title, 100, "https://aigulphotography.com/hinnasto")
    assert J.service_cost(o, n) is None and o.raw.get("not_comparable")


def test_wedding_package_lines_stay_main():
    n = svc("wedding photographer")
    for t in ("Vihkiminen ja häämuotokuvat", "Perus", "8 tunnin dokumentaarinen hääkuvaus"):
        assert R.service_line_kind(n, t, "job") == "main", t
    assert R.service_line_kind(svc("home cleaning"), "Lisätunti", "hour") == "main"   # cleaning: an hourly rate


def test_first_hour_price_is_not_eight_first_hours():
    n = svc("wedding photographer")
    o = line("documentary style wedding photography: 1st hour", 450, "https://nooiko.com/prices", "hour")
    o.raw["other_prices"] = [{"title": "following hours", "price_eur": 175.0, "unit": "hour"}]
    tc = J.service_cost(o, n)
    assert tc is not None and tc.total_eur == 450 + 175 * 7
    bare = line("documentary style wedding photography: 1st hour", 450, "https://nooiko.com/prices", "hour")
    tc = J.service_cost(bare, n)
    assert tc is not None and tc.total_eur == 450 and bare.raw.get("partial_job")


def test_wedding_portraits_only_package_is_not_the_pick():
    n = svc("wedding photographer")
    offers = [line("hääpotrettikuvaus miljöössä — 20 kpl", 460, "https://miiakoskinen.com/hinnasto"),
              line("Vihkiminen ja häämuotokuvat", 900, "https://www.artomarkkanen.fi/haakuvaus-hinnasto/"),
              line("Perus", 1400, "https://aigulphotography.com/hinnasto"),
              line("Hääpaketti 8 h", 1900, "https://annikuitula.com/hinnasto/")]
    things = R.resolve(n, offers)
    v = J.judge(n, things, history=False)
    # round 6: a ceremony-only package no longer wins against a full-day one (like with like by coverage)
    assert v.best_true_cost_url not in (offers[0].url, offers[1].url), v.headline
    assert any("portraits only" in f for f in offers[0].flags)
    assert any("ceremony" in f for f in offers[1].flags)


def test_directory_price_in_dollars_on_a_local_provider_is_flagged():
    n = svc("wedding photographer")
    o = Offer(url="https://wezoree.com/vendors/profile/15695-photographers-maria-hedengren/", source="wezoree.com",
              title="Wedding photographer", price=15000, currency="USD", price_eur=13572.2, condition="service",
              unit="job", location="Helsinki")
    ok = line("Hääpaketti 8 h", 1900, "https://annikuitula.com/hinnasto/", location="Helsinki")
    v = J.judge(n, R.resolve(n, [o, ok]), history=False)
    assert any("directory" in f for f in o.flags) and (o.trust or 1) < 0.6
    assert v.best_true_cost_url == ok.url


def test_travel_per_km_is_said_not_hidden():
    n = svc("electrician")
    o = line("Tuntihinta", 61, "https://kallion-sahko.fi/hinnasto", "hour")
    o.raw["search_text"] = "Sähkömiehen tuntihinta 61 €/h. Auton käyttökorvaus 0,65 €/km."
    tc = J.service_cost(o, n)
    assert tc is not None and "0.65 €/km" in tc.basis


def test_unknown_call_out_and_minimum_borrow_the_others():
    n = svc("electrician")
    a = line("Tuntihinta", 75, "https://sskt.fi/hinnat", "hour")
    a.raw.update(callout_fee=35.0, min_hours=2.0)
    b = line("Tuntihinta", 52, "https://sahkopalveluhelsinki.fi/hinnasto", "hour")
    b.raw.update(callout_fee=50.0, min_hours=2.0)
    c = line("Sähkömies tuntihinta", 55, "https://tekijatori.fi/sahkomies", "hour")
    J._estimate_missing_minimums(n, [a, b, c])
    tc = J.service_cost(c, n)
    assert tc is not None and tc.total_eur > 55 * 2 and "est." in " ".join(lbl for lbl, _ in tc.receipt)


def test_same_plan_read_twice_is_one_vote():
    offers = [line("EU Sales", 50, "https://adcount.fi/en/prices", "month"),
              line("EU Sales", 50, "https://www.adcount.fi/en/prices.html", "month"),
              line("Essential", 99, "https://tilitoimistonm.fi/en/pricing", "month"),
              line("Essential", 99, "https://tilitoimistonm.fi/", "month")]
    assert len(J._dedupe_service(offers)) == 2


def test_school_catering_without_prices_explains_instead_of_watch():
    n = svc("school catering", "Finland", {"id": "cpv:55524", "label": "School catering"})
    v = J.judge(n, [], history=False)
    assert "free" in v.headline and "watch" not in v.headline.lower()
