#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ファセット（URL パラメータの解釈、絞り込み、画面部品、ページ送り）のテスト
"""

from urllib.parse import parse_qsl, urlsplit

import pytest
from werkzeug.datastructures import MultiDict

from kgraphnavi.app import Application, Gadget, build_application, create_app, limit_rows
from kgraphnavi.collection import Collection
from kgraphnavi.facets import (
    request_params,
    facet_selection,
    page_number,
    make_url,
    render_value_facet,
    render_conditions,
    render_pager,
    value_label,
)

MOUNTAIN = "http://example.org/Mountain"
COUNTRY = "http://example.org/country"
JAPAN = "http://example.org/Japan"
FRANCE = "http://example.org/France"


def query_items(url):
    return parse_qsl(urlsplit(url).query)


# --------------------------------------------------
# URL パラメータの解釈
# --------------------------------------------------

def test_request_params_parses_facets():
    args = MultiDict([
        ("class", MOUNTAIN),
        ("f.country", JAPAN),
        ("f.country", FRANCE),
        ("f.country", JAPAN),   # 重複は除く
        ("f.range", ""),        # 空は無視
        ("f.year.min", "2000"),
        ("f.year.max", ""),
        ("page", "2"),
    ])
    params = request_params(args, path="/collection")
    assert params["class"] == MOUNTAIN
    assert params["page"] == "2"
    values, ranges = facet_selection(params)
    assert values == {"country": [JAPAN, FRANCE]}
    assert ranges == {"year": {"min": "2000"}}
    assert params["_path"] == "/collection"
    assert ("f.country", FRANCE) in params["_args"]


@pytest.mark.parametrize("value,expected", [("3", 3), ("0", 1), ("-2", 1), ("x", 1), (None, 1)])
def test_page_number(value, expected):
    assert page_number({"page": value} if value is not None else {}) == expected


def test_make_url_drops_page_and_items():
    params = request_params(MultiDict([
        ("class", MOUNTAIN), ("f.country", JAPAN), ("f.country", FRANCE), ("page", "3"),
    ]), path="/collection")
    url = make_url(params, drop_items={("f.country", JAPAN)})
    assert url.startswith("/collection?")
    assert query_items(url) == [("class", MOUNTAIN), ("f.country", FRANCE)]


def test_value_label():
    assert value_label("http://dbpedia.org/resource/Pennine_Alps") == "Pennine Alps"
    assert value_label("行政訴訟") == "行政訴訟"


# --------------------------------------------------
# 画面部品
# --------------------------------------------------

def facet_content(selected=(), args=()):
    params = request_params(MultiDict(list(args)), path="/collection")
    return {
        "name": "country",
        "label": "国",
        "candidates": [
            {"value": JAPAN, "label": "Japan", "count": 3, "type": "uri"},
            {"value": FRANCE, "label": "France", "count": 1200, "type": "uri"},
        ],
        "selected": list(selected),
        "params": params,
    }


def test_render_value_facet_form():
    html = render_value_facet(facet_content(
        selected=[JAPAN],
        args=[("class", MOUNTAIN), ("f.country", JAPAN), ("f.range", "http://example.org/Alps"), ("page", "4")],
    ))
    assert '<form class="facet" method="GET" action="/collection"' in html
    # 選択中の値はチェック済み
    assert f'name="f.country" value="{JAPAN}" checked' in html
    assert f'name="f.country" value="{FRANCE}">' in html
    assert ">1,200<" in html
    # 他のパラメータは hidden で引き継ぎ、自分のファセットとページは引き継がない
    assert f'<input type="hidden" name="class" value="{MOUNTAIN}">' in html
    assert 'name="f.range"' in html
    assert '<input type="hidden" name="f.country"' not in html
    assert 'name="page"' not in html
    assert 'class="facet-clear"' in html


def test_render_value_facet_keeps_selected_value_without_count():
    html = render_value_facet(facet_content(selected=["http://example.org/Peru"]))
    assert 'value="http://example.org/Peru" checked' in html
    assert ">Peru<" in html


def test_render_value_facet_escapes_html():
    content = facet_content()
    content["candidates"] = [{"value": "<b>x</b>", "label": "<script>", "count": 1}]
    html = render_value_facet(content)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_conditions():
    params = request_params(MultiDict([
        ("class", MOUNTAIN), ("f.country", JAPAN), ("f.year.min", "2000"), ("f.year.max", "2010"),
    ]), path="/collection")
    html = render_conditions(params, {"country": {"label": "国"}, "year": {"label": "年"}}, count=1234)
    assert "1,234 件" in html
    assert "国:" in html and ">Japan<" in html
    assert "年:" in html and "2000–2010" in html
    assert "すべての条件を外す" in html
    assert "/collection?class=http%3A%2F%2Fexample.org%2FMountain&amp;f.year.min=2000" in html


def test_render_pager():
    params = request_params(MultiDict([("class", MOUNTAIN), ("page", "2")]), path="/collection")
    html = render_pager(params, 2, 20, 57)
    assert "21–40 / 57 件" in html
    assert "page=3" in html
    assert "最初" in html and "最後" in html
    assert render_pager(params, 1, 20, 15) == ""


# --------------------------------------------------
# 絞り込みの適用
# --------------------------------------------------

class DummySPARQL:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params or {}))
        return self.results


def make_application(gadgets, sparql=None):
    application = Application.__new__(Application)
    application.gadgetset = gadgets
    application.sparql_client = sparql or DummySPARQL()
    application.max_rows = 100
    return application


def facet_gadget(name, predicate, **extra):
    return Gadget({"type": "facet", "name": name, "predicate": predicate, **extra}, {"type": "facet"}, None)


def test_apply_facets_values_and_ranges():
    application = make_application({
        "country": facet_gadget("country", COUNTRY, value_type="iri"),
        "year": facet_gadget("year", "dbo:year", kind="range", datatype="date", unit="year"),
    })
    params = request_params(MultiDict([
        ("class", MOUNTAIN), ("f.country", JAPAN), ("f.country", FRANCE),
        ("f.year.min", "2000"), ("f.unknown", "x"),
    ]))
    collection = application.apply_collection_filters(
        Collection.from_class(application.sparql_client, MOUNTAIN), params
    )
    names = [c.name for c in collection.conditions]
    assert names == ["country", "year"]
    query = collection.get_query()
    assert f"?_c0 IN (<{JAPAN}>, <{FRANCE}>)" in query
    assert "FILTER(YEAR(?_c1) >= 2000)" in query


def test_apply_facets_rejects_invalid_value():
    from kgraphnavi.terms import ValueTermError

    application = make_application({"country": facet_gadget("country", COUNTRY, value_type="iri")})
    params = request_params(MultiDict([("f.country", "http://x.org/a> . ?s")]))
    with pytest.raises(ValueTermError):
        application.apply_collection_filters(Collection.from_class(None, MOUNTAIN), params)


def test_apply_range_requires_datatype():
    from kgraphnavi.errors import GadgetError

    application = make_application({"year": facet_gadget("year", "dbo:year", kind="range")})
    params = request_params(MultiDict([("f.year.min", "2000")]))
    with pytest.raises(GadgetError):
        application.apply_collection_filters(Collection.from_class(None, MOUNTAIN), params)


def test_extract_facet_returns_render_content():
    sparql = DummySPARQL([{
        "value": {"type": "uri", "value": JAPAN},
        "label": {"type": "literal", "value": "Japan"},
        "count": {"type": "literal", "value": "3"},
    }])
    gadget = facet_gadget("country", COUNTRY, label="国", lang="en", limit=10)
    gadget.sparql_client = sparql
    application = make_application({"country": gadget}, sparql)
    params = request_params(MultiDict([("class", MOUNTAIN), ("f.country", JAPAN)]))
    collection = application.apply_collection_filters(Collection.from_class(sparql, MOUNTAIN), params)
    content = gadget.extract(None, application=application, params=params, collection=collection)
    assert content["name"] == "country"
    assert content["label"] == "国"
    assert content["selected"] == [JAPAN]
    assert content["candidates"][0]["count"] == 3
    query, _ = sparql.calls[0]
    # 自分自身の条件は候補の計算に使わない
    assert f"<{JAPAN}>" not in query
    assert "LIMIT 10" in query
    html = gadget.show(content)
    assert "checked" in html


# --------------------------------------------------
# ページ送り・行数の上限
# --------------------------------------------------

def test_paged_gadget_limits_collection_subquery():
    sparql = DummySPARQL([])
    gadget = Gadget(
        {"type": "sparql", "page_size": 20, "src": "SELECT ?entity WHERE { ?entity rdfs:label ?l }"},
        {"type": "htable"},
        None,
    )
    gadget.sparql_client = sparql
    application = make_application({}, sparql)
    collection = Collection.from_class(sparql, MOUNTAIN)
    gadget.extract(None, application=application, params={"page": "3"}, collection=collection)
    query, _ = sparql.calls[0]
    assert "ORDER BY ?uri\n  LIMIT 20\n  OFFSET 40" in query


def test_max_rows_truncates():
    rows = [{"x": {"type": "literal", "value": str(i)}} for i in range(101)]
    sparql = DummySPARQL(rows)
    gadget = Gadget({"type": "sparql", "src": "SELECT ?x WHERE { ?x ?p ?o }"}, {"type": "htable"}, None)
    gadget.sparql_client = sparql
    application = make_application({}, sparql)
    result = gadget.extract(None, application=application, params={})
    assert len(result) == 100
    assert result.truncated
    query, _ = sparql.calls[0]
    assert query.rstrip().endswith("LIMIT 101")


@pytest.mark.parametrize("query,changed", [
    ("SELECT ?x WHERE { ?x ?p ?o }", True),
    ("SELECT ?x WHERE { ?x ?p ?o } ORDER BY ?x", True),
    ("SELECT ?x WHERE { ?x ?p ?o } LIMIT 10", False),
    ("SELECT ?x WHERE { ?x ?p ?o } LIMIT 10 OFFSET 5", False),
    ("SELECT ?x WHERE { ?x ?p ?o } VALUES ?x { <http://e/a> }", False),
    ("SELECT ?x WHERE { { SELECT ?x WHERE { ?x ?p ?o } LIMIT 3 } ?x ?q ?r }", True),
])
def test_limit_rows(query, changed):
    result = limit_rows(query, 50)
    assert (result != query) == changed
    if changed:
        assert result.endswith("LIMIT 51")


# --------------------------------------------------
# 画面全体（Flask）
# --------------------------------------------------

CONFIG = """
- title: TestKG
- max_rows: 50
- def: page
  name: MountainCollection
  type: collection
  gadget: [country_facet, mountain_list]
