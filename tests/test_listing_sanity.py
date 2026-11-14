"""Marketplace floods (hundreds of vinted / tori / marktplaats / olx rows): robust reference price, private-seller
'new', multi-language red flags, and the pick check on the listing's own page.

Regression: live 'airpods pro 2' (895 offers) picked '€30 all in: used at tori.fi' (the description says the noise
cancelling is faulty) with 'New from €75 (vinted.fi)', because every median ran over hundreds of cases, boxes,
single earbuds and €30 'sealed' copies."""
from __future__ import annotations

import asyncio
import gzip
import json
import pathlib
import time

import pytest

from agora import hunt, judge as J, reader
from agora.models import Need, Offer
from agora.resolve import explain, listing_red_flags, resolve

FIX = pathlib.Path(__file__).parent / "fixtures"
AIRPODS = Need(raw="airpods pro 2", thing="airpods pro 2")
LIST_VIA = ("contextdev_markdown_split", "jsonld_itemlist", "contextdev_json", "contextdev_list")


def _flood() -> tuple[Need, list[Offer], str]:
    need, offers, recorded = None, [], ""
    with gzip.open(FIX / "live_offers_airpods-pro-2_flood.jsonl.gz", "rt") as f:
        for line in f:
            r = json.loads(line)
            if "need" in r:
                need = Need(**r["need"])
            elif "offer" in r:
                o = Offer(**r["offer"])
                if o.read_via in LIST_VIA:
                    o.raw["from_list_page"] = "search page"
                offers.append(o)
            else:
                recorded = r["recorded_verdict"]
    assert need is not None
    return need, offers, recorded


def _o(url: str, source: str, title: str, price: float, cond: str = "used", **raw) -> Offer:
    o = Offer(url=url, source=source, title=title, price=price, currency="EUR", price_eur=price, condition=cond,
              read_via="jsonld")
    o.raw.update(raw)
    return o


# ---------------------------------------------------------------- red flags (title + description, many languages)

@pytest.mark.parametrize("text,kind", [
    ("AirPods Pro 2 Oikea A3047", "part"),                                       # fi: the right one only
    ("Apple AirPods Pro 2 – Rechter AirPod (A2698) einzeln", "part"),            # de
    ("Apple AirPods Pro 2 - lewa słuchawka", "part"),                            # pl
    ("AirPods Pro 2 – 1 st höger/vänster hörlur", "part"),                       # sv
    ("Pudełko po AirPods Pro 2, Tuotemerkki: Apple", "part"),                    # pl: the box from them
    ("Original AirPods Pro (2nd generation) box, Tuotemerkki: Apple", "part"),
    ("Apple AirPods Pro 2 USB-C – Zonder Oplaadcase", "part"),                   # nl: no charging case
    ("AirPods 2 Pro, Tuotemerkki: Burga, Kunto: Uusi", "part"),                  # another brand: a case
    ("Ostetaan AirPods Pro 2", "wanted"),
    ("Gezocht: AirPods Pro 2", "wanted"),
    ("Airpods pro 2 replica, Kunto: Erittäin hyvä", "fake"),
    ("AirPods Pro 2 1:1 high quality copy", "fake"),
    ("Airpods pro 2, Tuotemerkki: TWS, Kunto: Hyvä", "fake"),                    # no-name brand field
    ("AirPods Pro 2 rikki", "broken"),
    ("Apple AirPods Pro 2 kapot", "broken"),
    ("AirPods Pro 2 defekt", "broken"),
    ("AirPods Pro 2 trasig", "broken"),
    ("Airpods pro 2 icloud locked", "locked"),
    ("Vaihdetaan AirPods Pro 2 iPhoneen", "swap"),
])
def test_title_red_flags(text, kind):
    assert kind in {k for k, _, _ in listing_red_flags(text, AIRPODS)}


