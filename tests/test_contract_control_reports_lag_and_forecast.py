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
    """Fact lines (code, money, volumes[, last KS day, complete by volume])."""
    return {"note": "", "lines": [{"code": code, "fact": money, "volumes": volumes, "last": (rest or ["2026-03-05"])[0],
                                   "complete": rest[1] if len(rest) > 1 else False}
                                  for code, money, volumes, *rest in lines]}


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
    assert got["ahead"] == (["3.1"] if state == "ahead" else []) and got["done"] == (["3.1"] if state == "done" else [])
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
                               "finish": "2026-03-15", "done": False, "days_over": 1, "days_early": 0,
                               "threat": True, "drivers": ["3.2"], "outside": 0, "passed": False}
    assert got["behind"] == ["3.1"] and got["ahead"] == []
    calm = control.build(planned, _fact(("3.1", 500.0, [])), None, "", "2026-03-05")["forecast"]
    assert calm["deadline_label"] == "окончание графика действующей редакции" and not calm["threat"]
    assert calm["finish"] == "2026-03-15" and calm["days_over"] == 0 and calm["days_early"] == 0
    late = control.build(planned, _fact(("3.1", 300.0, [])), "2026-03-04", "Указан вручную", "2026-03-05")
    assert late["forecast"]["passed"] and not calm["passed"]


def test_a_plan_line_has_a_natural_volume_only_in_one_unit_with_known_quantities():
    import developaid_contract_plan as plan
    assert plan._volume([("м³", 10.0, 0.5), ("м3", 4.0, 1.0)]) == {"unit": "м³", "quantity": 9.0}
    assert plan._volume([("м3", 10.0, 0.5), ("т", 4.0, 1.0)]) is None
    assert plan._volume([("м3", 10.0, 0.5), ("м3", None, 1.0)]) is None and plan._volume([]) is None


@pytest.mark.parametrize("money, complete, finished, late, shortfall", [
    # Весь объём ведомости выполнен, но по цене расчёта вышло меньше стоимости строки: отставания нет.
    (900.0, True, "2026-03-14", 4, 100.0),
    (1000.0, False, "2026-03-08", -2, 0.0),
])
def test_a_finished_line_reports_its_last_ks_day_against_the_schedule_not_a_lag(
        money, complete, finished, late, shortfall):
    got = control.build(_plan("2026-03-20", LINE), _fact(("3.1", money, [], finished, complete)),
                        "2026-03-12", "Указан вручную", "2026-03-20")
    (line,) = got["lines"]
    assert (line["state"], line["lag_days"], line["finished"], line["late_days"], line["shortfall"],
            line["behind_amount"], line["forecast_finish"]) == ("done", 0, finished, late, shortfall, 0.0, None)
    assert got["done"] == ["3.1"] and got["behind"] == [] and got["ahead"] == []
    assert got["total"]["state"] == "done" and got["total"]["shortfall"] == shortfall
    forecast = got["forecast"]
    assert (forecast["done"], forecast["finish"], forecast["threat"], forecast["days_over"],
            forecast["days_early"], forecast["drivers"]) == (
        True, finished, late > 0, max((late - 2), 0), max(2 - late, 0), ["3.1"] if late > 2 else [])


def test_an_unfinished_line_with_a_finished_one_counts_the_finished_in_full():
    later = {**LINE, "code": "3.2", "start": "2026-03-11", "finish": "2026-03-20"}
    got = control.build(_plan("2026-03-15", LINE, later),
                        _fact(("3.1", 900.0, [], "2026-03-10", True), ("3.2", 500.0, [])), None, "", "2026-03-15")
    # План 1 500 ₽; 3.1 закончена — считается целиком: 1 000 + 500 = плану, договор идёт по плану.
    assert got["total"]["state"] == "on_plan" and got["total"]["deviation"] == -100.0
    assert got["forecast"]["done"] is False and got["forecast"]["finish"] == "2026-03-20"


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
                            "behind_amount": 4500.0, "shortfall": 0.0, "incomplete": True}
    # Плиты в «т» и кладка № 9.9 не сопоставлены с расчётом: в факт не вошли, и отчёт это называет.
    assert got["left_out"] == {"count": 2, "reasons": [
        "В расчёте позиция № 1.2 измеряется в «м3», а в КС — в «т»: объём не пересчитать в деньги.",
        "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9)."]}
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


FINISHED_ROW = {**ROW, "physical_items": [
    # Стены выполнены на весь объём ведомости; у плит вторая работа ещё не начата.
    _item("1.1", "Устройство стен", (0.5, 4000, "2026-02-01", "2026-02-03"), plan_quantity=0.5),
    _item("1.2.1", "Армирование плит", (0.5, 1500, "2026-02-01", "2026-02-02"), plan_quantity=0.5),
    {**_item("1.2.2", "Бетонирование плит"), "completed_quantity": 0.0, "plan_quantity": 0.5},
]}


