"""Результаты проекта без жилья — без жилых таблиц на отрисованной странице.

Владелец (10.10.2026): «в разделе результаты у нежилья типа офисов и
гостиницы остаётся масса таблиц и полей, которые не работают, если нет
жилья». Рамку выбирает движок (`report_kind`): жильё, объект, гостиница.
Здесь — то, что страница печатала мимо рамки:

* нежилой проект с объектом по ДДУ (умолчание стратегии) уходил в жилой
  отчёт целиком;
* вкладка «Календарь» рисовала жилой календарь — «Старт продаж», «РВЭ», у
  гостиницы «Строительство ЖК» и «БРИДЖ»;
* вкладка «Финансирование» — «Маржа основных продуктов» нулём, у гостиницы
  нулевые строки маржи офиса и ТЦ, помесячная таблица БРИДЖа и ПФ нулями;
* карточка решения говорила «кредит гасится выручкой продаж» там, где
  причина другая (её называет движок, `debt_metric.reason`);
* форма чувствительности, построенная до смены типа, держала жилой LLCR.

Жилой проект — по-прежнему. Каждая проверка падает на прежнем коде.

Запуск: python3 -m pytest tests/test_nonres_results_have_no_housing.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402

core = wrapper.core

PORT = 18997

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

READ = r"""() => {
  const seen = el => el && el.offsetParent !== null;
  // innerText — только видимое: скрытые карточки (`hidden`) в него не входят.
  // Заголовки карточек страница пишет прописными (CSS) — сравнение без регистра.
  const text = id => { openTab(id, null); return document.getElementById(id).innerText.toLowerCase(); };
  const finance = text('finance'), calendar = text('calendar');
  openTab('report', null);
  const sections = [...document.querySelectorAll('#report .report-section')].filter(seen)
    .map(s => s.querySelector('.report-section-title').textContent.trim());
  const verdict = document.getElementById('iaVerdictLead');
  const grid = document.getElementById('iaVerdictGrid');
  return {finance, calendar, sections,
          kind: lastResult.report.layout.kind,
          verdict: (verdict ? verdict.textContent : '') + '\n' + (grid ? grid.textContent : ''),
          reason: (lastResult.report.layout.debt_metric || {}).reason || ''};
}"""

SENS = r"""async () => {
  openTab('sensitivity', null);
  await renderSensitivityForm();
  return [...document.querySelectorAll('#sensMetric option')].map(o => o.value);
}"""

HOUSING_CALENDAR = ("старт продаж", "рвэ", "строительство жк")


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser
    import main_registry

    path = browser.chromium_or_skip()
    out: dict = {}
    # Карточка решения — слой IA (корень, `main_registry`), как у человека.
    with browser.serve(main_registry.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            def fresh():
                page = engine.new_page(viewport={"width": 1440, "height": 900})
                page.on("pageerror", lambda e: out.setdefault("errors", []).append(str(e)))
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
                return page

            page = fresh()
            out["housing"] = page.evaluate(READ)
            out["sens_housing"] = page.evaluate(SENS)
            # Офис по ДДУ — умолчание стратегии объекта.
            page.evaluate(SET, ["offices_enabled", True])
            page.wait_for_function("() => lastResult && lastResult.revenue.offices > 0")
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            page.wait_for_function("() => lastResult.report.layout.kind !== 'housing'"
                                   " || lastResult.report.layout.project_finance === false")
            page.wait_for_timeout(500)
            out["office_ddu"] = page.evaluate(READ)
            # Та же страница, тип уже сменён: форма чувствительности, открытая
            # на жилье, обязана перестроиться.
            page.evaluate(SET, ["offices_strategy", "income"])
            page.wait_for_function("() => lastResult.report.layout.project_finance === false")
            page.wait_for_timeout(500)
            out["office_income"] = page.evaluate(READ)
            out["sens_office"] = page.evaluate(
                "() => [...document.querySelectorAll('#sensMetric option')].map(o => o.value)")
            # Аренда без кредита: показателя покрытия нет, причину называет движок.
            page.evaluate(SET, ["offices_loan_share_pct", 0])
            page.wait_for_function("() => !(lastResult.report.layout.debt_metric || {}).key")
            page.evaluate("() => openTab('report', document.querySelector('[data-tab=report]'))")
            page.wait_for_function("() => document.getElementById('iaVerdictLead')")
            page.wait_for_timeout(500)
            out["office_no_loan"] = page.evaluate(READ)
            page.close()

            page = fresh()
            page.evaluate("() => { applyProjectKind('hotel'); closeProjectKindDialog(); }")
            page.wait_for_function("() => lastResult.report && lastResult.report.hotel")
            page.evaluate(
                "() => document.querySelector('.hotel-preset[data-preset=hotel1] button').click()")
            page.wait_for_function(
                "() => lastResult.report.object_report && lastResult.report.object_report.hotel"
                " && lastResult.report.hotel.computed")
            page.wait_for_timeout(500)
            out["hotel"] = page.evaluate(READ)
            page.close()
    return out


def test_a_nonresidential_project_with_ddu_reads_as_an_object(walk) -> None:
    state = walk["office_ddu"]
    assert state["kind"] == "object"
    assert state["sections"][:3] == ["Решение", "Объект и участок", "Стратегия реализации"]
    assert "Удельная экономика" not in state["sections"]


def test_the_calendar_tab_has_no_housing_milestones(walk) -> None:
    for name in ("office_ddu", "office_income", "hotel"):
        calendar = walk[name]["calendar"]
        for word in HOUSING_CALENDAR:
            assert word not in calendar, (name, word)
    assert "бридж" not in walk["hotel"]["calendar"]
    # Жилой проект — по-прежнему.
    for word in HOUSING_CALENDAR:
        assert word in walk["housing"]["calendar"], word


def test_the_finance_tab_has_no_housing_zeros(walk) -> None:
    for name in ("office_income", "hotel"):
        finance = walk[name]["finance"]
        assert "маржа основных продуктов" not in finance, name
        assert "помесячное финансирование" not in finance, name
        assert "не ранее рвэ" not in finance, name
    assert "маржа мфоц" not in walk["hotel"]["finance"]
    assert "маржа тц" not in walk["hotel"]["finance"]
    housing = walk["housing"]["finance"]
    assert "маржа основных продуктов" in housing and "помесячное финансирование" in housing


def test_the_verdict_names_the_engine_reason(walk) -> None:
    state = walk["office_no_loan"]
    assert "нет кредита" in state["reason"]
    assert state["reason"] in state["verdict"]
    assert "гасится выручкой продаж" not in state["verdict"]


def test_the_sensitivity_form_follows_the_project_kind(walk) -> None:
    assert "llcr" in walk["sens_housing"]
    assert "llcr" not in walk["sens_office"]


def test_the_page_raised_no_errors(walk) -> None:
    assert walk.get("errors", []) == []
