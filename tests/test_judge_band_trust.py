"""Round 3: price band + fake discount, trust signals (photo reuse, look-alike, young domain),
GTIN matching, product-read cross-check, grey-import downgrade, gross/net dedupe. All offline."""
from __future__ import annotations

import io
import time
from datetime import date, timedelta

import pytest

from agora import judge as jd
from agora import trust
from agora.judge import judge
from agora.models import Need, Offer, Thing
from agora.resolve import normalize_gtin, normalize_mpn, product_keys, resolve
from live_offers import load

NEED = Need(raw="sony a7 iii", thing="sony a7 iii")


def offer(src: str, price: float, cond: str = "new", **kw) -> Offer:
    url = kw.pop("url", f"https://www.{src}/p/a7iii")
    return Offer(url=url, source=src, title=kw.pop("title", "Sony a7 III body"), price=price, currency="EUR",
                 price_eur=price, condition=cond, in_stock=True, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- GTIN

def test_gtin_normalises_every_length_to_gtin14():
    assert normalize_gtin("012345678905") == normalize_gtin("0012345678905") == "00012345678905"
    assert normalize_gtin("4548736079625") == "04548736079625"
    assert normalize_gtin("96385074") == "00000096385074"               # GTIN-8
    assert normalize_gtin("4548736079626") is None                       # bad check digit
    assert normalize_gtin("0000000000000") is None and normalize_gtin("abc") is None
    assert normalize_gtin(4548736079625) == "04548736079625"
    assert normalize_mpn("ILCE-7M3/B") == normalize_mpn("ilce7m3b") == "ILCE7M3B"
    assert normalize_mpn("black") is None


def test_same_gtin_is_one_thing_even_with_odd_titles():
    a = offer("shop-a.fi", 1100, title="Sony Alpha 7 III", raw={"gtin": "4548736079625"})
    b = offer("shop-b.de", 1080, title="Sony a7 III ILCE-7M3 body", raw={"gtin": "04548736079625"})
    # a shop's own catalogue name that the title matcher rejects, but the same EAN
    c = offer("shop-c.eu", 1050, title="Vollformat DSLM VF24 Gehäuse", sku="4548736079625")
    d = offer("shop-d.eu", 1050, title="Vollformat DSLM VF24 Gehäuse")                  # same title, no code
    things = resolve(NEED, [a, b, c, d])
    assert len(things) == 1
    t = things[0]
    assert c in t.offers and d not in t.offers
    assert c.raw["matched_by"] == "gtin" and c.raw["gtin14"] == "04548736079625"
    assert product_keys(a) == {"gtin:04548736079625"}


def test_gtin_merges_buckets_that_titles_split():
    a = offer("shop-a.fi", 1100, title="Sony a7 III", raw={"gtin": "4548736079625"})
    b = offer("shop-b.de", 1080, title="Sony ILCE7M3B", raw={"gtin13": "4548736079625"})
    things = resolve(NEED, [a, b])
    assert len(things) == 1 and len(things[0].offers) == 2


# ---------------------------------------------------------------- PRICE BAND

def market() -> list[Offer]:
    return [offer(f"shop{i}.fi", p) for i, p in enumerate((1000, 1050, 1100, 1150, 1200))]


def test_band_labels_low_typical_high():
    offers = market() + [offer("cheap.fi", 980), offer("dear.fi", 1300)]
    t = Thing(id="t", name="Sony A7 III", offers=offers)
    v = judge(NEED, [t])
    by = {o.source: o for o in offers}
    assert by["cheap.fi"].raw["band"]["label"] == "low"
    assert "cheapest new right now" in by["cheap.fi"].raw["band"]["badges"]
    assert by["shop2.fi"].raw["band"]["label"] == "typical"
    assert by["dear.fi"].raw["band"]["label"] == "high"
    # carried in the truecost payload and the verdict
    assert by["cheap.fi"].true_cost.band["label"] == "low"
    assert v.price_band and v.price_band["p25"] <= v.price_band["p75"]
    assert any(line.startswith("price band (new)") for line in v.lines)


def test_band_uses_history_and_gives_lowest_seen_badge():
    from agora import store
    offers = market()
    now = time.time()
    for o in offers:
        store.save_offer(o)
        store.snapshot(o.url, o.price_eur + 100, True, seen_at=now - 40 * 86400)
        store.snapshot(o.url, o.price_eur + 50, True, seen_at=now - 20 * 86400)
        store.snapshot(o.url, o.price_eur + 60, True, seen_at=now - 10 * 86400)
    bands = jd.price_band(Thing(id="t", name="x", offers=offers), now=now)
    b = bands["new"]
    assert b["n_history"] == 15 and b["days"] == 40 and "price history" in b["basis"]
    ob = jd.offer_band(offers[0], bands, now=now)
    assert "lowest seen in 40 days" in ob["badges"]
    assert any("30-day avg" in x for x in ob["badges"])
    # history off (live preview): market only
    assert jd.price_band(Thing(id="t", name="x", offers=offers), history=False)["new"]["n_history"] == 0


def test_too_few_prices_no_band():
    t = Thing(id="t", name="x", offers=[offer("a.fi", 1000), offer("b.fi", 1100)])
    assert jd.price_band(t) == {}


# ---------------------------------------------------------------- FAKE DISCOUNT (Omnibus 30-day rule)

def test_discount_inflated_against_our_30_day_history():
    from agora import store
    o = offer("deals.fi", 999, raw={"regular_price": 1499})
    now = time.time()
    for days, p in ((25, 1049), (12, 999), (3, 1019)):
        store.snapshot(o.url, p, True, seen_at=now - days * 86400)
    flag = jd.discount_check(o, [o], now=now)
    assert flag and flag.startswith("discount inflated") and "€1,049" in flag and "30-day low, €999" in flag
    assert o.raw["discount_claim_pct"] == pytest.approx(1 - 999 / 1499, abs=0.001)
    honest = offer("honest.fi", 999, raw={"regular_price": 1049}, url="https://honest.fi/x")
    store.snapshot(honest.url, 1049, True, seen_at=now - 20 * 86400)
    assert jd.discount_check(honest, [honest], now=now) is None


def test_discount_inflated_against_the_market_without_history():
    o = offer("deals.fi", 1050, raw={"regular_price": "1 899,00 €"})
    peers = market() + [o]
    t = Thing(id="t", name="x", offers=peers)
    judge(NEED, [t])
    assert any(f.startswith("discount inflated") and "above every new price" in f for f in o.flags)
    assert o.trust is not None and o.trust <= 0.9


# ---------------------------------------------------------------- TRUST SIGNALS

def test_lookalike_and_registrable_domain():
    assert trust.registrable("https://shop.verkkokauppa.com/fi/x") == "verkkokauppa.com"
    assert trust.registrable("usedlens.co.uk") == "usedlens.co.uk"
    assert trust.lookalike_of("verkkokaupa.com") == "verkkokauppa"
    assert trust.lookalike_of("verkkokauppa-outlet.shop") == "verkkokauppa"
    assert trust.lookalike_of("gigantti24.fi") == "gigantti"
    for honest in ("verkkokauppa.com", "mediamarkt.de", "swappa.com", "power-tools.fi", "fotoerhardt.de",
                   "usedlens.co.uk", "e-infin.com", "wedio.com", "novah.fi"):
        assert trust.lookalike_of(honest) is None, honest
    assert trust.edit_distance("kitten", "sitting") == 3


def test_lookalike_shop_is_capped_and_never_crowned():
    fake = offer("verkkokaupa-outlet.shop", 900, url="https://verkkokaupa-outlet.shop/a7iii")
    offers = market() + [fake]
    v = judge(NEED, [Thing(id="t", name="Sony A7 III", offers=offers)])
    assert fake.trust is not None and fake.trust <= 0.3
    assert any("looks like verkkokauppa" in f for f in fake.flags)
    assert "verkkokaupa" not in (v.best_offer_url or "") + (v.best_true_cost_url or "")


def test_young_domain_from_cache_and_scam_pattern():
    created = (date.today() - timedelta(days=23)).isoformat()
    trust._put("whois", "brandnewcams.shop", {"created": created, "ok": True, "ts": time.time()})
    young = offer("brandnewcams.shop", 690, url="https://brandnewcams.shop/a7")
    offers = market() + [young]
    judge(NEED, [Thing(id="t", name="Sony A7 III", offers=offers)])
    assert trust.domain_age_days("https://brandnewcams.shop/a7") == 23
    assert any(f.startswith("shop domain is only 23 days old") for f in young.flags)
    assert any(f.startswith("scam pattern") for f in young.flags)
    assert young.trust is not None and young.trust < 0.5


def test_same_photo_on_two_sellers_listings():
    img = "https://img.example/a7.jpg"
    a = offer("tori.fi", 700, cond="used", image=img, seller="matti", url="https://tori.fi/a")
    b = offer("huuto.net", 690, cond="used", image=img, seller="liisa", url="https://huuto.net/b")
    n1 = offer("shop1.fi", 1100, image=img)                         # new from shops: manufacturer photo, fine
    n2 = offer("shop2.fi", 1120, image=img)
    used2 = offer("kamerastore.com", 720, cond="used", url="https://kamerastore.com/x")
    judge(NEED, [Thing(id="t", name="Sony A7 III", offers=[a, b, n1, n2, used2])])
    assert any(f.startswith("photo copied from another seller") for f in a.flags)
    assert not any("photo" in f for f in n1.flags + n2.flags + used2.flags)


def test_phash_matches_near_identical_photos():
    from PIL import Image, ImageDraw

    def png(shift: int, size: int = 200, fmt: str = "PNG") -> bytes:
        im = Image.new("RGB", (200, 200), "white")
        d = ImageDraw.Draw(im)
        d.rectangle((40 + shift, 50, 150 + shift, 140), fill="black")
        d.ellipse((90, 70, 130, 110), fill="gray")
        buf = io.BytesIO()
        im.resize((size, size)).save(buf, fmt)
        return buf.getvalue()

    # the same photo, re-uploaded bigger and as a JPEG by another seller
    h1, h2 = trust.hash_image_bytes(png(0)), trust.hash_image_bytes(png(0, size=320, fmt="JPEG"))
    other = trust.hash_image_bytes(png(45))
    assert h1 and h2 and trust.hamming(h1, h2) <= trust.PHASH_MAX_DISTANCE
    assert trust.hamming(h1, other) > trust.PHASH_MAX_DISTANCE
    assert trust.hash_image_bytes(b"not an image") is None
    trust.remember_hash("https://x.example/1.jpg", h1)
    trust.remember_hash("https://y.example/2.jpg", h2)
    a = offer("tori.fi", 700, cond="used", image="https://x.example/1.jpg", url="https://tori.fi/a")
    b = offer("kamerastore.com", 710, cond="used", image="https://y.example/2.jpg", url="https://kamerastore.com/b")
    assert trust.same_photo_groups([a, b]) == {id(a): [b], id(b): [a]}


def test_warm_is_a_noop_offline():
    o = offer("shop.fi", 1000, image="https://img.example/x.jpg")
    assert trust.warm([o], budget_s=1.0) == {"images": 0, "whois": 0}
    assert trust.image_hash(o.image) is None


# ---------------------------------------------------------------- price cross-checks

def test_mpb_product_read_far_under_market_is_disputed():
    need, offers, _ = load("sony-a7-iii-body")
    things = resolve(need, offers)
    judge(need, things)
    mpb = next(o for t in things for o in t.offers if o.source == "mpb.com")
    assert mpb.raw["price_check"] == "disputed" and mpb.true_cost is None
    assert any(f.startswith("price disagrees: product read €239") for f in mpb.flags)


def test_title_and_snippet_prices_are_witnesses():
    o = offer("shop.fi", 239, cond="used", read_via="contextdev_product",
              raw={"search_text": "Used Sony A7 III from €789 - save €200 - €29/mo"})
    assert jd.text_prices(o) == [789.0]
    assert jd.verify_price(o).startswith("price disagrees: page €239 vs search €789")
    ok = offer("shop.fi", 789, cond="used", raw={"search_text": "Sony A7 III €789, free shipping over €50"})
    jd.verify_price(ok)
    assert ok.raw["price_check"] == "consistent"


def test_grey_import_pick_is_not_a_plain_buy_now():
    grey = offer("e-infin.com", 1000, title="Sony a7 III (import taxes included)")
    v = judge(NEED, [Thing(id="t", name="Sony A7 III", offers=[grey])])
    assert v.buy_or_wait == "check the warranty first"
    assert any("grey import" in line for line in v.lines)
    clean = offer("shop.fi", 1000)
    assert judge(NEED, [Thing(id="t", name="Sony A7 III", offers=[clean])]).buy_or_wait == "buy now"


def test_same_url_gross_and_net_is_one_offer_with_both_prices():
    url = "https://pro-shop.de/sony-a7-iii"
    gross = offer("pro-shop.de", 1240, url=url)
    net = offer("pro-shop.de", 1000, url=url, title="Sony a7 III body (excl. VAT)")
    t = Thing(id="t", name="Sony A7 III", offers=[gross, net])
    judge(NEED, [t])
    assert t.offers == [gross]
    assert gross.raw["net_price_eur"] == 1000
    assert [x["label"] for x in gross.raw["prices_shown"]] == ["incl. VAT", "excl. VAT"]
    assert any(f.startswith("page shows €1,240 incl. VAT and €1,000 excl. VAT") for f in gross.flags)
    # two genuinely different prices on one page (variants) stay apart
    a, b = offer("x.de", 1000, url="https://x.de/p"), offer("x.de", 1500, url="https://x.de/p")
    t2 = Thing(id="t2", name="x", offers=[a, b])
    judge(NEED, [t2])
    assert len(t2.offers) == 2
