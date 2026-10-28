# KGraphNavi 開発者ガイド

KGraphNavi のソースコードを読み、直し、機能を加えるための文書です。設定ファイルの書き方は [ユーザーズガイド](user-guide.md) と [設定ファイルリファレンス](config.md) を参照してください。

## 1. 全体の構成

KGraphNavi は Flask の Web アプリケーションです。設定ファイルからページとガジェットの定義を読み込み、リクエストごとに SPARQL を実行して HTML を作ります。

```text
            設定ファイル（YAML）
                   │ load_config / setconfig（検証）
                   ▼
  ┌─────────── Application ────────────┐
  │  Pages（ページ定義）                 │
  │  gadgetset {名前: Gadget}            │
  │  SPARQL（エンドポイントのクライアント）│
  └──────────────────────────────────┘
        ▲                         │
  views.py（ルーティング）           │ make_page → make_gadget
  /resource /collection /graph ...  │   Gadget.extract（get） → SPARQL / Collection
                                     │   Gadget.show（show）   → render_utils / facets
                                     ▼
                         makehtml.make_html → templates/layout.html
```

- **取得と表示を分ける**: ガジェットの `get` は SPARQL の結果（`results.bindings` の形のリスト）などのデータを返し、`show` がそれを HTML にします。
- **コレクションは SPARQL の条件として持つ**: コレクションは要素の URI のリストではなく、`?uri` を束縛するグラフパターンの式木です。絞り込みも式木に条件を加えるだけで、ガジェットには副問い合わせとして埋め込みます。
- **値は検証してから SPARQL に埋め込む**: URL のパラメータや設定の値は `terms.py` で IRI・リテラル・数値・プロパティパスとして検証し、SPARQL の項にしてから使います。

## 2. ソースコード

```text
kgraphnavi/
├── __main__.py      python -m kgraphnavi
├── app.py           設定の読み込み・検証、Application / Pages / Gadget、起動（main）
├── views.py         Flask のルーティング（URL → ページ）
├── sparql.py        SPARQL クライアント（接頭辞、$変数の置き換え、検索）
├── collection.py    コレクション（式木）と、その SPARQL の生成
├── facets.py        ファセットの URL パラメータ、絞り込みの画面部品、ページ送り、分布
├── terms.py         値の検証と SPARQL の項への変換
├── render_utils.py  表のセル、横・縦の表、行のまとめ（group_by）、階層（tree）、グラフ
├── makehtml.py      ページ全体の HTML、jsGrid の表の JavaScript
├── graph.py         ネットワーク図（show: type: graph）。行→ノード・辺、射影、指標、配置、HTML
├── saved.py         名前を付けて保存したコレクション（JSON ファイル）
├── compare.py       並べて比べる（/compare）
├── topic.py         キーワードからトピックのコレクション（/topic）
├── errors.py        例外クラス
├── misc.py          補助関数
└── templates/       HTML テンプレート、CSS、JavaScript（js/busy.js: 実行中の表示、js/graph.js: ネットワーク図）
tests/               pytest のテスト（SPARQL エンドポイントには接続しない）
config/              設定ファイル（dbpedia.yaml はサンプル）
docs/                文書
```

### 2.1 `app.py`

| 名前 | 役割 |
| --- | --- |
| `main()` | コマンドラインの解析、ログの設定、`build_application()`、Flask の起動 |
| `create_app_from_env()` | 環境変数 `KGRAPHNAVI_*` から Flask アプリを作る（WSGI サーバ用） |
| `build_application()` | `load_config()` の結果と引数から `SPARQL` と `Application` を作る（引数が設定より優先） |
| `load_config()` | 設定ファイルを探し（`resolve_config_path`）、`local.yaml` を後ろに足して `setconfig()` に渡す |
| `setconfig()` | `import` の展開（循環の検出）、項目の検証、`Pages` と `Gadget` の生成、組み込みのコレクションのページの追加、参照の検証 |
| `Pages` | ページ定義の登録と検証（`set_page`）、`rdf:type` → ページ（`rdftype2page`）、接頭辞の展開 |
| `Gadget` | `get`（`EXTRACTORS` の `extract_*`）と `show`（`show()`）。`$collection` の接続、行数の制限（`get.max_rows` が `max_rows` より優先）、ファセットの集計。`with_variant()` で `variants` の選んだものを重ねたガジェットと切り替えのリンクを作る |
| `parse_variants()` | ガジェットの `variants` の検証（`setconfig()` から）。`show.type: graph` の設定（`variants` で重ねたものも）と `get.max_rows` もここで検証する |
| `Application` | ページの組み立て（`make_page` / `make_gadgets` / `make_page_tabs` / `make_gadget`）、コレクションの作成と絞り込み（`get_collection` / `apply_collection_filters` / `gadget_collection`）、クラス → コレクションのページ（`collection_page`）、候補の検索の方法の判定（`text_search_method`）、ネットワーク図の保存の情報（`graph_save_info`） |

