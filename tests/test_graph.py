"""ネットワーク図（show: type: graph）のテスト"""
import json
import re

import pytest
from werkzeug.datastructures import MultiDict

from kgraphnavi.app import Application, Gadget
from kgraphnavi.collection import Collection
from kgraphnavi.errors import ConfigError
from kgraphnavi.facets import request_params
from kgraphnavi.graph import (
    build_graph,
    collect_graph,
    membership_query,
    render_graph,
    timeline_positions,
    to_number,
    validate_graph_show,
)

DOC = "http://ds.rois.ac.jp/caselaw/resource/doc/"
CLASS = "http://ds.rois.ac.jp/caselaw/ontology/CaseLawDocument"

SHOW = {
    "type": "graph",
    "edges": [{"from": "entity", "to": "cited"}],
    "nodes": {
        "entity": {"label": "label", "kind": "判例", "x": "year"},
        "cited": {"label": "citedlabel", "kind": "判例", "x": "citedyear", "in_collection": "check"},
    },
}


def uri(v):
    return {"type": "uri", "value": v}


def lit(v):
    return {"type": "literal", "value": str(v)}


def cite(a, b, ya=2000, yb=1990):
    return {"entity": uri(DOC + a), "label": lit(f"判例{a}"), "year": lit(ya),
            "cited": uri(DOC + b), "citedlabel": lit(f"判例{b}"), "citedyear": lit(yb)}


ROWS = [
    cite("A", "B", 2010, 1990),
    cite("A", "C", 2010, 1980),
    cite("B", "C", 1990, 1980),
    cite("D", "C", 2015, 1980),
    cite("D", "X", 2015, 1970),     # X はコレクション外
    cite("D", "X", 2015, 1970),     # 同じ参照の行が重なっても辺は1本（重み 2）
]
MEMBERS = {DOC + n for n in "ABCD"}


def test_collect_graph_nodes_and_edges():
    nodes, edges = collect_graph(ROWS, SHOW)
    assert set(nodes) == {DOC + n for n in "ABCDX"}
    assert nodes[DOC + "A"]["in_collection"] is True       # entity は要素
    assert nodes[DOC + "X"]["in_collection"] == "check"
    # B は entity としても cited としても出るので、要素と分かる
    assert nodes[DOC + "B"]["in_collection"] is True
    assert nodes[DOC + "C"]["x"] == 1980
    assert edges[(DOC + "D", DOC + "X")]["weight"] == 2
    assert len(edges) == 5


def test_build_graph_hides_outside_by_default():
    graph = build_graph(ROWS, SHOW, members=MEMBERS)
    ids = {n["id"] for n in graph["nodes"]}
    assert ids == {DOC + n for n in "ABCD"}
    assert graph["outside"] == "hide" and graph["outside_count"] == 1
    assert len(graph["edges"]) == 4
    c = next(n for n in graph["nodes"] if n["id"] == DOC + "C")
    assert c["indegree"] == 3 and c["size"] == 3              # 既定の大きさは被参照数
    assert graph["layout"] == "timeline"
    assert all("position" in n for n in graph["nodes"])


def test_build_graph_shows_outside_with_url_param():
    params = request_params(MultiDict([("graph.outside", "show")]), path="/collection")
    graph = build_graph(ROWS, SHOW, params=params, members=MEMBERS)
    x = next(n for n in graph["nodes"] if n["id"] == DOC + "X")
    assert x["outside"] is True
    assert len(graph["edges"]) == 5


def test_build_graph_asks_collection_for_members():
    class FakeCollection:
        def __init__(self):
            self.queries = []

        def to_subquery(self, var):
            return f"    {{ SELECT ?uri WHERE {{ ?uri a <{CLASS}> }} }}"

        def _run(self, query):
            self.queries.append(query)
            return [{"uri": uri(DOC + "C")}]

    collection = FakeCollection()
    graph = build_graph(ROWS, SHOW, collection=collection)
    # 調べるのは in_collection: check で、要素と分かっていないノードだけ
    assert len(collection.queries) == 1
    assert f"<{DOC}C>" in collection.queries[0] and f"<{DOC}X>" in collection.queries[0]
    assert f"<{DOC}A>" not in collection.queries[0]
    assert DOC + "X" not in {n["id"] for n in graph["nodes"]}


def test_membership_query():
    query = membership_query("{ SELECT ?uri WHERE { ?uri a <http://ex.org/C> } }", ["http://ex.org/a"])
    assert "VALUES ?uri { <http://ex.org/a> }" in query


def test_isolated_nodes_are_hidden():
    rows = [cite("A", "X")]  # 参照先がコレクション外だけ → A も孤立
    graph = build_graph(rows, SHOW, members={DOC + "A"})
    assert graph["nodes"] == []
    html = render_graph(graph, request_params(MultiDict(), path="/collection"))
    assert "コレクションの中のつながりはありません" in html
    assert "graph.outside=show" in html


def test_max_nodes_keeps_high_degree():
    graph = build_graph(ROWS, {**SHOW, "max_nodes": 2}, members=MEMBERS)
    assert graph["truncated"] and graph["total_nodes"] == 4
    assert len(graph["nodes"]) == 2
    ids = {n["id"] for n in graph["nodes"]}
    assert DOC + "C" in ids                                     # 最も多くつながる
    html = render_graph(graph)
    assert "つながりの多い 2 件を表示しています" in html


