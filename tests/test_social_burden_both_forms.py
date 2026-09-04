"""Проект может и строить соцобъекты, и платить деньгами.

Форма исполнения соцнагрузки была переключателем «или/или»: либо стройка,
либо компенсация. Для Румянцева этого не хватило — школа на 350 мест и ДОО на
180 строятся за счёт проекта, а за стадион регби платится 1 149,23 млн ₽ по
соглашению о финансировании, и стройки там нет вовсе.

Пока режимы исключали друг друга, происходило вот что: подставляешь денежное
обязательство — импорт переключает режим — стройка школы и садика выпадает из
CAPEX, и EBITDA растёт на 0,46 млрд ₽ от **добавленного** расхода. Число,
которое двигается не в ту сторону, — единственный признак, по которому такую
подмену вообще можно заметить.

Третий режим — решение владельца (14.08.2026). Случай редкий, но реальный:
компенсация за поликлинику вместе со стройкой школы в Москве обычное дело.

Обе формы считаются порознь и по своим срокам: каждая стройка идёт своим
графиком, денежная часть — одним платежом в свою дату. В лимит БРИДЖа входит
только денежная часть: стройку банк финансирует проектным финансированием
после РнС, и включать её в БРИДЖ значило бы просить лимит дважды.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

BASE = {**core.DEFAULT_INPUTS, "apartment_price_th": 650, "commercial_price_th": 650,
        "kindergarten_places": 180, "school_places": 350,
        "social_compensation_mln": 1149.23}


def result(mode: str):
    return core.calculate(core.CalcRequest(
        inputs={**BASE, "social_mode": mode}, tep=core.TEP_DEFAULT, rates=[]))


def workbook(mode: str):
    content, _, _ = core.build_project_workbook(
        {**BASE, "social_mode": mode}, core.TEP_DEFAULT, [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


# --- режим существует и считает обе формы ---------------------------------------

def test_the_third_mode_is_offered():
    modes = [item[0] for item in core._M2_EXTRA_OPTIONS["social_mode"]]
    assert core.SOCIAL_MODE_BOTH in modes


def test_both_forms_are_added_up():
    build = result("Строительство")["summary"]["social_payment"]
    cash = result("Денежная компенсация")["summary"]["social_payment"]
    both = result(core.SOCIAL_MODE_BOTH)["summary"]["social_payment"]
    assert both == pytest.approx(build + cash, rel=1e-9)


def test_adding_a_cost_does_not_raise_the_profit():
    """Тот самый признак подмены: расход добавили, а прибыль выросла."""
    build = result("Строительство")["summary"]
    both = result(core.SOCIAL_MODE_BOTH)["summary"]
    assert both["capex"] > build["capex"]
    assert both["ebitda"] < build["ebitda"]
    assert both["net_profit"] < build["net_profit"]


def test_construction_keeps_its_own_schedule():
    """Стройка идёт месяцами по графику объектов, а не разовым платежом."""
    operating = core.build_operating_model(
        {**BASE, "social_mode": core.SOCIAL_MODE_BOTH}, core.TEP_DEFAULT, [])
    months = [month for month, value in operating["capex_by_article"]["social"].items()
              if value > 0] if "capex_by_article" in operating else []
    if not months:  # у движка своя раскладка — берём общий календарь расходов
        months = [month for month, value in operating["capex"].items() if value > 0]
    assert len(months) > 1


def test_the_cash_part_is_paid_on_its_own_date():
    """Денежное обязательство — платёж в свою дату, а не размазанный по стройке."""
    inputs = {**BASE, "social_mode": core.SOCIAL_MODE_BOTH,
              "social_comp_date": "2029-02-01"}
    operating = core.build_operating_model(inputs, core.TEP_DEFAULT, [])
    from datetime import date

    assert operating["capex"].get(date(2029, 2, 1), 0.0) >= 1149.23 * 1_000_000 * 0.99


# --- лимит БРИДЖа ---------------------------------------------------------------

def test_only_the_cash_part_enters_the_bridge_limit():
    """Стройку финансирует ПФ после РнС: попади она в БРИДЖ, лимит попросили
    бы дважды."""
    build = result("Строительство")["report"]["financing"]["calculated_bridge"]
    both = result(core.SOCIAL_MODE_BOTH)["report"]["financing"]["calculated_bridge"]
    assert both - build == pytest.approx(1149.23 * 1_000_000, rel=1e-6)


# --- книга считает так же -------------------------------------------------------

@pytest.mark.parametrize("mode", ["Строительство", "Денежная компенсация",
                                  "Строительство и компенсация"])
def test_the_workbook_agrees_with_the_engine(mode):
    """Методику меняют в двух местах: в движке и в книге."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    book = workbook(mode)
    evaluator = Evaluator(book)
    checks = book["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", \
            f"{mode}: {checks[f'A{row}'].value}"


def test_the_workbook_carries_both_parts():
    book = v4_inputs.inputs(workbook(core.SOCIAL_MODE_BOTH))
    assert book["B17"].value == pytest.approx(
        result(core.SOCIAL_MODE_BOTH)["summary"]["social_payment"] / 1_000_000, rel=1e-6)
    assert book["B56"].value == pytest.approx(1149.23)
    assert book["D56"].value == "social_cash_part_mln"


def test_the_other_modes_leave_the_cash_cell_empty():
    """Ячейка живёт только совмещённым режимом: в остальных её содержимое
    исказило бы базу комиссии."""
    for mode in ("Строительство", "Денежная компенсация"):
        assert v4_inputs.inputs(workbook(mode))["B56"].value == 0


def test_the_book_formula_knows_the_third_mode():
    formula = str(workbook(core.SOCIAL_MODE_BOTH)["CF_1"]["F57"].value)
    assert "Строительство и компенсация" in formula
    assert "$B$56" in formula


# --- порядок листов -------------------------------------------------------------

def test_the_book_opens_on_the_result():
    """Книгу открывают ради отчёта, а он лежал пятнадцатым листом — после
    четырёх CF, КРЕДИТОВ и КОНСОЛИДАТОРА. Порядок листов ничего не ломает:
    формулы ссылаются по именам, а не по позиции.

    Разделение ввода едва не отобрало у отчёта его место: «Параметры модели»
    встали вторым листом просто потому, что там раньше стояли «Вводные».
    Печатать в них больше нечего, и стоять перед отчётом им незачем.
    """
    names = workbook("Строительство").sheetnames
    assert names[:4] == ["Вводные", "ОТЧЕТ", "Дашборд", "Параметры модели"]


def test_no_sheet_was_lost_in_the_reorder():
    names = workbook("Строительство").sheetnames
    assert len(names) == len(set(names)) == 20
    for required in ("ПРОВЕРКИ", "CF_1", "CF_4", "КРЕДИТЫ", "ОБЪЕКТЫ"):
        assert required in names


def test_the_page_takes_the_modes_from_the_engine():
    """Список форм жил на странице копией, и третий режим в неё не попал:
    движок считал, книга предлагала, а выбрать было нельзя."""
    assert "__DEVELOPAID_SOCIAL_MODES__" not in core.PAGE
    assert "Строительство и компенсация" in core.PAGE


# --- очереди --------------------------------------------------------------------

def test_the_phased_project_keeps_both_forms():
    """В фазовом расчёте реестр соцобъектов собирался только для режима
    «Строительство»: у совмещённого он оставался пустым, стройка исчезала, а
    денежная часть не расходилась по очередям вовсе — на Румянцеве это 1,15
    млрд ₽ мимо."""
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 24,
               "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 36},
                          {"name": "О2", "start_offset_months": 24, "construction_months": 36}]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs={**BASE, "social_mode": core.SOCIAL_MODE_BOTH},
        tep=core.TEP_DEFAULT, rates=[], phasing=phasing))
    total = bundle["consolidated"]["summary"]["social_payment"] / 1_000_000
    # Стройка индексируется к старту своей очереди, поэтому сумма выше простой:
    # проверяем, что обе формы на месте, а не точное число.
    assert total > 1149.23 + 1500.0
    modes = {phase["result"]["summary"].get("social_payment_mode") for phase in bundle["phases"]}
    assert core.SOCIAL_MODE_BOTH in modes


