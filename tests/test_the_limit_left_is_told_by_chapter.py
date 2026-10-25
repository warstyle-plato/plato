"""Остаток лимита банка — по главам.

Владелец (24.10.2026), на плитке «Остаток лимита банка 1,28 млрд ₽ — главы
2–3: лимит 4,64 млрд ₽ без оплаченного 3,36 млрд ₽»: «остаток лимита лучше
расписывать по главам». Числа по главам — те же, что в разбивке потребности
(лимит главы минус оплаченное по ней), второй раз не считаются.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def _built(monkeypatch):
    import developaid_management_report as report
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
    return report, report.build(PROJECT, "week", "2026-10-18")


def test_the_remaining_limit_is_split_by_chapter(monkeypatch):
    report, built = _built(monkeypatch)
    tile = {item["label"]: item for item in report.tiles(built)}["Остаток лимита банка"]
    assert tile["value"] == "1,28 млрд ₽"
    assert tile["note"].startswith("по 2 главе 1,12 млрд ₽, по 3 главе 155,4 млн ₽ — главы 2–3: "
                                   "лимит 4,64 млрд ₽ без оплаченного 3,36 млрд ₽; по финмодели "
                                   "не хватает 2,39 млрд ₽")
    text = report.render_text(built)
    assert "остаток лимитов 1,28 млрд ₽ (по 2 главе 1,12 млрд ₽, по 3 главе 155,4 млн ₽) — " in text
    assert "по 2 главе 1,12 млрд ₽, по 3 главе 155,4 млн ₽" in report.render_html(built)
