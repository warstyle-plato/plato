"""One GPR forecast across APIs, money-independent and with honest source facts."""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_monitor_pace as pace
import developaid_management_report as report
from test_monitor_management_gantt import _gpr_book

CUT = dt.date(2026, 11, 6)
PROJECT = "Учебный график"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    start, finish = dt.date(2026, 9, 1), dt.date(2026, 10, 31)
    monitor.store_schedule(PROJECT, _gpr_book([
        (1, "Каркас", .2, start, finish, "В работе", "2.2.1.1"),
        (2, "Фасад", .3, start, finish, "В работе", "2.2.1.1"),
    ]), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, _gpr_book([
        (1, "Каркас", .4, start, finish, "В работе", "2.2.1.1"),
        (2, "Фасад", .3, start, finish, "В работе", "2.2.1.1"),
    ]), "2026-10-21")
    # Install the same production stack without replacing its captured builds.
    import developaid_monitor_page  # noqa: F401
    return PROJECT


def test_schedule_only_workflows_need_no_rss_and_all_readers_agree(site):
    view = monitor.build(site, CUT)
    assert view["financial_state"]["state"] == "missing"
    assert all(value is None for value in view["money"].values())
    assert view["by_code"] == view["schedule"]["rows"]
    rows = {r["id"]: r for r in view["by_code"]}
    assert rows["1"]["forecast_finish"] == "2026-12-20"
    assert rows["2"]["forecast_finish"] is None
    assert rows["2"]["pace_forecast_method"] == "stalled"
    assert view["schedule"]["risks"] == 2
    assert view["schedule"]["forecast_state"] == "partial"
    assert view["schedule"]["forecast_end"] is None
    assert view["schedule"]["indicative_forecast_end"] == "2026-12-20"
    api = monitor.gantt(site, CUT)
    assert api["rows"] == view["schedule"]["rows"]
    assert api["by_code"] == api["rows"]
    assert api["overdue"] == 2 and api["forecast_end"] is None
    assert api["work_fact"] == view["schedule"]["work_fact"]
    block = report.gantt(view, view["dashboard"])
    assert block["work_fact"] == api["work_fact"]
    assert block["corpora"][0]["forecast_partial"]
    assert block["corpora"][0]["forecast_finish"] == "2026-12-20"
    assert block["source"]["basis"] == "gpr"


def test_overlay_replaces_all_old_money_aliases_and_dates(site):
    view = manager._schedule_only(site, CUT)
    view["by_code"] = [{"actual_progress": .99, "forecast_finish": "2099-01-01"}]
    view["schedule"].update(risks=99, forecast_end="2099-01-01", pace_forecast_end="2099-01-01")
    for node in pace._walk(view["schedule"]["management"]):
        node.update(actual_progress=.99, actual_equivalent_date="2026-12-01", accepted=99, eac=100)
    pace._apply_gpr(site, view, CUT)
    assert view["by_code"] == view["schedule"]["rows"]
    assert view["schedule"]["risks"] == 2 and view["schedule"]["forecast_end"] is None
    for node in pace._walk(view["schedule"]["management"]):
        assert node["actual_equivalent_date"] is None
        if node["level"] == "task":
            assert node["actual_progress"] in (.3, .4)
            assert node["progress_source"]["date"] == "2026-10-21"
            assert node["progress_source"]["kind"] == "weekly_gpr"
        else:
            assert node["actual_progress"] is None and node["pace_progress"] is None
            assert node["progress_kind"] == "not_aggregated"
            assert node["progress_reason"]


def test_old_task_forecast_is_removed_when_current_gpr_has_no_pace(site):
    view = manager._schedule_only(site, CUT)
    for node in pace._walk(view["schedule"]["management"]):
        node["forecast_finish"] = "2099-01-01"
    pace._apply_gpr(site, view, CUT)
    leaf = next(node for node in pace._walk(view["schedule"]["management"])
                if node.get("id") == "2")
    assert leaf["forecast_finish"] is None and not leaf["forecast_known"]
    assert "стоит" in leaf["forecast_reason"]


def test_known_zero_has_source_and_missing_reading_is_not_zero(site):
    import developaid_schedule_gpr_forecast as gpr
    row = {"plan_start": "2026-09-01", "plan_finish": "2026-10-31"}
    known = gpr.work(row, [(dt.date(2026, 11, 1), 0., "weekly_gpr")], CUT)
    unknown = gpr.work(row, [], CUT)
    assert known["progress"] == 0 and known["progress_origin"] == "weekly_gpr"
    assert known["progress_date"] == "2026-11-01"
    assert unknown["progress"] is None and unknown["progress_origin"] is None
    assert unknown["method"] == "unknown" and "стоит" not in unknown["reason"]