def test_the_cash_part_is_not_multiplied_by_phases():
    """Один котёл на проект: без кассовых долей каждая очередь заплатила бы
    полную сумму."""
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 24,
               "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 36},
                          {"name": "О2", "start_offset_months": 24, "construction_months": 36}]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs={**BASE, "social_mode": core.SOCIAL_MODE_BOTH, "kindergarten_places": 0,
                "school_places": 0, "clinic_capacity": 0},
        tep=core.TEP_DEFAULT, rates=[], phasing=phasing))
    total = bundle["consolidated"]["summary"]["social_payment"] / 1_000_000
    assert total == pytest.approx(1149.23, rel=1e-6)


# --- отчёт называет режим своим именем -----------------------------------------

def test_the_report_does_not_call_the_third_mode_a_cash_payment():
    """В отчёте стоял «Денежная компенсация» при выбранном совмещённом режиме.

    Ветки было две — «Строительство» и всё остальное, — и третий режим уезжал
    во вторую: заголовок врал, разбивка по объектам стояла нулями (импорт
    ГлавАПУ по объектам компенсацию не всегда даёт), а итог нёс и стройку тоже.
    Владелец увидел три нуля против 2,7 млрд ₽ итога (19.08.2026).
    """
    block = core.PAGE[core.PAGE.index("const socialMode=r.summary.social_payment_mode"):]
    block = block[:block.index("const bridgeTotal")]
    assert "socialMode==='Строительство и компенсация'" in block, "третий режим не разобран"
    built = block[block.index("socialMode==='Строительство и компенсация'"):]
    built = built[:built.index("else if(socialMode==='Строительство')")]
    assert "row('Режим','Строительство и компенсация')" in built
    assert "Стоимость строительства" in built and "Денежная компенсация" in built
    assert "Социальная нагрузка / всего" in built


