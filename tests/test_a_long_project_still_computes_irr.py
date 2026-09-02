"""Длинный горизонт не роняет расчёт делением на ноль.

IRR ищется перебором ставок, и нижняя граница перебора — −95% в месяц. На
проекте из пяти очередей с длинными остаточными продажами ряд доходит до 250+
месяцев, а 0,05 в 240-й степени — это уже машинный ноль: деление на него роняло
`calculate_phased` целиком (площадка КРТ «Магистральные улицы», 02.09.2026).
Ноль в знаменателе здесь не ошибка данных, а предел арифметики.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


def test_a_three_hundred_month_series_does_not_divide_by_zero(core):
    flows = [-100.0] + [0.0] * 300 + [500.0]
    irr = core._monthly_irr(flows)
    assert irr is not None and irr > 0


def test_a_short_series_keeps_its_answer(core):
    """Правка границы не имеет права сдвинуть обычный ответ."""
    irr = core._monthly_irr([-100.0, 10.0, 20.0, 30.0, 60.0, 40.0])
    assert irr == pytest.approx(3.938401, rel=1e-4)


def test_a_series_without_a_sign_change_has_no_irr(core):
    assert core._monthly_irr([-1.0, -2.0, -3.0]) is None
