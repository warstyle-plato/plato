"""Разбор, связки и итог читают одно сравнение темпа, в том числе при нулях."""

from __future__ import annotations

import pytest

from market_search.market_reference import MoscowMarket
from market_search.metrics import build_blocks, pace_comparison
from market_search.narrative import analysis, findings
from market_search.verdict import build_notes


def _case(paces, *, own=4.4, unpriced=()):
    subject = {
        "name": "Наш проект", "segment": "Бизнес", "price_per_sqm": 695_000,
        "units_per_month": own, "units_per_month_3m": 3.7, "remaining_units": 154,
    }
    peers = [
        {"name": f"Сосед {index}", "segment": "Бизнес",
         "price_per_sqm": None if index in unpriced else 500_000,
         "units_per_month": pace}
        for index, pace in enumerate(paces)
    ]
    blocks = build_blocks(subject, peers, MoscowMarket({}), ["price", "pace", "stock"])
    comparison = {"found": len(peers), "used": len(peers)}
    notes = build_notes(blocks)
    essay = {part["code"]: part for part in analysis(
        subject, peers, comparison, segment="Бизнес", blocks=blocks)}
    linked = {part["code"]: part for part in findings(
        subject, peers, comparison, segment="Бизнес", blocks=blocks)}
    return subject, peers, blocks, notes, essay, linked


@pytest.mark.parametrize(
    "paces,own,unpriced,median,ratio,tone",
    [
        ([0, 0, 0, 5.7, 20.8, 21, 30], 4.4, (), 5.7, 1.3, "good"),
        ([7, 32, 67, 0, 13, 39], 7, (), 22.5, 3.2, "bad"),
        ([0, 10, 20, 30, 40], 4.4, (), 20.0, 4.5, "bad"),
        ([0, 0, 0, 5.7, 20.8, 21, 30], 4.4, (0, 1, 2), 5.7, 1.3, "good"),
        ([6.54, 6.54, 6.54, 6.54], 4.5, (), 6.5, 1.4, "good"),
        ([None, 0, 4, 8, 12], 4.4, (), 6.0, 1.4, "good"),
    ],
)
def test_all_report_conclusions_use_the_same_pace(paces, own, unpriced, median, ratio, tone):
    subject, peers, blocks, notes, essay, linked = _case(paces, own=own, unpriced=unpriced)
    pace = next(block for block in blocks if block["code"] == "pace")
    assert pace["peers"]["median"] == median
    assert pace["peers"]["peer_median_over_subject"] == ratio
    assert pace["peers"]["count"] == sum(value is not None for value in paces)
    assert notes["blocks"]["pace"]["ratio"] == ratio
    assert notes["overall"]["tone"] == tone
    displayed_median = f"{median:.1f}".replace(".", ",")
    assert f"медианы {displayed_median}" in " ".join(essay["pace"]["paragraphs"])
    assert f"медианы {displayed_median}" in linked["pace"]["text"]
    if tone == "bad":
        assert essay["pace"]["headline"] == "Темп продаж премию не подтверждает"
        assert linked["pace"]["tone"] == "bad"
        assert f"{ratio:.1f}".replace(".", ",") in essay["pace"]["paragraphs"][0]
    else:
        assert essay["pace"]["headline"] == "Темп продаж премию выдерживает"
        assert linked["pace"]["tone"] != "bad"
    # Самостоятельные читатели без готовых блоков используют ту же функцию.
    standalone = {part["code"]: part for part in analysis(subject, peers, {}, segment="Бизнес")}
    assert standalone["pace"] == essay["pace"]


def test_ready_pace_block_is_the_authority_for_text():
    subject, peers, blocks, _, _, _ = _case([0, 0, 0, 5.7, 20.8, 21, 30])
    # Участники сравнения не должны повторно отбираться текстовым модулем.
    raw_positive_only = [peer for peer in peers if peer["units_per_month"]]
    essay = {part["code"]: part for part in analysis(
        subject, raw_positive_only, {}, segment="Бизнес", blocks=blocks)}
    linked = {part["code"]: part for part in findings(
        subject, raw_positive_only, {}, segment="Бизнес", blocks=blocks)}
    assert "медианы 5,7" in essay["pace"]["paragraphs"][0]
    assert essay["pace"]["headline"] == "Темп продаж премию выдерживает"
    assert linked["pace"]["tone"] != "bad"


@pytest.mark.parametrize("own,paces", [(None, [0, 5, 10, 20]), (0, [0, 5, 10, 20]), (4.4, [None] * 4)])
def test_missing_or_zero_own_pace_does_not_produce_a_positive_verdict(own, paces):
    _, _, _, notes, essay, linked = _case(paces, own=own)
    assert notes["overall"]["headline"] == "Вывод не сложился"
    assert "pace" not in essay and "pace" not in linked


def test_known_zero_is_counted_and_missing_pace_is_not():
    got = pace_comparison({"units_per_month": 4.4}, [
        {"units_per_month": 0}, {"units_per_month": None},
        {"units_per_month": 10}, {},
    ])
    assert got["count"] == 2 and got["median"] == 5.0
