#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      views.py
##  Author:
##      Fumihito NISHINO       nisino@nii.ac.jp
##  Description:
##      FlaskのHTTPリクエストを受け、ページ生成を呼び出す
"""

import logging
import urllib.parse
from werkzeug.exceptions import HTTPException
from flask import current_app, request, render_template, send_from_directory, Response
from .render_utils import get_highest_priority_item, get_localname
from .app import error
from .makehtml import make_html
from .facets import request_params
from .app import BUILTIN_COLLECTION_PAGE, expand_prefixed
from .errors import KGraphError, SparqlError      # 作成した例外クラス
logger = logging.getLogger(__name__)

def render_page(
    application,
    page_name: str,
    uri: str | None,
    *,
    params: dict | None = None,
    page_title: str="",
    category: str | None = None,
    base_collection=None,
) -> Response:
    """
    page名 と uri に対応するページを生成して返す。
    """
    frames = application.make_page(page_name, uri, params=params, base_collection=base_collection)
    page_body = "\n".join(frames)
    if page_name.startswith("_"):
        # 組み込みのページはページ名を出さない
        title = page_title or page_name
    else:
        title = f"{page_title}({page_name})" if uri else (page_title or page_name)
    html = make_html(
        page_body,
        title,
        navi=application.navi,
        libraries=["jsgrid", "cytoscape", "chartjs"],
        category=category or page_name,
    )
    return Response(html, mimetype="text/html")

# ルーティング
def init_app(app):

    @app.route("/")
    def root():
        # Flask のコンテキストから Application を取得
        application = current_app.extensions["application"]
        resource_samples_encode = [
            (urllib.parse.urlencode({"uri": uri}), label)
            for uri, label in application.resource_samples
        ]
        collection_samples_encode = [
            (
                urllib.parse.urlencode(
                    {"view": value}
                    if application.pages.pagedict.get(value, {}).get("type") == "collection"
                    else {"class": value}
                ),
                label,
            )
            for value, label in application.collection_samples
        ]
        return render_template(
            'index.html',
            query_samples=application.query_samples,
            resource_samples=resource_samples_encode,
            collection_samples=collection_samples_encode,
            page_title=application.title,
            describe=application.describe,
        )

    @app.route("/search", methods=["GET"])
    def search():
        application = current_app.extensions["application"]
        sparql_client = application.sparql_client
        req = request.args
        query = req.get("q")
        mode = req.get("mode")
        if not query:
            return error('検索語がありません', '/search?q=xxxと指定してください')
        retrieve_result = sparql_client.retrieve(query, mode)
        return render_template(
            'retrieval_result.html',
            query=query,
            result=retrieve_result,
            page_title=application.title,
        )

# RDFエンティティのページ
    @app.route("/resource", methods=['GET', 'POST'])
    def get_resource() -> Response:
        application = current_app.extensions["application"]
        sparql_client = application.sparql_client
        uristr = request.args.get("uri")
        logger.debug("resource uri=%r", uristr)
        if not uristr:
            return error('uriパラメタがない', '/resource?uri=xxxと指定してください')
        uri_rdftypes = sparql_client.get_target(uristr, 'a')
        logger.debug(
            "Page selection: uri=%s, rdf_types=%s",
            uristr,
            str(uri_rdftypes),
            )
        if uri_rdftypes:
            uri_rdftype = get_highest_priority_item(uri_rdftypes, application.priority_list)
        else:
            return error(f'{uristr}にはrdf:typeが設定されていない', 'rdf:typeを設定してください')
        page_name = application.pages.rdftype2page(uri_rdftype)
        page_title = get_localname(uristr)
        return render_page(
            application,
            page_name,
            uristr,
            page_title=page_title,
            category=page_name,
        )

# RDFエンティティ集合のページ
    @app.route("/collection", methods=['GET'])
    def collection() -> Response:
        """エンティティの集合（コレクション）を表示する。

        /collection?class=<クラスURI>   クラスに対応するページ（なければ組み込みのページ）
        /collection?view=<ページ名>     ページを直接指定（ページの query で集合を定義する場合など）
        /collection?from=<ガジェット名>&uri=<URI>
                                        ガジェットの一覧をコレクションとして表示
                                        （class= があればそのクラスのページで表示）
        """
        application = current_app.extensions["application"]
        # class もコレクションを定義するパラメータとして渡す
        params = request_params(request.args, path=request.path)
        view = params.get("view")
        class_uri = params.get("class")
        source = params.get("from")
        if source:
            return gadget_collection_page(application, params, source, view, class_uri)
        if view:
            page = application.pages.pagedict.get(view)
            if page is None or page.get("type") != "collection":
                return error("コレクションのページがない", f"view={view} というコレクションのページは定義されていません"), 404
            page_name = view
        elif class_uri:
            page_name = application.collection_page(class_uri)
        else:
            return error(
                "classパラメタがない",
                "/collection?class=<クラスURI> または /collection?view=<ページ名> と指定してください",
            ), 400
        page_title = (
            get_localname(expand_prefixed(class_uri, application.prefixes)) if class_uri else view
        )
        return render_page(
            application,
            page_name,
            uri=class_uri,
            params=params,
            page_title=page_title,
            category=page_name,
        )

    def gadget_collection_page(application, params, source, view, class_uri):
        """ガジェットの一覧から作ったコレクションを表示する。"""
        gadget = application.gadgetset.get(source)
        if gadget is None or not getattr(gadget, "collection_config", None):
            return error("コレクションにできる一覧がない", f"from={source} というガジェットはコレクションにできません"), 404
        target = params.get("uri")
        base = application.gadget_collection(source, target)
        if view:
            page = application.pages.pagedict.get(view)
            if page is None or page.get("type") != "collection":
                return error("コレクションのページがない", f"view={view} というコレクションのページは定義されていません"), 404
            page_name = view
        elif class_uri:
            page_name = application.collection_page(class_uri)
        else:
            page_name = BUILTIN_COLLECTION_PAGE
        list_title = gadget.collection_config.get("title") or application.gadget_title(source, gadget)
        page_title = f"{get_localname(target)}: {list_title}" if target else list_title
        return render_page(
            application,
            page_name,
            uri=None,
            params=params,
            page_title=page_title,
            category=page_name,
            base_collection=base,
        )

# グラフのページ
    @app.route("/graph", methods=["GET"])
    def graph() -> Response:
        """KG全体を対象とするGraphページ（type: graph の最初のページ）を表示する。"""
        application = current_app.extensions["application"]
        page_name = application.graph_page()
        if page_name is None:
            return error(
                "KG全体用のページがない",
                "設定ファイルに type: graph のページを定義してください",
            ), 404
        return render_page(
            application,
            page_name,
            None,
            params=request_params(request.args, path=request.path),
            page_title="Knowledge Graph",
            category=page_name,
        )

# 既存HTML等のファイルを配信
    @app.route("/data/<path:filename>")
    def getfile(filename: str):
        application = current_app.extensions["application"]
        if application.data_dir is None:
            return (
                error(
                    "データフォルダが設定されていない",
                    "設定ファイルの data_dir またはコマンドラインの --data-dir で指定してください",
                ),
                404,
            )
        # send_from_directory は data_dir の外（../ など）への参照を拒否する
        return send_from_directory(application.data_dir, filename)

    @app.errorhandler(KGraphError)
    def handle_kgraph_error(e):
        current_app.logger.warning("%s", e)
        return (
            render_template(
                "error.html",
                title="KGraphNavi Error",
                message=str(e),
            ),
            400,
        )

    @app.errorhandler(Exception)
    def handle_exception(e):
        # 404 などのHTTPエラーはそのまま返す
        if isinstance(e, HTTPException):
            return e
        current_app.logger.exception(e)
        return (
            render_template(
                "error.html",
                title="Internal Server Error",
                message="Unexpected internal error.",
            ),
            500,
        )

    @app.errorhandler(SparqlError)
    def handle_sparql_error(error):
        logger.error("SPARQL error: %s", error)
        return render_template(
            "error.html",
            title="SPARQL Error",
            message=str(error),
        ), 500