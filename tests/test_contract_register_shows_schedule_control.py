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
          "fact": 5500.0, "deviation": -4500.0, "percent": -0.45, "finish": "2026-02-06", "deadline": "2026-02-05",
          "from_register": False, "done": False, "threat": True, "days_over": 1, "days_early": 0, "passed": False}


def _register():
    return {"rows": [dict(REGISTER_ROW), {"id": EMPTY, "contract": "Д-02", "physical_items": []}]}


def test_the_row_carries_the_card_numbers_and_says_why_they_are_missing(card):  # noqa: F811
    rows = files.register_control(PROJECT, _register(), CUT)["rows"]
    assert rows[0]["schedule_control"] == BEHIND
    # Тот же итог, что в карточке договора: строка таблицы читает карточку.
    own = files.listing(PROJECT, CONTRACT, CUT, fact.acts(REGISTER_ROW))["control"]
    assert (own["total"]["lag_days"], own["total"]["percent"], own["forecast"]["finish"]) == (2, -0.45, "2026-02-06")
    assert rows[1]["schedule_control"]["documents"] == 0
    assert rows[1]["schedule_control"]["note"] == "ГПР и расчёт договора в карточку не загружены."
    # Документы есть, но связи не подтверждены: причина карточки, а не «не загружены».
    listed = files.listing(PROJECT, CONTRACT, CUT)
    positions = next(d for d in listed["documents"] if d["sha256"] == card)["estimates"][0]["links"]["positions"]
    files.save_links(PROJECT, CONTRACT, card, 0, [{"index": p["index"]} for p in positions], clear=True, cut=CUT)
    got = files.register_control(PROJECT, _register(), CUT)["rows"][0]["schedule_control"]
    assert got["documents"] == 2 and got["state"] is None
    assert got["note"] == "Отклонение не рассчитано: в плане нет ни одной строки с подтверждённой связью."


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

    from test_monitor_cumulative_controls import OTHER, browser_page
    with browser_page(width) as (page, responses, errors):
        shown = files.register_control(PROJECT, {"rows": [
            {"id": CONTRACT, **{k: v for k, v in REGISTER_ROW.items() if k != "id"}},
            {"id": OTHER, "physical_items": []}]}, CUT)["rows"]
        for row in responses.data["rows"]:
            row["schedule_control"] = next(x["schedule_control"] for x in shown if x["id"] == row["id"])
        page.locator("#contractsTab").click()
        row = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        lag = row.locator(".contract-schedule-lag")
        expect(lag).to_have_text("2 дняотставание от плана")
        assert lag.get_attribute("data-label") == "Отставание по ГПР договора"
        if width > 900:
            head = page.locator(".contract-register thead th")
            names = [" ".join(x.split()) for x in head.evaluate_all("hs => hs.map(h => h.innerText)")]
            assert names[5:9] == ["Срок договора", "Отставание по ГПР договора", "Отклонение от плана",
                                  "Прогноз окончания по ГПР"]
        expect(row.locator(".contract-schedule-deviation")).to_have_text(
            "−45 %−4 500 ₽план 10 000 ₽ · факт 5 500 ₽")
        forecast = row.locator(".contract-schedule-forecast")
        expect(forecast).to_have_text("06.02.2026на 1 день позже срокаОкончание ГПР: 05.02.2026")
        color = "e => getComputedStyle(e).color"
        red = lag.locator(".risktext").evaluate(color)
        assert forecast.locator(".contract-main-money").evaluate(color) == red != row.evaluate(color)
        other = page.locator(f'tr[data-contract-id="{OTHER}"]')
        expect(other.locator(".contract-schedule-lag")).to_have_text(
            "—ГПР и расчёт договора в карточку не загружены.")
        expect(other.locator(".contract-schedule-forecast")).to_have_text("—")
        assert errors == []
