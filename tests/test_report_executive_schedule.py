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
        assert executive["state"] == "partial" and executive["forecast"] == "2026-12-31"
        assert built["schedule"]["qualification"]["forecast"] is None
        assert executive["forecast_label"] == "Оценка по части работ"
    elif scenario in {"unknownpace", "versionspresent"}:
        assert executive["forecast"] is None
    if scenario == "versionspresent":
        assert len(list((monitor._project_dir(PROJECT) / "schedule_fact").glob("*.xlsx"))) == 2
        assert executive["version_comparison"]["state"] == "not_calculated"
    assert "не предоставлены" not in report.render_html(built)


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
            summary = tab.locator("#reportBox .executive-schedule")
            summary.wait_for(state="visible")
            for width in (390, 1440):
                tab.set_viewport_size({"width": width, "height": 1000})
                summary.scroll_into_view_if_needed()
                visible = summary.inner_text()
                assert "План ввода" in visible
                assert "не предоставлены" not in visible
                assert "PM" not in visible and "цепочк" not in visible
                assert "разными единицами" not in visible and "Сравнение версий" not in visible
                assert "Команде:" in visible
                if scenario in {"unknownpace", "partialRNV", "versionspresent"}:
                    assert "4 из 10 м³" in visible and "28.02.2026" in visible
                    assert "текущего темпа" in visible
                if scenario == "unmapped":
                    assert "ещё не сопоставлены" in visible
                if scenario == "historical":
                    assert "после даты сводки" in visible
                if scenario == "partialRNV":
                    assert "Оценка по части работ" in visible and "31.12.2026" in visible
                    assert "не подтверждает дату" in visible
                assert summary.evaluate("e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1}")
                for node in summary.locator(".schedule-rnv-cards>div,.executive-action").all():
                    assert node.evaluate("e=>e.scrollWidth<=e.clientWidth+1"), node.inner_text()
                tab.screenshot(path=f"/tmp/plato1043-{scenario}-{width}.png", full_page=False)
            detail = tab.locator("#reportBox details.report-source-screen").filter(has_text="Источники и ограничения оценки")
            assert not detail.get_attribute("open")
            assert not tab.locator("#reportBox .report-source-appendix").is_visible()
            assert "PM" not in tab.locator("#reportBox").inner_text()
            detail.locator("summary").click()
            assert "Сравнение версий ГПР пока не рассчитано." in detail.inner_text()
            with tab.expect_download(timeout=90_000) as download:
                tab.click("#reportPdfBtn")
            raw = Path(download.value.path()).read_bytes()
            Path(f"/tmp/plato1043-{scenario}.pdf").write_bytes(raw)
            pages = PdfReader(io.BytesIO(raw)).pages
            texts = [" ".join((p.extract_text() or "").split()) for p in pages]
            text = " ".join(texts)
            assert "Сроки и выполнение работ" in text
            assert "Приложение. Источники и ограничения оценки" in text
            assert "Сравнение версий ГПР пока не рассчитано." in text
            assert "не предоставлены" not in text
            assert "PM" not in text
            assert text.index("Сроки и выполнение работ") < text.index("Приложение. Источники")
            if scenario in {"unknownpace", "partialRNV", "versionspresent"}:
                assert "4 из 10 м³" in text
            if scenario == "partialRNV":
                assert "Оценка по части работ" in text and "31.12.2026" in text
                chart_page = next(page for page in texts if "План и прогноз по корпусам" in page)
                chart_start = chart_page.split("План и прогноз по корпусам", 1)[1]
                assert "Работа / объект" in chart_start and "Корпус 1" in chart_start
            assert not errors, errors
        finally:
            browser.close()


def test_archive_without_dates_and_archive_after_cut_have_distinct_states():
    monitor.store_schedule(PROJECT, gpr(), None, "2026-11-01")
    ledgers.store_archive(PROJECT, archive([("Недатированные.xlsx", cumulative_book(split=True))]),
                          CUT, "Учебный архив.zip")
    status = physical.build(PROJECT, CUT)["evidence_status"]
    assert status["archive"] == "available" and status["state"] == "no_dated_quantities"
    assert "Архив загружен" in status["reason"]
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
    assert "0 из 10 м³" in report.render_html(built)


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
