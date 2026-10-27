#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      collection.py
##  Description:
##      Resource集合（コレクション）を表す・操作する
##
##  コレクションは「?uri を束縛するSPARQLの条件」を式木として表す。
##
##      ClassCollection      クラスのインスタンス          ?uri a <C> .
##      AnyCollection        すべてのリソース（検索語などの条件を付けて使う）
##      QueryCollection      ?uri を返すSELECT
##      UriCollection        URIの列挙                     VALUES ?uri { ... }
##      FilteredCollection   絞り込み条件（Condition）を追加
##      UnionCollection      和   A ∪ B                    { A } UNION { B }
##      IntersectCollection  積   A ∩ B                    { A } { B }
##      MinusCollection      差   A − B                    { A } MINUS { B }
##
##  いずれも遅延評価で、生成時にはSPARQLを実行しない。get_uris()、count()、
##  get_facets() が呼ばれた時点でクエリを実行する。
##  コレクションはイミュータブルで、filter() や union() は新しいコレクションを返す。
##
##  ガジェットには to_subquery() で副問い合わせとして埋め込む。副問い合わせは
##  ?entity（など指定した変数）だけを外に出すので、コレクション内部の変数が
##  ガジェットの変数と衝突しない。
"""

import re
import logging
from dataclasses import dataclass

from .errors import CollectionError
from .terms import (
    ValueTermError,
    iri_term,
    literal_term,
    language_tag,
    typed_term,
    number_term,
    predicate_term,
    normalize_typed_value,
    DATATYPES,
    XSD,
)

logger = logging.getLogger(__name__)

VALUE_TYPES = ("iri", "literal", "auto")
RANGE_UNITS = (None, "year")


def _indent(text, spaces=4):
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


# bif:contains の検索式で特別な意味を持つ文字（語から取り除く）
_BIF_SPECIAL = re.compile(r'[\\"\'*()&|!~^<>\[\]{}:;,.?+=/-]+')


def bif_text_expression(text):
    """検索語を Virtuoso の bif:contains の検索式にする。

    空白で区切った語をそれぞれ "語" とし、AND でつなぐ（例: 写真 著作 → "写真" AND "著作"）。
    検索式の記号は取り除く。語が残らなければ None。
    """
    words = [_BIF_SPECIAL.sub(" ", word).strip() for word in str(text or "").split()]
    words = [w for part in words for w in part.split() if w]
    if not words:
        return None
    return " AND ".join(f'"{word}"' for word in words)


def numeric_expression(datatype=None, unit=None, var="?_v"):
    """範囲ファセットで値 var を数値にする SPARQL の式を返す。

    日付（date / dateTime）や unit="year" は年、gYear は先頭4桁、それ以外は decimal。
    文字列として格納された値（"2003" など）も数値に変換して扱う。
    """
    if unit == "year" or datatype in ("date", "dateTime"):
        return f"YEAR({var})"
    if datatype == "gYear":
        return f"<{XSD}integer>(SUBSTR(STR({var}), 1, 4))"
    return f"<{XSD}decimal>({var})"


# 範囲の比較を数値で行うデータ型（それ以外の date / dateTime は日付として比較する）
NUMERIC_DATATYPES = ("integer", "decimal", "double", "gYear")


# --------------------------------------------------
# 絞り込み条件
# --------------------------------------------------

@dataclass(frozen=True)
class ValueCondition:
    """predicate の値が values のいずれかに一致する（同じ条件内の複数値は OR）。

    value_type:
        iri      値はIRI
        literal  値は文字列リテラル（言語タグ・型は問わず、文字列として比較）
        auto     IRIとして解釈できればIRI、そうでなければ文字列
    """

    predicate: str
    values: tuple
    value_type: str = "auto"
    name: str | None = None

    def __post_init__(self):
        if self.value_type not in VALUE_TYPES:
            raise CollectionError(f"未対応のvalue_typeです: {self.value_type!r}")
        if not self.values:
            raise CollectionError("絞り込みの値がありません")
        # 生成時に検証しておく（不正な値はここで例外になる）
        predicate_term(self.predicate)
        self._terms()

    def _terms(self):
        iris, literals = [], []
        for value in self.values:
            if self.value_type == "iri":
                iris.append(iri_term(value))
            elif self.value_type == "literal":
                literals.append(literal_term(value))
            else:
                try:
                    iris.append(iri_term(value))
                except ValueTermError:
                    literals.append(literal_term(value))
        return iris, literals

    def pattern(self, var, index):
        predicate = predicate_term(self.predicate)
        iris, literals = self._terms()
        if len(iris) == 1 and not literals:
            return f"{var} {predicate} {iris[0]} ."
        value_var = f"?_c{index}"
        tests = []
        if iris:
            tests.append(f"{value_var} IN ({', '.join(iris)})")
        if literals:
            tests.append(
                f"(isLiteral({value_var}) && STR({value_var}) IN ({', '.join(literals)}))"
            )
        return (
            f"{var} {predicate} {value_var} .\n"
            f"FILTER({' || '.join(tests)})"
        )


@dataclass(frozen=True)
class RangeCondition:
    """predicate の値が minimum 以上 maximum 以下（片側のみも可）。

    datatype: integer | decimal | double | date | dateTime | gYear
    unit:     "year" のとき、date/dateTime の値を YEAR() で年に変換して比較する
    """

    predicate: str
    datatype: str
    minimum: object = None
    maximum: object = None
    unit: str | None = None
    name: str | None = None

    def __post_init__(self):
        if self.datatype not in DATATYPES:
            raise CollectionError(f"未対応のdatatypeです: {self.datatype!r}")
        if self.unit not in RANGE_UNITS:
            raise CollectionError(f"未対応のunitです: {self.unit!r}")
        if self.minimum in (None, "") and self.maximum in (None, ""):
            raise CollectionError("範囲の下限・上限のどちらもありません")
        predicate_term(self.predicate)
        self._bounds()

    def _numeric(self):
        """数値として比較するか（unit: year、または数値のデータ型）"""
        return self.unit == "year" or self.datatype in NUMERIC_DATATYPES

    def _bound(self, value):
        if value in (None, ""):
            return None
        if self.unit == "year":
            return number_term(value)
        if self._numeric():
            return number_term(normalize_typed_value(value, self.datatype))
        return typed_term(value, self.datatype)

    def _bounds(self):
        return self._bound(self.minimum), self._bound(self.maximum)

    def pattern(self, var, index):
        predicate = predicate_term(self.predicate)
        value_var = f"?_c{index}"
        if self._numeric():
            # 文字列で格納された値も数値に変換して比較する（変換できない値は条件を満たさない）
            subject = numeric_expression(self.datatype, self.unit, value_var)
        else:
            subject = f"<{XSD}{self.datatype}>({value_var})"
        low, high = self._bounds()
        tests = []
        if low is not None:
            tests.append(f"{subject} >= {low}")
        if high is not None:
            tests.append(f"{subject} <= {high}")
        return (
            f"{var} {predicate} {value_var} .\n"
            f"FILTER({' && '.join(tests)})"
        )


@dataclass(frozen=True)
class TextCondition:
    """ラベル（label_predicate の値）に検索語 text を含む（2026.10.19）。

    空白で区切った語は、すべてを含む（AND）。大文字小文字は区別しない。
    method: "contains"（SPARQL の CONTAINS。ラベルを全件走査する）
            "bif"（Virtuoso の全文索引 bif:contains で先に絞り、そのうえで CONTAINS で確かめる）
    exact:  ラベルが検索語と一致する（完全一致）
    """

    text: str
    label_predicate: str = "rdfs:label"
    method: str = "contains"
    exact: bool = False
    name: str | None = "q"

    def __post_init__(self):
        if not str(self.text or "").strip():
            raise CollectionError("検索語がありません")
        if self.method not in ("contains", "bif"):
            raise CollectionError(f"未対応の検索の方法です: {self.method!r}")
        predicate_term(self.label_predicate)

    def words(self):
        return [w for w in str(self.text).split() if w]

    def pattern(self, var, index):
        predicate = predicate_term(self.label_predicate)
        label_var = f"?_c{index}"
        lines = [f"{var} {predicate} {label_var} ."]
        if self.method == "bif" and (expression := bif_text_expression(self.text)):
            lines.append(f"{label_var} bif:contains {literal_term(expression)} .")
        if self.exact:
            lines.append(f"FILTER(STR({label_var}) = {literal_term(str(self.text).strip())})")
        else:
            tests = [f"CONTAINS(LCASE(STR({label_var})), {literal_term(word.lower())})" for word in self.words()]
            lines.append(f"FILTER({' && '.join(tests)})")
        return "\n".join(lines)


# --------------------------------------------------
# コレクション
# --------------------------------------------------

class Collection:
    """コレクションの基底クラス。

    サブクラスは _pattern()（?uri を束縛するグラフパターン）を実装する。
    """

    def __init__(self, sparql, params=None):
        self.sparql = sparql
        self.params = dict(params or {})

    # ---- 生成 ----

    @classmethod
    def from_uris(cls, sparql, uris):
        """URI一覧からCollectionを作成する。"""
        return UriCollection(sparql, uris)

    @classmethod
    def from_query(cls, sparql, query, params=None):
        """?uri を返すSPARQL queryからCollectionを作成する。"""
        return QueryCollection(sparql, query, params=params)

    @classmethod
    def from_class(cls, sparql, class_uri):
        """クラスに属するResourceのCollectionを作成する。"""
        return ClassCollection(sparql, class_uri)

    # ---- 組み合わせ ----

    def where(self, *conditions):
        """条件を追加した新しいCollectionを返す。"""
        if not conditions:
            return self
        return FilteredCollection(self, conditions)

    def filter(self, predicate, value, *, value_type="auto", name=None):
        """predicate の値が value（リストなら いずれか）に一致する条件を追加する。"""
        values = tuple(value) if isinstance(value, (list, tuple, set)) else (value,)
        return self.where(ValueCondition(predicate, values, value_type=value_type, name=name))

    def search(self, text, *, label_predicate="rdfs:label", method="contains", exact=False, name="q"):
        """ラベルに検索語を含む条件を追加する（TextCondition）。"""
        return self.where(TextCondition(text, label_predicate, method=method, exact=exact, name=name))

    def filter_range(self, predicate, datatype, minimum=None, maximum=None, *, unit=None, name=None):
        """predicate の値が範囲に入る条件を追加する。"""
        return self.where(
            RangeCondition(predicate, datatype, minimum, maximum, unit=unit, name=name)
        )

    def union(self, other):
        return UnionCollection(self, other)

    def intersect(self, other):
        return IntersectCollection(self, other)

    def minus(self, other):
        return MinusCollection(self, other)

    __or__ = union
    __and__ = intersect
    __sub__ = minus

    # ---- 構造 ----

    @property
    def conditions(self):
        """このCollection自身に直接付いている絞り込み条件（なければ空）"""
        return ()

    @property
    def base(self):
        """絞り込み条件を除いた元のCollection"""
        return self

    def without(self, names):
        """指定した名前の条件を外したCollectionを返す（ファセットの候補計算用）。"""
        return self

    def all_params(self):
        """このCollectionと構成要素のクエリに渡すパラメータ"""
        return dict(self.params)

    # ---- SPARQL生成 ----

    def _pattern(self):
        raise NotImplementedError

    def pattern(self, var="?uri"):
        """var を束縛するグラフパターンを返す。"""
        body = self._pattern()
        if var == "?uri":
            return body
        return self._scoped(var, body)

    @staticmethod
    def _scoped(var, body):
        return (
            f"{{ SELECT DISTINCT (?uri AS {var})\n"
            f"  WHERE {{\n{_indent(body)}\n  }}\n}}"
        )

    def to_subquery(self, var="?entity", limit=None, offset=None):
        """ガジェットのSPARQLに埋め込む副問い合わせを返す。var だけを外に出す。

        limit / offset を指定すると、URI の順に並べたうえでその範囲だけを返す（ページ送り用）。
        """
        head = "SELECT DISTINCT ?uri" if var == "?uri" else f"SELECT DISTINCT (?uri AS {var})"
        modifiers = ""
        if limit is not None:
            modifiers = f"\n  ORDER BY ?uri\n  LIMIT {int(limit)}"
            if offset:
                modifiers += f"\n  OFFSET {int(offset)}"
        return f"{{ {head}\n  WHERE {{\n{_indent(self._pattern())}\n  }}{modifiers}\n}}"

    def get_condition(self, variable="?entity"):
        """（互換用）to_subquery() と同じ"""
        return self.to_subquery(variable)

    def get_query(self, limit=None, offset=None, order=False):
        """CollectionのURIを取得するSELECTを返す。"""
        query = f"SELECT DISTINCT ?uri\nWHERE {{\n{_indent(self._pattern())}\n}}"
        if order:
            query += "\nORDER BY ?uri"
        if limit is not None:
            query += f"\nLIMIT {int(limit)}"
        if offset:
            query += f"\nOFFSET {int(offset)}"
        return query

    def count_query(self):
        return (
            "SELECT (COUNT(DISTINCT ?uri) AS ?count)\n"
            f"WHERE {{\n{_indent(self._pattern())}\n}}"
        )

    def facet_query(self, predicate, *, label_predicate="rdfs:label", lang=None, limit=None,
                    search=None, search_method="contains", value_type="auto"):
        """predicate の値ごとの件数を求めるSELECTを返す。

        search: 値のラベル（IRIでない値はその値自身）にこの語句を含む候補だけにする
                （大文字小文字を区別しない）
        search_method: "contains"（SPARQL の CONTAINS。どのストアでも使えるが、ラベルを全件走査する）
                       "bif"（Virtuoso の全文索引 bif:contains。語単位の一致）
        value_type: "iri" ならラベルだけ、"literal" なら値自身だけを bif:contains で探す
        """
        predicate = predicate_term(predicate)
        label_predicate = predicate_term(label_predicate)
        lang_filter = ""
        if lang:
            lang_filter = f"\n        FILTER(LANGMATCHES(LANG(?_label), {literal_term(language_tag(lang))}))"
        search_filter = ""
        text_expression = bif_text_expression(search) if search and search_method == "bif" else None
        if text_expression:
            # 全文索引で先にラベルが一致する値を絞り、それからコレクションと突き合わせる
            expression = literal_term(text_expression)
            branches = []
            if value_type != "literal":  # IRI の値はラベルで探す
                branches.append(
                    f"?value {label_predicate} ?_search_label .\n"
                    f"?_search_label bif:contains {expression} ."
                )
            if value_type != "iri":  # 文字列の値はその値自身で探す
                branches.append(
                    f"?_search_uri {predicate} ?value .\n"
                    f"?value bif:contains {expression} ."
                )
            pattern = "\nUNION\n".join("{\n" + _indent(b) + "\n}" for b in branches)
            search_filter = (
                "    {\n"
                "        SELECT DISTINCT ?value WHERE {\n"
                f"{_indent(_indent(_indent(pattern)))}\n"
                "        }\n"
                "    }\n"
            )
        elif search:
            needle = literal_term(str(search).strip().lower())
            search_filter = (
                "    OPTIONAL {\n"
                f"        ?value {label_predicate} ?_search_label .\n"
                "    }\n"
                "    FILTER(CONTAINS(LCASE(STR(COALESCE(?_search_label, ?value))), "
                f"{needle}))\n"
            )
        query = (
            "SELECT ?value (SAMPLE(?_label) AS ?label) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{search_filter if text_expression else ''}"
            f"{_indent(self.to_subquery('?uri'))}\n"
            f"    ?uri {predicate} ?value .\n"
            f"{'' if text_expression else search_filter}"
            "    OPTIONAL {\n"
            f"        ?value {label_predicate} ?_label .{lang_filter}\n"
            "    }\n"
            "}\n"
            "GROUP BY ?value\n"
            "ORDER BY DESC(?count) ?value"
        )
        if limit is not None:
            query += f"\nLIMIT {int(limit)}"
        return query

    def _numeric_pattern(self, predicate, datatype=None, unit=None):
        """?uri の predicate の値を数値 ?_n にするパターン（数値にできない値は除く）"""
        predicate = predicate_term(predicate)
        expression = numeric_expression(datatype, unit)
        return (
            f"{_indent(self.to_subquery('?uri'))}\n"
            f"    ?uri {predicate} ?_v .\n"
            f"    BIND({expression} AS ?_n)\n"
            "    FILTER(BOUND(?_n))\n"
        )

    def range_query(self, predicate, *, datatype=None, unit=None):
        """predicate の値（数値、日付なら年）の最小値・最大値・件数を求めるSELECTを返す。"""
        return (
            "SELECT (MIN(?_n) AS ?min) (MAX(?_n) AS ?max) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{self._numeric_pattern(predicate, datatype, unit)}"
            "}"
        )

    def histogram_query(self, predicate, low, width, *, datatype=None, unit=None):
        """predicate の値を low から幅 width の区間に分け、区間ごとの件数を求めるSELECTを返す。

        区間の番号 ?bin は 0 始まり（FLOOR((値 - low) / width)）。
        """
        low = number_term(low)
        width = number_term(width)
        return (
            "SELECT ?bin (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{self._numeric_pattern(predicate, datatype, unit)}"
            f"    BIND(FLOOR((?_n - {low}) / {width}) AS ?bin)\n"
            "}\n"
            "GROUP BY ?bin\n"
            "ORDER BY ?bin"
        )

    # ---- 実行 ----

    def _run(self, query):
        logger.debug("Collection query=\n%s", query)
        return self.sparql.query(query, self.all_params())

    def get_uris(self, variable="uri", limit=None, offset=None):
        """Collectionに含まれるResourceのURIを返す。"""
        results = self._run(self.get_query(limit=limit, offset=offset, order=limit is not None))
        return [
            row[variable]["value"]
            for row in results
            if variable in row
        ]

    def count(self):
        """Collectionに含まれるResourceの数を返す（結果は覚えておき、2回目以降は再計算しない）。"""
        cached = getattr(self, "_count_cache", None)
        if cached is not None:
            return cached
        results = self._run(self.count_query())
        count = int(results[0]["count"]["value"]) if results else 0
        self._count_cache = count
        return count

    def _rank_pattern(self, predicate, value_class=None, value_filter=None):
        """順位表（rank）の集計の WHERE の中身: コレクションの要素 ?uri と、まとめる値 ?value。
        value_filter は設定ファイルに書いた FILTER の式（?value の条件）"""
        predicate = predicate_term(predicate)
        pattern = f"{_indent(self.to_subquery('?uri'))}\n    ?uri {predicate} ?value ."
        if value_class:
            pattern += f"\n    ?value a {iri_term(value_class)} ."
        if value_filter:
            pattern += f"\n    FILTER({value_filter})"
        return pattern

    def rank_query(self, predicate, *, value_class=None, value_filter=None, label_predicate="rdfs:label", lang=None,
                   order="count", limit=None, offset=None):
        """順位表: predicate の値ごとに要素を数え、件数の多い順（order="value" なら値の順）に返すSELECT（2026.10.20）。

        facet_query と同じ数え方（要素の COUNT DISTINCT）で、ページ送り（offset）と値のクラスの限定を加えたもの。
        同じ件数の値は値の順に並べ、ページ送りで行がずれないようにする。
        """
        label_predicate = predicate_term(label_predicate)
        lang_filter = ""
        if lang:
            lang_filter = f"\n        FILTER(LANGMATCHES(LANG(?_label), {literal_term(language_tag(lang))}))"
        order_by = "ORDER BY ?value" if order == "value" else "ORDER BY DESC(?count) ?value"
        query = (
            "SELECT ?value (SAMPLE(?_label) AS ?label) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{self._rank_pattern(predicate, value_class, value_filter)}\n"
            "    OPTIONAL {\n"
            f"        ?value {label_predicate} ?_label .{lang_filter}\n"
            "    }\n"
            "}\n"
            "GROUP BY ?value\n"
            f"{order_by}"
        )
        if limit is not None:
            query += f"\nLIMIT {int(limit)}"
        if offset:
            query += f"\nOFFSET {int(offset)}"
        return query

    def rank_total_query(self, predicate, *, value_class=None, value_filter=None):
        """順位表の値の種類の数"""
        return (
            "SELECT (COUNT(DISTINCT ?value) AS ?total)\n"
            "WHERE {\n"
            f"{self._rank_pattern(predicate, value_class, value_filter)}\n"
            "}"
        )

    def rank_above_query(self, predicate, count, *, value_class=None, value_filter=None):
        """件数が count より多い値の数（そのページの最初の行の順位を決める）"""
        return (
            "SELECT (COUNT(*) AS ?above)\n"
            "WHERE {\n"
            "    {\n"
            "        SELECT ?value (COUNT(DISTINCT ?uri) AS ?c)\n"
            "        WHERE {\n"
            f"{_indent(_indent(self._rank_pattern(predicate, value_class, value_filter)))}\n"
            "        }\n"
            "        GROUP BY ?value\n"
            "    }\n"
            f"    FILTER(?c > {int(count)})\n"
            "}"
        )

    def _ratio_core(self, predicate, denominator, *, value_class=None, value_filter=None,
                    label_predicate="rdfs:label", lang=None, min_denominator=None):
        """比の順位表の WHERE の中身: 値ごとの件数（?count）と分母（?denominator）と比（?ratio）（2026.10.21）。

        denominator は ?value と ?denominator を返す SELECT（設定ファイルに書く。コレクションの条件は掛からない）。
        """
        label_predicate = predicate_term(label_predicate)
        lang_filter = ""
        if lang:
            lang_filter = f"\n            FILTER(LANGMATCHES(LANG(?_label), {literal_term(language_tag(lang))}))"
        minimum = f"\n    FILTER(?denominator >= {float(min_denominator)})" if min_denominator else ""
        return (
            "    {\n"
            "        SELECT ?value (SAMPLE(?_label) AS ?label) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "        WHERE {\n"
            f"{_indent(_indent(self._rank_pattern(predicate, value_class, value_filter)))}\n"
            "            OPTIONAL {\n"
            f"                ?value {label_predicate} ?_label .{lang_filter}\n"
            "            }\n"
            "        }\n"
            "        GROUP BY ?value\n"
            "    }\n"
            "    {\n"
            f"{_indent(_indent(denominator.strip()))}\n"
            "    }\n"
            "    FILTER(?denominator > 0)"
            f"{minimum}\n"
            "    BIND(xsd:double(?count) / xsd:double(?denominator) AS ?ratio)"
        )

    def get_ratio_rank(self, predicate, denominator, *, value_class=None, value_filter=None,
                       label_predicate="rdfs:label", lang=None, min_denominator=None, limit=50, offset=0):
        """比の順位表（件数 ÷ 分母の大きい順）の1ページ分の行と、値の種類の数を返す（2026.10.21）。

        返り値の行には rank・value・label・count・denominator・ratio が入る。比が同じなら同じ順位。
        """
        core = self._ratio_core(predicate, denominator, value_class=value_class, value_filter=value_filter,
                                label_predicate=label_predicate, lang=lang, min_denominator=min_denominator)
        query = (
            "SELECT ?value ?label ?count ?denominator ?ratio\nWHERE {\n" + core + "\n}\n"
            "ORDER BY DESC(?ratio) DESC(?count) ?value"
            + (f"\nLIMIT {int(limit)}" if limit is not None else "")
            + (f"\nOFFSET {int(offset)}" if offset else "")
        )
        rows = []
        for row in self._run(query):
            value = row["value"]["value"]
            rows.append({
                "value": value,
                "label": row.get("label", {}).get("value") or value,
                "count": int(float(row["count"]["value"])),
                "denominator": float(row["denominator"]["value"]),
                "ratio": float(row["ratio"]["value"]),
                "type": row["value"].get("type", "literal"),
            })
        total_rows = self._run("SELECT (COUNT(DISTINCT ?value) AS ?total)\nWHERE {\n" + core + "\n}")
        total = int(total_rows[0]["total"]["value"]) if total_rows else 0
        if rows:
            rank = 1
            if offset:
                above = self._run(
                    "SELECT (COUNT(DISTINCT ?value) AS ?above)\nWHERE {\n" + core
                    + f"\n    FILTER(?ratio > {rows[0]['ratio']!r})\n}}"
                )
                rank = (int(above[0]["above"]["value"]) if above else 0) + 1
            previous = None
            for i, row in enumerate(rows):
                if previous is not None and abs(row["ratio"] - previous) > 1e-12:
                    rank = (offset or 0) + i + 1
                row["rank"] = rank
                previous = row["ratio"]
        return {"rows": rows, "total": total}

    def get_rank(self, predicate, *, value_class=None, value_filter=None, label_predicate="rdfs:label", lang=None,
                 order="count", limit=50, offset=0):
        """順位表の1ページ分の行と、値の種類の数を返す。

        返り値: {"rows": [{"rank", "value", "label", "count", "type"}, ...], "total": 値の種類の数}
        rank は同じ件数を同じ順位にする（1・2・2・4）。order="value" のときは並び順の番号。
        """
        rows = []
        for row in self._run(self.rank_query(predicate, value_class=value_class, value_filter=value_filter, label_predicate=label_predicate,
                                             lang=lang, order=order, limit=limit, offset=offset)):
            value = row["value"]["value"]
            rows.append({
                "value": value,
                "label": row.get("label", {}).get("value") or value,
                "count": int(row["count"]["value"]),
                "type": row["value"].get("type", "literal"),
            })
        total_rows = self._run(self.rank_total_query(predicate, value_class=value_class, value_filter=value_filter))
        total = int(total_rows[0]["total"]["value"]) if total_rows else 0
        if order == "value":
            for i, row in enumerate(rows):
                row["rank"] = (offset or 0) + i + 1
        elif rows:
            rank = 1
            if offset:
                above = self._run(self.rank_above_query(predicate, rows[0]["count"], value_class=value_class, value_filter=value_filter))
                rank = (int(above[0]["above"]["value"]) if above else 0) + 1
            previous = None
            for i, row in enumerate(rows):
                if previous is not None and row["count"] != previous:
                    rank = (offset or 0) + i + 1
                row["rank"] = rank
                previous = row["count"]
        return {"rows": rows, "total": total}

    def get_facets(self, predicate, *, exclude=None, label_predicate="rdfs:label", lang=None, limit=None,
                   search=None, search_method="contains", value_type="auto"):
        """Facet候補（値・ラベル・件数・値の種類）を件数の多い順に返す。

        exclude: 候補計算のときに外す条件の名前（通常は自分自身のファセット名）
        search:  ラベルにこの語句を含む候補だけにする
        """
        collection = self.without(exclude) if exclude else self
        query = collection.facet_query(
            predicate, label_predicate=label_predicate, lang=lang, limit=limit,
            search=search, search_method=search_method, value_type=value_type,
        )
        results = collection._run(query)
        facets = []
        for row in results:
            value = row["value"]["value"]
            label = row.get("label", {}).get("value") or value
            facets.append({
                "value": value,
                "label": label,
                "count": int(row["count"]["value"]),
                "type": row["value"].get("type", "literal"),
            })
        return facets

    def get_range(self, predicate, *, exclude=None, datatype=None, unit=None):
        """predicate の値の範囲 {"min", "max", "count"} を返す。値がなければ None。

        日付（date / dateTime）や unit="year" のときは年で返す。
        """
        collection = self.without(exclude) if exclude else self
        results = collection._run(collection.range_query(predicate, datatype=datatype, unit=unit))
        if not results or "min" not in results[0] or "max" not in results[0]:
            return None
        row = results[0]
        return {
            "min": row["min"]["value"],
            "max": row["max"]["value"],
            "count": int(row["count"]["value"]),
        }

    def get_histogram(self, predicate, low, width, *, exclude=None, datatype=None, unit=None):
        """区間番号 → 件数 の辞書を返す。"""
        collection = self.without(exclude) if exclude else self
        query = collection.histogram_query(predicate, low, width, datatype=datatype, unit=unit)
        counts = {}
        for row in collection._run(query):
            if "bin" not in row:
                continue
            try:
                index = int(float(row["bin"]["value"]))
            except ValueError:
                continue
            counts[index] = counts.get(index, 0) + int(row["count"]["value"])
        return counts

    # ---- 互換用 ----

    @property
    def uris(self):
        return None

    @property
    def query(self):
        return None

    @property
    def filters(self):
        """（互換用）値の条件を (predicate, value) の組で返す"""
        result = []
        for condition in self.conditions:
            if isinstance(condition, ValueCondition):
                for value in condition.values:
                    result.append((condition.predicate, value))
        return result


class AnyCollection(Collection):
    """すべてのリソース（主語）の集合。検索語などの条件を付けて使う（/search の検索結果。2026.10.19）。
    条件を付けると、その条件のパターンだけで ?uri を束縛する"""

    def _pattern(self):
        return "?uri ?_any_p ?_any_o ."

    def __repr__(self):
        return "AnyCollection()"


class ClassCollection(Collection):
    """クラスに属するResourceの集合"""

    def __init__(self, sparql, class_uri):
        super().__init__(sparql)
        self.class_uri = class_uri
        self._class_term = iri_term(class_uri)

    def _pattern(self):
        return f"?uri a {self._class_term} ."

    def __repr__(self):
        return f"ClassCollection({self.class_uri!r})"


class QueryCollection(Collection):
    """?uri を返すSELECTで定義される集合（page定義の query など）"""

    def __init__(self, sparql, query, params=None):
        super().__init__(sparql, params)
        if not query or not isinstance(query, str):
            raise CollectionError("Collectionのqueryがありません")
        if re.search(r"^\s*(PREFIX|BASE)\b", query, re.IGNORECASE | re.MULTILINE):
            raise CollectionError(
                "Collectionのqueryでは PREFIX を書かず、設定ファイルの prefixes で指定してください"
            )
        if not re.search(r"\?uri\b", query):
            raise CollectionError("Collectionのqueryは ?uri を返す必要があります")
        self._query = query

    @property
    def query(self):
        return self._query

    # SELECT句が ?uri だけか（その場合は利用者のSELECTをそのまま副問い合わせにできる）
    _ONLY_URI = re.compile(r"^\s*SELECT\s+(DISTINCT\s+|REDUCED\s+)?\?uri\s+WHERE\b", re.IGNORECASE)

    def _pattern(self):
        query = self._query.strip()
        if self._ONLY_URI.match(query):
            return f"{{\n{_indent(query)}\n}}"
        # 他の変数も返すSELECTは、?uri だけを外に出す副問い合わせで包む
        return f"{{ SELECT DISTINCT ?uri\n  WHERE {{\n    {{\n{_indent(query, 6)}\n    }}\n  }}\n}}"

    def __repr__(self):
        return f"QueryCollection({self._query!r})"


class UriCollection(Collection):
    """URIの列挙で定義される集合"""

    def __init__(self, sparql, uris):
        super().__init__(sparql)
        self._uris = list(uris)
        self._terms = [iri_term(uri) for uri in self._uris]

    @property
    def uris(self):
        return list(self._uris)

    def _pattern(self):
        if not self._terms:
            return "VALUES ?uri { }"
        return f"VALUES ?uri {{ {' '.join(self._terms)} }}"

    def get_uris(self, variable="uri", limit=None, offset=None):
        # 列挙されたURIをそのまま返す（SPARQLは実行しない）
        uris = self.uris
        start = int(offset or 0)
        end = start + int(limit) if limit is not None else None
        return uris[start:end]

    def count(self):
        return len(set(self._uris))

    def __repr__(self):
        return f"UriCollection({self._uris!r})"


class FilteredCollection(Collection):
    """元のCollectionに絞り込み条件を追加した集合（条件はすべて AND）"""

    def __init__(self, source, conditions):
        # 絞り込み済みのCollectionに更に条件を付ける場合は1段にまとめる
        if isinstance(source, FilteredCollection):
            conditions = tuple(source._conditions) + tuple(conditions)
            source = source._source
        super().__init__(source.sparql)
        self._source = source
        self._conditions = tuple(conditions)

    @property
    def conditions(self):
        return self._conditions

    @property
    def base(self):
        return self._source

    @property
    def uris(self):
        return self._source.uris

    @property
    def query(self):
        return self._source.query

    def all_params(self):
        return self._source.all_params()

    def without(self, names):
        names = {names} if isinstance(names, str) else set(names or ())
        kept = tuple(c for c in self._conditions if c.name not in names)
        if len(kept) == len(self._conditions):
            return self
        if not kept:
            return self._source
        return FilteredCollection(self._source, kept)

    def _pattern(self):
        # すべてのリソースの集合に条件を付けたものは、条件のパターンだけにする（全件を走査しない）
        lines = [] if isinstance(self._source, AnyCollection) and self._conditions else [self._source._pattern()]
        for index, condition in enumerate(self._conditions):
            lines.append(condition.pattern("?uri", index))
        return "\n".join(lines)

    def __repr__(self):
        return f"FilteredCollection({self._source!r}, {list(self._conditions)!r})"


class _BinaryCollection(Collection):
    """2つのCollectionの集合演算"""

    symbol = "?"

    def __init__(self, left, right):
        if not isinstance(left, Collection) or not isinstance(right, Collection):
            raise CollectionError("集合演算の対象はCollectionでなければなりません")
        super().__init__(left.sparql)
        self.left = left
        self.right = right

    def all_params(self):
        params = self.right.all_params()
        params.update(self.left.all_params())
        return params

    @staticmethod
    def _operand(collection):
        # 各オペランドは ?uri だけを出す副問い合わせにして、内部の変数を隔離する
        return collection.to_subquery("?uri")

    def __repr__(self):
        return f"{type(self).__name__}({self.left!r}, {self.right!r})"


class UnionCollection(_BinaryCollection):
    symbol = "|"

    def _pattern(self):
        return f"{{\n{_indent(self._operand(self.left))}\n}}\nUNION\n{{\n{_indent(self._operand(self.right))}\n}}"


class IntersectCollection(_BinaryCollection):
    symbol = "&"

    def _pattern(self):
        return f"{self._operand(self.left)}\n{self._operand(self.right)}"


class MinusCollection(_BinaryCollection):
    symbol = "-"

    def _pattern(self):
        return f"{self._operand(self.left)}\nMINUS {{\n{_indent(self._operand(self.right))}\n}}"


def parse_typed(value, datatype):
    """（ファセット入力の検証用）値をdatatypeとして解釈できれば正規形を返す。"""
    return normalize_typed_value(value, datatype)
