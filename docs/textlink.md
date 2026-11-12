# テキストにリンクを付ける（/textlink・/api/textlink）

貼り付けたテキストの中の参照（判例の引用、山や人の名前など）を見つけ、KGraphNavi のリソースのページへのリンクにします。
見つけて結ぶ処理はリンカのモジュールに任せます。どの知識グラフにも使える組み込みのリンカ（ラベルの辞書。下の「ラベルの辞書のリンカ」）があり、DBpedia のサンプル（dbpedia.yaml）はこれを使います。判例の知識グラフ（caselaw.yaml）では、hanrei の **caselinker**（判例引用リンカ）と、
照合の索引（判例LODの Release の `caselink-index.sqlite`）を使います。テキストは保存しません。

```
最二小判昭和58年7月15日集民139号293頁
  → 判例のページ /resource?uri=http://ds.rois.ac.jp/caselaw/resource/D062261
     判例ID ECLI:JP:S:1983:0715.S56O1173
```

## 画面（/textlink）

画面上端の「判例リンク」から開きます。テキストを貼って「リンクを付ける」を押すと、

- 引用の部分が判例のページへのリンクになります。下線の実線は確かさ「高」、破線は「中」、点線は「低」。青い地は、判例LODに判決が無い判例ID（判例IDのリソースのページへ）
- 結べなかった引用は点線の下線（マウスを載せると理由と候補）
- 下に引用の表（判例キー・判例ID・決め方・確かさ）と JSON

「確かさ」で、どの確かさ以上を結ぶかを選べます。

## Web API（/api/textlink）

```
curl -s http://127.0.0.1:8000/api/textlink -H 'Content-Type: application/json' \
     -d '{"text": "最判平成12年9月7日民集54巻7号2481頁を参照", "min_confidence": "中"}'
curl -s http://127.0.0.1:8000/api/textlink --data-urlencode text@準備書面.txt     # フォームでも
curl -s 'http://127.0.0.1:8000/api/textlink?text=最判昭58・7・15'                  # 短いテキストは GET でも
```

返す JSON:

```json
{"length": 27, "citations": 1, "linked": 1,
 "index": {"format": "caselink-index/1", "id_format": "caselaw-id/0.1", "judgments": "67823", "data_date": "2026-11-10", "linker": "caselinker"},
 "items": [{"start": 0, "end": 24, "text": "最判平成12年9月7日民集54巻7号2481頁",
            "linked": true, "target": "http://ds.rois.ac.jp/caselaw/resource/D050001",
            "page": "http://127.0.0.1:8000/resource?uri=http%3A%2F%2Fds.rois.ac.jp%2Fcaselaw%2Fresource%2FD050001",
            "ecli": "ECLI:JP:S:2000:0907.H10O1234", "key": "最高裁判所/2000-09-07/平成10(オ)1234",
            "id_uri": "http://ds.rois.ac.jp/caselaw/id/S/2000/0907.H10O1234",
            "in_data": true, "ids": ["050001"], "method": "判例集", "confidence": "高", "candidates": [],
            "court": "最高裁判所", "bench": "", "kind": "判決", "date": "2000-09-07", "caseno": "",
            "reporters": ["民集54巻7号2481頁"], "forms": ["略記", "判例集"]}]}
```

| 項目 | 内容 |
|---|---|
| `start`・`end` | 元のテキストでの位置（文字） |
| `linked` | 結べたか（確かさが `min_confidence` 以上） |
| `target` | リンク先のリソース。判決が判例LODにあれば判例（`…/resource/D<ID>`）、無ければ判例IDの URI |
| `page` | `target` の KGraphNavi のページ |
| `ecli`・`key`・`id_uri` | 判例ID（ECLI 形式）・判例キー・判例IDの URI |
| `method`・`confidence`・`candidates` | 決め方・確かさ（高・中・低）・決まらないときの候補 |

誤り: テキストが無い・長すぎる・`min_confidence` が違うときは 400 と `{"error": …}`。設定が無ければ 404。

## 設定（textlink:）

