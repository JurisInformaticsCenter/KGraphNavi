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
        if (type === "image") {
            return $("<img>").attr("src", value).attr("width", imageWidth);
        }
        if ((type === "link" || type === "directlink") && cell.href) {
            return $("<a>").attr("href", cell.href).attr("target", "_top").text(value);
        }
        return $("<span>").text(value);
    }
    </script>
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

def make_jsgrid(gridid, data, header, columns, height, paging=True):
    """jsGrid 用の JavaScript 文字列を生成する

    paging: jsGrid 自身のページ送りを使うか（KGraphNavi 側でページ送りする場合は False）
    """

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
    
        return f"""
    {{
        name: "{escape_js(name)}",
        title: "{escape_js(title)}",
        width: {width},
    
        itemTemplate: function(cell) {{
            return kgRenderCell(cell, {width});
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
            make_fieldstr(column)
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

    js = (
        GRIDDATA1
        + DATALIST.format(datalist)
        + f"""
$("#{gridid}").jsGrid({{
"""
        + GRIDDATA22.format(paging="true" if paging else "false")
        + f'height: "{jsgrid_height}",\n'
        + FIELDS.format(fields)
        + "});});"
    )

    logger.debug(
        "make_jsgrid: gridid=%s rows=%d fields=%d",
        gridid,
        len(data),
        len(columns) if columns else len(header),
    )

    return js

def make_table(data, header=None, columns=None, height=None, paging=True):
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
    js = make_jsgrid(
        gridid,
        data,
        header,
        columns,
        height,
        paging=paging,
    )
    return f"""
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
