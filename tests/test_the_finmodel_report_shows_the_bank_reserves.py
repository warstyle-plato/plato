"""При финмодели резервы банка 2.8/2.9 видны, но второй раз не прибавляются.

Владелец (24.10.2026), на строке «Резерв 0 ₽» блока «Финансирование»: «Резерв
разве 0». Ноль — пустая строка резерва самой финмодели (2.2.11); резервы банка
лежат в смете РСС внутри лимита главы 2 и уже вошли в остаток лимита глав 2–3.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_the_monitor_takes_the_finmodel_as_its_finance_book import (  # noqa: E402
    ESTIMATE, PAID, SECTIONS, _finmodel_funding)

RESERVES = {"2.8": {"estimate": 30.0, "parent": "2", "article": "Резерв на непредвиденные расходы"},
            "2.9": {"estimate": 20.0, "parent": "2", "article": "Резерв на инфляционное удорожание"}}


def test_the_monitor_reads_the_reserves_from_the_estimate(monkeypatch):
    got = _finmodel_funding(monkeypatch, SECTIONS, {**ESTIMATE, **RESERVES},
                            {**PAID, "2.8": (5.0, 5.0), "2.9": (0.0, 0.0)})
    assert got["reserve_inside"] == {
        "total": pytest.approx(45.0), "parts": {"2.8": 25.0, "2.9": 20.0},
        "names": {"2.8": "Резерв на непредвиденные расходы",
                  "2.9": "Резерв на инфляционное удорожание"},
        "chapters": "2"}
    # Резерв — часть остатка, а не прибавка к нему: потребность та же, что без него.
    assert got["reserve"] == 0.0
    assert got["bank_remaining"] == pytest.approx(60.0)
    assert got["additional_financing"] == pytest.approx(370.0)
    assert got["deficit_ladder"]["total"] == pytest.approx(370.0)
    summary = " ".join(__import__("developaid_monitor_dashboard")._summary(
        {"schedule": {}}, {**got, "known": True}, {}))
    assert "в нём уже" in summary and "резервов 2.8/2.9" in summary


def test_the_report_names_the_reserves_instead_of_zero(monkeypatch):
    import developaid_management_report as report
    from test_management_report_funding import M, PROJECT, _project

    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "need_basis": "model", "bank_limit": 6_810 * M, "paid_actual": 5_263 * M,
        "paid_borrowed": 4_832 * M, "bank_remaining": 1_278 * M, "reserve": 0.0,
        "reserve_parts": {"2.2.11": 0.0}, "reserve_names": {"2.2.11": "Резерв"},
        "reserve_inside": {"total": 137.8 * M, "parts": {"2.8": 68.8 * M, "2.9": 69.0 * M},
                           "names": {"2.8": "Резерв на непредвиденные расходы",
                                     "2.9": "Резерв на инфляционное удорожание"},
                           "chapters": "2"},
        "remaining_scope": {"chapters": "2–3", "limit": 4_640 * M, "paid": 3_362 * M,
                            "borrowed": 3_270 * M},
        "need_by_chapter": {"2": {"label": "стройка", "label_acc": "стройку", "need": 3_052 * M,
                                  "remaining": 1_123 * M, "gap": 1_928 * M},
                            "3": {"label": "коммерция", "label_acc": "коммерцию", "need": 621 * M,
                                  "remaining": 155 * M, "gap": 465 * M}},
        "additional_financing": 2_393 * M, "additional_financing_from": "2026-11-01",
        "approved": 9_599 * M, "approved_remaining": 3_672 * M,
        "deficit_ladder": {"total": 2_393 * M}}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    page = report.render_html(built)
    assert "<td>Резерв</td><td>0 ₽</td>" not in page
    assert "Резервы банка 2.8/2.9 (уже входят в остаток лимита главы 2)" in page
    assert "137,8 млн ₽" in page
    text = report.render_text(built)
    assert "резерв 0 ₽" not in text
    assert ("резервы: Резерв на непредвиденные расходы 68,8 млн ₽ и Резерв на инфляционное "
            "удорожание 69,0 млн ₽ — уже входят в остаток лимита главы 2") in text
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert "уже входят в остаток лимита главы 2" in tiles["Лимит банка"]["note"]
    # Потребность от резерва не меняется: резерв уже внутри остатка 1,28.
    assert tiles["Потребность в допфинансировании банка"]["value"] == "2,39 млрд ₽"
