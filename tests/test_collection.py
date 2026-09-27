#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Collection（コレクション）のテスト

- 生成・絞り込み・集合演算がSPARQLを実行しない（遅延評価）こと
- 生成されるSPARQLの形
- 不正な値が拒否されること
"""

import pytest

from kgraphnavi.collection import (
    Collection,
    ClassCollection,
    QueryCollection,
    UriCollection,
    FilteredCollection,
    UnionCollection,
    IntersectCollection,
    MinusCollection,
    ValueCondition,
    RangeCondition,
)
from kgraphnavi.errors import CollectionError
from kgraphnavi.terms import ValueTermError


class DummySPARQL:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params))
        return self.results


def uri_rows(*uris, variable="uri"):
    return [{variable: {"type": "uri", "value": uri}} for uri in uris]


MOUNTAIN = "http://example.org/Mountain"
COUNTRY = "http://example.org/country"
JAPAN = "http://example.org/Japan"
FRANCE = "http://example.org/France"


# --------------------------------------------------
# 生成
# --------------------------------------------------

def test_from_uris():
    sparql = DummySPARQL()
    collection = Collection.from_uris(sparql, ["http://example.org/A", "http://example.org/B"])
    assert isinstance(collection, UriCollection)
    assert collection.sparql is sparql
    assert collection.uris == ["http://example.org/A", "http://example.org/B"]
    assert collection.query is None
    assert collection.params == {}
    assert collection.conditions == ()


def test_from_query():
    sparql = DummySPARQL()
    query = "SELECT ?uri WHERE { ?uri a <http://example.org/Mountain> . }"
    collection = Collection.from_query(sparql, query, params={"x": "1"})
    assert isinstance(collection, QueryCollection)
    assert collection.query == query
    assert collection.params == {"x": "1"}
    assert collection.uris is None


def test_from_class():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    assert isinstance(collection, ClassCollection)
    assert "?uri a <http://example.org/Mountain> ." in collection.get_query()


def test_from_class_accepts_prefixed_name():
    collection = Collection.from_class(DummySPARQL(), "dbo:Mountain")
    assert "?uri a dbo:Mountain ." in collection.get_query()


@pytest.mark.parametrize("bad", [
    "Mountain",
    "http://example.org/a b",
    "<http://example.org/A> . ?s ?p ?o",
    'http://example.org/"x',
])
def test_from_class_rejects_invalid_iri(bad):
    with pytest.raises(ValueTermError):
        Collection.from_class(DummySPARQL(), bad)


def test_from_uris_rejects_invalid_iri():
    with pytest.raises(ValueTermError):
        Collection.from_uris(DummySPARQL(), ["http://example.org/A> } DELETE {"])


def test_query_collection_requires_uri_variable():
    with pytest.raises(CollectionError):
        Collection.from_query(DummySPARQL(), "SELECT ?x WHERE { ?x a <http://e/C> }")


def test_query_collection_rejects_prefix():
    with pytest.raises(CollectionError):
        Collection.from_query(
            DummySPARQL(),
            "PREFIX dbo: <http://dbpedia.org/ontology/>\nSELECT ?uri WHERE { ?uri a dbo:Mountain }",
        )


# --------------------------------------------------
# URI取得
# --------------------------------------------------

def test_get_uris_from_uris_does_not_query():
    sparql = DummySPARQL()
    collection = Collection.from_uris(sparql, ["http://example.org/A", "http://example.org/B"])
    assert collection.get_uris() == ["http://example.org/A", "http://example.org/B"]
    assert collection.get_uris(limit=1, offset=1) == ["http://example.org/B"]
    assert collection.count() == 2
    assert sparql.calls == []


def test_get_uris_from_query():
    sparql = DummySPARQL(uri_rows("http://example.org/A"))
    collection = Collection.from_query(
        sparql,
        "SELECT ?uri WHERE { ?uri a <http://example.org/Mountain> . }",
        params={"lang": "en"},
    )
    assert collection.get_uris() == ["http://example.org/A"]
    assert len(sparql.calls) == 1
    query, params = sparql.calls[0]
    assert query.startswith("SELECT DISTINCT ?uri")
    # 利用者のqueryは副問い合わせとして埋め込まれる
    assert "?uri a <http://example.org/Mountain> ." in query
    assert params == {"lang": "en"}


def test_get_uris_with_limit_and_offset():
    sparql = DummySPARQL(uri_rows("http://example.org/A"))
    Collection.from_class(sparql, MOUNTAIN).get_uris(limit=10, offset=20)
    query, _ = sparql.calls[0]
    assert "ORDER BY ?uri" in query
    assert "LIMIT 10" in query
    assert "OFFSET 20" in query


def test_get_uris_with_variable():
    sparql = DummySPARQL(uri_rows("http://example.org/A", variable="entity"))
    collection = Collection.from_class(sparql, MOUNTAIN)
    assert collection.get_uris("entity") == ["http://example.org/A"]


def test_count():
    sparql = DummySPARQL([{"count": {"type": "literal", "value": "42"}}])
    collection = Collection.from_class(sparql, MOUNTAIN)
    assert collection.count() == 42
    query, _ = sparql.calls[0]
    assert "COUNT(DISTINCT ?uri)" in query


# --------------------------------------------------
# 絞り込み
# --------------------------------------------------

def test_filter_returns_new_collection_and_is_lazy():
    sparql = DummySPARQL()
    collection = Collection.from_class(sparql, MOUNTAIN)
    filtered = collection.filter(COUNTRY, JAPAN)
    assert isinstance(filtered, FilteredCollection)
    assert filtered is not collection
    assert filtered.base is collection
    assert filtered.filters == [(COUNTRY, JAPAN)]
    assert collection.filters == []
    assert sparql.calls == []


def test_filter_chain_is_flattened():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    filtered = collection.filter(COUNTRY, JAPAN, name="country").filter(
        "http://example.org/range", "Alps", name="range"
    )
    assert filtered.base is collection
    assert [c.name for c in filtered.conditions] == ["country", "range"]


def test_filter_single_iri_uses_triple_pattern():
    sparql = DummySPARQL(uri_rows("http://example.org/A"))
    Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, JAPAN).get_uris()
    query, _ = sparql.calls[0]
    assert "?uri <http://example.org/country> <http://example.org/Japan> ." in query


def test_filter_multiple_values_is_or():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, [JAPAN, FRANCE]).get_uris()
    query, _ = sparql.calls[0]
    assert "?uri <http://example.org/country> ?_c0 ." in query
    assert "?_c0 IN (<http://example.org/Japan>, <http://example.org/France>)" in query


def test_filter_literal_value_is_quoted_and_compared_as_string():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter(
        "caselawp:訴訟類型", ["行政訴訟", "民事訴訟"], value_type="literal"
    ).get_uris()
    query, _ = sparql.calls[0]
    assert "?uri caselawp:訴訟類型 ?_c0 ." in query
    assert 'STR(?_c0) IN ("行政訴訟", "民事訴訟")' in query


def test_filter_auto_value_type():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, [JAPAN, "Japan"]).get_uris()
    query, _ = sparql.calls[0]
    assert "?_c0 IN (<http://example.org/Japan>)" in query
    assert 'STR(?_c0) IN ("Japan")' in query


def test_filter_literal_value_is_escaped():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter(
        "rdfs:label", 'x") } DELETE WHERE { ?s ?p ?o } #', value_type="literal"
    ).get_uris()
    query, _ = sparql.calls[0]
    assert '"x\\") } DELETE WHERE { ?s ?p ?o } #"' in query


def test_filter_rejects_invalid_iri_value():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    with pytest.raises(ValueTermError):
        collection.filter(COUNTRY, "http://example.org/a> . ?s ?p ?o", value_type="iri")


def test_filter_rejects_invalid_predicate():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    with pytest.raises(ValueTermError):
        collection.filter("dbo:x } ?s ?p ?o {", JAPAN)


def test_filter_accepts_property_path():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter("dct:subject/skos:broader*", "dbc:Alps").get_uris()
    query, _ = sparql.calls[0]
    assert "?uri dct:subject/skos:broader* dbc:Alps ." in query


def test_filter_on_uri_collection_queries():
    sparql = DummySPARQL(uri_rows("http://example.org/A"))
    collection = Collection.from_uris(sparql, ["http://example.org/A", "http://example.org/B"])
    assert collection.filter(COUNTRY, JAPAN).get_uris() == ["http://example.org/A"]
    query, _ = sparql.calls[0]
    assert "VALUES ?uri { <http://example.org/A> <http://example.org/B> }" in query
    assert "?uri <http://example.org/country> <http://example.org/Japan> ." in query


def test_without_removes_named_conditions():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    filtered = collection.filter(COUNTRY, JAPAN, name="country").filter(
        "http://example.org/range", "Alps", name="range"
    )
    assert [c.name for c in filtered.without({"country"}).conditions] == ["range"]
    assert filtered.without({"country", "range"}) is collection
    assert filtered.without({"unknown"}) is filtered


# --------------------------------------------------
# 範囲
# --------------------------------------------------

def test_filter_range_numeric():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter_range(
        "dbo:elevation", "decimal", 1000, "3000.5"
    ).get_uris()
    query, _ = sparql.calls[0]
    assert "?uri dbo:elevation ?_c0 ." in query
    assert (
        'FILTER(?_c0 >= "1000"^^<http://www.w3.org/2001/XMLSchema#decimal> '
        '&& ?_c0 <= "3000.5"^^<http://www.w3.org/2001/XMLSchema#decimal>)'
    ) in query


def test_filter_range_one_side():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter_range(
        "dbo:elevation", "integer", maximum=500
    ).get_uris()
    query, _ = sparql.calls[0]
    assert 'FILTER(?_c0 <= "500"^^<http://www.w3.org/2001/XMLSchema#integer>)' in query


def test_filter_range_date():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter_range(
        "caselawp:判決日", "date", "2000-01-01", "2010-12-31"
    ).get_uris()
    query, _ = sparql.calls[0]
    assert '?_c0 >= "2000-01-01"^^<http://www.w3.org/2001/XMLSchema#date>' in query
    assert '?_c0 <= "2010-12-31"^^<http://www.w3.org/2001/XMLSchema#date>' in query


def test_filter_range_year_unit():
    sparql = DummySPARQL()
    Collection.from_class(sparql, MOUNTAIN).filter_range(
        "caselawp:判決日", "date", 2000, 2010, unit="year"
    ).get_uris()
    query, _ = sparql.calls[0]
    assert "FILTER(YEAR(?_c0) >= 2000 && YEAR(?_c0) <= 2010)" in query


@pytest.mark.parametrize("datatype,value", [
    ("integer", "12a"),
    ("integer", "1; DROP"),
    ("decimal", "abc"),
    ("date", "2000-13-01"),
    ("date", '2000-01-01"^^<x>'),
])
def test_filter_range_rejects_invalid_values(datatype, value):
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN)
    with pytest.raises(ValueTermError):
        collection.filter_range("dbo:x", datatype, value)


def test_filter_range_requires_a_bound():
    with pytest.raises(CollectionError):
        RangeCondition("dbo:x", "integer")


def test_filter_range_rejects_unknown_datatype():
    with pytest.raises(CollectionError):
        RangeCondition("dbo:x", "string", 1)


# --------------------------------------------------
# 集合演算
# --------------------------------------------------

def test_set_operations_are_lazy_and_typed():
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN)
    b = Collection.from_class(sparql, "http://example.org/Volcano")
    assert isinstance(a | b, UnionCollection)
    assert isinstance(a & b, IntersectCollection)
    assert isinstance(a - b, MinusCollection)
    assert isinstance(a.union(b), UnionCollection)
    assert sparql.calls == []


def test_union_query():
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN)
    b = Collection.from_class(sparql, "http://example.org/Volcano")
    (a | b).get_uris()
    query, _ = sparql.calls[0]
    assert "UNION" in query
    assert "?uri a <http://example.org/Mountain> ." in query
    assert "?uri a <http://example.org/Volcano> ." in query


def test_intersect_query():
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN)
    b = Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, JAPAN)
    (a & b).get_uris()
    query, _ = sparql.calls[0]
    assert "UNION" not in query and "MINUS" not in query
    assert query.count("SELECT DISTINCT ?uri") == 3  # 外側 + 各オペランド


def test_minus_query():
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN)
    b = Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, JAPAN)
    (a - b).get_uris()
    query, _ = sparql.calls[0]
    assert "MINUS {" in query


def test_operands_are_scoped_so_condition_variables_do_not_clash():
    """両オペランドの内部変数 ?_c0 は副問い合わせの中に閉じている。"""
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN).filter(COUNTRY, [JAPAN, FRANCE])
    b = Collection.from_class(sparql, MOUNTAIN).filter("dbo:range", ["dbr:Alps", "dbr:Andes"])
    query = (a & b).get_query()
    # ?_c0 は2つの副問い合わせにそれぞれ現れるが、各副問い合わせは ?uri だけを返す
    assert query.count("?_c0 IN") == 2
    assert query.count("SELECT DISTINCT ?uri") == 3


def test_filter_after_set_operation():
    sparql = DummySPARQL()
    a = Collection.from_class(sparql, MOUNTAIN)
    b = Collection.from_class(sparql, "http://example.org/Volcano")
    filtered = (a | b).filter(COUNTRY, JAPAN)
    assert isinstance(filtered.base, UnionCollection)
    filtered.get_uris()
    query, _ = sparql.calls[0]
    assert "UNION" in query
    assert "?uri <http://example.org/country> <http://example.org/Japan> ." in query


def test_set_operation_merges_params():
    sparql = DummySPARQL()
    a = Collection.from_query(sparql, "SELECT ?uri WHERE { ?uri a $cls }", params={"cls": "x"})
    b = Collection.from_query(sparql, "SELECT ?uri WHERE { ?uri a $other }", params={"other": "y"})
    (a | b).get_uris()
    _, params = sparql.calls[0]
    assert params == {"cls": "x", "other": "y"}


def test_set_operation_requires_collections():
    with pytest.raises(CollectionError):
        UnionCollection(Collection.from_class(DummySPARQL(), MOUNTAIN), "x")


# --------------------------------------------------
# ガジェットへの埋め込み
# --------------------------------------------------

def test_to_subquery_exposes_only_given_variable():
    collection = Collection.from_class(DummySPARQL(), MOUNTAIN).filter(COUNTRY, [JAPAN, FRANCE])
    subquery = collection.to_subquery("?entity")
    assert subquery.startswith("{ SELECT DISTINCT (?uri AS ?entity)")
    assert "?_c0" in subquery
    assert subquery.rstrip().endswith("}")


# --------------------------------------------------
# ファセット
# --------------------------------------------------

def test_get_facets():
    sparql = DummySPARQL([
        {
            "value": {"type": "uri", "value": JAPAN},
            "label": {"type": "literal", "value": "Japan"},
            "count": {"type": "literal", "value": "3"},
        },
        {
            "value": {"type": "literal", "value": "Alps"},
            "count": {"type": "literal", "value": "1"},
        },
    ])
    collection = Collection.from_class(sparql, MOUNTAIN)
    facets = collection.get_facets(COUNTRY, lang="en", limit=20)
    assert facets == [
        {"value": JAPAN, "label": "Japan", "count": 3, "type": "uri"},
        {"value": "Alps", "label": "Alps", "count": 1, "type": "literal"},
    ]
    query, _ = sparql.calls[0]
    assert "COUNT(DISTINCT ?uri)" in query
    assert "GROUP BY ?value" in query
    assert "SAMPLE(?_label)" in query
    assert 'LANGMATCHES(LANG(?_label), "en")' in query
    assert "LIMIT 20" in query
    assert "<http://example.org/country>" in query


def test_get_facets_excludes_own_condition():
    sparql = DummySPARQL()
    collection = (
        Collection.from_class(sparql, MOUNTAIN)
        .filter(COUNTRY, JAPAN, name="country")
        .filter("http://example.org/continent", "http://example.org/Asia", name="continent")
    )
    collection.get_facets(COUNTRY, exclude={"country"})
    query, _ = sparql.calls[0]
    assert "<http://example.org/Japan>" not in query
    assert "<http://example.org/Asia>" in query


def test_get_facets_rejects_invalid_lang():
    with pytest.raises(ValueTermError):
        Collection.from_class(DummySPARQL(), MOUNTAIN).get_facets(COUNTRY, lang='en") } #')


def test_get_range():
    sparql = DummySPARQL([{
        "min": {"type": "literal", "value": "1990"},
        "max": {"type": "literal", "value": "2020"},
        "count": {"type": "literal", "value": "15"},
    }])
    result = Collection.from_class(sparql, MOUNTAIN).get_range("caselawp:判決日", unit="year")
    assert result == {"min": "1990", "max": "2020", "count": 15}
    query, _ = sparql.calls[0]
    assert "MIN(YEAR(?_v))" in query


def test_get_range_without_values():
    sparql = DummySPARQL([{"count": {"type": "literal", "value": "0"}}])
    assert Collection.from_class(sparql, MOUNTAIN).get_range("dbo:elevation") is None


def test_value_condition_validates_on_creation():
    with pytest.raises(CollectionError):
        ValueCondition(COUNTRY, ())
    with pytest.raises(CollectionError):
        ValueCondition(COUNTRY, (JAPAN,), value_type="number")