@pytest.mark.parametrize("text", [
    "Apple AirPods Pro 2 (USB-C)",
    "Lewa i prawa słuchawka AirPods Pro 2 + etui",                     # both earbuds
    "AirPods Pro 2 Nieuw in doos",                                      # new in box: the whole thing
    "Apple AirPods Pro 2 - Nieuw in gesealde verpakking",
    "Säljer ett par AirPods Pro 2 med tillhörande laddningsetui.",
])
def test_clean_titles_have_no_red_flags(text):
    assert listing_red_flags(text, AIRPODS) == []


@pytest.mark.parametrize("text,kind", [
    ("HUOM! Kuulokkeiden vastamelussa on häiriötä, toimii kuitenkin jos nämä kytkee pois.", "broken"),
    ("Myydään vain vasen kuuloke, oikea hukassa.", "part"),
    ("Ich verkaufe hier einen einzelnen, rechten AirPod Pro von Apple.", "part"),
    ("100% origineel Apple – losse oplaadcase AirPods Pro 2 (USB-C)", "part"),
    ("Selger originale Apple AirPods Pro reservedeler.", "part"),
])
def test_description_red_flags(text, kind):
    assert kind in {k for k, _, _ in listing_red_flags(text, AIRPODS, title=False)}


@pytest.mark.parametrize("text", [
    "Kaikki toimii, ei vikoja. Mukana alkuperäinen laatikko.",                  # 'no faults'
    "Myydään Sonyn a7 iii-runko. Mitään vikoja ei ole ilmentynyt.",             # live: negation after the word
    "Die Kopfhörer sowie case funktionieren einwandfrei und haben keinerlei Mängel.",
    "Vervanging bij verlies of defect. Werkt perfect.",                         # 'replacement in case of a defect'
    "Säljer mina AirPods Pro (Gen 2) i fint skick. De fungerar helt felfritt.",
    "Apple AirPods Pro 2 nowe, oryginalne, kopia paragonu",                     # a copy of the receipt
    "Tausch möglich, sonst Festpreis",                                          # swap is only flagged in titles
])
def test_clean_descriptions_have_no_red_flags(text):
    assert listing_red_flags(text, AIRPODS, title=False) == []


def test_resolve_drops_single_earbuds_boxes_and_wanted_ads_with_a_reason():
    offers = [_o("https://www.tori.fi/item/1", "tori.fi", "AirPods Pro 2 Oikea A3047", 9),
              _o("https://www.tori.fi/item/2", "tori.fi", "Ostetaan AirPods Pro 2", 100),
              _o("https://www.tori.fi/item/3", "tori.fi", "Apple AirPods Pro 2 (USB-C)", 140)]
    kept = [o for t in resolve(AIRPODS, offers) for o in t.offers]
    assert [o.url for o in kept] == ["https://www.tori.fi/item/3"]
    assert "only one earbud" in (explain(AIRPODS, offers[0])[1] or "")
    assert "wanted ad" in (explain(AIRPODS, offers[1])[1] or "")


# ---------------------------------------------------------------- reference price + private sellers

def _market(n_junk: int = 120) -> list[Offer]:
    shops = [_o("https://www.gigantti.fi/p/1", "gigantti.fi", "Apple AirPods Pro 2 (USB-C)", 229, "new"),
             _o("https://hinta.fi/1", "hinta.fi", "Apple AirPods Pro (2nd generation)", 229, "new"),
             _o("https://www.verkkokauppa.com/p/1", "verkkokauppa.com", "Apple AirPods Pro 2", 219, "new"),
             _o("https://www.backmarket.fi/p/1", "backmarket.fi", "AirPods Pro 2", 175, "refurbished")]
    junk = [_o(f"https://www.vinted.fi/items/{i}", "vinted.fi", f"AirPods Pro 2 nr {i}", 25 + (i % 30),
               "new" if i % 3 == 0 else "used", from_list_page="s") for i in range(n_junk)]
    real = [_o(f"https://www.tori.fi/recommerce/forsale/item/{i}", "tori.fi", "Apple AirPods Pro 2 (USB-C)",
               110 + 3 * i, from_list_page="s") for i in range(20)]
    return shops + junk + real


