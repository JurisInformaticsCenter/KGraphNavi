#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      labellinker.py
##  Author:
##      Fumihito NISHINO       nishino@nii.ac.jp
##  Description:
##      ラベルの辞書でテキストの語をリソースに結ぶリンカ（/textlink の汎用のリンカ。2026.11.10）
##      知識グラフのラベル（と別名）を SPARQL で集めて辞書（SQLite）にし、テキストの中を最長一致で探す。
##      テキストは手元だけで処理する（外へは送らない）。同じラベルのリソースが複数あれば、重み（score）で選び、
##      確かさを下げて候補を返す。
##
##  辞書を作る（設定ファイルの textlink.options.queries を使う。エンドポイントは sparql_endpoint）
##      python3 -m kgraphnavi.labellinker build config/dbpedia.yaml
##      python3 -m kgraphnavi.labellinker build config/dbpedia.yaml --tsv labels.tsv   # TSV（uri, label, score[, group]）から
##      python3 -m kgraphnavi.labellinker link config/dbpedia.yaml "Mount Fuji is ..."  # 試す
##
##  設定
##    - textlink:
##        module: kgraphnavi.labellinker
##        index: dbpedia-labels.sqlite           辞書（相対パスは設定ファイルのフォルダから）
##        options:
##          min_length: 3                        これより短いラベルは使わない（漢字・かなは min_length_cjk）
##          min_length_cjk: 2
##          ignore_case: true                    大文字・小文字を区別しない（ただし全部大文字のラベルは区別する）
##          stopwords: [The, Mount]              結ばない語
##          page_size: 10000                     SPARQL の1回の行数
##          queries:                             ?s ?label（必須）、?score（重み。省略可）を返す SELECT
##            - name: 山
##              query: SELECT ?s ?label ?score WHERE { ... }
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

logger = logging.getLogger(__name__)

FORMAT = "kgraphnavi-labels/1"
DEFAULT_OPTIONS = {"min_length": 3, "min_length_cjk": 2, "ignore_case": True, "stopwords": [], "page_size": 10000,
                   "max_label_length": 80}

# 画面の文言（textlink の labels。設定で上書きできる）
LABELS = {
    "description": "テキストを貼り付けて「リンクを付ける」を押すと、知識グラフのラベル（と別名）にあたる語を見つけ、"
                   "リソースのページへのリンクにします。テキストは保存しません。同じことを Web API（/api/textlink）でもできます。",
    "placeholder": "例: Mount Fuji is the highest mountain in Japan.",
    "item": "見つけた語", "key": "リソース", "id": "", "in_data": "",
    "legend": "下線の実線は確かさ「高」（ラベルが1つのリソースだけのもの）、破線は「中」（同じラベルのリソースが複数で、重みで選んだもの）、"
              "点線は「低」（短い語・決め手の無いもの）",
}

CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯]")


def is_word_char(ch):
    """語の境目を見る文字（英数字）。漢字・かなは境目を見ない"""
    return ch.isalnum() and not CJK.match(ch)


def normalize(text, ignore_case=True):
    """→ (正規化した文字列, 元の位置の表)。NFKC・空白の連続を1つに・（ignore_case なら）小文字。
    位置の表 pos[i] は、正規化した i 文字目の元の位置（末尾に元の長さ）"""
    out, pos = [], []
    space = False
    for i, ch in enumerate(text):
        n = unicodedata.normalize("NFKC", ch)
        if ignore_case:
            n = n.casefold()
        if n.isspace() or not n:
            if n and not space and out:
                out.append(" "); pos.append(i)
            space = bool(n)
            continue
        space = False
        for c in n:
            out.append(c); pos.append(i)
    pos.append(len(text))
    return "".join(out), pos


def label_key(label, ignore_case=True):
    """辞書の見出し。全部大文字の略語（NASA・US）は大文字のまま（"us" と区別する）"""
    s = normalize(label.strip(), ignore_case=False)[0].strip()
    if ignore_case and not (s.isupper() and len(s) <= 6):
        s = s.casefold()
    return s


def localname(uri):
    from urllib.parse import unquote
    return unquote(re.split(r"[/#]", uri.rstrip("/"))[-1]).replace("_", " ")


# ---- 辞書を作る ---------------------------------------------------------------

