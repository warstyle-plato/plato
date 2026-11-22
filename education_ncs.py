"""НЦС-2026: удельная стоимость образовательного объекта в базовых ценах МО."""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
import copy
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads((Path(__file__).parent / "reference_data/education_ncs_2026.json").read_text())


def catalog() -> dict:
    return copy.deepcopy(_data())


def rate(kind: str, table_id: str, places: Decimal) -> dict:
    """Выбор конструкции явный; мощность — всего объекта, не льготного профицита.

    Пп. 39–40: удельная интерполяция и крайняя ставка в пределах 10%.
    Другие способы оценки, в том числе по строительному объёму, здесь не
    подменяются экстраполяцией: для них можно ввести отдельно рассчитанную ставку.
    """
    table = next((t for t in _data()["tables"] if t["id"] == table_id and t["kind"] == kind), None)
    if table is None:
        raise ValueError("Выберите тип школы или ДОО по НЦС.")
    if places <= 0 or places != places.to_integral_value():
        raise ValueError("Для НЦС укажите полную проектную мощность: целое положительное число мест.")
    points = table["points"]
    lower, upper = points[0], points[-1]
    selected = []
    method = "Точное значение НЦС"
    for point in points:
        if places == point["places"]:
            selected = [point]
            break
    if not selected:
        if places < lower["places"] or places > upper["places"]:
            edge = lower if places < lower["places"] else upper
            if abs(places - edge["places"]) > Decimal(edge["places"]) * Decimal("0.1"):
                raise ValueError("Мощность вне диапазона подбора ставки НЦС по местам. "
                                 "Укажите отдельно рассчитанную стоимость места и её источник.")
            selected, method = [edge], "Крайний показатель НЦС: отклонение мощности не больше 10%"
        else:
            for a, c in zip(points, points[1:]):
                if a["places"] < places < c["places"]:
                    selected, method = [a, c], "Интерполяция удельной ставки НЦС, п. 39"
                    break
    if len(selected) == 1:
        value = Decimal(selected[0]["thousand_rub_per_place"]) * 1000
    else:
        a, c = selected
        pa, pc = (Decimal(p["thousand_rub_per_place"]) * 1000 for p in selected)
        value = pa + (places - a["places"]) * (pc - pa) / (c["places"] - a["places"])
    return {"rate": value, "table": table["id"], "label": table["label"],
            "method": method, "points": copy.deepcopy(selected),
            "scope": "one_building", "capacity_used": float(places),
            "source_url": _data()["source_url"], "price_date": _data()["price_date"],
            "vat": "без НДС", "region": "Московская область"}
