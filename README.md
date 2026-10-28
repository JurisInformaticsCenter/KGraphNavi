# KGraphNavi

KGraphNavi（Knowledge Graph Navigator）は、RDF の知識グラフ（Knowledge Graph; KG）を Web 画面で探索・分析するためのフレームワークです。

SPARQL エンドポイントに問い合わせた結果を、表・グラフ・絞り込み（ファセット）などの部品（ガジェット）で表示します。どのクラスのリソースをどう見せるかは YAML の設定ファイルに書くので、プログラムを変えずに、いろいろな知識グラフに使えます。

## 主な機能

- **リソースのページ**: リソースの `rdf:type` に応じたページ（ガジェットの組み合わせ）を表示する。タブで分けることもできる
- **コレクションのページ**: リソースの集合（クラスのインスタンス、SPARQL で定義した集合、ガジェットの一覧）を一覧・集計する
- **ファセットでの絞り込み**: 値の選択（いずれか／すべて、候補の検索）と、数値・日付の範囲（分布の棒グラフ付き）
- **表示部品**: 縦・横の表（リンク・画像・ローカル名表示、同じリソースの行をまとめる、親子の階層表示）、棒グラフ・円グラフ
- **ネットワーク図**: コレクションの要素のつながり（参照関係など）、二部グラフ（判例と法令の条など）、片側への射影（一緒に参照される条など）を描く。年で並べる配置、PageRank・連結成分の指標の表、範囲選択したノードの保存、画像・CSV・GraphML での書き出し
- **画面のつながり**: 表の値から、その値で絞り込んだコレクションへ移る。ガジェットの一覧をそのままコレクションとして開く
- **保存したコレクション**: 絞り込んだコレクションに名前を付けて保存し、和・共通部分・差でまとめる
- **並べて比べる**: 2〜4 のリソースを列に並べ、同じ種類の情報を横にそろえて比べる（違う行を色付け）
- **トピック**: キーワードから、語とリンク（カテゴリ・参照など）を手がかりに関係するリソースを集める（試作）
- **検索**: ラベルによるリソースの検索（部分一致・完全一致）
- **ファイルの配信**: 文書の HTML などを `/data/...` で配信する
- **設定**: 設定ファイルの分割（import）、手元の環境だけの設定（`local.yaml`）、設定内容の検証

## 動作環境

- Python 3.10 以降
- Flask 3.1 以降、PyYAML、SPARQLWrapper 2.0 以降
- SPARQL 1.1 のエンドポイント（Virtuoso を想定。Virtuoso の全文索引 `bif:contains` があれば候補の検索に使う）。長い問い合わせは POST で送るので、エンドポイントが POST を受け付ける必要がある
- ブラウザ: 表（jsGrid）・グラフ（Chart.js）・ネットワーク図（Cytoscape.js）のライブラリを CDN から読み込むので、インターネットに接続できること

## インストール

```bash
git clone https://github.com/JurisInformaticsCenter/KGraphNavi.git
cd KGraphNavi
pip install -e .            # kgraphnavi コマンドが使えるようになる
# テストも実行する場合
pip install -e ".[test]"
```

依存パッケージだけを入れる場合は `pip install -r requirements.txt` とし、`python -m kgraphnavi` で起動します。

## 使ってみる（DBpedia のサンプル）

`config/dbpedia.yaml` は、公開の DBpedia（https://dbpedia.org/sparql）を使うサンプルです。インターネットに接続していれば、そのまま動きます。

```bash
kgraphnavi config/dbpedia.yaml
```

Web ブラウザで http://127.0.0.1:8000/ を開き、トップ画面のサンプルから次の画面を試せます。

| 画面 | 内容 | 使っている機能 |
| --- | --- | --- |
| マッターホルン（`/resource?uri=…/Matterhorn`） | 山の概要・説明・同じ山脈の山・すべてのデータ | タブ、縦の表、画像、リンク、一覧をコレクションとして開く |
| ペンニネアルプス（山脈） | この山脈の山 | ファセットで絞り込んだコレクションへ移るボタン |
| アルプスの山（`/collection?view=AlpsMountains`） | 山の一覧、国別・山脈別の数 | SPARQL で定義した集合、ファセット（国・山脈・標高・初登頂の年）、ページ送り、グラフ |
| 山（`/collection?class=dbo:Mountain`） | DBpedia のすべての山 | クラスのコレクション |
| dbo:Mountain（クラス） | インスタンスの一覧・国別の数 | クラスのページでのインスタンスの集計 |
| `/graph` | 山の多い山脈、クラス階層 | 全体のページ、親子の階層表示 |
| 山を比べる（`/compare?uri=…/Matterhorn&uri=…/Mont_Blanc&uri=…/Mount_Fuji`） | 概要・カテゴリ・同じ山脈の山を列に並べる | 並べて比べる（カテゴリは行をそろえ、共通・違いを色付け） |
| アルプスの山の一覧で「比べる」にチェック | 選んだ山を並べて比べる | コレクションから選んで比べる |
| トピック（上の帯に `stratovolcano`） | 成層火山に関係する山 | キーワードからトピックのコレクションを作る |

DBpedia は大きな知識グラフなので、集計の重い画面では時間がかかったり、エンドポイントの制限で失敗したりすることがあります。DBpedia のエンドポイントがメンテナンス中のときは使えません。

## 自分の知識グラフで使う

1. `config/` に設定ファイル（例 `config/mykg.yaml`）を作り、SPARQL エンドポイント、接頭辞、クラスごとのページとガジェットを書きます（[設定ファイルリファレンス](docs/config.md)、[ユーザーズガイド](docs/user-guide.md)）。
2. 起動します。

