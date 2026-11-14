"""Round-3 judges' relevance / pricing / verdict defects, as offline regressions.

Titles, prices and sites are copied from the live streams the judges read (eval r3, 14 Nov). Each test names the
defect it pins down; every fix is a rule per listing (never a blocked site).
"""
from __future__ import annotations

import pytest

from agora import judge as J
from agora import resolve as R
from agora.models import Need, Offer

CARS = {"id": "sp:vp-2-2-1", "label": "Cars, Trucks & Vans", "source": "classified", "confidence": 0.9}
PHONE_CAT = {"id": "sp:el-4-8-5", "label": "Mobile & Smart Phones", "source": "tree", "confidence": 1.0}
STROLLER_CAT = {"id": "sp:bt-6-3", "label": "Baby Strollers", "source": "classified", "confidence": 0.9}
SOFA_CAT = {"id": "sp:fr-22", "label": "Sofas", "source": "classified", "confidence": 0.9}
ROAD_CAT = {"id": "sp:sg-4-4-3-11", "label": "Road Bikes", "source": "tree", "confidence": 1.0,
            "labels": {"en": "Road Bikes", "fi": "Maantiepyörät", "de": "Rennräder"}}
CONSOLE_CAT = {"id": "sp:el-19", "label": "Video Game Consoles", "source": "classified", "confidence": 0.9}
ROBOVAC_CAT = {"id": "sp:hg-9-10-5", "label": "Robotic Vacuums", "source": "classified", "confidence": 0.9}


def need(thing: str, cat: dict | None = None, **kw) -> Need:
    return Need(raw=kw.pop("raw", thing), thing=thing, category=cat, **kw)


def svc(thing: str, where: str = "Helsinki") -> Need:
    return Need(raw=f"{thing} {where}", thing=thing, kind="service", where=where, conditions=["service"])


def row(title: str, price: float = 100.0, source: str = "tori.fi", condition: str = "used", **raw) -> Offer:
    site = source.split(".")[0]
    return Offer(url=f"https://www.{source}/item/{abs(hash((title, price, source))) % 10**9}", source=source,
                 title=title, price=price, currency="EUR", price_eur=price, condition=condition,
                 raw={"site": site, "from_list_page": f"https://www.{source}/search", **raw})


def exact(title: str, price: float = 100.0) -> Offer:
    return row(title, price, category_page={"exact": True})


def shop(title: str, price: float, url: str, condition: str = "new", **kw) -> Offer:
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price, currency="EUR",
                 price_eur=price, condition=condition, **kw)


def kept(n: Need, o: Offer) -> bool:
    return R.explain(n, o)[1] is None


def why(n: Need, o: Offer) -> str:
    return R.explain(n, o)[1] or ""


# ---------------------------------------------------------------- volvo v70: other makes, junk cars, model pages
VOLVO = need("volvo v70", CARS)


def car(title: str, price: float = 2000.0) -> Offer:
    return row(title, price, "nettiauto.com", category="vehicle")


@pytest.mark.parametrize("title", ["Saab 96", "Peugeot 206", "Nissan Almera", "Talbot Horizon Volkswagen"])
def test_a_cars_category_row_of_another_make_is_not_the_volvo(title):
    assert not kept(VOLVO, car(title))
    if title == "Saab 96":
        assert "another make (Saab)" in why(VOLVO, car(title))


@pytest.mark.parametrize("title", ["Volvo V70", "Volvo V70 2.0 d4 Polar plus edition geartronic",
                                   "Volvo V70 2.4-20 Sportswagon A", "Käytetty (2010) Volvo V70 Kinetic 175 HP"])
def test_real_v70s_are_kept_whatever_their_trim_words(title):
    assert kept(VOLVO, car(title))


def test_a_volvo_naming_no_model_is_not_shown_to_be_the_v70():
    assert "names no model" in why(VOLVO, car("Volvo 940"))
    assert not kept(VOLVO, car("Volvo V50"))


