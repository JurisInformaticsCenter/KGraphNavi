# KGraphNavi ユーザーズガイド

## 1. はじめに

KGraphNavi は、RDF データを SPARQL によって検索し、検索結果を Web ページとして表示するナビゲーションシステムです。

KGraphNavi では、RDF リソースの種類に応じた `Page` を定義し、Page を複数の `Gadget` から構成します。

Gadget は、

1. データを取得する
2. 取得したデータを表示する

という2つの役割を持ちます。

設定ファイルでは、主に次のような構造でアプリケーションを定義します。

設定ファイル
    │
    ├── アプリケーション設定
    │
    ├── Page
    │     └── Gadget
    │           ├── get
    │           └── show
    │
    └── その他のデータ設定

この構造により、データセット固有の表示内容を、KGraphNavi 本体のプログラムを変更せずに設定ファイルから構成できます。

---

# 2. 基本概念

## 2.1 RDF リソース

KGraphNavi は RDF リソースを URI によって識別します。

例えば、

```text
http://dbpedia.org/resource/France
```

という URI は、1つの RDF リソースを表します。

リソースには、

- ラベル

- RDF type

- 他のリソースとの関係

- 数値

- 日付

- 画像 URI

などの情報が関連付けられています。

---

## 2.2 Page

`Page` は、特定の RDF リソースをどのような画面として表示するかを定義します。

Page には、

- Page 名

- 対象となる RDF type

- 表示する Gadget

を指定します。

例えば、

```yaml
- def: page
  name: Mountain
  type: http://dbpedia.org/ontology/Mountain
  gadget:
    - MountainInfo
    - MountainH
```

とすると、Mountain type のリソースを表示するときに、

- `MountainInfo`

- `MountainH`

という2つの Gadget が表示されます。

---

## 2.3 Gadget

`Gadget` は Page を構成する表示部品です。

Gadget は、

```text
get
 ↓
show
```

という構造になっています。

`get` はデータ取得方法を指定し、`show` は取得したデータの表示方法を指定します。

```yaml
- def: gadget
  name: MountainInfo

  get:
    type: sparql
    src: |
      SELECT ?name
      WHERE {
        $uri <http://example.org/name> ?name
      }

  show:
    type: vtable
```

---

## 2.4 リソースページ

リソースページは、特定の RDF URI を表示するページです。

概念的には、

```text
/resource?uri=<RDF URI>
```

のように URI を指定して表示します。

リソースページでは、対象リソースの RDF type を調べ、その type に対応する Page が選択されます。

その後、Page に指定された Gadget が順番に実行されます。

---

## 2.5 Gadget の実行

Page に、

```yaml
gadget:
  - Profile
  - Relations
  - Network
```

と指定されている場合、これらの Gadget が順番に処理されます。

各 Gadget について、

```text
対象 URI
   ↓
get
   ↓
取得データ
   ↓
show
   ↓
HTML
```

という処理が行われます。

---

# 3. 設定ファイル

## 3.1 設定ファイルの構造

KGraphNavi の設定ファイルは YAML 形式です。

設定ファイルには、アプリケーション全体の設定と、Page / Gadget の定義を記述します。

主な項目は次のとおりです。

| 項目              | 説明             |
| --------------- | -------------- |
| `title`         | アプリケーションタイトル   |
| `describe`      | アプリケーション説明     |
| `rdfstore`      | RDF ストア設定      |
| `label`         | 検索に利用するラベル     |
| `priority`      | RDF type の優先順位 |
| `query_samples` | クエリサンプル        |
| `uri_samples`   | URI サンプル       |
| `import`        | 外部データ          |
| `def: page`     | Page 定義        |
| `def: gadget`   | Gadget 定義      |

---

## 3.2 title

アプリケーションのタイトルを指定します。

```yaml
title: KGraphNavi
```

トップページなどで使用されます。

---

## 3.3 describe

アプリケーションの説明を指定します。

```yaml
describe: RDF resource navigation system
```

---

## 3.4 rdfstore

RDF ストアおよび SPARQL エンドポイントに関する設定を指定します。

データセットに応じて利用する RDF ストアを設定します。

---

## 3.5 label

検索などで利用するリソースのラベルプロパティを指定します。

