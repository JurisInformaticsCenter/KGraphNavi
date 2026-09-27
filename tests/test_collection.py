#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      test_collection.py
## Collectionという集合オブジェクトそのものが正しく動くか
"""

import pytest

from kgraphnavi.collection import Collection


class DummySPARQL:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params))
        return self.results

def test_from_uris():
    sparql = DummySPARQL()

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    assert collection.sparql is sparql
    assert collection.uris == [
        "http://example.org/A",
        "http://example.org/B",
    ]
    assert collection.query is None
    assert collection.params == {}


def test_from_query():
    sparql = DummySPARQL()

    collection = Collection.from_query(
        sparql,
        "SELECT ?entity WHERE { ?entity a ?class }",
        params={"class": "http://example.org/Mountain"},
    )

    assert collection.sparql is sparql
    assert collection.query == (
        "SELECT ?entity WHERE { ?entity a ?class }"
    )
    assert collection.params == {
        "class": "http://example.org/Mountain"
    }


def test_collection_requires_uris_or_query():
    sparql = DummySPARQL()

    with pytest.raises(ValueError):
        Collection(sparql)


def test_collection_cannot_have_both_uris_and_query():
    sparql = DummySPARQL()

    with pytest.raises(ValueError):
        Collection(
            sparql,
            uris=["http://example.org/A"],
            query="SELECT ?entity WHERE { ?entity ?p ?o }",
        )

def test_get_uris_from_uris():
    sparql = DummySPARQL()

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    assert collection.get_uris() == [
        "http://example.org/A",
        "http://example.org/B",
    ]

    # URI列挙型ではSPARQLを実行しない
    assert sparql.calls == []
    
def test_get_uris_from_query():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/B",
                }
            },
        ]
    )

    collection = Collection.from_query(
        sparql,
        "SELECT ?uri WHERE { ?uri a ?class }",
        {"class": "http://example.org/Mountain"},
    )

    assert collection.get_uris() == [
        "http://example.org/A",
        "http://example.org/B",
    ]

    assert sparql.calls == [
        (
            "SELECT ?uri WHERE { ?uri a ?class }",
            {"class": "http://example.org/Mountain"},
        )
    ]
    
def test_get_uris_with_variable():
    sparql = DummySPARQL(
        [
            {
                "entity": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_query(
        sparql,
        "SELECT ?entity WHERE {}",
    )

    assert collection.get_uris("entity") == [
        "http://example.org/A"
    ]
    

def test_filter_returns_new_collection():
    sparql = DummySPARQL()

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert filtered is not collection

    # filter()ではまだSPARQLを実行しない
    assert filtered.uris == collection.uris
    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        )
]



    
def test_filter_get_uris():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert filtered.get_uris() == [
        "http://example.org/A",
    ]
    
    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "VALUES ?uri" in query
    assert "<http://example.org/A>" in query
    assert "<http://example.org/B>" in query
    assert "<http://example.org/C>" in query
    assert (
        "<http://example.org/country> "
        "<http://example.org/Japan>"
    ) in query
    assert params == {}

def test_filter_can_be_chained():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered2 = filtered.filter(
        "http://example.org/type",
        "http://example.org/Mountain",
    )

    assert filtered2 is not filtered

    assert filtered2.uris == collection.uris

    assert filtered2.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
        (
            "http://example.org/type",
            "http://example.org/Mountain",
        ),
    ]

def test_filter_can_be_chained_get_uris():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered = filtered.filter(
        "http://example.org/type",
        "http://example.org/Mountain",
    )

    assert filtered.get_uris() == [
        "http://example.org/A",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "VALUES ?uri" in query

    assert "<http://example.org/A>" in query
    assert "<http://example.org/B>" in query
    assert "<http://example.org/C>" in query

    assert (
        "<http://example.org/country> "
        "<http://example.org/Japan>"
    ) in query

    assert (
        "<http://example.org/type> "
        "<http://example.org/Mountain>"
    ) in query

    assert params == {}

def test_filter_query_collection():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/B",
                }
            },
        ]
    )

    collection = Collection.from_query(
        sparql,
        """
        SELECT DISTINCT ?uri
        WHERE {
            ?uri a <http://example.org/Mountain> .
        }
        """,
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert filtered is not collection
    assert filtered.uris is None

    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        )
    ]

    assert filtered.get_uris() == [
        "http://example.org/A",
        "http://example.org/B",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "SELECT DISTINCT ?uri" in query

    assert "?uri a <http://example.org/Mountain>" in query

    assert (
        "<http://example.org/country> "
        "<http://example.org/Japan>"
    ) in query

def test_filter_query_collection_can_be_chained():
    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_query(
        sparql,
        """
        SELECT DISTINCT ?uri
        WHERE {
            ?uri a <http://example.org/Mountain> .
        }
        """,
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered = filtered.filter(
        "http://example.org/heightClass",
        "high",
    )

    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
        (
            "http://example.org/heightClass",
            "high",
        ),
    ]

    assert filtered.get_uris() == [
        "http://example.org/A",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "?uri a <http://example.org/Mountain>" in query

    assert (
        "<http://example.org/country> "
        "<http://example.org/Japan>"
    ) in query

    # リテラル値の扱い（引用符・型）は Collection の作り替え（Step 1）で仕様化する
    assert "<http://example.org/heightClass>" in query
    
def test_get_facets():
    sparql = DummySPARQL(
        [
            {
                "value": {
                    "type": "uri",
                    "value": "http://example.org/Japan",
                },
                "label": {
                    "type": "literal",
                    "value": "Japan",
                },
                "count": {
                    "type": "literal",
                    "value": "20",
                },
            },
            {
                "value": {
                    "type": "uri",
                    "value": "http://example.org/USA",
                },
                "label": {
                    "type": "literal",
                    "value": "USA",
                },
                "count": {
                    "type": "literal",
                    "value": "15",
                },
            },
        ]
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    facets = collection.get_facets(
        "http://example.org/country",
    )

    assert facets == [
        {
            "value": "http://example.org/Japan",
            "label": "Japan",
            "count": 20,
        },
        {
            "value": "http://example.org/USA",
            "label": "USA",
            "count": 15,
        },
    ]

    assert len(sparql.calls) == 1
    
    query, params = sparql.calls[0]

    assert "GROUP BY ?value ?label" in query
    assert "COUNT(DISTINCT ?uri)" in query

    assert "<http://example.org/country>" in query

def test_filter_multiple_conditions():
    """複数のFacet条件を指定するとAND条件として保持される。"""

    sparql = DummySPARQL()

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered = filtered.filter(
        "http://example.org/continent",
        "http://example.org/Asia",
    )

    assert filtered is not collection

    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
        (
            "http://example.org/continent",
            "http://example.org/Asia",
        ),
    ]

def test_filter_multiple_conditions_get_uris():
    """複数のFacet条件がSPARQLにAND条件として反映される。"""

    sparql = DummySPARQL(
        [
            {
                "uri": {
                    "type": "uri",
                    "value": "http://example.org/A",
                }
            },
        ]
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered = filtered.filter(
        "http://example.org/continent",
        "http://example.org/Asia",
    )

    assert filtered.get_uris() == [
        "http://example.org/A",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "?uri <http://example.org/country> <http://example.org/Japan> ." in query
    assert "?uri <http://example.org/continent> <http://example.org/Asia> ." in query


def test_filter_does_not_modify_original_collection():
    """filter()は元のCollectionを変更しない。"""

    sparql = DummySPARQL()

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert collection.filters == []
    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
    ]

    assert collection.uris == [
        "http://example.org/A",
        "http://example.org/B",
    ]

