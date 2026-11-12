"""探索グラフ（/explore。kgraphnavi/explore.py）のテスト"""
import json
from pathlib import Path

import pytest

from kgraphnavi.app import build_application, create_app
from kgraphnavi.errors import SparqlError
from kgraphnavi.explore import Explorer, count_query, explore_settings, page_query

CL = "http://ds.rois.ac.jp/caselaw/resource/"
CO = "http://ds.rois.ac.jp/caselaw/ontology/"
LAW = "http://lod4all.net/law/resource/"
U = lambda v: {"type": "uri", "value": v}
L = lambda v: {"type": "literal", "value": str(v)}

CONF = {
    "limit": 2,
    "attrs": [{"name": "result", "label": "裁判の結果"}],
    "kinds": [
        {"name": "判例", "types": ["caselawo:CaseLawDocument"], "shape": "ellipse",
         "info": "SELECT ?n ?label ?year ?a_result WHERE { $nodes ?n rdfs:label ?label }"},
        {"name": "条", "types": ["lawo:Clause"], "shape": "round-rectangle",
         "info": "SELECT ?n ?label (COUNT(?d) AS ?count) WHERE { $nodes ?d caselawp:reflawCore ?n } GROUP BY ?n ?label"},
        {"name": "語", "types": ["caselawo:Term"]},
    ],
    "relations": [
        {"name": "doc_clause", "label": "参照している条", "from": "判例", "to": "条",
         "query": "SELECT DISTINCT ?n WHERE { $uri caselawp:reflawCore ?n }"},
        {"name": "clause_doc", "label": "この条を参照する判例", "from": "条", "to": "判例", "direction": "in",
         "weak": ["中"],
         "query": "SELECT ?n ?conf ?year WHERE { ?n caselawp:reflawCore $uri } ORDER BY DESC(?year)"},
    ],
}


class Fake:
    """問い合わせの文字列で答えを決める SPARQL クライアント"""

    def __init__(self):
        self.queries = []

    def query(self, q, params=None):
        uri = (params or {}).get("uri", "")
        self.queries.append(q)
        if "COUNT(DISTINCT ?n)" in q:
            return [{"total": L(5 if "reflawCore $uri" in q else 2)}]
        if "VALUES ?n" in q:
            if "reflawCore ?n" in q:     # 条の info
                return [{"n": U(LAW + "A_709"), "label": L("民法709条"), "count": L(1200)}]
            rows = []
            for d in ("D1", "D2", "D3"):
                if CL + d in q:
                    rows.append({"n": U(CL + d), "label": L("判例" + d), "year": L("2020-01-01"), "a_result": L("棄却")})
            return rows
        if "a ?t" in q:
            return [{"t": U({CL + "D1": CO + "CaseLawDocument", LAW + "A_709": "http://lod4all.net/law/ontology/Clause"}
                             .get(uri, CO + "Other"))}]
        if "$uri caselawp:reflawCore ?n" in q.replace(uri, "$uri") or "reflawCore ?n }" in q:
            return [{"n": U(LAW + "A_709")}, {"n": U(LAW + "A_715")}]
        if "?n caselawp:reflawCore" in q:
            return [{"n": U(CL + "D2"), "conf": L("強"), "year": L(2021)},
                    {"n": U(CL + "D3"), "conf": L("中"), "year": L(2019)}]
        if "rdfs:label ?label } LIMIT 1" in q:
            return [{"label": L("ラベル")}]
        return []

    def query_value(self, q, var, **params):
        rows = self.query(q, params)
        return rows[0][var]["value"] if rows and var in rows[0] else None

    def query_values(self, q, var, **params):
        return [r[var]["value"] for r in self.query(q, params) if var in r]

    def retrieve(self, text, mode):
        if mode == "perfect":
            return [(CL + "パワハラ", "パワハラ", CO + "Term")]
        return [(CL + "パワハラ", "パワハラ", CO + "Term"), (CL + "パワハラ行為", "パワハラ行為", CO + "Term"),
                (CL + "X", "パワハラ事件", CO + "Unknown")]


