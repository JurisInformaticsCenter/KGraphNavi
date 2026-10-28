#!/usr/bin/env python
# -*- coding: utf-8 -*-
##
##      graph.py
##
##      ネットワーク図（show: type: graph）
##      ガジェットの SPARQL の結果の行を辺として読み、ノードと辺のグラフを作って Cytoscape.js で描く。
##      2026.10.28
##
"""ネットワーク図

設定（show）の例::

    show:
      type: graph
      edges:
        - {from: entity, to: cited}            # 変数 entity の値から cited の値への辺（directed: false で向きなし）
      nodes:
        entity: {label: label, kind: 判例, x: year}
        cited:  {label: citedlabel, kind: 判例, x: citedyear, in_collection: check}
      outside: hide       # コレクション外のノード: hide（既定）/ show（灰色で出す）。画面で切り替えられる
      layout: timeline    # timeline（x の値で横に並べる）/ force / circle / grid
      max_nodes: 500      # これを超えたら次数の大きいものから残す
      size: indegree      # ノードの大きさ: indegree / outdegree / degree / none
      height: 600

nodes の in_collection:
    true   … いつもコレクションの要素（変数 entity は既定で true）
    check  … コレクションの要素かどうかを問い合わせて調べる（参照先の判例など）
    false  … コレクションの要素ではない（法令の条など。outside の対象にしない。entity 以外の既定）
"""
import json
import re
import uuid
from html import escape
from urllib.parse import quote

from .errors import ConfigError
from .facets import make_url
from .render_utils import get_localname
from .terms import iri_term

# 画面でコレクション外のノードの表示を切り替える URL パラメータ
OUTSIDE_PARAM = "graph.outside"
OUTSIDE_MODES = ("hide", "show")
LAYOUTS = ("timeline", "force", "circle", "grid")
SIZE_MODES = ("indegree", "outdegree", "degree", "none")
DEFAULT_MAX_NODES = 500
# 名前を常に出すノードの数（大きい順）。他はマウスを乗せる・選ぶと出す
LABELLED_NODES = 30
# コレクションの要素かを調べる問い合わせ1回あたりの URI の数
MEMBERSHIP_BATCH = 300

SHOW_KEYS = {"type", "edges", "nodes", "outside", "layout", "max_nodes", "size", "height", "isolated"}
EDGE_KEYS = {"from", "to", "directed", "label"}
NODE_KEYS = {"label", "kind", "x", "in_collection", "link"}


# --------------------------------------------------
# 設定
# --------------------------------------------------

def validate_graph_show(name, show):
    """show: type: graph の設定を検証する（setconfig から呼ぶ）。"""
    unknown = set(show) - SHOW_KEYS
    if unknown:
        raise ConfigError(f"gadget({name})のshow(graph)に未知のキー: {sorted(unknown)}")
    edges = show.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ConfigError(f"gadget({name})のshow(graph)には edges（[{{from:, to:}}] のリスト）が必要です")
    for edge in edges:
        if not isinstance(edge, dict) or not edge.get("from") or not edge.get("to"):
            raise ConfigError(f"gadget({name})のshow(graph)の edges の各項目には from と to が必要です: {edge!r}")
        unknown = set(edge) - EDGE_KEYS
        if unknown:
            raise ConfigError(f"gadget({name})のshow(graph)の edges に未知のキー: {sorted(unknown)}")
    nodes = show.get("nodes") or {}
    if not isinstance(nodes, dict):
        raise ConfigError(f"gadget({name})のshow(graph)の nodes は変数名をキーとする辞書です")
    for var, node in nodes.items():
        if not isinstance(node, dict):
            raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var} は辞書です")
        unknown = set(node) - NODE_KEYS
        if unknown:
            raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var} に未知のキー: {sorted(unknown)}")
        if node.get("in_collection", None) not in (None, True, False, "check"):
            raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var}.in_collection は true / false / check です")
    for key, choices in (("outside", OUTSIDE_MODES), ("layout", LAYOUTS), ("size", SIZE_MODES),
                         ("isolated", OUTSIDE_MODES)):
        if key in show and show[key] not in choices:
            raise ConfigError(f"gadget({name})のshow(graph)の {key} は {' / '.join(choices)} のいずれかです")
    for key in ("max_nodes", "height"):
        if key in show:
            try:
                if int(show[key]) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as e:
                raise ConfigError(f"gadget({name})のshow(graph)の {key} は正の整数です") from e


