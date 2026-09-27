#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      sparql.py
##  Description:
##      SPARQL/RDFへのアクセスだけを担当
## Class SPARQL
##
##    get_target(self, uri, path)
##         uri からpathでたどり着けるリソースのリストを返す。pathは例えば(skos:altLabel|skos:prefLabel)/^(skos:altLabel|skos:prefLabel)のように記述する。
"""

import re
import logging
from SPARQLWrapper import SPARQLWrapper
from .errors import SparqlError      # 作成した例外クラス

logger = logging.getLogger(__name__)

def make_prefix(prefixes):
    """prefix辞書からSPARQL PREFIX文を生成する"""
    if not prefixes:
        return ""
    return "\n".join(
        f"PREFIX {name}: <{uri}>"
        for name, uri in prefixes.items()
    ) + "\n\n"

def expand_iri(value):
    if value is None:
        return None
    if value.startswith("<") and value.endswith(">"):
        return value
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return f"<{value}>"
    return value
    
class SPARQL:
    __slots__ = ("sparql", "prefix", "retrieve_template", "retrieve_template_perfect")
    def __init__(self, endpoint, prefixes="", label_predicate="rdfs:label"):
        self.sparql = SPARQLWrapper(endpoint=endpoint, returnFormat='json')
        self.prefix = make_prefix(prefixes)
        # label は無変化なのでここで埋め込む。textはクエリーなので毎回変化するので、変数のままにしておく
        retrieve_exp = 'FILTER contains(?label, "{text}")' # 部分一致
        retrieve_exp_perfect = 'FILTER (str(?label)="{text}")' # 完全一致
        self.retrieve_template = 'select ?uri ?label ?type where {{?uri ' + label_predicate + ' ?label. ' + retrieve_exp + '. OPTIONAL{{?uri a ?type}} }}'
        self.retrieve_template_perfect = 'select ?uri ?label ?type where {{?uri ' + label_predicate + ' ?label. ' + retrieve_exp_perfect + '. OPTIONAL{{?uri a ?type}} }}'

    def exsparql(self, query):
        full_query = self.prefix + query

        logger.debug("SPARQL prefix=%r", self.prefix)
        logger.debug("SPARQL query=%r", query)
        logger.debug("SPARQL full_query=%r", full_query)
    
        self.sparql.setQuery(full_query)
    
        try:
            response = self.sparql.query()
            logger.debug("SPARQL response=%s", type(response))
            results = response.convert()
        except Exception as e:
            logger.exception("SPARQL execution failed")
            raise SparqlError(str(e)) from e
    
        logger.debug("*****SPARQL results=%r", results)
    
        bindings = results["results"]["bindings"]
        logger.debug("SPARQL returned %d rows", len(bindings))
    
        return bindings
    
    def query(self, sparql, params=None):
        """paramsに指定された$変数を展開してSPARQLを実行する。"""
        if params is None:
            params = {}
        logger.debug("*****query(template)=%s params=%s", sparql, params)
        for key, value in params.items():
            if value is None:
                continue
            if key in ("uri", "class", "class_uri", "predicate"):
                value = expand_iri(value)
            sparql = sparql.replace(f"${key}", value)
        logger.debug("*****query(expanded)=%s", sparql)
        return self.exsparql(sparql)

    def query_values(self, query, variable, **params):
        results = self.query(query, params)
        return [
            r[variable]["value"]
            for r in results
            if variable in r
        ]

    def query_value(self, query, variable, **params):
        values = self.query_values(query, variable, **params)
        return values[0] if values else None

    def rdfobject(self, uri, predicate):
        """uriのpredicateの先を取得する"""

        query = "select ?o where {$uri $predicate ?o}"
        return self.query_value(
            query,
            "o",
            uri=expand_iri(uri),
            predicate=expand_iri(predicate),
        )

    def get_target(self, uri, path):
        """uri からpathでたどり着けるリソースのリストを返す。pathは例えば(skos:altLabel|skos:prefLabel)/^(skos:altLabel|skos:prefLabel)のように記述する。
        """
        query = f'select ?target where {{$uri {path} ?target}}'
        return self.query_values(
            query,
            "target",
            uri=expand_iri(uri),
        )

    def get_subject(self, r_object, predicate):
        """predicate, r_object に対するsubjectのリストを返す。
        """
        query = f'select ?subject where {{?subject {predicate} {r_object} }}'
        return self.query_values(
            query,
            "subject",
        )


    def get_priority_class(self, class_uri, priority):
        """class_uri 自身またはその上位クラスのうち、
        priority の先頭から最初に一致するクラスを返す。
        priority は優先順位の高い順。
        """
    
        if not priority:
            return None
        values = " ".join(f"<{uri}>" for uri in priority)
        query = f"""
        SELECT DISTINCT ?class WHERE {{
            <{class_uri}> rdfs:subClassOf* ?class .
            VALUES ?class {{ {values} }}
        }}
        """
        # priority の順序をSPARQLに任せず、Python側で決める
        classes = set(self.query_values(query, "class"))
        for priority_class in priority:
            if priority_class in classes:
                return priority_class
        return None
    
    def get_count(self, uri, predicate):
        """uriからpredicateがいくつあるかを返す"""
        query = (
            "select (count(?target) as ?count) "
            "where {$uri $predicate ?target}"
        )
        return self.query_value(
            query,
            "count",
            uri=uri,
            predicate=predicate,
        )

    def get_list(self, uri, predicate):
        """uriからpredicateの先のリストを返す"""
        query = "select ?target where {$uri $predicate ?target}"
        return self.query_values(
            query,
            "target",
            uri=expand_iri(uri),
            predicate=predicate,
)
        
    def make_collection(self, uri, path):
        """uri からpathで再帰的にたどり着けるリソースのリストを返す"""
        processed = []
        queue = [uri, ]
        while queue:
            focus = queue.pop()
            logger.debug("focus=%s processed=%d queue=%d", focus, len(processed), len(queue))
            new_nodes = self.get_target(focus, path)
            logger.debug("new nodes=%s", new_nodes)
            processed.append(focus)
            for node_uri in new_nodes:
                if node_uri in processed:
                    pass
                else:
                    queue.append(node_uri)
        return processed

    def retrieve(self, text, mode):
        """textをラベルに含むURIを返す"""
        if mode == "perfect":
            query = self.retrieve_template_perfect.format(text=text)
        else:
            query = self.retrieve_template.format(text=text)
        if result := self.exsparql(query):
            return [(record['uri']['value'], record['label']['value'], record['type']['value']) for record in result]
        return []