データセットで、

```text
rdfs:label
```

などをリソース名として使用する場合に設定します。

---

## 3.6 priority

複数の RDF type を持つリソースについて、Page の選択に利用する優先順位を指定します。

例えば、

```yaml
priority:
  - http://dbpedia.org/ontology/Mountain
  - http://dbpedia.org/ontology/Place
  - http://www.w3.org/2002/07/owl#Thing
```

のように指定します。

複数の type を持つリソースでは、この優先順位を考慮して Page が選択されます。

---

## 3.7 query_samples

クエリサンプルを指定できます。

トップページなどで、利用者が実行できるサンプルクエリを提示するために使用します。

---

## 3.8 uri_samples

URI サンプルを指定できます。

KGraphNavi で表示できる代表的な URI を利用者に提示するために使用します。

---

## 3.9 import

CSV などの外部データを読み込むための設定です。

隣接グラフなど、SPARQL 以外のデータを利用する Gadget から参照できます。

---

# 4. Page

## 4.1 Page の定義

KGraphNavi では、Web ページを Page として定義します。

Page は、表示する対象と、ページ内で使用する Gadget を指定します。

Page には、大きく次の2種類があります。

| Page の種類  | 用途                         |
| --------- | -------------------------- |
| リソースページ   | 1つの RDF エンティティを表示          |
| コレクションページ | 同じ RDF クラスに属する複数のエンティティを表示 |

Page は YAML で定義します。



## 4.2 リソースページ

リソースページは、1つの RDF エンティティを表示するためのページです。
例えば、Mountain という RDF クラスに属するリソースを表示するページは、次のように定義できます。

```yaml

- def: page
  name: Mountain
  type: http://dbpedia.org/ontology/Mountain
  gadget:
  - MountainH
  - MountainV

## 4.2.2  name

Page を識別する名前です。

```yaml
name: Mountain
```

Page 名は設定ファイル内で識別可能な名前にします。

## 4.2.3 type

リソースページでは、対象リソースの `rdf:type` を指定します。

Page が対象とする RDF type を指定します。

```yaml
type: http://dbpedia.org/ontology/Mountain
```

例えば、

```sparql
?resource a <http://dbpedia.org/ontology/Mountain>
```

`/resource?uri=...` にアクセスすると、対象リソースの `rdf:type` に応じて表示する Page が選択されます。

##### ワイルドカード Page

`type` に `*` を指定すると、特定の RDF type に限定されない Page を定義できます。

```yaml
- def: page
  name: DefaultPage
  type: "*"
  gadget:
    - Profile
```

特定の type に対応する Page が存在しない場合のデフォルト Page として利用できます。

### 4.2.4 gadget

ページ内に表示する Gadget を指定します。

```
gadget:
  - Profile
  - Relations
  - Network
```

指定された Gadget が上から順番に表示されます。

---

## 4.3 コレクションページ

コレクションページは、同じ RDF クラスに属する複数のエンティティを一覧表示するためのページです。

コレクションページは `/collection` URL でアクセスします。

例えば、DBpedia の Mountain クラスに属するエンティティの集合を表示する場合、

```
/collection?class=http://dbpedia.org/ontology/Mountain
```

にアクセスします。

コレクションページは、次のように定義します。

```
 def: page
  name: MountainCollection
  type: collection
  class: http://dbpedia.org/ontology/Mountain
  gadget:
    - mountain_list

```

| 項目       | 必須  | 説明          |
| -------- | --- | ----------- |
| `def`    | ○   | `page`      |
| `name`   | ○   | Page 名      |
| `type`   | ○   | 対象 RDF type |
| `gadget` | ○   | Gadget の一覧  |





---

## 4.6 Gadget のパス指定

Gadget 名にパスを指定することができます。

```yaml
gadget:
  - Profile
  - Relations(country)
```

この場合、Gadget の実行前に指定されたパスを使って対象 URI を移動します。

例えば、

```text
Relations(country)
```

では、`country` に対応する関係をたどった先を Gadget の対象 URI として使用します。

---

# 5. Gadget

## 5.1 Gadget の定義

Gadget の基本形は次のとおりです。

```yaml
- def: gadget
  name: GadgetName

  get:
    ...

  show:
    ...
