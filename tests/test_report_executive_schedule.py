"""Executive conclusions retain real source states in HTML and printed PDF.

All workbooks, archive contents, names and dates here are synthetic. The app,
archive parser, explicit binding, Monitor, report model and PDF renderer run for
real; no report API or physical result is replaced with a fixture response.
"""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import pytest

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_gpr_physical as physical
from browser import chromium_or_skip, serve
from test_monitor_cumulative_ledgers import archive, book as cumulative_book
from test_monitor_management_gantt import _gpr_book

PROJECT = "Учебная сводка"
CUT = "2026-11-06"
KEY = "executive-synthetic-key"
SCENARIOS = ["noarchive", "unmapped", "unknownpace", "historical", "partialRNV", "versionspresent"]


def gpr(progress=.2, *, second=False):
    rows = [(1, "Устройство стены", progress, dt.date(2026, 9, 1), dt.date(2026, 10, 31), "В работе", "2.2.1.1")]
    if second:
        rows.append((2, "Монтаж кровли", .2, dt.date(2026, 9, 1), dt.date(2026, 12, 31), "В работе", "2.2.1.2"))
    return _gpr_book(rows)


def sources(scenario):
    monitor.store_schedule(PROJECT, gpr(second=scenario == "partialRNV"), None, "2026-11-01")
    if scenario == "noarchive":
        return CUT
    # Jan/Feb volumes have a known total but do not prove a current November pace.
    ledgers.store_archive(PROJECT, archive([("Учебные объёмы.xlsx", cumulative_book())]),
                          "2026-11-01", "Учебный архив.zip")
    if scenario in {"unknownpace", "historical", "partialRNV", "versionspresent"}:
        state = physical.catalog(PROJECT, CUT)
        physical.save(PROJECT, **{k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")},
                      configuration={"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": True,
                                                 "actual_finish": ""}],
                                     "components": [{"component_id": "Стены корпуса 1", "task_id": "1", "item_ids": ["0:0"]}],
                                     "note": "Учебный пример: проверены участок, единица и полный объём."})
    if scenario == "versionspresent":
        monitor.store_schedule_fact(PROJECT, gpr(.1), "2026-10-15")
        monitor.store_schedule_fact(PROJECT, gpr(.3), "2026-11-02")
    return "2026-11-05" if scenario == "historical" else CUT


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setattr(physical, "_now", lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))
    import developaid_monitor_page  # noqa: F401 — installs the actual Monitor pipeline


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_real_source_states_and_values(scenario):
    cut = sources(scenario)
    built = report.build(PROJECT, "week", cut)
    executive = built["construction_summary"]
    expected = {"noarchive": "no_archive", "unmapped": "unmapped", "unknownpace": "pace_unknown",
                "historical": "historical", "partialRNV": "pace_unknown", "versionspresent": "pace_unknown"}[scenario]
    assert executive["source_status"]["state"] == expected
    if scenario != "noarchive":
        assert executive["source_status"]["archive"] == "available"
    if scenario in {"unknownpace", "partialRNV", "versionspresent"}:
        assert executive["facts"][0]["done"] == 4 and executive["facts"][0]["plan"] == 10
        assert executive["facts"][0]["unit"] == "м3"
        assert executive["facts"][0]["date"] == "2026-02-28"
        assert built["gantt"]["dependency_timeline"]["physical"]["tasks"][0]["progress"] == .4
    else:
        assert not executive["facts"]
    if scenario == "partialRNV":
        # The source plan ending in December is not the selected-work assessment.
        assert executive["state"] == "selected_gpr" and executive["forecast"] == "2027-02-11"
        assert executive["rnv_state"] == "partial" and executive["rnv_forecast"] is None
        assert built["schedule"]["qualification"]["forecast"] is None
        assert executive["forecast_label"] == "Оценка окончания учтённых работ"
    elif scenario in {"unknownpace", "versionspresent"}:
        assert executive["forecast"] is None
    if scenario == "versionspresent":
        assert len(list((monitor._project_dir(PROJECT) / "schedule_fact").glob("*.xlsx"))) == 2
        assert executive["version_comparison"]["state"] == "not_calculated"
    assert "не предоставлены" not in report.render_html(built)


