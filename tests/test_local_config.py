#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ローカル設定の読み込み: <設定ファイル名>.local.yaml を local.yaml より先に使う（2026.10.27）"""

from kgraphnavi import app as app_module

BASE = """
-   title: base
-   def: page
    name: P
    type: http://example.org/C
    gadget: [G]
-   def: gadget
    name: G
    get: {type: sparql, src: "SELECT ?s WHERE { ?s ?p ?o }"}
    show: {type: htable}
"""


def loaded_title(tmp_path, monkeypatch):
    seen = {}

    def fake_setconfig(items, base_dir=None):
        seen["title"] = [i["title"] for i in items if isinstance(i, dict) and "title" in i][-1]
        return seen

    monkeypatch.setattr(app_module, "setconfig", fake_setconfig)
    app_module.load_config(str(tmp_path / "kg.yaml"))
    return seen["title"]


def test_config_specific_local_file_wins(tmp_path, monkeypatch):
    (tmp_path / "kg.yaml").write_text(BASE, encoding="utf-8")
    assert loaded_title(tmp_path, monkeypatch) == "base"
    (tmp_path / "local.yaml").write_text("- title: common\n", encoding="utf-8")
    assert loaded_title(tmp_path, monkeypatch) == "common"
    (tmp_path / "kg.local.yaml").write_text("- title: specific\n", encoding="utf-8")
    assert loaded_title(tmp_path, monkeypatch) == "specific"
