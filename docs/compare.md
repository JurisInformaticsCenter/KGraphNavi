# 列に並べて比べる（/compare。2026.10.26）

少数（2〜4）のリソースを縦の列に並べ、同じ種類の情報を横にそろえて比べる。判例に限らない仕組みで、
判例の比べ方は設定ファイル（config/caselaw.yaml の `compare:`）に書く。

## 入口
- `/compare?uri=A&uri=B[&uri=C…]` … リソースを直接
- `/compare?from=<ガジェット>&uri=X` … ガジェットの一覧と X（判例では AppealCaseLaw の「審級を並べて比べる」）
- コレクションのページ … 一覧の「比べる」の列で選び（4件まで。ページ送りしても残る）、上の「並べて比べる」。
  要素 ?entity の一覧の表（htable）に自動で付く。付けたくない表は show に `select: false`
- `/compare?saved=<名前>` … 保存したコレクション（2〜4件のとき一覧に「比べる」）
- `&view=<比べ方>` … 比べ方を選ぶ（`_properties` は組み込みの「プロパティごと」）

## 比べ方の設定
```yaml
-   compare:
        - name: 判例
          types: [caselawo:CaseLawDocument, …]   # このクラスのリソースに使う
          sort: "select ?k where {…$uri…}"       # 列の並び（小さい順。判例は判決日）
          max: 4
          rows:
              - gadget: CaseLawInfo              # 各列にそのガジェットの表
                columns: [court, judgmentdate, result]
              - gadget: Legislation              # 値で行をそろえた表（全部にない行は色付け）
                align: legislation
                label: label
                value: status
```
ガジェットに `compare: {var: doc, label: …}` を書くと、そのガジェットに「並べて比べる」ボタンが付く。
比べ方の無いクラスでは、組み込みの比べ方（プロパティごとに値を並べ、違う値を色付け）を使う。

## 試した例（3審）
- 090298（最高裁 2021-05-17、建設アスベスト）← 087255（東京高裁）← 082464（横浜地裁）
- 093839（最高裁 2025-03-03、特許）← 092146（知財高裁）← 091124（東京地裁）

## ToDo
- 争点の対応付け: 審級で争点の見出しが違う（最高裁は判示事項の項目）ので、ラベルではそろわない。語の重なりで対応を付ける
- 結果（請求認容→控訴棄却→破棄差戻 など）の流れを1行で見せる