def test_reference_comes_from_shops_and_resists_a_flood_of_cheap_rows():
    offers = _market()
    ref = J.reference_price(offers, J.category_for("airpods pro 2"), AIRPODS)
    assert ref is not None and 219 <= ref.new_eur <= 229 and ref.shop_new == 3
    assert 80 <= ref.floor_eur <= 90


def test_flooded_market_never_picks_a_too_good_listing():
    offers = _market()
    v = J.judge(AIRPODS, resolve(AIRPODS, offers), history=False)
    pick = next(o for o in offers if o.url == v.best_offer_url)
    assert pick.price_eur >= 100 and pick.source == "tori.fi", v.headline
    cheap = next(o for o in offers if o.price_eur == 25)
    assert J._risky(cheap) and any("too good to be true" in f and "new price" in f for f in cheap.flags)
    assert cheap.true_cost is None
    assert any(line.startswith("reference: new €2") for line in v.lines)
    # private-seller 'new' is not shop-new: the headline's "New from" is a shop price
    assert "New from €219" in v.headline or "new from €219" in v.headline


def test_private_new_is_used_like_and_labelled():
    offers = [_o("https://www.gigantti.fi/p/1", "gigantti.fi", "Apple AirPods Pro 2", 229, "new"),
              _o("https://hinta.fi/1", "hinta.fi", "Apple AirPods Pro 2", 225, "new"),
              # (round 4: vinted's buyer protection fee, €0.70 + 5%, is now always in 'all in')
              _o("https://www.vinted.fi/items/1", "vinted.fi", "Apple AirPods Pro 2 sealed", 140, "new"),
              _o("https://www.tori.fi/item/2", "tori.fi", "Apple AirPods Pro 2", 160),
              _o("https://www.tori.fi/item/3", "tori.fi", "Apple AirPods Pro 2", 170)]
    v = J.judge(AIRPODS, resolve(AIRPODS, offers), history=False)
    priv = offers[2]
    assert J.private_new(priv) and J.market_condition(priv) == "used"
    assert v.best_offer_url == priv.url
    assert "new (private seller) at vinted.fi" in v.headline and "New from €2" in v.headline
    assert 140.0 in J.market_prices(offers, "used") and 140.0 not in J.market_prices(offers, "new")


def test_red_flagged_listing_is_never_the_pick_nor_a_market_price():
    offers = [_o("https://www.gigantti.fi/p/1", "gigantti.fi", "Apple AirPods Pro 2", 229, "new"),
              _o("https://www.tori.fi/item/1", "tori.fi", "Apple AirPods Pro 2 rikki", 120),
              _o("https://www.tori.fi/item/2", "tori.fi", "Apple AirPods Pro 2", 150),
              _o("https://www.tori.fi/item/3", "tori.fi", "Apple AirPods Pro 2", 160)]
    v = J.judge(AIRPODS, resolve(AIRPODS, offers), history=False)
    assert v.best_offer_url == "https://www.tori.fi/item/2"
    assert any(f.startswith("red flag: broken or faulty") for f in offers[1].flags)
    assert 120.0 not in J.market_prices(offers, "used")


def test_cameras_keep_cheap_but_plausible_used_bodies():
    need = Need(raw="sony a7 iii body", thing="sony a7 iii body")
    offers = [_o("https://www.verkkokauppa.com/p/1", "verkkokauppa.com", "Sony A7 III body", 1499, "new"),
              _o("https://www.gigantti.fi/p/1", "gigantti.fi", "Sony A7 III runko", 1449, "new"),
              _o("https://www.tori.fi/item/1", "tori.fi", "Sony A7 III body", 820),
              _o("https://www.tori.fi/item/2", "tori.fi", "Sony a7 iii runko", 900),
              _o("https://www.tori.fi/item/3", "tori.fi", "Sony A7III", 390)]
    v = J.judge(need, resolve(need, offers), history=False)
    assert v.best_offer_url == "https://www.tori.fi/item/1"
    assert J._risky(offers[4])