def test_a_make_model_page_is_no_offer():
    o = shop("Volvo V70", 988, "https://www.mobile.de/en/car/volvo/v70", "used")
    assert R.not_an_offer(o)


def test_a_whole_car_for_100_euros_is_never_the_pick_nor_the_band():
    n = need("car", CARS, must_have=["bright red"])
    junk = [car("Talbot Horizon", 100), car("Fiat Punto 1.2 2003 210 tkm", 200), car("Opel Astra", 250)]
    real = [car(f"Ford Mondeo 2.0 TDCi 2016 {i}", 6500 + 400 * i) for i in range(4)]
    things = R.resolve(n, junk + real)
    v = J.judge(n, things, history=False)
    assert "nettiauto.com" in v.headline and "€100" not in v.headline
    talbot = next(o for t in things for o in t.offers if o.title == "Talbot Horizon")
    assert J._risky(talbot)
    assert all(p >= 500 for p in J.used_comps([o for t in things for o in t.offers]))


# ---------------------------------------------------------------- iphone 13: the floor comes from what sellers ask
def test_used_floor_follows_the_used_market_when_the_new_price_is_stale():
    n = need("iphone 13")
    shops = [shop("Apple iPhone 13 128GB", p, f"https://www.shop{i}.fi/p/{i}") for i, p in enumerate([598, 598, 610])]
    market = [row(f"Apple iPhone 13 128 GB {i}", p, "finn.no") for i, p in
              enumerate([160, 170, 175, 180, 185, 189, 195, 199, 205, 210, 215, 220, 225, 228, 230, 235, 240, 245])]
    ref = J.reference_price(shops + market, J.category_for("iphone 13"), n)
    assert ref is not None and ref.floor_basis and ref.floor_eur < 189
    assert J.reference_flag(market[5], ref, J.category_for("iphone 13")) is None     # €189: an ordinary one
    assert J.reference_flag(row("Apple iPhone 13", 90, "finn.no"), ref, J.category_for("iphone 13"))


# ---------------------------------------------------------------- dyson v15
DYSON = need("dyson v15")


@pytest.mark.parametrize("title", ["Akku Staubsauger DYSON V15 DETECT Absolute +STÄNDER + WISCHER",
                                   "Dyson v15 detect Akku Staubsauger in Moers",
                                   "Lite brukt: Dyson V15 Detect Absolute støvsuger",
                                   "Dyson V15s Detect Submarine – sladdlös dammsugare med våttorkning"])
def test_whole_dyson_v15s_are_kept(title):
    assert kept(DYSON, row(title, 450, "kleinanzeigen.de"))


@pytest.mark.parametrize("title", ["Dyson V15 Ersatzakku", "Originalt Dyson V15s Detect Submarine tilbehør",
                                   "Ny original Dyson-lader til V15 Detect Absolute", "Moppaussuulake Dyson V15s Submarine",
                                   "Dyson dammsugare", "Dyson ledningsfri støvsuger"])
def test_dyson_parts_and_unnamed_models_are_not_the_v15(title):
    assert not kept(DYSON, row(title, 200, "dba.dk"))


# ---------------------------------------------------------------- sony a7 iii shorthand
@pytest.mark.parametrize("title", ["Sony A73 m. Sigma 35mm 1.4+fullt tillbehörspaket", "Mark 7iii", "Sony a7m3"])
def test_a7_iii_shorthand_is_the_a7_iii(title):
    assert kept(need("sony a7 iii body"), row(title, 900, "blocket.se"))


def test_a7_shorthand_never_takes_another_model():
    n = need("sony a7 iii body")
    assert not kept(n, row("Samsung Galaxy A73", 300, "blocket.se"))
    assert not kept(n, row("Sony A7R3", 900, "blocket.se"))