def node_settings(show):
    """変数ごとのノードの設定（edges に出てくる変数すべて）"""
    nodes = dict(show.get("nodes") or {})
    settings = {}
    for edge in show.get("edges") or []:
        for var in (edge["from"], edge["to"]):
            if var not in settings:
                conf = dict(nodes.get(var) or {})
                conf.setdefault("kind", var)
                conf.setdefault("in_collection", var == "entity")
                settings[var] = conf
    return settings


def outside_mode(show, params):
    """コレクション外のノードの扱い（URL の graph.outside が設定より優先）"""
    mode = (params or {}).get(OUTSIDE_PARAM)
    if mode in OUTSIDE_MODES:
        return mode
    return show.get("outside", "hide")


def to_number(value):
    """x 軸の値を数にする。日付などは先頭の数（年）を使う。数にできなければ None"""
    if value is None:
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = re.match(r"^-?\d+", text)
    return float(match.group(0)) if match else None


# --------------------------------------------------
# グラフを作る
# --------------------------------------------------

def collect_graph(rows, show):
    """SPARQL の結果の行から、ノードと辺を集める。

    返り値: (nodes, edges)
      nodes: {id: {"id", "label", "kind", "x", "uri", "in_collection"(True/False/"check")}}
      edges: {(source, target): {"source", "target", "directed", "label", "weight"}}
    """
    settings = node_settings(show)
    nodes = {}
    edges = {}

    def add_node(row, var):
        cell = row.get(var)
        if not cell or cell.get("value") in (None, ""):
            return None
        node_id = str(cell["value"])
        conf = settings[var]
        label_cell = row.get(conf.get("label")) if conf.get("label") else None
        label = (label_cell or {}).get("value") or ""
        x_cell = row.get(conf.get("x")) if conf.get("x") else None
        x = to_number((x_cell or {}).get("value"))
        node = nodes.get(node_id)
        if node is None:
            node = nodes[node_id] = {
                "id": node_id,
                "label": label,
                "kind": str(conf["kind"]),
                "x": x,
                "uri": node_id if cell.get("type") == "uri" else None,
                "in_collection": conf["in_collection"],
            }
        else:
            if not node["label"] and label:
                node["label"] = label
            if node["x"] is None and x is not None:
                node["x"] = x
            # コレクションの要素と分かっている方を優先する
            if conf["in_collection"] is True or node["in_collection"] is True:
                node["in_collection"] = True
            elif conf["in_collection"] == "check":
                node["in_collection"] = "check"
        return node_id

    for row in rows or []:
        for spec in show.get("edges") or []:
            source = add_node(row, spec["from"])
            target = add_node(row, spec["to"])
            if source is None or target is None or source == target:
                continue
            directed = spec.get("directed", True) is not False
            key = (source, target) if directed else tuple(sorted((source, target)))
            edge = edges.get(key)
            if edge is None:
                label_cell = row.get(spec.get("label")) if spec.get("label") else None
                edges[key] = {
                    "source": key[0], "target": key[1], "directed": directed,
                    "label": (label_cell or {}).get("value") or "", "weight": 1,
                }
            else:
                edge["weight"] += 1
    for node in nodes.values():
        if not node["label"]:
            node["label"] = get_localname(node["id"]) if node["uri"] else node["id"]
    return nodes, edges


def membership_query(subquery, uris):
    """uris のうちコレクションの要素であるものを求める SELECT

    ファセットの絞り込みと同じ FILTER(?uri IN (...)) で限る。
    URI を多く並べて長くなるので、SPARQL クライアントは POST で送る（sparql.POST_THRESHOLD）。
    """
    values = ", ".join(iri_term(u) for u in uris)
    return (
        "SELECT DISTINCT ?uri\n"
        "WHERE {\n"
        f"{subquery}\n"
        f"    FILTER(?uri IN ({values}))\n"
        "}"
    )


def collection_members(collection, uris):
    """uris のうち、コレクションの要素であるものの集合"""
    uris = sorted(set(uris))
    members = set()
    if collection is None or not uris:
        return members
    subquery = collection.to_subquery("?uri")
    for i in range(0, len(uris), MEMBERSHIP_BATCH):
        query = membership_query(subquery, uris[i:i + MEMBERSHIP_BATCH])
        for row in collection._run(query):
            if "uri" in row:
                members.add(row["uri"]["value"])
    return members


