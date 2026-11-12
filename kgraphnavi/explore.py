#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      explore.py
##  Author:
##      Fumihito NISHINO       nishino@nii.ac.jp
##  Description:
##      探索グラフ（/explore。2026.11.9）
##      種（語・判例・条など）から始めて、ノードをクリックして関係ごとに広げていく。
##      たどった道（手順）を残し、URL に入れて再現・共有でき、判例を名前を付けて保存できる。
##
##  /explore?q=<語>                 ラベルに語を含むリソースを種にする（種類のあるものだけ）
##  /explore?uri=<IRI>[&uri=…]      リソースを種にする
##  /explore/node?uri=<IRI>         ノードの情報と、広げられる関係ごとの件数（JSON）
##  /explore/expand?uri=<IRI>&rel=<関係>[&offset=0&limit=30]   関係の先のノード（JSON）
##
##  設定（アプリケーション設定 explore:）
##    explore:
##      limit: 30                  1回に広げるノードの数の既定
##      max_nodes: 400             図に出すノードの上限
##      save_kind: 判例            保存の対象にする種類
##      save_class: caselawo:CaseLawDocument   保存するコレクションのクラス
##      kinds:                     ノードの種類（形・色）。リソースのクラスで決める（上から順に照合）
##        - name: 判例
##          types: [caselawo:CaseLawDocument]
##          shape: ellipse
##          color: "#0072B2"
##          info: |                ノードの名前・年・属性・全体の件数（省略可）。$nodes は VALUES ?n { … } に置き換わる
##              SELECT ?n ?label ?year ?a_result (COUNT(…) AS ?count) WHERE { $nodes … } GROUP BY …
##          広げたノードもまとめてこれで調べるので、関係の問い合わせには ?n ?label だけ書けばよい
##      attrs:                     色の切り替えに使う属性。問い合わせで ?a_<name> を返すとノードに付く
##        - {name: result, label: 裁判の結果}
##        - {name: instance, label: 審級}
##      relations:                 広げる関係
##        - name: reflaw
##          label: 判断の中で参照している条
##          from: 判例              この種類のノードから
##          to: 条                  この種類のノードへ
##          direction: out          辺の向き: out（$uri → ?n）/ in（?n → $uri）。directed: false で向きなし
##          weak: [中（候補）]      ?conf がこの値の辺は破線（確かさの低い関係）
##          query: |                $uri から ?n（と ?label・?year・?count・?conf・?a_<属性>）を求める SELECT。
##              SELECT ?n ?label …  1つの ?n に1行になるように書く（GROUP BY・SAMPLE）。LIMIT は書かない
##              WHERE { $uri caselawp:reflawCore ?n . … }
##              ORDER BY DESC(?count)
"""

import logging
import re

from .errors import SparqlError
from .terms import is_iri, iri_term

logger = logging.getLogger(__name__)

EXPLORE_KEYS = {"kinds", "relations", "attrs", "limit", "max_nodes", "save_kind", "save_class", "search_limit",
                "title", "describe"}
KIND_KEYS = {"name", "types", "shape", "color", "info"}
RELATION_KEYS = {"name", "label", "from", "to", "query", "direction", "directed", "weak", "limit"}
ATTR_KEYS = {"name", "label", "type"}
SHAPES = ("ellipse", "round-rectangle", "diamond", "hexagon", "triangle", "barrel", "tag", "star", "vee",
          "rectangle", "round-triangle", "pentagon", "octagon")
DEFAULT_LIMIT = 30
MAX_LIMIT = 200
DEFAULT_MAX_NODES = 400
DEFAULT_SEARCH_LIMIT = 10
# ノードに付ける値の変数（これ以外の ?a_<名前> は属性）
NODE_VARS = {"n", "label", "year", "count", "conf", "weight"}


def explore_settings(conf):
    """設定の explore: を確かめて、形をそろえる"""
    if not isinstance(conf, dict):
        raise ValueError("explore は辞書で書いてください")
    unknown = set(conf) - EXPLORE_KEYS
    if unknown:
        raise ValueError(f"explore の未知のキー: {sorted(unknown)}")
    kinds = []
    for kind in conf.get("kinds") or []:
        if not isinstance(kind, dict) or not kind.get("name"):
            raise ValueError(f"explore.kinds の各項目には name が要ります: {kind!r}")
        unknown = set(kind) - KIND_KEYS
        if unknown:
            raise ValueError(f"explore.kinds（{kind['name']}）の未知のキー: {sorted(unknown)}")
        types = kind.get("types") or []
        if isinstance(types, str):
            types = [types]
        if kind.get("shape") and kind["shape"] not in SHAPES:
            raise ValueError(f"explore.kinds（{kind['name']}）の shape は {' / '.join(SHAPES)} のいずれかです")
        if kind.get("color") and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(kind["color"])):
            raise ValueError(f"explore.kinds（{kind['name']}）の color は #rrggbb で書いてください")
        if kind.get("info") and "$nodes" not in str(kind["info"]):
            raise ValueError(f"explore.kinds（{kind['name']}）の info には $nodes（VALUES ?n {{…}} に置き換わる）が要ります")
        kinds.append({**kind, "name": str(kind["name"]), "types": [str(t) for t in types]})
    if not kinds:
        raise ValueError("explore には kinds（ノードの種類）が要ります")
    names = {k["name"] for k in kinds}
    attrs = []
    for attr in conf.get("attrs") or []:
        if not isinstance(attr, dict) or not re.fullmatch(r"\w+", str(attr.get("name", ""))):
            raise ValueError(f"explore.attrs の各項目には name（英数字）が要ります: {attr!r}")
        unknown = set(attr) - ATTR_KEYS
        if unknown:
            raise ValueError(f"explore.attrs（{attr['name']}）の未知のキー: {sorted(unknown)}")
        attrs.append({"name": str(attr["name"]), "label": str(attr.get("label") or attr["name"]),
                      "type": attr.get("type") or "category"})
    relations = []
    seen = set()
    for rel in conf.get("relations") or []:
        if not isinstance(rel, dict) or not rel.get("name") or not rel.get("query"):
            raise ValueError(f"explore.relations の各項目には name と query が要ります: {rel!r}")
        unknown = set(rel) - RELATION_KEYS
        if unknown:
            raise ValueError(f"explore.relations（{rel['name']}）の未知のキー: {sorted(unknown)}")
        if not re.fullmatch(r"[\w.-]+", str(rel["name"])):
            raise ValueError(f"explore.relations の name は英数字で書いてください: {rel['name']!r}")
        if rel["name"] in seen:
            raise ValueError(f"explore.relations の name が重なっています: {rel['name']}")
        seen.add(rel["name"])
        for key in ("from", "to"):
            if rel.get(key) not in names:
                raise ValueError(f"explore.relations（{rel['name']}）の {key} は kinds の name です: {rel.get(key)!r}")
        if rel.get("direction", "out") not in ("out", "in"):
            raise ValueError(f"explore.relations（{rel['name']}）の direction は out / in です")
        query = str(rel["query"])
        if "$uri" not in query:
            raise ValueError(f"explore.relations（{rel['name']}）の query には $uri が要ります")
        if not re.search(r"\?n\b", query):
            raise ValueError(f"explore.relations（{rel['name']}）の query は ?n（広げた先のノード）を返してください")
        if re.search(r"\bLIMIT\s+\d+\s*$", query.strip(), re.IGNORECASE):
            raise ValueError(f"explore.relations（{rel['name']}）の query に LIMIT は書かないでください（画面で送る）")
        weak = rel.get("weak") or []
        if isinstance(weak, str):
            weak = [weak]
        relations.append({
            "name": str(rel["name"]), "label": str(rel.get("label") or rel["name"]),
            "from": rel["from"], "to": rel["to"], "query": query,
            "direction": rel.get("direction", "out"), "directed": rel.get("directed", True) is not False,
            "weak": [str(w) for w in weak], "limit": int(rel.get("limit") or 0) or None,
        })
    if not relations:
        raise ValueError("explore には relations（広げる関係）が要ります")

    def positive(key, default):
        try:
            value = int(conf.get(key, default))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as e:
            raise ValueError(f"explore.{key} は正の整数です") from e

    save_kind = conf.get("save_kind") or kinds[0]["name"]
    if save_kind not in names:
        raise ValueError(f"explore.save_kind は kinds の name です: {save_kind!r}")
    return {
        "kinds": kinds, "attrs": attrs, "relations": relations,
        "limit": min(positive("limit", DEFAULT_LIMIT), MAX_LIMIT),
        "max_nodes": positive("max_nodes", DEFAULT_MAX_NODES),
        "search_limit": positive("search_limit", DEFAULT_SEARCH_LIMIT),
        "save_kind": save_kind, "save_class": conf.get("save_class"),
        "title": conf.get("title") or "探索グラフ", "describe": conf.get("describe") or "",
    }


def resolve_kind_types(settings, expand):
    """kinds の types の接頭辞付きの名前を IRI にする（expand は app.expand_prefixed と prefixes）"""
    for kind in settings["kinds"]:
        kind["types"] = [expand(t) for t in kind["types"]]
    if settings.get("save_class"):
        settings["save_class"] = expand(str(settings["save_class"]))
    return settings


def strip_limit(query):
    return re.sub(r"\s+(LIMIT|OFFSET)\s+\d+(\s+(LIMIT|OFFSET)\s+\d+)?\s*$", "", query.strip(), flags=re.IGNORECASE)


def count_query(query):
    """関係の先のノードの数を数える問い合わせ（関係の問い合わせを副問い合わせにする）"""
    inner = re.sub(r"\bORDER\s+BY\b[\s\S]*$", "", strip_limit(query), flags=re.IGNORECASE)
    return "SELECT (COUNT(DISTINCT ?n) AS ?total) WHERE {\n{\n" + inner + "\n}\n}"


def page_query(query, offset, limit):
    return f"{strip_limit(query)}\nLIMIT {int(limit)}\nOFFSET {int(offset)}"


def value(row, var):
    cell = row.get(var)
    return None if not cell else cell.get("value")


def to_year(text):
    if text is None:
        return None
    match = re.match(r"^-?\d{3,4}", str(text).strip())
    return int(match.group(0)) if match else None


def to_count(text):
    try:
        return float(text) if text is not None else None
    except (TypeError, ValueError):
        return None


class Explorer:
    """探索グラフの問い合わせ（SPARQL クライアントと設定 explore:）"""

    def __init__(self, sparql, settings):
        self.sparql = sparql
        self.settings = settings
        self.kinds = {k["name"]: k for k in settings["kinds"]}
        self.relations = {r["name"]: r for r in settings["relations"]}

    # ---- 種類 ----

    def kind_of_types(self, types):
        """クラスの IRI の集まりから種類（kinds の上から順に、最初に合うもの）"""
        types = set(types)
        for kind in self.settings["kinds"]:
            if types & set(kind["types"]):
                return kind["name"]
        return None

    def kind_of(self, uri):
        types = self.sparql.query_values("SELECT DISTINCT ?t WHERE { $uri a ?t }", "t", uri=uri)
        return self.kind_of_types(types)

    def relations_from(self, kind):
        return [r for r in self.settings["relations"] if r["from"] == kind]

    # ---- ノード ----

    def node(self, uri, kind=None):
        """ノードの情報（種類・名前・年・属性・全体の件数）"""
        if not is_iri(uri):
            raise ValueError(f"URI として使えない値です: {uri}")
        kind = kind if kind in self.kinds else self.kind_of(uri)
        node = self.make_node(uri, kind, None, {})
        self.enrich([node])
        if node["label"] == local_name(uri):
            label = self.sparql.query_value("SELECT ?label WHERE { $uri rdfs:label ?label } LIMIT 1", "label", uri=uri)
            if label:
                node["label"] = label
        return node

    def enrich(self, nodes):
        """種類の info の問い合わせで、ノードの名前・年・属性・全体の件数をまとめて付ける"""
        by_kind = {}
        for node in nodes:
            if (self.kinds.get(node["kind"]) or {}).get("info"):
                by_kind.setdefault(node["kind"], []).append(node)
        for kind, members in by_kind.items():
            index = {n["id"]: n for n in members}
            for i in range(0, len(members), 100):
                chunk = members[i:i + 100]
                values = "VALUES ?n { " + " ".join(iri_term(n["id"]) for n in chunk) + " }"
                query = self.kinds[kind]["info"].replace("$nodes", values)
                for row in self.sparql.query(query, {}):
                    node = index.get(value(row, "n"))
                    if node is None:
                        continue
                    label = value(row, "label")
                    if label and (not node.get("label") or node["label"] == local_name(node["id"])):
                        node["label"] = label
                    extra = self.make_node(node["id"], kind, None, row)
                    if "x" in extra and "x" not in node:
                        node["x"] = extra["x"]
                    if "count" in extra and "count" not in node:
                        node["count"] = extra["count"]
                    for attr, v in extra["attrs"].items():
                        node["attrs"].setdefault(attr, v)
        return nodes

    def make_node(self, uri, kind, label, row):
        node = {
            "id": uri, "label": label or local_name(uri), "kind": kind,
            "href": "/resource?uri=" + quote_uri(uri), "attrs": {},
        }
        year = to_year(value(row, "year"))
        if year is not None:
            node["x"] = year
        count = to_count(value(row, "count"))
        if count is not None:
            node["count"] = count
        for var in row:
            if var.startswith("a_") and value(row, var) not in (None, ""):
                node["attrs"][var[2:]] = value(row, var)
        return node

    def counts(self, uri, kind):
        """広げられる関係ごとの、先のノードの数"""
        result = []
        for rel in self.relations_from(kind):
            try:
                total = self.sparql.query_value(count_query(rel["query"]), "total", uri=uri)
                total = int(float(total)) if total is not None else 0
                error = None
            except SparqlError as e:
                total, error = None, e.message
            result.append({"name": rel["name"], "label": rel["label"], "to": rel["to"], "count": total,
                           **({"error": error} if error else {})})
        return result

    def expand(self, uri, rel_name, offset=0, limit=None):
        """関係 rel_name の先のノードと辺。返り値 {nodes, edges, total, offset, limit, rel}"""
        if not is_iri(uri):
            raise ValueError(f"URI として使えない値です: {uri}")
        rel = self.relations.get(rel_name)
        if rel is None:
            raise ValueError(f"関係「{rel_name}」はありません")
        limit = max(1, min(int(limit or rel.get("limit") or self.settings["limit"]), MAX_LIMIT))
        offset = max(0, int(offset or 0))
        total = self.sparql.query_value(count_query(rel["query"]), "total", uri=uri)
        total = int(float(total)) if total is not None else 0
        rows = self.sparql.query(page_query(rel["query"], offset, limit), {"uri": uri})
        nodes, edges = {}, {}
        for row in rows:
            n = value(row, "n")
            if not n or n == uri or row["n"].get("type") != "uri":
                continue
            if n not in nodes:
                nodes[n] = self.make_node(n, rel["to"], value(row, "label"), row)
            else:
                for var in row:
                    if var.startswith("a_") and value(row, var):
                        nodes[n]["attrs"].setdefault(var[2:], value(row, var))
            source, target = (uri, n) if rel["direction"] == "out" else (n, uri)
            key = (source, target, rel["name"])
            conf = value(row, "conf")
            if key not in edges:
                edges[key] = {
                    "id": f"{rel['name']}|{source}|{target}", "source": source, "target": target,
                    "rel": rel["name"], "label": rel["label"], "directed": rel["directed"],
                    "conf": conf or "", "weak": bool(conf and conf in rel["weak"]),
                    "weight": to_count(value(row, "weight")) or 1,
                }
            elif conf and edges[key]["weak"] and conf not in rel["weak"]:
                # 確かさの高い方を残す
                edges[key].update(conf=conf, weak=False)
        self.enrich(list(nodes.values()))
        return {"nodes": list(nodes.values()), "edges": list(edges.values()), "total": total,
                "offset": offset, "limit": limit, "rel": rel["name"], "label": rel["label"], "to": rel["to"]}

    # ---- 種 ----

    def seeds_from_text(self, text):
        """ラベルに語を含むリソースのうち、種類のあるもの（ラベルが語と同じものを先に）"""
        text = (text or "").strip()
        if not text:
            return []
        found = {}
        for mode in ("perfect", "partial"):
            for uri, label, rdftype in self.sparql.retrieve(text, mode):
                entry = found.setdefault(uri, {"label": label, "types": set(), "exact": mode == "perfect"})
                if rdftype:
                    entry["types"].add(rdftype)
            if len([u for u, e in found.items() if self.kind_of_types(e["types"])]) >= self.settings["search_limit"]:
                break
        order = {k["name"]: i for i, k in enumerate(self.settings["kinds"])}
        seeds = []
        for uri, entry in found.items():
            kind = self.kind_of_types(entry["types"])
            if kind:
                seeds.append({**self.make_node(uri, kind, entry["label"], {}), "exact": entry["exact"]})
        seeds.sort(key=lambda s: (not s["exact"], len(s["label"]), order.get(s["kind"], 99), s["label"]))
        # 種にも年・属性・全体の件数を付ける（大きさを「全体の件数」にしたときのため）
        return self.enrich(seeds[: self.settings["search_limit"]])

    def client_config(self):
        """画面（templates/js/explore.js）に渡す設定"""
        s = self.settings
        return {
            "kinds": [{"name": k["name"], "shape": k.get("shape"), "color": k.get("color")} for k in s["kinds"]],
            "attrs": s["attrs"],
            "relations": [{"name": r["name"], "label": r["label"], "from": r["from"], "to": r["to"]}
                          for r in s["relations"]],
            "limit": s["limit"], "maxNodes": s["max_nodes"],
            "saveKind": s["save_kind"], "saveClass": s.get("save_class"),
        }


def local_name(uri):
    text = str(uri).rstrip("/#")
    return re.split(r"[/#]", text)[-1] or text


def quote_uri(uri):
    from urllib.parse import quote
    return quote(uri, safe="")


# --------------------------------------------------
# 画面
# --------------------------------------------------

def _json_for_script(data):
    import json
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_explore(explorer, seeds, *, q="", notice="", can_save=False, save_max=10000):
    """探索グラフのページの本文"""
    from html import escape
    settings = explorer.settings
    element_id = "kg-explore"
    payload = {
        "config": explorer.client_config(),
        "seeds": seeds,
        "q": q,
        "save": {"action": "/collections/save_uris", "max": int(save_max)} if can_save else None,
    }
    # 語と同じラベルのもの（なければすべて）を最初の種にする。ほかは左の欄で選んで加える
    exact = [sd for sd in seeds if sd.get("exact", True)]
    for sd in seeds:
        sd["start"] = sd in (exact or seeds)
    candidates = ""
    if q and len(seeds) > 1:
        items = "".join(
            f'<li><label><input type="checkbox" class="kg-explore-seed" value="{escape(s["id"])}"'
            f'{" checked" if s.get("start") else ""}> '
            f'{escape(s["label"])} <span class="kg-explore-kind">{escape(s["kind"])}</span></label></li>'
            for s in seeds)
        candidates = (f'<details class="kg-explore-candidates" open><summary>「{escape(q)}」で見つかった種（{len(seeds)}）'
                      f'</summary><ul>{items}</ul><p class="kg-explore-hint">チェックを付けると種に加わり、外すと図から消えます。</p></details>')
    describe = f'<p class="kg-explore-describe">{escape(settings["describe"])}</p>' if settings.get("describe") else ""
    notice_html = f'<p class="gadget-notice">{escape(notice)}</p>' if notice else ""
    return f"""