def test_future_readings_never_supply_a_percent_or_pace():
    import developaid_schedule_gpr_forecast as gpr
    row = {"plan_start": "2026-09-01", "plan_finish": "2026-10-31"}
    got = gpr.work(row, [(dt.date(2026, 11, 7), 1., "weekly_gpr")], CUT)
    assert got["progress"] is None and got["forecast_finish"] is None


def test_duplicate_gpr_identifiers_do_not_borrow_the_last_rows_progress(monkeypatch):
    import developaid_schedule_gpr_forecast as gpr
    monkeypatch.setattr(gpr, "history", lambda *_: {"1": [(dt.date(2026,11,1), 1., "weekly_gpr")]})
    rows = [{"id": "1", "plan_finish": "2026-10-31"}, {"id": "1", "plan_finish": "2026-10-31"}]
    got = gpr.forecasts("Учебный", CUT, rows)["1"]
    assert got["forecast_finish"] is None and got["progress"] is None
    assert "повторяется" in got["reason"]


def test_nonconstruction_tasks_do_not_define_the_rnv_plan(site):
    view = manager._schedule_only(site, CUT)
    view["schedule"]["rows"].append({"id": "3", "name": "Продажи", "code": "",
                                      "plan_start": "2026-01-01", "plan_finish": "2030-01-01"})
    pace._apply_gpr(site, view, CUT)
    qualified = view["schedule"]["dependency_timeline"]["rnv"]
    assert qualified["approved"] == "2026-10-31"
    assert any("без статьи" in reason for reason in qualified["reasons"])


def test_unapproved_corpus_file_has_source_view_and_a_specific_mapping_blocker(tmp_path, monkeypatch):
    import developaid_schedule_gpr_physical as physical
    from test_gpr_corpus_preview import book
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule_fact(PROJECT, book(bad_date="01.02.2027"), CUT.isoformat())
    import developaid_monitor_page  # noqa: F401
    view = monitor.build(PROJECT, CUT)
    assert view["schedule"]["rows"] == []
    assert view["schedule"]["corpus_gpr"]["baseline_approved"] is False
    assert "Исходные показания ГПР" in view["schedule"]["corpus_gpr_html"]
    assert view["schedule"]["forecast_end"] is None
    state = physical.catalog(PROJECT, CUT.isoformat())
    assert state["source_state"] == "unapproved_corpus" and not state["can_edit"]
    assert "пакет и корпус" in state["source_reason"]
    assert state["tasks"] == [] and not state["model"]["physical_evidence"]


@pytest.mark.parametrize("value", [True, False, -1, -0.1, 101, float("nan"), float("inf")])
def test_corrupt_percent_cannot_become_work_readiness(value):
    import developaid_schedule_gpr_forecast as gpr
    assert gpr._progress(value) is None


def test_first_hundred_percent_reading_is_not_a_late_finish(tmp_path, monkeypatch):
    """Работа, давно законченная, получает 100% в шапке новой версии плана.

    Дата показания — не дата окончания: ни работа, ни корпус не становятся
    «позже плана» на разницу между сроком работы и датой файла.
    """
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule(PROJECT, _gpr_book([
        (1, "Котлован", 1., dt.date(2025, 11, 1), dt.date(2026, 1, 31), "Завершено", "2.2.1.1"),
        (2, "Каркас", .2, dt.date(2026, 9, 1), dt.date(2027, 6, 30), "В работе", "2.2.1.1"),
    ]), None, "2026-10-01")
    import developaid_monitor_page  # noqa: F401
    view = manager._schedule_only(PROJECT, CUT)
    pace._apply_gpr(PROJECT, view, CUT)
    rows = {r["id"]: r for r in view["schedule"]["rows"]}
    assert rows["1"]["pace_forecast_method"] == "done"
    assert rows["1"]["observed_complete_by"] == "2026-10-01"
    assert rows["1"]["delta_days"] is None and rows["1"]["pace_delta_days"] is None
    assert rows["2"]["observed_complete_by"] is None
    assert view["schedule"]["risks"] == 0
    for node in pace._walk(view["schedule"]["management"]):
        assert not (node.get("delta_days") or 0) > 0, node.get("name")


