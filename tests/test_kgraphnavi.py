#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      test_kgraphnavi.py
## URLパラメータやGadget定義をCollection操作に変換できるか
"""

import pytest
from unittest.mock import Mock
from kgraphnavi.app import Gadget, Application
from kgraphnavi.collection import Collection
from kgraphnavi.errors import GadgetError

class DummySPARQL:
    """SPARQL呼び出しを記録する最小モック。"""

    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params or {}))
        return self.results
        
class DummyGadget:
    """Facet定義を持つGadgetの最小モック。"""

    def __init__(self, extract_method):
        self.extract_method = extract_method

class DummyPages:
    """make_page() テスト用の最小ページ定義。"""

    def __init__(self):
        self.pagedict = {}
        self.snippet = ""
    
class DummyApplication:
    """Collection関連テストに必要な部分だけを持つモック。

    make_gadget 以外は本物の Application のメソッドを使う。
    """

    def __init__(self, gadgets=None, sparql=None):
        self.sparql_client = sparql or DummySPARQL()
        self.gadgets = gadgets or {}
        self.pages = DummyPages()

    @property
    def gadgetset(self):
        return self.gadgets

    def make_gadget(self, gadget_name, uri, params=None, collection=None):
        """テスト用の最小make_gadget。"""
        if params is None:
            params = {}
        gadget = self.gadgets[gadget_name]
        content = gadget.extract(
            uri,
            application=self,
            params=params,
            collection=collection,
        )
        return gadget.show(content)

    get_collection = Application.get_collection
    get_facet_definition = Application.get_facet_definition
    apply_collection_filters = Application.apply_collection_filters
    make_page = Application.make_page
    make_page_tabs = Application.make_page_tabs


@pytest.fixture
def application():
    return DummyApplication(
        {
            "mountain_facet": DummyGadget(
                {
                    "type": "facet",
                    "name": "country",
                    "predicate": "http://example.org/country",
                }
            ),
            "continent_facet": DummyGadget(
                {
                    "type": "facet",
                    "name": "continent",
                    "predicate": "http://example.org/continent",
                }
            ),
        }
    )


@pytest.fixture
def collection():
    return Collection.from_uris(
        None,
        [
            "http://example.org/A",
            "http://example.org/B",
            "http://example.org/C",
        ],
    )


def test_get_facet_definition(application):
    """Facet名からFacet定義を取得できる。"""

    facet = application.get_facet_definition("country")

    assert facet == {
        "type": "facet",
        "name": "country",
        "predicate": "http://example.org/country",
    }


def test_get_facet_definition_returns_none_for_unknown(application):
    """存在しないFacet名はNoneを返す。"""

    assert application.get_facet_definition("unknown") is None


def test_apply_collection_filters(application, collection):
    """URLパラメータからFacet条件をCollectionに適用できる。"""

    filtered = application.apply_collection_filters(
        collection,
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
        },
    )

    assert filtered is not collection

    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
    ]


def test_apply_collection_filters_multiple_facets(
    application,
    collection,
):
    """複数のFacet条件をAND条件として適用できる。"""

    filtered = application.apply_collection_filters(
        collection,
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
            "continent": "http://example.org/Asia",
        },
    )

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


def test_apply_collection_filters_exclude_current_facet(
    application,
    collection,
):
    """現在表示中のFacet自身は絞り込み条件から除外できる。"""

    filtered = application.apply_collection_filters(
        collection,
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
            "continent": "http://example.org/Asia",
        },
        exclude={"country"},
    )

    assert filtered.filters == [
        (
            "http://example.org/continent",
            "http://example.org/Asia",
        ),
    ]


def test_apply_collection_filters_ignores_unknown_parameter(
    application,
    collection,
):
    """Facetとして定義されていないURLパラメータは無視する。"""

    filtered = application.apply_collection_filters(
        collection,
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
            "unknown": "something",
        },
    )

    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
    ]


def test_apply_collection_filters_ignores_empty_value(
    application,
    collection,
):
    """空のURLパラメータはFacet条件にしない。"""

    filtered = application.apply_collection_filters(
        collection,
        params={
            "country": "",
            "continent": None,
        },
    )

    assert filtered is collection
    assert filtered.filters == []


def test_apply_collection_filters_requires_predicate(
    collection,
):
    """Facet定義にpredicateがなければエラーにする。"""

    application = DummyApplication(
        {
            "bad_facet": DummyGadget(
                {
                    "type": "facet",
                    "name": "country",
                }
            )
        }
    )

    with pytest.raises(
        GadgetError,
        match=r"facet\(country\)にpredicateがありません",
    ):
        application.apply_collection_filters(
            collection,
            params={
                "country": "http://example.org/Japan",
            },
        )

def test_get_collection_from_class(application):
    """class指定ではクラスのインスタンスを表すCollectionが作られる。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    assert collection.uris is None
    assert "?uri a <http://example.org/Mountain> ." in collection.get_query()
    # URLの値はSPARQLのパラメータとしては渡さない（検証済みの項として埋め込む）
    assert collection.all_params() == {}
    assert application.sparql_client.calls == []

