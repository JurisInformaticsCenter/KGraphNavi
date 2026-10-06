# コレクションとファセット

コレクションは、RDF リソース（エンティティ）の集合です。`/collection` のページで一覧・統計・絞り込み（ファセット）を表示します。

## コレクションのページ

```yaml
- def: page
  name: MountainCollection
  type: collection
  class: dbo:Mountain       # このページが対象とするクラス（リストで複数も可）
  query: |                  # 省略時は URL の class=<クラスURI> のインスタンス
    SELECT ?uri
    WHERE {
      ?uri rdf:type dbo:Mountain .
      ?uri dct:subject dbc:Mountains_of_the_Alps .
    }
  gadget:
    - mountain_facet        # ファセットは左の列に表示される
    - mountain_list
```

- `query` は `?uri` を返す SELECT です。`PREFIX` は書かず、設定ファイルの `prefixes` に書いてください（`rdf` `rdfs` `xsd` `owl` は書かなくても使えます）。
- ページの先頭に、件数と現在の絞り込み条件が表示されます。条件の ✕ で、その条件を外せます。
- `gadget` の代わりに `tabs` も使えます。選んだタブは URL（`tab=番号`）に残ります。

### ファセットを左の列に置く（sidebar）

`sidebar:` に書いたガジェットは、`gadget` / `tabs` の左の列に表示します。タブを切り替えても、絞り込みの条件は共通です。

```yaml
- def: page
  name: CaseLawDocuments
  type: collection
  class: caselawo:CaseLawDocument
  sidebar: [facet_suit_type, facet_year]
  tabs:
    - label: 一覧
      gadget: [CaseLawDocumentList]
    - label: PDFページ数分布
      gadget: [PageFrequencyDistributionBar]
```

### クラスのリソースのページでインスタンスを集計する（collection: instances）

`/resource` のページ（`type` にRDFクラスを指定したページ）で `collection: instances` を指定すると、表示しているリソースをクラスとみなし、そのインスタンスをコレクションにします。`$collection` を使うガジェット（統計など）をクラスのページで使えます。

```yaml
- def: page
  name: Class
  type: http://www.w3.org/2002/07/owl#Class
  collection: instances
  gadget: [Out, PageFrequencyDistributionBar]
```

### ガジェットの一覧をコレクションとして表示する（collection）

リソースのページのガジェットに `collection:` を書くと、見出しの横に「コレクションとして表示」のボタンが出ます。押すと、そのガジェットの一覧の `var` の列を要素とするコレクションを表示します（ファセットでの絞り込みや統計も使えます）。

```yaml
- def: gadget
  name: Involved                 # 人物のページの「関与した裁判」
  collection:
    var: judge                   # コレクションの要素にする列（SPARQL の変数名）
    class: caselawo:Trial        # 要素のクラス。そのクラスのコレクションのページで表示する
    title: 関与した裁判           # コレクションのページの見出し（「尾島明: 関与した裁判」）
    label: 関与した裁判をコレクションとして表示   # ボタンの文字
  get:
    type: sparql
    src: |
      select distinct ?caseno ?casename ?role ?judge where { ... $uri ... }
```

- ボタンのリンク先は `/collection?from=<ガジェット名>&uri=<表示中のリソース>&class=<クラス>` です。
- `var` の代わりに `facet: <ファセット名>` を書くと、表示中のリソースをそのファセットの値として絞り込んだコレクションへ移ります（例: タームのページ → そのタームの判決文書。移った先で他のタームを加えられます）。
- ガジェットの SPARQL をそのまま副問い合わせとして使います（`$uri` には表示中のリソースが入ります）。
- `class` を省略すると、組み込みのページ（名前とURIの一覧）で表示します。
- `view: <ページ名>` を書くと、そのコレクションのページで表示します（`query` で集合を定義したページなど。`facet` と組み合わせると `/collection?view=<ページ名>&f.<ファセット>=<表示中のリソース>`）。

### 表の値から、その値を持つコレクションへ移る（列の collection）

