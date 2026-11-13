"""Строка таблицы «Договоры» показывает отставание, отклонение и прогноз по ГПР договора.

Решение владельца А: итог карточки виден в списке договоров, не открывая карточку. Числа строки —
те же, что в карточке (`listing`), а не второй расчёт. Документы и ведомость выдуманы: репозиторий
публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_monitor_contract_links as links
import developaid_monitor_contracts as contracts
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, PROJECT
from tests.test_contract_fact_prices_ks_by_the_edition import REGISTER_ROW, card  # noqa: F401

CUT = "2026-02-04"
EMPTY = "f" * 64
BEHIND = {"documents": 2, "note": "", "state": "behind", "lag_days": 2, "ahead_days": 0, "planned": 10000.0,
          "fact": 5500.0, "deviation": -4500.0, "percent": pytest.approx(-0.45), "readiness": 0.5,
          "plan_share": pytest.approx(10 / 11), "plan_done": pytest.approx(0.55), "overdue_days": 0, "overdue_works": 2,
          "auto": 0, "source": "ks6a", "preliminary": False, "finish": "2026-02-06", "deadline": "2026-02-05",
          "from_register": False, "done": False, "threat": True, "days_over": 1, "days_early": 0, "passed": False,
          # Две строки КС ведомости не сопоставлены с расчётом: отставание посчитано без них.
          "incomplete": True, "left_out": {"count": 2, "reasons": [
              "В расчёте позиция № 1.2 измеряется в «м3», а в КС — в «т»: объём не пересчитать в деньги.",
              "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9)."]}}


def _register():
    return {"rows": [dict(REGISTER_ROW), {"id": EMPTY, "contract": "Д-02", "physical_items": []}]}


def test_the_row_carries_the_card_numbers_and_says_why_they_are_missing(card):  # noqa: F811
    rows = files.register_control(PROJECT, _register(), CUT)["rows"]
    assert rows[0]["schedule_control"] == BEHIND
    # Тот же итог, что в карточке договора: строка таблицы читает карточку.
    own = files.listing(PROJECT, CONTRACT, CUT, fact.acts(REGISTER_ROW))["control"]
    assert (own["total"]["lag_days"], own["total"]["percent"], own["forecast"]["finish"]) == (2, pytest.approx(-0.45), "2026-02-06")
    assert rows[1]["schedule_control"]["documents"] == 0
    assert rows[1]["schedule_control"]["note"] == "ГПР и расчёт договора в карточку не загружены."
    # Подтверждения сняты: однозначные связи остаются в расчёте (правило 3), строка называет их число.
    listed = files.listing(PROJECT, CONTRACT, CUT)
    positions = next(d for d in listed["documents"] if d["sha256"] == card)["estimates"][0]["links"]["positions"]
    files.save_links(PROJECT, CONTRACT, card, 0, [{"index": p["index"]} for p in positions], clear=True, cut=CUT)
    got = files.register_control(PROJECT, _register(), CUT)["rows"][0]["schedule_control"]
    assert got["documents"] == 2 and got["note"] == "" and got["state"] == "behind" and got["auto"] > 0


def test_a_card_that_fails_keeps_the_register_and_names_the_failure(card, monkeypatch):  # noqa: F811
    real = files.listing

    def listing(project, contract_id, *args):
        if contract_id == EMPTY:
            raise OSError("disk")
        return real(project, contract_id, *args)
    monkeypatch.setattr(files, "listing", listing)
    rows = files.register_control(PROJECT, _register(), CUT)["rows"]
    assert rows[0]["schedule_control"] == BEHIND
    assert rows[1]["schedule_control"] == {"documents": None, "note": (
        "Отчёт по графику договора не построен: документы карточки не прочитаны. Откройте карточку договора "
        "и обновите её.")}
    bad = files.register_control(PROJECT, {"rows": [{"id": "x"}]}, CUT)["rows"][0]["schedule_control"]
    assert bad == {"documents": None, "note": "Выберите договор из списка."}


def test_the_register_view_of_the_monitor_brings_the_schedule_control(card, monkeypatch):  # noqa: F811
    import main as wrapper
    monkeypatch.setattr(contracts, "build", lambda project, cut: _register())
    monkeypatch.setattr(links, "enrich", lambda project, register, cut: register)
    got = wrapper.core._monitor_cumulative_execute("view", {"project": PROJECT, "cut": CUT})
    assert got["ok"] is True and got["register"]["rows"][0]["schedule_control"] == BEHIND


@pytest.mark.parametrize("width", [390, 1440])
def test_the_table_shows_lag_deviation_and_forecast_in_plain_words(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from contract_rows import opened
    from test_monitor_cumulative_controls import OTHER, browser_page
    with browser_page(width) as (page, responses, errors):
        shown = files.register_control(PROJECT, {"rows": [
            {"id": CONTRACT, **{k: v for k, v in REGISTER_ROW.items() if k != "id"}},
            {"id": OTHER, "physical_items": []}]}, CUT)["rows"]
        for row in responses.data["rows"]:
            row["schedule_control"] = next(x["schedule_control"] for x in shown if x["id"] == row["id"])
        page.locator("#contractsTab").click()
        row = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        # The short row: one chip with the lag, the deviation and the forecast in a few words.
        brief = row.locator(".contract-schedule")
        expect(brief).to_have_text("отстаёт на 2 дняготовность 50 %, выполнение плана 55 %просрочено работ: 2"
                                   "отставание неполное: 2 периода КС не вошли в фактпрогноз 06.02.2026, позже на 1 день")
        assert brief.get_attribute("data-label") == "График договора"
        head = page.locator(".contract-register thead th")
        expect(head).to_have_count(6)
        names = [" ".join(x.split()) for x in head.evaluate_all("hs => hs.map(h => h.textContent)")]
        assert names == ["Договор", "Сумма и выполнение", "Срок", "График договора", "Внимание", "Открыть"]
        color = "e => getComputedStyle(e).color"
        red = brief.locator(".contract-risk").evaluate(color)
        assert brief.locator(".contract-sub").nth(1).evaluate(color) == brief.locator(".contract-sub").first.evaluate(
            color) != row.evaluate(color)
        # The detail keeps the full answer of the card.
        more = opened(page, CONTRACT)
        lag = more.locator(".contract-schedule-lag")
        expect(lag).to_have_text("Отставание по ГПР договора2 дняотставание от планаПросрочено работ: 2."
                                 "Отставание неполное. 2 периода КС "
                                 "не вошли в факт: В расчёте позиция № 1.2 измеряется в «м3», а в КС — в «т»: объём "
                                 "не пересчитать в деньги. В расчёте нет позиции с этим номером или с таким же "
                                 "названием и единицей (№ 9.9).")
        assert lag.get_attribute("data-label") == "Отставание по ГПР договора"
        expect(more.locator(".contract-schedule-deviation")).to_have_text(
            "Готовность и выполнение плана50 %готовность договоравыполнение плана на дату среза — 55 %"
            "отклонение −45 % · −4 500 ₽план 10 000 ₽ · факт 5 500 ₽")
        forecast = more.locator(".contract-schedule-forecast")
        expect(forecast).to_have_text("Прогноз окончания по ГПР06.02.2026на 1 день позже срокаОкончание плана по ГПР: 05.02.2026")
        assert forecast.locator(".contract-main-money").evaluate(color) == lag.locator(".contract-main-money").evaluate(
            color) != row.evaluate(color)
        assert red != row.evaluate(color)
        other = page.locator(f'tr[data-contract-id="{OTHER}"]')
        expect(other.locator(".contract-schedule")).to_have_text("ГПР не загружен")
        assert other.locator(".contract-schedule .contract-risk").get_attribute("title") == (
            "ГПР и расчёт договора в карточку не загружены.")
        more = opened(page, OTHER)
        expect(more.locator(".contract-schedule-lag")).to_have_text(
            "Отставание по ГПР договора—ГПР и расчёт договора в карточку не загружены.")
        expect(more.locator(".contract-schedule-forecast")).to_have_text("Прогноз окончания по ГПР—")
        assert errors == []
