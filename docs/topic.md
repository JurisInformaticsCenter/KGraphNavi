# キーワードからトピックのコレクションを作る（/topic。試作）

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

## 画面

- **1. 何をしたか**: 語をいくつに広げたか、種の要素の数、主なリンク（条）・補助リンクの数、本文で数えた語の数、確かさごとの件数と決め方。
  広げた語・選んだ条は「見る」で開く
- **2. 結果**: 確かさ・要素・なぜ入ったか。外のコマンドの版（判例）では、要素を「事件番号 裁判所 判決日」と事件名で出し、
  「なぜ入ったか」に当たった条（主・補助。3つまで）、本文に出た語と回数、関連語、事件名に語を出す。表示は「強だけ」「強・中（保存するもの）」「弱も」と、文字での絞り込み
- **3. 次にできること**: 保存（2. で表示していてチェックしたものだけ。「強だけ」や文字で絞ると、それが保存される）、
  「コレクションの画面で開く」（同じものを「トピック_<キーワード>」に上書きで保存して /collection?saved=… を開く。ファセットで絞って名前を付けて保存できる）、
  「直す」（語・関連語・条の選び直し。開いたときだけ出る）。選んだものは改行で区切って uris で送る（フォームの項目の数の上限のため）
- **作っている途中**: 外のコマンドは裏で動かし、作り手が標準エラーに出す「@@進み …」の段階と経過秒を表示する（/topic/status を2秒ごとに読む）。
  出来上がるとページが切り替わる。結果は KGraphNavi が動いている間は覚えておく

## 外のコマンドで作る（builder: command）

重い計算（本文の語の数え方、全件の確かさ）を外のコマンドに任せる。KGraphNavi は次の形でコマンドを呼び、結果の JSON を読んで同じ画面に出す
（kgraphnavi/topic.py の CommandTopicBuilder。同じ引数の結果は KGraphNavi が動いている間は覚えておく）。

```yaml
- topic:
    builder: command
    command: ["{python}", "build_topic.py", "{q}", "--json", "{json}"]   # {python} は KGraphNavi の Python、{q} はキーワード、{json} は結果を書くファイル
    cwd: ~/path/to/builder           # コマンドを実行するフォルダ
    timeout: 900
```

- 引数: キーワード（`|` の2つめ以降は `--add-word`）、画面で選び直したもの `--add-word` `--drop-word` `--add-related`
  `--add-clause`（主なリンク）`--aux-clause` `--drop-clause`（リンクの id）
- JSON: `keyword, seed_count, total, words[{word,kind}], links[{id,uri,label,prop,count,df,lift,role}], related[{word,core}],
  context[語], members[{uri,label,level,via}]`
- 判例のように要素を詳しく出すときは、members に `caseno, court, date, casename, clauses[{label, role}], words[[語, 回数]], related[[語, 回数]], name_hit` と、全体の `summary` も書ける
