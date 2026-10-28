#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      app.py
##  Author:
##      Fumihito NISHINO       nishino@nii.ac.jp
##  Description:
##        指定されたコンフィグレーションのKGraphNaviを起動する
##        Gadget/Pageを管理し、extract → showを制御
##  使用例：
##      % kgraphnavi config/dbpedia.yaml
##      % kgraphnavi -e http://localhost:8891/sparql --data-dir /path/to/html config/caselaw.yaml
##
## '-e', '--endpoint', エンドポイント。省略時は設定ファイルの sparql_endpoint
## '-l', '--label', ラベルを表現するpredicateを指定する。デフォルトはrdfs:label
"""
import os
import re
from urllib.parse import urlencode
from html import escape as html_escape
from pathlib import Path
import argparse
import logging
import csv
import yaml
from flask import Flask, render_template
from .render_utils import show_vertical_table, show_horizontal_table, show_facet, get_localname
from .render_utils import show_chart
from .graph import build_graph, render_graph, validate_graph_show
from .sparql import SPARQL, STANDARD_PREFIXES
from .collection import AnyCollection, TextCondition
from .saved import SavedCollectionStore, DEFAULT_SAVE_MAX
from .topic import topic_settings
from .compare import compare_settings, resolve_types as resolve_compare_types, COMPARE_MAX
from .collection import Collection, bif_text_expression
from .errors import ConfigError, GadgetError, ShowError, KGraphError, SparqlError
from .terms import predicate_term, literal_term, language_tag, is_iri, iri_term
from .facets import (
    facet_selection,
    facet_option,
    match_mode,
    page_number,
    render_value_facet,
    render_range_facet,
    render_conditions,
    render_search_box,
    render_save_form,
    SEARCH_PARAM,
    SEARCH_MODE_PARAM,
    plan_bins,
    build_histogram,
    is_integer_scale,
    render_pager,
    render_rank,
    make_url,
    TAB_PARAM,
    RANK_PAGE_PARAM,
)

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
# 設定ファイル名だけが指定されたときの探索先（カレントディレクトリの config/）
CONFIG_DIR = Path.cwd() / "config"
# 設定ファイルと同じフォルダにあれば自動で読み込むローカル設定（リポジトリには含めない）
LOCAL_CONFIG_NAME = "local.yaml"
VALID_TYPES = {
    "literal",
    "link",
    "select",     # コレクションの要素を選ぶチェックボックス（選んで比べる。2026.10.26）
    "directlink",
    "image",
}

def create_app(application) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(TEMPLATES_DIR),
        static_url_path="/templates",
    )
    # app.config や app.extensions に載せる
    app.config["TEMPLATES_DIR"] = TEMPLATES_DIR
    app.extensions["application"] = application
    app.extensions["sparql_client"] = application.sparql_client
    # views を初期化
    from . import views
    views.init_app(app)
    return app

def load_yaml(path):
    with open(path) as yamlf:
        return yaml.safe_load(yamlf)

def move_focus(uri, path, sparql_client):
    """現在のuriからpathによって、新しいuriを求める。見つからなければNone"""
    query = f"select ?new where {{ $uri {predicate_term(path)} ?new }}"
    results = [record['new']['value'] for record in sparql_client.query(query, {"uri": uri})]
    return results[0] if results else None

def sparql_result(val):
    return [{"val": {'value': val, 'type': 'text'}}, ]

def vtype(val):
    if re.match(r'https?://.*', val): # 直接リンク
        return 'directlink'
    if re.match(r'<https?://.*>', val): # リソースページ
        return 'uri'
    return 'text'

def make_sparql_result_from_list(contents, header):
    def make_sparql_result_record(record, header):
        rdict = {}
        for i, name in enumerate(header):
            rdict[name] = {'type': vtype(record[i]), 'value': record[i]}
        return rdict

    return [make_sparql_result_record(record, header) for record in contents]

def prepare_columns(content, columns):
    """
    columns を正規化する。
    Parameters:
        content : list[dict]
            SPARQL の結果(bindings)
        columns : list[dict] | None
            YAML の columns 指定
    Returns:
        list[dict]
            正規化済み columns
    """
    # データがない場合
    if not content:
        return []
    # columns省略時は自動生成
    if columns is None:
        columns = [
            {"id": key}
            for key in content[0].keys()
        ]
    result = []
    for col in columns:
        # "label" のような省略記法も許す
        if isinstance(col, str):
            col = {"id": col}
        col = dict(col)      # 元データを壊さない
        ctype = col.setdefault("type", "literal")
        if ctype not in VALID_TYPES:
            raise ConfigError(f"Unknown column type '{ctype}'")
        if "id" not in col:
            raise ConfigError(f"column definition has no 'id': {col}")
        # 見出し
        col.setdefault("label", col["id"])
        # 型
        col.setdefault("type", "literal")
        # width のデフォルト
        if col["type"] == "image":
            col.setdefault("width", 120)
        result.append(col)
    # 同じ id の列は表のセルが上書きされる(前の列に後の列の値が出る)ので誤りにする(2026.10.19)
    ids = [col["id"] for col in result]
    if duplicated := sorted({i for i in ids if ids.count(i) > 1}):
        raise ConfigError(f"columns に同じ id の列があります: {', '.join(duplicated)}（別の変数にしてください）")
    return result

# static_dirs の名前に使えないもの（KGraphNavi のURL）
RESERVED_STATIC_NAMES = {"templates", "data", "resource", "collection", "search", "graph"}

# 1つのガジェットで取得する行数の既定の上限（設定 max_rows で変更可）
DEFAULT_MAX_ROWS = 5000

_HAS_LIMIT = re.compile(r"\b(LIMIT|OFFSET)\s+\d+\s*(\b(LIMIT|OFFSET)\s+\d+\s*)?$", re.IGNORECASE)
_TRAILING_VALUES = re.compile(r"\bVALUES\b[^{}]*\{[^{}]*\}\s*$", re.IGNORECASE)


def limit_rows(query, max_rows):
    """クエリの末尾に LIMIT がなければ、max_rows+1 行までに制限する。

    +1 行取得するのは、上限を超えたかどうかを判定するため。
    末尾に LIMIT/OFFSET や VALUES がある場合は変更しない。
    """
    if not max_rows:
        return query
    stripped = query.rstrip()
    if _HAS_LIMIT.search(stripped) or _TRAILING_VALUES.search(stripped):
        return query
    return f"{stripped}\nLIMIT {int(max_rows) + 1}"


class Rows(list):
    """SPARQLの結果。truncated が True なら上限で打ち切った"""
    truncated = False
    server_paged = False   # KGraphNavi 側でページ送りした（コレクションのページで page_size があるとき）


# ガジェットの variants を選ぶ URL パラメータ（v.<ガジェット名>=<variant の name>）
VARIANT_PREFIX = "v."
VARIANT_KEYS = {"name", "label", "get", "show"}


def parse_variants(name, config):
    """gadget の variants を検証して返す（[{name, label, get, show}]）"""
    variants = config.get("variants")
    if variants is None:
        return []
    if not isinstance(variants, list) or not variants:
        raise ConfigError(f"gadget({name})のvariantsは [{{name:, label:, get:, show:}}] のリストです")
    seen = set()
    for variant in variants:
        if not isinstance(variant, dict) or not re.fullmatch(r"[\w-]+", str(variant.get("name", ""))):
            raise ConfigError(f"gadget({name})のvariantsの各項目には name（英数字）が必要です: {variant!r}")
        unknown = set(variant) - VARIANT_KEYS
        if unknown:
            raise ConfigError(f"gadget({name})のvariants({variant['name']})に未知のキー: {sorted(unknown)}")
        if variant["name"] in seen:
            raise ConfigError(f"gadget({name})のvariantsの name が重なっています: {variant['name']}")
        seen.add(variant["name"])
        for part in ("get", "show"):
            if part in variant and not isinstance(variant[part], dict):
                raise ConfigError(f"gadget({name})のvariants({variant['name']})の{part}は辞書です")
    return variants


class GadgetNotFound(Exception):
    pass

class Gadget:
    """Gadget"""
    __slots__ = ("extract_method", "show_method", "height", "sparql_client", "title", "collection_config", "compare_config",
                 "variants")
    EXTRACTORS = {
        "sparql": "extract_sparql",
        "facet": "extract_facet",
        "list": "extract_list",
        "python": "extract_python",
        "csv": "extract_csv",
        "dbpedia": "extract_dbpedia",
        "rank": "extract_rank",         # 順位表（コレクションの要素を値ごとに数える。2026.10.20）
    }
    SHOWERS = {
        "chart": show_chart,
    }

    def __repr__(self):
        return f'Config(extract={self.extract_method!r}, show={self.show_method!r})'

    def __init__(self, config_get, config_show, height, title=None, collection=None, compare=None, variants=None):
        """Gadgetの生成。get内容の辞書と、show内容の辞書、gadgetの高さ、見出しを受け取る

        collection: 一覧の列（var）の値をコレクションとして表示するボタンの設定
                    {"var": 変数名, "class": 要素のクラス, "label": ボタンの文字}
        """
        self.extract_method = config_get
        self.show_method = config_show
        self.height = height
        self.sparql_client = None # あとで設定
        # 見出し。省略時はファセットなら label、それ以外はガジェット名
        self.title = title
        self.collection_config = collection
        # 一覧（var の列のリソース）と表示中のリソースを並べて比べるボタン（/compare?from=。2026.10.26）
        self.compare_config = compare
        # 画面で切り替える問い合わせ・表示（[{name, label, get, show}]。URL v.<ガジェット名>=<name>。2026.10.28）
        self.variants = variants or []

    def with_variant(self, gadget_name, params):
        """variants があれば、URL（v.<ガジェット名>）で選んだもの（既定は最初）の get / show を重ねたガジェットと、
        切り替えのリンクの HTML を返す。なければ (self, "")"""
        if not self.variants:
            return self, ""
        key = VARIANT_PREFIX + gadget_name
        chosen = (params or {}).get(key)
        current = next((v for v in self.variants if v["name"] == chosen), self.variants[0])
        gadget = Gadget({**self.extract_method, **(current.get("get") or {})},
                        {**self.show_method, **(current.get("show") or {})},
                        self.height, self.title, self.collection_config, self.compare_config)
        gadget.sparql_client = self.sparql_client
        links = []
        for variant in self.variants:
            label = html_escape(str(variant.get("label") or variant["name"]))
            if variant is current:
                links.append(f'<span class="kg-variant current">{label}</span>')
            else:
                # 切り替えると数の条件（graph.min・graph.w）の意味が変わるので外す
                url = make_url(params or {}, drop={key, "graph.min", "graph.w"}, add=[(key, variant["name"])])
                links.append(f'<a class="kg-variant" href="{html_escape(url)}">{label}</a>')
        return gadget, f'<div class="kg-variants">{"".join(links)}</div>'

    @property
    def is_facet(self):
        return (self.extract_method or {}).get("type") == "facet"

    def _expand_snippet(self, query, application):
        """SPARQL中の$snippetを展開する。"""
        if "$snippet" not in query:
            return query
        if application is None:
            return query.replace("$snippet", "")
        snippet = application.pages.snippet or ""
        return query.replace("$snippet", snippet)

    def _apply_values(self, result, uri):
        """SPARQL結果にvalues定義による追加値を設定する。"""
        values = self.extract_method.get("values")
        if not values or not result:
            return result
    
        for var, exp in values.items():
            match = re.match(r"(.*)\((.*)\)", exp)
            if not match:
                continue
    
            func, predicate = match.groups()
    
            match func:
                case "count":
                    value = self.sparql_client.get_count(uri, predicate)
                    result[0][var] = {
                        "type": "literal",
                        "value": value,
                    }
    
                case "list":
                    value = self.sparql_client.get_list(uri, predicate)
                    result[0][var] = {
                        "type": "list",
                        "value": value,
                    }
    
                case _:
                    error("設定されていない関数", func)
    
        return result


    # ガジェットのSPARQLでCollectionを受け取るプレースホルダ（?entity に束縛される）
    COLLECTION_PLACEHOLDER = "$collection"
    _WHERE_OPEN = re.compile(r"\bWHERE\s*\{", re.IGNORECASE)

    def _connect_collection(self, query, collection, limit=None, offset=None):
        """GadgetのSPARQLにCollectionの対象を接続する。

        SPARQL中の $collection を、?entity を束縛する副問い合わせに置き換える。
        $collection がなければ、最初の WHERE { の直後に挿入する。
        limit / offset はページ送り用（コレクションの要素をその範囲に限る）。
        """
        if collection is None:
            if self.COLLECTION_PLACEHOLDER in query:
                raise GadgetError(
                    "$collection を使うガジェットはコレクションのページで使ってください"
                )
            return query
        subquery = collection.to_subquery("?entity", limit=limit, offset=offset)
        if self.COLLECTION_PLACEHOLDER in query:
            return query.replace(self.COLLECTION_PLACEHOLDER, subquery)
        match = self._WHERE_OPEN.search(query)
        if match is None:
            raise GadgetError(
                "Collectionを使用するSPARQLにはWHERE句が必要です"
            )
        return query[:match.end()] + "\n" + subquery + "\n" + query[match.end():]


    @property
    def page_size(self):
        """ページ送りの1ページあたりの件数（get.page_size）。指定がなければ None"""
        if self.extract_method.get("type") == "rank":
            return None   # 順位表は自分でページを送る（rpage）。要素の一覧のページ送りは付けない
        size = self.extract_method.get("page_size")
        return int(size) if size else None

    def extract_sparql(self, uri, application, params=None, collection=None):
        """SPARQLを実行してデータを取得する。"""
        params = dict(params or {})
        if uri:
            params["uri"] = uri
        logger.debug(
            "extract_sparql: uri=%r params=%r collection=%r",
            uri,
            params,
            collection,
        )
        query = self.extract_method.get("src", "")
        query = self._expand_snippet(query, application)
        limit = offset = None
        if collection is not None and self.page_size:
            limit = self.page_size
            offset = (page_number(params) - 1) * self.page_size
        query = self._connect_collection(query, collection, limit=limit, offset=offset)
        max_rows = getattr(application, "max_rows", DEFAULT_MAX_ROWS) if application else DEFAULT_MAX_ROWS
        if self.extract_method.get("max_rows"):
            # ガジェットごとの上限（ネットワーク図の辺など、多くの行を取るもの。2026.10.28）
            max_rows = int(self.extract_method["max_rows"])
        query = limit_rows(query, max_rows)
        logger.info(
            "extract_sparql: final query=\n%s",
            query,
        )
        result = Rows(self.sparql_client.query(query, params=params) or [])
        if max_rows and len(result) > max_rows:
            del result[max_rows:]
            result.truncated = True
        result.server_paged = limit is not None
        out = self._apply_values(result, uri)
        if isinstance(out, Rows):
            out.server_paged = result.server_paged
        return out

    def extract_list(self, uri, application, params=None, collection=None):
        lines = [line for line in self.extract_method['src'].split('\n') if line]
        contents = [[val.strip() for val in line.split(',')] for line in lines]
        header = [name.strip() for name in self.extract_method['header'].split(',')]
        return make_sparql_result_from_list(contents, header)

    def extract_python(self, uri, application, params=None, collection=None):
        extract_function = self.extract_method['src']
        raise GadgetError(f"Undefined gadget extraction python function: {extract_function}")

    def extract_csv(self, uri, application, params=None, collection=None):
        extract_function = self.extract_method['src']
        raise GadgetError(f"Undefined gadget extraction python function: {extract_function}")

    def extract_dbpedia(self, uri, application, params=None, collection=None):
        objects = self.sparql_client.rdfobject(uri, self.extract_method['object'])
        if objects:
            result = sparql_result(f'<a href="https://dbpedia.org/page/{objects}">DBpedia</a>')
            return result
        return []

    def extract(self, uri, application=None, params=None, collection=None):
        """Gadgetの定義に従ってデータを取得する。"""
        logger.debug("extract: params=%r collection=%r", params, collection)
        extract_type = self.extract_method["type"]
        method_name = self.EXTRACTORS.get(extract_type)
        if method_name is None:
            raise GadgetError(f"Unknown extract type '{extract_type}'")
        return getattr(self, method_name)(uri, application, params=params or {}, collection=collection)

    def apply_collection_filters(
        self,
        collection,
        application,
        params=None,
        *,
        exclude=None,
    ):
        """（互換用）Application.apply_collection_filters() を呼ぶ。"""
        return application.apply_collection_filters(collection, params=params, exclude=exclude)

    def extract_rank(self, uri, application, params=None, collection=None):
        """順位表: コレクションの要素を、ファセットの値ごとに数えて多い順に並べる（2026.10.20）。

        get:
          facet: まとめる値のファセット名（そのファセットの predicate・label_predicate を使う。件数のリンクの絞り込みにも使う）
          predicate: ファセットを使わずにまとめる値のパスを書くとき（件数のリンクは出ない）
          value_class: まとめる値をこのクラスのものに限る（例 lawo:Clause）
          value_filter: まとめる値 ?value の条件（SPARQL の FILTER の式。例: 条だけにする）
          order: count（件数の多い順。既定）/ value（値の順）
          page_size: 1ページの行数（既定 50）。ページ送りは rpage=
          detail: 値の属性を取る SPARQL。$values が VALUES ?value { そのページの値 } になる
          list_tab: 件数のリンク先のタブの番号（要素の一覧のタブ）
          measure: count（件数。既定）/ ratio（件数 ÷ 分母の大きい順。2026.10.21）
          denominator: measure: ratio のときの分母。?value と ?denominator を返す SELECT（コレクションの条件は掛からない）
          min_denominator: 分母がこれより小さい値は除く（少ない分母で比が大きく出るのを避ける）
        """
        if application is None or collection is None:
            raise GadgetError("get.type=rank はコレクションのページで使ってください")
        params = params or {}
        facet_name = self.extract_method.get("facet")
        definition = application.get_facet_definition(facet_name) if facet_name else None
        if facet_name and definition is None:
            raise GadgetError(f"rank の facet が見つかりません: {facet_name}")
        definition = definition or {}
        predicate = self.extract_method.get("predicate") or definition.get("predicate")
        if not predicate:
            raise GadgetError("rank には facet か predicate が必要です")
        page_size = int(self.extract_method.get("page_size") or 50)
        try:
            page = max(1, int(params.get(RANK_PAGE_PARAM, 1)))
        except (TypeError, ValueError):
            page = 1
        measure = self.extract_method.get("measure", "count")
        label_predicate = self.extract_method.get("label_predicate") or definition.get("label_predicate", "rdfs:label")
        if measure == "ratio":
            denominator = self.extract_method.get("denominator")
            if not denominator:
                raise GadgetError("measure: ratio には denominator（?value と ?denominator を返す SELECT）が必要です")
            result = collection.get_ratio_rank(
                predicate,
                self._expand_snippet(denominator, application),
                value_class=self.extract_method.get("value_class"),
                value_filter=self.extract_method.get("value_filter"),
                label_predicate=label_predicate,
                lang=self.extract_method.get("lang") or definition.get("lang"),
                min_denominator=self.extract_method.get("min_denominator"),
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        else:
            result = collection.get_rank(
                predicate,
                value_class=self.extract_method.get("value_class"),
                value_filter=self.extract_method.get("value_filter"),
                label_predicate=label_predicate,
                lang=self.extract_method.get("lang") or definition.get("lang"),
                order=self.extract_method.get("order", "count"),
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        rows = result["rows"]
        src = self.extract_method.get("detail")
        if src and rows:
            values = " ".join(iri_term(r["value"]) if r.get("type") == "uri" else literal_term(r["value"]) for r in rows)
            query = self._expand_snippet(src, application).replace("$values", f"VALUES ?value {{ {values} }}")
            details = {}
            for b in self.sparql_client.query(query) or []:
                if "value" not in b:
                    continue
                d = details.setdefault(b["value"]["value"], {})
                for k, v in b.items():
                    if k == "value":
                        continue
                    text = v.get("value")
                    if k in d and text not in str(d[k]).split("、"):
                        d[k] = f"{d[k]}、{text}"
                    else:
                        d.setdefault(k, text)
            for r in rows:
                r["detail"] = details.get(str(r["value"]), {})
        return {
            "kind": "rank",
            "facet": facet_name if definition else None,
            "facet_label": definition.get("label"),
            "rows": rows,
            "total": result["total"],
            "page": page,
            "page_size": page_size,
            "params": params,
            "list_tab": self.extract_method.get("list_tab"),
            "measure": measure,
        }

    def extract_facet(self, uri, application, params=None, collection=None):
        """CollectionからFacet候補を取得する。

        返り値は描画用の辞書（候補・選択中の値・パラメータ）。
        """
        if application is None:
            raise GadgetError("facet extractにはapplicationが必要です")
        facet_name = self.extract_method.get("name")
        predicate = self.extract_method.get("predicate")
        if not facet_name:
            raise GadgetError("facet extractにはnameが必要です")
        if not predicate:
            raise GadgetError("facet extractにはpredicateが必要です")
        if collection is None:
            raise GadgetError("facet extractにはCollectionが必要です")
        params = params or {}
        # 現在表示しているFacet自身の条件だけ除外して、
        # 他のFacet条件は維持する。
        collection = application.apply_collection_filters(
            collection.without({facet_name}),
            params=params,
            exclude={facet_name},
        )
        if self.extract_method.get("kind") == "range":
            return self._extract_range_facet(facet_name, predicate, collection, params)
        search = facet_option(params, facet_name, "search") if self.extract_method.get("search") else None
        # 要素が多いコレクションでは、上位の候補の集計は重いので行わず、検索で探してもらう
        top_limit = self.extract_method.get("top_when_under")
        too_many = False
        if top_limit and not search and collection.count() > int(top_limit):
            candidates = []
            too_many = True
        else:
            label_predicate = self.extract_method.get("label_predicate", "rdfs:label")
            options = dict(
                label_predicate=label_predicate,
                lang=self.extract_method.get("lang"),
                limit=self.extract_method.get("limit"),
                value_type=self.extract_method.get("value_type", "auto"),
            )
            method = "contains"
            if search and hasattr(application, "text_search_method"):
                method = application.text_search_method(label_predicate)
            candidates = collection.get_facets(predicate, search=search, search_method=method, **options)
            # 全文索引は語単位の一致なので、見つからなければ部分一致（CONTAINS）でも探す
            if (search and method == "bif" and not candidates
                    and getattr(application, "text_search", "auto") == "auto"):
                candidates = collection.get_facets(predicate, search=search, search_method="contains", **options)
        values, _ranges = facet_selection(params)
        selected = list(values.get(facet_name, []))
        legacy = params.get(facet_name)
        if isinstance(legacy, str) and legacy and legacy not in selected:
            selected.append(legacy)
        return {
            "name": facet_name,
            "label": self.extract_method.get("label") or facet_name,
            "candidates": candidates,
            "selected": selected,
            "params": params,
            "match": match_mode(self.extract_method, params, facet_name),
            "selectable_match": self.extract_method.get("match") == "selectable",
            "searchable": bool(self.extract_method.get("search")),
            "search": search or "",
            "too_many": too_many,
            "top_limit": top_limit,
        }

    def _extract_range_facet(self, facet_name, predicate, collection, params):
        """範囲のファセット: 値の範囲と、区間ごとの件数（分布）を取得する。"""
        datatype = self.extract_method.get("datatype")
        if not datatype:
            raise GadgetError(f"facet({facet_name})にdatatypeがありません")
        unit = self.extract_method.get("unit")
        _values, ranges = facet_selection(params)
        selected = ranges.get(facet_name, {})
        value_range = collection.get_range(predicate, datatype=datatype, unit=unit)
        histogram = []
        if value_range is not None:
            low, width, count = plan_bins(
                value_range["min"],
                value_range["max"],
                self.extract_method.get("bins", 20),
                integer=is_integer_scale(datatype, unit),
            )
            counts = collection.get_histogram(predicate, low, width, datatype=datatype, unit=unit)
            histogram = build_histogram(
                counts, low, width, count, datatype=datatype, unit=unit, selected=selected
            )
        return {
            "kind": "range",
            "name": facet_name,
            "label": self.extract_method.get("label") or facet_name,
            "datatype": datatype,
            "unit": unit,
            "range": value_range,
            "histogram": histogram,
            "selected": selected,
            "params": params,
        }

    def show(self, content):
        """取得したデータを表示する。"""
        show_type = self.show_method["type"]
        kwargs = {"height": self.height,}
        if show_type in ("vtable", "htable"):
            columns = prepare_columns(content, self.show_method.get("columns"))
            shower = {
                "vtable": show_vertical_table,
                "htable": show_horizontal_table,
            }[show_type]
            
            if show_type == "vtable":
                kwargs["attribute_width"] = self.show_method.get("attribute_width")
                kwargs["value_width"] = self.show_method.get("value_width")
            else:
                kwargs["group_by"] = self.show_method.get("group_by")
                # 親子の階層で表示する（2026.10.18）
                kwargs["tree"] = self.show_method.get("tree")
                # KGraphNavi 側でページ送りするガジェットでは、表のページ送りは使わない
                # （コレクションでないページでは page_size があっても全行を取るので、表の中でページ送りし、件数も出す）
                kwargs["paging"] = not getattr(content, "server_paged", False)
            return shower(content, columns, **kwargs,)
        if show_type == "rank":
            chart_html = ""
            chart = self.show_method.get("chart")
            if chart and isinstance(content, dict) and content.get("page", 1) == 1 and content.get("rows"):
                top = content["rows"][: int(self.show_method.get("chart_top", 20))]
                ratio = content.get("measure") == "ratio"
                pairs = [
                    {"label": {"value": r["label"] if r["label"] != r["value"] else get_localname(str(r["value"]))},
                     "count": {"value": round(r["ratio"] * 100, 2) if ratio else r["count"]}}
                    for r in top
                ]
                chart_html = show_chart(pairs, {"chart": chart, "labels": "label", "dataset": "count",
                                                "label": (self.show_method.get("ratio_label", "比（%）") if ratio
                                                          else self.show_method.get("label", "件数")),
                                                "height": self.show_method.get("chart_height", 320)})
            return render_rank(content, self.show_method, chart_html)
        if show_type == "graph":
            # ネットワーク図（content は make_gadget で build_graph したもの。2026.10.28）
            return render_graph(content, content.get("params"),
                                height=self.show_method.get("height") or self.height)
        if show_type == "facet":
            if isinstance(content, dict) and content.get("kind") == "range":
                return render_range_facet(content)
            if isinstance(content, dict):
                return render_value_facet(content, height=self.height)
            return show_facet(
                content,
                self.show_method,
                **kwargs,
            )
         # その他のshow type
        shower = self.SHOWERS.get(show_type)
        if shower is None:
            raise ShowError(
                f"Undefined show type '{show_type}'"
            )
        if show_type == "chart":
            return shower(content, self.show_method)
        return shower(content)

SELECT_COLUMN = {"id": "_kgselect", "type": "select", "label": "比べる", "width": 50}


def with_select_column(gadget, content):
    """コレクションの要素（?entity が IRI）の一覧の表なら、先頭にチェックボックスの列を足したガジェットと結果を返す。
    show に select: false と書いたガジェットには足さない"""
    show = gadget.show_method or {}
    columns = show.get("columns")
    if (show.get("type") != "htable" or show.get("select") is False or not isinstance(columns, list)
            or not content or not isinstance(content, list) or not isinstance(content[0], dict)
            or (content[0].get("entity") or {}).get("type") != "uri"):
        return gadget, content
    rows = Rows(dict(r, _kgselect=r.get("entity")) for r in content)
    rows.truncated = getattr(content, "truncated", False)
    rows.server_paged = getattr(content, "server_paged", False)
    g = Gadget(gadget.extract_method, {**show, "columns": [SELECT_COLUMN] + columns}, gadget.height,
               gadget.title, gadget.collection_config, gadget.compare_config)
    g.sparql_client = gadget.sparql_client
    return g, rows


class Pages:
    """Pageの処理
       type:に指定されたuri（あるいはワイルドカードの*）のページ定義に従う
    """
    __slots__ = ("pagedict", "config", "snippet")
    def __repr__(self):
        return f'Pages(pagedict={self.pagedict!r})'
    def __init__(self):
        self.pagedict = {}
        self.snippet = None

    def set_page(self, name, config):
        """page定義を検証して登録する。同名のpageが既に定義されている場合は警告を出す"""
        if not name:
            raise ConfigError(f"page定義にnameがありません: {config!r}")
        if name in self.pagedict:
            raise ConfigError(f"page({name})が二重に定義されています")
        page_type = config.get("type")
        if not page_type:
            raise ConfigError(f"page({name})にtypeがありません")
        gadget = config.get("gadget")
        tabs = config.get("tabs")
        if gadget is None and tabs is None:
            raise ConfigError(f"page({name})にはgadgetまたはtabsが必要です")
        # gadgetの検証
        if gadget is not None:
            if not isinstance(gadget, list):
                raise ConfigError(f"page({name})のgadgetはリストで指定してください")
            for gadget_name in gadget:
                if not isinstance(gadget_name, str):
                    raise ConfigError(
                        f"page({name})のgadget名は文字列で指定してください: "
                        f"{gadget_name!r}"
                    )
        # tabsの検証
        if tabs is not None:
            if not isinstance(tabs, list):
                raise ConfigError(
                    f"page({name})のtabsはリストで指定してください"
                )
            for i, tab in enumerate(tabs):
                if not isinstance(tab, dict):
                    raise ConfigError(
                        f"page({name})のtabs[{i}]は辞書で指定してください"
                    )
                if not tab.get("label"):
                    raise ConfigError(
                        f"page({name})のtabs[{i}]にlabelがありません"
                    )
                tab_gadget = tab.get("gadget")
                if not isinstance(tab_gadget, list):
                    raise ConfigError(
                        f"page({name})のtabs[{i}].gadgetは"
                        "リストで指定してください"
                    )
        classes = config.get("class")
        if classes is not None:
            if page_type != "collection":
                raise ConfigError(f"page({name})のclassは type: collection のページでだけ指定できます")
            if isinstance(classes, str):
                classes = [classes]
            if not isinstance(classes, list) or not all(isinstance(c, str) for c in classes):
                raise ConfigError(f"page({name})のclassは文字列またはリストで指定してください")
        sidebar = config.get("sidebar")
        if sidebar is not None and (
            not isinstance(sidebar, list) or not all(isinstance(g, str) for g in sidebar)
        ):
            raise ConfigError(f"page({name})のsidebarはガジェット名のリストで指定してください")
        page_collection = config.get("collection")
        if page_collection not in (None, "instances"):
            raise ConfigError(f"page({name})のcollectionには instances だけが指定できます: {page_collection!r}")
        self.pagedict[name] = {
            "type": page_type,
            "gadget": gadget,
            "tabs": tabs,
            "query": config.get("query"),
            "class": list(classes) if classes else [],
            "sidebar": list(sidebar) if sidebar else [],
            "collection": page_collection,
        }
        self.config = config

    def resolve_prefixes(self, prefixes):
        """ページの type（RDFクラス）と class に書かれた接頭辞付きの名前を完全なIRIにする。"""
        for page in self.pagedict.values():
            if page["type"] not in SPECIAL_PAGE_TYPES:
                page["type"] = expand_prefixed(page["type"], prefixes)
            page["class"] = [expand_prefixed(c, prefixes) for c in page.get("class") or []]

    def rdftype2page(self, rdftype):
        """RDF typeに対応するresource用Page名を返す。

        type が一致するページを優先し、なければ type: '*' のページを返す。
        """
        fallback = None
        for name, page in self.pagedict.items():
            if page["type"] == rdftype:
                return name
            if page["type"] == "*" and fallback is None:
                fallback = name
        return fallback

    def pages_of_type(self, page_type):
        return [name for name, page in self.pagedict.items() if page["type"] == page_type]

    def collection_page_for_class(self, class_uri):
        """class: に class_uri を含むコレクションのページ（なければNone）"""
        for name in self.pages_of_type("collection"):
            if class_uri in self.pagedict[name].get("class", []):
                return name
        return None

    def collection_classes(self):
        """コレクションのページの class: に書かれたクラス（定義順）"""
        classes = []
        for name in self.pages_of_type("collection"):
            for class_uri in self.pagedict[name].get("class", []):
                if class_uri not in classes:
                    classes.append(class_uri)
        return classes

    def default_collection_page(self):
        """class も query も持たないコレクションのページ（なければNone）"""
        for name in self.pages_of_type("collection"):
            page = self.pagedict[name]
            if not page.get("class") and not page.get("query"):
                return name
        return None


def expand_prefixed(name, prefixes):
    """接頭辞付きの名前（dbo:Mountain）を、prefixes を使って完全なIRIにする。

    既に完全なIRIのもの、接頭辞が定義されていないものはそのまま返す。
    """
    if not isinstance(name, str):
        return name
    text = name.strip()
    if text.startswith("<") and text.endswith(">"):
        return text[1:-1]
    if "://" in text or ":" not in text:
        return text
    prefix, local = text.split(":", 1)
    base = (prefixes or {}).get(prefix)
    if base is None:
        return text
    return f"{base}{local}"


# 特別なページの種類（RDFクラスではないもの）
SPECIAL_PAGE_TYPES = {"*", "collection", "graph"}

# class に対応するページがないときに使う、組み込みのコレクションのページとガジェット
BUILTIN_COLLECTION_PAGE = "_Collection"
BUILTIN_COLLECTION_GADGET = "_collection_list"
# 検索結果のページ（2026.10.19）
BUILTIN_SEARCH_PAGE = "_Search"
BUILTIN_SEARCH_GADGET = "_search_list"
BUILTIN_TYPE_FACET = "_facet_type"
TYPE_FACET = "_type"


def builtin_collection_gadget(label_predicate="rdfs:label", label_lang=None):
    """コレクションの要素をラベルとともに一覧する組み込みガジェット"""
    label_predicate = predicate_term(label_predicate)
    if label_lang:
        preferred = (
            f"    OPTIONAL {{ ?entity {label_predicate} ?_preferred . "
            f"FILTER(LANGMATCHES(LANG(?_preferred), {literal_term(language_tag(label_lang))})) }}\n"
        )
        label = "COALESCE(SAMPLE(?_preferred), SAMPLE(?_any))"
    else:
        preferred = ""
        label = "SAMPLE(?_any)"
    src = (
        f"SELECT ?entity ({label} AS ?label) (STR(?entity) AS ?entityuri)\n"
        "WHERE {\n"
        "    $collection\n"
        f"{preferred}"
        f"    OPTIONAL {{ ?entity {label_predicate} ?_any }}\n"
        "}\n"
        "GROUP BY ?entity\n"
        "ORDER BY ?entity"
    )
    return Gadget(
        config_get={"type": "sparql", "page_size": 50, "src": src},
        config_show={
            "type": "htable",
            "columns": [
                {"id": "entity", "type": "link", "string": "?label", "label": "名前", "width": 400},
                # 名前の列と同じ id にすると、セルが上書きされて名前の列に URI が出る(2026.10.19)
                {"id": "entityuri", "type": "literal", "label": "URI", "width": 500},
            ],
        },
        height=None,
        title="一覧",
    )


def builtin_search_gadget(label_predicate="rdfs:label", label_lang=None):
    """検索結果の要素を、ラベルと種類（rdf:type）とともに一覧する組み込みガジェット（2026.10.19）"""
    label_predicate = predicate_term(label_predicate)
    if label_lang:
        preferred = (
            f"    OPTIONAL {{ ?entity {label_predicate} ?_preferred . "
            f"FILTER(LANGMATCHES(LANG(?_preferred), {literal_term(language_tag(label_lang))})) }}\n"
        )
        label = "COALESCE(SAMPLE(?_preferred), SAMPLE(?_any))"
    else:
        preferred = ""
        label = "SAMPLE(?_any)"
    src = (
        f"SELECT ?entity ({label} AS ?label) (STR(?entity) AS ?entityuri) ?type\n"
        "WHERE {\n"
        "    $collection\n"
        f"{preferred}"
        f"    OPTIONAL {{ ?entity {label_predicate} ?_any }}\n"
        "    OPTIONAL { ?entity a ?type }\n"
        "}\n"
        "GROUP BY ?entity ?type\n"
        "ORDER BY ?entity"
    )
    return Gadget(
        config_get={"type": "sparql", "page_size": 50, "src": src},
        config_show={
            "type": "htable",
            "group_by": "entity",
            "columns": [
                {"id": "entity", "type": "link", "string": "?label", "label": "名前", "width": 400},
                {"id": "type", "type": "literal", "display": "localname", "label": "種類", "width": 160},
                {"id": "entityuri", "type": "literal", "label": "URI", "width": 400},
            ],
        },
        height=None,
        title="検索結果",
    )


# ファセットの候補の検索の方法（設定 text_search）
TEXT_SEARCH_MODES = ("auto", "bif", "contains")


def probe_bif_contains(sparql_client, label_predicate="rdfs:label"):
    """エンドポイントで bif:contains（Virtuoso の全文索引）が使えるかを試し、"bif" / "contains" を返す。

    実際のラベルを1つ取り出し、それを bif:contains で探して見つかれば使えると判定する。
    Virtuoso でないエンドポイントでは問い合わせがエラーになるので contains とする。
    """
    try:
        predicate = predicate_term(label_predicate)
        rows = sparql_client.exsparql(
            f"SELECT ?l WHERE {{ ?s {predicate} ?l . FILTER(isLiteral(?l)) }} LIMIT 20"
        )
        for row in rows:
            expression = bif_text_expression(row.get("l", {}).get("value", ""))
            if not expression or len(expression) < 4:
                continue
            found = sparql_client.exsparql(
                f"SELECT ?s WHERE {{ ?s {predicate} ?l . ?l bif:contains {literal_term(expression)} . }} LIMIT 1"
            )
            return "bif" if found else "contains"
    except Exception as e:
        # エンドポイントの一時的なエラー（DBpedia の 502 など）もあるので、決めずに次の問い合わせでまた試す（2026.10.27）
        logger.info("bif:contains が使えるか確かめられません（次にまた試します）: %s", e)
        return None
    return "contains"


# 設定の検証で使う、対応しているget/showの種類
SUPPORTED_GET_TYPES = set(Gadget.EXTRACTORS)
SUPPORTED_SHOW_TYPES = {"vtable", "htable", "facet", "rank", "graph"} | set(Gadget.SHOWERS)

TOPIC_FORM = '<form action="/topic" method="GET"><div class="search_wrap"><input name="q" type="search" placeholder="トピックのキーワード" /><button type="submit">トピック</button></div></form>'
RETRIEVE_FORM = '<form action="/search" method="GET"><div class="search_wrap"><input name="q" type="search" placeholder="検索キーワード" /><button type="submit">検索</button><div class="search-modes"><label><input type="radio" name="mode" value="partial" checked>部分</label><label><input type="radio" name="mode" value="perfect">完全</label></div></div></form>'

class Application:
    """Application"""
    __slots__ = ("pages", "gadgetset", "title", "describe", "query_samples", "resource_samples", "collection_samples", "priority_list", "focus", "navi", "sparql_client", "data_dir", "data_dirs", "static_dirs", "max_rows", "prefixes", "class_page_cache", "text_search", "text_search_cache", "label_predicate", "saved_store", "saved_max", "topic_config", "compare_views")
    def __repr__(self):
        return f'Application={self.pages!r}, {self.gadgetset}'

    def __init__(self, frontend_base_url, pages, gadgetset, title, describe, query_samples, resource_samples, collection_samples, priority_list, sparql_client, data_dir):
        self.pages = pages
        self.gadgetset = gadgetset
        self.title = title
        self.describe = describe
        self.query_samples = query_samples
        self.resource_samples = resource_samples
        self.collection_samples = collection_samples
        self.priority_list = priority_list
        self.focus = None
        self.navi = (f'<nav class="navbar"><ul><li class="nav_left"><a href="{frontend_base_url}">{self.title}</a></li>'
                     '<li class="nav_left"><a href="/collections">保存したコレクション</a></li>'
                     f'<li class="nav_right search_item">{RETRIEVE_FORM}</li></ul></nav>')
        self.sparql_client = sparql_client
        self.data_dir = Path(data_dir) if data_dir else None
        # /data/<名前>/<path> で配信する別のフォルダ（設定の data_dirs。例: churoi → 中労委のlhtml）
        self.data_dirs = {}
        # /<名前>/<path> で配信するフォルダ（設定の static_dirs。例: css → 判決HTMLが ../../css/hanrei.css で参照するCSS）
        self.static_dirs = {}
        self.max_rows = DEFAULT_MAX_ROWS
        self.prefixes = {}
        # RDFクラス → コレクションのページ名（上位クラスの問い合わせ結果を記憶する）
        self.class_page_cache = {}
        # 候補の検索の方法（auto / bif / contains）と、auto で判定した結果（ラベルの述語ごと）
        self.text_search = "auto"
        self.text_search_cache = {}
        # ラベルの predicate（検索語の条件に使う）
        self.label_predicate = "rdfs:label"
        # 名前を付けて保存したコレクション（設定 saved_collections_dir・saved_collection_max。2026.10.19）
        self.saved_store = None
        self.saved_max = DEFAULT_SAVE_MAX
        # キーワードからトピックを作る設定（topic:。2026.10.26）
        self.topic_config = None
        # 列に並べて比べる比べ方（compare:。2026.10.26）
        self.compare_views = None

    def resolve_gadget(self, spec):
        if m := re.match(r'(.*)\((.*)\)', spec):
            name = m.group(1)
            path = m.group(2)
        else:
            name = spec
            path = None
        # gadget定義を取得
        gadget = self.gadgetset.get(name)
        return name, path, gadget

    def text_search_method(self, label_predicate="rdfs:label"):
        """ファセットの候補の検索に使う方法 "bif" / "contains" を返す。

        設定 text_search が auto（既定）のときは、SPARQL エンドポイントで Virtuoso の全文索引
        （bif:contains）が使えるかを一度だけ試して決める。
        """
        mode = getattr(self, "text_search", "auto") or "auto"
        if mode in ("bif", "contains"):
            return mode
        cache = getattr(self, "text_search_cache", None)
        if cache is None:
            cache = {}
        if label_predicate not in cache:
            method = probe_bif_contains(self.sparql_client, label_predicate)
            if method is None:          # 確かめられなかった: 今回は CONTAINS で探し、覚えない
                return "contains"
            cache[label_predicate] = method
            logger.info(
                "候補の検索（%s）: %s", label_predicate,
                "全文索引 bif:contains を使います" if cache[label_predicate] == "bif"
                else "bif:contains が使えないため CONTAINS を使います",
            )
        return cache[label_predicate]

    def text_condition(self, text, exact=False, collection=None):
        """検索語の条件（ラベルに検索語を含む。URL の q、mode=perfect なら完全一致）を返す（2026.10.19）。

        Virtuoso の全文索引（bif:contains）が使えればそれで先に絞る。全文索引は語単位の一致なので、
        collection を渡すと、全文索引で1件も無いときは CONTAINS だけで探す条件にする（text_search: auto のとき）
        """
        label_predicate = getattr(self, "label_predicate", None) or "rdfs:label"
        method = self.text_search_method(label_predicate)
        condition = TextCondition(text, label_predicate, method=method, exact=exact)
        if (method == "bif" and collection is not None
                and getattr(self, "text_search", "auto") == "auto"
                and collection.where(condition).count() == 0):
            condition = TextCondition(text, label_predicate, method="contains", exact=exact)
        return condition

    def search_collection(self, text, exact=False):
        """検索結果（ラベルに検索語を含むリソース）のコレクション"""
        return AnyCollection(self.sparql_client).where(self.text_condition(text, exact, AnyCollection(self.sparql_client)))

    def make_gadget(self, gadget_name, uri, params=None, collection=None,):
        """Gadgetを実行してHTMLを作成する。"""
        name, path, gadget = self.resolve_gadget(gadget_name)
        if gadget is None:
            return error("gadget定義がない", name)
        # path指定ならuriを移動
        if path:
            uri = move_focus(uri, path, self.sparql_client)
            if uri is None:
                return f"""
        <section class="gadget">
        <h2 class="gadget-title">{gadget_name}</h2>
        <p class="gadget-empty">該当するデータがありません</p>
        </section>
        """
        if params is None:
            params = {}
        # variants（条／法令など）を URL で選ぶ
        gadget, variant_bar = gadget.with_variant(name, params) if getattr(gadget, "variants", None) else (gadget, "")
        # データ取得
        logger.info(
            "make_gadget: name=%r gadget=%r collection=%r",
            gadget_name,
            gadget,
            collection,
        )
        try:
            content = gadget.extract(uri, application=self, params=params, collection=collection)
        except SparqlError as e:
            # 1つのガジェットの問い合わせの失敗で、ページ全体をエラーにしない（DBpedia など公開のエンドポイント。2026.10.27）
            return f"""
        <section class="gadget">
        <h2 class="gadget-title">{html_escape(self.gadget_title(gadget_name, gadget))}</h2>
        <p class="gadget-error">{html_escape(e.message)}</p>
        <details class="gadget-error-detail"><summary>詳しい情報</summary><pre>{html_escape(e.detail or '')}</pre></details>
        </section>
        """
        logger.debug(
            "gadget extract: type=%s rows=%d",
            type(content).__name__,
            len(content) if content else 0,
        )
        if (getattr(gadget, "show_method", None) or {}).get("type") == "graph":
            # ネットワーク図: 行を辺として読み、ノード・辺にする（コレクション外のノードを調べる。2026.10.28）
            rows_truncated = getattr(content, "truncated", False)
            content = build_graph(content, gadget.show_method, collection=collection, params=params)
            content["params"] = params
            content["rows_truncated"] = rows_truncated
        # 表示（コレクションのページで要素 ?entity の一覧なら、選んで比べるチェックボックスの列を付ける。2026.10.26）
        shown_gadget, content = with_select_column(gadget, content) if collection is not None else (gadget, content)
        gadget_body = variant_bar + shown_gadget.show(content)
        if getattr(content, "truncated", False) or (isinstance(content, dict) and content.get("rows_truncated")):
            gadget_body += (
                '<p class="gadget-notice">表示件数の上限'
                f'（{getattr(self, "max_rows", DEFAULT_MAX_ROWS):,} 行）に達したため、'
                '以降は省略しました。</p>'
            )
        page_size = getattr(gadget, "page_size", None)
        if collection is not None and page_size:
            pager = render_pager(params, page_number(params), page_size, collection.count())
            gadget_body = pager + gadget_body + pager
        title = self.gadget_title(gadget_name, gadget)
        action = ""
        config = getattr(gadget, "collection_config", None)
        if config and content and collection is None:
            if config.get("facet") and uri:
                # 表示中のリソースを値とするファセットで絞り込んだコレクション
                # （例: タームのページ → そのタームを含む判決文書。他のタームを加えられる）
                query = {}
                if config.get("class"):
                    query["class"] = config["class"]
                if config.get("view"):
                    query["view"] = config["view"]
                query[f"f.{config['facet']}"] = uri
            else:
                # 一覧をコレクションとして表示するボタン（このガジェットの SPARQL でコレクションを定義）
                query = {"from": name}
                if uri:
                    query["uri"] = uri
                if config.get("class"):
                    query["class"] = config["class"]
                if config.get("view"):
                    query["view"] = config["view"]
            action = (
                f'<a class="gadget-action" href="/collection?{html_escape(urlencode(query))}">'
                f'{html_escape(config.get("label") or "コレクションとして表示")}</a>'
            )
        compare_conf = getattr(gadget, "compare_config", None)
        if compare_conf and content and collection is None and uri:
            # 一覧と表示中のリソースを列に並べて比べる（2026.10.26）
            query = {"from": name, "uri": uri}
            if compare_conf.get("view"):
                query["view"] = compare_conf["view"]
            action += (
                f'<a class="gadget-action" href="/compare?{html_escape(urlencode(query))}">'
                f'{html_escape(compare_conf.get("label") or "並べて比べる")}</a>'
            )
        return f"""
        <section class="gadget">
        <h2 class="gadget-title">{html_escape(title)}{action}</h2>
        {gadget_body}
        </section>
        """

    @staticmethod
    def gadget_title(gadget_name, gadget):
        title = getattr(gadget, "title", None)
        if title:
            return str(title)
        extract_method = getattr(gadget, "extract_method", None) or {}
        if extract_method.get("type") == "facet" and extract_method.get("label"):
            return str(extract_method["label"])
        return gadget_name

    def make_gadgets(self, gadget_names, uri, params=None, collection=None):
        """ガジェットを並べたHTMLを返す。

        ファセットと、それ以外のガジェットの両方があれば、ファセットを左の列に置く。
        """
        facets, others = [], []
        for gadget_name in gadget_names:
            _name, _path, gadget = self.resolve_gadget(gadget_name)
            (facets if getattr(gadget, "is_facet", False) else others).append(gadget_name)
        render = lambda names: "\n".join(
            self.make_gadget(name, uri, params=params, collection=collection) for name in names
        )
        if not facets or not others:
            return render(gadget_names)
        return (
            '<div class="collection-layout">'
            f'<aside class="facet-column">{render(facets)}</aside>'
            f'<div class="main-column">{render(others)}</div>'
            '</div>'
        )


    def make_page_tabs(self, page, uri, tabs, params=None, collection=None):
        """タブ付きページを作成する。"""
        if params is None:
            params = {}
        tab_buttons = []
        tab_bodies = []
        logger.info(
            "make_page_tabs: page=%r tabs=%r collection=%r",
            page,
            tabs,
            collection,
        )
        try:
            active = int(params.get(TAB_PARAM, 0))
        except (TypeError, ValueError):
            active = 0
        if not 0 <= active < len(tabs):
            active = 0
        for i, tab in enumerate(tabs):
            tab_id = f"tab_{page}_{i}"
            current = " active" if i == active else ""
            # lazy: true のタブは、選ばれたときだけ計算する（順位表など重いもの。2026.10.20）。ボタンはページを読み直すリンク
            if tab.get("lazy") and i != active:
                href = make_url(params, drop={TAB_PARAM, RANK_PAGE_PARAM}, add=[(TAB_PARAM, str(i))])
                tab_buttons.append(
                    f'<a class="kg-tab-button kg-tab-link" href="{html_escape(href)}">'
                    f'{html_escape(str(tab["label"]))}</a>'
                )
                continue
            tab_buttons.append(
                f'<button type="button" '
                f'class="kg-tab-button{current}" '
                f'data-tab="{tab_id}" data-index="{i}">'
                f'{html_escape(str(tab["label"]))}'
                f'</button>'
            )
            gadget_html = self.make_gadgets(tab["gadget"], uri, params=params, collection=collection)
            display = "" if i == active else "display:none;"
            tab_bodies.append(
                f'<div id="{tab_id}" '
                f'class="kg-tab-content" '
                f'style="{display}">'
                f'{gadget_html}'
                f'</div>'
            )
        script = """
    <script>
    document.addEventListener("DOMContentLoaded", function () {
        const buttons = document.querySelectorAll("button.kg-tab-button");
        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                const target = button.dataset.tab;
                document.querySelectorAll(".kg-tab-content")
                    .forEach(function (content) {
                        content.style.display =
                            content.id === target ? "" : "none";
                    });
                buttons.forEach(function (b) { b.classList.toggle("active", b === button); });
                // 選んだタブを URL とフォームに残し、再読み込みや絞り込みの後も同じタブを表示する
                const index = button.dataset.index;
                const url = new URL(window.location.href);
                url.searchParams.set("tab", index);
                window.history.replaceState(null, "", url);
                document.querySelectorAll("form.facet").forEach(function (form) {
                    let input = form.querySelector('input[name="tab"]');
                    if (!input) {
                        input = document.createElement("input");
                        input.type = "hidden";
                        input.name = "tab";
                        form.appendChild(input);
                    }
                    input.value = index;
                });
            });
        });
    });
    </script>
    """
        return [
            '<div class="kg-tabs">',
            '<div class="kg-tab-buttons">',
            "\n".join(tab_buttons),
            '</div>',
            "\n".join(tab_bodies),
            script,
            '</div>',
        ]

    def get_collection(self, uri=None, params=None, query=None):
        """現在のページに対応するCollectionを取得する。

        Collectionの取得方法は、次の3種類をサポートする（上ほど優先）。

        1. queryが指定されている場合: ページ定義のqueryによって定義されるCollection
        2. classが指定されている場合: classに属するリソースのCollection
        3. uriが指定されている場合: uriを要素とするCollection

        このメソッドではCollectionの絞り込みは行わない。
        絞り込みはCollection側で行う。
        """
        if params is None:
            params = {}
        # page定義のqueryによって定義されるCollection
        if query:
            logger.debug("get_collection: query=%r params=%r", query, params)
            return Collection.from_query(
                self.sparql_client,
                query,
                params=params,
            )
        # classによって定義されるCollection
        class_uri = params.get("class")
        if class_uri:
            return Collection.from_class(self.sparql_client, class_uri)
        # URIを列挙して定義されるCollection
        if uri:
            return Collection.from_uris(
                self.sparql_client,
                [uri],
            )
        raise GadgetError(
            "Collectionを作成するためのclassまたはuriがありません"
        )

    def make_page(self, page, uri, params=None, base_collection=None):
        """ページ定義に従ってページを作成する。

        base_collection: コレクションのページで、ページ定義の代わりに使うコレクション
                         （ガジェットの一覧から作ったコレクションなど）
        """
        logger.info(
            "make_page: page=%r uri=%r params=%r",
            page,
            uri,
            params,
        )
        page_def = self.pages.pagedict[page]
        if params is None:
            params = {}
        collection = self.page_collection(page, uri, params, base_collection)
        logger.debug(
            "collection: query=%r",
            collection.get_query() if collection is not None else None,
        )
        header = []
        if collection is not None:
            header = [self.make_collection_header(collection, params)]
        tabs = page_def.get("tabs")
        if tabs:
            body = self.make_page_tabs(page, uri, tabs, params=params, collection=collection)
        elif collection is None:
            body = [self.make_gadget(gadget_name, uri, params=params, collection=collection) for gadget_name in page_def["gadget"]]
        else:
            body = [self.make_gadgets(page_def["gadget"], uri, params=params, collection=collection)]
        sidebar = page_def.get("sidebar") or []
        if sidebar:
            aside = "\n".join(
                self.make_gadget(gadget_name, uri, params=params, collection=collection)
                for gadget_name in sidebar
            )
            body = [
                '<div class="collection-layout">'
                f'<aside class="facet-column">{aside}</aside>'
                '<div class="main-column">' + "\n".join(body) + "</div>"
                "</div>"
            ]
        return header + body

    def page_collection(self, page, uri, params=None, base_collection=None):
        """ページのコレクション（URL のファセット・検索語の条件で絞り込んだもの）。コレクションの無いページは None"""
        page_def = self.pages.pagedict[page]
        params = params or {}
        collection = None
        if base_collection is not None:
            collection = base_collection
        elif page_def.get("type") == "collection":
            collection = self.get_collection(
                uri,
                params=params,
                query=page_def.get("query"),
            )
        elif page_def.get("collection") == "instances" and uri:
            # リソース（クラス）のページで、そのクラスのインスタンスをコレクションにする
            collection = Collection.from_class(self.sparql_client, uri)
        if collection is not None:
            # URLで指定されたFacet条件で絞り込み、ページ内のGadgetで共有する
            collection = self.apply_collection_filters(collection, params)
        return collection

    def make_collection_header(self, collection, params):
        """コレクションのページの先頭に、件数と現在の絞り込み条件を表示する。"""
        definitions = {}
        for gadget in self.gadgetset.values():
            extract_method = getattr(gadget, "extract_method", {}) or {}
            if extract_method.get("type") == "facet" and extract_method.get("name"):
                definitions[extract_method["name"]] = extract_method
        labels = self.condition_labels(params, definitions)
        return (render_conditions(params, definitions, count=collection.count(), labels=labels)
                + '<div class="collection-tools">' + render_search_box(params) + render_save_form(params)
                + f'<div class="kg-compare-bar" id="kg-compare-bar" data-max="{COMPARE_MAX}"></div></div>')

    def condition_labels(self, params, definitions):
        """現在の条件の値（IRI）のラベルを、1回の問い合わせでまとめて取得する。"""
        values, _ranges = facet_selection(params)
        by_predicate = {}
        for name, selected in values.items():
            definition = definitions.get(name) or {}
            label_predicate = definition.get("label_predicate", "rdfs:label")
            for value in selected:
                if is_iri(value):
                    by_predicate.setdefault(label_predicate, set()).add(value)
        labels = {}
        for label_predicate, iris in by_predicate.items():
            query = (
                "SELECT ?value (SAMPLE(?label) AS ?name)\n"
                "WHERE {\n"
                f"    VALUES ?value {{ {' '.join(iri_term(v) for v in sorted(iris))} }}\n"
                f"    ?value {predicate_term(label_predicate)} ?label .\n"
                "}\n"
                "GROUP BY ?value"
            )
            try:
                rows = self.sparql_client.query(query)
            except KGraphError:
                # ラベルが取れなくても条件の表示は続ける
                logger.warning("条件のラベルを取得できませんでした", exc_info=True)
                continue
            for row in rows or []:
                if "value" in row and "name" in row:
                    labels[row["value"]["value"]] = row["name"]["value"]
        return labels

    # 記憶するクラスの数の上限
    CLASS_PAGE_CACHE_SIZE = 1000

    def collection_page(self, class_uri):
        """RDFクラスに対応するコレクションのページ名を返す。

        1. class: にそのクラスを含むページ
        2. そのクラスの上位クラスを class: に含むページ（rdfs:subClassOf+ を1回問い合わせる）
        3. class も query も持たないコレクションのページ
        4. 組み込みのコレクションのページ
        """
        class_uri = expand_prefixed(class_uri, self.prefixes)
        if class_uri in self.class_page_cache:
            return self.class_page_cache[class_uri]
        page = self.pages.collection_page_for_class(class_uri)
        if page is None:
            candidates = [c for c in self.pages.collection_classes() if c != class_uri]
            if candidates:
                superclasses = self.sparql_client.get_superclasses_among(class_uri, candidates)
                # ページ定義の順で最初に見つかったもの
                for candidate in candidates:
                    if candidate in superclasses:
                        page = self.pages.collection_page_for_class(candidate)
                        break
        if page is None:
            page = self.pages.default_collection_page() or BUILTIN_COLLECTION_PAGE
        if len(self.class_page_cache) >= self.CLASS_PAGE_CACHE_SIZE:
            self.class_page_cache.clear()
        self.class_page_cache[class_uri] = page
        return page

    def gadget_collection(self, gadget_name, uri=None):
        """ガジェットの一覧（collection.var の列）をコレクションにする。

        ガジェットの SPARQL を副問い合わせとして使い、var の値を要素とする。
        SPARQL 中の $uri には uri を入れる。
        """
        gadget = self.gadgetset.get(gadget_name)
        config = getattr(gadget, "collection_config", None)
        if gadget is None or not config:
            raise GadgetError(f"gadget({gadget_name})はコレクションにできません")
        if gadget.extract_method.get("type") != "sparql":
            raise GadgetError(f"gadget({gadget_name})の取得方法は sparql でなければなりません")
        src = gadget.extract_method.get("src", "")
        if "$uri" in src and not uri:
            raise GadgetError(f"gadget({gadget_name})のコレクションには uri が必要です")
        query = (
            f"SELECT DISTINCT (?{config['var']} AS ?uri)\n"
            "WHERE {\n"
            "  {\n"
            f"{src.strip()}\n"
            "  }\n"
            f"  FILTER(isIRI(?{config['var']}))\n"
            "}"
        )
        return Collection.from_query(self.sparql_client, query, params={"uri": uri} if uri else {})

    def graph_page(self):
        """知識グラフ全体（/graph）のページ名。なければNone"""
        pages = self.pages.pages_of_type("graph")
        return pages[0] if pages else None

    def get_facet_definition(self, name):
        """nameに対応するfacet Gadgetの定義を返す。"""
    
        for gadget_name, gadget in self.gadgetset.items():
            extract_method = gadget.extract_method
    
            if extract_method.get("type") != "facet":
                continue
    
            if extract_method.get("name") == name:
                return extract_method
    
        return None
    
    def apply_collection_filters(self, collection, params=None, *, exclude=None):
        """URLパラメータのFacet条件をCollectionに適用する。

        - Facetとして定義されていないパラメータ、値が空のパラメータは無視する
        - exclude に指定した名前のFacetは適用しない（そのFacet自身の候補計算用）
        - Collectionに同じ名前の条件が既に付いていれば重ねて適用しない
        """
        if params is None:
            params = {}
        excluded = set(exclude or ())
        applied = {condition.name for condition in collection.conditions}
        result = collection
        # 検索語（q。mode=perfect なら完全一致）: ラベルに検索語を含む（2026.10.19）
        text = params.get(SEARCH_PARAM)
        if isinstance(text, str) and text.strip() and SEARCH_PARAM not in excluded and SEARCH_PARAM not in applied:
            result = result.where(self.text_condition(text, params.get(SEARCH_MODE_PARAM) == "perfect", collection))
            applied.add(SEARCH_PARAM)
        for name, value in params.items():
            # Collection自身を定義するパラメータ、検索語
            if name in ("class", "uri", "saved", SEARCH_PARAM, SEARCH_MODE_PARAM):
                continue
            # 値が指定されていないパラメータ、除外するFacet、適用済みのFacet
            if value is None or value == "" or name in excluded or name in applied:
                continue
            facet = self.get_facet_definition(name)
            # Facetとして定義されていないパラメータは無視
            if facet is None:
                continue
            predicate = facet.get("predicate")
            if not predicate:
                raise GadgetError(
                    f"facet({name})にpredicateがありません"
                )
            result = result.filter(
                predicate,
                value,
                value_type=facet.get("value_type", "auto"),
                name=name,
            )
            applied.add(name)
        # f.<name>=値（複数値は OR）、f.<name>.min / .max（範囲）
        values, ranges = facet_selection(params)
        for name, selected in values.items():
            if name in excluded or name in applied or not selected:
                continue
            facet = self._facet_for(name)
            if facet is None or facet.get("kind", "value") != "value":
                continue
            if match_mode(facet, params, name) == "all":
                # すべての値を持つ（AND）: 値ごとに条件を重ねる
                for value in selected:
                    result = result.filter(
                        facet["predicate"],
                        [value],
                        value_type=facet.get("value_type", "auto"),
                        name=name,
                    )
            else:
                # いずれかの値を持つ（OR）
                result = result.filter(
                    facet["predicate"],
                    selected,
                    value_type=facet.get("value_type", "auto"),
                    name=name,
                )
            applied.add(name)
        for name, bounds in ranges.items():
            if name in excluded or name in applied:
                continue
            facet = self._facet_for(name)
            if facet is None or facet.get("kind") != "range":
                continue
            datatype = facet.get("datatype")
            if not datatype:
                raise GadgetError(f"facet({name})にdatatypeがありません")
            result = result.filter_range(
                facet["predicate"],
                datatype,
                bounds.get("min"),
                bounds.get("max"),
                unit=facet.get("unit"),
                name=name,
            )
            applied.add(name)
        return result

    def _facet_for(self, name):
        """ファセット定義を返す。predicate がなければエラー、未定義ならNone"""
        facet = self.get_facet_definition(name)
        if facet is not None and not facet.get("predicate"):
            raise GadgetError(f"facet({name})にpredicateがありません")
        return facet


def error(message_type, message):
    return render_template('error.html', message_type=message_type, message=message)

def setconfig(config, base_dir=None):
    """configファイルからpage定義、gadget定義、各種設定を読み込む

    base_dir: import やフォルダ指定の相対パスを解決する基準。省略時は CONFIG_DIR
    """
    base_dir = Path(base_dir) if base_dir is not None else CONFIG_DIR

    def parse_uri_sample(value):
        """URIサンプルを [URI, 表示名] に変換する。"""
        value = value.strip()
        if "," in value:
            uri, label = value.split(",", 1)
            return [uri.strip(), label.strip()]
        return [value, value]

    def load_imports(configs, importing=None):
        """設定リスト中のimportを再帰的に展開する。
        import は base_dir からの相対パスとして解決する。
        循環 import は ConfigError とする。
        """
        if importing is None:
            importing = []
        result = []
        for config in configs:
            if not isinstance(config, dict):
                raise ConfigError(f"設定項目は辞書でなければなりません: {config!r}")
            imports = config.get("import", [])
            if isinstance(imports, str):
                imports = [imports]
            elif not isinstance(imports, list):
                raise ConfigError(f"importは文字列またはリストで指定してください: {imports!r}")
            for filename in imports:
                path = (base_dir / filename).resolve()
                if path in importing:
                    chain = " -> ".join(p.name for p in importing + [path])
                    raise ConfigError(f"importが循環しています: {chain}")
                imported = load_yaml(path)
                if not isinstance(imported, list):
                    raise ConfigError(f"import先は設定項目のリストでなければなりません: {filename}")
                result.extend(load_imports(imported, importing=importing + [path]))
            # import は読み込み指示なので、通常の設定としては残さない
            config = dict(config)
            config.pop("import", None)
            if config:
                result.append(config)
        return result

    def validate_pages(pages, gadgetset):
        """pageから参照されるgadgetの存在を検証する。"""
        errors = set()
        for page_name, page in pages.pagedict.items():
            for gadget_name in page.get("sidebar") or []:
                if gadget_name not in gadgetset:
                    errors.add(f"page({page_name}) sidebar -> gadget({gadget_name})")
            for gadget_name in page.get("gadget") or []:
                if gadget_name not in gadgetset:
                    errors.add(f"page({page_name}) -> gadget({gadget_name})")
            for tab_index, tab in enumerate(page.get("tabs") or []):
                for gadget_name in tab.get("gadget") or []:
                    if gadget_name not in gadgetset:
                        errors.add(
                            f"page({page_name}) "
                            f"tab[{tab_index}] -> gadget({gadget_name})"
                        )
        if errors:
            raise ConfigError("設定エラーが見つかりました:\n" + "\n".join(f"  - {error}" for error in sorted(errors)))

    def validate_gadget_config(config):
        """gadget定義の構造を検証する。"""
    
        errors = []
        name = config.get("name")
        if not name:
            errors.append("nameがありません")
        get_config = config.get("get")
        if get_config is None:
            errors.append("getがありません")
        elif not isinstance(get_config, dict):
            errors.append("getは辞書で指定してください")
        else:
            get_type = get_config.get("type")
            if not get_type:
                errors.append("get.typeがありません")
            elif get_type not in SUPPORTED_GET_TYPES:
                errors.append(f"未対応のget.typeです: {get_type!r}")
            if get_type == "sparql":
                src = get_config.get("src")
                if not src or not isinstance(src, str):
                    errors.append("get.type=sparql の場合、get.srcが必要です")
                if "max_rows" in get_config:
                    try:
                        if int(get_config["max_rows"]) <= 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        errors.append("get.max_rowsは正の整数で指定してください")
            if get_type == "rank":
                if not get_config.get("facet") and not get_config.get("predicate"):
                    errors.append("get.type=rank の場合、get.facet か get.predicate が必要です")
                if get_config.get("order", "count") not in ("count", "value"):
                    errors.append("get.order は count か value です")
                if get_config.get("measure", "count") not in ("count", "ratio"):
                    errors.append("get.measure は count か ratio です")
                if get_config.get("measure") == "ratio" and not get_config.get("denominator"):
                    errors.append("get.measure=ratio の場合、get.denominator が必要です")
        show_config = config.get("show")
        if show_config is None:
            errors.append("showがありません")
        elif not isinstance(show_config, dict):
            errors.append("showは辞書で指定してください")
        else:
            show_type = show_config.get("type")
            if not show_type:
                errors.append("show.typeがありません")
            elif show_type not in SUPPORTED_SHOW_TYPES:
                errors.append(f"未対応のshow.typeです: {show_type!r}")
            if show_type == "graph":
                try:
                    validate_graph_show(config.get("name"), show_config)
                except ConfigError as e:
                    errors.append(str(e))
            if show_type == "htable":
                columns = show_config.get("columns")
                if columns is None:
                    errors.append("show.type=htable の場合、show.columnsが必要です")
                elif not isinstance(columns, list):
                    errors.append("show.columnsはリストで指定してください")
                else:
                    for i, column in enumerate(columns):
                        if not isinstance(column, dict):
                            errors.append(f"show.columns[{i}]は辞書で指定してください")
                            continue
                        if not column.get("id"):
                            errors.append(f"show.columns[{i}].idがありません")
                        if not column.get("type"):
                            errors.append(f"show.columns[{i}].typeがありません")
        if errors:
            raise ConfigError(
                f"gadget({name or '?'})の設定エラー:\n"
                + "\n".join(f"  - {error}" for error in errors)
            )
        
    APPLICATION_KEYS = {
        "rdfstore",
        "label",
        "sample",
        "priority",
        "title",
        "describe",
        "prefixes",
        "sparql_endpoint",
        "frontend_base_url",
        "data_dir",
        "data_dirs", # /data/<名前>/<path> で配信する別のフォルダ {名前: フォルダ}
        "static_dirs", # /<名前>/<path> で配信するフォルダ {名前: フォルダ}（判決HTMLのCSSなど）
        "saved_collections_dir", # 名前を付けて保存したコレクションのフォルダ（既定は設定ファイルのフォルダの saved_collections）
        "saved_collection_max",  # 保存できるコレクションの要素の数の上限（既定 10000）
        "max_rows",
        "label_lang",
        "text_search", # ファセットの候補の検索: auto（既定）/ bif / contains
        "topic",       # キーワードからトピックのコレクションを作る（kgraphnavi/topic.py。2026.10.26）
        "compare",     # 少数のリソースを列に並べて比べる比べ方（kgraphnavi/compare.py。2026.10.26）
    }
    PAGE_KEYS = {
        "def",
        "name",
        "type", # ページの種類
        "query",
        "gadget", # 表示するガジェット
        "tabs", # ガジェットをタブで分類
        "class", # コレクションのページが対象とするRDFクラス
        "sidebar", # 左の列に置くガジェット（ファセットなど）。gadget / tabs の横に表示
        "collection", # instances: リソースのページで、そのリソース（クラス）のインスタンスをコレクションにする
    }
    GADGET_KEYS = {
        "def",
        "name",
        "title", # 見出し（省略時はガジェット名、ファセットは get.label）
        "collection", # 一覧をコレクションとして表示するボタン {var, class, label}
        "compare",    # 一覧（var の列）と表示中のリソースを並べて比べるボタン {var, label, self}（2026.10.26）
        "height",
        "get",
        "show",
        "variants",   # 画面で切り替える問い合わせ・表示 [{name, label, get, show}]（2026.10.28）
    }
    
    configs = load_imports(config)
    pages = Pages()
    gadgetset = {}
    rdfstore = None
    sparql_endpoint = None
    frontend_base_url = None
    data_dir = None
    data_dirs = {}
    static_dirs = {}
    saved_collections_dir = None
    saved_collection_max = DEFAULT_SAVE_MAX
    max_rows = DEFAULT_MAX_ROWS
    label_lang = None
    text_search = "auto"
    topic = None
    compare = None
    label_predicate = None
    prefixes = {}
    query_samples = []
    resource_samples = []
    collection_samples = []
    priority_list = []
    title = "KG frontend"
    describe = ""

    for config in configs:
        if not isinstance(config, dict):
            raise ConfigError(f"設定項目は辞書でなければなりません: {config!r}")
        deftype = config.get("def")

        if deftype is None: # application設定
            unknown = set(config) - APPLICATION_KEYS
            if unknown:
                raise ConfigError(f"未知のapplication設定キー: {sorted(unknown)}")
            if "rdfstore" in config:
                rdfstore = config["rdfstore"]
            if "label" in config:
                label_predicate = config["label"]
            if "sample" in config:
                sample = config["sample"] or {}
                resource_samples = [
                    parse_uri_sample(value)
                    for value in sample.get("resource", [])]
                collection_samples = [
                    parse_uri_sample(value)
                    for value in sample.get("collection", [])]
                query_samples = list(sample.get("search", []) or [])
            if "priority" in config:
                priority_list = config["priority"]
            if "title" in config:
                title = config["title"]
            if "describe" in config:
                describe = config["describe"]
            if "prefixes" in config:
                prefixes = config["prefixes"]
            if "sparql_endpoint" in config:
                sparql_endpoint = config["sparql_endpoint"]
            if "frontend_base_url" in config:
                frontend_base_url = config["frontend_base_url"]
            if "data_dir" in config:
                data_dir = resolve_dir(config["data_dir"], base_dir)
            if "data_dirs" in config:
                if not isinstance(config["data_dirs"], dict):
                    raise ConfigError("data_dirs は {名前: フォルダ} の形で書いてください")
                for key, value in config["data_dirs"].items():
                    data_dirs[str(key)] = resolve_dir(value, base_dir)
            if "saved_collections_dir" in config:
                saved_collections_dir = resolve_dir(config["saved_collections_dir"], base_dir)
            if "saved_collection_max" in config:
                saved_collection_max = int(config["saved_collection_max"])
            if "static_dirs" in config:
                if not isinstance(config["static_dirs"], dict):
                    raise ConfigError("static_dirs は {名前: フォルダ} の形で書いてください")
                for key, value in config["static_dirs"].items():
                    if str(key) in RESERVED_STATIC_NAMES:
                        raise ConfigError(f"static_dirs の名前 '{key}' は KGraphNavi が使っています")
                    static_dirs[str(key)] = resolve_dir(value, base_dir)
            if "label_lang" in config:
                label_lang = config["label_lang"]
            if "text_search" in config:
                text_search = str(config["text_search"]).strip().lower()
                if text_search not in TEXT_SEARCH_MODES:
                    raise ConfigError(
                        f"text_searchは {' / '.join(TEXT_SEARCH_MODES)} のいずれかです: {config['text_search']!r}"
                    )
            if "topic" in config:
                try:
                    topic = topic_settings(config["topic"])
                except ValueError as e:
                    raise ConfigError(str(e)) from e
            if "compare" in config:
                try:
                    compare = compare_settings(config["compare"])
                except ValueError as e:
                    raise ConfigError(str(e)) from e
            if "max_rows" in config:
                try:
                    max_rows = int(config["max_rows"])
                except (TypeError, ValueError) as e:
                    raise ConfigError(f"max_rowsは整数で指定してください: {config['max_rows']!r}") from e
        elif deftype == "page": # page定義
            unknown = set(config) - PAGE_KEYS
            if unknown:
                raise ConfigError(f"未知のpage設定キー: {sorted(unknown)}")
            name = config.get("name")
            if not name:
                raise ConfigError(f"page定義にnameがありません: {config!r}")
            if not config.get("type"):
                raise ConfigError(f"page定義にtypeがありません: {name}")
            if str(name).startswith("_"):
                raise ConfigError(f"_ で始まるpage名は組み込み用です: {name}")
            pages.set_page(name, config)
        elif deftype == "gadget": # gadget定義
            unknown = set(config) - GADGET_KEYS
            if unknown:
                raise ConfigError(f"未知のgadget設定キー: {sorted(unknown)}")
            name = config.get("name")
            if not name:
                raise ConfigError(f"gadget定義にnameがありません: {config!r}")
            if "get" not in config:
                raise ConfigError(f"gadget定義にgetがありません: {name}")
            if "show" not in config:
                raise ConfigError(f"gadget定義にshowがありません: {name}")
            if name in gadgetset:
                raise ConfigError(f"gadgetが二重定義されています: {name}")
            if str(name).startswith("_"):
                raise ConfigError(f"_ で始まるgadget名は組み込み用です: {name}")
            height = config.get("height", 500)
            gadget_collection = config.get("collection")
            if gadget_collection is not None:
                if isinstance(gadget_collection, str):
                    gadget_collection = {"var": gadget_collection}
                if not isinstance(gadget_collection, dict):
                    raise ConfigError(f"gadget({name})のcollectionは辞書で指定してください")
                if gadget_collection.get("facet"):
                    if not re.fullmatch(r"[\w.-]+", str(gadget_collection["facet"])):
                        raise ConfigError(f"gadget({name})のcollection.facetが不正です")
                elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(gadget_collection.get("var", ""))):
                    raise ConfigError(f"gadget({name})のcollectionには var（変数名）か facet が必要です")
                if config["get"].get("type") != "sparql":
                    raise ConfigError(f"gadget({name})のcollectionは get.type: sparql のガジェットでだけ使えます")
            gadget_compare = config.get("compare")
            if gadget_compare is not None:
                if isinstance(gadget_compare, str):
                    gadget_compare = {"var": gadget_compare}
                if not isinstance(gadget_compare, dict) or not re.fullmatch(
                        r"[A-Za-z_][A-Za-z0-9_]*", str(gadget_compare.get("var", ""))):
                    raise ConfigError(f"gadget({name})のcompareには var（変数名）が必要です")
            variants = parse_variants(name, config)
            for show in [config["show"]] + [{**config["show"], **(v.get("show") or {})} for v in variants]:
                if isinstance(show, dict) and show.get("type") == "graph":
                    validate_graph_show(name, show)
            max_rows_conf = (config["get"] or {}).get("max_rows") if isinstance(config["get"], dict) else None
            if max_rows_conf is not None:
                try:
                    if int(max_rows_conf) <= 0:
                        raise ValueError
                except (TypeError, ValueError) as e:
                    raise ConfigError(f"gadget({name})のget.max_rowsは正の整数です") from e
            gadgetset[name] = Gadget(
                config_get=config["get"],
                config_show=config["show"],
                height=height,
                title=config.get("title"),
                collection=gadget_collection,
                compare=gadget_compare,
                variants=variants,
            )
        else: # 未知のdef
            raise ConfigError(f"未知のdef: {deftype!r}(page または gadget を指定してください)")
    pages.resolve_prefixes({**STANDARD_PREFIXES, **(prefixes or {})})
    # class に対応するページがないときに使う組み込みのコレクションのページ
    gadgetset[BUILTIN_COLLECTION_GADGET] = builtin_collection_gadget(
        label_predicate or "rdfs:label", label_lang
    )
    pages.pagedict[BUILTIN_COLLECTION_PAGE] = {
        "type": "collection",
        "gadget": [BUILTIN_COLLECTION_GADGET],
        "tabs": None,
        "query": None,
        "class": [],
    }
    # 検索結果（/search）のページ: ラベルに検索語を含むリソースのコレクション。種類（rdf:type）のファセットで
    # クラスを1つ選ぶと、そのクラスのコレクションのページに検索語の条件を持ったまま移る（2026.10.19）
    gadgetset[BUILTIN_SEARCH_GADGET] = builtin_search_gadget(label_predicate or "rdfs:label", label_lang)
    gadgetset[BUILTIN_TYPE_FACET] = Gadget(
        config_get={"type": "facet", "name": TYPE_FACET, "label": "種類", "predicate": "rdf:type",
                    "value_type": "iri", "limit": 50},
        config_show={"type": "facet"},
        height=None,
    )
    pages.pagedict[BUILTIN_SEARCH_PAGE] = {
        "type": "collection",
        "gadget": [BUILTIN_SEARCH_GADGET],
        "sidebar": [BUILTIN_TYPE_FACET],
        "tabs": None,
        "query": None,
        "class": [],
    }
    validate_pages(pages, gadgetset)
    return {
        "pages": pages,
        "gadgetset": gadgetset,
        "title": title,
        "describe": describe,
        "querysamples": query_samples,
        "resource_samples": resource_samples,
        "collection_samples": collection_samples,
        "prioritylist": priority_list,
        "rdfstore": rdfstore,
        "labelpredicate": label_predicate,
        "sparql_endpoint": sparql_endpoint,
        "prefixes": prefixes,
        "frontend_base_url": frontend_base_url,
        "data_dir": data_dir,
        "data_dirs": data_dirs,
        "static_dirs": static_dirs,
        "saved_collections_dir": saved_collections_dir or (base_dir / "saved_collections"),
        "saved_collection_max": saved_collection_max,
        "max_rows": max_rows,
        "text_search": text_search,
        "topic": topic,
        "compare": compare,
    }


def resolve_dir(value, base_dir):
    """フォルダ指定を絶対パスにする。~ を展開し、相対パスは base_dir 基準で解決する。"""
    if value is None or value == "":
        return None
    path = Path(os.path.expanduser(str(value)))
    if not path.is_absolute():
        path = Path(base_dir) / path
    return path.resolve()


def resolve_config_path(name):
    """設定ファイルのパスを求める。

    指定されたパスが存在すればそれを使い、なければ CONFIG_DIR から探す。
    """
    path = Path(os.path.expanduser(str(name)))
    if path.is_file():
        return path.resolve()
    candidate = CONFIG_DIR / name
    if candidate.is_file():
        return candidate.resolve()
    raise ConfigError(f"設定ファイルが見つかりません: {name}")


def load_config(config_path, local_path=None):
    """設定ファイルを読み込み、ローカル設定があれば末尾に追加して返す。

    ローカル設定は、local_path が指定されればそれを、なければ設定ファイルと同じフォルダの
    <設定ファイル名>.local.yaml（例: caselaw.local.yaml。その設定ファイルだけに使う。2026.10.27）、
    それも無ければ local.yaml を（存在すれば）使う。後から読んだ設定が優先される。
    """
    config_path = resolve_config_path(config_path)
    items = load_yaml(config_path) or []
    if not isinstance(items, list):
        raise ConfigError(f"設定ファイルは設定項目のリストでなければなりません: {config_path}")
    if local_path is None:
        for candidate in (config_path.with_name(f"{config_path.stem}.local.yaml"),
                          config_path.parent / LOCAL_CONFIG_NAME):
            if candidate.is_file():
                local_path = candidate
                break
    if local_path is not None:
        local_items = load_yaml(local_path) or []
        if not isinstance(local_items, list):
            raise ConfigError(f"ローカル設定は設定項目のリストでなければなりません: {local_path}")
        logger.info("ローカル設定を読み込みます: %s", local_path)
        items = items + local_items
    return setconfig(items, base_dir=config_path.parent)


def build_application(
    config_path,
    *,
    endpoint=None,
    label=None,
    data_dir=None,
    local_path=None,
):
    """設定ファイルからApplicationを作成する。

    引数で指定された値は設定ファイルより優先される。
    """
    cfg = load_config(config_path, local_path=local_path)
    endpoint = (
        endpoint
        or cfg.get("sparql_endpoint")
        or "http://localhost:8890/sparql"
    )
    label_predicate = label or cfg["labelpredicate"] or "rdfs:label"
    frontend_base_url = cfg["frontend_base_url"] or "/"
    data_dir = resolve_dir(data_dir, Path.cwd()) if data_dir else cfg["data_dir"]
    sparql_client = SPARQL(endpoint, cfg["prefixes"], label_predicate)
    # Gadget に sparql_client を渡す
    for gadget in cfg["gadgetset"].values():
        gadget.sparql_client = sparql_client
    application = Application(
        frontend_base_url,
        cfg["pages"],
        cfg["gadgetset"],
        cfg["title"],
        cfg["describe"],
        cfg["querysamples"],
        cfg["resource_samples"],
        cfg["collection_samples"],
        cfg["prioritylist"],
        sparql_client,
        data_dir,
    )
    application.max_rows = cfg["max_rows"]
    application.data_dirs = {k: v for k, v in (cfg.get("data_dirs") or {}).items() if v}
    application.static_dirs = {k: v for k, v in (cfg.get("static_dirs") or {}).items() if v}
    if cfg.get("saved_collections_dir"):
        application.saved_store = SavedCollectionStore(cfg["saved_collections_dir"])
    application.saved_max = cfg.get("saved_collection_max") or DEFAULT_SAVE_MAX
    application.text_search = cfg.get("text_search", "auto")
    application.label_predicate = label_predicate
    application.prefixes = {**STANDARD_PREFIXES, **(cfg["prefixes"] or {})}
    application.topic_config = cfg.get("topic")
    application.compare_views = cfg.get("compare") or []
    resolve_compare_types(application.compare_views, lambda t: expand_prefixed(t, application.prefixes))
    if application.topic_config:   # 上の帯に「トピック」の入り口
        application.navi = application.navi.replace(
            '<li class="nav_right search_item">',
            f'<li class="nav_right search_item">{TOPIC_FORM}</li><li class="nav_right search_item">', 1)
    return application


def create_app_from_env():
    """環境変数からFlaskアプリを作成する（WSGIサーバ用）。

    KGRAPHNAVI_CONFIG   設定ファイル（必須）
    KGRAPHNAVI_ENDPOINT SPARQLエンドポイント
    KGRAPHNAVI_LABEL    ラベルのpredicate
    KGRAPHNAVI_DATA_DIR /data で配信するフォルダ
    KGRAPHNAVI_LOCAL    ローカル設定ファイル

    例: gunicorn "kgraphnavi.app:create_app_from_env()"
    """
    config_path = os.environ.get("KGRAPHNAVI_CONFIG")
    if not config_path:
        raise ConfigError("環境変数 KGRAPHNAVI_CONFIG に設定ファイルを指定してください")
    application = build_application(
        config_path,
        endpoint=os.environ.get("KGRAPHNAVI_ENDPOINT"),
        label=os.environ.get("KGRAPHNAVI_LABEL"),
        data_dir=os.environ.get("KGRAPHNAVI_DATA_DIR"),
        local_path=os.environ.get("KGRAPHNAVI_LOCAL"),
    )
    return create_app(application)


def main(argv=None):
    """main"""
    parser = argparse.ArgumentParser(
        prog="kgraphnavi",
        description="RDF知識グラフを探索・可視化するWebアプリケーションを起動する",
    )
    parser.add_argument("config", help="設定ファイル（パス、または ./config/ 内のファイル名）")
    parser.add_argument("-e", "--endpoint", default=None, help="SPARQLエンドポイント（設定ファイルより優先）")
    parser.add_argument("-l", "--label", default=None, help="ラベルを表すpredicate（既定 rdfs:label）")
    parser.add_argument("--data-dir", default=None, help="/data/<path> で配信するフォルダ（設定ファイルより優先）")
    parser.add_argument("--local", default=None, help="ローカル設定ファイル（既定: 設定ファイルと同じフォルダの local.yaml）")
    parser.add_argument("--host", default="127.0.0.1", help="待ち受けるホスト（既定 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="待ち受けるポート（既定 8000）")
    parser.add_argument("--dev", action="store_true", help="開発モード（Flaskのデバッガと自動再読み込みを有効にする）")
    parser.add_argument(
        "-d", "--debug",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="ログレベル",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.debug),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    application = build_application(
        args.config,
        endpoint=args.endpoint or os.environ.get("KGRAPHNAVI_ENDPOINT"),
        label=args.label,
        data_dir=args.data_dir or os.environ.get("KGRAPHNAVI_DATA_DIR"),
        local_path=args.local,
    )
    app = create_app(application)
    app.run(host=args.host, port=args.port, debug=args.dev)

if __name__ == '__main__':
    main()