### 2.2 `views.py`

| URL | 関数 | 処理 |
| --- | --- | --- |
| `/` | `root` | `index.html` にサンプルを渡す |
| `/search` | `search` | `SPARQL.retrieve()` でラベルを検索し、`retrieval_result.html` |
| `/resource` | `get_resource` | `rdf:type` を取り、`priority` で1つ選び、`rdftype2page` のページを `render_page` |
| `/collection` | `collection` | `from=`（ガジェットの一覧）、`view=`（ページ名）、`class=`（`collection_page`）の順にページを決めて `render_page` |
| `/graph` | `graph` | `type: graph` の最初のページ |
| `/collections` | `saved_collections` | 保存したコレクションの一覧 |
| `POST /collections/save` | `save_collection` | `source` の URL と同じコレクションを作り、要素を保存する |
| `POST /collections/save_uris` | `save_selected_uris` | ネットワーク図で選んだ URI（`uris`）をそのまま保存し、`/collection?saved=` へ |
| `POST /collections/merge` / `delete` | | 和・積・差でまとめる、消す |
| `/compare` | `compare` | 並べて比べる（`compare.py`） |
| `/topic` | `topic` | キーワードからトピック（`topic.py`） |
| `/data/<path>` | `getfile` | `data_dirs` / `data_dir` から `send_from_directory` |
| `/<名前>/<path>` | `getstatic` | `static_dirs` から `send_from_directory` |

`render_page()` は `Application.make_page()` の HTML 片をつなげ、`makehtml.make_html()` でページ全体にします。`KGraphError` は 400、`SparqlError` は 500 のエラー画面になります。ただし、ガジェットの問い合わせの失敗（`SparqlError`）は `make_gadget()` で受け止め、そのガジェットの中に説明（`user_message()`）と詳しい情報を出して、ページの他の部分は表示します。

### 2.3 `sparql.py`

`SPARQL` は SPARQLWrapper の薄いラッパーです。

- `exsparql(query)`: 接頭辞（`STANDARD_PREFIXES` と設定の `prefixes`）を付けて実行し、`bindings` を返す。失敗は `SparqlError`
  - 問い合わせごとに `SPARQLWrapper` を作る（Flask は複数のリクエストを並行して処理するため）
  - `POST_THRESHOLD`（2000 バイト）を超える問い合わせは POST で送る（URI を多く並べた問い合わせが GET の URL の長さで切れ、構文エラーになるため）
  - エラーは `describe_error()` で状態コード（`SPARQLWrapper` の例外の種類 `QueryBadFormed` などからも補う）とエンドポイントのエラーの1行目を取り出し、`user_message()` で利用者向けの説明にする。問い合わせの誤り（`is_query_error()`: 400・414、Virtuoso の `SP0xx` など）はやり直さず、再読み込みも勧めない。混雑・内部エラー・接続の失敗（`is_transient()`）は1回やり直し、再読み込みを勧める
- `query(sparql, params)`: `$名前` を `param_term()` で検証した項に置き換えてから実行する（`uri` / `class` / `class_uri` は IRI、`predicate` はプロパティパス、それ以外はリテラル）。SPARQL に現れない名前は無視する
- `get_target` / `rdfobject` / `get_count` / `get_list`: よく使う問い合わせ
- `get_superclasses_among(class, candidates)`: コレクションのページを上位クラスで探すときに使う
- `retrieve(text, mode)`: `/search` のラベル検索

