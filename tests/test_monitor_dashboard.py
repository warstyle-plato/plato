import datetime
from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard


def test_schedule_baseline_never_becomes_finance_file(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    folder = monitor._project_dir("demo") / "baseline"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gpr.xlsx").write_bytes(b"gpr")
    (folder / "finance.xlsx").write_bytes(b"finance")
    assert monitor._baseline_file("demo").name == "gpr.xlsx"


def test_physical_smr_counts_only_dated_construction_acts(monkeypatch):
    estimate = {
        "rows": [
            {"code": "2", "parent": ""},
            {"code": "2.2", "parent": "2"},
            {"code": "2.2.1", "parent": "2.2"},
        ]
    }
    monkeypatch.setattr(
        dashboard.actuals,
        "read_completed_works",
        lambda _: {
            "rows": [
                {"code": "2.2.1", "amount": 100.0, "construction": True, "date": datetime.date(2026, 8, 10)},
                {"code": "2.2.1", "amount": 500.0, "construction": False, "date": datetime.date(2026, 8, 10)},
                {"code": "2.2.1", "amount": 300.0, "construction": True, "date": None},
                {"code": "2.2.1", "amount": 200.0, "construction": True, "date": datetime.date(2026, 9, 10)},
            ]
        },
    )
    assert dashboard._physical_smr(Path("rss.xlsx"), estimate, datetime.date(2026, 8, 20)) == 100.0


def test_dashboard_separates_approved_need_limit_fact_and_pf(monkeypatch):
    estimate = {"rows": [], "by_code": {"2": {"estimate": 4_000.0, "contracted": 3_700.0, "paid": 2_300.0}}}
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: estimate)
    monkeypatch.setattr(dashboard, "_approved_baseline", lambda _: {"known": True, "approved_smr": 5_800.0, "source": "finance.xlsx"})
    monkeypatch.setattr(dashboard, "_physical_smr", lambda *_: 1_500.0)
    monkeypatch.setattr(dashboard, "_unclosed_advance", lambda _: 600.0)
    monkeypatch.setattr(dashboard, "_sales_snapshot", lambda *_: {"known": False})
    view = {"schedule": {"baseline_end": "2027-09-25", "forecast_end": "2027-10-25"}}
    result = dashboard._dashboard("demo", Path("2026-08-20.xlsx"), datetime.date(2026, 8, 20), view)
    assert result["physical"]["completion"] == 1_500.0 / 5_800.0
    assert result["construction"]["limit_gap"] == 1_800.0
    assert result["construction"]["remaining_need"] == 3_500.0
    assert result["advances"]["unclosed"] == 600.0
    assert result["pf"]["available"] is False
    assert "ДДС DevelopAid" in result["pf"]["reason"]


def test_page_has_management_kpis_and_high_level_gantt():
    from developaid_monitor_page import MONITOR_PAGE
    assert "Физическая готовность СМР" in MONITOR_PAGE
    assert "Незакрытые авансы" in MONITOR_PAGE
    assert "Утвержденная потребность СМР" in MONITOR_PAGE
    assert "Остаток потребности" in MONITOR_PAGE
    assert "Проектное финансирование" in MONITOR_PAGE
    assert "По умолчанию только крупные блоки" in MONITOR_PAGE
