"""キーワードからトピックのコレクションを作る（kgraphnavi/topic.py。2026.10.26）のテスト"""
import pytest

from kgraphnavi.app import build_application, create_app
from kgraphnavi.topic import classify, level_of, topic_settings, override_from_args, DEFAULTS
from tests.test_pages import CONFIG

R = "http://dbpedia.org/resource/"
CAT = R + "Category:"
V1, V2, V3, V4 = R + "Mount_Fuji", R + "Mount_St._Helens", R + "Mount_Rainier", R + "Lake_X"


def test_classify():
    cfg = dict(DEFAULTS)
    # 種100件のうち40件、全体100万件のうち300件 → 主なリンク
    assert classify(40, 300, 100, 1_000_000, cfg)[0] == "main"
    # 全体で多く使われる（5万件）が偏りは小さい → 補助リンク
    assert classify(20, 50_000, 100, 1_000_000, cfg)[0] == "aux"
    # 件数が少ない・偏りが小さい → 使わない
    assert classify(3, 10, 100, 1_000_000, cfg)[0] == ""
    assert classify(50, 900_000, 100, 1_000_000, cfg)[0] == ""


def test_level_of():
    assert level_of(False, True, False, True)[0] == "強"
    assert level_of(False, False, True, False)[0] == "中"
    assert level_of(True, True, False, False)[0] == "中"
    assert level_of(False, True, False, False)[0] == "弱"


def test_settings_and_override():
    cfg = topic_settings({"text_properties": ["dbo:abstract"], "link_properties": ["dct:subject"], "total": 10})
    assert cfg["seed_max"] == DEFAULTS["seed_max"] and cfg["label_property"] == "rdfs:label"
    with pytest.raises(ValueError):
        topic_settings({"link_properties": []})
    with pytest.raises(ValueError):
        topic_settings({"link_properties": ["dct:subject"], "unknown": 1})
    assert override_from_args({"q": "x"}) is None
    o = override_from_args({"q": "x", "edit": "1", "r.http://a": "main", "r.http://b": "aux", "r.http://c": ""})
    assert o["main"] == ["http://a"] and o["aux"] == ["http://b"] and o["none"] == ["http://c"] and o["links_edited"]