def test_done_label_and_no_delay_reach_the_gantt_tree_and_the_report(tmp_path, monkeypatch):
    """Настоящий путь: загрузка ГПР → срез Монитора → дерево Ганта и сводка.

    Метка «100% на дату» живёт на строке работы; Гант и сводка руководству
    читают дерево `schedule.management`, поэтому метка обязана дойти туда, а
    дата файла не должна становиться ни сроком раздела, ни опозданием корпуса.
    """
    import developaid_report_gantt as report_gantt
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule(PROJECT, _gpr_book([
        (1, "Котлован", 1., dt.date(2025, 11, 1), dt.date(2026, 1, 31), "Завершено", "2.2.1.1"),
        (2, "Каркас", .2, dt.date(2026, 9, 1), dt.date(2027, 6, 30), "В работе", "2.2.1.1"),
    ]), None, "2026-10-01")
    import developaid_monitor_page  # noqa: F401
    view = monitor.build(PROJECT, CUT)
    tasks = {n.get("id"): n for n in pace._walk(view["schedule"]["management"]) if n.get("level") == "task"}
    assert tasks["1"]["observed_complete_by"] == "2026-10-01"
    assert tasks["1"]["delta_days"] is None
    assert tasks["2"]["observed_complete_by"] is None
    for node in pace._walk(view["schedule"]["management"]):
        if node.get("level") != "task" and node.get("forecast_finish") == "2026-10-01":
            # Если других сроков нет, дата раздела — та же метка «на дату».
            assert node["observed_complete_by"] == "2026-10-01", node.get("name")
    gantt = report_gantt.model(view["schedule"]["management"])
    for item in [row for corpus in gantt["corpora"] for row in [corpus, *corpus["articles"]]]:
        assert not (item["delta_days"] or 0) > 0, item
        assert item["forecast_finish"] != "2026-10-01", item
    rnv = view["schedule"]["dependency_timeline"]["rnv"]
    assert rnv.get("indicative_forecast") != "2026-10-01"
    text = report.render_text(report.build(PROJECT, "week", CUT.isoformat()))
    assert "Сильнее всех опаздывает" not in text and "+243" not in text


def test_the_report_late_rule_is_the_row_delta_not_file_date_minus_plan():
    import developaid_report_gantt as report_gantt
    done = {"level": "task", "name": "Котлован", "object": "Корпус 1", "plan_start": "2025-11-01",
            "plan_finish": "2026-01-31", "forecast_finish": "2026-10-01", "pace_forecast_known": True,
            "pace_forecast_method": "done", "observed_complete_by": "2026-10-01", "delta_days": None,
            "work_done": True}
    late = dict(done, name="Каркас", plan_finish="2026-09-01", forecast_finish="2026-12-01",
                pace_forecast_method="gpr_pace", observed_complete_by=None, delta_days=91, work_done=False)
    corpus = report_gantt.model([done])["corpora"][0]
    for item in (corpus, *corpus["articles"]):
        assert item["all_done"] is True and item["delta_days"] is None and item["forecast_finish"] is None
    assert report_gantt.text_lines({"corpora": [corpus]}) == [
        "Корпус 1: окончание работ по графику 31.01.2026, все работы завершены."]
    corpus = report_gantt.model([done, late])["corpora"][0]
    assert corpus["delta_days"] == 91 and corpus["forecast_finish"] == "2026-12-01"
    # Нет отклонения — не «в срок».
    unknown = dict(corpus, delta_days=None, all_done=False, forecast_partial=False)
    assert report_gantt.text_lines({"corpora": [unknown]})[0].endswith("отклонение от графика не посчитано.")