def test_get_collection_from_uri(application):
    """uri指定では、そのURIだけを要素とするCollectionが作られる。"""

    collection = application.get_collection(
        "http://example.org/Mountain/A"
    )

    assert collection.uris == [
        "http://example.org/Mountain/A",
    ]
    assert collection.query is None

def test_get_collection_then_filter(application):
    """get_collection()で作ったCollectionをfilter()できる。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert filtered is not collection
    assert filtered.base is collection
    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        )
    ]

    # 母集合は変更されない
    assert collection.filters == []

def test_get_collection_then_filter_multiple(application):
    """get_collection()後に複数のFacet条件を追加できる。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    filtered = filtered.filter(
        "http://example.org/continent",
        "http://example.org/Asia",
    )

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

    # 元のCollectionには条件が入らない
    assert collection.filters == []

def test_get_collection_then_filter_is_lazy(application):
    """get_collection()とfilter()ではSPARQLを実行しない。"""

    application.sparql_client.calls.clear()

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    assert application.sparql_client.calls == []
    assert filtered.base is collection
    assert filtered.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        )
    ]

def test_get_collection_filter_get_uris():
    """Collection取得→Facet絞り込み→get_uris()まで一連で動作する。"""

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

    application = DummyApplication(gadgets=[], sparql=sparql)
    application.sparql_client = sparql

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    )

    uris = filtered.get_uris()

    assert uris == [
        "http://example.org/A",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert (
        "?uri <http://example.org/country> "
        "<http://example.org/Japan> ."
    ) in query
    
def test_get_collection_multiple_filters_get_uris():
    """複数Facetを付けたCollectionからget_uris()するとAND条件になる。"""

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

    application = DummyApplication(
        gadgets=[],
        sparql=sparql,
    )

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    filtered = collection.filter(
        "http://example.org/country",
        "http://example.org/Japan",
    ).filter(
        "http://example.org/continent",
        "http://example.org/Asia",
    )

    uris = filtered.get_uris()

    assert uris == [
        "http://example.org/A",
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert (
        "?uri <http://example.org/country> "
        "<http://example.org/Japan> ."
    ) in query

    assert (
        "?uri <http://example.org/continent> "
        "<http://example.org/Asia> ."
    ) in query

def test_facet_gadget_definition_keeps_predicate():
    """extract_facet()がCollectionからFacet候補を取得する。"""

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
                    "value": "3",
                },
            },
        ]
    )

    application = DummyApplication(
        gadgets=[],
        sparql=sparql,
    )

    gadget = DummyGadget(
        {
            "type": "facet",
            "predicate": "http://example.org/country",
        }
    )

    result = gadget.extract_method

    assert result["type"] == "facet"
    assert result["predicate"] == "http://example.org/country"


def test_extract_facet_gets_facets_from_collection():
    """extract_facet()がCollectionからFacet候補を取得する。"""

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
                    "value": "3",
                },
            },
        ]
    )

    application = DummyApplication(
        gadgets=[],
        sparql=sparql,
    )

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    result = gadget.extract(
        None,
        application=application,
        params={},
        collection=collection,
    )

    assert result == [
        {
            "value": "http://example.org/Japan",
            "label": "Japan",
            "count": 3,
            "type": "uri",
        }
    ]

