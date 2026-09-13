"""Выручка КАЖДОГО продукта входит в налоговую базу.

Пул расходов перечислялся руками в двух местах — в налоговой базе и в
разбивке расходов отчёта, — и продукт, заведённый позже, не попал ни в один.
`object_parking` (места собственного гаража отдельно стоящего объекта, заведён
06.09.2026) собирал выручку, а налога с неё не брали вовсе: на пресете
Нагатино это 5 366,6 млн ₽ мимо базы, на проекте владельца от 13.09.2026 —
5 138,8 млн налога и 6 101,4 млн чистой прибыли. Книга считала верно и кричала
об этом своим же блоком паритета, а читать его было некому: строка «Паритет:
налог» расходилась при сходящихся выручке, CAPEX и EBITDA.

Проверка держит не список, а ТОЖДЕСТВО: сумма налоговой маржи очереди равна
«выручка − CAPEX − коммерческие − НДС». Списком она ловила бы ровно те
продукты, о которых мы вспомнили, — то есть себя. Продукт, заведённый завтра и
забытый в пуле, валит её тем, что он появился.

Запуск: python3 -m pytest tests/test_every_product_enters_the_tax_base.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core


def _project():
    """Очереди с отдельно стоящими объектами: у них и живёт собственный гараж."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["offices_enabled"] = True
    inputs["retail_enabled"] = True
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    for key, gns in (("offices", 40000.0), ("standalone_retail", 30000.0)):
        tep.setdefault(key, {})
        tep[key].update({
            "gns": gns, "total_area": gns * 0.94, "saleable": gns * 0.6,
            "units": 0, "parking_units": 300.0, "parking_saleable_units": 280.0,
        })
    phasing = {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "phases": [{"name": f"Очередь {i + 1}", "start_offset_months": 12 * i,
                    "construction_months": 24} for i in range(2)],
        "discrete": {"offices": 1, "standalone_retail": 2},
    }
    return inputs, tep, phasing


@pytest.fixture(scope="module")
def bundle():
    inputs, tep, phasing = _project()
    return core._run_authoritative_model(inputs, tep, [], phasing)


def test_the_object_garage_actually_sells_in_this_project(bundle):
    """Предохранитель: без проданных мест гаража проверка ниже не значит ничего."""
    sold = 0.0
    for phase in bundle["phases"]:
        for item in (phase["result"]["report"].get("products") or []):
            if item.get("key") == "object_parking":
                sold += float(item.get("revenue") or 0.0)
    assert sold > 0, "в проекте нет выручки собственного паркинга объектов"


def test_the_taxable_margin_of_a_queue_covers_all_of_its_revenue(bundle):
    """Сумма налоговой маржи = выручка − CAPEX − коммерческие − НДС.

    Расхождение здесь значит ровно одно: выручка какого-то продукта в базу не
    попала (или его расход признан дважды) — и налог посчитан не с того.
    """
    for index, phase in enumerate(bundle["phases"]):
        finance = phase["result"]["finance"]
        margin = sum(float(row.get("taxable_margin") or 0.0)
                     for row in finance["rows"])
        expected = (float(finance["total_revenue"])
                    - float(finance["total_capex"])
                    - float(finance["commercial_costs"])
                    - float(finance.get("vat") or 0.0))
        assert margin == pytest.approx(expected, abs=1.0), (
            f"очередь {index + 1}: маржа {margin / 1e6:.2f} млн против "
            f"{expected / 1e6:.2f} млн — выручка мимо налоговой базы")


def test_the_report_shares_the_whole_residual_cost_pool(bundle):
    """Доли остаточного пула в отчёте дают ровно пул, а не больше и не меньше.

    Знаменатель доли считался по тому же перечню, что и налоговая база: продукт,
    забытый в нём, брал свою долю из чужого знаменателя — сумма долей
    переставала быть единицей, и расход разъезжался с CAPEX.
    """
    for index, phase in enumerate(bundle["phases"]):
        report = phase["result"]["report"]
        finance = phase["result"]["finance"]
        allocated = sum(float(item.get("cost") or 0.0)
                        for item in (report.get("products") or []))
        assert allocated == pytest.approx(float(finance["total_capex"]), rel=1e-6), (
            f"очередь {index + 1}: разнесено {allocated / 1e6:.2f} млн "
            f"при CAPEX {float(finance['total_capex']) / 1e6:.2f} млн")
