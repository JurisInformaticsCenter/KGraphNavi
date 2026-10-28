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
      layout: timeline    # timeline（x の値で横に並べる）/ bipartite（2段）/ force / circle / grid
      max_nodes: 500      # これを超えたら次数の大きいものから残す
      size: indegree      # ノードの大きさ: indegree / outdegree / degree / none
      height: 600

二部グラフ（判例と法令の条）の例::

    show:
      type: graph
      edges:
        - {from: entity, to: article, directed: false}
      nodes:
        entity:  {label: label, kind: 判例, x: year}
        article: {label: articlelabel, kind: 条, min_degree: 2,
                  collection: {facet: reflaw_core_clause}}   # ノードから、その値で絞り込んだコレクションへ
      layout: bipartite

片側への射影（同じ判例で一緒に参照される条どうし／同じ条を参照する判例どうし）::

    show:
      ...（二部グラフと同じ edges / nodes）
      project: {keep: article, via: entity, min_weight: 2}   # article どうしを、共通の entity の数を重みとして結ぶ
      layout: force

nodes の min_degree: これより少ない数のノードとしかつながらないノードは出さない（画面で変えられる。URL graph.min）
nodes の in_collection:
    true   … いつもコレクションの要素（変数 entity は既定で true）
    check  … コレクションの要素かどうかを問い合わせて調べる（参照先の判例など）
    false  … コレクションの要素ではない（法令の条など。outside の対象にしない。entity 以外の既定）
