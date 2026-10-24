"""Книга нежилого проекта без офиса — каркас жилой v4, сверка с движком.

С 24.10.2026 нежилой проект без офиса (ТЦ, наземный паркинг, ФОК рядом с ними) получает ту
же книгу, что проект с офисом (`office_workbook`, `docs/office_workbook.md`),
только с одним способом продажи: каждый объект продаётся стратегией, выбранной
у него в проекте (по ДДУ с эскроу и ПФ, блоками после ввода или арендой с
продажей здания). Сравнения путей, как у офиса, нет; «ПРОВЕРКИ» сверяют книгу
с основным расчётом движка. Прежняя книга (`nonres_workbook`, листы «Объект N»,
«ДДУ N», «Сверка») убрана.

Формулы считает `xlsx_eval` (`office_workbook.evaluate`) — без Excel. Проверка
обязана падать на подделке: формула, статья сметы, вводная, правило налога,
горизонт, ставка ПФ и цена по ДДУ краснят «ПРОВЕРКИ».

Запуск: python3 -m pytest tests/test_nonres_workbook.py -q
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


def _project(nonresidential: bool = True, **over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(offices_enabled=False)
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
        # Ставка метрового объекта нежилого проекта — СМР; умолчание то же,
        # что ставит страница при выборе вида (`object_smr_rate`).
        for key, turnkey in core.OBJECT_SMR_RATE_DEFAULTS.items():
            if key not in over and float(x.get(key) or 0) == turnkey:
                x[key] = core.object_smr_rate(turnkey, x)
    return x, t


# Аренда задана числами: умолчания малы, чтобы сценарии удержания платили
# налог и гасили кредит из NOI — а это и проверяется.
RETAIL_ONLY = dict(retail_enabled=True, retail_gba_sqm=40000.0,
                   retail_saleable_sqm=24000.0, retail_parking_under_spaces=200,
                   retail_parking_over_spaces=40, retail_rent_th_per_sqm_month=4.5,
                   retail_occupancy_stable_pct=92.0, retail_leaseup_months=12,
                   retail_opex_pct=18.0, retail_exit_cap_pct=11.0, retail_rent_date="2025-12-01")
SPORTS = dict(sports_enabled=True, sports_gba_sqm=5000.0, sports_saleable_sqm=3500.0,
              sports_disposition=core.SPORTS_DISPOSITION_SALE)
PARKING = dict(above_parking_enabled=True, above_parking_spaces=300)
VARIANTS = {
    "ТЦ ДКП, продажи до ввода": dict(RETAIL_ONLY, retail_strategy="direct",
                                     retail_direct_sale_offset_months=-6,
                                     retail_direct_sale_curve="bell"),
    "ТЦ аренда и продажа, аннуитет": dict(RETAIL_ONLY, retail_strategy="income"),
    "аренда и удержание, погашение из NOI": dict(RETAIL_ONLY, retail_strategy="income",
                                                 retail_exit_mode="hold", retail_debt_repayment="sweep",
                                                 retail_rent_th_per_sqm_month=7.0),
    "баллон в срок, участок рассрочкой, сценарий": dict(
        RETAIL_ONLY, retail_strategy="income", retail_loan_term_years=4, retail_hold_years=8,
        retail_loan_balloon_pct=10, purchase_price_mln=900, purchase_schedule="30%@0; 70%@8",
        land_buyout_mln=120, scenario_cost_multiplier=1.1, scenario_revenue_multiplier=0.9,
        rate_scenario="high"),
    # Объекты по ДДУ: продажи, эскроу, БРИДЖ и ПФ — формулами листа объекта и «ПФ».
    "ТЦ по ДДУ": dict(RETAIL_ONLY, retail_strategy="ddu"),
    "наземный паркинг по ДДУ и ТЦ в аренде": dict(RETAIL_ONLY, retail_strategy="income", **PARKING),
    "ТЦ по ДДУ: проценты капиталом, свои деньги, лимит, сценарий": dict(
        RETAIL_ONLY, retail_strategy="ddu", bridge_interest_mode="Оплата капиталом", pre_pf_own_funds_mln=300,
        pf_limit_approved_mln=9000, scenario_revenue_multiplier=0.95, scenario_cost_multiplier=1.05,
        rate_scenario="high"),
    "ТЦ по ДДУ: профиль продаж и лестница цены": dict(
        RETAIL_ONLY, retail_strategy="ddu", retail_sales_profile="30%@0; 50%@12; 20%@30",
        retail_growth_stage1_pct=5, retail_growth_stage3_pct=7, retail_share_before_rve_pct=70,
        retail_residual_months=9),
    # ФОК — только рядом с другими объектами: нежилого проекта из одного ФОК
    # не бывает (владелец, 24.10.2026: «Для ФОК вообще отдельная книга не нужна»).
    "наземный паркинг по ДДУ": dict(PARKING),
    "ТЦ блоками и ФОК по ДДУ": dict(RETAIL_ONLY, retail_strategy="direct", **SPORTS),
}
DDU_NAMES = [name for name in VARIANTS if "ДДУ" in name]
RETAIL = "Коммерция ОСЗ"
SPORTS_SHEET = "ФОК - медцентр"
_BOOKS: dict[str, tuple[bytes, dict]] = {}


def _book(name: str) -> tuple[bytes, dict]:
    if name not in _BOOKS:
        x, t = _project(**VARIANTS[name])
        content, filename, meta = core.build_project_workbook(x, t, [], {}, project_name="ТЦ")
        assert meta.get("nonres_book") is True and "нежилой_ТЦ" in filename, (filename, meta)
        assert not meta.get("office_book")
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


def _input(sheet, label: str, title: str = RETAIL):
    """Клетка «Вводных» у объекта: строка по подписи, столбец по заголовку объекта."""
    row = _row(sheet, label)
    head = max(r for r in range(1, row) if sheet[f"A{r}"].value == "Объект")
    column = next(c for c in range(2, sheet.max_column + 1) if sheet.cell(head, c).value == title)
    return sheet.cell(row, column)


def _tampered(name: str, tamper) -> set[str]:
    verdict, bad, _, _ = _evaluate(_book(name)[0], tamper)
    assert verdict == ow.FAILED
    return {f"{section}: {label}" for section, label in bad}


@pytest.mark.parametrize("name", list(VARIANTS))
def test_the_book_formulas_agree_with_the_engine(name) -> None:
    content, meta = _book(name)
    assert meta["missing"] == [] and meta["checks"] == ow.PASSED
    verdict, bad, _, book = _evaluate(content)
    assert bad == [] and verdict == ow.PASSED
    checks = book[ow.CHECK_SHEET]
    rows = [(checks[f"A{r}"].value, checks[f"B{r}"].value, checks[f"D{r}"].value)
            for r in range(5, checks.max_row + 1)]
    sections = {section for section, _, _ in rows}
    assert {"Проект", "Смета"} <= sections
    # Один способ — стратегия объектов: сравнения путей офиса нет.
    assert not any(str(section).startswith("Вариант") for section in sections)
    engine = {(section, label): value for section, label, value in rows}
    # Сверяются настоящие деньги, а не нули.
    for label in ("Выручка проекта", "CAPEX", "EBITDA", "NPV проекта", "Расходы всего", "Чистая прибыль"):
        assert engine[("Проект", label)] not in ("", None, 0), label
    # Свод «на глаз»: выручка − расходы всего = чистая прибыль, EBITDA −
    # проценты = прибыль до налога; обе разности стоят в сверке нулём.
    assert engine[("Проект", "Выручка − расходы всего − чистая прибыль")] == 0.0
    assert engine[("Проект", "EBITDA − проценты − прибыль до налога")] == 0.0
    if name in DDU_NAMES and "профиль" not in name:
        # ПФ и продажи по ДДУ сверяются подробно, на своём листе «ПФ».
        assert "ПФ" in sections and ow.PF_SHEET in book.sheetnames
        for label in ("Выдача ПФ всего", "ПФ — пик долга", "Эскроу — пик"):
            assert engine[("ПФ", label)] not in ("", None, 0), label
        assert isinstance(engine[("Проект", "LLCR")], float)
    elif name not in DDU_NAMES:
        assert ow.PF_SHEET not in book.sheetnames
        assert engine[("Проект", "Кредит объектов — пик")] not in ("", None, 0)
        assert "Собственное участие" in sections and "По годам" in sections


def test_the_book_is_the_v4_frame_with_one_way_to_sell() -> None:
    """Состав книги — как у офиса, без листов трёх способов продажи офиса и
    шкалы класса: объекты — своими листами, поток — один лист «CF»."""
    content, _ = _book("наземный паркинг по ДДУ и ТЦ в аренде")
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames == [ow.DASH_SHEET, ow.REPORT_SHEET, ow.INPUTS_SHEET, ow.GUIDE_SHEET, ow.TEP_SHEET,
                               ow.TIME_SHEET, ow.CAPEX_SHEET, ow.RATE_SHEET, RETAIL, "Наземный паркинг",
                               ow.PF_SHEET, "CF", ow.TAX_SHEET, ow.CHECK_SHEET]
    for name in (ow.TIME_SHEET, ow.CAPEX_SHEET, RETAIL, "Наземный паркинг", ow.PF_SHEET, "CF", ow.TAX_SHEET):
        sheet = book[name]
        # Месяцы вправо с D, шапка и подписи закреплены, печать — по 12 месяцев.
        assert sheet.freeze_panes == "D5", name
        assert sheet.print_title_cols.replace("$", "") == "A:C", name
        assert len(sheet.col_breaks.brk) >= 5, name
        assert sheet["A1"].font.name == ow.FONT
    assert book[RETAIL].sheet_properties.tabColor.rgb.endswith(ow.RENT_TAB)
    assert book["Наземный паркинг"].sheet_properties.tabColor.rgb.endswith(ow.DDU_TAB)
    report = book[ow.REPORT_SHEET]
    head = _row(report, "Показатель")
    assert [report.cell(head, c).value for c in (2, 3)] == [ow.PROJECT_PATH["label"], None]
    chosen = report.cell(_row(report, "Способ, выбранный в проекте"), 2).value
    assert "Коммерция ОСЗ — аренда и выход" in chosen and "Наземный паркинг — продажа по ДДУ" in chosen
    assert not any(str(report[f"A{r}"].value or "").startswith(("Выгоднее", "Офис"))
                   for r in range(1, report.max_row + 1))
    cached = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    assert isinstance(cached[ow.REPORT_SHEET][f"B{_row(report, 'NPV проекта')}"].value, float)
    assert cached[ow.CHECK_SHEET]["I5"].value == ow.PASSED
    inputs = book[ow.INPUTS_SHEET]
    assert not any(str(inputs[f"A{r}"].value or "").startswith(("Шкала класса", "Класс офиса"))
                   for r in range(1, inputs.max_row + 1))


@pytest.mark.parametrize("name", ["ТЦ ДКП, продажи до ввода", "ТЦ блоками и ФОК по ДДУ"])
def test_the_model_sheets_hold_formulas_not_engine_numbers(name) -> None:
    """Числа на листах модели — формулы; значения — только на «Вводных» и в
    рядах, подписанных «СЧИТАЕТ ДВИЖОК»."""
    book = openpyxl.load_workbook(io.BytesIO(_book(name)[0]))
    formulas = 0
    for sheet_name in book.sheetnames:
        if sheet_name in (ow.INPUTS_SHEET, ow.CHECK_SHEET, ow.GUIDE_SHEET):
            continue
        sheet = book[sheet_name]
        for row in sheet.iter_rows(min_row=5, min_col=2):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formulas += 1
                elif isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                    engine = cell.fill.fgColor.rgb.endswith(ow.ENGINE)
                    year = sheet_name == ow.REPORT_SHEET and cell.column == 1
                    assert engine or year or cell.value == 0, f"{sheet_name}!{cell.coordinate} = {cell.value}"
    assert formulas > 2000


def test_choices_are_russian_lists_and_dates_are_dates() -> None:
    sheet = openpyxl.load_workbook(io.BytesIO(_book("ТЦ аренда и продажа, аннуитет")[0]))[ow.INPUTS_SHEET]
    lists = {str(rng) for dv in sheet.data_validations.dataValidation for rng in dv.sqref.ranges}
    for label in ("Профиль продаж", "Выход в конце удержания", "Погашение после ввода"):
        assert _input(sheet, label).coordinate in lists, label
    assert f"B{_row(sheet, 'Сценарий ключевой ставки')}" in lists
    assert hasattr(sheet[f"B{_row(sheet, 'Начало проекта')}"].value, "year")
    assert hasattr(_input(sheet, "Дата ставки аренды").value, "year")
    codes = {"income", "direct", "sweep", "annuity", "bullet", "hold", "sale", "flat", "bell", "ddu"}
    for row in sheet.iter_rows():
        for cell in row:
            assert cell.value not in codes, f"{cell.coordinate}: код «{cell.value}» вместо подписи"


def test_a_tampered_formula_is_caught() -> None:
    """Подделка формулы: доход аренды ТЦ завышен на процент."""
    def tamper(book):
        sheet = book[RETAIL]
        row = _row(sheet, "Доход аренды")
        for col in range(ow.FIRST_COL, sheet.max_column + 1):
            cell = sheet.cell(row, col)
            cell.value = cell.value + "*1.01"

    labels = _tampered("ТЦ аренда и продажа, аннуитет", tamper)
    assert {f"{RETAIL}: Доход аренды", f"{RETAIL}: NOI за срок удержания", "Проект: Выручка проекта"} <= labels


def test_a_tampered_cost_article_is_caught() -> None:
    def tamper(book):
        sheet = book[ow.CAPEX_SHEET]
        row = _row(sheet, "Резерв")
        sheet[f"B{row}"] = sheet[f"B{row}"].value + "*1.2"

    labels = _tampered("ТЦ аренда и продажа, аннуитет", tamper)
    assert {"Смета: Резерв", "Проект: CAPEX", f"{RETAIL}: Кредит — выдача"} <= labels


def test_a_tampered_input_and_rent_date_are_caught() -> None:
    def rent(book):
        cell = _input(book[ow.INPUTS_SHEET], "Ставка аренды с НДС")
        cell.value = cell.value * 1.1

    assert {f"{RETAIL}: Доход аренды", f"{RETAIL}: NOI за срок удержания"} <= _tampered(
        "ТЦ аренда и продажа, аннуитет", rent)

    def rent_date(book):
        _input(book[ow.INPUTS_SHEET], "Дата ставки аренды").value = None

    assert f"{RETAIL}: Доход аренды" in _tampered("ТЦ аренда и продажа, аннуитет", rent_date)


def test_a_tampered_tax_rule_is_caught() -> None:
    """Убыток прошлых лет зачитывается целиком, без половинного ограничения."""
    def tamper(book):
        sheet = book[ow.INPUTS_SHEET]
        sheet[f"B{_row(sheet, 'Убыток прошлых лет')}"] = 1.0

    assert "Проект: Налог на прибыль" in _tampered("аренда и удержание, погашение из NOI", tamper)


def test_switching_the_exit_in_the_book_moves_the_model() -> None:
    """Список — не подпись: «Удержание с оценкой» убирает выручку выхода и
    ставит оценку, как у движка с тем же выбором."""
    def tamper(book):
        _input(book[ow.INPUTS_SHEET], "Выход в конце удержания").value = ow.EXIT["hold"]

    labels = _tampered("ТЦ аренда и продажа, аннуитет", tamper)
    assert {f"{RETAIL}: Продажа здания", f"{RETAIL}: Оценка удержания"} <= labels


def test_a_longer_project_than_the_engine_is_caught() -> None:
    """Срок удержания длиннее движка: книга не обрезает поток молча — горизонт в
    «ПРОВЕРКАХ» красный."""
    def tamper(book):
        cell = _input(book[ow.INPUTS_SHEET], "Срок удержания")
        cell.value = cell.value + 2

    assert "Проект: Горизонт модели, мес." in _tampered("ТЦ аренда и продажа, аннуитет", tamper)


def test_a_tampered_pf_rate_is_caught() -> None:
    """Подделка ставки ПФ на один месяц краснит проценты и LLCR."""
    def tamper(book):
        sheet = book[ow.PF_SHEET]
        row = _row(sheet, "Ставка ПФ")
        for col in range(ow.FIRST_COL + 20, sheet.max_column + 1):
            cell = sheet.cell(row, col)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.value = cell.value + "*1.5"
                break

    labels = _tampered("ТЦ по ДДУ", tamper)
    assert {"Проект: Проценты и комиссии", "Проект: LLCR"} <= labels


@pytest.mark.parametrize("name, sheet_name", [("ТЦ по ДДУ", RETAIL), ("ТЦ блоками и ФОК по ДДУ", SPORTS_SHEET),
                                              ("наземный паркинг по ДДУ", "Наземный паркинг")])
def test_a_tampered_ddu_price_is_caught(name, sheet_name) -> None:
    """Цена по ДДУ ТЦ, ФОК и наземного паркинга завышена: краснеют выручка,
    эскроу и итоги проекта."""
    def tamper(book):
        sheet = book[sheet_name]
        cell = sheet[f"B{_row(sheet, 'Цена продажи «в расчёт»')}"]
        cell.value = cell.value + "*1.05"

    labels = _tampered(name, tamper)
    assert {"ПФ: Эскроу — пик", "Проект: Выручка проекта", f"{sheet_name.replace('-', '/')}: Выручка по ДДУ"} \
        <= labels


def test_every_nonres_project_without_an_office_gets_the_v4_book(monkeypatch) -> None:
    """Нежилой проект без офиса — только книга v4-каркаса: прежней книги нет, а
    вызов офисной книги без офиса сверяет один способ — стратегию объектов."""
    assert not (ROOT / "nonres_workbook.py").exists()
    assert not hasattr(core, "nonres_workbook")
    seen: list[set] = []
    original = ow.build

    def spy(result, spec, office_keys):
        seen.append(set(office_keys))
        return original(result, spec, office_keys)

    monkeypatch.setattr(core.office_workbook, "build", spy)
    x, t = _project(**VARIANTS["ТЦ по ДДУ"])
    _, filename, meta = core.build_project_workbook(x, t, [], {})
    assert seen == [set()] and meta["nonres_book"] and not meta["office_book"]
    assert meta["checks"] == ow.PASSED and "нежилой_офис" not in filename


def test_a_mixed_project_keeps_the_v4_book() -> None:
    x, t = _project(nonresidential=False, offices_enabled=True, offices_gba_sqm=40000.0,
                    offices_saleable_sqm=24000.0, offices_strategy="income")
    _, filename, meta = core.build_project_workbook(x, t, [], {})
    assert not meta.get("nonres_book") and "нежилой" not in filename


def test_the_evaluator_irr_matches_the_engine() -> None:
    import xlsx_eval

    flows = [v * 1e6 for v in (-100.0, -50.0, 10.0, 20.0, 40.0, 60.0, 80.0, 30.0)]
    monthly = xlsx_eval.FUNCTIONS["IRR"]([flows])
    assert (1 + monthly) ** 12 - 1 == pytest.approx(core._monthly_irr(flows), abs=1e-9)
    assert xlsx_eval.FUNCTIONS["INT"]([-6.5]) == -7.0


def test_the_ddu_vat_leaves_the_engine_cash_flows(monkeypatch) -> None:
    """НДС продаж по ДДУ уходит из потоков проекта и капитала (решение владельца 13.10.2026).

    Прежде он был только в чистой прибыли, и NPV/IRR его не видели; книга
    вычитает его в своих потоках, поэтому сверка выше сходится лишь с движком,
    который вычитает его тоже.
    """
    x, t = _project(**VARIANTS["ТЦ по ДДУ"])
    result = core.calculate(core.CalcRequest(inputs=x, tep=t))
    original = core.simulate_financing
    seen: list[float] = []

    def without_vat(*args, **kwargs):
        fin = original(*args, **kwargs)
        seen.append(sum(fin.get("vat_ddu_schedule", {}).values()))
        fin["vat_ddu_schedule"] = {}
        return fin

    monkeypatch.setattr(core, "simulate_financing", without_vat)
    blind = core.calculate(core.CalcRequest(inputs=x, tep=t))
    assert seen and seen[0] > 1e6
    for flow in ("project", "equity"):
        gap = sum(blind["cashflow"][flow]) - sum(result["cashflow"][flow])
        assert abs(gap - seen[0]) < 1.0, flow


def test_the_v4_book_takes_the_vat_out_of_its_flows() -> None:
    """Книга v4 вычитает НДС к уплате (строка 21) из потоков, как движок."""
    x, t = _project(nonresidential=False, offices_enabled=True, offices_gba_sqm=40000.0,
                    offices_saleable_sqm=24000.0, offices_strategy="ddu")
    content, _, meta = core.build_project_workbook(x, t, [], {})
    assert not [m for m in meta["missing"] if "CF_" in m and ("49" in m or "54" in m or "63" in m)]
    sheet = openpyxl.load_workbook(io.BytesIO(content))["CF_1"]
    column = core._v4_cf_columns()[0]
    for row, _, replacement in core._V4_VAT_CASH_ROWS:
        assert replacement.format(c=column) in str(sheet[f"{column}{row}"].value), row


@pytest.mark.parametrize("name", ["nonres_retail_sports_ddu", "nonres_parking_ddu"])
def test_the_parity_script_finds_no_gap_for_sports_and_parking(name, tmp_path) -> None:
    """ФОК по ДДУ рядом с ТЦ и наземный паркинг по ДДУ — те же сценарии, что гоняет
    `scripts/excel_book_parity.py`: значения книги, посчитанные `xlsx_eval`
    при сборке (`v4_value_cache`), скрипт читает без LibreOffice и не находит
    ни одной строки «ПРОВЕРОК», расходящейся с движком."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import excel_book_parity as parity

    spec = parity.nonres_scenario(core, parity.NONRES_BOOKS[name])
    content, _, meta = core.build_project_workbook(copy.deepcopy(spec["inputs"]), copy.deepcopy(spec["tep"]),
                                                   [], {}, project_name=name)
    assert meta["nonres_book"] and not meta["office_book"] and meta["checks"] == ow.PASSED
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(content)
    consolidated = core._run_authoritative_model(copy.deepcopy(spec["inputs"]), copy.deepcopy(spec["tep"]),
                                                 [], {})["consolidated"]
    assert parity.report(name, path, consolidated) == [f"  проверки книги нежилого проекта: {ow.PASSED}"]


