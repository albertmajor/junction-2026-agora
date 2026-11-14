"""Round-4 judges' relevance / pricing / verdict defects, as offline regressions.

Titles, prices and sites are copied from the live streams the judges read (eval r4, 14 Nov). Every fix is a rule
per listing (never a blocked site).
"""
from __future__ import annotations

import pytest

from agora import judge as J
from agora import resolve as R
from agora.models import Need, Offer

CYCLING = {"id": "sp:sg-4-4", "label": "Cycling", "source": "classified", "confidence": 0.9}
ROAD_CAT = {"id": "sp:sg-4-4-3-11", "label": "Road Bikes", "source": "tree", "confidence": 1.0}
PHONE_CAT = {"id": "sp:el-4-8-5", "label": "Mobile & Smart Phones", "source": "tree", "confidence": 1.0}
ROBOVAC = {"id": "sp:hg-9-10-5", "label": "Robot Vacuums", "source": "classified", "confidence": 0.92,
           "labels": {"en": "Robot Vacuums", "fi": "Robotti-imurit", "de": "Saugroboter", "nl": "Robotstofzuigers",
                      "sv": "Robotdammsugare", "da": "Robotstøvsugere", "nb": "Robotstøvsugere",
                      "pl": "Roboty sprzątające"},
           "synonyms": ["Robotti imurin tarvikkeet", "Saugroboter zubehör", "Saugroboter mit wischfunktion"]}
COFFEE_DIY = {"id": "m:power:kahvi-ja-tee-ac1e64", "label": "Coffee & Tees", "source": "classified", "confidence": 0.8}
TABLES = {"id": "sp:fr-x", "label": "Kitchen & Dining Tables", "source": "classified", "confidence": 0.9}


def need(thing: str, cat: dict | None = None, **kw) -> Need:
    return Need(raw=kw.pop("raw", thing), thing=thing, category=cat, **kw)


def svc(thing: str, where: str, raw: str | None = None) -> Need:
    return Need(raw=raw or f"{thing} {where}", thing=thing, kind="service", where=where, conditions=["service"])


def row(title: str, price: float = 100.0, source: str = "tori.fi", exact: bool = False, **raw) -> Offer:
    r = {"site": source.split(".")[0], "from_list_page": f"https://www.{source}/search", **raw}
    if exact:
        r["category_page"] = {"exact": True}
    return Offer(url=f"https://www.{source}/item/{abs(hash((title, price, source))) % 10**9}", source=source,
                 title=title, price=price, currency="EUR", price_eur=price, condition="used", raw=r)


def page(url: str, title: str, price: float, unit: str | None = "job", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price, currency="EUR",
                 price_eur=price, condition="service", unit=unit, **kw)


def kept(n: Need, o: Offer) -> bool:
    return R.explain(n, o)[1] is None


def why(n: Need, o: Offer) -> str:
    return R.explain(n, o)[1] or ""


# ---------------------------------------------------------------- samsung s24 ultra: spellings and a cracked camera
S24 = need("samsung galaxy s24 ultra")


@pytest.mark.parametrize("title", ["Samsung Galaxy S 24 Ultra 256 GB", "Samsung Galaxy S 24 Ultra mit S pen",
                                   "Samsung galaxy 24 ultra 256 gb", "Samsung Galaxy s24ultra 256GB Top Zustand",
                                   "Sprzedam Samsung s24ultra 256GB", "Samsung S 24 ULTRA"])
def test_s24_ultra_spelled_with_a_space_or_glued_is_the_s24_ultra(title):
    assert kept(S24, row(title, 480, "kleinanzeigen.de")), why(S24, row(title, 480, "kleinanzeigen.de"))


def test_other_galaxy_models_stay_out():
    assert "different model" in why(S24, row("Samsung Galaxy S25 Ultra 512gb", 700))
    assert not kept(S24, row("Samsung Galaxy S24 Plus 256GB", 500))


