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
##      f.<name>.match=all     値の組み合わせ（any: いずれか〔既定〕、all: すべて）
##      f.<name>.search=語     候補の検索（絞り込みの条件にはならない）
##      q=語                   検索語（ラベルに語を含む。空白で区切ると、すべてを含む。2026.10.19）
##      mode=perfect           検索語と一致するラベル（完全一致）
##      page=2                 ページ送り（1始まり）
##      tab=1                  タブ（0始まり）
##
##  Gadget に渡す params には、通常のパラメータ（最初の値）に加えて
##  次の予約キーが入る。
##      params["_facets"] = {"values": {name: [値, ...]}, "ranges": {name: {"min":…, "max":…}}}
##      params["_args"]   = [(key, value), ...]   URL パラメータそのもの（リンク生成用）
"""

import collections
import math
from decimal import Decimal
from html import escape
from urllib.parse import urlencode, quote

from .render_utils import get_localname

FACETS_PARAM = "_facets"
ARGS_PARAM = "_args"
PATH_PARAM = "_path"
FACET_PREFIX = "f."
# f.<name>.<option> のオプション（絞り込みの値ではないもの）
FACET_OPTIONS = (".match", ".search")
PAGE_PARAM = "page"
SEARCH_PARAM = "q"
SEARCH_MODE_PARAM = "mode"
TAB_PARAM = "tab"
RANK_PAGE_PARAM = "rpage"   # 順位表のページ送り（要素の一覧の page と分ける。2026.10.20）


# --------------------------------------------------
# URL パラメータの解釈
# --------------------------------------------------

def request_params(args, path=""):
    """Flask の request.args（MultiDict）から Gadget に渡す params を作る。"""
    params = {}
    values = {}
    ranges = {}
    options = {}
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
            elif rest.endswith(FACET_OPTIONS):
                name, option = rest.rsplit(".", 1)
                if name and non_empty:
                    options.setdefault(name, {})[option] = non_empty[0].strip()
            elif rest and non_empty:
                # 重複を除き、順序は保つ
                values[rest] = list(dict.fromkeys(value.strip() for value in non_empty))
            continue
        if non_empty:
            params[key] = non_empty[0]
    params[FACETS_PARAM] = {"values": values, "ranges": ranges, "options": options}
    params[ARGS_PARAM] = raw
    params[PATH_PARAM] = path
    return params


def facet_selection(params):
    """params からファセットの選択状態を取り出す。"""
    selection = (params or {}).get(FACETS_PARAM) or {}
    return selection.get("values", {}), selection.get("ranges", {})


def facet_option(params, name, option, default=None):
    """ファセットのオプション（f.<name>.match / .search）の値"""
    selection = (params or {}).get(FACETS_PARAM) or {}
    return (selection.get("options", {}).get(name) or {}).get(option, default)


def match_mode(definition, params, name):
    """値の組み合わせ方（any / all）。設定の match が selectable なら URL の指定に従う。"""
    match = (definition or {}).get("match", "any")
    if match == "selectable":
        return "all" if facet_option(params, name, "match") == "all" else "any"
    return "all" if match == "all" else "any"


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


def namespace_hint(value):
    """IRI の名前空間を短く示す語（http://lod4all.net/law/ontology/Term → law、http://ds.rois.ac.jp/caselaw/ontology/Term → caselaw）"""
    text = str(value).split("#")[0].rstrip("/")
    parts = [p for p in text.split("://", 1)[-1].split("/")[1:-1] if p not in ("ontology", "property", "resource", "ns")]
    return parts[-1] if parts else text.split("://", 1)[-1].split("/")[0]


def facet_label(definition, name):
    return (definition or {}).get("label") or name


