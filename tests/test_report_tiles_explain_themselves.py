"""У каждой плитки управленческого отчёта — значок «i» с подсказкой.

Владелец, 02.11.2026, про плашки «Управленческий отчёт» на вкладке
«Результат»: «Можно ли пояснение методики сделать небольшой ссылкой на
значении в плашке? Типо I как инфо? Всплывающей подсказкой».

Утверждения:

  — тексты живут в одном словаре (`report_kpi_hints`), страница его читает,
    и каждый ключ, который называет страница или движок, в словаре есть;
  — параметры (ставка дисконтирования, порог покрытия) подставляются из
    расчёта, а не вписаны текстом;
  — на отрисованной странице значок стоит у каждой плитки, подсказка
    открывается наведением (1280 px) и нажатием (390 px, телефон), закрывается
    повторным нажатием и нажатием вне неё, и не выходит за край экрана;
  — проверка падает, если у плитки нет подсказки (контрпример в браузере).

Запуск: python3 -m pytest tests/test_report_tiles_explain_themselves.py -q
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402
from engine_source import engine_source  # noqa: E402
from report_kpi_hints import HINT_PARAMETERS, REPORT_KPI_HINTS  # noqa: E402

PORT = 18991


# --- словарь -------------------------------------------------------------------

def test_the_page_reads_the_dictionary_not_a_copy() -> None:
    assert "__DEVELOPAID_KPI_HINTS__" not in core.PAGE
    # Литерала подсказки в странице нет: текст приходит одним JSON словаря.
    sample = REPORT_KPI_HINTS["margin"]
    assert core.PAGE.count(sample) == 1


def test_every_text_uses_only_known_parameters() -> None:
    for key, text in REPORT_KPI_HINTS.items():
        for name in re.findall(r"\{(\w+)\}", text):
            assert name in HINT_PARAMETERS, f"{key}: неизвестный параметр {{{name}}}"


def test_the_discount_rate_is_not_written_into_the_text() -> None:
    """Ставка меняется человеком: число в тексте разошлось бы с расчётом."""
    for key in ("npv", "npv_hotel"):
        assert "{discount_rate}" in REPORT_KPI_HINTS[key]
        assert "20%" not in REPORT_KPI_HINTS[key]


def test_the_npv_hint_names_the_tax_shield() -> None:
    """Налог на прибыль в потоке проекта — тот, что платится с кредитом:
    проценты уменьшают базу. Подсказка обязана сказать это прямо."""
    assert "проценты его уменьшают" in REPORT_KPI_HINTS["npv"]


def test_every_tile_the_page_names_has_a_text() -> None:
    body = core.PAGE[core.PAGE.index("const reportKpis=["):]
    body = body[:body.index("reportKpi.innerHTML")]
    named = set(re.findall(r",'([a-z_]+)'(?:,|\])", body)) | {"npv", "npv_hotel"}
    assert named - set(REPORT_KPI_HINTS) == set()
    assert len(named) >= 11


def test_every_engine_tile_carries_a_known_hint() -> None:
    """Плитки объектов и гостиницы собирает движок; каждая несёт ключ."""
    source = engine_source()
    start = source.index("def report_layout(")
    block = source[start:source.index("    for tile in tiles:", start)]
    labels = re.findall(r'\{"label":', block) + re.findall(r'append\(\{"label":', block)
    hints = re.findall(r'"hint": "([a-z_]+)"', block)
    hints += [h for pair in re.findall(r'"hint": "([a-z_]+)" if sale else "([a-z_]+)"', block)
              for h in pair]
    assert hints and set(hints) <= set(REPORT_KPI_HINTS)
    assert block.count('{"label":') == block.count('"hint":'), labels


def _hotel() -> tuple[dict, dict]:
    import hotel_presets
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = core.PROJECT_KIND_HOTEL
    return hotel_presets.apply_preset(x, "hotel1"), t


def test_a_hotel_layout_has_a_hint_on_every_tile() -> None:
    x, t = _hotel()
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    layout = result["report"]["layout"]
    assert layout["nonres_tiles"], "у гостиницы нет плиток — проверять нечего"
    for tile in layout["nonres_tiles"]:
        assert tile.get("hint") in REPORT_KPI_HINTS, tile["label"]
    assert layout["npv_basis"] == "hotel"
    assert result["summary"]["discount_rate_pct"] == pytest.approx(
        float(x.get("discount_rate_pct", 20)))


def test_an_office_layout_has_a_hint_on_every_tile() -> None:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update(project_kind=core.PROJECT_KIND_NONRESIDENTIAL, offices_enabled=True,
             offices_gba_sqm=60000, offices_price_th=300, purchase_price_mln=500,
             offices_strategy="income")
    layout = core.calculate(core.CalcRequest(inputs=x, tep=t))["report"]["layout"]
    labels = {tile["label"] for tile in layout["nonres_tiles"]}
    assert {"Кредит объектов — пик", "Стабилизированный NOI, год"} <= labels
    for tile in layout["nonres_tiles"]:
        assert tile.get("hint") in REPORT_KPI_HINTS, tile["label"]
    assert layout["npv_basis"] == "project"


# --- на отрисованной странице ---------------------------------------------------

TILES = r"""() => [...document.querySelectorAll('#reportKpi .kpi')].map(k => {
  const b = k.querySelector('.kpi-i');
  const r = b ? b.getBoundingClientRect() : null;
  return {label: k.querySelector('span').textContent.trim(), has: !!b,
          text: b ? b.getAttribute('data-hint-text') : '',
          visible: !!r && r.width > 0 && r.height > 0};
})"""

TIP = r"""() => {
  const box = document.getElementById('kpiTip');
  if (!box || box.hidden) return {shown: false};
  const r = box.getBoundingClientRect();
  return {shown: true, text: box.textContent, left: r.left, right: r.right,
          top: r.top, bottom: r.bottom,
          vw: document.documentElement.clientWidth, vh: window.innerHeight};
}"""

OPEN_REPORT = r"""() => {
  const tab = document.querySelector('.tab[data-tab="report"]');
  openTab('report', tab);
}"""


def _inside(tip: dict) -> bool:
    return (tip["shown"] and tip["left"] >= 0 and tip["top"] >= 0
            and tip["right"] <= tip["vw"] and tip["bottom"] <= tip["vh"])


def _walk(page, tap: bool) -> dict:
    out: dict = {"tiles": page.evaluate(TILES), "opened": [], "closed_again": [],
                 "closed_outside": None}
    buttons = page.locator("#reportKpi .kpi .kpi-i")
    for i in range(buttons.count()):
        button = buttons.nth(i)
        button.scroll_into_view_if_needed()
        (button.tap() if tap else button.click())
        tip = page.evaluate(TIP)
        tip["expected"] = button.get_attribute("data-hint-text")
        out["opened"].append(tip)
        (button.tap() if tap else button.click())
        out["closed_again"].append(page.evaluate(TIP)["shown"])
    first = buttons.first
    first.scroll_into_view_if_needed()
    (first.tap() if tap else first.click())
    page.locator("#reportKpi .kpi span").first.click()
    out["closed_outside"] = page.evaluate(TIP)["shown"]
    return out


@pytest.fixture(scope="module")
def seen() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {"errors": []}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            desk = engine.new_page(viewport={"width": 1280, "height": 800})
            desk.on("pageerror", lambda e: out["errors"].append(str(e)))
            desk.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(desk)
            desk.evaluate(OPEN_REPORT)
            out["rate"] = desk.evaluate("() => kpiDiscountRate(lastResult)")
            out["desk"] = _walk(desk, tap=False)
            # Наведение мышью открывает, уход — закрывает.
            button = desk.locator("#reportKpi .kpi .kpi-i").nth(5)
            button.scroll_into_view_if_needed()
            button.hover()
            out["hover_open"] = desk.evaluate(TIP)
            desk.mouse.move(2, 2)
            out["hover_closed"] = desk.evaluate(TIP)["shown"]
            # Контрпример: текст плитки пропал из словаря — значка у неё нет,
            # и проверка видит это.
            desk.evaluate("() => { delete KPI_HINTS.llcr; renderResult(); }")
            out["broken"] = desk.evaluate(TILES)
            desk.close()

            phone_ctx = engine.new_context(viewport={"width": 390, "height": 844},
                                           is_mobile=True, has_touch=True)
            phone = phone_ctx.new_page()
            phone.on("pageerror", lambda e: out["errors"].append(str(e)))
            phone.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(phone)
            phone.evaluate(OPEN_REPORT)
            out["phone"] = _walk(phone, tap=True)
            phone_ctx.close()
    return out


def test_the_page_raises_no_errors(seen) -> None:
    assert seen["errors"] == []


@pytest.mark.parametrize("screen", ["desk", "phone"])
def test_every_tile_has_a_visible_icon(seen, screen) -> None:
    tiles = seen[screen]["tiles"]
    assert len(tiles) >= 10
    missing = [t["label"] for t in tiles if not (t["has"] and t["visible"] and t["text"])]
    assert missing == [], f"нет значка «i»: {missing}"


@pytest.mark.parametrize("screen", ["desk", "phone"])
def test_the_tip_opens_inside_the_screen(seen, screen) -> None:
    opened = seen[screen]["opened"]
    assert len(opened) == len(seen[screen]["tiles"])
    for tip in opened:
        assert tip["shown"], tip.get("expected")
        assert tip["text"] == tip["expected"]
        assert _inside(tip), tip


@pytest.mark.parametrize("screen", ["desk", "phone"])
def test_the_tip_closes_by_a_second_press_and_outside(seen, screen) -> None:
    assert not any(seen[screen]["closed_again"])
    assert seen[screen]["closed_outside"] is False


def test_the_mouse_opens_it_by_hovering(seen) -> None:
    assert seen["hover_open"]["shown"] and _inside(seen["hover_open"])
    assert seen["hover_closed"] is False


def test_the_rate_comes_from_the_calculation(seen) -> None:
    npv = next(t for t in seen["desk"]["tiles"] if t["label"].startswith("NPV @"))
    rate = f"{seen['rate']:g}".replace(".", ",")
    assert npv["label"] == f"NPV @{rate}%"
    assert f"по ставке {rate}% годовых" in npv["text"]
    llcr = next(t for t in seen["desk"]["tiles"] if t["label"].startswith("LLCR"))
    assert re.search(r"не ниже \d,\d\dx", llcr["text"]), llcr["text"]
    assert "{" not in "".join(t["text"] for t in seen["desk"]["tiles"])


def test_the_check_fails_without_a_hint(seen) -> None:
    """Подделка: без текста в словаре у LLCR нет значка — и это видно."""
    broken = [t["label"] for t in seen["broken"] if not t["has"]]
    assert broken == ["LLCR (расчётный)"]