@pytest.mark.parametrize("text,word", [
    ("Stan dobry tylko pęknięcie na jednym aparacie", "pęknięcie"),
    ("Gebruikte dyson steelstofzuiger. Komt in complete set. Accu dient vervangen te worden.", "Accu dient vervangen"),
    ("Akku muss getauscht werden", "Akku muss getauscht"),
    ("Honor magic 7 lite näyttörikki", "näyttörikki"),
    ("Apple MacBook Air M2 (2022) - AZERTY - Oplaadprobleem", "Oplaadprobleem"),
    ("MacBook Air 13 inch m2 8GB 256GB | spatiebalk plakt", "plakt"),
    ("Samsung Galaxy S24 Ultra met gebreken", "gebreken"),
])
def test_damage_words_in_every_language_are_broken(text, word):
    flags = R.listing_red_flags(text, S24, title=False)
    assert flags and flags[0][0] == "broken" and flags[0][2] == word


def test_negated_damage_is_not_a_flag():
    assert R.listing_red_flags("Kein Riss, top Zustand", S24, title=False) == []


def test_off_platform_or_dm_price_talk_is_a_scam_signal():
    ps5 = need("ps5")
    assert R.listing_red_flags("Very new and dm to discuss price", ps5, title=False)[0][0] == "scam"
    assert R.listing_red_flags("Kontakta mig på WhatsApp", ps5, title=False)[0][0] == "scam"
    assert R.listing_red_flags("Toimii hyvin, nouto Helsingistä", ps5, title=False) == []


# ---------------------------------------------------------------- bicycles: subtypes are bicycles, parts are not
FIETS = need("bicycle", CYCLING, raw="fiets")


@pytest.mark.parametrize("title", ["Cannondale Habit Carbon SE täysjousitettu maastopyörä L 29\"",
                                   "Helkama FE12 sähköfatbike M", "Giant Mountain Bike, size M, €150",
                                   "Tunturi miesten kaupunkipyörä 28\"/700c", "Specialized Allez E5 Elite Road Bike 2022"])
def test_a_mountain_city_road_or_e_bike_is_a_bicycle(title):
    assert kept(FIETS, row(title, 300, exact=True)), why(FIETS, row(title, 300, exact=True))


@pytest.mark.parametrize("title", ["Etuhaarukka 28\"", "Erä OnGuard Rottweiler 8026 panssarivaijerilukkoja",
                                   "Tomorrow, We Ride - Jean Bobet 9781874739517",
                                   "Hello, Bicycle - Anna Brones 9781607748830",
                                   "Bafang BBS 36V 250W keskiömoottori ja akku", "Panasonic Display - Gebruikt"])
def test_bike_parts_locks_books_and_motors_are_not_a_bicycle(title):
    assert not kept(FIETS, row(title, 60, exact=True))


def test_a_bike_with_a_lock_is_still_a_bike():
    assert kept(FIETS, row("Sähköpyörä, uusi akku ja lukko", 900, exact=True))


# ---------------------------------------------------------------- road bikes: model lines, MTB descriptions
ROAD = need("road bike", ROAD_CAT)


@pytest.mark.parametrize("title", ["Liv langma advanced pro 0 kuitukiekoilla", "Augment Road AER 2020 XS",
                                   "Uudenveroinen hiilikuiturunkoinen KTM Revelator 3500", "Áspero-5 Shimano GRX Di2",
                                   "Aika-ajo pyörä, All Carbon + DuraAce Di2", "Nishiki Competition Bike"])
def test_road_model_lines_and_groupsets_name_a_road_bike(title):
    assert kept(ROAD, row(title, 1500, exact=True)), why(ROAD, row(title, 1500, exact=True))


def test_a_road_frameset_is_a_frame():
    assert "frame alone" in why(ROAD, row("Cannondale System Six Liquigas -runkosetti", 350, exact=True))


@pytest.mark.parametrize("desc,word", [('Specialized Hardrock Comp 28". Hyvä työmatkapyörä.', "Hardrock"),
                                       ("Hyvä kunto, 3-vaihdetta, kori mukana", "3-vaihdetta")])
def test_a_description_naming_an_mtb_or_a_3_speed_vetoes_the_road_bike_pick(desc, word):
    flags = R.listing_red_flags(desc, ROAD, title=False)
    assert flags and flags[0][0] == "kind" and word in flags[0][2]
    assert R.listing_red_flags("Kevyt hiilikuitu, Ultegra 2x11, ei maastopyörä", ROAD, title=False) == []


# ---------------------------------------------------------------- phones: tablets and watches in the phone category
@pytest.mark.parametrize("n", [need("puhelin"), need("Mobile & Smart Phones", PHONE_CAT)])
@pytest.mark.parametrize("title", ["iPad 10th Generation 64 GB", "Brugt Samsung Galaxy Watch 5",
                                   "Samsung Galaxy Watch 8 LTE 44mm", "Google Pixel Watch 5 45mm LTE"])
