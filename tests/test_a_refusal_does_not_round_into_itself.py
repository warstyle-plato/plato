"""Отказ подбора не округляет два своих числа в одно.

Снимок владельца (06.09.2026), площадка «Маршала Прошлякова ул., вл. 9»:
«LLCR не ниже 1,20x не достигается ни при одном значении „Цена покупки, млн ₽"
в диапазоне 0–479 930 — даже при нулевом значении выходит 1,20x». Счёт верен —
у площадки 1,197x, — а фраза противоречит сама себе: порог и достигнутое
округлились в одно число, и отказ читается как ошибка расчёта.

Знаков берём столько, чтобы числа фразы различались, и только когда они и
правда разные: «1,05x» против «1,20x» третьего знака не требует.

Запуск: python3 -m pytest tests/test_a_refusal_does_not_round_into_itself.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy  # noqa: E402


def _reason(closest: float, target: float = 1.20) -> str:
    return main_legacy._goal_refusal_reason(
        "весь проект", "purchase_price_mln", "llcr", target, "at_least",
        0.0, 479_930.0, 0.0, closest, "весь проект")


def test_the_threshold_and_the_best_are_two_different_numbers():
    said = _reason(1.197)
    assert "1,197x" in said, said
    assert "1,200x" in said, "порог остался с двумя знаками — числа снова равны"
    # Ровно то, из-за чего фраза читалась как ошибка счёта.
    assert said.count("1,20x") == 0, said


def test_a_number_that_differs_already_keeps_two_digits():
    """Кратность банка читают с двумя знаками — лишние появляются по нужде."""
    said = _reason(1.05)
    assert "не ниже 1,20x" in said, said
    assert "выходит 1,05x" in said, said
    assert "1,050x" not in said, "знаки добавлены там, где числа и так различны"