def explorer(fake=None):
    settings = explore_settings(json.loads(json.dumps(CONF)))
    from kgraphnavi.explore import resolve_kind_types
    from kgraphnavi.app import expand_prefixed, STANDARD_PREFIXES
    prefixes = {**STANDARD_PREFIXES, "caselawo": CO, "lawo": "http://lod4all.net/law/ontology/"}
    resolve_kind_types(settings, lambda t: expand_prefixed(t, prefixes))
    return Explorer(fake or Fake(), settings)


def test_settings_validation():
    s = explore_settings(json.loads(json.dumps(CONF)))
    assert s["limit"] == 2 and s["save_kind"] == "判例"
    assert s["relations"][1]["direction"] == "in" and s["relations"][1]["weak"] == ["中"]
    bad = [
        {**CONF, "kinds": []},
        {**CONF, "relations": [{**CONF["relations"][0], "to": "無い種類"}]},
        {**CONF, "relations": [{**CONF["relations"][0], "query": "SELECT ?n WHERE { ?x ?p ?n }"}]},      # $uri が無い
        {**CONF, "relations": [{**CONF["relations"][0], "query": "SELECT ?n WHERE { $uri ?p ?n } LIMIT 10"}]},
        {**CONF, "kinds": [{**CONF["kinds"][0], "shape": "cloud"}] + CONF["kinds"][1:]},
        {**CONF, "kinds": [{**CONF["kinds"][0], "info": "SELECT ?n WHERE { ?n ?p ?o }"}] + CONF["kinds"][1:]},
        {**CONF, "unknown": 1},
    ]
    for conf in bad:
        with pytest.raises(ValueError):
            explore_settings(json.loads(json.dumps(conf)))


def test_count_and_page_queries():
    q = "SELECT ?n ?year WHERE { ?n caselawp:reflawCore $uri } ORDER BY DESC(?year)"
    c = count_query(q)
    assert c.startswith("SELECT (COUNT(DISTINCT ?n) AS ?total)") and "ORDER BY" not in c
    assert page_query(q, 30, 10).endswith("LIMIT 10\nOFFSET 30")


def test_node_kind_and_info():
    e = explorer()
    node = e.node(CL + "D1")
    assert node["kind"] == "判例" and node["label"] == "判例D1" and node["x"] == 2020
    assert node["attrs"] == {"result": "棄却"}
    assert node["href"].startswith("/resource?uri=http%3A")
    clause = e.node(LAW + "A_709")
    assert clause["kind"] == "条" and clause["count"] == 1200


def test_counts_per_relation():
    e = explorer()
    rels = e.counts(LAW + "A_709", "条")
    assert [r["name"] for r in rels] == ["clause_doc"] and rels[0]["count"] == 5


def test_expand_in_direction_with_confidence():
    e = explorer()
    res = e.expand(LAW + "A_709", "clause_doc")
    assert res["total"] == 5 and res["limit"] == 2 and res["offset"] == 0
    ids = [n["id"] for n in res["nodes"]]
    assert ids == [CL + "D2", CL + "D3"]
    assert all(n["kind"] == "判例" for n in res["nodes"])
    assert res["nodes"][0]["attrs"]["result"] == "棄却"          # 種類の info でまとめて付けた
    edge = {e_["source"]: e_ for e_ in res["edges"]}
    assert edge[CL + "D2"]["target"] == LAW + "A_709"           # direction: in → ?n から $uri へ
    assert edge[CL + "D2"]["weak"] is False and edge[CL + "D3"]["weak"] is True
    # LIMIT・OFFSET を付けて問い合わせる
    assert any("LIMIT 2\nOFFSET 0" in q for q in e.sparql.queries)


def test_expand_errors():
    e = explorer()
    with pytest.raises(ValueError):
        e.expand(LAW + "A_709", "無い関係")
    with pytest.raises(ValueError):
        e.expand("not an iri", "clause_doc")


