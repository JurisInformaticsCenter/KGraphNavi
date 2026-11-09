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


def test_display_duration_and_number():
    # 量刑の刑期（xsd:duration）と金額の表示（2026.11.7）
    from kgraphnavi.render_utils import format_duration, format_number, get_item_data
    assert format_duration("P2Y6M") == "2年6月"
    assert format_duration("P30D") == "30日"
    assert format_duration("abc") == "abc"
    assert format_number("30000") == "30,000"
    _, cell = get_item_data({"id": "t", "display": "duration"}, {"t": {"type": "literal", "value": "P1Y2M"}})
    assert cell["value"] == "1年2月"


def test_display_months_days_yen():
    # 量刑の刑期の数に単位を付ける（2026.11.7）
    from kgraphnavi.render_utils import format_months, format_days, format_yen
    assert format_months("5") == "5月"
    assert format_months("24") == "2年"
    assert format_months("30") == "2年6月"
    assert format_days("110") == "110日"
    assert format_yen("3000000") == "3,000,000円"
