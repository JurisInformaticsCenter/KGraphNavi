#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      facets.py
##  Description:
##      ファセット（コレクションの絞り込み）の URL パラメータの解釈と、
##      絞り込み用の画面部品（フォーム・現在の条件・ページ送り）の生成
##
##  URL パラメータ
##      f.<name>=値            値の選択。同じ名前を繰り返すと OR
##      f.<name>.min=下限      範囲の下限
##      f.<name>.max=上限      範囲の上限
##      page=2                 ページ送り（1始まり）
##      tab=1                  タブ（0始まり）
##
##  Gadget に渡す params には、通常のパラメータ（最初の値）に加えて
##  次の予約キーが入る。
##      params["_facets"] = {"values": {name: [値, ...]}, "ranges": {name: {"min":…, "max":…}}}
##      params["_args"]   = [(key, value), ...]   URL パラメータそのもの（リンク生成用）
"""

from html import escape
from urllib.parse import urlencode, quote

from .render_utils import get_localname

FACETS_PARAM = "_facets"
ARGS_PARAM = "_args"
PATH_PARAM = "_path"
FACET_PREFIX = "f."
PAGE_PARAM = "page"
TAB_PARAM = "tab"


# --------------------------------------------------
# URL パラメータの解釈
# --------------------------------------------------

def request_params(args, path=""):
    """Flask の request.args（MultiDict）から Gadget に渡す params を作る。"""
    params = {}
    values = {}
    ranges = {}
    raw = []
    for key in args.keys():
        items = [value for value in args.getlist(key)]
        raw.extend((key, value) for value in items)
        non_empty = [value for value in items if value.strip() != ""]
        if key.startswith(FACET_PREFIX):
            rest = key[len(FACET_PREFIX):]
            if rest.endswith(".min") or rest.endswith(".max"):
                name, bound = rest.rsplit(".", 1)
                if name and non_empty:
                    ranges.setdefault(name, {})[bound] = non_empty[0].strip()
            elif rest and non_empty:
                # 重複を除き、順序は保つ
                values[rest] = list(dict.fromkeys(value.strip() for value in non_empty))
            continue
        if non_empty:
            params[key] = non_empty[0]
    params[FACETS_PARAM] = {"values": values, "ranges": ranges}
    params[ARGS_PARAM] = raw
    params[PATH_PARAM] = path
    return params


def facet_selection(params):
    """params からファセットの選択状態を取り出す。"""
    selection = (params or {}).get(FACETS_PARAM) or {}
    return selection.get("values", {}), selection.get("ranges", {})


def page_number(params):
    """ページ番号（1以上）"""
    try:
        return max(1, int((params or {}).get(PAGE_PARAM, 1)))
    except (TypeError, ValueError):
        return 1


def is_reserved(key):
    return key in (FACETS_PARAM, ARGS_PARAM, PATH_PARAM)


# --------------------------------------------------
# URL の生成
# --------------------------------------------------

def _args(params):
    return list((params or {}).get(ARGS_PARAM) or [])


def make_url(params, *, drop=(), drop_items=(), add=()):
    """現在の URL パラメータを元に、一部を外したり加えたりした URL を返す。

    drop:       外すキー（すべての値）
    drop_items: 外す (キー, 値) の組
    add:        加える (キー, 値) の組
    ページ送り（page）は条件が変わるので常に外す。
    """
    drop = set(drop) | {PAGE_PARAM}
    drop_items = set(drop_items)
    items = [
        (key, value)
        for key, value in _args(params)
        if key not in drop and (key, value) not in drop_items
    ]
    items.extend(add)
    path = (params or {}).get(PATH_PARAM) or ""
    return f"{path}?{urlencode(items)}" if items else (path or "?")


def page_url(params, page):
    items = [(k, v) for k, v in _args(params) if k != PAGE_PARAM]
    if page > 1:
        items.append((PAGE_PARAM, str(page)))
    path = (params or {}).get(PATH_PARAM) or ""
    return f"{path}?{urlencode(items)}"


def hidden_inputs(params, *, exclude_keys=()):
    """現在の URL パラメータを hidden input として返す（フォーム送信で引き継ぐため）。"""
    exclude = set(exclude_keys) | {PAGE_PARAM}
    return "\n".join(
        f'<input type="hidden" name="{escape(key)}" value="{escape(value)}">'
        for key, value in _args(params)
        if key not in exclude
    )


# --------------------------------------------------
# 表示
# --------------------------------------------------

def value_label(value):
    """値の表示名（IRI ならローカル名）"""
    text = str(value)
    if "://" in text:
        # ローカル名の _ は空白にする（DBpedia などの慣例）
        return (get_localname(text) or text).replace("_", " ")
    return text


def facet_label(definition, name):
    return (definition or {}).get("label") or name


def render_value_facet(content, height=None):
    """値の選択ファセットをフォームとして描画する。

    content = {
        "name": ファセット名, "label": 見出し,
        "candidates": [{"value", "label", "count", "type"}, ...],
        "selected": [値, ...],
        "params": Gadget に渡された params,
    }
    """
    name = content["name"]
    field = FACET_PREFIX + name
    params = content.get("params") or {}
    selected = list(content.get("selected") or [])
    candidates = list(content.get("candidates") or [])
    # 選択中の値は件数 0 でも候補に残す
    shown = {candidate["value"] for candidate in candidates}
    for value in selected:
        if value not in shown:
            candidates.append({"value": value, "label": value_label(value), "count": 0})
    style = f' style="max-height:{int(height)}px"' if height else ""
    items = []
    for candidate in candidates:
        value = str(candidate["value"])
        label = candidate.get("label") or value
        if label == value:
            label = value_label(value)
        checked = " checked" if value in selected else ""
        items.append(
            '<li><label class="facet-item">'
            f'<input type="checkbox" name="{escape(field)}" value="{escape(value)}"{checked}>'
            f'<span class="facet-label" title="{escape(value)}">{escape(str(label))}</span>'
            f'<span class="facet-count">{int(candidate.get("count", 0)):,}</span>'
            '</label></li>'
        )
    if not items:
        items.append('<li class="facet-empty">候補がありません</li>')
    clear = ""
    if selected:
        clear = (
            f'<a class="facet-clear" href="{escape(make_url(params, drop={field}))}">'
            'クリア</a>'
        )
    return (
        f'<form class="facet" method="GET" action="{escape(params.get(PATH_PARAM) or "")}" '
        f'data-facet-name="{escape(name)}">\n'
        f'{hidden_inputs(params, exclude_keys={field})}\n'
        f'<ul class="facet-items"{style}>\n' + "\n".join(items) + "\n</ul>\n"
        '<div class="facet-actions">'
        '<button type="submit" class="facet-apply">適用</button>'
        f'{clear}</div>\n'
        "</form>"
    )


def render_conditions(params, definitions, count=None):
    """「現在の条件」と件数を描画する。

    definitions: ファセット名 → ファセット定義（見出しの取得用）
    """
    values, ranges = facet_selection(params)
    chips = []
    for name, selected in values.items():
        field = FACET_PREFIX + name
        label = facet_label(definitions.get(name), name)
        for value in selected:
            url = make_url(params, drop_items={(field, value)})
            chips.append(
                '<span class="condition">'
                f'<span class="condition-name">{escape(label)}:</span> '
                f'<span class="condition-value" title="{escape(value)}">{escape(value_label(value))}</span>'
                f'<a class="condition-remove" href="{escape(url)}" title="この条件を外す">✕</a>'
                "</span>"
            )
    for name, bounds in ranges.items():
        label = facet_label(definitions.get(name), name)
        low = bounds.get("min", "")
        high = bounds.get("max", "")
        url = make_url(params, drop={f"{FACET_PREFIX}{name}.min", f"{FACET_PREFIX}{name}.max"})
        chips.append(
            '<span class="condition">'
            f'<span class="condition-name">{escape(label)}:</span> '
            f'<span class="condition-value">{escape(str(low))}–{escape(str(high))}</span>'
            f'<a class="condition-remove" href="{escape(url)}" title="この条件を外す">✕</a>'
            "</span>"
        )
    parts = ['<div class="collection-header">']
    if count is not None:
        parts.append(f'<span class="collection-count">{int(count):,} 件</span>')
    if chips:
        parts.append('<span class="conditions">' + " ".join(chips) + "</span>")
        facet_keys = {FACET_PREFIX + name for name in values} | {
            f"{FACET_PREFIX}{name}.{bound}" for name in ranges for bound in ("min", "max")
        }
        parts.append(
            f'<a class="conditions-clear" href="{escape(make_url(params, drop=facet_keys))}">'
            "すべての条件を外す</a>"
        )
    parts.append("</div>")
    return "\n".join(parts)


def render_pager(params, page, page_size, total):
    """ページ送りを描画する。"""
    if total is None or total <= page_size:
        return ""
    last = (total + page_size - 1) // page_size
    page = min(page, last)
    start = (page - 1) * page_size + 1
    end = min(page * page_size, total)
    links = []
    if page > 1:
        links.append(f'<a href="{escape(page_url(params, 1))}">« 最初</a>')
        links.append(f'<a href="{escape(page_url(params, page - 1))}">‹ 前へ</a>')
    links.append(f'<span class="pager-status">{start:,}–{end:,} / {total:,} 件</span>')
    if page < last:
        links.append(f'<a href="{escape(page_url(params, page + 1))}">次へ ›</a>')
        links.append(f'<a href="{escape(page_url(params, last))}">最後 »</a>')
    return '<nav class="pager">' + " ".join(links) + "</nav>"


def resource_url(uri):
    return f"/resource?uri={quote(str(uri), safe='')}"
