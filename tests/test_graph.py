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
    assert "FILTER(?uri IN (<http://ex.org/a>))" in query


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
    positions = timeline_positions(nodes, edges)
    xs = {n: p["x"] for n, p in positions.items()}
    assert xs[DOC + "X"] < xs[DOC + "C"] < xs[DOC + "B"] < xs[DOC + "A"] < xs[DOC + "D"]
    # 同じ年のノードは縦に並べる
    rows = [cite("A", "B", 2000, 1990), cite("C", "D", 2000, 1990)]
    nodes, edges = collect_graph(rows, SHOW)
    p = timeline_positions(nodes, edges)
    assert p[DOC + "A"]["x"] == p[DOC + "C"]["x"]
    assert p[DOC + "A"]["y"] != p[DOC + "C"]["y"]
    # 辺でつながるノードは同じ高さの側に寄せる
    assert (p[DOC + "A"]["y"] < p[DOC + "C"]["y"]) == (p[DOC + "B"]["y"] < p[DOC + "D"]["y"])


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
            if "FILTER(?uri IN" in query:
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


# --------------------------------------------------
# 二部グラフ（判例と法令の条）・min_degree・ノードからコレクションへ・variants（2026.10.28）
# --------------------------------------------------

LAW = "http://lod4all.net/law/resource/129AC0000000089_"
BI_SHOW = {
    "type": "graph",
    "edges": [{"from": "entity", "to": "article", "directed": False}],
    "nodes": {
        "entity": {"label": "label", "kind": "判例", "x": "year"},
        "article": {"label": "articlelabel", "kind": "条", "min_degree": 2,
                    "collection": {"facet": "reflaw_core_clause"}},
    },
    "layout": "bipartite",
}


def ref(doc, article, year=2000):
    return {"entity": uri(DOC + doc), "label": lit(f"判例{doc}"), "year": lit(year),
            "article": uri(LAW + article), "articlelabel": lit(f"民法第{article}条")}


BI_ROWS = [ref("A", "709", 1990), ref("B", "709", 2000), ref("C", "709", 2010),
           ref("A", "1", 1990), ref("B", "1", 2000),
           ref("C", "90", 2010),                     # 1件の判例だけが参照する条
           ref("D", "415", 2015)]                    # D は 1件だけの条しか参照しない → 孤立して消える


def test_min_degree_drops_rarely_cited_articles():
    graph = build_graph(BI_ROWS, BI_SHOW)
    ids = {n["id"] for n in graph["nodes"]}
    assert ids == {DOC + "A", DOC + "B", DOC + "C", LAW + "709", LAW + "1"}
    assert graph["min_degree"] == 2 and graph["min_kinds"] == ["条"]
    # URL の graph.min で変えられる
    params = request_params(MultiDict([("graph.min", "1")]), path="/collection")
    graph = build_graph(BI_ROWS, BI_SHOW, params=params)
    assert LAW + "90" in {n["id"] for n in graph["nodes"]} and graph["min_degree"] == 1
    params = request_params(MultiDict([("graph.min", "3")]), path="/collection")
    assert {n["id"] for n in build_graph(BI_ROWS, BI_SHOW, params=params)["nodes"]} == \
        {DOC + "A", DOC + "B", DOC + "C", LAW + "709"}


def test_bipartite_positions_two_rows():
    graph = build_graph(BI_ROWS, BI_SHOW)
    assert graph["layout"] == "bipartite"
    assert set(graph["positions"]) == {"timeline", "bipartite"}
    nodes = {n["id"]: n for n in graph["nodes"]}
    # 条は上の段（y=0）、判例は下の段
    assert nodes[LAW + "709"]["position"]["y"] == 0 and nodes[LAW + "709"]["side"] == "top"
    assert nodes[DOC + "A"]["position"]["y"] > 0 and nodes[DOC + "A"]["side"] == "bottom"
    # 判例は年の順
    assert nodes[DOC + "A"]["position"]["x"] < nodes[DOC + "B"]["position"]["x"] < nodes[DOC + "C"]["position"]["x"]
    # 名前を常に出すのは上の段だけ
    assert nodes[LAW + "709"].get("labelled") and not nodes[DOC + "A"].get("labelled")
    # 条の大きさは参照する判例の数
    assert nodes[LAW + "709"]["size"] == 3


