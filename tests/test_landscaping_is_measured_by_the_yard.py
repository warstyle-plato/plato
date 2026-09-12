"""Благоустройство меряется площадью ДВОРА, а не строительным объёмом.

«Благоустройство — 5 метров на человека, далее по площади комфорт 10, бизнес
25, элитный 50 на метр» (решение владельца, 10.09.2026). Прежняя ставка 11,5
тыс ₽ умножалась на строительный объём: на умолчаниях это 2 060,2 млн ₽ против
121,2 по норме — в семнадцать раз больше. Число было посчитано верно и
прочитано неверно, потому что подпись звала базу «строительный объём», а
благоустраивают двор.

Мера одна — м² на человека, — и заданная руками площадь приводится к ней: тогда
очередь считает свою площадь своим населением, и сумма очередей сходится с
проектом без второго списка «что делить долями».

Запуск: python3 -m pytest tests/test_landscaping_is_measured_by_the_yard.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402


def _tep():
    return copy.deepcopy(core.TEP_DEFAULT)


def _single(**extra):
    inputs = {**core.DEFAULT_INPUTS, **extra}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=_tep(), rates=[]))


def _phased(count: int, **extra):
    inputs = {**core.DEFAULT_INPUTS, **extra}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=_tep(), rates=[],
        phasing={"enabled": True, "phase_count": count, "phase_gap_months": 24}))


def test_the_area_is_the_population_times_the_norm():
    result = _single()
    summary = result["summary"]
    # 80 000 м² квартир ÷ 33 = 2 425 человек; 5 м² на человека.
    assert summary["landscaping_area_sqm"] == pytest.approx(2425 * 5)
    assert "2425 чел" in summary["landscaping_basis"], summary["landscaping_basis"]
    assert result["capex"]["landscaping"] == pytest.approx(2425 * 5 * 10 * 1000)


def test_the_rate_follows_the_class():
    """Ставка класса — 10 / 25 / 50, и на странице копии её нет."""
    rates = {key: preset["landscaping_th_per_sqm"]
             for key, preset in core.PROJECT_CLASS_PRESETS.items()}
    assert rates == {"comfort": 10, "business": 25, "elite": 50}
    for key, rate in rates.items():
        preset = {k: v for k, v in core.PROJECT_CLASS_PRESETS[key].items() if k != "label"}
        money = _single(project_class=key, **preset)["capex"]["landscaping"]
        assert money == pytest.approx(2425 * 5 * rate * 1000), key


def test_the_base_is_not_the_construction_volume():
    """Сторож, не падающий на прежней базе, — не сторож.

    Прежняя база дала бы на умолчаниях 1,79 млн м² × ставку: разница в
    семнадцать раз, и на экране она выглядела бы обычным числом.
    """
    result = _single()
    volume = result["summary"]["construction_volume_sqm"]
    assert volume > 100_000, volume
    assert result["summary"]["landscaping_area_sqm"] < volume / 10, (
        "база благоустройства подозрительно похожа на строительный объём")


def test_a_given_area_wins_over_the_norm():
    result = _single(landscaping_area_sqm=20_000)
    assert result["summary"]["landscaping_area_sqm"] == pytest.approx(20_000, rel=1e-9)
    assert "задана площадь" in result["summary"]["landscaping_basis"]


def test_the_queues_do_not_landscape_the_same_yard_twice():
    """Заданная площадь — величина ПРОЕКТА: оставленная очереди целиком, она
    благоустроила бы один двор столько раз, сколько очередей."""
    project = _single(landscaping_area_sqm=20_000)["summary"]["landscaping_area_sqm"]
    per_person, _ = core.landscaping_area_per_person(
        {**core.DEFAULT_INPUTS, "landscaping_area_sqm": 20_000}, core.TEP_DEFAULT)
    for count in (2, 3, 4):
        total = _phased(count, landscaping_area_sqm=20_000)["consolidated"]["summary"][
            "landscaping_area_sqm"]
        # Население очереди округляется ВВЕРХ — человек неделим, — и сумма
        # очередей выходит больше проектной не более чем на одного человека с
        # очереди. Это округление неделимого, а не расхождение методики.
        assert total >= project
        assert total - project <= per_person * count, (count, total, project)


def test_the_norm_path_also_adds_up_by_queues():
    project = _single()["summary"]["landscaping_area_sqm"]
    total = _phased(3)["consolidated"]["summary"]["landscaping_area_sqm"]
    assert total == pytest.approx(project, rel=1e-6)


def test_the_region_norm_is_declared_once():
    """Население — от площади квартир нормой региона, и норма не копия."""
    msk = core.project_population(core.TEP_DEFAULT, "msk")
    mo = core.project_population(core.TEP_DEFAULT, "mo")
    assert msk[0] == 2425 and "945-ПП" in msk[1]
    assert mo[0] == 2858 and "РНГП" in mo[1]
    assert str(int(core._PARKING_2118_SQM_PER_PERSON)) in msk[1]
    assert str(int(core.MO_NORMS_DEFAULT["living_space_per_person_sqm"])) in mo[1]


def test_the_fields_name_their_base():
    """Подпись ставки называет свою базу: на прежней стояло «строительного
    объёма», и человек вписал бы ставку на метр двора."""
    hints = {field[0]: field[2] for group in core.FIELD_GROUPS for field in group[1]
             if str(field[0]).startswith("landscaping")}
    assert set(hints) == {"landscaping_th_per_sqm", "landscaping_area_sqm",
                          "landscaping_area_per_person_sqm"}
    assert "БЛАГОУСТРОЕННОЙ" in hints["landscaping_th_per_sqm"]
    # Запрещается МЕСТО, а не слово: прежняя подпись ОБЪЯВЛЯЛА базой
    # строительный объём, а нынешняя называет его, чтобы сказать «не он».
    assert "м² строительного объёма" not in hints["landscaping_th_per_sqm"]


def test_the_workbook_reads_the_same_base():
    """Книга не придаток веб-сервиса: площадь двора она считает формулой."""
    openpyxl = pytest.importorskip("openpyxl")
    import v4_entry_sheet

    content, _name, report = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), _tep(), [], {}, project_name="Двор")
    assert not [one for one in (report.get("missing") or [])
                if "благоустрой" in str(one).lower()], report.get("missing")
    book = openpyxl.load_workbook(io.BytesIO(content))
    formula = book["CAPEX"]["B24"].value
    # База — население очереди, а не сумма трёх ГНС.
    queue_flats = v4_entry_sheet.rename_in_formula("'Вводные'!$L$88")
    assert "ROUNDUP" in formula and queue_flats in formula, formula
    assert v4_entry_sheet.rename_in_formula("'Вводные'!$I$88") not in formula, formula

    sys.setrecursionlimit(400_000)
    from xlsx_eval import Evaluator

    ev = Evaluator(book)
    engine = _single()["capex"]["landscaping"] / 1e6
    assert float(ev.cell("CAPEX", "B24")) == pytest.approx(engine, rel=1e-6)


def test_an_unrecognised_template_formula_is_named():
    """Не опознали формулу — это `missing`, а не тихий счёт по прежней базе."""
    missing: list[str] = []
    core._v4_apply_landscaping_base("<x:sheetData/>", "$B$1", "$B$2", missing)
    assert len(missing) == core._V4_CAPEX_PHASES, missing
    assert all("благоустрой" in one.lower() for one in missing), missing
