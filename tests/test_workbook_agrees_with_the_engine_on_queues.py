"""Книга и движок считают один проект — проверяет машина, а не глаз.

Расхождение поверхностей находилось скриншотом. На Мытищах с тремя очередями
отчёт и PDF показывали 8 169 машино-мест, книга — верные 2 723; узнали об этом
через несколько дней и случайно. Книга при этом была права: она берёт числа из
делёжки очередей, а та работала всегда — врал движок, и вместе с ним всё, что
считает через него.

Сверка книги с движком в проекте есть (`audit_plato_workbook`), но она требует
книгу, пересчитанную Excel: openpyxl формул не считает. Поэтому на свежей
сборке она не работает, и в наборе её нет. `xlsx_eval` считает формулы прямо
здесь — значит сверка может быть обычным тестом, а не ручной проверкой раз в
месяц.

Проверяются ТЭП-числа очередей: именно они разошлись, и именно на них у книги
и движка два независимых пути.

Запуск: python3 -m pytest tests -q
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

openpyxl = pytest.importorskip("openpyxl")

# Колонки таблицы очередей на листе «Вводные»: строка 87 — заголовок,
# 88–91 — четыре очереди.
QUEUE_ROWS = range(88, 92)
COLUMNS = {
    "apartments_gns": "I",
    "commercial_gns": "J",
    "underground_gns": "K",
    "apartments_saleable": "L",
    "commercial_saleable": "M",
    "parking_units": "N",
    "storage_units": "O",
}


def phasing(count: int) -> dict:
    return {"enabled": True, "mode": "phased", "phase_count": count, "user_enabled": True,
            "phase_gap_months": 12,
            "phases": [{"name": f"О{i+1}", "start_offset_months": 12 * i,
                        "construction_months": 30} for i in range(count)]}


@pytest.fixture(scope="module")
def project():
    """Мытищи: подземный паркинг задан решением проекта — то сочетание, на
    котором поверхности и разошлись."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, social_mode="Денежная компенсация",
                  social_compensation_mln=575.0,
                  underground_manual_spaces=2723, underground_manual_gns_sqm=95305)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["underground_parking"].update(units=2723, gns=95305, total_area=95305)
    return inputs, tep


def workbook_queue_totals(inputs, tep, count) -> dict[str, float]:
    """Суммы по очередям из посчитанной книги."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    content, _, _ = core.build_project_workbook(
        inputs, tep, [], phasing(count), project_name="Сверка")
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    totals: dict[str, float] = {}
    for name, column in COLUMNS.items():
        total = 0.0
        for row in QUEUE_ROWS:
            value = evaluator.cell("Вводные", f"{column}{row}")
            if isinstance(value, (int, float)):
                total += float(value)
        totals[name] = total
    return totals


def engine_queue_totals(inputs, tep, count) -> dict[str, float]:
    """Те же суммы из расчёта движка."""
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    totals = {name: 0.0 for name in COLUMNS}
    for phase in bundle["phases"]:
        rows = {row["key"]: row for row in phase["result"]["tep"]["rows"]}
        totals["apartments_gns"] += float(rows.get("apartments", {}).get("gns") or 0)
        totals["commercial_gns"] += float(rows.get("ground_commercial", {}).get("gns") or 0)
        totals["underground_gns"] += float(rows.get("underground_parking", {}).get("gns") or 0)
        totals["apartments_saleable"] += float(rows.get("apartments", {}).get("saleable") or 0)
        totals["commercial_saleable"] += float(
            rows.get("ground_commercial", {}).get("saleable") or 0)
        totals["parking_units"] += float(rows.get("underground_parking", {}).get("units") or 0)
        totals["storage_units"] += float(rows.get("storage", {}).get("units") or 0)
    return totals


# --- книга против движка ---------------------------------------------------------

@pytest.mark.parametrize("count", [2, 3])
def test_the_book_and_the_engine_split_the_queues_alike(project, count):
    """Та самая проверка, которой не было: 8 169 против 2 723 упали бы здесь."""
    inputs, tep = project
    book = workbook_queue_totals(inputs, tep, count)
    engine = engine_queue_totals(inputs, tep, count)
    for name in COLUMNS:
        assert book[name] == pytest.approx(engine[name], rel=0.01, abs=1.0), (
            f"{name}: книга {book[name]:.0f}, движок {engine[name]:.0f}")


def test_both_keep_the_project_total(project):
    """И обе суммы равны исходному ТЭП — иначе они согласованно неверны."""
    inputs, tep = project
    book = workbook_queue_totals(inputs, tep, 3)
    assert book["parking_units"] == pytest.approx(2723, abs=1.0)
    assert book["underground_gns"] == pytest.approx(95305, rel=0.01)
    assert book["apartments_saleable"] == pytest.approx(
        tep["apartments"]["saleable"], rel=0.01)


def test_the_queue_table_is_not_empty(project):
    """Пустая книга сошлась бы с чем угодно: сверка, которой нечего сверять,
    зелена всегда."""
    inputs, tep = project
    book = workbook_queue_totals(inputs, tep, 3)
    assert book["parking_units"] > 0 and book["apartments_gns"] > 0