def build_graph(rows, show, *, collection=None, params=None, members=None):
    """表示するグラフ（ノード・辺・件数・注意）を作る。

    members: コレクションの要素の集合（テスト用。省略時はコレクションに問い合わせる）
    """
    nodes, edges = collect_graph(rows, show)
    mode = outside_mode(show, params)
    to_check = [n["id"] for n in nodes.values() if n["in_collection"] == "check" and n["uri"]]
    if to_check and members is None:
        members = collection_members(collection, to_check) if collection is not None else set(to_check)
    outside_count = 0
    for node in nodes.values():
        if node["in_collection"] == "check":
            node["outside"] = node["id"] not in (members or set())
        else:
            node["outside"] = False
        outside_count += node["outside"]
    if mode == "hide":
        hidden = {n for n, node in nodes.items() if node["outside"]}
        nodes = {n: node for n, node in nodes.items() if n not in hidden}
        edges = {k: e for k, e in edges.items() if e["source"] not in hidden and e["target"] not in hidden}

    degree = degrees(nodes, edges)
    # 辺のないノード（コレクション外の参照先を隠した結果など）は出さない
    if show.get("isolated", "hide") == "hide":
        nodes = {n: node for n, node in nodes.items() if degree[n]["degree"] > 0}

    total_nodes, total_edges = len(nodes), len(edges)
    max_nodes = int(show.get("max_nodes", DEFAULT_MAX_NODES))
    truncated = len(nodes) > max_nodes
    if truncated:
        ranked = sorted(nodes, key=lambda n: (-degree[n]["degree"], nodes[n]["label"]))
        kept = set(ranked[:max_nodes])
        nodes = {n: node for n, node in nodes.items() if n in kept}
        edges = {k: e for k, e in edges.items() if e["source"] in kept and e["target"] in kept}
        degree = degrees(nodes, edges)

    size_mode = show.get("size") or ("indegree" if any(e["directed"] for e in edges.values()) else "degree")
    for n, node in nodes.items():
        node.update(degree[n])
        node["size"] = 0 if size_mode == "none" else degree[n][size_mode]
    # 大きいノードから LABELLED_NODES 個は名前を常に出す
    for n in sorted(nodes, key=lambda n: (-nodes[n]["size"], nodes[n]["label"]))[:LABELLED_NODES]:
        nodes[n]["labelled"] = True

    layout = show.get("layout") or ("timeline" if any(node["x"] is not None for node in nodes.values()) else "force")
    if layout == "timeline":
        timeline_positions(nodes, edges)
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "layout": layout,
        "outside": mode,
        "outside_count": outside_count,
        "has_check": bool(to_check) or outside_count > 0,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "truncated": truncated,
        "kinds": list(dict.fromkeys(node["kind"] for node in nodes.values())),
    }


def degrees(nodes, edges):
    degree = {n: {"indegree": 0, "outdegree": 0, "degree": 0} for n in nodes}
    for edge in edges.values():
        s, t = edge["source"], edge["target"]
        if s in degree:
            degree[s]["outdegree"] += 1
            degree[s]["degree"] += 1
        if t in degree:
            degree[t]["indegree"] += 1
            degree[t]["degree"] += 1
    return degree


# --------------------------------------------------
# 配置: 年（x）で横に並べる
# --------------------------------------------------

ROW_GAP = 34        # 同じ年のノードの縦の間隔の最小（px）
ASPECT = 1.6        # 図の横:縦の目安
MIN_COLUMN_GAP, MAX_COLUMN_GAP = 22, 80   # 年（x）1 あたりの横の間隔（px）


