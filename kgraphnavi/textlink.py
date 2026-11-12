#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      textlink.py
##  Author:
##      Fumihito NISHINO       nishino@nii.ac.jp
##  Description:
##      テキストにリンクを付ける（/textlink・/api/textlink。2026.11.10）
##      貼り付けたテキストの中の参照（判例の引用など）を見つけ、KGraphNavi のリソースのページへのリンクにする。
##      見つけて結ぶ処理は外のモジュール（判例なら hanrei の caselinker）に任せる。
##
##  /textlink                画面（テキストを貼って「リンクを付ける」）
##  /api/textlink            Web API（POST: JSON {"text": …, "min_confidence": "中"} かフォーム。GET: ?text=…）
##
##  設定（アプリケーション設定 textlink:）
##    textlink:
##      module: caselinker         make_linker(options) を持つモジュール
##      path: ~/nii/hanrei         モジュールを探すフォルダ（sys.path に足す。相対パスは設定ファイルのフォルダから）
##      index: ~/nii/hanrei/data/release/caselink-index.sqlite   モジュールに渡す（相対パスは設定ファイルのフォルダから）
##      title: 判例リンク          画面の見出し・上の帯の名前（既定「リンク」）
##      labels: {item: 引用, …}    画面の文言（既定はモジュールの LABELS、無ければ DEFAULT_LABELS）
##      min_confidence: 低         既定の確かさの下限（高・中・低）
##      max_chars: 200000          受け付けるテキストの長さの上限
##      cors: "*"                  /api/textlink の Access-Control-Allow-Origin（省略時は付けない）
##      options: {…}               そのほかモジュールに渡す値
##
##  モジュールの約束
##    make_linker(options) → run(text, min_confidence) 。run は引用ごとの辞書のリストを返す:
##      start, end, text（必須）、linked（結べたか）、target（リンク先のリソースの URI）、
##      ecli, key, id_uri, in_data, ids, method, confidence, candidates, court, date, caseno, reporters（任意）
##    run.meta に索引の情報（版・件数など）を置いてよい
"""
import importlib
import importlib.util
import json
import sys
import threading
import urllib.parse
from html import escape
from pathlib import Path

TEXTLINK_KEYS = {"module", "path", "index", "title", "min_confidence", "max_chars", "cors", "options", "labels"}
CONFIDENCES = ("高", "中", "低")
DEFAULTS = {"title": "リンク", "min_confidence": "低", "max_chars": 200000, "cors": None}


# 画面の文言。モジュールの LABELS、設定の labels の順に上書きする。空の列名（key・id・in_data）はその列を出さない
DEFAULT_LABELS = {
    "description": "テキストを貼り付けて「リンクを付ける」を押すと、テキストの中の参照を見つけ、リソースのページへのリンクにします。"
                   "テキストは保存しません。同じことを Web API（/api/textlink）でもできます。",
    "placeholder": "",
    "nav_tip": "貼り付けたテキストの参照を、リソースのページへのリンクにします",
    "item": "参照", "key": "リソース", "id": "ID", "in_data": "",
    "legend": "下線の実線は確かさ「高」、破線は「中」、点線は「低」",
}


def textlink_settings(config, base_dir):
    """設定の textlink: 節を検証して辞書にする（path・index は絶対パスにする）"""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("textlink は辞書で書いてください")
    unknown = set(config) - TEXTLINK_KEYS
    if unknown:
        raise ValueError(f"textlink の未知のキー: {sorted(unknown)}")
    if not config.get("module"):
        raise ValueError("textlink.module に、make_linker を持つモジュールの名前を書いてください（例: caselinker）")
    cfg = dict(DEFAULTS)
    cfg.update(config)
    for key in ("path", "index"):
        if cfg.get(key):
            p = Path(str(cfg[key])).expanduser()
            cfg[key] = str((p if p.is_absolute() else Path(base_dir) / p).resolve())
    if cfg["min_confidence"] not in CONFIDENCES:
        raise ValueError(f"textlink.min_confidence は {'・'.join(CONFIDENCES)} のどれかです")
    try:
        cfg["max_chars"] = int(cfg["max_chars"])
    except (TypeError, ValueError) as e:
        raise ValueError("textlink.max_chars は整数で書いてください") from e
    if cfg.get("labels") is not None and (not isinstance(cfg["labels"], dict) or set(cfg["labels"]) - set(DEFAULT_LABELS)):
        raise ValueError(f"textlink.labels は {sorted(DEFAULT_LABELS)} の辞書で書いてください")
    if cfg.get("options") is not None and not isinstance(cfg["options"], dict):
        raise ValueError("textlink.options は辞書で書いてください")
    return cfg


class TextLinker:
    """モジュールを初めて使うときに読み込み、make_linker を一度だけ呼ぶ（索引の読み込みは数秒かかる）"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._run = None
        self._lock = threading.Lock()

    def module(self):
        path = self.cfg.get("path")
        if path and path not in sys.path:
            sys.path.insert(0, path)
        name = self.cfg["module"]
        return importlib.import_module(name + ".kgraphnavi" if _has_submodule(name) else name)

    @property
    def labels(self):
        """画面の文言（モジュールを読めなければ既定と設定だけ）"""
        labels = dict(DEFAULT_LABELS)
        try:
            labels.update(getattr(self.module(), "LABELS", {}) or {})
        except ImportError:
            pass
        labels.update(self.cfg.get("labels") or {})
        return labels

    def linker(self):
        with self._lock:
            if self._run is None:
                module = self.module()
                options = dict(self.cfg.get("options") or {})
                if self.cfg.get("index"):
                    options["index"] = self.cfg["index"]
                self._run = module.make_linker(options)
            return self._run

    @property
    def meta(self):
        return getattr(self.linker(), "meta", {})

    def run(self, text, min_confidence=None):
        """→ 引用のリスト。テキストが長すぎる・確かさの指定が違うときは ValueError"""
        if len(text) > self.cfg["max_chars"]:
            raise ValueError(f"テキストが長すぎます（{len(text):,} 字。上限 {self.cfg['max_chars']:,} 字）")
        mc = min_confidence or self.cfg["min_confidence"]
        if mc not in CONFIDENCES:
            raise ValueError(f"min_confidence は {'・'.join(CONFIDENCES)} のどれかです: {mc}")
        items = self.linker()(text, mc)
        return sorted(items, key=lambda x: x["start"])


