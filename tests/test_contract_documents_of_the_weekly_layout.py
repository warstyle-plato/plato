"""Расчёт и ГПР договора в другой раскладке: шапка расчёта словами и график по неделям.

Документы рисуются здесь же, с выдуманными номерами, суммами и работами:
репозиторий публичный, а договоры владельца — нет. Нарисовано то, на чём
ломался разбор живых документов этой раскладки: шапка расчёта без строки с
номерами граф, суммы со знаком рубля и точкой, итоги «По разделу», раздел без
номера над группами, заголовок с объёмом, но без стоимости, даты договора и
соглашения словами под заголовком, график без граф дат, где скрыты месяцы
между показанными, полоса объединённой ячейки на несколько строк, две полосы
одной строки, страница продолжения без заголовка, синяя заливка шапки поверх
первой строки. Каждая особенность проверяется и обратным ходом: без её
обработки разбор обязан ошибиться.
"""
from __future__ import annotations

import pytest

import developaid_contract_documents as documents
from tests.test_contract_documents_are_read_from_their_tables import _page, _table, _text, pymupdf

COLUMNS = (40, 80, 300, 340, 390, 450, 510, 570, 640, 710, 790)
SPLIT = 120  # линейка внутри графы наименования: название в двух ячейках
LABELS = ("№", "Наименование", "Ед. изм.", "Кол-во", "Цена мат.", "Цена раб.", "Цена всего",
          "Сумма мат.", "Сумма раб.", "Сумма всего")
TITLE = ("Приложение № 1 к Дополнительному соглашению № 3",
         "к Договору подряда № 7-ТСТ от 16.03.2026",
         "г. Москва «22» июня 2026 г.",
         "Расчёт договорной стоимости")
ROWS = [
    ("", "Корпус 1 этаж 1-9") + ("",) * 8,
    ("1", "Устройство фасадов") + ("",) * 8,
    ("1.1", "(Ф1) Облицовка панелями", "м2", "100.00", "", "", "50.00 ₽", "", "", "5 000.00 ₽"),
    # Заголовок с объёмом своих работ, без стоимости: стоимость — у этапов под ним.
    ("2", "Монтаж витражей") + ("",) * 8,
    ("2.1", "(В-3) Витражная система", "м2", "10.00") + ("",) * 6,
    ("2.1.1", "В-3. Монтаж каркаса", "м2", "10.00", "", "", "100.00 ₽", "", "", "1 000.00 ₽"),
    ("2.1.2", "В-3. Остекление", "м2", "10.00", "", "", "200.00 ₽", "", "", "2 000.00 ₽"),
    ("", "По разделу Корпус 1 этаж 1-9", "", "", "", "", "", "", "", "8 000.00 ₽"),
    ("", "Корпус 2 этаж 1-7") + ("",) * 8,
    ("3", "Ограждения") + ("",) * 8,
    ("3.1", "Ограждение балконов", "м", "20.00", "", "", "100.00 ₽", "", "", "2 000.00 ₽"),
    ("", "По разделу Корпус 2 этаж 1-7", "", "", "", "", "", "", "", "2 000.00 ₽"),
    ("", "ВСЕГО по расчёту", "", "", "", "", "", "", "", "10 000.00 ₽"),
]


def labelled_estimate_pdf(rows=ROWS, header=LABELS, title=TITLE, second=()):
    document = pymupdf.open()
    page = _page(document)
    for n, line in enumerate(title):
        _text(page, 40, 30 + 12 * n, line)
    edges = _table(page, [header] + list(rows), 90)
    page.draw_line((SPLIT, edges[1]), (SPLIT, edges[-1]), width=0.5)
    if second:
        # Страница продолжения повторяет шапку словами.
        _table(_page(document), [header] + list(second), 60)
    return document.tobytes()


