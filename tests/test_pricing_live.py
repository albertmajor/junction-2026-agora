"""Pricing regressions from the first live-mode hunts (Nov 14): snippet cross-checks, condition words,
resale comps, same-page duplicates and URL-locale currencies. Every case is a real search listing or
offer from those streams, trimmed."""
from __future__ import annotations

import pytest

from agora import fx, reader
from agora import judge as jd
from agora.judge import judge
from agora.models import Need, Offer, Thing

SWITCH = Need(raw="nintendo switch oled", thing="nintendo switch oled")
AIRPODS = Need(raw="airpods pro 2", thing="airpods pro 2")
DYSON = Need(raw="dyson v15 vacuum", thing="dyson v15 vacuum")


@pytest.fixture(autouse=True)
def static_fx(monkeypatch):
    monkeypatch.setattr(fx, "_rates", dict(fx.STATIC_RATES))
    monkeypatch.setattr(fx, "_rates_source", "static")


def read_offer(url: str, price: float, title: str, search_title: str, snippet: str, need: Need = SWITCH,
               cond: str = "new", via: str = "contextdev_product") -> Offer:
    o = Offer(url=url, source=reader.domain_of(url), title=title, price=price, currency="EUR", price_eur=price,
              condition=cond, read_via=via)
    reader.add_witnesses(o, via, search_title=search_title, snippet=snippet, need=need)
    return o


# ---------------------------------------------------------------- snippet witnesses

@pytest.mark.parametrize("url,price,title,snippet", [
    # 'Save up to €434.00€434.00': a saving, rendered twice, glued
    ("https://www.amazon.de/-/en/Nintendo-10010900-Switch-OLED-Modell-Weiss/dp/B098RJXBTY", 238.08,
     "Nintendo Switch (OLED-Modell) Weiss - Amazon.de",
     "Nintendo Switch (OLED-Modell) Weiss. Save up to €434.00€434.00. Returnable until Jan 15, 2027."),
    # 'Price €50 and above' is a filter label; the page price is in the listing too
    ("https://store.nintendo.com/en-ie/consoles/nintendo-switch-oled-model", 349.99,
     "Nintendo Switch - OLED Model | Consoles",
     "Price €50 and above. Nintendo Switch – OLED Model (White) €349.99 (Inc VAT) €359.99 (Inc VAT)"),
    # 'Germany from €10.60 (DPD...)' is shipping
    ("https://dt24.lv/nintendo-switch-oled-model-zelda", 313.95,
     "Nintendo Switch OLED Model Zelda: Tears of the Kingdom Limited ...",
     "Nintendo Switch OLED Model Zelda: Tears of the Kingdom Limited Edition Gold/ White EU. ... "
     "Germany from €10.60 (DPD, Latvijas Pasts) Sweden ... (refurbished) ..."),
    # Greek 'από € 1149' (was) and 'κέρδος €479' (you save): the page price €669.95 is right there
    ("https://electroline.cy/en/products/dyson-v15", 669.95, "DYSON V15 Detect Submarine Wireless HandHeld Vacuum Cleaner",
     "από € 1149.00. €669.95 κέρδος €479.05. Add to cart. See here the availability of the stores."),
    # current / was / save
    ("https://www.dyson.ie/vacuum-cleaners/cordless/v15/detect-yellow-nickel", 579.99,
     "Dyson V15 Detect™ Absolute cordless vacuum",
     "In stock. current price: €579.99. original price: Was €749.99. Save €170.00. Price includes VAT."),
])
def test_snippet_noise_never_disputes_a_page_price(url, price, title, snippet):
    o = read_offer(url, price, title, title, snippet)
    jd.verify_price(o)
    assert o.raw["price_check"] != "disputed"


def test_amazon_switch_oled_is_costed_and_wins_new():
    amazon = read_offer("https://www.amazon.de/-/en/Nintendo-10010900-Switch-OLED-Modell-Weiss/dp/B098RJXBTY",
                        238.08, "Nintendo Switch (OLED-Modell) Weiss", "Nintendo Switch (OLED-Modell) Weiss - Amazon.de",
                        "Nintendo Switch (OLED-Modell) Weiss. Save up to €434.00€434.00. Returnable until Jan 15, 2027.")
    others = [Offer(url=f"https://shop{i}.de/switch-oled", source=f"shop{i}.de", title="Nintendo Switch OLED",
                    price=p, currency="EUR", price_eur=p, condition="new", seller="s")
              for i, p in enumerate((304.6, 324.44, 349.0))]
    v = judge(SWITCH, [Thing(id="t", name="Nintendo Switch OLED", offers=[amazon, *others])], history=False)
    assert amazon.true_cost is not None and not any("disagrees" in f for f in amazon.flags)
    assert "risky" not in " ".join(v.lines)