def render_value_facet(content, height=None):
    """値の選択ファセットをフォームとして描画する。

    content = {
        "name": ファセット名, "label": 見出し,
        "candidates": [{"value", "label", "count", "type"}, ...],
        "selected": [値, ...],
        "params": Gadget に渡された params,
        "match": "any" | "all", "selectable_match": 組み合わせを画面で切り替えるか,
        "searchable": 候補の検索欄を出すか, "search": 検索語,
        "too_many": 要素が多いため上位の候補を出していないか,
    }
    """
    name = content["name"]
    field = FACET_PREFIX + name
    match_field = f"{field}.match"
    search_field = f"{field}.search"
    params = content.get("params") or {}
    selected = list(content.get("selected") or [])
    candidates = list(content.get("candidates") or [])
    by_value = {str(candidate["value"]): candidate for candidate in candidates}
    # 選択中の値を先頭に（候補になければ件数なしで）、その後に他の候補
    ordered = [by_value.get(value) or {"value": value, "count": None} for value in selected]
    ordered += [c for c in candidates if str(c["value"]) not in selected]
    style = f' style="max-height:{int(height)}px"' if height else ""
    items = []

    def shown(candidate):
        value = str(candidate["value"])
        label = candidate.get("label") or value
        return value_label(value) if label == value else label

    # 表示名が同じになる別の値（caselawo:Term と lawo:Term がどちらも「Term」）は、名前空間を添えて区別する（2026.10.23）
    same = collections.Counter(shown(c) for c in ordered)
    for candidate in ordered:
        value = str(candidate["value"])
        label = shown(candidate)
        if same[label] > 1 and "://" in value:
            label = f"{label}（{namespace_hint(value)}）"
        checked = " checked" if value in selected else ""
        count = candidate.get("count")
        count_text = f"{int(count):,}" if count is not None else ""
        items.append(
            '<li><label class="facet-item">'
            f'<input type="checkbox" name="{escape(field)}" value="{escape(value)}"{checked}>'
            f'<span class="facet-label" title="{escape(value)}">{escape(str(label))}</span>'
            f'<span class="facet-count">{count_text}</span>'
            '</label></li>'
        )
    search = content.get("search") or ""
    if content.get("too_many") and not search:
        items.append(
            '<li class="facet-empty">件数が多いため候補を表示していません。'
            '下の検索欄で探してください。</li>'
        )
    elif search and not candidates:
        items.append(f'<li class="facet-empty">「{escape(search)}」を含む候補はありません</li>')
    elif not items:
        items.append('<li class="facet-empty">候補がありません</li>')
    search_box = ""
    if content.get("searchable"):
        clear_search = ""
        if search:
            clear_search = (
                f'<a class="facet-clear" href="{escape(make_url(params, drop={search_field}))}">'
                "検索をやめる</a>"
            )
        search_box = (
            '<div class="facet-search">'
            f'<input type="search" name="{escape(search_field)}" value="{escape(search)}" '
            f'placeholder="{escape(content.get("label") or name)}を検索" aria-label="候補を検索">'
            '<button type="submit" class="facet-search-button">検索</button>'
            f"{clear_search}</div>\n"
        )
    match_box = ""
    if content.get("selectable_match"):
        match = content.get("match", "any")
        match_box = (
            '<div class="facet-match">'
            f'<label><input type="radio" name="{escape(match_field)}" value="any"'
            f'{" checked" if match != "all" else ""}>いずれかを含む</label>'
            f'<label><input type="radio" name="{escape(match_field)}" value="all"'
            f'{" checked" if match == "all" else ""}>すべて含む</label>'
            "</div>\n"
        )
    clear = ""
    if selected:
        clear = (
            f'<a class="facet-clear" href="{escape(make_url(params, drop={field, match_field}))}">'
            'クリア</a>'
        )
    return (
        f'<form class="facet" method="GET" action="{escape(params.get(PATH_PARAM) or "")}" '
        f'data-facet-name="{escape(name)}">\n'
        f'{hidden_inputs(params, exclude_keys={field, match_field, search_field})}\n'
        f"{search_box}"
        f'<ul class="facet-items"{style}>\n' + "\n".join(items) + "\n</ul>\n"
        f"{match_box}"
        '<div class="facet-actions">'
        '<button type="submit" class="facet-apply">適用</button>'
        f'{clear}</div>\n'
        "</form>"
    )