def test_tablets_and_watches_are_not_phones(n, title):
    assert "another kind of thing" in why(n, row(title, 200, "blocket.se", exact=True))


def test_a_phone_sold_with_a_watch_is_a_phone_and_rep_objects_are_parts():
    n = need("puhelin")
    assert kept(n, row("Samsung Galaxy S23 + Galaxy Watch 6", 400, exact=True))
    assert not kept(n, row("2 stk Apple iPad – rep/deleobjekter", 53, "finn.no"))


# ---------------------------------------------------------------- robot vacuum: the category's words in every language
ROBO = need("robotti-imuri", ROBOVAC, raw="robotti-imuri alle 300", budget=300.0)


@pytest.mark.parametrize("title,source", [("Roborock Q7 Max Saugroboter mit Wischfunktion", "kleinanzeigen.de"),
                                          ("iRobot Roomba j7+ Robotstofzuiger - Nieuwstaat", "marktplaats.nl"),
                                          ("Xiaomi Robot Vacuum E5 robotdammsugare", "blocket.se"),
                                          ("Ecovacs DEEBOT N8 Pro robotstøvsuger", "dba.dk")])
def test_foreign_robot_vacuums_match_the_finnish_word(title, source):
    assert kept(ROBO, row(title, 120, source)), why(ROBO, row(title, 120, source))


@pytest.mark.parametrize("title", ["Terskelrampe til Robotstøvsugere", "2 stk. Edgevise mopp til Roborock S8 robotstøvsuger",
                                   "Zubehörset für Dreame D10 Saugroboter"])
def test_things_for_a_robot_vacuum_are_not_one(title):
    assert not kept(ROBO, row(title, 10, "finn.no"))


# ---------------------------------------------------------------- winter tyres: one size token, the season matters
TYRES = need("talvirenkaat 205/55 r16", raw="talvirenkaat 205/55 R16")


@pytest.mark.parametrize("title", ["205/55 R16 käytetyt nastarenkaat", "UUSI nastar. 205/55-16 Goodyear Ultra Grip Arctic",
                                   "Piggfrie vinterdekk - 205/55R16 91H", "Vinterdäck 205/55R16 94T XL",
                                   "205/55R16\" Käytetyt Kitkarenkaat", "Vinterdäck 205/55/16", "dubbdäck 205 55 16",
                                   "Continental vinterdæk 205, 55, R16 på stålfælg"])
def test_winter_tyres_in_the_asked_size_are_kept(title):
    assert kept(TYRES, row(title, 200)), why(TYRES, row(title, 200))


@pytest.mark.parametrize("title", ["205/55 R16 käytetyt kesärenkaat", "Sommerreifen 2x 205/55 R16", "Opony letnie 205/55 R16",
                                   "Hankook Kinergy Eco 205/55 R16", "Viking ProTech NewGen 205/55R16"])
def test_summer_tyres_are_not_winter_tyres(title):
    assert "summer tyres" in why(TYRES, row(title, 200))


def test_another_tyre_size_is_another_model():
    assert "different model (t205x60r16" in why(TYRES, row("205/60 R16 92V nastat", 120))
    assert R.signature("Volvo V70 2.4 2005, 205 hv").models == ("v70",)


# ---------------------------------------------------------------- kahvinkeitin: a drip coffee maker
COFFEE = need("kahvinkeitin", COFFEE_DIY)


@pytest.mark.parametrize("title", ["Kaffebryggare", "Mintgrön kaffebryggare Smeg", "Bodum kaffebrygger",
                                   "Sage Precision Brewer", "Moccamaster KBG Select kahvinkeitin"])
def test_drip_coffee_makers_in_every_language_are_kept(title):
    assert kept(COFFEE, row(title, 40, "blocket.se")), why(COFFEE, row(title, 40, "blocket.se"))


@pytest.mark.parametrize("title", ["Nespresso Pixie D60 -kahvikone", "L’OR Barista kapselikone", "Jura Z9 One Touch",
                                   "Siemens EQ500 integral", "DeLonghi Dedica EC685", "Moccamaster kahvinkeitin runko",
                                   "kaffefilter hållare till Moccamaster"])