### 2.4 `collection.py`

```text
Collection（抽象）
├── ClassCollection      ?uri a <C> .
├── QueryCollection      ?uri を返す SELECT（ページの query、ガジェットの一覧）
├── UriCollection        VALUES ?uri { … }
├── FilteredCollection   条件（ValueCondition / RangeCondition）を加えたもの
├── UnionCollection / IntersectCollection / MinusCollection
```

- いずれもイミュータブルで遅延評価です。`filter()` / `filter_range()` / `without()` は新しいコレクションを返し、`count()` / `get_facets()` / `get_range()` / `get_histogram()` / `get_uris()` が呼ばれたときに SPARQL を実行します（`count()` は結果を覚えます）。
- `to_subquery("?entity", limit, offset)` は、要素を `?entity` だけに出す副問い合わせを返します。ガジェットの `$collection` はこれに置き換わります。`limit` / `offset` は `page_size` のページ送りで使い、`ORDER BY ?uri` を付けます。
- 条件には名前（ファセット名）が付き、`without({名前})` でその条件だけを外せます。ファセットの候補は、自分の条件を外したコレクションで数えます。
- `facet_query()` は候補の検索に `CONTAINS` または Virtuoso の `bif:contains` を使います。

### 2.5 `facets.py`

- `request_params(args, path)`: Flask の `request.args` から、ガジェットに渡す `params` を作る。`f.<名前>` は `params["_facets"]`（`values` / `ranges` / `options`）にまとめ、元の引数（`_args`）とパス（`_path`）も残す
- `facet_selection()` / `facet_option()` / `match_mode()` / `page_number()`: `params` の解釈
- `make_url()` / `hidden_inputs()`: 条件を外す・加える URL、フォームで条件を引き継ぐ hidden input
- `render_value_facet()` / `render_range_facet()` / `render_conditions()` / `render_pager()`: 画面部品
- `plan_bins()` / `build_histogram()` / `render_histogram()`: 範囲のファセットの分布

### 2.6 `terms.py`

`iri_term()`（`<…>` または接頭辞付きの名前）、`literal_term()`、`typed_term()`、`number_term()`、`predicate_term()`（プロパティパス）などで、値を検証して SPARQL の項にします。検証できない値は `ValueTermError`（`KGraphError` の一種なので 400）になります。新しく SPARQL に値を埋め込むときは、文字列を直接つながず、必ずこれらを通してください。

### 2.7 `render_utils.py` と `makehtml.py`

表は次の順で作ります。

```text
SPARQL の行（bindings）
  → get_record_cells()       列（columns）ごとのセル {value, type, href}
  → group_rows()             group_by: 同じ値の行をまとめ、複数の値は {type: multi}
  → arrange_tree()           tree: 親子の順に並べ、行に _kgtree {id, depth, anc, hasChildren}
  → makehtml.make_table()    jsGrid のデータと列の定義（JavaScript）
  → kgRenderCell()           ブラウザでセルを描画（link / directlink / image / multi）
```

- セルのリンク先は `get_item_data()` で決めます（列の `collection` → `link` → `href` → `type` の順）。
- `show_vertical_table()` は最初の1行を「属性・値」の表にします。
- `show_chart()` は Chart.js の設定を JSON にして埋め込みます（グラフごとに固有の canvas）。
- `makehtml.make_html()` は `templates/layout.html` に本文と、使うライブラリ（jsGrid、Chart.js、Cytoscape.js）を入れます。

### 2.8 `graph.py` と `templates/js/graph.js`（ネットワーク図）

`make_gadget()` は、`show.type: graph` のガジェットの取得結果（行）を `build_graph()` でグラフにしてから `Gadget.show()`（→ `render_graph()`）に渡します。

