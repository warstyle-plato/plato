"""Work and RNV forecast from the GPR and cumulatives (PM off, no money pace). Synthetic data."""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_monitor as monitor
import developaid_schedule_gpr_forecast as gpr
from test_monitor_management_gantt import _gpr_book

CUT = dt.date(2026, 11, 6)


def d(text):
    return dt.date.fromisoformat(text)


def row(tid="1", start="2026-09-01", finish="2026-12-31", code="2.2.1.1", name="Каркас"):
    return {"id": tid, "plan_start": start, "plan_finish": finish, "code": code, "name": name}


def test_pace_of_gpr_percent_over_the_last_ninety_days():
    points = [(d("2026-10-01"), 0.2, "weekly_gpr"), (d("2026-10-21"), 0.4, "weekly_gpr")]
    got = gpr.work(row(), points, CUT)
    # 0.2 per 20 days -> 0.6 left takes 60 days after the last record.
    assert got["method"] == "gpr_pace" and got["forecast_finish"] == "2026-12-20"
    assert got["window"] == ["2026-10-01", "2026-10-21"]


def test_no_growth_after_the_deadline_is_a_standing_work_without_a_date():
    points = [(d("2026-10-01"), 0.3, "weekly_gpr"), (d("2026-11-01"), 0.3, "weekly_gpr")]
    got = gpr.work(row(finish="2026-10-15"), points, CUT)
    assert got["method"] == "stalled" and got["forecast_finish"] is None and "стоит" in got["reason"]


@pytest.mark.parametrize("start,reason", [("2026-09-01", "роста процента"), ("2026-12-01", "ещё не началась")])
def test_within_plan_without_growth_keeps_the_plan(start, reason):
    points = [(d("2026-10-01"), 0.0, "weekly_gpr"), (d("2026-11-01"), 0.0, "weekly_gpr")]
    got = gpr.work(row(start=start, finish="2027-02-01"), points, CUT)
    assert got["method"] == "plan" and got["forecast_finish"] == "2027-02-01" and reason in got["reason"]


def test_done_work_takes_the_first_record_at_one_hundred_percent():
    points = [(d("2026-09-01"), 0.8, "weekly_gpr"), (d("2026-09-20"), 1.0, "weekly_gpr"),
              (d("2026-10-20"), 1.0, "weekly_gpr")]
    got = gpr.work(row(), points, CUT)
    assert got["method"] == "done" and got["forecast_finish"] == "2026-09-20"


def test_old_records_do_not_make_a_pace_and_stale_overdue_has_no_date():
    points = [(d("2026-07-01"), 0.1, "weekly_gpr"), (d("2026-09-01"), 0.5, "weekly_gpr")]
    got = gpr.work(row(finish="2026-10-01"), points, CUT)
    assert got["forecast_finish"] is None and got["method"] == "stale"


def test_cumulative_quantities_take_precedence_when_the_work_is_bound():
    points = [(d("2026-10-01"), 0.2, "weekly_gpr"), (d("2026-10-21"), 0.4, "weekly_gpr")]
    got = gpr.work(row(), points, CUT, {"forecast_finish": "2027-01-15", "progress": 0.35})
    assert got["method"] == "cumulative_quantities" and got["forecast_finish"] == "2027-01-15"


def test_rnv_is_the_latest_construction_work_and_names_what_is_left_out():
    rows = [row("1", code="2.2.1.1", name="Каркас"), row("2", code="2.2.2.3", name="Кровля"),
            row("3", code="", name="Продажи"), row("4", code="", name="Ходатайство")]
    works = {"1": {"forecast_finish": "2027-03-01", "method": "gpr_pace"},
             "2": {"forecast_finish": "2027-05-10", "method": "plan", "reason": "по плану"},
             "3": {"forecast_finish": "2030-01-01"}, "4": {"forecast_finish": None}}
    got = gpr.rnv(rows, works, "2027-04-30")
    assert got["state"] == "estimate" and got["forecast"] == "2027-05-10" and got["delay_days"] == 10
    assert got["driving_chain"][0]["name"] == "Кровля"
    assert any("2 работ ГПР без статьи" in r for r in got["reasons"])
    assert gpr.ESTIMATE_NOTE in got["reasons"]


