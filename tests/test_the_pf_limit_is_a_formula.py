"""Лимит ПФ книга считает сама, а не переписывает число движка.

Книга обязана работать почти как движок: правка календаря очереди двигает её
выборку, а лимит — это выборка, округлённая вверх до 10 млн. Пока в клетку
писалось число, правка срока строительства прямо в Excel лимит не двигала, а
следом не двигалась и плата за невыбранный лимит: книга оставалась придатком
веб-сервиса, где считает движок.

Округляется КАЖДАЯ очередь, а не сумма: на трёх очередях округление суммы даёт
другое число, и разойтись с движком книга успела бы молча.

Запуск: python3 -m pytest tests/test_the_pf_limit_is_a_formula.py -q
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

openpyxl = pytest.importorskip("openpyxl")

BASE = {**core.DEFAULT_INPUTS, "purchase_price_mln": 12000,
        "project_start": "2027-01-01", "ird_months": 12,
        "construction_months": 24, "apartment_price_th": 700}

PHASING = {
    "enabled": True, "mode": "phased", "user_enabled": True,
    "phase_count": 3, "phase_gap_months": 12,
    "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 24},
               {"name": "О2", "start_offset_months": 12, "construction_months": 24},
               {"name": "О3", "start_offset_months": 24, "construction_months": 24}],
    "products": {key: [30, 35, 35] for key in
                 ("apartments", "ground_commercial", "underground_parking")},
    "shared_cash": {}, "shared_allocation": {}, "social_objects": [],
    "carry_debt_forward": False,
}


def book(phasing, **overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, core.TEP_DEFAULT, [], phasing, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def evaluated(workbook):
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(workbook)


@pytest.fixture(scope="module")
def single():
    return book({})


@pytest.fixture(scope="module")
def phased():
    return book(PHASING)


def test_the_limit_is_a_formula_not_a_number(single):
    """Число здесь неотличимо от посчитанного и не двигается ни от чего."""
    value = single["Вводные"]["B26"].value
    assert isinstance(value, str) and value.startswith("=") and "CF_1" in value


def test_the_share_of_a_queue_is_a_formula_too(phased):
    """Доля от числа при живом лимите разошлась бы с ним на первой же правке."""
    for row in range(88, 92):
        value = phased["Вводные"][f"V{row}"].value
        assert isinstance(value, str) and value.startswith("="), f"V{row}"


def test_the_limit_equals_the_engine_on_one_queue(single):
    result = core.calculate(core.CalcRequest(
        inputs=BASE, tep=core.TEP_DEFAULT, rates=[]))
    engine = (result["report"]["financing"].get("pf_limit") or 0) / 1_000_000
    assert engine > 0
    assert evaluated(single).cell("Вводные", "B26") == pytest.approx(engine, abs=0.01)


def test_the_limit_equals_the_engine_on_three_queues(phased):
    """Ради чего округляется каждая очередь: сумма округлений — не округление суммы."""
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=BASE, tep=core.TEP_DEFAULT, rates=[], phasing=PHASING))
    limits = [(phase["result"]["report"]["financing"].get("pf_limit") or 0) / 1_000_000
              for phase in bundle["phases"]]
    assert len(limits) == 3 and all(limit > 0 for limit in limits)

    evaluator = evaluated(phased)
    total = evaluator.cell("Вводные", "B26")
    assert total == pytest.approx(sum(limits), abs=0.01)

    shares = [evaluator.cell("Вводные", f"V{row}") for row in range(88, 92)]
    assert sum(shares) == pytest.approx(1.0, abs=1e-9)
    for index, limit in enumerate(limits):
        assert total * shares[index] == pytest.approx(limit, abs=0.01), f"очередь {index + 1}"


def test_a_longer_queue_moves_the_limit_inside_excel():
    """То, ради чего формула: правка вводной в самой книге двигает лимит.

    Проверяется не подстановкой числа движка, а пересчётом книги: срок
    строительства длиннее — расходы дороже с инфляцией, выборка больше,
    лимит выше. Число на этом месте осталось бы прежним."""
    short = evaluated(book({}, construction_months=24)).cell("Вводные", "B26")
    long = evaluated(book({}, construction_months=36)).cell("Вводные", "B26")
    assert long > short, (short, long)


def test_the_limit_is_a_multiple_of_ten(phased):
    """Методика движка — округление вверх до 10 млн, и книга округляет так же."""
    total = evaluated(phased).cell("Вводные", "B26")
    assert total % 10 == pytest.approx(0.0, abs=1e-6)
