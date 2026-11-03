"""Подземная СМР — 0,8 наземной, и это отношение, а не три числа.

Решение владельца 27.08.2026. Прежде обе ставки были равны — метр подземного
гаража стоил ровно столько же, сколько метр жилого дома. Держалось это не на
основании, а на том, что ставки пережили переделку профиля классов
нетронутыми. Свод «Статистики» говорит обратное (подземная там дороже
наземной), но стоит на ОДНОМ наблюдении: это единственный источник с раскрытой
подземной частью, консультанты её не выделяют вовсе. Владелец признал точку
непоказательной: «надо все-таки наземную делать на 20 проц ниже».

Проверяется отношение, а не три конкретных числа: ставки классов правят, и
тест, зашивший 88 / 152 / 240, придётся править вместе с ними — он перестанет
защищать решение и станет его копией.

Запуск: python3 -m pytest tests/test_the_underground_costs_less_than_the_ground.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core

RATIO = 0.8


@pytest.mark.parametrize("key", sorted(core.PROJECT_CLASS_PRESETS))
def test_every_class_keeps_the_ratio(key):
    preset = core.PROJECT_CLASS_PRESETS[key]
    above = float(preset["main_above_th_per_sqm"])
    under = float(preset["main_under_th_per_sqm"])
    assert above > 0, f"«{key}»: наземная ставка не задана"
    assert under == pytest.approx(above * RATIO, rel=1e-6), (
        f"«{key}»: подземная {under} при наземной {above} — отношение "
        f"{under / above:.3f}, а решение владельца — {RATIO}")


def test_the_default_keeps_it_too():
    above = float(core.DEFAULT_INPUTS["main_above_th_per_sqm"])
    under = float(core.DEFAULT_INPUTS["main_under_th_per_sqm"])
    assert under == pytest.approx(above * RATIO, rel=1e-6)


def test_the_classes_are_not_all_the_same_rate():
    """Предохранитель. Совпади все три класса — проверка отношения прошла бы и
    на пресетах, потерявших различие между комфортом и элиткой."""
    rates = {float(p["main_above_th_per_sqm"]) for p in core.PROJECT_CLASS_PRESETS.values()}
    assert len(rates) == len(core.PROJECT_CLASS_PRESETS), (
        "наземные ставки классов обязаны различаться")
