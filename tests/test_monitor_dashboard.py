import datetime
from pathlib import Path

import pytest

import developaid_monitor_dashboard as dashboard


def test_article_surplus_does_not_cross_fund_another_article():
    articles = {
        "2.2.1": {"rss_limit": 100.0, "paid_at_baseline": 0.0, "monthly_need": {"2026-08-01": 0.0}},
        "2.2.2": {"rss_limit": 0.0, "paid_at_baseline": 0.0, "monthly_need": {"2026-08-01": 50.0}},
    }
    result = dashboard._article_waterfall(
        articles, reserve=100.0, cut=datetime.date(2026, 8, 1), current_paid={}
    )
    assert result["monthly_reserve_draw"]["2026-08-01"] == pytest.approx(50.0)
    assert result["remaining_article_limits"] == pytest.approx(100.0)


def test_grodnenskaya_reserve_control_benchmark_exhausts_in_november():
    reserve = 306_141_482.2601274
    uses = {
        "2026-08-01": 2_000_000.0,
        "2026-09-01": 66_330_343.0,
        "2026-10-01": 100_680_310.59827147,
        "2026-11-01": 208_530_177.3909351,
        "2026-12-01": 290_632_872.24154127,
    }
    articles = {
        f"x{i}": {"rss_limit": 0.0, "paid_at_baseline": 0.0, "monthly_need": {month: amount}}
        for i, (month, amount) in enumerate(uses.items())
    }
    result = dashboard._article_waterfall(
        articles, reserve=reserve, cut=datetime.date(2026, 8, 1), current_paid={}
    )
    assert result["reserve_start"] == datetime.date(2026, 8, 1)
    assert result["monthly_reserve_balance"]["2026-08-01"] == pytest.approx(304_141_482.2601274)
    assert result["monthly_reserve_balance"]["2026-09-01"] == pytest.approx(237_811_139.2601274)
    assert result["monthly_reserve_balance"]["2026-10-01"] == pytest.approx(137_130_828.66185594)
    assert result["reserve_exhaustion"].month == 11
    assert result["monthly_unfunded"]["2026-11-01"] == pytest.approx(71_399_348.72907916)
    assert result["additional_financing"] == pytest.approx(362_032_220.9706204)


def test_funding_risk_uses_article_waterfall(monkeypatch):
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda project: {
        "known": True,
        "source": "finance.xlsx",
        "approved": 1000.0,
        "completion_need_at_baseline": 200.0,
        "paid_at_baseline": 0.0,
        "reserve": 100.0,
        "reserve_parts": {"2.8": 50.0, "2.9": 50.0},
        "tail_after_apr": 0.0,
        "articles": {
            "2.2.1": {"rss_limit": 0.0, "paid_at_baseline": 0.0,
                       "monthly_need": {"2026-08-01": 50.0, "2026-09-01": 70.0}},
        },
    })
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda rss: {"by_code": {}, "rows": []})
    monkeypatch.setattr(dashboard, "_rss_ch23", lambda estimate: {"limit": 0.0, "paid_bank_sheet": 0.0, "contracted": 0.0})
    monkeypatch.setattr(dashboard, "_payment_total_ch23", lambda rss, estimate: 0.0)
    monkeypatch.setattr(dashboard, "_payment_by_code", lambda rss: {})
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}

    result = dashboard._funding_risk(
        "demo", Path("rss.xlsx"), datetime.date(2026, 8, 20), view
    )

    assert result["reserve_start"] == "2026-08-01"
    assert result["reserve_exhaustion"].startswith("2026-09-")
    assert result["additional_financing"] == pytest.approx(20.0)
    assert result["reserve"] == pytest.approx(100.0)
    assert "постатейный waterfall" in result["method"]


def test_page_has_funding_and_correct_cost_evidence_language():
    from developaid_monitor_page import MONITOR_PAGE
    assert "Исчерпание резерва" in MONITOR_PAGE
    assert "Непокрытая потребность" in MONITOR_PAGE
    assert "Cost control" in MONITOR_PAGE
    assert "КС / EAC proxy" in MONITOR_PAGE
    assert "Утверждённый РНВ" in MONITOR_PAGE
    assert "Current Forecast РНВ" in MONITOR_PAGE
