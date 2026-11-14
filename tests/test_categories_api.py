"""/api/categories*: the tree of everything you can buy (products + services) for the landing explorer,
the search-box suggestions and the hunt breadcrumb. Offline, in memory."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from agora import api

WEB = pathlib.Path(api.__file__).resolve().parent / "web"


@pytest.fixture(scope="module")
def c() -> TestClient:
    return TestClient(api.app)


def test_roots_have_counts_kinds_and_icons(c):
    r = c.get("/api/categories")
    assert r.status_code == 200
    j = r.json()
    items = j["items"]
    assert len(items) >= 25 and j["parent"] is None and j["total"] >= 25_000
    ids = {i["id"] for i in items}
    assert {"electronics", "furniture", "home-services", "trades"} <= ids
    kinds = {i["kind"] for i in items}
    assert {"product", "service"} <= kinds           # things and services side by side
    for i in items:
        assert i["icon"] == i["id"] and i["count"] > 0 and i["n"] > 0 and not i["leaf"]
    assert sum(i["count"] + 1 for i in items) == j["total"]
    assert len(r.content) < 8000                     # small


def test_children_sorted_by_size_with_path_and_language(c):
    j = c.get("/api/categories", params={"parent": "electronics", "lang": "fi"}).json()
    assert j["lang"] == "fi"
    assert j["parent"]["path"][0] == {"id": "electronics", "label": "Elektroniikka ja tietokoneet"}
    counts = [i["count"] for i in j["items"]]
    assert counts == sorted(counts, reverse=True)
    assert all(i["icon"] == "electronics" for i in j["items"])
    assert c.get("/api/categories", params={"parent": "electronics", "lang": "xx"}).json()["lang"] == "en"


def test_unknown_parent_is_404(c):
    assert c.get("/api/categories", params={"parent": "no-such-node"}).status_code == 404


def test_search_completes_a_half_typed_word_and_gives_the_path(c):
    j = c.get("/api/categories/search", params={"q": "sof", "limit": 8}).json()
    sofas = [h for h in j["items"] if h["id"] == "sp:fr-22"]
    assert sofas and sofas[0]["path"] == ["Furniture", "Sofas"] and sofas[0]["path_ids"] == ["furniture", "sp:fr-22"]
    j = c.get("/api/categories/search", params={"q": "putkimies", "lang": "fi"}).json()
    assert j["items"][0]["kind"] == "service" and j["items"][0]["path"][0] == "Remontti- ja rakennuspalvelut"
    paths = [tuple(h["path"]) for h in c.get("/api/categories/search", params={"q": "software", "limit": 12}).json()["items"]]
    assert len(paths) == len(set(paths))             # the same place is listed once
    assert c.get("/api/categories/search", params={"q": "a"}).json()["items"] == []


def test_classify_and_nodes(c):
    m = c.get("/api/categories/classify", params={"q": "plumber in berlin"}).json()["match"]
    assert m["path_ids"][0] == "trades" and m["kind"] == "service" and m["confidence"] >= 0.6
    j = c.get("/api/categories/nodes", params={"ids": "sp:co-2-2,nope,trades.plumbing", "lang": "de"}).json()
    assert [n["id"] for n in j["items"]] == ["sp:co-2-2", "trades.plumbing"]
    assert j["items"][0]["path_ids"] == ["electronics", "sp:co-2", "sp:co-2-2"]


def test_index_lists_category_endpoints(c):
    eps = c.get("/api").json()["endpoints"]
    assert any(k.startswith("GET /api/categories?") for k in eps)
    assert any(k.startswith("GET /api/categories/search") for k in eps)


def test_viewer_ships_the_tree():
    html = (WEB / "index.html").read_text()
    assert 'id="crumbs"' in html and "/web/css/tree.css" in html
    for f in ("js/tree.js", "js/cats.js", "js/suggest.js", "css/tree.css"):
        assert (WEB / f).is_file()
    tree = (WEB / "js" / "tree.js").read_text()
    assert "mountTree" in tree and "/api/categories" in (WEB / "js" / "cats.js").read_text()
    # the tree lives in the category navbar's dropdown (catnav.js), no longer on the landing page
    assert 'id="catnav"' in html and "/web/css/catnav.css" in html
    nav = (WEB / "js" / "catnav.js").read_text()
    assert "mountTree(treeHost" in nav and "import('./tree.js')" in nav and "huntcategory" in nav
    assert "mountCatnav" in (WEB / "js" / "main.js").read_text()
    assert "mountTree" not in (WEB / "js" / "landing.js").read_text()
    assert "mountSuggest" in (WEB / "js" / "main.js").read_text()