def range_text(low, high):
    """範囲の表示（片側だけなら「以上」「以下」）"""
    if low and high:
        return f"{low}–{high}"
    if low:
        return f"{low} 以上"
    return f"{high} 以下"


def render_conditions(params, definitions, count=None, labels=None):
    """「現在の条件」と件数を描画する。

    definitions: ファセット名 → ファセット定義（見出しの取得用）
    """
    values, ranges = facet_selection(params)
    chips = []
    text = (params or {}).get(SEARCH_PARAM)
    if isinstance(text, str) and text.strip():
        # 検索語の条件。検索結果のページ（/search）で外すとトップページへ
        if (params or {}).get(PATH_PARAM) == "/search":
            url = "/"
        else:
            url = make_url(params, drop={SEARCH_PARAM, SEARCH_MODE_PARAM})
        exact = (params or {}).get(SEARCH_MODE_PARAM) == "perfect"
        chips.append(
            '<span class="condition">'
            f'<span class="condition-name">{"検索語（完全一致）" if exact else "検索語"}:</span> '
            f'<span class="condition-value">{escape(text)}</span>'
            f'<a class="condition-remove" href="{escape(url)}" title="この条件を外す">✕</a>'
            "</span>"
        )
    for name, selected in values.items():
        field = FACET_PREFIX + name
        label = facet_label(definitions.get(name), name)
        if len(selected) > 1 and match_mode(definitions.get(name), params, name) == "all":
            label += "（すべて）"
        for value in selected:
            url = make_url(params, drop_items={(field, value)})
            chips.append(
                '<span class="condition">'
                f'<span class="condition-name">{escape(label)}:</span> '
                f'<span class="condition-value" title="{escape(value)}">'
                f'{escape((labels or {}).get(value) or value_label(value))}</span>'
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
            f'<span class="condition-value">{escape(range_text(low, high))}</span>'
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
        if (params or {}).get(PATH_PARAM) != "/search":
            facet_keys |= {SEARCH_PARAM, SEARCH_MODE_PARAM}
        parts.append(
            f'<a class="conditions-clear" href="{escape(make_url(params, drop=facet_keys))}">'
            "すべての条件を外す</a>"
        )
    parts.append("</div>")
    return "\n".join(parts)


def render_search_box(params):
    """コレクションの中を検索語で絞り込む入力欄（q）。ほかの条件は引き継ぐ（2026.10.19）"""
    params = params or {}
    text = params.get(SEARCH_PARAM) or ""
    exact = params.get(SEARCH_MODE_PARAM) == "perfect"
    path = params.get(PATH_PARAM) or ""
    return (
        f'<form class="collection-search" method="GET" action="{escape(path)}">'
        f'{hidden_inputs(params, exclude_keys={SEARCH_PARAM, SEARCH_MODE_PARAM})}'
        f'<input type="search" name="{SEARCH_PARAM}" value="{escape(text)}" placeholder="この中を検索（ラベル）">'
        f'<label><input type="checkbox" name="{SEARCH_MODE_PARAM}" value="perfect"{" checked" if exact else ""}>完全一致</label>'
        '<button type="submit">絞り込む</button>'
        '</form>'
    )


def current_url(params):
    """今のページの URL（ページ送りを除く）"""
    params = params or {}
    items = [(k, v) for k, v in _args(params) if k != PAGE_PARAM]
    path = params.get(PATH_PARAM) or ""
    return f"{path}?{urlencode(items)}" if items else path


def render_save_form(params):
    """今のコレクションに名前を付けて保存するフォーム（POST /collections/save。2026.10.19）"""
    return (
        '<form class="collection-save" method="POST" action="/collections/save">'
        f'<input type="hidden" name="source" value="{escape(current_url(params))}">'
        '<input type="text" name="name" required maxlength="60" placeholder="名前">'
        '<label><input type="checkbox" name="overwrite" value="1">上書き</label>'
        '<button type="submit">名前を付けて保存</button>'
        '</form>'
    )


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


def rank_page_url(params, page):
    """順位表のページ送りの URL（要素の一覧の page はそのまま残す）"""
    items = [(k, v) for k, v in _args(params) if k != RANK_PAGE_PARAM]
    if page > 1:
        items.append((RANK_PAGE_PARAM, str(page)))
    path = (params or {}).get(PATH_PARAM) or ""
    return f"{path}?{urlencode(items)}"


def render_rank(content, show_method=None, chart_html=""):
    """順位表（get.type: rank）を描画する（2026.10.20）。

    content = {
        "facet": ファセット名, "facet_label": まとめる値の見出し,
        "rows": [{"rank", "value", "label", "count", "type", "detail": {列: 値}}, ...],
        "total": 値の種類の数, "page": ページ番号, "page_size": 1ページの行数,
        "params": Gadget に渡された params, "list_tab": 要素の一覧のタブの番号（件数のリンク先）,
    }
    件数は、その値で絞り込んだ要素の一覧（コレクション）へのリンクにする。
    """
    show_method = show_method or {}
    params = content.get("params") or {}
    rows = content.get("rows") or []
    facet = content.get("facet")
    columns = show_method.get("columns") or []
    count_label = show_method.get("label") or "件数"
    value_label_text = show_method.get("value_label") or content.get("facet_label") or "値"
    total = content.get("total") or 0
    page = content.get("page") or 1
    page_size = content.get("page_size") or len(rows) or 1
    list_tab = content.get("list_tab")
    ratio = content.get("measure") == "ratio"
    ratio_head = ""
    if ratio:
        ratio_head = (
            f'<th class="rank-count">{escape(str(show_method.get("denominator_label") or "分母"))}</th>'
            f'<th class="rank-count">{escape(str(show_method.get("ratio_label") or "比"))}</th>'
        )
    head = (
        '<tr><th class="rank-no">順位</th>'
        f"<th>{escape(str(value_label_text))}</th>"
        + "".join(f"<th>{escape(str(c.get('label') or c.get('id')))}</th>" for c in columns)
        + f'<th class="rank-count">{escape(str(count_label))}</th>' + ratio_head + "</tr>"
    )
    body = []
    highlight = params.get("highlight")
    for row in rows:
        value = str(row["value"])
        label = row.get("label") or value
        if label == value:
            label = value_label(value)
        if row.get("type") == "uri":
            value_html = f'<a href="{escape(resource_url(value))}" title="{escape(value)}">{escape(str(label))}</a>'
        else:
            value_html = escape(str(label))
        drop = {RANK_PAGE_PARAM, TAB_PARAM, "highlight"}
        add = [(FACET_PREFIX + facet, value)] if facet else []
        if list_tab is not None:
            add.append((TAB_PARAM, str(list_tab)))
        count_html = (
            f'<a href="{escape(make_url(params, drop=drop, add=add))}" title="この値の要素の一覧">{int(row["count"]):,}</a>'
            if facet else f'{int(row["count"]):,}'
        )
        cells = []
        detail = row.get("detail") or {}
        for c in columns:
            v = detail.get(c.get("id"))
            if v is None:
                cells.append("<td></td>")
                continue
            text = get_localname(v) if c.get("display") == "localname" else v
            cells.append(f"<td>{escape(str(text))}</td>")
        cls = ' class="rank-highlight"' if highlight and highlight == value else ""
        ratio_cells = ""
        if ratio:
            d = row.get("denominator") or 0
            d_text = f"{int(d):,}" if float(d).is_integer() else f"{d:,.2f}"
            r = row.get("ratio") or 0
            r_text = f"{r * 100:.1f}%" if show_method.get("ratio_format", "percent") == "percent" else f"{r:.3f}"
            ratio_cells = f'<td class="rank-count">{d_text}</td><td class="rank-count">{r_text}</td>'
        body.append(
            f'<tr{cls}><td class="rank-no">{int(row["rank"]):,}</td><td>{value_html}</td>'
            + "".join(cells) + f'<td class="rank-count">{count_html}</td>' + ratio_cells + "</tr>"
        )
    if not body:
        body.append(f'<tr><td colspan="{3 + len(columns) + (2 if ratio else 0)}" class="facet-empty">値がありません</td></tr>')
    pager = ""
    if total > page_size:
        last = (total + page_size - 1) // page_size
        start = (page - 1) * page_size + 1
        end = min(page * page_size, total)
        links = []
        if page > 1:
            links.append(f'<a href="{escape(rank_page_url(params, 1))}">« 最初</a>')
            links.append(f'<a href="{escape(rank_page_url(params, page - 1))}">‹ 前へ</a>')
        links.append(f'<span class="pager-status">{start:,}–{end:,} / {total:,} 種類</span>')
        if page < last:
            links.append(f'<a href="{escape(rank_page_url(params, page + 1))}">次へ ›</a>')
            links.append(f'<a href="{escape(rank_page_url(params, last))}">最後 »</a>')
        pager = '<nav class="pager">' + " ".join(links) + "</nav>"
    summary = f'<p class="rank-summary">{escape(str(value_label_text))}: {total:,} 種類。件数を押すと、その値を持つ要素の一覧に移ります。</p>'
    style = (
        "<style>.rank-table{border-collapse:collapse;margin:.5em 0}.rank-table th,.rank-table td{padding:.25em .6em;"
        "border-bottom:1px solid #e3e3e0;text-align:left}.rank-table .rank-no,.rank-table .rank-count{text-align:right;"
        "white-space:nowrap}.rank-table tr.rank-highlight td{background:#fff4cc}</style>"
    )
    return (
        style + summary + chart_html + pager
        + '<table class="rank-table"><thead>' + head + "</thead><tbody>\n" + "\n".join(body) + "\n</tbody></table>"
        + pager
    )


def resource_url(uri):
    return f"/resource?uri={quote(str(uri), safe='')}"


# --------------------------------------------------
# 範囲のファセット
# --------------------------------------------------

# 値を年（整数）で扱う種類
YEARLY_TYPES = ("date", "dateTime")
INTEGER_TYPES = ("integer", "gYear")

# 棒グラフの配色（dataviz の参照パレットの青。範囲外は同じ色相の淡い段）
HISTOGRAM_BAR = "#2a78d6"
HISTOGRAM_BAR_MUTED = "#b5cdee"
HISTOGRAM_AXIS = "#d4d4d0"
HISTOGRAM_TEXT = "#52514e"


def is_integer_scale(datatype, unit):
    """区間を整数（年を含む）で区切るか"""
    return unit == "year" or datatype in YEARLY_TYPES or datatype in INTEGER_TYPES


def _nice_width(raw):
    """区間の幅を 1, 2, 5 × 10^k に丸める"""
    if raw <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw))
    base = 10 ** exponent
    for step in (1, 2, 5, 10):
        if raw <= step * base:
            return step * base
    return 10 * base


