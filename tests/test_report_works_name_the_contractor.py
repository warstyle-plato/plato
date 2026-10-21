"""Работы в сводке приписаны тому подрядчику, который в строке назван.

«МОЭК в отчёте по работам за неделю — это не Клодо! Это отдельный
подрядчик» (владелец, 21.10.2026). Строку «Моэк ( теплосети)- монтаж
ограждения» разбор отдаёт названному подрядчику, только если имя известно
проекту. Сводка проверяла имя лишь по численности того же дня, а в тот день
МОЭК людей не выводил — и строка уходила заголовку выше, Клодо. Карточка
Монитора при этом смотрела ещё и в реестры РСС и ГУ: два ответа на один
вопрос. Теперь список известных подрядчиков один (`daily.known_parties`):
реестры РСС и ГУ плюс численность всех ежедневных отчётов проекта.

Запуск: python3 -m pytest tests/test_report_works_name_the_contractor.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_daily as daily

PROJECT = "Кутузов Сити"

EARLIER = """Добрый день.
1. НУР: ИТР- 11чел.; Рабочие - 54чел.;
2. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
3. МОЭК (теплосети): ИТР - 1 чел., Рабочие - 4 чел.
По работам:
1. МОЭК (теплосети): прокладка трубы
"""

WEEK = """Добрый день.
1. НУР: ИТР- 11чел.; Рабочие - 54чел.;
2. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
По работам:
1. Клодо ( кладка): Корпус 2 кладка 3 эт
Моэк ( теплосети)- монтаж ограждения
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _groups(end: str) -> dict[str, list[str]]:
    got = report.crew(PROJECT, "week", end)
    return {group["contractor"]: [entry["line"] for entry in group["lines"]]
            for group in got["works"]}


def test_a_contractor_known_from_another_day_gets_its_line():
    daily.store_daily_report(PROJECT, EARLIER, "2026-10-08")
    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    groups = _groups("2026-10-18")
    moek = next(name for name in groups if "МОЭК" in name.upper())
    assert groups[moek] == ["монтаж ограждения"]
    klodo = next(name for name in groups if "Клодо" in name)
    assert groups[klodo] == ["Корпус 2 кладка 3 эт"]


def test_a_contractor_known_from_the_registers_gets_its_line(monkeypatch):
    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    monkeypatch.setattr(monitor, "latest_retention", lambda _p: {
        "rows": [{"counterparty": "ПАО «МОЭК»", "customer": ""}]})
    groups = _groups("2026-10-18")
    assert groups.get("ПАО «МОЭК»") == ["монтаж ограждения"]
    assert all("ограждения" not in line
               for name, lines in groups.items() if "Клодо" in name for line in lines)


def test_the_monitor_and_the_report_share_one_list(monkeypatch):
    import main_legacy as core

    daily.store_daily_report(PROJECT, EARLIER, "2026-10-08")
    assert core._monitor_known_parties(PROJECT) == daily.known_parties(PROJECT)
    assert any("МОЭК" in name for name in daily.known_parties(PROJECT))
    # Отчёт после даты сводки в список этой сводки не попадает.
    assert not any("МОЭК" in name for name in daily.known_parties(PROJECT, "2026-10-07"))
