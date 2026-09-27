# コレクションとファセット

コレクションは、RDF リソース（エンティティ）の集合です。`/collection` のページで一覧・統計・絞り込み（ファセット）を表示します。

## コレクションのページ

```yaml
- def: page
  name: MountainCollection
  type: collection
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

- `query` は `?uri` を返す SELECT です。`PREFIX` は書かず、設定ファイルの `prefixes` に書いてください。
- ページの先頭に、件数と現在の絞り込み条件が表示されます。条件の ✕ で、その条件を外せます。
- `gadget` の代わりに `tabs` も使えます。選んだタブは URL（`tab=番号`）に残ります。

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
- `page_size` を指定すると、コレクションの要素をその件数ずつに区切り、ページ送りを表示します。
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
- 各ファセットの候補の件数は、自分以外のファセットの条件で絞り込んだコレクションで数えます。

### 範囲のファセット（条件の適用のみ。画面は今後追加）

```yaml
  get:
    type: facet
    kind: range
    name: year
    label: 判決年
    predicate: caselawp:判決日
    datatype: date          # integer | decimal | double | date | dateTime | gYear
    unit: year              # 日付を年で比較する場合
```

## URL パラメータ

| パラメータ | 内容 |
| --- | --- |
| `class=<クラスURI>` | コレクションのクラス（ページに `query` がない場合） |
| `f.<name>=<値>` | 値の選択。繰り返すと OR |
| `f.<name>.min=<下限>` / `f.<name>.max=<上限>` | 範囲 |
| `page=<番号>` | ページ送り（1始まり） |
| `tab=<番号>` | 表示するタブ（0始まり） |

URL の値は、IRI・文字列・数値・日付として検証してから SPARQL に埋め込みます。検証できない値はエラー（400）になります。
