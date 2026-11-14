"""Offline tests for agora.taxonomy (the merged tree of everything you can buy) and its build helpers."""
from __future__ import annotations

import gzip
import importlib.util
import json
import pathlib

import pytest

from agora import taxonomy as tx

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def T():
    return tx.load()


def _build_module():
    spec = importlib.util.spec_from_file_location("build_taxonomy", ROOT / "scripts" / "build_taxonomy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ shape of the tree

def test_tree_is_huge_and_well_formed(T):
    assert len(T) >= 25_000
    assert 25 <= len(T.roots) <= 35
    assert max(T.depth) <= 7
    assert len(set(T.ids)) == len(T.ids)
    for i, p in enumerate(T.parent):
        assert p < i                     # parents come first (depth-first export)


def test_roots_have_five_languages_and_services(T):
    roots = {T.ids[r]: T.labels[r] for r in T.roots}
    for rid, labels in roots.items():
        assert {"en", "fi", "de", "nl", "sv"} <= set(labels), rid
    for rid in ("home-services", "trades", "beauty-wellness", "health-services", "education", "events-leisure",
                "travel", "transport", "professional", "digital-services", "finance-insurance", "utilities"):
        assert rid in roots
        assert T.kind[T.by_id[rid]] == "service"
    assert T.kind[T.by_id["electronics"]] == "product"
    assert T.kind[T.by_id["software"]] == "digital"


def test_language_coverage(T):
    st = T.stats()
    n = st["nodes"]
    for lang in ("en", "fi", "de", "nl", "sv"):
        assert st["labels_per_lang"][lang] > 0.6 * n, lang
    assert sum(st["per_root"].values()) == n


def test_sources_and_licences_recorded(T):
    names = " ".join(s["name"] for s in T.meta["sources"])
    for want in ("Shopify", "Google", "CPV", "NACE", "Yelp"):
        assert want in names
    assert all(s.get("licence") for s in T.meta["sources"])


# ------------------------------------------------------------------ API

@pytest.mark.parametrize("query, root, label", [
    ("city bike", "sports-outdoors", "City Bikes"),
    ("plumber berlin", "trades", "Plumbing"),
    ("ps5 controller", "electronics", "Video Game Controllers"),
    ("wedding photographer", "events-leisure", "Wedding photographer"),
    ("car insurance", "finance-insurance", "Car insurance"),
])
def test_owner_examples(T, query, root, label):
    c = T.classify(query)
    assert c["path_ids"][0] == root, c["path"]
    assert c["label"] == label, c["path"]
    assert c["confidence"] >= 0.6


@pytest.mark.parametrize("query, root", [
    ("putkimies tampere", "trades"),           # Finnish
    ("kinderwagen gebraucht", "baby-kids"),    # German, condition word dropped
    ("astianpesukone", "appliances"),          # Finnish inflection vs 'Astianpesukoneet'
    ("sähkösopimus", "utilities"),
    ("flat to rent in berlin", "property"),    # 'rent' kept: a flat, not shoes
    ("hotel in rome", "travel"),
    ("kallax shelf", "furniture"),             # synonym (model name)
])
def test_multilingual_and_synonyms(T, query, root):
    assert T.classify(query)["path_ids"][0] == root


def test_search_returns_paths_and_scores(T):
    hits = T.search("dishwasher", limit=5)
    assert hits and hits[0]["label"] == "Dishwashers"
    assert hits[0]["path"][0] == "Home Appliances"
    assert all(hits[i]["score"] >= hits[i + 1]["score"] for i in range(len(hits) - 1))
    assert T.search("") == []
    assert all(h["kind"] == "service" for h in T.search("repair", kind="service", limit=5))


def test_node_children_where_and_sizes(T):
    sofa = T.node(T.classify("sofa")["id"])
    assert sofa["bulky"] and sofa["size"] in ("large", "pickup")
    ctrl = T.node(T.classify("ps5 controller")["id"])
    assert not ctrl["bulky"]
    plumb = T.node("trades.plumbing")
    assert plumb["kind"] == "service" and plumb["size"] is None
    assert any(w["domain"] == "my-hammer.de" for w in plumb["where"])      # inherited from the root
    assert plumb["lanes"] == ["service"]
    kids = T.children("trades.plumbing")
    assert any(k["label"] == "Drain unblocking" for k in kids)
    assert {c["id"] for c in T.children()} == {T.ids[r] for r in T.roots}
    assert T.node("no-such-node") is None
    assert T.path("trades.plumbing", "fi") == ["Remontti- ja rakennuspalvelut", "Putkityöt"]


def test_module_level_helpers():
    assert tx.node("electronics")["label"] == "Electronics & Computers"
    assert tx.search("car insurance")[0]["label"] == "Car insurance"
    assert tx.stats()["nodes"] == len(tx.load())


def test_load_gzip_transparently(tmp_path):
    doc = {"name": "t", "sources": [], "nodes": [
        {"i": "a", "p": -1, "l": {"en": "Bikes", "fi": "Pyörät"}, "k": "p", "z": "large", "w": [["tori.fi", "used"]]},
        {"i": "b", "p": 0, "l": {"en": "City bikes"}, "s": ["kaupunkipyörä"]},
        {"i": "c", "p": -1, "l": {"en": "Bike repair"}, "k": "s"},
    ]}
    p = tmp_path / "tree.json.gz"
    p.write_bytes(gzip.compress(json.dumps(doc).encode()))
    t = tx.load(p)
    assert len(t) == 3
    n = t.node("b")
    assert n["size"] == "large" and n["kind"] == "product" and n["where"][0]["domain"] == "tori.fi"
    assert t.node("c")["size"] is None
    assert t.search("kaupunkipyörä")[0]["id"] == "b"
    assert t.search("bike repair")[0]["id"] == "c"


# ------------------------------------------------------------------ build helpers (no network)

def test_build_merge_rules():
    b = _build_module()
    assert b.key("Bookcases & Shelves") == b.key("bookcase and shelf")
    assert b.fold("Fahrräder", "de") == b.fold("Fahrraeder", "de")
    t = b.Tree()
    t.add("r", None, {"en": "Home"}, src="test", kind="product")
    t.add("r.s", "r", {"en": "Sofas", "fi": "Sohvat"}, src="test")
    # same meaning (other source, plural/case differ) merges, keeps the first label and adds the language
    hit = t.place("x:1", "r", {"en": "sofa", "de": "Sofas"}, src="other")
    assert hit == "r.s" and t.nodes["r.s"]["labels"]["de"] == "Sofas" and "other" in t.nodes["r.s"]["src"]
    # generic labels only merge among direct children
    t.add("r.s.acc", "r.s", {"en": "Accessories"}, src="test")
    assert t.place("x:2", "r", {"en": "Accessories"}, src="other") == "x:2"
    # depth cap: past MAX_DEPTH a node folds into its parent's synonyms
    parent = "r"
    for d in range(2, b.MAX_DEPTH + 1):
        parent = t.add(f"d{d}", parent, {"en": f"Level {d} thing"}, src="test")
    assert t.place("deep", parent, {"en": "Too deep"}, src="other") == parent
    assert "Too deep" in t.nodes[parent]["syn"]


def test_build_fuzzy_and_specialise():
    b = _build_module()
    t = b.Tree()
    t.add("r", None, {"en": "Appliances"}, src="curated", kind="product")
    t.add("r.dw", "r", {"en": "Dishwashers", "fi": "Astianpesukoneet"}, src="shopify")
    t.add("r.mw", "r", {"en": "Microwaves", "de": "Mikrowellen"}, src="shopify")
    tix = b.TokenIndex(t, ["r"])
    assert tix.fuzzy("Astianpesukone", "fi", ["r"]) == "r.dw"
    assert tix.specialize("Mikrowellen mit Grill", "de", ["r"]) == "r.mw"
    assert tix.specialize("Mikrowellen", "de", ["r"]) is None
