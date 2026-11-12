#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
パンくずリスト（履歴型＋リソースの所属コレクション。2026.11.9）のテスト

経路の記録と表示はブラウザ側（templates/js/breadcrumb.js）。ここではサーバが渡すキー・段の名前・所属コレクションを確かめる
"""

import html as htmlmod
import re

import pytest
from werkzeug.datastructures import MultiDict

from kgraphnavi.app import build_application, create_app
from kgraphnavi.makehtml import breadcrumb_key, make_breadcrumb, shorten_crumb, BREADCRUMB_TITLE_MAX
from kgraphnavi.views import collection_crumb_title
from kgraphnavi.facets import request_params

EX = "http://example.org/"


# --------------------------------------------------
# 段のキー
# --------------------------------------------------

def test_key_ignores_facets_paging_and_tab():
    a = breadcrumb_key("/collection", MultiDict([("class", EX + "Doc")]))
    b = breadcrumb_key("/collection", MultiDict([("class", EX + "Doc"), ("f.year.min", "2000"), ("page", "2"), ("tab", "1")]))
    assert a == b


def test_key_distinguishes_target():
    a = breadcrumb_key("/resource", MultiDict([("uri", EX + "a")]))
    b = breadcrumb_key("/resource", MultiDict([("uri", EX + "b")]))
    assert a != b
    assert breadcrumb_key("/collection", MultiDict([("class", EX + "a")])) != breadcrumb_key("/resource", MultiDict([("uri", EX + "a")]))


def test_key_is_order_independent():
    a = breadcrumb_key("/compare", MultiDict([("uri", EX + "a"), ("uri", EX + "b"), ("view", "v")]))
    b = breadcrumb_key("/compare", MultiDict([("view", "v"), ("uri", EX + "b"), ("uri", EX + "a")]))
    assert a == b


def test_key_q_only_where_it_names_the_target():
    # /search の q は対象（検索語）、/collection の q はコレクション内の絞り込み
    assert breadcrumb_key("/search", MultiDict([("q", "a")])) != breadcrumb_key("/search", MultiDict([("q", "b")]))
    assert breadcrumb_key("/collection", MultiDict([("class", "c"), ("q", "a")])) == breadcrumb_key("/collection", MultiDict([("class", "c")]))


# --------------------------------------------------
# 段の名前
# --------------------------------------------------

def test_collection_crumb_title_with_conditions():
    params = request_params(MultiDict([
        ("class", EX + "Doc"),
        ("f.suit", EX + "ontology/行政訴訟"),
        ("f.suit", "民事訴訟"),
        ("f.year.min", "2000"),
        ("f.year.max", "2010"),
        ("q", "損害"),
    ]), path="/collection")
    title = collection_crumb_title("Doc", params)
    assert title == "Doc［「損害」; 行政訴訟,民事訴訟; 2000–2010］"


def test_collection_crumb_title_without_conditions():
    params = request_params(MultiDict([("class", EX + "Doc")]), path="/collection")
    assert collection_crumb_title("Doc", params) == "Doc"


def test_long_title_is_shortened():
    text = "あ" * 100
    assert len(shorten_crumb(text)) == BREADCRUMB_TITLE_MAX
    assert shorten_crumb(text).endswith("…")


def test_make_breadcrumb_escapes_and_has_parent():
    nav = make_breadcrumb('"<x>"', path="/resource", args=MultiDict([("uri", EX + "a")]),
                          parent={"title": "Doc", "href": "/collection?class=x&y=1"})
    assert 'data-title="&quot;&lt;x&gt;&quot;"' in nav
    assert 'data-kind="resource"' in nav
    assert 'href="/collection?class=x&amp;y=1"' in nav
    assert "Doc の一覧" in nav


# --------------------------------------------------
# ページ
# --------------------------------------------------

CONFIG = """
- title: TestKG
- label_lang: ja
- prefixes:
    ex: http://example.org/
- def: page
  name: Doc
  type: ex:Doc
  gadget: [g]
- def: page
  name: Other
  type: '*'
  gadget: [g]
- def: page
  name: Docs
  type: collection
  class: ex:Doc
  gadget: [g2]
- def: gadget
  name: g
  get:
    type: sparql
    src: 'select ?p ?o where { $uri ?p ?o }'
  show:
    type: htable
- def: gadget
  name: g2
  get:
    type: sparql
    src: 'select ?entity where { $collection }'
  show:
    type: htable
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module

    def fake_exsparql(self, query):
        if "?target where" in query:
            if "/doc1>" in query:
                return [{"target": {"type": "uri", "value": EX + "Doc"}}]
            return [{"target": {"type": "uri", "value": EX + "Thing"}}]
        if "?label WHERE" in query:
            if "/doc1>" in query:
                return [{"label": {"type": "literal", "value": "Judgment one", "xml:lang": "en"}},
                        {"label": {"type": "literal", "value": "判決その一", "xml:lang": "ja"}}]
            raise RuntimeError("ラベルの問い合わせに失敗")
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    return create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client()


def nav_of(html):
    m = re.search(r'<nav class="kg-breadcrumb"[^>]*>.*?</nav>', html, re.S)
    assert m, "パンくずの欄がない"
    return m.group(0)


def attr(nav, name):
    return htmlmod.unescape(re.search(name + r'="([^"]*)"', nav).group(1))


def test_resource_page_breadcrumb_uses_label_and_parent(client):
    html = client.get("/resource?uri=" + EX + "doc1").get_data(as_text=True)
    nav = nav_of(html)
    assert attr(nav, "data-title") == "判決その一"         # label_lang の言語を優先
    assert attr(nav, "data-key") == "/resource?uri=http%3A%2F%2Fexample.org%2Fdoc1"
    assert 'class="kg-crumb-parent" href="/collection?class=http%3A%2F%2Fexample.org%2FDoc"' in nav
    assert "/templates/js/breadcrumb.js" in html


def test_resource_page_without_collection_page_has_no_parent(client):
    # 種類のコレクションのページが無い・ラベルの問い合わせに失敗してもページは出る（名前はローカル名）
    response = client.get("/resource?uri=" + EX + "other")
    assert response.status_code == 200
    nav = nav_of(response.get_data(as_text=True))
    assert "kg-crumb-parent" not in nav
    assert attr(nav, "data-title") == "other"


def test_collection_page_breadcrumb(client):
    html = client.get("/collection?class=ex:Doc&f.year.min=2000").get_data(as_text=True)
    nav = nav_of(html)
    assert attr(nav, "data-kind") == "collection"
    assert attr(nav, "data-mark") == "一覧"
    assert attr(nav, "data-title") == "Doc［2000–］"
    assert attr(nav, "data-key") == "/collection?class=ex%3ADoc"


def test_top_page_resets_trail(client):
    html = client.get("/").get_data(as_text=True)
    assert 'sessionStorage.removeItem("kgTrail")' in html
