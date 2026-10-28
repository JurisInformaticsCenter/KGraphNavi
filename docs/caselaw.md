# 判例の知識グラフ（caselaw.yaml）

裁判所ウェブサイトで公開されている判例（判決文書 67,825 件）から作った RDF を、KGraphNavi の
`config/caselaw.yaml` で見るための説明です。

- 判例のページ: 詳細メタデータ（事件番号・裁判所・判決日・判示事項・裁判要旨など）、本文から取り出した争点と結論（推定）、
  参照法令（条・項。条の見出し、廃止法令・判決後の改正の注意）、参照判例、上訴審と原審、裁判官・個別意見、キーワード、類似判例
- コレクション: 裁判所・結果・参照法令の条・トピック・年などでの絞り込み、参照の多い判例・条の順位表、判例の参照関係のネットワーク図
- 並べて比べる: 地裁・高裁・最高裁を列に並べる（判例のページの「審級を並べて比べる」）

争点・結論・参照法令などは判決文から自動で取り出したもので、誤りを含みます。結論は必ず本文で確かめてください。

## データ

### RDF（このリポジトリの Releases）

RDF は [Releases](../../../releases) の `caselaw-data-*` に添付しています。

| ファイル | 中身 | ライセンス |
|---|---|---|
| `hanrei_public.ttl.gz` | 判例の RDF（下の 2 つを除くすべて。当事者の個人名を外した一般公開用） | CC BY 4.0 |
| `dbpedia.ttl.gz` | 日本語 DBpedia との対応と概要 | CC BY-SA 4.0 |
| `caseinfo.ttl.gz` | 事件の通称と、Wikipedia の記事の冒頭 | CC BY-SA 4.0 |
| `ontology.ttl` | 語彙（クラス・プロパティ） | CC BY 4.0 |

このリポジトリの LICENSE（MIT）はソースコードにだけ適用します。データのライセンスは上の表のとおりです。

URI は次のとおりです。判決文書は `caselaw:D<ID>`、裁判（審理）は `caselaw:T<ID>`、判決は `caselaw:J<ID>` で、
`caselawp:id` で結び付きます。

| 接頭辞 | 名前空間 |
|---|---|
| `caselaw:` | `http://ds.rois.ac.jp/caselaw/resource/`（判例・人・語など） |
| `caselawp:` | `http://ds.rois.ac.jp/caselaw/property/`（プロパティ） |
| `caselawo:` | `http://ds.rois.ac.jp/caselaw/ontology/`（クラス・値） |

#### 当事者の個人名について

一般公開用の RDF では、当事者（原告・被告・控訴人・被告人・申立人など）のうち個人名に見えるものを外しています。
裁判官・検察官・代理人（弁護士・弁理士など）の名前と、当事者のうち会社・国・自治体・団体などは残しています。
判定は自動なので、外れていない個人名や、外れた組織名がありえます。お気づきの点は Issue でお知らせください。

### 判例の HTML（本文）

判決文の PDF をテキスト化した HTML は、国立情報学研究所 情報学研究データリポジトリ（IDR）の
**「日本の判例HTMLデータ」**として提供しています。学術研究のための利用に限り、申請が必要です。

- 申請: https://www.nii.ac.jp/dsc/idr/rdata/HANREI/
- 申請は研究室などの単位で、代表者（教員・常勤のデータ管理者など）が行います。利用規約への同意と、年に一度の利用報告が必要です。
  詳しくは上のページを見てください。

HTML が無くても KGraphNavi は動きます。その場合、判例のページの「HTML文書」と、争点の「本文の判断へ」のリンクは開けません
（裁判所ウェブサイトの PDF へのリンクは使えます）。

## 動かし方

### 1. RDF を SPARQL エンドポイントに読み込む

`caselaw.yaml` の問い合わせは、名前付きグラフ `<http://ds.rois.ac.jp/caselaw/>` を見ます。Release の 4 つのファイルを
すべてこのグラフに読み込んでください。Virtuoso（全文索引 `bif:contains` を使うので推奨）の例:

```sql
-- Release のファイルを置いたフォルダ（virtuoso.ini の DirsAllowed に含めておく）
ld_dir('/path/to/caselaw-data', '*.ttl.gz', 'http://ds.rois.ac.jp/caselaw/');
ld_dir('/path/to/caselaw-data', 'ontology.ttl', 'http://ds.rois.ac.jp/caselaw/');
rdf_loader_run();
checkpoint;
-- 全文索引（候補の検索・トピックで使う）
DB.DBA.RDF_OBJ_FT_RULE_ADD (null, null, 'All');
DB.DBA.VT_INC_INDEX_DB_DBA_RDF_OBJ ();
```

### 2. KGraphNavi を起動する

```bash
kgraphnavi -e http://localhost:8890/sparql config/caselaw.yaml
```

### 3. 手元の設定（任意）

手元の環境だけの設定は `config/caselaw.local.yaml` に書きます（`config/local.yaml.example` を参照。リポジトリには含めません）。

```yaml
- sparql_endpoint: "http://localhost:8890/sparql"
- data_dir: ~/caselaw/html        # IDR の HTML（<年>/<ID>_hanrei.html）を置いたフォルダ
- static_dirs:
    css: ~/caselaw/css            # HTML が参照する CSS（/css/hanrei.css）
```

## ほかの部分について

- 条文の本文・定義規定を見るガジェット（法令の条のページの「定義」など）は、法令の RDF（e-Gov 法令データから作ったもの。
  グラフ `<http://lod4all.net/graph/e-laws-lod>`）を使います。このデータは Release に含めていないので、表示されません。
- トピック（`/topic`）は、`caselaw.yaml` の設定では SPARQL だけで作ります（タームのラベルと、中心の参照法令の条）。
- 中労委の判例のページ・ガジェットは、中労委のデータが無いと表示されません。

## 出典

- 判例: [裁判所ウェブサイト 裁判例検索](https://www.courts.go.jp/app/hanrei_jp/search1)（判決文の PDF と詳細メタデータ）
- 法令の条の見出し: [e-Gov 法令検索](https://laws.e-gov.go.jp/)
- 廃止法令: [日本法令索引](https://hourei.ndl.go.jp/)（国立国会図書館）
- DBpedia・Wikipedia: [日本語 DBpedia](https://ja.dbpedia.org/)、[Wikipedia 日本語版](https://ja.wikipedia.org/)（CC BY-SA 4.0）
- 特許: 特許の番号・題名と Google Patents へのリンク（要約は含めていません）
