# 判例の知識グラフ（caselaw.yaml）

裁判所ウェブサイトで公開されている判例（判決文書 67,825 件）から作った RDF を、KGraphNavi の
`config/caselaw.yaml` で見るための説明です。

- 判例のページ: 詳細メタデータ（事件番号・裁判所・判決日・判示事項・裁判要旨など）、本文から取り出した争点と結論（推定）、
  参照法令（条・項。条の見出し、廃止法令・判決後の改正の注意）、参照判例、上訴審と原審、裁判官・個別意見、キーワード、類似判例
- コレクション: 裁判所・結果・参照法令の条・トピック・年などでの絞り込み、参照の多い判例・条の順位表、判例の参照関係のネットワーク図、判例と参照法令（条・法令）の図、一緒に参照される条・同じ条を参照する判例の図、PageRank などの指標の表（図で選んだ判例の保存、画像・CSV・GraphML での書き出し）
- 並べて比べる: 地裁・高裁・最高裁を列に並べる（判例のページの「審級を並べて比べる」）
- 分類: 分野（何についての事件か）・法的論点（何が争われたか）・手続と審級（どの手続で判断されたか）の3つの軸と、
  軸の概念の判例を手がかりを詰めて集めたトピック
- 分析: 量刑（罪名・刑期での絞り込みと分布）、判例変更、個別意見、問題のあるPDF

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

## コレクションの図（2026.10.28）

判決文書のコレクション（`/collection?class=caselawo:CaseLawDocument`）には、次の図のタブがあります。ファセットで絞り込んでから開くと、
その範囲の図になります（全体のままでは、つながりの多い 500 件に絞って描きます）。

| タブ | 内容 |
|---|---|
| 参照関係 | 判例が本文で参照している判例（`caselawp:citedcaselaw`。データ中の判例に照合できたもの）。年で横に並べる。参照先がコレクション外の判例は既定では出さない |
| 参照法令の図 | 判例と、判断の中で参照している法令の条（`caselawp:reflawCore`）の二部グラフ。上のボタンで「条／法令／一緒に参照される条／同じ条を参照する判例」を切り替える。条は条の単位だけで、「第◯項」だけの参照は入らない。既定では2件以上の判例が参照する条だけを出す |

図の下の指標の表（PageRank の上位 50 件）は、「参照関係」ではコレクションの中で中心的な判例の順位になります。
図で囲んで選んだ判例は、名前を付けて保存したコレクションにできます（`saved_collections_dir` が必要）。

## ほかの部分について

- 条文の本文・定義規定を見るガジェット（法令の条のページの「定義」など）は、法令の RDF（e-Gov 法令データから作ったもの。
  グラフ `<http://lod4all.net/graph/e-laws-lod>`）を使います。このデータは Release に含めていないので、表示されません。
- 語のページ（判例のターム `caselawo:Term`、法令の定義語 `lawo:Term`・条の特徴語 `lawo:Keyword`・条見出し `skos:Concept`）は、
  どれから開いても同じガジェットを出します（ラベルが同じものを結ぶ。ガジェットの `focus`）。法令の定義・条見出しの条・特徴語の条と、
  判例の上位下位のターム・キーワードの判例・この語を含む判例です。法令の側は法令の RDF を使うので、Release のデータだけでは表示されません。
- 問題のあるPDF（`/collection?view=PdfProblems`。2026.11.8）: PDF化の誤り（画像になった文字・中黒の番号・表せない文字・外字・読み誤りなど。
  hanrei の `src/pdfdefects.py`）のある判決文書。誤りの種類・作成ツール（Producer・Creator）・PDFの作成年・裁判所で絞り込み、
  「問題別」「作成ツール別」（そのツールのPDF全体のうちの割合）「PDFの作成年別」のタブで集計を見られます。
- 分類の軸（2026.11.8）: 分野（何についての事件か。hanrei の `src/field.py`、人手・規則・トピックから）と、法的論点（何が争われたか。
  `src/legalissue.py`、確かさ 強・中（候補））。判例のページの「分類」、判決文書の一覧のサイドバー、分野・論点のページで見られます。
- 判例変更（hanrei の `src/precedent.py` の `precedent_change.ttl`）: 判例のページの「判例変更」に、この判決が変更した判例と、この判例を変更した判決を出します。
  一覧は「判例変更」のコレクション（`/collection?view=PrecedentChanges`）。大法廷の判決の「…判例は、これを変更すべきものと認める」などの文から機械で取り出したものです。
- 量刑（hanrei の `src/sentencing.py` の `sentencing.ttl`）: 判決文書の一覧のサイドバーで、罪名（事件名から）・量刑の種類・刑期・確定の状況・罰条で絞り込み、
  「量刑」のタブで量刑の種類と刑期の分布、刑期の長い順の一覧を見られます。判決のページには、量刑のまとめと、同じ罪名の判決の中での刑期を出します。
  上訴を棄却した判決では、刑を言い渡した原審のものを出します。裁判所のウェブサイトに載った判決だけなので、量刑の相場を示すものではありません。
- 手続と審級（2026.11.8。hanrei の `src/procedure.py` の `procedure.ttl`）: 事件記号と裁判所の段（`data/casecode.csv`）、事件名から、
  手続（民事訴訟›通常訴訟・国家賠償請求、行政訴訟›取消訴訟など・住民訴訟、刑事事件›公判 など）と審級（第一審・控訴審・上告審・抗告審など）を付けます。
  判例のページの「分類」、判決文書の一覧のサイドバー、手続・審級のページで見られます。
- トピック（2026.11.8 整理。hanrei の `src/topics.py` の `topics.ttl`）: 分類の軸の概念（主に法的論点、一部は分野）の判例を、
  条・概念の語・事件名の手がかりを人が詰めて集めたものです（確かさ 強・中・弱。定義は hanrei の `data/csv/topic_def.csv`）。
  トピックの一覧（`/collection?view=Topics`）は軸と大分類ごとに並び、対応する軸の概念・判例の件数・答え合わせに使った外部の一覧を出します。
  法的論点・分野のページからも、対応するトピックへたどれます。
- トップ画面（2026.11.8）: 「判例を探す」「判例の例」「分類から探す」「分析する」「人・組織・法令・用語」「データの品質・試作」の見出しごとに
  サンプルをまとめています（`caselaw.yaml` の `sample.sections`）。
- キーワードから集めるトピック（`/topic`）は、`caselaw.yaml` の設定では SPARQL だけで作ります（タームのラベルと、中心の参照法令の条）。
- 中労委の判例のページ・ガジェットは、中労委のデータが無いと表示されません。

## 出典

- 判例: [裁判所ウェブサイト 裁判例検索](https://www.courts.go.jp/app/hanrei_jp/search1)（判決文の PDF と詳細メタデータ）
- 法令の条の見出し: [e-Gov 法令検索](https://laws.e-gov.go.jp/)
- 廃止法令: [日本法令索引](https://hourei.ndl.go.jp/)（国立国会図書館）
- DBpedia・Wikipedia: [日本語 DBpedia](https://ja.dbpedia.org/)、[Wikipedia 日本語版](https://ja.wikipedia.org/)（CC BY-SA 4.0）
- 特許: 特許の番号・題名と Google Patents へのリンク（要約は含めていません）
