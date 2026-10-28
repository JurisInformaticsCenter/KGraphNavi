"""名前を付けて保存したコレクション（保存・読み込み・まとめる。2026.10.19）のテスト"""
import pytest

from kgraphnavi.app import build_application, create_app
from kgraphnavi.errors import CollectionError
from kgraphnavi.saved import SavedCollectionStore, check_name
from tests.test_pages import CONFIG, DBO

A, B, C = "http://example.org/A", "http://example.org/B", "http://example.org/C"


def test_store_save_get_merge(tmp_path):
    store = SavedCollectionStore(tmp_path / "saved")
    store.save("山1", [A, B, A], class_uri=DBO + "Mountain", source="/collection?class=dbo:Mountain")
    store.save("山2", [B, C], class_uri=DBO + "Mountain")
    assert store.get("山1")["uris"] == [A, B] and store.get("山1")["count"] == 2
    with pytest.raises(CollectionError):
        store.save("山1", [C])                      # 同じ名前は上書きを選ばないと保存しない
    store.save("山1", [A, B], overwrite=True)
    assert store.merge(["山1", "山2"], "和", "union")["uris"] == [A, B, C]
    assert store.merge(["山1", "山2"], "積", "intersect")["uris"] == [B]
    assert store.merge(["山1", "山2"], "差", "minus")["uris"] == [A]
    assert store.get("和")["merged_from"] == ["山1", "山2"]
    assert store.get("積")["class"] is None or store.get("積")["class"] == DBO + "Mountain"
    with pytest.raises(CollectionError):
        store.merge(["山1"], "x")                   # 2つ以上
    store.delete("差")
    assert "差" not in store.names()


def test_check_name():
    assert check_name(" 特許の判決 ") == "特許の判決"
    for bad in ["", "a/b", "../x", "x" * 61]:
        with pytest.raises(CollectionError):
            check_name(bad)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module
    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        if "COUNT(DISTINCT ?uri)" in query and "?value" not in query:
            return [{"count": {"type": "literal", "value": "2"}}]
        if query.startswith("SELECT DISTINCT ?uri") and "LIMIT" in query:
            return [{"uri": {"type": "uri", "value": A}}, {"uri": {"type": "uri", "value": B}}]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    application = build_application(str(config), endpoint="http://example.org/sparql")
    return create_app(application).test_client(), sent, application


def test_save_from_collection_page_and_load(client):
    c, sent, application = client
    html = c.get(f"/collection?class={DBO}Mountain").get_data(as_text=True)
    assert 'action="/collections/save"' in html and "保存したコレクション" in html
    response = c.post("/collections/save", data={"source": f"/collection?class={DBO}Mountain&q=富士", "name": "富士の山"})
    assert response.status_code == 302 and "msg=" in response.headers["Location"]
    data = application.saved_store.get("富士の山")
    assert data["uris"] == [A, B] and data["class"] == DBO + "Mountain"
    assert any('CONTAINS(LCASE(STR(?_c0)), "富士")' in q for q in sent)
    # 一覧のページ
    listing = c.get("/collections").get_data(as_text=True)
    assert "富士の山" in listing and "/collection?saved=" in listing
    # 読み込むと、要素を列挙したコレクションをクラスのページで表示する
    sent.clear()
    page = c.get("/collection?saved=富士の山").get_data(as_text=True)
    assert "保存したコレクション: 富士の山" in page
    assert any(f"VALUES ?uri {{ <{A}> <{B}> }}" in q for q in sent)


def test_save_errors(client):
    c, _sent, application = client
    r = c.post("/collections/save", data={"source": "/resource?uri=x", "name": "x"})
    assert "err=" in r.headers["Location"]
    application.saved_max = 1
    r = c.post("/collections/save", data={"source": f"/collection?class={DBO}Mountain", "name": "多い"})
    assert "err=" in r.headers["Location"] and not application.saved_store.exists("多い")
    assert c.get("/collection?saved=無い").status_code == 404


def test_merge_and_delete_routes(client):
    c, _sent, application = client
    store = application.saved_store
    store.save("a", [A, B])
    store.save("b", [B, C])
    r = c.post("/collections/merge", data={"names": ["a", "b"], "name": "ab", "operation": "union"})
    assert "msg=" in r.headers["Location"] and store.get("ab")["uris"] == [A, B, C]
    r = c.post("/collections/delete", data={"delete": "ab"})
    assert not store.exists("ab")


def test_save_selected_uris_from_graph(client):
    """ネットワーク図で範囲選択したノードを保存し、そのコレクションを開く（2026.10.28）"""
    c, _sent, application = client
    r = c.post("/collections/save_uris", data={"name": "図から", "uris": [A, B, A], "class": "dbo:Mountain",
                                               "source": "/collection?class=dbo:Mountain&tab=1"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/collection?saved=")
    data = application.saved_store.get("図から")
    assert data["uris"] == [A, B] and data["class"] == DBO + "Mountain" and data["selected_from"] == "graph"
    # 誤り: URI でない値、選んでいない、上限、同じ名前
    for form in ({"name": "x", "uris": ["not an iri"]}, {"name": "x"}, {"name": "../x", "uris": [A]},
                 {"name": "図から", "uris": [C]}):
        r = c.post("/collections/save_uris", data=form)
        assert "err=" in r.headers["Location"]
    application.saved_max = 1
    r = c.post("/collections/save_uris", data={"name": "多い", "uris": [A, B]})
    assert "err=" in r.headers["Location"] and not application.saved_store.exists("多い")