def test_extract_facet_excludes_current_facet():
    """Facet自身の条件は除外し、他のFacet条件だけをCollectionに適用する。"""

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
                    "value": "3",
                },
            },
        ]
    )

    application = DummyApplication(
        gadgets={
            "country": DummyGadget({
                "type": "facet",
                "name": "country",
                "predicate": "http://example.org/country",
            }),
            "continent": DummyGadget({
                "type": "facet",
                "name": "continent",
                "predicate": "http://example.org/continent",
            }),
        },
        sparql=sparql,
    )

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    gadget.extract(
        None,
        application=application,
        params={
            "country": "http://example.org/Japan",
            "continent": "http://example.org/Asia",
        },
        collection=collection,
    )

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    # country自身は除外される
    assert (
        "?uri <http://example.org/country> "
        "<http://example.org/Japan> ."
    ) not in query

    # continentは適用される
    assert (
        "?uri <http://example.org/continent> "
        "<http://example.org/Asia> ."
    ) in query

def test_extract_facet_requires_collection():
    """facet extractにはCollectionが必要。"""

    sparql = DummySPARQL()

    application = DummyApplication(
        gadgets={
            "country": DummyGadget({
                "type": "facet",
                "name": "country",
                "predicate": "http://example.org/country",
            }),
        },
        sparql=sparql,
    )

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    with pytest.raises(GadgetError, match="Collectionが必要"):
        gadget.extract(
            None,
            application=application,
            params={
                "country": "http://example.org/Japan",
            },
        )

def test_make_gadget_passes_collection_to_extract(application):
    """make_gadget()はCollectionをGadget.extract()へ渡す。"""

    class RecordingGadget:
        def __init__(self):
            self.collection = None
            self.extract_method = {"type": "test"}
            self.show_method = {"type": "vtable"}

        def extract(self, uri, application=None, params=None, collection=None):
            self.collection = collection
            return []

        def show(self, content):
            return ""

    gadget = RecordingGadget()

    application.gadgets = {
        "test": gadget,
    }

    collection = Collection.from_uris(
        application.sparql_client,
        ["http://example.org/A"],
    )

    application.make_gadget(
        "test",
        "http://example.org/A",
        params={},
        collection=collection,
    )

    assert gadget.collection is collection

def test_make_page_shares_collection_with_gadgets(application):
    """make_page()は同じCollectionを各Gadgetに渡す。"""

    class RecordingGadget:
        def __init__(self):
            self.collections = []

        def extract(
            self,
            uri,
            application=None,
            params=None,
            collection=None,
        ):
            self.collections.append(collection)
            return []

        def show(self, content):
            return ""

    gadget1 = RecordingGadget()
    gadget2 = RecordingGadget()

    application.gadgets = {
        "gadget1": gadget1,
        "gadget2": gadget2,
    }

    application.pages.pagedict = {
        "test": {
            "type": "collection",
            "gadget": [
                "gadget1",
                "gadget2",
            ],
        },
    }

    application.make_page(
        "test",
        "http://example.org/Mountain",
    )

    assert len(gadget1.collections) == 1
    assert len(gadget2.collections) == 1

    assert gadget1.collections[0] is not None
    assert gadget1.collections[0] is gadget2.collections[0]

def test_make_page_tabs_passes_collection_to_gadgets(application):
    """タブページでも同じCollectionを各Gadgetへ渡す。"""

    class RecordingGadget:
        def __init__(self):
            self.collection = None

        def extract(
            self,
            uri,
            application=None,
            params=None,
            collection=None,
        ):
            self.collection = collection
            return []

        def show(self, content):
            return ""

    gadget1 = RecordingGadget()
    gadget2 = RecordingGadget()

    application.gadgets = {
        "gadget1": gadget1,
        "gadget2": gadget2,
    }

    application.pages.pagedict = {
        "test": {
            "type": "collection",
            "tabs": [
                {
                    "label": "Tab 1",
                    "gadget": ["gadget1"],
                },
                {
                    "label": "Tab 2",
                    "gadget": ["gadget2"],
                },
            ],
        },
    }

    application.make_page(
        "test",
        "http://example.org/Mountain",
    )

    assert gadget1.collection is not None
    assert gadget2.collection is not None
    assert gadget1.collection is gadget2.collection