def plan_bins(minimum, maximum, bins, *, integer):
    """最小値・最大値から、区間の開始値 low、幅 width、区間数 count を決める。"""
    bins = max(1, int(bins or 20))
    minimum = float(minimum)
    maximum = float(maximum)
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    if integer:
        low = math.floor(minimum)
        span = math.floor(maximum) - low + 1
        width = max(1, math.ceil(span / bins))
        count = max(1, math.ceil(span / width))
        return low, width, count
    width = _nice_width((maximum - minimum) / bins) if maximum > minimum else 1.0
    low = math.floor(minimum / width) * width
    count = max(1, math.floor((maximum - low) / width) + 1)
    return low, width, count


def _number_text(value):
    """数値を URL・表示用の短い文字列にする（1000.0 → 1000）"""
    number = Decimal(repr(float(value))).normalize()
    text = format(number, "f")
    return text


def bin_bounds(index, low, width, *, integer):
    """区間 index の下限・上限（上限を含む）"""
    start = low + index * width
    if integer:
        return int(start), int(start + width - 1)
    return start, start + width


def bound_param(value, datatype, unit, *, upper):
    """区間の端を、URL パラメータ（f.<name>.min / .max）の値にする。"""
    if unit != "year" and datatype in YEARLY_TYPES:
        year = int(value)
        if datatype == "date":
            return f"{year:04d}-12-31" if upper else f"{year:04d}-01-01"
        return f"{year:04d}-12-31T23:59:59" if upper else f"{year:04d}-01-01T00:00:00"
    if is_integer_scale(datatype, unit):
        return str(int(value))
    return _number_text(value)


