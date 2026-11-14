"""Round-1 judges' relevance / pricing / verdict defects, as offline regressions.

Every title and price below is copied from the live streams the judges read (eval r1, 14 Nov). Each test names
the defect it pins down; the fix is general (rules per listing), never a blocked site.
"""
from __future__ import annotations

import pytest

from agora import judge as J
from agora import resolve as R
from agora.models import Need, Offer, Thing

ROAD_CAT = {"id": "sp:sg-4-4-3-11", "label": "Road Bikes", "source": "tree", "confidence": 1.0,
            "labels": {"en": "Road Bikes", "fi": "Maantiepyörät", "de": "Rennräder"}}
PHONE_CAT = {"id": "sp:el-4-8-5", "label": "Mobile & Smart Phones", "source": "tree", "confidence": 1.0}
CONSOLE_CAT = {"id": "sp:el-4-12-1", "label": "Video Game Consoles", "source": "classified", "confidence": 0.9}


def need(thing: str, cat: dict | None = None, **kw) -> Need:
    return Need(raw=kw.pop("raw", thing), thing=thing, category=cat, **kw)


def row(title: str, price: float = 100.0, source: str = "tori.fi", condition: str = "used", **raw) -> Offer:
    site = source.split(".")[0]
    return Offer(url=f"https://www.{source}/item/{abs(hash((title, price))) % 10**9}", source=source, title=title,
                 price=price, currency="EUR", price_eur=price, condition=condition,
                 raw={"site": site, "from_list_page": f"https://www.{source}/search", **raw})


def kept(n: Need, o: Offer) -> bool:
    return R.explain(n, o)[1] is None


def why(n: Need, o: Offer) -> str:
    return R.explain(n, o)[1] or ""


# ------------------------------------------------------------------ road bike (defects 1, 10)

def test_gear_and_count_words_are_not_models():
    assert R.signature("Helkama Aino 3-Vaihteinen").models == ()
    assert R.signature("2kpl baarijakkaroita").models == ()
    assert R.signature("Sotka 2-istuttava sohva").models == ()
    assert R.signature("MacBook Air M2 2022 8/256").models == ("m2",)          # was 'm2-8' -> 'M2 VIII'


@pytest.mark.parametrize("title", ["Helkama Aino 3-Vaihteinen", "Tyylikäs 3-vaihteinen Tunturi kaupunkipyörä",
                                   "Helkama Kulkuri 28\" 3-vaihteinen", "26-tuuman sisärenkaita", "Polkupyörä varaosiksi",
                                   "Kuntopyörä"])
def test_road_bike_rejects_city_bikes_and_parts(title):
    n = need("road bike", ROAD_CAT)
    assert not kept(n, row(title, 70))


@pytest.mark.parametrize("title", ["Giant TCR", "Cannondale Caad 8 2014 ja 42,5 kengät", "Trek Domane AL 2 maantiepyörä 62 cm"])
def test_road_bike_keeps_real_road_bikes(title):
    n = need("road bike", ROAD_CAT)
    assert kept(n, row(title, 370))


def test_road_bike_cheap_ones_are_not_called_fakes_and_tiny_clusters_set_no_band():
    n = need("road bike", ROAD_CAT)
    offers = [row(t, p) for t, p in [("Trek road bike", 190), ("Maantiepyörä crescent", 350), ("Felt F75-maantiepyörä", 350),
                                     ("Ridley Triton S maantiepyörä", 350), ("Merida maantiepyörä S/M", 420),
                                     ("Giant TCR maantiepyörä", 650), ("Canyon Endurace maantiepyörä", 900),
                                     ("Cube Attain maantiepyörä", 520), ("Insera maantiepyörä", 5)]]
    offers.append(Offer(url="https://hi5bikes.fi/p/1", source="hi5bikes.fi", title="Cube Attain maantiepyörä",
                        price=899, currency="EUR", price_eur=899, condition="new"))
    things = R.resolve(n, offers)
    assert len(things) == 1 and things[0].name == "Road Bikes"
    v = J.judge(n, things, history=False)
    trek = offers[0]
    assert not any(f.startswith("too good to be true") for f in trek.flags), trek.flags
    assert trek.true_cost is not None                                   # costed (was 'not costed: price unconfirmed')
    assert "far under" in " ".join(offers[8].flags)                     # the €5 one: shown, never the pick
    assert v.best_offer_url == trek.url


