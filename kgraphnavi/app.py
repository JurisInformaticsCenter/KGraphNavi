#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      app.py
##  Author:
##      Fumihito NISHINO       nisino@nii.ac.jp
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
from pathlib import Path
import argparse
import logging
import csv
import yaml
from flask import Flask, render_template
from .render_utils import show_vertical_table, show_horizontal_table, show_facet
from .render_utils import show_chart, show_network, pairs2adjacent, show_adjacentnetwork
from .sparql import SPARQL
from .collection import Collection
from .errors import ConfigError, GadgetError, ShowError
from .terms import predicate_term

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
        # directlink の補完
        if col["type"] == "directlink":
            col.setdefault("href", lambda value: value)
        result.append(col)
    return result

class GadgetNotFound(Exception):
    pass

class Gadget:
    """Gadget"""
    __slots__ = ("extract_method", "show_method", "height", "sparql_client")
    EXTRACTORS = {
        "sparql": "extract_sparql",
        "facet": "extract_facet",
        "list": "extract_list",
        "csv2adjacent": "extract_csv2adjacent",
        "python": "extract_python",
        "csv": "extract_csv",
        "dbpedia": "extract_dbpedia",
    }
    SHOWERS = {
        "network": show_network,
        "chart": show_chart,
        "adjacentnetwork": show_adjacentnetwork,
    }

    def __repr__(self):
        return f'Config(extract={self.extract_method!r}, show={self.show_method!r})'

    def __init__(self, config_get, config_show, height):
        """Gadgetの生成。get内容の辞書と、show内容の辞書、gadgetの高さを受け取る"""
        self.extract_method = config_get
        self.show_method = config_show
        self.height = height
        self.sparql_client = None # あとで設定

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

    def _connect_collection(self, query, collection):
        """GadgetのSPARQLにCollectionの対象を接続する。

        SPARQL中の $collection を、?entity を束縛する副問い合わせに置き換える。
        $collection がなければ、最初の WHERE { の直後に挿入する。
        """
        if collection is None:
            if self.COLLECTION_PLACEHOLDER in query:
                raise GadgetError(
                    "$collection を使うガジェットはコレクションのページで使ってください"
                )
            return query
        subquery = collection.to_subquery("?entity")
        if self.COLLECTION_PLACEHOLDER in query:
            return query.replace(self.COLLECTION_PLACEHOLDER, subquery)
        match = self._WHERE_OPEN.search(query)
        if match is None:
            raise GadgetError(
                "Collectionを使用するSPARQLにはWHERE句が必要です"
            )
        return query[:match.end()] + "\n" + subquery + "\n" + query[match.end():]


    def extract_sparql(self, uri, application, params=None, collection=None):
        """SPARQLを実行してデータを取得する。"""
        logger.info(
            "extract_sparql CALLED: uri=%r collection=%r",
            uri,
            collection,
        )
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
        query = self._connect_collection(query, collection)
        logger.info(
            "extract_sparql: final query=\n%s",
            query,
        )
        result = self.sparql_client.query(query, params=params)
        return self._apply_values(result, uri)

    def extract_list(self, uri, application, params=None, collection=None):
        lines = [line for line in self.extract_method['src'].split('\n') if line]
        contents = [[val.strip() for val in line.split(',')] for line in lines]
        header = [name.strip() for name in self.extract_method['header'].split(',')]
        return make_sparql_result_from_list(contents, header)

    def extract_csv2adjacent(self, uri, application, params=None, collection=None):
        name = self.extract_method['file']
        direction = self.extract_method.get('direction')
        edge = self.extract_method['edge'].split()
        adjacent = application.get_adjacent_graph(name, edge, direction)
        target = self.sparql_client.rdfobject(uri, self.extract_method['target'])
        return (target, adjacent)

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

    def extract_facet(self, uri, application, params=None, collection=None):
        """CollectionからFacet候補を取得する。"""
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
        # 現在表示しているFacet自身の条件だけ除外して、
        # 他のFacet条件は維持する。
        collection = application.apply_collection_filters(
            collection.without({facet_name}),
            params=params,
            exclude={facet_name},
        )
        return collection.get_facets(
            predicate,
            label_predicate=self.extract_method.get("label_predicate", "rdfs:label"),
            lang=self.extract_method.get("lang"),
            limit=self.extract_method.get("limit"),
        )

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
            return shower(content, columns, **kwargs,)
        if show_type == "facet":
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
        self.pagedict[name] = {
            "type": page_type,
            "gadget": gadget,
            "tabs": tabs,
            "query": config.get("query"),
        }
        self.config = config

    def rdftype2page(self, rdftype):
        """RDF typeに対応するresource用Page名を返す"""
        for name, page in self.pagedict.items():
            if page["type"] == rdftype:
                return name
            if page["type"] == "*":
                return name
        return None

# 設定の検証で使う、対応しているget/showの種類
SUPPORTED_GET_TYPES = set(Gadget.EXTRACTORS)
SUPPORTED_SHOW_TYPES = {"vtable", "htable", "facet"} | set(Gadget.SHOWERS)