```

---

## 5.2 Gadget の項目

| 項目       | 必須  | 説明       |
| -------- | --- | -------- |
| `def`    | ○   | `gadget` |
| `name`   | ○   | Gadget 名 |
| `get`    | ○   | データ取得方法  |
| `show`   | ○   | 表示方法     |
| `height` |     | 表示領域の高さ  |

---

## 5.3 height

Gadget の表示領域の高さを指定できます。

```yaml
- def: gadget
  name: Network
  height: 500
```

テーブルやネットワークなど、表示領域の大きさが重要な Gadget で利用します。

---

## 5.4 get ― データ取得

`get.type` によってデータの取得方法を指定します。

代表的な取得方式は次のとおりです。

| `type`       | 用途             |
| ------------ | -------------- |
| `sparql`     | SPARQL による取得   |
| `list`       | 設定内に記述したデータ    |
| csv2adjacent | CSV から隣接グラフを取得 |
| `python`     | Python による拡張   |
| `csv`        | CSV データ        |
| `dbpedia`    | DBpedia 情報     |

---

### 5.4.1 SPARQL

#### 5.4.1.1 基本形

SPARQL を使用する Gadget は次のように記述します。

```yaml
get:
  type: sparql
  src: |
    SELECT ?name
    WHERE {
      $uri <http://example.org/name> ?name
    }
```

---

#### 5,4,1,2 `$uri`

`$uri` は現在表示している RDF リソースの URI を表します。

例えば対象 URI が、

```text
http://example.org/resource/123
```

の場合、

```sparql
$uri <http://example.org/name> ?name
```

は概念的に、

```sparql
<http://example.org/resource/123>
    <http://example.org/name>
    ?name
```

として実行されます。

---

#### 5.4.1.3 SPARQL の例

```yaml
get:
  type: sparql
  src: |
    PREFIX dbo: <http://dbpedia.org/ontology/>
    PREFIX dbp: <http://dbpedia.org/property/>

    SELECT ?country ?elevation ?thumbnail WHERE {
      $uri dbp:country ?country ;
           dbp:prominenceM ?elevation ;
           dbo:thumbnail ?thumbnail .
    }
```

この例では、

- `country`

- `elevation`

- `thumbnail`

の3つの値を取得します。

---

### 5.4.2 list

設定ファイル内に記述したデータを取得する場合に使用します。

```yaml
get:
  type: list
  ...
```

利用するデータ形式は Gadget の目的に応じて指定します。

---

# 5.4.3 csv2adjacent

CSV によって表現された関係データから隣接グラフを作成する場合に利用します。

設定では、CSV データのどの項目をエッジとして扱うか、方向をどうするかなどを指定します。

---

# 5.4.5 python / csv / dbpedia

データ取得処理を拡張するために、`python`、`csv`、`dbpedia` などの取得方式を利用できます。

具体的なパラメータは、それぞれのデータ取得方式の仕様に従います。

---

## 5.5 filter

検索条件などによってデータを絞り込むために使用します。

例えば、ページ設定にフィルタを関連付けることができます。

```yaml
filter:
  - label: 種類
    predicate: http://example.org/type
    type: select
    select: A,B,C
```

---

## 5.5 show ― 表示方法

`show.type` によって取得したデータの表示方法を指定します。

代表的な表示方式は次のとおりです。

| `type`            | 用途                   |
| ----------------- | -------------------- |
| `vtable`          | 1レコードを属性・値の縦型テーブルで表示 |
| `htable`          | 複数レコードを横型テーブルで表示     |
| `network`         | ネットワーク表示             |
| `adjacentnetwork` | 隣接グラフ表示              |
| `chart`           | チャート表示               |
| `filter`          | フィルタ表示               |

---

### 5.5.1 columns

`htable` や `vtable` では `columns` によって表示する項目と表示方法を指定します。

基本形は次のとおりです。

```yaml
columns:
  - id: country
    type: link
    label: Country

  - id: elevation
    type: literal
    label: Elevation

  - id: thumbnail
    type: image
    label: Thumbnail