TOPIC_CONFIG = CONFIG + """
- topic:
    text_properties: [rdfs:label, dbo:abstract]
    link_properties: [dct:subject]
    lang: en
    total: 1000000
- saved_collections_dir: saved
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    from kgraphnavi import sparql as sparql_module
    sent = []

    def fake_exsparql(self, query):
        sent.append(query)
        q = " ".join(query.split())
        if "bif:contains" in q and "ASK" in q:
            return []
        if q.startswith("SELECT DISTINCT ?s ?_l WHERE { {") :      # 種の要素
            return [{"s": {"type": "uri", "value": u}, "_l": {"type": "literal", "value": l}}
                    for u, l in ((V1, "Mount Fuji"), (V2, "Stratovolcano St. Helens"), (V4, "Lake X"))]
        if q.startswith("SELECT ?o (COUNT(DISTINCT ?s) AS ?c)"):    # リンクの候補
            return [{"o": {"type": "uri", "value": CAT + "Stratovolcanoes_of_Japan"}, "c": {"type": "literal", "value": "2"}},
                    {"o": {"type": "uri", "value": CAT + "Living_people"}, "c": {"type": "literal", "value": "1"}}]
        if q.startswith("SELECT ?o (COUNT(DISTINCT ?s) AS ?d)"):    # 全体での件数
            return [{"o": {"type": "uri", "value": CAT + "Stratovolcanoes_of_Japan"}, "d": {"type": "literal", "value": "30"}},
                    {"o": {"type": "uri", "value": CAT + "Living_people"}, "d": {"type": "literal", "value": "900000"}}]
        if q.startswith("SELECT DISTINCT ?s ?_l WHERE { VALUES ?o"):  # 主なリンクで入る要素
            return [{"s": {"type": "uri", "value": V1}}, {"s": {"type": "uri", "value": V3}, "_l": {"type": "literal", "value": "Mount Rainier"}}]
        return []

    monkeypatch.setattr(sparql_module.SPARQL, "exsparql", fake_exsparql)
    config = tmp_path / "test.yaml"
    config.write_text(TOPIC_CONFIG, encoding="utf-8")
    application = build_application(str(config), endpoint="http://example.org/sparql")
    application.text_search = "contains"
    return create_app(application).test_client(), sent, application


def test_topic_page_and_save(client, monkeypatch):
    import kgraphnavi.topic as topic_module
    monkeypatch.setitem(topic_module.DEFAULTS, "min_count", 1)
    c, sent, application = client
    application.topic_config["min_count"] = 1
    html = c.get("/topic?q=stratovolcano").get_data(as_text=True)
    assert "トピック「stratovolcano」" in html and "1. 何をしたか" in html and "3. 次にできること" in html
    assert "Stratovolcanoes_of_Japan" in html or "Stratovolcanoes of Japan" in html
    assert "Mount Rainier" in html          # 語は無いが、主なリンクで入る（中）
    assert any('CONTAINS(LCASE(STR(?_t1)), LCASE("stratovolcano"))' in q for q in sent)
    r = c.post("/topic/save", data={"source": "/topic?q=stratovolcano", "name": "成層火山"})
    assert r.status_code == 302 and "saved=" in r.headers["Location"]
    uris = application.saved_store.get("成層火山")["uris"]
    assert V1 in uris and V3 in uris and V4 not in uris   # 弱（語だけ）は入れない


def test_command_builder(tmp_path):
    """外のコマンドの版: 引数の組み立てと、結果の JSON の読み込み"""
    import json, sys
    from kgraphnavi.topic import CommandTopicBuilder
    script = tmp_path / "maker.py"
    script.write_text(
        "import json, sys\n"
        "a = sys.argv[1:]; out = a[a.index('--json') + 1]\n"
        "json.dump({'keyword': a[0], 'seed_count': 2, 'total': 100, 'words': [{'word': a[0], 'kind': 'キーワード'}],"
        " 'links': [{'id': 'L1', 'uri': 'http://x/L1', 'label': '条1', 'prop': 'p', 'count': 2, 'df': 5, 'lift': 20, 'role': 'aux'}],"
        " 'related': [{'word': 'いじめ', 'core': True}], 'context': ['上司'],"
        " 'members': [{'uri': 'http://x/D1', 'label': 'D1', 'level': '強', 'via': '語|補助条'}], 'args': a}, open(out, 'w'))\n",
        encoding="utf-8")
    cfg = topic_settings({"builder": "command", "command": [sys.executable, str(script), "{q}", "--json", "{json}"]})
    b = CommandTopicBuilder(cfg)
    first, extra = b.args("パワーハラスメント|パワハラ", override_from_args(
        {"edit": "1", "r.L1": "main", "w_all": ["x"], "add_related": "嫌がらせ"}))
    assert first == "パワーハラスメント" and extra[:2] == ["--add-word", "パワハラ"]
    assert "--add-clause" in extra and "L1" in extra and ["--drop-word", "x"] == extra[2:4] and "--add-related" in extra
    res = b.build("パワーハラスメント")
    assert res.seed_count == 2 and res.links[0].key() == "L1" and res.members[0][2] == "強" and res.related == [("いじめ", True)]


def test_command_builder_async_and_render(tmp_path):
    """外のコマンドを裏で動かし、途中の段階（@@進み）を取る。詳しい手がかりで画面を作る（2026.11.1）"""
    import sys, time
    from kgraphnavi.topic import CommandTopicBuilder, render_topic, render_topic_progress
    script = tmp_path / "maker2.py"
    script.write_text(
        "import json, sys, time\n"
        "a = sys.argv[1:]; out = a[a.index('--json') + 1]\n"
        "print('@@進み 語を広げました', file=sys.stderr, flush=True); time.sleep(0.3)\n"
        "print('@@進み 本文を数えています', file=sys.stderr, flush=True)\n"
        "json.dump({'keyword': a[0], 'seed_count': 1, 'total': 10, 'words': [{'word': a[0], 'kind': 'キーワード'}],"
        " 'links': [{'id': 'L1', 'uri': 'http://x/L1', 'label': '公職選挙法204条', 'prop': 'p', 'count': 1, 'df': 2, 'lift': 5, 'role': 'main'}],"
        " 'members': [{'uri': 'http://x/D1', 'label': '選挙無効請求事件', 'level': '強', 'via': '条|語', 'casename': '選挙無効請求事件',"
        " 'caseno': '平成29(行ツ)47', 'court': '最高裁判所大法廷', 'date': '2017-09-27',"
        " 'clauses': [{'label': '公職選挙法204条', 'role': 'main'}], 'words': [[a[0], 12]], 'related': [], 'name_hit': False}],"
        " 'summary': {'words': 1, 'seed': 1, 'main': 1, 'aux': 0, 'counted_words': 1, 'levels': {'強': 1, '中': 0, '弱': 0}}}, open(out, 'w'))\n",
        encoding="utf-8")
    cfg = topic_settings({"builder": "command", "command": [sys.executable, str(script), "{q}", "--json", "{json}"]})
    CommandTopicBuilder.CACHE.clear(); CommandTopicBuilder.JOBS.clear()
    b = CommandTopicBuilder(cfg)
    res, job = b.start("選挙制度")
    assert res is None and job.state == "running"
    assert "作っています" in render_topic_progress(job, "/topic?q=選挙制度")
    job.done.wait(10)
    st = job.status()
    assert st["state"] == "done" and [s["msg"] for s in st["steps"]] == ["語を広げました", "本文を数えています"]
    res, job2 = b.start("選挙制度")          # 2回目は覚えておいた結果
    assert job2 is None and res.details["http://x/D1"]["court"] == "最高裁判所大法廷"
    html = render_topic(res, cfg, "選挙制度", False, "/topic?q=選挙制度", True)
    assert "平成29(行ツ)47 最高裁判所大法廷 2017-09-27" in html and "主な条: 公職選挙法204条" in html
    assert "語「選挙制度」本文12回" in html and "強だけ" in html and "コレクションとして保存" in html


def test_command_builder_error(tmp_path):
    import sys
    from kgraphnavi.topic import CommandTopicBuilder
    script = tmp_path / "bad.py"
    script.write_text("import sys\nprint('だめ', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8")
    cfg = topic_settings({"builder": "command", "command": [sys.executable, str(script), "{q}", "--json", "{json}"]})
    CommandTopicBuilder.CACHE.clear(); CommandTopicBuilder.JOBS.clear()
    res, job = CommandTopicBuilder(cfg).start("x")
    job.done.wait(10)
    assert job.state == "error" and "失敗しました（3）" in job.error and "だめ" in job.error
