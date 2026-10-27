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
import unicodedata
from html import escape
from collections import defaultdict
from urllib.parse import quote, urlencode
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

def make_collection_url(config, record, default_var):
    """値を持つコレクションへのURL（/collection?class=...&f.<facet>=<値>）を返す。

    config: {"class": クラス, "facet": ファセット名, "value": 値の変数名（省略時はその列）}
    値がなければ空文字列。
    """
    if not isinstance(config, dict) or not config.get("facet"):
        return ""
    value = get_raw_value(record.get(config.get("value") or default_var))
    if value is None or value == "":
        return ""
    query = []
    if config.get("class"):
        query.append(("class", config["class"]))
    if config.get("view"):
        query.append(("view", config["view"]))
    query.append((f"f.{config['facet']}", str(value)))
    return "/collection?" + urlencode(query)


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
    # collection: {class, facet, value} は、その値を持つコレクションへのリンクにする
    #   （例: 事件区分 → その事件区分の裁判のコレクション）
    # link: <変数名> は、その変数のリソースのページへのリンクにする（例: 事件名 → 判例）
    if column.get("collection"):
        href = make_collection_url(column["collection"], record, key)
        if href:
            cell["type"] = "link"
            cell["href"] = href
    elif column.get("link"):
        target = record.get(column["link"])
        if target is not None:
            cell["type"] = "link"
            cell["href"] = make_resource_url(target)
    elif column.get("href"):
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


def natural_key(text):
    """数字の部分を数の大小で比べる並べ替えのキー（例: 90条 < 570条 < 570条の2、全角数字も）。"""
    text = unicodedata.normalize("NFKC", str(text or ""))
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", text)
        if part
    ]


def _cell_text(cell):
    """セルの表示文字列（複数値のセルはつなげる）。"""
    if not isinstance(cell, dict):
        return "" if cell is None else str(cell)
    value = cell.get("value")
    if isinstance(value, list):
        return "、".join(_cell_text(item) if isinstance(item, dict) else str(item) for item in value)
    return "" if value is None else str(value)


