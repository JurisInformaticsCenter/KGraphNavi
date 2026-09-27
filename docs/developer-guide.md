# KGraphNavi Developer Guide

## 1. この文書について

本書は、KGraphNaviのソースコードを理解し、保守・拡張するための開発者向けガイドです。

KGraphNaviは、RDF/Linked DataをSPARQL経由で取得し、URIに対応するPageとGadgetを設定ファイルから構成して表示するWebアプリケーションです。

KGraphNaviでは、画面そのものをPythonコードに直接記述するのではなく、主として以下の要素を組み合わせて画面を構成します。

- Page

- Gadget

- Extract

- Show

- SPARQL

- HTML/JavaScript生成

設定ファイルでPageとGadgetを定義し、実行時にURIからRDF typeを取得してPageを選択し、そのPageに登録されたGadgetを順番に実行します。

本書では、各ソースファイルの責務と主要な処理の流れを説明します。

---

# 2. 全体アーキテクチャ

KGraphNaviの基本的な処理は、概ね次のように構成されています。

```text
HTTP request
     │
     ▼
  views.py
     │
     ▼
Application
     │
     ├── URIからrdf:typeを取得
     │
     ├── Pageを選択
     │
     ▼
  Page
     │
     ├── Gadget 1
     ├── Gadget 2
     └── Gadget 3
            │
            ├── Extract
            │      │
            │      ▼
            │   sparql.py
            │      │
            │      ▼
            │   RDF/SPARQL endpoint
            │
            └── Show
                   │
                   ├── utils.py
                   │
                   └── makehtml.py
                           │
                           ▼
                    HTML / JavaScript
```

PageはGadgetの集合として構成されます。`Application.make_page()` はPage定義からGadget一覧を取得し、各Gadgetについて `make_gadget()` を呼び出します。

Gadgetでは、まずExtractによってデータを取得し、その結果をShowによって表示形式に変換します。現在の実装では、SPARQL、リスト、CSVからの隣接グラフなど複数のExtract方式が存在します。

---

# 3. ソースコードの構成

## 3.1 `kgraphnavi.py`

KGraphNaviのアプリケーション本体です。

主な責務は次のとおりです。

- 設定ファイルの読み込み

- Pageの管理

- Gadgetの管理

- URIからPageを決定した後のPage生成

- Gadgetの実行

- 隣接グラフなどのアプリケーション固有データの管理

- Flaskアプリケーションの生成

`Application` は、Page、Gadgetセット、アプリケーションタイトル、説明、サンプル、priority list、SPARQLクライアントなどを保持します。

### Application

ApplicationはKGraphNavi全体を管理するオブジェクトです。

主な属性は以下です。

- `pages`

- `gadgetset`

- `title`

- `describe`

- `query_samples`

- `uri_samples`

- `import_files`

- `priority_list`

- `sparql_client`

### `make_page()`

指定されたPageについて、そのPageに登録されたGadgetを生成します。

```text
Page
 ├─ Gadget A
 ├─ Gadget B
 └─ Gadget C
```

というPage定義を、実際のHTMLコンテンツへ変換する処理です。

### `make_gadget()`

Gadget名を解決し、必要ならURIをpathに従って移動し、ExtractとShowを実行します。

現在の構造では、

```text
make_gadget()
    ↓
make_window()
    ↓
gadget.extract()
    ↓
gadget.show()
```

という流れになります。

GadgetのHTMLにはGadget名をタイトルとして付加します。

---

# 4. Gadget

## 4.1 Gadgetの責務

Gadgetは、1つの表示部品を表します。

Gadgetは大きく、

```text
Extract → Show
```

という2段階で動作します。

- Extract: データを取得する

- Show: データを表示する

この分離により、同じデータ取得方法を異なる表示方法で利用できます。

---

## 4.2 Extract

現在のGadgetでは、Extract typeに応じて処理を切り替えています。

主なExtract typeは以下です。

- `sparql`

- `list`

- `filter`

- `csv2adjacent`

- `python`

- `csv`

- `dbpedia`

`Gadget.EXTRACTORS` にExtract方式と実装メソッドの対応を定義します。現在のコードでは、例えば `sparql` は `extract_sparql()`、`list` は `extract_list()` に対応します。

### `extract_sparql()`

設定されたSPARQLを実行します。

設定中の `$uri` は対象URIに置換されます。

また、Page側で設定されたsnippetを `$snippet` としてSPARQLへ埋め込む仕組みがあります。

---

## 4.3 Show

ShowはExtractで取得したデータを表示用の形式に変換します。

主なShow typeは、

- `vtable`

- `htable`

- `network`

- `adjacentnetwork`

