#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      topic.py
##  Author:
##      Fumihito NISHINO       nishino@nii.ac.jp
##  Description:
##      キーワードからトピックのコレクションを作る（2026.10.26）。判例に限らない一般の仕組み。
##      設定の topic: 節（集める要素のクラス、語を探すプロパティ、「リンク」のプロパティ、しきい値）だけを使う。
##        1. 種の要素: 語を探すプロパティ（ラベル・要約など）にキーワードを含む要素
##        2. リンクの候補: 種の要素がリンクするリソース（カテゴリなど）のうち、全体より何倍も偏るもの
##           - 主なリンク: 種の要素の main_share 以上がリンクし、全体ではあまり使われない（または何十倍も偏る）もの。それだけでトピックに入れる
##           - 補助リンク: aux_share 以上。語と一緒のときだけ確かさを上げる（判例の「補助条」にあたる）
##        3. 確かさ: 強 = 語とリンク（主・補助）の両方 / 中 = 主なリンクだけ、またはラベルに語 / 弱 = 本文（要約など）に語だけ
##      判例（hanrei）のように本文の語の数え方や全件の計算が重いデータは、同じ定義の形で外のコマンドが作る
##      （hanrei の src/topic_keyword.py・src/topics.py）。ここは SPARQL だけで作る版
"""
import math
import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode

from .terms import iri_term, predicate_term, literal_term, language_tag
from .collection import bif_text_expression
from .render_utils import get_localname

logger = logging.getLogger(__name__)

DEFAULTS = {
    "seed_max": 2000,        # 種の要素を取る数の上限
    "candidate_max": 40,     # リンクの候補を調べる数（プロパティごと）
    "member_max": 5000,      # 主なリンクで入る要素を取る数の上限
    "min_count": 5,          # リンクの候補にする、種の要素での件数
    "min_lift": 3.0,         # リンクの候補にする、全体より何倍偏るか
    "main_share": 0.15,      # 主なリンク: 種の要素のこの割合以上がリンクする
    "aux_share": 0.05,       # 補助リンク: この割合以上
    "specific_df": 400,      # 主なリンク: 全体でリンクする要素がこれ以下（多いものは補助リンク）
    "specific_lift": 30.0,   # ただし、これ以上偏っていれば主なリンク
}
TOPIC_KEYS = {"item_class", "text_properties", "label_property", "lang", "link_properties", "total", "title", "text_search",
              "builder", "command", "cwd", "timeout"} | set(DEFAULTS)


def topic_settings(config):
    """設定の topic: 節を検証して辞書にする"""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("topic は辞書で書いてください")
    unknown = set(config) - TOPIC_KEYS
    if unknown:
        raise ValueError(f"topic の未知のキー: {sorted(unknown)}")
    cfg = dict(DEFAULTS)
    cfg.update(config)
    cfg["text_properties"] = list(cfg.get("text_properties") or ["rdfs:label"])
    cfg["link_properties"] = list(cfg.get("link_properties") or [])
    cfg["label_property"] = cfg.get("label_property") or "rdfs:label"
    cfg["builder"] = cfg.get("builder") or "sparql"
    if cfg["builder"] not in ("sparql", "command"):
        raise ValueError("topic.builder は sparql か command です")
    if cfg["builder"] == "command":
        if not cfg.get("command") or not isinstance(cfg["command"], list):
            raise ValueError("topic.builder: command のときは topic.command（コマンドと引数のリスト）を書いてください")
    elif not cfg["link_properties"]:
        raise ValueError("topic.link_properties に、リンクを数えるプロパティを1つ以上書いてください")
    return cfg


@dataclass
class Link:
    prop: str           # プロパティ（設定の書き方のまま）
    uri: str
    count: int          # 種の要素でリンクする数
    df: int             # 全体でリンクする数
    lift: float
    role: str = ""      # main / aux / ""（候補だけ）
    label: str = ""
    id: str = ""        # 画面で選び直すときの名前（作り手に返す。SPARQL の版は URI）

    def key(self):
        return self.id or self.uri


@dataclass
class TopicResult:
    keyword: str
    seed_count: int = 0
    seed_capped: bool = False
    total: int = 0
    links: list = field(default_factory=list)
    members: list = field(default_factory=list)   # (uri, label, 確かさ, 手がかり)
    warnings: list = field(default_factory=list)
    words: list = None      # 広げた語 [(語, 種類)]（作り手が語を広げるときだけ。画面で外せる）
    related: list = None    # 関連語 [(語, 主か)]（語を使わない要素を拾う語）
    context: list = None    # 文脈語（関連語と一緒に要る語）
    details: dict = None    # 要素ごとの詳しい手がかり {uri: {caseno, court, date, casename, clauses, words, related, name_hit}}（作り手が出すときだけ）
    summary: dict = None    # 作り手の手順の数 {words, seed, main, aux, related, counted_words, levels}


def classify(count, df, seed_n, total, cfg):
    """リンクの役割（main / aux / ""）と偏り(lift)"""
    if not seed_n or not total or not df:
        return "", 0.0
    lift = (count / seed_n) / (df / total)
    if count < cfg["min_count"] or lift < cfg["min_lift"]:
        return "", lift
    if count >= cfg["main_share"] * seed_n and (df <= cfg["specific_df"] or lift >= cfg["specific_lift"]):
        return "main", lift
    if count >= cfg["aux_share"] * seed_n:
        return "aux", lift
    return "", lift


def level_of(word_in_label, word_in_text, main, aux):
    """確かさ（強・中・弱）と手がかり"""
    via = [v for v, ok in (("語（ラベル）", word_in_label), ("語", word_in_text and not word_in_label),
                            ("主なリンク", main), ("補助リンク", aux)) if ok]
    word = word_in_label or word_in_text
    if word and (main or aux):
        return "強", via
    if main or word_in_label:
        return "中", via
    if word:
        return "弱", via
    return "", via


class TopicBuilder:
    """SPARQL だけでトピックの案と要素を作る"""

    def __init__(self, sparql, cfg, text_method="bif"):
        self.sparql = sparql
        self.cfg = cfg
        self.text_method = text_method

    # ---- 問い合わせの部品 ----
    def _class_pattern(self, var="?s"):
        c = self.cfg.get("item_class")
        return f"{var} a {iri_term(c) if '://' in c else c} ." if c else ""

    @staticmethod
    def words(keyword):
        """キーワードの語（「パワーハラスメント|パワハラ」のように | で区切るといずれか）"""
        return [w.strip() for w in str(keyword).split("|") if w.strip()]

    def _text_pattern(self, keyword, prop, var="?s", tvar="?_t"):
        p = predicate_term(prop)     # プロパティのパス（dcterms:subject/rdfs:label など）も書ける
        lang = self.cfg.get("lang")
        lang_filter = f" FILTER(LANGMATCHES(LANG({tvar}), {literal_term(language_tag(lang))}))" if lang else ""
        words = self.words(keyword)
        exprs = [bif_text_expression(w) for w in words]
        if self.text_method == "bif" and all(exprs):
            expr = " OR ".join(f"({e})" for e in exprs) if len(exprs) > 1 else exprs[0]
            return f"{var} {p} {tvar} . {tvar} bif:contains {literal_term(expr)} .{lang_filter}"
        cond = " || ".join(f"CONTAINS(LCASE(STR({tvar})), LCASE({literal_term(w)}))" for w in words)
        return f"{var} {p} {tvar} . FILTER({cond}){lang_filter}"

    def _seed_pattern(self, keyword, var="?s"):
        parts = [f"{{ {self._text_pattern(keyword, p, var, f'?_t{i}')} }}" for i, p in enumerate(self.cfg["text_properties"])]
        return " UNION ".join(parts) + " " + self._class_pattern(var)

    def _label_lang(self):
        lang = self.cfg.get("lang")
        return f" FILTER(LANGMATCHES(LANG(?_l), {literal_term(language_tag(lang))}))" if lang else ""

    # ---- 1. 種の要素 ----
    def seeds(self, keyword):
        """種の要素 {uri: (label, ラベルに語があるか)}"""
        label_p = predicate_term(self.cfg["label_property"])
        q = (f"SELECT DISTINCT ?s ?_l WHERE {{ {self._seed_pattern(keyword)} "
             f"OPTIONAL {{ ?s {label_p} ?_l .{self._label_lang()} }} }} LIMIT {int(self.cfg['seed_max'])}")
        out = {}
        for r in self.sparql.exsparql(q):
            uri = r["s"]["value"]
            label = r.get("_l", {}).get("value", "")
            if uri not in out or (label and not out[uri][0]):
                out[uri] = (label, any(w.lower() in label.lower() for w in self.words(keyword)))
        return out

    def total(self):
        if self.cfg.get("total"):
            return int(self.cfg["total"])
        if self.cfg.get("item_class"):
            q = f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {self._class_pattern()} }}"
            rows = self.sparql.exsparql(q)
            return int(rows[0]["n"]["value"]) if rows else 0
        return 0

    # ---- 2. リンクの候補 ----
    def link_candidates(self, keyword, prop):
        p = predicate_term(prop)
        q = (f"SELECT ?o (COUNT(DISTINCT ?s) AS ?c) WHERE {{ {self._seed_pattern(keyword)} ?s {p} ?o . FILTER(isIRI(?o)) }} "
             f"GROUP BY ?o ORDER BY DESC(?c) LIMIT {int(self.cfg['candidate_max'])}")
        return [(r["o"]["value"], int(r["c"]["value"])) for r in self.sparql.exsparql(q)]

    def link_df(self, prop, uris):
        if not uris:
            return {}
        p = predicate_term(prop)
        values = " ".join(iri_term(u) for u in uris)
        q = (f"SELECT ?o (COUNT(DISTINCT ?s) AS ?d) WHERE {{ VALUES ?o {{ {values} }} ?s {p} ?o . {self._class_pattern()} }} GROUP BY ?o")
        return {r["o"]["value"]: int(r["d"]["value"]) for r in self.sparql.exsparql(q)}

    def labels(self, uris):
        if not uris:
            return {}
        label_p = predicate_term(self.cfg["label_property"])
        values = " ".join(iri_term(u) for u in uris)
        q = f"SELECT ?s ?_l WHERE {{ VALUES ?s {{ {values} }} ?s {label_p} ?_l .{self._label_lang()} }}"
        return {r["s"]["value"]: r["_l"]["value"] for r in self.sparql.exsparql(q)}

    # ---- 3. 要素 ----
    def linked_items(self, links):
        """リンクのどれかを持つ要素 {uri: label}（主なリンクで入る要素）"""
        out = {}
        label_p = predicate_term(self.cfg["label_property"])
        by_prop = {}
        for ln in links:
            by_prop.setdefault(ln.prop, []).append(ln.uri)
        for prop, uris in by_prop.items():
            values = " ".join(iri_term(u) for u in uris)
            q = (f"SELECT DISTINCT ?s ?_l WHERE {{ VALUES ?o {{ {values} }} ?s {predicate_term(prop)} ?o . {self._class_pattern()} "
                 f"OPTIONAL {{ ?s {label_p} ?_l .{self._label_lang()} }} }} LIMIT {int(self.cfg['member_max'])}")
            for r in self.sparql.exsparql(q):
                out.setdefault(r["s"]["value"], r.get("_l", {}).get("value", ""))
        return out

    def seeds_with_links(self, keyword, links):
        """種の要素のうち、links のどれかを持つもの"""
        out = set()
        by_prop = {}
        for ln in links:
            by_prop.setdefault(ln.prop, []).append(ln.uri)
        for prop, uris in by_prop.items():
            values = " ".join(iri_term(u) for u in uris)
            q = (f"SELECT DISTINCT ?s WHERE {{ {self._seed_pattern(keyword)} VALUES ?o {{ {values} }} ?s {predicate_term(prop)} ?o }} "
                 f"LIMIT {int(self.cfg['seed_max'])}")
            out |= {r["s"]["value"] for r in self.sparql.exsparql(q)}
        return out

    def build(self, keyword, override=None):
        """案と要素を作る。override = {"main": [uri…], "aux": [uri…]} なら、リンクの役割はそれに従う（画面で選び直したもの）"""
        res = TopicResult(keyword)
        seeds = self.seeds(keyword)
        res.seed_count = len(seeds)
        res.seed_capped = len(seeds) >= int(self.cfg["seed_max"])
        if res.seed_capped:
            res.warnings.append(f"種の要素が上限（{self.cfg['seed_max']:,}件）に達しました。偏りは上限までの要素で数えています")
        res.total = self.total()
        if not res.total:
            res.warnings.append("全体の要素の数が分かりません（設定 topic.total か topic.item_class を書いてください）。偏りは計算していません")
        for prop in self.cfg["link_properties"]:
            cands = self.link_candidates(keyword, prop)
            df = self.link_df(prop, [u for u, _ in cands])
            for uri, c in cands:
                role, lift = classify(c, df.get(uri, 0), res.seed_count, res.total, self.cfg)
                res.links.append(Link(prop, uri, c, df.get(uri, 0), lift, role))
        if override is not None and override.get("links_edited"):
            main, aux = set(override.get("main", [])), set(override.get("aux", []))
            for ln in res.links:
                ln.role = "main" if ln.key() in main else ("aux" if ln.key() in aux else "")
        names = self.labels([ln.uri for ln in res.links])
        for ln in res.links:
            ln.label = names.get(ln.uri) or get_localname(ln.uri)
        res.links.sort(key=lambda ln: ({"main": 0, "aux": 1}.get(ln.role, 2), -ln.count * math.log(max(ln.lift, 1.0001))))
        mains = [ln for ln in res.links if ln.role == "main"]
        auxs = [ln for ln in res.links if ln.role == "aux"]
        by_main = self.linked_items(mains) if mains else {}
        seed_main = set(by_main) & set(seeds)
        seed_aux = self.seeds_with_links(keyword, auxs) if auxs else set()
        for uri in set(seeds) | set(by_main):
            label, in_label = seeds.get(uri, (by_main.get(uri, ""), False))
            in_text = uri in seeds
            lv, via = level_of(in_label, in_text, uri in seed_main or (uri in by_main), uri in seed_aux)
            if lv:
                res.members.append((uri, label or by_main.get(uri, "") or get_localname(uri), lv, "・".join(via)))
        res.members.sort(key=lambda m: ({"強": 0, "中": 1, "弱": 2}[m[2]], m[1]))
        return res


LEVEL_HELP_COMMAND = ("強 = 主な条と語（本文に2回以上）の両方、事件名に語、または語と補助条・関連語 ／ "
                      "中 = 主な条だけ、語が本文に5回以上、または関連語が多く出る ／ 弱 = 語が本文に2〜4回出るだけ")
LEVEL_HELP_SPARQL = "強 = 語と（主な・補助）リンクの両方 ／ 中 = 主なリンクだけ、またはラベルに語 ／ 弱 = 本文（要約など）に語だけ"


def _member_cells(m, det, esc):
    """要素の表の「判例」と「なぜ入ったか」のセル（作り手が詳しい手がかりを出していれば使う）"""
    uri, label, lv, via = m
    link = f'/resource?{esc(urlencode([("uri", uri)]))}'
    if not det:
        return f'<a href="{link}">{esc(label or get_localname(uri))}</a>', esc(via)
    head = " ".join(esc(x) for x in (det.get("caseno"), det.get("court"), det.get("date")) if x)
    name = det.get("casename") or ""
    item = (f'<a href="{link}">{head or esc(get_localname(uri))}</a>'
            + (f'<br><span class="topic-name">{esc(name)}</span>' if name else ""))
    why = []
    clauses = sorted(det.get("clauses") or [], key=lambda c: c.get("role") != "main")
    for c in clauses[:3]:     # 条は3つまで（多いと行が長くなる）。残りは数だけ
        why.append(f'<span class="topic-why topic-{"main" if c.get("role") == "main" else "aux"}">'
                   f'{"主な条" if c.get("role") == "main" else "補助条"}: {esc(c.get("label", ""))}</span>')
    if len(clauses) > 3:
        why.append(f'<span class="topic-why topic-aux">ほか{len(clauses) - 3}条</span>')
    for w, n in det.get("words") or []:
        why.append(f'<span class="topic-why topic-word">語「{esc(w)}」本文{n}回</span>')
    for w, n in det.get("related") or []:
        why.append(f'<span class="topic-why topic-rel">関連語「{esc(w)}」{n}回</span>')
    if det.get("name_hit"):
        why.append('<span class="topic-why topic-word">事件名に語</span>')
    return item, " ".join(why) or esc(via)


TOPIC_CSS = """<style>
.topic-steps { margin: 0.3em 0 0.8em 1.2em; } .topic-steps li { margin: 0.25em 0; }
.topic-box { border: 1px solid #ccc; border-radius: 6px; padding: 0.6em 1em; margin: 0.8em 0; }
.topic-box h3 { margin-top: 0.2em; }
.topic-why { display: inline-block; border-radius: 4px; padding: 0 0.4em; margin: 1px 2px; font-size: 90%; }
.topic-main { background: #dbe9ff; } .topic-aux { background: #eef3fb; } .topic-word { background: #e6f5e1; } .topic-rel { background: #fbf0d9; }
.topic-name { color: #555; font-size: 90%; }
.topic-lv-強 { font-weight: bold; } .topic-help { color: #555; font-size: 90%; }
.topic-filter button.on { font-weight: bold; text-decoration: underline; }
#topic-members { table-layout: fixed; width: 100%; } #topic-members td { vertical-align: top; }
#topic-members th, #topic-members td { width: auto; }   /* table.css の th, td { width: 25% } を打ち消す */
#topic-members th:first-child, #topic-members td:first-child { width: 4em; white-space: nowrap; text-align: center; }
#topic-members th:nth-child(2), #topic-members td:nth-child(2) { width: 38%; }
</style>"""

TOPIC_JS = """<script>
function kgTopicFilter(maxLevel, btn) {
  var order = {"強": 0, "中": 1, "弱": 2};
  var text = (document.getElementById("topic-q") || {}).value || "";
  var shown = 0;
  document.querySelectorAll("#topic-members tbody tr").forEach(function (tr) {
    if (maxLevel !== null) tr.dataset.max = maxLevel;
    var ok = order[tr.dataset.level] <= Number(tr.dataset.max || 2) && (!text || tr.textContent.indexOf(text) >= 0);
    tr.style.display = ok ? "" : "none"; if (ok) shown++;
  });
  if (btn) { document.querySelectorAll(".topic-filter button").forEach(function (b) { b.classList.remove("on"); }); btn.classList.add("on"); }
  var c = document.getElementById("topic-shown"); if (c) c.textContent = shown.toLocaleString();
}
</script>"""


def render_topic(res, cfg, keyword, override_given, source_url, saved_enabled):
    """トピックの案と要素のページ（HTML の本体）。1. 何をしたか 2. 結果 3. 次にできること（2026.11.1 に組み直した）"""
    from html import escape
    lv = {k: sum(1 for m in res.members if m[2] == k) for k in ("強", "中", "弱")}
    summ = res.summary or {}
    by_command = res.details is not None
    mains = [ln for ln in res.links if ln.role == "main"]
    auxs = [ln for ln in res.links if ln.role == "aux"]
    # ---- 1. 何をしたか ----
    steps = []
    if res.words is not None:
        wlist = "、".join(f'{escape(w)}<small>（{escape(k)}）</small>' for w, k in res.words)
        steps.append(f'<li>キーワード「{escape(keyword)}」を <b>{len(res.words)}語</b>に広げた（異表記・キーワードを含むターム・略語）'
                     f'<details><summary>広げた語を見る</summary>{wlist}</details></li>')
        steps.append(f'<li>広げた語をタームに持つ判例（種の判例）: <b>{res.seed_count:,}件</b> / 全体 {res.total:,}件</li>')
    else:
        steps.append(f'<li>{escape("・".join(cfg["text_properties"]))} に「{escape(keyword)}」を含む要素（種の要素）: '
                     f'<b>{res.seed_count:,}件</b>{"（上限）" if res.seed_capped else ""} / 全体 {res.total:,}件</li>')
    def lnlist(lns):
        return "<br>".join(f'{escape(ln.label)}（種で {ln.count:,}・全体で {ln.df:,}・{ln.lift:,.0f}倍）' for ln in lns) or "なし"
    steps.append(f'<li>種{"の判例" if by_command else "の要素"}がよく{"参照する条" if by_command else "リンクする先"}を、全体と比べて選んだ: '
                 f'<b>主な{"条" if by_command else "リンク"} {len(mains)}</b>（それだけで入れる）・<b>補助{"条" if by_command else "リンク"} {len(auxs)}</b>（語と一緒のときだけ確かさを上げる）'
                 f'<details><summary>選んだものを見る</summary><b>主</b>: {lnlist(mains)}<br><b>補助</b>: {lnlist(auxs)}</details></li>')
    if by_command and res.related:
        steps.append(f'<li>キーワードを使わない判例を拾う関連語: {escape("、".join(w for w, _ in res.related))}'
                     f'（文脈語 {escape("、".join(res.context or []))} と一緒のときだけ）</li>')
    if by_command and not summ.get("no_text"):
        steps.append(f'<li>全判例の本文で {summ.get("counted_words", len(res.words or [])):,}語の出現数を数えた</li>')
    steps.append(f'<li>確かさを決めた: <b>強 {lv["強"]:,}・中 {lv["中"]:,}・弱 {lv["弱"]:,}件</b>'
                 f'<div class="topic-help">{LEVEL_HELP_COMMAND if by_command else LEVEL_HELP_SPARQL}</div></li>')
    did = (f'<div class="topic-box"><h3>1. 何をしたか</h3><ol class="topic-steps">{"".join(steps)}</ol>'
           + "".join(f'<p class="saved-error">{escape(w)}</p>' for w in res.warnings)
           + (f'<p class="topic-help">画面で選び直した結果です。</p>' if override_given else "") + '</div>')
    # ---- 2. 結果 ----
    rows = []
    for m in res.members[:2000]:
        item, why = _member_cells(m, (res.details or {}).get(m[0]), escape)
        hide = ' style="display:none"' if m[2] == "弱" else ""
        rows.append(f'<tr data-level="{escape(m[2])}" data-max="1"{hide}>'
                    f'<td class="topic-lv-{escape(m[2])}">{escape(m[2])}</td><td>{item}</td><td>{why}</td></tr>')
    more = f'<p>（ほか {len(res.members) - 2000:,}件は表示していません。保存すると全部入ります）</p>' if len(res.members) > 2000 else ""
    unit = "判例" if by_command else "要素"
    result = (f'<div class="topic-box"><h3>2. 結果（{unit} {len(res.members):,}件）</h3>'
              f'<p class="topic-filter">表示: <button type="button" onclick="kgTopicFilter(0, this)">強だけ</button> '
              f'<button type="button" class="on" onclick="kgTopicFilter(1, this)">強・中（保存するもの）</button> '
              f'<button type="button" onclick="kgTopicFilter(2, this)">弱も</button> '
              f'絞り込み: <input type="text" id="topic-q" placeholder="事件名・裁判所など" oninput="kgTopicFilter(null, null)"> '
              f'<span id="topic-shown"></span>件</p>'
              f'<table class="saved-table" id="topic-members"><colgroup><col style="width:5em"><col style="width:38%"><col></colgroup><thead><tr><th>確かさ</th><th>{unit}</th><th>なぜ入ったか</th></tr></thead>'
              f'<tbody>{"".join(rows)}</tbody></table>{more}</div>')
    # ---- 3. 次にできること ----
    save = ""
    if saved_enabled:
        save = (f'<form method="POST" action="/topic/save" class="saved-merge"><input type="hidden" name="source" value="{escape(source_url)}">'
                f'<b>保存する</b>: 強・中の{unit}（{lv["強"] + lv["中"]:,}件）を <input type="text" name="name" required maxlength="60" placeholder="名前"> '
                '<label><input type="checkbox" name="weak" value="1">弱も入れる</label> '
                '<label><input type="checkbox" name="overwrite" value="1">上書き</label> '
                '<button type="submit">コレクションとして保存</button>'
                '<div class="topic-help">保存したコレクションは、ファセットで絞ったり、ほかのコレクションと合わせたりできます。</div></form>')
    lrows = []
    for ln in res.links:
        if not ln.role and ln.count < cfg["min_count"]:
            continue
        def radio(role):
            checked = " checked" if ln.role == role else ""
            return f'<input type="radio" name="r.{escape(ln.key())}" value="{role}"{checked}>'
        lrows.append(f'<tr><td>{radio("main")}</td><td>{radio("aux")}</td><td>{radio("")}</td>'
                     f'<td><a href="/resource?{escape(urlencode([("uri", ln.uri)]))}">{escape(ln.label)}</a></td>'
                     f'<td class="num">{ln.count:,}</td><td class="num">{ln.df:,}</td><td class="num">{ln.lift:,.1f}</td></tr>')
    words_html = ""
    if res.words is not None:
        boxes = "".join(f'<label><input type="checkbox" name="w" value="{escape(w)}" checked>{escape(w)}'
                        f'<small>（{escape(k)}）</small></label> <input type="hidden" name="w_all" value="{escape(w)}">'
                        for w, k in res.words)
        words_html = (f'<h4>語（チェックを外すと使わない）</h4><p>{boxes}</p>'
                      f'<p>語を足す: <input type="text" name="add_words" placeholder="| で区切る"></p>')
    if res.related is not None:
        boxes = "".join(f'<label><input type="checkbox" name="rel" value="{escape(w)}" checked>{escape(w)}'
                        f'{"<small>（主）</small>" if core else ""}</label> <input type="hidden" name="rel_all" value="{escape(w)}">'
                        for w, core in res.related)
        ctx = "、".join(escape(w) for w in (res.context or []))
        words_html += (f'<h4>関連語</h4><p class="topic-help">キーワードを使わない{unit}を拾う語。文脈語（{ctx}）と一緒に何回も出るときだけ使う。</p>'
                       f'<p>{boxes}</p><p>関連語を足す: <input type="text" name="add_related" placeholder="| で区切る"></p>')
    kind = "条" if by_command else "リンク"
    fix = (f'<details{" open" if override_given else ""}><summary><b>直す</b>（語・{kind}を選び直して作り直す）</summary>'
           f'<form method="GET" action="/topic"><input type="hidden" name="q" value="{escape(keyword)}"><input type="hidden" name="edit" value="1">'
           + words_html +
           f'<h4>{kind}</h4><p class="topic-help">主: それだけで入れる ／ 補助: 語と一緒のときだけ確かさを上げる ／ 使わない</p>'
           '<table class="saved-table"><thead><tr><th>主</th><th>補助</th><th>使わない</th><th>' + kind + '</th>'
           f'<th>種で</th><th>全体で</th><th>偏り（倍）</th></tr></thead><tbody>{"".join(lrows)}</tbody></table>'
           '<p><button type="submit">選び直して作り直す</button></p></form></details>')
    nxt = f'<div class="topic-box"><h3>3. 次にできること</h3>{save}{fix}</div>'
    head = f'<h2 class="gadget-title">トピック「{escape(keyword)}」</h2>'
    return (f'<div class="container">{TOPIC_CSS}{TOPIC_JS}{head}{did}{result}{nxt}'
            '<script>kgTopicFilter(1, document.querySelectorAll(".topic-filter button")[1]);</script></div>')


def render_topic_progress(job, source_url):
    """作っている途中のページ。2秒ごとに /topic/status で段階を取り、出来上がったら読み直す（2026.11.1）"""
    from html import escape
    status_url = "/topic/status?" + urlencode([("id", job.id)])
    return (f'<div class="container"><h2 class="gadget-title">トピック「{escape(job.keyword)}」を作っています</h2>'
            '<p>判例の本文を全部数えるので、数分かかります。このページは出来上がると自動で切り替わります。</p>'
            '<ol id="topic-progress" class="topic-steps"></ol><p>経過 <span id="topic-elapsed">0</span>秒</p>'
            '<p id="topic-error" class="saved-error"></p>'
            '<script>(function poll(){ fetch(' + repr(status_url) + ').then(function(r){return r.json();}).then(function(s){'
            ' document.getElementById("topic-elapsed").textContent = s.elapsed;'
            ' document.getElementById("topic-progress").innerHTML = s.steps.map(function(x){'
            '   return "<li>" + x.msg.replace(/&/g,"&amp;").replace(/</g,"&lt;") + "（" + x.t + "秒）</li>"; }).join("");'
            ' if (s.state === "done") { location.reload(); }'
            ' else if (s.state === "error") { document.getElementById("topic-error").textContent = s.error; }'
            ' else { setTimeout(poll, 2000); } }).catch(function(){ setTimeout(poll, 5000); }); })();</script></div>')


def _split(text):
    return [w.strip() for w in str(text or "").replace("｜", "|").split("|") if w.strip()]


def _getlist(args, key):
    if hasattr(args, "getlist"):
        return args.getlist(key)
    v = args.get(key)
    return v if isinstance(v, list) else ([v] if v else [])


def override_from_args(args):
    """画面で選び直したもの。選び直していなければ None
    リンクの役割 r.<名前>=main/aux/""、語 w（チェックしたもの）と w_all（出したもの）・add_words、関連語 rel・rel_all・add_related"""
    if not args.get("edit"):
        return None
    main, aux, none = [], [], []
    for key in args:
        if key.startswith("r."):
            role = args.get(key)
            (main if role == "main" else aux if role == "aux" else none).append(key[2:])
    w_on, w_all = set(_getlist(args, "w")), _getlist(args, "w_all")
    r_on, r_all = set(_getlist(args, "rel")), _getlist(args, "rel_all")
    return {"main": main, "aux": aux, "none": none, "links_edited": bool(main or aux or none),
            "drop_words": [w for w in w_all if w not in w_on], "add_words": _split(args.get("add_words")),
            "drop_related": [w for w in r_all if w not in r_on], "add_related": _split(args.get("add_related"))}


class CommandTopicBuilder:
    """外のコマンドが作ったトピックの案と要素を読む（判例のように、本文の語の数え方や全件の計算が重いデータ）。
    コマンドは設定 topic.command（{q} はキーワード、{json} は結果を書くファイル、{python} は KGraphNavi の Python）。画面で選び直したものは次の引数で渡す:
      --add-word 語 / --drop-word 語 / --add-related 語 / --add-clause 名前（主なリンク）/ --aux-clause 名前 / --drop-clause 名前
    結果の JSON: keyword, seed_count, total, words[{word,kind}], links[{id,uri,label,prop,count,df,lift,role}],
      related[{word,core}], context[語], members[{uri,label,level,via}]（hanrei の src/topic_keyword.py --json）"""

    CACHE = {}

    def __init__(self, cfg, base_dir=None):
        self.cfg = cfg
        self.base_dir = base_dir

    def args(self, keyword, override):
        words = _split(keyword)
        if not words:
            raise ValueError("キーワードがありません")
        extra = []
        for w in words[1:] + (override or {}).get("add_words", []):
            extra += ["--add-word", w]
        if override:
            for w in override.get("drop_words", []) + override.get("drop_related", []):
                extra += ["--drop-word", w]
            for w in override.get("add_related", []):
                extra += ["--add-related", w]
            if override.get("links_edited"):
                extra += [x for i in override.get("main", []) for x in ("--add-clause", i)]
                extra += [x for i in override.get("aux", []) for x in ("--aux-clause", i)]
                extra += [x for i in override.get("none", []) for x in ("--drop-clause", i)]
        return words[0], extra

    JOBS = {}       # 作っている途中のもの {job_id: TopicJob}（2026.11.1）

    def key_of(self, keyword, override):
        first, extra = self.args(keyword, override)
        return (first, tuple(extra))

    @staticmethod
    def job_id(key):
        import hashlib
        return hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]

    def start(self, keyword, override=None):
        """作り始める（もう作ってあれば結果を返す）。戻り値 (結果 or None, TopicJob or None)"""
        import threading
        key = self.key_of(keyword, override)
        if key in self.CACHE:
            return self.CACHE[key], None
        jid = self.job_id(key)
        job = self.JOBS.get(jid)
        if job is None or job.state == "error":
            job = TopicJob(jid, keyword, key)
            self.JOBS[jid] = job
            threading.Thread(target=self._run, args=(job, keyword, override), daemon=True).start()
        return None, job

    def build(self, keyword, override=None):
        """出来上がるまで待って結果を返す（保存のとき）"""
        res, job = self.start(keyword, override)
        if res is not None:
            return res
        job.done.wait(int(self.cfg.get("timeout") or 900) + 30)
        if job.state != "done":
            raise ValueError(job.error or "トピックを作り終えていません")
        return self.CACHE[job.key]

    def _run(self, job, keyword, override):
        import json, os, subprocess, tempfile, sys, time
        first, extra = self.args(keyword, override)
        fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
        try:
            cmd = [str(c).replace("{q}", first).replace("{json}", path).replace("{python}", sys.executable)
                   for c in self.cfg["command"]] + extra
            cwd = os.path.expanduser(str(self.cfg.get("cwd") or ".")) if self.cfg.get("cwd") else None
            timeout = int(self.cfg.get("timeout") or 900)
            logger.info("トピックの作り手: %s (cwd=%s)", cmd, cwd)
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
            tail = []
            for line in proc.stderr:     # 作り手は途中の段階を「@@進み …」で標準エラーに出す
                line = line.rstrip("\n")
                if line.startswith("@@進み "):
                    job.steps.append((time.time() - job.started, line[len("@@進み "):]))
                else:
                    tail = (tail + [line])[-20:]
                if time.time() - job.started > timeout:
                    proc.kill()
                    raise ValueError(f"トピックの作り手が {timeout}秒で終わりませんでした。語が広がり過ぎていないか確かめてください: {' '.join(cmd[1:])}")
            code = proc.wait()
            if code != 0:
                raise ValueError(f"トピックの作り手が失敗しました（{code}）: " + "\n".join(tail)[-800:])
            data = json.load(open(path, encoding="utf-8"))
            self.CACHE[job.key] = self.result_from(keyword, data)
            job.state = "done"
        except Exception as e:     # 画面に出す
            job.state, job.error = "error", str(e)
            logger.warning("トピックを作れない: %s", e)
        finally:
            job.done.set()
            try: os.remove(path)
            except OSError: pass

    @staticmethod
    def result_from(keyword, data):
        res = TopicResult(keyword, seed_count=int(data.get("seed_count", 0)), total=int(data.get("total", 0)))
        res.links = [Link(d.get("prop", ""), d["uri"], int(d.get("count", 0)), int(d.get("df", 0)), float(d.get("lift", 0)),
                          d.get("role", ""), d.get("label", ""), d.get("id", "")) for d in data.get("links", [])]
        res.members = [(m["uri"], m.get("label", ""), m["level"], m.get("via", "").replace("|", "・")) for m in data.get("members", [])]
        res.members.sort(key=lambda m: ({"強": 0, "中": 1, "弱": 2}.get(m[2], 3), m[1]))
        res.details = {m["uri"]: m for m in data.get("members", [])}
        res.summary = data.get("summary")
        res.words = [(d["word"], d.get("kind", "")) for d in data.get("words", [])]
        res.related = [(d["word"], bool(d.get("core"))) for d in data.get("related", [])]
        res.context = list(data.get("context", []))
        res.warnings = list(data.get("warnings", []))
        return res


class TopicJob:
    """作っている途中のトピック（作り手のコマンドを裏で動かす。2026.11.1）"""
    def __init__(self, jid, keyword, key):
        import threading, time
        self.id, self.keyword, self.key = jid, keyword, key
        self.started = time.time()
        self.steps = []          # [(経過秒, 段階)]
        self.state = "running"   # running / done / error
        self.error = ""
        self.done = threading.Event()

    def status(self):
        import time
        return {"state": self.state, "error": self.error, "elapsed": round(time.time() - self.started),
                "steps": [{"t": round(t), "msg": m} for t, m in self.steps]}