# ------------------------------------------------------------------ lego technic (defect 3)

def test_lego_parts_books_and_manuals_go_sets_stay():
    n = need("lego technic")
    for t in ["LEGO Technic varaosia", "Lego Bedienungsanleitung Anleitungen City Technic Ninjago",
              "Das inoffizielle LEGO-Technic-Buch", "LEGO 107544 Star Wars Keychain 25 Year - LEGO Star Wars keychain"]:
        assert not kept(n, row(t, 16)), t
    for t in ["Lego technic Doms Charger 42111", "LEGO Technic 42111 Fast & Furious Dom's Dodge Charger",
              "LEGO Technic Fast & Furious Dodge Charger 42231", "LEGO Technic Star Wars 8008 Stormtrooper – Komplett m. manual"]:
        assert kept(n, row(t, 66)), (t, why(n, row(t, 66)))


def test_a_search_snippet_titled_with_the_search_words_is_not_an_offer():
    n = need("lego technic")
    o = Offer(url="https://reepeat.fi/lego-technic", source="reepeat.fi", title="lego technic refurbished | Reepeat",
              price=16, currency="EUR", price_eur=16, condition="refurbished", read_via="search_highlight")
    assert "search page" in why(n, o)


def test_product_line_need_is_one_mixed_thing_not_named_after_a_model():
    n = need("lego technic")
    offers = [row("LEGO Technic Porsche GT3 42056", 250), row("Lego Technic autoja", 25), row("Lego Technic 8291", 25)]
    things = R.resolve(n, offers)
    assert [t.name for t in things] == ["Lego Technic"]
    assert all(o.raw.get("generic_thing") for o in offers)


# ------------------------------------------------------------------ macbook air m2 (defect 4)

def test_macbook_broken_screens_ipads_and_old_years():
    n = need("macbook air m2")
    broken = row("Apple MacBook Air M2 13\" grå laptop knust skjerm", 404, "finn.no")
    assert any(k == "broken" for k, _, _ in R.title_red_flags(broken, n))
    assert any(k == "broken" for k, _, _ in R.title_red_flags(row("MacBook Air 13 inch met M2-chip met waterschade."), n))
    assert any(k == "broken" for k, _, _ in R.title_red_flags(row("Apple MacBook Air M2 13,6 Zoll 8/256 GB OVP Tastaturdefekt"), n))
    assert not kept(n, row("MacBook Air m2 scherm space grey 2022 a2681", 424, "marktplaats.nl"))
    assert "another product (iPad vs MacBook)" == why(n, row("Apple iPad Air M2 2024 128GB", 442))
    assert not kept(n, row("Laptop Apple MacBook Air 2018", 465))
    assert kept(n, row("Apple MacBook Air 13\" laptop blå med Apple M2-chip 8GB/256GB", 684, "finn.no"))
    assert kept(n, row("MacBook Air M2 16 GB RAM / 512 GB SSD – Svært god stand", 851, "finn.no"))


def test_unchecked_bargain_is_not_the_pick():
    n = need("macbook air m2")
    cheap = row("MacBook Air M2 2022 / 8GB / 256GB", 385, "olx.pl", page_check={"ok": None, "flags": []})
    others = [row(f"MacBook Air M2 8GB 256GB nr {i}", p) for i, p in enumerate([650, 700, 720, 750, 800, 832, 690])]
    v = J.judge(n, R.resolve(n, [cheap, *others]), history=False)
    assert v.best_offer_url != cheap.url


# ------------------------------------------------------------------ airpods pro 2 (defect 5)