def test_make_page_creates_collection_only_once(application):
    """make_page()ではページ内でCollectionを1回だけ作成する。"""

    class RecordingGadget:
        def __init__(self):
            self.collections = []

        def extract(
            self,
            uri,
            application=None,
            params=None,
            collection=None,
        ):
            self.collections.append(collection)
            return []

        def show(self, content):
            return ""

    gadget1 = RecordingGadget()
    gadget2 = RecordingGadget()

    application.gadgets = {
        "gadget1": gadget1,
        "gadget2": gadget2,
    }

    application.pages.pagedict = {
        "test": {
            "type": "collection",
            "gadget": [
                "gadget1",
                "gadget2",
            ],
        },
    }

    original_get_collection = application.get_collection
    calls = []

    def recording_get_collection(uri=None, params=None, query=None):
        calls.append((uri, params))
        return original_get_collection(uri, params=params, query=query)

    application.get_collection = recording_get_collection

    application.make_page(
        "test",
        "http://example.org/Mountain",
    )

    assert len(calls) == 1
    assert len(gadget1.collections) == 1
    assert len(gadget2.collections) == 1
    assert gadget1.collections[0] is gadget2.collections[0]

def test_facet_gadget_end_to_end(application):
    """Facet GadgetがCollectionから候補を取得して表示まで行える。"""

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
                    "value": "3",
                },
            },
        ]
    )

    application.sparql_client = sparql

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    content = gadget.extract(
        None,
        application=application,
        params={},
        collection=collection,
    )

    assert content == [
        {
            "value": "http://example.org/Japan",
            "label": "Japan",
            "count": 3,
            "type": "uri",
        }
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "COUNT(DISTINCT ?uri)" in query
    assert "http://example.org/country" in query

def test_facet_gadget_applies_other_facet_filters(application):
    """Facet候補取得時、自身の条件を除外し、他のFacet条件を適用する。"""

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
                    "value": "3",
                },
            },
        ]
    )

    application.sparql_client = sparql

    application.gadgets = {
        "country": DummyGadget({
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        }),
        "continent": DummyGadget({
            "type": "facet",
            "name": "continent",
            "predicate": "http://example.org/continent",
        }),
    }

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    collection = Collection.from_uris(
        sparql,
        [
            "http://example.org/A",
            "http://example.org/B",
        ],
    )

    content = gadget.extract(
        None,
        application=application,
        params={
            "country": "http://example.org/Japan",
            "continent": "http://example.org/Asia",
        },
        collection=collection,
    )

    assert content == [
        {
            "value": "http://example.org/Japan",
            "label": "Japan",
            "count": 3,
            "type": "uri",
        }
    ]

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    # 現在のFacet自身は条件に入らない
    assert (
        "?uri <http://example.org/country> "
        "<http://example.org/Japan> ."
    ) not in query

    # 他のFacet条件は入る
    assert (
        "?uri <http://example.org/continent> "
        "<http://example.org/Asia> ."
    ) in query


def test_facet_gadget_show_returns_facet_html():
    """Facet Gadgetは取得したFacet候補をHTMLとして表示する。"""

    gadget = Gadget(
        {
            "type": "facet",
            "name": "country",
            "predicate": "http://example.org/country",
        },
        {
            "type": "facet",
        },
        None,
    )

    content = [
        {
            "value": "http://example.org/Japan",
            "label": "Japan",
            "count": 3,
        },
        {
            "value": "http://example.org/France",
            "label": "France",
            "count": 2,
        },
    ]

    html = gadget.show(content)

    assert html
    assert "Japan" in html
    assert "France" in html

