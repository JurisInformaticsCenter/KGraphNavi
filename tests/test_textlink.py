"""テキストにリンクを付ける（/textlink・/api/textlink）のテスト。リンカは偽のモジュールを使う"""
import json
import sys
import types
from pathlib import Path
import pytest
from kgraphnavi.app import build_application, create_app
from kgraphnavi.textlink import textlink_settings, TextLinker

CONFIG = Path(__file__).resolve().parent.parent / "config" / "caselaw.yaml"
CL = "http://ds.rois.ac.jp/caselaw/resource/D"


def fake_make_linker(options):
    def run(text, min_confidence="低"):
        out = []
        i = text.find("最判平成12年9月7日")
        if i >= 0:
            out.append({"start": i, "end": i + 11, "text": text[i:i + 11], "linked": True, "target": CL + "050001",
                        "ecli": "ECLI:JP:S:2000:0907.H10O1234", "key": "最高裁判所/2000-09-07/平成10(オ)1234",
                        "id_uri": "http://ds.rois.ac.jp/caselaw/id/S/2000/0907.H10O1234", "in_data": True,
                        "ids": ["050001"], "method": "判例集", "confidence": "高", "candidates": []})
        j = text.find("判時1734号3頁")
        if j >= 0:
            out.append({"start": j, "end": j + 9, "text": text[j:j + 9], "linked": False, "method": "結べない",
                        "confidence": "", "candidates": []})
        return out
    run.meta = {"judgments": "5", "id_format": "caselaw-id/0.1", "options": options}
    return run


@pytest.fixture
def client(monkeypatch, tmp_path):
    mod = types.ModuleType("fakelinker")
    mod.make_linker = fake_make_linker
    mod.LABELS = {"item": "引用"}
    monkeypatch.setitem(sys.modules, "fakelinker", mod)
    local = tmp_path / "local.yaml"
    local.write_text("- textlink:\n    module: fakelinker\n    index: idx.sqlite\n    max_chars: 100\n    cors: '*'\n",
                     encoding="utf-8")
    app_obj = build_application(str(CONFIG), endpoint="http://localhost/sparql", local_path=str(local))
    return create_app(app_obj).test_client()


def test_settings(tmp_path):
    cfg = textlink_settings({"module": "m", "index": "a/b.sqlite"}, tmp_path)
    assert cfg["index"] == str((tmp_path / "a" / "b.sqlite").resolve()) and cfg["min_confidence"] == "低"
    with pytest.raises(ValueError):
        textlink_settings({"module": "m", "x": 1}, tmp_path)
    with pytest.raises(ValueError):
        textlink_settings({"index": "a"}, tmp_path)
    with pytest.raises(ValueError):
        textlink_settings({"module": "m", "min_confidence": "強"}, tmp_path)


def test_page(client):
    r = client.get("/textlink")
    assert r.status_code == 200 and "<textarea" in r.get_data(as_text=True)
    r = client.post("/textlink", data={"text": "<b>最判平成12年9月7日と判時1734号3頁", "min_confidence": "中"})
    page = r.get_data(as_text=True)
    assert "&lt;b&gt;" in page                                       # 元のテキストはエスケープ
    assert 'href="/resource?uri=http%3A%2F%2Fds.rois.ac.jp%2Fcaselaw%2Fresource%2FD050001"' in page
    assert "tl-unlinked" in page and "引用 2 件、リンクにした 1 件" in page
    assert 'href="/textlink"' in page                                # 上の帯の入り口


def test_too_long(client):
    r = client.post("/textlink", data={"text": "あ" * 101})
    assert r.status_code == 400 and "長すぎます" in r.get_data(as_text=True)


def test_api(client):
    r = client.post("/api/textlink", json={"text": "前掲 最判平成12年9月7日参照"})
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == "*"
    d = r.get_json()
    assert (d["citations"], d["linked"], d["length"]) == (1, 1, 16)
    x = d["items"][0]
    assert x["ecli"] == "ECLI:JP:S:2000:0907.H10O1234" and x["page"].endswith("/resource?uri=http%3A%2F%2Fds.rois.ac.jp%2Fcaselaw%2Fresource%2FD050001")
    assert d["index"]["options"]["index"].endswith("idx.sqlite")
    assert client.get("/api/textlink", query_string={"text": "判時1734号3頁"}).get_json()["linked"] == 0
    assert client.post("/api/textlink", json={"text": ""}).status_code == 400
    assert client.post("/api/textlink", json={"text": "x", "min_confidence": "強"}).status_code == 400
    assert client.post("/api/textlink", json=["x"]).status_code == 400
    assert client.open("/api/textlink", method="OPTIONS").status_code == 200


def test_not_configured():
    app_obj = build_application(str(CONFIG), endpoint="http://localhost/sparql", local_path=str(CONFIG.with_name("local.yaml.example")))
    c = create_app(app_obj).test_client()
    assert c.get("/textlink").status_code == 404 and c.post("/api/textlink", json={"text": "x"}).status_code == 404
