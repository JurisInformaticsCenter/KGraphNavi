#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      terms.py
##  Description:
##      外部から与えられた値を検証し、SPARQLの項（IRI・リテラル・プロパティパス）に変換する
##
##  URLパラメータなど信頼できない値をSPARQLに埋め込むときは、必ずこのモジュールの
##  関数を通す。検証できない値は ValueTermError を送出する。
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .errors import KGraphError

XSD = "http://www.w3.org/2001/XMLSchema#"


class ValueTermError(KGraphError):
    """SPARQLの項として使えない値"""


# IRIに使えない文字（RFC 3987 / SPARQL の IRIREF の定義による）
_IRI_FORBIDDEN = re.compile(r'[\s<>"{}|^`\\\x00-\x20]')
# スキームを持つ絶対IRI（http://..., urn:..., など）
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# 接頭辞付きの名前（dbo:Mountain, caselawp:訴訟類型 など）
_PREFIXED_NAME = re.compile(r"^(?:[A-Za-z][\w.-]*)?:(?:[\w%-][\w.%-]*)?$")
# 接頭辞付きの名前として解釈するスキーム（http: などはIRIとして扱う）
_IRI_SCHEMES = {"http", "https", "urn", "ftp", "file", "mailto", "tag", "doi"}


def iri_term(value):
    """値をSPARQLのIRI（<...>）または接頭辞付きの名前として返す。

    受け付ける形式:
        <http://example.org/A>   そのまま
        http://example.org/A     <...> で囲む
        dbo:Mountain             接頭辞付きの名前としてそのまま
    """
    if value is None:
        raise ValueTermError("IRIが指定されていません")
    text = str(value).strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
        return _checked_iri(text)
    scheme = text.split(":", 1)[0].lower() if ":" in text else ""
    if "://" in text or scheme in _IRI_SCHEMES:
        return _checked_iri(text)
    if _PREFIXED_NAME.match(text):
        return text
    raise ValueTermError(f"IRIとして解釈できない値です: {value!r}")


def _checked_iri(text):
    if not text or not _ABSOLUTE_IRI.match(text) or _IRI_FORBIDDEN.search(text):
        raise ValueTermError(f"IRIとして使えない文字を含んでいます: {text!r}")
    return f"<{text}>"


def is_iri(value):
    """iri_term() で変換できる値ならTrue"""
    try:
        iri_term(value)
    except ValueTermError:
        return False
    return True


_LITERAL_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def literal_term(value, lang=None):
    """値を文字列リテラル（"..."、必要なら @lang 付き）として返す。"""
    if value is None:
        raise ValueTermError("リテラルが指定されていません")
    text = "".join(_LITERAL_ESCAPES.get(ch, ch) for ch in str(value))
    if lang:
        return f'"{text}"@{language_tag(lang)}'
    return f'"{text}"'


def language_tag(lang):
    """言語タグ（en, ja, en-US, *）を検証して返す。"""
    text = str(lang).strip()
    if text != "*" and not re.match(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$", text):
        raise ValueTermError(f"言語タグとして使えない値です: {lang!r}")
    return text


# 型付きリテラルの変換。値を解釈して正規形の文字列を返す
def _parse_integer(value):
    text = str(value).strip()
    if not re.match(r"^[+-]?\d+$", text):
        raise ValueError
    return str(int(text))


def _parse_decimal(value):
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as e:
        raise ValueError from e
    if not number.is_finite():
        raise ValueError
    return format(number, "f")


def _parse_date(value):
    return date.fromisoformat(str(value).strip()).isoformat()


def _parse_datetime(value):
    return datetime.fromisoformat(str(value).strip()).isoformat()


def _parse_gyear(value):
    text = str(value).strip()
    if not re.match(r"^-?\d{4,}$", text):
        raise ValueError
    return text


def _parse_boolean(value):
    text = str(value).strip().lower()
    if text in ("true", "1"):
        return "true"
    if text in ("false", "0"):
        return "false"
    raise ValueError


DATATYPES = {
    "integer": _parse_integer,
    "decimal": _parse_decimal,
    "double": _parse_decimal,
    "date": _parse_date,
    "dateTime": _parse_datetime,
    "gYear": _parse_gyear,
    "boolean": _parse_boolean,
}


def normalize_typed_value(value, datatype):
    """値をdatatypeとして解釈し、正規形の文字列を返す。解釈できなければ ValueTermError。"""
    parser = DATATYPES.get(datatype)
    if parser is None:
        raise ValueTermError(f"未対応のデータ型です: {datatype!r}（{', '.join(DATATYPES)}）")
    try:
        return parser(value)
    except (ValueError, TypeError) as e:
        raise ValueTermError(f"{datatype} として解釈できない値です: {value!r}") from e


def typed_term(value, datatype):
    """値を型付きリテラル（"2000-01-01"^^<xsd:date> など）として返す。"""
    normalized = normalize_typed_value(value, datatype)
    return f'"{normalized}"^^<{XSD}{datatype}>'


def number_term(value):
    """数値をSPARQLの数値リテラル（引用符なし）として返す。YEAR() との比較などに使う。"""
    return _parse_decimal_or_integer(value)


def _parse_decimal_or_integer(value):
    text = str(value).strip()
    try:
        return _parse_integer(text)
    except ValueError:
        pass
    try:
        return _parse_decimal(text)
    except ValueError as e:
        raise ValueTermError(f"数値として解釈できない値です: {value!r}") from e


# プロパティパスの字句: IRI、接頭辞付きの名前、a、演算子
_PATH_TOKEN = re.compile(
    r"\s*(?:(<[^<>\s]*>)|([|/^*+?()!])|(a)(?![\w:])|([^\s|/^*+?()!<>]+))"
)


def predicate_term(path):
    """プロパティ（またはプロパティパス）を検証して返す。

    dbo:country、<http://...>、http://...、^dbo:country、dct:subject/skos:broader* など。
    """
    if path is None or str(path).strip() == "":
        raise ValueTermError("プロパティが指定されていません")
    text = str(path).strip()
    # 単独のIRIや接頭辞付きの名前はここで処理（http:// を含む場合もある）
    try:
        return iri_term(text)
    except ValueTermError:
        pass
    parts = []
    pos = 0
    while pos < len(text):
        match = _PATH_TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            raise ValueTermError(f"プロパティパスとして解釈できない値です: {path!r}")
        iri, op, a_keyword, name = match.groups()
        if iri is not None:
            parts.append(iri_term(iri))
        elif op is not None:
            parts.append(op)
        elif a_keyword is not None:
            parts.append("a")
        else:
            parts.append(iri_term(name))
        pos = match.end()
    return "".join(parts)


def variable_name(name):
    """SPARQLの変数名として使える文字列にする（?は付けない）。"""
    cleaned = re.sub(r"\W", "_", str(name))
    if not cleaned or cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    return cleaned