def test_get_collection_from_query(application):
    """pageのqueryからCollectionを作成できる。"""

    query = """
    SELECT DISTINCT ?uri
    WHERE {
        ?uri rdf:type dbo:Mountain .
        ?uri dct:subject dbc:Mountains_of_the_Alps .
    }
    """

    collection = application.get_collection(
        query=query,
        params={},
    )

    assert collection.query == query
    assert collection.params == {}
    assert collection.uris is None
    assert collection.filters == []

def test_collection_get_query():
    """Collection.get_query()が取得条件のqueryを返す。"""
    sparql = DummySPARQL([])

    collection = Collection.from_query(
        sparql,
        """
        SELECT DISTINCT ?uri
        WHERE {
            ?uri rdf:type dbo:Mountain .
        }
        """,
    )

    query = collection.get_query()

    assert "?uri rdf:type dbo:Mountain ." in query

def test_extract_sparql_connects_collection():
    """extract_sparql()がCollectionを対象Resourceとして接続する。"""
    sparql = DummySPARQL([])

    application = DummyApplication(
        gadgets=[],
        sparql=sparql,
    )

    gadget = Gadget(
        {
            "type": "sparql",
            "src": """
            SELECT DISTINCT ?entity ?label
            WHERE {
                ?entity rdfs:label ?label .
            }
            """,
        },
        {
            "type": "htable",
        },
        None,
    )
    gadget.sparql_client = sparql

    collection = Collection.from_query(
        sparql,
        """
        SELECT DISTINCT ?uri
        WHERE {
            ?uri rdf:type dbo:Mountain .
            ?uri dct:subject dbc:Mountains_of_the_Alps .
        }
        """,
    )

    gadget.extract(
        None,
        application=application,
        params={},
        collection=collection,
    )

    assert len(sparql.calls) == 1

    query, params = sparql.calls[0]

    assert "dbo:Mountain" in query
    assert "dbc:Mountains_of_the_Alps" in query
    assert "?entity rdfs:label ?label ." in query
    # Collectionは ?entity だけを外に出す副問い合わせとして接続される
    assert "SELECT DISTINCT (?uri AS ?entity)" in query
    assert "?uri rdf:type dbo:Mountain ." in query



# --------------------------------------------------
# ガジェットへのCollectionの接続（$collection）
# --------------------------------------------------

def _sparql_gadget(src, sparql):
    gadget = Gadget({"type": "sparql", "src": src}, {"type": "htable"}, None)
    gadget.sparql_client = sparql
    return gadget


def test_collection_placeholder_is_replaced():
    """$collection は ?entity を束縛する副問い合わせに置き換えられる。"""
    sparql = DummySPARQL([])
    gadget = _sparql_gadget(
        """
        SELECT ?npages (COUNT(?npages) AS ?count)
        WHERE {
            ?entity dcterms:extent ?npages .
            $collection
        }
        GROUP BY ?npages
        """,
        sparql,
    )
    collection = Collection.from_class(sparql, "http://example.org/Document")
    gadget.extract(None, application=DummyApplication(sparql=sparql), collection=collection)
    query, _ = sparql.calls[0]
    assert "$collection" not in query
    assert "SELECT DISTINCT (?uri AS ?entity)" in query
    assert "?uri a <http://example.org/Document> ." in query
    # 副問い合わせはプレースホルダの位置に入る（WHERE直後への自動挿入はしない）
    assert query.index("?entity dcterms:extent") < query.index("SELECT DISTINCT (?uri AS ?entity)")


def test_collection_is_inserted_after_lowercase_where():
    sparql = DummySPARQL([])
    gadget = _sparql_gadget("select ?entity where{ ?entity rdfs:label ?l }", sparql)
    collection = Collection.from_class(sparql, "http://example.org/Document")
    gadget.extract(None, application=DummyApplication(sparql=sparql), collection=collection)
    query, _ = sparql.calls[0]
    assert query.startswith("select ?entity where{\n{ SELECT DISTINCT (?uri AS ?entity)")


def test_collection_placeholder_without_collection_is_error():
    sparql = DummySPARQL([])
    gadget = _sparql_gadget("SELECT ?entity WHERE { $collection }", sparql)
    with pytest.raises(GadgetError):
        gadget.extract(None, application=DummyApplication(sparql=sparql), collection=None)


