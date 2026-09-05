"""Стопроцентная льгота по ВРИ означает, что платы нет — на всех поверхностях.

Проект со стопроцентной льготой показывал в ключевых параметрах очереди полную
плату за смену ВРИ. Расчёт при этом был верен: движок платит после льготы, и
структура расходов ниже показывала ноль. Врали две строки карточки — «Стоимость
покупки» и «Стоимость смены ВРИ», единственные во всём блоке, которые читались
из формы, а не из результата.

Форма не знает двух вещей. Первая — льгота: в поле лежит валовое обязательство,
а платится то, что осталось после неё. Вторая — очередь: в разрезе очереди форма
отдаёт цифру всего проекта, и рядом с расходами одной очереди стояла плата за
весь проект. Соседние строки той же карточки давно берутся из расчёта.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import v4_inputs  # noqa: E402

import main as wrapper  # noqa: E402

core = wrapper.core

GROSS_MLN = 2864.29


def _inputs(**extra):
    return {**core.DEFAULT_INPUTS, "vri_required": True,
            "land_rights_cost_mln": GROSS_MLN, "purchase_price_mln": 1500.0, **extra}


def _tep():
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


def _single(**extra):
    return core.calculate(core.CalcRequest(inputs=_inputs(**extra), tep=_tep(), rates=[]))


def _phased(**extra):
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(**extra), tep=_tep(), rates=[],
        phasing={"enabled": True, "phase_count": 2,
                 "phases": [{"name": "О1", "start_offset_months": 0},
                            {"name": "О2", "start_offset_months": 12}]}))


def _group(result, label):
    for item in result["report"]["expense_structure"]:
        if item["label"] == label:
            return float(item["value"])
    return 0.0


# --- движок платит после льготы ----------------------------------------------

def test_a_full_relief_leaves_no_payment():
    result = _single(vri_relief_mode="percent", vri_relief_pct=100.0)
    assert result["capex"]["land_rights"] == 0.0
    assert _group(result, "Смена ВРИ / земельные права") == 0.0
    assert result["vri"]["totals"]["relief"] == pytest.approx(GROSS_MLN * 1e6, rel=1e-6)


def test_the_gross_obligation_stays_visible():
    """Льгота — это не «платы не было»: валовое обязательство и размер льготы
    остаются в отчёте, иначе основание не проверить."""
    totals = _single(vri_relief_mode="percent", vri_relief_pct=100.0)["vri"]["totals"]
    assert totals["gross"] == pytest.approx(GROSS_MLN * 1e6, rel=1e-6)
    assert totals["amount"] == 0.0


def test_a_partial_relief_pays_the_rest():
    result = _single(vri_relief_mode="percent", vri_relief_pct=30.0)
    assert result["capex"]["land_rights"] == pytest.approx(GROSS_MLN * 1e6 * 0.7, rel=1e-6)


def test_no_phase_pays_a_relieved_obligation():
    """Доля очереди берётся из базового расчёта, где льгота уже срезана."""
    bundle = _phased(vri_relief_mode="percent", vri_relief_pct=100.0)
    for phase in bundle["phases"]:
        assert phase["result"]["capex"]["land_rights"] == 0.0
    assert bundle["consolidated"]["capex"]["land_rights"] == 0.0


def test_a_phase_carries_its_own_entry_price_not_the_whole_project():
    """Цена входа платится первой очередью: во второй её быть не должно."""
    bundle = _phased()
    first, second = (phase["result"] for phase in bundle["phases"])
    assert _group(first, "Цена приобретения") == pytest.approx(1500.0 * 1e6, rel=1e-6)
    assert _group(second, "Цена приобретения") == 0.0


# --- карточка ключевых параметров читает расчёт -------------------------------

def test_the_card_no_longer_reads_the_form():
    page = core.PAGE
    card = page[page.find("projectParamsTable.innerHTML="):]
    card = card[:card.find("reportFinanceTable.innerHTML=")]
    assert "inputs.land_rights_cost_mln" not in card
    assert "inputs.purchase_price_mln" not in card
    assert "r.capex.land_rights" in card
    assert "expenseGroup('Цена приобретения')" in card


def test_the_card_names_the_relief():
    """Ноль без объяснения читается как потерянная строка."""
    page = core.PAGE
    card = page[page.find("projectParamsTable.innerHTML="):]
    assert "льгота " in card[:card.find("reportFinanceTable.innerHTML=")]


# --- печать говорит то же самое ----------------------------------------------

def test_the_printed_report_shows_what_is_paid():
    result = _single(vri_relief_mode="percent", vri_relief_pct=100.0)
    rows = dict(core._pdf_entry_cost_rows(result, result["report"]["expense_structure"]))
    assert rows["Смена ВРИ / земельные права"].startswith("0")
    assert "льгота" in rows["Смена ВРИ / земельные права"]
    assert rows["Цена приобретения"].startswith("1,50")


def test_the_printed_report_says_nothing_about_a_relief_that_is_absent():
    result = _single()
    rows = dict(core._pdf_entry_cost_rows(result, result["report"]["expense_structure"]))
    assert "льгота" not in rows["Смена ВРИ / земельные права"]
    assert rows["Смена ВРИ / земельные права"].startswith("2,86")


def test_the_printed_phase_report_prints_the_phase(monkeypatch):
    """В печати очереди стояла цена покупки всего проекта — та же ошибка."""
    bundle = _phased()
    second = bundle["phases"][1]["result"]
    rows = dict(core._pdf_entry_cost_rows(second, second["report"]["expense_structure"]))
    assert rows["Цена приобретения"].startswith("0")


def _relief_cell(**extra) -> float:
    """Что книга считает льготой: вводная на координате B82.

    Само значение переехало на лист ввода, а на B82 стоит ссылка на него.
    Спрашивать надо величину, а не лист: разбор XML по имени «Вводные» после
    разделения попадал бы уже на другой лист и на другую ячейку.
    """
    import io

    import openpyxl

    data, _name, _meta = core.build_project_workbook(
        _inputs(**extra), _tep(), [], {}, project_name="проба")
    book = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    value = v4_inputs.value(book, "B82")
    assert value is not None, "ячейка льготы в книге не найдена"
    return float(value)


def test_the_workbook_takes_the_relief_the_engine_calculated():
    """В книгу писалось поле «льгота — сумма», а не посчитанная льгота.

    Льгота долей — обычный для Москвы случай (её получают через места
    приложения труда) — до книги не доезжала вовсе: отчёт показывал плату 0,
    книга платила полные 4 674 млн ₽ на 77:04:0001019:173. Одни и те же
    вводные, два достоверных на вид документа (владелец, 20.08.2026).
    """
    # Доля — та самая ветка, которой в книге не было.
    assert _relief_cell(vri_relief_mode="percent", vri_relief_pct=100) == pytest.approx(GROSS_MLN)
    assert _relief_cell(vri_relief_mode="percent", vri_relief_pct=30) == pytest.approx(GROSS_MLN * 0.3)
    # Сумма и зачёт — как и раньше, и вместе тоже.
    assert _relief_cell(vri_relief_mode="amount", vri_relief_mln=500) == pytest.approx(500)
    assert _relief_cell(vri_transfer_offset_mln=200) == pytest.approx(200)
    assert _relief_cell(vri_relief_mode="amount", vri_relief_mln=500,
                        vri_transfer_offset_mln=200) == pytest.approx(700)
    # Больше платы льгота не бывает: движок её обрезает, книга обязана так же.
    assert _relief_cell(vri_relief_mode="amount", vri_relief_mln=9000) == pytest.approx(GROSS_MLN)
    assert _relief_cell() == pytest.approx(0.0)


def test_the_book_and_the_engine_agree_on_what_is_paid():
    """Сверяем не поле, а итог: сколько платы остаётся после льготы."""
    for extra in ({"vri_relief_mode": "percent", "vri_relief_pct": 40},
                  {"vri_relief_mode": "amount", "vri_relief_mln": 900},
                  {"vri_transfer_offset_mln": 150},
                  {}):
        engine = core.vri_relief(_inputs(**extra), GROSS_MLN * 1_000_000)[0] / 1_000_000
        assert _relief_cell(**extra) == pytest.approx(engine, rel=1e-6), extra
