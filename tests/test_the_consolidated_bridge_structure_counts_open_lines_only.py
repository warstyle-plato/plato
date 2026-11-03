"""Расшифровка пика БРИДЖа свода — только по очередям, чья линия в этот месяц открыта.

На своде четырёх очередей таблица «Структура фактического БРИДЖа» стояла с
датой декабрь 2030 и долями 147,9% у наземной части, 64,3% у офисов, 2,5 млрд ₽
проектирования (владелец, 03.09.2026: «Что за бридж 2030, если проект сейчас?
Что за 2 ярда на ПИР в бридже?»). Дата верна: у каждой очереди своя линия до
открытия её ПФ, и пик свода приходится на ту, что в этот месяц крупнее. Неверна
была расшифровка: она складывала оплаченное ВСЕМИ очередями к этому месяцу,
включая те, что давно на ПФ, — 148% по одной статье это и есть чужие расходы,
а «2 ярда проектирования» — проектирование трёх очередей при одной на БРИДЖе.

Закреплено:
- в расшифровку входят только очереди с открытой линией в месяц пика, и она
  сходится с пиком без строки «Покрыто выручкой и ПФ»;
- ответ называет, чья линия открыта, чья уже закрыта и чья ещё не начата;
- сценарий держит очередь, которая к пику свода УЖЕ на ПФ, — иначе фильтр
  не проверяется вовсе.

Запуск: python3 -m pytest tests/test_the_consolidated_bridge_structure_counts_open_lines_only.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture(scope="module")
def phased() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, purchase_price_mln=1500)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    # Шаг в три года: вторая очередь начинает, когда первая уже на ПФ, а
    # три четверти продукта и вся покупка лежат на ней — её линия крупнее, и
    # пик свода уходит туда.
    phasing = {
        "enabled": True, "phase_count": 2, "phase_gap_months": 36,
        "cost_inflation_pct": 8,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 36, "construction_months": 24},
        ],
        "products": {key: [25, 75] for key in ("apartments", "ground_commercial", "underground_parking", "storage")},
        "shared_cash": {"purchase": [0, 100], "land_rights": [0, 100]},
        "social_objects": [],
        "discrete": {"offices": 2, "standalone_retail": 2, "above_parking": 2},
    }
    return core.calculate_phased(core.PhasedCalcRequest(inputs=inputs, tep=tep, phasing=phasing))


def _financing(bundle: dict) -> dict:
    return bundle["consolidated"]["report"]["financing"]


def test_the_scenario_has_a_queue_already_on_pf_at_the_peak(phased: dict) -> None:
    """Предохранитель: без закрытой линии фильтр нечем проверить."""
    queues = _financing(phased)["actual_bridge_queues"]
    assert queues["refinanced"], queues
    assert queues["on_bridge"], queues


def test_only_open_lines_make_up_the_peak(phased: dict) -> None:
    fin = _financing(phased)
    month = fin["actual_bridge_month"]
    expected_open = [
        p["name"] for p in phased["phases"]
        if core._bridge_balance_at(p["result"]["finance"]["rows"], month) > 0
    ]
    assert fin["actual_bridge_queues"]["on_bridge"] == expected_open
    rows = fin["actual_bridge_structure"]
    labels = [row["label"] for row in rows]
    assert "Покрыто выручкой и ПФ" not in labels, rows
    assert all(row["share"] <= 1.0 + 1e-6 for row in rows), rows
    assert sum(row["value"] for row in rows) == pytest.approx(fin["actual_bridge"], rel=0.01)


def test_the_closed_line_is_named_not_summed(phased: dict) -> None:
    """Расходы очереди на ПФ в расшифровку не входят — она названа отдельно."""
    fin = _financing(phased)
    month = fin["actual_bridge_month"]
    closed = fin["actual_bridge_queues"]["refinanced"]
    closed_paid = 0.0
    for p in phased["phases"]:
        if p["name"] not in closed:
            continue
        monthly = p["result"].get("monthly") or {}
        months = [str(m) for m in monthly.get("months") or []]
        upto = [i for i, m in enumerate(months) if m <= month]
        for cost in monthly.get("costs") or []:
            values = cost.get("values") or []
            closed_paid += sum(float(values[i] or 0) for i in upto if i < len(values))
    assert closed_paid > fin["actual_bridge"] * 0.2, "закрытая линия должна была что-то оплатить"
    assert sum(row["value"] for row in fin["actual_bridge_structure"]) < closed_paid + fin["actual_bridge"] * 0.5