```

---

#### 5.5.1.1 id

`id` は取得結果の変数名です。

例えば SPARQL が、

```sparql
SELECT ?country
```

を実行する場合、

```yaml
- id: country
```

と指定します。

---

#### 5.5.1.2 label

画面に表示する列名です。

```yaml
- id: country
  label: Country
```

`label` を省略した場合は `id` が使用されます。

---

#### 5.5.1.3 width

列の幅を指定します。

```yaml
- id: country
  width: 200
```

`htable` では各列の幅として使用します。

---

#### 5.5.1.4 type

値の表示形式を指定します。

主な値は次のとおりです。

| `type`          | 説明                     |
| --------------- | ---------------------- |
| `literal`       | 通常の値として表示              |
| `link`          | KGraphNavi 内部リソースへのリンク |
| `external-link` | 外部 URI へのリンク           |
| `image`         | 画像として表示                |

---

### 5.5.2 literal

通常の値として表示します。

```yaml
- id: elevation
  type: literal
```

---

### 5.5.3 link

KGraphNavi 内部のリソースへのリンクとして表示します。

```yaml
- id: country
  type: link
  href: "?country"
```

`link` では、表示文字列とリンク先を分離して指定できます。

---

### 5.5.4 external-link

外部データベースなどの URI に直接移動するリンクです。

```yaml
- id: country
  type: external-link
  href: "?country"
```

例えば DBpedia の URI を外部サイトへのリンクとして使用できます。

---

# 5.5.5 表示文字列とリンク先

KGraphNavi では、表示する文字列とリンク先を独立して指定できます。

例えば SPARQL で、

```sparql
SELECT ?label ?link
WHERE {
    ...
}
```

として、

```yaml
columns:
  - id: label
    type: link
    string: "?label"
    href: "?link"
```

とします。

この場合、

```text
string → 表示文字列
href   → リンク先
```

となります。

例えば、

```text
label = France
link  = http://dbpedia.org/resource/France
```

なら、

```text
表示: France
リンク先: http://dbpedia.org/resource/France
```

となります。

---

### 5.5.6 string

`string` は表示文字列を明示的に指定します。

```yaml
- id: country
  type: link
  string: "?label"
  href: "?link"
```

---

## 5.5.6.1 変数参照

`string` の中では取得結果の変数を参照できます。

```yaml
string: "?label"
```

複数の文字列を組み合わせることもできます。

```yaml
string: "Country: ?label"
```

変数には、

```text
?name
```

または、

```text
?{name}
```

の形式を使用できます。

---

### 5.5.7 href

`href` はリンク先を明示します。

```yaml
href: "?link"
```

変数を使用してリンク先を構成できます。

```yaml
href: "/resource?uri=?uri"
```

例えば、

```yaml
- id: label
  type: link
  string: "?label"
  href: "?uri"
```

とすると、

```text
表示文字列 = label
リンク先   = uri
```

となります。

---

### 5.5.8 display

`display` は取得した値の表示方法を指定します。

現在利用できる代表的な指定は、

```yaml
display: localname
```

です。

---

## 5.5.8.1 localname

RDF URI のローカル名を表示します。

例えば、

```text
http://dbpedia.org/resource/France
```

を、

```text
France
```

として表示できます。

設定例：

```yaml
- id: country
  type: link
  display: localname
  href: "?country"
```

ここで、

```text
display
```

は表示方法を決めるものであり、

```text
href
```

はリンク先を決めるものです。

したがって、

```yaml
- id: country
  type: link
  display: localname
  href: "?country"
```

では、

```text
表示文字列: France
リンク先:    http://dbpedia.org/resource/France
```

という構成になります。

---

### 5.5.9 image

画像を表示する場合は、

```yaml
- id: thumbnail
  type: image
  width: 120
```

と指定します。

SPARQL の結果には画像 URI を返します。

```sparql
SELECT ?thumbnail
WHERE {
    ...
}
```

画像の HTML タグを SPARQL の結果に埋め込むのではなく、画像 URI をデータとして返し、表示側で画像として扱います。

---

### 5.5.10 vtable

`vtable` は1レコードを属性名と属性値の2列で表示します。

例えば、

```yaml
show:
  type: vtable

  columns:
    - id: country
      type: link
      display: localname
      href: "?country"

    - id: elevation
      type: literal

    - id: thumbnail
      type: image
