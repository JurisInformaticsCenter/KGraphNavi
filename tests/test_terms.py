#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
値の検証（terms.py）と、SPARQLへのパラメータ埋め込み（sparql.substitute_params）のテスト
"""

import pytest

from kgraphnavi.terms import (
    ValueTermError,
    iri_term,
    is_iri,
    literal_term,
    language_tag,
    typed_term,
    number_term,
    predicate_term,
    normalize_typed_value,
)
from kgraphnavi.sparql import substitute_params

XSD = "http://www.w3.org/2001/XMLSchema#"


@pytest.mark.parametrize("value,expected", [
    ("http://example.org/A", "<http://example.org/A>"),
    ("<http://example.org/A>", "<http://example.org/A>"),
    ("https://dbpedia.org/resource/Mount_Fuji", "<https://dbpedia.org/resource/Mount_Fuji>"),
    ("urn:isbn:0451450523", "<urn:isbn:0451450523>"),
    ("dbo:Mountain", "dbo:Mountain"),
    ("caselawp:訴訟類型", "caselawp:訴訟類型"),
    (
        "http://ds.rois.ac.jp/caselaw/resource/C昭和62あ1351",
        "<http://ds.rois.ac.jp/caselaw/resource/C昭和62あ1351>",
    ),
    ("  http://example.org/A  ", "<http://example.org/A>"),
])
def test_iri_term_accepts(value, expected):
    assert iri_term(value) == expected


@pytest.mark.parametrize("value", [
    None,
    "",
    "Japan",
    "http://example.org/a b",
    "http://example.org/A> . ?s ?p ?o <x",
    'http://example.org/"x',
    "<http://example.org/A> } DELETE {",
    "http://example.org/{x}",
])
def test_iri_term_rejects(value):
    with pytest.raises(ValueTermError):
        iri_term(value)


def test_is_iri():
    assert is_iri("dbo:Mountain")
    assert not is_iri("Mount Fuji")


@pytest.mark.parametrize("value,expected", [
    ("行政訴訟", '"行政訴訟"'),
    ('a"b', '"a\\"b"'),
    ("a\\b", '"a\\\\b"'),
    ("line1\nline2", '"line1\\nline2"'),
    (123, '"123"'),
])
def test_literal_term(value, expected):
    assert literal_term(value) == expected


def test_literal_term_with_lang():
    assert literal_term("Mount Fuji", "en") == '"Mount Fuji"@en'
    with pytest.raises(ValueTermError):
        literal_term("x", 'en" . }')


@pytest.mark.parametrize("lang", ["en", "ja", "en-US", "*"])
def test_language_tag_accepts(lang):
    assert language_tag(lang) == lang


@pytest.mark.parametrize("datatype,value,expected", [
    ("integer", "42", "42"),
    ("integer", "+7", "7"),
    ("decimal", "3.50", "3.50"),
    ("decimal", "1e3", "1000"),
    ("date", "2000-01-02", "2000-01-02"),
    ("dateTime", "2000-01-02T03:04:05", "2000-01-02T03:04:05"),
    ("gYear", "1999", "1999"),
    ("boolean", "True", "true"),
])
def test_normalize_typed_value(datatype, value, expected):
    assert normalize_typed_value(value, datatype) == expected


@pytest.mark.parametrize("datatype,value", [
    ("integer", "4.2"),
    ("integer", "1 OR 1=1"),
    ("decimal", "NaN"),
    ("date", "2000/01/02"),
    ("gYear", "99"),
    ("boolean", "yes"),
    ("string", "x"),
])
def test_normalize_typed_value_rejects(datatype, value):
    with pytest.raises(ValueTermError):
        normalize_typed_value(value, datatype)


def test_typed_term():
    assert typed_term("2000-01-02", "date") == f'"2000-01-02"^^<{XSD}date>'


def test_number_term():
    assert number_term("2000") == "2000"
    assert number_term("2.5") == "2.5"
    with pytest.raises(ValueTermError):
        number_term("2000) || true || (1")


@pytest.mark.parametrize("path,expected", [
    ("dbo:country", "dbo:country"),
    ("http://example.org/p", "<http://example.org/p>"),
    ("^dbo:country", "^dbo:country"),
    ("dct:subject/skos:broader*", "dct:subject/skos:broader*"),
    ("(skos:altLabel|skos:prefLabel)", "(skos:altLabel|skos:prefLabel)"),
    ("a", "a"),
    ("<http://example.org/p>/dbo:x", "<http://example.org/p>/dbo:x"),
])
def test_predicate_term_accepts(path, expected):
    assert predicate_term(path) == expected


@pytest.mark.parametrize("path", [
    "",
    "dbo:x } ?s ?p ?o {",
    "dbo:x ?o",
    'dbo:x "y"',
    "dbo:x . ?s",
])
def test_predicate_term_rejects(path):
    with pytest.raises(ValueTermError):
        predicate_term(path)


# --------------------------------------------------
# SPARQLへのパラメータ埋め込み
# --------------------------------------------------

def test_substitute_uri_param():
    query = "SELECT ?p ?o WHERE { $uri ?p ?o }"
    assert substitute_params(query, {"uri": "http://example.org/A"}) == (
        "SELECT ?p ?o WHERE { <http://example.org/A> ?p ?o }"
    )


def test_substitute_rejects_malicious_uri():
    query = "SELECT ?p ?o WHERE { $uri ?p ?o }"
    with pytest.raises(ValueTermError):
        substitute_params(query, {"uri": "http://example.org/A> ?p ?o } ; DROP ALL ; { <x"})


def test_substitute_other_params_as_literals():
    query = 'SELECT ?s WHERE { ?s rdfs:label ?l FILTER(STR(?l) = $name) }'
    assert substitute_params(query, {"name": 'x") } #'}) == (
        'SELECT ?s WHERE { ?s rdfs:label ?l FILTER(STR(?l) = "x\\") } #") }'
    )


def test_substitute_ignores_params_not_in_query():
    query = "SELECT ?p ?o WHERE { $uri ?p ?o }"
    # URLの他のパラメータ（不正な値でも）は、SPARQLに現れなければ無視される
    result = substitute_params(query, {"uri": "http://example.org/A", "country": "} DROP ALL {"})
    assert "DROP" not in result


def test_substitute_does_not_touch_longer_names():
    query = "SELECT * WHERE { $uri ?p $uris }"
    result = substitute_params(query, {"uri": "http://example.org/A"})
    assert result == "SELECT * WHERE { <http://example.org/A> ?p $uris }"


def test_substitute_predicate_param():
    query = "SELECT ?o WHERE { $uri $predicate ?o }"
    result = substitute_params(query, {"uri": "dbr:Mount_Fuji", "predicate": "dbo:elevation"})
    assert result == "SELECT ?o WHERE { dbr:Mount_Fuji dbo:elevation ?o }"


def test_substitute_skips_none():
    query = "SELECT ?o WHERE { $uri ?p ?o }"
    assert substitute_params(query, {"uri": None}) == query