@pytest.mark.parametrize("title", ["Apple AirPods Pro (2e generatie)", "Originele Apple AirPods Pro (2e generatie)",
                                   "Apple AirPods pro2", "AirPods Pro2, Stan Idealny", "AirPods Pro 2. Generation",
                                   "Apple airPods Pro (2. Sukupolvi)"])
def test_airpods_generation_forms_are_the_same_model(title):
    assert kept(need("airpods pro 2"), row(title, 130, "marktplaats.nl"))


def test_airpods_max_says_another_version():
    assert why(need("airpods pro 2"), row("Apple AirPods Max 2", 400)).startswith("another version")


def test_a_for_iphone_tail_does_not_change_the_product():
    assert R.signature("Apple AirPods Pro 2 for iPhone").family == "airpods"


# ------------------------------------------------------------------ kallax / kitchen table (defects 6, 7)

def test_kallax_inserts_boxes_and_parts_go():
    n = need("ikea kallax shelf")
    for t in ["2kpl punaista laatikkoa Kallax", "Kallax -hyllyn kaappeja", "Kallax-hyllynjakaja", "Ristikkohylly Kallaxiin"]:
        assert not kept(n, row(t, 10)), t
    assert kept(n, row("Ikea Kallax hylly (1x4)", 10))


def test_the_makers_own_shop_price_is_not_too_good_to_be_true():
    n = need("ikea kallax shelf")
    shop = Offer(url="https://www.ikea.com/fi/fi/p/kallax-hylly-valkoinen-20275814/", source="ikea.com",
                 title="KALLAX Hylly - valkoinen 77x77 cm", price=29, currency="EUR", price_eur=29, condition="new")
    big = [Offer(url=f"https://www.ikea.com/fi/fi/p/kallax-{i}/", source="ikea.com", title=f"KALLAX Hylly 182x182 cm {i}",
                 price=p, currency="EUR", price_eur=p, condition="new") for i, p in enumerate([114, 199, 149])]
    v = J.judge(n, R.resolve(n, [shop, *big]), history=False)
    assert not any(f.startswith("too good") for f in shop.flags) and shop.true_cost is not None
    # round 4: a shop page with no delivery fee gets a labelled parcel / furniture delivery estimate in 'all in'
    assert v.best_offer_url == shop.url and "€44 all in" in v.headline, v.headline


def test_kitchen_table_keeps_tables_with_legs_and_rejects_chairs_and_other_tables():
    n = need("kitchen table")
    for t in ["Estelle ruokapöytä pyöreä 106cm harmaa marmori / mustat jalat",
              "💎 Vintage pyöreä ruokapöytä • tiikki / valkoiset jalat", "Ray ruokapöytä – valkoinen marmori, kultaiset jalat",
              "Pöytä ja tuolit 2kpl"]:
        assert kept(n, row(t, 150)), (t, why(n, row(t, 150)))
    for t in ["Ikea Kättil tuolit 4kpl", "2kpl baarijakkaroita", "Tv-pöytä 60x60cm", "Sohvapöytä tammi"]:
        assert not kept(n, row(t, 50)), t


# ------------------------------------------------------------------ fiets / bikes (defect 8)

def test_bike_need_rejects_scooters_bags_wheels_and_keeps_bikes_in_stand():
    n = need("fiets")
    for t in ["Xiaomi Scooter 4 Lite", "MTB Rucksack Evoc FR Trail", "Tuplapotkupyörä", "DT Swiss Laufräder XR 1501",
              "Erä Restrap satulalaukku", "Polkupyörän ohjaustangot musta", "Kuntopyörä"]:
        assert not kept(n, row(t, 120)), t
    for t in ["Top stand mtb Radon Cragger 7.0 (2024)", "Herrecykel pæn stand", "Leader Fox Brasa fat bike akku 720W"]:
        assert kept(n, row(t, 1000, "dba.dk")), (t, why(n, row(t, 1000, "dba.dk")))


