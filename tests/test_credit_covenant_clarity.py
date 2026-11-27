"""Синтетические проверки подписей и границы теста до первого раскрытия."""
from __future__ import annotations

import datetime

import pytest

import credit_repayment_fixture as fx
import developaid_credit_repayment as credit


def _inputs(balance=132.0, when="2027-09-30", *, partial=False):
    items = [{"date": when, "amount": 20.0 if partial else None,
              "confirmed": False, "final": not partial}]
    if partial:
        items.append({"date": "2028-03-31", "amount": None,
                      "confirmed": False, "final": True})
    return fx.inputs({
        "escrow": {"balance": balance}, "contracts": {"payments": []},
        "sales": {"payments": []}, "refunds": {"payments": []},
        "disclosure": {"items": items},
        "business_plan": {"escrow": [{"date": day, "amount": 100.0} for day in (
            "2026-12-31", "2027-03-31", "2027-06-30", "2027-09-30", "2027-12-31")],
            "ddu": []}})


@pytest.mark.parametrize(("when", "last"), [
    ("2027-09-29", "2027-06-30"),
    ("2027-09-30", "2027-06-30"),
    ("2027-10-01", "2027-09-30"),
])
@pytest.mark.parametrize("partial", [False, True])
def test_only_test_dates_strictly_before_first_disclosure_apply(when, last, partial):
    got = credit.forecast(_inputs(when=when, partial=partial))
    check = got["covenants"][0]
    assert check["items"][-1]["date"] == last
    assert all(item["date"] < when for item in check["items"])
    assert check["state"] == "ok"
    # The post-disclosure zero/partial balance remains in the cash forecast.
    event = next(e for e in got["escrow"]["events"] if e["kind"] == "disclosure")
    assert event["date"] == when
    assert event["balance_after"] == pytest.approx((112 if partial else 0) * credit.M)


def test_weekend_test_dates_keep_the_existing_calendar_and_plan_lookup():
    assert credit._test_days(datetime.date(2028, 9, 1), datetime.date(2028, 9, 30)) == [
        datetime.date(2028, 9, 29)]
    # Do not extend this change into selecting a different business-plan point.
    assert credit._test_days(datetime.date(2028, 9, 1), datetime.date(2028, 9, 29)) == []


@pytest.mark.parametrize(("balance", "label", "breach"), [
    (132.0, "опережение 32 %", False),
    (100.0, "по плану", False),
    (80.0, "отставание 20 %", False),
    (75.0, "отставание 25 %", True),
    (0.0, "отставание 100 %", True),
])
def test_direction_labels_do_not_change_the_shortfall_threshold(balance, label, breach):
    inputs = _inputs(balance)
    got = credit.forecast(inputs)
    check = got["covenants"][0]
    assert check["items"][0]["gap"] == pytest.approx(1 - balance / 100)
    assert check["items"][0]["breach"] is breach
    body = credit._covenants_html({"base": got})
    assert label in body and "отставание -" not in body
    assert "Проверки по кредитным договорам — базовый сценарий" in body
    assert "Источник плана: проверочные данные." in body


def test_missing_history_and_zero_plan_do_not_become_a_zero_actual_or_ahead():
    inputs = _inputs()
    inputs["datasets"]["business_plan"]["data"]["escrow"] = [
        {"date": "2025-12-31", "amount": 100 * credit.M},
        {"date": "2026-03-31", "amount": 100 * credit.M},
        {"date": "2026-12-31", "amount": 0.0}]
    inputs["datasets"]["escrow"]["data"]["history"] = [
        {"date": "2025-12-31", "amount": 0.0}]
    got = credit.forecast(inputs)
    items = {item["date"]: item for item in got["covenants"][0]["items"]}
    assert items["2025-12-31"]["actual"] == 0.0
    assert items["2025-12-31"]["breach"] is True
    assert items["2026-03-31"]["actual"] is None
    assert items["2026-03-31"]["gap"] is None
    assert items["2026-03-31"]["breach"] is None
    assert items["2026-12-31"]["gap"] is None
    body = credit._covenants_html({"base": got})
    assert f"31.03.2026: план {credit.mln(100 * credit.M)}, факт нет данных;" in body
    assert "опережение" not in body.split("<table", 1)[1]


def test_scenario_dates_are_rendered_from_events_with_the_original_source():
    inputs = _inputs(partial=True)
    inputs["datasets"]["disclosure"]["source"] = "срок ввода — утверждённый <срок>; допущение"
    got = credit.analyse(inputs)
    body = credit.render_html(got, monitor=True)
    assert "<td>Даты раскрытия эскроу</td><td>30.09.2027; 31.03.2028</td>" in body
    assert "<td>30.12.2027; 30.06.2028</td>" in body
    assert "раскрытие позже на 3 мес." in body
    assert "срок ввода — утверждённый &lt;срок&gt;; допущение" in body
    assert "<th>Базовый сценарий</th><th>Стрессовый сценарий</th>" in body
    assert "<td>Дефицит за прогноз, млн ₽</td>" in body
    assert "credit-covenants" not in credit.render_html(got)


def test_unknown_disclosure_does_not_display_a_guessed_date():
    inputs = _inputs()
    inputs["datasets"].pop("disclosure")
    got = credit.analyse(inputs)
    assert "<td>Даты раскрытия эскроу</td><td>нет данных</td><td>нет данных</td>" in (
        credit.render_html(got))


@pytest.mark.parametrize("width", [1280, 390])
def test_native_monitor_reaches_the_covenant_explanation_by_scrolling(width):
    from browser import chromium_or_skip
    from main import core
    from playwright.sync_api import sync_playwright

    result = credit.analyse(_inputs())
    answer = {"state": "ok", "status": result["status"],
              "html": credit.render_html(result, monitor=True)}
    chrome = chromium_or_skip()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.route("**/*", lambda route: route.abort())
            page.route("http://plato.test/monitor", lambda route: route.fulfill(
                body=core.MONITOR_PAGE_HTML, content_type="text/html"))
            page.goto("http://plato.test/monitor")
            page.evaluate("localStorage.setItem(ADMIN_KEY, 'synthetic-key'); syncAuthUi()")
            page.evaluate("answer => {selectMonitorTab('money'); drawCredit(answer)}", answer)
            wrapper = page.locator(".credit-covenants-scroll")
            header = wrapper.locator("th").last
            header.scroll_into_view_if_needed()
            # Start from the left edge, then use native horizontal wheel input.
            wrapper.evaluate("el => el.scrollLeft = 0")
            if width == 390:
                assert wrapper.evaluate("el => el.scrollWidth > el.clientWidth")
                wrapper.hover(position={"x": 30, "y": 15})
                page.mouse.wheel(1200, 0)
                page.wait_for_function("document.querySelector('.credit-covenants-scroll').scrollLeft > 0")
            bounds = wrapper.bounding_box()
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
            for index in (2, 3):
                cell = wrapper.locator("th").nth(index)
                assert cell.evaluate("el => {const r=el.getBoundingClientRect(); return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el}")
            assert "опережение 32 %" in wrapper.inner_text()
            assert "30.09.2027" in page.locator(".credit-comparison-scroll").inner_text()
            assert "30.12.2027" in page.locator(".credit-comparison-scroll").inner_text()
        finally:
            browser.close()
