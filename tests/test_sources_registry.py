"""agora.sources: the European source registry and its offline discovery helpers (no network)."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agora import sources as S
from agora.sources import discovery as D

FIX = pathlib.Path(__file__).parent / "fixtures" / "sources"
BASE = "https://shop.example.fi/"


def fx(name: str) -> str:
    return (FIX / name).read_text()


# --------------------------------------------------------------------------- finding a search template

def test_opensearch_link_and_description():
    assert D.opensearch_links(fx("home.html"), BASE) == ["https://shop.example.fi/opensearch.xml"]
    tpl = D.parse_opensearch(fx("opensearch.xml"))
    assert tpl == "https://shop.example.fi/haku?q={q}&src=osd"      # html Url, optional {startPage?} dropped


def test_searchaction_template():
    assert D.searchaction_templates(fx("home.html"), BASE) == ["https://shop.example.fi/haku?q={q}"]


def test_search_form_get_first_post_kept_login_and_newsletter_ignored():
    forms = D.form_templates(fx("home.html"), BASE)
    assert forms[0] == {"template": "https://shop.example.fi/haku?cat=all&q={q}", "method": "get"}
    assert {"template": "https://shop.example.fi/legacy-search?keyword={q}", "method": "post"} in forms
    assert not any("login" in f["template"] or "subscribe" in f["template"] for f in forms)


def test_common_patterns_follow_language_and_base_path():
    fi = D.common_templates("https://shop.example.fi/", "fi")
    assert fi[0] == "https://shop.example.fi/haku?q={q}"
    ikea = D.common_templates("https://www.ikea.com/fi/fi/", "fi")
    assert ikea[0] == "https://www.ikea.com/fi/fi/haku?q={q}" and "https://www.ikea.com/haku?q={q}" in ikea


def test_robots_rules_for_star_agent_longest_match():
    rules = D.parse_robots(fx("robots.txt"))
    assert not D.robots_allows(rules, "https://shop.example.fi/haku?q=lego")
    assert D.robots_allows(rules, "https://shop.example.fi/haku/ohje")
    assert not D.robots_allows(rules, "https://shop.example.fi/tuotteet?sort=price")
    assert not D.robots_allows(rules, "https://shop.example.fi/tili")
    assert D.robots_allows(rules, "https://shop.example.fi/tili/asetukset")
    assert D.robots_allows(rules, "https://shop.example.fi/private/x")        # only Googlebot's group
    assert D.robots_allows([], "https://shop.example.fi/anything")


def test_blocked_page():
    assert D.looks_blocked(200, fx("blocked.html"))
    assert D.looks_blocked(403, "")
    assert not D.looks_blocked(200, fx("results.html"))


# --------------------------------------------------------------------------- verifying a results page

def test_infer_listing_shape_skips_navigation_and_other_sites():
    lst = D.infer_listing(fx("results.html"), BASE + "haku?q=samsung", fx("home.html"), "samsung")
    assert lst["count"] == 8
    rx = re.compile(lst["regex"])
    assert rx.search("/tuote/samsung-galaxy-a1-100001")
    assert rx.search("/tuote/iphone-15-pro-123456?ref=x")
    assert not rx.search("/kategoria/puhelimet")
    assert not rx.search("/asiakaspalvelu/toimitus-ja-maksutavat-info")


def test_link_shape_ids_and_tracking_tail():
    assert D.link_shape("https://x.de/item/123") == ("=item", "#")
    assert D.link_shape("https://x.de/-/en/Samsung-Galaxy-A5/dp/B0GMWD27PF/ref=sr_1_3") == \
        ("=-", "=en", "slug", "=dp", "@")
    assert D.link_shape("https://x.pl/d/oferta/rower-gorski-CID767-IDabc12.html") == ("=d", "=oferta", "slug#", "ext.html")


def test_evaluate_results_page():
    ev = D.evaluate(fx("results.html"), BASE + "haku?q=samsung", "samsung", fx("home.html"))
    assert ev["verified"] and ev["links"] == 8 and ev["prices"] == 8
    assert ev["itemlist"] is True and ev["echo"] is True
    assert ev["pagination"] == {"param": "page"}
    assert 0.3 < ev["yield"] <= 1.0


def test_evaluate_home_page_is_not_results():
    ev = D.evaluate(fx("home.html"), BASE + "haku?q=samsung", "samsung", fx("home.html"))
    assert not ev["verified"] and ev["links"] == 0


def test_price_count_currencies():
    assert D.count_prices("<p>1 299 kr</p><p>€ 45,00</p><p>12,50 zł</p><p>£9.99</p><p>3 990 Kč</p>") == 5


# --------------------------------------------------------------------------- seeds

def test_seeds_are_big_unique_and_tagged():
    recs = S.seed_records()
    assert 400 <= len(recs) <= 900
    keys = [r["key"] for r in recs]
    assert len(keys) == len(set(keys))
    for r in recs:
        assert r["lanes"] and set(r["lanes"]) <= set(S.LANES), r
        assert r["categories"] and set(r["categories"]) <= set(S.CATEGORIES), r
        assert r["countries"] and r["languages"], r
    by = {r["key"]: r for r in recs}
    assert by["tori_fi"]["countries"] == ["fi"] and "used" in by["tori_fi"]["lanes"]
    assert "service" in by["helpling_de"]["lanes"] and "cleaning" in by["helpling_de"]["categories"]
    assert by["ikea_com_fi_fi"]["home"] == "https://www.ikea.com/fi/fi/"
    lanes = {lane for r in recs for lane in r["lanes"]}
    assert lanes == set(S.LANES)


def test_secondhand_market_names_to_countries():
    assert S._countries("Norway, Sweden, Denmark, Finland") == ["no", "se", "dk", "fi"]
    assert S._countries("Selected European markets") == ["eu"]
    assert S._countries("UK, Germany, Austria") == ["gb", "de", "at"]


def test_test_queries_travel_across_languages():
    assert S.test_query({"domain": "ikea.com", "categories": ["furniture"]}) == "billy"
    assert S.test_query({"domain": "x.fi", "categories": ["cleaning"], "languages": ["fi"]}) == "siivous"
    assert S.test_query({"domain": "x.de", "categories": ["phones"], "languages": ["de"]}) == "iphone"
    assert S.test_query({"domain": "x.nl", "categories": ["housing"], "countries": ["nl"]}) == "amsterdam"


# --------------------------------------------------------------------------- runtime API

MINI = [
    {"key": "tori_fi", "domain": "tori.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["used"],
     "categories": ["general"], "kind": "classifieds", "status": "verified_free", "yield": 1.0,
     "template": "https://www.tori.fi/recommerce/forsale/search?q={q}", "pagination": {"param": "page"},
     "listing": r"^/recommerce/forsale/item/\d+(?:[/?#]|$)", "itemlist": True, "method": "get"},
    {"key": "vinted_fi", "domain": "vinted.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["used"],
     "categories": ["fashion", "kids", "home"], "kind": "classifieds", "status": "verified_free", "yield": 0.9,
     "template": "https://www.vinted.fi/catalog?search_text={q}", "listing": r"^/items/\d+", "method": "get"},
    {"key": "kleinanzeigen_de", "domain": "kleinanzeigen.de", "countries": ["de"], "languages": ["de"],
     "lanes": ["used"], "categories": ["general"], "kind": "classifieds", "status": "verified_free", "yield": 0.8,
     "template": "https://www.kleinanzeigen.de/s-{dash}/k0", "listing": r"^/s-anzeige/", "method": "get"},
    {"key": "ebay_com", "domain": "ebay.com", "countries": ["eu"], "languages": ["en"], "lanes": ["used"],
     "categories": ["general"], "kind": "marketplace", "status": "verified_contextdev", "yield": 0.8,
     "template": "https://www.ebay.com/sch/i.html?_nkw={q}", "listing": r"^/itm/\d+", "method": "get"},
    {"key": "gigantti_fi", "domain": "gigantti.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["new"],
     "categories": ["electronics", "phones"], "kind": "retailer", "status": "search_found_unverified",
     "template": "https://www.gigantti.fi/search?q={q}", "method": "get"},
    {"key": "hintaopas_fi", "domain": "hintaopas.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["new"],
     "categories": ["electronics"], "kind": "comparison", "status": "verified_free", "yield": 0.9,
     "template": "https://www.hintaopas.fi/search?search={q}", "listing": r"^/product\.php", "method": "get"},
    {"key": "helpling_fi", "domain": "helpling.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["service"],
     "categories": ["cleaning"], "kind": "service", "status": "verified_free", "yield": 0.5,
     "template": "https://www.helpling.fi/haku?q={q}", "listing": r"^/pro/\d+", "method": "get"},
    {"key": "dead_fi", "domain": "dead.fi", "countries": ["fi"], "languages": ["fi"], "lanes": ["used"],
     "categories": ["general"], "kind": "classifieds", "status": "no_search", "template": None},
]


@pytest.fixture
def mini(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"meta": {}, "sources": MINI}))
    return p


def test_load_and_get(mini):
    assert len(S.load(mini)) == len(MINI)
    assert S.get("tori_fi", mini)["domain"] == "tori.fi"
    assert S.load(mini.parent / "missing.json") == []


def test_for_query_used_fi_ranks_home_country_free_first(mini):
    keys = [s["key"] for s in S.for_query("fi", ["used"], ["phones"], path=mini)]
    assert keys[0] == "tori_fi"                     # home country, free, general store
    assert "ebay_com" in keys                       # EU-wide after the home country
    assert "kleinanzeigen_de" not in keys           # another country
    assert "vinted_fi" not in keys                  # fashion site, no phones
    assert "dead_fi" not in keys and "gigantti_fi" not in keys


def test_for_query_options(mini):
    assert [s["key"] for s in S.for_query("fi", "new", path=mini)] == []
    assert [s["key"] for s in S.for_query("fi", "new", include_unverified=True, path=mini)] == ["gigantti_fi"]
    assert "hintaopas_fi" in [s["key"] for s in S.for_query("fi", "new", include_comparison=True, path=mini)]
    assert [s["key"] for s in S.for_query("fi", "service", ["cleaning"], path=mini)] == ["helpling_fi"]
    assert [s["key"] for s in S.for_query("fi", "refurbished", path=mini)] == []
    fashion = [s["key"] for s in S.for_query("fi", ["used"], ["fashion"], path=mini)]
    assert fashion[0] == "vinted_fi"
    assert len(S.for_query("fi", "used", limit=1, path=mini)) == 1


def test_build_url_and_pages(mini):
    tori, kl = S.get("tori_fi", mini), S.get("kleinanzeigen_de", mini)
    assert S.build_url(tori, "iphone 15") == "https://www.tori.fi/recommerce/forsale/search?q=iphone+15"
    assert S.build_url(tori, "iphone 15", 3) == "https://www.tori.fi/recommerce/forsale/search?q=iphone+15&page=3"
    assert S.build_url(kl, "ikea kallax") == "https://www.kleinanzeigen.de/s-ikea-kallax/k0"
    assert S.build_url(kl, "ikea kallax", 2) == "https://www.kleinanzeigen.de/s-ikea-kallax/k0"   # paging unknown
    path_paged = dict(tori, template="https://www.marktplaats.nl/q/{q}/", pagination={"path_suffix": "/p/{page}/"})
    assert S.build_url(path_paged, "lego", 2) == "https://www.marktplaats.nl/q/lego/p/2/"


def test_as_site_kwargs_builds_a_marketplaces_site(mini):
    from agora import marketplaces as M
    kw = S.as_site_kwargs(S.get("tori_fi", mini))
    site = M.Site(**kw)
    assert site.lane == "used" and site.country == "fi" and site.itemlist and site.verified
    assert M.build_url(site, "lego") == "https://www.tori.fi/recommerce/forsale/search?q=lego"
    assert S.as_site_kwargs(S.get("helpling_fi", mini)) is None                      # services: not a Site
    assert S.as_site_kwargs(S.get("hintaopas_fi", mini))["lane"] == "comparison"
    braces = dict(S.get("tori_fi", mini), template="https://x.fi/s?q={q}&f={a}")
    assert M.build_url(M.Site(**S.as_site_kwargs(braces)), "x y") == "https://x.fi/s?q=x+y&f={a}"


# --------------------------------------------------------------------------- the shipped registry

def test_shipped_registry_is_consistent():
    reg = S.load()
    if not reg:
        pytest.skip("registry.json not built yet (scripts/onboard_sources.py)")
    assert len(reg) >= 400
    for s in reg:
        assert s["status"] in S.STATUSES, s["key"]
        if s["status"].startswith("verified"):
            assert s["template"] and ("{q}" in s["template"] or "{dash}" in s["template"]), s["key"]
            assert s["listing"] and re.compile(s["listing"]), s["key"]
            assert s["links"] >= 5, s["key"]
            for path in s.get("sample", []):
                assert re.search(s["listing"], path), (s["key"], path)
    assert sum(s["status"] == "verified_free" for s in reg) >= 50


def test_rows_from_html_free_split():
    page = fx("results.html")
    url = BASE + "haku?q=samsung"
    src = {"listing": D.infer_listing(page, url, fx("home.html"), "samsung")["regex"], "countries": ["fi"]}
    rows = S.rows_from_html(page, url, src)
    assert len(rows) == 8
    assert rows[0] == {"title": "Samsung Galaxy A1", "url": "https://shop.example.fi/tuote/samsung-galaxy-a1-100001",
                       "price": 200.9, "currency": "EUR", "text": " Samsung Galaxy A1 200,90 € "}
    assert [r["price"] for r in rows] == [199.9 + n for n in range(1, 9)]
    assert S.rows_from_html(page, url, {"listing": None}) == []


def test_amount_formats():
    assert [S._amount(x) for x in ("1 299 kr", "€ 45,00", "12,50 zł", "£9.99", "3.990 Kč", "1,299.00 EUR")] == \
        [1299.0, 45.0, 12.5, 9.99, 3990.0, 1299.0]


def test_for_url(mini, tmp_path):
    recs = MINI + [{"key": "ikea_com_fi_fi", "domain": "ikea.com", "home": "https://www.ikea.com/fi/fi/",
                    "status": "verified_free"},
                   {"key": "ikea_com_se_sv", "domain": "ikea.com", "home": "https://www.ikea.com/se/sv/",
                    "status": "verified_free"}]
    p = tmp_path / "r2.json"
    p.write_text(json.dumps({"sources": recs}))
    assert S.for_url("https://www.ikea.com/se/sv/search/?q=billy", p)["key"] == "ikea_com_se_sv"
    assert S.for_url("https://www.tori.fi/recommerce/forsale/search?q=x", p)["key"] == "tori_fi"
    assert S.for_url("https://unknown.example/", p) is None