# ---------------------------------------------------------------- kahvinkeitin: flyers; lane lines far off
def test_a_store_flyer_page_is_no_offer():
    o = shop("KAHVINKEITIN VAALEANPUNAINEN", 14.99, "https://promotheus.fi/halpa-halli-tarjoukset/tarjouslehti-79434-0#page_25")
    assert "flyer" in (R.not_an_offer(o) or "")


def test_a_refurbished_lane_five_times_the_used_price_is_left_out_of_the_headline():
    good = [row(f"Moccamaster kahvinkeitin {i}", p) for i, p in enumerate([25, 30, 35, 40])]
    refurb = shop("Kahvinkeitin", 330, "https://www.marktplaats.nl/v/1", "refurbished")
    head = J.all_in_headline(good + [refurb], good[0], [])
    assert "efurbished" not in head


# ---------------------------------------------------------------- generic needs: fuzzy search rows, parts, rentals
@pytest.mark.parametrize("title", ["Puhelin/avainnauha uusi, Kunto: Uusi", "Puhelin kalansilmä kamera, Tuotemerkki: Huawei",
                                   "Gimbel puheliin kuva video, Tuotemerkki: DJI",
                                   "New Yorker musta strassikoristeinen käsilaukku, Kunto: Hyvä"])
def test_vinted_junk_is_not_a_phone(title):
    assert not kept(need("puhelin", PHONE_CAT), row(title, 20, "vinted.fi"))


@pytest.mark.parametrize("title", ["Vaaleanpunainen lastenvaunu keramiikka koriste/kukkaruukku, Kunto: Hyvä",
                                   "Vaunulelu, Tuotemerkki: Clementoni, Kunto: Hyvä", "Pieni huovutettu viltti, Kunto: Hyvä",
                                   "Lukitusvaijeri, Tuotemerkki: Ei tietoa", "Rött myggnät till barnvagn"])
def test_vinted_junk_is_not_a_pram(title):
    assert not kept(need("kinderwagen", STROLLER_CAT), row(title, 5, "vinted.fi"))


@pytest.mark.parametrize("title", ["Rikkaimuri, Tuotemerkki: OBH Nordica", "Electrolux varsi-imuri, Tuotemerkki: Electrolux"])
def test_other_vacuums_are_not_a_robot_vacuum(title):
    assert not kept(need("robotti-imuri", ROBOVAC_CAT), row(title, 20, "vinted.fi"))


@pytest.mark.parametrize("title", ["Brio lastenrattaiden istuinosa", "Bugaboo donkey istuin kankaat",
                                   "Twistshake rattaiden lisäosia", "Petite Chérie rattaiden istuinpehmuste",
                                   "Emmaljunga vaunukoppa", "VUOKRATAAN Ora Aina matkarattaat"])
def test_exact_stroller_page_still_drops_parts_and_rentals(title):
    assert not kept(need("baby stroller", STROLLER_CAT), exact(title, 5))


def test_exact_stroller_page_keeps_prams():
    assert kept(need("baby stroller", STROLLER_CAT), exact("Bugaboo Fox 3 yhdistelmävaunut", 400))


@pytest.mark.parametrize("title", ["Askon taivutettaessa tarjotintaso", "penkki", "yhden hengen vuode"])
def test_exact_sofa_page_drops_trays_benches_and_beds(title):
    assert not kept(need("sofa", SOFA_CAT), exact(title, 5))


@pytest.mark.parametrize("title", ["Ikea Hemnes sohvasänky", "Asko Sofie sohvasänky 80-160 x 200", "Ikea Kivik divaani",
                                   "Karup Design Roots vuodesohvan runko ilman patjaa", "Vuodesohva"])
def test_sofa_beds_and_divans_are_sofas(title):
    assert kept(need("sofa", SOFA_CAT), exact(title, 150))


@pytest.mark.parametrize("title", ["Stella Veneta Cycloman stemmi", "Shimano M525", "Nopsa rungo", "Myydään", "kiva fillari",
                                   "Helkama Nice power 7-vaihteinen", 'Champion Acrobat 26"'])