# ------------------------------------------------------------------ dyson (defects 11, 21)

def test_dyson_attachments_compat_lists_and_batteries_go():
    n = need("dyson v15")
    for t in ["Pölyharjakiinnitys Dyson V7 V8 V10 V11 V12 V15", "Dyson Flexi Fugendüse für V7", "Pojemnik na kurz dyson v11 v15",
              "Originele Dyson V11/V15 Accu - Perfect Werkend", "Dyson Floor Dok Oplaadstandaard V11/V15 - Zo goed als nieuw",
              "SUCHE NEUEN DYSON V15 STAUBSAUGER"]:
        assert not kept(n, row(t, 30)), t
    assert kept(n, row("Dyson V15 detect Complete", 190))


# ------------------------------------------------------------------ phones (defects 13, 24, 25)

def test_phone_category_rejects_desk_phones_and_keeps_smartphones():
    n = need("Mobile & Smart Phones", PHONE_CAT)
    for t in ["AudioCodes 420HD IP Puhelin - VoIP Puhelin", "Avaya J139 IP Puhelin",
              "Doro 4100H - Musta - 4G Fixed Cellular Puhelin 4G kiinteä matkapuhelin"]:
        assert not kept(n, row(t, 142, "proshop.fi", "new")), t
    p = need("puhelin")
    assert kept(p, Offer(url="https://www.tori.fi/recommerce/forsale/item/49845144", source="tori.fi",
                         title="OnePlus Nord 5 256GB", price=240, currency="EUR", price_eur=240, condition="used"))
    assert kept(p, row("Doro Senioripuhelin", 30))


def test_generic_phone_hunt_has_no_hunt_wide_floor_or_new_reference():
    n = need("puhelin")
    offers = [row("OnePlus Nord 5 256GB", 240), row("Google Pixel 8 Pro", 250), row("Samsung puhelin", 25),
              row("Nokia 3310", 20), row("Honor 7S matkapuhelin", 25), row("LG G3 -älypuhelin", 28)]
    offers += [row(f"Apple iPhone 13 128GB nr {i}", 300 + i) for i in range(6)]
    offers.append(Offer(url="https://www.proshop.fi/x", source="proshop.fi", title="Puhelin Samsung Galaxy A17 5G",
                        price=209, currency="EUR", price_eur=209, condition="new"))
    v = J.judge(n, R.resolve(n, offers), history=False)
    assert not any(l.startswith("reference: new") for l in v.lines)
    for o in offers[:2]:
        assert not any(f.startswith(("too good", "costs more than new")) for f in o.flags), o.flags


# ------------------------------------------------------------------ Nordic / Polish condition words (defect 14)

@pytest.mark.parametrize("title", ["Brugt iPhone 13 | 128GB | Blå | Rigtig god stand", "iPhone 13 – 128 GB – Sort – Flot stand",
                                   "iphone 13, 128 GB, super stand. md nyt batteri",
                                   "iPhone 13 93% kondycji - stan idealny - telefon,opakowanie,kabel",
                                   "IPhone 13 128GB 86% Stan Dobry Pudełko", "iPhone 13 128Gb Ladekabel&Hülle", "I Phone 13",
                                   "Apple iPhone 13-serien 128 GB"])
def test_iphone_condition_and_contents_words_are_not_accessories(title):
    assert kept(need("iphone 13"), row(title, 200, "dba.dk"))


# ------------------------------------------------------------------ winter jacket women / sofa / coffee maker (12, 19, 26)

def test_winter_jacket_women_rejects_dog_kids_and_mens():
    n = need("winter jacket women")
    for t in ["Koiran talvitakki koko 6XL", "Męska kurtka zimowa parka XXL", "Burton takki 126-133, 7-8v",
              "H&M Winterjacke Gr. 110 für Mädchen", "Poikien talvitakki 152"]:
        assert not kept(n, row(t, 20)), t