def stalled_sources(partial):
    rows = [(1, "Демонтаж башенных кранов К-1,2", .2, dt.date(2026, 9, 1),
             dt.date(2026, 10, 31), "В работе", "2.2.1.1")]
    if partial:
        rows.append((2, "Фасад", .3, dt.date(2026, 9, 1), dt.date(2026, 12, 31),
                     "В работе", "2.2.1.2"))
    monitor.store_schedule(PROJECT, _gpr_book(rows), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, _gpr_book(rows), "2026-10-21")


@pytest.mark.parametrize("partial", [False, True])
def test_stalled_gpr_work_and_its_cause_remain_in_the_executive_conclusion(partial):
    stalled_sources(partial)
    built = report.build(PROJECT, "week", CUT)
    assert built["construction_summary"]["state"] == "selected_gpr"
    assert built["construction_summary"]["forecast"] == ("2027-01-30" if partial else "2026-12-24")
    assert built["construction_summary"]["rnv_state"] == ("partial" if partial else "unknown")
    assert built["construction_summary"]["rnv_forecast"] is None
    risk = built["construction_summary"]["stalled_text"]
    assert "Демонтаж башенных кранов К-1,2" in risk
    assert built["schedule"]["stalled"][0]["reason"] in risk
    assert "процент в ГПР" in risk and "актов" not in risk
    conclusion = next(item["text"] for item in built["findings"] if item["topic"] == "Срок")
    assert risk in conclusion
    if partial:
        # The broader RNV source is retained apart from the selected assessment.
        assert "Фасад" in built["construction_summary"]["rnv_driver"]
    from developaid_report_schedule import render
    assert risk in render(built["construction_summary"])
    assert built["schedule"]["qualification"]["forecast"] is None