def test_a_real_misread_is_still_disputed():
    # prixretro: the page read €10.43, the listing says the median is €214
    o = read_offer("http://www.prixretro.com/en/nintendo-switch-oled/neon", 10.43,
                   "Nintendo Switch OLED Neon blue/Neon red", "Nintendo Switch OLED Neon blue/Neon red Price & Value 2026",
                   "As of 9 November 2026, the price guide value of Nintendo Switch OLED Neon blue/Neon red Complete "
                   "is €214 (median). Most sell between €205 and € ...", cond="used", via="jsonld")
    assert jd.verify_price(o).startswith("price disagrees")


def test_from_price_floor_only_disagrees_from_below():
    assert reader.witness_price("Used Sony A7 III from €789 - save €200", 239, "x.fi")[0] == 789
    assert reader.witness_price("Used Sony A7 III from €789 - save €200", 900, "x.fi") is None
    assert reader.witness_price("Buy Used & New from € 1,608 - Wedio", 1608, "wedio.com")[0] == 1608


def test_net_price_in_the_listing_is_not_a_witness():
    c = reader.witness_candidates('Switch OLED 7" (Refurbished) €74.64 Ex. VAT €90.31 Inc. fast shipping', 90.31)
    assert [a for a, *_ in c] == [90.31]


# ---------------------------------------------------------------- condition words beat schema defaults

def _ld(name: str, cond: str = "https://schema.org/NewCondition", price: str = "319.99", cur: str = "USD"):
    return {"json-ld": [{"@type": "Product", "name": name,
                         "offers": {"@type": "Offer", "price": price, "priceCurrency": cur, "itemCondition": cond,
                                    "availability": "https://schema.org/InStock"}}]}


def test_schema_new_condition_loses_to_refurbished_title():
    url = "https://www.nintendo.com/us/store/products/nintendo-switch-oled-model-white-set-refurbished/"
    o = reader.offer_from_structured(_ld("Nintendo Switch™ - OLED Model White set - REFURBISHED"), url, SWITCH)
    assert o.condition == "refurbished"
    o = reader.offer_from_structured(_ld('OLED Display for Nintendo Switch OLED 7" (Refurbished)', price="90.31",
                                         cur="EUR"), "https://www.mobilesentrix.eu/oled-display", SWITCH)
    assert o.condition == "refurbished"
    o = reader.offer_from_structured(_ld("Dyson V15 Detect käytetty", cur="EUR"), "https://shop.fi/v15", DYSON)
    assert o.condition == "used"


def test_schema_condition_kept_when_title_is_silent():
    o = reader.offer_from_structured(_ld("Nintendo Switch OLED", cond="https://schema.org/UsedCondition", cur="EUR"),
                                     "https://shop.fi/switch", SWITCH)
    assert o.condition == "used"
    o = reader.offer_from_structured(_ld("Nintendo Switch OLED", cur="EUR"), "https://shop.fi/switch", SWITCH)
    assert o.condition == "new"


# ---------------------------------------------------------------- resale comps

def _o(url: str, price: float, cond: str, title: str = "AirPods Pro 2", cur: str = "EUR") -> Offer:
    return Offer(url=url, source=reader.domain_of(url), title=title, price=price, currency=cur,
                 price_eur=fx.to_eur(price, cur), condition=cond, seller="s", in_stock=True)