def _has_submodule(name):
    """パッケージ name に kgraphnavi（KGraphNavi 用の入口）があるか"""
    try:
        return importlib.util.find_spec(name + ".kgraphnavi") is not None
    except (ImportError, ValueError):
        return False


def result_json(items, meta, text_length):
    linked = sum(1 for x in items if x.get("linked"))
    return {"length": text_length, "citations": len(items), "linked": linked, "index": meta, "items": items}


def resource_href(uri):
    return "/resource?" + urllib.parse.urlencode({"uri": uri})


CSS = """<style>
.tl-form textarea{width:100%;min-height:12em;font-size:.95em;line-height:1.6;box-sizing:border-box}
.tl-form .tl-ops{margin:.4em 0 1em;display:flex;gap:1em;align-items:center;flex-wrap:wrap}
.tl-summary{color:#555;margin:.5em 0}
.tl-text{white-space:pre-wrap;line-height:1.9;border:1px solid #ddd;border-radius:6px;padding:1em;background:#fff}
a.tl-link{background:#fdf1e4;border-bottom:2px solid #a35c2a;text-decoration:none;color:inherit}
a.tl-link.tl-c中{border-bottom-style:dashed}
a.tl-link.tl-c低{border-bottom:1px dotted #a35c2a;background:none}
a.tl-link.tl-external{background:#eef3f8;border-bottom-color:#3a6ea5}
span.tl-unlinked{border-bottom:1px dotted #999}
table.tl-table{border-collapse:collapse;margin-top:1em;font-size:.9em}
table.tl-table th,table.tl-table td{border:1px solid #ddd;padding:.25em .5em;vertical-align:top}
table.tl-table th{white-space:nowrap}
table.tl-table .tl-id{font-family:monospace;font-size:.9em}
.tl-note{font-size:.85em;color:#666}
</style>"""


