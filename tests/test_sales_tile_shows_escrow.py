"""Плашка продаж: сумма договоров и сколько по ним уже на эскроу.

Владелец, 27.10.2026: «У нас на плашке сводки продажи по сумме договора или по
сумме на эскроу? Обе цифры важны». Плашки «Продажи квартала к плану …» — по
сумме договоров (как планы финмодели и банка); рядом — «На эскроу по продажам
квартала»: сколько по тем же договорам поступило на эскроу и сколько ещё нет.

Запуск: python3 -m pytest tests/test_sales_tile_shows_escrow.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from test_management_report_analytics import _full  # noqa: E402
from test_management_report_model import M, _contract, _sales  # noqa: E402


def _quarter():
    paid = _contract("2026-10-05", "Квартира", 60.0, 100 * M)
    paid["escrow_paid"] = 100 * M
    installment = _contract("2026-10-09", "Квартира", 60.0, 80 * M)
    installment["escrow_paid"] = 20 * M
    earlier = _contract("2026-08-01", "Квартира", 60.0, 50 * M)
    earlier["escrow_paid"] = 50 * M
    _sales([paid, installment, earlier])
    return report.sales("ЖК Гродненская", "week", "2026-10-18")["quarter"]


def test_the_quarter_carries_both_figures():
    fact = _quarter()["fact"]
    # Только договоры квартала: августовский в квартал не входит.
    assert fact["amount"] == 180 * M and fact["escrow"] == 120 * M


def test_the_tile_says_both_figures():
    quarter = _quarter()
    built = _full()
    built["sales"]["quarter"] = quarter
    tiles = {item["label"]: item for item in report.tiles(built)}
    tile = tiles["На эскроу по продажам квартала"]
    assert tile["value"] == "120,0 млн ₽"
    assert tile["note"] == "из 180,0 млн ₽ по договорам квартала, ещё 60,0 млн ₽ покупатели внесут позже"
    # Плашки к планам — по сумме договоров, как сами планы.
    assert tiles["Продажи квартала к плану банка"]["note"].startswith("продано на 180,0 млн ₽ из")