- `chart`

です。

テーブル表示では、`columns` の定義を `prepare_columns()` に渡して表示用の情報を準備し、その後 `show_vertical_table()` または `show_horizontal_table()` を呼び出します。

---

# 5. Page

## 5.1 Pageの役割

Pageは、特定のRDF typeに対応する画面構成です。

Pageには、

- Page name

- RDF type

- Gadget list

が定義されます。

`Pages.set_page()` によってPage定義が登録され、内部ではPage nameとRDF type、Gadget listが保持されます。

---

## 5.2 URIからPageを選択する処理

`/resource` へのリクエストでは、まずURIの `rdf:type` をSPARQLで取得します。

その後、priority listを使って対象URIの代表的なRDF typeを決定し、Page定義と対応付けます。現在の `views.py` では、この処理は概ね次の順序です。

```text
URI
 ↓
rdf:typeを取得
 ↓
priorityによってtypeを選択
 ↓
rdf:type → Page
 ↓
Pageを生成
```

`views.py` では `get_target(uri, 'a')` によってRDF typeを取得し、`get_highest_priority_item()` によってpriorityを考慮したtypeを選択しています。

この処理はKGraphNaviの重要な仕様であるため、priorityの意味やfallbackの規則はユーザーズガイドにも明記する必要があります。

---

# 6. `views.py`

`views.py` はFlaskのHTTPリクエストをKGraphNavi内部の処理につなぐ入口です。

主な役割は、

- HTTPリクエストの受信

- URIや検索条件の取得

- Applicationへの処理委譲

- HTMLレスポンスの生成

です。

現在の主なエンドポイントには、

- `/`

- `/search`

- `/resource`

- `/collections`

- `/statistics`

- `/data/<filename>`

などがあります。

## `/resource`

KGraphNaviの主要な入口です。

```text
/resource?uri=...
```

というリクエストを受け取り、

1. URIを取得

2. RDF typeを取得

3. priorityを適用

4. Pageを決定

5. Pageを生成

6. HTML responseを返す

という処理を行います。

Page生成そのものは `render_page()` に委譲されます。`render_page()` はApplicationからPageを生成し、`make_html()` によって最終HTMLを構成します。

---

# 7. `sparql.py`

`sparql.py` はRDFストアとの通信を担当します。

中心となるクラスは `SPARQL` です。

```text
SPARQL
 ├─ query()
 ├─ query_values()
 ├─ query_value()
 ├─ rdfobject()
 ├─ get_target()
 ├─ get_subject()
 ├─ get_count()
 ├─ get_list()
 └─ retrieve()
```

現在の実装ではSPARQLWrapperを利用しています。

## `query()`

SPARQLクエリ中の `$uri` などの変数を置換して実行します。

## `query_values()`

指定された変数の値だけを取り出します。

## `query_value()`

最初の値を返します。値が存在しない場合は `None` を返します。

## `rdfobject()`

URIとpredicateからobjectを取得します。

## `get_target()`

URIから指定されたpathをたどり、対象となる値の一覧を取得します。

## `get_count()`

指定predicateの値の個数を取得します。

## `get_list()`

指定predicateの値の一覧を取得します。

---

# 8. SPARQL Prefix

SPARQLに共通して使用するprefixは `sparql.py` の共通prefix処理で管理します。

現在の実装では `PREFIX` がSPARQL実行時にクエリへ付加されます。`exsparql()` はログに実際に実行するSPARQLを出力し、共通prefixを付加してSPARQL endpointへ送信します。

共通prefixを増やす場合は、各GadgetのSPARQLへ同じprefixをコピーするのではなく、共通prefix管理側へ追加することを基本とします。

今後の整理では、

```text
共通prefix
    ↓
SPARQL client
    ↓
各GadgetのSPARQL
```

という責務分担を維持することが望まれます。

---

# 9. `utils.py`

`utils.py` は、取得したRDF/SPARQLデータを表示処理に適した形へ変換するためのユーティリティをまとめたモジュールです。

特に重要なのは、

- `prepare_columns()`

- `get_item_data()`

- `show_vertical_table()`

- `show_horizontal_table()`

などです。

## `prepare_columns()`

Gadgetの `columns` 設定を表示処理で利用できる形に準備します。

例えば、

- `type: directlink`

- `link`

などのcolumns属性に基づいて取得データを補正します。

今後は、この関数を単なるcolumnsの補助処理ではなく、

> columns定義を正規化し、表示処理が安全に利用できる状態にする

ための境界として扱うことが望まれます。

---

# 10. 表示データの内部形式

KGraphNaviでは、SPARQL結果を単なる文字列ではなく、

