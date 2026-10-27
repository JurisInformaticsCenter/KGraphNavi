import re
from pathlib import Path
from kgraphnavi.app import build_application, create_app
from kgraphnavi.compare import compare_settings
import pytest
U = lambda v: {"type":"uri","value":v}
L = lambda v: {"type":"literal","value":v}
CL="http://ds.rois.ac.jp/caselaw/resource/"
class Fake:
    def query(self, q, params=None):
        uri=(params or {}).get("uri","")
        i=uri[-6:]
        if "judgmentdate ?k" in q: return [{"k":L({"082464":"2016-01-01","087255":"2017-10-27","090298":"2021-05-17"}[i])}]
        if "?legislation" in q:
            rows=[{"legislation":U("http://lod4all.net/law/resource/L709"),"label":L("民法709条"),"status":L("現行")}]
            if i!="090298": rows.append({"legislation":U("http://lod4all.net/law/resource/K1"),"label":L("国家賠償法1条1項")})
            if i=="082464": rows.append({"legislation":U("http://lod4all.net/law/resource/X"),"label":L("労働安全衛生法22条")})
            return rows
        if "?issue" in q: return [{"issue":U(CL+"I"+i+"_1"),"label":L("争点"+i),"outcome":L("認める"),"otext":L("…と認める")}]
        if "?caseno" in q: return [{"caseno":L("平成"+i),"court":U("http://ds.rois.ac.jp/caselaw/ontology/裁判所"+i),"judgmentdate":L("2021"),"result":U("http://x/破棄差戻"),"id":L(i),"year":L("2021")}]
        if "?p ?o ?ol" in q: return [{"p":U("http://www.w3.org/2000/01/rdf-schema#label"),"o":L("ラベル"+i)},{"p":U("http://ds.rois.ac.jp/caselaw/property/year"),"o":L("2021")}]
        if "?l where" in q: return [{"l":L("判例"+i)}]
        if "?kind ?date ?court ?doc" in q: return [{"doc":U(CL+"D087255"),"label":L("x")},{"doc":U(CL+"D082464"),"label":L("y")}]
        return []
    def query_value(self, q, var, **params):
        r=self.query(q, params); return r[0][var]["value"] if r and var in r[0] else None
    def get_target(self, uri, path): return ["http://ds.rois.ac.jp/caselaw/ontology/CaseLawDocument"]

CONFIG = Path(__file__).resolve().parent.parent / "config" / "caselaw.yaml"


@pytest.fixture
def client():
    app_obj = build_application(str(CONFIG), endpoint="http://localhost/sparql")
    f = Fake()
    app_obj.sparql_client = f
    for g in app_obj.gadgetset.values():
        g.sparql_client = f
    return create_app(app_obj).test_client()


def test_settings():
    views = compare_settings({"name": "a", "rows": ["G", {"gadget": "H", "align": "x"}]})
    assert views[0]["rows"][0] == {"gadget": "G"} and views[0]["max"] == 4
    with pytest.raises(ValueError):
        compare_settings([{"name": "a"}])


def test_appeal_chain_sorted_by_date(client):
    r = client.get("/compare?from=AppealCaseLaw&uri=" + CL + "D090298")
    assert r.status_code == 200
    h = r.get_data(as_text=True)
    heads = re.findall(r'cmp-head">[^<]*<a[^>]*>([^<]*)', h)
    assert heads == ["判例082464", "判例087255", "判例090298"]       # 地裁・高裁・最高裁の順
    assert "共通 1 件・違い 2 件" in h                                 # 参照法令をそろえた表


def test_builtin_and_errors(client):
    r = client.get("/compare?uri=" + CL + "D090298&uri=" + CL + "D087255&view=_properties")
    assert r.status_code == 200 and "cmp-diff" in r.get_data(as_text=True)
    assert client.get("/compare?uri=" + CL + "D090298").status_code == 400
    many = "&".join(f"uri={CL}D00000{i}" for i in range(5))
    assert client.get("/compare?" + many).status_code == 400


def test_resource_page_has_compare_button(client):
    r = client.get("/resource?uri=" + CL + "D090298")
    assert "審級を並べて比べる" in r.get_data(as_text=True)


def test_select_column_for_collection_items():
    from kgraphnavi.app import with_select_column, Gadget, Rows
    g = Gadget({"type": "sparql", "src": ""}, {"type": "htable", "columns": [{"id": "entity", "type": "link"}]}, 300)
    rows = Rows([{"entity": U(CL + "D1")}, {"entity": U(CL + "D2")}])
    g2, rows2 = with_select_column(g, rows)
    assert g2.show_method["columns"][0]["type"] == "select" and rows2[0]["_kgselect"]["value"] == CL + "D1"
    html = g2.show(rows2)
    assert '_kgselect' in html and '"select"' in html
    # ?entity の無い表・select: false には足さない
    assert with_select_column(g, Rows([{"x": L("a")}]))[0] is g
    g3 = Gadget({"type": "sparql", "src": ""}, {"type": "htable", "select": False, "columns": [{"id": "entity"}]}, 300)
    assert with_select_column(g3, rows)[0] is g3
