"""Фактический пик БРИДЖа расшифрован так же, как расчётный лимит.

Расчётный лимит методики разложен по четырём целям — покупка, стадия П, стадия
РД, денежная соцкомпенсация. Фактический пик не был разложен ничем, а он всегда
больше: в него попадает всё, что платится до открытия ПФ, включая то, чего в
лимите нет по определению — плата за смену ВРИ, ИРД, подготовка территории,
техзаказчик, управление проектом.

Разница между двумя числами — это и есть то, что банк называет «остальное
вашими», и до сих пор её приходилось выводить глазами по структуре расходов.

До открытия ПФ у проекта нет ни выручки, ни ПФ, поэтому остаток БРИДЖа в месяц
пика равен всему, что к этому месяцу оплачено, — расшифровка сходится точно, а
не приблизительно.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _inputs(**extra):
    return {**core.DEFAULT_INPUTS, "purchase_price_mln": 4000.0, **extra}


def _tep():
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


def _single(**extra):
    return core.calculate(core.CalcRequest(inputs=_inputs(**extra), tep=_tep(), rates=[]))


def _phased(count: int = 3):
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(), tep=_tep(), rates=[],
        phasing={"enabled": True, "phase_count": count, "phase_gap_months": 12}))


def _financing(result):
    return result["report"]["financing"]


# --- расшифровка сходится с самим пиком ---------------------------------------

def test_the_structure_adds_up_to_the_peak():
    """Расшифровка, не сходящаяся с числом, которое объясняет, хуже её отсутствия."""
    financing = _financing(_single())
    rows = financing["actual_bridge_structure"]
    assert rows, "фактический пик обязан быть расшифрован"
    assert sum(row["value"] for row in rows) == pytest.approx(
        financing["actual_bridge"], rel=1e-6)
    assert sum(row["share"] for row in rows) == pytest.approx(1.0, abs=1e-6)


def test_the_structure_names_the_month_it_belongs_to():
    """«Оплачено к пику» без даты пика — не проверяемое утверждение."""
    financing = _financing(_single())
    assert financing["actual_bridge_month"], "месяц пика обязан быть назван"
    assert len(financing["actual_bridge_month"]) == 10


def test_the_purchase_is_the_biggest_article_when_it_is_paid():
    financing = _financing(_single())
    assert financing["actual_bridge_structure"][0]["label"].startswith("Покупка")


def test_what_the_limit_excludes_shows_up_in_the_actual():
    """Плата за смену ВРИ в расчётный лимит не входит по методике — и именно
    из-за неё фактический пик оказывался необъяснимо больше."""
    financing = _financing(_single())
    labels = [row["label"] for row in financing["actual_bridge_structure"]]
    assert any("ВРИ" in label for label in labels)
    assert financing["actual_bridge"] > financing["calculated_bridge"]


def test_a_relieved_obligation_leaves_the_structure():
    """Обнулённая льготой плата не должна висеть в расшифровке строкой на ноль."""
    financing = _financing(_single(vri_relief_mode="percent", vri_relief_pct=100.0))
    labels = [row["label"] for row in financing["actual_bridge_structure"]]
    assert not any("ВРИ" in label for label in labels)


# --- свод по очередям ---------------------------------------------------------

def test_the_consolidated_structure_is_built_on_the_common_peak():
    """Пик свода — общий месяц всех очередей, а не сумма их собственных пиков:
    расшифровка обязана собираться на тот же месяц, иначе она объясняет не то
    число, которое стоит рядом."""
    consolidated = _phased()["consolidated"]
    financing = _financing(consolidated)
    rows = financing["actual_bridge_structure"]
    assert rows
    assert sum(row["value"] for row in rows) == pytest.approx(
        financing["actual_bridge"], rel=1e-6)


def test_every_phase_carries_its_own_structure():
    for phase in _phased(2)["phases"]:
        financing = _financing(phase["result"])
        assert financing["actual_bridge_structure"]
        assert sum(row["value"] for row in financing["actual_bridge_structure"]) == pytest.approx(
            financing["actual_bridge"], rel=1e-6)


# --- поверхности показывают одно и то же --------------------------------------

def test_the_page_shows_the_structure():
    page = core.PAGE
    assert 'id="bridgeActualTable"' in page
    assert "actual_bridge_structure" in page
    assert "Структура фактического БРИДЖа" in page
    assert "Оплачено к пику" in page


def test_the_print_shows_the_same_table():
    import inspect
    source = inspect.getsource(core._build_developaid_pdf)
    assert 'financing.get("actual_bridge_structure")' in source
    assert "Структура фактического БРИДЖА" in source


def test_the_report_still_builds_with_the_new_section():
    """Отчёт обязан собираться: новая таблица не имеет права ронять печать."""
    pytest.importorskip("reportlab")
    inputs, tep = _inputs(), _tep()
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": inputs, "tep": tep,
        "rates": [], "phasing": {}, "scenario": "base", "project_name": "Проверка"})
    assert data[:4] == b"%PDF"


def test_a_project_without_a_bridge_says_so_instead_of_an_empty_table():
    page = core.PAGE
    assert "БРИДЖ не привлекался" in page
