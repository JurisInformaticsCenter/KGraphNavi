#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      collection.py
##  Description:
##      Resource集合を表す・操作する
"""

import re
import logging
from .sparql import expand_iri
from .errors import CollectionError

logger = logging.getLogger(__name__)

class Collection:
    """リソースの集合を表す。

    Collectionは遅延評価される。
    生成時にはSPARQLを実行せず、get_uris()やget_facets()
    が呼ばれた時点で必要なクエリを実行する。
    """

    def __init__(
        self,
        sparql,
        *,
        uris=None,
        query=None,
        params=None,
        filters=None,
    ):
        if uris is None and query is None:
            raise ValueError("urisまたはqueryが必要です")

        if uris is not None and query is not None:
            raise ValueError("urisとqueryは同時に指定できません")

        self.sparql = sparql
        self.uris = list(uris) if uris is not None else None
        self.query = query
        self.params = dict(params or {})
        self.filters = list(filters or [])
        logger.debug(
            "Collection.__init__: query repr=%r",
            query,
        )

    @classmethod
    def from_uris(cls, sparql, uris):
        """URI一覧からCollectionを作成する。"""
        return cls(
            sparql,
            uris=uris,
        )

    @classmethod
    def from_query(cls, sparql, query, params=None):
        """SPARQL queryからCollectionを作成する。"""
        return cls(
            sparql,
            query=query,
            params=params,
        )

    '''
    def get_uris(self, variable="uri"):
        """Collectionに含まれるResourceのURIを返す。"""
        if self.uris is not None and not self.filters:
            return list(self.uris)
    
        query = self._make_uri_query(variable)
    
        results = self.sparql.query(
            query,
            self.params,
        )
    
        return [
            row[variable]["value"]
            for row in results
            if variable in row
        ]
    '''

    def get_uris(self, variable="uri"):
        """Collectionに含まれるResourceのURIを返す。

        URI列挙で作られ、絞り込み条件のないCollectionはSPARQLを実行しない。
        """
        if self.uris is not None and not self.filters:
            return list(self.uris)
        query = self._make_query()
    
        logger.debug("***Collection get_uris query=%s", query)
    
        results = self.sparql.query(
            query,
            self.params,
        )
    
        logger.debug("***Collection get_uris results=%s", results)
    
        return [
            row[variable]["value"]
            for row in results
            if variable in row
        ]
    
    def get_query(self):
        """Collectionの取得条件からSPARQL queryを生成する。"""
        query = self._make_query()
        logger.debug("Collection.get_query: repr=%r", query)
        return query
    
    
    def filter(self, predicate, value):
        """predicate/valueの条件を追加した新しいCollectionを返す。"""
        return Collection(
            self.sparql,
            uris=self.uris,
            query=self.query,
            params=self.params,
            filters=self.filters + [(predicate, value)],
        )
    


    def _make_base_query(self):
        """Collection自身の取得条件からSPARQLを生成する。"""
        if self.uris is not None:
            values = " ".join(
                expand_iri(uri)
                for uri in self.uris
            )
            return f"""
            SELECT DISTINCT ?uri
            WHERE {{
                VALUES ?uri {{ {values} }}
            }}
            """
        return self.query

    def _make_filter_conditions(self):
        """filter条件をSPARQLのWHERE条件に変換する。"""
        return "\n".join(
            f"?uri {expand_iri(predicate)} {expand_iri(value)} ."
            for predicate, value in self.filters
        )

    def _make_query(self):
        """Collectionの取得条件とfilter条件からSPARQLを生成する。"""
        base_query = self._make_base_query()
        if not self.filters:
            return base_query
        conditions = self._make_filter_conditions()
        return f"""
        SELECT DISTINCT ?uri
        WHERE {{
            {{
                {base_query}
            }}
    
            {conditions}
        }}
        """

    def _make_uri_query(self, variable="uri"):
        """Collectionの条件からURI取得用SPARQLを生成する。"""
        base_query = self._make_base_query()
    
        if not self.filters:
            return base_query
    
        conditions = self._make_filter_conditions()
    
        return f"""
        SELECT DISTINCT ?{variable}
        WHERE {{
            {{
                {base_query}
            }}
            {conditions}
        }}
        """

    def get_condition(self, variable="?uri"):
        """Collectionの取得条件を指定した変数に置き換えて返す。"""
        if self.uris is not None:
            values = " ".join(
                expand_iri(uri)
                for uri in self.uris
            )
            return f"VALUES {variable} {{ {values} }}"
        query = self._make_query()
        match = re.search(
            r"\bWHERE\s*\{(.*)\}\s*$",
            query,
            re.DOTALL,
        )
        if match is None:
            raise CollectionError("Collection queryにWHERE句がありません")
        condition = match.group(1)
        return re.sub(r"\?uri\b", variable, condition).strip()

    def _make_facet_query(self, predicate):
        """Collectionの条件からFacet取得用SPARQLを生成する。"""
        predicate = expand_iri(predicate)
        base_query = self._make_query()
    
        return f"""
        SELECT ?value ?label (COUNT(DISTINCT ?uri) AS ?count)
        WHERE {{
            {{
                {base_query}
            }}
            ?uri {predicate} ?value .
            OPTIONAL {{
                ?value rdfs:label ?label .
                FILTER(LANG(?label) = "en")
            }}
        }}
        GROUP BY ?value ?label
        ORDER BY DESC(?count)
        """

    def get_facets(self, predicate):
        """現在のCollectionに含まれるResourceのFacet候補を取得する。"""
        query = self._make_facet_query(predicate)
    
        results = self.sparql.query(
            query,
            self.params,
        )
    
        facets = []
        for row in results:
            value = row["value"]["value"]
            label = row.get("label", {}).get("value") or value
            count = int(row["count"]["value"])
    
            facets.append({
                "value": value,
                "label": label,
                "count": count,
            })
    
        return facets