def timeline_positions(nodes, edges, sweeps=4):
    """x の値で列に分け、列の中の順は隣のノードの位置の平均（重心）で決めて、辺の交差を減らす。

    x のないノードは右端の列に置く。結果は各ノードの "position" {x, y}。
    図が横に長くなりすぎないよう、年の間隔と縦の間隔を図の縦横比に合わせて決める。
    辺には弧の膨らみ "arc"（px）を付ける（同じ高さに並ぶノードの間の辺が重ならないように）。
    """
    xs = sorted({node["x"] for node in nodes.values() if node["x"] is not None})
    unknown_x = (xs[-1] + 2) if xs else 0
    columns = {}
    for n, node in nodes.items():
        columns.setdefault(node["x"] if node["x"] is not None else unknown_x, []).append(n)
    neighbors = {n: [] for n in nodes}
    for edge in edges.values():
        if edge["source"] in nodes and edge["target"] in nodes:
            neighbors[edge["source"]].append(edge["target"])
            neighbors[edge["target"]].append(edge["source"])
    # 最初は次数の大きい順に並べる
    order = {}
    for key, members in columns.items():
        members.sort(key=lambda n: (-len(neighbors[n]), nodes[n]["label"]))
        for i, n in enumerate(members):
            order[n] = i - (len(members) - 1) / 2
    keys = sorted(columns)
    for sweep in range(sweeps):
        sequence = keys if sweep % 2 == 0 else list(reversed(keys))
        for key in sequence:
            members = columns[key]

            def barycenter(n):
                around = [order[m] for m in neighbors[n] if m in order]
                return sum(around) / len(around) if around else order[n]

            members.sort(key=lambda n: (barycenter(n), nodes[n]["label"]))
            for i, n in enumerate(members):
                order[n] = i - (len(members) - 1) / 2
    if not keys:
        return
    base = keys[0]
    span = max(keys[-1] - base, 1)
    tallest = max(len(m) for m in columns.values())
    column_gap = min(MAX_COLUMN_GAP, max(MIN_COLUMN_GAP, ASPECT * tallest * ROW_GAP / span))
    width = span * column_gap
    row_gap = max(ROW_GAP, width / ASPECT / max(tallest, 1)) if tallest > 1 else ROW_GAP
    for key in keys:
        for n in columns[key]:
            nodes[n]["position"] = {"x": round((key - base) * column_gap, 1), "y": round(order[n] * row_gap, 1)}
    for edge in edges.values():
        if edge["source"] in nodes and edge["target"] in nodes:
            dx = abs(nodes[edge["source"]]["position"]["x"] - nodes[edge["target"]]["position"]["x"])
            edge["arc"] = round(min(0.3 * dx, width / ASPECT / 2) + 8, 1)


# --------------------------------------------------
# 表示
# --------------------------------------------------

# 種類ごとの色（Cytoscape のノードの色）。コレクション外は灰色
KIND_COLORS = ["#2563eb", "#d97706", "#059669", "#db2777", "#7c3aed", "#0891b2", "#65a30d", "#dc2626"]
OUTSIDE_COLOR = "#9ca3af"


def graph_payload(graph):
    """Cytoscape.js に渡す JSON（elements と表示の設定）"""
    colors = {kind: KIND_COLORS[i % len(KIND_COLORS)] for i, kind in enumerate(graph["kinds"])}
    elements = []
    for node in graph["nodes"]:
        data = {
            "id": node["id"],
            "label": node["label"],
            "short": node["label"] if len(node["label"]) <= 18 else node["label"][:17] + "…",
            "kind": node["kind"],
            "color": OUTSIDE_COLOR if node["outside"] else colors[node["kind"]],
            "size": node["size"],
            "indegree": node["indegree"],
            "outdegree": node["outdegree"],
        }
        if node["uri"]:
            data["href"] = f"/resource?uri={quote(node['uri'], safe='')}"
        if node["x"] is not None:
            data["x"] = int(node["x"]) if float(node["x"]).is_integer() else node["x"]
        element = {"data": data, "classes": " ".join(
            c for c, on in (("outside", node["outside"]), ("labelled", node.get("labelled"))) if on
        )}
        if "position" in node:
            element["position"] = node["position"]
        elements.append(element)
    for i, edge in enumerate(graph["edges"]):
        elements.append({
            "data": {"id": f"e{i}", "source": edge["source"], "target": edge["target"],
                     "label": edge["label"], "weight": edge["weight"], "arc": edge.get("arc", 0)},
            "classes": "directed" if edge["directed"] else "",
        })
    if graph["layout"] == "timeline":
        elements.extend(axis_elements(graph["nodes"]))
    sizes = [node["size"] for node in graph["nodes"]] or [0]
    return {
        "elements": elements,
        "layout": graph["layout"],
        "size_range": [min(sizes), max(sizes)],
        "legend": [{"kind": k, "color": c} for k, c in colors.items()],
    }


