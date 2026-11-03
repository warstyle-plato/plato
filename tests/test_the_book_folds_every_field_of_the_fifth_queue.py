"""Пятая очередь в книге v4 слита в четвёртую по ВСЕМ складываемым полям.

Книга держит четыре листа очередей, движок — до пяти. `_v4_fold_tep_rows`
складывал хвост только по метрам и штукам, а гостевые, переданные,
продаваемые и паркинг объектов брал у первой из склеенных очередей: на пяти
очередях гостевые пятой пропадали, и мест к продаже в книге было больше, чем
у движка. Список складываемых полей теперь один — у свода движка
(`PHASE_ADDITIVE_TEP_FIELDS`).

Запуск: python3 -m pytest tests/test_the_book_folds_every_field_of_the_fifth_queue.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402

PHASING = {
    "enabled": True, "phase_count": 5,
    "phases": [{"start_offset_months": 12 * i, "construction_months": 24} for i in range(5)],
    "products": {k: [28, 22, 19, 16, 15] for k in ("apartments", "ground_commercial",
                                                   "underground_parking", "storage")},
    "shared_allocation": {}, "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
}


@pytest.fixture(scope="module")
def engine_rows() -> tuple[list[dict], dict]:
    bundle = core._run_authoritative_model(dict(core.DEFAULT_INPUTS),
                                           copy.deepcopy(core.TEP_DEFAULT), [],
                                           copy.deepcopy(PHASING))
    # Та же выжимка, что везёт книге `tep_by_phase` (xlsx_book_v4_sheets).
    by_phase = [{str(r["key"]): {k: v for k, v in r.items() if k != "key"}
                 for r in item["result"]["tep"]["rows"]} for item in bundle["phases"]]
    consolidated = {r["key"]: r for r in bundle["consolidated"]["tep"]["rows"]}
    return by_phase, consolidated


def test_the_engine_has_five_queues_with_guests_in_each(engine_rows) -> None:
    by_phase, _ = engine_rows
    assert len(by_phase) == 5
    assert all(row["underground_parking"]["guest_units"] > 0 for row in by_phase)


def test_the_fourth_book_queue_is_the_sum_of_the_fourth_and_fifth(engine_rows) -> None:
    by_phase, _ = engine_rows
    folded = core._v4_fold_tep_rows(copy.deepcopy(by_phase), 4)
    assert len(folded) == 4
    for field in core.PHASE_ADDITIVE_TEP_FIELDS:
        want = (float(by_phase[3]["underground_parking"].get(field) or 0)
                + float(by_phase[4]["underground_parking"].get(field) or 0))
        assert folded[3]["underground_parking"].get(field, 0) == pytest.approx(want), field


def test_the_book_queues_add_up_to_the_engine_project(engine_rows) -> None:
    by_phase, consolidated = engine_rows
    folded = core._v4_fold_tep_rows(copy.deepcopy(by_phase), 4)
    for field in ("units", "guest_units", "saleable_units", "transfer_units"):
        book = sum(float(q["underground_parking"].get(field) or 0) for q in folded)
        assert book == pytest.approx(consolidated["underground_parking"][field]), field