```python
{
    "type": "...",
    "value": "..."
}
```

というセル情報として扱います。

例えば、

```python
{
    "name": {
        "type": "literal",
        "value": "Mount Fuji"
    }
}
```

のような構造です。

この形式により、

- literal

- URI

- directlink

- image

- list

など、値そのものと表示方法を分離できます。

Gadgetのcolumns定義は、この内部形式に対する表示上の変換を指定するために使用されます。

---

# 11. `makehtml.py`

`makehtml.py` は、表示用データをHTMLおよびJavaScriptへ変換するモジュールです。

主な役割は、

- ページHTMLの生成

- JavaScriptライブラリの読み込み

- jsGridの生成

- テーブルのHTML/JavaScript生成

です。

現在の実装では、

```text
make_table()
    ↓
make_jsgrid()
```

という構造になっています。

---

# 12. jsGrid生成

jsGridを利用するテーブルでは、各テーブルに固有のIDを付けます。

例えば、

```text
jsGrid_9fb71b28
```

のようなIDです。

このIDはHTML側の

```html
<div id="jsGrid_9fb71b28"></div>
```

とJavaScript側の

```javascript
$("#jsGrid_9fb71b28").jsGrid(...)
```

で共有します。

これは、1ページに複数のGadgetが存在する場合に重要です。

各Gadgetが同じ `id="jsGrid"` を使用すると、複数のテーブルが同じDOM要素を参照してしまいます。

そのため、jsGridを生成する処理では、

```text
grid IDの生成
 ↓
HTMLのdiv
 ↓
JavaScriptのjsGrid初期化
```

を一つの処理単位として扱います。

---

# 13. HTML生成

現在の `make_html()` は、Page全体を構成するHTMLテンプレートに、

- title

- navigation

- libraries

- content

- categoryに基づく色

などを渡してHTMLを生成します。

現在は `render_template("page.html", ...)` を利用する実装に整理されています。

HTMLの基本構造はテンプレート側に置き、Pythonコードに巨大なHTML文字列を持たせないことを基本とします。

---

# 14. `templates/`

`templates/` はFlaskが利用するHTMLテンプレートを置くディレクトリです。

テンプレートと、実行時に生成されるHTML/JavaScriptは区別して管理します。

### テンプレート

例：

```text
templates/
    page.html
    index.html
    retrieval_result.html
    error.html
    filter.html
```

これらはアプリケーションのUI構造を定義するためのファイルです。

### 生成物

Gadget表示のたびに生成されるHTMLやJavaScriptを恒久的なテンプレートとして保存する設計は避けます。

現在の整理方針では、

```text
Python
  ↓
HTML/JavaScript文字列
  ↓
HTTP response
```

として扱い、実行時生成物を `templates/` に蓄積しない構成を基本とします。

---

# 15. `create_app()`

`kgraphnavi.py` の `create_app()` はFlaskアプリケーションを構築します。

Flaskのtemplate directoryやstatic directoryを設定し、ApplicationとSPARQL clientをFlaskのapplication contextに登録します。

概念的には、

```text
Application
     │
     ▼
 create_app()
     │
     ├── Flask
     ├── templates
     ├── Application
     └── SPARQL client
```

という関係です。

---

# 16. 設定ファイルの読み込み

`setconfig()` は設定ファイルを読み込み、Page、Gadget、SPARQL endpointなどのアプリケーション設定を構築します。

現在の設定には、

- `page`

- `gadget`

- `rdfstore`

- `label`

- `query_samples`

- `uri_samples`

- `priority`

- `title`

- `describe`

- `import`

などがあります。

設定値はApplicationへ渡され、Page/Gadgetの実行時に利用されます。

---

# 17. 設定とソースコードの責務分担

KGraphNaviを拡張するときは、次の原則を基本とします。

### PageやGadgetの追加

まず設定ファイルで表現できないか検討します。

```text
Page/Gadgetの追加
        ↓
設定ファイル
```

### 新しいExtract方式

既存Extractでは表現できない場合はGadget側へ追加します。

```text
新しいExtract方式
        ↓
Gadget
        ↓
EXTRACTORS
```

### 新しい表示方式

既存Showでは表現できない場合はShow側へ追加します。

```text
新しい表示方式
        ↓
utils.py等
        ↓
SHOWERS
```

### 新しいSPARQL操作

複数Gadgetから共通して利用する処理なら `sparql.py` に追加します。

```text
共通RDF操作
        ↓
SPARQL
```

### HTML/JavaScriptの変更

表示データをどのようにHTML/JavaScriptへ変換するかに関する処理は `makehtml.py` を対象とします。

---