表（`htable` / `vtable`）の列に `collection:` を書くと、その値のリンク先が「その値で絞り込んだコレクション」になります。

```yaml
columns:
  - id: casecategorylabel        # 表示するのはラベル
    label: 事件区分
    collection:
      class: caselawo:Trial      # 移り先のコレクションのクラス（view: でページ名の指定も可）
      facet: trial_case_category # 絞り込むファセットの名前（そのページにあるファセット）
      value: casecategory        # ファセットの値にする変数（省略時はこの列の値）
```

リンク先は `/collection?class=caselawo:Trial&f.trial_case_category=<値>` です。移り先ではファセットがチェック済みになり、条件の ✕ で外したり、他の条件と組み合わせたりできます。
現在の条件の値が IRI のときは、そのラベル（ファセットの `label_predicate`、既定 `rdfs:label`）を表示します。

### ページの選び方

`/collection?class=<クラス>` では、次の順でページを選びます。

1. `class:` にそのクラスを含むページ
2. そのクラスの上位クラス（`rdfs:subClassOf` をたどる）を `class:` に含むページ（ページ定義の順で最初のもの）
3. `class:` も `query` も持たないコレクションのページ
4. 組み込みのページ（要素を名前とURIで50件ずつ一覧する）

`query` を持つページは、その query の集合を表すので、他のクラスの代わりには使いません。
ページを直接指定するときは `/collection?view=<ページ名>` とします。トップ画面のコレクションサンプルにページ名を書くと、このリンクになります。

組み込みのページの名前には `rdfs:label`（設定の `label`）を使います。言語を選ぶ場合は `- label_lang: en` のように指定します。

`/graph` は、`type: graph` の最初のページを表示します。

## ガジェットでコレクションを受け取る

ガジェットの SPARQL に `$collection` と書くと、その位置にコレクションが入ります。コレクションの要素は `?entity` に入ります。

```yaml
- def: gadget
  name: mountain_list
  title: 山の一覧            # 見出し（省略時はガジェット名）
  get:
    type: sparql
    page_size: 20            # ページ送り（1ページの件数）
    src: |
      SELECT ?entity ?label
      WHERE {
        $collection
        ?entity rdfs:label ?label .
        FILTER(lang(?label) = "en")
      }
  show:
    type: htable
```

- `$collection` を書かない場合は、最初の `WHERE {` の直後に入ります。
- `page_size` を指定すると、コレクションの要素をその件数ずつに区切り、ページ送りを表示します（表自身のページ送りは使いません）。
- 1つのエンティティに複数の値（例: 複数の国）があると、SPARQL の結果は値ごとに別の行になります。`show` に `group_by: entity` を指定すると、同じエンティティの行を1行にまとめ、複数の値を1つのセルに並べて表示します。
- 1つのガジェットで取得する行数には上限があります（既定 5000 行）。設定 `- max_rows: 10000` で変更できます。上限を超えた場合はその旨を表示します。

## ファセット

```yaml
- def: gadget
  name: mountain_facet
  height: 240               # 候補リストの高さ（px）
  get:
    type: facet
    name: country           # URL パラメータ名（f.country）
    label: 国               # 見出し
    predicate: dbo:country  # プロパティまたはプロパティパス
    value_type: iri         # iri | literal | auto（既定 auto）
    label_predicate: rdfs:label
    lang: en                # 候補のラベルの言語
    limit: 30               # 候補の数（件数の多い順）
  show:
    type: facet
```

- `value_type: literal` の値は文字列として比較します（言語タグ・データ型は問いません）。
- 同じファセットで複数の値を選ぶと OR、異なるファセットの条件は AND になります。

### 値の組み合わせ（いずれか／すべて）と候補の検索

タームのように値の種類が多いファセットには、次の設定が使えます。

