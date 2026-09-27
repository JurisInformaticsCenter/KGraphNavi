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
from kgraphnavi.app import Gadget
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
    """Collection関連テストに必要な部分だけを持つモック"""

    def __init__(self, gadgets=None, sparql=None):
        self.sparql_client = sparql or DummySPARQL()
        self.gadgets = gadgets or {}
        self.pages = DummyPages()
    
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
    
    def get_collection(self, uri=None, params=None, query=None):
        """現在のページに対応するCollectionを取得する。"""

        if params is None:
            params = {}

        if query:
            collection = Collection.from_query(
                self.sparql_client,
                query,
                params=params,
            )
        else:
            class_uri = params.get("class")
    
            if class_uri:
                query = """
                SELECT DISTINCT ?uri
                WHERE {
                    ?uri a $class .
                }
                """
    
                return Collection.from_query(
                    self.sparql_client,
                    query,
                    params={"class": class_uri},
                )
    
            if uri:
                return Collection.from_uris(
                    self.sparql_client,
                    [uri],
                )

            raise GadgetError(
                "Collectionを作成するためのclassまたはuriがありません"
            )

        return self.apply_collection_filters(
            collection,
            params=params,
        )

    def get_facet_definition(self, name):
        """nameに対応するfacet Gadgetの定義を返す。"""

        for gadget in self.gadgets.values():
            extract_method = gadget.extract_method

            if extract_method.get("type") != "facet":
                continue

            if extract_method.get("name") == name:
                return extract_method

        return None

    def apply_collection_filters(
        self,
        collection,
        params=None,
        *,
        exclude=None,
    ):
        """URLパラメータに指定されたFacet条件をCollectionに適用する。"""

        if params is None:
            params = {}

        if exclude is None:
            exclude = set()
        else:
            exclude = set(exclude)

        result = collection

        for name, value in params.items():

            # Collection自身を定義するパラメータ
            if name in ("class", "uri"):
                continue

            # 値がない場合
            if value is None or value == "":
                continue

            # 現在計算中のFacet自身
            if name in exclude:
                continue

            facet = self.get_facet_definition(name)

            # 登録されていないパラメータはFacet条件にしない
            if facet is None:
                continue

            predicate = facet.get("predicate")

            if not predicate:
                raise GadgetError(
                    f"facet({name})にpredicateがありません"
                )

            result = result.filter(
                predicate,
                value,
            )
        return result

    def make_page(self, page, uri, params=None):
        """テスト用make_page。Collectionをページ内のGadgetで共有する。"""
    
        if params is None:
            params = {}
    
        page_def = self.pages.pagedict[page]
    
        collection = self.get_collection(
            uri,
            params=params,
        )
    
        tabs = page_def.get("tabs")
    
        if not tabs:
            return [
                self.make_gadget(
                    gadget_name,
                    uri,
                    params=params,
                    collection=collection,
                )
                for gadget_name in page_def["gadget"]
            ]
    
        for tab in tabs:
            for gadget_name in tab["gadget"]:
                self.make_gadget(
                    gadget_name,
                    uri,
                    params=params,
                    collection=collection,
                )
    
        return []
    



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
    """class指定ではqueryベースのCollectionが作られる。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
        }
    )

    assert collection.uris is None
    assert collection.query is not None
    assert "SELECT DISTINCT ?uri" in collection.query
    assert collection.params == {
        "class": "http://example.org/Mountain",
    }

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
    assert filtered.query is not None
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
    assert filtered.query is not None
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
            "gadget": [
                "gadget1",
                "gadget2",
            ],
        },
    }

    original_get_collection = application.get_collection
    calls = []

    def recording_get_collection(uri=None, params=None):
        calls.append((uri, params))
        return original_get_collection(uri, params=params)

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
    # Collectionの条件は ?uri を ?entity に置き換えて接続される
    assert "?entity rdf:type dbo:Mountain" in query

'''
def test_get_collection_with_facet_filter(application):
    """classで作ったCollectionにFacet条件が追加される。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
        }
    )

    assert collection.query is not None
    assert collection.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        )
    ]

def test_get_collection_with_multiple_facet_filters(application):
    """複数のFacet条件がCollectionにANDで追加される。"""

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
            "continent": "http://example.org/Asia",
        }
    )

    assert collection.filters == [
        (
            "http://example.org/country",
            "http://example.org/Japan",
        ),
        (
            "http://example.org/continent",
            "http://example.org/Asia",
        ),
    ]

def test_get_collection_does_not_execute_sparql(application):
    """Collection生成時にはSPARQLを実行しない。"""

    application.sparql_client.calls.clear()

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
        }
    )

    assert collection is not None
    assert application.sparql_client.calls == []

def test_get_collection_executes_query_on_get_uris(application):
    """get_collection()では実行せず、get_uris()でSPARQLを実行する。"""

    application.sparql_client.calls.clear()

    collection = application.get_collection(
        params={
            "class": "http://example.org/Mountain",
            "country": "http://example.org/Japan",
        }
    )

    collection.get_uris()

    assert len(application.sparql_client.calls) == 1
'''