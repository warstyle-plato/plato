"""Темп продаж: средние с начала продаж пунктиром поверх месячных значений.

Владелец (02.11.2026): «Может добавить скользящую среднюю с момента начала
продаж?» Решение: две нарастающие линии — средний темп в месяц (всё продано
с первого договора / число месяцев, месяц без продаж — в знаменателе) и
средняя цена квартир (сумма договоров квартир / их метры, средневзвешенная).
Одна функция `contracting.pace_since_start` — её читают график, пояснение
под ним и строка Telegram-версии. Данные — синтетика.

Запуск: python3 -m pytest tests/test_report_sales_pace_average.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_analytics import _full  # noqa: E402

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402
from market_search import contracting  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _month(key: str, flats_area: float, flats_amount: float, units: float,
           parking_amount: float = 0.0) -> dict:
    """Месяц динамики в форме `contracting.summarise`."""
    by_product = {"Квартира": {"units": units, "area": flats_area, "amount": flats_amount,
                               "price": flats_amount / flats_area if flats_area else None}}
    if parking_amount:
        by_product["Машиноместо"] = {"units": 1.0, "area": 0.0, "amount": parking_amount}
    return {"month": key, "by_product": by_product, "units": units + bool(parking_amount),
            "area": flats_area, "amount": flats_amount + parking_amount,
            "price_flats": by_product["Квартира"]["price"]}


# Январь: 100 м² по 300 тыс.; февраль — ни одного договора; март: 300 м² по
# 200 тыс. и машино-место за 2 млн (в цену квартир не входит); апрель пуст.
DYNAMICS = [
    _month("2026-01", 100.0, 30e6, 2.0),
    _month("2026-03", 300.0, 60e6, 5.0, parking_amount=2e6),
]


def _check(rows: list[dict]) -> None:
    by = {row["month"]: row for row in rows}
    assert list(by) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    # Пустой месяц — строка с нулём и в знаменателе темпа.
    assert by["2026-02"]["area"] == 0.0 and by["2026-02"]["avg_area"] == pytest.approx(50.0)
    assert by["2026-03"]["avg_area"] == pytest.approx(400 / 3)
    assert by["2026-04"]["avg_area"] == pytest.approx(100.0)
    assert by["2026-04"]["avg_units"] == pytest.approx(8 / 4)
    assert by["2026-04"]["avg_amount"] == pytest.approx(92e6 / 4)
    # Средневзвешенная цена: 90 млн / 400 м² = 225 тыс., а не (300 + 200) / 2.
    assert by["2026-02"]["avg_price_flats"] == pytest.approx(300e3)
    assert by["2026-04"]["avg_price_flats"] == pytest.approx(225e3)
    assert by["2026-04"]["months_since_start"] == 4


def test_averages_count_empty_months_and_weight_the_price():
    _check(contracting.pace_since_start(DYNAMICS, "2026-04"))
    # После конца периода — не считается; до первого договора — нет строк.
    assert contracting.pace_since_start(DYNAMICS, "2025-12") == []
    assert contracting.pace_since_start([], "2026-04") == []


def _skipping_empty_months(dynamics, until):
    rows = contracting.pace_since_start(dynamics, until)
    kept = [row for row in rows if row["units"]]
    for count, row in enumerate(kept, 1):
        row["avg_area"] = sum(r["area"] for r in kept[:count]) / count
    return kept


def _mean_of_monthly_prices(dynamics, until):
    rows = contracting.pace_since_start(dynamics, until)
    seen = []
    for row in rows:
        if row["price_flats"]:
            seen.append(row["price_flats"])
        row["avg_price_flats"] = sum(seen) / len(seen) if seen else None
    return rows


@pytest.mark.parametrize("fake", [_skipping_empty_months, _mean_of_monthly_prices])
def test_the_check_fails_on_a_fake(fake):
    with pytest.raises(AssertionError):
        _check(fake(DYNAMICS, "2026-04"))


def _built_with(rows: list[dict]) -> dict:
    built = _full()
    built["sales"]["pace"] = rows
    return built


def test_the_report_reads_the_one_function():
    built = _full()
    pace = built["sales"]["pace"]
    assert pace and all("avg_area" in row and "avg_price_flats" in row for row in pace)
    # Сводка показывает последние 12 месяцев, но средние — с первого договора.
    assert pace[-1]["months_since_start"] >= len(pace)
    if pace[-1]["months_since_start"] == len(pace):
        assert pace[-1]["avg_area"] == pytest.approx(sum(r["area"] for r in pace) / len(pace))
    built["sales"]["pace"] = contracting.pace_since_start(DYNAMICS, "2026-04")
    text = report.render_text(built)
    assert ("С начала продаж (01.26, месяцев: 4) в среднем в месяц: 100 м², лотов — 2,0, "
            "на 23,0 млн ₽; средняя цена квартир — 225 000 ₽ за м².") in text


SVG = """() => [...document.querySelectorAll('.switch-charts .pane')]
    .filter(p => p.getBoundingClientRect().height > 0).map(p => ({
        pane: p.dataset.pane,
        lines: [...p.querySelectorAll('path.average')].map(e => ({
            name: e.getAttribute('aria-label'), axis: e.dataset.axis,
            dash: getComputedStyle(e).strokeDasharray,
            shown: e.getBoundingClientRect().width > 0})),
        values: [...p.querySelectorAll('text.average-value')].map(e => e.textContent),
        legend: [...p.querySelectorAll('svg text')].map(e => e.textContent),
    }))"""


def test_the_rendered_page_draws_dashed_averages_with_one_label_each():
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    body = report.render_html(_built_with(contracting.pace_since_start(DYNAMICS, "2026-04")))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1100, "height": 900})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }", body)
            [area] = tab.evaluate(SVG)
            assert area["pane"] == "area"
            assert [(x["name"], x["axis"]) for x in area["lines"]] == [
                ("Средний темп с начала продаж", "left"), ("Средняя цена с начала продаж", "right")]
            assert all(x["shown"] and x["dash"] not in ("", "none") for x in area["lines"])
            # Подпись — только у последней точки: 100 м² в месяц и 225 тыс. ₽/м².
            assert sorted(area["values"]) == ["100", "225"]
            assert "Средний темп с начала продаж" in area["legend"]
            assert "Средняя цена с начала продаж" in area["legend"]
            tab.click("#reportBox .switch-charts .switch button[data-pane='amount']")
            [amount] = tab.evaluate(SVG)
            assert sorted(amount["values"]) == ["225", "23,0"]
            note = tab.inner_text("#reportBox .pace-average")
            assert "с начала продаж (01.26, месяцев: 4)" in note
            assert "месяцы без договоров тоже считаются" in note
        finally:
            browser.close()
