# コンフィグファイル仕様 (`config/*.yaml`)

## - コンフィグファイルは

## 全体構造

コンフィグファイルは YAML のシーケンスで、トップレベルに以下の種類のエントリを持ちます。

- フロントエンド共通設定 (title, describe, endpoint, rdfstore, label, search_samples, uri_samples, priority)
- page 定義 (`def: page`)
- gadget 定義 (`def: gadget`)
- import 定義 (`import: <csv> as <name>`)

```yaml
- title: CTD
  describe: CTD の genes, chemicals, diseases およびそれらの関係に関するデータ。
  endpoint: http://localhost:8890/sparql
  rdfstore: virtuoso
  label: rdfs:label
  search_samples: 2D216
  uri_samples:
    - http://bio2rdf.org/mesh:C000723031,2D216
  priority:
    - http://ds.rois.ac.jp/caselaw/ontology/Person
    - http://ds.rois.ac.jp/caselaw/ontology/Term
```

…

これに続けて、`def: page` と `def: gadget` の記述例を今のメモからコピペして整理します。現在の説明はほぼそのまま使えるので、「YAML の階層が分かるようにインデントとコードブロックを整える」くらいの修正で十分です。[file:47]

### 3. docs/language.md（gadget / page の「言語仕様」）

ここは「DSL」として仕様書きするセクションです。

- gadget の構造: `get` / `show`
- `get.type` のバリエーション（sparql, list, python, dbpedia, csv2adjacent）
- `show.type` のバリエーション（htable, vtable, chart, network, filter）
- `columns` の各フィールド (`id`, `label`, `match`, `string`, `width`, `link`, `type: directlink` etc.)

今のメモのこの部分を、そのまま「仕様書」として別ファイルに分離すると分かりやすくなります。

例:

```markdown
# Gadget 言語仕様

## Gadget 定義

```yaml
- def: gadget
  name: Subject
  height: 700
  get:
    type: sparql
    src: |
      prefix dc: <http://purl.org/dc/terms/>
      select ?term where {
        graph <http://ds.rois.ac.jp/caselaw/> {
          $uri dc:subject ?term .
        }
      }
  show:
    type: htable
    columns:
      - id: term
        label: ターム
        match: .*/resource/(.*)
        width: 200
```

…

ここに「count(list) の仕様」「chart の labels/dataset の意味」などを、箇条書きで再掲します。[1]

## コード側の修正ポイント

このドキュメント構成に合わせて、`kgraphnavi.py` 側を少し直すと、「コードと仕様がズレない」状態を保ちやすくなります。[1]

### 1. エントリポイントを明示する

README で `python -m src.kgraphnavi` を推奨するなら、`if __name__ == '__main__': main()` はそのままで OK です。[1]
ただし、モジュールとしても使えるようにするなら `main()` の引数を増やして、config ファイルを外から渡せるようにしておくと良いです。

例:

```python
def main(config_path: str | None = None) -> None:
    ...
    if config_path is None:
        args = parser.parse_args()
        config_path = args.config
    APPLICATION, endpoint, rdfstore, label_predicate = setconfig(config_path)
    ...
```

### 2. DSL に合わせて関数名・docstring を揃える

コンフィグの DSL 名とコードの関数名をできるだけ一致させると、仕様と実装を行き来しやすくなります。

例:

- `setconfig` → `load_config`
- `APPLICATION.make_page` → `render_page_from_config`
- `Gadget.extract` / `Gadget.show` の docstring に DSL の対応を書く。

```python
class Gadget:
    """
    Gadget 定義 (config の `def: gadget`) に対応するオブジェクト。
    - get: データ抽出 (`extract`)
    - show: 表示 (`show`)
    """
```

こうしておくと、docs/language.md からコードに戻ったときに対応関係が分かりやすいです。[1]

### 3. ルート関数のコメントを「公開仕様」に合わせる

現在のルートは次のような役割です。[1]

- `/` → トップページ
- `/search` → 検索
- `/resource` → RDF リソース詳細 (rdf:type → page)
- `/collections` → コレクションページ (page_type + `_collection`)
- `/statistics` → フィルタ付きページ
- `/data/` → データ配信

これをそのまま、コード中でもコメントにしておくと README と合わせやすくなります。

```python
@app.route("/")
def root() -> str:
    """トップページを表示する。config の title/describe, uri_samples を使用。"""
    ...

@app.route("/resource", methods=["GET", "POST"])
def get_resource() -> Response:
    """URI の rdf:type に応じてページ定義 (def: page) を選択し、詳細ページを生成する。"""
    ...
```

README の「ルーティング」セクションを、このコメントを元に生成できるようにしておくと維持が楽です。

### 4. requirements.txt を用意する

インストール説明を簡潔にするために、`requirements.txt` か `pyproject.toml` を置いておくと、ユーザーは `pip install -r requirements.txt` だけで済みます。[3]

`requirements.txt` 例:

```text
Flask>=2.2
PyYAML>=6.0
SPARQLWrapper>=1.8
```

README の「ライブラリ」セクションはこのファイルへのリンクにするだけで良くなります。

***

まとめると:

- ドキュメントは「README / config仕様 / gadget言語仕様」の3ファイル程度に分ける。
- `kgraphnavi.py` は Path ベースの設計と `render_page_to_file` の抽象化ができているので、名前と docstring を「仕様書の言葉」に揃える。
- ルーティング・インストール手順・DSL の説明は、今のメモを Markdown に再配置するだけでかなり良いドキュメントになります。

もし次にやるなら、「README の雛形を実際に Markdown で書いてほしい」や「config 言語仕様をそのまま docs/config.md の形にしてほしい」といった具体的な依頼を出してもらえれば、そのままコピペできる形で出します。