# 18. エラー処理

KGraphNaviでは、設定エラー、SPARQLエラー、Gadgetエラー、表示エラーを区別して扱うことを目指します。

SPARQL実行では例外を捕捉し、`SparqlError` として上位へ伝える構造が導入されています。

Gadgetについても、未知のExtract typeなどを `GadgetError` として通知する構造が導入されています。

今後追加する処理では、

```text
設定が不正
    → Config/設定関連エラー

SPARQL実行失敗
    → SparqlError

Extract設定が不正
    → GadgetError

Show設定が不正
    → ShowError
```

のように、原因を追跡できる例外体系を維持します。

---

# 19. Loggingとデバッグ

KGraphNaviではPythonの `logging` を利用してデバッグ情報を出力します。

特にSPARQL処理では、

```python
logger = logging.getLogger(__name__)
```

を使用し、実行されるSPARQLやSPARQL実行エラーを記録しています。

デバッグ時には、単に「エラーになった」という情報だけでなく、処理の境界ごとに、

```text
URI
 ↓
rdf:type
 ↓
priority判定
 ↓
Page
 ↓
Gadget
 ↓
Extract
 ↓
Show
```

を追跡できるログを出すことが重要です。

特にPage選択では、

- 対象URI

- 取得したrdf:type一覧

- priority list

- priority判定結果

- 選択されたPage

- fallbackしたかどうか

をDEBUGレベルで記録すると、設定ミスを発見しやすくなります。

---

# 20. 新しいGadgetを追加する場合

新しいGadgetを追加する場合は、まず設定ファイルだけで実現できるか検討します。

一般的には、

```text
1. Gadget定義を追加
2. Extractを指定
3. Showを指定
4. PageにGadgetを登録
```

という順序になります。

PageとGadgetは設定ファイルから登録されます。`setconfig()` は `def: page` と `def: gadget` をそれぞれ対応するオブジェクトへ登録します。

---

# 21. 新しいExtract方式を追加する場合

新しいExtract方式を追加する場合は、GadgetのExtract処理を拡張します。

基本的な設計は、

```text
extract type
      ↓
EXTRACTORS
      ↓
extract_xxx()
      ↓
共通のデータ形式
```

です。

新しいExtract方式を追加するときは、

1. 設定上のtype名を決める

2. Extractメソッドを実装する

3. `EXTRACTORS` に登録する

4. エラー処理を追加する

5. 必要ならテストを追加する

という手順を取ります。

---

# 22. 新しいShow方式を追加する場合

Show方式もExtractと同様に、方式名と実装を対応付けます。

```text
show type
    ↓
SHOWERS
    ↓
show_xxx()
```

表示処理では、Extract結果の内部データ形式を直接壊さず、表示層で必要な変換を行うことを基本とします。

---

# 23. データ形式を変更するときの注意

KGraphNaviでは、

```text
SPARQL result
    ↓
内部データ
    ↓
utils.py
    ↓
makehtml.py
    ↓
JavaScript
```

という複数の層でデータを受け渡します。

そのため、データ構造を変更するときは、1つの関数だけを修正するのではなく、入出力を確認する必要があります。

特にテーブルについては、

```text
record
    ↓
columns
    ↓
get_item_data()
    ↓
table row
    ↓
make_jsgrid()
```

という流れを意識してください。

横方向テーブルでは、1レコードを「列名をキーとする辞書」として扱う設計を基本とします。

---

# 24. HTML/JavaScriptを生成する処理を変更するとき

HTML生成処理では、以下の責務を分離します。

### データ変換

`utils.py`

### HTML/JavaScript構造

`makehtml.py`

### ページ全体のテンプレート

`templates/page.html`

### HTTPレスポンス

`views.py`

例えばjsGridについては、

```text
utils.py
    ↓
テーブルデータ
    ↓
makehtml.py
    ↓
grid ID
    ↓
<div id="...">
    ↓
jsGrid initialization
```

という流れです。

HTML文字列そのものをデータとしてSPARQL結果に混ぜる設計は避けます。

例えば画像の場合、

```text
悪い設計

value =
<img src="...">
```

ではなく、

```text
value =
http://example.org/image.png

type =
image
```

として、表示層で `<img>` を生成する設計を維持します。

---

# 25. 依存関係

主要な依存関係は次のように考えることができます。

```text
views.py
    │
    ├── kgraphnavi.py
    └── makehtml.py

kgraphnavi.py
    │
    ├── sparql.py
    ├── utils.py
    └── makehtml.py

utils.py
    │
    └── makehtml.py

makehtml.py
    │
    └── templates/
```

依存方向を不必要に逆転させないことが重要です。