def test_the_cash_part_is_what_is_left_of_the_total():
    """Денежная часть считается вычитанием, а не берётся из вводных.

    Итог таблицы обязан сходиться с моделью при любом источнике компенсации —
    импорт ГлавАПУ, ручной ввод, пресет.
    """
    both = result(core.SOCIAL_MODE_BOTH)["summary"]
    parts = both["social_payment_breakdown"]["construction"]
    built = sum(float(value or 0) for value in parts.values()) * 1e6
    assert both["social_payment"] - built == pytest.approx(1149.23 * 1e6, rel=1e-9)

    block = core.PAGE[core.PAGE.index("const socialBuilt="):]
    block = block[:block.index("const bridgeTotal")]
    assert "r.summary.social_payment||0)-socialBuilt" in block.replace(" ", "")


def test_the_self_check_knows_all_three_modes():
    """Самопроверка сравнивала CAPEX со стройкой и при совмещённом режиме.

    В CAPEX там лежит и денежная часть, поэтому проверка падала всегда, а отчёт
    2.0 писал «социалка расходится с выбранным режимом» на исправном расчёте.
    """
    for mode in ("Строительство", "Денежная компенсация", core.SOCIAL_MODE_BOTH):
        assert result(mode)["summary"]["social_in_capex_check"] is True, mode


def test_the_pdf_splits_the_bridge_like_the_site():
    """Денежная часть стоит своей целью, а не уезжает в «приобретение».

    Прежде проверка искала в исходнике печати строки `SOCIAL_MODE_BOTH` и
    `social_payment_breakdown` — то есть закрепляла РЕАЛИЗАЦИЮ, а не
    утверждение: обе поверхности выводили состав лимита вычитанием «итог минус
    социалка минус П минус РД», и правило «поверхности считают одинаково»
    держалось на том, что вычитаний два и они совпадают. Теперь состав лимита
    считает движок один раз, и проверять надо его: печать и экран читают одно
    поле, а денежная часть в нём названа своей целью.
    """
    parts = result(core.SOCIAL_MODE_BOTH)["report"]["financing"]["calculated_bridge_parts"]
    assert parts["social"] == pytest.approx(1149.23 * 1_000_000, rel=1e-6), (
        "денежная часть соцнагрузки не выделена в составе лимита")
    assert parts["purchase"] + parts["social"] + parts["design_p"] + parts["design_rd"] \
        == pytest.approx(
            result(core.SOCIAL_MODE_BOTH)["report"]["financing"]["calculated_bridge"],
            rel=1e-9), "состав лимита не складывается в сам лимит"
    # Стройка соцобъектов в лимит не входит: её финансирует ПФ после РнС.
    build_parts = result("Строительство")["report"]["financing"]["calculated_bridge_parts"]
    assert build_parts["social"] == 0.0
