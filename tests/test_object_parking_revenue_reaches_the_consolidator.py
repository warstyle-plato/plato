"""Выручка паркинга объектов доезжает до свода очередей.

Свод несёт колонку «Выручка · продукт» на очередь — она и отвечает, чем
очередь живёт. Продукт «паркинг отдельно стоящих объектов» завели позже обеих
карт свода (06.09.2026), и колонка не строилась ВОВСЕ: книга честно писала это
в `missing`, но на живом проекте с офисником строка свода молчала о 735,9 млн ₽.

Проверка держит два утверждения: книга не отказывается считать этот продукт, и
число в колонке равно тому, что посчитал движок для ТОЙ ЖЕ очереди. Первое без
второго зелено и у колонки, собранной не из тех строк.

Запуск: python3 -m pytest tests/test_object_parking_revenue_reaches_the_consolidator.py -q
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

PRODUCT = "object_parking"


def _phasing() -> dict:
    return {
        "enabled": True, "phase_count": 3, "phase_gap_months": 24,
        "cost_inflation_pct": 8,
        "phases": [{"name": f"О{i + 1}", "start_offset_months": 24 * i,
                    "construction_months": 24} for i in range(3)],
        "products": {key: [40, 35, 25] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [],
        # Офисник во ВТОРОЙ очереди: его гараж — единственный, чьи места
        # продаются, и очередь у колонки обязана быть его, а не первая.
        "discrete": {"offices": 2, "standalone_retail": 2,
                     "above_parking": 3, "sports": 3},
    }


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, retail_enabled=True, sports_enabled=True,
             sports_disposition="sale",
             offices_parking_under_spaces=300, offices_parking_over_spaces=80,
             retail_parking_under_spaces=210, sports_parking_under_spaces=90)
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key, gns, saleable in (("offices", 40000, 34000),
                               ("standalone_retail", 22000, 18000),
                               ("sports", 9000, 7500)):
        t[key] = {**t[key], "gns": gns, "total_area": gns * 0.94, "saleable": saleable}
    return t


@pytest.fixture(scope="module")
def built() -> tuple[bytes, dict, list[float]]:
    """Книга, её `missing` и выручка паркинга объектов по очередям у движка."""
    inputs, tep, phasing = _inputs(), _tep(), _phasing()
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    hints = core._v4_finance_hints(bundle)
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="П", finance_hints=hints)
    engine = []
    for phase in bundle["phases"]:
        products = phase["result"]["report"]["products"]
        hit = [p for p in products if p.get("key") == PRODUCT]
        engine.append((hit[0].get("revenue", 0.0) if hit else 0.0) / 1e6)
    return content, meta, engine


def test_the_book_does_not_refuse_this_product(built) -> None:
    """Отказ книги — названный пробел, и он про деньги очереди."""
    _content, meta, _engine = built
    refusals = [line for line in meta["missing"] if "не умеет считать выручку" in line]
    assert refusals == [], refusals


def test_the_column_carries_the_engines_number_for_the_same_queue(built) -> None:
    """Колонка считает то же, что движок, и у ТОЙ ЖЕ очереди.

    Предохранитель: у одной из очередей выручка обязана быть ненулевой —
    сравнение четырёх нулей с четырьмя нулями зелено при любой формуле.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    content, _meta, engine = built
    assert max(engine) > 0, "на этих вводных паркинг объектов не продаётся — сверять нечего"

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    label = core.NON_TEP_PRODUCT_LABELS[PRODUCT]
    sheet = evaluator.workbook["КОНСОЛИДАТОР"]
    columns = [cell.column_letter for cell in sheet[3]
               if isinstance(cell.value, str) and label in cell.value]
    assert len(columns) == 1, f"колонок «{label}» в своде {len(columns)}"

    book = [evaluator.cell("КОНСОЛИДАТОР", f"{columns[0]}{row}") or 0.0
            for row in (4, 5, 6, 7)]
    expected = engine + [0.0] * (4 - len(engine))
    assert [round(v, 2) for v in book] == [round(v, 2) for v in expected]


def test_the_column_is_built_from_the_rows_already_declared(built) -> None:
    """Строки берутся из `_V4_OBJECT_PARKING`, а не выписываются второй раз.

    Второй список «где лежит выручка гаража» разошёлся бы с первым молча.
    """
    openpyxl = pytest.importorskip("openpyxl")
    content, _meta, _engine = built
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    sheet = book["КОНСОЛИДАТОР"]
    label = core.NON_TEP_PRODUCT_LABELS[PRODUCT]
    column = next(cell.column_letter for cell in sheet[3]
                  if isinstance(cell.value, str) and label in cell.value)
    formula = str(sheet[f"{column}4"].value)
    for _label, enabled_row, _units, revenue_row, *_rest in core._V4_OBJECT_PARKING:
        assert f"$B${enabled_row + 1}=1" in formula, formula
        assert f"$B${revenue_row}" in formula, formula
