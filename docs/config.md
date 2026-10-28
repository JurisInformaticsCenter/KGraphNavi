# 設定ファイルリファレンス（`config/*.yaml`）

KGraphNavi の設定ファイルに書けるすべての項目の一覧です。考え方と書き方の手順は [ユーザーズガイド](user-guide.md)、コレクションとファセットの詳しい説明は [コレクションとファセット](collection.md) を参照してください。例は [`config/dbpedia.yaml`](../config/dbpedia.yaml) から取っています。

## 目次

1. [全体の構造](#1-全体の構造)
2. [アプリケーションの設定](#2-アプリケーションの設定)
3. [ページ（`def: page`）](#3-ページdef-page)
4. [ガジェット（`def: gadget`）](#4-ガジェットdef-gadget)
5. [取得（`get`）](#5-取得get)
6. [表示（`show`）](#6-表示show)
7. [表の列（`columns`）](#7-表の列columns)
8. [SPARQL の書き方](#8-sparql-の書き方)
9. [設定ファイルの読み込み](#9-設定ファイルの読み込み)
10. [設定の検証](#10-設定の検証)
11. [現在使えない機能](#11-現在使えない機能)

---

## 1. 全体の構造

設定ファイルは YAML のリスト（シーケンス）です。リストの各要素は辞書で、次の3種類があります。

| 要素 | 見分け方 | 内容 |
| --- | --- | --- |
| アプリケーションの設定 | `def` がない | タイトル、エンドポイント、接頭辞、サンプルなど |
| ページ | `def: page` | URL に対応する画面と、そこに置くガジェット |
| ガジェット | `def: gadget` | 画面の部品（データの取得 `get` と表示 `show`） |

```yaml
-   title: DBpedia
-   sparql_endpoint: "https://dbpedia.org/sparql"
-   prefixes:
        dbo: "http://dbpedia.org/ontology/"
-   def: page
    name: Mountain
    type: dbo:Mountain
    gadget:
        - MountainProfile
-   def: gadget
    name: MountainProfile
    get:
        type: sparql
        src: |
            SELECT ?elevation WHERE { $uri dbo:elevation ?elevation }
    show:
        type: vtable
```

アプリケーションの設定は、1つの要素にまとめて書いても、項目ごとに別の要素にしても構いません。同じ項目を2回書くと、後のものが使われます（`local.yaml` での上書きはこの性質を使います）。

---

## 2. アプリケーションの設定

| 項目 | 既定値 | 内容 |
| --- | --- | --- |
| `title` | `KG frontend` | アプリケーションの名前。トップ画面の見出しと、画面上端のナビゲーションに出る |
| `describe` | （空） | トップ画面の説明文 |
| `sparql_endpoint` | `http://localhost:8890/sparql` | SPARQL エンドポイントの URL。コマンドラインの `-e`（または環境変数 `KGRAPHNAVI_ENDPOINT`）が優先 |
| `prefixes` | （なし） | 接頭辞の辞書 `{接頭辞: 名前空間IRI}`。すべての SPARQL の先頭に `PREFIX` として付き、ページの `type` / `class` の接頭辞付きの名前の展開にも使う。`rdf` `rdfs` `xsd` `owl` は書かなくても使える |
| `label` | `rdfs:label` | リソースの名前を表すプロパティ。検索（`/search`）と組み込みのコレクションのページで使う。コマンドラインの `-l` が優先 |
| `label_lang` | （なし） | 組み込みのコレクションのページで優先するラベルの言語（例 `en`）。その言語のラベルがなければ他のラベルを使う |
| `priority` | （なし） | リソースに `rdf:type` が複数あるときに、ページを選ぶクラスの優先順のリスト。**完全な IRI で書く**（接頭辞は展開しない）。リストにないクラスはリストのクラスより後になる |
| `sample` | （なし） | トップ画面のサンプル（下記） |
| `text_search` | `auto` | ファセットの候補の検索の方法: `auto` / `bif` / `contains`（[コレクションとファセット](collection.md#検索の方法text_search)） |
| `max_rows` | `5000` | 1つのガジェットで取得する行数の上限。超えたときは、その旨を表示する |
| `data_dir` | （なし） | `/data/<path>` で配信するフォルダ。`~` と、設定ファイルのフォルダからの相対パスが使える。コマンドラインの `--data-dir`（環境変数 `KGRAPHNAVI_DATA_DIR`）が優先 |
| `data_dirs` | （なし） | `/data/<名前>/<path>` で配信するフォルダの辞書 `{名前: フォルダ}`。`data_dir` とは別に、名前ごとにフォルダを置ける |
| `saved_collections_dir` | 設定ファイルのフォルダの `saved_collections` | 名前を付けて保存したコレクションのフォルダ（collection.md） |
| `saved_collection_max` | 10000 | 保存できるコレクションの要素の数の上限 |
| `static_dirs` | （なし） | `/<名前>/<path>` で配信するフォルダの辞書 `{名前: フォルダ}`。`/data/` の外を相対パスで参照するファイル（判決HTMLの `../../css/hanrei.css` など）に使う。`templates`・`data`・`resource`・`collection`・`search`・`graph` は名前に使えない |
| `frontend_base_url` | `/` | 画面上端のアプリケーション名のリンク先 |
| `rdfstore` | （なし） | RDF ストアの種類（例 `virtuoso`）。記録用で、現在の動作には影響しない |

### `sample`（トップ画面のサンプル）

```yaml
-   sample:
        search:                 # 検索語（/search へのリンク）
            - Matterhorn
        resource:               # リソースのページ: 「IRI,表示名」（表示名は省略可）
            - http://dbpedia.org/resource/Matterhorn,マッターホルン（山）
        collection:             # コレクション: 「クラスのIRI,表示名」または「ページ名,表示名」
            - AlpsMountains,アルプスの山
            - http://dbpedia.org/ontology/Mountain,山
```

`collection` にコレクションのページの名前を書くと `/collection?view=<ページ名>`、それ以外は `/collection?class=<クラス>` へのリンクになります。

---

## 3. ページ（`def: page`）

ページは、URL に対応する画面です。`type` でページの種類を決めます。

| `type` | 画面 | 選ばれ方 |
| --- | --- | --- |
| RDF クラス（IRI または接頭辞付きの名前） | リソースのページ `/resource?uri=…` | リソースの `rdf:type`（`priority` で1つに決める）と一致するページ |
| `'*'` | リソースのページ | 一致するページがないとき（最初に定義したもの） |
| `collection` | コレクションのページ `/collection?…` | [コレクションとファセット](collection.md#ページの選び方) を参照 |
| `graph` | 知識グラフ全体のページ `/graph` | 最初に定義したもの |

### 項目

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `def` | ○ | `page` |
| `name` | ○ | ページの名前（`_` で始まる名前は組み込み用なので使えない）。画面のタイトルにも出る |
| `type` | ○ | ページの種類（上の表） |
| `gadget` | △ | 上から順に表示するガジェットの名前のリスト。`tabs` とどちらかが必要 |
| `tabs` | △ | タブのリスト。各タブは `{label: タブの名前, gadget: [ガジェット名, …], lazy: true/false}`。選んだタブは URL の `tab=<番号>`（0始まり）に残る。`lazy: true` のタブは選ばれたときだけ計算し、ボタンはページを読み直すリンクになる（順位表など重いもの。2026.10.20） |
| `sidebar` | | 左の列に置くガジェットのリスト（ファセットなど）。`gadget` / `tabs` の横に表示し、タブを切り替えても共通 |
| `query` | | `type: collection` のページで、コレクションを定義する SPARQL（`?uri` を返す SELECT。`PREFIX` は書かない） |
| `class` | | `type: collection` のページが対象とする RDF クラス（文字列またはリスト） |
| `collection` | | `instances` だけが指定できる。リソースのページで、表示しているリソースをクラスとみなし、そのインスタンスをコレクションにする |

```yaml
-   def: page
    name: Mountain
    type: dbo:Mountain
    tabs:
        - label: 概要
          gadget: [MountainProfile, Abstract]
        - label: 同じ山脈の山
          gadget: [SameRange]
```

コレクションを持つページ（`type: collection` のページ、`collection: instances` のページ）では、ページのすべてのガジェットにコレクションが渡されます。ガジェットの SPARQL に `$collection` がなければ最初の `WHERE {` の直後にコレクションが入るので、コレクションを使わないガジェット（`$uri ?p ?o` を表示するものなど）は置かないでください。また、ガジェットとファセットの両方を `gadget` に並べると、ファセットは自動的に左の列に置かれます。

---

## 4. ガジェット（`def: gadget`）

| 項目 | 必須 | 既定値 | 内容 |
| --- | --- | --- | --- |
| `def` | ○ | | `gadget` |
| `name` | ○ | | ガジェットの名前（`_` で始まる名前は使えない） |
| `get` | ○ | | データの取得方法（[5](#5-取得get)） |
| `show` | ○ | | 表示方法（[6](#6-表示show)） |
| `title` | | ガジェット名（ファセットは `get.label`） | 見出し |
| `height` | | `500` | 表の高さ（px）。ファセットでは候補のリストの最大の高さ |
| `collection` | | | 一覧をコレクションとして開くボタン（下記）。`get.type: sparql` のときだけ使える |

### `collection`（一覧をコレクションとして開くボタン）

リソースのページのガジェットに書くと、見出しの横にボタンが出ます。

| 項目 | 内容 |
| --- | --- |
| `var` | コレクションの要素にする列（SPARQL の変数名）。ボタンで `/collection?from=<ガジェット名>&uri=<表示中のリソース>` を開き、ガジェットの SPARQL を副問い合わせとして使って、その列の IRI を要素とするコレクションを表示する |
| `facet` | `var` の代わりに書く。表示中のリソースをそのファセットの値として絞り込んだコレクション（`/collection?class=…&f.<ファセット>=<表示中のリソース>`）へ移る |
| `class` | 開いたコレクションを表示するページを、このクラスで選ぶ |
| `view` | 開いたコレクションを表示するページの名前（`class` の代わり） |
| `title` | コレクションのページの見出し（既定はガジェットの見出し） |
| `label` | ボタンの文字（既定「コレクションとして表示」） |

```yaml
-   def: gadget
    name: SameRange
    collection:
        var: entity
        class: dbo:Mountain
        label: コレクションとして表示（絞り込み・統計）
    get: …
```

`class` も `view` もなければ、組み込みのページ（名前と IRI の一覧）で表示します。

---

## 5. 取得（`get`）

`get.type` で取得方法を選びます。

| `get.type` | 内容 |
| --- | --- |
| `sparql` | SPARQL の SELECT を実行する |
| `facet` | コレクションの絞り込みの候補を集計する（`show.type: facet` と組み合わせる） |
| `list` | 設定ファイルに書いた固定の表 |
| `dbpedia` | リソースの、あるプロパティの値の DBpedia のページへのリンク |

### `sparql`

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `src` | ○ | SPARQL の SELECT（[8](#8-sparql-の書き方)） |
| `page_size` | | コレクションの要素をこの件数ずつに区切ってページ送りを付ける（コレクションのページだけ。表自身のページ送りは使わない） |
| `max_rows` | | このガジェットで取得する行数の上限（既定はアプリケーションの `max_rows`）。ネットワーク図の辺など、多くの行を取るガジェットに使う |
| `values` | | 取得した最初の行に値を加える `{変数名: "count(プロパティ)" または "list(プロパティ)"}`。表示中のリソースからそのプロパティの値の数・値のリストを求める |

`src` の末尾に `LIMIT` / `OFFSET` / `VALUES` がなければ、`max_rows` + 1 行に制限して実行します。

### `facet`

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `name` | ○ | ファセットの名前（URL パラメータ `f.<name>`） |
| `predicate` | ○ | 値を取るプロパティ、またはプロパティパス |
| `label` | | 見出し（既定は `name`） |
| `kind` | | `value`（既定。値の選択）または `range`（範囲） |

値の選択（`kind: value`）

| 項目 | 既定値 | 内容 |
| --- | --- | --- |
| `value_type` | `auto` | 値の種類: `iri` / `literal` / `auto`。`literal` は文字列として比較する（言語タグ・データ型を問わない） |
| `label_predicate` | `rdfs:label` | IRI の値のラベルを表すプロパティ |
| `lang` | （なし） | 候補のラベルの言語 |
| `limit` | （なし） | 候補の数（件数の多い順） |
| `match` | `any` | 複数の値を選んだときの組み合わせ: `any`（いずれか）/ `all`（すべて）/ `selectable`（画面で切り替える） |
| `search` | `false` | `true` なら、候補をラベルで検索する欄を出す |
| `top_when_under` | （なし） | コレクションの要素がこれより多いときは、上位の候補を集計せず、検索で探してもらう |

範囲（`kind: range`）

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `datatype` | ○ | `integer` / `decimal` / `double` / `date` / `dateTime` / `gYear` |
| `unit` | | `year` なら、日付を年で比べる |
| `bins` | | 分布の区間の数の目安（既定 20） |

詳しくは [コレクションとファセット](collection.md#ファセット) を参照してください。

### `list`

```yaml
get:
    type: list
    header: name, url           # 列の名前（カンマ区切り）
    src: |                      # 1行に1件、値をカンマ区切りで書く
        アルプスの山,/collection?view=AlpsMountains
        山（dbo:Mountain）,/collection?class=dbo:Mountain
```

値は文字列として表示します。リンクにするときは、列の `href`（`href: "?url"`）や `type: directlink` を使います。

### `rank`（順位表。2026.10.20）

コレクションの要素を、ファセットの値ごとに数えて多い順に並べます（ファセットと同じ数え方。上位で切らずにページを送れます）。コレクションのページ（のタブ）に置きます。

```yaml
get:
    type: rank
    facet: cited_case          # まとめる値のファセット名（その predicate を使う。件数はこのファセットで絞り込んだ一覧へのリンクになる）
    # predicate: …             # ファセットを使わないとき（件数のリンクは出ない）
    value_class: lawo:Clause   # まとめる値をこのクラスに限る（任意）
    value_filter: '…'          # まとめる値 ?value の条件（FILTER の式。任意）
    order: count               # count（件数の多い順。既定）/ value（値の順）
    page_size: 50              # 1ページの行数。ページ送りは rpage=（要素の一覧の page とは別）
    list_tab: 0                # 件数のリンク先のタブ（要素の一覧のタブ）
    detail: |                  # 値の属性の列。$values がそのページの値の VALUES ?value { … } になる
        SELECT ?value ?court WHERE { $values ?value caselawp:id ?id . … }
    measure: count             # count（件数。既定）/ ratio（件数 ÷ 分母の大きい順。2026.10.21）
    denominator: |             # measure: ratio のときの分母。?value と ?denominator を返す SELECT（コレクションの条件は掛からない）
        SELECT ?value (COUNT(DISTINCT ?t) AS ?denominator) WHERE { ?t caselawp:judge/caselawp:person ?value } GROUP BY ?value
    min_denominator: 20        # 分母がこれより小さい値は除く（少ない分母で比が大きく出るのを避ける）
```

- `measure: ratio` では、表に分母と比の列が加わり、グラフは比（%）で描きます。分子（件数）はコレクションの条件で絞り込まれ、分母は絞り込まれません（例: 左のファセットで反対意見に絞ると、反対意見の数 ÷ 関与した裁判の数）。

- 同じ件数の値は同じ順位（1・2・2・4）です。
- URL に `highlight=<値のIRI>` があると、その行を強調します。

### `dbpedia`

```yaml
get:
    type: dbpedia
    object: owl:sameAs          # 表示中のリソースのこのプロパティの値（DBpedia のリソース名）
```

`https://dbpedia.org/page/<値>` へのリンクを1つ返します。

---

## 6. 表示（`show`）

| `show.type` | 内容 |
| --- | --- |
| `vtable` | 縦の表。最初の1行を「属性・値」の2列で表示する |
| `htable` | 横の表。1行を1行として表示する |
| `chart` | 棒グラフ・円グラフ（Chart.js） |
| `facet` | ファセット（`get.type: facet` と組み合わせる） |
| `graph` | ネットワーク図（Cytoscape.js）。SPARQL の結果の行を辺として描く |

### `vtable`

| 項目 | 内容 |
| --- | --- |
| `columns` | 表示する列（[7](#7-表の列columns)）。省略すると SPARQL の変数をすべて表示する |
| `attribute_width` | 属性の列の幅（px） |
| `value_width` | 値の列の幅（px） |

### `htable`

表の操作（2026.10.22）: 見出しをクリックすると、その列で並べ替える（数だけの列は数として、ほかは日本語の順）。
見出しの右端をドラッグすると列の幅を変えられる。表の中でページ送りする表（KGraphNavi 側でページ送りしない表）には、
見出しの下に列ごとの検索欄（その文字を含む行だけにする）と、表の上に件数（絞り込んだときは「n 件（全 m 件）」）が付く。
KGraphNavi 側でページ送りするコレクションの一覧は、そのページの行しか持たないので、検索欄と件数は付けない（件数はページの上に出る）。

| 項目 | 内容 |
| --- | --- |
| `columns` | 表示する列（[7](#7-表の列columns)）。省略すると SPARQL の変数をすべて表示する |
| `group_by` | この変数の値が同じ行を1行にまとめる。他の列の異なる値は1つのセルに並べる（例: 複数の国にまたがる山） |
| `tree` | 親子の階層で表示する（下記） |

見出しをクリックすると並べ替えができます（`tree` のときを除く）。行数が多いときは表の下にページ送りが出ます（`get.page_size` のときを除く）。

#### `tree`（親子の階層表示）

親子関係のある行（法令 > 条 > 項、クラス > 下位クラス など）を、親の下に子を字下げして表示します。▾／▸ の印で折りたたみ・展開ができます。

```yaml
show:
    type: htable
    group_by: class
    tree:
        node: class             # 行の識別子の変数
        parent: parent          # 親の識別子の変数
        column: label           # 字下げ・折りたたみの印を付ける列
        strip_parent: false
    columns:
        - id: label
          link: class
```

| 項目 | 内容 |
| --- | --- |
| `node` | 行の識別子の変数 |
| `parent` | 親の識別子の変数（`parent_regex` の代わりに指定する） |
| `parent_regex` | 識別子からこの正規表現に合う末尾を取り除いたものを親とする。その識別子の行がなければ、さらに取り除いて遡る（`…_570_1` → `…_570` → `…`） |
| `parent_by` | `contains` なら、`column` の値を部分に含む行のうち最も長いものを親とする（`node`・`parent` は不要。例: 「マンション」>「マンション建設」>「マンション建設工事」） |
| `parent_min_length` | `parent_by: contains` で親にする値の最短の長さ（既定 2） |
| `column` | 字下げ・折りたたみの印を付ける列 |
| `sort` | 同じ親の子を並べる列（省略時は `column`）。数字は数の大小で比べる（90条 < 570条 < 570条の2。全角数字も） |
| `order` | `size` なら、子孫の多い行を先に並べる（同じ数なら `sort` の列の順） |
| `strip_parent` | `column` の値が親の値で始まるとき、その部分を省く（既定 `true`。「民法570条第1項」→「第1項」） |
| `same_as_parent` | 列のリスト。親と同じ値なら子の行では空にする（例: `[caption, commentary]`） |
| `collapsed` | 最初から子を折りたたんでおく（既定 `false`） |
| `paging` | 表のページ送りをする（既定 `false`。親子が別のページに分かれたり、後ろの行が次のページに隠れたりしないよう、階層表示の表は全部の行を出す） |

親の行が結果にない行は最上位に置きます。`group_by` と一緒に使うと、まとめた行の最初のレコードで親を決めます。

### `chart`

```yaml
show:
    type: chart
    chart: bar                  # bar（既定）/ pie
    labels: country             # 項目名の変数
    dataset: count              # 値の変数
    label: 山の数               # 凡例（既定は dataset の名前）
    display: localname          # 項目名が IRI ならローカル名で表示する
    height: 400                 # 高さ（px。既定 320）
```

`chart` には Chart.js のグラフの種類を書きます（`bar` と `pie` を想定しています）。

### `graph`（ネットワーク図。2026.10.28）

`get.type: sparql` の結果の行を辺として読み、ノードと辺の図を描きます。コレクションのページでは `$collection` で、絞り込んだコレクションの図になります。

```yaml
- def: gadget
  name: CitationNetwork
  title: 判例の参照関係
  get:
    type: sparql
    max_rows: 50000               # 辺の数だけ行を取るので、上限を上げておく
    src: |
      SELECT ?entity ?label ?year ?cited ?citedlabel ?citedyear WHERE {
        $collection
        ?entity caselawp:citedcaselaw ?cited .
        OPTIONAL { ?entity rdfs:label ?label }
        OPTIONAL { ?entity caselawp:year ?year }
        OPTIONAL { ?cited rdfs:label ?citedlabel }
        OPTIONAL { ?cited caselawp:year ?citedyear }
      }
  show:
    type: graph
    edges:
      - {from: entity, to: cited}           # entity の値から cited の値への辺
    nodes:
      entity: {label: label, kind: 判例, x: year}
      cited:  {label: citedlabel, kind: 判例, x: citedyear, in_collection: check}
    outside: hide
    layout: timeline
    max_nodes: 500
    height: 640
```

| 項目 | 内容 |
| --- | --- |
| `edges` | 辺のリスト（必須）。`from` / `to` に変数名。`directed: false` で向きのない辺（既定は向きあり）。`label` に辺の名前の変数 |
| `nodes` | 変数ごとのノードの設定。`label`（名前の変数。なければ IRI の末尾）、`kind`（種類の名前。色分けと凡例。既定は変数名）、`x`（年で並べるときの横軸の値の変数。`1948-03-30` のような日付は先頭の年を使う）、`in_collection`（下） |
| `outside` | コレクション外のノード: `hide`（既定。出さない）/ `show`（灰色・点線で出す）。画面の「コレクション外の参照先も表示する」で切り替える（URL `graph.outside=show`） |
| `layout` | 配置: `timeline`（`x` の値で横に並べる。辺は弧）/ `force`（力学モデル）/ `circle` / `grid`。既定は `x` があれば `timeline`、なければ `force`。画面でも切り替えられる |
| `max_nodes` | ノードの上限（既定 500）。超えたらつながりの多いものから残し、その旨を表示する |
| `size` | ノードの大きさ: `indegree`（向きのある辺の既定。参照されている数）/ `outdegree` / `degree`（向きのない辺の既定）/ `none` |
| `isolated` | 辺のないノード: `hide`（既定）/ `show` |
| `height` | 図の高さ（px。既定はガジェットの `height`、なければ 600） |

`nodes` の `in_collection`:

- `true` … コレクションの要素（変数 `entity` は既定で `true`）
- `check` … コレクションの要素かどうかを問い合わせて調べる（参照先の判例など）。要素でなければ「コレクション外」
- `false` … コレクションの要素ではないノード（法令の条など）。`outside` の対象にしない（`entity` 以外の既定）

画面では、ノードをクリックすると右の欄に詳しい情報（参照している・されている判例の一覧）を出し、つながるノードを強調します。ダブルクリックでそのリソースのページを開きます。

### `rank`

`get.type: rank` のガジェットに書きます。順位・値・（detail の列）・件数の表と、ページ送りを出します。

```yaml
show:
    type: rank
    value_label: 参照されている判例   # 値の列の見出し（既定はファセットの label）
    label: 参照している判例の数       # 件数の列の見出し
    chart: bar                      # 1ページ目の上位を棒グラフで表の上に出す（任意）
    chart_top: 20                   # グラフに出す数（既定 20）
    denominator_label: 分母          # measure: ratio のときの分母の列の見出し
    ratio_label: 割合                # 比の列の見出し
    ratio_format: percent           # percent（既定。12.3%）/ decimal（0.123）
    columns:                        # detail の列
        - id: court
          label: 裁判所
          display: localname
```

### `facet`

`get.type: facet` のガジェットに書きます（`show` の項目は `type: facet` だけ）。

---

## 7. 表の列（`columns`）

`vtable` / `htable` の列のリストです。各列は辞書、または変数名だけの文字列（`- elevation`）で書きます。

| 項目 | 既定値 | 内容 |
| --- | --- | --- |
| `id` | （必須） | 列の値を取る SPARQL の変数名 |
| `label` | `id` | 見出し（`vtable` では属性の名前） |
| `type` | `literal` | 値の種類（下表） |
| `width` | 600（`image` は 120） | 列の幅（px）。`image` では画像の幅 |
| `display` | | `localname` なら、IRI をローカル名（最後の `/` や `#` の後ろ）で表示する |
| `string` | | 表示する文字列。`?変数` / `?{変数}` を結果の値で置き換える（例 `"?label（?year）"`） |
| `link` | | 変数名。その変数のリソースのページへのリンクにする（表示は `id` の値）。その変数に値がなければリンクにしない |
| `href` | | リンク先。`?変数` ならその値、変数を含む文字列なら置き換えたもの |
| `collection` | | その値で絞り込んだコレクションへのリンクにする（下記） |

| `type` | 表示 |
| --- | --- |
| `literal` | 文字列 |
| `link` | リソースのページ（`/resource?uri=<値>`）へのリンク |
| `directlink` | 値の URL へのリンク（外部のページ） |
| `image` | 値の URL の画像 |

リンク先は、`collection` → `link` → `href` → `type` の順に、最初に指定されたもので決まります。

### 列の `collection`（その値で絞り込んだコレクションへ）

```yaml
columns:
    - id: countryLabel          # 表示するのはラベル
      label: 国
      collection:
        class: dbo:Mountain     # 移り先のコレクションのクラス（view: でページ名も可）
        facet: country          # 絞り込むファセットの名前
        value: country          # ファセットの値にする変数（省略時はこの列の値）
```

リンク先は `/collection?class=dbo:Mountain&f.country=<値>` です。

---

## 8. SPARQL の書き方

- `PREFIX` は書かず、`prefixes` に書きます（すべての問い合わせの先頭に付きます）。
- `$uri` は表示中のリソース（`<…>` の IRI）に置き換わります。リソースのページで使います。
- `$collection` はコレクションの要素を `?entity` に束縛する副問い合わせに置き換わります。コレクションを持つページで使います。書かない場合は最初の `WHERE {` の直後に入ります。コレクションのないページで `$collection` を使うとエラーになります。
- コレクションのページでは、URL のパラメータも `$<名前>` で使えます（`class` と `uri` は IRI、それ以外は文字列のリテラル）。値は検証してから埋め込みます。
- 結果の行数は `max_rows` で制限されます。並べ替えた上位だけを出すときは自分で `ORDER BY … LIMIT …` を書いてください。

```sparql
SELECT ?country (COUNT(DISTINCT ?entity) AS ?count)
WHERE {
    $collection
    ?entity dbo:country ?country .
}
GROUP BY ?country
ORDER BY DESC(?count)
LIMIT 12
```

---

## 9. 設定ファイルの読み込み

### `import`（設定ファイルの分割）

```yaml
-   import: common.yaml               # 文字列またはリスト
-   import: [facets.yaml, gadgets.yaml]
```

`import` に書いた YAML ファイル（設定項目のリスト）を、その位置に読み込みます。パスは設定ファイルのフォルダからの相対パスです。読み込みが循環するとエラーになります。

### ローカル設定（`local.yaml`）

設定ファイルと同じフォルダに `<設定ファイル名>.local.yaml`（例: `caselaw.local.yaml`。その設定ファイルだけに使う）があればそれを、無ければ `local.yaml` を、設定ファイルの後に読み込みます。後から読んだ設定が優先されるので、エンドポイントや配信するフォルダなど、手元の環境だけの値を上書きできます（`config/local.yaml.example`）。別のファイルを使うときは `--local <ファイル>`（環境変数 `KGRAPHNAVI_LOCAL`）で指定します。`local.yaml` と `*.local.yaml` は `.gitignore` の対象です。

### 設定ファイルの探し方

コマンドラインに書いた設定ファイルがなければ、カレントディレクトリの `config/` から探します（`kgraphnavi dbpedia.yaml` で `./config/dbpedia.yaml`）。

---

## 10. 設定の検証

起動時に次のことを調べ、問題があればエラー（`ConfigError`）で止まります。

- 未知の項目（アプリケーションの設定・ページ・ガジェットそれぞれ）
- `name` / `type` / `get` / `show` の書き忘れ、`gadget` も `tabs` もないページ
- ページ・ガジェットの名前の重複、`_` で始まる名前
- ページから参照しているガジェット（`gadget` / `tabs` / `sidebar`）が定義されていない
- `class` を `type: collection` 以外のページに書いた、`collection` に `instances` 以外を書いた
- ガジェットの `collection` に `var` も `facet` もない、`get.type` が `sparql` でない
- `text_search` / `max_rows` / `data_dirs` の値の誤り
- 列の `type` が未知（表示するときに検出）

---

## 11. 現在使えない機能

次の機能は、コードや古い文書に記述がありますが、現在は動作しません。

| 機能 | 状況 |
| --- | --- |
| ガジェットのパス指定 `Gadget(プロパティ)`（表示中のリソースからプロパティをたどった先でガジェットを実行する） | ページの検証で「ガジェットが定義されていない」エラーになる |
| `show.type: network` / `adjacentnetwork`、`get.type: csv2adjacent` | 廃止。ネットワーク図は `show.type: graph` を使う |
| `get.type: python` / `csv` | 未実装（エラーになる） |
| `filter`、`statistics` のページ | 廃止。コレクションとファセットを使う |