```

画面上では概念的に、

| 属性        | 値       |
| --------- | ------- |
| country   | France  |
| elevation | 4805.59 |
| thumbnail | 画像      |

のように表示されます。

---

#### 5.5.10.1 vtable の幅

`vtable` では属性列と値列の幅をそれぞれ指定できます。

attribute_widthは属性名を表示する列の幅、value_widthは属性値を表示する列の幅です。attribute_width`と`value_width`は`vtable` 全体に対する設定です。

```yaml
show:
  type: vtable
  attribute_width: 150
  value_width: 500
```

---

### 5.5.11 htable

`htable` は複数レコードを横方向の表として表示します。

```yaml
show:
  type: htable

  columns:
    - id: country
      type: link
      display: localname
      href: "?country"
      label: Country
      width: 200

    - id: elevation
      type: literal
      label: Elevation
      width: 100

    - id: thumbnail
      type: image
      label: Thumbnail
      width: 120
```

---

#### 5.5.11.1 htable の幅指定

htableでは各列について `width` を指定します。

```yaml
columns:
  - id: country
    width: 200

  - id: elevation
    width: 100
```

### 5.5.12 network

ネットワークを表示する Gadget では、ノードとエッジを定義します。

例えば、

```yaml
show:
  type: network

  node:
    - id: Subject
    - id: Object

  edge:
    - Subject, Object
```

のように指定します。

---

### 5.5.13 adjacentnetwork

隣接関係をネットワークとして表示します。

CSV などの外部データから隣接関係を構築する場合には、`csv2adjacent` と組み合わせて利用します。

---

# 5,5,14 chart

集計結果などをチャートとして表示するための Gadget です。

具体的なチャートの種類やデータ形式は、利用する Gadget の設定に従います。

---

### 5.5.15 filter

データを絞り込むための表示を提供します。

例えば、

```yaml
filter:
  - label: 訴訟類型
    predicate: http://example.org/caseType
    type: select
    select: 行政訴訟,民事訴訟,刑事訴訟
```

のように設定します。

---

# 6. 設定例

## 6.1 最小構成

```yaml
title: Example KGraphNavi

describe: Example RDF browser

- def: page
  name: ResourcePage
  type: http://example.org/Resource
  gadget:
    - Profile

- def: gadget
  name: Profile

  get:
    type: sparql
    src: |
      SELECT ?name
      WHERE {
        $uri <http://example.org/name> ?name
      }

  show:
    type: vtable

    columns:
      - id: name
        label: 名前
        type: literal
```

---

## 6.2 複数の Gadget

```yaml
- def: page
  name: ResourcePage
  type: http://example.org/Resource

  gadget:
    - Profile
    - Relations
    - Network
```

この場合、3つの Gadget が同じ Page に配置されます。

---

## 6.3 テーブル表示

```yaml
- def: gadget
  name: Relations

  get:
    type: sparql
    src: |
      SELECT ?name ?type
      WHERE {
        ?resource <http://example.org/name> ?name .
        ?resource a ?type .
      }

  show:
    type: htable

    columns:
      - id: name
        label: 名前
        type: literal

      - id: type
        label: 種類
        type: literal
```

---

## 6.4 表示値とリンク先を分離した例

SPARQL で表示用ラベルとリンク用 URI を別々に取得します。

```yaml
- def: gadget
  name: RelatedResources

  get:
    type: sparql
    src: |
      SELECT ?label ?link
      WHERE {
        ?resource <http://example.org/label> ?label .
        ?resource <http://example.org/uri> ?link .
      }

  show:
    type: htable

    columns:
      - id: label
        type: link
        string: "?label"
        href: "?link"
        label: 名前
```

この構成では、表示文字列とリンク先が明確に分離されています。

---

## 6.5 URI のローカル名を表示する例

```yaml
- def: gadget
  name: Countries

  get:
    type: sparql
    src: |
      SELECT ?country
      WHERE {
        $uri <http://example.org/country> ?country
      }

  show:
    type: htable

    columns:
      - id: country
        type: link
        display: localname
        href: "?country"
        label: Country
```

例えば、

```text
http://dbpedia.org/resource/France
```

を、

```text
France
```

として表示します。

---

