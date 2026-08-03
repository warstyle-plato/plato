"""Плата за невыбранный лимит живёт только в окне доступности линии.

Решение владельца: после РВЭ эскроу раскрыт, долг гасится, и лимита, за
который платят, больше нет — «после РВЭ платить не за что». Движок прежде
начислял плату, пока жив долг ПФ (на Мытищах это давало +465 млн комиссий
против книги), а книга тянула хвост «после РВЭ при живом долге» до конца
срока продаж. Теперь окно единое: с открытия ПФ до РВЭ.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_engine_stops_the_fee_at_rve():
    """Слабый проект держит долг ПФ до конца горизонта: раньше плата за
    невыбранный лимит тикала вместе с ним, теперь замолкает на РВЭ."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["apartment_price_th"] = 245  # долг не гасится, ending_pf > 0
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    result = core._run_authoritative_model(inputs, tep, [], {})["consolidated"]
    finance = result["finance"]
    assert finance["ending_pf"] > 0, "нужен проект с живым долгом после РВЭ"

    rve = date.fromisoformat(str(result["dates"]["rve"])[:10])
    before, after = 0.0, 0.0
    for row in finance["rows"]:
        month = date.fromisoformat(str(row["month"])[:10])
        fee = float(row.get("limit_fee") or 0)
        if month < rve:
            before += fee
        else:
            after += fee
    assert before > 0, "до РВЭ плата за невыбранный лимит обязана начисляться"
    assert after == pytest.approx(0.0, abs=1e-9), \
        "после РВЭ лимита нет — плата начисляться не должна"


def test_the_book_window_matches_the_decision():
    """Формула строки 43 всех CF: строго с открытия ПФ (B7) до РВЭ (B8),
    без прежнего хвоста «после РВЭ при живом долге до РВЭ+срок продаж»."""
    template = openpyxl.load_workbook(core._V4_TEMPLATE_PATH, data_only=False)
    for sheet in ("CF_1", "CF_2", "CF_3", "CF_4"):
        formula = str(template[sheet]["D43"].value)
        assert "D$3>=$B$7" in formula and "D$3<$B$8" in formula
        assert "EDATE($B$8" not in formula, "хвост после РВЭ должен быть срезан"
        assert "OR(D38>0" not in formula
        # Разовая комиссия резервирования в месяц открытия ПФ остаётся.
        assert "MONTH($B$7)" in formula


def test_the_mini_model_follows_the_same_window():
    assert "Плата за неиспользованный лимит" in open(
        "main_legacy.py", encoding="utf-8").read()
    source = open("main_legacy.py", encoding="utf-8").read()
    start = source.find('credit.formula("limit_fee"')
    block = source[start:start + 600]
    assert "{ref('rve')}" in block.replace('"', "'"), \
        "мини-модель обязана резать плату за лимит на РВЭ"