def test_the_irr_holds_when_it_is_searched_from_a_guess_like_excel(monkeypatch) -> None:
    """Excel и LibreOffice ищут IRR Ньютоном от догадки, а `xlsx_eval` —
    делением отрезка. У паркинга по ДДУ поток «сначала деньги покупателей,
    потом затраты» (−65% в год): от догадки 0,01 Ньютон уходит в ложный корень
    на бесконечности. Книга пробует догадки по очереди и отбрасывает ответ
    больше 100% в месяц — IRR сходится с движком и при поиске «как у Excel»."""
    import xlsx_eval

    def newton(args):
        flows = xlsx_eval._numbers(args[:1])
        rate = xlsx_eval._as_number(args[1]) if len(args) > 1 else 0.1
        for _ in range(50):
            try:
                value = sum(f / (1 + rate) ** k for k, f in enumerate(flows))
                slope = sum(-k * f / (1 + rate) ** (k + 1) for k, f in enumerate(flows))
            except (OverflowError, ZeroDivisionError):
                break
            if slope == 0:
                break
            step = value / slope
            rate -= step
            if abs(step) < 1e-12:
                return rate
        raise xlsx_eval._DivZero()

    spec_name = "наземный паркинг по ДДУ"
    content, _ = _book(spec_name)
    monkeypatch.setitem(xlsx_eval.FUNCTIONS, "IRR", newton)
    verdict, bad, _, _ = _evaluate(content)
    assert verdict == ow.PASSED and bad == []

    def first_guess_only(book):
        sheet = book["CF"]
        cell = sheet[f"B{_row(sheet, 'IRR проекта')}"]
        flows = cell.value.split("IRR(")[1].split(",")[0]
        cell.value = f'=IFERROR((1+IRR({flows},0.01))^12-1,"")'

    assert "Проект: IRR проекта" in _tampered(spec_name, first_guess_only)
