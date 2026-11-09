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


def test_setconfig_text_search():
    assert setconfig([])["text_search"] == "auto"
    assert setconfig([{"text_search": "BIF"}])["text_search"] == "bif"
    with pytest.raises(ConfigError):
        setconfig([{"text_search": "fulltext"}])


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


# --------------------------------------------------
# ガジェットの一覧をコレクションとして表示
# --------------------------------------------------

GADGET_COLLECTION_CONFIG = """
- title: TestKG
- prefixes:
    ex: http://example.org/
- def: page
  name: Person
  type: http://example.org/Person
  gadget: [Involved]
- def: page
  name: Trials
  type: collection
  class: ex:Trial
  gadget: [TrialList]
- def: gadget
  name: Involved
  collection:
    var: trial
    class: ex:Trial
    title: 関与した裁判
    label: 関与した裁判をコレクションとして表示
  get:
    type: sparql
    src: "select ?trial ?name where { ?trial ex:judge $uri ; ex:name ?name }"
  show:
    type: htable
- def: gadget
  name: TrialList
  get:
    type: sparql
    src: "SELECT ?entity WHERE { $collection ?entity ex:name ?n }"
  show:
    type: htable
"""


@pytest.fixture
def gadget_collection_client(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        if "?target where" in query:
            return [{"target": {"type": "uri", "value": "http://example.org/Person"}}]
        if "select ?trial ?name" in query and "SELECT DISTINCT (?trial AS ?uri)" not in query:
            return [{"trial": {"type": "uri", "value": "http://example.org/T1"},
                     "name": {"type": "literal", "value": "事件1"}}]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(GADGET_COLLECTION_CONFIG, encoding="utf-8")
    application = build_application(str(config), endpoint="http://example.org/sparql")
    return create_app(application).test_client(), sent


def test_gadget_shows_collection_button(gadget_collection_client):
    client, _sent = gadget_collection_client
    html = client.get("/resource?uri=http://example.org/judgeA").get_data(as_text=True)
    assert 'class="gadget-action"' in html
    assert "関与した裁判をコレクションとして表示" in html
    assert "/collection?from=Involved&amp;uri=http%3A%2F%2Fexample.org%2FjudgeA&amp;class=ex%3ATrial" in html


def test_gadget_collection_page(gadget_collection_client):
    client, sent = gadget_collection_client
    sent.clear()
    response = client.get("/collection?from=Involved&uri=http://example.org/judgeA&class=ex:Trial")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "judgeA: 関与した裁判" in html
    # 裁判のページ（class: ex:Trial）のガジェットに、一覧から作ったコレクションが渡る
    query = next(q for q in sent if "?entity ex:name ?n" in q)
    assert "SELECT DISTINCT (?trial AS ?uri)" in query
    assert "?trial ex:judge <http://example.org/judgeA>" in query
    assert "FILTER(isIRI(?trial))" in query


def test_gadget_collection_errors(gadget_collection_client):
    client, _sent = gadget_collection_client
    assert client.get("/collection?from=TrialList").status_code == 404
    assert client.get("/collection?from=Nothing").status_code == 404
    # $uri を使うガジェットには uri が必要
    assert client.get("/collection?from=Involved").status_code == 400


def test_gadget_collection_config_validation():
    with pytest.raises(ConfigError):
        setconfig([{"def": "gadget", "name": "g", "collection": {"var": "a b"},
                    "get": {"type": "sparql", "src": "x"}, "show": {"type": "htable"}}])
    with pytest.raises(ConfigError):
        setconfig([{"def": "gadget", "name": "g", "collection": "doc",
                    "get": {"type": "list", "src": "x", "header": "a"}, "show": {"type": "htable"}}])


def test_gadget_collection_button_with_facet(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    def fake_exsparql(self, query):
        if "?target where" in query:
            return [{"target": {"type": "uri", "value": "http://example.org/Term"}}]
        return [{"doc": {"type": "uri", "value": "http://example.org/D1"}}]

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text("""
- def: page
  name: Term
  type: http://example.org/Term
  gadget: [Docs]
- def: gadget
  name: Docs
  collection:
    class: ex:Document
    facet: term
    label: このタームの文書
  get:
    type: sparql
    src: "select ?doc where { ?doc ex:subject $uri }"
  show:
    type: htable
""", encoding="utf-8")
    client = create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client()
    html = client.get("/resource?uri=http://example.org/T1").get_data(as_text=True)
    assert "/collection?class=ex%3ADocument&amp;f.term=http%3A%2F%2Fexample.org%2FT1" in html


# --------------------------------------------------
# 種類が複数あるリソース: ページのある種類を選ぶ(2026.11.5)
# --------------------------------------------------

MULTI_TYPE_CONFIG = """
- title: TestKG
- def: page
  name: Keyword
  type: http://lod4all.net/law/ontology/Keyword
  gadget: [g]
- def: page
  name: Resource
  type: '*'
  gadget: [d]
- def: gadget
  name: g
  title: キーワードのガジェット
  get:
    type: sparql
    src: 'select ?p ?o where { $uri ?p ?o }'
  show:
    type: htable
- def: gadget
  name: d
  title: 既定のガジェット
  get:
    type: sparql
    src: 'select ?p ?o where { $uri ?p ?o }'
  show:
    type: htable
"""


def test_resource_page_prefers_type_with_page(tmp_path, monkeypatch):
    # 「株主提案権」(law:株主提案権)は skos:Concept と lawo:Keyword。ページの無い種類が先に選ばれても、ページのある種類のページにする
    from kgraphnavi import sparql as sparql_module

    def fake_exsparql(self, query):
        if "?target where" in query:
            return [{"target": {"type": "uri", "value": "http://www.w3.org/2004/02/skos/core#Concept"}},
                    {"target": {"type": "uri", "value": "http://lod4all.net/law/ontology/Keyword"}},
                    {"target": {"type": "uri", "value": "http://aaa.example.org/First"}}]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(MULTI_TYPE_CONFIG, encoding="utf-8")
    client = create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client()
    html = client.get("/resource?uri=http://lod4all.net/law/resource/株主提案権").get_data(as_text=True)
    assert "キーワードのガジェット" in html and "既定のガジェット" not in html


# --------------------------------------------------
# ガジェットの focus: 問い合わせる前に $uri から別のリソースへ移る(2026.11.5)
# --------------------------------------------------

FOCUS_CONFIG = """
- title: TestKG
- def: page
  name: Resource
  type: '*'
  gadget: [g]
- def: gadget
  name: g
  title: 移った先のガジェット
  focus: '$uri rdfs:label ?l . ?new rdfs:label ?l'
  get:
    type: sparql
    src: 'select ?o where { $uri <http://example.org/p> ?o }'
  show:
    type: htable
"""


def _focus_client(tmp_path, monkeypatch, focused):
    from kgraphnavi import sparql as sparql_module
    seen = []

    def fake_exsparql(self, query):
        seen.append(query)
        if "?target where" in query:
            return [{"target": {"type": "uri", "value": "http://example.org/Thing"}}]
        if "?new where" in query:
            return [{"new": {"type": "uri", "value": u}} for u in focused]
        if "<http://example.org/p>" in query and "http://example.org/B" in query:
            return [{"o": {"type": "literal", "value": "Bの値"}}]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(FOCUS_CONFIG, encoding="utf-8")
    return create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client(), seen


def test_gadget_focus_moves_uri(tmp_path, monkeypatch):
    client, seen = _focus_client(tmp_path, monkeypatch, ["http://example.org/B"])
    html = client.get("/resource?uri=http://example.org/A").get_data(as_text=True)
    assert "Bの値" in html


def test_gadget_focus_keeps_self(tmp_path, monkeypatch):
    # 自分が候補にあれば自分のまま
    client, seen = _focus_client(tmp_path, monkeypatch, ["http://example.org/B", "http://example.org/A"])
    html = client.get("/resource?uri=http://example.org/A").get_data(as_text=True)
    assert "Bの値" not in html


def test_gadget_focus_not_found(tmp_path, monkeypatch):
    client, seen = _focus_client(tmp_path, monkeypatch, [])
    html = client.get("/resource?uri=http://example.org/A").get_data(as_text=True)
    assert "移った先のガジェット" in html and "該当するデータがありません" in html


def test_top_page_sample_sections(tmp_path, monkeypatch):
    """sample.sections: 見出しごとのまとまり（2026.11.8）"""
    from kgraphnavi import sparql as sparql_module

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", lambda self, q: [])
    config = tmp_path / "test.yaml"
    config.write_text(
        "- sample:\n"
        "    sections:\n"
        "      - title: 探す\n"
        "        describe: 説明文\n"
        "        collection: [Alps,アルプス]\n"
        "        search: [Matterhorn]\n"
        "        resource: ['http://example.org/x,エックス']\n"
        "- def: page\n  name: Alps\n  type: collection\n  class: 'http://example.org/M'\n  gadget: [g]\n"
        "- def: page\n  name: Resource\n  type: '*'\n  gadget: [g]\n"
        "- def: gadget\n  name: g\n  get:\n    type: sparql\n    src: 'select * where { $uri ?p ?o }'\n"
        "  show:\n    type: htable\n",
        encoding="utf-8",
    )
    client = create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client()
    html = client.get("/").get_data(as_text=True)
    assert "探す" in html and "説明文" in html
    assert 'href="/collection?view=Alps"' in html
    assert 'href="/search?q=Matterhorn"' in html
    assert 'href="/resource?uri=http%3A%2F%2Fexample.org%2Fx"' in html
    assert "リソースサンプル" not in html


def test_collection_view_with_class_only(client_and_queries):
    """query が無く class だけのコレクションのページを view= で開ける（2026.11.8）"""
    client, sent = client_and_queries
    response = client.get("/collection?view=Mountains")
    assert response.status_code == 200
    assert "Collectionを作成するための" not in response.get_data(as_text=True)
    assert any("Mountain" in q for q in sent)