def test_rnv_with_a_standing_construction_work_is_partial_not_a_date():
    rows = [row("1", name="Каркас"), row("2", name="Фасад")]
    works = {"1": {"forecast_finish": "2027-03-01"}, "2": {"forecast_finish": None, "method": "stalled"}}
    got = gpr.rnv(rows, works, "2027-04-30")
    assert got["state"] == "partial" and got["forecast"] is None and got["indicative_forecast"] == "2027-03-01"
    assert any("«Фасад»" in r for r in got["reasons"])


def test_monitor_layer_uses_stored_gpr_files_and_never_money_pace(tmp_path, monkeypatch):
    import developaid_monitor_pace as pace
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    start, finish = dt.date(2026, 9, 1), dt.date(2026, 12, 31)
    monitor.store_schedule("Учебный", _gpr_book([
        (1, "Каркас", 0.0, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.0, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), None, "2026-09-01")
    monitor.store_schedule_fact("Учебный", _gpr_book([
        (1, "Каркас", 0.2, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.1, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), "2026-10-01")
    monitor.store_schedule_fact("Учебный", _gpr_book([
        (1, "Каркас", 0.4, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.2, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), "2026-10-21")
    rows = [dict(row("1"), rss_accepted_ratio=0.9, rss_act_cost_rate_3m=0.5),
            dict(row("2", finish="2030-01-01", code="", name="Продажи"))]
    view = {"cut": CUT.isoformat(), "schedule": {"rows": rows, "management": []},
            "dashboard": {"schedule": {"approved_finish": "2026-12-31"}, "summary": []}}
    pace._apply_pace("Учебный", view, CUT)
    first = view["schedule"]["rows"][0]
    # The approved GPR of 01.09 (0%) is inside the 90-day window: 40% per 50 days,
    # 60% left -> 75 days after 21.10.
    assert first["pace_forecast_method"] == "gpr_pace" and first["pace_forecast_finish"] == "2027-01-04"
    qualified = view["dashboard"]["schedule"]["qualified_rnv"]
    assert qualified["state"] == "estimate" and qualified["forecast"] == "2027-01-04"
    assert qualified["basis"] == "gpr" and qualified["delay_days"] == 4
    assert qualified["driving_chain"][0]["name"] == "Каркас"  # «Продажи» has no article
    assert "оценка по ГПР" in view["schedule"]["dependency_timeline_html"]
    assert view["dashboard"]["summary"][0].startswith("Срок.") and "Без цепочки" in view["dashboard"]["summary"][0]


def test_summary_shows_the_estimate_but_does_not_shift_loans():
    import developaid_management_report as report
    qualified = {"state": "estimate", "approved": "2027-04-30", "forecast": "2027-05-10",
                 "delay_days": 10, "basis": "gpr", "reasons": [gpr.ESTIMATE_NOTE], "driving_chain": []}
    dashboard = {"schedule": {"qualified_rnv": qualified}}
    block = report.schedule(dashboard)
    assert block["known"] and block["estimate"] and block["delay_days"] == 10
    assert report._forecast_shift(dashboard, {"date": "2027-04-30"}) is None
    payload = {"project": "Учебный", "kind": "week", "start": "2026-11-01", "end": "2026-11-06", "schedule": block}
    text = " ".join(f["text"] for f in report.findings(payload) if f.get("topic") == "Срок")
    assert "Оценка окончания работ — 10.05.2027" in text
    assert "Оценка работ не подтверждает дату получения разрешения на ввод" in text
    assert "PM" not in text and gpr.ESTIMATE_NOTE not in text
    assert block['qualification'] == qualified  # presentation cannot qualify the estimate as final


def test_monitor_card_shows_the_estimate_date_with_its_caveat():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    qualified = {"state": "estimate", "approved": "2027-04-30", "forecast": "2027-05-10",
                 "delay_days": 10, "basis": "gpr", "reasons": [gpr.ESTIMATE_NOTE], "driving_chain": []}
    with browser_page(390) as (page, responses, errors):
        page.evaluate("(q)=>renderDash({dashboard:{schedule:{qualified_rnv:q}},schedule:{}})", qualified)
        kpis = page.locator('#kpis')
        expect(kpis).to_contain_text('10.05.2027')
        expect(kpis).to_contain_text('оценка по ГПР')
        assert not errors


def test_rnv_driven_by_a_plan_only_work_is_not_called_on_time():
    import developaid_management_report as report
    import developaid_monitor_dashboard as dashboard
    qualified = {"state": "estimate", "approved": "2027-04-30", "forecast": "2027-04-30", "delay_days": 0,
                 "basis": "gpr", "reasons": [gpr.ESTIMATE_NOTE],
                 "driving_chain": [{"id": "2", "name": "Кровля", "method": "plan", "reason": "показан план"}]}
    sentence = dashboard._schedule_summary({"qualified_rnv": qualified})
    assert "оценка по ГПР — 30.04.2027" in sentence and "в срок" not in sentence
    assert "по плану ГПР" in sentence and "накопительн" not in sentence
    block = report.schedule({"schedule": {"qualified_rnv": qualified}})
    payload = {"project": "Учебный", "kind": "week", "start": "2026-11-01", "end": "2026-11-06", "schedule": block}
    text = " ".join(f["text"] for f in report.findings(payload) if f.get("topic") == "Срок")
    words = text.casefold()
    assert "в срок" not in words and "в пределах плана" not in words
    assert "по плану гпр" in words and "темп ещё не подтверждён" in words
    assert "накопительн" not in words and "не подтверждает дату получения разрешения" in words


@pytest.mark.parametrize('width', [390, 1440])
def test_gpr_rnv_driver_is_shown_once_without_restoring_pm_drawing(width):
    import io
    from playwright.sync_api import expect
    from pypdf import PdfReader
    import developaid_management_report as report
    import developaid_schedule_timeline as timeline
    from test_monitor_cumulative_controls import browser_page

    name = 'Монтаж фасада <img src=x onerror="window.forecastXSS=1">'
    works = {'1': {'forecast_finish': '2027-05-10', 'method': 'gpr_pace',
                   'reason': 'Оценка по измеренному росту процента ГПР.'}}
    qualified = gpr.rnv([row(name=name)], works, '2027-04-30')
    # Keep a legacy PM row in the same model: integrating the GPR renderer
    # must not make removed dependency lanes/technical details reappear.
    block = {'state': 'ok', 'rnv': qualified, 'edges': [], 'rows': [
        {'id': 'historic-pm', 'name': 'Устаревшая техническая работа',
         'plan_start': '2020-01-01', 'plan_finish': '2020-12-31'}]}
    view = {'schedule': {'management': [], 'dependency_timeline': block,
                        'dependency_timeline_html': timeline.render(block)}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(view)=>renderGantt(view)', view)
        body = page.locator('#dependencyTimelineBody')
        expect(body).to_be_visible()
        estimate = body.locator('.schedule-rnv-cards>div').nth(1)
        expect(estimate.locator('span')).to_have_text('Оценка по ГПР')
        expect(estimate.locator('strong')).to_have_text('10.05.2027')
        expect(body.get_by_text(
            'Окончание строительных работ оценено по ГПР. Дата разрешения на ввод этим не подтверждается.',
            exact=True)).to_be_visible()
        driver = body.locator('p.schedule-note').filter(has_text='Срок тянет')
        assert driver.count() == 1
        expect(driver).to_be_hidden()
        body.get_by_text('Основание и ограничения', exact=True).click()
        expect(driver).to_be_visible()
        expect(driver).to_contain_text(name)
        expect(driver).to_contain_text('Оценка по измеренному росту процента ГПР.')
        assert body.locator('.schedule-lane,.schedule-technical,svg,img').count() == 0
        assert page.evaluate('window.forecastXSS') is None
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            data = {'project': 'Учебный', 'kind': 'week', 'start': '2026-11-01',
                    'end': '2026-11-06', 'gantt': {'dependency_timeline': block}}
            page.set_content(report.render_html(data))
            basis = 'Оценка по измеренному росту процента ГПР.'
            expect(page.locator('.executive-schedule')).not_to_contain_text(basis)
            source_details = page.locator('details.report-source-screen')
            assert not source_details.get_attribute('open')
            source_details.locator('summary').click()
            expect(source_details.get_by_text(basis, exact=False)).to_be_visible()
            text = ' '.join(' '.join(p.extract_text() or '' for p in
                                    PdfReader(io.BytesIO(page.pdf(format='A4'))).pages).split())
            assert '10.05.2027' in text and 'Оценка окончания работ' in text
            assert 'Оценка работ не подтверждает дату получения разрешения на ввод' in text
            assert text.count('На срок влияет') == 1
            assert 'Оценка по измеренному росту процента ГПР.' in text
            assert text.count(basis) == 1  # one printed appendix, no duplicate main-method explanation
            assert 'Устаревшая техническая работа' not in text
            assert 'Техническая сеть работ' not in text
        assert not errors
