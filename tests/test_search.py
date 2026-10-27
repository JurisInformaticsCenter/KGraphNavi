"""検索結果をコレクションとして扱う（/search と q の条件。2026.10.19）のテスト"""
import pytest

from kgraphnavi.app import build_application, create_app
from kgraphnavi.collection import AnyCollection, ClassCollection, TextCondition
from kgraphnavi.errors import CollectionError
from tests.test_pages import CONFIG, DBO


def test_text_condition_contains_words():
    pattern = TextCondition("写真 著作").pattern("?uri", 0)
    assert "?uri rdfs:label ?_c0 ." in pattern
    assert 'CONTAINS(LCASE(STR(?_c0)), "写真")' in pattern and 'CONTAINS(LCASE(STR(?_c0)), "著作")' in pattern
    assert "bif:contains" not in pattern


def test_text_condition_bif_and_exact():
    pattern = TextCondition("富士山", method="bif", exact=True).pattern("?uri", 1)
    assert '?_c1 bif:contains \'"富士山"\'' in pattern or '?_c1 bif:contains "\\"富士山\\""' in pattern
    assert 'FILTER(STR(?_c1) = "富士山")' in pattern


def test_text_condition_requires_text():
    with pytest.raises(CollectionError):
        TextCondition("  ")


def test_any_collection_with_condition_uses_only_condition():
    collection = AnyCollection(None).search("富士山")
    query = collection.get_query()
    assert "?_any_p" not in query
    assert "?uri rdfs:label ?_c0 ." in query
    # クラスのコレクションに付けると、クラスの条件と一緒に
    query = ClassCollection(None, DBO + "Mountain").search("富士山").get_query()
    assert f"?uri a <{DBO}Mountain> ." in query and "?uri rdfs:label ?_c0 ." in query


@pytest.fixture
def client_and_queries(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module
    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    return create_app(build_application(str(config), endpoint="http://example.org/sparql")).test_client(), sent


def test_search_page_is_collection(client_and_queries):
    client, sent = client_and_queries
    response = client.get("/search?q=富士山")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "検索結果（富士山）" in html
    assert "検索語:" in html and "種類" in html          # 検索語の条件と種類のファセット
    assert any('CONTAINS(LCASE(STR(?_c0)), "富士山")' in q for q in sent)
    assert any("rdf:type ?value" in q for q in sent)     # 種類の候補


def test_search_exact_mode(client_and_queries):
    client, sent = client_and_queries
    client.get("/search?q=富士山&mode=perfect")
    assert any('FILTER(STR(?_c0) = "富士山")' in q for q in sent)


def test_search_without_text(client_and_queries):
    client, _sent = client_and_queries
    assert "検索語がありません" in client.get("/search?q=").get_data(as_text=True)


def test_search_one_type_redirects_to_class_collection(client_and_queries):
    client, _sent = client_and_queries
    response = client.get(f"/search?q=富士山&f._type={DBO}Mountain")
    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith("/collection?class=http%3A%2F%2Fdbpedia.org%2Fontology%2FMountain")
    assert "q=%E5%AF%8C%E5%A3%AB%E5%B1%B1" in location and "f._type" not in location


def test_collection_with_search_text(client_and_queries):
    client, sent = client_and_queries
    html = client.get(f"/collection?class={DBO}Mountain&q=富士").get_data(as_text=True)
    assert any(f"?uri a <{DBO}Mountain> ." in q and 'CONTAINS(LCASE(STR(?_c0)), "富士")' in q for q in sent)
    assert 'class="collection-search"' in html and 'value="富士"' in html