def test_cheap_used_sofas_are_giveaways_not_parts():
    n = need("sofa")
    offers = [row(t, p) for t, p in [("Sotka 2-istuttava sohva", 10), ("Kahden hengen sohva", 15), ("Askon kulmasohva", 10),
                                     ("Kulmasohva harmaa", 350), ("Sohva 3-istuttava", 400), ("Sohva nahka", 600),
                                     ("Vuodesohva", 300), ("Kangassohva", 250)]]
    assert not kept(n, row("Uusi Erika-vuodetuoli, BLACK WEEKS poisto", 199))
    v = J.judge(n, R.resolve(n, offers), history=False)
    assert not any("probably a part" in f for f in offers[0].flags)
    assert offers[0].true_cost is not None
    assert v.best_offer_url not in (offers[0].url, offers[2].url)       # a giveaway is shown, never crowned


def test_coffee_maker_toys_filters_and_magazines_go():
    n = need("kahvinkeitin")
    for t in ["Bosch Tassimo Spielzeug-Kaffeemaschine für Kinder", "5kpl suodatinpusseja", "Mocca masterin kansi",
              "Suuri Käsityö lehti syyskuu 2006", "Leikkikeittiön kahvinkeitin"]:
        assert not kept(n, row(t, 2)), t
    # round 4: 'kahvinkeitin' is a drip coffee maker; a capsule machine is another kind for it, but still a coffee
    # machine for a plain 'coffee machine' hunt
    assert not kept(n, row("Krups Dolce Gusto Circolo – flot stand", 40, "dba.dk"))
    assert kept(need("coffee machine"), row("Krups Dolce Gusto Circolo – flot stand", 40, "dba.dk"))


# ------------------------------------------------------------------ ps5 (defects 22, 23, 33)

@pytest.mark.parametrize("title", ["Dying Light 2: Stay Human (PS5)", "Tekken 8 PS5 -peli", "Battlefield 6 PS5",
                                   "Horizon Forbidden West Complete Edition PS5 (Käytetty)", "Sony 3D Pulse PS5 kuulokkeet",
                                   "Turtle Beach Recon 70 - 2024 - White Pelikuulokemikrofoni Turtle Beach"])
def test_ps5_games_and_headsets_are_not_the_console(title):
    assert not kept(need("ps5", CONSOLE_CAT), row(title, 15))


@pytest.mark.parametrize("title", ["Sony PlayStation 5 Konsole", "Ps5 Slim 1tb", "PS5 Slim Disc Edition 1 TB",
                                   "uåpnet PS5 slim 1TB m/diskdrev", "Myydään PS5", "PlayStation 5 + 2 ohjainta"])
def test_ps5_consoles_stay(title):
    assert kept(need("ps5", CONSOLE_CAT), row(title, 400))


def test_vinted_playstation_brand_field_is_sony():
    o = row("PlayStation 5, Tuotemerkki: PlayStation, Kunto: Erittäin hyvä, 344.49 €, 362.07 €", 344.49, "vinted.fi")
    assert kept(need("ps5"), o)


# ------------------------------------------------------------------ switch oled (defects 27, 28)

def test_switch_oled_word_order():
    n = need("nintendo switch oled")
    assert kept(n, row("OLED Nintendo Switch", 250))
    assert kept(n, row("Nintendo Oled ja peli", 240))
    assert not kept(n, row("Nintendo Switch (EJ OLED)", 153))


def test_vinted_buyer_fee_from_the_row_and_a_good_grade_beats_a_satisfactory_one():
    n = need("nintendo switch oled")
    low = row("Nintendo Switch OLED, 64GB, Neon Blue and Red, Tuotemerkki: Nintendo, Kunto: Tyydyttävä, 134.95 €, 142.40 €",
              134.95, "vinted.fi")
    good = row("Nintendo Switch OLED biały, Tuotemerkki: Nintendo, Kunto: Hyvä, 137.80 €, 145.39 €", 137.80, "vinted.fi")
    assert J.buyer_fee(low) == pytest.approx(7.45)
    others = [row(f"Nintendo Switch OLED valkoinen {i}", p) for i, p in enumerate([220, 240, 250, 260, 230])]
    v = J.judge(n, R.resolve(n, [low, good, *others]), history=False)
    assert any("buyer protection" in lbl for lbl, _ in low.true_cost.receipt)
    assert v.best_offer_url == good.url