def arrange_tree(rows, records, tree):
    """行を親子の順（深さ優先）に並べ、各行に階層表示の情報 _kgtree を付ける。

    rows:    表示用セルの辞書のリスト
    records: rows と同じ順の SPARQL の結果（行の識別子・親を取り出す）
    tree:    show.tree の設定
        node:          行の識別子の変数（例: legislation）
        parent:        親の識別子の変数（どちらか一方）
        parent_regex:  識別子からこの正規表現に合う末尾を取り除いたものを親とする。
                       その識別子の行がなければ、さらに取り除いて、ある行まで遡る
                       （例: "_[^_/]*$" で …_570_1 → …_570 → 法令）
        column:        字下げ・折りたたみをする列（例: label）
        sort:          同じ親の子を並べる列（省略時は column）。数字は数の大小で比べる
        strip_parent:  column の値が親の値で始まるとき、その部分を省く（既定 true）
        collapsed:     最初から子を折りたたんでおくか（既定 false）
        same_as_parent: 列のリスト。親と同じ値なら子の行では空にする
                       （例: 条の見出し・解説を、項・号の行では繰り返さない）
        parent_by:     contains なら、column の値を部分に含む行のうち最も長いものを親とする
                       （例: 「マンション」>「マンション建設」>「マンション建設工事」。node・parent は不要）
        parent_min_length: parent_by: contains で親にする値の最短の長さ（既定 2）
        order:         size なら、子孫の多い行を先に並べる（同じ数なら sort の列の順）
    親の行がない行は最上位に置く。
    """
    node_var = tree.get("node")
    parent_var = tree.get("parent")
    parent_regex = tree.get("parent_regex")
    column = tree.get("column")
    sort_column = tree.get("sort") or column
    strip_parent = tree.get("strip_parent", True)
    same_as_parent = tree.get("same_as_parent") or []
    if isinstance(same_as_parent, str):
        same_as_parent = [same_as_parent]

    ids = [str(get_raw_value(record.get(node_var))) if node_var else str(i)
           for i, record in enumerate(records)]
    index = {}
    for i, node_id in enumerate(ids):
        if node_id and node_id not in index:
            index[node_id] = i

    def find_parent(i):
        if parent_var:
            parent_id = get_raw_value(records[i].get(parent_var))
            if parent_id and parent_id != ids[i]:
                return index.get(str(parent_id))
            return None
        if parent_regex:
            current = ids[i]
            while True:
                upper = re.sub(parent_regex, "", current, count=1)
                if not upper or upper == current:
                    return None
                if upper in index and index[upper] != i:
                    return index[upper]
                current = upper
        return None

    if tree.get("parent_by") == "contains":
        # 同じ値の行は最初の行だけを親の候補にする
        min_length = int(tree.get("parent_min_length", 2))
        texts = [_cell_text(row.get(column)) for row in rows]
        candidates = {}
        for i, text in enumerate(texts):
            if len(text) >= min_length and text not in candidates:
                candidates[text] = i
        by_length = sorted(candidates.items(), key=lambda item: -len(item[0]))

        def find_parent(i):  # noqa: F811
            text = texts[i]
            for candidate, j in by_length:
                if len(candidate) < len(text) and candidate in text:
                    return j
            return None
        ids = [str(i) for i in range(len(rows))]
        index = {node_id: i for i, node_id in enumerate(ids)}

    parents = [find_parent(i) for i in range(len(rows))]
    children = defaultdict(list)
    roots = []
    for i, parent in enumerate(parents):
        if parent is None or index.get(ids[i]) != i:
            roots.append(i)
        else:
            children[parent].append(i)

    sizes = {}

    def subtree_size(i):
        if i not in sizes:
            sizes[i] = 0  # 循環しても止まるように
            sizes[i] = sum(1 + subtree_size(k) for k in children.get(i, []))
        return sizes[i]

    if tree.get("order") == "size":
        def sort_key(i):
            return (-subtree_size(i), natural_key(_cell_text(rows[i].get(sort_column))))
    else:
        def sort_key(i):
            return natural_key(_cell_text(rows[i].get(sort_column)))

    result = []
    visited = set()

    def walk(i, depth, ancestors):
        if i in visited:
            return
        visited.add(i)
        row = dict(rows[i])
        kids = sorted(children.get(i, []), key=sort_key)
        parent = ancestors[-1] if ancestors else None
        if strip_parent and parent is not None and isinstance(row.get(column), dict):
            text = _cell_text(rows[i].get(column))
            parent_text = _cell_text(rows[parent].get(column))
            if parent_text and len(text) > len(parent_text) and text.startswith(parent_text):
                cell = dict(row[column])
                cell["value"] = text[len(parent_text):].lstrip()
                row[column] = cell
        if parent is not None:
            for key in same_as_parent:
                cell, parent_cell = rows[i].get(key), rows[parent].get(key)
                if (isinstance(cell, dict) and isinstance(parent_cell, dict)
                        and _cell_text(cell) == _cell_text(parent_cell)
                        and cell.get("href") == parent_cell.get("href")):
                    row[key] = {"value": "", "type": "literal"}
        row["_kgtree"] = {
            "id": i,
            "depth": depth,
            "anc": list(ancestors),
            "hasChildren": bool(kids),
        }
        result.append(row)
        for kid in kids:
            walk(kid, depth + 1, ancestors + [i])

    for root in sorted(roots, key=sort_key):
        walk(root, 0, [])
    # 親子が循環しているなど、たどれなかった行
    for i in range(len(rows)):
        if i not in visited:
            walk(i, 0, [])
    return result


def show_horizontal_table(data, columns=None, height=None, group_by=None, paging=True, tree=None):
    """SPARQL結果を横型テーブルとして表示する。

    group_by: この変数の値が同じ行を1行にまとめる（例: entity）
    paging:   表のライブラリ（jsGrid）のページ送りを使うか
    tree:     親子の階層で表示する（arrange_tree を参照）
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
    if tree and rows:
        if group_by:
            # group_rows と同じ順（各グループが最初に現れた順）の代表のレコード
            first = {}
            for record in data:
                binding = record.get(group_by)
                key = get_raw_value(binding) if binding is not None else id(record)
                first.setdefault(key, record)
            records = list(first.values())
        else:
            records = list(data)
        rows = arrange_tree(rows, records, tree)
    return make_table(
        rows,
        header=header,
        columns=columns,
        height=height,
        paging=paging,
        tree=tree if (tree and rows) else None,
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