def test_an_estimate_with_a_header_in_words_reads_its_sections_groups_and_ruble_sums():
    result = documents.read(labelled_estimate_pdf())
    # Дата соглашения — словами в строке под заголовком, после названного договора.
    assert result["contract"] == {"number": "7-ТСТ", "date": "2026-03-16"}
    assert result["agreement"] == {"number": "3", "date": "2026-06-22"}
    (estimate,) = result["estimates"]
    assert estimate["warnings"] == []
    got = [(p["number"], p["name"], p["amount"]["total"], p["section"], (p["group"] or {}).get("number"))
           for p in estimate["positions"]]
    assert got == [("1.1", "(Ф1) Облицовка панелями", 5000.0, "Корпус 1 этаж 1-9", "1"),
                   ("2.1.1", "В-3. Монтаж каркаса", 1000.0, "Корпус 1 этаж 1-9", "2.1"),
                   ("2.1.2", "В-3. Остекление", 2000.0, "Корпус 1 этаж 1-9", "2.1"),
                   ("3.1", "Ограждение балконов", 2000.0, "Корпус 2 этаж 1-7", "3")]
    assert estimate["positions"][1]["group"]["name"] == "(В-3) Витражная система"
    assert [(t["amount"], t["section"]) for t in estimate["totals"]] == [
        (8000.0, "Корпус 1 этаж 1-9"), (2000.0, "Корпус 2 этаж 1-7"), (10000.0, None)]


def test_a_continuation_page_repeating_the_header_in_words_reads_on():
    whole = documents.read(labelled_estimate_pdf())["estimates"][0]
    (split,) = documents.read(labelled_estimate_pdf(ROWS[:8], second=ROWS[8:]))["estimates"]
    assert split["warnings"] == [] and split["pages"] == [1, 2]
    assert split["positions"] == [{**p, "page": 2 if p["number"] == "3.1" else 1} for p in whole["positions"]]


def test_without_the_header_in_words_the_estimate_is_not_found():
    unnamed = ("№",) + ("",) * 9
    result = documents.read(labelled_estimate_pdf(header=unnamed))
    assert result["estimates"] == []
    assert any("Расчёт договорной стоимости упомянут" in w for w in result["warnings"])


def test_a_volume_heading_groups_the_stages_numbered_under_it_not_the_last_heading():
    # Этап 2.1.3 стоит после заголовка 2.2, но пронумерован под 2.1.
    rows = ROWS[:7] + [("2.2", "(В-8) Витражная система", "м2", "5.00") + ("",) * 6,
                       ("2.1.3", "В-3. Отделка", "м2", "10.00", "", "", "0.00 ₽", "", "", "0.00 ₽")] + ROWS[7:]
    positions = documents.read(labelled_estimate_pdf(rows))["estimates"][0]["positions"]
    assert {p["number"]: p["group"]["number"] for p in positions}["2.1.3"] == "2.1"


def test_a_title_without_a_number_over_positions_heads_them_and_names_no_section():
    free = ("4.1", "Разные работы", "шт", "1.00", "", "", "0.00 ₽", "", "", "0.00 ₽")
    roof = ("5.1", "Кровля плоская", "м2", "1.00", "", "", "0.00 ₽", "", "", "0.00 ₽")
    rows = ROWS[:11] + [("", "Прочие работы") + ("",) * 8, free, ("5", "Кровля") + ("",) * 8, roof] + ROWS[11:]
    positions = {p["number"]: p for p in documents.read(labelled_estimate_pdf(rows))["estimates"][0]["positions"]}
    assert positions["4.1"]["group"] == {"number": "", "name": "Прочие работы"}
    # Заголовок над позициями — их группа, а не раздел следующих групп.
    assert (positions["5.1"]["group"]["number"], positions["5.1"]["section"]) == ("5", "Корпус 2 этаж 1-7")


def test_a_contract_titled_for_its_work_takes_the_date_under_the_title():
    title = ("ДОГОВОР ПОДРЯДА № 7-ТСТ на выполнение фасадных работ", "г. Москва «16» марта 2026 г.",
             "Расчёт договорной стоимости")
    result = documents.read(labelled_estimate_pdf(title=title))
    assert result["contract"] == {"number": "7-ТСТ", "date": "2026-03-16"} and result["agreement"] is None


# --- ГПР по неделям -------------------------------------------------------------

