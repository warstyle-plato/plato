"""«Главное → Финансирование» говорит каждую вещь один раз и без тавтологий.

Владелец (25.10.2026), на «…при нынешнем темпе эскроу очереди «1 очередь» НЕ
покрывает кредит…»: «Сам додумаешься?». Там же 2,39 млрд ₽ стояло дважды
подряд: «по утверждённому бюджету … не хватает на достройку 2,39» и «по
финмодели не хватает 2,39» — при финмодели это одно число.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import developaid_management_report as report  # noqa: E402


def test_one_queue_is_not_named_and_several_are_named_plainly():
    one = [{"queue": "1 очередь"}]
    assert report._escrow_of(one[0], one) == "эскроу"
    two = [{"queue": "1 очередь"}, {"queue": "2 очередь"}]
    assert report._escrow_of(two[1], two) == "эскроу 2-й очереди"
    other = [{"queue": "Башня А"}, {"queue": "Башня Б"}]
    assert report._escrow_of(other[0], other) == "эскроу очереди «Башня А»"


def test_the_finmodel_deficit_is_said_once_with_its_chapters(monkeypatch):
    built = _built(monkeypatch)
    text = {item["topic"]: item["text"] for item in built["findings"]}["Финансирование"]
    assert text.count("2,39 млрд ₽") == 1, text
    assert "не хватает на достройку" not in text
    assert text.startswith("По финмодели не хватает 2,39 млрд ₽ с января 2027 (на стройку "
                           "1,93 млрд ₽, на коммерцию 465,0 млн ₽)")


def _built(monkeypatch):
    from test_management_report_funding import M, PROJECT, _project

    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "need_basis": "model", "bank_limit": 6_810 * M, "paid_actual": 5_263 * M,
        "paid_borrowed": 4_832 * M, "bank_remaining": 1_278 * M, "reserve": 0.0,
        "remaining_scope": {"chapters": "2–3", "limit": 4_640 * M, "paid": 3_362 * M,
                            "borrowed": 3_270 * M},
        "need_by_chapter": {"2": {"label": "стройка", "label_acc": "стройку", "need": 3_052 * M,
                                  "remaining": 1_123 * M, "gap": 1_928 * M},
                            "3": {"label": "коммерция", "label_acc": "коммерцию", "need": 621 * M,
                                  "remaining": 155.4 * M, "gap": 465 * M}},
        "additional_financing": 2_393 * M, "additional_financing_from": "2027-01-01",
        "approved": 9_599 * M, "approved_remaining": 3_672 * M,
        "deficit_ladder": {"total": 2_393 * M}}}})
    return report.build(PROJECT, "week", "2026-10-18")