# ------------------------------------------------------------------ services (defects 2, 9, 16, 17, 20, 29, 30, 31, 32)

def svc(source: str, title: str, price: float, unit: str | None = "hour", currency: str = "EUR", **kw) -> Offer:
    raw = kw.pop("raw", {})
    return Offer(url=f"https://{source}/hinnasto", source=source, title=title, price=price, currency=currency,
                 price_eur=price, condition="service", unit=unit, raw=raw, **kw)


def test_haircut_local_words_and_no_household_deduction():
    n = need("haircut", where="Helsinki", kind="service", raw="haircut helsinki",
             cat={"id": "beauty-wellness.hair-salons-barbers.haircut", "label": "Haircut"})
    for o in [svc("helsinkibarber.fi", "Hiustenleikkuu", 20, "job"), svc("mroom.com", "M Cut™", 36, "job"),
              svc("onnihair.fi", "Trim & Basic Cut", 45, "job", location="Helsinki"),
              svc("hiusstudiohelsinki.fi", "Hiusstudio Helsinki: Parturi kampaamo Töölö", 79)]:
        assert kept(n, o), (o.title, why(n, o))
    o = svc("empirehelsinki.fi", "Haircut", 90, "job", location="Helsinki, Finland")
    v = J.judge(n, [Thing(id="t", name="haircut", offers=[o])], history=False)
    assert "deduction" not in v.headline and "deduction" not in o.true_cost.basis


def test_wedding_photographer_finnish_packages_and_a_full_day():
    n = need("wedding photographer", kind="service", must_have=["photography"],
             cat={"id": "events-leisure.weddings.wedding-photographer", "label": "Wedding photographer", "source": "tree"})
    for o in [svc("artomarkkanen.fi", "Vihkiminen ja häämuotokuvat", 900, "job"),
              svc("tori.fi", "• Hääkuvaaja & Potrettikuvaaja – Laadukkaat kuvat nopeasti", 69, None)]:
        assert kept(n, o), (o.title, why(n, o))
    hourly = svc("photo.fi", "Hääkuvaus tuntihinta", 150)
    J.judge(n, [Thing(id="t", name="wedding photographer", offers=[hourly])], history=False)
    assert hourly.true_cost.total_eur == 150 * 8


def test_bookkeeping_finland_keeps_finnish_firms_and_drops_us_ones():
    n = need("bookkeeping service", where="Finland", kind="service", cat={"id": "cpv:79211", "label": "Accounting"})
    for o in [svc("holvi.com", "Kirjanpitopalvelut", 79, "month", location="Finland"),
              svc("ktkirjanpito.fi", "ktkirjanpito HINNASTO 2026 – Hinnasto | ktkirjanpito", 75, "month"),
              svc("fintra-accounting.com", "Sole Trader (Toiminimi) bookkeeping", 85, "month", location="Finland")]:
        assert kept(n, o), (o.title, why(n, o))
    for o in [svc("pilot.com", "Pilot Essentials – Pilot Pricing: Transparent Bookkeeping", 99, "month", "USD"),
              svc("lukro.co.uk", "Lukro Ltd Basic MTD Package – Pricing for Bookkeeping", 39, "month", "GBP")]:
        assert why(n, o).startswith("a provider abroad"), (o.title, why(n, o))