def axis_elements(nodes):
    """年で並べるときの、下の年の目盛り（クリックできないノード）"""
    placed = [n for n in nodes if "position" in n and n["x"] is not None]
    if len(placed) < 2:
        return []
    by_x = {}
    for node in placed:
        by_x.setdefault(node["x"], node["position"]["x"])
    low, high = min(by_x), max(by_x)
    (x0, p0), (x1, p1) = (low, by_x[low]), (high, by_x[high])
    if x1 == x0:
        return []
    scale = (p1 - p0) / (x1 - x0)
    span = x1 - x0
    step = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 10 ** 9) if span / s <= 12)
    bottom = max(n["position"]["y"] for n in placed) + 70
    ticks = []
    tick = (int(x0) // step) * step
    while tick <= x1:
        if tick >= x0:
            ticks.append({
                "data": {"id": f"_axis{tick}", "label": str(tick), "axis": True},
                "position": {"x": round(p0 + (tick - x0) * scale, 1), "y": bottom},
                "classes": "axis", "selectable": False, "grabbable": False,
            })
        tick += step
    return ticks


def _json_for_script(value):
    """<script type="application/json"> に入れる JSON（</script> で閉じないように < をエスケープ）"""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_graph(graph, params=None, height=None):
    """ネットワーク図の HTML"""
    if not graph["nodes"]:
        message = "表示するつながりがありません。"
        if graph["outside"] == "hide" and graph["outside_count"]:
            message = "コレクションの中のつながりはありません。"
        return (f'<p class="gadget-empty">{message}</p>' + _outside_toggle(graph, params))
    element_id = f"kg-graph-{uuid.uuid4().hex[:8]}"
    payload = graph_payload(graph)
    height = int(height or 600)
    summary = f'ノード {len(graph["nodes"]):,}・辺 {len(graph["edges"]):,}'
    notes = []
    if graph["truncated"]:
        notes.append(
            f'ノードが多いため、つながりの多い {len(graph["nodes"]):,} 件を表示しています'
            f'（全 {graph["total_nodes"]:,} 件・辺 {graph["total_edges"]:,} 本）。ファセットで絞り込むと全体を表示できます。'
        )
    legend = "".join(
        f'<span class="kg-graph-legend-item"><span class="kg-graph-dot" style="background:{escape(item["color"])}"></span>'
        f'{escape(item["kind"])}</span>'
        for item in payload["legend"]
    )
    if graph["outside"] == "show" and graph["outside_count"]:
        legend += (f'<span class="kg-graph-legend-item"><span class="kg-graph-dot kg-graph-dot-outside"></span>'
                   'コレクション外</span>')
    layouts = "".join(
        f'<option value="{name}"{" selected" if name == payload["layout"] else ""}>{label}</option>'
        for name, label in (("timeline", "年で並べる"), ("force", "力学モデル"), ("circle", "円"), ("grid", "格子"))
        if name != "timeline" or any("x" in e["data"] for e in payload["elements"] if "source" not in e["data"])
    )
    return f"""
<div class="kg-graph-wrap">
  <div class="kg-graph-toolbar">
    <span class="kg-graph-summary">{summary}</span>
    <span class="kg-graph-legend">{legend}</span>
    <span class="kg-graph-tools">
      <label>配置 <select class="kg-graph-layout">{layouts}</select></label>
      <button type="button" class="kg-graph-fit">全体を表示</button>
    </span>
  </div>
  {''.join(f'<p class="gadget-notice">{escape(n)}</p>' for n in notes)}
  {_outside_toggle(graph, params)}
  <div class="kg-graph-body">
    <div class="kg-graph" id="{element_id}" style="height:{height}px"></div>
    <div class="kg-graph-panel" id="{element_id}-panel" hidden></div>
  </div>
  <script type="application/json" id="{element_id}-data">{_json_for_script(payload)}</script>
  <script>kgDrawGraph("{element_id}");</script>
</div>
"""


def _outside_toggle(graph, params):
    """コレクション外のノードの表示の切り替えのリンク"""
    if not graph.get("has_check") or params is None:
        return ""
    if graph["outside"] == "hide":
        if not graph["outside_count"]:
            return ""
        url = make_url(params, drop={OUTSIDE_PARAM}, add=[(OUTSIDE_PARAM, "show")])
        text = f'コレクション外の参照先（{graph["outside_count"]:,} 件）も表示する'
    else:
        url = make_url(params, drop={OUTSIDE_PARAM}, add=[(OUTSIDE_PARAM, "hide")])
        text = "コレクションの中のつながりだけにする"
    return f'<p class="kg-graph-outside"><a href="{escape(url)}">{escape(text)}</a></p>'