def rows_from_sparql(client, queries, page_size):
    """queries の SELECT を LIMIT/OFFSET で繰り返し → (uri, label, score, group)"""
    for q in queries:
        name, query = q.get("name", ""), q["query"].strip()
        offset = 0
        while True:
            page = client.query(f"{query}\nLIMIT {page_size} OFFSET {offset}")
            for r in page:
                if "s" not in r or "label" not in r:
                    continue
                score = r.get("score", {}).get("value")
                try:
                    score = float(score) if score is not None else 0.0
                except ValueError:
                    score = 0.0
                yield r["s"]["value"], r["label"]["value"], score, name
            logger.info("%s: %d 行（%d から）", name, len(page), offset)
            print(f"  {name}: {offset + len(page)} 行", file=sys.stderr)
            if len(page) < page_size:
                break
            offset += page_size


def rows_from_tsv(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            yield cols[0], cols[1], float(cols[2]) if len(cols) > 2 and cols[2] else 0.0, cols[3] if len(cols) > 3 else ""


def build(rows, path, options=None, meta=None):
    """(uri, label, score, group) の並び → 辞書の SQLite。同じ (見出し, uri) は score の大きい方"""
    opts = dict(DEFAULT_OPTIONS, **(options or {}))
    best = {}
    names = {}
    for uri, label, score, group in rows:
        label = (label or "").strip()
        if not label or len(label) > opts["max_label_length"]:
            continue
        k = label_key(label, opts["ignore_case"])
        if (k, uri) not in best or score > best[(k, uri)][1]:
            best[(k, uri)] = (label, score, group)
        names.setdefault(uri, label)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode=MEMORY")
    con.executescript("""CREATE TABLE label (key TEXT, uri TEXT, label TEXT, score REAL, grp TEXT);
                         CREATE TABLE name (uri TEXT PRIMARY KEY, label TEXT);
                         CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT);""")
    con.executemany("INSERT INTO label VALUES (?, ?, ?, ?, ?)",
                    [(k, u, l, s, g) for (k, u), (l, s, g) in best.items()])
    con.executemany("INSERT INTO name VALUES (?, ?)", names.items())
    import datetime
    info = {"format": FORMAT, "built": datetime.date.today().isoformat(), "labels": str(len(best)),
            "resources": str(len(names)), "ignore_case": str(opts["ignore_case"])}
    info.update(meta or {})
    con.executemany("INSERT INTO meta VALUES (?, ?)", sorted(info.items()))
    con.commit()
    con.close()
    os.replace(tmp, path)
    return info


# ---- 結ぶ -----------------------------------------------------------------------

class LabelIndex:
    def __init__(self, path, options=None):
        self.opts = dict(DEFAULT_OPTIONS, **(options or {}))
        con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro&immutable=1", uri=True)
        self.meta = dict(con.execute("SELECT name, value FROM meta"))
        if self.meta.get("format") != FORMAT:
            raise ValueError(f"辞書の形が違います: {self.meta.get('format')}（この版は {FORMAT}）")
        self.opts["ignore_case"] = self.meta.get("ignore_case", "True") == "True"
        stop = {label_key(w, self.opts["ignore_case"]) for w in self.opts.get("stopwords") or []}
        self.entries = defaultdict(list)          # 見出し → [(uri, score, label, group)]
        self.lengths = defaultdict(set)           # 見出しの先頭の文字 → 見出しの長さ
        for key, uri, label, score, grp in con.execute("SELECT key, uri, label, score, grp FROM label"):
            if key in stop or key.isdigit():
                continue
            short = self.opts["min_length_cjk"] if CJK.search(key) else self.opts["min_length"]
            if len(key) < short:
                continue
            self.entries[key].append((uri, score or 0.0, label, grp or ""))
            self.lengths[key[0]].add(len(key))
        self.names = dict(con.execute("SELECT uri, label FROM name"))
        con.close()
        self.lengths = {c: sorted(v, reverse=True) for c, v in self.lengths.items()}

    def find(self, text):
        """→ [(start, end, 見出し, [(uri, score, label, group)])]（左から、最長一致、重ならない）"""
        ic = self.opts["ignore_case"]
        folded, pos = normalize(text, ic)
        plain = normalize(text, False)[0] if ic else folded     # 全部大文字の見出し用（位置は同じ）
        found, i, n = [], 0, len(folded)
        while i < n:
            hit = None
            if i == 0 or not (is_word_char(folded[i - 1]) and is_word_char(folded[i])):
                for src in ((folded, plain) if ic else (folded,)):
                    for L in self.lengths.get(src[i], ()):
                        if i + L > n:
                            continue
                        cand = src[i:i + L]
                        if cand not in self.entries:
                            continue
                        j = i + L
                        if j < n and is_word_char(src[j - 1]) and is_word_char(src[j]):
                            continue                    # 語の途中で切れる
                        if hit is None or L > hit[1] - hit[0]:
                            hit = (i, j, cand)
                        break
            if hit:
                s, e, key = hit
                found.append((pos[s], pos[e - 1] + 1, key, self.entries[key]))
                i = e
            else:
                i += 1
        return found


def choose(cands, key, opts):
    """候補 → (選んだ uri, 確かさ, 決め方, 候補の uri)"""
    by_uri = {}
    for uri, score, label, grp in cands:
        if uri not in by_uri or score > by_uri[uri][0]:
            by_uri[uri] = (score, grp)
    ranked = sorted(by_uri.items(), key=lambda x: (-x[1][0], x[0]))
    top, (score, grp) = ranked[0]
    short = len(key) < (opts["min_length_cjk"] + 1 if CJK.search(key) else opts["min_length"] + 2)
    if len(ranked) == 1:
        return top, ("中" if short else "高"), "ラベル" + (f"（{grp}）" if grp else ""), []
    second = ranked[1][1][0]
    others = [u for u, _ in ranked[1:6]]
    if score > 0 and score >= 2 * max(second, 0) and not short:
        return top, "中", f"ラベル（候補 {len(ranked)}。重みで選んだ）", others
    return top, "低", f"ラベル（候補 {len(ranked)}。決め手が無い）", others


CONF = {"高": 3, "中": 2, "低": 1}


def make_linker(options):
    """KGraphNavi の textlink から呼ばれる。options: index（辞書のパス）、min_length など"""
    path = options.get("index")
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"ラベルの辞書がありません: {path}（python3 -m kgraphnavi.labellinker build <設定ファイル>）")
    index = LabelIndex(path, options)

    def run(text, min_confidence="低"):
        th = CONF.get(min_confidence or "低", 1)
        out = []
        for start, end, key, cands in index.find(text):
            uri, conf, method, others = choose(cands, key, index.opts)
            ok = CONF[conf] >= th
            item = {"start": start, "end": end, "text": text[start:end], "linked": ok, "method": method,
                    "confidence": conf, "candidates": [index.names.get(u, localname(u)) + " <" + u + ">" for u in others],
                    "key": index.names.get(uri, localname(uri)), "id_uri": uri, "in_data": True}
            if ok:
                item["target"] = uri
            out.append(item)
        return out

    run.meta = dict(index.meta, linker="kgraphnavi.labellinker")
    return run