def test_ear_tips_do_not_set_the_airpods_market():
    tips = _o("https://www.apple.com/ie-edu/shop/product/mwu33zm/a/airpods-pro-2-ear-tips", 10, "new",
              "AirPods Pro 2 Ear Tips - 2 sets (Medium)")
    refurb = [_o("https://www.refurbed.de/en-de/p/apple-airpods-pro-2/", 167.99, "refurbished"),
              _o("https://swappie.com/en/airpods/", 179, "refurbished"),
              _o("https://www.backmarket.ie/en-ie/p/airpods-pro-2", 180, "refurbished")]
    search = [_o("https://www.tori.fi/recommerce/forsale/search?q=airpods+pro+2&sub_category=1", 100, "used"),
              _o("https://www.tori.fi/recommerce/forsale/search?q=airpods+pro+2", 159, "used")]
    offers = [tips, *refurb, *search]
    v = judge(AIRPODS, [Thing(id="t", name="AirPods Pro 2", offers=offers)], history=False)
    assert tips.true_cost is None and any(f.startswith("too good to be true") for f in tips.flags)
    assert "apple.com" not in (v.best_offer_url or "") and "apple.com" not in (v.best_true_cost_url or "")
    for r in refurb:
        assert r.true_cost.resale_eur > 50, r.true_cost.basis           # was €4.12 from the ear tips
    assert jd.used_comps(offers) == []                                  # search pages are not comps
    assert not any(f.startswith("costs more than new") for o in search for f in o.flags)


def test_search_pages_are_not_resale_comps():
    offers = [_o("https://www.tori.fi/recommerce/forsale/search?page=6&q=switch+nintendo", 170, "used",
                 "Nintendo Switch OLED -pelikonsoli"),
              _o("https://www.tori.fi/recommerce/forsale/search?q=switch", 200, "used", "Nintendo Switch OLED"),
              _o("https://www.worldshop.eu/en/nintendo-switch-oled-model-console-white-1765950", 349, "new",
                 "Nintendo Switch OLED"),
              _o("https://ceno.lv/en/product/nintendo-switch-oled-x", 304.6, "new", "Nintendo Switch OLED")]
    tc = jd.estimate_true_cost(offers[2], offers)
    assert "resale from" not in tc.basis and "no used listings" in tc.basis


def test_a_used_offer_is_not_its_own_only_comp():
    tori = _o("https://www.tori.fi/recommerce/forsale/item/38231132", 395, "used", "Dyson V15 Detect Absolute")
    new = [_o(f"https://shop{i}.lv/dyson-v15-detect", p, "new", "Dyson v15 Detect") for i, p in enumerate((549, 579.99))]
    tc = jd.estimate_true_cost(tori, [tori, *new])
    assert "resale from 1 used listing" not in tc.basis and "only 1 used listing" in tc.basis
    tc_new = jd.estimate_true_cost(new[0], [tori, *new])
    assert "only 1 used listing" in tc_new.basis


def test_two_real_comps_still_price_resale():
    used = [_o(f"https://www.tori.fi/recommerce/forsale/item/{i}", p, "used", "Dyson V15 Detect")
            for i, p in enumerate((380, 420))]
    tc = jd.estimate_true_cost(used[0], used)
    assert tc.basis.startswith("resale from 2 used listings, median €400")


# ---------------------------------------------------------------- duplicates and currencies

def test_same_page_with_tracking_params_is_one_offer():
    a = _o("https://www.mobilesentrix.eu/oled-display-for-nintendo-switch?srsltid=AYCX9vIsj", 300, "new",
           "Nintendo Switch OLED")
    b = _o("https://mobilesentrix.eu/oled-display-for-nintendo-switch/", 300, "new", "Nintendo Switch OLED")
    assert len(jd._merge_same_page([a, b])) == 1


def test_locale_path_sets_the_currency_of_a_dot_com_page():
    assert fx.locale_currency("https://www.backmarket.com/en-us/p/switch-oled") == "USD"
    assert fx.locale_currency("https://www.nintendo.com/us/store/products/x") == "USD"
    assert fx.locale_currency("https://www.backmarket.ie/en-ie/p/airpods-pro-2") is None
    assert fx.locale_currency("https://www.dyson.com/outlet/refurbished") is None
    o = Offer(url="https://www.backmarket.com/en-us/p/switch-oled", source="backmarket.com", title="Switch OLED",
              price=239.0, currency=None, price_eur=None, condition="refurbished")
    reader._finish(o, SWITCH)
    assert o.currency == "USD" and o.price_eur == pytest.approx(239 / fx.STATIC_RATES["USD"], abs=0.01)
    assert "currency_unknown" not in o.flags
