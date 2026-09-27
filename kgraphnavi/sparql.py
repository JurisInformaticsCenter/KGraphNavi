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
from .terms import iri_term, literal_term, predicate_term, ValueTermError

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
    """（互換用）http://... を <...> で囲む。検証が必要な値には terms.iri_term() を使う。"""
    if value is None:
        return None
    if value.startswith("<") and value.endswith(">"):
        return value
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return f"<{value}>"
    return value

# $変数として埋め込むときに IRI として扱うパラメータ、プロパティ（パス）として扱うパラメータ
IRI_PARAMS = {"uri", "class", "class_uri"}
PATH_PARAMS = {"predicate"}


def param_term(key, value):
    """パラメータの値を検証し、SPARQLに埋め込める項に変換する。

    uri / class / class_uri はIRI、predicate はプロパティ（パス）、それ以外は文字列リテラル。
    """
    if key in IRI_PARAMS:
        return iri_term(value)
    if key in PATH_PARAMS:
        return predicate_term(value)
    return literal_term(value)


def substitute_params(sparql, params):
    """SPARQL中の $key を、検証済みの項に置き換える。

    SPARQLに現れない $key は無視する（URLのパラメータがすべて渡されるため）。
    """
    for key, value in (params or {}).items():
        if value is None:
            continue
        pattern = re.compile(r"\$" + re.escape(str(key)) + r"(?![\w])")
        if not pattern.search(sparql):
            continue
        term = param_term(key, value)
        sparql = pattern.sub(lambda _match: term, sparql)
    return sparql
    
class SPARQL:
    __slots__ = ("sparql", "prefix", "retrieve_template", "retrieve_template_perfect")
    def __init__(self, endpoint, prefixes="", label_predicate="rdfs:label"):
        self.sparql = SPARQLWrapper(endpoint=endpoint, returnFormat='json')
        self.prefix = make_prefix(prefixes)
        # label は無変化なのでここで埋め込む。検索語は毎回変わるので {text} のままにしておく
        # （{text} には literal_term() でエスケープした文字列リテラルが入る）
        label_predicate = predicate_term(label_predicate)
        retrieve_exp = 'FILTER contains(str(?label), {text})' # 部分一致
        retrieve_exp_perfect = 'FILTER (str(?label)={text})' # 完全一致
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
        """paramsに指定された$変数を検証済みの値に置き換えてSPARQLを実行する。"""
        logger.debug("query(template)=%s params=%s", sparql, params)
        sparql = substitute_params(sparql, params)
        logger.debug("query(expanded)=%s", sparql)
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
            uri=uri,
            predicate=predicate,
        )

    def get_target(self, uri, path):
        """uri からpathでたどり着けるリソースのリストを返す。pathは例えば(skos:altLabel|skos:prefLabel)/^(skos:altLabel|skos:prefLabel)のように記述する。
        """
        query = f'select ?target where {{$uri {predicate_term(path)} ?target}}'
        return self.query_values(
            query,
            "target",
            uri=uri,
        )

    def get_subject(self, r_object, predicate):
        """predicate, r_object に対するsubjectのリストを返す。
        """
        query = f'select ?subject where {{?subject {predicate_term(predicate)} $uri }}'
        return self.query_values(
            query,
            "subject",
            uri=r_object,
        )


    def get_priority_class(self, class_uri, priority):
        """class_uri 自身またはその上位クラスのうち、
        priority の先頭から最初に一致するクラスを返す。
        priority は優先順位の高い順。
        """
    
        if not priority:
            return None
        values = " ".join(iri_term(uri) for uri in priority)
        query = f"""
        SELECT DISTINCT ?class WHERE {{
            {iri_term(class_uri)} rdfs:subClassOf* ?class .
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
            uri=uri,
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
        text = literal_term(text)
        if mode == "perfect":
            query = self.retrieve_template_perfect.format(text=text)
        else:
            query = self.retrieve_template.format(text=text)
        if result := self.exsparql(query):
            return [
                (
                    record['uri']['value'],
                    record['label']['value'],
                    record.get('type', {}).get('value', ''),
                )
                for record in result
            ]
        return []

