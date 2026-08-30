"""Графики колоды одеты по продукту, а не оставлены заводскими.

«PPT убогие графики очень, как для первого класса школы» (владелец,
30.08.2026) — и это была правда: столбик во всю ширину слота офисной синевы,
сетка по всему полю, ось со значениями, подписи заводским шрифтом, таблицы в
синюю полоску.

Правила взяты не с потолка: один ряд — легенды нет, её работу делает заголовок
слайда; текст носит текстовые токены, а не цвет ряда; значения стоят прямо на
столбиках, пока их немного, и тогда сетка с осью — лишняя краска; столбик не
заполняет слот. Цвет — фирменный синий кабинета, и он проверен валидатором
палитры (светлота, насыщенность, контраст к белому).

Запуск: python3 -m pytest tests/test_the_deck_charts_are_not_factory_default.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import sales_deck  # noqa: E402

pptx = pytest.importorskip("pptx")


def deck(categories: int):
    head = ["Месяц", "млн ₽"]
    rows = [[f"2026-{month + 1:02d}", str(100 + month)] for month in range(categories)]
    pages = [{"title": "Динамика", "note": "Темп растёт.",
              "tables": [{"head": head, "rows": rows}], "lines": []}]
    raw = sales_deck.build(pages, title="Продажи", subtitle="срез", footer="DevelopAid")
    return pptx.Presentation(io.BytesIO(raw))


def charts(presentation):
    return [shape.chart for slide in presentation.slides for shape in slide.shapes
            if getattr(shape, "has_chart", False) and shape.has_chart]


def tables(presentation):
    return [shape.table for slide in presentation.slides for shape in slide.shapes
            if getattr(shape, "has_table", False) and shape.has_table]


def test_the_bar_wears_the_product_colour_not_the_office_blue() -> None:
    chart = charts(deck(6))[0]
    series = chart.plots[0].series[0]
    assert str(series.format.fill.fore_color.rgb) == "1367AE", "фирменный синий кабинета"
    # Обводки у столбика нет: рамка вокруг метки — краска, которая не данные.
    assert series.format.line.fill.type is not None


def test_one_series_has_no_legend() -> None:
    """Легенда из одной строки повторяет заголовок слайда и ест место."""
    assert charts(deck(6))[0].has_legend is False


def test_few_columns_carry_their_values_and_drop_the_grid() -> None:
    chart = charts(deck(5))[0]
    plot = chart.plots[0]
    assert plot.has_data_labels is True
    assert chart.value_axis.has_major_gridlines is False
    assert chart.value_axis.visible is False, "ось со значениями рядом с подписями — лишняя"


def test_many_columns_drop_the_labels_and_keep_a_hairline_grid() -> None:
    """Число на каждом столбике — хаос, когда столбиков тринадцать."""
    chart = charts(deck(13))[0]
    assert chart.plots[0].has_data_labels is False
    assert chart.value_axis.has_major_gridlines is True
    assert chart.value_axis.visible is True
    line = chart.value_axis.major_gridlines.format.line
    assert str(line.color.rgb) == "E3EBF2", "сетка волосяная и отступает на второй план"


def test_the_column_does_not_fill_its_slot() -> None:
    """Столбик во всю ширину слота и есть то самое «как для первого класса»."""
    assert charts(deck(3))[0].plots[0].gap_width >= 400
    assert charts(deck(6))[0].plots[0].gap_width >= 250
    assert charts(deck(14))[0].plots[0].gap_width <= 100, "тринадцати столбикам нужен воздух поуже"


def test_the_text_does_not_wear_the_data_colour() -> None:
    chart = charts(deck(5))[0]
    assert str(chart.font.color.rgb) == "5B6B7D"
    labels = chart.plots[0].data_labels
    assert str(labels.font.color.rgb) == "16202B"
    assert labels.number_format == "#,##0.#" and labels.number_format_is_linked is False


def test_the_table_is_not_blue_striped() -> None:
    grid = tables(deck(5))[0]
    assert grid.first_row is True and grid.horz_banding is False
    assert str(grid.cell(0, 0).fill.fore_color.rgb) == "F4F7FA", "шапка на светлой подложке"
    assert str(grid.cell(1, 0).fill.fore_color.rgb) == "FFFFFF"


def test_numbers_stand_to_the_right() -> None:
    """Колонка чисел, прижатая влево, не читается столбиком."""
    from pptx.enum.text import PP_ALIGN

    grid = tables(deck(5))[0]
    value = grid.cell(1, 1)
    assert value.text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
    assert grid.cell(1, 0).text_frame.paragraphs[0].alignment != PP_ALIGN.RIGHT


def test_sibling_labels_do_not_glue_into_one_word() -> None:
    """«факт, млн ₽цена квартир, ₽/м²» — так это выглядело на слайде.

    Подписи легенды и полос лежат соседними `span` без пробела между ними:
    браузер разводит их отступом, разбор склеивал в одно слово. Разделитель
    ставится только между соседями одного уровня — `span` внутри строки
    разбивать нечего.
    """
    html = ('<section class="salesblock"><h2>Динамика</h2>'
            '<div class="muted"><span><span></span>факт, млн ₽</span>'
            '<span><span></span>цена квартир, ₽/м²</span></div>'
            '<p>Внутри строки <span class="muted">пояснение</span> не рвётся.</p>'
            '</section>')
    lines = sales_deck.sections(html)[0]["lines"]
    assert "факт, млн ₽ · цена квартир, ₽/м²" in lines
    assert "Внутри строки пояснение не рвётся." in lines


def test_a_fold_label_is_not_content() -> None:
    """«Помесячно числами» — подпись сворачивалки, и на слайде она сирота."""
    html = ('<section class="salesblock"><h2>Продукты</h2>'
            '<details><summary>Продукты числами</summary>'
            '<table><thead><tr><th>Что</th><th>Сколько</th></tr></thead>'
            '<tbody><tr><td>Квартира</td><td>56</td></tr>'
            '<tr><td>Паркинг</td><td>14</td></tr></tbody></table></details></section>')
    page = sales_deck.sections(html)[0]
    assert "Продукты числами" not in page["lines"]
    assert page["tables"], "таблица под сворачивалкой при этом обязана остаться"


def test_a_section_without_words_does_not_get_an_empty_slide() -> None:
    """«Расторжения» шли листом, на котором стоял один заголовок."""
    from pptx import Presentation
    import io

    html = ('<section class="salesblock"><h2>Расторжения</h2>'
            '<table><thead><tr><th>Месяц</th><th>млн ₽</th></tr></thead>'
            '<tbody><tr><td>2026-05</td><td>12,0</td></tr>'
            '<tr><td>2026-06</td><td>3,5</td></tr></tbody></table></section>')
    deck = Presentation(io.BytesIO(sales_deck.build(
        sales_deck.sections(html), title="Т", subtitle="с", footer="ф")))
    for slide in deck.slides:
        filled = [shape for shape in slide.shapes
                  if shape.has_chart or shape.has_table
                  or (shape.has_text_frame and shape.text_frame.text.strip())]
        # Заголовок и номер — не содержание: лист, кроме них, обязан что-то нести.
        assert len(filled) > 2, "слайд с одним заголовком и номером"


def test_the_reader_is_told_once_not_on_every_chart() -> None:
    """Сноска под каждым графиком повторялась двадцать раз и стала шумом."""
    source = (ROOT / "market_search" / "sales_deck.py").read_text(encoding="utf-8")
    assert source.count("правятся в PowerPoint") == 1


def test_the_price_per_metre_rides_as_a_line_not_its_own_slide() -> None:
    """«И линия цены метра то должна быть на этих графиках» (владелец,
    30.08.2026).

    Правило про цену уже записано: «цена — всегда линия на своей шкале, а не
    вкладка со столбиками». В колоде она уходила своим слайдом со столбиками —
    то же самое другими словами: смотрят на объём, а цена в это время на
    соседнем листе. Теперь она идёт линией справа на каждом графике объёма, а
    своим слайдом остаётся, только если объёма рядом нет вовсе.
    """
    table = {"head": ["Месяц", "Лотов", "млн ₽", "₽/м²"],
             "rows": [["2026-07", "4", "140,8", "712 747"],
                      ["2026-06", "9", "301,2", "717 000"],
                      ["2026-05", "9", "288,0", "705 100"]]}
    drawn = sales_deck.charts(table)
    assert [item["name"] for item in drawn] == ["Лотов", "млн ₽"], \
        "цена больше не заводит своего слайда со столбиками"
    assert all(item["line"]["name"] == "₽/м²" for item in drawn)
    # Одна цена без объёма — сама себе график: показать её иначе нечем.
    alone = sales_deck.charts({"head": ["Месяц", "₽/м²"],
                               "rows": [["2026-07", "712 747"], ["2026-06", "717 000"]]})
    assert [item["name"] for item in alone] == ["₽/м²"]
    assert "line" not in alone[0]


def test_the_price_line_is_a_real_line_on_its_own_axis() -> None:
    """Комбинированный график собирается правкой XML, и порядок в нём строгий.

    Все группы графиков обязаны стоять раньше всех осей: линия, приписанная в
    конец области, встаёт после осей — PowerPoint такой файл не открывает
    вовсе, а python-pptx, LibreOffice и схема его читают и молчат.
    """
    import io
    import zipfile

    from lxml import etree
    from pptx import Presentation
    from pptx.chart.xmlwriter import ChartXmlWriter  # noqa: F401  (проверка окружения)

    html = ('<section class="salesblock"><h2>Динамика</h2>'
            '<table><thead><tr><th>Месяц</th><th>млн ₽</th><th>₽/м²</th></tr></thead>'
            '<tbody><tr><td>2026-07</td><td>140,8</td><td>712 747</td></tr>'
            '<tr><td>2026-06</td><td>301,2</td><td>717 000</td></tr>'
            '<tr><td>2026-05</td><td>288,0</td><td>705 100</td></tr>'
            '</tbody></table></section>')
    blob = sales_deck.build(sales_deck.sections(html),
                            title="Т", subtitle="с", footer="ф")

    deck = Presentation(io.BytesIO(blob))
    found = [shape.chart for slide in deck.slides for shape in slide.shapes
             if shape.has_chart]
    assert found, "график не нарисовался вовсе"
    chart = found[0]
    kinds = [type(plot).__name__ for plot in chart.plots]
    assert "BarPlot" in kinds and "LinePlot" in kinds, kinds
    assert chart.has_legend, "два ряда без легенды неразличимы"

    namespace = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    with zipfile.ZipFile(io.BytesIO(blob)) as pack:
        part = next(name for name in pack.namelist()
                    if name.startswith("ppt/charts/chart"))
        area = etree.fromstring(pack.read(part)).find(".//c:plotArea", namespace)
    order = [etree.QName(child).localname for child in area]
    groups = [index for index, name in enumerate(order) if name.endswith("Chart")]
    axes = [index for index, name in enumerate(order) if name.endswith("Ax")]
    assert max(groups) < min(axes), f"оси встали раньше групп: {order}"
    # Своя шкала справа, и её деления видны: урезанная шкала обязана назваться.
    right = [ax for ax in area.findall("c:valAx", namespace)
             if ax.find("c:axPos", namespace).get("val") == "r"]
    assert right, "у цены нет своей шкалы справа"
    assert right[0].find("c:delete", namespace).get("val") == "0"
