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
from flask import current_app, request, render_template, send_from_directory, Response, redirect
from urllib.parse import urlencode, urlsplit, parse_qsl
from html import escape
from werkzeug.datastructures import MultiDict
from .render_utils import get_highest_priority_item, get_localname
from .app import error
from .makehtml import make_html
from .facets import request_params, facet_selection, SEARCH_PARAM, SEARCH_MODE_PARAM, ARGS_PARAM
from .app import BUILTIN_COLLECTION_PAGE, BUILTIN_SEARCH_PAGE, TYPE_FACET, expand_prefixed
from .errors import KGraphError, SparqlError, CollectionError      # 作成した例外クラス
from .collection import Collection
from .saved import check_name, OPERATIONS
from .topic import TopicBuilder, CommandTopicBuilder, render_topic, override_from_args
from .compare import items_from_args, choose_view, sort_items, render_compare, COMPARE_MAX
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

class CollectionRequestError(Exception):
    """コレクションの URL の誤り"""

    def __init__(self, title, message, status=400):
        super().__init__(message)
        self.title, self.message, self.status = title, message, status


def resolve_collection_request(application, path, args):
    """コレクションのページの URL（/collection・/search とその引数）から、ページ名・コレクションなどを決める。

    返り値: {"page_name", "uri", "params", "page_title", "base_collection", "class_uri"}
    （名前を付けて保存するときも、同じ URL から同じコレクションを作るために使う。2026.10.19）
    """
    params = request_params(args, path=path)
    if path == "/search":
        text = (params.get(SEARCH_PARAM) or "").strip()
        if not text:
            raise CollectionRequestError('検索語がありません', '/search?q=xxxと指定してください')
        values, _ranges = facet_selection(params)
        types = values.get(TYPE_FACET) or []
        exact = params.get(SEARCH_MODE_PARAM) == "perfect"
        return {
            "page_name": BUILTIN_SEARCH_PAGE,
            "uri": None,
            "params": params,
            "page_title": f"検索結果（{text}）",
            "base_collection": application.search_collection(text, exact),
            "class_uri": types[0] if len(types) == 1 else None,
        }
    view = params.get("view")
    class_uri = params.get("class")
    source = params.get("from")
    saved = params.get("saved")
    if saved:
        store = application.saved_store
        if store is None:
            raise CollectionRequestError("コレクションを保存できない", "設定 saved_collections_dir を指定してください", 404)
        try:
            data = store.get(saved)
        except CollectionError as e:
            raise CollectionRequestError("保存したコレクションがない", str(e), 404)
        saved_class = data.get("class")
        page_name = application.collection_page(saved_class) if saved_class else BUILTIN_COLLECTION_PAGE
        return {
            "page_name": page_name,
            "uri": None,
            "params": params,
            "page_title": f"保存したコレクション: {data['name']}",
            "base_collection": Collection.from_uris(application.sparql_client, data["uris"]),
            "class_uri": saved_class,
        }
    if source:
        gadget = application.gadgetset.get(source)
        if gadget is None or not getattr(gadget, "collection_config", None):
            raise CollectionRequestError("コレクションにできる一覧がない", f"from={source} というガジェットはコレクションにできません", 404)
        target = params.get("uri")
        base = application.gadget_collection(source, target)
        if view:
            page = application.pages.pagedict.get(view)
            if page is None or page.get("type") != "collection":
                raise CollectionRequestError("コレクションのページがない", f"view={view} というコレクションのページは定義されていません", 404)
            page_name = view
        elif class_uri:
            page_name = application.collection_page(class_uri)
        else:
            page_name = BUILTIN_COLLECTION_PAGE
        list_title = gadget.collection_config.get("title") or application.gadget_title(source, gadget)
        return {
            "page_name": page_name,
            "uri": None,
            "params": params,
            "page_title": f"{get_localname(target)}: {list_title}" if target else list_title,
            "base_collection": base,
            "class_uri": expand_prefixed(class_uri, application.prefixes) if class_uri else gadget.collection_config.get("class"),
        }
    if view:
        page = application.pages.pagedict.get(view)
        if page is None or page.get("type") != "collection":
            raise CollectionRequestError("コレクションのページがない", f"view={view} というコレクションのページは定義されていません", 404)
        page_name = view
    elif class_uri:
        page_name = application.collection_page(class_uri)
    else:
        raise CollectionRequestError(
            "classパラメタがない",
            "/collection?class=<クラスURI> または /collection?view=<ページ名> と指定してください",
        )
    return {
        "page_name": page_name,
        "uri": class_uri,
        "params": params,
        "page_title": get_localname(expand_prefixed(class_uri, application.prefixes)) if class_uri else view,
        "base_collection": None,
        "class_uri": expand_prefixed(class_uri, application.prefixes) if class_uri else None,
    }


