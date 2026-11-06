"""«Сравнение стратегий»: пояснения — в подсказках «i», на виду — числа и вывод.

Владелец, 02.11.2026, после значков «i» у плиток отчёта (PR #986): «Может
быть в пояснение стратегий тоже сделать сноску I?».

Утверждения:
  — у каждой стратегии (столбца), каждой строки таблицы, заголовка точек и
    подписи блока есть ключ подсказки, и текст под ним есть в одном словаре
    `report_kpi_hints` (второго словаря и второго значка нет);
  — длинные пояснения в подписях строк ушли в подсказку только на странице:
    полная подпись (`label`) остаётся для PDF, числа и вывод не меняются;
  — на отрисованной странице (1280 px — мышью, 390 px — пальцем) значок стоит
    у каждой стратегии и строки, подсказка открывается, не выходит за край
    экрана и закрывается повторным нажатием;
  — проверка падает, если у строки нет подсказки (контрпример в браузере).

Запуск: python3 -m pytest tests/test_strategies_explain_themselves.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402
from report_kpi_hints import REPORT_KPI_HINTS  # noqa: E402
from test_an_office_shows_sale_and_rent_side_by_side import _spec  # noqa: E402
from test_strategies_are_compared_everywhere import _retail_spec  # noqa: E402

PORT = 18993


def _keys(block: dict) -> list[str]:
    out = [block["stamp_hint"]]
    for item in block["items"]:
        out += [c["hint"] for c in item["columns"]] + [r["hint"] for r in item["rows"]]
        out.append(item["points_hint"])
    return out


@pytest.fixture(scope="module")
def office_block() -> dict:
    x, t = _spec(offices_strategy=ns.STRATEGY_DIRECT)
    return core.strategy_compare_block(core._run_authoritative_model(x, t, [], {})["consolidated"], None)


# --- блок движка ----------------------------------------------------------------

def test_every_strategy_and_row_names_a_known_text(office_block) -> None:
    keys = _keys(office_block)
    assert all(keys) and set(keys) <= set(REPORT_KPI_HINTS), set(keys) - set(REPORT_KPI_HINTS)
    columns = [c["key"] for c in office_block["items"][0]["columns"]]
    assert {"ddu", "presale", "direct"} <= set(columns) and len(columns) == 5


def test_the_retail_block_names_known_texts_too() -> None:
    x, t = _retail_spec()
    block = core.strategy_compare_block(core._run_authoritative_model(x, t, [], {})["consolidated"], None)
    assert block and set(_keys(block)) <= set(REPORT_KPI_HINTS)


def test_the_rent_columns_explain_their_own_exit(office_block) -> None:
    hints = {c["key"]: c["hint"] for c in office_block["items"][0]["columns"]}
    assert hints["income_hold"] == "strategy_income_hold"
    assert hints["income"] == "strategy_income_sale"


def test_the_page_labels_are_short_and_the_pdf_labels_stay(office_block) -> None:
    rows = {r["key"]: r for r in office_block["items"][0]["rows"]}
    assert rows["exit_value"]["page_label"] == "Стоимость здания для покупателя-инвестора"
    assert "(чистый доход / ставка капитализации)" in rows["exit_value"]["label"]
    # Ставка капитализации для сравнения — число, оно остаётся на виду.
    assert rows["yield_on_cost"]["page_label"].startswith("Доходность на затраты (для сравнения: ставка")
    assert "к затратам на создание" in rows["yield_on_cost"]["label"]


def test_the_page_stamp_is_short_and_keeps_a_failure_reason() -> None:
    assert core._strategy_page_stamp({"error": True, "reason": "нет памяти"}).endswith(
        "не подобраны: нет памяти.")
    assert "ещё подбираются" in core._strategy_page_stamp(None)


def test_the_rate_in_the_texts_is_a_parameter() -> None:
    for key in ("strategy_npv", "strategy_npv_equity"):
        assert "{discount_rate}" in REPORT_KPI_HINTS[key] and "20%" not in REPORT_KPI_HINTS[key]


def test_the_texts_are_plain_sentences() -> None:
    for key, text in REPORT_KPI_HINTS.items():
        if key.startswith("strategy_"):
            assert text.endswith(".") and len(text) > 60, key
            assert not re.search(r"\b(ПФ|РВЭ|ПДКП)\b", text), key


# --- на отрисованной странице ---------------------------------------------------

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

CARD = "#rsObj-decision [data-strategy-compare-card]"

SPOTS = r"""(card) => {
  const box = document.querySelector(card);
  const spot = (kind, name, el) => {
    const b = el && el.querySelector('.kpi-i');
    const r = b ? b.getBoundingClientRect() : null;
    return {kind, name, has: !!b, text: b ? b.getAttribute('data-hint-text') : '',
            sized: !!r && r.width > 0 && r.height > 0};
  };
  return [
    ...[...box.querySelectorAll('table.strategy-compare-table thead th[data-strategy]')]
      .map(th => spot('strategy', th.dataset.strategy, th)),
    ...[...box.querySelectorAll('table.strategy-compare-table tbody tr')]
      .map(tr => spot('row', tr.dataset.row, tr.cells[0])),
    spot('points', 'points', box.querySelector('.strategy-points-title')),
    spot('stamp', 'stamp', box.querySelector('.strategy-compare-stamp')),
  ];
}"""

TIP = r"""() => {
  const box = document.getElementById('kpiTip');
  if (!box || box.hidden) return {shown: false};
  const r = box.getBoundingClientRect();
  return {shown: true, text: box.textContent, left: r.left, right: r.right,
          top: r.top, bottom: r.bottom,
          vw: document.documentElement.clientWidth, vh: window.innerHeight};
}"""


def _inside(tip: dict) -> bool:
    return (tip["shown"] and tip["left"] >= 0 and tip["top"] >= 0
            and tip["right"] <= tip["vw"] and tip["bottom"] <= tip["vh"])


def _open_office(page, base: str) -> None:
    import browser

    page.goto(base, wait_until="domcontentloaded")
    browser.wait_for_result(page)
    page.evaluate(SET, ["offices_enabled", True])
    browser.wait_for_result(page)
    page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
    browser.wait_for_result(page)
    page.evaluate(SET, ["offices_strategy", "direct"])
    browser.wait_for_result(page)
    # Точки приходят отдельным запросом после расчёта — ждём их, чтобы
    # перерисовка блока не случилась посреди нажатий.
    page.wait_for_function(
        f"() => document.querySelectorAll('{CARD} .strategy-points li').length > 0", timeout=120_000)
    page.evaluate("() => openTab('report', document.querySelector('.tab[data-tab=\"report\"]'))")


def _walk(page, tap: bool) -> dict:
    out: dict = {"spots": page.evaluate(SPOTS, CARD), "opened": [], "closed_again": []}
    buttons = page.locator(f"{CARD} .kpi-i")
    for i in range(buttons.count()):
        button = buttons.nth(i)
        button.scroll_into_view_if_needed()
        (button.tap() if tap else button.click())
        tip = page.evaluate(TIP)
        tip["expected"] = button.get_attribute("data-hint-text")
        out["opened"].append(tip)
        (button.tap() if tap else button.click())
        out["closed_again"].append(page.evaluate(TIP)["shown"])
    return out


@pytest.fixture(scope="module")
def seen() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    out: dict = {"errors": []}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            desk = engine.new_page(viewport={"width": 1280, "height": 800})
            desk.on("pageerror", lambda e: out["errors"].append(str(e)))
            _open_office(desk, base)
            out["rate"] = desk.evaluate("() => kpiDiscountRate(lastResult)")
            out["desk"] = _walk(desk, tap=False)
            # Наведение мышью открывает подсказку стратегии.
            first = desk.locator(f"{CARD} thead .kpi-i").first
            first.scroll_into_view_if_needed()
            first.hover()
            out["hover_open"] = desk.evaluate(TIP)
            desk.mouse.move(2, 2)
            # Контрпример: текста строки NPV нет в словаре — значка у неё нет,
            # и проверка это видит.
            desk.evaluate("() => { delete KPI_HINTS.strategy_npv; paintStrategyCompare(strategyCompareBlock); }")
            out["broken"] = desk.evaluate(SPOTS, CARD)
            desk.close()

            phone_ctx = engine.new_context(viewport={"width": 390, "height": 844},
                                           is_mobile=True, has_touch=True)
            phone = phone_ctx.new_page()
            phone.on("pageerror", lambda e: out["errors"].append(str(e)))
            _open_office(phone, base)
            out["phone"] = _walk(phone, tap=True)
            phone_ctx.close()
    return out


def test_the_page_raises_no_errors(seen) -> None:
    assert seen["errors"] == []


@pytest.mark.parametrize("screen", ["desk", "phone"])
def test_every_strategy_and_row_has_an_icon(seen, screen) -> None:
    spots = seen[screen]["spots"]
    assert sum(s["kind"] == "strategy" for s in spots) == 5
    assert sum(s["kind"] == "row" for s in spots) >= 13
    missing = [f"{s['kind']}:{s['name']}" for s in spots if not (s["has"] and s["sized"] and s["text"])]
    assert missing == [], f"нет значка «i»: {missing}"


@pytest.mark.parametrize("screen", ["desk", "phone"])
def test_the_tip_opens_inside_the_screen(seen, screen) -> None:
    opened = seen[screen]["opened"]
    assert len(opened) == len(seen[screen]["spots"])
    for tip in opened:
        assert tip["shown"], tip.get("expected")
        assert tip["text"] == tip["expected"]
        assert _inside(tip), tip
    assert not any(seen[screen]["closed_again"])


def test_the_mouse_opens_it_by_hovering(seen) -> None:
    assert seen["hover_open"]["shown"] and _inside(seen["hover_open"])


def test_the_rate_comes_from_the_calculation(seen) -> None:
    rate = f"{seen['rate']:g}".replace(".", ",")
    npv = next(s for s in seen["desk"]["spots"] if s["name"] == "npv")
    assert f"по ставке {rate}% годовых" in npv["text"]
    assert "{" not in "".join(s["text"] for s in seen["desk"]["spots"])


def test_the_check_fails_without_a_hint(seen) -> None:
    """Подделка: без текста в словаре у строки NPV нет значка — и это видно."""
    broken = [s["name"] for s in seen["broken"] if not s["has"]]
    assert broken == ["npv"]