"""
import json
import re
import uuid
from html import escape
from urllib.parse import quote, urlencode

from .errors import ConfigError
from .facets import make_url
from .render_utils import get_localname
from .terms import iri_term

# 画面でコレクション外のノードの表示を切り替える URL パラメータ
OUTSIDE_PARAM = "graph.outside"
OUTSIDE_MODES = ("hide", "show")
# 画面で min_degree を変える URL パラメータと、選べる値
MIN_PARAM = "graph.min"
MIN_CHOICES = (1, 2, 3, 5, 10, 20, 50)
LAYOUTS = ("timeline", "bipartite", "force", "circle", "grid")
LAYOUT_LABELS = {"timeline": "年で並べる", "bipartite": "2段に並べる", "force": "力学モデル", "circle": "円", "grid": "格子"}
SIZE_MODES = ("indegree", "outdegree", "degree", "strength", "none")
# 射影の辺の重み（一緒に参照された判例の数など）の下限を画面で変える URL パラメータと、選べる値
WEIGHT_PARAM = "graph.w"
WEIGHT_CHOICES = (1, 2, 3, 5, 10, 20)
DEFAULT_MAX_SHARED = 200
# 指標の表に出す数
METRICS_ROWS = 50
DEFAULT_MAX_NODES = 500
# 名前を常に出すノードの数（大きい順）。他はマウスを乗せる・選ぶと出す
LABELLED_NODES = 30
# コレクションの要素かを調べる問い合わせ1回あたりの URI の数
MEMBERSHIP_BATCH = 300

SHOW_KEYS = {"type", "edges", "nodes", "outside", "layout", "max_nodes", "size", "height", "isolated",
             "project", "metrics"}
PROJECT_KEYS = {"keep", "via", "min_weight", "max_shared", "label"}
EDGE_KEYS = {"from", "to", "directed", "label"}
NODE_KEYS = {"label", "kind", "x", "in_collection", "min_degree", "collection"}
NODE_COLLECTION_KEYS = {"facet", "class", "view", "label"}


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
        if "min_degree" in node:
            try:
                if int(node["min_degree"]) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as e:
                raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var}.min_degree は正の整数です") from e
        if "collection" in node:
            conf = node["collection"]
            if not isinstance(conf, dict) or not conf.get("facet") or not re.fullmatch(r"[\w.-]+", str(conf["facet"])):
                raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var}.collection には facet（ファセットの名前）が必要です")
            unknown = set(conf) - NODE_COLLECTION_KEYS
            if unknown:
                raise ConfigError(f"gadget({name})のshow(graph)の nodes.{var}.collection に未知のキー: {sorted(unknown)}")
    project = show.get("project")
    if project is not None:
        if not isinstance(project, dict) or not project.get("keep") or not project.get("via"):
            raise ConfigError(f"gadget({name})のshow(graph)の project には keep と via（変数名）が必要です")
        unknown = set(project) - PROJECT_KEYS
        if unknown:
            raise ConfigError(f"gadget({name})のshow(graph)の project に未知のキー: {sorted(unknown)}")
        variables = {v for edge in edges for v in (edge["from"], edge["to"])}
        if project["keep"] not in variables or project["via"] not in variables or project["keep"] == project["via"]:
            raise ConfigError(f"gadget({name})のshow(graph)の project の keep / via は edges の別々の変数です")
        for key in ("min_weight", "max_shared"):
            if key in project:
                try:
                    if int(project[key]) <= 0:
                        raise ValueError
                except (TypeError, ValueError) as e:
                    raise ConfigError(f"gadget({name})のshow(graph)の project.{key} は正の整数です") from e
    if "metrics" in show and not isinstance(show["metrics"], bool):
        raise ConfigError(f"gadget({name})のshow(graph)の metrics は true / false です")
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
                "var": var,
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

    # min_degree: 少ない数としかつながらないノード（1件の判例からしか参照されない条など）は出さない
    settings = node_settings(show)
    min_degree = effective_min_degree(settings, params)
    if min_degree:
        degree = degrees(nodes, edges)
        dropped = {n for n, node in nodes.items()
                   if settings[node["var"]].get("min_degree") and degree[n]["degree"] < min_degree}
        nodes = {n: node for n, node in nodes.items() if n not in dropped}
        edges = {k: e for k, e in edges.items() if e["source"] not in dropped and e["target"] not in dropped}

    # 片側への射影（同じ判例で一緒に参照される条どうしなど）
    project = show.get("project")
    min_weight = None
    skipped_hubs = 0
    if project:
        min_weight = effective_min_weight(project, params)
        nodes, edges, skipped_hubs = project_graph(nodes, edges, project, min_weight)

    degree = degrees(nodes, edges)
    # 辺のないノード（コレクション外の参照先を隠した結果など）は出さない
    if show.get("isolated", "hide") == "hide":
        nodes = {n: node for n, node in nodes.items() if degree[n]["degree"] > 0}

    total_nodes, total_edges = len(nodes), len(edges)
    # 指標（被参照数・PageRank・連結成分）は、ノードを減らす前のグラフで計算する
    metrics = graph_metrics(nodes, edges) if show.get("metrics", True) else None
    max_nodes = int(show.get("max_nodes", DEFAULT_MAX_NODES))
    truncated = len(nodes) > max_nodes
    if truncated:
        rank_key = "strength" if project else "degree"
        ranked = sorted(nodes, key=lambda n: (-degree[n][rank_key], nodes[n]["label"]))
        kept = set(ranked[:max_nodes])
        nodes = {n: node for n, node in nodes.items() if n in kept}
        edges = {k: e for k, e in edges.items() if e["source"] in kept and e["target"] in kept}
        degree = degrees(nodes, edges)

    size_mode = show.get("size") or ("strength" if project else
                                     "indegree" if any(e["directed"] for e in edges.values()) else "degree")
    for n, node in nodes.items():
        node.update(degree[n])
        node["size"] = 0 if size_mode == "none" else degree[n][size_mode]
    # ノードから、その値で絞り込んだコレクションへのリンク
    for node in nodes.values():
        conf = settings[node["var"]].get("collection")
        if conf:
            node["filter"] = node_filter_url(conf, node["id"], params)

    # 配置（年で並べる・2段）の位置は、ここで計算しておく（画面で切り替えられる）
    positions = {}
    if any(node["x"] is not None for node in nodes.values()):
        positions["timeline"] = timeline_positions(nodes, edges)
    two_rows = bipartite_positions(nodes, edges)
    if two_rows:
        positions["bipartite"] = two_rows
    layout = show.get("layout") or ("timeline" if "timeline" in positions else "force")
    if layout in ("timeline", "bipartite") and layout not in positions:
        layout = "force"
    for n, node in nodes.items():
        if layout in positions:
            node["position"] = positions[layout][n]
        node["side"] = "bottom" if node["in_collection"] else "top"

    # 大きいノードから LABELLED_NODES 個は名前を常に出す（2段のときは上の段＝参照される側だけ）
    candidates = [n for n in nodes if layout != "bipartite" or nodes[n]["side"] == "top"]
    for n in sorted(candidates, key=lambda n: (-nodes[n]["size"], nodes[n]["label"]))[:LABELLED_NODES]:
        nodes[n]["labelled"] = True
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
        "positions": positions,
        "min_degree": min_degree,
        "min_kinds": [str(conf["kind"]) for conf in settings.values() if conf.get("min_degree")],
        "project": project,
        "via_kind": str(settings[project["via"]]["kind"]) if project else None,
        "min_weight": min_weight,
        "skipped_hubs": skipped_hubs,
        "metrics": metrics,
        "directed": any(e["directed"] for e in edges.values()),
    }


def effective_min_weight(project, params):
    """射影の辺の重みの下限（URL の graph.w が設定より優先）"""
    try:
        value = int((params or {}).get(WEIGHT_PARAM) or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else int(project.get("min_weight", 1))


def project_graph(nodes, edges, project, min_weight=1):
    """二部グラフを keep の側だけのグラフにする。

    via の側のノード（判例など）を共有する keep の側のノード（条など）どうしを、向きのない辺で結ぶ。
    辺の重みは共有する via のノードの数。重みが min_weight より小さい辺は出さない。
    つながる keep のノードが max_shared より多い via のノード（多くの判例が参照する条など）は、
    組の数が膨らむうえ、似ていることの手がかりにならないので使わない。
    返り値: (nodes, edges, 使わなかった via のノードの数)
    """
    keep_var, via_var = project["keep"], project["via"]
    max_shared = int(project.get("max_shared", DEFAULT_MAX_SHARED))
    around = {}
    for edge in edges.values():
        s, t = edge["source"], edge["target"]
        for a, b in ((s, t), (t, s)):
            if nodes.get(a, {}).get("var") == via_var and nodes.get(b, {}).get("var") == keep_var:
                around.setdefault(a, set()).add(b)
    pairs = {}
    skipped = 0
    for via, kept in around.items():
        if len(kept) > max_shared:
            skipped += 1
            continue
        ordered = sorted(kept)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                pairs[(a, b)] = pairs.get((a, b), 0) + 1
    new_edges = {
        key: {"source": key[0], "target": key[1], "directed": False, "label": "", "weight": weight}
        for key, weight in pairs.items() if weight >= min_weight
    }
    new_nodes = {n: node for n, node in nodes.items() if node.get("var") == keep_var}
    return new_nodes, new_edges, skipped

def effective_min_degree(settings, params):
    """min_degree の値（URL の graph.min が設定より優先）。min_degree を持つノードがなければ None"""
    configured = [int(conf["min_degree"]) for conf in settings.values() if conf.get("min_degree")]
    if not configured:
        return None
    try:
        value = int((params or {}).get(MIN_PARAM) or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else max(configured)


def node_filter_url(conf, value, params):
    """ノードの値で絞り込んだコレクションの URL。

    コレクションのページでは今の条件にその値の条件を加える（図もその範囲で描き直す）。
    それ以外のページでは collection.class / view のコレクションへ移る。
    """
    key = f"f.{conf['facet']}"
    path = (params or {}).get("_path") or ""
    if path.rstrip("/").endswith("/collection") and params is not None:
        return make_url(params, drop_items={(key, value)}, add=[(key, value)])
    query = {}
    if conf.get("class"):
        query["class"] = conf["class"]
    if conf.get("view"):
        query["view"] = conf["view"]
    if not query:
        return None
    query[key] = value
    return "/collection?" + urlencode(query)


def degrees(nodes, edges):
    degree = {n: {"indegree": 0, "outdegree": 0, "degree": 0, "strength": 0} for n in nodes}
    for edge in edges.values():
        s, t = edge["source"], edge["target"]
        if s in degree:
            degree[s]["outdegree"] += 1
            degree[s]["degree"] += 1
            degree[s]["strength"] += edge["weight"]
        if t in degree:
            degree[t]["indegree"] += 1
            degree[t]["degree"] += 1
            degree[t]["strength"] += edge["weight"]
    return degree


# --------------------------------------------------
# 指標: PageRank・連結成分
# --------------------------------------------------

def pagerank(nodes, edges, damping=0.85, iterations=100, tolerance=1e-10):
    """PageRank。向きのある辺はその向きに、向きのない辺は両方向に、重みに比例して流す。
    出ていく辺のないノードの値は全体に均等に配る。"""
    ids = list(nodes)
    count = len(ids)
    if not count:
        return {}
    out = {n: [] for n in ids}
    for edge in edges.values():
        s, t, w = edge["source"], edge["target"], edge.get("weight", 1)
        if s in out and t in out:
            out[s].append((t, w))
            if not edge["directed"]:
                out[t].append((s, w))
    totals = {n: sum(w for _, w in out[n]) for n in ids}
    rank = {n: 1 / count for n in ids}
    for _ in range(iterations):
        dangling = sum(rank[n] for n in ids if not totals[n])
        new = {n: (1 - damping) / count + damping * dangling / count for n in ids}
        for n in ids:
            if totals[n]:
                share = damping * rank[n] / totals[n]
                for t, w in out[n]:
                    new[t] += share * w
        change = sum(abs(new[n] - rank[n]) for n in ids)
        rank = new
        if change < tolerance:
            break
    return rank


def components(nodes, edges):
    """連結成分（辺の向きは見ない）。{ノード: 成分の番号}、成分は大きい順に 1, 2, …"""
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for edge in edges.values():
        if edge["source"] in parent and edge["target"] in parent:
            a, b = find(edge["source"]), find(edge["target"])
            if a != b:
                parent[a] = b
    groups = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    ordered = sorted(groups.values(), key=lambda g: (-len(g), min(g)))
    return {n: i for i, group in enumerate(ordered, 1) for n in group}, [len(g) for g in ordered]


def graph_metrics(nodes, edges):
    """ノードごとの指標（被参照数・つながり・PageRank・連結成分）と、成分の数・大きさ"""
    degree = degrees(nodes, edges)
    rank = pagerank(nodes, edges)
    component, sizes = components(nodes, edges)
    rows = []
    for n, node in nodes.items():
        rows.append({
            "id": n, "label": node["label"], "kind": node["kind"], "uri": node["uri"],
            "x": node["x"], "outside": node.get("outside", False),
            **degree[n], "pagerank": rank.get(n, 0.0),
            "component": component[n], "component_size": sizes[component[n] - 1],
        })
    rows.sort(key=lambda r: (-r["pagerank"], r["label"]))
    return {"rows": rows, "component_sizes": sizes}


# --------------------------------------------------
# 配置: 年（x）で横に並べる
# --------------------------------------------------

ROW_GAP = 34        # 同じ年のノードの縦の間隔の最小（px）
ASPECT = 1.6        # 図の横:縦の目安
MIN_COLUMN_GAP, MAX_COLUMN_GAP = 22, 80   # 年（x）1 あたりの横の間隔（px）


def timeline_positions(nodes, edges, sweeps=4):
    """x の値で列に分け、列の中の順は隣のノードの位置の平均（重心）で決めて、辺の交差を減らす。

    x のないノードは右端の列に置く。返り値は {ノード: {x, y}}。
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
        return {}
    base = keys[0]
    span = max(keys[-1] - base, 1)
    tallest = max(len(m) for m in columns.values())
    column_gap = min(MAX_COLUMN_GAP, max(MIN_COLUMN_GAP, ASPECT * tallest * ROW_GAP / span))
    width = span * column_gap
    row_gap = max(ROW_GAP, width / ASPECT / max(tallest, 1)) if tallest > 1 else ROW_GAP
    positions = {}
    for key in keys:
        for n in columns[key]:
            positions[n] = {"x": round((key - base) * column_gap, 1), "y": round(order[n] * row_gap, 1)}
    for edge in edges.values():
        if edge["source"] in nodes and edge["target"] in nodes:
            dx = abs(positions[edge["source"]]["x"] - positions[edge["target"]]["x"])
            edge["arc"] = round(min(0.3 * dx, width / ASPECT / 2) + 8, 1)
    return positions


