"""Книга офисного проекта на каркасе жилой v4 — два пути формулами, сверка с движком.

Образец владельца 22.10.2026 (`docs/samples/office_book/`): «модель должна быть
такой же по философии и архитектуре, как для жилья». Книга считает формулами
оба пути офиса — продажу блоками и аренду с продажей здания, — смету по статьям
и налог на прибыль проекта; «ПРОВЕРКИ» сравнивают каждый итог с движком: оба
пути — с `office_paths`, путь проекта — подробно.

Проверка обязана падать на подделке: формула, статья сметы, вводная, класс
офиса, правило налога и горизонт краснят «ПРОВЕРКИ».

Запуск: python3 -m pytest tests/test_office_workbook.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import office_workbook as ow  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

# Аренда задана числами: умолчания класса B слишком малы, чтобы сценарии
# удержания платили налог и гасили кредит из NOI — а это и проверяется.
OFFICE = dict(offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
              offices_parking_under_spaces=200, offices_parking_over_spaces=40,
              offices_parking_guest_pct=10, offices_rent_th_per_sqm_month=4.5,
              offices_occupancy_stable_pct=92.0, offices_leaseup_months=12,
              offices_opex_pct=18.0, offices_exit_cap_pct=11.0)
RETAIL = dict(retail_enabled=True, retail_gba_sqm=15000.0, retail_saleable_sqm=11000.0)


def _project(nonresidential: bool = True, **over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(OFFICE)
    x.update(over)
    for obj in core.STANDALONE_OBJECTS:
        gba = float(x.get(f"{obj.prefix}_gba_sqm") or 0)
        if not x.get(f"{obj.prefix}_enabled") or gba <= 0:
            continue
        saleable = float(x.get(f"{obj.prefix}_saleable_sqm") or 0)
        t.setdefault(obj.key, {}).update(gns=gba, total_area=round(gba * 0.94, 2),
                                         useful=saleable, saleable=saleable)
    if nonresidential:
        for key in core.MKD_PRODUCTS:
            for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
                if key in t:
                    t[key][col] = 0
        x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
        for key, turnkey in core.OBJECT_SMR_RATE_DEFAULTS.items():
            if key not in over and float(x.get(key) or 0) == turnkey:
                x[key] = core.object_smr_rate(turnkey, x)
    return x, t


VARIANTS = {
    "продажа блоками, продажи до ввода колоколом": dict(
        offices_strategy="direct", offices_direct_sale_offset_months=-6, offices_direct_sale_curve="bell"),
    "аренда и продажа здания, аннуитет": dict(offices_strategy="income"),
    "аренда и удержание, погашение из NOI": dict(offices_strategy="income", offices_exit_mode="hold",
                                                 offices_debt_repayment="sweep"),
    "офис и ТЦ в аренде": dict(offices_strategy="direct", retail_strategy="income", **RETAIL),
    "баллон в срок, участок рассрочкой, сценарий": dict(
        offices_strategy="income", offices_loan_term_years=4, offices_hold_years=8,
        offices_loan_balloon_pct=10, purchase_price_mln=900, purchase_schedule="30%@0; 70%@8",
        land_buyout_mln=120, scenario_cost_multiplier=1.1, scenario_revenue_multiplier=0.9,
        rate_scenario="high"),
}
_BOOKS: dict[str, tuple[bytes, dict]] = {}


def _book(name: str) -> tuple[bytes, dict]:
    if name not in _BOOKS:
        x, t = _project(**VARIANTS[name])
        content, filename, meta = core.build_project_workbook(x, t, [], {}, project_name="Офис")
        assert meta.get("office_book") is True and "офис" in filename, (filename, meta)
        _BOOKS[name] = content, meta
    return _BOOKS[name]


def _evaluate(content: bytes, tamper=None):
    book = openpyxl.load_workbook(io.BytesIO(content))
    if tamper:
        tamper(book)
    evaluator = ow.evaluate(book)
    verdict, bad = ow.verdict(evaluator)
    return verdict, bad, evaluator, book


def _row(sheet, label: str) -> int:
    """Строка по подписи: точное совпадение, иначе первая, что с неё начинается."""
    texts = [(r, str(sheet[f"A{r}"].value or "")) for r in range(1, sheet.max_row + 1)]
    return next((r for r, text in texts if text == label), None) or next(
        r for r, text in texts if text.startswith(label))


def _tampered(name: str, tamper) -> set[str]:
    verdict, bad, _, _ = _evaluate(_book(name)[0], tamper)
    assert verdict == ow.FAILED
    return {f"{section}: {label}" for section, label in bad}


SALE, RENT = (f"Путь «{p['label']}»" for p in ow.PATHS)


@pytest.mark.parametrize("name", list(VARIANTS))
def test_both_paths_agree_with_the_engine(name) -> None:
    content, meta = _book(name)
    assert meta["missing"] == [] and meta["checks"] == ow.PASSED
    verdict, bad, evaluator, book = _evaluate(content)
    assert bad == [] and verdict == ow.PASSED
    checks = book[ow.CHECK_SHEET]
    rows = [(checks[f"A{r}"].value, checks[f"B{r}"].value, checks[f"D{r}"].value)
            for r in range(5, checks.max_row + 1)]
    sections = {section for section, _, _ in rows}
    assert {SALE, RENT, "Проект", "Смета", "Собственное участие", "По годам"} <= sections
    # Сверяются настоящие деньги обоих путей, а не нули.
    engine = {(section, label): value for section, label, value in rows}
    for section in (SALE, RENT):
        for label in ("Выручка", "Затраты на создание", "NPV проекта", "Чистая прибыль", "Пик собственных денег"):
            assert engine[(section, label)] not in ("", None, 0), (section, label)
    assert engine[(RENT, "Офис: стоимость здания")] or "удержание" in name


def test_the_book_has_the_sample_composition_and_the_v4_look() -> None:
    content, _ = _book("аренда и продажа здания, аннуитет")
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames == [ow.DASH_SHEET, ow.REPORT_SHEET, ow.INPUTS_SHEET, ow.GUIDE_SHEET, ow.TEP_SHEET,
                               ow.TIME_SHEET, ow.CAPEX_SHEET, ow.RATE_SHEET, ow.SALE_SHEET, ow.RENT_SHEET,
                               ow.EXIT_SHEET, "CF_Продажа", "CF_Аренда", ow.TAX_SHEET, ow.CHECK_SHEET,
                               ow.SOURCES_SHEET]
    for name in (ow.TIME_SHEET, ow.CAPEX_SHEET, ow.SALE_SHEET, ow.RENT_SHEET, "CF_Продажа", "CF_Аренда",
                 ow.TAX_SHEET):
        sheet = book[name]
        # Месяцы вправо с D, шапка и подписи закреплены, печать — по 12 месяцев.
        assert sheet.freeze_panes == "D5", name
        assert sheet.print_title_cols.replace("$", "") == "A:C", name
        assert sheet.print_title_rows.replace("$", "") == "3:4", name
        assert len(sheet.col_breaks.brk) >= 5, name
        assert sheet["A1"].fill.fgColor.rgb.endswith(ow.DARK) and sheet["A3"].fill.fgColor.rgb.endswith(ow.HEAD)
        assert sheet["D4"].value == 0 or "СРОКИ" in str(sheet["D4"].value)
        assert sheet["A1"].font.name == ow.FONT
    # Деньги — в формате v4, а не «37266,16417».
    rent = book[ow.RENT_SHEET]
    row = _row(rent, "Доход аренды")
    assert rent[f"E{row}"].number_format == ow.NUM and rent[f"B{row}"].number_format == ow.NUM
    inputs = book[ow.INPUTS_SHEET]
    row = _row(inputs, "Срок удержания")
    assert inputs[f"B{row}"].fill.fgColor.rgb.endswith(ow.INPUT) and inputs[f"B{row}"].font.color.rgb.endswith("0000FF")


def test_the_model_sheets_hold_formulas_not_engine_numbers() -> None:
    """Числа на листах модели — формулы; значения — только на «Вводных» и в
    рядах, подписанных «СЧИТАЕТ ДВИЖОК»."""
    content, _ = _book("офис и ТЦ в аренде")
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert "Коммерция ОСЗ" in book.sheetnames or any("ТЦ" in n or "Коммерц" in n for n in book.sheetnames)
    for name in book.sheetnames:
        if name in (ow.INPUTS_SHEET, ow.CHECK_SHEET, ow.SOURCES_SHEET, ow.GUIDE_SHEET):
            continue
        sheet = book[name]
        for row in sheet.iter_rows(min_row=5, min_col=2):
            for cell in row:
                if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    engine = cell.fill.fgColor.rgb.endswith(ow.ENGINE)
                    year = name == ow.REPORT_SHEET and cell.column == 1
                    assert engine or year or cell.value == 0, f"{name}!{cell.coordinate} = {cell.value}"
    # У книги есть значения рядом с формулами: телефон и предпросмотр формул не считают.
    cached = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    report = cached[ow.REPORT_SHEET]
    row = _row(report, "NPV проекта")
    assert isinstance(report[f"B{row}"].value, float) and isinstance(report[f"C{row}"].value, float)
    assert cached[ow.CHECK_SHEET]["I5"].value == ow.PASSED


def test_choices_are_russian_lists_and_dates_are_dates() -> None:
    content, _ = _book("аренда и продажа здания, аннуитет")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[ow.INPUTS_SHEET]
    lists = {str(rng) for dv in sheet.data_validations.dataValidation for rng in dv.sqref.ranges}
    for label in ("Профиль продаж", "Выход в конце удержания", "Погашение после ввода",
                  "Класс офиса", "Сценарий ключевой ставки"):
        assert f"B{_row(sheet, label)}" in lists, label
    assert hasattr(sheet[f"B{_row(sheet, 'Начало проекта')}"].value, "year")
    assert hasattr(sheet[f"B{_row(sheet, 'Дата ставки аренды')}"].value, "year")
    codes = {"income", "direct", "sweep", "annuity", "bullet", "hold", "sale", "flat", "bell"}
    for row in sheet.iter_rows():
        for cell in row:
            assert cell.value not in codes, f"{cell.coordinate}: код «{cell.value}» вместо подписи"


def test_a_tampered_formula_is_caught() -> None:
    """Подделка формулы: доход аренды завышен на процент."""
    def tamper(book):
        sheet = book[ow.RENT_SHEET]
        row = _row(sheet, "Доход аренды")
        for col in range(ow.FIRST_COL, sheet.max_column + 1):
            cell = sheet.cell(row, col)
            cell.value = cell.value + "*1.01"

    labels = _tampered("аренда и продажа здания, аннуитет", tamper)
    assert {f"{RENT}: Офис: доход аренды", "Проект: Выручка проекта", "Офисы: Доход аренды"} <= labels
    assert not any(label.startswith(SALE) for label in labels)


def test_a_tampered_cost_article_is_caught() -> None:
    def tamper(book):
        sheet = book[ow.CAPEX_SHEET]
        row = _row(sheet, "Резерв")
        sheet[f"B{row}"] = sheet[f"B{row}"].value + "*1.2"

    labels = _tampered("аренда и продажа здания, аннуитет", tamper)
    assert {"Смета: Резерв", "Проект: CAPEX", f"{SALE}: Затраты на создание", "Офисы: Кредит — выдача"} <= labels


def test_a_tampered_input_and_rent_date_are_caught() -> None:
    def rent(book):
        sheet = book[ow.INPUTS_SHEET]
        cell = sheet[f"B{_row(sheet, 'Ставка аренды с НДС')}"]
        cell.value = cell.value * 1.1

    assert {f"{RENT}: Офис: доход аренды", "Офисы: NOI за срок удержания"} <= _tampered(
        "аренда и продажа здания, аннуитет", rent)

    def rent_date(book):
        sheet = book[ow.INPUTS_SHEET]
        sheet[f"B{_row(sheet, 'Дата ставки аренды')}"].value = None

    assert f"{RENT}: Офис: доход аренды" in _tampered("аренда и продажа здания, аннуитет", rent_date)


def test_the_office_class_drives_the_model() -> None:
    """Класс офиса — список, а не подпись: другая ступень меняет допущения,
    не заданные вручную, и пути расходятся с движком."""
    content, _ = _book("аренда и продажа здания, аннуитет")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[ow.INPUTS_SHEET]
    chosen = sheet[f"B{_row(sheet, 'Класс офиса')}"].value
    assert chosen in core.nonres_strategy.OFFICE_CLASSES
    # Числа проекта, отличные от ступени, стоят «вручную»: правка руками видна.
    assert sheet[f"B{_row(sheet, 'Ставка аренды с НДС')}"].value == pytest.approx(4.5)

    def other_class(book):
        ws = book[ow.INPUTS_SHEET]
        ws[f"B{_row(ws, 'Класс офиса')}"] = "A+" if chosen != "A+" else "B"

    labels = _tampered("аренда и продажа здания, аннуитет", other_class)
    assert f"{RENT}: NPV проекта" in labels


def test_the_class_of_the_engine_defaults_is_written_without_manual_cells() -> None:
    values = {key: ow._class_value("B", field) for key, field in ow.CLASS_FIELDS.items()}
    assert ow.office_class_of(values) == ("B", {})
    values["cap"] = 0.12
    assert ow.office_class_of(values) == ("B", {"cap": 0.12})


def test_a_tampered_tax_rule_is_caught() -> None:
    """Убыток прошлых лет зачитывается целиком, без половинного ограничения."""
    def tamper(book):
        sheet = book[ow.INPUTS_SHEET]
        sheet[f"B{_row(sheet, 'Убыток прошлых лет')}"] = 1.0

    labels = _tampered("аренда и удержание, погашение из NOI", tamper)
    assert "Проект: Налог на прибыль" in labels


def test_switching_the_exit_in_the_book_moves_the_model() -> None:
    def tamper(book):
        sheet = book[ow.INPUTS_SHEET]
        sheet[f"B{_row(sheet, 'Выход в конце удержания')}"] = ow.EXIT["hold"]

    labels = _tampered("аренда и продажа здания, аннуитет", tamper)
    assert {f"{RENT}: Офис: продажа здания", "Офисы: Оценка удержания"} <= labels


def test_a_longer_project_than_the_engine_is_caught() -> None:
    def tamper(book):
        sheet = book[ow.INPUTS_SHEET]
        cell = sheet[f"B{_row(sheet, 'Срок удержания')}"]
        cell.value = cell.value + 2

    assert "Проект: Горизонт модели, мес." in _tampered("аренда и продажа здания, аннуитет", tamper)


def test_other_projects_keep_their_books() -> None:
    """Офис по ДДУ и нежилой проект без офиса — прежняя книга; смешанный — v4."""
    for over in (dict(offices_strategy="ddu"),
                 dict(offices_enabled=False, retail_strategy="income", **RETAIL)):
        x, t = _project(**over)
        _, _, meta = core.build_project_workbook(x, t, [], {})
        assert meta.get("nonres_book") and not meta.get("office_book"), over
    x, t = _project(nonresidential=False, offices_strategy="income")
    _, _, meta = core.build_project_workbook(x, t, [], {})
    assert not meta.get("nonres_book") and not meta.get("office_book")
