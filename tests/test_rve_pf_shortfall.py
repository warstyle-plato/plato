"""Остаток ПФ сразу после раскрытия эскроу в РВЭ виден отдельно.

Это не то же самое, что долг на конец проекта: после РВЭ могут пройти продажи,
которые погасят остаток позднее. Результаты всё равно должны предупредить, что
самого раскрытого эскроу в дату РВЭ для полного погашения не хватило.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def later_sales_repay_the_rve_gap():
    """При 400 тыс. ₽/м² в РВЭ остаётся долг, но к концу он погашен."""
    inputs = {**core.DEFAULT_INPUTS, "apartment_price_th": 400}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return inputs, tep


def test_engine_exposes_the_rve_gap_even_when_the_ending_debt_is_zero():
    inputs, tep = later_sales_repay_the_rve_gap()
    result = core._run_authoritative_model(inputs, tep, [], {})["consolidated"]
    finance = result["finance"]

    assert finance["rve_pf_shortfall"] > 0
    assert finance["ending_pf"] == pytest.approx(0.0, abs=1e-6)
    assert finance["rve_pf_shortfall"] == pytest.approx(
        max(finance["rve_pf_before_repayment"] - finance["rve_escrow_release"], 0.0)
    )
    rve_row = next(row for row in finance["rows"] if row["month"] == result["dates"]["rve"])
    assert finance["rve_pf_shortfall"] == pytest.approx(rve_row["pf_balance"])
    assert result["summary"]["rve_pf_shortfall"] == pytest.approx(
        finance["rve_pf_shortfall"])
    assert result["report"]["financing"]["rve_pf_shortfall"] == pytest.approx(
        finance["rve_pf_shortfall"])


def test_phases_sum_each_queues_own_rve_gap():
    inputs, tep = later_sales_repay_the_rve_gap()
    phasing = {"enabled": True, "phase_count": 2, "phase_gap_months": 12, "phases": []}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    expected = sum(
        phase["result"]["finance"]["rve_pf_shortfall"] for phase in bundle["phases"]
    )

    result = bundle["consolidated"]
    assert result["finance"]["rve_pf_shortfall"] == pytest.approx(expected)
    assert result["summary"]["rve_pf_shortfall"] == pytest.approx(expected)
    assert result["report"]["financing"]["rve_pf_shortfall"] == pytest.approx(expected)


def card_text(monkeypatch, shortfall_mln: float) -> str:
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda session: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda chat_id: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kwargs: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *args, **kwargs: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 6500,
        "net_profit_mln": 900,
        "llcr": 1.3,
        "rve_pf_shortfall_mln": shortfall_mln,
    }))
    return sent[0]


def test_result_surfaces_warn_about_the_rve_gap(monkeypatch):
    text = card_text(monkeypatch, 2659.6)
    assert "Эскроу не погашает ПФ полностью в РВЭ" in text
    assert core._telegram_money_mln(2659.6) in text

    assert 'id="pfRveWarning"' in core.PAGE
    assert "Эскроу не погашает ПФ полностью." in core.PAGE
    assert "rve_pf_shortfall_mln:Number(f.rve_pf_shortfall||0)/1e6" in core.PAGE
    assert "Остаток ПФ после раскрытия эскроу в РВЭ" in core.PAGE
    assert "Остаток ПФ после раскрытия в РВЭ" in core.PAGE


def test_no_rve_warning_when_escrow_covers_the_pf(monkeypatch):
    assert "Эскроу не погашает ПФ полностью в РВЭ" not in card_text(monkeypatch, 0.0)

