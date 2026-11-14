import pytest

from agora.models import Need, Offer
from agora.need import parse_need
from agora.resolve import explain, is_accessory, is_bundle, relevance, resolve, signature
from brain_fixtures import fixture_offers, market


@pytest.mark.parametrize("title", [
    "a7 iii", "a7iii", "A7III", "ILCE-7M3", "Sony ILCE7M3B", "a7 mark 3", "A7 Mark III", "a7 mk iii",
    "Sony Alpha a7 III Mirrorless Digital Camera - Black (Body Only)", "SONY A7 III BODY",
])
def test_a7iii_aliases(title):
    assert signature(title).models == ("a7-3",)


@pytest.mark.parametrize("a,b,same", [
    ("Sony a7 III", "Sony A7R III", False),
    ("Sony a7 III", "Sony a7 IV", False),
    ("Sony ILCE-7RM4A", "Sony A7R IV", True),
    ("iPhone 15 Pro", "Apple iPhone15 Pro 256GB Natural Titanium", True),
    ("iPhone 15 Pro", "iPhone 15 Pro Max", False),
    ("Canon EOS R6 Mark II", "canon r6 mk2", True),
    ("Fujifilm X100V", "Fuji X100 V silver", True),
])
def test_same_thing(a, b, same):
    assert (signature(a).key == signature(b).key) is same


def test_accessories_and_bundles():
    assert is_accessory("NP-FZ100 battery for Sony a7 III")
    assert is_accessory("Camera cage compatible with Sony A7III")
    assert is_accessory("Case for iPhone 15 Pro")
    assert not is_accessory("Sony a7 III + 2 batteries + charger")
    assert not is_accessory("Sony a7 III body")
    assert is_bundle("Sony a7 III + 2 batteries + charger")
    assert is_bundle("Sony A7 III with 28-70mm lens kit")
    # asking for the accessory makes it relevant
    n = parse_need("battery for sony a7 iii")
    assert not is_accessory("NP-FZ100 battery for Sony a7 III", n)


def test_relevance_ranks():
    n = parse_need("used sony a7 iii under 900")
    def r(t: str) -> float:
        return relevance(n, Offer(url="u", source="s", title=t, price=1, currency="EUR", condition="used"))
    assert r("Sony Alpha ILCE-7M3") == 1.0
    assert r("A7iii käytetty") > 0.8
    assert r("Sony A7 II body") < 0.2
    assert r("Canon EOS R6") < 0.1
    assert r("Battery for Sony a7 III") < 0.2
    assert 0.5 <= r("Sony alpha mirrorless camera") < 0.7    # cannot tell: kept, but lower


def test_explain_reasons():
    n = parse_need("sony a7 iii")
    _, why = explain(n, Offer(url="u", source="s", title="NP-FZ100 battery for Sony a7 III", price=39, currency="EUR"))
    assert why == "accessory, not the item"
    _, why = explain(n, Offer(url="u", source="s", title="Sony A7 II", price=500, currency="EUR"))
    assert why and why.startswith("different model")


def test_real_fixtures_resolve_to_one_thing():
    n = parse_need("sony a7 iii")
    things = resolve(n, fixture_offers())
    assert len(things) == 1
    assert things[0].name == "Sony A7 III" and things[0].id == "t-sony-a7-iii"
    assert len(things[0].offers) == 3 and all(o.thing_id == "t-sony-a7-iii" for o in things[0].offers)


def test_market_clusters_and_rejects():
    n = parse_need("sony a7 iii")
    offers = market()
    things = resolve(n, offers)
    main = things[0]
    titles = {o.title for o in main.offers}
    assert "NP-FZ100 battery for Sony a7 III" not in titles
    assert "Sony A7 II body" not in titles
    assert len(main.offers) == 10
    rejected = [o for o in offers if o.thing_id is None]
    assert {o.title for o in rejected} == {"NP-FZ100 battery for Sony a7 III", "Sony A7 II body"}


def test_kit_is_its_own_thing():
    n = Need(raw="sony a7 iii", thing="sony a7 iii")
    offs = [Offer(url="1", source="a", title="Sony a7 III body", price=1, currency="EUR"),
            Offer(url="2", source="b", title="Sony a7 III + FE 28-70mm F3.5-5.6 kit", price=1, currency="EUR")]
    things = resolve(n, offs)
    assert sorted(t.name for t in things) == ["Sony A7 III", "Sony A7 III kit"]
    assert "bundle" in offs[1].flags


def test_service_offers_cluster_together():
    n = parse_need("home cleaning in Espoo")
    offs = [Offer(url=str(i), source="s", title=t, price=p, currency="EUR", unit="hour", condition="service")
            for i, (t, p) in enumerate([("Home cleaning Espoo, from 35 €/h", 35), ("Kotisiivous / home cleaning", 39)])]
    things = resolve(n, offs)
    assert len(things) == 1 and len(things[0].offers) == 2


def test_shop_name_in_brand_field_does_not_hide_a_match():
    from agora.models import Need, Offer
    from agora.resolve import relevance
    need = Need(raw="x", thing="sony a7 iii body")
    o = Offer(url="u", source="allenscamera.net", title="Used Sony a7 III Body", price=700,
              currency="USD", brand="Allen's Camera", condition="used")
    assert relevance(need, o) >= 0.9


def test_pro_is_not_the_base_phone():
    from agora.models import Need, Offer
    from agora.resolve import relevance
    need = Need(raw="x", thing="iphone 15 128gb", conditions=["used"])
    pro = Offer(url="u", source="iused.nl", title="iPhone 15 Pro - 128GB - White Titanium", price=739,
                currency="EUR", condition="used")
    base = Offer(url="v", source="swappie.com", title="Apple iPhone 15 128 GB Black", price=439,
                 currency="EUR", condition="used")
    assert relevance(need, pro) < 0.5 <= relevance(need, base)