## 6.6 画像表示

```yaml
- def: gadget
  name: Images

  get:
    type: sparql
    src: |
      SELECT ?thumbnail
      WHERE {
        $uri <http://example.org/thumbnail> ?thumbnail
      }

  show:
    type: htable

    columns:
      - id: thumbnail
        type: image
        label: 画像
        width: 120
```

---

## 6.7 Mountain の完全な例

```yaml
- def: page
  name: Mountain
  type: http://dbpedia.org/ontology/Mountain

  gadget:
    - MountainInfo
    - MountainH

- def: gadget
  name: MountainInfo

  get:
    type: sparql
    src: |
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

      SELECT ?label
      WHERE {
        $uri rdfs:label ?label
      }

  show:
    type: vtable

    attribute_width: 150
    value_width: 500

    columns:
      - id: label
        label: Name
        type: literal

- def: gadget
  name: MountainH

  get:
    type: sparql
    src: |
      PREFIX dbo: <http://dbpedia.org/ontology/>
      PREFIX dbp: <http://dbpedia.org/property/>

      SELECT ?country ?elevation ?thumbnail
      WHERE {
        $uri dbp:country ?country ;
             dbp:prominenceM ?elevation ;
             dbo:thumbnail ?thumbnail .
      }

  show:
    type: htable

    columns:
      - id: country
        type: link
        display: localname
        href: "?country"
        label: Country
        width: 200

      - id: elevation
        type: literal
        label: Elevation
        width: 100

      - id: thumbnail
        type: image
        label: Thumbnail
        width: 120
```

---

## 6.7 設定ファイルの設計

設定ファイルでは、次の役割を分けて記述することを推奨します。

```text
Page
  └── どのリソースをどの画面で表示するか

Gadget
  ├── get
  │    └── 何を取得するか
  │
  └── show
       └── どう表示するか
```

さらに `columns` では、

```text
id
  ↓
どの値か

string
  ↓
何を表示するか

display
  ↓
どのような形で表示するか

href
  ↓
どこへリンクするか

type
  ↓
どの表示形式にするか
```

を分離して指定します。

---

## 6.8 表示値とリンク先の設計

例えば、

```sparql
SELECT ?label ?link
WHERE {
    ...
}
```

というデータを取得した場合、

```yaml
- id: label
  type: link
  string: "?label"
  href: "?link"
```

とすることで、

```text
取得データ
    │
    ├── label ──→ 表示文字列
    │
    └── link  ──→ リンク先
```

という明確な構造になります。

URI の一部を表示したい場合には、

```yaml
display: localname
```

を追加します。

```yaml
- id: label
  type: link
  display: localname
  href: "?link"
```

---

## 6.9  JavaScript 側のセル構造

テーブル表示では、セルは単純な文字列ではなく、表示情報を持つ構造として扱われます。

通常の値：

```javascript
{
    "value": "4805.59",
    "type": "literal"
}
```

リンク：

```javascript
{
    "value": "France",
    "type": "link",
    "href": "/resource?uri=http%3A%2F%2Fdbpedia.org%2Fresource%2FFrance"
}
```

外部リンク：

```javascript
{
    "value": "France",
    "type": "external-link",
    "href": "http://dbpedia.org/resource/France"
}
```

画像：

```javascript
{
    "value": "http://example.org/image.jpg",
    "type": "image"
}
```

ここで、

- `value` は表示文字列

- `type` は表示形式

- `href` はリンク先

です。

---

## 6.10 表示処理

テーブル表示では概ね次の処理が行われます。

```text
SPARQL 結果
    ↓
get_raw_value()
    ↓
get_value() / get_value1()
    ↓
get_item_data()
    ↓
get_record_cells()
    ↓
show_vertical_table()
または
show_horizontal_table()
    ↓
make_kvtable()
または
make_table()
    ↓
make_jsgrid()
    ↓
HTML + JavaScript
```

この構造により、データ取得と表示処理を分離しています。

---

# 7. トラブルシューティング

## 7.1 Page が選択されない

次を確認します。

1. 対象リソースの RDF type

2. Page の `type`

3. `priority`

4. ワイルドカード Page

特定の type に対応する Page がない場合は、

```yaml
type: "*"
```

