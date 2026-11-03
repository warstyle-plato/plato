"""Меню руководства собирается из разделов, а не перечисляется рядом.

«Вставь нормативную базу в руководство — раздел, который мы не пересобрали
кстати увы по новым пунктам меню» (владелец, 07.09.2026). Замерено на живой
странице прода: пунктов меню девять, разделов десять — «Справочник нормативной
базы» существовал и в меню не значился, дойти до него можно было только
прокруткой. Тот же класс, что подвал, собираемый из `PAGE`: следующий раздел
попадает в меню тем, что он ПОЯВИЛСЯ, а не тем, что о нём вспомнили.

Запуск: python3 -m pytest tests/test_the_guide_menu_is_built_from_its_sections.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import guide  # noqa: E402

PAGE = (ROOT / "guide" / "page.html").read_text(encoding="utf-8")


def _section_ids(page: str) -> list[str]:
    return re.findall(r'<section[^>]*\bid="([^"]+)"', page)


def test_every_section_has_a_menu_item() -> None:
    ids = _section_ids(PAGE)
    assert ids, "разделов не найдено"
    menu = [section_id for section_id, _ in guide.nav_items(PAGE)]
    assert menu == ids, f"меню разошлось с разделами: {set(ids) ^ set(menu)}"


def test_the_normative_reference_is_in_the_menu() -> None:
    """Ровно то, чего не хватало: раздел был, пункта не было.

    Раздел ищется по тому, что он НЕСЁТ, а не по своему идентификатору:
    первая версия держала `normative`, сосед назвал его `normatives`, и
    проверка упала на верном поведении, ничего не сказав о меню. Реестр
    подставляется в один-единственный раздел — он и есть контракт.
    """
    holder = re.search(
        r'<section[^>]*\bid="([^"]+)"[^>]*>(?:(?!</section>).)*?'
        r"__GUIDE_NORMATIVE_REGISTRY__", PAGE, re.S)
    assert holder, "раздела с нормативным реестром в руководстве нет"
    menu = dict(guide.nav_items(PAGE))
    assert holder.group(1) in menu, menu
    assert "орматив" in menu[holder.group(1)], menu[holder.group(1)]


def test_a_section_added_later_appears_by_itself() -> None:
    """Подделка: новый раздел обязан попасть в меню без правки списка."""
    grown = PAGE.replace(
        '<section id="export"',
        '<section id="brandnew" class="gsection" data-nav="Совсем новый">'
        "<h2>Совсем новый</h2></section>\n      <section id=\"export\"", 1)
    menu = dict(guide.nav_items(grown))
    assert menu.get("brandnew") == "Совсем новый", menu


def test_a_section_without_a_short_label_falls_back_to_its_heading() -> None:
    """Забытая подпись — не повод пропасть из меню: берётся заголовок."""
    bare = PAGE.replace('<section id="areas" class="gsection" data-nav="Площади: чей термин">',
                        '<section id="areas" class="gsection">', 1)
    menu = dict(guide.nav_items(bare))
    assert menu.get("areas"), menu
    assert "Площади" in menu["areas"], menu["areas"]


def test_the_menu_is_not_a_hand_written_list_any_more() -> None:
    """Утверждение: в шаблоне нет второго списка ссылок на разделы.

    Запрещено МЕСТО — рукописный перечень внутри самого меню, — а не слово:
    ссылки на разделы законны в тексте руководства и в кнопках.
    """
    nav = re.search(r'<nav id="gnavList"[^>]*>(.*?)</nav>', PAGE, re.S)
    assert nav, "меню не найдено"
    assert "__GUIDE_NAV__" in nav.group(1), nav.group(1)[:200]
    assert 'href="#' not in nav.group(1), nav.group(1)[:200]