```text
SPARQL の行
  → collect_graph()          edges の from/to の値をノード、行を辺に（同じ辺は重み +1）。ノードに変数名 var
  → in_collection: check のノードがコレクションの要素かを collection_members()（FILTER(?uri IN (…)) を 300 件ずつ）
  → outside: hide なら外のノードを除く
  → min_degree（URL graph.min）で、少ない数としかつながらないノードを除く
  → project_graph()          射影: keep の側どうしを、共有する via の数を重みとして結ぶ（URL graph.w が下限）
  → 孤立したノードを除く → graph_metrics()（PageRank・連結成分。ここで計算するので、次で省くノードも含む）
  → max_nodes で次数（射影では重みの合計）の大きいものから残す
  → 大きさ（size）、node_filter_url()（nodes.collection）、配置の位置（timeline_positions / bipartite_positions）
  → render_graph()           graph_payload() の JSON を <script type="application/json"> に入れ、kgDrawGraph(id) を呼ぶ
```

- 年で並べる・2段に並べる配置はサーバで位置を計算し（`payload.positions`）、ブラウザでは Cytoscape.js の `preset` で置きます。力学モデル・円・格子は Cytoscape.js の配置です。
- `graph.js` は、右の欄、配置の切り替え、範囲選択（`boxSelectionEnabled`、「範囲を選ぶ」では `userPanningEnabled(false)`）、選んだノードの保存のフォーム（`/collections/save_uris`）、書き出し（PNG は `cy.png()`、SVG・CSV・GraphML は自前で作る）を受け持ちます。
- Cytoscape.js は `makehtml.LIBRARIES["cytoscape"]` で `cdn.jsdelivr.net/npm/cytoscape@3` から読み込みます。

### 2.9 例外

| 例外 | 場面 |
| --- | --- |
| `KGraphError` | すべての基底（画面では 400） |
| `ConfigError` | 設定の誤り（起動時、または表示時の列の `type`） |
| `SparqlError` | SPARQL の実行の失敗（画面では 500） |
| `GadgetError` / `ShowError` | ガジェットの取得・表示の誤り |
| `CollectionError` | コレクションの定義の誤り（`query` に `PREFIX`、`?uri` がない、未対応の `datatype` など） |
| `ValueTermError` | 値の検証の失敗 |

## 3. リクエストの流れ

### 3.1 `/resource?uri=…`

1. `sparql.get_target(uri, "a")` で `rdf:type` を取る
2. `get_highest_priority_item()` で `priority` の最も前のクラスを選び、`Pages.rdftype2page()` でページ名にする（なければ `type: '*'`）
3. `Application.make_page()`: ページに `collection: instances` があれば `ClassCollection(uri)` を作り、URL の条件で絞り込む
4. `gadget` / `tabs` / `sidebar` の各ガジェットで `make_gadget()`
   - `Gadget.extract()`: `get.type` の `extract_*` を呼ぶ。`sparql` では `$collection` の接続 → `limit_rows()` → `SPARQL.query()`（`$uri` などの置き換え）
   - `Gadget.show()`: `show.type` の表示関数
   - 見出し、`collection` のボタン、行数の上限の注意、ページ送りを付ける

### 3.2 `/collection?…`

1. `request_params()` で `params` を作る
2. ページを決める: `from=` なら `gadget_collection()` でガジェットの SPARQL からコレクションを作り、`view=` / `class=` / 組み込みのページの順で表示するページを選ぶ。`view=` ならそのページ。`class=` なら `collection_page()`（`class:` のページ → 上位クラスのページ → `class` も `query` もないページ → 組み込みのページ。結果は覚える）
3. `make_page()`: `get_collection()`（`query` → `class` → `uri`）でコレクションを作り、`apply_collection_filters()` で `f.…` の条件を加える。先頭に件数と現在の条件（`make_collection_header()`）
4. ファセットのガジェットは `extract_facet()` で、自分の条件を外したコレクションの候補・範囲・分布を求める

## 4. 機能を加える

### 4.1 新しい取得方法（`get.type`）