の Page を利用できます。

---

## 7.2 Gadget が表示されない

次を確認します。

1. Page に Gadget 名が指定されているか

2. Gadget 定義が存在するか

3. `get` の設定が正しいか

4. SPARQL クエリが正しいか

5. `show.type` が正しいか

---

## 7.3 SPARQL の結果が空

SPARQL エンドポイントでクエリを単独実行して確認します。

特に、

```text
$uri
```

が対象 URI に置き換わったときに、期待する SPARQL になっているか確認します。

---

## 7.4 columns の値が表示されない

`columns[].id` は SPARQL の取得変数と一致している必要があります。

例えば、

```sparql
SELECT ?name
```

に対して、

```yaml
columns:
  - id: title
```

とすると、`title` は取得されていないため値を表示できません。

---

## 7.5 値は表示されるがリンクにならない

生成されたセルに `href` が設定されているか確認します。

リンクセルでは概念的に、

```javascript
{
    value: "...",
    type: "link",
    href: "..."
}
```

となっている必要があります。

---

## 7.6 URI がそのまま表示される

例えば、

```text
http://dbpedia.org/resource/France
```

ではなく、

```text
France
```

と表示したい場合は、

```yaml
display: localname
```

を指定します。

---

## 7.7 画像が表示されない

次を確認します。

```yaml
type: image
```

が指定されているか確認します。

また、生成された JavaScript で、

```javascript
{
    value: "http://...",
    type: "image"
}
```

となっているか確認します。

画像 URI がブラウザからアクセス可能であることも確認してください。

---

## 7.8 Gadget の表示結果が `None` になる

表示関数が HTML 文字列を `return` しているか確認します。

例えば、

```python
return make_kvtable(...)
```

のような戻り値が必要です。

---

## 7.9 JavaScript のエラー

テーブルなどの JavaScript を利用する表示方式では、ブラウザの開発者ツールを確認します。

特に、

```javascript
const datalist = [...]
```

と、

```javascript
fields: [...]
```

が正しく生成されているか確認します。

---

# 7.10 デバッグログ

データ取得と表示は別の段階で確認できます。

### SPARQL

```text
SPARQL returned N rows
```

取得した行数を確認します。

### Gadget.extract

```text
gadget extract:
```

取得結果を確認します。

### Gadget.show

```text
Gadget.show: type=... columns=...
```

`show` と `columns` が期待どおり解釈されているか確認します。

### show_vertical_table / show_horizontal_table

表示用の `data` を確認します。

### make_jsgrid

次を確認します。

```text
data
header
columns
```

### 生成された JavaScript

```javascript
const datalist = [...]
```

と、

```javascript
fields: [...]
```

を確認します。

---

# 8. 設定リファレンス

## 8.1 トップレベル設定

| 項目              | 説明             |
| --------------- | -------------- |
| `title`         | アプリケーションタイトル   |
| `describe`      | アプリケーション説明     |
| `rdfstore`      | RDF ストア設定      |
| `label`         | 検索に利用するラベル     |
| `priority`      | RDF type の優先順位 |
| `query_samples` | クエリサンプル        |
| `uri_samples`   | URI サンプル       |
| `import`        | 外部データ          |

---

## 8.2 Page

| 項目       | 必須  | 説明          |
| -------- | --- | ----------- |
| `def`    | ○   | `page`      |
| `name`   | ○   | Page 名      |
| `type`   | ○   | 対象 RDF type |
| `gadget` | ○   | Gadget 一覧   |

---

## 8.3 Gadget

| 項目       | 必須  | 説明       |
| -------- | --- | -------- |
| `def`    | ○   | `gadget` |
| `name`   | ○   | Gadget 名 |
| `get`    | ○   | データ取得方法  |
| `show`   | ○   | 表示方法     |
| `height` |     | 表示領域の高さ  |

---

## 8.4 get

| `type`         | 説明           |
| -------------- | ------------ |
| `sparql`       | SPARQL による取得 |
| `list`         | 設定内データ       |
| `filter`       | フィルタ用データ     |
| `csv2adjacent` | 隣接グラフ用データ    |
| `python`       | Python 拡張    |
| `csv`          | CSV データ      |
| `dbpedia`      | DBpedia 情報   |

