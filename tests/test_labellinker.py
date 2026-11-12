"""ラベルの辞書のリンカ（kgraphnavi/labellinker.py）のテスト。辞書は TSV の小さなもの"""
from pathlib import Path
import pytest
from kgraphnavi.labellinker import build, make_linker, normalize, rows_from_tsv, main
from kgraphnavi.app import build_application, create_app

R = "http://dbpedia.org/resource/"
TSV = f"""{R}Mount_Fuji\tMount Fuji\t50000\t山
{R}Mount_Fuji\t富士山\t50000\t山
{R}Mount_Fuji\tFujisan\t50000\t山（別名）
{R}Japan\tJapan\t100000\t国
{R}Japan\t日本\t100000\t国
{R}Georgia_(country)\tGeorgia\t40000\t国
{R}Georgia_(mountain)\tGeorgia\t1000\t山
{R}Alps\tAlps\t60000\t山脈
{R}Alps_(film)\tAlps\t55000\t山
{R}NASA\tNASA\t30000\t
{R}The_Peak\tThe\t10\t山
"""
CONFIG = Path(__file__).resolve().parent.parent / "config"


@pytest.fixture
def index(tmp_path):
    tsv = tmp_path / "labels.tsv"
    tsv.write_text(TSV, encoding="utf-8")
    path = str(tmp_path / "sub" / "labels.sqlite")
    info = build(rows_from_tsv(str(tsv)), path, {}, {"source": "test"})
    assert (info["labels"], info["resources"]) == ("11", "8")
    return path


def test_normalize():
    s, pos = normalize("Ｍｏｕｎｔ　 Fuji")
    assert s == "mount fuji" and pos[0] == 0 and pos[6] == 7 and pos[-1] == 11


def test_link(index):
    run = make_linker({"index": index, "stopwords": ["The"]})
    text = "Mount Fuji (富士山) is in Japan; the Alps are in Europe. Georgia and NASA, nasa. Fujisanx 日本の Ｍｏｕｎｔ　Ｆｕｊｉ"
    got = [(x["text"], x["key"], x["confidence"], x["linked"]) for x in run(text)]
    assert got == [("Mount Fuji", "Mount Fuji", "高", True), ("富士山", "Mount Fuji", "高", True),
                   ("Japan", "Japan", "高", True), ("Alps", "Alps", "低", True),
                   ("Georgia", "Georgia", "中", True), ("NASA", "NASA", "中", True),
                   ("日本", "Japan", "中", True), ("Ｍｏｕｎｔ　Ｆｕｊｉ", "Mount Fuji", "高", True)]
    x = run(text)[3]
    assert x["target"] == R + "Alps" and x["candidates"] == [f"Alps <{R}Alps_(film)>"] and "決め手" in x["method"]
    assert [x["text"] for x in run(text, "中")if x["linked"]] == ["Mount Fuji", "富士山", "Japan", "Georgia", "NASA", "日本", "Ｍｏｕｎｔ　Ｆｕｊｉ"]
    assert run.meta["format"] == "kgraphnavi-labels/1" and run.meta["source"] == "test"


def test_missing_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_linker({"index": str(tmp_path / "none.sqlite")})


def test_dbpedia_textlink(index, tmp_path):
    local = tmp_path / "local.yaml"
    local.write_text(f"- textlink:\n    module: kgraphnavi.labellinker\n    index: {index}\n    title: リンク\n", encoding="utf-8")
    app_obj = build_application(str(CONFIG / "dbpedia.yaml"), endpoint="http://localhost/sparql", local_path=str(local))
    c = create_app(app_obj).test_client()
    page = c.get("/textlink").get_data(as_text=True)
    assert "知識グラフのラベル" in page and "Mount Fuji is" in page           # モジュールの文言
    page = c.post("/textlink", data={"text": "Mount Fuji in Japan"}).get_data(as_text=True)
    assert 'href="/resource?uri=http%3A%2F%2Fdbpedia.org%2Fresource%2FMount_Fuji"' in page
    assert "<th>見つけた語</th><th>リソース</th><th>決め方</th>" in page        # 空の列名の列は出さない
    d = c.post("/api/textlink", json={"text": "富士山と日本"}).get_json()
    assert [x["target"] for x in d["items"]] == [R + "Mount_Fuji", R + "Japan"]


def test_dbpedia_config_queries():
    from kgraphnavi.app import load_config
    tl = load_config(str(CONFIG / "dbpedia.yaml"), local_path=str(CONFIG / "local.yaml.example"))["textlink"]
    assert tl["module"] == "kgraphnavi.labellinker" and tl["index"].endswith("data/dbpedia-labels.sqlite")
    assert [q["name"] for q in tl["options"]["queries"]] == ["山", "山（別名）", "山脈", "国", "初登頂した人"]


def test_cli(index, tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    tsv = tmp_path / "labels.tsv"
    cfg.write_text(f"- sparql_endpoint: http://localhost/sparql\n- textlink:\n    module: kgraphnavi.labellinker\n    index: out.sqlite\n",
                   encoding="utf-8")
    main(["build", str(cfg), "--tsv", str(tsv)])
    assert (tmp_path / "out.sqlite").exists()
    main(["link", str(cfg), "富士山"])
    assert "Mount_Fuji" in capsys.readouterr().out
