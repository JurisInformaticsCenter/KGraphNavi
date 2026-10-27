# KGraphNavi ユーザーズガイド

このガイドでは、KGraphNavi の考え方と、自分の知識グラフ用の設定ファイルを書く手順を説明します。例はすべて DBpedia のサンプル [`config/dbpedia.yaml`](../config/dbpedia.yaml) から取っています。サンプルを動かしながら読むと分かりやすいでしょう。

- すべての設定項目の一覧: [設定ファイルリファレンス](config.md)
- コレクションとファセットの詳細: [コレクションとファセット](collection.md)
- ソースコードの構成: [開発者ガイド](developer-guide.md)

## 目次

1. [KGraphNavi でできること](#1-kgraphnavi-でできること)
2. [基本の考え方](#2-基本の考え方)
3. [はじめての設定](#3-はじめての設定)
4. [リソースのページを作る](#4-リソースのページを作る)
5. [画面をつなぐ](#5-画面をつなぐ)
6. [コレクションのページを作る](#6-コレクションのページを作る)
7. [ファセットで絞り込む](#7-ファセットで絞り込む)
8. [知識グラフ全体のページ](#8-知識グラフ全体のページ)
9. [トップ画面](#9-トップ画面)
10. [運用](#10-運用)
11. [トラブルシューティング](#11-トラブルシューティング)
12. [用語](#12-用語)

---

## 1. KGraphNavi でできること

KGraphNavi は、SPARQL エンドポイントで公開されている RDF の知識グラフを、Web 画面で見て回るためのアプリケーションです。

- リソース（例: マッターホルン）を開くと、その種類（`rdf:type`、例: 山）に応じた画面が出ます。画面には、概要の表、説明、関連するリソースの一覧などが並びます。
- 一覧の中のリソースや値をクリックすると、そのリソースの画面や、その値を持つリソースの集合（コレクション）の画面へ移ります。
- コレクションの画面では、要素の一覧と統計（グラフ）を表示し、ファセット（国、標高の範囲など）で絞り込めます。

どのクラスにどのような画面を出すかは、すべて YAML の設定ファイルに書きます。SPARQL を書ければ、プログラムを変えずに画面を作れます。

---

## 2. 基本の考え方

### 2.1 ページとガジェット

KGraphNavi の画面は **ページ** で、ページは **ガジェット** を並べたものです。

```text
ページ（例: Mountain … 山のリソースの画面）
 ├── ガジェット MountainProfile（山の概要の表）
 ├── ガジェット Abstract（説明）
 └── ガジェット SameRange（同じ山脈の山の一覧）
```

ガジェットは、**取得**（`get`: SPARQL でデータを取る）と **表示**（`show`: 表やグラフにする）の組です。

```yaml
-   def: gadget
    name: Abstract
    get:                          # 取得: 表示中のリソース（$uri）の説明を取る
        type: sparql
        src: |
            SELECT ?lang ?abstract
            WHERE {
                $uri dbo:abstract ?abstract .
                BIND(LANG(?abstract) AS ?lang)
                FILTER(?lang IN ("ja", "en"))
            }
    show:                         # 表示: 横の表にする
        type: htable
        columns:
            - id: lang
              label: 言語
            - id: abstract
              label: 説明
```

### 2.2 ページの種類

| 種類 | URL | 表示するもの |
| --- | --- | --- |
| リソースのページ | `/resource?uri=<IRI>` | 1つのリソース。`$uri` がそのリソースになる |
| コレクションのページ | `/collection?class=…` など | リソースの集合。`$collection` がその集合になる |
| 全体のページ | `/graph` | 知識グラフ全体の集計など |

### 2.3 リソースのページの選ばれ方

`/resource?uri=<IRI>` を開くと、次の順でページが決まります。

1. そのリソースの `rdf:type` を調べる
2. `rdf:type` が複数あれば、設定の `priority` のリストで最も前にあるクラスを選ぶ
3. そのクラスを `type` に書いたページを使う。なければ `type: '*'` のページを使う

DBpedia のマッターホルンには `dbo:Mountain`、`dbo:Place`、`owl:Thing` など多くのクラスが付いているので、`priority` の先頭に `dbo:Mountain` を書いて、山のページが選ばれるようにしています。

### 2.4 コレクションとファセット

**コレクション** はリソースの集合です。クラスのインスタンス（すべての山）、SPARQL で定義した集合（アルプスの山）、ガジェットの一覧（同じ山脈の山）がコレクションになります。

**ファセット** は、コレクションを絞り込むための部品です。「国」のファセットでスイスを選ぶと、スイスの山だけになり、同じページのすべてのガジェット（一覧、グラフ、他のファセットの件数）がその条件で表示し直されます。

---

## 3. はじめての設定

### 3.1 最小の設定

どの知識グラフでも動く、最小の設定です。すべてのリソースに、そのリソースから出るリンクと値の一覧を表示します。

```yaml
-   title: My KG
-   sparql_endpoint: "http://localhost:8890/sparql"
-   def: page
    name: Resource
    type: '*'
    gadget:
        - Out
-   def: gadget
    name: Out
    get:
        type: sparql
        src: |
            SELECT ?p ?o WHERE { $uri ?p ?o } LIMIT 500
    show:
        type: htable
        columns:
            - id: p
              type: link
              display: localname
            - id: o
```

`config/mykg.yaml` として保存し、起動します。

```bash
kgraphnavi config/mykg.yaml
```

`http://127.0.0.1:8000/resource?uri=<リソースのIRI>` を開くと、一覧が表示されます。プロパティの列はリンクになっているので、クリックするとそのプロパティのページへ移ります。

### 3.2 接頭辞

SPARQL の `PREFIX` は、ガジェットごとには書かず、`prefixes` にまとめて書きます。すべての問い合わせの先頭に付きます。`rdf` `rdfs` `xsd` `owl` は書かなくても使えます。

```yaml
-   prefixes:
        dbo: "http://dbpedia.org/ontology/"
        dbr: "http://dbpedia.org/resource/"
        dct: "http://purl.org/dc/terms/"
```

ページの `type` や `class` にも、`dbo:Mountain` のような接頭辞付きの名前が使えます（`priority` だけは完全な IRI で書きます）。

### 3.3 設定の誤り

起動時に設定を検証します。未知の項目、定義されていないガジェットの参照、必須項目の書き忘れなどがあると、エラーの一覧を出して止まります。

```text
kgraphnavi.errors.ConfigError: 設定エラーが見つかりました:
  - page(Mountain) -> gadget(MountainProfil)
```

---

## 4. リソースのページを作る

### 4.1 クラスのページ

`type` にクラスを書くと、そのクラスのリソースのページになります。

```yaml
-   def: page
    name: Mountain
    type: dbo:Mountain
    gadget:
        - MountainProfile
        - Abstract
```

`type: '*'` のページは、対応するページのないリソースに使われます。最後の受け皿として1つ置いておくと便利です。

### 4.2 縦の表（vtable）: 1つのリソースの概要

`vtable` は、SPARQL の結果の最初の1行を「属性・値」の2列で表示します。1つのリソースの概要に向いています。値がないこともあるプロパティは `OPTIONAL` で取ります。

```yaml
-   def: gadget
    name: MountainProfile
    title: 山の概要
    get:
        type: sparql
        src: |
            SELECT ?elevation ?firstAscent ?thumbnail ?wikipedia
            WHERE {
                OPTIONAL { $uri dbo:elevation ?elevation }
                OPTIONAL { $uri dbo:firstAscentYear ?firstAscent }
                OPTIONAL { $uri dbo:thumbnail ?thumbnail }
                OPTIONAL { $uri foaf:isPrimaryTopicOf ?wikipedia }
            }
            LIMIT 1
    show:
        type: vtable
        attribute_width: 160      # 属性の列の幅
        value_width: 520          # 値の列の幅
        columns:
            - id: elevation
              label: 標高（m）
            - id: firstAscent
              label: 初登頂の年
            - id: thumbnail
              label: 画像
              type: image         # 値の URL の画像を表示する
              width: 400          # 画像の幅
            - id: wikipedia
              label: Wikipedia
              type: directlink    # 値の URL へのリンク
```

`$uri` は、表示中のリソースの IRI に置き換わります。`title` はガジェットの見出しです（省略するとガジェットの名前）。

### 4.3 横の表（htable）: 一覧

`htable` は、SPARQL の結果の1行を表の1行にします。

```yaml
-   def: gadget
    name: FirstAscents
    title: 初登頂した山
    get:
        type: sparql
        src: |
            SELECT DISTINCT ?entity ?label ?firstAscent
            WHERE {
                ?entity dbo:firstAscentPerson $uri ;
                        rdfs:label ?label .
                FILTER(LANG(?label) = "en")
                OPTIONAL { ?entity dbo:firstAscentYear ?firstAscent }
            }
            ORDER BY ?firstAscent
    show:
        type: htable
        columns:
            - id: label
              label: 山
              link: entity        # 表示はラベル、リンク先は ?entity のページ
              width: 250
            - id: firstAscent
              label: 初登頂の年
              width: 100
```

表の見出しをクリックすると並べ替えができ、行が多いと表の下にページ送りが出ます。

### 4.4 列の表示とリンク

列（`columns`）では、表示する文字列とリンク先を別々に決められます。

| 書き方 | 表示 | リンク先 |
| --- | --- | --- |
| `type: link` | 値（IRI） | 値のリソースのページ |
| `type: link` と `display: localname` | IRI のローカル名（`…/Switzerland` → `Switzerland`） | 値のリソースのページ |
| `link: entity` | 値（ラベルなど） | `?entity` のリソースのページ |
| `string: "?label（?year）"` | 変数を埋め込んだ文字列 | （`type` などによる） |
| `href: "?url"` | 値 | `?url` の値 |
| `type: directlink` | 値 | 値の URL（外部のページ） |
| `type: image` | 値の URL の画像 | なし |
| `collection: {…}` | 値 | その値で絞り込んだコレクション（[5.2](#52-値から絞り込んだコレクションへ)） |

おすすめは、SPARQL でラベルと IRI の両方を取り、`id` にラベル、`link` に IRI を書く方法です。ラベルのないリソースもある場合は、`display: localname` を使うか、SPARQL の `COALESCE` でラベルの代わりを作ります。

### 4.5 同じリソースの行をまとめる（group_by）

1つの山に国が2つあると、SPARQL の結果は国ごとに2行になります。`group_by` を書くと、同じリソースの行を1行にまとめ、国の列に2つの国を並べます。

```yaml
    show:
        type: htable
        group_by: entity
```

### 4.6 タブ

ガジェットが多いページは、タブで分けられます。選んだタブは URL（`tab=番号`）に残ります。

```yaml
-   def: page
    name: Mountain
    type: dbo:Mountain
    tabs:
        - label: 概要
          gadget: [MountainProfile, Abstract]
        - label: 同じ山脈の山
          gadget: [SameRange]
        - label: すべてのデータ
          gadget: [Out, In]
```

---

## 5. 画面をつなぐ

### 5.1 リソースからリソースへ

`type: link` や `link:` の列は、リソースのページへのリンクになります。山のページの「山脈」をクリックすると山脈のページ、山脈のページの山をクリックすると山のページ、というように知識グラフをたどれます。

### 5.2 値から絞り込んだコレクションへ

列に `collection:` を書くと、その値で絞り込んだコレクションへのリンクになります。山の概要の「国」をクリックすると、その国の山のコレクションが開きます。

```yaml
            - id: countryLabel
              label: 国
              collection:
                class: dbo:Mountain     # 移り先: dbo:Mountain のコレクション
                facet: country          # ファセット country で
                value: country          # ?country の値で絞り込む
```

移り先では、ファセット「国」にその国がチェックされた状態になります。条件を外したり、他の条件を加えたりできます。

### 5.3 一覧をコレクションとして開く

ガジェットに `collection:` を書くと、見出しの横にボタンが出ます。押すと、その一覧をコレクションとして開き、ファセットでの絞り込みや統計が使えます。

```yaml
-   def: gadget
    name: SameRange
    title: 同じ山脈の山
    collection:
        var: entity               # 一覧の ?entity の列を要素にする
        class: dbo:Mountain       # dbo:Mountain のコレクションのページで表示する
        label: コレクションとして表示（絞り込み・統計）
    get: …
```

`var` の代わりに `facet:` を書くと、表示中のリソースをそのファセットの値として絞り込んだコレクションへ移ります。山脈のページの「この山脈の山」は `facet: range` で、その山脈で絞り込んだ山のコレクションへ移ります。

---

## 6. コレクションのページを作る

### 6.1 クラスのコレクション

```yaml
-   def: page
    name: MountainCollection
    type: collection
    class: dbo:Mountain
    gadget:
        - MountainList
```

`/collection?class=dbo:Mountain` で開きます。`dbo:Mountain` の下位クラス（`rdfs:subClassOf`）のコレクションにも、このページが使われます。対応するページのないクラスは、組み込みのページ（名前と IRI の一覧）で表示します。

### 6.2 SPARQL で定義したコレクション

`query` に、要素を `?uri` で返す SELECT を書きます。`/collection?view=<ページ名>` で開きます。

```yaml
-   def: page
    name: AlpsMountains
    type: collection
    query: |
        SELECT ?uri
        WHERE {
            ?uri a dbo:Mountain ;
                 dct:subject dbc:Mountains_of_the_Alps .
        }
    gadget:
        - MountainList
```

### 6.3 コレクションのガジェット

コレクションのページのガジェットでは、SPARQL に `$collection` と書きます。その位置にコレクションの要素を `?entity` に束縛する副問い合わせが入ります。

```yaml
-   def: gadget
    name: MountainList
    title: 山の一覧
    get:
        type: sparql
        page_size: 50             # 50件ずつ表示し、ページ送りを付ける
        src: |
            SELECT ?entity ?label ?elevation ?country
            WHERE {
                $collection
                OPTIONAL { ?entity rdfs:label ?label . FILTER(LANG(?label) = "en") }
                OPTIONAL { ?entity dbo:elevation ?elevation }
                OPTIONAL { ?entity dbo:country ?country }
            }
    show:
        type: htable
        group_by: entity
        columns:
            - id: label
              link: entity
            - id: elevation
            - id: country
              type: link
              display: localname
```

コレクションのページでは、すべてのガジェットにコレクションが渡されます（`$collection` がなければ `WHERE {` の直後に入ります）。コレクションと関係のないガジェットは置かないでください。

### 6.4 統計のグラフ

`show.type: chart` で、棒グラフ・円グラフを表示します。

```yaml
-   def: gadget
    name: CountryPie
    title: 国別の山の数（上位12か国）
    get:
        type: sparql
        src: |
            SELECT ?country (COUNT(DISTINCT ?entity) AS ?count)
            WHERE {
                $collection
                ?entity dbo:country ?country .
            }
            GROUP BY ?country
            ORDER BY DESC(?count)
            LIMIT 12
    show:
        type: chart
        chart: pie                # bar（棒グラフ）/ pie（円グラフ）
        labels: country           # 項目名の変数
        dataset: count            # 値の変数
        display: localname
```

### 6.5 クラスのページでインスタンスを集計する

クラス自身もリソースです（`/resource?uri=http://dbpedia.org/ontology/Mountain`）。クラスのページに `collection: instances` を書くと、そのクラスのインスタンスをコレクションとして、コレクションのガジェットを使えます。

```yaml
-   def: page
    name: Class
    type: owl:Class
    collection: instances
    tabs:
        - label: インスタンス
          gadget: [ClassInstances]
        - label: 国別
          gadget: [CountryBar]
```

---

## 7. ファセットで絞り込む

ファセットは `get.type: facet` と `show.type: facet` のガジェットです。コレクションのページの `sidebar` に並べると、左の列に表示されます。

```yaml
-   def: page
    name: AlpsMountains
    type: collection
    query: …
    sidebar: [facet_country, facet_range, facet_elevation, facet_first_ascent]
    tabs:
        - label: 一覧
          gadget: [MountainList]
        - label: 国別
          gadget: [CountryPie]
```

ページの先頭には、件数と現在の条件が表示されます。条件の ✕ で、その条件を外せます。

### 7.1 値のファセット

```yaml
-   def: gadget
    name: facet_country
    height: 240                   # 候補のリストの高さ
    get:
        type: facet
        name: country             # URL では f.country=<値>
        label: 国
        predicate: dbo:country
        value_type: iri
        lang: en                  # 候補のラベルの言語
        limit: 30                 # 件数の多い順に30件
        match: selectable         # 「いずれか」「すべて」を画面で切り替える
    show:
        type: facet
```

複数の値を選ぶと、既定では「いずれかを持つ」（OR）になります。`match: selectable` にすると画面で「すべてを持つ」（AND）に切り替えられます。スイスとイタリアを選んで「すべて」にすると、国境の山（マッターホルンなど）だけになります。

候補が多いファセットには `search: true` を書くと、候補をラベルで検索する欄が出ます（サンプルの「山脈」）。

### 7.2 範囲のファセット

数値や日付は `kind: range` で範囲を指定して絞り込みます。値の分布が棒グラフで表示され、下限・上限を入力するか、棒をクリックして絞り込みます。

```yaml
-   def: gadget
    name: facet_elevation
    get:
        type: facet
        kind: range
        name: elevation           # URL では f.elevation.min / f.elevation.max
        label: 標高（m）
        predicate: dbo:elevation
        datatype: double          # integer / decimal / double / date / dateTime / gYear
        bins: 20
    show:
        type: facet
```

各ファセットの候補の件数は、他のファセットの条件で絞り込んだコレクションで数えます。詳しくは [コレクションとファセット](collection.md#ファセット) を参照してください。

---

## 8. 知識グラフ全体のページ

`type: graph` のページは `/graph` で表示します。特定のリソースやコレクションに依存しない集計を置きます。

```yaml
-   def: page
    name: Overview
    type: graph
    gadget:
        - Links
        - RangeRanking
        - NaturalPlaceTree
```

### 8.1 固定の一覧（get: list）

よく使う画面へのリンク集などは、`get.type: list` で設定ファイルに直接書けます。

```yaml
-   def: gadget
    name: Links
    get:
        type: list
        header: name, url
        src: |
            アルプスの山,/collection?view=AlpsMountains
            山（dbo:Mountain）,/collection?class=dbo:Mountain
    show:
        type: htable
        columns:
            - id: name
              type: link
              href: "?url"
```

### 8.2 階層の表示（tree）

クラス階層のように親子関係のある行は、`tree` で親の下に子を字下げして表示できます。▾／▸ で折りたためます。

```yaml
-   def: gadget
    name: NaturalPlaceTree
    get:
        type: sparql
        src: |
            SELECT DISTINCT ?class ?parent ?label
            WHERE {
                ?class rdfs:subClassOf* dbo:NaturalPlace .
                OPTIONAL {
                    ?class rdfs:subClassOf ?parent .
                    ?parent rdfs:subClassOf* dbo:NaturalPlace .
                }
                OPTIONAL { ?class rdfs:label ?label . FILTER(LANG(?label) = "en") }
            }
    show:
        type: htable
        group_by: class
        tree:
            node: class           # 行の識別子
            parent: parent        # 親の識別子
            column: label         # 字下げする列
            strip_parent: false
        columns:
            - id: label
              link: class
```

親を、識別子の文字列（`parent_regex`）や、値の包含関係（`parent_by: contains`）から決めることもできます（[リファレンス](config.md#tree親子の階層表示)）。

---

## 9. トップ画面

トップ画面（`/`）には、`title`・`describe` と、検索欄、`sample` に書いたサンプルへのリンクが出ます。

```yaml
-   title: DBpedia
-   describe: DBpedia の山・山脈・国・人物を例に、KGraphNavi の主な機能を試すためのサンプルです。
-   sample:
        search:
            - Matterhorn
        resource:
            - http://dbpedia.org/resource/Matterhorn,マッターホルン（山）
        collection:
            - AlpsMountains,アルプスの山（ページ名を指定）
            - http://dbpedia.org/ontology/Mountain,山（クラス dbo:Mountain）
```

検索欄（`/search`）は、ラベル（設定の `label`、既定 `rdfs:label`）に語句を含む（部分一致）、または語句と一致する（完全一致）リソースを探します。大きな知識グラフでは部分一致の検索は時間がかかります。

---

## 10. 運用

### 10.1 手元の環境だけの設定（local.yaml）

エンドポイントの URL や、配信するファイルのフォルダなど、環境ごとに違う値は、設定ファイルと同じフォルダの `local.yaml` に書きます。自動で読み込まれ、設定ファイルの値を上書きします。

```yaml
# config/local.yaml
- sparql_endpoint: "http://localhost:8891/sparql"
- data_dir: ~/caselaw/html
```

### 10.2 設定ファイルの分割（import）

設定が大きくなったら、ファセットやガジェットを別のファイルに分け、`import` で読み込めます。

```yaml
-   import: [facets.yaml, gadgets.yaml]
```

### 10.3 ファイルの配信

文書の HTML などを KGraphNavi から配信するときは、`data_dir`（`/data/<path>`）や `data_dirs`（`/data/<名前>/<path>`）にフォルダを書きます。ガジェットでは、`href` でそのファイルへのリンクを作ります。

```yaml
            - id: id
              label: 文書
              type: link
              string: "HTML文書"
              href: "/data/?year/?id.html"
```

### 10.4 ログ

`-d INFO` で、実行した SPARQL（`extract_sparql: final query=…`）がログに出ます。`-d DEBUG` では、問い合わせの結果なども出ます。画面の表示がおかしいときは、まずログの SPARQL をエンドポイントで直接実行してみてください。

---

## 11. トラブルシューティング

### ページが選ばれない（`type: '*'` のページになる、エラーになる）

- リソースに `rdf:type` があるか確かめてください。`rdf:type` のないリソースはエラーになります。
- `rdf:type` が複数あるときは、`priority` にページのクラスを **完全な IRI** で書いてください。
- ページの `type` の接頭辞が `prefixes` に定義されているか確かめてください。

### ガジェットが空になる

- ログの SPARQL をエンドポイントで直接実行し、結果があるか確かめてください。
- `FILTER(LANG(?label) = "en")` のような言語の条件で、行がなくなっていないか確かめてください（`OPTIONAL` の中に入れると、ラベルがなくても行は残ります）。
- `$uri` の綴りを確かめてください。`$uri`・`$collection` 以外の `$名前` は、コレクションのページで同じ名前の URL パラメータがあるときだけ置き換わり、それ以外はそのまま残って SPARQL のエラーになります。

### 列の値が表示されない

- `columns` の `id` が SPARQL の変数名（`?` を除いた名前）と一致しているか確かめてください。
- `vtable` は最初の1行だけを表示します。

### リンクにならない

- `type: link` / `link:` / `href:` / `collection:` のどれかが必要です。
- `link: <変数>` は、その変数に値がない行ではリンクになりません。

### IRI がそのまま表示される

- `display: localname` を使うか、SPARQL でラベルを取り、`link:` でリンク先を指定してください。

### 画像が表示されない

- `type: image` の列の値が画像の URL になっているか確かめてください（HTML のタグではなく URL を返します）。

### コレクションのページで行が多すぎる・遅い

- `$collection` を使わないガジェットを置いていないか確かめてください（すべてのガジェットにコレクションが入ります）。
- 一覧には `page_size` を指定してください。
- 候補の多いファセットには `search: true` と `top_when_under` を指定してください。

### 「表示件数の上限に達した」と出る

- 1つのガジェットで取得する行数の上限（`max_rows`、既定 5000）に達しています。SPARQL に `LIMIT` を書くか、`max_rows` を増やしてください。

### 設定エラーで起動しない

- エラーの一覧に、どのページ・ガジェットのどの項目が問題かが出ます。[リファレンスの「設定の検証」](config.md#10-設定の検証) を参照してください。
- ガジェットのパス指定 `Gadget(プロパティ)` は現在使えません（[現在使えない機能](config.md#11-現在使えない機能)）。

---

## 12. 用語

| 用語 | 意味 |
| --- | --- |
| リソース | IRI で識別される RDF の対象（例 `http://dbpedia.org/resource/Matterhorn`） |
| クラス | リソースの種類。`rdf:type` で付く（例 `dbo:Mountain`） |
| ページ | 画面の定義（`def: page`）。リソースのページ、コレクションのページ、全体のページがある |
| ガジェット | 画面の部品（`def: gadget`）。取得（`get`）と表示（`show`）の組 |
| コレクション | リソースの集合。クラスのインスタンス、SPARQL で定義した集合、ガジェットの一覧など |
| ファセット | コレクションを値や範囲で絞り込むガジェット |
| `$uri` | SPARQL の中で、表示中のリソースに置き換わる変数 |
| `$collection` | SPARQL の中で、コレクションの要素（`?entity`）に置き換わる副問い合わせ |