def test_stalled_gpr_risk_is_visible_before_details_in_html_and_pdf(monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import main_legacy as core

    stalled_sources(True)
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, 18844) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(accept_downloads=True)
            errors = []
            tab.on("pageerror", lambda error: errors.append(str(error)))
            tab.add_init_script(f"localStorage.setItem('plato_projects_key','{KEY}')")
            tab.goto(base + "/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.fill("#cut", CUT)
            tab.click("#reportBtn")
            summary = tab.locator("#reportBox .report-gpr-compact")
            summary.wait_for(state="visible")
            for width in (390,1440):
                tab.set_viewport_size(dict(width=width,height=1000))
                assert summary.locator('[data-gpr-block]').count()==3
                assert summary.locator('details,.executive-stalled').count()==0
                risk = summary.locator('[data-gpr-block=forecast] .rg-stalled')
                assert risk.count() == 1 and risk.is_visible()
                text = risk.inner_text()
                assert 'По всему текущему ГПР' in text
                assert 'Демонтаж башенных кранов К-1,2' in text and 'процент в ГПР' in text
                assert 'актов' not in text
                assert risk.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                assert summary.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            with tab.expect_download(timeout=90_000) as download:
                tab.click("#reportPdfBtn")
            raw = Path(download.value.path()).read_bytes()
            text = " ".join(" ".join((page.extract_text() or "").split())
                            for page in PdfReader(io.BytesIO(raw)).pages)
            assert 'Приложение. Источники и ограничения оценки'not in text
            assert 'Прогноз учтённых работ'in text and 'Гант по корпусам'in text
            assert 'По всему текущему ГПР' in text
            assert text.count('Демонтаж башенных кранов К-1,2') == 1 and 'процент в ГПР' in text
            assert '2044'not in text
            assert not errors,errors

        finally:
            browser.close()


def test_status_distinguishes_unconfirmed_and_undated_quantities():
    sources("unmapped")
    state = physical.catalog(PROJECT, CUT)
    physical.save(PROJECT, **{k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")},
                  configuration={"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": False,
                                             "actual_finish": ""}],
                                 "components": [{"component_id": "Стены", "task_id": "1", "item_ids": ["0:0"]}],
                                 "note": "Состав ещё проверяется."})
    got = physical.build(PROJECT, CUT)
    assert got["evidence_status"]["state"] == "unconfirmed"
    assert got["tasks"][0]["progress"] is None
    # Real parser: undated KS header does not invent dated installation volume.
    ledgers.store_archive(PROJECT, archive([("Без дат.xlsx", cumulative_book(split=True))]), CUT, "Без дат.zip")
    got = physical.build(PROJECT, CUT)
    assert got["evidence_status"]["dated_rows"] == 0
    # The changed source is the immediate actionable blocker, never 'not provided'.
    assert got["evidence_status"]["state"] == "source_changed"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_page_and_pdf(scenario, tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import main_legacy as core

    cut = sources(scenario)
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, 18843) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(accept_downloads=True)
            errors = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script(f"localStorage.setItem('plato_projects_key','{KEY}')")
            tab.goto(base + "/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.fill("#cut", cut)
            tab.click("#reportBtn")
            summary=tab.locator('#reportBox .report-gpr-compact')
            summary.wait_for(state='visible')
            for width in (390,1440):
                tab.set_viewport_size(dict(width=width,height=1000))
                assert summary.locator('[data-gpr-block]').count()==3
                dates=summary.locator('[data-gpr-block]').evaluate_all('es=>es.map(e=>e.dataset.projectForecast)')
                assert dates==[dates[0]]*3
                assert summary.locator('details,.executive-schedule,.cg-work').count()==0
                assert summary.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                assert tab.locator('#reportBox .report-source-appendix').count()==0
                assert 'PM'not in summary.inner_text()
                tab.screenshot(path=f'/tmp/plato1043-{scenario}-{width}.png',full_page=False)
            with tab.expect_download(timeout=90_000) as download:
                tab.click("#reportPdfBtn")
            raw = Path(download.value.path()).read_bytes()
            Path(f"/tmp/plato1043-{scenario}.pdf").write_bytes(raw)
            pages = PdfReader(io.BytesIO(raw)).pages
            texts = [" ".join((p.extract_text() or "").split()) for p in pages]
            text = " ".join(texts)
            assert 'Прогноз учтённых работ'in text and 'Матрица готовности'in text and 'Гант по корпусам'in text
            assert 'Приложение. Источники и ограничения оценки'not in text
            assert 'Сравнение версий ГПР пока не рассчитано.'not in text
            assert '4 из 10 м³'not in text and 'PM'not in text
            assert not errors, errors
        finally:
            browser.close()


def test_known_undated_quantities_and_archive_after_cut_have_distinct_states():
    monitor.store_schedule(PROJECT, gpr(), None, "2026-11-01")
    ledgers.store_archive(PROJECT, archive([("Недатированные.xlsx", cumulative_book(split=True))]),
                          CUT, "Учебный архив.zip")
    status = physical.build(PROJECT, CUT)["evidence_status"]
    assert status["archive"] == "available" and status["state"] == "unmapped"
    assert status["reported_rows"] == 2 and status["dated_rows"] == 0
    assert status["measured_tasks"] == 0 and status["mapping"] == "unbound"
    assert "Накопительные загружены" in status["reason"]
    status = physical.build(PROJECT, "2026-11-05")["evidence_status"]
    assert status["state"] == "historical" and status["archive"] == "after_cut"


def test_confirmed_zero_is_known_natural_fact_even_without_pace():
    from openpyxl import load_workbook
    monitor.store_schedule(PROJECT, gpr(), None, "2026-11-01")
    workbook = load_workbook(io.BytesIO(cumulative_book(actual=0)))
    workbook.active["H9"] = 0
    workbook.active["K9"] = 0
    output = io.BytesIO()
    workbook.save(output)
    ledgers.store_archive(PROJECT, archive([("Нулевой факт.xlsx", output.getvalue())]),
                          "2026-11-01", "Учебный архив.zip")
    state = physical.catalog(PROJECT, CUT)
    physical.save(PROJECT, **{k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")},
                  configuration={"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": True,
                                             "actual_finish": ""}],
                                 "components": [{"component_id": "Стены", "task_id": "1", "item_ids": ["0:0"]}],
                                 "note": "Подтверждён учебный нулевой объём за закрытые периоды."})
    built = report.build(PROJECT, "week", CUT)
    executive = built["construction_summary"]
    assert executive["facts"][0]["done"] == 0
    assert executive["source_status"]["state"] == "pace_unknown"
    assert executive["forecast"] is None
    # Confirmed zero is still a measured fact in the complete native consumer;
    # the compact document links to those details rather than printing them.
    from developaid_report_schedule import fact_text
    from developaid_schedule_timeline import render as monitor_timeline
    assert "0 из 10 м³" in fact_text(executive["facts"][0])
    assert "0 / 10 м³" in monitor_timeline(built['gantt']['dependency_timeline'])
    markup = report.render_html(built)
    assert markup.count('data-gpr-block=') == 3
    assert "0 из 10 м³" not in markup and 'Подробные работы и источники — в Мониторе' in markup