def test_bipartite_staggers_many_bottom_nodes():
    rows = [ref(f"N{i:03d}", "709", 1950 + i) for i in range(200)] + \
           [ref(f"N{i:03d}", "1", 1950 + i) for i in range(0, 200, 2)]
    graph = build_graph(rows, {**BI_SHOW, "max_nodes": 1000})
    ys = {n["position"]["y"] for n in graph["nodes"] if n["side"] == "bottom"}
    assert len(ys) > 1          # 下の段を何列かに互い違いに並べる
    xs = [n["position"]["x"] for n in graph["nodes"]]
    assert max(xs) - min(xs) < 200 * 22   # 1列に並べたときより狭い


def test_node_filter_url():
    params = request_params(MultiDict([("class", CLASS), ("tab", "5"), ("f.year.min", "2000")]), path="/collection")
    graph = build_graph(BI_ROWS, BI_SHOW, params=params)
    article = next(n for n in graph["nodes"] if n["id"] == LAW + "709")
    # コレクションのページでは、今の条件にその条の条件を加える（タブはそのまま）
    assert "f.reflaw_core_clause=" in article["filter"] and "tab=5" in article["filter"]
    assert "f.year.min=2000" in article["filter"]
    assert "filter" not in next(n for n in graph["nodes"] if n["id"] == DOC + "A")
    # コレクションでないページでは class のコレクションへ
    from kgraphnavi.graph import node_filter_url
    url = node_filter_url({"facet": "reflaw_core_clause", "class": "caselawo:CaseLawDocument"}, LAW + "709",
                          request_params(MultiDict(), path="/resource"))
    assert url.startswith("/collection?class=caselawo%3ACaseLawDocument&f.reflaw_core_clause=")
    assert node_filter_url({"facet": "x"}, LAW + "709", request_params(MultiDict(), path="/resource")) is None
    html = render_graph(graph, params)
    assert '"filter":' in html
    assert "表示する条: つながりが" in html and "graph.min=3" in html
    assert '<option value="bipartite" selected>2段に並べる</option>' in html


@pytest.mark.parametrize("nodes", [
    {"article": {"min_degree": 0}},
    {"article": {"collection": {"class": "x"}}},
    {"article": {"collection": {"facet": "a b"}}},
    {"article": {"collection": {"facet": "f", "colour": "red"}}},
])
def test_validate_graph_nodes_errors(nodes):
    with pytest.raises(ConfigError):
        validate_graph_show("g", {"type": "graph", "edges": [{"from": "entity", "to": "article"}], "nodes": nodes})


# ---- ガジェットの variants（画面で問い合わせ・表示を切り替える）----

from kgraphnavi.app import setconfig, parse_variants


def gadget_config(**extra):
    return {"def": "gadget", "name": "RefLawNetwork",
            "get": {"type": "sparql", "src": "SELECT * WHERE { $collection ?entity <p> ?article }"},
            "show": BI_SHOW, **extra}


VARIANTS = [
    {"name": "clause", "label": "条"},
    {"name": "law", "label": "法令",
     "get": {"src": "SELECT * WHERE { $collection ?entity <p>/<law> ?article }"},
     "show": {"nodes": {"entity": {"kind": "判例"}, "article": {"kind": "法令", "min_degree": 1}}}},
]


