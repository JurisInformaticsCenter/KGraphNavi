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
)

logger = logging.getLogger(__name__)

VALUE_TYPES = ("iri", "literal", "auto")
RANGE_UNITS = (None, "year")


def _indent(text, spaces=4):
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


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

    def _bound(self, value):
        if value in (None, ""):
            return None
        if self.unit == "year":
            return number_term(value)
        return typed_term(value, self.datatype)

    def _bounds(self):
        return self._bound(self.minimum), self._bound(self.maximum)

    def pattern(self, var, index):
        predicate = predicate_term(self.predicate)
        value_var = f"?_c{index}"
        subject = f"YEAR({value_var})" if self.unit == "year" else value_var
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

    def to_subquery(self, var="?entity"):
        """ガジェットのSPARQLに埋め込む副問い合わせを返す。var だけを外に出す。"""
        if var == "?uri":
            return f"{{ SELECT DISTINCT ?uri\n  WHERE {{\n{_indent(self._pattern())}\n  }}\n}}"
        return self._scoped(var, self._pattern())

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

    def facet_query(self, predicate, *, label_predicate="rdfs:label", lang=None, limit=None):
        """predicate の値ごとの件数を求めるSELECTを返す。"""
        predicate = predicate_term(predicate)
        label_predicate = predicate_term(label_predicate)
        lang_filter = ""
        if lang:
            lang_filter = f"\n        FILTER(LANGMATCHES(LANG(?_label), {literal_term(language_tag(lang))}))"
        query = (
            "SELECT ?value (SAMPLE(?_label) AS ?label) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{_indent(self.to_subquery('?uri'))}\n"
            f"    ?uri {predicate} ?value .\n"
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

    def range_query(self, predicate, *, unit=None):
        """predicate の値の最小値・最大値・件数を求めるSELECTを返す。"""
        predicate = predicate_term(predicate)
        value = "YEAR(?_v)" if unit == "year" else "?_v"
        return (
            f"SELECT (MIN({value}) AS ?min) (MAX({value}) AS ?max) (COUNT(DISTINCT ?uri) AS ?count)\n"
            "WHERE {\n"
            f"{_indent(self.to_subquery('?uri'))}\n"
            f"    ?uri {predicate} ?_v .\n"
            "}"
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
        """Collectionに含まれるResourceの数を返す。"""
        results = self._run(self.count_query())
        if not results:
            return 0
        return int(results[0]["count"]["value"])

    def get_facets(self, predicate, *, exclude=None, label_predicate="rdfs:label", lang=None, limit=None):
        """Facet候補（値・ラベル・件数・値の種類）を件数の多い順に返す。

        exclude: 候補計算のときに外す条件の名前（通常は自分自身のファセット名）
        """
        collection = self.without(exclude) if exclude else self
        query = collection.facet_query(
            predicate, label_predicate=label_predicate, lang=lang, limit=limit
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

    def get_range(self, predicate, *, exclude=None, unit=None):
        """predicate の値の範囲 {"min", "max", "count"} を返す。値がなければ None。"""
        collection = self.without(exclude) if exclude else self
        results = collection._run(collection.range_query(predicate, unit=unit))
        if not results or "min" not in results[0]:
            return None
        row = results[0]
        return {
            "min": row["min"]["value"],
            "max": row["max"]["value"],
            "count": int(row["count"]["value"]),
        }

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
        lines = [self._source._pattern()]
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