def selection_number(value, datatype, unit):
    """選択中の下限・上限を、区間と比べられる数値にする（日付は年）。解釈できなければ None"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if unit != "year" and datatype in YEARLY_TYPES:
            return int(text[:4]) if text[:4].isdigit() else None
        return float(text)
    except ValueError:
        return None


def build_histogram(counts, low, width, count, *, datatype, unit, selected):
    """区間ごとの件数と、各区間を選ぶ URL パラメータの値を並べる。"""
    integer = is_integer_scale(datatype, unit)
    selected_min = selection_number((selected or {}).get("min"), datatype, unit)
    selected_max = selection_number((selected or {}).get("max"), datatype, unit)
    result = []
    for index in range(count):
        start, end = bin_bounds(index, low, width, integer=integer)
        # 最大値ちょうどは最後の区間に入れる
        value = counts.get(index, 0) + (counts.get(count, 0) if index == count - 1 else 0)
        in_range = True
        if selected_min is not None and end < selected_min:
            in_range = False
        if selected_max is not None and start > selected_max:
            in_range = False
        result.append({
            "start": start,
            "end": end,
            "count": value,
            "min_param": bound_param(start, datatype, unit, upper=False),
            "max_param": bound_param(end, datatype, unit, upper=True),
            "in_range": in_range,
        })
    return result


def _bin_label(item, integer):
    if integer:
        if item["start"] == item["end"]:
            return str(item["start"])
        return f'{item["start"]}–{item["end"]}'
    return f'{_number_text(item["start"])}–{_number_text(item["end"])}'


def _axis_text(value, integer):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if integer else _number_text(number)


def render_histogram(content, *, width=260, height=72):
    """区間ごとの件数を棒グラフ（SVG）で描く。各棒はその区間で絞り込むリンク。"""
    histogram = content.get("histogram") or []
    if not histogram:
        return ""
    params = content.get("params") or {}
    name = content["name"]
    integer = is_integer_scale(content.get("datatype"), content.get("unit"))
    field_min = f"{FACET_PREFIX}{name}.min"
    field_max = f"{FACET_PREFIX}{name}.max"
    peak = max(item["count"] for item in histogram) or 1
    gap = 2
    slot = width / len(histogram)
    bar_width = max(1.0, min(24.0, slot - gap))
    plot_height = height - 18  # 下に軸ラベルの余白
    radius = min(4.0, bar_width / 2)
    parts = [
        f'<svg class="histogram" viewBox="0 0 {width} {height}" width="100%" '
        f'role="img" aria-label="{escape(content.get("label") or name)}の分布">'
    ]
    for index, item in enumerate(histogram):
        x = index * slot + (slot - bar_width) / 2
        label = _bin_label(item, integer)
        url = make_url(
            params,
            drop={field_min, field_max},
            add=[(field_min, item["min_param"]), (field_max, item["max_param"])],
        )
        color = HISTOGRAM_BAR if item["in_range"] else HISTOGRAM_BAR_MUTED
        bar = ""
        if item["count"] > 0:
            bar_height = max(2.0, plot_height * item["count"] / peak)
            top = plot_height - bar_height
            r = min(radius, bar_height)
            # 上端だけ角を丸め、軸側は四角にする
            bar = (
                f'<path fill="{color}" d="M{x:.1f},{plot_height:.1f} '
                f'V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} '
                f'H{x + bar_width - r:.1f} Q{x + bar_width:.1f},{top:.1f} {x + bar_width:.1f},{top + r:.1f} '
                f'V{plot_height:.1f} Z"/>'
            )
        parts.append(
            f'<a href="{escape(url)}" class="histogram-bin">'
            f'<title>{escape(label)}: {item["count"]:,} 件</title>'
            # 棒より大きい当たり判定（透明）
            f'<rect x="{index * slot:.1f}" y="0" width="{slot:.1f}" height="{plot_height:.1f}" fill="transparent"/>'
            f"{bar}</a>"
        )
    parts.append(
        f'<line x1="0" y1="{plot_height + 0.5:.1f}" x2="{width}" y2="{plot_height + 0.5:.1f}" '
        f'stroke="{HISTOGRAM_AXIS}" stroke-width="1"/>'
    )
    # 軸の両端は、実際の最小値・最大値を表示する
    value_range = content.get("range") or {}
    first = histogram[0]
    last = histogram[-1]
    start_value = value_range.get("min", first["start"])
    end_value = value_range.get("max", last["end"])
    start_text = _axis_text(start_value, integer)
    end_text = _axis_text(end_value, integer)
    parts.append(
        f'<text x="0" y="{height - 4}" font-size="11" fill="{HISTOGRAM_TEXT}">{escape(start_text)}</text>'
        f'<text x="{width}" y="{height - 4}" font-size="11" fill="{HISTOGRAM_TEXT}" '
        f'text-anchor="end">{escape(end_text)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def input_type(datatype, unit):
    if unit != "year" and datatype == "date":
        return "date"
    if unit != "year" and datatype == "dateTime":
        return "datetime-local"
    return "number"


def render_range_facet(content):
    """範囲のファセット（下限・上限の入力欄と分布の棒グラフ）を描画する。

    content = {
        "kind": "range", "name", "label", "datatype", "unit",
        "range": {"min", "max", "count"} または None,
        "histogram": build_histogram() の結果,
        "selected": {"min", "max"},
        "params": Gadget に渡された params,
    }
    """
    name = content["name"]
    params = content.get("params") or {}
    selected = content.get("selected") or {}
    value_range = content.get("range")
    field_min = f"{FACET_PREFIX}{name}.min"
    field_max = f"{FACET_PREFIX}{name}.max"
    kind = input_type(content.get("datatype"), content.get("unit"))
    step = ""
    if kind == "number":
        step = ' step="1"' if is_integer_scale(content.get("datatype"), content.get("unit")) else ' step="any"'
    placeholder_min = placeholder_max = ""
    if value_range and kind == "number":
        placeholder_min = f' placeholder="{escape(str(value_range["min"]))}"'
        placeholder_max = f' placeholder="{escape(str(value_range["max"]))}"'
    if value_range is None:
        body = '<p class="facet-empty">値がありません</p>'
    else:
        body = render_histogram(content)
    clear = ""
    if selected.get("min") or selected.get("max"):
        clear = (
            f'<a class="facet-clear" href="{escape(make_url(params, drop={field_min, field_max}))}">'
            "クリア</a>"
        )
    return (
        f'<form class="facet facet-range" method="GET" action="{escape(params.get(PATH_PARAM) or "")}" '
        f'data-facet-name="{escape(name)}">\n'
        f"{hidden_inputs(params, exclude_keys={field_min, field_max})}\n"
        f"{body}\n"
        '<div class="range-inputs">'
        f'<input type="{kind}" name="{escape(field_min)}" value="{escape(str(selected.get("min") or ""))}"'
        f'{step}{placeholder_min} aria-label="下限">'
        '<span class="range-separator">〜</span>'
        f'<input type="{kind}" name="{escape(field_max)}" value="{escape(str(selected.get("max") or ""))}"'
        f'{step}{placeholder_max} aria-label="上限">'
        "</div>\n"
        '<div class="facet-actions">'
        '<button type="submit" class="facet-apply">適用</button>'
        f"{clear}</div>\n"
        "</form>"
    )
