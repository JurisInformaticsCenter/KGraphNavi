#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ページの選択（/resource・/collection・/graph）のテスト
"""

import pytest

from kgraphnavi.app import (
    Application,
    Pages,
    expand_prefixed,
    setconfig,
    build_application,
    create_app,
    BUILTIN_COLLECTION_PAGE,
)
from kgraphnavi.errors import ConfigError

DBO = "http://dbpedia.org/ontology/"
PREFIXES = {"dbo": DBO}


# --------------------------------------------------
# 接頭辞の展開
# --------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("dbo:Mountain", DBO + "Mountain"),
    ("http://dbpedia.org/ontology/Mountain", DBO + "Mountain"),
    ("<http://dbpedia.org/ontology/Mountain>", DBO + "Mountain"),
    ("unknown:Thing", "unknown:Thing"),
    ("*", "*"),
])
def test_expand_prefixed(name, expected):
    assert expand_prefixed(name, PREFIXES) == expected


# --------------------------------------------------
# /resource のページ
# --------------------------------------------------

def make_pages(*definitions):
    pages = Pages()
    for definition in definitions:
        definition = dict(definition)
        name = definition.pop("name")
        definition.setdefault("gadget", ["g"])
        pages.set_page(name, definition)
    pages.resolve_prefixes(PREFIXES)
    return pages


def test_rdftype2page_prefers_exact_match_over_wildcard():
    pages = make_pages(
        {"name": "Resource", "type": "*"},
        {"name": "Mountain", "type": "dbo:Mountain"},
    )
    assert pages.rdftype2page(DBO + "Mountain") == "Mountain"
    assert pages.rdftype2page(DBO + "River") == "Resource"


def test_rdftype2page_without_wildcard():
    pages = make_pages({"name": "Mountain", "type": DBO + "Mountain"})
    assert pages.rdftype2page(DBO + "River") is None


def test_class_only_on_collection_pages():
    with pytest.raises(ConfigError):
        make_pages({"name": "Mountain", "type": DBO + "Mountain", "class": "dbo:Mountain"})


# --------------------------------------------------
# /collection のページ
# --------------------------------------------------

class SuperclassSPARQL:
    """rdfs:subClassOf+ の問い合わせに、決めた上位クラスを返す"""

    def __init__(self, superclasses):
        self.superclasses = superclasses
        self.calls = []

    def get_superclasses_among(self, class_uri, candidates):
        self.calls.append((class_uri, list(candidates)))
        return set(self.superclasses.get(class_uri, ())) & set(candidates)


def make_application(pages, superclasses=None):
    application = Application.__new__(Application)
    application.pages = pages
    application.prefixes = PREFIXES
    application.class_page_cache = {}
    application.sparql_client = SuperclassSPARQL(superclasses or {})
    return application


def test_collection_page_exact_class():
    pages = make_pages(
        {"name": "Places", "type": "collection", "class": ["dbo:Place"]},
        {"name": "Mountains", "type": "collection", "class": "dbo:Mountain"},
    )
    application = make_application(pages)
    assert application.collection_page(DBO + "Mountain") == "Mountains"
    assert application.collection_page("dbo:Mountain") == "Mountains"
    # 完全一致なら上位クラスは問い合わせない
    assert application.sparql_client.calls == []


def test_collection_page_superclass_and_cache():
    pages = make_pages(
        {"name": "Places", "type": "collection", "class": ["dbo:Place"]},
        {"name": "Mountains", "type": "collection", "class": "dbo:Mountain"},
    )
    application = make_application(pages, {DBO + "Volcano": [DBO + "Mountain", DBO + "Place"]})
    # ページ定義の順で最初に見つかった上位クラスのページ
    assert application.collection_page(DBO + "Volcano") == "Places"
    assert application.collection_page(DBO + "Volcano") == "Places"
    assert len(application.sparql_client.calls) == 1


def test_collection_page_default_page_without_class_or_query():
    pages = make_pages(
        {"name": "Alps", "type": "collection", "query": "SELECT ?uri WHERE { ?uri ?p ?o }"},
        {"name": "Generic", "type": "collection"},
    )
    application = make_application(pages)
    # query を持つページは、他のクラスの代わりには使わない
    assert application.collection_page(DBO + "River") == "Generic"


def test_collection_page_builtin_fallback():
    pages = make_pages({"name": "Alps", "type": "collection", "query": "SELECT ?uri WHERE { ?uri ?p ?o }"})
    application = make_application(pages)
    assert application.collection_page(DBO + "River") == BUILTIN_COLLECTION_PAGE


def test_graph_page():
    pages = make_pages(
        {"name": "Resource", "type": "*"},
        {"name": "Stats", "type": "graph"},
    )
    assert make_application(pages).graph_page() == "Stats"
    assert make_application(make_pages({"name": "Resource", "type": "*"})).graph_page() is None


# --------------------------------------------------
# 設定
# --------------------------------------------------

def test_setconfig_adds_builtin_collection_page():
    cfg = setconfig([
        {"prefixes": PREFIXES},
        {"label_lang": "en"},
        {"def": "page", "name": "Resource", "type": "*", "gadget": ["Out"]},
        {"def": "gadget", "name": "Out", "get": {"type": "sparql", "src": "select * where { $uri ?p ?o }"},
         "show": {"type": "htable"}},
    ])
    assert BUILTIN_COLLECTION_PAGE in cfg["pages"].pagedict
    gadget = cfg["gadgetset"]["_collection_list"]
    src = gadget.extract_method["src"]
    assert "$collection" in src
    assert 'LANGMATCHES(LANG(?_preferred), "en")' in src
    assert gadget.page_size == 50


@pytest.mark.parametrize("definition", [
    {"def": "page", "name": "_Mine", "type": "*", "gadget": ["x"]},
    {"def": "gadget", "name": "_mine", "get": {"type": "sparql", "src": "x"}, "show": {"type": "htable"}},
])
def test_reserved_names(definition):
    with pytest.raises(ConfigError):
        setconfig([definition])


# --------------------------------------------------
# 画面（Flask）
# --------------------------------------------------

CONFIG = """
- title: TestKG
- prefixes:
    dbo: http://dbpedia.org/ontology/