```yaml
- def: gadget
  name: facet_term
  get:
    type: facet
    name: term
    label: ターム
    predicate: dcterms:subject
    value_type: iri
    match: selectable      # any（いずれかを含む。既定）/ all（すべて含む）/ selectable（画面で切り替え）
    search: true           # 候補をラベルで検索する欄を出す
    top_when_under: 5000   # 要素がこれより多いときは上位の候補を集計せず、検索で探してもらう
    limit: 30
  show:
    type: facet
```

- `match: all`（または画面で「すべて含む」）では、選んだ値をすべて持つ要素に絞り込みます。現在の条件には「ターム（すべて）」と表示します。
- 検索欄に入力して「検索」を押すと、ラベル（`label_predicate`）にその語句を含む候補を、件数とともに表示します。検索語は絞り込みの条件にはなりません。
- 選んだ値は、候補の一覧の先頭に表示します。
- URL: `f.term=<値>&f.term=<値>&f.term.match=all&f.term.search=<語句>`

#### 検索の方法（text_search）

候補の検索には、次の2つの方法があります。設定ファイルの application 設定 `- text_search: auto` で選びます。

| 値 | 方法 |
| --- | --- |
| `auto`（既定） | 最初の検索のときに、エンドポイントで Virtuoso の全文索引（`bif:contains`）が使えるかを試し、使えれば `bif`、使えなければ `contains` で検索する。判定の結果はサーバのログに出る |
| `bif` | `bif:contains` を使う。全文索引を引くので、ラベルの数が多くても速い |
| `contains` | SPARQL の `CONTAINS` を使う。どのエンドポイントでも使えるが、ラベルを全件調べるので遅くなることがある |

- 判定は、実際のラベルを1つ取り出して `bif:contains` で探せるかどうかで行います（Virtuoso でないエンドポイントでは問い合わせがエラーになり、`contains` になります）。
- `bif:contains` は語単位の一致です。空白で区切った語はすべて含むもの（AND）を探します。`auto` のときは、`bif:contains` で候補が見つからなければ、`CONTAINS`（部分一致）で探し直します。
- 日本語のラベルの語の区切り方は Virtuoso の設定によります。部分一致で探したい語が見つからない場合は `contains` を指定してください。

検索・適用のボタンを押したり、リンクで次のページへ移ったりすると、結果が出るまで画面の上端に「実行しています…（経過秒数）」を表示します。
- 各ファセットの候補の件数は、自分以外のファセットの条件で絞り込んだコレクションで数えます。

### 範囲のファセット

数値や日付の範囲で絞り込みます。値の分布を棒グラフで表示し、下限・上限を入力するか、棒をクリックしてその区間で絞り込みます。

```yaml
- def: gadget
  name: mountain_elevation_facet
  get:
    type: facet
    kind: range
    name: elevation
    label: 標高（m）
    predicate: dbo:elevation
    datatype: decimal       # integer | decimal | double | date | dateTime | gYear
    bins: 20                # 分布の区間の数（目安。既定 20）
  show:
    type: facet
```

- `datatype: date` / `dateTime` の値は、分布を年ごとに数え、入力欄は日付になります。
- `unit: year` を指定すると、日付を年で比較し、入力欄も年（数値）になります（例: 判決年）。
- 数値にできない値（表記ゆれのある文字列など）は、範囲・分布の計算から除きます。
- 片側だけの指定もできます（例: 下限だけ → 「4000 以上」）。

## URL パラメータ

| パラメータ | 内容 |
| --- | --- |
| `class=<クラスURI>` | コレクションのクラス（`dbo:Mountain` のような接頭辞付きの名前も可） |
| `view=<ページ名>` | コレクションのページを直接指定 |
| `from=<ガジェット名>` / `uri=<URI>` | ガジェットの一覧をコレクションとして表示 |
| `f.<name>=<値>` | 値の選択。繰り返すと OR |
| `f.<name>.min=<下限>` / `f.<name>.max=<上限>` | 範囲 |
| `page=<番号>` | ページ送り（1始まり） |
| `tab=<番号>` | 表示するタブ（0始まり） |

URL の値は、IRI・文字列・数値・日付として検証してから SPARQL に埋め込みます。検証できない値はエラー（400）になります。