def render_textlink(cfg, text="", items=None, meta=None, min_confidence=None, message="", labels=None):
    """画面: 入力の欄と、結果（リンクにしたテキスト・参照の表）"""
    lb = labels or DEFAULT_LABELS
    mc = min_confidence or cfg["min_confidence"]
    opts = "".join(f'<option value="{c}"{" selected" if c == mc else ""}>{c}</option>' for c in CONFIDENCES)
    parts = [CSS, f'<p class="tl-note">{escape(lb["description"])}</p>',
             '<form class="tl-form" method="POST" action="/textlink">',
             f'<textarea name="text" placeholder="{escape(lb["placeholder"])}">{escape(text)}</textarea>',
             f'<div class="tl-ops"><button type="submit">リンクを付ける</button>'
             f'<label>確かさ <select name="min_confidence">{opts}</select> 以上を結ぶ</label></div></form>']
    if message:
        parts.append(f'<p class="tl-summary">{escape(message)}</p>')
    if items is not None:
        parts.append(render_result(text, items, meta or {}, lb))
    return "\n".join(parts)


def render_result(text, items, meta, labels=None):
    lb = labels or DEFAULT_LABELS
    linked = [x for x in items if x.get("linked")]
    size = meta.get("judgments") or meta.get("labels") or ""
    info = "・".join(escape(str(v)) for v in [f"索引 {size} 件" if size else "", meta.get("id_format", ""),
                                            meta.get("data_date") or meta.get("built", "")] if v)
    out = [f'<p class="tl-summary">{escape(lb["item"])} {len(items)} 件、リンクにした {len(linked)} 件'
           + (f"（{info}）" if info else "") + f'。<span class="tl-note">{escape(lb["legend"])}</span></p>']
    body, last = [], 0
    for x in items:
        if x["start"] < last:        # 重なりは飛ばす
            continue
        body.append(escape(text[last:x["start"]]))
        frag = escape(text[x["start"]:x["end"]])
        ident = x.get("id") or x.get("ecli") or ""
        if x.get("linked") and x.get("target"):
            cls = f'tl-link tl-c{x.get("confidence", "")}' + ("" if x.get("in_data", True) else " tl-external")
            tip = "｜".join(v for v in [ident, x.get("key", ""), f'{x.get("method", "")}（確かさ {x.get("confidence", "")}）'] if v)
            body.append(f'<a class="{cls}" href="{escape(resource_href(x["target"]))}" title="{escape(tip)}">{frag}</a>')
        else:
            tip = x.get("method") or "結べない"
            if x.get("candidates"):
                tip += "｜候補: " + "、".join(x["candidates"])
            body.append(f'<span class="tl-unlinked" title="{escape(tip)}">{frag}</span>')
        last = x["end"]
    body.append(escape(text[last:]))
    out.append(f'<div class="tl-text">{"".join(body)}</div>')
    if items:
        cols = [c for c in ("key", "id") if lb.get(c)]
        head = f'<th></th><th>{escape(lb["item"])}</th>' + "".join(f"<th>{escape(lb[c])}</th>" for c in cols) \
            + "<th>決め方</th><th>確かさ</th>" + (f'<th>{escape(lb["in_data"])}</th>' if lb.get("in_data") else "")
        rows = []
        for i, x in enumerate(items, 1):
            cells = [str(i), escape(x["text"])]
            if "key" in cols:
                case = (f'<a href="{escape(resource_href(x["target"]))}">{escape(x.get("key", ""))}</a>'
                        if x.get("linked") and x.get("target") else escape(x.get("key", "")))
                if x.get("candidates"):
                    case += '<br><span class="tl-note">候補: ' + "、".join(escape(c) for c in x["candidates"]) + "</span>"
                cells.append(case)
            if "id" in cols:
                idcell = escape(x.get("id") or x.get("ecli") or "")
                if x.get("id_uri") and idcell:
                    idcell = f'<a href="{escape(resource_href(x["id_uri"]))}">{idcell}</a>'
                cells.append(f'<span class="tl-id">{idcell}</span>')
            cells += [escape(x.get("method", "")), escape(x.get("confidence", ""))]
            if lb.get("in_data"):
                cells.append("あり" if x.get("in_data") else "")
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        out.append(f'<table class="tl-table"><tr>{head}</tr>' + "".join(rows) + "</table>")
    out.append(f'<details class="tl-note"><summary>JSON</summary><pre>{escape(json.dumps(items, ensure_ascii=False, indent=1))}</pre></details>')
    return "\n".join(out)