def test_exact_road_bike_page_drops_parts_and_plain_bikes(title):
    assert not kept(need("Road Bikes", ROAD_CAT), exact(title, 50))


@pytest.mark.parametrize("title", ["Felt Z85 maantiepyörä 56 cm – Shimano 105 & Ultegra-kiekot",
                                   "Chebici maantiepyörä 51/S + Mavic Cosmic Elite kiekot", "Peugeot PSV10kilpapyörä vm 1984",
                                   "Canyon Endurace AL 2019"])
def test_road_bikes_with_extras_or_another_word_are_kept(title):
    assert kept(need("Road Bikes", ROAD_CAT), exact(title, 600))


@pytest.mark.parametrize("title", ["Apple iPhone 16 128 GB Sort + 5 cover", "Apple iPhone 16 128 GB inkl 3 covers",
                                   "Google Pixel 10 – 256 GB (Frost) + 3 covers"])
def test_a_phone_with_covers_included_is_a_phone(title):
    assert kept(need("puhelin", PHONE_CAT), row(title, 450, "dba.dk"))


# ---------------------------------------------------------------- ps5: drives, wanted ads, the Pro
@pytest.mark.parametrize("title", ["Corsair MP600 Elite SSD 2Tb kiintolevy PS5 konsolille", "WD_BLACK SN850P 2TB NVMe SSD – PS5 / PC",
                                   "(Oöppnad) Corsair MP600 Elite 2TB PS5 NVMe SSD", "Söker ps5"])
def test_ps5_drives_and_wanted_ads_are_not_the_console(title):
    assert not kept(need("ps5", CONSOLE_CAT), row(title, 430, "blocket.se"))


@pytest.mark.parametrize("title", ["Ps5 pro", "PS5 Pro pelikonsoli, 2 ohjainta", "PS5 Digital 825GB SSD", "PS5 + 2TB SSD"])
def test_a_bare_ps5_takes_the_pro_and_spec_titles(title):
    assert kept(need("ps5", CONSOLE_CAT), row(title, 450))


def test_iphone_pro_is_still_another_version():
    assert not kept(need("iphone 15"), row("iPhone 15 Pro", 700))


# ---------------------------------------------------------------- switch oled word order
@pytest.mark.parametrize("title", ["Nintendo Switch - Vit OLED", "Nintendo Switch spelkonsol OLED",
                                   "Nintendo Switch OLED+12 magiska spelklassiker", "Nintendo Switch Oled+Sd card",
                                   "Konsola Nintendo Switch Oled+gra", "Nintendo Switch Console Set OLED Wit in Doos"])
def test_switch_oled_after_other_words(title):
    assert kept(need("nintendo switch oled"), row(title, 250, "blocket.se"))


def test_switch_lite_and_not_oled_stay_out():
    n = need("nintendo switch oled")
    assert not kept(n, row("Nintendo Switch Lite", 120))
    assert not kept(n, row("Nintendo Switch (EJ OLED)", 150))


# ---------------------------------------------------------------- broken / not working
@pytest.mark.parametrize("text", ["Xiaomi robotti-imuri korjattavaksi", "Xiaomi robotti-imuri ilman akkua",
                                  "Pyörät eivät kunnolla käänny"])
def test_not_working_is_a_red_flag(text):
    assert any(k == "broken" for k, _, _ in R.listing_red_flags(text, need("robotti-imuri"), title=False))


# ---------------------------------------------------------------- lego technic: the line asked
LEGO = need("lego technic")


@pytest.mark.parametrize("title", ["LEGO Speed Champions 77260 Toyota Supra MK4", "LEGO City 30735 Hot rod -auto",
                                   "Tabouret Lego en travertin - Edition limitée", "LEGO Technic ohjekirja setille 8259",
                                   "Ohjekirja settiin Telanosturi , Lego Technic , 42042"])