def test_capsule_automatic_espresso_bodies_and_holders_are_not_a_drip_maker(title):
    assert not kept(COFFEE, row(title, 40, "blocket.se"))


# ---------------------------------------------------------------- lego technic: set numbers and local spellings
LEGO = need("lego technic")


@pytest.mark.parametrize("title", ["Lego 42226 BMW M4 GT3 nowe", "Lego 42029 Gruvlastare", "Lego 42204",
                                   "Lego Technik Auto Lamborghini", "Lego tehnik traktor"])
def test_technic_sets_by_number_or_local_spelling_are_technic(title):
    assert kept(LEGO, row(title, 40, "blocket.se")), why(LEGO, row(title, 40, "blocket.se"))


def test_other_lego_lines_and_parts_lots_stay_out():
    assert "another product line" in why(LEGO, row("LEGO City 60337 juna", 40))
    assert not kept(LEGO, row("LEGO Bionicle- och Technic-delar", 15, "blocket.se"))


# ---------------------------------------------------------------- shops that are not shops / category pages
@pytest.mark.parametrize("url,title", [("https://mobiili.fi/puhelin/apple_iphone_13/", "Apple iPhone 13"),
                                       ("https://hinta.fi/123/apple-iphone-13", "Apple iPhone 13 256GB musta, 1138€ | Hinta.fi"),
                                       ("https://www.prisma.fi/kategoriat/997/lego-technic", "LEGO - Technic | Prisma.fi-verkkokauppa"),
                                       ("https://www.madeinfinlandshop.fi/c10302/sofas-sofa-beds", "Sofas & sofa beds | Made in Finland Shop")])
def test_comparison_sites_and_category_urls_are_not_offers(url, title):
    assert R.not_an_offer(Offer(url=url, source="x", title=title, price=329, currency="EUR"))


# ---------------------------------------------------------------- kitchen table: other tables and chairs
@pytest.mark.parametrize("title", ["Massiivitammiset pinnatuolit", "Pöydän kansilevy", "Brafab Bigby ulkoruokapöytä",
                                   "Maison Exclusive - Valkoinen baaripöytä Ø60x110 cm"])
def test_chairs_tabletops_outdoor_and_bar_tables_are_not_kitchen_tables(title):
    assert "another kind of thing" in why(need("kitchen table", TABLES), row(title, 60))


def test_a_table_with_chairs_is_a_kitchen_table():
    assert kept(need("kitchen table", TABLES), row("Ruokapöytä + 6 tuolia", 200))


# ---------------------------------------------------------------- camera body: kits on every site
@pytest.mark.parametrize("title", ["Sony A7 III + Sigma 24-70mm f/2.8 DG DN II Art", "Sony A7 III + Zeiss 16-35mm F4.0 Lens",
                                   "Sony A7 III (SC 2,870) + 2 Lenses – Tamron 17–28", "Sony A73 m. Sigma 35mm 1.4+..."])
def test_lens_kits_are_kits_whatever_the_site(title):
    assert R.signature(title).kit
    assert not R.signature("Sony A7 III runko + 2 akkua").kit


def test_lens_kits_never_set_the_body_band():
    n = need("sony a7 iii body")
    bodies = [row("Sony A7 III body", p, "tori.fi") for p in (800, 820, 850, 870, 900)]
    kits = [row("Sony A7 III + Sigma 24-70mm f/2.8 DG DN II Art", p, "marktplaats.nl") for p in (1800, 1900, 2000)]
    J.judge(n, R.resolve(n, bodies + kits), history=False)
    assert all(k.raw.get("with_lens") for k in kits)
    assert max(J.market_prices(bodies + kits, "used")) <= 900


# ---------------------------------------------------------------- services
def test_car_insurance_needs_the_cover_named_and_no_savings_page():
    n = svc("car insurance", "Finland")
    assert "investment or savings" in why(n, page("https://www.lahitapiola.fi/henkilo/",
                                                  "LähiTapiola Sijoittaminen – Suomen luotetuin vakuutusyhtiö", 30, "month"))
    assert "no cover named" in why(n, page("https://www.ayvens.com/en-fi/our-services/full-cover-insurance/",
                                           "Ayvens Comprehensive Insurance", 53, "month"))
    assert kept(n, page("https://www.if.fi/henkiloasiakkaat/vakuutukset/autovakuutus", "Autovakuutus | If", 25, "month"))