---

## 8.5 show

| `type`            | 説明            |
| ----------------- | ------------- |
| `vtable`          | 属性・値の縦型テーブル   |
| `htable`          | 複数レコードの横型テーブル |
| `network`         | ネットワーク        |
| `adjacentnetwork` | 隣接グラフ         |
| `chart`           | チャート          |
| `filter`          | フィルタ          |

---

## 8.6 columns

| 項目        | 説明       |
| --------- | -------- |
| `id`      | 取得結果の変数名 |
| `label`   | 表示する列名   |
| `width`   | 列幅       |
| `type`    | 表示形式     |
| `string`  | 表示文字列    |
| `href`    | リンク先     |
| `display` | 表示値の変換   |

---

## 8.7 columns.type

| 値               | 説明               |
| --------------- | ---------------- |
| `literal`       | 通常の値             |
| `link`          | KGraphNavi 内部リンク |
| `external-link` | 外部リンク            |
| `image`         | 画像               |

---

## 8.8 columns.display

| 値           | 説明            |
| ----------- | ------------- |
| `localname` | URI のローカル名を表示 |

---

## 8.9 vtable 固有設定

| 項目                | 説明     |
| ----------------- | ------ |
| `attribute_width` | 属性列の幅  |
| `value_width`     | 属性値列の幅 |

---

# 9. 推奨する設定方法

新しいデータセットを KGraphNavi に追加する場合は、次の順序で設定すると分かりやすくなります。

1. SPARQL エンドポイントが利用できることを確認する。

2. 表示対象となる RDF type を決める。

3. type ごとに Page を定義する。

4. Page に必要な Gadget を定義する。

5. Gadget の `get` で必要なデータを取得する。

6. `show` で表示形式を指定する。

7. `columns` で表示項目を定義する。

8. 必要に応じて `string` で表示文字列を指定する。

9. 必要に応じて `href` でリンク先を指定する。

10. URI の短縮表示が必要なら `display: localname` を指定する。

11. `vtable` なら `attribute_width` / `value_width` を設定する。

12. ブラウザで生成された表示を確認する。

特にリンクを扱う場合は、

```yaml
string: "?label"
href: "?link"
```

のように、**表示文字列とリンク先を別々の変数にする設計**を推奨します。

---

# 10. 用語

### RDF

リソースを URI で識別し、リソース間の関係をトリプルとして表現するデータモデルです。

### URI

RDF リソースを識別するための識別子です。

### RDF type

RDF リソースがどのクラスに属するかを表します。

### SPARQL

RDF データを検索するためのクエリ言語です。

### SPARQL エンドポイント

SPARQL クエリを受け付け、RDF データを検索するサービスです。

### Page

RDF リソースを表示するための画面定義です。

### Gadget

Page を構成する表示部品です。

### get

Gadget が表示するデータを取得する方法です。

### show

取得したデータを表示する方法です。

### columns

テーブルなどで表示する項目と表示方法を定義します。

---

# 11. まとめ

KGraphNavi の設定は、

```text
Page
 └── Gadget
      ├── get
      │    └── データ取得
      │
      └── show
           └── データ表示
                └── columns
```

という構造で考えることができます。

テーブル表示では、特に次の4つを分離して指定することが重要です。

```text
id
 ↓
取得する値

string
 ↓
表示する文字列

display
 ↓
表示文字列の変換方法

href
 ↓
リンク先
```

例えば、

```yaml
- id: country
  type: link
  display: localname
  string: "?label"
  href: "?link"
```

とすれば、

- `?label` を表示文字列として使用

- `display: localname` によって URI のローカル名を表示することも可能

- `?link` をリンク先として使用

- `type: link` によって KGraphNavi 内部リソースへのリンクとして表示

というように、それぞれの役割を明確に指定できます。

`vtable` では、

```yaml
attribute_width: 150
value_width: 500
```

によって属性列と値列を独立して設定できます。

この Page / Gadget / get / show / columns という構造を利用することで、データセットごとに異なる RDF データの表示画面を設定ファイルから構成できます。

```markdown

```

この構造により、データセット固有の表示内容を、KGraphNavi 本体のプログラムを変更せずに設定ファイルから構成できます。

---
