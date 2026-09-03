"""Структурный дефицит и «ДЕФИЦИТ» в шапке связаны лестницей, а не суммой.

«Я не понимаю, что значит в данном случае структурный дефицит… к нему же ещё
надо добавлять дефицит, который будет с учётом потребности бюджета реального
на достройку» (владелец, 03.09.2026). Складывать нельзя: потребность модели
уже включает программу РСС. Связь: структурный (без перебросок) → минус
перераспределение внутри глав → минус запертый свободный лимит → дефицит по
РСС при полном перераспределении → плюс превышение модели над РСС → итого,
и это то же число, что в шапке.

Запуск: python3 -m pytest tests/test_the_deficit_ladder_leads_to_the_header_number.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_monitor_dashboard as dashboard  # noqa: E402
from developaid_monitor_page import MONITOR_PAGE  # noqa: E402

M = 1e6
WATERFALL = {
    "articles": [
        {"code": "2.4", "need_total": 900 * M, "unfunded_take": 320 * M},
        {"code": "2.5", "need_total": 300 * M, "unfunded_take": 80 * M},
        {"code": "2.1", "need_total": 0.0, "unfunded_take": 0.0},
        {"code": "3.2", "need_total": 200 * M, "unfunded_take": 0.0},
    ],
    "opening_bank_remaining": 1_000 * M,
    "additional_financing": 400 * M,
}
UNSPENT = {"by_chapter": [{"chapter": "2", "shortage": 400 * M, "sources": 150 * M},
                          {"chapter": "3", "shortage": 0.0, "sources": 50 * M}]}


def test_every_step_leads_to_the_next_and_ends_at_the_header() -> None:
    approved_remaining = 3_630 * M
    lad = dashboard._deficit_ladder(WATERFALL, 300 * M, approved_remaining, UNSPENT)
    assert lad["structural"] == 400 * M
    # Перераспределение — только внутри главы и не больше нехватки главы:
    # 150 из главы 2; 50 главы 3 нехватку главы 2 не закрывают.
    assert lad["redistributable"] == 150 * M
    # Программа РСС после среза 1 400 против лимитов с резервом 1 300 → 100.
    assert lad["rss_need_after_cut"] == 1_400 * M and lad["fuel"] == 1_300 * M
    assert lad["rss_gap"] == pytest.approx(100 * M)
    # Остаток лестницы после перебросок 250 против пула 100: 150 заперто.
    assert lad["locked_limits"] == pytest.approx(150 * M)
    assert lad["structural"] - lad["redistributable"] - lad["locked_limits"] == pytest.approx(lad["rss_gap"])
    # Сверх РСС по модели: 3 630 − 1 400 = 2 230; итого 2 330 — как в шапке.
    assert lad["model_excess"] == pytest.approx(2_230 * M)
    assert lad["total"] == pytest.approx(lad["rss_gap"] + lad["model_excess"])
    assert lad["total"] == pytest.approx(max(0.0, approved_remaining - lad["fuel"]))


def test_without_a_book_the_ladder_stops_at_the_rss_gap() -> None:
    lad = dashboard._deficit_ladder(WATERFALL, 300 * M, None, UNSPENT)
    assert lad["model_excess"] is None and lad["total"] is None
    assert lad["rss_gap"] == pytest.approx(100 * M)


def test_a_model_below_the_rss_programme_does_not_go_negative() -> None:
    lad = dashboard._deficit_ladder(WATERFALL, 300 * M, 1_000 * M, UNSPENT)
    assert lad["model_excess"] == pytest.approx(-400 * M)
    assert lad["total"] == 0.0


def test_the_page_shows_the_ladder_next_to_the_structural_block() -> None:
    for label in ("От структурного дефицита к дефициту на достройку",
                  "Закрывается перераспределением внутри глав",
                  "Свободный лимит, который просить нельзя",
                  "= Дефицит по РСС при полном перераспределении",
                  "Сверх РСС по утверждённой модели",
                  "= Итого не хватает на достройку"):
        assert label in MONITOR_PAGE, label
    assert "f.deficit_ladder" in MONITOR_PAGE