特に、

- `utils.py` がHTTP requestを直接扱う

- `makehtml.py` がPage選択を行う

- `sparql.py` がHTMLを生成する

といった責務の混在は避けます。

---

# 26. 拡張時の基本原則

KGraphNaviを拡張するときは、次の原則を基本とします。

### 原則1：設定と実装を分離する

PageやGadgetの個別設定をPythonコードへ埋め込まない。

### 原則2：取得と表示を分離する

Extractはデータ取得、Showは表示変換を担当する。

### 原則3：データとHTMLを分離する

内部データにHTML文字列を混在させず、表示層でHTMLを生成する。

### 原則4：共通処理は共通モジュールへ置く

SPARQL操作は `sparql.py`、表示データ変換は `utils.py`、HTML生成は `makehtml.py` に集約する。

### 原則5：エラーの原因を保持する

単に `None` を返すのではなく、必要に応じて専用例外を利用する。

### 原則6：デバッグ可能性を維持する

URI、RDF type、Page、Gadget、Extract、Showという処理単位でDEBUGログを確認できるようにする。

---

# 27. 今後の整理事項

現在のコードには、今後さらに責務を分離できる部分があります。

## 27.1 Page選択の独立

現在、`views.py` がURIからrdf:typeを取得し、priorityを適用し、Pageを選択しています。

今後は、

```text
URI
 ↓
PageResolver
 ↓
Page
```

のようにPage選択処理を独立させると、テストしやすくなります。

## 27.2 設定検証

現在は設定項目の不足や型の誤りが実行時に発見される場合があります。

将来的には、

```text
YAML
 ↓
Config validation
 ↓
正規化された設定
 ↓
Application
```

という構造を導入することが望まれます。

## 27.3 データモデルの明確化

SPARQL結果、テーブル行、セル情報などの内部データ形式を明確に定義し、各関数の入出力として文書化する必要があります。

## 27.4 HTML生成のさらなる分離

`makehtml.py` にHTML、JavaScript、jsGrid固有処理が集約されているため、規模が大きくなった場合には、

```text
html.py
jsgrid.py
network.py
```

などへの分割を検討します。

---

# 28. 開発時に最初に読むべきファイル

KGraphNaviのコードを初めて読む場合は、次の順序を推奨します。

```text
1. kgraphnavi.py
       ↓
2. views.py
       ↓
3. Gadget / Pages
       ↓
4. sparql.py
       ↓
5. utils.py
       ↓
6. makehtml.py
       ↓
7. templates/
```

最初に `kgraphnavi.py` でApplication、Page、Gadgetの関係を理解します。

次に `views.py` でHTTPリクエストからPage生成までの入口を確認します。

その後、

```text
Extract → SPARQL
Show    → utils
HTML    → makehtml
```

の順に読むと、1つのGadgetがどのように画面になるかを追いやすくなります。

---

# 29. 典型的なデバッグ手順

Gadgetが表示されない場合は、上流から順番に確認します。

### 1. URI

対象URIが正しいか確認します。

### 2. RDF type

対象URIについて期待する `rdf:type` が取得されているか確認します。

### 3. priority

複数のRDF typeがある場合、期待するtypeがpriorityによって選択されているか確認します。

### 4. Page

選択されたPageが期待するPageか確認します。

### 5. Gadget

Pageに期待するGadgetが登録されているか確認します。

### 6. Extract

GadgetのSPARQLが実行され、期待するデータが返っているか確認します。

### 7. Show

Show typeとcolumns定義がデータ形式に対応しているか確認します。

### 8. HTML/JavaScript

最終的に生成されたHTMLとブラウザのJavaScriptエラーを確認します。

この順序で確認すると、

```text
Page選択の問題
```

と

```text
Gadgetの問題
```

と

```text
表示処理の問題
```

を切り分けることができます。

---

# 30. まとめ

KGraphNaviの主要な責務は、次のように分けて理解するとよいでしょう。

```text
views.py
    HTTP

kgraphnavi.py
    Application / Page / Gadget

sparql.py
    RDF / SPARQL

utils.py
    データ変換 / 表示処理

makehtml.py
    HTML / JavaScript

templates/
    HTMLテンプレート

YAML
    Page / Gadget / アプリケーション設定
```

KGraphNaviを拡張するときは、まず「その変更はどの責務に属するか」を判断し、その責務を担当するモジュールへ実装することを基本とします。

特に、

```text
設定
 ↓
Page
 ↓
Gadget
 ↓
Extract
 ↓
データ
 ↓
Show
 ↓
HTML / JavaScript
```

という処理の流れを維持することが、今後の保守性を高める上で重要です。
