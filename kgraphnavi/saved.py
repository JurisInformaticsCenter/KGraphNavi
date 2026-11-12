#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      saved.py
##  Description:
##      名前を付けて保存したコレクション（2026.10.19）
##
##  コレクションの要素（URI）を、名前を付けて JSON ファイルに保存する（その時点の内容の写し）。
##  保存したコレクションは /collection?saved=<名前> で読み込み、ファセットでさらに絞り込める。
##  複数の保存したコレクションを和（マージ）・積・差で1つにまとめて、新しい名前で保存できる。
##
##  ファイル: <保存先>/<名前>.json
##      {"name": 名前, "created": 作成日時, "source": 元のページのURL, "class": 要素のクラス（無ければ null）,
##       "count": 要素の数, "uris": [URI, ...], "merged_from": [名前, ...]（まとめたもの）, "operation": union|intersect|minus}
"""

import json
import os
import re
import datetime
from pathlib import Path

from .errors import CollectionError

# 保存できる要素の数の既定の上限（設定 saved_collection_max）
DEFAULT_SAVE_MAX = 10000
OPERATIONS = {
    "union": "和（どれかに含まれる）",
    "intersect": "積（すべてに含まれる）",
    "minus": "差（最初のものから、残りに含まれるものを除く）",
}
NAME_PATTERN = re.compile(r"[\w\-ー・（）()]{1,60}")


def check_name(name):
    """保存の名前として使えるか（文字・数字・_-ー・括弧の60字まで）。前後の空白は除く"""
    name = (name or "").strip()
    if not NAME_PATTERN.fullmatch(name):
        raise CollectionError("名前には、文字・数字と _ - ー ・ ( ) だけを使ってください（60字まで）")
    return name


class SavedCollectionStore:
    """保存したコレクションの置き場所（フォルダ）"""

    def __init__(self, folder):
        self.folder = Path(folder)

    def _path(self, name):
        return self.folder / f"{check_name(name)}.json"

    def names(self):
        if not self.folder.is_dir():
            return []
        return sorted(p.stem for p in self.folder.glob("*.json"))

    def list(self):
        """保存したコレクションの一覧（要素の URI は含めない）。新しいものから"""
        items = []
        for name in self.names():
            try:
                data = self.get(name)
            except CollectionError:
                continue
            items.append({k: v for k, v in data.items() if k != "uris"})
        return sorted(items, key=lambda d: d.get("created", ""), reverse=True)

    def exists(self, name):
        return self._path(name).is_file()

    def get(self, name):
        path = self._path(name)
        if not path.is_file():
            raise CollectionError(f"保存したコレクション「{name}」はありません")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise CollectionError(f"保存したコレクション「{name}」を読めません: {e}")
        data.setdefault("name", name)
        data.setdefault("uris", [])
        data["count"] = len(data["uris"])
        return data

    def save(self, name, uris, *, source=None, class_uri=None, extra=None, overwrite=False):
        name = check_name(name)
        if self.exists(name) and not overwrite:
            raise CollectionError(f"「{name}」という名前のコレクションはもうあります（上書きするには「上書き」を選んでください）")
        uris = list(dict.fromkeys(uris))
        data = {
            "name": name,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "class": class_uri,
            "count": len(uris),
            "uris": uris,
        }
        data.update(extra or {})
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(name)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return data

    def delete(self, name):
        path = self._path(name)
        if path.is_file():
            path.unlink()

    def merge(self, names, new_name, operation="union", overwrite=False):
        """保存したコレクションを和・積・差でまとめて、new_name で保存する"""
        if operation not in OPERATIONS:
            raise CollectionError(f"未対応のまとめ方です: {operation}")
        names = [check_name(n) for n in names if n and n.strip()]
        if len(names) < 2:
            raise CollectionError("まとめるコレクションを2つ以上選んでください")
        collections = [self.get(n) for n in names]
        sets = [c["uris"] for c in collections]
        if operation == "union":
            uris = list(dict.fromkeys(u for s in sets for u in s))
        elif operation == "intersect":
            rest = [set(s) for s in sets[1:]]
            uris = [u for u in sets[0] if all(u in r for r in rest)]
        else:
            rest = set(u for s in sets[1:] for u in s)
            uris = [u for u in sets[0] if u not in rest]
        classes = {c.get("class") for c in collections}
        class_uri = classes.pop() if len(classes) == 1 else None
        return self.save(new_name, uris, class_uri=class_uri, overwrite=overwrite,
                         extra={"merged_from": names, "operation": operation})