WEEK_COLUMNS = (30, 50, 230, 280) + tuple(280 + 30 * n for n in range(1, 7))
# Показаны январь и июль: месяцы между ними в графике скрыты.
WEEKS = (("янв.26", ("5-11", "12-18", "19-25", "26-31")), ("июл.26", ("1-5", "6-12")))
GREEN = (0.3, 0.7, 0.3)
# код, название, полосы (первая и последняя неделя), высота строки
FIRST = (
    ("0", "Подготовительные работы", (), 10),
    ("", "Корпус 1 этаж 1-9", (), 16),
    ("1", "Устройство фасадов", (), 16),
    ("1.1", "(Ф1) Облицовка панелями", ((0, 1),), 16),
    ("1.2", "(Ф2) Штукатурка", ((0, 0), (4, 4)), 16),
    ("2", "Монтаж витражей", (), 16),
    ("2.1", "(В-3) Витражная система", ((2, 3),), 16),
    ("2.1.1", "Оконный блок витражной системы В-3", ((3, 5),), 16),
    ("", "Итого по корпусу 1", (), 16),
)
SECOND = (
    ("", "Корпус 2 этаж 1-7", (), 16),
    ("3", "Ограждения", (), 16),
    ("3.1", "Ограждение балконов", "merged", 16),
    ("3.2", "Ограждение лоджий", "merged", 16),
    ("3.3", "Ограждение кровли", "merged", 16),
    ("", "Итого по корпусу 2", (), 16),
    # Строка после итога корпуса этому корпусу не принадлежит.
    ("4", "Благоустройство территории", ((5, 5),), 16),
)
MERGED = (4, 5)


def _week_table(page, lines, top):
    columns = WEEK_COLUMNS
    edges = [top]
    for *_, height in lines:
        edges.append(edges[-1] + height)
    for y in edges:
        page.draw_line((columns[0], y), (columns[-1], y), width=0.5)
    for x in columns:
        page.draw_line((x, edges[0]), (x, edges[-1]), width=0.5)
    merged = [index for index, line in enumerate(lines) if line[2] == "merged"]
    if merged:
        page.draw_rect(pymupdf.Rect(columns[3 + MERGED[0]], edges[merged[0]], columns[4 + MERGED[1]],
                                    edges[merged[-1] + 1]), color=None, fill=GREEN)
    for index, (code, name, bars, height) in enumerate(lines):
        y0, y1 = edges[index], edges[index + 1]
        for first, last in (bars if bars != "merged" else ()):
            page.draw_rect(pymupdf.Rect(columns[3 + first] + 1, y0 + 3, columns[4 + last] - 1, y1 - 3),
                           color=None, fill=GREEN)
        for column, text in enumerate((code, name)):
            if text:
                _text(page, columns[column] + 2, y0 + min(11, height - 2), text)
    return edges


def weekly_pdf(first=FIRST, second=SECOND, weeks=WEEKS, header_fill=True, over=None):
    document = pymupdf.open()
    page = _page(document)
    _text(page, 30, 30, "Приложение № 2 к Дополнительному соглашению № 3")
    _text(page, 30, 42, "График производства работ")
    columns, top = WEEK_COLUMNS, 60
    page.draw_line((columns[0], top), (columns[-1], top), width=0.5)
    # Месяцы и недели — одна строка шапки: делящая их линейка не доходит до графы номера.
    page.draw_line((columns[3], top + 18), (columns[-1], top + 18), width=0.5)
    for x in columns:
        page.draw_line((x, top), (x, top + 36), width=0.5)
    for text, x in (("№", 0), ("Наименование работ", 1), ("Примечание", 2)):
        _text(page, columns[x] + 2, top + 14, text)
    column = 3
    for month, ranges in weeks:
        # `over` ставит подпись месяца над чужими неделями: {месяц: графа}.
        x = columns[(over or {})[month]] + 2 if month in (over or {}) else (
            columns[column] + columns[column + len(ranges)]) / 2 - 10
        _text(page, x, top + 12, month)
        for week in ranges:
            _text(page, columns[column] + 4, top + 30, week)
            column += 1
    edges = _week_table(page, first, top + 36)
    if header_fill:
        # Синяя заливка месяцев доходит до низа тонкой первой строки.
        page.draw_rect(pymupdf.Rect(columns[3], top, columns[-1], edges[1]), color=None, fill=(0.6, 0.8, 1))
    page = _page(document)
    _week_table(page, second, 40)
    return document.tobytes()


