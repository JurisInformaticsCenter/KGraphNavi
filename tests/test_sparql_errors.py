#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SPARQL のエラーの扱い（一時的なエラーのやり直し・利用者向けの説明・ガジェット単位の表示。2026.10.27）"""

import urllib.error

import pytest

from kgraphnavi import sparql as sparql_module
from kgraphnavi.sparql import SPARQL, describe_error, user_message, is_transient
from kgraphnavi.errors import SparqlError

VIRTUOSO_500 = ("EndPointInternalError: The endpoint returned the HTTP status code 500. \n\nResponse:\n"
                "b'Virtuoso 22023 Error SR549: Both datatype id 310 and language id 332 are not default\\n\\nSPARQL query:\\n...'")


class EndPointInternalError(Exception):
    pass


def test_describe_error_and_message():
    status, first = describe_error(EndPointInternalError(VIRTUOSO_500))
    assert status == 500 and first.startswith("Virtuoso 22023 Error SR549")
    message = user_message(status, first)
    assert "内部エラー" in message and "再読み込み" in message and "SR549" in message
    status, first = describe_error(urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None))
    assert status == 502 and "応答しませんでした" in user_message(status, first)
    assert is_transient(EndPointInternalError(VIRTUOSO_500), 500)
    assert not is_transient(EndPointInternalError("x"), 400)


class FlakyWrapper:
    """1回目は 502、2回目は結果を返す"""
    calls = 0

    def __init__(self, endpoint=None, returnFormat=None):
        pass

    def setQuery(self, q):
        pass

    def query(self):
        FlakyWrapper.calls += 1
        if FlakyWrapper.calls == 1:
            raise urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
        return self

    def convert(self):
        return {"results": {"bindings": [{"x": {"type": "literal", "value": "1"}}]}}


class BrokenWrapper(FlakyWrapper):
    def query(self):
        BrokenWrapper.calls += 1
        raise EndPointInternalError(VIRTUOSO_500)


def test_retry_once_then_succeed(monkeypatch):
    FlakyWrapper.calls = 0
    monkeypatch.setattr(sparql_module, "SPARQLWrapper", FlakyWrapper)
    monkeypatch.setattr(sparql_module, "RETRY_WAIT", 0)
    rows = SPARQL("http://example.org/sparql").exsparql("SELECT ?x WHERE {}")
    assert FlakyWrapper.calls == 2 and rows[0]["x"]["value"] == "1"


def test_give_up_with_user_message(monkeypatch):
    BrokenWrapper.calls = 0
    monkeypatch.setattr(sparql_module, "SPARQLWrapper", BrokenWrapper)
    monkeypatch.setattr(sparql_module, "RETRY_WAIT", 0)
    with pytest.raises(SparqlError) as info:
        SPARQL("http://example.org/sparql").exsparql("SELECT ?x WHERE {}")
    assert BrokenWrapper.calls == 2                       # 1回だけやり直す
    assert info.value.status == 500 and "SR549" in info.value.message
    assert "SPARQL query" in info.value.detail            # 詳しい情報には全文


def test_gadget_error_does_not_break_page():
    """1つのガジェットの問い合わせが失敗しても、ページは表示し、そのガジェットに説明を出す"""
    from tests.test_compare import Fake, CONFIG, CL
    from kgraphnavi.app import build_application, create_app

    class Failing(Fake):
        def query(self, q, params=None):
            if "?legislation" in q:
                raise SparqlError("SPARQL エンドポイントが応答しませんでした（HTTP 502）。", detail="HTTP Error 502", status=502)
            return super().query(q, params)

    app_obj = build_application(str(CONFIG), endpoint="http://localhost/sparql")
    f = Failing()
    app_obj.sparql_client = f
    for g in app_obj.gadgetset.values():
        g.sparql_client = f
    r = create_app(app_obj).test_client().get("/resource?uri=" + CL + "D090298")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "gadget-error" in html and "HTTP 502" in html


def test_long_query_is_sent_by_post(monkeypatch):
    """URI を多く並べた長い問い合わせは、GET の URL で切れないよう POST で送る"""
    sent = []

    class RecordingWrapper:
        def __init__(self, *args, **kwargs):
            self.method = "GET"

        def setQuery(self, query):
            self.text = query

        def setMethod(self, method):
            self.method = method

        def query(self):
            sent.append((self.method, len(self.text)))

            class Response:
                def convert(self):
                    return {"results": {"bindings": []}}
            return Response()

    monkeypatch.setattr(sparql_module, "SPARQLWrapper", RecordingWrapper)
    client = sparql_module.SPARQL("http://example.org/sparql")
    client.exsparql("SELECT ?s WHERE { ?s ?p ?o }")
    iris = ", ".join(f"<http://ds.rois.ac.jp/caselaw/resource/D{i:06d}>" for i in range(300))
    client.exsparql(f"SELECT ?uri WHERE {{ ?uri a ?c FILTER(?uri IN ({iris})) }}")
    assert sent[0][0] == "GET"
    assert sent[1][0] == "POST"


class QueryBadFormed(Exception):
    pass


VIRTUOSO_SYNTAX = ("QueryBadFormed: A bad request has been sent to the endpoint: probably the SPARQL query is badly formed. \n\n"
                   "Response:\nb'Virtuoso 37000 Error SP030: SPARQL compiler, line 0: Parentheses are not balanced at \\'}\\'\\n\\nSPARQL query:\\n...'")


def test_syntax_error_is_not_told_to_reload():
    """構文の誤りは、再読み込みしても直らないので「少し待って再読み込み」と言わない。接続の失敗とも言わない"""
    e = QueryBadFormed(VIRTUOSO_SYNTAX)
    status, first = describe_error(e)
    assert status == 400 and first.startswith("Virtuoso 37000 Error SP030")
    message = user_message(status, first)
    assert "問い合わせに誤り" in message and "SP030" in message
    assert "再読み込み" not in message and "接続できません" not in message
    assert not is_transient(e, status, first)
    # 状態コードが分からなくても、Virtuoso の SPARQL コンパイラのエラーなら問い合わせの誤り
    assert "再読み込み" not in user_message(None, "Virtuoso 37000 Error SP030: SPARQL compiler, line 24: syntax error")
    assert not is_transient(EndPointInternalError("x"), 500, "Virtuoso 37000 Error SP030: SPARQL compiler")


def test_connection_failure_and_unknown_error_messages():
    connection = user_message(None, "<urlopen error [Errno 61] Connection refused>", connection_failed=True)
    assert "接続できませんでした" in connection and "再読み込み" in connection
    unknown = user_message(None, "something odd")
    assert "接続できません" not in unknown and "再読み込み" not in unknown
    assert "sparql_endpoint" in user_message(404, "Not Found")


def test_exsparql_syntax_error_is_not_retried(monkeypatch):
    class SyntaxWrapper(FlakyWrapper):
        calls = 0

        def query(self):
            SyntaxWrapper.calls += 1
            raise QueryBadFormed(VIRTUOSO_SYNTAX)

    monkeypatch.setattr(sparql_module, "SPARQLWrapper", SyntaxWrapper)
    monkeypatch.setattr(sparql_module, "RETRY_WAIT", 0)
    with pytest.raises(SparqlError) as info:
        SPARQL("http://example.org/sparql").exsparql("SELECT * WHERE { ?s ?p ?o ")
    assert SyntaxWrapper.calls == 1
    assert "再読み込み" not in info.value.message