def test_lego_technic_needs_the_line_and_a_set(title):
    assert not kept(LEGO, row(title, 20, "proshop.fi"))


@pytest.mark.parametrize("title", ["LEGO Technic 42115 Lamborghini Sián", "Lego Technic 42042 telanosturi, ohjekirja mukana"])
def test_lego_technic_sets_kept(title):
    assert kept(LEGO, row(title, 60))


def test_a_product_line_pick_sits_in_the_usual_range():
    offers = [row("LEGO Technic Monster Jam 42149", 9)] + [row(f"LEGO Technic 4{2000 + i}", p) for i, p in
                                                           enumerate([40, 45, 50, 55, 60, 65, 70])]
    v = J.judge(LEGO, R.resolve(LEGO, offers), history=False)
    assert "€9 " not in v.headline


# ---------------------------------------------------------------- macbook air m2: part numbers and screen sizes
@pytest.mark.parametrize("title", ['Apple MacBook Air 2023 MQKU3H/A 15" 256 GB', "Uåpnet: MacBook Air 13 (2022) 512GB"])
def test_m2_air_by_part_number_or_year(title):
    assert kept(need("macbook air m2"), row(title, 900, "finn.no"))


def test_refurbed_new_price_beside_the_price_is_no_dispute():
    o = shop('FAIR Apple MacBook Air 2022 | 13.6" | M2 699 € 1 499 € (Uusi...', 699,
             "https://www.refurbed.fi/p/fair-apple-macbook-air-m2-2022/489539c/", "refurbished", read_via="jsonld",
             raw={"witnesses": [{"via": "jsonld", "price": 699, "currency": "EUR", "primary": True},
                                {"via": "snippet", "price": 1499, "currency": "EUR", "primary": False}]})
    assert J.verify_price(o) is None and o.raw["price_check"] is None


# ---------------------------------------------------------------- fiets: a category page from a snippet
def test_a_category_snippet_with_a_price_range_is_no_offer():
    o = shop("Polkupyörät parhailta merkeiltä | Intersport", 109, "https://www.intersport.fi/fi/laji/pyoraily/polkupyorat/",
             read_via="search_highlight",
             raw={"search_text": "edullisimmat polkupyörät -kategorian tuotteet saat hintaan 109.00 € ja hintavimmat 10999.00 €"})
    assert R.not_an_offer(o)


# ---------------------------------------------------------------- gift for mom
def test_an_adult_product_is_never_a_gift_for_mom():
    o = shop("Womanizer Delight Box Lahjapakkaus Naisille", 127, "https://www.sinful.fi/p/1")
    assert "adult product" in why(need("gift for mom"), o)


# ---------------------------------------------------------------- services
@pytest.mark.parametrize("title,url", [
    ("Otsatukan leikkaus – Parturi-kampaamo Karrar Oy", "https://www.fresha.com/a/karrar-oy-helsinki-x"),
    ("Leikkaus 15 min", "https://www.saloncaramel.fi/hinnasto/"),
    ("Cornrows (All Back)", "https://www.fresha.com/a/braids-helsinki-y"),
    ("Hair Cut – LA CASA DE BARBER", "https://www.fresha.com/a/la-casa-de-barber-tampere-hameenkatu-1"),
    ("Hiusten leikkaus – Lumme Salonki", "https://www.fresha.com/a/lumme-salonki-klaukkala-x")])
def test_haircut_add_ons_and_other_towns_are_not_a_helsinki_haircut(title, url):
    o = shop(title, 15, url, "service", unit="job")
    assert not kept(svc("haircut"), o)


def test_a_helsinki_or_metro_salon_from_its_slug_is_kept():
    for url in ("https://www.fresha.com/a/barber-helsinki-mannerheimintie-1", "https://www.fresha.com/a/barber-espoo-x"):
        assert kept(svc("haircut"), shop("Hair Cut", 30, url, "service", unit="job"))


