"""Блок «Стройка» сводки читает тот же ГПР и те же решения, что Монитор.

«И нельзя ли пока для примера ГПР взять из Монитора? Я вчера 30 сомнительных
закрыл там» (владелец, 21.10.2026). Кнопка Монитора «Согласен — закрыть
перечисленные» пишет точечные факты работ (`/monitor/work-fact`), и сводка
обязана их видеть: один вопрос — один владелец ответа
(`manager._baseline_status`).

Запуск: python3 -m pytest tests/test_report_reads_the_monitor_gpr.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _project

import developaid_management_report as report
import developaid_monitor as monitor


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _corpus(got, name):
    return next(item["fact"] for item in got["objects"] if item["object"] == name)


def test_a_doubt_closed_in_the_monitor_reaches_the_report(monkeypatch):
    import main_legacy as core

    _project()  # ГПР-факт от 16.10: «Фасад» (Корпус 2) — 40 %
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    before = report.physical(PROJECT, "week", "2026-10-18")
    assert _corpus(before, "Корпус 2") == pytest.approx(0.40)

    # Ровно то, что шлёт кнопка «закрыть сомнительные» на странице Монитора.
    core.monitor_store_work_fact(core.MonitorWorkFactRequest(
        project=PROJECT, taken_at="2026-10-17",
        rows=[{"id": "2", "progress": 1.0, "status": "Завершено (подтверждено владельцем)"}]))

    after = report.physical(PROJECT, "week", "2026-10-18")
    assert _corpus(after, "Корпус 2") == pytest.approx(1.0)
    assert after["fact"] > before["fact"]
    assert after["source"]["label"] == (
        "ГПР-факт от 16.10.2026 и решения в Мониторе по 1 работе (последнее — 17.10.2026)")
    # Решение после конца периода в сводку этого периода не попадает.
    assert _corpus(report.physical(PROJECT, "week", "2026-10-16"), "Корпус 2") == \
        pytest.approx(0.40)

    # Монитор на ту же дату считает работу закрытой — тем же правилом.
    import developaid_monitor_page  # noqa: F401 — слои среза, как на странице

    view = monitor.build(PROJECT, cut="2026-10-18", upto="2026-10-18")
    closed = {str(row["id"]): row["baseline_closed"] for row in view["schedule"]["rows"]}
    assert closed["2"] is True and closed["1"] is False
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert "решения в Мониторе по 1 работе" in text
