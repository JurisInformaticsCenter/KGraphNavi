"""階層表示の表（show.tree）のテスト"""
from kgraphnavi.render_utils import arrange_tree, natural_key, get_record_cells, show_horizontal_table

LAW = "http://lod4all.net/law/resource/"


def rec(node, label):
    return {"legislation": {"type": "uri", "value": LAW + node},
            "label": {"type": "literal", "value": label}}


COLUMNS = [{"id": "label", "type": "literal", "link": "legislation"}]
TREE = {"node": "legislation", "parent_regex": "_[^_/]*$", "column": "label"}


def labels(rows):
    return [("  " * r["_kgtree"]["depth"]) + r["label"]["value"] for r in rows]


def test_natural_key():
    names = ["民法570条", "民法90条", "民法570条の2", "民法", "民法１００条"]
    assert sorted(names, key=natural_key) == ["民法", "民法90条", "民法１００条", "民法570条", "民法570条の2"]


def test_arrange_tree_law_article_clause():
    records = [
        rec("129AC0000000089", "民法"),
        rec("129AC0000000089_570", "民法570条"),
        rec("129AC0000000089_570_1", "民法570条第1項"),
        rec("129AC0000000089_90", "民法90条"),
        rec("132AC0000000048_526_1", "商法526条第1項"),   # 法令・条の行がない
        rec("132AC0000000048", "商法"),
    ]
    rows = [get_record_cells(r, COLUMNS) for r in records]
    out = arrange_tree(rows, records, TREE)
    assert labels(out) == ["商法", "  526条第1項", "民法", "  90条", "  570条", "    第1項"]
    clause = out[-1]
    assert clause["_kgtree"]["anc"] == [0, 1]
    assert clause["label"]["href"].endswith("129AC0000000089_570_1")
    assert out[2]["_kgtree"]["hasChildren"] and not out[3]["_kgtree"]["hasChildren"]


def test_show_horizontal_table_tree_js():
    records = [rec("129AC0000000089_570", "民法570条"), rec("129AC0000000089", "民法")]
    html = show_horizontal_table(records, COLUMNS, tree=TREE)
    assert "kgTreeInit(" in html and "kgRenderTreeCell(" in html and "sorting: false" in html
    assert '"_kgtree": {"id": 1, "depth": 0' in html


def test_same_as_parent_blanks_repeated_values():
    columns = COLUMNS + [{"id": "caption", "type": "literal"}]
    records = [rec("L", "民法"), rec("L_570", "民法570条"), rec("L_570_1", "民法570条第1項"), rec("L_570_2", "民法570条第2項")]
    for r, cap in zip(records, [None, "売主の瑕疵担保責任", "売主の瑕疵担保責任", "別の見出し"]):
        if cap:
            r["caption"] = {"type": "literal", "value": cap}
    rows = [get_record_cells(r, columns) for r in records]
    out = arrange_tree(rows, records, dict(TREE, same_as_parent=["caption"]))
    assert [r["caption"]["value"] for r in out] == ["", "売主の瑕疵担保責任", "", "別の見出し"]


def test_parent_by_contains():
    words = ["工事", "マンション", "マンション建設", "マンション建設工事", "土壌", "土壌汚染", "汚染土壌", "瑕疵"]
    records = [{"term": {"type": "uri", "value": "http://x/" + w}} for w in words]
    columns = [{"id": "term", "type": "link", "display": "localname"}]
    rows = [get_record_cells(r, columns) for r in records]
    tree = {"column": "term", "parent_by": "contains", "strip_parent": False, "order": "size"}
    out = arrange_tree(rows, records, tree)
    assert [("  " * r["_kgtree"]["depth"]) + r["term"]["value"] for r in out] == [
        "マンション", "  マンション建設", "    マンション建設工事",
        "土壌", "  土壌汚染", "  汚染土壌",
        "工事", "瑕疵",
    ]


def test_tree_table_has_no_paging():
    """階層表示の表はページ送りしない(後ろの法令が2ページ目に隠れていた。2026.10.19)"""
    records = [rec("129AC0000000089_570", "民法570条"), rec("129AC0000000089", "民法")]
    html = show_horizontal_table(records, COLUMNS, tree=TREE)
    assert "paging: false" in html and 'height: "auto"' in html
    html = show_horizontal_table(records, COLUMNS, tree=dict(TREE, paging=True))
    assert "paging: true" in html