def test_make_page_applies_facet_params_to_shared_collection(application):
    """make_page() はURLのFacet条件で絞り込んだCollectionをGadgetに渡す。"""

    class RecordingGadget:
        extract_method = {"type": "sparql"}

        def __init__(self):
            self.collection = None

        def extract(self, uri, application=None, params=None, collection=None):
            self.collection = collection
            return []

        def show(self, content):
            return ""

    gadget = RecordingGadget()
    application.gadgets["list"] = gadget
    application.pages.pagedict = {"test": {"type": "collection", "gadget": ["list"]}}

    application.make_page(
        "test",
        None,
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
            "unknown": "ignored",
        },
    )

    assert gadget.collection.filters == [
        ("http://example.org/country", "http://example.org/Japan"),
    ]
    assert [c.name for c in gadget.collection.conditions] == ["country"]


def test_extract_facet_on_filtered_page_collection(application):
    """ページで絞り込み済みのCollectionでも、自分自身の条件は外して候補を数える。"""
    sparql = DummySPARQL([])
    application.sparql_client = sparql
    facet = Gadget(
        {"type": "facet", "name": "country", "predicate": "http://example.org/country"},
        {"type": "facet"},
        None,
    )
    facet.sparql_client = sparql
    params = {
        "class": "http://example.org/Mountain",
        "country": "http://example.org/Japan",
        "continent": "http://example.org/Asia",
    }
    collection = application.apply_collection_filters(
        application.get_collection(params=params), params
    )
    facet.extract(None, application=application, params=params, collection=collection)
    query, _ = sparql.calls[0]
    assert "<http://example.org/Japan>" not in query
    assert query.count("<http://example.org/Asia>") == 1


def test_move_focus_validates_path():
    from kgraphnavi.app import move_focus
    from kgraphnavi.terms import ValueTermError

    class Client:
        def __init__(self):
            self.calls = []

        def query(self, query, params=None):
            self.calls.append((query, params))
            return [{"new": {"type": "uri", "value": "http://example.org/B"}}]

    client = Client()
    assert move_focus("http://example.org/A", "dbo:country", client) == "http://example.org/B"
    assert client.calls[0] == (
        "select ?new where { $uri dbo:country ?new }",
        {"uri": "http://example.org/A"},
    )
    with pytest.raises(ValueTermError):
        move_focus("http://example.org/A", "dbo:x } ?s ?p ?o {", client)


# --------------------------------------------------
# 画面（テンプレート）
# --------------------------------------------------

def test_templates_have_no_fixed_host():
    """テンプレートのリンクは相対パスで、特定のホスト・ポートを含まない。"""
    from pathlib import Path
    import kgraphnavi

    templates = Path(kgraphnavi.__file__).parent / "templates"
    for path in templates.glob("*.html"):
        assert "localhost" not in path.read_text(encoding="utf-8"), path.name


def test_top_page_links_are_relative(tmp_path):
    from kgraphnavi.app import build_application, create_app

    config = tmp_path / "test.yaml"
    config.write_text(
        """
- title: TestKG
- sample:
    resource:
      - http://example.org/A,Aの例
    collection:
      - http://example.org/Mountain,山
    search:
      - 富士山
- def: page
  name: Resource
  type: '*'
  gadget: [Out]
- def: gadget
  name: Out
  get:
    type: sparql
    src: "select ?p ?o where { $uri ?p ?o }"
  show:
    type: htable
""",
        encoding="utf-8",
    )
    app = create_app(build_application(str(config), endpoint="http://example.org/sparql"))
    html = app.test_client().get("/").get_data(as_text=True)
    assert "TestKG" in html
    assert 'href="/resource?uri=http%3A%2F%2Fexample.org%2FA"' in html
    assert 'href="/collection?class=http%3A%2F%2Fexample.org%2FMountain"' in html
    assert 'href="/search?q=%E5%AF%8C%E5%A3%AB%E5%B1%B1"' in html
    assert ">富士山<" in html
