"""Пресет знает все продукты движка, включая заведённые позже.

Копия списка здесь вынужденная: движок импортирует `project_preset`, обратной
дороги нет, и спросить `TEP_DEFAULT` из него нельзя. Цена копии уже была
заплачена — ФОК завели четвёртым отдельно стоящим объектом 05.09.2026, а в
список продуктов очереди он не попал, и метры, объявленные на очереди, до
расчёта не доезжали: рядом с именем очереди терялся сам ФОК, вложенной формой
не проходило НИЧЕГО. Ровно та же поломка, что стоила «Очереди 4 · ТЦ», где
подпись была от пресета, а объект — от умолчания движка.

Копия, за которой следят, отличается от копии, которая расходится молча.

Запуск: python3 -m pytest tests/test_the_preset_knows_every_product.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import project_preset as preset  # noqa: E402


def test_the_phase_product_list_matches_the_engine() -> None:
    """Продукт, заведённый в движке, обязан появиться и здесь.

    Сверяется СОСТАВ, а не длина: список из двенадцати чужих имён прошёл бы
    проверку на число.
    """
    assert tuple(preset.PHASE_PRODUCT_KEYS) == tuple(core.TEP_DEFAULT), (
        "список продуктов очереди разошёлся с движком; нет здесь: "
        f"{sorted(set(core.TEP_DEFAULT) - set(preset.PHASE_PRODUCT_KEYS))}, "
        f"нет у движка: {sorted(set(preset.PHASE_PRODUCT_KEYS) - set(core.TEP_DEFAULT))}")


def test_metres_declared_on_a_phase_reach_the_engine() -> None:
    """Проверяется то, что видно: доезжают ли метры, а не совпадают ли списки.

    Обе формы записи — рядом с именем очереди и вложенная в `products`, —
    потому что ломались обе и по-разному: первая теряла один продукт, вторая
    не отдавала ничего.
    """
    for key in core.TEP_DEFAULT:
        beside = preset._phase_products({"name": "О1", key: {"gns": 8000}})
        assert key in beside, f"метры {key}, объявленные рядом с именем очереди, потерялись"
        nested = preset._phase_products({"name": "О1", "products": {key: {"gns": 8000}}})
        assert key in nested, f"метры {key}, объявленные вложенной формой, потерялись"


def test_the_check_fails_when_the_list_falls_behind() -> None:
    """Предохранитель: сторож обязан падать на отставшем списке.

    Проверка, которая не падает на поломке, — не проверка. Убираем последний
    продукт, как когда-то не добавили ФОК.
    """
    full = preset.PHASE_PRODUCT_KEYS
    try:
        preset.PHASE_PRODUCT_KEYS = full[:-1]
        assert tuple(preset.PHASE_PRODUCT_KEYS) != tuple(core.TEP_DEFAULT)
        lost = preset._phase_products({"name": "О1", full[-1]: {"gns": 8000}})
        assert full[-1] not in lost, "предохранитель: продукт не потерялся, проверять нечего"
    finally:
        preset.PHASE_PRODUCT_KEYS = full