def test_undirected_and_size_degree():
    show = {"type": "graph", "edges": [{"from": "entity", "to": "article", "directed": False}],
            "nodes": {"article": {"kind": "条"}}}
    rows = [{"entity": uri(DOC + "A"), "article": uri("http://law/1")},
            {"entity": uri(DOC + "B"), "article": uri("http://law/1")}]
    graph = build_graph(rows, show)
    law = next(n for n in graph["nodes"] if n["id"] == "http://law/1")
    assert law["size"] == 2 and law["label"] == "1"            # ラベルがなければ IRI の末尾
    assert law["outside"] is False                               # 要素でないノードはコレクション外にしない
    assert graph["layout"] == "force"                            # x がなければ力学モデル
    assert graph["kinds"] == ["entity", "条"]


@pytest.mark.parametrize("value,expected", [
    ("1990", 1990), ("1948-03-30", 1948), ("12.5", 12.5), ("昭和", None), (None, None),
])
def test_to_number(value, expected):
    assert to_number(value) == expected


def test_timeline_positions_orders_columns_by_x():
    nodes, edges = collect_graph(ROWS, SHOW)
    timeline_positions(nodes, edges)
    xs = {n: node["position"]["x"] for n, node in nodes.items()}
    assert xs[DOC + "X"] < xs[DOC + "C"] < xs[DOC + "B"] < xs[DOC + "A"] < xs[DOC + "D"]
    # 同じ年のノードは縦に並べる
    rows = [cite("A", "B", 2000, 1990), cite("C", "D", 2000, 1990)]
    nodes, edges = collect_graph(rows, SHOW)
    timeline_positions(nodes, edges)
    assert nodes[DOC + "A"]["position"]["x"] == nodes[DOC + "C"]["position"]["x"]
    assert nodes[DOC + "A"]["position"]["y"] != nodes[DOC + "C"]["position"]["y"]
    # 辺でつながるノードは同じ高さの側に寄せる
    assert (nodes[DOC + "A"]["position"]["y"] < nodes[DOC + "C"]["position"]["y"]) == \
           (nodes[DOC + "B"]["position"]["y"] < nodes[DOC + "D"]["position"]["y"])


def test_render_graph_payload_is_safe_json():
    rows = [cite("A", "B")]
    rows[0]["label"] = lit("</script><b>判例")
    graph = build_graph(rows, SHOW, members={DOC + "A", DOC + "B"})
    html = render_graph(graph, request_params(MultiDict(), path="/collection"), height=500)
    assert "</script><b>" not in html
    match = re.search(r'<script type="application/json" id="(kg-graph-\w+)-data">(.*?)</script>', html, re.S)
    payload = json.loads(match.group(2))
    labels = {e["data"]["label"] for e in payload["elements"] if "source" not in e["data"]}
    assert "</script><b>判例" in labels
    a = next(e for e in payload["elements"] if e["data"].get("id") == DOC + "A")
    assert a["data"]["href"].startswith("/resource?uri=")
    assert a["data"]["x"] == 2000
    assert f'kgDrawGraph("{match.group(1)}")' in html
    assert "height:500px" in html
    assert '<option value="timeline" selected>' in html


@pytest.mark.parametrize("show", [
    {"type": "graph"},
    {"type": "graph", "edges": [{"from": "a"}]},
    {"type": "graph", "edges": [{"from": "a", "to": "b"}], "layout": "spring"},
    {"type": "graph", "edges": [{"from": "a", "to": "b"}], "outside": "grey"},
    {"type": "graph", "edges": [{"from": "a", "to": "b"}], "nodes": {"b": {"in_collection": "maybe"}}},
    {"type": "graph", "edges": [{"from": "a", "to": "b"}], "max_nodes": 0},
    {"type": "graph", "edges": [{"from": "a", "to": "b"}], "colour": "red"},
])
def test_validate_graph_show_errors(show):
    with pytest.raises(ConfigError):
        validate_graph_show("g", show)


def test_make_gadget_draws_graph_in_collection_page():
    class SPARQL:
        def __init__(self):
            self.queries = []

        def query(self, query, params=None):
            self.queries.append(query)
            if "VALUES ?uri" in query:
                return [{"uri": uri(DOC + n)} for n in "ABCD"]
            return ROWS

    sparql = SPARQL()
    gadget = Gadget({"type": "sparql", "max_rows": 10000,
                     "src": "SELECT * WHERE { $collection ?entity <p> ?cited }"}, SHOW, None, title="参照関係")
    gadget.sparql_client = sparql
    application = Application.__new__(Application)
    application.gadgetset = {"CitationNetwork": gadget}
    application.sparql_client = sparql
    application.max_rows = 100
    params = request_params(MultiDict([("class", CLASS), ("tab", "3")]), path="/collection")
    html = application.make_gadget("CitationNetwork", None, params=params,
                                   collection=Collection.from_class(sparql, CLASS))
    assert "ノード 4・辺 4" in html
    assert "コレクション外の参照先（1 件）も表示する" in html
    assert "tab=3" in html and "graph.outside=show" in html
    # ガジェットの max_rows がアプリの上限より優先
    assert "LIMIT 10001" in sparql.queries[0]
