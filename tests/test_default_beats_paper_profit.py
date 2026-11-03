"""Непогашенный долг — дефолт, и он старше бумажной прибыли.

Проект с положительной чистой прибылью и непогашенным долгом на конец
показывался «прибыльным с оговоркой», а книга соседа и вовсе закрывала дыру
«вкладом акционера» — благотворительность выглядела инвестицией (владелец,
27.08.2026: «для инвестора он дефолтный, а не прибыльный»). Вердикт обязан
называть дефолт раньше прибыли, а строка прибыли — говорить, что она бумажная.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_unpaid_debt_beats_paper_profit():
    verdict = core._purchase_feasibility(6000, 3630, 1.0, 10990, 7130)
    assert verdict["status"] == "default"
    assert "Дефолтный" in verdict["title"]
    assert "бумажная" in verdict["text"]
    assert "7 130" in verdict["text"].replace(" ", " ")


def test_unpaid_debt_beats_even_a_healthy_llcr():
    # LLCR выше целевого не оправдывает непогашенный долг: дефолт старше.
    verdict = core._purchase_feasibility(6000, 3630, 1.35, 10990, 500)
    assert verdict["status"] == "default"


def test_repaid_debt_keeps_the_old_verdicts():
    assert core._purchase_feasibility(6000, 3630, 1.35, 10990, 0)["status"] == "positive"
    assert core._purchase_feasibility(6000, -100, 1.35, 10990, 0)["status"] == "negative"
    assert core._purchase_feasibility(6000, 3630, 1.05, 10990, 0)["status"] == "review"
    # Копеечный остаток — округление, а не дефолт.
    assert core._purchase_feasibility(6000, 3630, 1.35, 10990, 0.2)["status"] == "positive"


def test_the_pdf_marks_paper_profit_next_to_the_number():
    source = inspect.getsource(core._build_developaid_pdf)
    assert "бумажная: долг не погашен" in source
    # Пометка привязана к строке прибыли, а не живёт отдельным абзацем.
    assert "_pdf_money(summary.get('net_profit'))+_default_note" in source


def test_both_verdict_surfaces_pass_the_ending_debt():
    pdf = inspect.getsource(core._build_developaid_pdf)
    assert 'financing.get("ending_pf")' in pdf
    telegram = inspect.getsource(core.telegram_result)
    assert 'summary.get("ending_pf_mln")' in telegram