def test_seeds_from_text_prefers_exact_and_known_kinds():
    seeds = explorer().seeds_from_text("パワハラ")
    assert [s["id"] for s in seeds] == [CL + "パワハラ", CL + "パワハラ行為"]   # 種類の無いものは除く
    assert seeds[0]["exact"] is True and seeds[1]["exact"] is False


# ---- 画面（Flask）----

CONFIG = Path(__file__).resolve().parent.parent / "config" / "caselaw.yaml"


@pytest.fixture
def client(tmp_path):
    app_obj = build_application(str(CONFIG), endpoint="http://localhost/sparql")
    fake = Fake()
    app_obj.sparql_client = fake
    for g in app_obj.gadgetset.values():
        g.sparql_client = fake
    from kgraphnavi.saved import SavedCollectionStore
    app_obj.saved_store = SavedCollectionStore(tmp_path)
    return create_app(app_obj).test_client()


def test_caselaw_config_has_explore(client):
    app_obj = client.application.extensions["application"]
    conf = app_obj.explore_config
    names = {k["name"] for k in conf["kinds"]}
    assert {"判例", "条", "語", "論点", "トピック"} <= names
    assert all(r["from"] in names and r["to"] in names for r in conf["relations"])
    assert conf["kinds"][0]["types"] == [CO + "CaseLawDocument"]
    assert 'href="/explore"' in app_obj.navi


def test_explore_page_with_keyword(client):
    r = client.get("/explore?q=パワハラ")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "kgExplore(" in html and "/templates/js/explore.js" in html and "encode.js" in html
    data = json.loads(html.split('id="kg-explore-data">', 1)[1].split("</script>", 1)[0])
    assert data["seeds"][0]["id"] == CL + "パワハラ" and data["seeds"][0]["start"] is True
    assert data["save"]["action"] == "/collections/save_uris"
    assert data["config"]["saveKind"] == "判例"


def test_explore_json_endpoints(client):
    r = client.get("/explore/node?uri=" + CL + "D1")
    body = r.get_json()
    assert r.status_code == 200 and body["node"]["kind"] == "判例"
    assert {x["name"] for x in body["relations"]} >= {"doc_clause", "doc_keyword"}
    r = client.get("/explore/expand?uri=" + CL + "D1&rel=nope")
    assert r.status_code == 400 and "error" in r.get_json()


def test_save_from_explore_keeps_source(client, tmp_path):
    r = client.post("/collections/save_uris", data={
        "name": "探索の試し", "uris": [CL + "D1", CL + "D2"], "selected_from": "explore",
        "source": "/explore?q=x#s=%5B%5D", "class": "caselawo:CaseLawDocument"})
    assert r.status_code == 302
    saved = json.loads((tmp_path / "探索の試し.json").read_text(encoding="utf-8"))
    assert saved["selected_from"] == "explore" and saved["source"].startswith("/explore?q=x#s=")
    assert saved["count"] == 2


def test_explore_without_config_is_404(client):
    client.application.extensions["application"].explore_config = None
    assert client.get("/explore").status_code == 404
    assert client.get("/explore/node?uri=" + CL + "D1").status_code == 404


def test_sparql_error_in_counts_is_reported():
    class Broken(Fake):
        def query_value(self, q, var, **params):
            raise SparqlError("止まっています", detail="x", status=503)
    e = explorer(Broken())
    rels = e.counts(LAW + "A_709", "条")
    assert rels[0]["count"] is None and "止まって" in rels[0]["error"]


def test_resource_page_has_explore_button(client):
    fake = client.application.extensions["application"].sparql_client
    fake.get_target = lambda uri, path: [CO + "Term"] if "パワハラ" in uri else [CO + "Other"]
    html = client.get("/resource?uri=" + CL + "パワハラ").get_data(as_text=True)
    assert 'class="kg-explore-entry-button" href="/explore?uri=http%3A%2F%2Fds.rois.ac.jp' in html
    assert "この語から探索グラフで広げる" in html
    html = client.get("/resource?uri=" + CL + "X").get_data(as_text=True)
    assert "kg-explore-entry-button" not in html
