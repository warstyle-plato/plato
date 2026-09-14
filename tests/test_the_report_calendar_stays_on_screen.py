"""Календарь вкладки «Отчёт» прокручивается внутри блока, а не телом страницы.

Снимок владельца (13.09.2026): страница уехала далеко вправо, слева обрезано
всё содержимое, на экране одни кварталы 2030–2032. Замер: на ноутбуке 1440 px
ширина страницы была 3245 px, на телефоне 390 — 3229.

Причина не в самом календаре: он широкий законно (`min-width` считается как
`max(1150, 250 + кварталов×105)` — на семилетнем проекте это 3190 px), и на
вкладке «Календарь» это никому не мешает, потому что там он лежит в
`.gantt-wrap{overflow:auto}`. А на вкладке «Отчёт» контейнеру дали класс
`gantt` — то есть внутри `.gantt` рисовался ещё один `.gantt` со своим
`min-width`, и держать эту ширину было некому, кроме тела страницы. Та же
ошибка, что уже ловилась в торгах: широкое содержимое живёт в СВОЁМ окне
прокрутки, а тело страницы горизонтально не едет.

Второй виновник нашёлся тем же замером и рядом: `.legend` — flex-строка без
`flex-wrap`, и на телефоне она добавляла свои 84 px. Соседние легенды
(`.gantt-legend`, `.gantt-phase-legend`) переносятся с самого начала, то есть
исключением была именно эта.

И половина правки, без которой первая опаснее болезни: **на бумаге
`overflow:auto` не прокручивает, а ОБРЕЗАЕТ.** Вкладка «Календарь» в печати
скрыта, значит на лист идёт именно этот блок, и обрезанный план читался бы как
весь план — поэтому в печати обёртка размыкается, как `.scroll`.

Проверяется настоящим браузером: ширина — это поведение, и в исходнике
сломанная страница выглядит так же, как починенная. Рядом стоит проверка,
которая ЛОМАЕТ вёрстку нарочно, — сторож, не падающий на поломке, не сторож.

Запуск: python3 -m pytest tests/test_the_report_calendar_stays_on_screen.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

# Семилетний горизонт: столько кварталов даёт 3190 px сетки — вдвое шире
# ноутбука. На коротком проекте вылета не будет вовсе, и проверка не проверит
# ничего.
CALENDAR = {
    "start": "2026-01-01",
    "end": "2032-12-31",
    "events": [
        {"group": "Проект", "label": "ИРД", "start": "2026-01-01", "end": "2027-01-01"},
        {"group": "Проект", "label": "Строительство",
         "start": "2027-01-01", "end": "2031-06-01"},
        {"group": "Продажи", "label": "Продажи",
         "start": "2027-06-01", "end": "2032-06-01"},
        {"group": "Финансирование", "label": "РВЭ",
         "start": "2031-06-01", "end": "2031-06-01"},
    ],
}

PROBE = """(cal)=>{
  openTab('report');
  const el=document.getElementById('reportCalendarGantt');
  const read=()=>{
    renderGantt('reportCalendarGantt', cal);
    const inner=el.querySelector('.gantt');
    return {
      page: document.documentElement.scrollWidth,
      screen: document.documentElement.clientWidth,
      boxScroll: el.scrollWidth,
      boxWidth: Math.round(el.getBoundingClientRect().width),
      inner: inner ? Math.round(inner.getBoundingClientRect().width) : 0,
      overflowX: getComputedStyle(el).overflowX,
    };
  };
  const now = read();
  el.className = 'gantt';          // как было до правки
  const broken = read();
  el.className = 'gantt-wrap';
  return {now, broken};
}"""


@pytest.fixture(scope="module")
def probe():
    """Замер на настоящей странице по настоящему адресу, по одному на ширину."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    seen: dict[int, dict] = {}
    with browser.serve(core.app, 18101) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for width in (1440, 390):
                page = engine.new_page(viewport={"width": width, "height": 900})
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                seen[width] = page.evaluate(PROBE, CALENDAR)
                page.close()
    return seen


@pytest.mark.parametrize("width", (1440, 390))
def test_the_page_does_not_ride_sideways(probe, width):
    got = probe[width]["now"]
    assert got["page"] <= got["screen"] + 1, (
        f"на {width} px страница шириной {got['page']} — тело едет вбок на "
        f"{got['page'] - got['screen']} px")


@pytest.mark.parametrize("width", (1440, 390))
def test_the_calendar_scrolls_inside_its_own_box(probe, width):
    got = probe[width]["now"]
    assert got["overflowX"] in ("auto", "scroll"), \
        f"у блока календаря overflow-x={got['overflowX']} — прокручивать нечем"
    assert got["boxScroll"] > got["boxWidth"] + 1, (
        "сетка уместилась в блок — проверка не проверяет ничего: "
        f"прокрутка {got['boxScroll']} при блоке {got['boxWidth']}")


@pytest.mark.parametrize("width", (1440, 390))
def test_the_measurement_catches_the_old_layout(probe, width):
    """Предохранитель: без обёртки страница ОБЯЗАНА поехать.

    Иначе замер зелен на любом коде и говорит не о вёрстке, а о том, что
    календарь не нарисовался.
    """
    broken = probe[width]["broken"]
    assert broken["page"] > broken["screen"] + 100, (
        "прежняя вёрстка страницу не двигает — значит меряем не то: "
        f"{broken['page']} при экране {broken['screen']}")


def test_the_paper_unwraps_what_the_screen_scrolls():
    """На бумаге прокрутки нет: `overflow:auto` там обрезает молча."""
    page = core.PAGE
    assert ".gantt-wrap{overflow:auto" in page, "окна прокрутки у календаря нет"
    assert "body.print-report .gantt-wrap{overflow:visible!important}" in page, \
        "в печати обёртка не размыкается — план обрежется по краю листа"


def test_the_legend_wraps_like_its_neighbours():
    """Легенда переносится, как соседние: без переноса она распирает экран."""
    page = core.PAGE
    assert ".legend{display:flex;flex-wrap:wrap" in page, \
        "у .legend нет переноса — на телефоне она уводит страницу вбок"