- sample:
    collection:
      - dbo:Mountain,山
      - Alps,アルプス
- def: page
  name: Mountains
  type: collection
  class: dbo:Mountain
  gadget: [list]
- def: page
  name: Alps
  type: collection
  query: "SELECT ?uri WHERE { ?uri dbo:locatedInArea dbo:Alps }"
  gadget: [list]
- def: page
  name: Stats
  type: graph
  gadget: [triples]
- def: page
  name: Resource
  type: '*'
  gadget: [triples]
- def: gadget
  name: list
  get:
    type: sparql
    src: "SELECT ?entity WHERE { ?entity ?p ?o }"
  show:
    type: htable
- def: gadget
  name: triples
  get:
    type: sparql
    src: "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
  show:
    type: htable
"""


@pytest.fixture
def client_and_queries(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    application = build_application(str(config), endpoint="http://example.org/sparql")
    return create_app(application).test_client(), sent


def test_collection_by_class_uses_class_page(client_and_queries):
    client, sent = client_and_queries
    html = client.get(f"/collection?class={DBO}Mountain").get_data(as_text=True)
    assert "Mountain(Mountains)" in html
    assert any(f"?uri a <{DBO}Mountain> ." in q for q in sent)


def test_collection_by_unknown_class_uses_builtin_page(client_and_queries):
    client, sent = client_and_queries
    response = client.get("/collection?class=dbo:River")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "(_Collection)" not in html
    assert ">一覧<" in html
    assert any("?uri a dbo:River ." in q for q in sent)
    # 上位クラスの問い合わせは rdfs:subClassOf+ を使う
    assert any("rdfs:subClassOf+" in q for q in sent)


def test_collection_by_view(client_and_queries):
    client, sent = client_and_queries
    response = client.get("/collection?view=Alps")
    assert response.status_code == 200
    assert any("dbo:locatedInArea dbo:Alps" in q for q in sent)


def test_collection_errors(client_and_queries):
    client, _sent = client_and_queries
    assert client.get("/collection").status_code == 400
    assert client.get("/collection?view=Stats").status_code == 404
    assert client.get("/collection?view=Nothing").status_code == 404


def test_graph_route(client_and_queries):
    client, sent = client_and_queries
    response = client.get("/graph")
    assert response.status_code == 200
    assert any("COUNT(*)" in q for q in sent)


def test_top_page_collection_samples(client_and_queries):
    client, _sent = client_and_queries
    html = client.get("/").get_data(as_text=True)
    assert 'href="/collection?class=dbo%3AMountain"' in html
    assert 'href="/collection?view=Alps"' in html


def test_graph_route_without_graph_page(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", lambda self, q: [])
    config = tmp_path / "test.yaml"
    config.write_text(
        "- def: page\n  name: Resource\n  type: '*'\n  gadget: [g]\n"
        "- def: gadget\n  name: g\n  get:\n    type: sparql\n    src: 'select * where { $uri ?p ?o }'\n"
        "  show:\n    type: htable\n",
        encoding="utf-8",
    )
    client = create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client()
    assert client.get("/graph").status_code == 404