def test_a_rupee_price_is_never_a_local_photographer():
    o = shop("Pre-Wedding Shoot", 288, "https://www.wedmegood.com/vendors/x", "service", unit="job", location="Helsinki")
    o.currency, o.price = "INR", 30000
    assert "abroad" in why(svc("wedding photographer"), o)


def test_a_country_only_provider_is_not_the_pick_for_a_town():
    n = svc("plumber", "Berlin")
    far = shop("Stundensatz Monteur", 60, "https://fragbabsi.de/sanitaer", "service", unit="hour", location="Deutschland")
    near = shop("Klempner Stundensatz", 70, "https://www.a-klempner-berlin.de/preise", "service", unit="hour",
                location="Berlin")
    assert R.not_shown_local(n, far) and not R.not_shown_local(n, near)
    v = J.judge(n, R.resolve(n, [far, near]), history=False)
    assert v.best_offer_url == near.url


def test_a_per_km_fee_is_no_call_out_estimate():
    n = svc("plumber")
    a = shop("Putkimies tuntiveloitus", 40, "https://suomalainenputkimies.fi/hinnat", "service", unit="hour",
             raw={"callout_fee": 0.46})
    b = shop("Putkimies tuntihinta", 55, "https://manofix.fi/hinnasto", "service", unit="hour")
    J._estimate_missing_minimums(n, [a, b])
    assert "est_callout_fee" not in b.raw
    tc = J.service_cost(a, n)
    assert tc is not None and not any("call-out" in lbl for lbl, _ in tc.receipt)


def test_instalments_are_multiplied():
    o = shop("Epic hääkuvaus (neljä maksuerää)", 215, "https://nikistrbian.com/hinnasto", "service", unit="job")
    tc = J.service_cost(o, svc("wedding photographer"))
    assert tc is not None and tc.total_eur == 860


def test_a_cheap_monthly_plan_among_few_agencies_is_not_a_fake():
    n = Need(raw="unlimited graphic design subscription", thing="unlimited graphic design subscription",
             kind="service", conditions=["service"])
    plans = [shop(f"Design plan {i}", p, f"https://agency{i}.com/pricing", "service", unit="month")
             for i, p in enumerate([265, 799, 857, 899, 995, 1200])]
    trust, flags = J.assess_trust(plans[0], plans)
    assert not any(f.startswith("too good") for f in flags)


def test_a_marketing_agency_is_no_design_subscription():
    n = Need(raw="unlimited graphic design subscription", thing="unlimited graphic design subscription",
             kind="service", conditions=["service"])
    o = shop("Ninjapromo Weekly Reports – NinjaPromo – Full-Service Digital Marketing Agency", 12800,
             "https://ninjapromo.io/pricing", "service", unit="month")
    assert "marketing agency" in why(n, o)


def test_a_calculator_estimate_is_no_insurer_price():
    n = svc("car insurance", "Finland")
    o = shop("Arvioitu autovakuutus (liikennevakuutus + kasko)", 350, "https://selkoraha.fi/autovakuutus", "service",
             unit="year")
    assert not kept(n, o)


# ---------------------------------------------------------------- verdict text
def test_headline_names_a_pick_that_is_not_the_words_asked():
    n = need("volvo v70")
    o = row("Volvo V70 D4 Momentum 2014 210 tkm", 7900, "nettiauto.com", category="vehicle")
    v = J.judge(n, R.resolve(n, [o]), history=False)
    assert "(Volvo V70 D4 Momentum 2014" in v.headline


def test_risky_line_is_plain_counts():
    a = row("x", 1)
    a.flags = ["too good to be true: 60% under the used median (€250)"]
    b = row("y", 1)
    b.flags = ["red flag: a swap, not a sale (“VAIHDETAAN”)"]
    line = J.risky_line([a, b, b])
    assert line == "3 offers look risky: 2 are swaps, not sales; 1 priced too low to be real"