# ---- コマンド -------------------------------------------------------------------

def _settings(config_path):
    from .app import load_config
    cfg = load_config(config_path)
    tl = cfg.get("textlink")
    if not tl or tl.get("module") != "kgraphnavi.labellinker":
        raise SystemExit(f"{config_path} に textlink:（module: kgraphnavi.labellinker）がありません")
    if not tl.get("index"):
        raise SystemExit("textlink.index に辞書のパスを書いてください")
    return cfg, tl


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m kgraphnavi.labellinker", description="ラベルの辞書を作る・試す")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="設定の textlink.options.queries で辞書を作る")
    p.add_argument("config")
    p.add_argument("--tsv", help="SPARQL の代わりに TSV（uri, label, score[, group]）から")
    p.add_argument("--endpoint", help="SPARQL エンドポイント（既定は設定の sparql_endpoint）")
    p = sub.add_parser("link", help="テキストを結んでみる")
    p.add_argument("config")
    p.add_argument("text", help="テキスト（- で標準入力）")
    args = ap.parse_args(argv)
    cfg, tl = _settings(args.config)
    options = tl.get("options") or {}
    if args.cmd == "build":
        if args.tsv:
            rows, source = rows_from_tsv(args.tsv), args.tsv
        else:
            from .sparql import SPARQL
            endpoint = args.endpoint or cfg.get("sparql_endpoint")
            queries = options.get("queries") or []
            if not queries:
                raise SystemExit("textlink.options.queries に、?s ?label（?score）を返す SELECT を書いてください")
            rows, source = rows_from_sparql(SPARQL(endpoint, cfg.get("prefixes")), queries,
                                            int(options.get("page_size", DEFAULT_OPTIONS["page_size"]))), endpoint
        info = build(rows, tl["index"], options, {"source": source})
        print(f"{tl['index']}: ラベル {info['labels']}、リソース {info['resources']}")
    else:
        text = sys.stdin.read() if args.text == "-" else args.text
        run = make_linker(dict(options, index=tl["index"]))
        print(json.dumps(run(text), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