@pytest.mark.parametrize("revoked", [False, True])
def test_future_mapping_event_cannot_replace_the_state_selected_at_cut(monkeypatch, revoked):
    sources("unmapped")
    configuration = {"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": True,
                                 "actual_finish": ""}],
                     "components": [{"component_id": "Стены", "task_id": "1", "item_ids": ["0:0"]}],
                     "note": "Подтверждены учебные натуральные объёмы."}

    def record(day, config):
        monkeypatch.setattr(physical, "_now", lambda: dt.datetime(2026, 11, day, 12, tzinfo=dt.timezone.utc))
        state = physical.catalog(PROJECT, f"2026-11-{day:02d}")
        physical.save(PROJECT, **{k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")},
                      configuration=config)

    record(3, configuration)
    if revoked:
        record(4, {"tasks": [], "components": [], "note": "Соответствия отозваны до даты сводки."})
    record(10, configuration)
    got = physical.build(PROJECT, CUT)
    assert got["recorded_at"].startswith("2026-11-04" if revoked else "2026-11-03")
    assert got["evidence_status"]["state"] == ("unmapped" if revoked else "pace_unknown")
    assert got["evidence_status"]["mapping"] == ("unbound" if revoked else "confirmed")
    assert got["physical_evidence"] is (not revoked)
    assert got["tasks"][0]["progress"] == (None if revoked else .4)


def test_future_mapping_for_a_new_archive_does_not_change_old_unmapped_state(monkeypatch):
    sources("unmapped")
    before = physical.build(PROJECT, CUT)
    ledgers.store_archive(PROJECT, archive([("Будущие объёмы.xlsx", cumulative_book())]),
                          "2026-11-10", "Будущий учебный архив.zip")
    monkeypatch.setattr(physical, "_now", lambda: dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc))
    state = physical.catalog(PROJECT, "2026-11-10")
    physical.save(PROJECT, **{k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")},
                  configuration={"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": True,
                                             "actual_finish": ""}],
                                 "components": [{"component_id": "Стены", "task_id": "1", "item_ids": ["0:0"]}],
                                 "note": "Подтверждение будущего учебного архива."})
    after = physical.build(PROJECT, CUT)
    assert after["snapshot_id"] == before["snapshot_id"]
    assert after["recorded_at"] is None and not after["physical_evidence"]
    assert after["evidence_status"] == before["evidence_status"]
    assert after["evidence_status"]["state"] == "unmapped"
