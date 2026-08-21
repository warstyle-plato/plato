import datetime
from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard


def test_physical_smr_counts_only_dated_construction_acts(monkeypatch):
    monkeypatch.setattr(dashboard.actuals, "read_completed_works", lambda _: {"rows": [
        {"code": "2.2.1", "amount": 100.0, "construction": True, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 500.0, "construction": False, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 300.0, "construction": True, "date": None},
        {"code": "3.1", "amount": 200.0, "construction": True, "date": datetime.date(2026, 8, 10)},
    ]})
    assert dashboard._physical_smr(Path("rss.xlsx"), {}, datetime.date(2026, 8, 20)) == 100.0


def test_funding_risk_runs_to_rnv_not_to_april(monkeypatch):
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda _: {
        "known": True, "source": "finance.xlsx", "approved": 1000.0,
        "completion_need_at_baseline": 900.0, "paid_at_baseline": 100.0,
        "reserve": 100.0, "reserve_parts": {"2.8": 40.0, "2.9": 60.0},
        "monthly_need": {"2026-08-01": 100.0, "2026-09-01": 100.0, "2027-03-01": 100.0},
        "tail_after_apr": 600.0,
    })
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: {
        "rows": [], "by_code": {"2": {"estimate": 700.0}, "3": {"estimate": 100.0}}
    })
    monkeypatch.setattr(dashboard, "_payment_total_ch23", lambda *_: 200.0)
    view = {"schedule": {"forecast_end": "2027-09-30"}}
    result = dashboard._funding_risk("demo", Path("rss.xlsx"), datetime.date(2026, 8, 20), view)
    assert result["forecast_to"] == "2027-09-30"
    assert "2027-09-01" in result["monthly_need"]
    assert result["additional_financing"] > 0
    assert result["reserve"] == 100.0


def test_page_has_funding_and_pm_risk_language():
    from developaid_monitor_page import MONITOR_PAGE
    assert "Исчерпание лимита банка" in MONITOR_PAGE
    assert "Доп. финансирование до РВЭ" in MONITOR_PAGE
    assert "Сырой PM" in MONITOR_PAGE
    assert "клик по строке также открывает проблему" in MONITOR_PAGE