def test_car_insurance_rejects_us_insurers_and_other_insurances():
    n = need("car insurance", where="Finland", kind="service",
             cat={"id": "finance-insurance.insurance.car-insurance", "label": "Car insurance"})
    assert why(n, svc("progressive.com", "Progressive Umbrella insurance", 75, "year", "USD")).startswith("a provider abroad")
    assert "different insurance" in why(n, svc("if.fi", "Kotivakuutus", 120, "year"))
    assert R.off_topic_reason(n, svc("lemonade.com", "Lemonade Term Life", 8, "month")).startswith("a different insurance")


def test_plumber_berlin_connecticut_is_abroad():
    n = need("plumbing", where="Berlin", kind="service", cat={"id": "trades.plumbing", "label": "Plumbing"})
    o = svc("homeyou.com", "Plumbing Repair labor cost (lower estimate)", 36.19, currency="USD", location="Berlin, CT")
    assert "Berlin, CT" in why(n, o)


def test_cleaners_in_another_town_say_so_and_articles_are_not_providers():
    n = need("home cleaning 24m2", where="Tilburg", kind="service", raw="home cleaning tilburg 24m2",
             cat={"id": "home-services.cleaning.home-cleaning", "label": "Home cleaning"})
    assert why(n, svc("en.yoopies.nl", "house cleaning – Ines", 13.5, location="Amsterdam")) == "in Amsterdam, not Tilburg"
    assert not kept(n, svc("en.yoopies.nl", "housekeeping – Stephanie", 26, location="Amsterdam"))
    assert kept(n, svc("yoojo.nl", "Thuis schoonmaken", 13, location="Tilburg"))
    assert "article" in why(n, svc("dutchreview.com", "Find a cleaning service in the Netherlands", 20))
    o = svc("yoojo.nl", "Thuis schoonmaken", 13, location="Tilburg")
    J.judge(n, [Thing(id="t", name="home cleaning", offers=[o])], history=False)
    assert "usually 2 h minimum" in o.true_cost.receipt[0][0]


def test_electricians_compare_like_for_like():
    n = need("electrician", where="Helsinki", kind="service", raw="electrician helsinki",
             cat={"id": "trades.electrical-work", "label": "Electrical work"})
    full = svc("sahkopalveluhelsinki.fi", "Tuntihinta", 52, location="Helsinki", raw={"min_hours": 2, "callout_fee": 50})
    snippet = svc("tekijatori.fi", "Sähköasentaja", 55, location="Helsinki")
    v = J.judge(n, [Thing(id="t", name="electrician", offers=[full, snippet])], history=False)
    assert snippet.true_cost.total_eur == 55 * 2 + 50                  # the others' minimum and call-out, as estimates
    assert v.best_offer_url == full.url
    assert "2-hour call" in v.headline and "2 h labour" in full.true_cost.basis


# ------------------------------------------------------------------ verdict text (defects 21, 33)

def test_seen_before_is_not_a_shopper_flag():
    n = need("dyson v15")
    o = row("Dyson V15 Detect Absolute", 400)
    J._judge_offers(n, Thing(id="t", name="Dyson V15", offers=[o]), 12, {"tori.fi": 3})
    assert not any(f.startswith("seen before") for f in o.flags) and o.raw["seen_hunts"] == 3


def test_used_car_list_pages_and_spec_sites_never_quote_a_new_price():
    n = need("volvo v70")
    for o in [Offer(url="https://www.autouncle.fi/fi/kaytetyt-autot/Volvo/V70", source="autouncle.fi", title="Volvo V70",
                    price=3932, currency="EUR", price_eur=3932, condition="new"),
              Offer(url="https://www.auto1.fi/volvo-v70", source="auto1.fi", title="Volvo V70 vaihtoautot",
                    price=1690, currency="EUR", price_eur=1690, condition="new"),
              Offer(url="https://www.cars-data.com/en/volvo-v70-price/", source="cars-data.com",
                    title="Volvo V70 Price (EUR) — All Variants | Cars-Data.com", price=81995, currency="EUR",
                    price_eur=81995, condition="new")]:
        assert not kept(n, o), o.title
    assert not kept(n, row("Volvo V70 Mk2 Tdi maf", 30))                # a sensor, not a car