RETRIEVE_FORM = '<form action="/search" method="GET"><div class="search_wrap"><input name="q" type="search" placeholder="検索キーワード" /><button type="submit">検索</button><div class="search-modes"><label><input type="radio" name="mode" value="partial" checked>部分</label><label><input type="radio" name="mode" value="perfect">完全</label></div></div></form>'

class Application:
    """Application"""
    __slots__ = ("pages", "gadgetset", "title", "describe", "query_samples", "resource_samples", "collection_samples", "adjacent", "priority_list", "focus", "navi", "sparql_client", "data_dir")
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
        self.adjacent = dict()
        self.focus = None
        self.navi = f'<nav class="navbar"><ul><li class="nav_left"><a href="{frontend_base_url}">{self.title}</a></li><li class="nav_right search_item">{RETRIEVE_FORM}</li></ul></nav>'
        self.sparql_client = sparql_client
        self.data_dir = Path(data_dir) if data_dir else None

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
        # データ取得
        logger.info(
            "make_gadget: name=%r gadget=%r collection=%r",
            gadget_name,
            gadget,
            collection,
        )
        content = gadget.extract(uri, application=self, params=params, collection=collection)
        logger.debug(
            "gadget extract: type=%s rows=%d",
            type(content).__name__,
            len(content) if content else 0,
        )
        # 表示
        gadget_body = gadget.show(content)
        return f"""
        <section class="gadget">
        <h2 class="gadget-title">{gadget_name}</h2>
        {gadget_body}
        </section>
        """


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
        for i, tab in enumerate(tabs):
            tab_id = f"tab_{page}_{i}"
            tab_buttons.append(
                f'<button type="button" '
                f'class="kg-tab-button" '
                f'data-tab="{tab_id}">'
                f'{tab["label"]}'
                f'</button>'
            )
            gadget_html = "\n".join(self.make_gadget(gadget_name, uri, params=params, collection=collection) for gadget_name in tab["gadget"])
            display = "" if i == 0 else "display:none;"
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
        const buttons = document.querySelectorAll(".kg-tab-button");
        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                const target = button.dataset.tab;
                document.querySelectorAll(".kg-tab-content")
                    .forEach(function (content) {
                        content.style.display =
                            content.id === target ? "" : "none";
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

    def make_page(self, page, uri, params=None):
        """ページ定義に従ってページを作成する。"""
        logger.info(
            "make_page: page=%r uri=%r params=%r",
            page,
            uri,
            params,
        )
        page_def = self.pages.pagedict[page]
        if params is None:
            params = {}
        collection = None
        if page_def.get("type") == "collection":
            collection = self.get_collection(
                uri,
                params=params,
                query=page_def.get("query"),
            )
            # URLで指定されたFacet条件で絞り込み、ページ内のGadgetで共有する
            collection = self.apply_collection_filters(collection, params)
        logger.debug(
            "collection: query=%r",
            collection.get_query() if collection is not None else None,
        )
        tabs = page_def.get("tabs")
        if not tabs:
            gadget_list = page_def["gadget"]
            return [self.make_gadget(gadget_name, uri, params=params, collection=collection) for gadget_name in gadget_list]
        return self.make_page_tabs(page, uri, tabs, params=params, collection=collection)

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
        for name, value in params.items():
            # Collection自身を定義するパラメータ
            if name in ("class", "uri"):
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
        return result

    def get_adjacent_graph(self, name, edge, direction):
        if name not in self.adjacent:
            self.adjacent[name] = pairs2adjacent(
                self.import_files[name],
                edge[0],
                edge[1],
                direction,
            )
        return self.adjacent[name]


    
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
    }
    PAGE_KEYS = {
        "def",
        "name",
        "type", # ページの種類
        "query",
        "gadget", # 表示するガジェット
        "tabs", # ガジェットをタブで分類
    }
    GADGET_KEYS = {
        "def",
        "name",
        "height",
        "get",
        "show",
    }
    
    configs = load_imports(config)
    pages = Pages()
    gadgetset = {}
    rdfstore = None
    sparql_endpoint = None
    frontend_base_url = None
    data_dir = None
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
                query_samples = [sample.get("search", [])]
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
        elif deftype == "page": # page定義
            unknown = set(config) - PAGE_KEYS
            if unknown:
                raise ConfigError(f"未知のpage設定キー: {sorted(unknown)}")
            name = config.get("name")
            if not name:
                raise ConfigError(f"page定義にnameがありません: {config!r}")
            if not config.get("type"):
                raise ConfigError(f"page定義にtypeがありません: {name}")
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
            height = config.get("height", 500)
            gadgetset[name] = Gadget(
                config_get=config["get"],
                config_show=config["show"],
                height=height,
            )
        else: # 未知のdef
            raise ConfigError(f"未知のdef: {deftype!r}(page または gadget を指定してください)")
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

    ローカル設定は、local_path が指定されればそれを、なければ設定ファイルと
    同じフォルダの local.yaml を（存在すれば）使う。後から読んだ設定が優先される。
    """
    config_path = resolve_config_path(config_path)
    items = load_yaml(config_path) or []
    if not isinstance(items, list):
        raise ConfigError(f"設定ファイルは設定項目のリストでなければなりません: {config_path}")
    if local_path is None:
        candidate = config_path.parent / LOCAL_CONFIG_NAME
        local_path = candidate if candidate.is_file() else None
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
    return Application(
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