```bash
kgraphnavi config/mykg.yaml
kgraphnavi -e http://localhost:8890/sparql config/mykg.yaml   # エンドポイントを指定する
```

手元の環境だけの設定（エンドポイント、配信するフォルダなど）は、設定ファイルと同じフォルダの `<設定ファイル名>.local.yaml`（例 `caselaw.local.yaml`）か `local.yaml` に書くと自動で読み込まれ、設定ファイルの値を上書きします（`config/local.yaml.example` を参照。どちらもリポジトリに含めません）。

### コマンドラインのオプション

| オプション | 内容 |
| --- | --- |
| `config` | 設定ファイル（パス、または `./config/` 内のファイル名） |
| `-e`, `--endpoint` | SPARQL エンドポイント（設定ファイルより優先。環境変数 `KGRAPHNAVI_ENDPOINT` も可） |
| `-l`, `--label` | ラベルを表すプロパティ（既定 `rdfs:label`） |
| `--data-dir` | `/data/<path>` で配信するフォルダ（環境変数 `KGRAPHNAVI_DATA_DIR` も可） |
| `--local` | ローカル設定ファイル（既定: 設定ファイルと同じフォルダの `local.yaml`） |
| `--host`, `--port` | 待ち受けるホストとポート（既定 `127.0.0.1:8000`） |
| `--dev` | 開発モード（Flask のデバッガと自動再読み込み） |
| `-d`, `--debug` | ログレベル（`DEBUG` / `INFO` / `WARNING`（既定）/ `ERROR` / `CRITICAL`） |

WSGI サーバで動かす場合は、環境変数 `KGRAPHNAVI_CONFIG` に設定ファイルを指定します。

```bash
KGRAPHNAVI_CONFIG=config/mykg.yaml gunicorn "kgraphnavi.app:create_app_from_env()"
```

## 画面（URL）

| URL | 内容 |
| --- | --- |
| `/` | トップ画面（説明と、検索・リソース・コレクションのサンプル） |
| `/search?q=<語>&mode=partial\|perfect` | ラベルによるリソースの検索（部分一致・完全一致） |
| `/resource?uri=<IRI>` | リソースのページ（`rdf:type` に対応するページ） |
| `/collection?class=<クラス>` | クラスのインスタンスのコレクション |
| `/collection?view=<ページ名>` | コレクションのページを名前で指定 |
| `/collection?from=<ガジェット名>&uri=<IRI>` | ガジェットの一覧をコレクションとして表示 |
| `/graph` | 知識グラフ全体のページ（`type: graph` のページ） |
| `/compare?uri=<IRI>&uri=<IRI>…` | 2〜4 のリソースを列に並べて比べる（`&view=<比べ方>`、`?saved=<名前>`、`?from=<ガジェット>&uri=<IRI>` も） |
| `/collections` | 保存したコレクションの一覧と、まとめる（和・共通部分・差） |
| `POST /collections/save_uris` | ネットワーク図で範囲選択したノードを保存し、そのコレクションを開く |
| `/topic?q=<語>` | キーワードからトピックのコレクションを作る |
| `/data/<path>`、`/data/<名前>/<path>` | 設定したフォルダのファイルの配信 |

コレクションの絞り込みの URL パラメータ（`f.<ファセット名>=…` など）と、ネットワーク図の表示を変える URL パラメータ（`graph.outside` など）は [コレクションとファセット](docs/collection.md#url-パラメータ) を参照してください。

## ドキュメント

| 文書 | 内容 |
| --- | --- |
| [docs/user-guide.md](docs/user-guide.md) | ユーザーズガイド: 考え方と、設定ファイルの書き方の手順 |
| [docs/config.md](docs/config.md) | 設定ファイルリファレンス: すべての設定項目 |
| [docs/collection.md](docs/collection.md) | コレクションとファセット、ネットワーク図 |
| [docs/caselaw.md](docs/caselaw.md) | 日本の判例の知識グラフ（RDF の入手・読み込み、caselaw.yaml での動かし方） |
| [docs/compare.md](docs/compare.md) | 並べて比べる |
| [docs/topic.md](docs/topic.md) | トピック（キーワードからコレクションを作る。試作） |
| [docs/developer-guide.md](docs/developer-guide.md) | 開発者ガイド: ソースコードの構成と拡張の方法 |

## 設定ファイルの例

```text
config/
├── dbpedia.yaml          DBpedia のサンプル（公開のエンドポイントで動く）
├── caselaw.yaml          日本の判例の知識グラフ用（RDF は Releases で公開。docs/caselaw.md）
└── local.yaml.example    ローカル設定の例
```

## テスト

```bash
pip install -e ".[test]"
pytest
```

テストは SPARQL エンドポイントに接続せずに実行できます。

## ライセンス

KGraphNavi のソースコードは [MIT License](LICENSE) で公開します。

KGraphNavi とともに配布するデータには、ソースコードとは別のライセンスを適用します。第三者が作成・提供したデータは、元のデータのライセンスと利用条件に従います（DBpedia のデータは CC BY-SA と GFDL）。

## 引用

KGraphNavi を研究で利用した場合は、以下の研究成果を引用してください。

> ※ 論文情報を確定後に記載予定

## 開発状況

KGraphNavi は研究目的で開発しているソフトウェアです。現在、研究用の知識グラフを対象に開発・検証を行っています。

## 問い合わせ・バグ報告

バグの報告や機能の提案は、GitHub の Issues をご利用ください。