def render_saved_collections(items, message="", err=""):
    """保存したコレクションの一覧（まとめるフォームを兼ねる）"""
    rows = []
    for item in items:
        name = item["name"]
        merged = ""
        if item.get("merged_from"):
            merged = f'{escape(OPERATIONS.get(item.get("operation"), "").split("（")[0])}: ' + "、".join(escape(n) for n in item["merged_from"])
        source = item.get("source")
        origin = f'<a href="{escape(source)}">元のページ</a>' if source else merged
        rows.append(
            "<tr>"
            f'<td><input type="checkbox" name="names" value="{escape(name)}"></td>'
            f'<td><a href="/collection?{escape(urlencode([("saved", name)]))}">{escape(name)}</a></td>'
            f'<td class="num">{int(item.get("count", 0)):,}</td>'
            f'<td>{escape(get_localname(item["class"])) if item.get("class") else ""}</td>'
            f'<td>{escape(item.get("created", ""))}</td>'
            f'<td>{origin}</td>'
            # 要素が少なければ列に並べて比べる（2026.10.26）
            + (f'<td><a href="/compare?{escape(urlencode([("saved", name)]))}">比べる</a></td>'
               if 2 <= int(item.get("count", 0)) <= COMPARE_MAX else '<td></td>') +
            f'<td><button type="submit" formaction="/collections/delete" name="delete" value="{escape(name)}" '
            f'formnovalidate>消す</button></td>'
            "</tr>"
        )
    options = "".join(f'<option value="{k}">{escape(v)}</option>' for k, v in OPERATIONS.items())
    notice = ""
    if message:
        notice += f'<p class="saved-message">{escape(message)}</p>'
    if err:
        notice += f'<p class="saved-error">{escape(err)}</p>'
    if not rows:
        body = '<p>保存したコレクションはまだありません。コレクションのページの「名前を付けて保存」で保存できます。</p>'
    else:
        body = (
            '<form class="saved-collections" method="POST" action="/collections/merge">'
            '<table class="saved-table"><thead><tr><th></th><th>名前</th><th>件数</th><th>クラス</th><th>保存した日時</th>'
            '<th>元のページ／まとめ方</th><th></th><th></th></tr></thead><tbody>'
            + "".join(rows)
            + '</tbody></table>'
            '<div class="saved-merge">選んだコレクションを '
            f'<select name="operation">{options}</select> で '
            '<input type="text" name="name" required maxlength="60" placeholder="新しい名前"> '
            '<label><input type="checkbox" name="overwrite" value="1">上書き</label> '
            '<button type="submit">まとめて保存</button></div>'
            '</form>'
        )
    return f'<div class="container">{notice}{body}</div>'


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
        """検索結果（ラベルに検索語を含むリソース）をコレクションとして表示する（2026.10.19）。

        /search?q=語[&mode=perfect]   種類（rdf:type）のファセットと一覧のページ
        種類のファセットでクラスを1つ選ぶと（f._type=<クラス>）、そのクラスのコレクションのページ
        /collection?class=<クラス>&q=語 に移る（検索語・ほかの条件はそのまま）
        """
        application = current_app.extensions["application"]
        params = request_params(request.args, path=request.path)
        text = params.get(SEARCH_PARAM)
        if not text or not text.strip():
            return error('検索語がありません', '/search?q=xxxと指定してください')
        values, _ranges = facet_selection(params)
        types = values.get(TYPE_FACET) or []
        if len(types) == 1:
            items = [(k, v) for k, v in params.get(ARGS_PARAM, []) if k != f"f.{TYPE_FACET}" and k != "page"]
            return redirect("/collection?" + urlencode([("class", types[0])] + items))
        info = resolve_collection_request(application, request.path, request.args)
        return render_page(
            application,
            info["page_name"],
            None,
            params=info["params"],
            page_title=info["page_title"],
            category=info["page_name"],
            base_collection=info["base_collection"],
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
        /collection?saved=<名前>        名前を付けて保存したコレクション（2026.10.19）
        """
        application = current_app.extensions["application"]
        try:
            info = resolve_collection_request(application, request.path, request.args)
        except CollectionRequestError as e:
            return error(e.title, e.message), e.status
        return render_page(
            application,
            info["page_name"],
            uri=info["uri"],
            params=info["params"],
            page_title=info["page_title"],
            category=info["page_name"],
            base_collection=info["base_collection"],
        )

# 保存したコレクション（2026.10.19）
    @app.route("/collections", methods=["GET"])
    def saved_collections() -> Response:
        """保存したコレクションの一覧と、まとめる（和・積・差）・消すフォーム"""
        application = current_app.extensions["application"]
        store = application.saved_store
        if store is None:
            return error("コレクションを保存できない", "設定 saved_collections_dir を指定してください"), 404
        html = make_html(
            render_saved_collections(store.list(), request.args.get("msg", ""), request.args.get("err", "")),
            "保存したコレクション",
            navi=application.navi,
            libraries=[],
            category="_SavedCollections",
        )
        return Response(html, mimetype="text/html")

    @app.route("/collections/save", methods=["POST"])
    def save_collection() -> Response:
        """今のコレクション（form の source の URL）の要素に名前を付けて保存する"""
        application = current_app.extensions["application"]
        store = application.saved_store
        if store is None:
            return error("コレクションを保存できない", "設定 saved_collections_dir を指定してください"), 404
        source = request.form.get("source", "")
        name = request.form.get("name", "")
        parts = urlsplit(source)
        try:
            check_name(name)
            if parts.path not in ("/collection", "/search"):
                raise CollectionError(f"コレクションのページではありません: {source}")
            args = MultiDict(parse_qsl(parts.query, keep_blank_values=True))
            info = resolve_collection_request(application, parts.path, args)
            target = application.page_collection(info["page_name"], info["uri"], info["params"], info["base_collection"])
            if target is None:
                raise CollectionError("このページにはコレクションがありません")
            count = target.count()
            limit = int(application.saved_max)
            if count > limit:
                raise CollectionError(f"要素が {count:,} 件あり、保存できる上限（{limit:,} 件）を超えています。絞り込んでから保存してください")
            uris = target.get_uris(limit=limit)
            data = store.save(name, uris, source=source, class_uri=info.get("class_uri"),
                              overwrite=bool(request.form.get("overwrite")))
        except CollectionRequestError as e:
            return redirect("/collections?" + urlencode([("err", e.message)]))
        except CollectionError as e:
            return redirect("/collections?" + urlencode([("err", str(e))]))
        return redirect("/collections?" + urlencode([("msg", f"「{data['name']}」として {data['count']:,} 件を保存しました")]))

    @app.route("/collections/merge", methods=["POST"])
    def merge_collections() -> Response:
        """選んだ保存したコレクションを和・積・差でまとめて、新しい名前で保存する"""
        application = current_app.extensions["application"]
        store = application.saved_store
        if store is None:
            return error("コレクションを保存できない", "設定 saved_collections_dir を指定してください"), 404
        try:
            data = store.merge(request.form.getlist("names"), request.form.get("name", ""),
                               request.form.get("operation", "union"), overwrite=bool(request.form.get("overwrite")))
        except CollectionError as e:
            return redirect("/collections?" + urlencode([("err", str(e))]))
        return redirect("/collections?" + urlencode([("msg", f"「{data['name']}」（{data['count']:,} 件）を作りました")]))

    @app.route("/collections/delete", methods=["POST"])
    def delete_collection() -> Response:
        application = current_app.extensions["application"]
        store = application.saved_store
        name = request.form.get("delete", "")
        if store is None:
            return error("コレクションを保存できない", "設定 saved_collections_dir を指定してください"), 404
        try:
            store.delete(name)
        except CollectionError as e:
            return redirect("/collections?" + urlencode([("err", str(e))]))
        return redirect("/collections?" + urlencode([("msg", f"「{name}」を消しました")]))

# キーワードからトピックのコレクション（2026.10.26）
    def build_topic(application, args):
        cfg = application.topic_config
        keyword = (args.get("q") or "").strip()
        if not keyword:
            raise CollectionError("キーワードがありません（/topic?q=xxx）")
        try:
            # 外のコマンドが作る（判例: hanrei の src/topic_keyword.py --json）。&builder=sparql なら SPARQL の版（比べるため）
            if cfg.get("builder") == "command" and not (args.get("builder") == "sparql" and cfg.get("link_properties")):
                builder = CommandTopicBuilder(cfg)
            else:                                    # SPARQL だけで作る
                method = cfg.get("text_search") or application.text_search_method(cfg["text_properties"][0])
                builder = TopicBuilder(application.sparql_client, cfg, text_method=method)
            return keyword, builder.build(keyword, override_from_args(args))
        except ValueError as e:
            raise CollectionError(str(e)) from e

    @app.route("/topic", methods=["GET"])
    def topic() -> Response:
        """キーワードからトピックの案（語・主なリンク・補助リンク）と要素（確かさ 強・中・弱）を作る。
        /topic?q=語            案を作る
        /topic?q=語&edit=1&r.<リンク先>=main|aux|   画面でリンクの役割を選び直したもの
        """
        application = current_app.extensions["application"]
        if not application.topic_config:
            return error("トピックの設定がない", "設定ファイルに topic: を書いてください"), 404
        try:
            keyword, res = build_topic(application, request.args)
        except CollectionError as e:
            return error("トピックを作れない", str(e)), 400
        body = render_topic(res, application.topic_config, keyword, override_from_args(request.args) is not None,
                            request.full_path, application.saved_store is not None)
        html = make_html(body, f"トピック: {keyword}", navi=application.navi, libraries=[], category="_Topic")
        return Response(html, mimetype="text/html")

    @app.route("/topic/save", methods=["POST"])
    def save_topic() -> Response:
        """トピックの要素（強・中。弱も選べる）を名前を付けて保存したコレクションにする"""
        application = current_app.extensions["application"]
        store = application.saved_store
        if store is None or not application.topic_config:
            return error("コレクションを保存できない", "設定 saved_collections_dir と topic を書いてください"), 404
        source = request.form.get("source", "")
        parts = urlsplit(source)
        try:
            name = check_name(request.form.get("name", ""))
            if parts.path != "/topic":
                raise CollectionError(f"トピックのページではありません: {source}")
            args = MultiDict(parse_qsl(parts.query, keep_blank_values=True))
            _keyword, res = build_topic(application, args)
            levels = {"強", "中", "弱"} if request.form.get("weak") else {"強", "中"}
            uris = [m[0] for m in res.members if m[2] in levels]
            if len(uris) > int(application.saved_max):
                raise CollectionError(f"要素が {len(uris):,} 件あり、保存できる上限（{int(application.saved_max):,} 件）を超えています")
            data = store.save(name, uris, source=source, class_uri=application.topic_config.get("item_class") and
                              expand_prefixed(application.topic_config["item_class"], application.prefixes),
                              overwrite=bool(request.form.get("overwrite")))
        except CollectionError as e:
            return redirect("/collections?" + urlencode([("err", str(e))]))
        return redirect("/collection?" + urlencode([("saved", data["name"])]))

# 少数のリソースを列に並べて比べる（kgraphnavi/compare.py。2026.10.26）
    @app.route("/compare", methods=["GET"])
    def compare() -> Response:
        """/compare?uri=A&uri=B[&uri=C…][&view=比べ方]、/compare?saved=名前、/compare?from=ガジェット&uri=X"""
        application = current_app.extensions["application"]
        try:
            uris = items_from_args(application, request.args)
            view = choose_view(application, uris, request.args.get("view"))
        except (ValueError, CollectionError) as e:
            return error("比べられない", str(e)), 400
        limit = view["max"] if view else COMPARE_MAX
        if len(uris) < 2:
            return error("比べられない", "2つ以上のリソースを指定してください（/compare?uri=A&uri=B）"), 400
        if len(uris) > limit:
            return error("比べられない", f"{len(uris):,} 件あります。比べられるのは {limit} 件までです"), 400
        uris = sort_items(application, uris, view)
        body = render_compare(application, uris, view, request.args)
        title = "比べる: " + (view.get("title") or view["name"] if view else "プロパティごと")
        html = make_html(body, title, navi=application.navi, libraries=["jsgrid", "chartjs"], category="_Compare")
        return Response(html, mimetype="text/html")

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
        # /data/<名前>/<path>: 設定の data_dirs にその名前があれば、そのフォルダから配信する
        head, sep, rest = filename.partition("/")
        if sep and head in getattr(application, "data_dirs", {}):
            return send_from_directory(application.data_dirs[head], rest)
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

    # 設定の static_dirs のフォルダを /<名前>/<path> で配信する
    # （判決HTML /data/<年>/<ID>_hanrei.html が ../../css/hanrei.css で参照するCSS → /css/hanrei.css）
    @app.route("/<name>/<path:filename>")
    def getstatic(name: str, filename: str):
        application = current_app.extensions["application"]
        folder = getattr(application, "static_dirs", {}).get(name)
        if folder is None:
            return (error("ページが見つからない", f"/{name}/{filename}"), 404)
        return send_from_directory(folder, filename)

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