def test_a_line_is_finished_when_the_statement_volume_of_all_its_positions_is_done(card):  # noqa: F811
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(FINISHED_ROW))
    assert [(r["code"], r["complete"]) for r in got["fact"]["lines"]] == [
        ("1.1", True), ("1.2", True), ("1.3", False)]
    rows = {r["code"]: r for r in got["control"]["lines"]}
    # 1.1 по соглашению должна была закончиться 01.02, закончена по КС 03.02; 1.2 — на 2 дня раньше графика.
    assert [(c, rows[c]["state"], rows[c]["finished"], rows[c]["late_days"], rows[c]["shortfall"])
            for c in ("1.1", "1.2")] == [("1.1", "done", "2026-02-03", 2, 1500.0),
                                         ("1.2", "done", "2026-02-03", -2, 2500.0)]
    assert rows["1.3"]["state"] == "behind" and got["control"]["done"] == ["1.1", "1.2"]
    # Без объёма ведомости работа законченной не считается: решает только стоимость.
    unknown = {**FINISHED_ROW, "physical_items": [
        {k: v for k, v in item.items() if k != "plan_quantity"} for item in FINISHED_ROW["physical_items"]]}
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(unknown))
    assert [r["complete"] for r in got["fact"]["lines"]] == [False, False, False]


def test_a_finished_line_ends_on_its_latest_ks_day_and_waits_for_every_linked_position(card):  # noqa: F811
    both = {**FINISHED_ROW, "physical_items": [
        *FINISHED_ROW["physical_items"][:2],
        _item("1.2.2", "Бетонирование плит", (0.5, 1500, "2026-02-01", "2026-02-01"), plan_quantity=0.5)]}
    lines = {r["code"]: r for r in files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(both))["fact"]["lines"]}
    assert (lines["1.3"]["complete"], lines["1.3"]["last"]) == (True, "2026-02-02")
    # Лестницы привязаны и к плитам, но работ по ним в ведомости нет: строка ещё не закончена.
    estimate = next(d for d in files.listing("Учебный", CONTRACT, "2026-02-04")["documents"]
                    if d["sha256"] == card)["estimates"][0]
    stairs = next(p["index"] for p in estimate["links"]["positions"] if p["number"] == "2.1")
    files.save_links("Учебный", CONTRACT, card, 0, [{"index": stairs, "lines": ["1.3"]}], cut="2026-02-04")
    lines = {r["code"]: r for r in files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(both))["fact"]["lines"]}
    assert lines["1.3"]["complete"] is False and lines["1.1"]["complete"] is True


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
            "На 04.02.2026: план 10 000 ₽, факт 5 500 ₽, отклонение −4 500 ₽ (−45 % от плана на дату среза)")
        expect(report.locator(".contract-control-left-out")).to_have_text(
            "2 периода КС не вошли в факт: В расчёте позиция № 1.2 измеряется в «м3», а в КС — в «т»: объём не "
            "пересчитать в деньги. В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9). "
            "Поэтому отставание и отклонение неполные: выполнение этих периодов в них не учтено.")
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
        expect(rows.nth(2)).to_contain_text("−1 500 ₽−37,5 % от плана на дату среза")
        expect(rows.nth(2)).to_contain_text("в натуре: 0,188 м3 из 0,5 м3 по плану")
        expect(rows.nth(2)).to_contain_text("06.02.2026")
        expect(report.locator(".contract-control-ahead")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []


@pytest.mark.parametrize("width", [390, 1440])
def test_a_finished_contract_says_when_its_work_ended_against_the_deadline(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    row = {**FINISHED_ROW, "deadline": "2026-02-02", "deadline_source": {"label": "Указан вручную"},
           "physical_items": FINISHED_ROW["physical_items"][:2]}
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(row))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        report = page.locator("#contractDocuments .contract-control")
        expect(report.locator(".contract-control-state")).to_have_text(
            "Все работы плана закончены. Стоимость выполненного по КС меньше расчёта на 5 500 ₽.")
        ended = report.locator(".contract-control-forecast")
        expect(ended).to_have_text("Работы закончены 03.02.2026 — на 1 день позже срока. Позже срока закончены: "
                                   "1.1 Возведение стен 1-го этажа — 03.02.2026; "
                                   "1.2 Возведение стен 2-го этажа — 03.02.2026.")
        assert "risktext" in ended.get_attribute("class")
        expect(report).not_to_contain_text("а работы не закончены")
        report.get_by_text("Закончены (3)").click()
        rows = report.locator(".contract-control-done tbody tr")
        expect(rows.nth(0)).to_contain_text("1.1 Возведение стен 1-го этажа")
        expect(rows.nth(0).locator("td").nth(3)).to_have_text("на 2 дня позже")
        assert "risktext" in rows.nth(0).locator("td").nth(3).get_attribute("class")
        assert rows.nth(0).locator("td").nth(2).get_attribute("data-label") == "Окончание по КС"
        expect(rows.nth(0)).to_contain_text("меньше расчёта на 1 500 ₽")
        expect(rows.nth(2).locator("td").nth(3)).to_have_text("на 2 дня раньше")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