<div class="kg-explore" id="{element_id}">
  <aside class="kg-explore-side">
    <form class="kg-explore-search" action="/explore" method="GET">
      <input type="search" name="q" value="{escape(q)}" placeholder="種にする語・判例名など" />
      <button type="submit">種にする</button>
    </form>
    {describe}
    {notice_html}
    {candidates}
    <h3 class="kg-explore-head">たどった道</h3>
    <ol class="kg-explore-steps"></ol>
    <div class="kg-explore-stepbar">
      <button type="button" class="kg-explore-undo" disabled>1つ戻す</button>
      <button type="button" class="kg-explore-copy" title="この探索を再現する URL をコピーします">URL をコピー</button>
    </div>
    <h3 class="kg-explore-head">集める</h3>
    <div class="kg-explore-save"></div>
  </aside>
  <section class="kg-explore-main">
    <div class="kg-graph-toolbar">
      <span class="kg-graph-summary kg-explore-summary"></span>
      <span class="kg-graph-tools">
        <span class="kg-graph-encode"></span>
        <button type="button" class="kg-explore-relayout" title="全体を配置し直します（広げたときは、それまでの位置を動かしません）">配置し直す</button>
        <button type="button" class="kg-graph-fit">全体を表示</button>
        <button type="button" class="kg-explore-png">画像（PNG）</button>
      </span>
    </div>
    <div class="kg-graph-legend kg-explore-legend"></div>
    <div class="kg-explore-canvas-wrap">
      <div class="kg-graph kg-explore-canvas" id="{element_id}-cy"></div>
      <div class="kg-explore-busy" hidden>問い合わせています…</div>
      <div class="kg-explore-start" hidden>種を置きました。右の欄「次に広げられる関係」を押すと、その先のノードが加わります（ノードのダブルクリックでも広がります）。</div>
    </div>
    <p class="kg-explore-hint">ノードをクリックすると右に「次に広げられる関係」と件数が出ます。ダブルクリックで、いちばん上の関係を広げます。
    Shift を押しながらドラッグすると、囲んだノードを選べます（選んだ判例だけを保存・比べる）。</p>
  </section>
  <aside class="kg-explore-panel">
    <p class="kg-explore-hint">{"ノードを選んでください。" if seeds else "左上の欄に語（例: パワーハラスメント、民法709条、判例の事件名）を入れて「種にする」を押してください。"}</p>
  </aside>
  <script type="application/json" id="{element_id}-data">{_json_for_script(payload)}</script>
</div>
<script src="/templates/js/explore.js"></script>
<script>kgExplore("{element_id}");</script>
"""
