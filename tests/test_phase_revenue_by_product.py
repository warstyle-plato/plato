"""Выручка очереди разложена по продуктам — и на экране, и в книге.

В сравнении очередей выручка стояла одной строкой. Она не отвечает на вопрос,
чем очередь живёт: у одной весь объём в квартирах, у другой треть в паркинге и
ОСЗ, а маржа и риск у них разные (владелец, 23.08.2026). Числа для разбивки
лежали в отчёте каждой очереди и просто не выводились.

Разбивка не считается заново: берётся `report.products` очереди. Второй счёт
той же выручки однажды разошёлся бы с первым, и обе строки выглядели бы верными.

Запуск: python3 -m pytest tests/test_phase_revenue_by_product.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture(scope="module")
def bundle():
    inputs = dict(core.DEFAULT_INPUTS)
    # Офисы и ОСЗ включены нарочно: с одними квартирами разбивка ничего не
    # показывает, а вся её польза — в очереди со смешанным составом.
    inputs.update({"offices_enabled": True, "retail_enabled": True})
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(
        inputs, tep, [], {"enabled": True, "phase_count": 2, "phase_gap_months": 12})


# --- разбивка едет из расчёта -------------------------------------------------

def test_every_queue_carries_its_revenue_by_product(bundle):
    for item in bundle["comparison"]:
        assert item["revenue_by_product"], f"{item['name']}: разбивки нет"
        assert item["saleable_by_product"], f"{item['name']}: объёма продаж нет"


def test_the_parts_add_up_to_the_queue_revenue(bundle):
    """Сумма продуктов — это и есть выручка очереди, а не близкое к ней число."""
    for item in bundle["comparison"]:
        assert sum(item["revenue_by_product"].values()) == pytest.approx(
            item["revenue"], rel=1e-9), item["name"]


def test_the_queues_add_up_to_the_project(bundle):
    """По каждому продукту сумма очередей сходится со сводом."""
    consolidated = {str(p["key"]): float(p.get("revenue") or 0.0)
                    for p in bundle["consolidated"]["report"]["products"]}
    for key, total in consolidated.items():
        by_queue = sum(float((item["revenue_by_product"] or {}).get(key) or 0.0)
                       for item in bundle["comparison"])
        assert by_queue == pytest.approx(total, rel=1e-9), key


def test_the_split_is_not_counted_a_second_time():
    """Числа берутся из отчёта очереди, а не считаются здесь заново."""
    import inspect

    source = inspect.getsource(core.calculate_phased)
    block = source[source.index('"revenue_by_product"'):]
    block = block[:block.index('"cash_shared_cost"')]
    assert 'report' in block and 'products' in block
    assert "price" not in block and "*" not in block, "разбивка снова считается своей формулой"


def test_a_discrete_object_lands_in_one_queue_only(bundle):
    """Офисы и ОСЗ размещаются дискретно — выручка обязана стоять в своей
    очереди целиком, а не размазаться по всем."""
    for key in ("offices", "standalone_retail"):
        values = [float((item["revenue_by_product"] or {}).get(key) or 0.0)
                  for item in bundle["comparison"]]
        assert sum(1 for v in values if v > 0) == 1, f"{key}: {values}"


# --- экран --------------------------------------------------------------------

def test_the_screen_lists_the_products_under_revenue():
    page = core.PAGE
    found = re.search(r"\nfunction renderPhaseComparison\(.*?\n\}", page, re.S)
    assert found, "функция сравнения очередей на странице не найдена"
    body = found.group(0)
    assert "revenue_by_product" in body
    # Строки продуктов стоят сразу под выручкой, а не в конце таблицы.
    revenue = body.index("['Выручка',")
    assert body.index("...prodRows") > revenue
    assert body.index("['Цена реализации на м² продаваемой'") > body.index("...prodRows")


def test_the_screen_hides_products_without_revenue():
    """Семь нулевых строк — это шум, а не полнота."""
    body = re.search(r"\nfunction renderPhaseComparison\(.*?\n\}", core.PAGE, re.S).group(0)
    assert "filter(k=>c.some(x=>Number((x.revenue_by_product||{})[k]||0)>0))" in body


# --- книга --------------------------------------------------------------------

def _sheet(bundle):
    sheet = core._model_sheet_phase_comparison(bundle)
    rows = sheet["rows"]
    header = [getattr(cell, "value", cell) for cell in rows[3]]
    return header, rows


def test_the_workbook_has_the_same_columns(bundle):
    header, _ = _sheet(bundle)
    titles = [h for h in header if isinstance(h, str) and h.startswith("Выручка · ")]
    assert titles, "в книге разбивки нет — книга и экран скажут разное"
    labels = {p["label"] for p in bundle["consolidated"]["report"]["products"]}
    for title in titles:
        assert title[len("Выручка · "):-len(", млн ₽")] in labels


def test_the_workbook_total_row_sums_each_product(bundle):
    header, rows = _sheet(bundle)
    columns = [i for i, h in enumerate(header)
               if isinstance(h, str) and h.startswith("Выручка · ")]
    queues = rows[4:4 + len(bundle["comparison"])]
    total = rows[4 + len(bundle["comparison"])]
    assert getattr(total[0], "value", total[0]) == "Итого"
    for index in columns:
        by_queue = sum(float(getattr(row[index], "value", 0) or 0) for row in queues)
        assert float(getattr(total[index], "value", 0) or 0) == pytest.approx(by_queue)


def test_a_project_without_extra_products_gets_no_empty_columns():
    """Колонка заводится под продукт, у которого выручка есть."""
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    plain = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS), tep, [],
        {"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    header, _ = _sheet(plain)
    titles = [h for h in header if isinstance(h, str) and h.startswith("Выручка · ")]
    assert titles, "разбивка пропала совсем"
    assert not any("Офисы" in t or "ОСЗ" in t for t in titles), titles
