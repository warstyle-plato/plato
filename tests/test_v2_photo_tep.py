from developaid_v2_upgrade import _parse_number, parse_tep_text


TEP_BLOCK = {
    "kind": "tep",
    "rows": [
        {
            "key": "apartments",
            "label": "Квартиры",
            "fields": [
                {"key": "gns", "label": "ГНС"},
                {"key": "total_area", "label": "Общая площадь"},
                {"key": "useful", "label": "Полезная"},
                {"key": "saleable", "label": "Продаваемая"},
                {"key": "transfer", "label": "Передаётся городу"},
                {"key": "units", "label": "Количество"},
            ],
        },
        {
            "key": "ground_commercial",
            "label": "Коммерция 1 этажа",
            "fields": [
                {"key": "gns", "label": "ГНС"},
                {"key": "total_area", "label": "Общая площадь"},
                {"key": "useful", "label": "Полезная"},
                {"key": "saleable", "label": "Продаваемая"},
                {"key": "transfer", "label": "Передаётся городу"},
                {"key": "units", "label": "Количество"},
            ],
        },
    ],
}


def test_photo_number_accepts_thousands_with_dot_or_comma():
    assert _parse_number("5.000") == 5000
    assert _parse_number("5,000") == 5000
    assert _parse_number("5 000") == 5000


def test_photo_tep_keeps_table_columns_and_ignores_digit_in_label():
    text = """Наименование   ГНС   Общая площадь   Полезная   Продаваемая   Передается городу   Количество
Квартиры   130 000   117 000   80 000   80 000   5 000   1362
Коммерция 1 этажа   9 664   8 695   7 826   7 826   0   0
"""
    parsed = parse_tep_text(text, TEP_BLOCK)
    values = {
        (row["row_key"], row["field_key"]): row["value"]
        for row in parsed["suggestions"]
    }
    assert parsed["recognized_rows"] == 2
    assert values[("apartments", "gns")] == 130000
    assert values[("apartments", "transfer")] == 5000
    assert values[("apartments", "units")] == 1362
    assert values[("ground_commercial", "gns")] == 9664
    assert values[("ground_commercial", "saleable")] == 7826
