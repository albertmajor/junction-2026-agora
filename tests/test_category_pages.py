"""Category pages (owner, 14 Nov): a broad category ("Lifestyle Services") never hunts its own label; it opens a
page of concrete subcategories. Only concrete things and services are huntable."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from agora import api
from agora import taxonomy as tx
from agora.taxonomy import browse

WEB = pathlib.Path(api.__file__).resolve().parent / "web"


@pytest.fixture(scope="module")
def T():
    return tx.load()


@pytest.fixture(scope="module")
def c():
    return TestClient(api.app)


@pytest.mark.parametrize("label", ["Lifestyle Services", "Accessories", "Other personal services", "Home Services",
                                   "General Services", "Personal Care Services", "Supplies"])
def test_vague_labels_are_browse_only(label):
    ok, why = browse.assess("x:1", label, depth=3, n_children=0, n_desc=0, kind="service")
    assert not ok and why in ("vague", "other")


@pytest.mark.parametrize("label, kind", [("Gunsmith", "service"), ("City Bikes", "product"),
                                         ("Wedding photographer", "service"), ("Locksmith services", "service"),
                                         ("Home Health Care", "service"), ("Rangefinder Accessories", "product"),
                                         ("Headphones & Headsets", "product"), ("Personal trainer", "service")])
def test_concrete_labels_are_huntable(label, kind):
    assert browse.assess("x:1", label, depth=4, n_children=0, n_desc=0, kind=kind) == (True, None)


def test_groups_and_departments_are_browse_only():
    assert browse.assess("x:1", "Hair salons, barbers & stylists", depth=2, n_children=5, n_desc=9,
                         kind="service")[1] == "group"
    assert browse.assess("x:1", "Shoes", depth=2, n_children=30, n_desc=120, kind="product")[1] == "department"
    assert browse.assess("cpv:1", "Seats, chairs & related products", depth=3, n_children=3, n_desc=7,
                         kind="product")[1] == "official"
    assert browse.assess("electronics", "Electronics", depth=1, n_children=9, n_desc=900, kind="product")[1] == "root"


def test_tree_flags(T):
    assert T.meta["stats"]["huntable"] > 20000 and T.meta["stats"]["browse_only"]
    assert all(not T.huntable(T.ids[r]) for r in T.roots)
    for nid in ("yelp:gunsmith", "trades.plumbing", "events-leisure.weddings.wedding-photographer"):
        assert T.huntable(nid), nid
    assert T.node("trades.plumbing")["huntable"] is True
    assert T.node("beauty-wellness")["browse_reason"] == "root"


def test_lifestyle_services_is_merged_into_a_plain_root(T):
    assert T.resolve("sp:se-6-4") == "beauty-wellness"          # old id keeps resolving
    assert T.label(T._i("beauty-wellness")) == "Hair, Beauty & Wellness"
    assert "Beauty & Wellness Services" in T.syn[T._i("beauty-wellness")]   # old name stays searchable
    assert T.label(T._i("personal-services")) == "Care, Family & Everyday Help"
    assert not any(T.label(i) == "Lifestyle Services" for i in range(len(T)))


def test_products_are_not_filed_as_services(T):
    i = T._i("sp:sg-2-26-3")            # yoga mats used to sit under the yoga CLASS node, as a service
    assert T.kind[i] == "product" and T.path(i)[0] == "Sports & Outdoors"


def test_page_api(c):
    r = c.get("/api/categories/page", params={"id": "sp:se-6-4"}).json()
    assert r["id"] == "beauty-wellness" and r["asked"] == "sp:se-6-4" and r["huntable"] is False
    assert r["about"] and r["path"][-1]["label"] == "Hair, Beauty & Wellness"
    labels = [g["label"] for g in r["groups"]]
    assert "Hair salons & barbers" in labels and all(g["examples"] for g in r["groups"])
    assert [p["q"] for p in r["popular"]][:2] == ["haircut", "massage"]
    assert all(p["id"] for p in r["popular"])
    assert c.get("/api/categories/page", params={"id": "nope"}).status_code == 404
    # a menu leads with what people buy: the popular chips' groups come first
    el = c.get("/api/categories/page", params={"id": "electronics"}).json()
    assert el["groups"][0]["label"] != "Electronics Accessories"


def test_items_carry_huntable(c):
    roots = c.get("/api/categories").json()["items"]
    assert all(x["huntable"] is False for x in roots)
    kids = c.get("/api/categories", params={"parent": "trades"}).json()["items"]
    assert any(k["id"] == "trades.plumbing" and k["huntable"] for k in kids)


def test_search_within(c):
    r = c.get("/api/categories/search", params={"q": "hair", "within": "beauty-wellness"}).json()
    assert r["items"] and all("beauty-wellness" in h["path_ids"] for h in r["items"])


@pytest.mark.parametrize("q, page", [("lifestyle services", "beauty-wellness"), ("home services", "home-services"),
                                     ("electronics", "electronics")])
def test_typed_umbrella_names_open_the_page(c, q, page):
    m = c.get("/api/categories/classify", params={"q": q}).json()["match"]
    assert (m.get("browse") or {}).get("id") == page or (m["id"] == page and not m["huntable"] and m["exact"])


def test_typed_concrete_words_still_hunt(c):
    m = c.get("/api/categories/classify", params={"q": "massage in tampere"}).json()["match"]
    assert m["huntable"] and not m.get("browse")


def test_viewer_ships_the_category_page():
    html = (WEB / "index.html").read_text()
    assert 'id="catpage"' in html and "/web/css/catpage.css" in html
    assert "mountCatpage" in (WEB / "js" / "main.js").read_text()
    tree = (WEB / "js" / "tree.js").read_text()
    assert "openCategory" in tree and "canHunt" in tree
    assert "huntable === false" in (WEB / "js" / "suggest.js").read_text()