def test_a_parking_ban_permit_is_an_add_on_not_the_move():
    n = svc("umzugsfirma 2-zimmer-wohnung", "Hamburg", raw="Umzugsfirma Hamburg 2-Zimmer-Wohnung")
    assert "add-on" in why(n, page("https://www.immobilienscout24.de/umzug/halteverbot.html", "Halteverbotszone", 99))
    good = page("https://www.umzugslogistik.hamburg/preise", "Umzug für kleine 1-2 Zimmer Wohnung (bis 60 m²)", 400)
    assert kept(n, good) and J.fits_job_size(n, good)


def test_directory_self_rows_are_not_providers():
    n = svc("home cleaning 24m2", "Tilburg", raw="home cleaning tilburg 24m2")
    assert "directory" in why(n, page("https://trustoo.nl/tilburg/schoonmaakbedrijf/", "schoonmaakbedrijf – Trustoo", 20, "hour"))
    assert "directory" in why(n, page("https://www.ikzoekeenschoonmaakster.nl/schoonmaakster-tilburg",
                                      "Schoonmaakster Tilburg gezocht? - Ikzoekeenschoonmaakster.nl", 18, "hour"))
    named = page("https://trustoo.nl/tilburg/schoonmaakbedrijf/ambiance/", "home cleaning – Ambiance Schoonmaakdiensten",
                 15, "hour", seller="Ambiance Schoonmaakdiensten")
    assert J._who(named) == "Ambiance Schoonmaakdiensten (via trustoo.nl)"


def test_aggregator_rows_name_the_restaurant_and_merge():
    a = page("https://www.lounasmenu.fi/keskusta/#unicafe", "Lounas", 8.7, "person", seller="UniCafe Kaivopiha",
             location="Helsinki")
    b = page("https://luncher.fi/unicafe", "Lounas", 9.8, "person", seller="UniCafe Kaivopiha", location="Helsinki")
    assert J._dedupe_service([a, b]) == [a]
    assert J._who(a) == "UniCafe Kaivopiha (via lounasmenu.fi)"


# ---------------------------------------------------------------- pricing: floor, vehicles, vinted fee, bulky delivery
def test_floor_is_at_most_75pct_of_the_plain_used_median():
    shops = [Offer(url=f"https://www.{s}/p/1", source=s, title="Apple iPhone 13 128GB", price=549, currency="EUR",
                   price_eur=549, condition="new") for s in ("gigantti.fi", "verkkokauppa.com")]
    market = [row("Apple iPhone 13 128 Gt", p) for p in [180, 190, 195, 200, 200, 205, 210, 220, 230, 240] * 2]
    ref = J.reference_price(shops + market, J.category_for("iphone 13"), need("iphone 13"))
    assert ref is not None and ref.floor_eur <= 0.75 * 202.5 + 0.01


def test_one_car_model_is_a_mixed_bag_of_years():
    n = need("volvo v70", {"id": "sp:vp-2-2-1", "label": "Cars, Trucks & Vans", "source": "classified"})
    cars = [row(f"Volvo V70 {y}", p, "nettiauto.com", category="vehicle")
            for y, p in [(2001, 700), (2003, 900), (2012, 4000), (2014, 4500), (2015, 5000), (2016, 5500)]]
    J.judge(n, R.resolve(n, cars), history=False)
    assert not any("under a quarter" in f for f in cars[0].flags)


def test_vinted_buyer_protection_fee_is_always_in():
    o = row("Nintendo Switch OLED", 134.95, "vinted.fi")
    assert J.buyer_fee(o) == round(0.70 + 0.05 * 134.95, 2) and o.raw["buyer_fee_est"]


def test_bulky_new_without_delivery_gets_an_estimate():
    n = need("kitchen table", TABLES)
    o = Offer(url="https://www.homeroom.fi/p/plaza", source="homeroom.fi", title="Venture Home Ruokapöytä Plaza - Musta",
              price=112.4, currency="EUR", price_eur=112.4, condition="new")
    J._bulky_delivery(o, n)
    assert o.shipping_eur == 50.0 and "delivery not on the page" in o.flags[-1]


def test_reference_is_per_version():
    assert J._tier_key("Sony PlayStation 5 Pro 2TB") == frozenset({"pro"})
    assert J._tier_key("PS5 Slim Edition") == J._tier_key("ps5")