1. `Gadget` に `extract_<名前>(self, uri, application, params=None, collection=None)` を作る。表に出すなら SPARQL の `bindings` と同じ形（`[{変数: {"type": …, "value": …}}]`）を返す
2. `Gadget.EXTRACTORS` に `"<名前>": "extract_<名前>"` を加える（設定の検証の `SUPPORTED_GET_TYPES` にも入る）
3. テストと [設定ファイルリファレンス](config.md#5-取得get) を更新する

### 4.2 新しい表示方法（`show.type`）

1. `render_utils.py` に `show_<名前>(content, show_method)` を作り、HTML の文字列を返す
2. `Gadget.SHOWERS` に加え、`Gadget.show()` で必要な引数を渡す（`chart` の分岐を参照）
3. 外部のライブラリが要るなら `makehtml.LIBRARIES` に加える
4. 表示の前に URL のパラメータやコレクションを使う処理が要るなら、`graph` のように `make_gadget()` で取得結果を変換してから渡す。設定の検証は `setconfig()` のガジェットの処理に加える（`SUPPORTED_SHOW_TYPES` にも加える）

### 4.3 新しい設定項目

`setconfig()` の `APPLICATION_KEYS` / `PAGE_KEYS` / `GADGET_KEYS` に加えないと、未知の項目としてエラーになります。値の検証もここで行い、[リファレンス](config.md) に書いてください。

### 4.4 新しいファセットの種類

`facets.py` に URL パラメータの解釈と画面部品を、`collection.py` に条件（`Condition` の派生クラス）と集計の SPARQL を、`Application.apply_collection_filters()` に条件の適用を加えます。

## 5. テスト

```bash
pip install -e ".[test]"
pytest
```

| ファイル | 対象 |
| --- | --- |
| `test_kgraphnavi.py` | コレクションの作成と絞り込み、ファセットのガジェット、ページ・タブのガジェットへのコレクションの受け渡し、`$collection` の接続、テンプレート |
| `test_pages.py` | ページの選び方（`/resource` / `/collection` / `/graph`）、接頭辞の展開 |
| `test_collection.py` | コレクションの SPARQL の生成、絞り込み、範囲、集合演算、値の検証 |
| `test_facets.py` | ファセットの URL パラメータ・画面部品・分布・候補の検索、ページ送り、行数の制限、列のリンク、`group_by` |
| `test_terms.py` | 値の検証 |
| `test_tree.py` | 階層表示（`tree`） |
| `test_graph.py` | ネットワーク図（ノード・辺、コレクション外、min_degree、射影、PageRank・連結成分、配置、HTML・JSON、variants、保存の情報） |
| `test_saved.py` | 名前を付けて保存したコレクション（保存・読み込み・まとめる、図で選んだ URI の保存） |
| `test_sparql_errors.py` | SPARQL のエラーの説明・やり直し、長い問い合わせの POST |
| `test_compare.py` / `test_topic.py` / `test_search.py` / `test_local_config.py` | 並べて比べる、トピック、検索、手元の設定 |

テストは、SPARQL の問い合わせを記録して決まった結果を返す偽のクライアントを使い、エンドポイントには接続しません。新しい機能には、生成される SPARQL と HTML を確かめるテストを付けてください。

## 6. デバッグ

- `kgraphnavi -d INFO …` で、ガジェットの最終的な SPARQL（`extract_sparql: final query=`）がログに出ます。`-d DEBUG` では結果やセルの内容も出ます。
- `--dev` で Flask のデバッガと自動再読み込みが有効になります。
- 画面の表示がおかしいときは、(1) ページの選択（`rdf:type` と `priority`）、(2) ログの SPARQL をエンドポイントで直接実行した結果、(3) 列の定義（`columns` の `id` と変数名）の順に確かめます。

## 7. 既知の問題

| 問題 | 場所 |
| --- | --- |
| ガジェットのパス指定 `Gadget(プロパティ)` が、ページの検証（`validate_pages`）で未定義のガジェットとして拒否される。`make_gadget()` には `move_focus()` で対応する処理がある | `app.py` `setconfig.validate_pages` |
| `setconfig()` 内の `validate_gadget_config()` は定義されているが呼ばれていない（`show.type: graph` と `get.max_rows` の検証は、呼ばれる箇所に移した） | `app.py` |
| ネットワーク図の書き出し（SVG）は Cytoscape.js の描画をそのまま写したものではなく、円・直線（または弧）・名前で描き直したもの。矢印の位置などは画面と少し違う | `templates/js/graph.js` |
| `get.values` に未知の関数を書くと、例外にならず `error()`（エラー画面の HTML を返す関数）を呼ぶだけで処理が続く | `app.py` `Gadget._apply_values` |