# ---------------------------------------------------------------- the live flood, replayed offline

def test_live_airpods_flood_replay_gives_a_sane_pick_fast():
    need, offers, recorded = _flood()
    assert recorded.startswith("€30 all in: used at tori.fi")     # the bad verdict this guards against
    t = time.perf_counter()
    things = resolve(need, offers)
    v = J.judge(need, things, history=False)
    assert time.perf_counter() - t < 3.0                        # ~0.7 s here; generous for slow CI
    kept = [o for th in things for o in th.offers]
    pick = next(o for o in kept if o.url == v.best_offer_url)
    # nothing under the reference floor (round 4: hinta.fi, a price-comparison site, no longer sets the new
    # reference, and the floor is at most 75% of the plain used median, so it is ~€72 rather than €84; the €30 pick
    # this guards against stays out and the pick sits in the typical used band)
    assert pick.price_eur >= 70 and not J._risky(pick), v.headline
    assert "New from €75" not in v.headline and "new from €75" not in v.headline
    tori30 = next(o for o in kept if o.url.endswith("/49683131"))
    assert J._risky(tori30)
    assert sum(1 for o in kept if J._risky(o)) > 100      # the flood of €5-€60 fakes and cases (round 4: lower floor)


# ---------------------------------------------------------------- the pick check (listing page description)

def test_listing_description_reads_the_sellers_text_not_similar_listings():
    html = (FIX / "tori_item_airpods_fault.html").read_text()
    d = reader.listing_description(html)
    assert "häiriötä" in d and "Samankaltaisia" not in d and "40 €" not in d
    assert [k for k, _, _ in listing_red_flags(d, AIRPODS, title=False)] == ["broken"]


def test_verify_pick_skips_a_failing_candidate_and_says_so():
    offers = [_o("https://www.gigantti.fi/p/1", "gigantti.fi", "Apple AirPods Pro 2", 229, "new"),
              _o("https://www.tori.fi/recommerce/forsale/item/1", "tori.fi", "Apple AirPods Pro 2", 140),
              _o("https://www.tori.fi/recommerce/forsale/item/2", "tori.fi", "Apple AirPods Pro 2", 150),
              _o("https://www.tori.fi/recommerce/forsale/item/3", "tori.fi", "Apple AirPods Pro 2", 160)]
    things = resolve(AIRPODS, offers)
    v = J.judge(AIRPODS, things, history=False)
    assert v.best_offer_url.endswith("/item/1")
    html = (FIX / "tori_item_airpods_fault.html").read_text()
    seen: list[str] = []

    async def check(url: str, need: Need) -> dict:
        seen.append(url)
        if url.endswith("/item/1"):
            desc = reader.listing_description(html)
            return {"ok": False, "flags": [list(f) for f in listing_red_flags(desc, need, title=False)],
                    "description": desc}
        return {"ok": True, "flags": [], "description": "Hyvässä kunnossa, toimii moitteetta."}

    v2, checks = asyncio.run(hunt.verify_pick(AIRPODS, things, v, lambda: J.judge(AIRPODS, things, history=False),
                                              check=check))
    assert v2.best_offer_url.endswith("/item/2")
    assert any(line.startswith("skipped €140 tori.fi") and "häiriötä" in line for line in v2.lines)
    assert {c["url"] for c in checks} == set(seen) and "https://www.gigantti.fi/p/1" not in seen
    assert any(c["ok"] is False for c in checks)


def test_check_listing_offline_without_cache_is_unknown_not_a_fail():
    r = asyncio.run(reader.check_listing("https://www.tori.fi/recommerce/forsale/item/999", AIRPODS))
    assert r["ok"] is None and r["flags"] == []