def test_setconfig_variants_and_graph_validation():
    cfg = setconfig([gadget_config(variants=VARIANTS)])
    assert [v["name"] for v in cfg["gadgetset"]["RefLawNetwork"].variants] == ["clause", "law"]
    # graph の設定の誤りは、設定を読むときにエラーにする（variants で重ねたものも）
    with pytest.raises(ConfigError):
        setconfig([gadget_config(show={**BI_SHOW, "layout": "spring"})])
    with pytest.raises(ConfigError):
        setconfig([gadget_config(variants=[{"name": "x", "show": {"outside": "grey"}}])])
    with pytest.raises(ConfigError):
        setconfig([gadget_config(get={"type": "sparql", "src": "x", "max_rows": 0})])


@pytest.mark.parametrize("variants", [
    [], "law", [{"label": "名前なし"}], [{"name": "a"}, {"name": "a"}], [{"name": "a", "colour": "x"}],
    [{"name": "a", "get": "x"}],
])
def test_parse_variants_errors(variants):
    with pytest.raises(ConfigError):
        parse_variants("g", {"variants": variants})


def test_make_gadget_switches_variant():
    class SPARQL:
        def __init__(self):
            self.queries = []

        def query(self, query, params=None):
            self.queries.append(query)
            return BI_ROWS

    sparql = SPARQL()
    gadget = setconfig([gadget_config(variants=VARIANTS)])["gadgetset"]["RefLawNetwork"]
    gadget.sparql_client = sparql
    application = Application.__new__(Application)
    application.gadgetset = {"RefLawNetwork": gadget}
    application.sparql_client = sparql
    application.max_rows = 100
    collection = Collection.from_class(sparql, CLASS)

    params = request_params(MultiDict([("class", CLASS), ("tab", "5")]), path="/collection")
    html = application.make_gadget("RefLawNetwork", None, params=params, collection=collection)
    assert '<span class="kg-variant current">条</span>' in html
    assert "v.RefLawNetwork=law" in html
    assert "<p>/<law>" not in sparql.queries[-1]

    params = request_params(MultiDict([("class", CLASS), ("tab", "5"), ("v.RefLawNetwork", "law"),
                                       ("graph.min", "3")]), path="/collection")
    html = application.make_gadget("RefLawNetwork", None, params=params, collection=collection)
    assert '<span class="kg-variant current">法令</span>' in html
    assert "<p>/<law>" in sparql.queries[-1]
    assert "表示する法令" in html
    # 条に戻すリンクでは、数の条件（graph.min）を外す
    switch = re.search(r'<a class="kg-variant" href="([^"]+)">条</a>', html).group(1)
    assert "v.RefLawNetwork=clause" in switch and "graph.min" not in switch
    # 元のガジェットの設定は変えない
    assert gadget.show_method["nodes"]["article"]["kind"] == "条"


# --------------------------------------------------
# 射影（共参照・書誌結合）と指標（PageRank・連結成分）（2026.10.28）
# --------------------------------------------------

from kgraphnavi.graph import components, pagerank, project_graph


def test_cocitation_projection():
    show = {**BI_SHOW, "project": {"keep": "article", "via": "entity", "min_weight": 1}, "layout": "force"}
    graph = build_graph(BI_ROWS, {**show, "nodes": {**BI_SHOW["nodes"],
                                                   "article": {**BI_SHOW["nodes"]["article"], "min_degree": 1}}})
    edges = {(e["source"], e["target"]): e["weight"] for e in graph["edges"]}
    # 709 と 1 は A・B の2件の判例が一緒に参照する。709 と 90 は C だけ
    assert edges[(LAW + "1", LAW + "709")] == 2
    assert edges[(LAW + "709", LAW + "90")] == 1
    assert all(n["kind"] == "条" for n in graph["nodes"])
    assert graph["via_kind"] == "判例"
    # 大きさは重みの合計（共有する判例の延べ数）
    node = next(n for n in graph["nodes"] if n["id"] == LAW + "709")
    assert node["size"] == 3 and node["strength"] == 3
    # 重みの下限（URL の graph.w）
    params = request_params(MultiDict([("graph.w", "2"), ("graph.min", "1")]), path="/collection")
    graph = build_graph(BI_ROWS, show, params=params)
    assert [(e["source"], e["target"]) for e in graph["edges"]] == [(LAW + "1", LAW + "709")]
    assert graph["min_weight"] == 2
    html = render_graph(graph, params)
    assert "線で結ぶ組: 共有する判例が" in html and "graph.w=3" in html


