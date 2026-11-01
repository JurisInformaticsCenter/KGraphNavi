"""決まった文字列のリンク（string: "本文の判断へ"）は、リンク先が無ければ出さない（2026.11.1）"""
from kgraphnavi.render_utils import get_item_data

COLUMN = {"id": "jump", "type": "directlink", "string": "本文の判断へ"}


def test_directlink_with_target():
    _, cell = get_item_data(COLUMN, {"jump": {"type": "literal", "value": "/data/2020/092922_hanrei.html#:~:text=x"}})
    assert cell["value"] == "本文の判断へ"
    assert cell["href"]


def test_directlink_without_target_is_empty():
    _, cell = get_item_data(COLUMN, {})
    assert cell["value"] == ""
    _, cell = get_item_data(COLUMN, {"jump": {"type": "literal", "value": ""}})
    assert cell["value"] == ""


def test_literal_string_is_kept():
    _, cell = get_item_data({"id": "x", "type": "literal", "string": "固定"}, {})
    assert cell["value"] == "固定"
