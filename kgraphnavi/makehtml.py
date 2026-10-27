#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      makehtml.py
##  Description:
##      HTML/JavaScriptを生成する
"""
import re
import logging
import json
import uuid
from flask import render_template
from .misc import hash_color
logger = logging.getLogger(__name__)

JSGRID = """    <link type="text/css" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jsgrid/1.5.3/jsgrid.min.css" />
    <link type="text/css" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jsgrid/1.5.3/jsgrid-theme.min.css" />
    <link type="text/css" rel="stylesheet" href="/templates/css/default.css" />
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/jsgrid/1.5.3/jsgrid.min.js"></script>
    <script>
    // 表のセル {value, type, href} を描画する。type が multi のときは value が複数のセル
    function kgRenderCell(cell, imageWidth) {
        if (cell === null || cell === undefined) {
            return "";
        }
        if (typeof cell !== "object") {
            return $("<span>").text(cell);
        }
        var value = cell.value;
        var type = cell.type || "literal";
        if (type === "multi") {
            var box = $("<span>").addClass("kg-multi");
            (value || []).forEach(function (item, index) {
                if (index > 0) {
                    box.append(item.type === "image" ? " " : ", ");
                }
                box.append(kgRenderCell(item, imageWidth));
            });
            return box;
        }
        if (value === null || value === undefined || value === "") {
            return "";
        }
        if (type === "select") {
            // コレクションの要素を選ぶ（選んだものを /compare で並べて比べる。2026.10.26）
            return $("<input>").attr("type", "checkbox").addClass("kg-select").attr("value", value)
                     .attr("title", "選んで比べる").prop("checked", kgSelGet().indexOf(value) >= 0)
                     .on("change", function () { kgSelToggle(value, this); });
        }
        if (type === "image") {
            return $("<img>").attr("src", value).attr("width", imageWidth);
        }
        if ((type === "link" || type === "directlink") && cell.href) {
            return $("<a>").attr("href", cell.href).attr("target", "_top").text(value);
        }
        return $("<span>").text(value);
    }
    // ---- 選んで比べる（コレクションのページ。選んだものはこのタブの間、ページ送りしても残る。2026.10.26）----
    var kgSelMemory = [];
    function kgSelGet() {
        try { var v = JSON.parse(window.sessionStorage.getItem("kgCompareSel") || "[]"); return Array.isArray(v) ? v : []; }
        catch (e) { return kgSelMemory.slice(); }
    }
    function kgSelSet(list) {
        kgSelMemory = list.slice();
        try { window.sessionStorage.setItem("kgCompareSel", JSON.stringify(list)); } catch (e) {}
        kgSelBar();
    }
    function kgSelToggle(value, box) {
        var list = kgSelGet(), i = list.indexOf(value);
        var bar = document.getElementById("kg-compare-bar");
        var max = bar ? parseInt(bar.getAttribute("data-max") || "4", 10) : 4;
        if (box.checked && i < 0) {
            if (list.length >= max) { box.checked = false; kgSelBar("比べられるのは " + max + " 件までです"); return; }
            list.push(value);
        } else if (!box.checked && i >= 0) {
            list.splice(i, 1);
        }
        kgSelSet(list);
    }
    function kgSelBar(message) {
        var bar = document.getElementById("kg-compare-bar");
        if (!bar) { return; }
        var list = kgSelGet();
        var q = list.map(function (u) { return "uri=" + encodeURIComponent(u); }).join("&");
        $(bar).empty().append($("<span>").text("選んだもの " + list.length + " 件"));
        var go = $("<a>").addClass("kg-compare-go").text("並べて比べる");
        if (list.length >= 2) { go.attr("href", "/compare?" + q); } else { go.addClass("disabled").attr("title", "2件以上選んでください"); }
        bar.appendChild(go[0]);
        if (list.length) {
            $(bar).append($("<a>").attr("href", "#").text("選択を解除").on("click", function (e) {
                e.preventDefault(); kgSelSet([]); $("input.kg-select").prop("checked", false);
            }));
        }
        if (message) { $(bar).append($("<span>").addClass("kg-compare-msg").text(message)); }
    }
    window.addEventListener("load", function () { kgSelBar(); });
    // ---- 表の並べ替え・列の中の検索・件数・列幅（2026.10.22）----
    // セル {value, type, href} の比べる値（multi は値をつないだもの）
    function kgCellKey(cell) {
        if (cell === null || cell === undefined) { return ""; }
        if (typeof cell !== "object") { return cell; }
        var v = cell.value;
        if (Array.isArray(v)) { v = v.map(function (x) { return x && typeof x === "object" ? x.value : x; }).join(", "); }
        return (v === null || v === undefined) ? "" : v;
    }
    // 数だけの列は数として、ほかは文字列として（日本語の順で）並べる
    function kgCellSorter(a, b) {
        var x = String(kgCellKey(a)).trim(), y = String(kgCellKey(b)).trim();
        var num = /^-?\\d+(\\.\\d+)?$/;
        if (num.test(x) && num.test(y)) { return parseFloat(x) - parseFloat(y); }
        if (x === "" && y !== "") { return 1; }
        if (y === "" && x !== "") { return -1; }
        return x.localeCompare(y, "ja");
    }
    window.kgGridData = window.kgGridData || {};
    // 件数の表示。絞り込んでいるときは「絞り込み後 / 全体」
    function kgUpdateCount(gridid, shown, total) {
        var box = $("#" + gridid + "_count");
        box.text(shown === total ? total + " 件" : shown + " 件（全 " + total + " 件）");
    }
    // 列の中の検索: 各列の入力欄の文字を含む行だけにする（大文字小文字は区別しない）
    function kgFilterRows(gridid, filter) {
        var rows = window.kgGridData[gridid] || [];
        var keys = Object.keys(filter).filter(function (k) { return filter[k]; });
        var res = rows.filter(function (item) {
            return keys.every(function (k) {
                return String(kgCellKey(item[k])).toLowerCase().indexOf(String(filter[k]).toLowerCase()) >= 0;
            });
        });
        kgUpdateCount(gridid, res.length, rows.length);
        return res;
    }
    function kgFilterTemplate(field) {
        var input = $("<input>").attr("type", "text").attr("placeholder", "検索").addClass("kg-filter")
            .val(field._kgValue || "")
            .on("input", function () {
                field._kgValue = input.val();
                clearTimeout(field._kgTimer);
                field._kgTimer = setTimeout(function () { field._grid.search(); }, 250);
            });
        field._kgInput = input;
        return input;
    }
    // 列幅: 見出しの右端をドラッグして変える
    function kgAddResizers(gridid) {
        var grid = $("#" + gridid), inst = grid.data("JSGrid");
        if (!inst) { return; }
        var fields = inst.fields.filter(function (f) { return f.visible !== false; });
        grid.find(".jsgrid-header-row > th").each(function (i) {
            var th = $(this), field = fields[i];
            if (!field || th.find(".kg-resizer").length) { return; }
            th.css("position", "relative");
            var handle = $("<span>").addClass("kg-resizer").attr("title", "ドラッグで列の幅を変える");
            handle.on("mousedown", function (e) {
                e.preventDefault(); e.stopPropagation();
                var x0 = e.pageX, w0 = field.width;
                $(document).on("mousemove.kgresize", function (ev) {
                    field.width = Math.max(40, w0 + ev.pageX - x0);
                    th.css("width", field.width + "px");
                }).on("mouseup.kgresize", function () {
                    $(document).off(".kgresize");
                    inst.refresh();
                });
            }).on("click", function (e) { e.stopPropagation(); });
            th.append(handle);
        });
    }
    // 階層表示の表（show.tree）。行の _kgtree = {id, depth, anc: 先祖のid, hasChildren}
    window.kgTrees = window.kgTrees || {};
    function kgTreeVisible(tree) {
        return tree.all.filter(function (item) {
            var t = item._kgtree;
            return !t || !t.anc.some(function (a) { return tree.collapsed.has(a); });
        });
    }
    function kgTreeInit(gridid, data, collapsed) {
        var tree = {all: data, collapsed: new Set()};
        if (collapsed) {
            data.forEach(function (item) {
                if (item._kgtree && item._kgtree.hasChildren) { tree.collapsed.add(item._kgtree.id); }
            });
        }
        window.kgTrees[gridid] = tree;
        return kgTreeVisible(tree);
    }
    function kgTreeToggle(gridid, id) {
        var tree = window.kgTrees[gridid];
        if (tree.collapsed.has(id)) { tree.collapsed.delete(id); } else { tree.collapsed.add(id); }
        var grid = $("#" + gridid);
        var pageIndex = grid.jsGrid("option", "pageIndex");
        grid.jsGrid("option", "data", kgTreeVisible(tree));
        grid.jsGrid("openPage", pageIndex);
    }
    function kgRenderTreeCell(cell, item, gridid, imageWidth) {
        var t = item._kgtree || {depth: 0};
        var box = $("<span>").addClass("kg-tree").css("padding-left", (t.depth * 1.2) + "em");
        var toggle = $("<span>").addClass("kg-tree-toggle");
        if (t.hasChildren) {
            var tree = window.kgTrees[gridid];
            toggle.text(tree && tree.collapsed.has(t.id) ? "\u25B8" : "\u25BE")
                  .attr("title", "折りたたむ／広げる")
                  .on("click", function (event) {
                      event.preventDefault();
                      event.stopPropagation();
                      kgTreeToggle(gridid, t.id);
                  });
        }
        box.append(toggle);
        box.append(kgRenderCell(cell, imageWidth));
        return box;
    }
    </script>
    <style>
    .kg-count { font-size: 90%; color: #555; margin: 2px 0 4px; }
    .kg-filter { width: 100%; box-sizing: border-box; }
    .kg-resizer { position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize; }
    .kg-resizer:hover { background: rgba(0, 0, 0, 0.15); }
    .kg-compare-bar { display: inline-flex; gap: 10px; align-items: center; margin-left: 12px; font-size: 92%; }
    .kg-compare-bar a.disabled { color: #999; pointer-events: none; }
    .kg-compare-msg { color: #b00; }
    </style>
"""

CYTOSCAPE = """    <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>
"""

GRIDDATA1 = "window.addEventListener('load', (event) => {"
DATALIST = """
    const datalist = [
    {}
    ];
"""

# 閲覧用の表なので、行の追加・編集はできないようにする
GRIDDATA22 = """
        width: "100%",
        inserting: false,
        editing: false,
        sorting: true,
        paging: {paging},
        pageSize: 20,
        data: datalist,
"""

JSGRID_DEFAULT_HEIGHT = 450
JSGRID_PADDING = 50

FIELDS = 'fields: [ {} ]'
CHARTJS = """    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
"""

LIBRARIES = {
    "jsgrid": JSGRID,
    "cytoscape": CYTOSCAPE,
    "chartjs": CHARTJS,
}

def make_html(content, title="タイトル", navi="", libraries=None, category=None):
    """HTMLを組み立てる"""
    if libraries is None:
        libraries = []
    library_html = "".join(
        LIBRARIES[name]
        for name in libraries
        if name in LIBRARIES
    )
    return render_template(
        "page.html",
        title=title,
        content=content,
        navi=navi,
        libraries=library_html,
        color=hash_color(category) if category else hash_color(title),
    )

def make_jsgrid(gridid, data, header, columns, height, paging=True, tree=None, interactive=False):
    """jsGrid 用の JavaScript 文字列を生成する

    paging: jsGrid 自身のページ送りを使うか（KGraphNavi 側でページ送りする場合は False）
    tree:   階層表示の設定（show.tree）。column の列を字下げし、折りたたみの印を付ける。
            行の順序は親子の順なので、見出しをクリックしての並べ替えはしない
    interactive: 列の中の検索（見出しの下の入力欄）と件数の表示を付ける（2026.10.22。make_table の htable）。
            並べ替え（見出しのクリック）と列幅の変更（見出しの右端のドラッグ）はどの表にも付ける
    """
    tree_column = tree.get("column") if tree else None
    if tree_column and not tree.get("paging"):
        # 階層表示の表はページ送りしない(親子が別のページに分かれ、後ろの法令が2ページ目に隠れていた。024047 の道路交通法。2026.10.19)
        # 行が多いときは折りたたんでおく(collapsed)か、tree.paging: true でページ送りする
        paging = False

    def escape_js(value):
        if value is None:
            return ""
        value = str(value)
        value = value.replace("\\", "\\\\")
        value = value.replace('"', '\\"')
        value = value.replace("\n", "\\n")
        value = value.replace("\r", "")
        return value

    def make_js_value(value):
        """Pythonの値をJavaScriptリテラルに変換する。"""
        if value is None:
            return"null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(value, ensure_ascii=False)

    def make_rowstr(row):
        """1行を JavaScript オブジェクトに変換する"""

        items = []
        for key, cell in row.items():
            if key == "_kgtree":
                # 階層表示の情報（render_utils.arrange_tree）はそのまま渡す
                items.append(f"{make_js_value(key)}: {json.dumps(cell, ensure_ascii=False)}")
                continue
            if isinstance(cell, dict) and "value" in cell:
                value = cell.get("value")
                item_type = cell.get("type", "literal")
                href = cell.get("href")
            else:
                value = cell
                item_type = "literal"
                href = None
            js_value = make_js_value(value)
            cell_js = (
                "{ "
                f"value: {make_js_value(value)}, "
                f"type: {make_js_value(item_type)}"
            )
            if href is not None:
                cell_js += f", href: {make_js_value(href)}"
            cell_js += " }"
            items.append(
                f"{make_js_value(key)}: {cell_js}"
            )

        return "{ " + ", ".join(items) + " }"

    def make_fieldstr(column):
        """jsGrid の field 定義を生成する"""
    
        name = column["id"]
        title = column.get("label", name)
        width = int(column.get("width", 600))
    
        filter_js = ("""
        filtering: true,
        filterTemplate: function() { return kgFilterTemplate(this); },
        filterValue: function() { return this._kgValue || ""; },""" if interactive else """
        filtering: false,""")
        return f"""
    {{
        name: "{escape_js(name)}",
        title: "{escape_js(title)}",
        width: {width},
        sorter: kgCellSorter,{filter_js}
        itemTemplate: function(cell) {{
            return kgRenderCell(cell, {width});
        }}
    }}
    """
    def make_tree_fieldstr(column):
        """階層表示の列の field 定義（字下げと折りたたみの印）"""
        name = column["id"]
        title = column.get("label", name)
        width = int(column.get("width", 600))
        return f"""
    {{
        name: "{escape_js(name)}",
        title: "{escape_js(title)}",
        width: {width},

        itemTemplate: function(cell, item) {{
            return kgRenderTreeCell(cell, item, "{gridid}", {width});
        }}
    }}
    """
    # データ
    datalist = ",\n".join(
        make_rowstr(row)
        for row in data
    )

    # columns は [{id: ..., type: ...}, ...]
    if columns:
        fields = ",\n".join(
            make_tree_fieldstr(column) if column["id"] == tree_column else make_fieldstr(column)
            for column in columns
        )
    else:
        # columns がない場合は header から通常の text 列を作る
        fields = ",\n".join(
            make_fieldstr({"id": name})
            for name in header
        )

    if not paging:
        # ページ送りしない表は、行数に合わせた高さにする
        jsgrid_height = "auto"
    elif height:
        jsgrid_height = f"{height - JSGRID_PADDING}px"
    else:
        jsgrid_height = f"{JSGRID_DEFAULT_HEIGHT}px"

    if interactive and not tree_column:
        # 列の中の検索: データは controller.loadData で返す（data は使わない）
        grid_options = (GRIDDATA22.format(paging="true" if paging else "false").replace("        data: datalist,\n", "")
                        + f'filtering: true,\nautoload: true,\n'
                        + f'controller: {{ loadData: function(filter) {{ return kgFilterRows("{gridid}", filter); }} }},\n')
        store = f'window.kgGridData["{gridid}"] = datalist;\n'
    else:
        grid_options = GRIDDATA22.format(paging="true" if paging else "false")
        store = ''
    js = (
        GRIDDATA1
        + DATALIST.format(datalist)
        + store
        + f"""
$("#{gridid}").jsGrid({{
"""
        + grid_options
        + f'onRefreshed: function() {{ kgAddResizers("{gridid}"); }},\n'
        + (f'sorting: false,\ndata: kgTreeInit("{gridid}", datalist, {"true" if tree.get("collapsed") else "false"}),\n'
           if tree_column else "")
        + f'height: "{jsgrid_height}",\n'
        + FIELDS.format(fields)
        + "});"
        + (f'kgUpdateCount("{gridid}", datalist.length, datalist.length);' if interactive or tree_column else '')
        + "});"
    )

    logger.debug(
        "make_jsgrid: gridid=%s rows=%d fields=%d",
        gridid,
        len(data),
        len(columns) if columns else len(header),
    )

    return js

def make_table(data, header=None, columns=None, height=None, paging=True, tree=None):
    "jsGridのtableを作成し、<div> と <script> を返す"
    logger.debug(
        "make_table: header=%r columns=%r",
        header, columns
)
    if not data:
        return ""
    if header:
        header = list(header)
    else:
        header = list(data[0].keys())
    gridid = f"jsGrid_{uuid.uuid4().hex[:8]}"
    # 列の中の検索と件数は、表の中でページ送りする表だけ（KGraphNavi 側でページ送りする表は、そのページの行しか持たないので付けない）
    interactive = bool(paging)
    js = make_jsgrid(
        gridid,
        data,
        header,
        columns,
        height,
        paging=paging,
        tree=tree,
        interactive=interactive,
    )
    count = f'<div class="kg-count" id="{gridid}_count"></div>' if (interactive or tree) else ''
    return f"""
    {count}
    <div id="{gridid}"></div>
    <script>
    {js}
    </script>
    """


def make_kvtable(data, columns=None, height=None):
    """属性名・属性値の縦型テーブルを作成する。"""
    if not data:
        return ""
    header = ['attribute', 'value']
    columns_kv = [
        {"id": "attribute", "label": "属性"},
        {"id": "value", "label": "値"},
    ]
    if columns:
        for column in columns:
            column_id = column.get("id")
            if column_id == "attribute":
                columns_kv[0].update(column)
            elif column_id == "value":
                columns_kv[1].update(column)
    gridid = f"jsGrid_{uuid.uuid4().hex[:8]}"
    js = make_jsgrid(
        gridid,
        data,
        header,
        columns_kv,
        height
    )
    return f"""
    <div id="{gridid}"></div>
    <script>
    {js}
    </script>
    """