# --------------------------------------------------
# 配置: 2段（二部グラフ。下の段にコレクションの要素、上の段に参照される側）
# --------------------------------------------------

SLOT_BOTTOM = 22    # 下の段のノードの間隔の最小（px。下の段は何列かに互い違いに並べて詰める）
SLOT_TOP = 46       # 上の段のノードの間隔の最小（px。名前を出すので広め）
LANE_GAP = 22       # 下の段を互い違いに並べるときの縦の間隔（px）
MAX_LANES = 8


def bipartite_positions(nodes, edges, sweeps=6):
    """コレクションの要素（判例）を下の段、それ以外（条など）を上の段に並べる。2段にならなければ None。

    下の段は x（年）があれば年の順、上の段はつながる下のノードの位置の平均（重心）の順にして、
    辺の交差を減らす。年がなければ下の段も上の段の重心で並べ直す。
    下の段が上の段より多いときは、何列かに互い違いに並べて、図が横に長くなりすぎないようにする。
    """
    bottom = [n for n, node in nodes.items() if node["in_collection"]]
    top = [n for n, node in nodes.items() if not node["in_collection"]]
    if not bottom or not top:
        return None
    neighbors = {n: [] for n in nodes}
    for edge in edges.values():
        if edge["source"] in nodes and edge["target"] in nodes:
            neighbors[edge["source"]].append(edge["target"])
            neighbors[edge["target"]].append(edge["source"])
    by_year = all(nodes[n]["x"] is not None for n in bottom)
    bottom.sort(key=lambda n: (nodes[n]["x"] if by_year else 0, -len(neighbors[n]), nodes[n]["label"]))
    width = max((len(top) - 1) * SLOT_TOP, 600)
    lanes = min(MAX_LANES, max(1, -(-(len(bottom) - 1) * SLOT_BOTTOM // int(width))))
    width = max(width, (len(bottom) - 1) * SLOT_BOTTOM / lanes)

    def spread(row):
        step = width / (len(row) - 1) if len(row) > 1 else 0
        return {n: (i * step if len(row) > 1 else width / 2) for i, n in enumerate(row)}

    def barycenter(n, x):
        around = [x[m] for m in neighbors[n] if m in x]
        return sum(around) / len(around) if around else width / 2

    x_bottom = spread(bottom)
    x_top = {}
    for sweep in range(sweeps):
        top.sort(key=lambda n: (barycenter(n, x_bottom), nodes[n]["label"]))
        x_top = spread(top)
        if by_year:
            break
        bottom.sort(key=lambda n: (barycenter(n, x_top), nodes[n]["label"]))
        x_bottom = spread(bottom)
    base = max(260.0, width / ASPECT / 2)
    positions = {n: {"x": round(x_bottom[n], 1), "y": round(base + (i % lanes) * LANE_GAP, 1)}
                 for i, n in enumerate(bottom)}
    positions.update({n: {"x": round(x, 1), "y": 0.0} for n, x in x_top.items()})
    return positions


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
        if node.get("filter"):
            data["filter"] = node["filter"]
        element = {"data": data, "classes": " ".join(
            c for c, on in (("outside", node["outside"]), ("labelled", node.get("labelled")),
                            ("top", node.get("side") == "top")) if on
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
    if "timeline" in graph.get("positions", {}):
        elements.extend(axis_elements(graph["nodes"], graph["positions"]["timeline"]))
    sizes = [node["size"] for node in graph["nodes"]] or [0]
    weights = [edge["weight"] for edge in graph["edges"]] or [1]
    return {
        "weight_range": [min(weights), max(weights)],
        "elements": elements,
        "layout": graph["layout"],
        "positions": graph.get("positions", {}),
        "size_range": [min(sizes), max(sizes)],
        "legend": [{"kind": k, "color": c} for k, c in colors.items()],
    }


def axis_elements(nodes, positions):
    """年で並べるときの、下の年の目盛り（クリックできないノード）"""
    placed = [n for n in nodes if n["id"] in positions and n["x"] is not None]
    if len(placed) < 2:
        return []
    by_x = {}
    for node in placed:
        by_x.setdefault(node["x"], positions[node["id"]]["x"])
    low, high = min(by_x), max(by_x)
    (x0, p0), (x1, p1) = (low, by_x[low]), (high, by_x[high])
    if x1 == x0:
        return []
    scale = (p1 - p0) / (x1 - x0)
    span = x1 - x0
    step = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 10 ** 9) if span / s <= 12)
    bottom = max(positions[n["id"]]["y"] for n in placed) + 70
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
        f'<option value="{name}"{" selected" if name == payload["layout"] else ""}>{LAYOUT_LABELS[name]}</option>'
        for name in LAYOUTS
        if name not in ("timeline", "bipartite") or name in payload["positions"]
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
  {_min_degree_links(graph, params)}
  {_min_weight_links(graph, params)}
  <div class="kg-graph-body">
    <div class="kg-graph" id="{element_id}" style="height:{height}px"></div>
    <div class="kg-graph-panel" id="{element_id}-panel" hidden></div>
  </div>
  <script type="application/json" id="{element_id}-data">{_json_for_script(payload)}</script>
  <script>kgDrawGraph("{element_id}");</script>
  {render_metrics(graph, {n["id"] for n in graph["nodes"]})}
</div>
"""


def _choice_links(params, param, choices, current):
    links = []
    for value in sorted(set(choices) | {current}):
        if value == current:
            links.append(f'<strong>{value}</strong>')
        else:
            url = make_url(params, drop={param}, add=[(param, str(value))])
            links.append(f'<a href="{escape(url)}">{value}</a>')
    return " ".join(links)


def _min_weight_links(graph, params):
    """射影の「共有する判例が ○ 以上の組だけ線で結ぶ」の切り替え"""
    if not graph.get("project") or params is None:
        return ""
    via = graph.get("via_kind") or ""
    text = _choice_links(params, WEIGHT_PARAM, WEIGHT_CHOICES, graph["min_weight"])
    note = ""
    if graph.get("skipped_hubs"):
        note = (f'（{DEFAULT_MAX_SHARED if not graph["project"].get("max_shared") else graph["project"]["max_shared"]} '
                f'より多くとつながる{escape(via)} {graph["skipped_hubs"]:,} 件は、組を作るのに使っていません）')
    return f'<p class="kg-graph-min">線で結ぶ組: 共有する{escape(via)}が {text} 以上{note}</p>'


def render_metrics(graph, shown):
    """指標の表（PageRank の上位）と連結成分。shown: 図に出ているノード（「図で見る」を付ける）"""
    metrics = graph.get("metrics")
    if not metrics or not metrics["rows"]:
        return ""
    rows = metrics["rows"]
    count = len(rows)
    sizes = metrics["component_sizes"]
    directed = graph.get("directed")
    has_year = any(r["x"] is not None for r in rows[:METRICS_ROWS])
    if directed:
        heads = ["参照されている", "参照している"]
    elif graph.get("project"):
        heads = ["つながり", f"共有する{graph.get('via_kind') or ''}の延べ数"]
    else:
        heads = ["つながり"]
    header = ("<tr><th>順位</th><th>名前</th>" + ("<th>年</th>" if has_year else "")
              + "".join(f"<th>{escape(h)}</th>" for h in heads)
              + '<th title="平均を 1 とした値">PageRank</th><th>連結成分</th><th></th></tr>')
    body = []
    for i, row in enumerate(rows[:METRICS_ROWS], 1):
        name = escape(row["label"])
        if row["uri"]:
            name = f'<a href="/resource?uri={quote(row["uri"], safe="")}">{name}</a>'
        if row["outside"]:
            name += '<span class="kg-graph-outside-mark">（コレクション外）</span>'
        year = ""
        if has_year:
            x = row["x"]
            year = f"<td>{'' if x is None else (int(x) if float(x).is_integer() else x)}</td>"
        if directed:
            values = [row["indegree"], row["outdegree"]]
        elif graph.get("project"):
            values = [row["degree"], row["strength"]]
        else:
            values = [row["degree"]]
        cells = "".join(f'<td class="num">{v:,}</td>' for v in values)
        locate = (f'<button type="button" class="kg-graph-locate" data-node="{escape(row["id"])}">図で見る</button>'
                  if row["id"] in shown else "")
        component = f'{row["component"]}（{row["component_size"]:,}）'
        body.append(f'<tr><td class="num">{i}</td><td>{name}</td>{year}{cells}'
                    f'<td class="num">{row["pagerank"] * count:.2f}</td><td>{component}</td><td>{locate}</td></tr>')
    largest = sizes[0] if sizes else 0
    summary = (f'指標（PageRank の上位 {min(count, METRICS_ROWS)} 件）・連結成分 {len(sizes):,} 個'
               f'（最大 {largest:,} ノード）')
    return (f'<details class="kg-graph-metrics" open><summary>{escape(summary)}</summary>'
            '<p class="kg-graph-metrics-note">PageRank は、つながりの多いノードとつながるほど高くなる値です（平均を 1 とした値）。'
            '連結成分は、線でたどってつながるノードのまとまりで、大きい順の番号と（ノードの数）です。'
            f'{"指標は、図で省いたノードも含めて計算しています。" if graph.get("truncated") else ""}</p>'
            f'<table class="kg-graph-metrics-table"><thead>{header}</thead><tbody>{"".join(body)}</tbody></table>'
            '</details>')


def _min_degree_links(graph, params):
    """「○件以上とつながる条だけ」の切り替え（min_degree を持つノードがあるとき）"""
    if not graph.get("min_degree") or params is None:
        return ""
    kinds = "・".join(graph.get("min_kinds") or [])
    current = graph["min_degree"]
    choices = sorted(set(MIN_CHOICES) | {current})
    links = []
    for value in choices:
        if value == current:
            links.append(f'<strong>{value}</strong>')
        else:
            url = make_url(params, drop={MIN_PARAM}, add=[(MIN_PARAM, str(value))])
            links.append(f'<a href="{escape(url)}">{value}</a>')
    return (f'<p class="kg-graph-min">表示する{escape(kinds)}: つながりが '
            f'{" ".join(links)} 以上</p>')


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
