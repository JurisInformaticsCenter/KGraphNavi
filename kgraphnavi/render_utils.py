#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      render_utils.py
##  Author:
##      Fumihito NISHINO       nisino@nii.ac.jp
##  Description:
##      データを表示用の構造に変換する
"""

import re
import json
import uuid
import logging
import heapq
import random
from html import escape
from collections import defaultdict
from urllib.parse import quote
from urllib.parse import unquote
from flask import render_template # show_chart が使う
from .makehtml import make_table, make_kvtable
from .cytoscape import make_graphjs
logger = logging.getLogger(__name__)

# --------------------------------------------------
# Common utilities
# --------------------------------------------------

def generate_random_rgb():
    """ランダムに色を与える。ただし、白と黒を除く"""
    return (
        random.randint(30, 220),
        random.randint(30, 220),
        random.randint(30, 220),
        0.2
    )

def get_highest_priority_item(items, prioritylist):
    """items の中からprioritylistで指定される一番優先度の高いものを選択する
       例： get_highest_priority_item([1, 3, 5, 7], [3, 5]) -> 3
       """
    # 優先度付きキューを作成
    pq = []

    # アイテムと優先度をキューに追加
    for item in items:
        # 優先度リストでのインデックスを優先度として使用（小さいほど優先度が高い）
        priority = prioritylist.index(item) if item in prioritylist else len(prioritylist)
        heapq.heappush(pq, (priority, item))

    # 最も優先度の高いアイテムを取り出す
    if pq:
        return heapq.heappop(pq)[1]
    return None

# --------------------------------------------------
# Value conversion
# --------------------------------------------------

def get_raw_value(data):
    """SPARQLの値から生のvalueを取り出す。
    data:
        {"type": "uri", "value": "http://example.org/foo"}
    戻り値:
        "http://example.org/foo"
    複数値の場合は、各valueをリストで返す。
    """

    if data is None:
        return ""
    if isinstance(data, list):
        return [
            item.get("value", "")
            for item in data
            if isinstance(item, dict)
        ]
    if isinstance(data, dict):
        return data.get("value", "")
    return str(data)

def get_localname(value):
    """URIから表示用のローカル名を取り出す。"""
    if not value:
        return ""
    value = str(value)
    if "#" in value:
        localname = value.rsplit("#", 1)[1]
    else:
        localname = value.rstrip("/").rsplit("/", 1)[-1]
    return unquote(localname)

def get_value(valdict):
    """SPARQL結果から値だけを取り出す。
    HTMLは生成しない。
    """
    if not valdict:
        return ""
    if isinstance(valdict, list):
        return [
            item.get("value", "")
            for item in valdict
            if isinstance(item, dict)
        ]
    if isinstance(valdict, dict):
        return valdict.get("value", "")
    return valdict

def replace_variables(template, values):
    """文字列中の ?var / ?{var} を取得結果で置換する。"""

    def repl(match):
        var = match.group(1) or match.group(2)
        data = values.get(var)
        return str(get_raw_value(data)) if data is not None else ""

    return re.sub(
        r"\?([a-zA-Z0-9_]+)|\?\{([a-zA-Z0-9_]+)\}",
        repl,
        template,
    )

def make_resource_url(data):
    """RDF URIをKGraphNaviのResourceページへのURLに変換する。"""
    uri = get_raw_value(data)
    if not uri:
        return ""
    return f"/resource?uri={quote(uri, safe='')}"

def make_external_url(data):
    """RDF URIを外部URLとしてそのまま返す。"""
    return get_raw_value(data)


def get_column_href(column, record):
    """columnのhref指定からリンク先を生成する。"""
    href = column.get("href")
    if not href:
        return ""

    if href.startswith("?"):
        var = href[1:]
        return get_raw_value(record.get(var))

    return replace_variables(href, record)

def get_item_data(column, record):
    """1つのcolumnについて表示用セル情報を作成する。"""
    key = column["id"]
    item_type = column.get("type", "literal")
    # 元データ
    data = record.get(key)
    # 表示値
    if "string" in column:
        value = replace_variables(column["string"], record)
    elif item_type == "image":
        value = get_raw_value(data)
    else:
        value = get_value(data)
    # displayによる変換
    if column.get("display") == "localname":
        if isinstance(value, list):
            value = [get_localname(v) for v in value]
        else:
            value = get_localname(value)
    cell = {
        "value": value,
        "type": item_type,
    }
    # リンク（設定の href があればそれを優先する）
    if column.get("href"):
        cell["href"] = get_column_href(column, record)
    elif item_type == "link":
        cell["href"] = make_resource_url(data)
    elif item_type == "directlink":
        cell["href"] = make_external_url(data)
    return key, cell

def get_record_cells(record, columns=None):
    """1レコードを表示用セル情報の辞書に変換する。"""

    if columns is None:
        columns = [{"id": key} for key in record.keys()]
    cells = {}
    for column in columns:
        key, cell = get_item_data(column, record)
        cells[key] = cell
    return cells

# --------------------------------------------------
# Table rendering
# --------------------------------------------------

def show_vertical_table(pairs, columns=None, height=None, attribute_width=None, value_width=None,):
    """SPARQL結果の1レコードを縦型テーブルとして表示する。
    pairsはSPARQL結果のレコード(dict)のリスト。
    columnsは表示する属性と表示形式を指定する。
    attribute_width: 属性列の幅。
    value_width: 属性値列の幅。
    """

    if not pairs:
        return ""
    record = pairs[0]
    # get_item_data() を使って、表示用セルを作る
    cells = get_record_cells(record, columns)
    # columns が指定されていなければ、recordのキーから自動生成
    display_columns = columns or [{"id": key} for key in cells]
    data = []
    for column in display_columns:
        key = column["id"]
        cell = cells.get(key)
        if cell is None:
            continue
        data.append({
            "attribute": {
                "value": column.get("label", key),
                "type": "literal",
            },
            "value": cell,
        })
    logger.debug(
        "show_vertical_table: data=%r",
        data,
    )
    # vtable専用の2列定義
    kv_columns =  [
            {"id": "attribute", "label": "属性"},
            {"id": "value", "label": "値"},
        ]
    if attribute_width is not None:
        kv_columns[0]["width"] = attribute_width
    if value_width is not None:
        kv_columns[1]["width"] = value_width
    result = make_kvtable(
        data,
        columns=kv_columns,
        height=height,
    )
    return result

def _cell_key(cell):
    return (repr(cell.get("value")), cell.get("type"), cell.get("href"))


def merge_cells(cells_list):
    """同じ列の複数のセルを1つにまとめる。値が1種類ならそのセル、複数なら multi セル。"""
    unique = []
    seen = set()
    for cell in cells_list:
        value = cell.get("value")
        if value is None or value == "":
            continue
        key = _cell_key(cell)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cell)
    if not unique:
        return {"value": "", "type": "literal"}
    if len(unique) == 1:
        return unique[0]
    return {"value": unique, "type": "multi"}


def group_rows(data, group_by, columns=None):
    """group_by の変数の値が同じ行を1行にまとめ、表示用セルの辞書のリストを返す。

    例えば「山×国」の組み合わせごとに返る SPARQL の結果を、山ごとに1行にし、
    国の列には複数の国を並べる。行の順序は、各グループが最初に現れた順。
    """
    groups = {}
    for record in data:
        binding = record.get(group_by)
        key = get_raw_value(binding) if binding is not None else id(record)
        groups.setdefault(key, []).append(get_record_cells(record, columns))
    rows = []
    for cells_list in groups.values():
        keys = []
        for cells in cells_list:
            for key in cells:
                if key not in keys:
                    keys.append(key)
        rows.append({
            key: merge_cells([cells[key] for cells in cells_list if key in cells])
            for key in keys
        })
    return rows


def show_horizontal_table(data, columns=None, height=None, group_by=None, paging=True):
    """SPARQL結果を横型テーブルとして表示する。

    group_by: この変数の値が同じ行を1行にまとめる（例: entity）
    paging:   表のライブラリ（jsGrid）のページ送りを使うか
    """

    logger.debug(
        "show_horizontal_table: rows=%d columns=%r",
        len(data) if data else 0,
        columns,
    )
    if columns:
        header = [column["id"] for column in columns]
    elif data:
        header = list(data[0].keys())
    else:
        header = []
    if group_by:
        rows = group_rows(data, group_by, columns)
    else:
        rows = [get_record_cells(record, columns) for record in data]
    return make_table(
        rows,
        header=header,
        columns=columns,
        height=height,
        paging=paging,
    )

def show_retrieval_result(data, columns=None):
    return show_horizontal_table(data, columns)

# --------------------------------------------------
# Facet rendering
# --------------------------------------------------

def facet_value(value):
    """SPARQL結果の値をfacet用の文字列に変換する。"""
    if isinstance(value, dict):
        return value.get("value", "")
    return value

def show_facet(rows, config, height=None):
    """ファセット候補をチェックボックスとして表示する。

    rows:
        Collection.get_facets() が返すファセット候補。
        例:
            [
                {
                    "value": "http://example.org/Japan",
                    "label": "Japan",
                    "count": 20,
                },
                ...
            ]

    config:
        show.facet の設定。

    height:
        Gadgetの表示高さ。指定された場合はCSSに反映する。
    """

    facet_name = config.get("name", "facet")

    html = []

    html.append(
        f'<div class="facet" data-facet-name="{escape(str(facet_name))}">'
    )

    for row in rows:
        value = row.get("value", "")
        label = row.get("label", value)
        count = row.get("count", 0)

        value = str(value)
        label = str(label)

        html.append(
            '<label class="facet-item">'
            f'<input type="checkbox" '
            f'name="{escape(facet_name)}" '
            f'value="{escape(value)}">'
            f'<span class="facet-label">{escape(label)}</span>'
            f'<span class="facet-count">({escape(str(count))})</span>'
            '</label>'
        )

    html.append(
        '<button type="button" class="facet-apply">'
        '適用'
        '</button>'
    )

    html.append("</div>")

    return "\n".join(html)
    
# --------------------------------------------------
# Chart rendering
# --------------------------------------------------
def show_chart(pairs, show_method):
    """棒グラフ/円グラフの描画（Chart.js）

    ページに複数のグラフがあっても衝突しないよう、グラフごとに固有の canvas を使う。
    Chart.js はページの先頭で読み込む（makehtml の LIBRARIES["chartjs"]）。
    """
    if not pairs:
        return ""
    chart_type = show_method.get("chart", "bar")
    labels = show_method["labels"]
    dataset = show_method["dataset"]
    data = {
        "labels": [get_localname(val[labels]["value"]) if show_method.get("display") == "localname"
                   else val[labels]["value"] for val in pairs if labels in val],
        "datasets": [{
            "label": show_method.get("label", dataset),
            "data": [val[dataset]["value"] for val in pairs if labels in val],
            "backgroundColor": "rgba(42, 120, 214, 0.75)",
            "borderWidth": 0,
        }],
    }
    if chart_type == "pie":
        data["datasets"][0]["backgroundColor"] = [
            f"rgba{generate_random_rgb()}" for _ in data["labels"]
        ]
    chart_id = f"chart_{uuid.uuid4().hex[:8]}"
    config = {
        "type": chart_type,
        "data": data,
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": chart_type == "pie", "position": "right"}},
        },
    }
    height = int(show_method.get("height", 320))
    return (
        f'<div class="chart" style="position:relative;height:{height}px;max-width:900px">'
        f'<canvas id="{chart_id}"></canvas></div>\n'
        "<script>\n"
        "window.addEventListener('load', function () {\n"
        f"  new Chart(document.getElementById('{chart_id}'), {json.dumps(config, ensure_ascii=False)});\n"
        "});\n"
        "</script>"
    )

# --------------------------------------------------
# Network rendering
# --------------------------------------------------

def show_network(data, show_method, jsname):
    def split_strip(delim, s0):
        return [s.strip() for s in s0.split(delim)]

    def get_edge(record, from_node, to_node):
        if (from_node in record) and (to_node in record):
            return [record[from_node]['value'], record[to_node]['value']]
        return []
    def get_all_edges(record, edge_schema):
        edges = []
        for from_node, to_node in edge_schema:
            if pair := get_edge(record, from_node, to_node):
                edges.append(pair)
        return edges

    edge_schema = [split_strip(',', pair_str) for pair_str in show_method['edge']]
    all_edges = []
    for record in data:
        edges = get_all_edges(record, edge_schema)
        all_edges += edges
    nodedict = defaultdict(lambda: set())
    for record in data:
        for key in record.keys():
            nodedict[key].add(record[key]['value'])
    make_graphjs(jsname, all_edges, nodedict)
    return f'<div id="cy"></div> <script src="./{jsname}"></script>'

def pairs2adjacent(json, keyname, targetname, direction=None):
    """jsonのkeyからtargetへの集合のdictを作成する"""
    adj_dict = defaultdict(list)
    for row in json:
        fromnode = row[keyname]
        tonode = row[targetname]
        adj_dict[fromnode].append(tonode)
        if direction is None:
            adj_dict[tonode].append(fromnode)
    return adj_dict

def concatenated_graph(seed_node, adj_dict):
    """seed からedgesでたどり着けるグラフ"""
    processed = []
    queue = [seed_node, ]
    while queue:
        seed_node = queue.pop()
        new_nodes = adj_dict[seed_node]
        processed.append(seed_node)
        for seednode in new_nodes:
            if seednode in processed:
                pass
            else:
                queue.append(seednode)
    return processed

def show_adjacentnetwork(data, jsname):
    target, adj_dict = data
    all_nodes = concatenated_graph(target, adj_dict)
    all_edges = []
    for node in all_nodes:
        for to_node in adj_dict[node]:
            all_edges.append((node, to_node))
    make_graphjs(jsname, all_edges, {'node': all_nodes, 'start': [target,]}, edge_styles='triangle')
    return f'<div id="cy"></div> <script src="./{jsname}"></script>'
