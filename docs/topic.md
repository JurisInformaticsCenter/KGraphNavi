# キーワードからトピックのコレクションを作る（設計メモ。2026.10.26）

## ねらい

任意のキーワード（「stratovolcano」「パワーハラスメント」）から、それに関する要素（記事・判例など）のコレクションを作る。
語の検索だけでは、語を書かない要素（古い判例、要約に語の無い記事）を落とし、関係の薄い要素（語が1回出るだけ）を拾う。
そこで「語」と、要素からたどれる「リンク」（カテゴリ、参照する条など）の偏りを組み合わせる。データに依存する所は設定に出し、
判例に限らない一般の仕組みにする。

## 手順

1. **種の要素**: 語を探すプロパティ（`text_properties`。ラベル・要約など）にキーワードを含む要素
2. **リンクの候補**: 種の要素がリンクするリソース（`link_properties` の値）を数え、全体での数と比べた偏り（倍）を出す
   - **主なリンク**: 種の要素の `main_share` 以上がリンクし、全体では `specific_df` 以下（または `specific_lift` 倍以上偏る）。
     それだけでトピックに入れる（例: Category:Stratovolcanoes of Japan）
   - **補助リンク**: `aux_share` 以上。全体で多く使われるので、語と一緒のときだけ確かさを上げる（例: 判例の民法709条）
3. **確かさ**: 強 = 語とリンク（主・補助）の両方 / 中 = 主なリンクだけ、またはラベルに語 / 弱 = 本文（要約など）に語だけ
4. **画面で直す**: リンクごとに主・補助・使わないを選び直して作り直す（`/topic?q=…&edit=1&r.<リンク先>=main|aux|`）
5. **保存**: 強・中（選べば弱も）の要素を、名前を付けて保存したコレクションにする（`/collection?saved=<名前>`。ファセットで絞れる）

## 設定（`topic:`）

```yaml
- topic:
    item_class: dbo:Volcano          # 集める要素のクラス（省略すると限らない）
    text_properties: [rdfs:label, dbo:abstract]
    label_property: rdfs:label
    lang: en                         # 語を探す文字列とラベルの言語
    link_properties: [dct:subject]   # リンクを数えるプロパティ
    total: 6000000                   # 全体の要素の数（item_class があれば数える）
    seed_max: 2000                   # 種の要素の上限
    # しきい値: min_count, min_lift, main_share, aux_share, specific_df, specific_lift
```

## キーワードの書き方

`|` で区切るといずれかの語（`/topic?q=パワーハラスメント|パワハラ`）。部分一致なので「パワーハラスメント行為」なども入る。

## データごとの違い

| | DBpedia（config/dbpedia.yaml） | 判例（hanrei） |
|---|---|---|
| 要素 | 記事 | 判例文書 |
| 語 | ラベルと要約（bif:contains） | ターム（略語・派生語に広げる）と本文の出現数 |
| リンク | カテゴリ・山脈・所在地 | 中心の参照の条（主な条・補助条） |
| 関連語・文脈語 | （まだ無い） | いじめ・嫌がらせなど（本文の近さで選ぶ） |
| 作り方 | SPARQL だけ（kgraphnavi/topic.py の TopicBuilder） | 外のコマンド（builder: command。hanrei の src/topic_keyword.py --json を kgraphnavi/topic.py の CommandTopicBuilder が呼ぶ）。&builder=sparql で SPARQL の版も出せる |

## これから（ToDo。2026.10.26 にいったん置いた）

- 待ち時間（判例は1回2〜3分）: 裏で作って、できたら表示する。または本文の語の数を全件分先に数えておき grep を使わない
- 画面で直した定義を topic_def.csv に入れるボタン（src/topic_keyword.py --apply）。トピックの一覧・ページ・広げ・争点の仕組みに乗せる
- 関連語だけで入った判例（パワハラで 112件）の確からしさ: 事件の種類・当事者の呼び名などで混じり物を外す

- 判例の版を同じ画面に載せる（設定で「作り手」を外のコマンドに切り替え、定義と所属を読み込む）
- 定義を RDF で持つ（共通の語彙: トピック、条件の種類・プロパティ・値・役割）
- 引用・内部リンク（dbo:wikiPageWikiLink）で1段広げる
- 関連語（本文の語）を SPARQL の版にも入れるか

## 外のコマンドの版（builder: command）

重い計算（本文の語の数え方、全件の確かさ）を外のコマンドに任せる。KGraphNavi は次の形でコマンドを呼び、結果の JSON を読んで同じ画面に出す
（kgraphnavi/topic.py の CommandTopicBuilder。同じ引数の結果は KGraphNavi が動いている間は覚えておく）。

```yaml
- topic:
    builder: command
    command: ["{python}", "src/topic_keyword.py", "{q}", "--json", "{json}"]   # {python} は KGraphNavi の Python
    cwd: ~/nii/hanrei
    timeout: 900
```

- 引数: キーワード（`|` の2つめ以降は `--add-word`）、画面で選び直したもの `--add-word` `--drop-word` `--add-related`
  `--add-clause`（主なリンク）`--aux-clause` `--drop-clause`（リンクの id）
- JSON: `keyword, seed_count, total, words[{word,kind}], links[{id,uri,label,prop,count,df,lift,role}], related[{word,core}],
  context[語], members[{uri,label,level,via}]`
