import datetime
from pathlib import Path

import pytest

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard


def test_dated_construction_acts_exclude_nonconstruction_and_undated_rows(monkeypatch):
    monkeypatch.setattr(dashboard.actuals, "read_completed_works", lambda _: {"rows": [
        {"code": "2.2.1", "amount": 100.0, "construction": True, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 500.0, "construction": False, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 300.0, "construction": True, "date": None},
        {"code": "3.1", "amount": 200.0, "construction": True, "date": datetime.date(2026, 8, 10)},
    ]})
    assert dashboard._physical_smr(Path("rss.xlsx"), {}, datetime.date(2026, 8, 20)) == 100.0


def test_article_surplus_does_not_cross_fund_another_article():
    articles = {
        "2.2.2.1": {
            "rss_limit": 100.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-08-01": 0.0},
        },
        "2.2.3.3": {
            "rss_limit": 0.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-08-01": 50.0},
        },
    }
    result = dashboard._article_waterfall(
        articles, reserve=60.0, cut=datetime.date(2026, 8, 21)
    )
    assert result["opening_bank_remaining"] == pytest.approx(100.0)
    assert result["monthly_reserve_draw"]["2026-08-01"] == pytest.approx(50.0)
    assert result["reserve_balance"] == pytest.approx(10.0)
    assert result["additional_financing"] == pytest.approx(0.0)


def test_grodnenskaya_reserve_control_benchmark_exhausts_in_november():
    # Control figures from «справка резервы_обновлено_по_остаткам_20.08.2026».
    # We intentionally model them as article shortfalls: the waterfall must not
    # defer reserve use because another article still has a free bank balance.
    articles = {
        "2.2.3.3": {
            "rss_limit": 0.0,
            "paid_at_baseline": 0.0,
            "monthly_need": {
                "2026-08-01": 2_000_000.0,
                "2026-09-01": 66_330_343.0,
                "2026-10-01": 100_680_310.59827147,
                "2026-11-01": 208_530_177.3909351,
                "2026-12-01": 290_632_872.24154127,
            },
        }
    }
    result = dashboard._article_waterfall(
        articles,
        reserve=306_141_482.2601274,
        cut=datetime.date(2026, 8, 21),
    )

    assert result["reserve_start"] == datetime.date(2026, 8, 1)
    assert result["monthly_reserve_balance"]["2026-08-01"] == pytest.approx(304_141_482.2601274)
    assert result["monthly_reserve_balance"]["2026-09-01"] == pytest.approx(237_811_139.2601274)
    assert result["monthly_reserve_balance"]["2026-10-01"] == pytest.approx(137_130_828.66185594)
    assert result["reserve_exhaustion"].year == 2026
    assert result["reserve_exhaustion"].month == 11
    assert result["monthly_unfunded"]["2026-11-01"] == pytest.approx(71_399_348.72907916)
    assert result["additional_financing"] == pytest.approx(362_032_220.9706204)


def test_funding_risk_uses_article_waterfall(monkeypatch):
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda _: {
        "known": True,
        "source": "finance.xlsx",
        "approved": 1000.0,
        "completion_need_at_baseline": 900.0,
        "paid_at_baseline": 100.0,
        "reserve": 100.0,
        "reserve_parts": {"2.8": 40.0, "2.9": 60.0},
        "monthly_need": {},
        "tail_after_apr": 600.0,
        "articles": {
            "2.2.3.3": {
                "rss_limit": 50.0,
                "paid_at_baseline": 0.0,
                "monthly_need": {
                    "2026-08-01": 70.0,
                    "2026-09-01": 100.0,
                },
            }
        },
    })
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: {
        "rows": [], "by_code": {"2": {"estimate": 700.0}, "3": {"estimate": 100.0}}
    })
    monkeypatch.setattr(dashboard, "_payment_total_ch23", lambda *_: 200.0)
    monkeypatch.setattr(dashboard, "_payment_by_code", lambda _: {})
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
    assert "Исчерпание лимита банка" in MONITOR_PAGE
    assert "Доп. финансирование до РВЭ" in MONITOR_PAGE
    assert "Сырой PM" in MONITOR_PAGE
    assert "Актировано СМР / утв. модель" in MONITOR_PAGE
    assert "это не физический % WBS" in MONITOR_PAGE
