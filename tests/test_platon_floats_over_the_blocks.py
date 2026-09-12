"""Кнопка Платона висит над экраном и называет блок, о котором спросит.

Владелец 06.09.2026: «надо во всех блоках кабинета чтобы Платон был не внизу а
всплывал видимо как на основном расчете модели». Ящик справа сделан ещё
04.09.2026 — а звала его карточка «Спросить Платона Сергеевича», стоявшая ПОД
блоком: под сводом продаж это десять экранов таблиц, под отчётом о рынке —
восемь карточек. Находил её только тот, кто дочитал до низа; на расчёте кнопка
стоит в шапке и видна всегда.

Шапка кабинета одна, а блоков несколько, поэтому кнопка не в шапке, а над
экраном — и о каком блоке спросит, написано на ней самой: молча сменившийся
груз читается как ответ не о том. Кнопка ОДНА: вторая рядом означала бы двух
разных Платонов на одном экране, ровно как два ящика.

Проверяется браузером, а не строкой в исходнике: какой блок перед глазами —
это геометрия, и `getBoundingClientRect` в тексте файла не измерить. Строкой
проверяется другое — что карточки внизу больше нет ни на одной поверхности и
что объявленный блок на своей странице существует: селектор с опечаткой
молча не найдёт ничего, и кнопка просто не покажется.

Запуск: python3 -m pytest tests/test_platon_floats_over_the_blocks.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from browser import chromium_or_skip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402


def _pages() -> dict[str, str]:
    import auction_search.ui as auction_ui
    import main_legacy
    import market_search.cabinet as cabinet

    return {
        "торги": auction_ui.auctions_page(main_legacy),
        "кабинет рынка": cabinet.cabinet_page("market"),
        "свод продаж": cabinet.cabinet_page("sales"),
    }


def test_no_surface_asks_from_the_bottom_of_the_block() -> None:
    """Карточки внизу нет, всплывающая кнопка — одна на страницу."""
    for name, page in _pages().items():
        assert page.count('id="platoFab"') == 1, (
            f"{name}: кнопок не одна — это два разных Платона на экране")
        assert ".ai-fab{position:fixed" in page, f"{name}: кнопка не всплывает"
        for gone in ('id="askcard"', 'id="askCard"', 'id="bnask"', 'id="salesask"',
                     'id="askbtn"', 'id="bnaskbtn"'):
            assert gone not in page, f"{name}: карточка внизу осталась ({gone})"
        # Заголовок карточки уехал вместе с ней: подпись о том, что Платон
        # видит, живёт в шапке ящика (`surface.hint`), и второй такой на
        # экране не бывает.
        assert "Спросить Платона Сергеевича<" not in page, f"{name}: карточка внизу осталась"


def test_every_declared_block_exists_somewhere() -> None:
    """Блок объявляется селектором, и селектор обязан кого-то находить.

    Скрипт кабинета один на три вида, а разметка режется по видам: объявление
    блока рынка доезжает и до свода продаж, где `#out` не существует вовсе, и
    это не поломка — блок просто не найдётся. Поломка — это селектор, которого
    нет НИГДЕ: опечатка в нём молча не найдёт ничего, и кнопка не покажется.
    """
    pages = _pages()
    everywhere = "\n".join(pages.values())
    seen = set()
    for name, page in pages.items():
        blocks = set(re.findall(r"platoBlock\('#([A-Za-z0-9_-]+)'", page))
        assert blocks, f"{name}: ни один блок себя не объявил — кнопке не о чем говорить"
        assert any(f'id="{block}"' in page for block in blocks), (
            f"{name}: ни один объявленный блок на этом виде не существует")
        seen |= blocks
    for block in sorted(seen):
        assert f'id="{block}"' in everywhere, (
            f"блок #{block} объявлен, но такого узла нет ни на одной поверхности")
    assert len(seen) >= 4, "поверхности растеряли блоки"


def test_the_button_is_not_printed() -> None:
    """Кнопки и поле ввода на бумаге не текст — правило старое, место новое."""
    assert "@media print{.ai-fab{display:none !important}}" in plato_question.LAUNCHER_CSS
    import market_search.cabinet as cabinet

    assert ".ai-fab" in cabinet.cabinet_page("market").split("@media print")[1][:400], (
        "печатный стиль кабинета кнопку не прячет")


HARNESS = """<!doctype html><meta charset="utf-8">
<style>__CSS__ body{margin:0} .tall{height:1400px;border:1px solid #ccc}</style>
<div id="first" class="tall">рынок</div>
<div id="second" class="tall">продажи</div>
<div id="empty"></div>
__FAB__
__DRAWER__
<script>
__PACK__
const first={talk:platoThread(), hint:'о рынке', chips:[], message:q=>'рынок: '+q};
const second={talk:platoThread(), hint:'о продажах', chips:[], message:q=>'продажи: '+q};
const nothing={talk:platoThread(), hint:'пусто', chips:[], message:q=>'пусто'};
platoBlock('#first', first, 'об отчёте о рынке');
platoBlock('#second', second, 'о продажах');
platoBlock('#empty', nothing, 'о пустом');
function fabState(){
  const fab=document.getElementById('platoFab');
  return {hidden: fab.hidden,
          label: document.getElementById('platoFabLabel').textContent,
          hint: document.getElementById('platoHint').textContent,
          open: !!document.querySelector('.ai-drawer.open')};
}
</script>"""


def _harness() -> str:
    import main_legacy

    return (HARNESS
            .replace("__CSS__", plato_question.drawer_css(main_legacy)
                     + "\n" + plato_question.launcher_css())
            .replace("__FAB__", plato_question.floating_launcher())
            .replace("__DRAWER__", plato_question.drawer_markup(plato_question.DRAWER_IDS))
            .replace("__PACK__", plato_question.script()))


@pytest.fixture(scope="module")
def browser_page(tmp_path_factory):
    # Где браузер — один ответ на весь набор (`tests/browser.py`): он ищет, а
    # не помнит номер сборки, и на машине, где браузер ОБЯЗАН быть, его
    # отсутствие красит проверку красным, а не пропускает её молча.
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    page_file = tmp_path_factory.mktemp("fab") / "harness.html"
    page_file.write_text(_harness(), encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(page_file.as_uri())
        yield page, errors
        browser.close()


def test_the_button_names_the_block_in_view(browser_page) -> None:
    """Прокрутили к другому блоку — кнопка говорит уже о нём."""
    page, errors = browser_page
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(120)
    top = page.evaluate("fabState()")
    assert top["hidden"] is False, "кнопки нет там, где есть о чём спросить"
    assert top["label"] == "Спросить Платона об отчёте о рынке", top["label"]

    page.evaluate("window.scrollTo(0, 1600)")
    page.wait_for_timeout(200)
    below = page.evaluate("fabState()")
    assert below["label"] == "Спросить Платона о продажах", below["label"]
    assert not errors, errors


def test_the_button_opens_the_block_it_named(browser_page) -> None:
    """Груз берётся у блока перед глазами, а не у того, кого спрашивали вчера."""
    page, errors = browser_page
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(200)
    page.click("#platoFab")
    page.wait_for_timeout(200)
    opened = page.evaluate("fabState()")
    assert opened["open"] is True, "ящик не открылся"
    assert opened["hint"] == "о рынке", opened["hint"]
    # Под открытым ящиком кнопке делать нечего: висеть поверх завесы — значит
    # предлагать спросить то, о чём уже спрашивают.
    assert opened["hidden"] is True

    page.evaluate("platoDrawer(false)")
    page.evaluate("window.scrollTo(0, 1600)")
    page.wait_for_timeout(200)
    page.click("#platoFab")
    page.wait_for_timeout(200)
    second = page.evaluate("fabState()")
    assert second["hint"] == "о продажах", second["hint"]
    page.evaluate("platoDrawer(false)")
    assert not errors, errors


def test_a_block_that_is_not_built_is_not_offered(browser_page) -> None:
    """Пустой блок — это «нечего показать», а не «спросите о нём».

    Пустой `div` во всю ширину страницы выглядит видимым, если мерить ширину;
    высота у него нулевая, и по ней он честно не находится.
    """
    page, errors = browser_page
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(200)
    at_bottom = page.evaluate("fabState()")
    assert at_bottom["label"] != "Спросить Платона о пустом", (
        "кнопка предлагает спросить о блоке, которого ещё нет")

    # А когда блоков нет вовсе, кнопки нет тоже: предлагать разговор не о чем.
    hidden = page.evaluate("""(() => {
      const nodes=['#first','#second'].map(at=>document.querySelector(at));
      nodes.forEach(node=>node.style.display='none');
      platoFabSync();
      const state=fabState();
      nodes.forEach(node=>node.style.display='');
      platoFabSync();
      return state;
    })()""")
    assert hidden["hidden"] is True, "кнопка осталась там, где спрашивать не о чем"
    assert not errors, errors