def _lines(data=None):
    schedule = documents.read(data or weekly_pdf())["schedule"]
    return schedule, {line["code"]: line for line in schedule["lines"]}


def test_a_weekly_chart_dates_each_line_by_its_weeks_across_hidden_months():
    schedule, lines = _lines()
    assert schedule["pages"] == [1, 2] and schedule["assumption"] == documents.WEEKS_ASSUMPTION
    assert list(lines) == ["0", "1", "1.1", "1.2", "2", "2.1", "2.1.1", "3", "3.1", "3.2", "3.3", "4"]
    spans = {code: (line["start"], line["finish"]) for code, line in lines.items()}
    assert spans["1.1"] == ("2026-01-05", "2026-01-18")
    # Две полосы одной строки — этапы одной работы: срок от первой до последней.
    assert spans["1.2"] == ("2026-01-05", "2026-07-05")
    assert spans["2.1.1"] == ("2026-01-26", "2026-07-12")
    # Полоса объединённой ячейки — полоса каждой строки под ней, и на странице продолжения.
    assert spans["3.1"] == spans["3.2"] == spans["3.3"] == ("2026-07-01", "2026-07-12")
    assert (lines["1"]["dates_from"], spans["1"]) == ("works", ("2026-01-05", "2026-07-05"))
    assert all(line["dates_from"] == "bar" and line["cells"] == {"start": None, "finish": None}
               for code, line in lines.items() if code not in ("0", "1", "2", "3", "4"))


def test_a_header_fill_over_the_first_row_is_not_its_bar():
    schedule, lines = _lines()
    assert lines["0"]["bar"] is None
    assert any("у строки 0 «Подготовительные работы» нет дат" in w for w in schedule["warnings"])
    _, plain = _lines(weekly_pdf(header_fill=False))
    assert {c: (x["start"], x["finish"]) for c, x in plain.items()} == {
        c: (x["start"], x["finish"]) for c, x in lines.items()}


def test_a_line_with_its_own_bar_is_a_work_even_with_lines_numbered_under_it():
    _, lines = _lines()
    assert (lines["2.1"]["parent"], lines["2.1.1"]["parent"], lines["1.1"]["parent"]) == ("2", "2", "1")
    import developaid_contract_schedule_links as links
    leaves = [line["code"] for line in links.leaves({"lines": list(lines.values())})]
    assert "2.1" in leaves and "2.1.1" in leaves and "2" not in leaves


def test_untitled_rows_name_the_building_of_the_lines_below_and_a_total_does_not():
    _, lines = _lines()
    assert {code: line["section"] for code, line in lines.items()} == {
        "0": None, "1": "Корпус 1 этаж 1-9", "1.1": "Корпус 1 этаж 1-9", "1.2": "Корпус 1 этаж 1-9",
        "2": "Корпус 1 этаж 1-9", "2.1": "Корпус 1 этаж 1-9", "2.1.1": "Корпус 1 этаж 1-9",
        "3": "Корпус 2 этаж 1-7", "3.1": "Корпус 2 этаж 1-7", "3.2": "Корпус 2 этаж 1-7",
        "3.3": "Корпус 2 этаж 1-7", "4": None}


@pytest.mark.parametrize("weeks, problem, over", [
    ((("янв.26", ("5-11", "12-18", "19-25", "26-31", "1-5", "6-12")),), "месяцев 1, отрезков недель 2", None),
    ((("фев.26", ("5-11", "12-18", "19-25", "26-31")), ("июл.26", ("1-5", "6-12"))), "нет недели 26-31", None),
    # Июль подписан над январскими неделями: недели не его, а полосы получили бы чужие месяцы.
    (WEEKS, "не над своими неделями", {"июл.26": 3}),
])
def test_weeks_that_do_not_fit_the_months_leave_the_bars_unread(weeks, problem, over):
    schedule, lines = _lines(weekly_pdf(weeks=weeks, over=over))
    assert any(problem in w and "Полосы графика не прочитаны" in w for w in schedule["warnings"])
    assert all(line["bar"] is None for line in lines.values())