- def: page
  name: Resource
  type: '*'
  gadget: [mountain_list]
- def: gadget
  name: country_facet
  get:
    type: facet
    name: country
    label: 国
    predicate: http://example.org/country
    value_type: iri
  show:
    type: facet
- def: gadget
  name: mountain_list
  title: 山の一覧
  get:
    type: sparql
    page_size: 2
    src: "SELECT ?entity WHERE { ?entity ?p ?o }"
  show:
    type: htable
    columns:
      - id: entity
        type: link
"""


def test_collection_page_end_to_end(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        if "COUNT(DISTINCT ?uri) AS ?count)\nWHERE" in query and "?value" not in query:
            return [{"count": {"type": "literal", "value": "5"}}]
        if "SELECT ?value" in query:
            return [{
                "value": {"type": "uri", "value": JAPAN},
                "label": {"type": "literal", "value": "Japan"},
                "count": {"type": "literal", "value": "5"},
            }]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    application = build_application(str(config), endpoint="http://example.org/sparql")
    assert application.max_rows == 50
    client = create_app(application).test_client()
    response = client.get(f"/collection?class={MOUNTAIN}&f.country={JAPAN}&page=2")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "5 件" in html
    assert 'class="collection-layout"' in html
    assert ">国<" in html and ">山の一覧<" in html
    assert "3–4 / 5 件" in html
    assert f'value="{JAPAN}" checked' in html
    list_query = next(q for q in sent if "?entity ?p ?o" in q)
    assert f"?uri a <{MOUNTAIN}> ." in list_query
    assert f"?uri <{COUNTRY}> <{JAPAN}> ." in list_query
    assert "LIMIT 2\n  OFFSET 2" in list_query

    bad = client.get(f"/collection?class={MOUNTAIN}&f.country=http://x.org/a%3E%20.")
    assert bad.status_code == 400



# --------------------------------------------------
# 表: 行のまとめ（group_by）とページ送り
# --------------------------------------------------

def test_group_rows_merges_multi_valued_columns():
    from kgraphnavi.render_utils import group_rows

    R = "http://dbpedia.org/resource/"
    uri = lambda n: {"type": "uri", "value": R + n}
    lit = lambda v: {"type": "literal", "value": v}
    data = [
        {"entity": uri("Breithorn"), "label": lit("Breithorn"), "country": uri("Italy")},
        {"entity": uri("Matterhorn"), "label": lit("Matterhorn"), "country": uri("Italy")},
        {"entity": uri("Breithorn"), "label": lit("Breithorn"), "country": uri("Switzerland")},
        {"entity": uri("Breithorn"), "label": lit("Breithorn"), "country": uri("Italy")},
    ]
    columns = [
        {"id": "entity", "type": "link", "string": "?label"},
        {"id": "country", "type": "link", "display": "localname"},
    ]
    rows = group_rows(data, "entity", columns)
    assert len(rows) == 2
    breithorn = rows[0]
    assert breithorn["entity"]["value"] == "Breithorn"
    assert breithorn["country"]["type"] == "multi"
    assert [cell["value"] for cell in breithorn["country"]["value"]] == ["Italy", "Switzerland"]
    assert rows[1]["country"]["value"] == "Italy"


def test_paged_gadget_disables_table_paging():
    rows = [{"entity": {"type": "uri", "value": "http://e/a"}}]
    paged = Gadget(
        {"type": "sparql", "page_size": 20, "src": "SELECT ?entity WHERE { ?entity ?p ?o }"},
        {"type": "htable", "columns": [{"id": "entity", "type": "link"}]},
        None,
    )
    plain = Gadget(
        {"type": "sparql", "src": "SELECT ?entity WHERE { ?entity ?p ?o }"},
        {"type": "htable", "columns": [{"id": "entity", "type": "link"}]},
        None,
    )
    paged_html = paged.show(rows)
    plain_html = plain.show(rows)
    assert "paging: false" in paged_html
    assert 'height: "auto"' in paged_html
    assert "paging: true" in plain_html
    # 閲覧用の表なので編集はできない
    assert "editing: false" in plain_html and "inserting: false" in plain_html


# --------------------------------------------------
# 範囲のファセット
# --------------------------------------------------

from kgraphnavi.facets import plan_bins, build_histogram, bound_param, render_range_facet


@pytest.mark.parametrize("minimum,maximum,bins,integer,expected", [
    (1947, 2023, 20, True, (1947, 4, 20)),
    (2000, 2000, 20, True, (2000, 1, 1)),
    (4000, 4808, 20, False, (4000, 50, 17)),
    (5, 5, 20, False, (5.0, 1.0, 1)),
    (0.3, 9.7, 10, False, (0.0, 1.0, 10)),
])
def test_plan_bins(minimum, maximum, bins, integer, expected):
    assert plan_bins(minimum, maximum, bins, integer=integer) == expected


@pytest.mark.parametrize("value,datatype,unit,upper,expected", [
    (1999, "date", None, False, "1999-01-01"),
    (1999, "date", None, True, "1999-12-31"),
    (1999, "dateTime", None, True, "1999-12-31T23:59:59"),
    (1999, "date", "year", True, "1999"),
    (4050.0, "decimal", None, True, "4050"),
    (0.5, "decimal", None, False, "0.5"),
    (12, "integer", None, False, "12"),
])
def test_bound_param(value, datatype, unit, upper, expected):
    assert bound_param(value, datatype, unit, upper=upper) == expected


def test_build_histogram_marks_selected_range_and_last_bin():
    counts = {0: 2, 1: 5, 3: 1, 4: 7}   # 4 は最大値ちょうど（最後の区間に入れる）
    items = build_histogram(
        counts, 2000, 1, 4, datatype="date", unit="year", selected={"min": "2001", "max": "2002"}
    )
    assert [item["count"] for item in items] == [2, 5, 0, 8]
    assert [item["in_range"] for item in items] == [False, True, True, False]
    assert items[1]["min_param"] == "2001" and items[1]["max_param"] == "2001"


def test_build_histogram_with_date_selection():
    items = build_histogram(
        {0: 1, 1: 1}, 1990, 5, 2, datatype="date", unit=None, selected={"min": "1996-03-01"}
    )
    assert items[0]["min_param"] == "1990-01-01" and items[0]["max_param"] == "1994-12-31"
    assert [item["in_range"] for item in items] == [False, True]


def range_content(**overrides):
    params = request_params(MultiDict([("class", MOUNTAIN), ("f.year.min", "2001")]), path="/collection")
    content = {
        "kind": "range",
        "name": "year",
        "label": "判決年",
        "datatype": "date",
        "unit": "year",
        "range": {"min": "2000", "max": "2003", "count": 15},
        "histogram": build_histogram(
            {0: 2, 1: 5, 3: 1}, 2000, 1, 4, datatype="date", unit="year", selected={"min": "2001"}
        ),
        "selected": {"min": "2001"},
        "params": params,
    }
    content.update(overrides)
    return content


def test_render_range_facet():
    html = render_range_facet(range_content())
    assert 'class="facet facet-range"' in html
    assert '<input type="number" name="f.year.min" value="2001" step="1" placeholder="2000"' in html
    assert 'name="f.year.max" value=""' in html
    # 自分の範囲以外のパラメータは引き継ぐ
    assert f'<input type="hidden" name="class" value="{MOUNTAIN}">' in html
    assert '<input type="hidden" name="f.year.min"' not in html
    # 棒グラフ: 各区間はその範囲で絞り込むリンク
    assert "<svg" in html and "判決年の分布" in html
    assert "f.year.min=2003&amp;f.year.max=2003" in html
    assert "<title>2001: 5 件</title>" in html
    assert html.count("<path") == 3      # 件数 0 の区間は棒を描かない
    assert "#b5cdee" in html              # 範囲外の棒
    assert "クリア" in html


def test_render_range_facet_date_inputs_and_empty():
    html = render_range_facet(range_content(unit=None, range=None, histogram=[], selected={}))
    assert 'type="date"' in html
    assert "値がありません" in html
    assert "クリア" not in html


def test_extract_range_facet():
    responses = [
        [{"min": {"type": "literal", "value": "2000"},
          "max": {"type": "literal", "value": "2003"},
          "count": {"type": "literal", "value": "15"}}],
        [{"bin": {"type": "literal", "value": "0"}, "count": {"type": "literal", "value": "4"}}],
    ]

    class SequenceSPARQL(DummySPARQL):
        def query(self, query, params=None):
            self.calls.append((query, params or {}))
            return responses[len(self.calls) - 1]

    sparql = SequenceSPARQL()
    gadget = facet_gadget("year", "caselawp:判決日", kind="range", datatype="date", unit="year", label="判決年")
    gadget.sparql_client = sparql
    application = make_application({"year": gadget}, sparql)
    params = request_params(MultiDict([("class", MOUNTAIN), ("f.year.min", "2001")]))
    collection = application.apply_collection_filters(Collection.from_class(sparql, MOUNTAIN), params)
    content = gadget.extract(None, application=application, params=params, collection=collection)
    assert content["kind"] == "range"
    assert content["range"] == {"min": "2000", "max": "2003", "count": 15}
    assert content["selected"] == {"min": "2001"}
    assert [item["count"] for item in content["histogram"]] == [4, 0, 0, 0]
    # 自分自身の範囲条件は、範囲・分布の計算に使わない
    assert all("YEAR(?_c" not in query for query, _ in sparql.calls)
    assert "<svg" in gadget.show(content)


def test_render_conditions_one_sided_range():
    params = request_params(MultiDict([("f.year.min", "2000")]), path="/collection")
    assert "2000 以上" in render_conditions(params, {})
    params = request_params(MultiDict([("f.year.max", "2010")]), path="/collection")
    assert "2010 以下" in render_conditions(params, {})