```yaml
- textlink:
    module: caselinker            # make_linker(options) を持つモジュール（パッケージに kgraphnavi があればそれ）
    path: ~/nii/hanrei            # モジュールを探すフォルダ（pip で入れたなら不要）
    index: ~/nii/hanrei/data/release/caselink-index.sqlite   # モジュールに渡す索引
    title: 判例リンク             # 画面の見出し・上端の入り口の名前
    min_confidence: 低            # 既定の確かさの下限（高・中・低）
    max_chars: 200000             # テキストの長さの上限
    cors: "*"                     # /api/textlink の Access-Control-Allow-Origin（別のサイトから呼ぶとき）
    options: {}                   # そのほかモジュールに渡す値
    labels:                       # 画面の文言（既定はモジュールの LABELS）
      nav_tip: 上端の入り口のツールチップ
      # description・placeholder・item（見つけたものの呼び名）・key・id・in_data（表の列名。空にするとその列を出さない）・legend
```

`path`・`index` の相対パスは設定ファイルのフォルダから。手元のパスなので、`caselaw.local.yaml` に書きます（`config/local.yaml.example`）。
モジュールは初めて使うときに読み込みます（索引の読み込みに数秒）。

## ほかのリンカをつなぐ

`make_linker(options)` が、関数 `run(text, min_confidence)` を返せば使えます。`run` は引用ごとに辞書
（`start`・`end`・`text` は必須。`linked`・`target` があればリンクにする。ほかの項目は任意）のリストを返します。
`run.meta` に索引の情報を置くと、画面と API に出ます。法令の条の参照など、判例以外のリンカにも使えます。

## ラベルの辞書のリンカ（kgraphnavi.labellinker）

知識グラフのラベル（と別名）を SPARQL で集めて辞書（SQLite）にし、テキストの中を最長一致で探します。
英数字の語は語の境目で切れるものだけ、漢字・かなは境目を見ません。全角・半角、大文字・小文字の違いは無視します
（全部大文字の短い語 NASA・US などは区別）。テキストは手元だけで処理します。

| 確かさ | 場合 |
|---|---|
| 高 | ラベルにあたるリソースが1つだけ |
| 中 | 同じラベルのリソースが複数で、重み（`?score`）が2番目の2倍以上のものを選んだ。または1つだけだが短い語 |
| 低 | 同じラベルのリソースが複数で決め手が無い（重みの大きいものを選び、候補を出す）。短い語で候補が複数 |

設定（dbpedia.yaml の例）:

```yaml
- textlink:
    module: kgraphnavi.labellinker
    index: ../data/dbpedia-labels.sqlite      # 辞書
    options:
      min_length: 3                           # これより短い英数字のラベルは使わない
      min_length_cjk: 2                       # 漢字・かなのラベル
      stopwords: [The, Mount, Island]         # 結ばない語
      page_size: 10000                        # SPARQL の1回の行数（LIMIT/OFFSET で繰り返す。query には ORDER BY を）
      queries:                                # ?s ?label（必須）と ?score（重み）を返す SELECT。name は決め方に出る
        - name: 山
          query: |
            SELECT ?s ?label ?score WHERE {
              ?s a dbo:Mountain ; rdfs:label ?label . FILTER(lang(?label) IN ("en", "ja"))
              OPTIONAL { ?s dbo:wikiPageLength ?score }
            } ORDER BY ?s ?label
```

辞書を作る・試す:

```
python3 -m kgraphnavi.labellinker build config/dbpedia.yaml                 # sparql_endpoint から（数分）
python3 -m kgraphnavi.labellinker build config/dbpedia.yaml --tsv labels.tsv  # TSV（uri, label, score[, name]）から
python3 -m kgraphnavi.labellinker link config/dbpedia.yaml "Mount Fuji is the highest mountain in Japan."
```

辞書に入れる範囲は、知識グラフ全体ではなく、設定のページで見せたい種類（DBpedia のサンプルでは山・山脈・国・初登頂した人）に絞ります。
範囲を広げるほど、普通の語（Bear・Table・Chad など、山や国の名前でもある語）を誤って結ぶことが増えるので、`stopwords` で外します。
