"""Отклонение факта договора от накопленного плана, отставание в днях, отчёт и прогноз срока.

Документы, ведомость и сроки выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_control as control
import developaid_contract_fact as fact
import developaid_contract_files as files
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, ROW
from tests.test_contract_fact_prices_ks_by_the_edition import REGISTER_ROW, _item, card  # noqa: F401

LINE = {"code": "3.1", "name": "Кладка стен", "start": "2026-03-01", "finish": "2026-03-10", "amount": 1000.0,
        "volume": {"unit": "м3", "quantity": 20.0}}


def _plan(cut, *lines, start=None):
    import developaid_contract_plan as plan
    import datetime as dt
    day = dt.date.fromisoformat(cut)
    lines = [{**line, "planned": line["amount"] * plan.done(line, day, dt.date.fromisoformat(start)
                                                             if start else None)} for line in lines]
    return {"editions": [{"in_force": True, "start": start, "lines": lines, "total": sum(x["amount"] for x in lines),
                          "planned": sum(x["planned"] for x in lines), "outside": {}}]}


def _fact(*lines):
    return {"note": "", "lines": [{"code": code, "fact": money, "volumes": volumes} for code, money, volumes in lines]}


@pytest.mark.parametrize("cut, money, state, lag, ahead, forecast", [
    # План 100 ₽ в день с 01.03: к 05.03 — 500 ₽.
    ("2026-03-05", 300.0, "behind", 2, 0, "2026-03-12"),
    ("2026-03-05", 0.0, "behind", 5, 0, "2026-03-15"),
    ("2026-03-05", 500.0, "on_plan", 0, 0, "2026-03-10"),
    ("2026-03-05", 800.0, "ahead", 0, 3, "2026-03-10"),
    ("2026-03-05", 1000.0, "done", 0, 5, None),
    ("2026-02-20", 0.0, "not_due", 0, 0, "2026-03-10"),
    # Срок строки прошёл: отставание растёт каждый день, пока остаток не выполнен.
    ("2026-03-20", 900.0, "behind", 11, 0, "2026-03-21"),
])
def test_a_line_lags_by_the_days_back_to_when_the_plan_equalled_its_fact(cut, money, state, lag, ahead, forecast):
    got = control.build(_plan(cut, LINE), _fact(("3.1", money, [{"unit": "м3", "quantity": money / 50}])),
                        None, "", cut)
    (line,) = got["lines"]
    assert (line["state"], line["lag_days"], line["ahead_days"], line["forecast_finish"]) == (
        state, lag, ahead, forecast)
    assert line["deviation"] == money - line["planned"]
    assert line["behind_amount"] == max(line["planned"] - money, 0.0)


def test_the_behind_volume_is_shown_in_its_unit_only_when_the_line_has_one():
    got = control.build(_plan("2026-03-05", LINE), _fact(("3.1", 300.0, [{"unit": "м³", "quantity": 6.0}])),
                        None, "", "2026-03-05")
    assert got["lines"][0]["volume"] == {"unit": "м3", "quantity": 20.0, "planned": 10.0, "fact": 6.0,
                                         "behind": 4.0}
    assert got["lines"][0]["percent"] == pytest.approx(-0.4)
    mixed = control.build(_plan("2026-03-05", LINE), _fact(("3.1", 300.0, [{"unit": "т", "quantity": 6.0}])),
                          None, "", "2026-03-05")
    unknown = control.build(_plan("2026-03-05", {**LINE, "volume": None}), _fact(("3.1", 300.0, [])),
                            None, "", "2026-03-05")
    assert mixed["lines"][0]["volume"] is None and unknown["lines"][0]["volume"] is None


def test_the_forecast_keeps_each_lag_and_names_the_lines_that_break_the_deadline():
    later = {**LINE, "code": "3.2", "name": "Перегородки", "start": "2026-03-06", "finish": "2026-03-15"}
    planned = _plan("2026-03-05", LINE, later)
    got = control.build(planned, _fact(("3.1", 300.0, [])), "2026-03-14", "Указан вручную", "2026-03-05")
    # 3.1 отстаёт на 2 дня → 12.03; 3.2 ещё не начата → 15.03 по графику, позже срока договора.
    assert [(r["code"], r["forecast_finish"]) for r in got["lines"]] == [("3.1", "2026-03-12"), ("3.2", "2026-03-15")]
    assert got["forecast"] == {"deadline": "2026-03-14", "deadline_label": "Указан вручную", "from_register": True,
                               "finish": "2026-03-15", "days_over": 1, "threat": True, "drivers": ["3.2"],
                               "outside": 0, "passed": False}
    assert got["behind"] == ["3.1"] and got["ahead"] == []
    calm = control.build(planned, _fact(("3.1", 500.0, [])), None, "", "2026-03-05")["forecast"]
    assert calm["deadline_label"] == "окончание графика действующей редакции" and not calm["threat"]
    assert calm["finish"] == "2026-03-15" and calm["days_over"] == 0
    late = control.build(planned, _fact(("3.1", 300.0, [])), "2026-03-04", "Указан вручную", "2026-03-05")
    assert late["forecast"]["passed"] and not calm["passed"]


def test_a_plan_line_has_a_natural_volume_only_in_one_unit_with_known_quantities():
    import developaid_contract_plan as plan
    assert plan._volume([("м³", 10.0, 0.5), ("м3", 4.0, 1.0)]) == {"unit": "м³", "quantity": 9.0}
    assert plan._volume([("м3", 10.0, 0.5), ("т", 4.0, 1.0)]) is None
    assert plan._volume([("м3", 10.0, 0.5), ("м3", None, 1.0)]) is None and plan._volume([]) is None


def test_the_report_orders_the_lagging_lines_by_days_and_the_ahead_ones_by_lead():
    lines = [{**LINE, "code": code} for code in ("1", "2", "3", "4")]
    got = control.build(_plan("2026-03-05", *lines),
                        _fact(("1", 400.0, []), ("2", 100.0, []), ("3", 700.0, []), ("4", 900.0, [])),
                        None, "", "2026-03-05")
    assert got["behind"] == ["2", "1"] and got["ahead"] == ["4", "3"]
    assert got["total"]["fact"] == 2100.0 and got["total"]["state"] == "ahead"


def test_without_a_plan_or_a_fact_the_deviation_says_why():
    none = control.build({"editions": []}, _fact(), None, "", "2026-03-05")
    assert none["note"] == "Отклонение не рассчитано: на дату среза нет действующей редакции плана."
    missing = control.build(_plan("2026-03-05", LINE), {"note": "Факт не рассчитан: Выберите проект.", "lines": []},
                            None, "", "2026-03-05")
    assert missing["note"] == ("Отклонение от плана не рассчитано, потому что нет факта. "
                               "Факт не рассчитан: Выберите проект.")
    empty = control.build(_plan("2026-03-05"), _fact(), None, "", "2026-03-05")
    assert empty["note"] == "Отклонение не рассчитано: в плане нет ни одной строки с подтверждённой связью."


# --- карточка договора --------------------------------------------------------------

def test_the_card_reports_lag_volume_and_the_threat_to_the_schedule_end(card):  # noqa: F811
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(REGISTER_ROW))["control"]
    assert got["note"] == "" and got["assumption"] == control.ASSUMPTION
    rows = {r["code"]: r for r in got["lines"]}
    # 1.1 должна была быть закончена на дату соглашения 01.02: половина остатка — 3 дня отставания.
    assert [(c, rows[c]["planned"], rows[c]["fact"], rows[c]["lag_days"], rows[c]["forecast_finish"])
            for c in ("1.1", "1.2", "1.3")] == [
        ("1.1", 3000.0, 1500.0, 3, "2026-02-04"), ("1.2", 4000.0, 2500.0, 1, "2026-02-06"),
        ("1.3", 3000.0, 1500.0, 2, "2026-02-05")]
    assert rows["1.2"]["volume"] == {"unit": "м3", "quantity": 0.625, "planned": 0.5, "fact": 0.3125,
                                     "behind": 0.1875}
    assert got["behind"] == ["1.1", "1.3", "1.2"]
    assert got["total"] == {"amount": 11000.0, "planned": 10000.0, "fact": 5500.0, "deviation": -4500.0,
                            "percent": -0.45, "state": "behind", "lag_days": 2, "ahead_days": 0,
                            "behind_amount": 4500.0}
    forecast = got["forecast"]
    assert (forecast["deadline"], forecast["from_register"], forecast["finish"], forecast["days_over"],
            forecast["drivers"]) == ("2026-02-05", False, "2026-02-06", 1, ["1.2"])
    # Лестницы корпуса 2 на проверке: в план и прогноз не вошли.
    assert forecast["outside"] == 2


def test_the_register_deadline_is_the_limit_and_a_ks_without_work_yet_is_a_zero_fact(card):  # noqa: F811
    row = {**ROW, "deadline": "2026-02-10", "deadline_source": {"label": "Срок из источника"},
           "physical_items": [_item("1.1", "Устройство стен", (0.25, 2000, "2026-02-05", "2026-02-06"))]}
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(row))
    # Работа есть, но её период закончился после среза: факт ноль, а не «нет данных».
    assert got["fact"]["note"] == "" and got["fact"]["total"] == 0.0 and got["fact"]["after_cut"] == 1
    forecast = got["control"]["forecast"]
    assert (forecast["deadline"], forecast["deadline_label"], forecast["threat"]) == (
        "2026-02-10", "Срок из источника", False)
    assert got["control"]["total"]["fact"] == 0.0 and got["control"]["total"]["lag_days"] == 4
    # Работа в КС-6а есть, но выполнения по ней ещё не было: это тоже ноль, а не «нет данных».
    idle = {**ROW, "physical_items": [{**_item("1.1", "Устройство стен"), "completed_quantity": 0.0}]}
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(idle))
    assert got["fact"]["note"] == "" and got["fact"]["total"] == 0.0
    empty = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts({**ROW, "physical_items": []}))
    assert empty["fact"]["note"].startswith("В накопительной КС-6а этого договора нет выполнения")


# --- страница -----------------------------------------------------------------------

@pytest.mark.parametrize("width", [390, 1440])
def test_the_card_reports_the_lag_and_the_threat_in_plain_words(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(REGISTER_ROW))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        report = page.locator("#contractDocuments .contract-control")
        expect(report.locator(".contract-plan-total")).to_have_text(
            "На 04.02.2026: план 10 000 ₽, факт 5 500 ₽, отклонение −4 500 ₽ (−45 %)")
        state = report.locator(".contract-control-state")
        expect(state).to_have_text("Договор отстаёт от плана на 2 дня: столько дней назад план нарастающим итогом "
                                   "был равен сегодняшнему факту. Не выполнено по плану на дату среза: 4 500 ₽.")
        expect(report).to_contain_text("Срок договора в реестре не указан, поэтому прогноз сравнивается с окончанием "
                                       "графика действующей редакции — 05.02.2026.")
        threat = report.locator(".contract-control-forecast")
        expect(threat).to_have_text("Есть угроза сроку: если отставание сохранится, работы закончатся 06.02.2026 — "
                                    "на 1 день позже срока. Позже срока заканчиваются: "
                                    "1.2 Возведение стен 2-го этажа — 06.02.2026.")
        color = "e => getComputedStyle(e).color"
        assert threat.evaluate(color) == state.evaluate(color) != report.evaluate(color), "угроза выделена красным"
        expect(report).to_contain_text("Позиции расчёта без подтверждённой связи с графиком (2) в план и прогноз")
        expect(report).to_contain_text("не меняет прогноз срока ввода проекта")
        report.get_by_text("Отстают от плана (3)").click()
        rows = report.locator(".contract-control-behind tbody tr")
        expect(rows.nth(0)).to_contain_text("1.1 Возведение стен 1-го этажа")
        expect(rows.nth(0)).to_contain_text("3 дня")
        # На телефоне таблица становится карточками: у каждого числа видна его подпись.
        assert rows.nth(0).locator("td").nth(4).get_attribute("data-label") == "Отставание"
        expect(rows.nth(2)).to_contain_text("−1 500 ₽−37,5 %")
        expect(rows.nth(2)).to_contain_text("в натуре: 0,188 м3 из 0,5 м3 по плану")
        expect(rows.nth(2)).to_contain_text("06.02.2026")
        expect(report.locator(".contract-control-ahead")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
