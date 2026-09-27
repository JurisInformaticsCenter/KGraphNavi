# KGraphNavi

KGraphNavi（Knowledge Graph Navigator）は、RDFベースの知識グラフ（Knowledge Graph; KG）を探索・分析するための可視化フレームワークです。

SPARQLクエリの結果をテーブル、チャート、ネットワークなどの可視化コンポーネントに接続することで、知識グラフに含まれる情報を対話的に探索・分析できます。

KGraphNaviでは、対象とする知識グラフに応じた設定をYAML形式の設定ファイルとして記述することで、異なるデータセットに対応できます。

## 主な機能

- RDFベースの知識グラフの探索・可視化

- SPARQLエンドポイントへの問い合わせ

- SPARQLクエリ結果のテーブル表示

- SPARQLクエリ結果のチャート表示

- グラフ構造のネットワーク表示

- RDFリソースの検索

- RDFリソースの詳細情報の表示

- コレクションの表示

- 統計情報の表示

- YAML設定ファイルによる知識グラフごとのカスタマイズ

## 動作環境

- Python 3.10 以降

- Flask

- PyYAML

- SPARQLWrapper

- SPARQLエンドポイントを提供するRDFストア
  
  - 例：Virtuoso

## インストール

リポジトリを取得し、パッケージとしてインストールします（仮想環境の利用を推奨します）。

```bash
git clone https://github.com/xiyewenren/KGraphNavi.git
cd KGraphNavi
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

インストールせずに依存パッケージだけを入れる場合は、以下でも動作します。

```bash
pip install -r requirements.txt
```

テストは以下で実行します。

```bash
pytest
```

## 設定ファイル

KGraphNaviでは、対象とする知識グラフに応じた設定をYAML形式で記述します。

設定ファイルでは、例えば以下のような情報を指定できます。

- 知識グラフの名称・説明

- 利用するRDFストア

- ラベルとして利用するプロパティ

- 検索例

- 表示するリソースのサンプル

- 優先して表示するクラス

- RDFクラスごとのページ定義

- SPARQLを利用したGadgetの定義

- テーブル、チャート、ネットワークなどの表示方法

- 統計ページ

- フィルタ

### 現在の設定例

現在、KGraphNaviでは日本の判例データを対象とした `caselaw.yaml` を使用しています。

```yaml
- title: caselaw
  describe: 日本の判例に関するデータ
  rdfstore: virtuoso
  label: rdfs:label
```

`caselaw.yaml` では、判例、裁判、判決、判決文書、人物、法令、特許などのRDFクラスに対して、それぞれ表示する情報や関連情報を定義しています。

また、SPARQLクエリを利用して、例えば以下のような情報を表示できます。

- 裁判官

- 当事者

- 関連ターム

- 参照法令

- 参照特許

- 刑罰

- 判例間の関連

- 判例文書のページ数分布

- 判決意見の構造パターン

## 設定ファイルの例

リポジトリには、実際の知識グラフに接続しなくても設定ファイルの構造を理解できるよう、サンプル設定として `dbpedia.yaml` を提供しています。

```text
config/
├── caselaw.yaml
├── dbpedia.yaml
└── local.yaml.example
```

`caselaw.yaml` は判例知識グラフ用の設定です。

一方、`dbpedia.yaml` はKGraphNaviの設定方法を理解するためのサンプルとして提供します。

## 起動方法

```bash
kgraphnavi config/dbpedia.yaml
```

起動後、Webブラウザから以下にアクセスします。

```text
http://127.0.0.1:8000/
```

`kgraphnavi` コマンドの代わりに `python -m kgraphnavi` でも起動できます。主なオプションは以下のとおりです。

| オプション | 内容 |
| --- | --- |
| `-e`, `--endpoint` | SPARQLエンドポイント（設定ファイルの `sparql_endpoint` より優先） |
| `-l`, `--label` | ラベルを表すプロパティ（既定 `rdfs:label`） |
| `--data-dir` | `/data/<path>` で配信するフォルダ |
| `--local` | ローカル設定ファイル（既定: 設定ファイルと同じフォルダの `local.yaml`） |
| `--host`, `--port` | 待ち受けるホストとポート（既定 `127.0.0.1:8000`） |
| `--dev` | 開発モード（Flaskのデバッガと自動再読み込み） |
| `-d`, `--debug` | ログレベル |

### ローカル設定

SPARQLエンドポイントやデータフォルダなど、環境ごとに異なる値は `config/local.yaml` に書きます。
`config/local.yaml.example` をコピーして使ってください。`config/local.yaml` はリポジトリに含まれません。

### 判例データ用設定

`caselaw.yaml` は、別途公開する判例RDFデータセットを閲覧・ナビゲーションするための設定です。

```bash
kgraphnavi -e http://localhost:8890/sparql --data-dir /path/to/caselaw/html config/caselaw.yaml
```

> 注：`caselaw.yaml` は現在、新しい設定形式への移行作業中です。

### WSGIサーバでの運用

環境変数で設定ファイルを指定し、WSGIサーバから起動できます。

```bash
KGRAPHNAVI_CONFIG=config/dbpedia.yaml gunicorn "kgraphnavi.app:create_app_from_env()"
```

## DBpediaを利用したサンプル

`config/dbpedia.yaml` は、KGraphNaviの設定方法を示すサンプルです。DBpediaの公開SPARQLエンドポイントを利用するため、インターネット接続が必要です。

```bash
kgraphnavi config/dbpedia.yaml
```

## Web画面

KGraphNaviでは、以下のような画面を提供します。

| URL                     | 内容         |
| ----------------------- | ---------- |
| `/`                     | トップ画面      |
| `/search?q=...`         | 検索結果       |
| `/resource?uri=...`     | RDFリソースの詳細 |
| `/collection?class=...` | コレクション（エンティティの集合）の表示 |
| `/graph`                | 知識グラフ全体の統計 |
| `/data/<path:filename>` | データフォルダ（`data_dir`）のファイルの配信 |

## データ

KGraphNaviでは、対象とする知識グラフそのものと、KGraphNaviの設定・可視化機能を分離して利用できます。

`caselaw.yaml` は日本の判例に関する知識グラフを対象とした設定例です。

KGraphNaviとともにデータを配布する場合は、データの出典、作成方法、利用条件およびライセンスをデータごとに明記します。

データのライセンスは、ソースコードのライセンスとは別に扱います。

## ライセンス

KGraphNaviのソースコードは **MIT License** の下で公開します（`LICENSE` を参照）。

KGraphNaviとともに配布するデータについては、ソースコードとは別のライセンスを適用します。

本プロジェクトで作成・配布するデータについて **CC BY 4.0** を適用する場合は、`DATA_LICENSE` にその旨を記載します。

ただし、第三者が作成・提供したデータについては、元のデータのライセンスおよび利用条件に従います。

## 引用

KGraphNaviを研究で利用した場合は、以下の研究成果を引用してください。

> ※ 論文情報を確定後に記載予定

将来的には `CITATION.cff` を提供し、GitHubからKGraphNaviを引用できるようにする予定です。

## 開発状況

KGraphNaviは研究目的で開発されているソフトウェアです。

現在、研究用の知識グラフを対象として開発・検証を行っています。

## 問い合わせ・バグ報告

バグの報告や機能に関する提案は、GitHubのIssuesをご利用ください。