def test_coupling_projection_skips_hub():
    nodes, edges = collect_graph(BI_ROWS, BI_SHOW)
    # 709 は A・B・C の3件とつながる。max_shared=2 なら組を作るのに使わない
    new_nodes, new_edges, skipped = project_graph(nodes, edges, {"keep": "entity", "via": "article", "max_shared": 2})
    assert skipped == 1
    assert set(new_nodes) == {DOC + n for n in "ABCD"}
    assert {(e["source"], e["target"]): e["weight"] for e in new_edges.values()} == {(DOC + "A", DOC + "B"): 1}
    new_nodes, new_edges, skipped = project_graph(nodes, edges, {"keep": "entity", "via": "article"})
    assert skipped == 0
    assert {(e["source"], e["target"]): e["weight"] for e in new_edges.values()} == {
        (DOC + "A", DOC + "B"): 2, (DOC + "A", DOC + "C"): 1, (DOC + "B", DOC + "C"): 1}


def test_pagerank_and_components():
    def edge(s, t, directed=True, w=1):
        return {"source": s, "target": t, "directed": directed, "weight": w}
    nodes = {n: {} for n in "ABCDE"}
    edges = {1: edge("A", "C"), 2: edge("B", "C"), 3: edge("C", "D"), 4: edge("E", "E")}
    rank = pagerank(nodes, edges)
    assert abs(sum(rank.values()) - 1) < 1e-9
    assert rank["D"] > rank["C"] > rank["A"] == pytest.approx(rank["B"])
    # 向きのない辺は両方向に流すので、同じ形なら同じ値
    rank = pagerank({n: {} for n in "XYZ"}, {1: edge("X", "Y", False), 2: edge("Y", "Z", False)})
    assert rank["X"] == pytest.approx(rank["Z"]) and rank["Y"] > rank["X"]
    component, sizes = components(nodes, {1: edge("A", "C"), 2: edge("B", "C"), 3: edge("D", "E")})
    assert sizes == [3, 2]
    assert component["A"] == component["B"] == component["C"] == 1 and component["D"] == 2


def test_metrics_table():
    graph = build_graph(ROWS, SHOW, members=MEMBERS)
    rows = graph["metrics"]["rows"]
    assert rows[0]["id"] == DOC + "C"                      # 最も参照される判例
    assert graph["metrics"]["component_sizes"] == [4]
    html = render_graph(graph, request_params(MultiDict(), path="/collection"))
    assert "指標（PageRank の上位 4 件）・連結成分 1 個（最大 4 ノード）" in html
    assert "<th>参照されている</th>" in html and "<th>年</th>" in html
    assert f'data-node="{DOC}C"' in html
    # 図でノードを省いても、指標は省く前のグラフで計算する
    graph = build_graph(ROWS, {**SHOW, "max_nodes": 2}, members=MEMBERS)
    assert len(graph["metrics"]["rows"]) == 4 and len(graph["nodes"]) == 2
    html = render_graph(graph)
    assert "図で省いたノードも含めて" in html
    assert html.count('class="kg-graph-locate"') == 2      # 図に出ているものだけ「図で見る」
    # metrics: false なら出さない
    assert "kg-graph-metrics" not in render_graph(build_graph(ROWS, {**SHOW, "metrics": False}, members=MEMBERS))


@pytest.mark.parametrize("project", [
    {"keep": "article"},
    {"keep": "article", "via": "article"},
    {"keep": "article", "via": "nothere"},
    {"keep": "article", "via": "entity", "min_weight": 0},
    {"keep": "article", "via": "entity", "weight": 2},
])
def test_validate_project_errors(project):
    with pytest.raises(ConfigError):
        validate_graph_show("g", {**BI_SHOW, "project": project})