def test_a_file_date_of_a_done_work_is_not_the_latest_date_of_its_stage_or_the_rnv():
    import developaid_schedule_gpr_forecast as gpr
    done = {"level": "task", "id": "1", "name": "Котлован", "forecast_known": True,
            "forecast_finish": "2026-10-01", "observed_complete_by": "2026-10-01", "delta_days": None}
    closed = {"level": "task", "id": "2", "name": "Сваи", "forecast_known": True,
              "forecast_finish": "2026-09-01", "actual_finish": "2026-09-01", "delta_days": -5}
    stage = {"level": "stage", "name": "Подземная часть", "children": [done, closed]}
    only = {"level": "stage", "name": "Земляные работы", "children": [dict(done)]}
    pace._aggregate_gpr([stage, only])
    assert stage["forecast_finish"] == "2026-09-01" and stage["observed_complete_by"] is None
    # Других сроков нет — дата раздела остаётся меткой «на дату», не окончанием.
    assert only["forecast_finish"] == "2026-10-01" and only["observed_complete_by"] == "2026-10-01"
    rows = [{"id": "1", "name": "Котлован", "code": "2.2.1.1", "plan_finish": "2026-01-31",
             "observed_complete_by": "2026-10-01"},
            {"id": "2", "name": "Сваи", "code": "2.2.1.1", "plan_finish": "2026-09-06"}]
    works = {"1": {"forecast_finish": "2026-10-01", "method": "done"},
             "2": {"forecast_finish": "2026-09-01", "method": "confirmed_completion"}}
    assert gpr.rnv(rows, works, "2026-12-31")["indicative_forecast"] == "2026-09-01"
    alone = gpr.rnv(rows[:1], {"1": works["1"]}, "2026-12-31")
    assert alone["indicative_forecast"] == "2026-10-01"
    assert any("впервые отмечено 100%" in reason for reason in alone["reasons"])


def test_a_confirmed_late_finish_is_finished_late_not_a_current_delay(tmp_path, monkeypatch):
    """Владелец (п.3, вариант А): подтверждённо законченная позже плана работа —
    «Закончено на N дн. позже плана» везде; отстающим корпус делают только
    незаконченные работы, и сводка руководству законченные не берёт."""
    import developaid_report_gantt as report_gantt
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule(PROJECT, _gpr_book([
        (1, "Котлован", 1., dt.date(2025, 11, 1), dt.date(2026, 1, 31), "Завершено", "2.2.1.1"),
        (2, "Каркас", .2, dt.date(2026, 9, 1), dt.date(2027, 6, 30), "В работе", "2.2.1.1"),
    ]), None, "2026-10-01")
    import developaid_monitor_page  # noqa: F401
    real = pace.gpr_forecast.forecasts

    def confirmed(*args, **kwargs):
        works = real(*args, **kwargs)
        works["1"] = dict(works.get("1") or {}, method="confirmed_completion", progress=1.,
                          progress_origin="confirmed_completion", forecast_finish="2026-04-03")
        works["2"] = dict(works.get("2") or {}, method="gpr_pace", progress=.2, forecast_finish="2027-06-20")
        return works
    monkeypatch.setattr(pace.gpr_forecast, "forecasts", confirmed)
    view = monitor.build(PROJECT, CUT)
    nodes = pace._walk(view["schedule"]["management"])
    tasks = {n.get("id"): n for n in nodes if n.get("level") == "task"}
    assert tasks["1"]["work_done"] is True and tasks["1"]["finished_late_days"] == 62
    assert tasks["2"]["work_done"] is False and tasks["2"]["finished_late_days"] is None
    assert view["schedule"]["risks"] == 0
    for node in nodes:
        if node.get("level") != "task":
            assert node["finished_late_days"] == 62 and not (node["delta_days"] or 0) > 0, node.get("name")
    gantt = report_gantt.model(view["schedule"]["management"])
    corpus = gantt["corpora"][0]
    assert corpus["finished_late_days"] == 62 and corpus["delta_days"] == -10
    assert "среди законченных работ: закончено на 62 дн. позже плана" in report_gantt.text_lines(gantt)[0]
    assert "Закончено на 62 дн. позже плана" in report_gantt.render(gantt, CUT)
    text = report.render_text(report.build(PROJECT, "week", CUT.isoformat()))
    assert "Сильнее всех опаздывает" not in text
    assert "закончено на 62 дн. позже плана" in text


@pytest.mark.parametrize("item,done,reading,plan", [
    ({"method": "done"}, True, True, False),
    ({"method": "confirmed_completion"}, True, False, False),
    ({"method": "cumulative_quantities", "progress_origin": "confirmed_completion"}, True, False, False),
    ({"method": "gpr_pace", "progress_origin": "gpr"}, False, False, False),
    ({"method": "plan"}, False, False, True),
    ({}, False, False, False),
])
def test_one_rule_says_a_work_is_done_and_whether_its_date_is_only_a_reading(item, done, reading, plan):
    import developaid_schedule_done as done_rule
    assert done_rule.plan_only(item) is plan  # только план, темпа нет — не прогноз
    assert done_rule.work_done(item) is done
    assert done_rule.reading_only(item) is reading
    assert done_rule.reading_only(item, "2026-09-01") is False  # подтверждённое окончание — не показание
