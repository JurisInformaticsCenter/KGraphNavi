#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      compare.py
##  Author:
##      Fumihito NISHINO       nisino@nii.ac.jp
##  Description:
##      少数（2〜4）のリソースを縦の列に並べて比べる（/compare。2026.10.26）
##
##  /compare?uri=A&uri=B[&uri=C…]      リソースを並べる
##  /compare?saved=<名前>               保存したコレクション（要素が上限以下のとき）
##  /compare?from=<ガジェット>&uri=X    ガジェットの一覧（compare.var の列）と X を並べる（例: 上訴審・原審）
##  &view=<名前>                        比べ方（設定の compare: の name）。省略時は最初のリソースのクラスで選ぶ
##
##  比べ方（設定ファイルのアプリケーション設定 compare:）
##    - name: 判例
##      types: [caselawo:CaseLawDocument, …]   このクラスのリソースに使う
##      sort: "select ?k where {…$uri…}"       列の並び順（例: 判決日。古い順）
##      rows:
##        - gadget: CaseLawInfo                各列にガジェットの表（columns で列を絞れる）
##          columns: [caseno, court, …]
##        - gadget: Legislation                ガジェットの key の値で行をそろえた表（どの列にあるか）
##          align: legislation                 行をそろえる変数
##          label: label                       行の見出しの変数（省略時は align の値）
##          value: status                      セルに出す変数（省略時は ✓）
##  比べ方が無いクラスでは、組み込みの比べ方（プロパティごとに値を並べる）を使う。
"""

import logging
from html import escape
from urllib.parse import urlencode, quote

from .render_utils import get_raw_value, get_localname, get_highest_priority_item

logger = logging.getLogger(__name__)

COMPARE_MAX = 4
BUILTIN_VIEW = "_properties"
ROW_KEYS = {"gadget", "title", "columns", "align", "label", "value"}
VIEW_KEYS = {"name", "title", "types", "sort", "rows", "max"}


def compare_settings(conf):
    """設定の compare:（比べ方のリスト。辞書1つでもよい）を確かめる"""
    if isinstance(conf, dict):
        conf = [conf]
    if not isinstance(conf, list):
        raise ValueError("compare は比べ方のリストで書いてください")
    views = []
    for view in conf:
        if not isinstance(view, dict) or not view.get("name"):
            raise ValueError(f"compare の比べ方に name がありません: {view!r}")
        unknown = set(view) - VIEW_KEYS
        if unknown:
            raise ValueError(f"compare（{view['name']}）の未知のキー: {sorted(unknown)}")
        rows = view.get("rows") or []
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"compare（{view['name']}）に rows がありません")
        norm_rows = []
        for row in rows:
            if isinstance(row, str):
                row = {"gadget": row}
            if not isinstance(row, dict) or not row.get("gadget"):
                raise ValueError(f"compare（{view['name']}）の rows には gadget が要ります: {row!r}")
            unknown = set(row) - ROW_KEYS
            if unknown:
                raise ValueError(f"compare（{view['name']}）の rows の未知のキー: {sorted(unknown)}")
            norm_rows.append(dict(row))
        types = view.get("types") or []
        if isinstance(types, str):
            types = [types]
        views.append({**view, "types": list(types), "rows": norm_rows,
                      "max": int(view.get("max") or COMPARE_MAX)})
    return views


def resolve_types(views, expand):
    """types の接頭辞付きの名前を IRI にする（expand は app.expand_prefixed と prefixes）"""
    for view in views:
        view["types"] = [expand(t) for t in view["types"]]


def choose_view(application, uris, name=None):
    """比べ方を選ぶ。name が無ければ、最初のリソースの（優先する）クラスを types に持つもの"""
    views = application.compare_views or []
    if name:
        if name == BUILTIN_VIEW:
            return None
        for view in views:
            if view["name"] == name:
                return view
        raise ValueError(f"比べ方 {name} がありません")
    if not views or not uris:
        return None
    rdftypes = application.sparql_client.get_target(uris[0], "a") or []
    if not rdftypes:
        return None
    for t in [get_highest_priority_item(rdftypes, application.priority_list)] + list(rdftypes):
        for view in views:
            if t in view["types"]:
                return view
    return None


def items_from_args(application, args):
    """URL の引数から並べるリソース（URI のリスト）を作る"""
    uris = [u for u in args.getlist("uri") if u]
    if args.get("saved"):
        store = application.saved_store
        if store is None:
            raise ValueError("保存したコレクションがありません（saved_collections_dir）")
        data = store.get(args["saved"])     # 無ければ CollectionError
        return list(data.get("uris") or [])
    if args.get("from"):
        name, path, gadget = application.resolve_gadget(args["from"])
        conf = getattr(gadget, "compare_config", None) if gadget else None
        if not conf:
            raise ValueError(f"ガジェット {args['from']} には compare（比べる）の設定がありません")
        if not uris:
            raise ValueError("uri がありません（/compare?from=ガジェット&uri=xxx）")
        uri = uris[0]
        content = gadget.extract(uri, application=application) or []
        found = []
        for rec in content:
            value = get_raw_value(rec.get(conf["var"])) if isinstance(rec, dict) else ""
            if value and value not in found:
                found.append(value)
        return ([uri] if conf.get("self", True) else []) + [u for u in found if u != uri]
    return uris


def sort_items(application, uris, view):
    """比べ方の sort（$uri の並べるキーを返す SPARQL）で並べる。キーの無いものは後ろ"""
    query = view.get("sort") if view else None
    if not query:
        return uris
    keys = {}
    for uri in uris:
        try:
            values = application.sparql_client.query(query, params={"uri": uri}) or []
        except Exception:      # 並べられなくても比べる
            logger.exception("compare sort failed: %s", uri)
            values = []
        vals = [get_raw_value(v) for rec in values for v in rec.values()]
        keys[uri] = min(vals) if vals else None
    return sorted(uris, key=lambda u: (keys[u] is None, keys[u] or "", uris.index(u)))


def item_label(application, uri):
    label_predicate = application.label_predicate or "rdfs:label"
    try:
        label = application.sparql_client.query_value(
            f"select ?l where {{ $uri {label_predicate} ?l }} limit 1", "l", uri=uri)
    except Exception:
        label = None
    return label or get_localname(uri)


def resource_link(uri, text=None):
    return f'<a href="/resource?uri={quote(uri, safe="")}">{escape(text or get_localname(uri))}</a>'


# 各列にガジェットの表
def gadget_cell(application, row, uri):
    from .app import Gadget, move_focus      # app が compare を読むので、ここで読む
    name, path, gadget = application.resolve_gadget(row["gadget"])
    if gadget is None:
        return f'<p class="gadget-empty">ガジェット {escape(row["gadget"])} がありません</p>'
    target = move_focus(uri, path, application.sparql_client) if path else uri
    if target is None:
        return '<p class="gadget-empty">該当するデータがありません</p>'
    if row.get("columns") and isinstance(gadget.show_method.get("columns"), list):
        wanted = list(row["columns"])
        cols = [c for c in gadget.show_method["columns"] if c.get("id") in wanted]
        cols.sort(key=lambda c: wanted.index(c["id"]))
        g = Gadget(gadget.extract_method, {**gadget.show_method, "columns": cols}, gadget.height, gadget.title)
        g.sparql_client = gadget.sparql_client
        gadget = g
    try:
        content = gadget.extract(target, application=application)
        if not content:
            return '<p class="gadget-empty">該当するデータがありません</p>'
        return gadget.show(content)
    except Exception as e:    # 1つの列の失敗で全体を止めない
        logger.exception("compare gadget %s failed for %s", row["gadget"], uri)
        return f'<p class="saved-error">取得できませんでした: {escape(str(e))[:200]}</p>'


# ガジェットの値で行をそろえる
def align_data(application, row, uris):
    """各列の {キー: (見出し, セルの値, キーがURIか)} とキーの順"""
    from .app import move_focus
    name, path, gadget = application.resolve_gadget(row["gadget"])
    if gadget is None:
        raise ValueError(f"ガジェット {row['gadget']} がありません")
    key_var, label_var, value_var = row["align"], row.get("label"), row.get("value")
    order, columns = [], []
    for uri in uris:
        target = move_focus(uri, path, application.sparql_client) if path else uri
        content = gadget.extract(target, application=application) if target else []
        cells = {}
        for rec in content or []:
            if not isinstance(rec, dict) or key_var not in rec:
                continue
            key = get_raw_value(rec[key_var])
            is_uri = isinstance(rec[key_var], dict) and rec[key_var].get("type") == "uri"
            label = get_raw_value(rec.get(label_var)) if label_var and rec.get(label_var) else ""
            value = get_raw_value(rec.get(value_var)) if value_var and rec.get(value_var) else ""
            if value and rec[value_var].get("type") == "uri":     # 役割などのURIはローカル名で
                value = get_localname(value)
            if key in cells:      # 同じキーの行が複数あれば値をつなぐ
                old = cells[key]
                if value and value not in old[1].split("、"):
                    cells[key] = (old[0], "、".join(x for x in (old[1], value) if x), is_uri)
                continue
            cells[key] = (label, value, is_uri)
            if key not in order:
                order.append(key)
        columns.append(cells)
    return order, columns


def align_table(application, row, uris):
    try:
        order, columns = align_data(application, row, uris)
    except Exception as e:
        logger.exception("compare align %s failed", row["gadget"])
        return f'<p class="saved-error">取得できませんでした: {escape(str(e))[:200]}</p>'
    if not order:
        return '<p class="gadget-empty">該当するデータがありません</p>'
    n = len(uris)

    def count(key):
        return sum(1 for c in columns if key in c)
    # 全部にあるものを先に、次に多くの列にあるもの（元の順を保つ）
    order.sort(key=lambda k: -count(k))
    common = sum(1 for k in order if count(k) == n)
    trs = []
    for key in order:
        label, is_uri = "", False
        for c in columns:
            if key in c:
                label = label or c[key][0]
                is_uri = is_uri or c[key][2]
        head = resource_link(key, label or None) if is_uri else escape(label or key)
        tds = []
        for c in columns:
            if key in c:
                tds.append(f'<td class="cmp-has">{escape(c[key][1]) if c[key][1] else "✓"}</td>')
            else:
                tds.append('<td class="cmp-none">—</td>')
        cls = "cmp-same" if count(key) == n else "cmp-diff"
        trs.append(f'<tr class="{cls}"><th>{head}</th>{"".join(tds)}</tr>')
    per = [sum(1 for k in c if count(k) < n) for c in columns]
    summary = (f'<p class="cmp-summary">共通 {common:,} 件・違い {len(order) - common:,} 件'
               f'（列ごとの違い: {" / ".join(f"{p:,}" for p in per)}）</p>')
    return summary + f'<table class="cmp-align"><tbody>{"".join(trs)}</tbody></table>'


# 組み込みの比べ方: プロパティごとに値を並べる
BUILTIN_QUERY = """select ?p ?o ?ol where {{ $uri ?p ?o .
  OPTIONAL {{ ?o {label} ?ol }} }} limit 2000"""


def builtin_rows(application, uris):
    label_predicate = application.label_predicate or "rdfs:label"
    query = BUILTIN_QUERY.format(label=label_predicate)
    order, columns = [], []
    for uri in uris:
        props = {}
        try:
            result = application.sparql_client.query(query, params={"uri": uri}) or []
        except Exception as e:
            logger.exception("compare builtin failed: %s", uri)
            result = []
        for rec in result:
            p = get_raw_value(rec.get("p"))
            o = rec.get("o") or {}
            value = (o.get("value", ""), o.get("type") == "uri", get_raw_value(rec.get("ol")))
            props.setdefault(p, {})
            if value[0] not in props[p]:
                props[p][value[0]] = value
            if p not in order:
                order.append(p)
        columns.append(props)
    trs = []
    n = len(uris)
    for p in order:
        sets = [frozenset(c.get(p, {})) for c in columns]
        same = all(s == sets[0] for s in sets) and bool(sets[0])
        tds = []
        for c in columns:
            vals = list(c.get(p, {}).values())
            if not vals:
                tds.append('<td class="cmp-none">—</td>')
                continue
            shown = []
            for v, is_uri, label in vals[:30]:
                common = all(v in x for x in sets)
                text = resource_link(v, label or None) if is_uri else escape(v[:400] + ("…" if len(v) > 400 else ""))
                shown.append(f'<li class="{"cmp-v-same" if common else "cmp-v-diff"}">{text}</li>')
            more = f'<li>ほか {len(vals) - 30:,} 件</li>' if len(vals) > 30 else ""
            tds.append(f'<td><ul class="cmp-values">{"".join(shown)}{more}</ul></td>')
        trs.append(f'<tr class="{"cmp-same" if same else "cmp-diff"}"><th title="{escape(p)}">'
                   f'{escape(get_localname(p))}</th>{"".join(tds)}</tr>')
    if not trs:
        return '<p class="gadget-empty">該当するデータがありません</p>'
    width = f"{90 / n:.1f}%"
    cols = "".join(f'<col style="width:{width}">' for _ in uris)
    return (f'<table class="cmp-align cmp-props"><colgroup><col style="width:10%">{cols}</colgroup>'
            f'<tbody>{"".join(trs)}</tbody></table>')


STYLE = """<style>
.cmp-heads { position: sticky; top: 0; z-index: 3; }
.cmp-grid { display: grid; gap: 8px; align-items: start; }
.cmp-grid > .cmp-head { background: #f4f6f8; border-bottom: 2px solid #8aa; padding: 4px 6px; font-weight: bold; z-index: 2; }
.cmp-grid > .cmp-cell { overflow-x: auto; min-width: 0; border-left: 1px solid #dde; padding-left: 4px; }
.cmp-row-title { grid-column: 1 / -1; margin: 14px 0 2px; font-size: 1.05em; border-bottom: 1px solid #ccd; }
table.cmp-align { border-collapse: collapse; width: 100%; font-size: 0.92em; }
table.cmp-align th, table.cmp-align td { border: 1px solid #dde; padding: 2px 6px; vertical-align: top; text-align: left; }
table.cmp-align th { background: #f7f7fa; font-weight: normal; }
table.cmp-align thead th { font-weight: bold; }
tr.cmp-diff > th { background: #fff4d6; }
td.cmp-none { color: #aaa; text-align: center; }
td.cmp-has { background: #eef7ee; }
tr.cmp-same td.cmp-has { background: inherit; }
ul.cmp-values { margin: 0; padding-left: 1.1em; }
li.cmp-v-diff { background: #fff4d6; }
.cmp-summary { margin: 2px 0 4px; color: #555; font-size: 0.9em; }
body.cmp-only-diff tr.cmp-same { display: none; }
.cmp-controls { margin: 6px 0; }
</style>"""


def render_compare(application, uris, view, args=None):
    """並べたページの本文"""
    n = len(uris)
    labels = [item_label(application, u) for u in uris]
    views = application.compare_views or []
    options = "".join(
        f'<option value="{escape(v["name"])}"{" selected" if view and v["name"] == view["name"] else ""}>'
        f'{escape(v.get("title") or v["name"])}</option>' for v in views)
    options += (f'<option value="{BUILTIN_VIEW}"{" selected" if view is None else ""}>'
                'プロパティごと（組み込み）</option>')
    hidden = "".join(f'<input type="hidden" name="uri" value="{escape(u)}">' for u in uris)
    controls = (
        '<form class="cmp-controls" method="GET" action="/compare">'
        f'{hidden}比べ方 <select name="view" onchange="this.form.submit()">{options}</select> '
        '<label><input type="checkbox" onchange="document.body.classList.toggle(\'cmp-only-diff\', this.checked)">'
        ' 違うところだけ（行をそろえた表）</label></form>'
    )
    head_row = "".join(f'<div class="cmp-head">{chr(0x2460 + i)} {resource_link(u, labels[i])}</div>'
                       for i, u in enumerate(uris))
    parts = []
    if view is None:
        header = "".join(f'<th>{chr(0x2460 + i)} {resource_link(u, labels[i])}</th>' for i, u in enumerate(uris))
        body = builtin_rows(application, uris).replace(
            "<tbody>", f'<thead><tr><th>プロパティ</th>{header}</tr></thead><tbody>', 1)
        parts.append(body)
    else:
        for row in view["rows"]:
            name, _path, gadget = application.resolve_gadget(row["gadget"])
            title = row.get("title") or (application.gadget_title(name, gadget) if gadget else name)
            if row.get("align"):
                header = "".join(f'<th>{chr(0x2460 + i)}</th>' for i in range(n))
                table = align_table(application, row, uris).replace(
                    '<table class="cmp-align"><tbody>',
                    f'<table class="cmp-align"><thead><tr><th></th>{header}</tr></thead><tbody>', 1)
                parts.append(f'<h3 class="cmp-row-title">{escape(title)}</h3>{table}')
            else:
                cells = "".join(f'<div class="cmp-cell">{gadget_cell(application, row, u)}</div>' for u in uris)
                parts.append(f'<div class="cmp-grid" style="grid-template-columns: repeat({n}, minmax(0, 1fr))">'
                             f'<h3 class="cmp-row-title">{escape(title)}</h3>{cells}</div>')
    grid_head = (f'<div class="cmp-grid cmp-heads" style="grid-template-columns: repeat({n}, minmax(0, 1fr))">'
                 f'{head_row}</div>')
    return f'{STYLE}<div class="container cmp-wrap">{controls}{grid_head}{"".join(parts)}</div>'


def compare_url(uris, view=None):
    query = [("uri", u) for u in uris]
    if view:
        query.append(("view", view))
    return "/compare?" + urlencode(query)
